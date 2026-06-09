import { describe, expect, it } from "vitest";
import { initialSelectedDate } from "../features/calendar/view-model";
import { weeklyExecutionRatio } from "../features/evolution/view-model";
import { overviewHeroTitle } from "../features/overview/view-model";
import { workoutStats } from "../features/workout-detail/view-model";
import { buildSvgPath } from "../lib/polyline";

describe("frontend view models", () => {
  it("picks today first in calendar", () => {
    const selected = initialSelectedDate([
      { date: "2026-03-27", day_number: 27, in_month: true, is_today: false, is_current_week: true, items: [] },
      { date: "2026-03-28", day_number: 28, in_month: true, is_today: true, is_current_week: true, items: [] },
    ]);
    expect(selected).toBe("2026-03-28");
  });

  it("computes weekly execution ratio", () => {
    expect(
      weeklyExecutionRatio({
        completion: { sessions_this_week: 4, done_this_week: 3, rate_14d: 0.8, key_sessions_done_14d: 2, volume_sessions_done_14d: 4 },
      } as never),
    ).toBe(0.75);
  });

  it("formats hero title with suffix", () => {
    expect(overviewHeroTitle({ title: "Long run", session_type: "easy_run" } as never)).toEqual({
      title: "LONG RUN",
      suffix: "_EASY RUN",
    });
  });

  it("builds workout stats from metrics", () => {
    const stats = workoutStats({
      metrics: { distance_m: 15200, duration_min: 95, elevation_m: 450, avg_hr: 145 },
    } as never);
    expect(stats[0].value).toContain("15.2");
    expect(stats[1].value).toBe("95 min");
  });

  it("preserves route proportions when building svg paths", () => {
    const route = buildSvgPath([
      [0, 0],
      [1, 1],
    ]);

    expect(route).not.toBeNull();
    // Equal lat/lng spans near the equator -> a square-ish bounding box (true proportions).
    const [, , w, h] = route!.viewBox.split(" ").map(Number);
    expect(Math.abs(w - h)).toBeLessThan(0.01);
    expect(route!.path.startsWith("M ")).toBe(true);
  });
});
