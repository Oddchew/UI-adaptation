"""Типы данных модуля B (run-time адаптация A→B→C).

Контракты согласованы с module_a.types (PackageAtoB) и
проектированием Модуля B (Король Г. А.).
CommandBtoC — общий контракт B→C (используется и MockModuleC).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class DecisionStatus(str, Enum):
    COMMAND = "command"
    REJECTED = "rejected"


class RejectReason(str, Enum):
    MANUAL_OVERRIDE = "manual_override"
    INSUFFICIENT_DATA = "insufficient_data"
    COLD_START = "cold_start"
    NO_RULE_MATCHED = "no_rule_matched"
    CONSTRAINT_VIOLATION = "constraint_violation"
    ALREADY_APPLIED = "already_applied"
    HINT_HIDDEN = "hint_hidden"


@dataclass
class CommandBtoC:
    """Команда B → C (формализованное изменение UI).

    Совместима с заглушкой module_a.mocks.module_b.CommandBtoC
    (+ дополнительные поля source_event_ids, constraints по ПЗ).
    """

    request_id: str
    interface_id: str
    user_id: str
    base_version_id: str
    target_element_id: str
    property: str
    old_value: Any
    new_value: Any
    reason: str
    rule_id: str
    source_event_ids: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    source_package_trigger: Optional[str] = None
    created_at: str = ""


@dataclass
class DecisionResult:
    status: DecisionStatus
    command: Optional[CommandBtoC] = None
    reject_reason: Optional[RejectReason] = None
    reject_message: Optional[str] = None


@dataclass
class ModuleBConfig:
    """Пороги и параметры Модуля B (ПЗ Короля + контракты A)."""

    MIN_EVENTS_IN_WINDOW: int = 3

    # R1: показ hints / help panel после ошибок
    ERROR_COUNT_FOR_HINTS: int = 2
    ERROR_RATE_FOR_HINTS: float = 0.25  # согласовано с порогом mock/A
    HINTS_PANEL_ID: str = "hints_panel"
    HINTS_PROPERTY: str = "visible"
    HINTS_OLD: Any = False
    HINTS_NEW: Any = True
    RULE_HINT_AFTER_ERRORS: str = "R_hint_after_2_errors"

    # R2: увеличение шрифта после help
    HELP_COUNT_FOR_FONT: int = 3
    FONT_TARGET_ID: str = "main_content"
    FONT_PROPERTY: str = "fontSize"
    FONT_OLD: Any = 14
    FONT_NEW: Any = 16
    RULE_FONT_ON_HELP: str = "R_enlarge_font_on_help"

    # R3: сворачивание редко используемого блока
    COLLAPSE_TARGET_ID: str = "history_panel"
    COLLAPSE_PROPERTY: str = "collapsed"
    COLLAPSE_OLD: Any = False
    COLLAPSE_NEW: Any = True
    RULE_COLLAPSE_HISTORY: str = "R_collapse_history_on_help_without_check"
    HELP_FOR_COLLAPSE: int = 3

    FORBIDDEN_TARGETS: tuple[str, ...] = (
        "code_editor",
        "code_editor.content",
        "task_stage",
        "results_criteria",
    )

    MAX_APPLY_MS: int = 2000
    ANTI_FLICKER: bool = True


DEFAULT_B_CONFIG = ModuleBConfig()
