import type {
  Activity,
  AppBootstrap,
  PerformanceOverview,
  TodayView,
} from "../types";

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (response.status === 404 && url.startsWith("/api/v0/today")) {
    return null as T;
  }
  if (!response.ok) {
    throw new Error(`${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function loadBootstrap(): Promise<AppBootstrap> {
  const [profile, week, facts, activities, stravaStatus, timeline, trainingLoad, volume, records, performanceOverview, today] =
    await Promise.all([
      fetchJson("/api/v0/profile"),
      fetchJson("/api/v0/week"),
      fetchJson("/api/v0/facts"),
      fetchJson("/api/v0/activities"),
      fetchJson("/api/v0/strava/status"),
      fetchJson("/api/v0/timeline"),
      fetchJson("/api/v0/stats/training-load"),
      fetchJson("/api/v0/stats/volume"),
      fetchJson("/api/v0/stats/records"),
      fetchJson<PerformanceOverview>("/api/v0/stats/performance-overview"),
      fetchJson<TodayView | null>("/api/v0/today"),
    ]);

  return {
    profile,
    week,
    facts,
    activities,
    stravaStatus,
    timeline,
    trainingLoad,
    volume,
    records,
    performanceOverview,
    today,
  };
}

export function loadTodayBySession(sessionId: number) {
  return fetchJson<TodayView | null>(`/api/v0/today/session/${sessionId}`);
}

export function completeSession(sessionId: number) {
  return fetchJson(`/api/v0/plan/sessions/${sessionId}/complete`, { method: "POST" });
}

export function skipSession(sessionId: number) {
  return fetchJson(`/api/v0/plan/sessions/${sessionId}/skip`, { method: "POST" });
}

export function moveSession(sessionId: number) {
  return fetchJson(`/api/v0/plan/sessions/${sessionId}/move`, { method: "POST" });
}

export function regenerateWeek() {
  return fetchJson(`/api/v0/week/regenerate`, { method: "POST" });
}

export function syncStrava() {
  return fetchJson<{ synced: boolean; imported?: number }>(`/api/v0/strava/sync`, { method: "POST" });
}

export function createManualActivity(payload: Record<string, unknown>) {
  return fetchJson<Activity>(`/api/v0/activities/manual`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
