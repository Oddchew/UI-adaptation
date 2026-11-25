import copy
import unittest

from module_c.model import tutor_model
from module_c.sc_model import ScModelError, ScModelRuntime


class FakeAdapter:
    exclusive_writer = True

    def __init__(self, model):
        self.model = copy.deepcopy(model)
        self.reads = []

    async def read_model(self, interface_id):
        self.reads.append(interface_id)
        result = copy.deepcopy(self.model)
        result["id"] = interface_id
        return result


class FakeRenderer:
    def __init__(self):
        self.pending_calls = []
        self.acks = []
        self.activations = []

    def commands(self, user_id, session_id):
        self.pending_calls.append((user_id, session_id))
        return [{"token": "pending"}]

    def acknowledge(self, token, success):
        self.acks.append((token, success))

    async def activate(self, interface_id, model, *, user_id=None, session_id=None):
        self.activations.append((interface_id, user_id, session_id))


class FakeWriter:
    def current_version(self, *args):
        return 0


class ScModelRuntimeBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_pending_and_ack_are_forwarded_to_renderer(self):
        renderer = FakeRenderer()
        runtime = ScModelRuntime(FakeAdapter(tutor_model()), renderer, writer=FakeWriter())

        commands = runtime.commands("user-1", "session-1")
        runtime.acknowledge("token-1", True)

        self.assertEqual(commands, [{"token": "pending"}])
        self.assertEqual(renderer.pending_calls, [("user-1", "session-1")])
        self.assertEqual(renderer.acks, [("token-1", True)])

    async def test_session_scope_is_rejected_by_default(self):
        adapter = FakeAdapter(tutor_model())
        runtime = ScModelRuntime(adapter, FakeRenderer(), writer=FakeWriter())

        with self.assertRaisesRegex(ScModelError, "session-specific model routing is not configured"):
            await runtime.activate(
                "python_tutor_model", tutor_model(),
                user_id="user-1", session_id="session-1",
            )

        self.assertEqual(adapter.reads, [])

    async def test_explicit_shared_session_demo_uses_common_sc_model(self):
        adapter = FakeAdapter(tutor_model())
        renderer = FakeRenderer()
        runtime = ScModelRuntime(
            adapter, renderer, writer=FakeWriter(),
            allow_shared_session_model=True,
        )

        await runtime.activate(
            "python_tutor_model", tutor_model(),
            user_id="user-1", session_id="session-1",
        )

        self.assertEqual(adapter.reads, ["python_tutor_model"])
        self.assertEqual(
            renderer.activations,
            [("python_tutor_model", "user-1", "session-1")],
        )


if __name__ == "__main__":
    unittest.main()
