import type { EvolutionView } from "../../types";

export function weeklyExecutionRatio(data: EvolutionView) {
  const total = data.completion.sessions_this_week || 0;
  if (!total) return 0;
  return data.completion.done_this_week / total;
}

export function latestCtl(data: EvolutionView) {
  return data.history[data.history.length - 1]?.ctl ?? data.load.ctl ?? 0;
}
