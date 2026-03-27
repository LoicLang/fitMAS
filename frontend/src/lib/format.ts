import { format, isSameMonth, parseISO, startOfWeek } from "date-fns";
import { fr } from "date-fns/locale";

export const SPORT_LABEL: Record<string, string> = {
  running: "Course",
  cycling: "Vélo",
  swimming: "Natation",
  climbing: "Escalade",
  strength: "Renfo",
  rest: "Repos",
};

export const SPORT_EMOJI: Record<string, string> = {
  running: "🏃",
  cycling: "🚴",
  swimming: "🏊",
  climbing: "🧗",
  strength: "💪",
  rest: "🛌",
};

export const LOAD_BAND_LABEL: Record<string, string> = {
  hard: "Charge haute",
  moderate: "Charge modérée",
  easy: "Charge facile",
  recovery: "Récup",
  mobility: "Mobilité",
};

export function sportLabel(sport: string) {
  return SPORT_LABEL[sport] || sport;
}

export function sessionTypeLabel(sessionType: string) {
  const labels: Record<string, string> = {
    intervals: "Fractionné",
    tempo: "Tempo run",
    threshold: "Seuil",
    long_run: "Long run",
    easy_run: "Endurance",
    swim_drills: "Swim drills",
    strength: "Renforcement",
    mobility: "Mobilité",
    rest: "Repos",
  };
  return labels[sessionType] || sessionType.replaceAll("_", " ");
}

export function loadBandLabel(loadBand?: string | null) {
  if (!loadBand) return "Charge facile";
  return LOAD_BAND_LABEL[loadBand] || loadBand;
}

export function formatDateShort(iso?: string | null) {
  if (!iso) return "—";
  return format(parseISO(iso), "EEE d MMM", { locale: fr }).replace(".", "");
}

export function formatDateLong(iso?: string | null) {
  if (!iso) return "—";
  return format(parseISO(iso), "EEEE d MMMM yyyy", { locale: fr });
}

export function formatDateTime(iso?: string | null) {
  if (!iso) return "—";
  return format(parseISO(iso), "EEE d MMM · HH:mm", { locale: fr }).replace(".", "");
}

export function formatMonth(date: Date) {
  return format(date, "MMMM yyyy", { locale: fr }).toUpperCase();
}

export function formatDistance(distanceM?: number | null) {
  if (!distanceM) return null;
  return `${(distanceM / 1000).toFixed(distanceM >= 10000 ? 0 : 1)} km`;
}

export function formatPace(avgSpeed?: number | null) {
  if (!avgSpeed || avgSpeed <= 0) return null;
  const seconds = 1000 / avgSpeed;
  const mins = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  return `${mins}:${String(secs).padStart(2, "0")}/km`;
}

export function formatWeekAxis(iso: string) {
  return format(parseISO(iso), "MMM", { locale: fr }).replace(".", "");
}

export function getWeekStart(date: Date) {
  return startOfWeek(date, { weekStartsOn: 1 });
}

export function sameVisibleMonth(date: Date, visibleMonth: Date) {
  return isSameMonth(date, visibleMonth);
}
