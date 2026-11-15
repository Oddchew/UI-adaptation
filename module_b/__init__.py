"""Модуль B — принятие решения об адаптации (run-time A→B→C)."""

from .module_b import ModuleB
from .models import (
    DEFAULT_B_CONFIG,
    CommandBtoC,
    DecisionResult,
    DecisionStatus,
    ModuleBConfig,
    RejectReason,
)
from .rule_schema import (
    DEFAULT_RULES,
    AdaptationRule,
    RuleAction,
    RuleTrigger,
    TriggerKind,
    CompareOp,
    rules_from_jsonable,
    rules_to_jsonable,
)

__all__ = [
    "ModuleB",
    "DEFAULT_B_CONFIG",
    "CommandBtoC",
    "DecisionResult",
    "DecisionStatus",
    "ModuleBConfig",
    "RejectReason",
    "DEFAULT_RULES",
    "AdaptationRule",
    "RuleAction",
    "RuleTrigger",
    "TriggerKind",
    "CompareOp",
    "rules_from_jsonable",
    "rules_to_jsonable",
]

__version__ = "0.2.0"
