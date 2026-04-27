from __future__ import annotations

import unittest

from fitmas.session_templates import list_session_templates, render_session_description, select_session_template


class SessionTemplatesTest(unittest.TestCase):
    def test_template_library_covers_expected_v1_counts(self) -> None:
        templates = list_session_templates()
        counts: dict[str, int] = {}
        for template in templates:
            counts[template.sport_type] = counts.get(template.sport_type, 0) + 1

        self.assertEqual(counts["running"], 6)
        self.assertEqual(counts["cycling"], 4)
        self.assertEqual(counts["swimming"], 5)
        self.assertEqual(counts["strength"], 3)
        self.assertEqual(counts["climbing"], 2)

    def test_rendered_template_description_is_actionable(self) -> None:
        template = select_session_template(sport_type="running", session_type="intervals")
        description = render_session_description(template, duration_min=55)

        self.assertIn("echauffement", description.lower())
        self.assertIn("retour", description.lower())
        self.assertIn("\n", description)

    def test_select_template_normalizes_composite_sport_type(self) -> None:
        template = select_session_template(sport_type="strength/general", session_type="training")

        self.assertEqual(template.sport_type, "strength")
        self.assertEqual(template.session_type, "general")


if __name__ == "__main__":
    unittest.main()
