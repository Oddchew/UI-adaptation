import asyncio
import unittest
import tempfile
from datetime import datetime, timezone
from dataclasses import replace

from module_a import ModuleA, ModuleAConfig, InMemoryStorage, InteractionEvent, EventType
from module_b import ModuleB, CommandBtoC
from module_c import ModuleC, MemoryRepository, SQLiteRepository, MemoryRuntime, default_model, component_by_id


def command(**changes):
    base = CommandBtoC('r1', 'ui', 'u', 'v1', 'hints_panel', 'visible', False, True, 'errors', 'R1')
    return replace(base, **changes)


class ModuleCTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.repo = MemoryRepository()
        self.repo.register('ui', default_model('ui'))
        self.runtime = MemoryRuntime()
        self.c = ModuleC(self.repo, self.runtime)
        self.outcomes = []
        self.c.set_application_handler(self.outcomes.append)

    async def test_apply_idempotence_and_conflict(self):
        first = await self.c.apply(command())
        second = await self.c.apply(command())
        self.assertEqual(first.status, 'applied')
        self.assertEqual(first.active_version_after, second.active_version_after)
        self.assertEqual(len(self.repo.journal), 1)
        self.assertEqual(len(self.outcomes), 1)
        self.assertEqual((await self.c.apply(command(new_value=False))).failure_reason, 'request_id_conflict')
        self.assertEqual(component_by_id(self.runtime.states['ui'], 'hints_panel')['props']['visible'], True)

    async def test_rejection_and_restore(self):
        result = await self.c.apply(command(base_version_id='obsolete'))
        self.assertEqual(result.failure_reason, 'stale_base_version')
        applied = await self.c.apply(command(request_id='r2'))
        restored = await self.c.restore('ui', 'v1', 'r3', 'u')
        self.assertEqual(restored.status, 'applied')
        self.assertNotEqual(restored.active_version_after, applied.active_version_after)
        self.assertFalse(component_by_id((await self.repo.current('ui'))[1], 'hints_panel')['props']['visible'])

    async def test_runtime_failure_blocks_when_compensation_fails(self):
        class Broken:
            async def activate(self, interface_id, model):
                raise RuntimeError('unavailable')
        c = ModuleC(self.repo, Broken())
        result = await c.apply(command())
        self.assertEqual(result.status, 'failed')
        self.assertTrue(result.recovery_required)
        self.assertEqual((await c.apply(command(request_id='r2'))).failure_reason, 'recovery_required')
        self.assertEqual((await self.repo.current('ui'))[0], 'v1')

    async def test_sqlite_persists_version_and_idempotence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = directory + '/versions.sqlite3'
            repo = SQLiteRepository(path)
            repo.register('ui', default_model('ui'))
            result = await ModuleC(repo, MemoryRuntime()).apply(command())
            repo.db.close()
            reopened = SQLiteRepository(path)
            self.assertEqual((await reopened.current('ui'))[0], result.active_version_after)
            self.assertEqual((await ModuleC(reopened, MemoryRuntime()).apply(command())).active_version_after, result.active_version_after)
            self.assertEqual(len(reopened.journal), 1)
            reopened.db.close()

    async def test_sessions_have_isolated_models(self):
        version = await self.c.active_version('ui', 'alice', 's1')
        result = await self.c.apply(command(base_version_id=version, user_id='alice', session_id='s1'))
        self.assertEqual(result.status, 'applied')
        self.assertTrue(component_by_id((await self.c.state('ui', 'alice', 's1'))[1], 'hints_panel')['props']['visible'])
        self.assertFalse(component_by_id((await self.c.state('ui', 'bob', 's2'))[1], 'hints_panel')['props']['visible'])
        self.assertFalse(component_by_id((await self.c.state('ui', 'alice', 's3'))[1], 'hints_panel')['props']['visible'])

    async def test_help_collapses_history_and_user_can_reopen(self):
        cfg = ModuleAConfig(COLD_START_THRESHOLD=3, PERIODIC_SNAPSHOT_MS=0)
        a = ModuleA(InMemoryStorage(cfg), cfg)
        b = ModuleB()
        demo_repo = MemoryRepository()
        demo_repo.register('python_tutor_model', default_model())
        demo_c = ModuleC(demo_repo, MemoryRuntime())
        b.set_version_provider(demo_c.active_version)
        b.set_command_handler(demo_c.apply)
        demo_c.set_application_handler(a.handle_application_result)
        a.set_package_handler(b.handle_package)
        def event(id, kind, element):
            return InteractionEvent(id=id, user_id='u', interface_id='python_tutor_model', session_id='s',
                event_type=kind, timestamp=datetime.now(timezone.utc).isoformat(), element_id=element)
        for i in range(3):
            await a.handle_event(event(str(i), EventType.HELP_REQUEST, 'hints_panel'))
        self.assertFalse(component_by_id((await demo_c.state('python_tutor_model', 'u', 's'))[1], 'history_content')['props']['visible'])
        await a.handle_event(event('open', EventType.BLOCK_OPEN, 'history_content'))
        self.assertTrue(component_by_id((await demo_c.state('python_tutor_model', 'u', 's'))[1], 'history_content')['props']['visible'])
        a.dispose()

    async def test_manual_mode_blocks_automatic_adaptation_per_session(self):
        cfg = ModuleAConfig(COLD_START_THRESHOLD=3, PERIODIC_SNAPSHOT_MS=0)
        a = ModuleA(InMemoryStorage(cfg), cfg)
        b = ModuleB()
        b.set_version_provider(self.c.active_version)
        b.set_command_handler(self.c.apply)
        self.c.set_application_handler(a.handle_application_result)
        a.set_package_handler(b.handle_package)
        def event(id, kind, **values):
            return InteractionEvent(id=id, user_id='u', interface_id='ui', session_id='s',
                event_type=kind, timestamp=datetime.now(timezone.utc).isoformat(), **values)
        await a.handle_event(event('manual', EventType.MANUAL_OVERRIDE, property='adaptation_mode', new_value='manual'))
        for i in range(2):
            await a.handle_event(event(str(i), EventType.ERROR, element_id='code_editor', error_code='syntax'))
        self.assertFalse(component_by_id((await self.c.state('ui', 'u', 's'))[1], 'hints_panel')['props']['visible'])
        await a.handle_event(event('auto', EventType.MANUAL_OVERRIDE, property='adaptation_mode', new_value='automatic'))
        await a.handle_event(event('3', EventType.ERROR, element_id='code_editor', error_code='syntax'))
        self.assertTrue(component_by_id((await self.c.state('ui', 'u', 's'))[1], 'hints_panel')['props']['visible'])
        a.dispose()

    async def test_history_content_visibility_preserves_other_components(self):
        cmd = command(target_element_id='history_content', property='visible', old_value=True, new_value=False)
        before = (await self.c.state('ui'))[1]
        self.assertEqual((await self.c.apply(cmd)).status, 'applied')
        after = (await self.c.state('ui'))[1]
        self.assertFalse(component_by_id(after, 'history_content')['props']['visible'])
        self.assertEqual(component_by_id(before, 'code_editor'), component_by_id(after, 'code_editor'))
        self.assertEqual(before['links'], after['links'])

    async def test_outcome_delivery_retries_without_applying_twice(self):
        attempts = []
        async def handler(result):
            attempts.append(result.event_id)
            if len(attempts) == 1:
                raise RuntimeError('temporary failure')
        self.c.set_application_handler(handler)
        result = await self.c.apply(command())
        self.assertEqual(result.status, 'applied')
        await self.c.retry_notifications()
        self.assertEqual(attempts, ['r1', 'r1'])
        self.assertEqual(len(self.repo.journal), 1)
        self.assertTrue((await self.repo.result('r1'))['delivered'])

    async def test_interrupted_operation_blocks_context_until_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            path = directory + '/versions.sqlite3'
            repo = SQLiteRepository(path)
            repo.register('ui', default_model('ui'))
            await repo.prepare('crash', 'ui', {'version_before': 'v1'})
            repo.db.close()
            reopened = SQLiteRepository(path)
            c = ModuleC(reopened, MemoryRuntime())
            self.assertEqual((await c.apply(command())).failure_reason, 'recovery_required')
            self.assertEqual((await c.restore('ui', 'v1', 'restore1', 'u')).status, 'applied')
            reopened.db.close()
            reopened = SQLiteRepository(path)
            self.assertFalse(await reopened.blocked('ui'))
            reopened.db.close()

    async def test_two_errors_show_then_hide_until_session_ends(self):
        cfg = ModuleAConfig(COLD_START_THRESHOLD=3, PERIODIC_SNAPSHOT_MS=0)
        a = ModuleA(InMemoryStorage(cfg), cfg)
        b = ModuleB()
        demo_repo = MemoryRepository()
        demo_repo.register('python_tutor_model', default_model())
        demo_c = ModuleC(demo_repo, MemoryRuntime())
        b.set_version_provider(demo_c.active_version)
        b.set_command_handler(demo_c.apply)
        demo_c.set_application_handler(a.handle_application_result)
        a.set_package_handler(b.handle_package)
        def event(id, kind, session='s'):
            return InteractionEvent(id=id, user_id='u', interface_id='python_tutor_model', session_id=session,
                event_type=kind, timestamp=datetime.now(timezone.utc).isoformat(),
                element_id='code_editor' if kind == EventType.ERROR else 'hints_panel',
                error_code='syntax' if kind == EventType.ERROR else None)
        await a.handle_event(event('1', EventType.ERROR))
        await a.handle_event(event('2', EventType.ERROR))
        await a.handle_event(event('2b', EventType.FOCUS))
        self.assertTrue(component_by_id((await demo_c.state('python_tutor_model', 'u', 's'))[1], 'hints_panel')['props']['visible'])
        await a.handle_event(event('3', EventType.HINT_HIDE))
        self.assertFalse(component_by_id((await demo_c.state('python_tutor_model', 'u', 's'))[1], 'hints_panel')['props']['visible'])
        await a.handle_event(event('4', EventType.ERROR))
        self.assertFalse(component_by_id((await demo_c.state('python_tutor_model', 'u', 's'))[1], 'hints_panel')['props']['visible'])
        self.assertEqual(len((await a.get_user_model('u')).adaptation_history), 2)
        await a.handle_event(event('5', EventType.ERROR, 'next'))
        await a.handle_event(event('6', EventType.ERROR, 'next'))
        self.assertTrue(component_by_id((await demo_c.state('python_tutor_model', 'u', 'next'))[1], 'hints_panel')['props']['visible'])
        a.dispose()


if __name__ == '__main__':
    unittest.main()
