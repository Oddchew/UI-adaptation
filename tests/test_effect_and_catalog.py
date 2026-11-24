"""Tests for effect evaluation and design-time catalog alignment."""
from __future__ import annotations

import unittest
from datetime import datetime, timezone, timedelta

from module_a.effect_tracker import EffectTracker, EffectTrackerConfig
from module_a.types import AdaptationResult, EventType, InteractionEvent
from module_c.catalog import (
    ADAPTABLE_PROPERTIES,
    COMPONENT_TYPES,
    FORBIDDEN_ADAPTATION_PROPERTIES,
    PROPERTY_TYPES,
    is_adaptable_property,
)
from module_c.model import AdaptationPolicy, COMPONENT_TYPES as MODEL_CT, PROPERTY_TYPES as MODEL_PT


class CatalogAlignmentTest(unittest.TestCase):
    def test_model_reexports_catalog(self):
        self.assertEqual(COMPONENT_TYPES, MODEL_CT)
        self.assertEqual(set(PROPERTY_TYPES), set(MODEL_PT))

    def test_adaptable_vs_forbidden(self):
        self.assertTrue(is_adaptable_property("visible"))
        self.assertTrue(is_adaptable_property("font_size"))
        self.assertFalse(is_adaptable_property("text_value"))
        self.assertFalse(is_adaptable_property("action_id"))
        self.assertTrue(FORBIDDEN_ADAPTATION_PROPERTIES.isdisjoint(ADAPTABLE_PROPERTIES))

    def test_policy_from_catalog(self):
        policy = AdaptationPolicy.from_catalog(["hints_panel", "code_editor"])
        self.assertIn("visible", policy.allowed["hints_panel"])
        self.assertNotIn("text_value", policy.allowed["code_editor"])


class EffectTrackerTest(unittest.TestCase):
    def test_score_after_followup(self):
        cfg = EffectTrackerConfig(
            followup_window_ms=1000,
            min_events_for_score=2,
            expire_after_ms=60_000,
        )
        tracker = EffectTracker(cfg)
        applied_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        result = AdaptationResult(
            request_id="req1",
            interface_id="ui",
            user_id="u1",
            success=True,
            applied_at=applied_at.isoformat().replace("+00:00", "Z"),
            reason="R_hint_after_2_errors",
        )
        tracker.on_applied(
            result,
            rule_id="R_hint_after_2_errors",
            baseline_error_rate=0.5,
            baseline_help_rate=0.2,
            baseline_success_count=0,
        )
        # events inside follow-up window [applied, applied+1000ms]
        t1 = applied_at + timedelta(milliseconds=200)
        t2 = applied_at + timedelta(milliseconds=400)
        events = [
            InteractionEvent(
                id="e1",
                user_id="u1",
                interface_id="ui",
                event_type=EventType.SUCCESSFUL_ACTION,
                timestamp=t1.isoformat().replace("+00:00", "Z"),
            ),
            InteractionEvent(
                id="e2",
                user_id="u1",
                interface_id="ui",
                event_type=EventType.SUCCESSFUL_ACTION,
                timestamp=t2.isoformat().replace("+00:00", "Z"),
            ),
        ]
        # score only after the follow-up window has elapsed
        now = applied_at + timedelta(milliseconds=1500)
        scored = tracker.on_events("u1", events, now=now)
        self.assertEqual(len(scored), 1)
        self.assertEqual(scored[0].status, "scored")
        self.assertIsNotNone(scored[0].score)
        # error rate dropped 0.5 -> 0, help 0.2 -> 0 => positive score
        self.assertGreater(scored[0].score, 0)
        scores = tracker.all_rule_scores()
        self.assertIn("R_hint_after_2_errors", scores)


class LinkCatalogTest(unittest.TestCase):
    def test_link_kinds(self):
        from module_c.catalog import LINK_KINDS, validate_link, ACTION_COMPONENT_TYPES
        self.assertIn("input_target", LINK_KINDS)
        self.assertIn("output_target", LINK_KINDS)
        self.assertIsNone(validate_link("input_target", "button", "text_field"))
        self.assertEqual(validate_link("input_target", "window", "text_field"), "invalid_link_source_type")
        self.assertEqual(validate_link("output_target", "button", "divider"), "invalid_link_target_type")
        self.assertEqual(ACTION_COMPONENT_TYPES, frozenset({"button", "select", "menu_item"}))

    def test_action_id_only_on_triggers(self):
        from module_c.catalog import component_allows_action_id
        self.assertTrue(component_allows_action_id("button"))
        self.assertFalse(component_allows_action_id("text_field"))

    def test_normalize_rejects_action_id_on_text(self):
        from module_c.model import normalize_model
        model = {
            "id": "ui",
            "title": "t",
            "components": [
                {"id": "t1", "typeId": "text", "props": {"visible": True, "action_id": "x"}},
            ],
            "links": [],
        }
        with self.assertRaises(ValueError) as ctx:
            normalize_model(model, "ui")
        self.assertEqual(str(ctx.exception), "action_id_not_allowed")

    def test_normalize_accepts_input_target(self):
        from module_c.model import normalize_model
        model = {
            "id": "ui",
            "title": "t",
            "components": [
                {"id": "b1", "typeId": "button", "props": {"visible": True, "action_id": "run"}},
                {"id": "f1", "typeId": "text_field", "props": {"visible": True}},
            ],
            "links": [{"id": "l1", "kind": "input_target", "sourceId": "b1", "targetId": "f1"}],
        }
        out = normalize_model(model, "ui")
        self.assertEqual(out["links"][0]["kind"], "input_target")


if __name__ == "__main__":
    unittest.main()
