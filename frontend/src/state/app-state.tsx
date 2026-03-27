import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  completeSession,
  createManualActivity,
  loadBootstrap,
  loadTodayBySession,
  moveSession,
  regenerateWeek,
  skipSession,
  syncStrava,
} from "../lib/api";
import type {
  Activity,
  AppBootstrap,
  ScheduledSession,
  TodayView,
} from "../types";

interface AppStateValue {
  data: AppBootstrap | null;
  loading: boolean;
  error: string | null;
  selectedSession: ScheduledSession | null;
  selectedActivity: Activity | null;
  setSelectedSession: (session: ScheduledSession | null) => void;
  setSelectedActivity: (activity: Activity | null) => void;
  refresh: () => Promise<void>;
  refreshToday: (sessionId?: number | null) => Promise<TodayView | null>;
  actOnSession: (action: "done" | "skip" | "move", sessionId: number) => Promise<void>;
  regenerate: () => Promise<void>;
  addActivity: (payload: Record<string, unknown>) => Promise<void>;
  runStravaSync: () => Promise<void>;
}

const AppStateContext = createContext<AppStateValue | null>(null);

export function AppStateProvider({ children }: { children: ReactNode }) {
  const [data, setData] = useState<AppBootstrap | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedSession, setSelectedSession] = useState<ScheduledSession | null>(null);
  const [selectedActivity, setSelectedActivity] = useState<Activity | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const next = await loadBootstrap();
      setData(next);
      if (selectedSession) {
        const freshSession = next.timeline.find((item) => item.id === selectedSession.id) || null;
        setSelectedSession(freshSession);
      }
      if (selectedActivity) {
        const freshActivity = next.activities.find((item) => item.id === selectedActivity.id) || null;
        setSelectedActivity(freshActivity);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur de chargement");
    } finally {
      setLoading(false);
    }
  }, [selectedActivity, selectedSession]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const refreshToday = useCallback(async (sessionId?: number | null) => {
    if (!sessionId) return data?.today || null;
    const nextToday = await loadTodayBySession(sessionId);
    setData((current) => (current ? { ...current, today: nextToday } : current));
    return nextToday;
  }, [data?.today]);

  const actOnSession = useCallback(async (action: "done" | "skip" | "move", sessionId: number) => {
    if (action === "done") await completeSession(sessionId);
    if (action === "skip") await skipSession(sessionId);
    if (action === "move") await moveSession(sessionId);
    await refresh();
    await refreshToday(sessionId);
  }, [refresh, refreshToday]);

  const regenerate = useCallback(async () => {
    await regenerateWeek();
    await refresh();
  }, [refresh]);

  const addActivity = useCallback(async (payload: Record<string, unknown>) => {
    await createManualActivity(payload);
    await refresh();
  }, [refresh]);

  const runStravaSync = useCallback(async () => {
    await syncStrava();
    await refresh();
  }, [refresh]);

  const value = useMemo<AppStateValue>(() => ({
    data,
    loading,
    error,
    selectedSession,
    selectedActivity,
    setSelectedSession,
    setSelectedActivity,
    refresh,
    refreshToday,
    actOnSession,
    regenerate,
    addActivity,
    runStravaSync,
  }), [actOnSession, addActivity, data, error, loading, refresh, refreshToday, regenerate, runStravaSync, selectedActivity, selectedSession]);

  return <AppStateContext.Provider value={value}>{children}</AppStateContext.Provider>;
}

export function useAppState() {
  const context = useContext(AppStateContext);
  if (!context) {
    throw new Error("useAppState must be used within AppStateProvider");
  }
  return context;
}
