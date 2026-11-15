#!/usr/bin/env python3
"""Тесты Модуля B (решение об адаптации + декларативные правила)."""

from __future__ import annotations

import asyncio
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from module_a.types import (
    EventType,
    InteractionEvent,
    ObservationWindow,
    PackageAtoB,
    PackageTrigger,
    UserCounters,
    UserModel,
    UserPreferences,
    UserCharacteristics,
)
from module_b import ModuleB, DecisionStatus, RejectReason

passed = failed = 0
errors: list[str] = []


def assert_(cond: bool, msg: str) -> None:
    global passed, failed
    if cond:
        passed += 1
        print(".", end="", flush=True)
    else:
        failed += 1
        errors.append(msg)
        print("F", end="", flush=True)


def make_pkg(
    *,
    errors: int = 0,
    helps: int = 0,
    successes: int = 0,
    cold: bool = False,
    manual: bool = False,
    error_rate: float = 0.0,
    n_pad: int = 0,
) -> PackageAtoB:
    evs: list[InteractionEvent] = []
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for i in range(errors):
        evs.append(
            InteractionEvent(
                id=f"err{i}_{uuid.uuid4().hex[:4]}",
                user_id="u1",
                interface_id="python_tutor_task_1",
                event_type=EventType.ERROR,
                timestamp=ts,
                element_id="hints_panel",
            )
        )
    for i in range(helps):
        evs.append(
            InteractionEvent(
                id=f"help{i}_{uuid.uuid4().hex[:4]}",
                user_id="u1",
                interface_id="python_tutor_task_1",
                event_type=EventType.HELP_REQUEST,
                timestamp=ts,
            )
        )
    for i in range(successes):
        evs.append(
            InteractionEvent(
                id=f"ok{i}_{uuid.uuid4().hex[:4]}",
                user_id="u1",
                interface_id="python_tutor_task_1",
                event_type=EventType.SUCCESSFUL_ACTION,
                timestamp=ts,
                action_id="check_run",
            )
        )
    for i in range(n_pad):
        evs.append(
            InteractionEvent(
                id=f"pad{i}_{uuid.uuid4().hex[:4]}",
                user_id="u1",
                interface_id="python_tutor_task_1",
                event_type=EventType.FOCUS,
                timestamp=ts,
            )
        )
    model = UserModel(
        user_id="u1",
        model_version=2,
        is_cold_start=cold,
        counters=UserCounters(
            total_events=len(evs),
            total_errors=errors,
            help_requests=helps,
            successful_actions=successes,
        ),
        observation=ObservationWindow(
            event_count=len(evs),
            recent_error_rate=error_rate if error_rate else (errors / max(len(evs), 1)),
        ),
        preferences=UserPreferences(),
        characteristics=UserCharacteristics(),
    )
    return PackageAtoB(
        user_id="u1",
        interface_id="python_tutor_task_1",
        model_version=2,
        model_snapshot=model,
        observation_window={"event_count": len(evs)},
        interaction_events=evs,
        manual_override=manual,
        trigger=PackageTrigger.COLD_START if cold else PackageTrigger.THRESHOLD,
        timestamp=ts,
    )


async def run() -> None:
    global passed, failed
    print("Module B suite\n")
    b = ModuleB()

    r = await b.decide(make_pkg(errors=5, n_pad=3, manual=True))
    assert_(r.status == DecisionStatus.REJECTED and r.reject_reason == RejectReason.MANUAL_OVERRIDE, "manual")

    r = await b.decide(make_pkg(errors=5, n_pad=3, cold=True))
    assert_(r.status == DecisionStatus.REJECTED and r.reject_reason == RejectReason.COLD_START, "cold")

    r = await b.decide(make_pkg(errors=1))
    assert_(
        r.status == DecisionStatus.REJECTED and r.reject_reason == RejectReason.INSUFFICIENT_DATA,
        "insufficient",
    )

    b.reset_anti_flicker()
    r = await b.decide(make_pkg(errors=3, n_pad=1))
    assert_(r.status == DecisionStatus.COMMAND and r.command is not None, "R1 command")
    assert_(r.command is not None and r.command.rule_id == "R_hint_after_2_errors", "R1 rule")
    assert_(r.command is not None and r.command.target_element_id == "hints_panel", "R1 target")
    assert_(r.command is not None and r.command.property == "visible" and r.command.new_value is True, "R1 val")

    r2 = await b.decide(make_pkg(errors=3, n_pad=1))
    assert_(
        r2.status == DecisionStatus.REJECTED and r2.reject_reason == RejectReason.ALREADY_APPLIED,
        "anti-flicker",
    )

    b.reset_anti_flicker()
    r = await b.decide(make_pkg(helps=4))
    assert_(r.status == DecisionStatus.COMMAND and r.command is not None, "R2 command")
    assert_(r.command is not None and r.command.rule_id == "R_enlarge_font_on_help", "R2 rule")
    assert_(r.command is not None and r.command.property == "fontSize", "R2 prop")

    b.reset_anti_flicker()
    r = await b.decide(make_pkg(successes=3))
    assert_(
        r.status == DecisionStatus.REJECTED and r.reject_reason == RejectReason.NO_RULE_MATCHED,
        "no match",
    )

    b.reset_anti_flicker()
    seen = []

    async def on_cmd(cmd):
        seen.append(cmd)

    b.set_command_handler(on_cmd)
    cmd = await b.handle_package(make_pkg(errors=4, n_pad=1))
    assert_(cmd is not None and len(seen) == 1, "handler called")

    # --- декларативное правило «из редактора» ---
    print("\nDeclarative")
    custom = [
        {
            "id": "R_theme_on_many_errors",
            "priority": 1,
            "enabled": True,
            "trigger": {"kind": "error_count", "threshold": 4, "op": "gte"},
            "action": {
                "target_element_id": "app_shell",
                "property": "theme",
                "old_value": "light",
                "new_value": "dark",
            },
        }
    ]
    b3 = ModuleB(rules=custom)
    r = await b3.decide(make_pkg(errors=5, n_pad=1))
    assert_(r.status == DecisionStatus.COMMAND and r.command is not None, "custom command")
    assert_(r.command is not None and r.command.rule_id == "R_theme_on_many_errors", "custom id")
    assert_(r.command is not None and r.command.new_value == "dark", "custom value")

    path = Path(__file__).resolve().parents[1] / "module_b" / "rules_default.json"
    b4 = ModuleB(rules=path)
    r = await b4.decide(make_pkg(errors=3, n_pad=1))
    assert_(r.status == DecisionStatus.COMMAND, "json file rules")

    print(f"\n\npassed={passed} failed={failed}")
    for e in errors:
        print(" -", e)
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run())
