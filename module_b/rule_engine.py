"""Интерпретатор декларативных правил по PackageAtoB."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from module_a.types import EventType, PackageAtoB, UserModel, session_key

from .rule_schema import AdaptationRule, CompareOp, TriggerKind


@dataclass
class RuleMatch:
    rule_id: str
    target_element_id: str
    property: str
    old_value: Any
    new_value: Any
    reason: str
    source_event_ids: list[str]
    priority: int
    constraints: list[str]


def _et_value(et: Any) -> str:
    if hasattr(et, "value"):
        return str(et.value)
    return str(et)


def _is_type(event_type: Any, expected: Any) -> bool:
    return _et_value(event_type) == _et_value(expected)


def _compare(value: float, threshold: float, op: CompareOp) -> bool:
    if op == CompareOp.GTE:
        return value >= threshold
    if op == CompareOp.LTE:
        return value <= threshold
    if op == CompareOp.EQ:
        return abs(value - threshold) < 1e-9
    return False


def _events(
    pkg: PackageAtoB,
    kind: Optional[str] = None,
    element_id: Optional[str] = None,
    action_id: Optional[str] = None,
):
    for e in pkg.interaction_events:
        if kind is not None and not _is_type(e.event_type, kind):
            continue
        if element_id is not None and (e.element_id or "") != element_id:
            continue
        if action_id is not None and e.action_id != action_id:
            continue
        yield e


def _count_event_type(pkg: PackageAtoB, et: Any, element_id: Optional[str] = None) -> int:
    n = sum(1 for _ in _events(pkg, _et_value(et), element_id))
    if n > 0:
        return n
    if pkg.interaction_events:
        return 0
    if element_id is not None:
        return 0
    c = pkg.model_snapshot.counters
    if _is_type(et, EventType.ERROR):
        return int(getattr(c, "total_errors", 0) or 0)
    if _is_type(et, EventType.HELP_REQUEST):
        return int(getattr(c, "help_requests", 0) or 0)
    if _is_type(et, EventType.SUCCESSFUL_ACTION):
        return int(getattr(c, "successful_actions", 0) or 0)
    return 0


def _has_success(pkg: PackageAtoB) -> bool:
    if pkg.interaction_events:
        return any(_is_type(e.event_type, EventType.SUCCESSFUL_ACTION) and e.action_id == 'check_run' for e in pkg.interaction_events)
    return int(getattr(pkg.model_snapshot.counters, "successful_actions", 0) or 0) > 0


def _hint_hidden(pkg: PackageAtoB) -> bool:
    snap = pkg.model_snapshot
    if getattr(snap.preferences, "show_tooltips", None) is False:
        return True
    if pkg.interaction_events:
        last = pkg.interaction_events[-1]
        hidden_key = session_key(pkg.interface_id, last.session_id)
        return hidden_key in (getattr(snap, "hint_hidden_sessions", None) or [])
    return False


def _metric(pkg: PackageAtoB, rule: AdaptationRule) -> tuple[float, list[str]]:
    tr = rule.trigger
    eid = tr.element_id

    if tr.kind == TriggerKind.ERROR_COUNT:
        evs = list(_events(pkg, EventType.ERROR.value, eid))
        ids = [e.id for e in evs]
        val = float(len(evs) if evs else _count_event_type(pkg, EventType.ERROR, eid))
        if not ids and val > 0:
            ids = [f"err_agg_{int(val)}"]
        return val, ids

    if tr.kind == TriggerKind.ERROR_RATE:
        rate = float(getattr(pkg.model_snapshot.observation, "recent_error_rate", 0.0) or 0.0)
        ids = [e.id for e in _events(pkg, EventType.ERROR.value, eid)]
        return rate, ids or [f"rate_{rate:.2f}"]

    if tr.kind == TriggerKind.HELP_COUNT:
        evs = list(_events(pkg, EventType.HELP_REQUEST.value, eid))
        ids = [e.id for e in evs]
        val = float(len(evs) if evs else _count_event_type(pkg, EventType.HELP_REQUEST, eid))
        if not ids and val > 0:
            ids = [f"help_agg_{int(val)}"]
        return val, ids

    if tr.kind == TriggerKind.SUCCESS_COUNT:
        evs = list(_events(pkg, EventType.SUCCESSFUL_ACTION.value, eid, tr.action_id))
        ids = [e.id for e in evs]
        if tr.action_id is not None:
            return float(len(evs)), ids
        val = float(len(evs) if evs else _count_event_type(pkg, EventType.SUCCESSFUL_ACTION, eid))
        return val, ids

    if tr.kind == TriggerKind.EVENT_COUNT:
        evs = list(_events(pkg, None, eid))
        n = len(evs) or int(getattr(pkg.model_snapshot.observation, "event_count", 0) or 0)
        return float(n), [e.id for e in evs]

    if tr.kind == TriggerKind.ALWAYS:
        return 1.0, []

    return 0.0, []


def rule_matches(pkg: PackageAtoB, rule: AdaptationRule) -> bool:
    if not rule.enabled:
        return False
    if rule.respect_hint_hidden and _hint_hidden(pkg):
        return False
    if rule.trigger.require_no_success and _has_success(pkg):
        return False
    value, _ = _metric(pkg, rule)
    if not _compare(value, float(rule.trigger.threshold), rule.trigger.op):
        return False
    if rule.action.target_element_id == "$output_target":
        if not rule.trigger.action_id:
            return False
        matching = [
            event for event in pkg.interaction_events
            if event.action_id == rule.trigger.action_id
            and _is_type(event.event_type, EventType.SUCCESSFUL_ACTION)
        ]
        if not matching or not isinstance(matching[-1].new_value, dict):
            return False
        targets = matching[-1].new_value.get("output_target_ids")
        if not isinstance(targets, list) or len(targets) != 1 or not isinstance(targets[0], str):
            return False
    return True


def evaluate_declarative_rules(
    pkg: PackageAtoB, rules: list[AdaptationRule]
) -> list[RuleMatch]:
    matches: list[RuleMatch] = []
    scores = getattr(pkg.model_snapshot, "rule_scores", None) or {}
    for rule in rules:
        if not rule_matches(pkg, rule):
            continue
        # Skip rules that historically harm the user (mean effect score < -0.05, ≥3 samples)
        score_entry = scores.get(rule.id)
        if isinstance(score_entry, dict):
            mean = score_entry.get("mean_score")
            samples = int(score_entry.get("samples", 0) or 0)
        else:
            mean = score_entry
            samples = 0
        value, src_ids = _metric(pkg, rule)
        target_element_id = rule.action.target_element_id
        if target_element_id == "$output_target":
            matching = [
                event for event in pkg.interaction_events
                if event.action_id == rule.trigger.action_id
                and _is_type(event.event_type, EventType.SUCCESSFUL_ACTION)
            ]
            targets = matching[-1].new_value.get("output_target_ids", [])
            target_element_id = targets[0]
        # Adjust priority: lower priority number = preferred.
        # Positive effectiveness lowers effective priority (boosts rule).
        adj = 0
        if mean is not None and samples >= 3:
            if float(mean) > 0.05:
                adj = -1
            elif float(mean) < -0.05:
                adj = 2
        matches.append(
            RuleMatch(
                rule_id=rule.id,
                target_element_id=target_element_id,
                property=rule.action.property,
                old_value=rule.action.old_value,
                new_value=rule.action.new_value,
                reason=f"{rule.trigger.kind.value}={value} (threshold {rule.trigger.op.value} {rule.trigger.threshold})",
                source_event_ids=src_ids,
                priority=rule.priority + adj,
                constraints=list(rule.constraints),
            )
        )
    return matches


def choose_minimal_intervention(matches: list[RuleMatch]) -> Optional[RuleMatch]:
    if not matches:
        return None
    return min(matches, key=lambda m: (m.priority, m.rule_id))
