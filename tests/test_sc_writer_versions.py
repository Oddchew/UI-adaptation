from __future__ import annotations

import unittest
from types import SimpleNamespace

from module_c.sc_writer import ExclusiveScWriter


class FakeAdapter:
    exclusive_writer = True

    def __init__(self):
        self.value = False
        self.writes = 0

    async def read_property(self, interface_id, component_id, prop):
        return SimpleNamespace(value=self.value)

    async def update_property(self, interface_id, component_id, prop, expected, new_value):
        self.value = new_value
        self.writes += 1


class ExclusiveScWriterVersionTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_stale_expected_version_without_writing(self):
        adapter = FakeAdapter()
        writer = ExclusiveScWriter(adapter)

        first = await writer.apply(
            interface_id="ui", component_id="panel", property="visible",
            expected=False, new_value=True, request_id="r1", expected_version=0,
        )
        stale = await writer.apply(
            interface_id="ui", component_id="panel", property="visible",
            expected=True, new_value=False, request_id="r2", expected_version=0,
        )

        self.assertTrue(first.ok)
        self.assertEqual(first.new_version, 1)
        self.assertFalse(stale.ok)
        self.assertEqual(stale.error, "version_mismatch")
        self.assertEqual(stale.new_version, 1)
        self.assertEqual(adapter.writes, 1)
        self.assertTrue(adapter.value)

    async def test_accepts_current_expected_version_and_increments_it(self):
        adapter = FakeAdapter()
        writer = ExclusiveScWriter(adapter)

        result = await writer.apply(
            interface_id="ui", component_id="panel", property="visible",
            expected=False, new_value=True, request_id="r1", expected_version=0,
        )

        self.assertTrue(result.ok)
        self.assertEqual(writer.current_version("ui", "panel", "visible"), 1)
        self.assertEqual(adapter.writes, 1)


if __name__ == "__main__":
    unittest.main()
