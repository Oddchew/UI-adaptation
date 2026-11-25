from __future__ import annotations

import time
import uuid

from module_a.types import (
    EventType, InteractionEvent, ObservationWindow, PackageAtoB, PackageTrigger,
    UserCounters, UserModel, UserPreferences, UserCharacteristics,
)


def make_package(errors: int = 0) -> PackageAtoB:
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    events = [
        InteractionEvent(
            id=f"err-{i}-{uuid.uuid4().hex[:6]}",
            user_id="u1",
            interface_id="python_tutor_task_1",
            event_type=EventType.ERROR,
            timestamp=timestamp,
            element_id="hints_panel",
            error_code="validation",
        )
        for i in range(errors)
    ]
    model = UserModel(
        user_id="u1",
        counters=UserCounters(total_events=errors, total_errors=errors),
        observation=ObservationWindow(event_count=errors),
        preferences=UserPreferences(),
        characteristics=UserCharacteristics(),
    )
    return PackageAtoB(
        user_id="u1",
        interface_id="python_tutor_task_1",
        model_version=1,
        model_snapshot=model,
        observation_window={"event_count": errors},
        interaction_events=events,
        manual_override=False,
        trigger=PackageTrigger.THRESHOLD,
        timestamp=timestamp,
    )
