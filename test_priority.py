"""
Simple tests for compute_priority, the system prompt and the profile file (no API calls).

Run with:
    python test_priority.py
"""

import copy
import hashlib
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta

from prioritizer import (FILL_IN, PROFILE_FIELDS, SYSTEM_PROMPT, TIMEZONE, ProfileError,
                         build_system_prompt, compute_priority, load_profile, validate_result)

REF = datetime(2026, 11, 16, 9, 0, tzinfo=TIMEZONE)

# SHA-256 of SYSTEM_PROMPT as it was BEFORE personalisation was added (2094 characters).
# If this test fails, the prompt for runs without --profile has changed.
ORIGINAL_PROMPT_SHA256 = "7a1a71fe2264a2625f27ce6c903f500b81ef3b2cd191a3c839bdf26389956921"

EXAMPLE_PROFILE = {
    "student_type": "exchange",
    "study_period": "Aug–Dec 2026",
    "programme": "Business",
    "enrolled_courses": ["GE2340", "CB4601"],
    "residence": "Hall 17",
    "fees_paid_to_cityu": "no",
    "visa_or_entry_permit": "student visa valid until end of study period",
    "work_or_internship_allowed_in_hk": "no",
    "interested_in": ["sports", "hall events"],
}


def deadline_in(**kwargs):
    """Deadline string (YYYY-MM-DD HH:MM) at REF + the given offset."""
    return (REF + timedelta(**kwargs)).strftime("%Y-%m-%d %H:%M")


# importance -> expected final priority at 47 h, 49 h, 6 days, 8 days
EXPECTED = {
    "Low":    ["Medium", "Low",    "Low",    "Low"],
    "Medium": ["High",   "Medium", "Medium", "Medium"],
    "High":   ["Urgent", "High",   "High",   "High"],
}
OFFSETS = [{"hours": 47}, {"hours": 49}, {"days": 6}, {"days": 8}]


class TestComputePriority(unittest.TestCase):

    def test_no_deadline_returns_importance(self):
        for importance in EXPECTED:
            with self.subTest(importance=importance):
                self.assertEqual(compute_priority(importance, None, REF), (importance, None))

    def test_passed_deadline_is_expired(self):
        for importance in EXPECTED:
            with self.subTest(importance=importance):
                priority, hours_left = compute_priority(importance, deadline_in(hours=-1), REF)
                self.assertEqual(priority, "Expired")
                self.assertEqual(hours_left, -1.0)

    def test_matrix(self):
        for importance, expected_row in EXPECTED.items():
            for offset, expected in zip(OFFSETS, expected_row):
                with self.subTest(importance=importance, offset=offset):
                    priority, _ = compute_priority(importance, deadline_in(**offset), REF)
                    self.assertEqual(priority, expected)

    def test_boundaries_are_inclusive(self):
        self.assertEqual(compute_priority("High", deadline_in(hours=48), REF), ("Urgent", 48.0))
        self.assertEqual(compute_priority("High", deadline_in(days=7), REF), ("High", 168.0))

    def test_hours_left(self):
        self.assertEqual(compute_priority("Medium", deadline_in(hours=47), REF), ("High", 47.0))

    def test_invalid_importance_passes_through(self):
        self.assertEqual(compute_priority("INVALID(Huge)", deadline_in(hours=1), REF), ("INVALID(Huge)", None))


class TestSystemPrompt(unittest.TestCase):

    def test_prompt_without_profile_is_unchanged(self):
        for prompt in (build_system_prompt(None), build_system_prompt({}), SYSTEM_PROMPT):
            self.assertEqual(hashlib.sha256(prompt.encode("utf-8")).hexdigest(), ORIGINAL_PROMPT_SHA256)
        self.assertIs(build_system_prompt(None), SYSTEM_PROMPT)

    def test_profile_only_appends_one_block(self):
        prompt = build_system_prompt(EXAMPLE_PROFILE)
        self.assertTrue(prompt.startswith(SYSTEM_PROMPT))
        block = prompt[len(SYSTEM_PROMPT):]
        self.assertIn("Student profile (provided by the student at sign-up):", block)
        self.assertIn("- enrolled_courses: GE2340, CB4601", block)
        self.assertIn("- fees_paid_to_cityu: no", block)
        self.assertIn('"relevant_to_user"', block)
        self.assertIn("If you are unsure, do NOT lower the importance", block)


class TestProfileFile(unittest.TestCase):

    def write(self, data):
        f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(data, f)
        f.close()
        self.addCleanup(os.remove, f.name)
        return f.name

    def test_empty_template_is_rejected(self):
        # Built here instead of reading user_profile.json, which the student fills in
        template = {k: [FILL_IN] if k in ("enrolled_courses", "interested_in") else FILL_IN
                    for k in PROFILE_FIELDS}
        with self.assertRaises(ProfileError) as ctx:
            load_profile(self.write(template))
        self.assertIn(FILL_IN, str(ctx.exception))

    def test_one_unfilled_field_is_rejected(self):
        for field in PROFILE_FIELDS:
            data = copy.deepcopy(EXAMPLE_PROFILE)
            data[field] = [FILL_IN] if isinstance(data[field], list) else FILL_IN
            with self.subTest(field=field), self.assertRaises(ProfileError) as ctx:
                load_profile(self.write(data))
            self.assertIn(field, str(ctx.exception))

    def test_missing_field_is_rejected(self):
        data = copy.deepcopy(EXAMPLE_PROFILE)
        del data["residence"]
        with self.assertRaises(ProfileError):
            load_profile(self.write(data))

    def test_filled_profile_is_accepted(self):
        self.assertEqual(load_profile(self.write(EXAMPLE_PROFILE)), EXAMPLE_PROFILE)


class TestValidateResult(unittest.TestCase):

    BASE = {"importance": "Low", "llm_priority": "Low"}

    def test_without_profile_relevance_is_null(self):
        r = validate_result(dict(self.BASE, relevant_to_user=False, relevance_reason="x"), profile_used=False)
        self.assertIsNone(r["relevant_to_user"])
        self.assertIsNone(r["relevance_reason"])

    def test_with_profile_valid_values_are_kept(self):
        r = validate_result(dict(self.BASE, relevant_to_user=False, relevance_reason="Not your course"), profile_used=True)
        self.assertIs(r["relevant_to_user"], False)
        self.assertEqual(r["relevance_reason"], "Not your course")

    def test_with_profile_invalid_value_is_marked(self):
        r = validate_result(dict(self.BASE, relevant_to_user="maybe"), profile_used=True)
        self.assertEqual(r["relevant_to_user"], "INVALID(maybe)")
        self.assertIsNone(r["relevance_reason"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
