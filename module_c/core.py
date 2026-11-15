"""Применение команд к версии модели интерфейса."""
from __future__ import annotations

import asyncio
import copy
import inspect
import json
import logging
import sqlite3
import time
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Protocol

from module_a.types import AdaptationResult
from module_b.models import CommandBtoC
from .model import AdaptationPolicy, component_by_id, normalize_model, tutor_model

logger = logging.getLogger(__name__)


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def default_model(interface_id: str = 'python_tutor_model') -> dict[str, Any]:
    return tutor_model(interface_id)


@dataclass
class UIResponse:
    request_id: str
    status: str
    active_version_after: str | None
    duration_ms: int
    failure_reason: str | None = None
    recovery_required: bool = False

    @property
    def success(self) -> bool:
        return self.status == 'applied'


class Repository(Protocol):
    async def current(self, interface_id: str) -> tuple[str, dict] | None: ...
    async def version(self, interface_id: str, version_id: str) -> dict | None: ...
    async def commit(self, interface_id: str, expected: str, model: dict, entry: dict) -> str: ...
    async def record(self, request_id: str, entry: dict) -> None: ...
    async def result(self, request_id: str) -> dict | None: ...
    async def set_blocked(self, interface_id: str, blocked: bool) -> None: ...
    async def blocked(self, interface_id: str) -> bool: ...
    async def prepare(self, request_id: str, interface_id: str, entry: dict) -> None: ...
    async def mark_delivered(self, request_id: str) -> None: ...


class Runtime(Protocol):
    async def activate(self, interface_id: str, model: dict) -> None: ...


class MemoryRepository:
    def __init__(self) -> None:
        self.interfaces: dict[str, dict] = {}
        self.results: dict[str, dict] = {}
        self.journal: list[dict] = []
        self.pending: dict[str, dict] = {}

    def register(self, interface_id: str, model: dict, version_id: str = 'v1') -> None:
        if interface_id in self.interfaces:
            raise ValueError('interface already registered')
        self.interfaces[interface_id] = {'interface_id': interface_id, 'active': version_id, 'versions': {version_id: normalize_model(model, interface_id)},
                                         'blocked': False}

    async def ensure_context(self, interface_id: str, user_id: str | None, session_id: str | None) -> str:
        if not user_id or not session_id:
            return interface_id
        key = 'context:' + json.dumps([interface_id, user_id, session_id], ensure_ascii=False, separators=(',', ':'))
        if key not in self.interfaces:
            template = self.interfaces.get(interface_id)
            if not template:
                return key
            self.interfaces[key] = copy.deepcopy(template)
            self.interfaces[key]['interface_id'] = interface_id
        return key

    async def current(self, interface_id: str):
        obj = self.interfaces.get(interface_id)
        return (obj['active'], normalize_model(obj['versions'][obj['active']], obj.get('interface_id', interface_id))) if obj else None

    async def version(self, interface_id: str, version_id: str):
        obj = self.interfaces.get(interface_id)
        model = obj['versions'].get(version_id) if obj else None
        return normalize_model(model, obj.get('interface_id', interface_id)) if model else None

    async def commit(self, interface_id: str, expected: str, model: dict, entry: dict) -> str:
        obj = self.interfaces[interface_id]
        if obj['active'] != expected:
            raise RuntimeError('stale_base_version')
        version = 'v_' + uuid.uuid4().hex
        obj['versions'][version] = copy.deepcopy(model)
        obj['active'] = version
        entry = copy.deepcopy(entry)
        entry['response']['active_version_after'] = version
        self.results[entry['response']['request_id']] = entry
        self.journal.append(copy.deepcopy(entry))
        self.pending.pop(entry['response']['request_id'], None)
        if entry['command'].get('operation') == 'restore':
            obj['blocked'] = False
            self.pending = {request_id: item for request_id, item in self.pending.items() if item['interface_key'] != interface_id}
        return version

    async def record(self, request_id: str, entry: dict) -> None:
        self.results[request_id] = copy.deepcopy(entry)
        self.journal.append(copy.deepcopy(entry))
        self.pending.pop(request_id, None)

    async def prepare(self, request_id: str, interface_id: str, entry: dict) -> None:
        self.pending[request_id] = {'interface_key': interface_id, **copy.deepcopy(entry)}

    async def mark_delivered(self, request_id: str) -> None:
        if request_id in self.results:
            self.results[request_id]['delivered'] = True
        for entry in self.journal:
            if entry['response']['request_id'] == request_id:
                entry['delivered'] = True

    async def result(self, request_id: str):
        return copy.deepcopy(self.results.get(request_id))

    async def blocked(self, interface_id: str) -> bool:
        return bool(self.interfaces.get(interface_id, {}).get('blocked'))

    async def set_blocked(self, interface_id: str, blocked: bool) -> None:
        self.interfaces[interface_id]['blocked'] = blocked


class MemoryRuntime:
    def __init__(self) -> None:
        self.states: dict[str, dict] = {}

    async def activate(self, interface_id: str, model: dict) -> None:
        self.states[interface_id] = copy.deepcopy(model)


class SQLiteRepository(MemoryRepository):
    """Локальное хранение версий, журнала и обработанных запросов."""
    def __init__(self, path: str) -> None:
        super().__init__()
        self.db = sqlite3.connect(path)
        self.db.execute('CREATE TABLE IF NOT EXISTS module_c_state (id INTEGER PRIMARY KEY CHECK (id = 1), data TEXT NOT NULL)')
        row = self.db.execute('SELECT data FROM module_c_state WHERE id = 1').fetchone()
        if row:
            state = json.loads(row[0])
            self.interfaces, self.results, self.journal = state['interfaces'], state['results'], state['journal']
            self.pending = state.get('pending', {})
            for entry in self.pending.values():
                obj = self.interfaces.get(entry['interface_key'])
                if obj is not None:
                    obj['blocked'] = True
            if self.pending:
                self._persist()

    def _persist(self):
        data = json.dumps({'interfaces': self.interfaces, 'results': self.results, 'journal': self.journal, 'pending': self.pending}, ensure_ascii=False)
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO module_c_state VALUES (1, ?)', (data,))

    def register(self, interface_id: str, model: dict, version_id: str = 'v1') -> None:
        super().register(interface_id, model, version_id)
        self._persist()

    async def ensure_context(self, interface_id: str, user_id: str | None, session_id: str | None) -> str:
        before = set(self.interfaces)
        key = await super().ensure_context(interface_id, user_id, session_id)
        if key not in before and key in self.interfaces:
            try:
                self._persist()
            except Exception:
                del self.interfaces[key]
                raise
        return key

    async def commit(self, interface_id: str, expected: str, model: dict, entry: dict) -> str:
        old = copy.deepcopy((self.interfaces, self.results, self.journal, self.pending))
        try:
            result = await super().commit(interface_id, expected, model, entry)
            self._persist()
            return result
        except Exception:
            self.interfaces, self.results, self.journal, self.pending = old
            raise

    async def record(self, request_id: str, entry: dict) -> None:
        old = copy.deepcopy((self.results, self.journal, self.pending))
        try:
            await super().record(request_id, entry)
            self._persist()
        except Exception:
            self.results, self.journal, self.pending = old
            raise

    async def prepare(self, request_id: str, interface_id: str, entry: dict) -> None:
        await super().prepare(request_id, interface_id, entry)
        try:
            self._persist()
        except Exception:
            self.pending.pop(request_id, None)
            raise

    async def mark_delivered(self, request_id: str) -> None:
        old = copy.deepcopy((self.results, self.journal))
        try:
            await super().mark_delivered(request_id)
            self._persist()
        except Exception:
            self.results, self.journal = old
            raise

    async def set_blocked(self, interface_id: str, blocked: bool) -> None:
        old = self.interfaces[interface_id]['blocked']
        try:
            await super().set_blocked(interface_id, blocked)
            self._persist()
        except Exception:
            self.interfaces[interface_id]['blocked'] = old
            raise


class ModuleC:
    def __init__(self, repository: Repository, runtime: Runtime, timeout: float = 2.0, policy: AdaptationPolicy | None = None) -> None:
        self.repository, self.runtime, self.timeout = repository, runtime, timeout
        self.policy = policy or AdaptationPolicy()
        self._locks: dict[str, asyncio.Lock] = {}
        self._requests_lock = asyncio.Lock()
        self._on_application = None

    def set_application_handler(self, handler) -> None:
        self._on_application = handler

    async def _context_key(self, interface_id: str, user_id: str | None, session_id: str | None) -> str:
        ensure = getattr(self.repository, 'ensure_context', None)
        if ensure:
            return await ensure(interface_id, user_id, session_id)
        if user_id and session_id:
            raise RuntimeError('repository does not support session isolation')
        return interface_id

    async def state(self, interface_id: str, user_id: str | None = None, session_id: str | None = None):
        key = await self._context_key(interface_id, user_id, session_id)
        return await self.repository.current(key)

    async def active_version(self, interface_id: str, user_id: str | None = None, session_id: str | None = None) -> str | None:
        current = await self.state(interface_id, user_id, session_id)
        return current[0] if current else None

    async def retry_notifications(self) -> None:
        """Redeliver stored outcomes with their original event IDs."""
        async with self._requests_lock:
            for entry in list(getattr(self.repository, 'journal', [])):
                if entry.get('delivered'):
                    continue
                data = entry['command']
                if data.get('operation') == 'restore':
                    command = CommandBtoC(entry['response']['request_id'], data['interface_id'], data['user_id'],
                        entry.get('version_before') or '', '', '', None, None, 'restore', 'restore', session_id=data.get('session_id'))
                else:
                    command = CommandBtoC(**data)
                await self._notify(command, UIResponse(**entry['response']), entry.get('version_before'))

    async def restore(self, interface_id: str, version_id: str, request_id: str, user_id: str, session_id: str | None = None) -> UIResponse:
        started = time.monotonic()
        async with self._requests_lock:
            key = await self._context_key(interface_id, user_id, session_id)
            async with self._locks.setdefault(key, asyncio.Lock()):
                previous = await self.repository.result(request_id)
                signature = {'operation': 'restore', 'interface_id': interface_id, 'version_id': version_id, 'user_id': user_id, 'session_id': session_id}
                if previous:
                    if previous['command'] != signature:
                        return UIResponse(request_id, 'rejected', await self.active_version(interface_id), 0, 'request_id_conflict')
                    if not previous.get('delivered'):
                        cmd = CommandBtoC(request_id, interface_id, user_id, previous.get('version_before') or '', '', '', None, None, 'restore', 'restore', session_id=session_id)
                        await self._notify(cmd, UIResponse(**previous['response']), previous.get('version_before'))
                    return UIResponse(**previous['response'])
                current = await self.repository.current(key)
                target = await self.repository.version(key, version_id)
                before = current[0] if current else None
                response = UIResponse(request_id, 'rejected', before, 0)
                if not current or target is None:
                    response.failure_reason = 'unknown_version'
                else:
                    try:
                        restore_command = CommandBtoC(request_id, interface_id, user_id, before or '', '', '', None, None, 'restore', 'restore', session_id=session_id)
                        await self.repository.prepare(request_id, key, {'command': signature, 'version_before': before})
                        await asyncio.wait_for(self._activate(restore_command, target), self.timeout)
                        response.status = 'applied'
                        entry = {'command': signature, 'version_before': before, 'response': asdict(response), 'time': now()}
                        response.active_version_after = await self.repository.commit(key, before, target, entry)
                    except Exception as exc:
                        response.status = 'failed'
                        response.failure_reason = 'runtime_timeout' if isinstance(exc, asyncio.TimeoutError) else 'application_failed'
                        try:
                            await asyncio.wait_for(self._activate(restore_command, current[1]), self.timeout)
                        except Exception:
                            response.recovery_required = True
                            await self.repository.set_blocked(key, True)
                response.duration_ms = int((time.monotonic() - started) * 1000)
                if response.status != 'applied':
                    await self.repository.record(request_id, {'command': signature, 'version_before': before, 'response': asdict(response), 'time': now()})
                command = CommandBtoC(request_id, interface_id, user_id, before or '', '', '', None, None, 'restore', 'restore', session_id=session_id)
                await self._notify(command, response, before)
                return response

    async def _notify(self, command: CommandBtoC, response: UIResponse, before: str | None) -> None:
        if not self._on_application:
            return
        result = AdaptationResult(request_id=command.request_id, interface_id=command.interface_id,
            user_id=command.user_id, success=response.success, applied_at=now(),
            target_element_id=command.target_element_id, property=command.property,
            old_value=command.old_value, new_value=command.new_value if response.success else None,
            reason=command.reason, error_message=response.failure_reason, status=response.status,
            event_id=command.request_id, source_event_ids=list(command.source_event_ids),
            version_before=before, version_after=response.active_version_after,
            duration_ms=response.duration_ms, recovery_required=response.recovery_required,
            outcome_type='restore' if command.rule_id == 'restore' else 'adaptation', session_id=command.session_id)
        try:
            value = self._on_application(result)
            if inspect.isawaitable(value):
                await value
            await self.repository.mark_delivered(command.request_id)
        except Exception:
            logger.exception('Could not deliver adaptation outcome %s', command.request_id)

    async def apply(self, command: CommandBtoC) -> UIResponse:
        started = time.monotonic()
        # Serialising request IDs also prevents duplicate execution across interfaces.
        async with self._requests_lock:
            key = await self._context_key(command.interface_id, command.user_id, command.session_id)
            async with self._locks.setdefault(key, asyncio.Lock()):
                previous = await self.repository.result(command.request_id)
                if previous:
                    if previous['command'] != asdict(command):
                        return UIResponse(command.request_id, 'rejected', await self.active_version(command.interface_id), 0, 'request_id_conflict')
                    if not previous.get('delivered'):
                        await self._notify(command, UIResponse(**previous['response']), previous.get('version_before'))
                    return UIResponse(**previous['response'])
                current = await self.repository.current(key)
                before = current[0] if current else None
                response = UIResponse(command.request_id, 'rejected', before, 0)
                failure = None
                required = (command.request_id, command.interface_id, command.user_id, command.base_version_id,
                            command.target_element_id, command.property, command.rule_id, command.reason)
                if any(not isinstance(v, str) or not v.strip() for v in required): failure = 'missing_required_field'
                elif not current: failure = 'unknown_interface'
                elif await self.repository.blocked(key): failure = 'recovery_required'
                elif before != command.base_version_id: failure = 'stale_base_version'
                elif any(c not in {'не изменять code_editor.content', 'не изменять этап задания', 'не изменять критерии проверки'} for c in command.constraints): failure = 'unsupported_constraint'
                else:
                    model = current[1]
                    component = component_by_id(model, command.target_element_id)
                    if component is None: failure = 'unknown_target'
                    else:
                        failure = self.policy.validate(component, command.property, command.new_value)
                        if not failure and component['props'][command.property] == command.new_value: failure = 'no_change_required'
                        elif not failure and (type(command.old_value) is not type(command.new_value) or component['props'][command.property] != command.old_value): failure = 'old_value_mismatch'
                if failure:
                    response.failure_reason = failure
                    response.recovery_required = failure == 'recovery_required'
                else:
                    candidate = copy.deepcopy(current[1])
                    component_by_id(candidate, command.target_element_id)['props'][command.property] = command.new_value
                    try:
                        await self.repository.prepare(command.request_id, key, {'command': asdict(command), 'version_before': before})
                        await asyncio.wait_for(self._activate(command, candidate), self.timeout)
                        response.status = 'applied'
                        response.duration_ms = int((time.monotonic() - started) * 1000)
                        entry = {'command': asdict(command), 'version_before': before, 'response': asdict(response), 'time': now()}
                        response.active_version_after = await asyncio.wait_for(self.repository.commit(key, before, candidate, entry), max(0.001, self.timeout - (time.monotonic() - started)))
                    except Exception as exc:
                        response.status = 'failed'
                        response.failure_reason = 'runtime_timeout' if isinstance(exc, asyncio.TimeoutError) else 'application_failed'
                        try:
                            await asyncio.wait_for(self._activate(command, current[1]), self.timeout)
                        except Exception:
                            response.recovery_required = True
                            await self.repository.set_blocked(key, True)
                response.duration_ms = int((time.monotonic() - started) * 1000)
                if response.status != 'applied':
                    await self.repository.record(command.request_id, {'command': asdict(command), 'version_before': before, 'response': asdict(response), 'time': now()})
                await self._notify(command, response, before)
                return response

    async def _activate(self, command: CommandBtoC, model: dict) -> None:
        if 'session_id' in inspect.signature(self.runtime.activate).parameters:
            await self.runtime.activate(command.interface_id, model, user_id=command.user_id, session_id=command.session_id)
        else:
            await self.runtime.activate(command.interface_id, model)
