import type {
  Activity,
  CalendarView,
  EvolutionView,
  OverviewView,
  TodayView,
  WorkoutDetailView,
} from "../types";

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    throw new Error(`${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function loadOverview() {
  return fetchJson<OverviewView>("/api/v0/app/overview");
}

export function loadCalendar(month?: string | null) {
  const search = month ? `?month=${encodeURIComponent(month)}` : "";
  return fetchJson<CalendarView>(`/api/v0/app/calendar${search}`);
}

export function loadEvolution() {
  return fetchJson<EvolutionView>("/api/v0/app/evolution");
}

export function loadWorkoutDetail(sessionId: number | string) {
  return fetchJson<WorkoutDetailView>(`/api/v0/sessions/${sessionId}`);
}

export function completeSession(sessionId: number) {
  return fetchJson<TodayView>(`/api/v0/plan/sessions/${sessionId}/complete`, { method: "POST" });
}

export function skipSession(sessionId: number) {
  return fetchJson<TodayView>(`/api/v0/plan/sessions/${sessionId}/skip`, { method: "POST" });
}

export function moveSession(sessionId: number) {
  return fetchJson<TodayView>(`/api/v0/plan/sessions/${sessionId}/move`, { method: "POST" });
}

export function syncStrava() {
  return fetchJson<{ synced: boolean; imported?: number }>("/api/v0/strava/sync", { method: "POST" });
}

export function createManualActivity(payload: Record<string, unknown>) {
  return fetchJson<Activity>("/api/v0/activities/manual", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
