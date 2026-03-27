import { addDays, formatISO, parseISO } from "date-fns";
import type { AppBootstrap, ScheduledSession, WeeklyPlan } from "../types";

const DAY_OFFSETS: Record<string, number> = {
  monday: 0,
  tuesday: 1,
  wednesday: 2,
  thursday: 3,
  friday: 4,
  saturday: 5,
  sunday: 6,
};

function buildDraftTimeline(week: WeeklyPlan, weekStart: string): ScheduledSession[] {
  const anchor = parseISO(weekStart);
  return week.days.map((day, index) => {
    const offset = DAY_OFFSETS[day.day] ?? index;
    return {
      id: -(index + 1),
      day: day.day,
      label: day.label,
      scheduled_date: formatISO(addDays(anchor, offset), { representation: "date" }),
      sport_type: day.sport_type,
      session_type: day.session_type,
      session_title: day.session_title,
      session_goal: day.session_goal,
      session_note: day.session_note,
      session_description: day.session_description,
      duration_min: day.duration_min,
      intensity: day.intensity,
      load_score: day.load_score,
      load_band: day.load_band,
      priority: day.priority,
      nutrition_focus: day.nutrition_focus,
      flexibility: day.flexibility,
      completion_status: day.completion_status,
      linked_activity_id: null,
    };
  });
}

export function getVisibleTimeline(data?: AppBootstrap | null): ScheduledSession[] {
  if (!data) return [];
  if (data.timeline.length) return data.timeline;
  return buildDraftTimeline(data.week, data.performanceOverview.week.week_start);
}

export function getPrimarySession(data?: AppBootstrap | null) {
  const visibleTimeline = getVisibleTimeline(data);
  if (!data?.today) return visibleTimeline[0] || null;
  return visibleTimeline.find((session) => session.id === data.today?.scheduled_session_id) || visibleTimeline[0] || null;
}
