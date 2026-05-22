from __future__ import annotations

import unittest

from fitmas.domain.memory.profile_summary import build_profile_summary


class ProfileSummaryTest(unittest.TestCase):
    def test_prefers_durable_profile_like_facts(self) -> None:
        summary = build_profile_summary(
            [
                {"category": "execution", "key": "done", "value": "Sortie faite hier", "ttl": "immediate", "confidence": 0.9},
                {"category": "objective", "key": "main", "value": "Preparer un marathon", "ttl": "permanent", "confidence": 0.9},
                {"category": "constraint", "key": "tuesday", "value": "Mardi soir fragile", "ttl": "long", "confidence": 0.8},
                {"category": "preference", "key": "tone", "value": "Coach direct", "ttl": "long", "confidence": 0.7},
            ]
        )

        self.assertIn("objectif: Preparer un marathon", summary)
        self.assertIn("contrainte: Mardi soir fragile", summary)
        self.assertIn("preference: Coach direct", summary)
        self.assertNotIn("Sortie faite hier", summary)


if __name__ == "__main__":
    unittest.main()
