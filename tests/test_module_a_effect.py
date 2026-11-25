"""Regression tests for Module A adaptation effect registration."""

from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timezone

from module_a import AdaptationResult, InMemoryStorage, ModuleA, ModuleAConfig, UserModel
from module_a.effect_tracker import EffectTracker


class ModuleAEffectRegistrationTest(unittest.TestCase):
    def test_invalid_observation_window_does_not_register_effect_sample(self):
        async def run():
            storage = InMemoryStorage(ModuleAConfig())
            tracker = EffectTracker()
            module = ModuleA(storage=storage, effect_tracker=tracker)
            model = UserModel(user_id="u1")
            model.observation.window_start = "not-a-timestamp"
            await storage.save_user_model(model)

            result = AdaptationResult(
                request_id="req-invalid-window",
                interface_id="ui",
                user_id="u1",
                success=True,
                applied_at=datetime.now(timezone.utc).isoformat(),
                reason="R_test",
            )
            await module.handle_application_result(result)

            self.assertEqual(tracker.pending_count(), 0)
            saved = await module.get_user_model("u1")
            self.assertEqual(len(saved.adaptation_history), 1)
            module.dispose()

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
