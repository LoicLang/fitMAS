import type { CalendarItem, OverviewView } from "../../types";
import { loadBandLabel, sportLabel } from "../../shared/format";

export function overviewHeroLabel(data: OverviewView) {
  if (!data.lead_session) return data.week.label || "Bloc actif";
  return `${sportLabel(data.lead_session.sport_type)} · ${loadBandLabel(data.lead_session.load_band)}`;
}

export function overviewHeroTitle(session: CalendarItem | null) {
  if (!session) return { title: "FITMAS", suffix: "_COCKPIT" };
  return {
    title: session.title.toUpperCase(),
    suffix: `_${(session.session_type || "session").replaceAll("_", " ").toUpperCase()}`,
  };
}

export function overviewCompletionRatio(data: OverviewView) {
  const total = data.completion.sessions_this_week || 0;
  if (!total) return 0;
  return data.completion.done_this_week / total;
}
