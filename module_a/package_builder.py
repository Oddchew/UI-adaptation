"""Формирование пакета A→B."""

from __future__ import annotations

import copy
from datetime import datetime, timezone

from .types import PackageAtoB, PackageTrigger, UserModel, session_key
from .user_model_manager import UserModelManager


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class PackageBuilder:
    def __init__(self, model_manager: UserModelManager) -> None:
        self._mgr = model_manager

    async def build(
        self,
        user_id: str,
        interface_id: str,
        trigger: PackageTrigger,
        manual_override: bool = False,
        session_id: str | None = None,
    ) -> PackageAtoB:
        model = await self._mgr.get_or_create_model(user_id)
        events = await self._mgr.get_events_in_window(user_id, interface_id, session_id)
        limit = self._mgr.config.HISTORY_IN_SNAPSHOT_LIMIT

        snapshot: UserModel = copy.deepcopy(model)
        snapshot.adaptation_history = list(snapshot.adaptation_history or [])[-limit:]

        return PackageAtoB(
            user_id=user_id,
            interface_id=interface_id,
            model_version=model.model_version,
            model_snapshot=snapshot,
            observation_window={
                "start": events[0].timestamp if events else "",
                "end": events[-1].timestamp if events else "",
                "event_count": len(events),
            },
            interaction_events=events,
            manual_override=manual_override or session_key(interface_id, session_id) in model.manual_mode_sessions,
            trigger=trigger,
            timestamp=_now_iso(),
        )
