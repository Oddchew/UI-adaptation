"""Валидация входных данных модуля A."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Union

from .types import (
    AdaptationResult,
    DEFAULT_CONFIG,
    EventType,
    InteractionEvent,
    ModuleAConfig,
)


class ValidationError(ValueError):
    def __init__(self, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


def _parse_iso(ts: str) -> datetime:
    # support trailing Z
    normalized = ts.replace("Z", "+00:00") if ts.endswith("Z") else ts
    return datetime.fromisoformat(normalized)


def validate_interaction_event(
    event: InteractionEvent,
    config: ModuleAConfig = DEFAULT_CONFIG,
) -> InteractionEvent:
    if not isinstance(event, InteractionEvent):
        raise ValidationError("event must be InteractionEvent")

    if not event.id or not str(event.id).strip():
        raise ValidationError("id is required", "id")
    if not event.user_id or not str(event.user_id).strip():
        raise ValidationError("user_id is required", "user_id")
    if not event.interface_id or not str(event.interface_id).strip():
        raise ValidationError("interface_id is required", "interface_id")

    if not isinstance(event.event_type, EventType):
        try:
            event.event_type = EventType(event.event_type)
        except (ValueError, TypeError) as e:
            raise ValidationError(
                f"event_type must be one of {[e.value for e in EventType]}",
                "event_type",
            ) from e

    if not event.timestamp or not str(event.timestamp).strip():
        raise ValidationError("timestamp must be a valid ISO-8601 string", "timestamp")

    try:
        ts = _parse_iso(event.timestamp)
    except Exception as e:
        raise ValidationError("timestamp must be a valid ISO-8601 string", "timestamp") from e

    now = datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    if ts - now > timedelta(minutes=5):
        raise ValidationError("timestamp is too far in the future", "timestamp")

    if event.message and len(event.message) > config.MAX_MESSAGE_LENGTH:
        event.message = event.message[: config.MAX_MESSAGE_LENGTH]

    event.id = str(event.id).strip()
    event.user_id = str(event.user_id).strip()
    event.interface_id = str(event.interface_id).strip()
    return event


def validate_adaptation_result(result: AdaptationResult) -> AdaptationResult:
    if not isinstance(result, AdaptationResult):
        raise ValidationError("adaptation result must be AdaptationResult")
    if not result.request_id or not str(result.request_id).strip():
        raise ValidationError("request_id is required", "request_id")
    if not result.user_id or not str(result.user_id).strip():
        raise ValidationError("user_id is required", "user_id")
    if not result.interface_id or not str(result.interface_id).strip():
        raise ValidationError("interface_id is required", "interface_id")
    if not isinstance(result.success, bool):
        raise ValidationError("success must be boolean", "success")
    if not result.applied_at:
        raise ValidationError("applied_at must be a valid ISO-8601 string", "applied_at")
    try:
        _parse_iso(result.applied_at)
    except Exception as e:
        raise ValidationError("applied_at must be a valid ISO-8601 string", "applied_at") from e
    return result
