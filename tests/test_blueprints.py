from __future__ import annotations

import unittest

from fitmas.legacy.domain.athlete.zones import AthleteZones, compute_cycling_zones, compute_running_zones, compute_swimming_zones
from fitmas.legacy.domain.planning.session_templates import (
    SessionBlueprint,
    get_blueprint,
    render_blueprint,
    render_session_description,
    select_session_template,
)


def _running_zones(vma: float = 14.0, fc_max: int | None = None) -> AthleteZones:
    return AthleteZones(
        vma_kmh=vma, fc_max=fc_max, ftp_watts=None, css_per_100m=None,
        running_zones=compute_running_zones(vma, fc_max),
        cycling_zones=(), swimming_zones=(),
    )


def _cycling_zones(ftp: int = 200) -> AthleteZones:
    return AthleteZones(
        vma_kmh=None, fc_max=None, ftp_watts=ftp, css_per_100m=None,
        running_zones=(), cycling_zones=compute_cycling_zones(ftp), swimming_zones=(),
    )


def _swimming_zones(css: int = 110) -> AthleteZones:
    return AthleteZones(
        vma_kmh=None, fc_max=None, ftp_watts=None, css_per_100m=css,
        running_zones=(), cycling_zones=(), swimming_zones=compute_swimming_zones(css),
    )


class TestBlueprintRegistry(unittest.TestCase):
    def test_running_intervals_exists(self) -> None:
        bp = get_blueprint("running", "intervals")
        self.assertIsNotNone(bp)
        self.assertEqual(bp.target_zone, "Z5")

    def test_cycling_sweet_spot_exists(self) -> None:
        bp = get_blueprint("cycling", "sweet_spot")
        self.assertIsNotNone(bp)
        self.assertEqual(bp.target_zone, "Z4")

    def test_swimming_css_exists(self) -> None:
        bp = get_blueprint("swimming", "css")
        self.assertIsNotNone(bp)

    def test_nonexistent_returns_none(self) -> None:
        self.assertIsNone(get_blueprint("climbing", "bouldering"))


class TestRunningBlueprint(unittest.TestCase):
    def test_intervals_vma_14_contains_pace(self) -> None:
        bp = get_blueprint("running", "intervals")
        zones = _running_zones(14.0)
        text = render_blueprint(bp, zones, duration_min=55)
        self.assertIn("400m", text)
        self.assertIn("4:17/km", text)  # Z5 pace_high
        self.assertIn("(Z5)", text)

    def test_intervals_with_hr(self) -> None:
        bp = get_blueprint("running", "intervals")
        zones = _running_zones(14.0, fc_max=190)
        text = render_blueprint(bp, zones, duration_min=55)
        self.assertIn("FC", text)

    def test_intervals_beginner_fewer_reps(self) -> None:
        bp = get_blueprint("running", "intervals")
        zones = _running_zones(14.0)
        text = render_blueprint(bp, zones, duration_min=55, athlete_level="beginner")
        self.assertIn("6x400m", text)

    def test_intervals_advanced_more_reps(self) -> None:
        bp = get_blueprint("running", "intervals")
        zones = _running_zones(14.0)
        text = render_blueprint(bp, zones, duration_min=55, athlete_level="advanced")
        self.assertIn("10x400m", text)

    def test_intervals_cycle_week_3_extra_reps(self) -> None:
        bp = get_blueprint("running", "intervals")
        zones = _running_zones(14.0)
        text = render_blueprint(bp, zones, duration_min=55, athlete_level="intermediate", cycle_week=3)
        # intermediate base=8, delta=1, week3 bonus=2 → 10
        self.assertIn("10x400m", text)

    def test_intervals_recovery_week_halved(self) -> None:
        bp = get_blueprint("running", "intervals")
        zones = _running_zones(14.0)
        text = render_blueprint(bp, zones, duration_min=55, athlete_level="intermediate", cycle_week=4)
        # intermediate base=8, recovery → 4
        self.assertIn("4x400m", text)


class TestCyclingBlueprint(unittest.TestCase):
    def test_sweet_spot_ftp_200(self) -> None:
        bp = get_blueprint("cycling", "sweet_spot")
        zones = _cycling_zones(200)
        text = render_blueprint(bp, zones, duration_min=75)
        self.assertIn("176-188W", text)
        self.assertIn("(Z4)", text)


class TestSwimmingBlueprint(unittest.TestCase):
    def test_css_110(self) -> None:
        bp = get_blueprint("swimming", "css")
        zones = _swimming_zones(110)
        text = render_blueprint(bp, zones, duration_min=45)
        self.assertIn("100m", text)
        self.assertIn("(Z3)", text)


class TestFallback(unittest.TestCase):
    def test_no_zones_uses_legacy(self) -> None:
        template = select_session_template(sport_type="running", session_type="intervals")
        text = render_session_description(template, duration_min=55, zones=None)
        # Legacy text
        self.assertIn("8x400m allure 10k", text)

    def test_strength_uses_legacy(self) -> None:
        """Strength has no blueprint, should use legacy rendering."""
        template = select_session_template(sport_type="strength", session_type="general")
        zones = _running_zones(14.0)
        text = render_session_description(template, duration_min=40, zones=zones)
        self.assertIn("squats", text)

    def test_with_zones_uses_blueprint(self) -> None:
        template = select_session_template(sport_type="running", session_type="intervals")
        zones = _running_zones(14.0)
        text = render_session_description(template, duration_min=55, zones=zones)
        # Should use blueprint, not legacy
        self.assertNotIn("allure 10k", text)
        self.assertIn("(Z5)", text)


if __name__ == "__main__":
    unittest.main()
