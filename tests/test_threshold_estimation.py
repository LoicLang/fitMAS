"""Tests for Strava threshold estimation."""

from fitmas.domain.athlete.threshold_estimation import estimate_vma_from_activity


class FakeActivity:
    def __init__(self, **kwargs):
        defaults = {
            "sport_type": "running",
            "duration_min": 45,
            "avg_speed": 3.5,  # m/s ≈ 12.6 km/h
            "avg_hr": 150,
            "max_hr": 190,
            "distance_m": 9450,
            "tss": None,
            "scheduled_session_id": None,
        }
        defaults.update(kwargs)
        for k, v in defaults.items():
            setattr(self, k, v)


class TestEstimateVma:
    def test_moderate_run(self):
        # 3.5 m/s = 12.6 km/h, HR ratio 150/190 = 0.79 → moderate, correction 1.15
        # VMA ≈ 12.6 * 1.15 ≈ 14.5
        a = FakeActivity()
        vma = estimate_vma_from_activity(a)
        assert vma is not None
        assert 14.0 <= vma <= 15.0

    def test_easy_run(self):
        # HR ratio < 0.72 → easy, correction 1.35
        a = FakeActivity(avg_speed=2.8, avg_hr=130, max_hr=190)  # 10.1 km/h
        vma = estimate_vma_from_activity(a)
        assert vma is not None
        assert 13.0 <= vma <= 14.5

    def test_hard_run(self):
        # HR ratio > 0.85 → hard, correction 1.05
        a = FakeActivity(avg_speed=4.0, avg_hr=170, max_hr=190)  # 14.4 km/h
        vma = estimate_vma_from_activity(a)
        assert vma is not None
        assert 14.5 <= vma <= 16.0

    def test_not_running(self):
        a = FakeActivity(sport_type="cycling")
        assert estimate_vma_from_activity(a) is None

    def test_too_short(self):
        a = FakeActivity(duration_min=10)
        assert estimate_vma_from_activity(a) is None

    def test_no_speed(self):
        a = FakeActivity(avg_speed=None)
        assert estimate_vma_from_activity(a) is None

    def test_very_slow(self):
        a = FakeActivity(avg_speed=1.0)  # ~3.6 km/h (walking)
        assert estimate_vma_from_activity(a) is None

    def test_no_hr_defaults_moderate(self):
        # Without HR → defaults to moderate correction
        a = FakeActivity(avg_hr=None, max_hr=None, avg_speed=3.5)
        vma = estimate_vma_from_activity(a)
        assert vma is not None
        # 12.6 * 1.15 ≈ 14.5
        assert 14.0 <= vma <= 15.0

    def test_trail_running(self):
        a = FakeActivity(sport_type="trail_running", avg_speed=2.5, avg_hr=155, max_hr=190)
        # "run" is in "trail_running" → should work
        vma = estimate_vma_from_activity(a)
        assert vma is not None
