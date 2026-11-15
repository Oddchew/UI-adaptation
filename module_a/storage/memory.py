"""In-memory хранилище с ring buffer."""

from __future__ import annotations

import copy
from datetime import datetime
from typing import Optional

from ..types import (
    DEFAULT_CONFIG,
    AdaptationResult,
    InteractionEvent,
    ModuleAConfig,
    UserModel,
)
from .base import IStorage


def _parse_ts(ts: str) -> float:
    normalized = ts.replace("Z", "+00:00") if ts.endswith("Z") else ts
    return datetime.fromisoformat(normalized).timestamp()


class InMemoryStorage(IStorage):
    def __init__(self, config: Optional[ModuleAConfig] = None) -> None:
        cfg = config or DEFAULT_CONFIG
        self._max_events = cfg.MAX_EVENTS_STORED
        self._models: dict[str, UserModel] = {}
        self._events: dict[str, list[InteractionEvent]] = {}
        self._history: dict[str, list[AdaptationResult]] = {}

    async def get_user_model(self, user_id: str) -> Optional[UserModel]:
        m = self._models.get(user_id)
        return copy.deepcopy(m) if m else None

    async def save_user_model(self, model: UserModel) -> None:
        self._models[model.user_id] = copy.deepcopy(model)

    async def append_event(self, event: InteractionEvent) -> None:
        lst = self._events.setdefault(event.user_id, [])
        lst.append(copy.deepcopy(event))
        if len(lst) > self._max_events:
            del lst[: len(lst) - self._max_events]

    async def get_events(
        self,
        user_id: str,
        *,
        from_ts: Optional[str] = None,
        to_ts: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[InteractionEvent]:
        lst = list(self._events.get(user_id, []))
        if from_ts:
            ft = _parse_ts(from_ts)
            lst = [e for e in lst if _parse_ts(e.timestamp) >= ft]
        if to_ts:
            tt = _parse_ts(to_ts)
            lst = [e for e in lst if _parse_ts(e.timestamp) <= tt]
        if limit is not None and len(lst) > limit:
            lst = lst[-limit:]
        return copy.deepcopy(lst)

    async def save_adaptation_result(self, result: AdaptationResult) -> None:
        lst = self._history.setdefault(result.user_id, [])
        lst.append(copy.deepcopy(result))
        if len(lst) > 100:
            del lst[: len(lst) - 100]

    async def get_adaptation_history(
        self, user_id: str, limit: int = 50
    ) -> list[AdaptationResult]:
        lst = self._history.get(user_id, [])
        return copy.deepcopy(lst[-limit:])

    def clear(self) -> None:
        self._models.clear()
        self._events.clear()
        self._history.clear()

    def dump(self) -> dict[str, int]:
        return {
            "models": len(self._models),
            "events": sum(len(v) for v in self._events.values()),
            "history": sum(len(v) for v in self._history.values()),
        }
