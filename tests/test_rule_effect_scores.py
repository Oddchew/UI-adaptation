from __future__ import annotations

import unittest
from types import SimpleNamespace

from module_a.types import EventType
from module_b.rule_engine import evaluate_declarative_rules
from module_b.rule_schema import DEFAULT_RULES
from tests_helpers import make_package


class RuleEffectThresholdTests(unittest.TestCase):
    def _priority(self, samples: int, mean_score: float) -> int:
        package = make_package(errors=3)
        package.model_snapshot.rule_scores = {
            "R_hint_after_2_errors": {
                "mean_score": mean_score,
                "samples": samples,
            }
        }
        matches = evaluate_declarative_rules(package, DEFAULT_RULES)
        match = next(item for item in matches if item.rule_id == "R_hint_after_2_errors")
        return match.priority

    def test_negative_score_is_ignored_before_three_samples(self):
        self.assertEqual(self._priority(2, -0.5), 1)

    def test_negative_score_penalizes_rule_after_three_samples(self):
        self.assertEqual(self._priority(3, -0.5), 3)

    def test_positive_score_boosts_rule_after_three_samples(self):
        self.assertEqual(self._priority(3, 0.5), 0)


if __name__ == "__main__":
    unittest.main()
