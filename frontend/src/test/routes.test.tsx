import { cleanup, render, screen } from "@testing-library/react";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AppLayout } from "../app/AppLayout";
import { CalendarPage } from "../features/calendar/CalendarPage";
import { EvolutionPage } from "../features/evolution/EvolutionPage";
import { OverviewPage } from "../features/overview/OverviewPage";
import { WorkoutDetailPage } from "../features/workout-detail/WorkoutDetailPage";

const overviewPayload = {
  today: {
    scheduled_session_id: 42,
    scheduled_date: "2026-03-28",
    day: "saturday",
    label: "Samedi",
    sport_type: "running",
    session_type: "long_run",
    session_title: "Long run",
    session_goal: "Endurance fondamentale",
    session_note: "On pose une vraie sortie d'endurance avant la semaine chargée.",
    session_description: "20 min souple\n80 min endurance\n20 min retour au calme",
    duration_min: 120,
    load_band: "easy",
    priority: "Cle",
    change_notes: [],
    watch_items: [],
  },
  lead_session: {
    kind: "session",
    id: 42,
    status: "planned",
    scheduled_date: "2026-03-28",
    display_date: "2026-03-28",
    title: "Long run",
    goal: "Endurance fondamentale",
    sport_type: "running",
    session_type: "long_run",
    duration_min: 120,
    load_band: "easy",
    label: "Samedi",
  },
  upcoming_sessions: [],
  week: { week_start: "2026-03-24", week_end: "2026-03-30", label: "Semaine build", mesocycle_week: 2, mesocycle_number: 1, is_deload: false },
  load: { ctl: 48, atl: 52, tsb: -4, ramp_rate: 0.08, freshness: "stable" },
  tss: { target: 420, actual: 210, remaining: 210, delta: -210 },
  completion: { rate_14d: 0.5, key_sessions_done_14d: 2, volume_sessions_done_14d: 3, sessions_this_week: 4, done_this_week: 2 },
  weekly_hours: 6.5,
  profile: { name: "Loic", coach_name: "FitMAS", objective: "reprendre", sports: ["running"], constraints: [], preferences: [] },
  strava: { configured: true, connected: false, last_sync_at: null },
};

const calendarPayload = {
  month: { key: "2026-03", label: "2026-03", week_label: "Build", mesocycle_week: 2, mesocycle_number: 1, is_deload: false },
  days: [
    { date: "2026-03-28", day_number: 28, in_month: true, is_today: true, is_current_week: true, items: [
      { kind: "session", id: 42, status: "missing", scheduled_date: "2026-03-28", display_date: "2026-03-28", title: "Tempo run", goal: "Tenir", sport_type: "running", session_type: "tempo", duration_min: 50, load_band: "moderate", label: "Samedi" },
      { kind: "offplan", id: 9, status: "offplan", display_date: "2026-03-28", title: "Sortie vélo off-plan", sport_type: "cycling", session_type: "offplan", duration_min: 70, load_band: "moderate" },
    ] },
  ],
  feed: [],
};

const evolutionPayload = {
  week: { week_start: "2026-03-24", week_end: "2026-03-30", label: "Build", mesocycle_week: 2, mesocycle_number: 1, is_deload: false, planning_mode: "increase_load", adaptation_level: "medium", adaptation_scope: "week", intensity_distribution: "balanced" },
  load: { ctl: 48, atl: 52, tsb: -4, ramp_rate: 0.08, freshness: "stable" },
  tss: { target: 420, actual: 210, remaining: 210, delta: -210 },
  completion: { rate_14d: 0.5, key_sessions_done_14d: 2, volume_sessions_done_14d: 3, sessions_this_week: 4, done_this_week: 2 },
  distribution: { planned: { easy: { count: 2, tss: 80 } }, completed: { easy: { count: 1, tss: 40 } } },
  sports: { ctl: { running: 48 }, volume_hours_14d: { running: 8 } },
  rationale: ["Bloc build propre."],
  risk_flags: [],
  history: [{ date: "2026-03-20", ctl: 45, atl: 50, tsb: -5 }],
  week_daily: [{ date: "2026-03-28", label: "Sam", planned_tss: 80, actual_tss: 40, planned_duration_min: 120, actual_duration_min: 60 }],
  forecast: [{ week_index: 1, cycle_week: 2, target_tss: 420, projected_ctl: 49, focus: "Build", planning_mode: "increase_load", is_deload: false }],
};

const workoutPayload = {
  session: { kind: "session", id: 42, status: "done", scheduled_date: "2026-03-28", display_date: "2026-03-28", title: "Long run", goal: "Endurance", sport_type: "running", session_type: "long_run", duration_min: 120, load_band: "easy", label: "Samedi" },
  metrics: { distance_m: 24000, duration_min: 135, elevation_m: 450, avg_hr: 145, avg_speed: 3.2, tss: 82 },
  linked_activity: { id: 88, title: "Long run du jour", sport_type: "running", source: "manual", started_at: "2026-03-28T07:30:00Z" },
  fitness: { ctl: 48, atl: 52, tsb: -4, freshness: "stable" },
  recent_activity: null,
  coach: { goal: "Endurance fondamentale", note: "ClawCoach garde cette séance lisible.", description: "Sortie longue", nutrition_focus: "Hydrate-toi", change_notes: [], watch_items: [] },
  content: {
    objective: "Construire une vraie endurance stable.",
    rationale: "On pose une sortie longue propre avant de remonter la densité.",
    execution: ["20 min souple", "80 min endurance régulière", "20 min retour au calme"],
    coach_cue: "Reste propre et garde du jus jusqu'au bout.",
    nutrition_note: "Hydrate-toi bien et reste simple aujourd'hui.",
  },
  zone_distribution: [20, 45, 20, 10, 5],
  map_polyline: null,
};

afterEach(() => {
  vi.restoreAllMocks();
  cleanup();
});

function renderAt(path: string, loaderData: Record<string, unknown>) {
  const router = createMemoryRouter([
    {
      id: "root",
      path: "/",
      element: <AppLayout />,
      children: [
        { id: "overview", index: true, element: <OverviewPage /> },
        { id: "calendar", path: "calendar", element: <CalendarPage /> },
        { id: "evolution", path: "evolution", element: <EvolutionPage /> },
        { id: "workout", path: "workout/:sessionId", element: <WorkoutDetailPage /> },
      ],
    },
  ], {
    initialEntries: [path],
    hydrationData: {
      loaderData,
    },
  });
  return render(<RouterProvider router={router} />);
}

describe("app routes", () => {
  it("renders overview with today's workout", async () => {
    renderAt("/", { overview: overviewPayload });
    expect(await screen.findByText("LONG RUN")).toBeInTheDocument();
    expect(screen.getByText("À venir")).toBeInTheDocument();
    expect(screen.getByText("On pose une vraie sortie d'endurance avant la semaine chargée.")).toBeInTheDocument();
    expect(screen.queryByText("20 min souple")).not.toBeInTheDocument();
  });

  it("renders overview without quick actions when today is null", async () => {
    renderAt("/", { overview: { ...overviewPayload, today: null } });
    expect(await screen.findByText("LONG RUN")).toBeInTheDocument();
    expect(screen.queryByText("Fait")).not.toBeInTheDocument();
  });

  it("renders calendar with missing and offplan states", async () => {
    renderAt("/calendar", { calendar: calendarPayload });
    expect(await screen.findByText("Planning")).toBeInTheDocument();
    expect(await screen.findByText("Tempo run")).toBeInTheDocument();
    expect(screen.getAllByText("manqué").length).toBeGreaterThan(0);
    expect(screen.getAllByText("hors plan").length).toBeGreaterThan(0);
  });

  it("renders workout detail route directly", async () => {
    renderAt("/workout/42", { workout: workoutPayload });
    expect(await screen.findByText("Long run")).toBeInTheDocument();
    expect(screen.getByText("Pourquoi aujourd'hui")).toBeInTheDocument();
    expect(screen.getByText("Séance")).toBeInTheDocument();
    expect(screen.getByText("Reste propre et garde du jus jusqu'au bout.")).toBeInTheDocument();
    expect(screen.queryByText("ClawCoach garde cette séance lisible.")).not.toBeInTheDocument();
  });

  it("renders evolution with historical data", async () => {
    renderAt("/evolution", { evolution: evolutionPayload });
    expect(await screen.findByText("Progression")).toBeInTheDocument();
    expect(screen.getByText("Charge")).toBeInTheDocument();
    expect(screen.getByText("Prévu vs fait")).toBeInTheDocument();
  });

  it("renders evolution without history gracefully", async () => {
    renderAt("/evolution", { evolution: { ...evolutionPayload, history: [] } });
    expect(await screen.findByText("Progression")).toBeInTheDocument();
    expect(screen.getByText("48.0")).toBeInTheDocument();
  });
});
