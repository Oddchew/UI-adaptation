"""Evaluation of adaptation effect after C applies a change.

After an adaptation is applied, subsequent events in a follow-up window
are compared to the pre-adaptation baseline (error_rate, help_rate, success rate).
The result is stored on UserModel and can be used by Module B to adjust rule priority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from .types import AdaptationResult, InteractionEvent, EventType, UserModel


def _parse_ts(ts: str) -> Optional[datetime]:
    if not ts:
        return None
    try:
        parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


@dataclass
class EffectSample:
    request_id: str
    rule_id: Optional[str]
    interface_id: str
    user_id: str
    applied_at: str
    # baseline (from model snapshot at apply time)
    baseline_error_rate: float = 0.0
    baseline_help_rate: float = 0.0
    baseline_success_count: int = 0
    baseline_success_rate: float = 0.0
    # after follow-up window
    followup_error_rate: Optional[float] = None
    followup_help_rate: Optional[float] = None
    followup_success_count: Optional[int] = None
    score: Optional[float] = None  # positive = improvement
    status: str = "pending"  # pending | scored | expired
    session_id: Optional[str] = None


@dataclass
class RuleEffectiveness:
    rule_id: str
    samples: int = 0
    mean_score: float = 0.0
    positive: int = 0
    negative: int = 0
    last_score: Optional[float] = None


@dataclass
class EffectTrackerConfig:
    followup_window_ms: int = 5 * 60 * 1000  # 5 minutes
    min_events_for_score: int = 3
    expire_after_ms: int = 30 * 60 * 1000
    # weights for composite score
    w_error: float = 0.5
    w_help: float = 0.3
    w_success: float = 0.2


class EffectTracker:
    """Tracks open adaptations and scores them when enough post-events arrive."""

    def __init__(self, config: Optional[EffectTrackerConfig] = None) -> None:
        self.config = config or EffectTrackerConfig()
        self._pending: dict[str, EffectSample] = {}
        self._scored: list[EffectSample] = []
        self._rules: dict[tuple[str, str], RuleEffectiveness] = {}
        self._claimed_event_ids: dict[str, datetime] = {}

    def on_applied(
        self,
        result: AdaptationResult,
        *,
        rule_id: Optional[str],
        baseline_error_rate: float,
        baseline_help_rate: float,
        baseline_success_count: int = 0,
        baseline_success_rate: float = 0.0,
    ) -> None:
        if not result.success or result.request_id in self._pending:
            return
        sample = EffectSample(
            request_id=result.request_id,
            rule_id=rule_id or result.reason,
            interface_id=result.interface_id,
            user_id=result.user_id,
            applied_at=result.applied_at,
            baseline_error_rate=baseline_error_rate,
            baseline_help_rate=baseline_help_rate,
            baseline_success_count=baseline_success_count,
            baseline_success_rate=baseline_success_rate,
            session_id=result.session_id,
        )
        self._pending[result.request_id] = sample

    def on_events(
        self,
        user_id: str,
        events: list[InteractionEvent],
        *,
        now: Optional[datetime] = None,
    ) -> list[EffectSample]:
        """Try to score pending samples for this user using recent events."""
        now = now or datetime.now(timezone.utc)
        scored: list[EffectSample] = []
        cfg = self.config
        to_drop: list[str] = []

        for rid, sample in list(self._pending.items()):
            if sample.user_id != user_id:
                continue
            applied = _parse_ts(sample.applied_at)
            if not applied:
                to_drop.append(rid)
                continue
            age_ms = (now - applied).total_seconds() * 1000
            if age_ms > cfg.expire_after_ms:
                sample.status = "expired"
                to_drop.append(rid)
                continue
            if age_ms < cfg.followup_window_ms:
                continue

            window_end = applied + timedelta(milliseconds=cfg.followup_window_ms)
            post = []
            seen_in_sample: set[str] = set()
            for event in events:
                if event.id in self._claimed_event_ids or event.id in seen_in_sample:
                    continue
                if event.user_id != sample.user_id or event.interface_id != sample.interface_id:
                    continue
                if event.session_id != sample.session_id:
                    continue
                event_time = _parse_ts(event.timestamp)
                if event_time is None:
                    continue
                if applied < event_time <= window_end:
                    post.append(event)
                    seen_in_sample.add(event.id)
            if len(post) < cfg.min_events_for_score:
                if age_ms > cfg.expire_after_ms:
                    sample.status = "expired"
                    to_drop.append(rid)
                continue

            n = len(post)
            errors = sum(1 for e in post if e.event_type == EventType.ERROR)
            helps = sum(1 for e in post if e.event_type == EventType.HELP_REQUEST)
            successes = sum(
                1 for e in post if e.event_type == EventType.SUCCESSFUL_ACTION
            )
            err_rate = errors / n
            help_rate = helps / n
            sample.followup_error_rate = err_rate
            sample.followup_help_rate = help_rate
            sample.followup_success_count = successes

            # Positive score = rates went down / successes went up
            d_err = sample.baseline_error_rate - err_rate
            d_help = sample.baseline_help_rate - help_rate
            d_suc = (successes / n) - sample.baseline_success_rate
            score = cfg.w_error * d_err + cfg.w_help * d_help + cfg.w_success * d_suc
            sample.score = round(score, 4)
            sample.status = "scored"
            self._update_rule(sample)
            for event in post:
                event_time = _parse_ts(event.timestamp)
                if event_time is not None:
                    self._claimed_event_ids[event.id] = event_time
            scored.append(sample)
            self._scored.append(sample)
            to_drop.append(rid)

        for rid in to_drop:
            self._pending.pop(rid, None)
        if len(self._scored) > 200:
            self._scored = self._scored[-200:]
        claim_expiry = timedelta(milliseconds=cfg.expire_after_ms)
        self._claimed_event_ids = {
            event_id: event_time
            for event_id, event_time in self._claimed_event_ids.items()
            if now <= event_time + claim_expiry
        }
        return scored

    def _update_rule(self, sample: EffectSample) -> None:
        if not sample.rule_id or sample.score is None:
            return
        key = (sample.user_id, sample.rule_id)
        re = self._rules.get(key)
        if re is None:
            re = RuleEffectiveness(rule_id=sample.rule_id)
            self._rules[key] = re
        re.samples += 1
        re.last_score = sample.score
        if sample.score > 0.02:
            re.positive += 1
        elif sample.score < -0.02:
            re.negative += 1
        # running mean
        re.mean_score = (
            re.mean_score * (re.samples - 1) + sample.score
        ) / re.samples

    def rule_effectiveness(self, rule_id: str, user_id: Optional[str] = None) -> Optional[RuleEffectiveness]:
        if user_id is not None:
            return self._rules.get((user_id, rule_id))
        matches = [value for (owner, rid), value in self._rules.items() if rid == rule_id]
        return matches[0] if len(matches) == 1 else None

    def all_rule_scores(self, user_id: Optional[str] = None) -> dict[str, dict[str, float | int]]:
        return {
            rid: {"mean_score": value.mean_score, "samples": value.samples}
            for (owner, rid), value in self._rules.items()
            if value.samples > 0 and (user_id is None or owner == user_id)
        }

    def pending_count(self) -> int:
        return len(self._pending)

    def snapshot_for_model(self, user_id: Optional[str] = None) -> dict[str, Any]:
        return {
            "pending": sum(1 for sample in self._pending.values()
                           if user_id is None or sample.user_id == user_id),
            "scored": sum(1 for sample in self._scored
                          if user_id is None or sample.user_id == user_id),
            "rules": {
                rid: {
                    "samples": value.samples,
                    "mean_score": round(value.mean_score, 4),
                    "positive": value.positive,
                    "negative": value.negative,
                }
                for (owner, rid), value in self._rules.items()
                if user_id is None or owner == user_id
            },
        }
