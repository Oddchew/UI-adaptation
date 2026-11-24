"""SC writer dual-write path in ModuleC (no real sc-server)."""
from __future__ import annotations

import asyncio
import unittest
from dataclasses import dataclass

from module_b.models import CommandBtoC
from module_c.core import ModuleC, MemoryRepository, MemoryRuntime
from module_c.model import tutor_model
from module_c.sc_writer import WriteResult


class RecordingWriter:
    def __init__(self) -> None:
        self.calls = []
        self.fail = False

    async def apply(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            return WriteResult(False, 0, "old_value_mismatch", 1)
        return WriteResult(True, 1, None, 1)


class ScWriterIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_successful_dual_write(self):
        repo = MemoryRepository()
        repo.register("python_tutor_model", tutor_model())
        writer = RecordingWriter()
        c = ModuleC(repo, MemoryRuntime(), sc_writer=writer)
        current = await c.state("python_tutor_model")
        assert current is not None
        version, model = current
        cmd = CommandBtoC(
            request_id="r-sc-1",
            interface_id="python_tutor_model",
            user_id="u1",
            base_version_id=version,
            target_element_id="hints_panel",
            property="visible",
            old_value=False,
            new_value=True,
            rule_id="R_hint_after_2_errors",
            reason="test",
            constraints=["не изменять code_editor.content", "не изменять этап задания", "не изменять критерии проверки"],
        )
        resp = await c.apply(cmd)
        self.assertEqual(resp.status, "applied")
        self.assertEqual(len(writer.calls), 1)
        self.assertEqual(writer.calls[0]["component_id"], "hints_panel")
        self.assertEqual(writer.calls[0]["new_value"], True)

    async def test_sc_write_failure_rejects(self):
        repo = MemoryRepository()
        repo.register("python_tutor_model", tutor_model())
        writer = RecordingWriter()
        writer.fail = True
        c = ModuleC(repo, MemoryRuntime(), sc_writer=writer)
        current = await c.state("python_tutor_model")
        version, _ = current
        cmd = CommandBtoC(
            request_id="r-sc-2",
            interface_id="python_tutor_model",
            user_id="u1",
            base_version_id=version,
            target_element_id="hints_panel",
            property="visible",
            old_value=False,
            new_value=True,
            rule_id="R_hint_after_2_errors",
            reason="test",
            constraints=["не изменять code_editor.content", "не изменять этап задания", "не изменять критерии проверки"],
        )
        resp = await c.apply(cmd)
        self.assertEqual(resp.status, "failed")
        self.assertTrue(resp.failure_reason and resp.failure_reason.startswith("sc_write:"))


if __name__ == "__main__":
    unittest.main()
