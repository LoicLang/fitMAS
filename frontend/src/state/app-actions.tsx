import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useNavigate, useRevalidator } from "react-router-dom";
import { createManualActivity, completeSession, moveSession, skipSession, syncStrava } from "../shared/api";

interface AppActionsValue {
  pendingKey: string | null;
  actOnSession: (action: "done" | "skip" | "move", sessionId: number) => Promise<void>;
  addActivity: (payload: Record<string, unknown>) => Promise<void>;
  runStravaSync: () => Promise<void>;
}

const AppActionsContext = createContext<AppActionsValue | null>(null);

export function AppActionsProvider({ children }: { children: ReactNode }) {
  const revalidator = useRevalidator();
  const navigate = useNavigate();
  const [pendingKey, setPendingKey] = useState<string | null>(null);

  const actOnSession = useCallback(async (action: "done" | "skip" | "move", sessionId: number) => {
    setPendingKey(`${action}:${sessionId}`);
    try {
      if (action === "done") await completeSession(sessionId);
      if (action === "skip") await skipSession(sessionId);
      if (action === "move") await moveSession(sessionId);
      revalidator.revalidate();
    } finally {
      setPendingKey(null);
    }
  }, [revalidator]);

  const addActivity = useCallback(async (payload: Record<string, unknown>) => {
    setPendingKey("add-activity");
    try {
      await createManualActivity(payload);
      revalidator.revalidate();
      navigate("/#utility");
    } finally {
      setPendingKey(null);
    }
  }, [navigate, revalidator]);

  const runStravaSync = useCallback(async () => {
    setPendingKey("sync-strava");
    try {
      await syncStrava();
      revalidator.revalidate();
    } finally {
      setPendingKey(null);
    }
  }, [revalidator]);

  const value = useMemo<AppActionsValue>(() => ({
    pendingKey,
    actOnSession,
    addActivity,
    runStravaSync,
  }), [actOnSession, addActivity, pendingKey, runStravaSync]);

  return <AppActionsContext.Provider value={value}>{children}</AppActionsContext.Provider>;
}

export function useAppActions() {
  const context = useContext(AppActionsContext);
  if (!context) {
    throw new Error("useAppActions must be used inside AppActionsProvider");
  }
  return context;
}
