#!/usr/bin/env python3
"""Сквозное демо A → ModuleB → MockModuleC."""

from __future__ import annotations

import asyncio
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from module_a import (
    ModuleA,
    InMemoryStorage,
    ModuleAConfig,
    InteractionEvent,
    EventType,
)
from module_b import ModuleB
from module_c import ModuleC, MemoryRepository, MemoryRuntime, default_model


def evt(event_type: EventType, **kw) -> InteractionEvent:
    return InteractionEvent(
        id=f"e_{uuid.uuid4().hex[:6]}",
        user_id=kw.pop("user_id", "user_001"),
        interface_id=kw.pop("interface_id", "python_tutor_model"),
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        event_type=event_type,
        **kw,
    )


async def main() -> None:
    print("=== A → ModuleB → C ===\n")
    cfg = ModuleAConfig(
        COLD_START_THRESHOLD=5,
        ERROR_RATE_THRESHOLD=0.25,
        HELP_THRESHOLD=2,
        OBSERVATION_EVENT_LIMIT=30,
        PERIODIC_SNAPSHOT_MS=0,
    )
    a = ModuleA(InMemoryStorage(cfg), cfg)
    b = ModuleB()
    repo = MemoryRepository()
    repo.register('python_tutor_model', default_model())
    c = ModuleC(repo, MemoryRuntime())
    b.set_version_provider(c.active_version)

    b.set_command_handler(c.apply)
    c.set_application_handler(a.handle_application_result)
    a.set_package_handler(b.handle_package)

    print("--- накопление (cold start) ---")
    for _ in range(5):
        await a.handle_event(evt(EventType.SUCCESSFUL_ACTION))
    m = await a.get_user_model("user_001")
    print(f"cold={m.is_cold_start} notified={m.cold_start_notified} events={m.counters.total_events}")

    print("\n--- ошибки → R1 (hints_panel) ---")
    for _ in range(4):
        await a.handle_event(evt(EventType.ERROR, element_id="hints_panel", error_code="validation"))
    print("UI state:", (await repo.current('python_tutor_model'))[1])
    m = await a.get_user_model("user_001")
    print(f"adaptation_history={len(m.adaptation_history)}")

    print("\n--- help → history ---")
    b.reset_anti_flicker("user_001")
    for _ in range(4):
        await a.handle_event(evt(EventType.HELP_REQUEST))
    print("UI state:", (await repo.current('python_tutor_model'))[1])

    a.dispose()
    print("\nГотово.")


if __name__ == "__main__":
    asyncio.run(main())
