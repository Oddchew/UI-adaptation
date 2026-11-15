"""Управление моделью пользователя: счётчики, окно, cold start, mutex."""

from __future__ import annotations

import asyncio
import copy
from datetime import datetime, timezone
from typing import Optional

from .storage.base import IStorage
from .storage.memory import InMemoryStorage
from .types import (
    DEFAULT_CONFIG,
    AdaptationResult,
    ExperienceLevel,
    InteractionEvent,
    ModuleAConfig,
    ThemePreference,
    UserModel,
    UserCharacteristics,
    UserCounters,
    ObservationWindow,
    UserPreferences,
    EventType,
)
from .validation import validate_adaptation_result, validate_interaction_event


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _create_empty_model(user_id: str) -> UserModel:
    now = _now_iso()
    return UserModel(
        user_id=user_id,
        model_version=1,
        created_at=now,
        updated_at=now,
        is_cold_start=True,
        cold_start_notified=False,
        completeness=0.0,
        characteristics=UserCharacteristics(),
        counters=UserCounters(),
        observation=ObservationWindow(window_start=now, window_end=now),
        preferences=UserPreferences(),
        adaptation_history=[],
    )


class UserModelManager:
    def __init__(
        self,
        storage: Optional[IStorage] = None,
        config: Optional[ModuleAConfig] = None,
    ) -> None:
        self.config = config or DEFAULT_CONFIG
        self.storage = storage or InMemoryStorage(self.config)
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock_for(self, user_id: str) -> asyncio.Lock:
        if user_id not in self._locks:
            self._locks[user_id] = asyncio.Lock()
        return self._locks[user_id]

    async def get_or_create_model(self, user_id: str) -> UserModel:
        model = await self.storage.get_user_model(user_id)
        if not model:
            model = _create_empty_model(user_id)
            await self.storage.save_user_model(model)
        return model

    async def process_event(self, raw: InteractionEvent) -> UserModel:
        event = validate_interaction_event(raw, self.config)
        async with self._lock_for(event.user_id):
            return await self._process_unlocked(event)

    async def _process_unlocked(self, event: InteractionEvent) -> UserModel:
        await self.storage.append_event(event)
        model = await self.get_or_create_model(event.user_id)

        model.counters.total_events += 1
        model.updated_at = _now_iso()

        et = event.event_type
        if et == EventType.ERROR:
            model.counters.total_errors += 1
            if event.error_code:
                model.counters.errors_by_type[event.error_code] = (
                    model.counters.errors_by_type.get(event.error_code, 0) + 1
                )
        elif et == EventType.HELP_REQUEST:
            model.counters.help_requests += 1
        elif et == EventType.SUCCESSFUL_ACTION:
            model.counters.successful_actions += 1
        elif et == EventType.BLOCK_OPEN:
            model.counters.block_opens += 1
        elif et == EventType.BLOCK_CLOSE:
            model.counters.block_closes += 1
        elif et == EventType.MANUAL_OVERRIDE:
            model.counters.manual_overrides += 1
            if event.property == "theme" and isinstance(event.new_value, str):
                try:
                    model.preferences.theme = ThemePreference(event.new_value)
                except ValueError:
                    pass
            if event.property == "show_tooltips" and isinstance(event.new_value, bool):
                model.preferences.show_tooltips = event.new_value

        all_events = await self.storage.get_events(event.user_id)
        self._update_observation(model, all_events)
        self._update_cold_start_and_completeness(model)
        self._update_experience(model)

        model.model_version += 1
        await self.storage.save_user_model(model)
        return model

    def _update_observation(self, model: UserModel, all_events: list[InteractionEvent]) -> None:
        now_ms = datetime.now(timezone.utc).timestamp() * 1000
        time_limit = self.config.OBSERVATION_TIME_LIMIT_MS
        event_limit = self.config.OBSERVATION_EVENT_LIMIT

        window: list[InteractionEvent] = []
        for e in all_events:
            try:
                t = datetime.fromisoformat(e.timestamp.replace("Z", "+00:00")).timestamp() * 1000
            except Exception:
                continue
            if now_ms - t <= time_limit:
                window.append(e)
        if len(window) > event_limit:
            window = window[-event_limit:]

        err = sum(1 for e in window if e.event_type == EventType.ERROR)
        help_n = sum(1 for e in window if e.event_type == EventType.HELP_REQUEST)
        n = len(window)
        model.observation = ObservationWindow(
            window_start=window[0].timestamp if window else model.observation.window_start,
            window_end=window[-1].timestamp if window else _now_iso(),
            event_count=n,
            recent_error_rate=(err / n) if n else 0.0,
            recent_help_rate=(help_n / n) if n else 0.0,
        )

    def _update_cold_start_and_completeness(self, model: UserModel) -> None:
        total = model.counters.total_events
        model.is_cold_start = total < self.config.COLD_START_THRESHOLD
        score = 0.0
        if total >= 5:
            score += 0.2
        if total >= self.config.COLD_START_THRESHOLD:
            score += 0.3
        if model.counters.successful_actions > 0:
            score += 0.15
        if model.counters.help_requests > 0 or model.counters.total_errors > 0:
            score += 0.15
        if model.preferences.theme is not None or model.preferences.show_tooltips is not None:
            score += 0.2
        model.completeness = min(1.0, score)

    def _update_experience(self, model: UserModel) -> None:
        c = model.counters
        if c.total_events < 10:
            model.characteristics.experience_level = ExperienceLevel.NOVICE
            return
        error_rate = c.total_errors / c.total_events if c.total_events else 0.0
        success_rate = c.successful_actions / c.total_events if c.total_events else 0.0
        if error_rate < 0.1 and success_rate > 0.6 and c.help_requests < 3:
            model.characteristics.experience_level = ExperienceLevel.EXPERT
        elif error_rate < 0.25 and success_rate > 0.3:
            model.characteristics.experience_level = ExperienceLevel.INTERMEDIATE
        else:
            model.characteristics.experience_level = ExperienceLevel.NOVICE

    async def record_adaptation_result(self, raw: AdaptationResult) -> UserModel:
        result = validate_adaptation_result(raw)
        async with self._lock_for(result.user_id):
            await self.storage.save_adaptation_result(result)
            model = await self.get_or_create_model(result.user_id)
            model.adaptation_history = await self.storage.get_adaptation_history(
                result.user_id, self.config.HISTORY_IN_SNAPSHOT_LIMIT
            )
            model.updated_at = _now_iso()
            model.model_version += 1
            await self.storage.save_user_model(model)
            return model

    async def get_events_in_window(self, user_id: str) -> list[InteractionEvent]:
        model = await self.get_or_create_model(user_id)
        return await self.storage.get_events(
            user_id,
            from_ts=model.observation.window_start,
            to_ts=model.observation.window_end,
        )

    async def should_send_package(
        self, user_id: str, force: bool = False
    ) -> tuple[bool, str]:
        if force:
            return True, "force"
        model = await self.get_or_create_model(user_id)
        if (
            not model.cold_start_notified
            and model.counters.total_events >= self.config.COLD_START_THRESHOLD
        ):
            return True, "cold_start"
        if model.observation.recent_error_rate >= self.config.ERROR_RATE_THRESHOLD:
            return True, "threshold"
        events = await self.get_events_in_window(user_id)
        help_n = sum(1 for e in events if e.event_type == EventType.HELP_REQUEST)
        if help_n >= self.config.HELP_THRESHOLD:
            return True, "threshold"
        return False, ""

    async def mark_cold_start_notified(self, user_id: str) -> None:
        async with self._lock_for(user_id):
            model = await self.get_or_create_model(user_id)
            if not model.cold_start_notified:
                model.cold_start_notified = True
                model.model_version += 1
                model.updated_at = _now_iso()
                await self.storage.save_user_model(model)

    async def get_model(self, user_id: str) -> Optional[UserModel]:
        return await self.storage.get_user_model(user_id)

    async def get_all_events(self, user_id: str) -> list[InteractionEvent]:
        return await self.storage.get_events(user_id)
