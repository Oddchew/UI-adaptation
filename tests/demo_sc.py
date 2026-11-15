#!/usr/bin/env python3
"""Демо: Module A + sc-server (ostis-example-app)."""

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
    HybridStorage,
    ScMemoryStorage,
    InteractionEvent,
    EventType,
)


def evt(etype: EventType, **kw) -> InteractionEvent:
    return InteractionEvent(
        id=kw.pop("id", f"e_{uuid.uuid4().hex[:6]}"),
        user_id=kw.pop("user_id", "user_sc_demo"),
        interface_id="ui_main",
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        event_type=etype,
        **kw,
    )


async def main() -> None:
    print("=== Module A + sc-server ===\n")
    ws = "ws://127.0.0.1:8090/ws_json"

    cfg = ModuleAConfig(COLD_START_THRESHOLD=5, ERROR_RATE_THRESHOLD=0.3)
    hybrid = HybridStorage(config=cfg, ws_url=ws)
    ok = await hybrid.connect_sc()
    print(f"✓ HybridStorage sc ready: {ok}")
    if not ok:
        print("sc не подключен — только in-memory")
        return

    # тот же ScMemoryStorage, что внутри Hybrid — общий кэш/запись
    sc = hybrid._sc  # noqa: SLF001

    module_a = ModuleA(hybrid, cfg)
    packages = []

    async def on_pkg(pkg):
        packages.append(pkg)
        print(f"  📦 A→B trigger={pkg.trigger.value} v={pkg.model_version}")

    module_a.set_package_handler(on_pkg)

    print("\n--- события ---")
    for i in range(5):
        await module_a.handle_event(evt(EventType.SUCCESSFUL_ACTION, id=f"ok_{i}"))
    for i in range(3):
        await module_a.handle_event(
            evt(EventType.ERROR, id=f"err_{i}", error_code="validation")
        )

    model = await module_a.get_user_model("user_sc_demo")
    print(f"\nmodel (hybrid/memory) events={model.counters.total_events if model else None}")
    print(f"cold_start={model.is_cold_start if model else None}")
    print(f"packages={len(packages)}")

    print("\n--- read-back из того же ScMemoryStorage ---")
    # кэш сессии
    cached_keys = list(getattr(sc, "_payload_text_by_marker", {}).keys())
    print(f"  session markers: {len(cached_keys)}")
    for k in cached_keys[:5]:
        print(f"    - {k}")

    from_sc = await sc.get_user_model("user_sc_demo")
    if from_sc:
        print(
            f"✓ sc model: events={from_sc.counters.total_events} "
            f"version={from_sc.model_version} completeness={from_sc.completeness:.2f}"
        )
    else:
        print("⚠ model not in sc cache/search")
        # диагностика: есть ли marker-link
        marker = sc._marker_model("user_sc_demo")
        found = sc._search_links(marker)
        print(f"  search marker '{marker}': {len(found)} link(s)")
        if found:
            data = sc._get_link_data(found[-1])
            print(f"  last link content preview: {(data or '')[:120]!r}")

    events_sc = await sc.get_events("user_sc_demo")
    print(f"  events via sc API: {len(events_sc)}")

    # отдельный клиент (как после рестарта процесса) — только sc search
    print("\n--- read-back новым клиентом (без session cache) ---")
    sc2 = ScMemoryStorage(ws_url=ws, soft_fail=True)
    await sc2.connect()
    from_sc2 = await sc2.get_user_model("user_sc_demo")
    if from_sc2:
        print(f"✓ sc2 model: events={from_sc2.counters.total_events} v={from_sc2.model_version}")
    else:
        marker = sc2._marker_model("user_sc_demo")
        found = sc2._search_links(marker)
        print(f"⚠ sc2: model not found; marker links={len(found)}")
        if found:
            print(f"  content: {(sc2._get_link_data(found[-1]) or '')[:120]!r}")
    await sc2.disconnect()

    module_a.dispose()
    await sc.disconnect()
    print("\n=== done ===")


if __name__ == "__main__":
    asyncio.run(main())

