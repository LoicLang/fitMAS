import { format, parseISO } from "date-fns";
import { fr } from "date-fns/locale";

export const SPORT_LABEL: Record<string, string> = {
  running: "Course",
  cycling: "Vélo",
  swimming: "Natation",
  climbing: "Escalade",
  strength: "Renfo",
  rest: "Repos",
};

export const LOAD_BAND_LABEL: Record<string, string> = {
  hard: "Charge haute",
  moderate: "Charge modérée",
  easy: "Charge facile",
  recovery: "Récup",
  mobility: "Mobilité",
};

export function sportLabel(sport?: string | null) {
  if (!sport) return "Sport";
  return SPORT_LABEL[sport] || sport;
}

export function loadBandLabel(loadBand?: string | null) {
  if (!loadBand) return "Charge facile";
  return LOAD_BAND_LABEL[loadBand] || loadBand;
}

export function sessionTypeLabel(value?: string | null) {
  if (!value) return "Séance";
  const table: Record<string, string> = {
    intervals: "Fractionné",
    threshold: "Seuil",
    tempo: "Tempo",
    long_run: "Long run",
    easy_run: "Endurance",
    strength: "Renforcement",
    swim_drills: "Drills",
    rest: "Repos",
  };
  return table[value] || value.replaceAll("_", " ");
}

export function formatDateLong(iso?: string | null) {
  if (!iso) return "—";
  return format(parseISO(iso), "EEEE d MMMM yyyy", { locale: fr });
}

export function formatDateShort(iso?: string | null) {
  if (!iso) return "—";
  return format(parseISO(iso), "EEE d MMM", { locale: fr }).replace(".", "");
}

export function formatDateTime(iso?: string | null) {
  if (!iso) return "—";
  return format(parseISO(iso), "EEE d MMM · HH:mm", { locale: fr }).replace(".", "");
}

export function formatMonthLabel(monthKey: string) {
  return format(parseISO(`${monthKey}-01`), "MMMM yyyy", { locale: fr }).toUpperCase();
}

export function formatDistance(distanceM?: number | null) {
  if (!distanceM) return null;
  return `${(distanceM / 1000).toFixed(distanceM >= 20000 ? 0 : 1)} km`;
}

export function formatPace(avgSpeed?: number | null) {
  if (!avgSpeed || avgSpeed <= 0) return null;
  const seconds = 1000 / avgSpeed;
  const mins = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  return `${mins}:${String(secs).padStart(2, "0")}/km`;
}

export function percent(value: number) {
  return `${Math.round(value * 100)}%`;
}
