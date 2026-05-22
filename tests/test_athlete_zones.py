from __future__ import annotations

import unittest
from types import SimpleNamespace

from fitmas.domain.athlete.zones import (
    AthleteZones,
    build_athlete_zones,
    compute_cycling_zones,
    compute_running_zones,
    compute_swimming_zones,
    estimate_css_from_level,
    estimate_ftp_from_level,
    estimate_vma_from_level,
    format_zones_for_prompt,
    get_zone_target,
)


class TestRunningZones(unittest.TestCase):
    def test_vma_14_z2_pace_range(self) -> None:
        """Z2 for VMA 14 should be roughly 5:21-6:07/km."""
        zones = compute_running_zones(14.0)
        z2 = next(z for z in zones if z.zone == "Z2")
        # pace_low = slower (lower speed), pace_high = faster (higher speed)
        self.assertEqual(z2.pace_low, "6:07/km")
        self.assertEqual(z2.pace_high, "5:21/km")

    def test_vma_14_z5_pace_range(self) -> None:
        """Z5 for VMA 14 should be roughly 4:31-4:17/km (near VMA pace)."""
        zones = compute_running_zones(14.0)
        z5 = next(z for z in zones if z.zone == "Z5")
        self.assertEqual(z5.pace_high, "4:17/km")

    def test_5_zones_produced(self) -> None:
        zones = compute_running_zones(14.0)
        self.assertEqual(len(zones), 5)
        self.assertEqual([z.zone for z in zones], ["Z1", "Z2", "Z3", "Z4", "Z5"])

    def test_hr_zones_with_fcmax(self) -> None:
        zones = compute_running_zones(14.0, fc_max=190)
        z3 = next(z for z in zones if z.zone == "Z3")
        self.assertEqual(z3.hr_low, 152)  # int(190 * 0.80)
        self.assertEqual(z3.hr_high, 167)  # int(190 * 0.88)

    def test_hr_zones_without_fcmax(self) -> None:
        zones = compute_running_zones(14.0)
        z1 = zones[0]
        self.assertIsNone(z1.hr_low)
        self.assertIsNone(z1.hr_high)


class TestCyclingZones(unittest.TestCase):
    def test_ftp_200_z4_sweet_spot(self) -> None:
        """Z4 Sweet Spot FTP 200 should be 176-188W."""
        zones = compute_cycling_zones(200)
        z4 = next(z for z in zones if z.zone == "Z4")
        self.assertEqual(z4.power_low, 176)  # int(200 * 0.88)
        self.assertEqual(z4.power_high, 188)  # int(200 * 0.94)

    def test_7_zones_produced(self) -> None:
        zones = compute_cycling_zones(200)
        self.assertEqual(len(zones), 7)

    def test_ftp_200_z5_threshold(self) -> None:
        zones = compute_cycling_zones(200)
        z5 = next(z for z in zones if z.zone == "Z5")
        self.assertEqual(z5.power_low, 190)  # int(200 * 0.95)
        self.assertEqual(z5.power_high, 210)  # int(200 * 1.05)


class TestSwimmingZones(unittest.TestCase):
    def test_css_110_z3_threshold(self) -> None:
        """Z3 Threshold for CSS 110 should be ~104-115 sec/100m."""
        zones = compute_swimming_zones(110)
        z3 = next(z for z in zones if z.zone == "Z3")
        self.assertEqual(z3.css_low, 104)  # int(110 * 0.95) faster
        self.assertEqual(z3.css_high, 115)  # int(110 * 1.05) slower

    def test_5_zones_produced(self) -> None:
        zones = compute_swimming_zones(110)
        self.assertEqual(len(zones), 5)

    def test_css_110_z1_recovery(self) -> None:
        zones = compute_swimming_zones(110)
        z1 = zones[0]
        # Z1: low_pct=1.15, high_pct=1.25 → css_low=126, css_high=137
        self.assertEqual(z1.css_low, 126)  # int(110 * 1.15) faster end
        self.assertEqual(z1.css_high, 137)  # int(110 * 1.25) slower end


class TestLevelEstimates(unittest.TestCase):
    def test_vma_levels(self) -> None:
        self.assertEqual(estimate_vma_from_level("beginner"), 10.0)
        self.assertEqual(estimate_vma_from_level("intermediate"), 14.0)
        self.assertEqual(estimate_vma_from_level("advanced"), 17.5)
        self.assertEqual(estimate_vma_from_level("unknown"), 12.0)

    def test_ftp_levels(self) -> None:
        self.assertEqual(estimate_ftp_from_level("beginner"), 120)
        self.assertEqual(estimate_ftp_from_level("intermediate"), 200)
        self.assertEqual(estimate_ftp_from_level("advanced"), 280)

    def test_css_levels(self) -> None:
        self.assertEqual(estimate_css_from_level("beginner"), 150)
        self.assertEqual(estimate_css_from_level("intermediate"), 110)
        self.assertEqual(estimate_css_from_level("advanced"), 85)


class TestBuildAthleteZones(unittest.TestCase):
    def test_builds_from_profile_levels(self) -> None:
        profile = SimpleNamespace(
            primary_sports=("running", "cycling"),
            level_by_sport={"running": "intermediate", "cycling": "beginner"},
        )
        zones = build_athlete_zones(profile, facts=[])
        self.assertEqual(zones.vma_kmh, 14.0)
        self.assertEqual(zones.ftp_watts, 120)
        self.assertIsNone(zones.css_per_100m)
        self.assertEqual(len(zones.running_zones), 5)
        self.assertEqual(len(zones.cycling_zones), 7)
        self.assertEqual(len(zones.swimming_zones), 0)

    def test_threshold_facts_override_estimates(self) -> None:
        profile = SimpleNamespace(
            primary_sports=("running",),
            level_by_sport={"running": "beginner"},
        )
        facts = [
            SimpleNamespace(category="threshold", key="vma", value="16.0"),
            SimpleNamespace(category="threshold", key="fc_max", value="185"),
        ]
        zones = build_athlete_zones(profile, facts)
        self.assertEqual(zones.vma_kmh, 16.0)
        self.assertEqual(zones.fc_max, 185)
        # Verify HR is present in zones
        z1 = zones.running_zones[0]
        self.assertIsNotNone(z1.hr_low)

    def test_no_zones_for_absent_sport(self) -> None:
        profile = SimpleNamespace(
            primary_sports=("climbing",),
            level_by_sport={"climbing": "intermediate"},
        )
        zones = build_athlete_zones(profile, facts=[])
        self.assertEqual(len(zones.running_zones), 0)
        self.assertEqual(len(zones.cycling_zones), 0)
        self.assertEqual(len(zones.swimming_zones), 0)


class TestFormatAndLookup(unittest.TestCase):
    def test_format_zones_for_prompt(self) -> None:
        zones = AthleteZones(
            vma_kmh=14.0,
            fc_max=None,
            ftp_watts=None,
            css_per_100m=None,
            running_zones=compute_running_zones(14.0),
            cycling_zones=(),
            swimming_zones=(),
        )
        text = format_zones_for_prompt(zones)
        self.assertIn("Running (VMA 14.0 km/h):", text)
        self.assertIn("Z1 Endurance fondamentale:", text)
        self.assertIn("/km", text)

    def test_get_zone_target(self) -> None:
        zones = AthleteZones(
            vma_kmh=14.0,
            fc_max=None,
            ftp_watts=200,
            css_per_100m=None,
            running_zones=compute_running_zones(14.0),
            cycling_zones=compute_cycling_zones(200),
            swimming_zones=(),
        )
        z4 = get_zone_target(zones, "cycling", "Z4")
        self.assertIsNotNone(z4)
        self.assertEqual(z4.power_low, 176)

    def test_get_zone_target_unknown_sport(self) -> None:
        zones = AthleteZones(
            vma_kmh=None, fc_max=None, ftp_watts=None, css_per_100m=None,
            running_zones=(), cycling_zones=(), swimming_zones=(),
        )
        self.assertIsNone(get_zone_target(zones, "climbing", "Z1"))


if __name__ == "__main__":
    unittest.main()
