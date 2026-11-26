"""Coursework alignment regression tests for Module B."""

from __future__ import annotations

import time
import unittest
import uuid

from module_a.types import (
    EventType,
    InteractionEvent,
    PackageAtoB,
    PackageTrigger,
    UserModel,
    session_key,
)
from module_b import ModuleB, DecisionStatus, RejectReason
from module_b.rule_schema import AdaptationRule, RuleAction, RuleTrigger, TriggerKind


def make_package(events, *, interface_id="custom_ui", manual=False, hidden=False):
    snapshot = UserModel(
        user_id="student-1",
        model_version=4,
        is_cold_start=False,
        hint_hidden_sessions=[session_key(interface_id, "session-1")] if hidden else [],
    )
    return PackageAtoB(
        user_id="student-1",
        interface_id=interface_id,
        model_version=4,
        model_snapshot=snapshot,
        observation_window={"event_count": len(events)},
        interaction_events=events,
        manual_override=manual,
        trigger=PackageTrigger.MANUAL_OVERRIDE if manual else PackageTrigger.THRESHOLD,
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )


def event(event_type, *, interface_id="custom_ui", element_id=None, error_code=None, action_id=None):
    return InteractionEvent(
        id=f"evt-{uuid.uuid4().hex[:8]}",
        user_id="student-1",
        interface_id=interface_id,
        event_type=event_type,
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        session_id="session-1",
        element_id=element_id,
        error_code=error_code,
        action_id=action_id,
    )


class ModuleBCourseworkAlignmentTests(unittest.IsolatedAsyncioTestCase):
    def make_b(self, rules=None):
        module = ModuleB(rules=rules)
        module.set_version_provider(lambda *_: "ui-v1")
        return module

    async def test_requires_three_events_even_for_explicit_success_action(self):
        pkg = make_package([event(EventType.SUCCESSFUL_ACTION, action_id="check_run")])
        result = await self.make_b().decide(pkg)
        self.assertEqual(result.status, DecisionStatus.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.INSUFFICIENT_DATA)

    async def test_two_error_rule_can_fire_before_generic_three_event_window(self):
        pkg = make_package([
            event(EventType.ERROR, element_id="hints_panel", error_code="syntax"),
            event(EventType.ERROR, element_id="hints_panel", error_code="runtime"),
        ])
        result = await self.make_b().decide(pkg)
        self.assertEqual(result.status, DecisionStatus.COMMAND)
        self.assertEqual(result.command.rule_id, "R_hint_after_2_errors")

    async def test_counts_errors_with_different_error_codes(self):
        pkg = make_package([
            event(EventType.ERROR, element_id="hints_panel", error_code="syntax"),
            event(EventType.ERROR, element_id="hints_panel", error_code="runtime"),
            event(EventType.FOCUS),
        ])
        result = await self.make_b().decide(pkg)
        self.assertEqual(result.status, DecisionStatus.COMMAND)
        self.assertEqual(result.command.rule_id, "R_hint_after_2_errors")
        self.assertEqual(len(result.command.source_event_ids), 2)

    async def test_forbidden_targets_are_rejected_for_every_interface(self):
        rule = AdaptationRule(
            id="R_forbidden",
            trigger=RuleTrigger(kind=TriggerKind.ALWAYS),
            action=RuleAction(
                target_element_id="code_editor.content",
                property="content",
                old_value="",
                new_value="changed",
            ),
        )
        pkg = make_package([event(EventType.FOCUS) for _ in range(3)])
        result = await self.make_b([rule]).decide(pkg)
        self.assertEqual(result.status, DecisionStatus.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.CONSTRAINT_VIOLATION)

    async def test_hidden_hints_are_respected_for_every_interface(self):
        rule = AdaptationRule(
            id="R_custom_hint",
            respect_hint_hidden=True,
            trigger=RuleTrigger(kind=TriggerKind.ALWAYS),
            action=RuleAction(
                target_element_id="hints_panel",
                property="visible",
                old_value=False,
                new_value=True,
            ),
        )
        pkg = make_package([event(EventType.FOCUS) for _ in range(3)], hidden=True)
        result = await self.make_b([rule]).decide(pkg)
        self.assertEqual(result.status, DecisionStatus.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.NO_RULE_MATCHED)

    async def test_explicit_hint_hide_control_is_not_blocked_by_automatic_threshold(self):
        pkg = make_package(
            [event(EventType.HINT_HIDE, interface_id="python_tutor_model")],
            interface_id="python_tutor_model",
        )
        result = await self.make_b().decide(pkg)
        self.assertEqual(result.status, DecisionStatus.COMMAND)
        self.assertEqual(result.command.rule_id, "user_hide_hint")

    async def test_manual_override_vetoes_legacy_user_action_path(self):
        pkg = make_package(
            [event(EventType.HINT_HIDE, interface_id="python_tutor_model")],
            interface_id="python_tutor_model",
            manual=True,
        )
        result = await self.make_b().decide(pkg)
        self.assertEqual(result.status, DecisionStatus.REJECTED)
        self.assertEqual(result.reject_reason, RejectReason.MANUAL_OVERRIDE)


if __name__ == "__main__":
    unittest.main()
