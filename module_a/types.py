"""Типы данных модуля A (run-time адаптация A→B→C)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional
import json


def session_key(interface_id: str, session_id: Optional[str]) -> str:
    return json.dumps([interface_id, session_id or 'default'], ensure_ascii=False, separators=(',', ':'))


class ExperienceLevel(str, Enum):
    NOVICE = "novice"
    INTERMEDIATE = "intermediate"
    EXPERT = "expert"


class DensityPreference(str, Enum):
    COMPACT = "compact"
    COMFORTABLE = "comfortable"
    SPACIOUS = "spacious"


class AnimationLevel(str, Enum):
    NONE = "none"
    REDUCED = "reduced"
    FULL = "full"


class ThemePreference(str, Enum):
    LIGHT = "light"
    DARK = "dark"
    SYSTEM = "system"


class EventType(str, Enum):
    ERROR = "error"
    HELP_REQUEST = "help_request"
    BLOCK_OPEN = "block_open"
    BLOCK_CLOSE = "block_close"
    SUCCESSFUL_ACTION = "successful_action"
    FOCUS = "focus"
    BLUR = "blur"
    MANUAL_OVERRIDE = "manual_override"
    TIME_SPENT = "time_spent"
    HINT_HIDE = "hint_hide"


class PackageTrigger(str, Enum):
    THRESHOLD = "threshold"
    PERIODIC = "periodic"
    MANUAL_OVERRIDE = "manual_override"
    COLD_START = "cold_start"
    FORCE = "force"
    APPLICATION_RESULT = "application_result"


@dataclass
class DeviceContext:
    type: Optional[str] = None  # desktop | tablet | mobile
    screen_width: Optional[int] = None
    screen_height: Optional[int] = None


@dataclass
class InteractionEvent:
    id: str
    user_id: str
    interface_id: str
    event_type: EventType
    timestamp: str  # ISO-8601
    session_id: Optional[str] = None
    element_id: Optional[str] = None
    error_code: Optional[str] = None
    severity: Optional[str] = None
    message: Optional[str] = None
    help_type: Optional[str] = None
    duration_ms: Optional[int] = None
    action_id: Optional[str] = None
    property: Optional[str] = None
    old_value: Any = None
    new_value: Any = None
    device_context: Optional[DeviceContext] = None


@dataclass
class AdaptationResult:
    request_id: str
    interface_id: str
    user_id: str
    success: bool
    applied_at: str
    target_element_id: Optional[str] = None
    property: Optional[str] = None
    old_value: Any = None
    new_value: Any = None
    reason: Optional[str] = None
    error_message: Optional[str] = None
    status: Optional[str] = None
    event_id: Optional[str] = None
    source_event_ids: list[str] = field(default_factory=list)
    version_before: Optional[str] = None
    version_after: Optional[str] = None
    duration_ms: Optional[int] = None
    recovery_required: bool = False
    outcome_type: str = 'adaptation'
    session_id: Optional[str] = None


@dataclass
class UserCharacteristics:
    experience_level: ExperienceLevel = ExperienceLevel.NOVICE
    preferred_density: DensityPreference = DensityPreference.COMFORTABLE
    accessibility_needs: list[str] = field(default_factory=list)


@dataclass
class UserCounters:
    total_events: int = 0
    total_errors: int = 0
    errors_by_type: dict[str, int] = field(default_factory=dict)
    help_requests: int = 0
    successful_actions: int = 0
    block_opens: int = 0
    block_closes: int = 0
    manual_overrides: int = 0
    total_sessions: int = 0


@dataclass
class ObservationWindow:
    window_start: str = ""
    window_end: str = ""
    event_count: int = 0
    recent_error_rate: float = 0.0
    recent_help_rate: float = 0.0


@dataclass
class UserPreferences:
    show_tooltips: Optional[bool] = None
    animation_level: Optional[AnimationLevel] = None
    theme: Optional[ThemePreference] = None


@dataclass
class UserModel:
    user_id: str
    model_version: int = 1
    created_at: str = ""
    updated_at: str = ""
    is_cold_start: bool = True
    cold_start_notified: bool = False
    completeness: float = 0.0
    characteristics: UserCharacteristics = field(default_factory=UserCharacteristics)
    counters: UserCounters = field(default_factory=UserCounters)
    observation: ObservationWindow = field(default_factory=ObservationWindow)
    preferences: UserPreferences = field(default_factory=UserPreferences)
    adaptation_history: list[AdaptationResult] = field(default_factory=list)
    hint_hidden_sessions: list[str] = field(default_factory=list)
    manual_mode_sessions: list[str] = field(default_factory=list)


@dataclass
class PackageAtoB:
    user_id: str
    interface_id: str
    model_version: int
    model_snapshot: UserModel
    observation_window: dict[str, Any]
    interaction_events: list[InteractionEvent]
    manual_override: bool
    trigger: PackageTrigger
    timestamp: str


@dataclass
class ModuleAConfig:
    COLD_START_THRESHOLD: int = 20
    ERROR_RATE_THRESHOLD: float = 0.25
    HELP_THRESHOLD: int = 3
    OBSERVATION_EVENT_LIMIT: int = 50
    OBSERVATION_TIME_LIMIT_MS: int = 15 * 60 * 1000
    PERIODIC_SNAPSHOT_MS: int = 5 * 60 * 1000
    MAX_EVENTS_STORED: int = 500
    HISTORY_IN_SNAPSHOT_LIMIT: int = 10
    MAX_MESSAGE_LENGTH: int = 2000


DEFAULT_CONFIG = ModuleAConfig()
