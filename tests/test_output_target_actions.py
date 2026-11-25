"""Tests for declarative actions routed through SC output_target links."""
from __future__ import annotations

import unittest

from module_a.types import (
    EventType,
    InteractionEvent,
    ModuleAConfig,
    PackageAtoB,
    PackageTrigger,
    UserModel,
)
from module_a.storage.memory import InMemoryStorage
from module_a.user_model_manager import UserModelManager
from module_b import ModuleB
from module_b.rule_schema import (
    AdaptationRule,
    RuleAction,
    RuleTrigger,
    TriggerKind,
    rules_from_jsonable,
    rules_to_jsonable,
)


def action_event(output_targets):
    return InteractionEvent(
        id="event-save",
        user_id="user-1",
        interface_id="calendar",
        session_id="session-1",
        event_type=EventType.SUCCESSFUL_ACTION,
        timestamp="2026-11-25T10:00:00Z",
        element_id="save_button",
        action_id="save_calendar",
        new_value={
            "input_values": {"title_field": "Planning"},
            "output_target_ids": output_targets,
        },
    )


def output_rule():
    return AdaptationRule(
        id="save_calendar_rule",
        trigger=RuleTrigger(
            kind=TriggerKind.SUCCESS_COUNT,
            threshold=1,
            action_id="save_calendar",
        ),
        action=RuleAction(
            target_element_id="$output_target",
            property="visible",
            old_value=False,
            new_value=True,
        ),
    )


def package(event):
    return PackageAtoB(
        user_id="user-1",
        interface_id="calendar",
        model_version=1,
        model_snapshot=UserModel(user_id="user-1", is_cold_start=True),
        observation_window={"event_count": 1},
        interaction_events=[event],
        manual_override=False,
        trigger=PackageTrigger.THRESHOLD,
        timestamp=event.timestamp,
    )


class OutputTargetActionTests(unittest.IsolatedAsyncioTestCase):
    async def test_action_event_is_forwarded_to_module_b(self):
        manager = UserModelManager(
            InMemoryStorage(),
            ModuleAConfig(PERIODIC_SNAPSHOT_MS=0),
        )
        send, trigger = await manager.should_send_package(
            "user-1",
            event=action_event(["status_panel"]),
        )
        self.assertTrue(send)
        self.assertEqual(trigger, "threshold")

    async def test_action_rule_resolves_single_output_target_during_cold_start(self):
        module_b = ModuleB(rules=[output_rule()])
        module_b.set_version_provider(lambda interface_id: "v1")

        result = await module_b.decide(package(action_event(["status_panel"])))

        self.assertEqual(result.status.value, "command")
        self.assertEqual(result.command.target_element_id, "status_panel")
        self.assertEqual(result.command.property, "visible")
        self.assertIs(result.command.new_value, True)

    async def test_dynamic_output_target_rejects_ambiguous_or_missing_targets(self):
        module_b = ModuleB(rules=[output_rule()])
        module_b.set_version_provider(lambda interface_id: "v1")

        ambiguous = await module_b.decide(
            package(action_event(["status_panel", "result_panel"]))
        )
        missing = await module_b.decide(package(action_event([])))

        self.assertEqual(ambiguous.status.value, "rejected")
        self.assertEqual(missing.status.value, "rejected")

    async def test_action_id_survives_rule_json_roundtrip(self):
        rule = output_rule()
        restored = rules_from_jsonable(rules_to_jsonable([rule]))
        self.assertEqual(restored[0].trigger.action_id, "save_calendar")
        self.assertEqual(restored[0].action.target_element_id, "$output_target")


    async def test_action_flows_from_module_a_through_b_and_c(self):
        from datetime import datetime, timezone

        from module_a import ModuleA
        from module_a.storage.memory import InMemoryStorage
        from module_c import MemoryRepository, MemoryRuntime, ModuleC
        from module_c.model import AdaptationPolicy

        config = ModuleAConfig(PERIODIC_SNAPSHOT_MS=0)
        module_a = ModuleA(InMemoryStorage(config), config)
        repository = MemoryRepository()
        runtime = MemoryRuntime()
        repository.register(
            "calendar",
            {
                "id": "calendar",
                "components": [
                    {
                        "id": "save_button",
                        "typeId": "button",
                        "props": {"visible": True, "action_id": "save_calendar"},
                    },
                    {
                        "id": "status_panel",
                        "typeId": "window",
                        "props": {"visible": False},
                    },
                ],
                "links": [
                    {
                        "id": "save_status",
                        "kind": "output_target",
                        "sourceId": "save_button",
                        "targetId": "status_panel",
                    }
                ],
            },
        )
        module_c = ModuleC(
            repository,
            runtime,
            policy=AdaptationPolicy.from_catalog(["save_button", "status_panel"]),
        )
        module_b = ModuleB(rules=[output_rule()])
        module_b.set_version_provider(module_c.active_version)
        module_b.set_command_handler(module_c.apply)
        module_c.set_application_handler(module_a.handle_application_result)
        module_a.set_package_handler(module_b.handle_package)

        try:
            await module_a.handle_event(
                InteractionEvent(
                    id="event-save-e2e",
                    user_id="user-1",
                    interface_id="calendar",
                    session_id="session-1",
                    event_type=EventType.SUCCESSFUL_ACTION,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    element_id="save_button",
                    action_id="save_calendar",
                    property="action_context",
                    new_value={
                        "input_values": {"title_field": "Planning"},
                        "output_target_ids": ["status_panel"],
                    },
                )
            )

            version, model = await module_c.state("calendar", "user-1", "session-1")
            status = next(item for item in model["components"] if item["id"] == "status_panel")
            self.assertTrue(status["props"]["visible"])
            self.assertNotEqual(version, "v1")
            self.assertEqual(runtime.states["calendar"]["components"][1]["props"]["visible"], True)
        finally:
            module_a.dispose()



if __name__ == "__main__":
    unittest.main()
