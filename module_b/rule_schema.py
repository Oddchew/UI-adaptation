"""Декларативные правила адаптации (без кода для автора UI).

Формат рассчитан на:
  - сохранение из ostis-ui-editor (JSON / позже SC);
  - загрузку Модулем B в рантайме;
  - совместимость с PackageAtoB и CommandBtoC.

Автор интерфейса задаёт: когда (trigger) → что менять (action).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Optional


class TriggerKind(str, Enum):
    """Условие срабатывания (то, что A уже считает в модели/событиях)."""

    ERROR_COUNT = "error_count"  # ≥ threshold ошибок в окне
    ERROR_RATE = "error_rate"  # recent_error_rate ≥ threshold
    HELP_COUNT = "help_count"  # ≥ threshold help_request
    SUCCESS_COUNT = "success_count"
    EVENT_COUNT = "event_count"  # любых событий в окне
    ALWAYS = "always"  # только для отладки; в проде не использовать


class CompareOp(str, Enum):
    GTE = "gte"  # ≥
    LTE = "lte"  # ≤
    EQ = "eq"


@dataclass
class RuleTrigger:
    kind: TriggerKind
    threshold: float = 1.0
    op: CompareOp = CompareOp.GTE
    # опционально: только события с этим element_id
    element_id: Optional[str] = None
    # для help_count: требовать отсутствие successful_action
    require_no_success: bool = False


@dataclass
class RuleAction:
    target_element_id: str
    property: str
    new_value: Any
    old_value: Any = None


@dataclass
class AdaptationRule:
    """Одно правило: id + trigger + action + служебное."""

    id: str
    trigger: RuleTrigger
    action: RuleAction
    priority: int = 100  # меньше = важнее (минимальное вмешательство)
    enabled: bool = True
    description: str = ""
    # не применять, если пользователь скрыл подсказки (для hint-правил)
    respect_hint_hidden: bool = False
    constraints: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["trigger"]["kind"] = self.trigger.kind.value
        d["trigger"]["op"] = self.trigger.op.value
        return d

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "AdaptationRule":
        tr = data["trigger"]
        ac = data["action"]
        return AdaptationRule(
            id=str(data["id"]),
            trigger=RuleTrigger(
                kind=TriggerKind(tr["kind"]),
                threshold=float(tr.get("threshold", 1)),
                op=CompareOp(tr.get("op", "gte")),
                element_id=tr.get("element_id"),
                require_no_success=bool(tr.get("require_no_success", False)),
            ),
            action=RuleAction(
                target_element_id=str(ac["target_element_id"]),
                property=str(ac["property"]),
                new_value=ac.get("new_value"),
                old_value=ac.get("old_value"),
            ),
            priority=int(data.get("priority", 100)),
            enabled=bool(data.get("enabled", True)),
            description=str(data.get("description", "")),
            respect_hint_hidden=bool(data.get("respect_hint_hidden", False)),
            constraints=list(data.get("constraints") or []),
        )


# --- Встроенный набор = бывшие R1–R3 (можно заменить файлом из редактора) ---

DEFAULT_RULES: list[AdaptationRule] = [
    AdaptationRule(
        id="R_hint_after_2_errors",
        description="Показать панель подсказок после повторных ошибок",
        priority=1,
        respect_hint_hidden=True,
        trigger=RuleTrigger(kind=TriggerKind.ERROR_COUNT, threshold=2, op=CompareOp.GTE),
        action=RuleAction(
            target_element_id="hints_panel",
            property="visible",
            old_value=False,
            new_value=True,
        ),
        constraints=[
            "не изменять code_editor.content",
            "не изменять этап задания",
        ],
    ),
    AdaptationRule(
        id="R_hint_on_error_rate",
        description="Показать подсказки при высоком error_rate",
        priority=1,
        respect_hint_hidden=True,
        trigger=RuleTrigger(kind=TriggerKind.ERROR_RATE, threshold=0.25, op=CompareOp.GTE),
        action=RuleAction(
            target_element_id="hints_panel",
            property="visible",
            old_value=False,
            new_value=True,
        ),
    ),
    AdaptationRule(
        id="R_enlarge_font_on_help",
        description="Увеличить шрифт после нескольких запросов помощи",
        priority=2,
        trigger=RuleTrigger(kind=TriggerKind.HELP_COUNT, threshold=3, op=CompareOp.GTE),
        action=RuleAction(
            target_element_id="main_content",
            property="fontSize",
            old_value=14,
            new_value=16,
        ),
    ),
    AdaptationRule(
        id="R_collapse_history_on_help_without_check",
        description="Свернуть history, если много help и нет успешной проверки",
        priority=3,
        trigger=RuleTrigger(
            kind=TriggerKind.HELP_COUNT,
            threshold=3,
            op=CompareOp.GTE,
            require_no_success=True,
        ),
        action=RuleAction(
            target_element_id="history_panel",
            property="collapsed",
            old_value=False,
            new_value=True,
        ),
    ),
]


def rules_to_jsonable(rules: list[AdaptationRule]) -> list[dict[str, Any]]:
    return [r.to_dict() for r in rules]


def rules_from_jsonable(items: list[dict[str, Any]]) -> list[AdaptationRule]:
    return [AdaptationRule.from_dict(x) for x in items]
