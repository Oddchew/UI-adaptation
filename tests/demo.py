#!/usr/bin/env python3
"""Демонстрация модуля A."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from module_a import (
    ModuleA,
    InMemoryStorage,
    ModuleAConfig,
    InteractionEvent,
    EventType,
    AdaptationResult,
)
import time
import uuid


def evt(event_type: EventType, **kw) -> InteractionEvent:
    return InteractionEvent(
        id=f"e_{uuid.uuid4().hex[:6]}",
        user_id=kw.pop("user_id", "user_001"),
        interface_id="ui_main",
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        event_type=event_type,
        **kw,
    )


async def main() -> None:
    print("=== Демо модуля A (Python) ===\n")
    cfg = ModuleAConfig(
        COLD_START_THRESHOLD=8,
        ERROR_RATE_THRESHOLD=0.3,
        HELP_THRESHOLD=2,
        OBSERVATION_EVENT_LIMIT=20,
        PERIODIC_SNAPSHOT_MS=60_000,
    )
    storage = InMemoryStorage(cfg)
    module_a = ModuleA(storage, cfg)
    packages = []

    async def on_pkg(pkg):
        packages.append(pkg)
        print(f"\n📦 Пакет → B  trigger={pkg.trigger.value}  v={pkg.model_version}")
        print(f"   cold_start={pkg.model_snapshot.is_cold_start}  "
              f"error_rate={pkg.model_snapshot.observation.recent_error_rate:.2f}")

    module_a.set_package_handler(on_pkg)

    print("--- Холодный старт ---")
    for _ in range(3):
        await module_a.handle_event(evt(EventType.SUCCESSFUL_ACTION))
    m = await module_a.get_user_model("user_001")
    print(f"После 3: cold={m.is_cold_start}, events={m.counters.total_events}")

    print("\n--- Накопление ---")
    for _ in range(5):
        await module_a.handle_event(evt(EventType.SUCCESSFUL_ACTION))
    m = await module_a.get_user_model("user_001")
    print(f"После 8: cold={m.is_cold_start}, notified={m.cold_start_notified}, packages={len(packages)}")

    print("\n--- Ошибки (порог) ---")
    for _ in range(5):
        await module_a.handle_event(evt(EventType.ERROR, error_code="validation"))
    m = await module_a.get_user_model("user_001")
    print(f"error_rate={m.observation.recent_error_rate:.2f}, packages={len(packages)}")

    print("\n--- manual_override ---")
    await module_a.handle_event(
        evt(EventType.MANUAL_OVERRIDE, property="theme", old_value="light", new_value="dark")
    )
    m = await module_a.get_user_model("user_001")
    print(f"theme={m.preferences.theme}, packages={len(packages)}")

    print("\n--- Результат от C ---")
    await module_a.handle_application_result(
        AdaptationResult(
            request_id="req_demo",
            interface_id="ui_main",
            user_id="user_001",
            success=True,
            applied_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            target_element_id="help_panel",
            property="visible",
            new_value=True,
            reason="demo",
        )
    )
    m = await module_a.get_user_model("user_001")
    print(f"history={len(m.adaptation_history)}")

    module_a.dispose()
    print("\n=== Готово ===")


if __name__ == "__main__":
    asyncio.run(main())
