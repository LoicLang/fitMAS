import type { WorkoutDetailView } from "../../types";
import { formatDistance, formatPace } from "../../shared/format";

export function workoutStats(data: WorkoutDetailView) {
  return [
    {
      label: "Distance",
      value: formatDistance(data.metrics.distance_m) || "—",
    },
    {
      label: "Durée",
      value: data.metrics.duration_min ? `${Math.round(data.metrics.duration_min)} min` : "—",
    },
    {
      label: "Dénivelé",
      value: data.metrics.elevation_m ? `+${Math.round(data.metrics.elevation_m)} m` : "—",
    },
    {
      label: "Intensité",
      value: data.metrics.avg_hr ? `${Math.round(data.metrics.avg_hr)} bpm` : formatPace(data.metrics.avg_speed) || "—",
    },
  ];
}
