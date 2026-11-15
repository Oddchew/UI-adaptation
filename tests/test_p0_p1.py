#!/usr/bin/env python3
"""Тесты P0/P1 для Python-модуля A."""

from __future__ import annotations

import asyncio
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from module_a import (
    ModuleAConfig,
    InMemoryStorage,
    UserModelManager,
    PackageBuilder,
    InteractionEvent,
    EventType,
    AdaptationResult,
    ValidationError,
    validate_interaction_event,
)
from module_a.types import PackageTrigger

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


def evt(etype: EventType, **kw) -> InteractionEvent:
    return InteractionEvent(
        id=kw.pop("id", f"e_{uuid.uuid4().hex[:6]}"),
        user_id=kw.pop("user_id", "u1"),
        interface_id=kw.pop("interface_id", "ui1"),
        timestamp=kw.pop("timestamp", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
        event_type=etype,
        **kw,
    )


async def run() -> None:
    global passed, failed
    print("P0/P1 Python suite\n")

    # validation
    try:
        validate_interaction_event(InteractionEvent(
            id="", user_id="u", interface_id="i", event_type=EventType.ERROR, timestamp="x"
        ))
        assert_(False, "empty id should fail")
    except ValidationError:
        assert_(True, "empty id rejected")

    try:
        future = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 3600)
        )
        validate_interaction_event(evt(EventType.ERROR, timestamp=future))
        assert_(False, "future ts should fail")
    except ValidationError:
        assert_(True, "future ts rejected")

    # cold_start once
    cfg = ModuleAConfig(COLD_START_THRESHOLD=3)
    storage = InMemoryStorage(cfg)
    mgr = UserModelManager(storage, cfg)
    for _ in range(3):
        await mgr.process_event(evt(EventType.SUCCESSFUL_ACTION))
    send, trig = await mgr.should_send_package("u1")
    assert_(send and trig == "cold_start", "first cold_start")
    await mgr.mark_cold_start_notified("u1")
    send, trig = await mgr.should_send_package("u1")
    assert_(trig != "cold_start", "no second cold_start")

    # mutex
    cfg2 = ModuleAConfig(COLD_START_THRESHOLD=100)
    st2 = InMemoryStorage(cfg2)
    mgr2 = UserModelManager(st2, cfg2)
    await asyncio.gather(*[
        mgr2.process_event(evt(EventType.SUCCESSFUL_ACTION, id=f"c_{i}"))
        for i in range(20)
    ])
    m = await mgr2.get_model("u1")
    assert_(m is not None and m.counters.total_events == 20, "mutex 20 events")

    # ring buffer
    cfg3 = ModuleAConfig(COLD_START_THRESHOLD=100, MAX_EVENTS_STORED=5)
    st3 = InMemoryStorage(cfg3)
    mgr3 = UserModelManager(st3, cfg3)
    for i in range(12):
        await mgr3.process_event(evt(EventType.SUCCESSFUL_ACTION, id=f"r_{i}"))
    stored = await st3.get_events("u1")
    assert_(len(stored) == 5, "ring buffer 5")
    m3 = await mgr3.get_model("u1")
    assert_(m3.counters.total_events == 12, "counters 12")

    # history limit in package
    cfg4 = ModuleAConfig(COLD_START_THRESHOLD=1, HISTORY_IN_SNAPSHOT_LIMIT=3)
    st4 = InMemoryStorage(cfg4)
    mgr4 = UserModelManager(st4, cfg4)
    await mgr4.process_event(evt(EventType.SUCCESSFUL_ACTION))
    for i in range(8):
        await mgr4.record_adaptation_result(
            AdaptationResult(
                request_id=f"r{i}",
                interface_id="ui1",
                user_id="u1",
                success=True,
                applied_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            )
        )
    builder = PackageBuilder(mgr4)
    pkg = await builder.build("u1", "ui1", PackageTrigger.FORCE)
    assert_(len(pkg.model_snapshot.adaptation_history) == 3, "history limit 3")

    # error threshold
    cfg5 = ModuleAConfig(COLD_START_THRESHOLD=2, ERROR_RATE_THRESHOLD=0.4)
    st5 = InMemoryStorage(cfg5)
    mgr5 = UserModelManager(st5, cfg5)
    await mgr5.process_event(evt(EventType.SUCCESSFUL_ACTION))
    await mgr5.process_event(evt(EventType.SUCCESSFUL_ACTION))
    await mgr5.mark_cold_start_notified("u1")
    for _ in range(3):
        await mgr5.process_event(evt(EventType.ERROR, error_code="v"))
    send, trig = await mgr5.should_send_package("u1")
    assert_(send and trig == "threshold", "error threshold")

    print(f"\n\nПройдено: {passed}\nПровалено: {failed}")
    if errors:
        for e in errors:
            print(" ", e)
        raise SystemExit(1)
    print("P0/P1 OK")


if __name__ == "__main__":
    asyncio.run(run())
