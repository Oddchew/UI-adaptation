"""Обратная совместимость: старый evaluate_rules поверх декларативного движка."""

from __future__ import annotations

from module_a.types import PackageAtoB

from .models import ModuleBConfig
from .rule_engine import RuleMatch, choose_minimal_intervention, evaluate_declarative_rules
from .rule_schema import DEFAULT_RULES


def evaluate_rules(pkg: PackageAtoB, cfg: ModuleBConfig) -> list[RuleMatch]:
    _ = cfg
    return evaluate_declarative_rules(pkg, DEFAULT_RULES)


def is_forbidden_target(target_element_id: str, cfg: ModuleBConfig) -> bool:
    t = (target_element_id or "").lower()
    for forbidden in cfg.FORBIDDEN_TARGETS:
        fl = forbidden.lower()
        if fl in t or t in fl:
            return True
    return False


__all__ = [
    "RuleMatch",
    "evaluate_rules",
    "choose_minimal_intervention",
    "is_forbidden_target",
]
