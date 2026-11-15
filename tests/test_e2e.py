#!/usr/bin/env python3
"""E2E A→B→C на Python."""

from __future__ import annotations

import asyncio
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from module_a import (
    ModuleA,
    ModuleAConfig,
    InMemoryStorage,
    InteractionEvent,
    EventType,
    MockModuleB,
    MockModuleC,
)

passed = failed = 0


def assert_(c: bool, msg: str) -> None:
    global passed, failed
    if c:
        passed += 1
        print(".", end="", flush=True)
    else:
        failed += 1
        print(f"\nFAIL: {msg}")


def evt(etype: EventType, **kw) -> InteractionEvent:
    return InteractionEvent(
        id=f"e_{uuid.uuid4().hex[:6]}",
        user_id=kw.pop("user_id", "user_e2e"),
        interface_id="ui_main",
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        event_type=etype,
        **kw,
    )


async def run() -> None:
    print("=== E2E Python A→B→C ===\n")
    cfg = ModuleAConfig(COLD_START_THRESHOLD=5, ERROR_RATE_THRESHOLD=0.25, HELP_THRESHOLD=3)
    storage = InMemoryStorage(cfg)
    module_a = ModuleA(storage, cfg)
    module_b = MockModuleB()
    module_c = MockModuleC()

    async def on_cmd(cmd):
        await module_c.apply(cmd)

    module_b.set_command_handler(on_cmd)

    async def on_app(result):
        await module_a.handle_application_result(result)

    module_c.set_application_handler(on_app)

    async def on_pkg(pkg):
        await module_b.handle_package(pkg)

    module_a.set_package_handler(on_pkg)

    # cold start
    for _ in range(5):
        await module_a.handle_event(evt(EventType.SUCCESSFUL_ACTION))
    m = await module_a.get_user_model("user_e2e")
    assert_(m is not None and m.cold_start_notified, "cold_start notified")
    assert_(not m.is_cold_start, "not cold after 5")

    # errors → help
    module_b.reset_anti_flicker("user_e2e")
    for _ in range(5):
        await module_a.handle_event(evt(EventType.ERROR, error_code="validation"))
    ui = module_c.get_ui_state()
    assert_(ui.get("help_panel", {}).get("visible") is True, "help_panel visible")

    # manual override
    await module_a.handle_event(
        evt(EventType.MANUAL_OVERRIDE, property="theme", old_value="light", new_value="dark")
    )
    m = await module_a.get_user_model("user_e2e")
    assert_(m.preferences.theme is not None and m.preferences.theme.value == "dark", "theme dark")

    # help user → font
    module_b.reset_anti_flicker("user_help")
    for _ in range(5):
        await module_a.handle_event(evt(EventType.SUCCESSFUL_ACTION, user_id="user_help"))
    module_b.reset_anti_flicker("user_help")
    for _ in range(4):
        await module_a.handle_event(
            evt(EventType.HELP_REQUEST, user_id="user_help", help_type="tooltip")
        )
    ui = module_c.get_ui_state()
    assert_(ui.get("main_content", {}).get("fontSize") == 16, "fontSize 16")

    module_a.dispose()
    print(f"\n\nПройдено: {passed}, Провалено: {failed}")
    if failed:
        raise SystemExit(1)
    print("E2E OK")


if __name__ == "__main__":
    asyncio.run(run())
