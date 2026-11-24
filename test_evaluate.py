"""
Tests for evaluate.py with a small hard-coded answer key where the right numbers are known.

Run with:
    python test_evaluate.py
"""

import unittest

from evaluate import cohen_kappa, compare_deadline, direction, evaluate_run, normalize_priority

FASIT = [
    # id, origin, include, key importance, key priority, key deadline
    {"id": "A", "origin": "real", "include_in_eval": "yes", "label_importance": "High",
     "label_priority_final": "High", "label_priority_AI": "High", "label_deadline": "2026-11-20 23:59"},
    {"id": "B", "origin": "real", "include_in_eval": "yes", "label_importance": "High",
     "label_priority_final": "High", "label_priority_AI": "High", "label_deadline": "2026-11-21 17:00"},
    {"id": "C", "origin": "real", "include_in_eval": "yes", "label_importance": "Low",
     "label_priority_final": "Low", "label_priority_AI": "Medium", "label_deadline": ""},
    {"id": "D", "origin": "synthetic", "include_in_eval": "yes", "label_importance": "Low",
     "label_priority_final": "Low", "label_priority_AI": "Low", "label_deadline": ""},
    {"id": "E", "origin": "synthetic", "include_in_eval": "yes", "label_importance": "Medium",
     "label_priority_final": "Medium", "label_priority_AI": "Medium", "label_deadline": "2026-12-01 12:00"},
    {"id": "F", "origin": "real", "include_in_eval": "no", "label_importance": "High",
     "label_priority_final": "High", "label_priority_AI": "High", "label_deadline": ""},
    {"id": "G", "origin": "real", "include_in_eval": "yes", "label_importance": "Low",
     "label_priority_final": "Low", "label_priority_AI": "Low", "label_deadline": ""},   # not in results
]

RESULTS = [
    # A: Urgent vs key High -> right when collapsing, wrong when strict; deadline exact
    {"id": "A", "final_priority": "Urgent", "ai_llm_priority": "High", "ai_importance": "High",
     "ai_deadline": "2026-11-20 23:59", "seconds": "1.0", "input_tokens": "1000", "output_tokens": "100"},
    # B: Medium vs High -> missed High (under); deadline same date, other time
    {"id": "B", "final_priority": "Medium", "ai_llm_priority": "High", "ai_importance": "Medium",
     "ai_deadline": "2026-11-21 23:59", "seconds": "2.0", "input_tokens": "1000", "output_tokens": "100"},
    # C: High vs Low -> false alarm (over); extra deadline
    {"id": "C", "final_priority": "High", "ai_llm_priority": "Low", "ai_importance": "Low",
     "ai_deadline": "2026-11-30 23:59", "seconds": "3.0", "input_tokens": "1000", "output_tokens": "100"},
    # D: Low vs Low -> right, noise filtered; both deadlines empty
    {"id": "D", "final_priority": "Low", "ai_llm_priority": "Low", "ai_importance": "Low",
     "ai_deadline": "", "seconds": "4.0", "input_tokens": "1000", "output_tokens": "100"},
    # E: Expired vs Medium -> wrong (other); missed deadline
    {"id": "E", "final_priority": "Expired", "ai_llm_priority": "Medium", "ai_importance": "Medium",
     "ai_deadline": "", "seconds": "5.0", "input_tokens": "1000", "output_tokens": "100"},
    # F is excluded by include_in_eval = no; X is not in the answer key
    {"id": "F", "final_priority": "High", "ai_llm_priority": "High", "ai_importance": "High",
     "ai_deadline": "", "seconds": "1", "input_tokens": "1", "output_tokens": "1"},
    {"id": "X", "final_priority": "High", "ai_llm_priority": "High", "ai_importance": "High",
     "ai_deadline": "", "seconds": "1", "input_tokens": "1", "output_tokens": "1"},
]


class TestHelpers(unittest.TestCase):

    def test_urgent_to_high(self):
        self.assertEqual(normalize_priority("Urgent"), "High")
        self.assertEqual(normalize_priority("Urgent", collapse_urgent=False), "Urgent")
        self.assertEqual(normalize_priority(" high "), "High")
        self.assertEqual(normalize_priority("Expired"), "Expired")

    def test_compare_deadline(self):
        self.assertEqual(compare_deadline("2026-11-20 23:59", "2026-11-20 23:59"), "exact")
        self.assertEqual(compare_deadline("2026-11-20 17:00", "2026-11-20 23:59"), "same_date")
        self.assertEqual(compare_deadline("2026-11-21 23:59", "2026-11-20 23:59"), "wrong_date")
        self.assertEqual(compare_deadline("", ""), "both_empty")
        self.assertEqual(compare_deadline("", "2026-11-20 23:59"), "missed")
        self.assertEqual(compare_deadline("2026-11-20 23:59", " "), "extra")

    def test_direction(self):
        self.assertEqual(direction("High", "Low"), "over")
        self.assertEqual(direction("Low", "Medium"), "under")
        self.assertEqual(direction("Expired", "Medium"), "other")

    def test_kappa(self):
        self.assertAlmostEqual(cohen_kappa(["a", "b", "a", "b"], ["a", "b", "a", "b"]), 1.0)
        self.assertAlmostEqual(cohen_kappa(["a", "a", "b", "b"], ["a", "b", "a", "b"]), 0.0)


class TestEvaluateRun(unittest.TestCase):

    def setUp(self):
        self.by_subset, self.pairs, self.skipped = evaluate_run(FASIT, RESULTS, collapse_urgent=True)
        self.m = self.by_subset["all"]

    def test_skipped(self):
        self.assertEqual(len(self.pairs), 5)
        reasons = dict(self.skipped)
        self.assertIn("include_in_eval", reasons["F"])
        self.assertEqual(reasons["G"], "not in results file")
        self.assertEqual(reasons["X"], "in results file but not in fasit")

    def test_accuracy(self):
        self.assertEqual(self.m["final_correct"], 2)          # A (Urgent=High), D
        self.assertEqual(self.m["final_correct_strict"], 1)   # only D
        self.assertEqual(self.m["llm_correct"], 5)            # all five: A, B, C, D, E
        self.assertEqual(self.m["importance_correct"], 4)     # A, C, D, E

    def test_strict_mode_main_numbers(self):
        strict = evaluate_run(FASIT, RESULTS, collapse_urgent=False)[0]["all"]
        self.assertEqual(strict["final_correct"], 1)
        self.assertEqual(strict["over"], 2)                   # A (Urgent > High) and C

    def test_high_recall_precision(self):
        self.assertEqual((self.m["high_found"], self.m["high_in_key"]), (1, 2))
        self.assertEqual((self.m["high_flagged_correct"], self.m["high_flagged"]), (1, 2))
        self.assertEqual(self.m["high_missed_ids"], ["B"])
        self.assertEqual(self.m["false_alarm_ids"], ["C"])

    def test_noise_and_direction(self):
        self.assertEqual((self.m["low_kept_low"], self.m["low_in_key"]), (1, 2))
        self.assertEqual((self.m["over"], self.m["under"], self.m["other_errors"]), (1, 1, 1))

    def test_deadlines(self):
        m = self.m
        self.assertEqual((m["deadline_exact"], m["deadline_same_date"], m["deadline_both_empty"],
                          m["deadline_missed"], m["deadline_extra"], m["deadline_wrong_date"]), (1, 1, 1, 1, 1, 0))

    def test_subsets_and_cost(self):
        self.assertEqual(self.by_subset["real"]["n"], 3)
        self.assertEqual(self.by_subset["synthetic"]["n"], 2)
        self.assertEqual(self.m["input_tokens"], 5000)
        self.assertAlmostEqual(self.m["cost_usd"], 5000 / 1e6 * 0.30 + 500 / 1e6 * 1.20)
        self.assertAlmostEqual(self.m["avg_seconds"], 3.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
