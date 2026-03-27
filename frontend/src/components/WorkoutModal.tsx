import { AnimatePresence, motion } from "motion/react";
import { Clock3, HeartPulse, Mountain, Route, X } from "lucide-react";
import { useMemo } from "react";
import { useAppState } from "../state/app-state";
import { buildSvgPath, decodePolyline } from "../lib/polyline";
import { formatDateLong, formatDistance, formatPace, loadBandLabel, sessionTypeLabel, sportLabel } from "../lib/format";

function buildZoneDistribution(loadBand?: string | null) {
  const table: Record<string, number[]> = {
    hard: [5, 15, 22, 38, 20],
    moderate: [12, 34, 24, 18, 12],
    easy: [24, 48, 20, 6, 2],
    recovery: [52, 34, 12, 2, 0],
    mobility: [68, 20, 10, 2, 0],
  };
  return table[loadBand || "easy"] || table.easy;
}

export function WorkoutModal() {
  const { data, selectedSession, selectedActivity, setSelectedSession, setSelectedActivity } = useAppState();

  const payload = useMemo(() => {
    if (!data) return null;
    if (selectedSession) {
      const linkedActivity = data.activities.find((activity) => activity.id === selectedSession.linked_activity_id) || null;
      return {
        title: selectedSession.session_title,
        date: selectedSession.scheduled_date,
        sport: selectedSession.sport_type,
        duration: selectedSession.duration_min,
        distance: linkedActivity?.distance_m || null,
        elevation: linkedActivity?.elevation_m || null,
        avgHr: linkedActivity?.avg_hr || null,
        avgSpeed: linkedActivity?.avg_speed || null,
        mapPolyline: linkedActivity?.map_polyline || null,
        note: selectedSession.session_goal,
        loadBand: selectedSession.load_band,
        subtitle: sessionTypeLabel(selectedSession.session_type),
      };
    }
    if (selectedActivity) {
      return {
        title: selectedActivity.title,
        date: selectedActivity.started_at,
        sport: selectedActivity.sport_type,
        duration: selectedActivity.duration_min,
        distance: selectedActivity.distance_m,
        elevation: selectedActivity.elevation_m,
        avgHr: selectedActivity.avg_hr,
        avgSpeed: selectedActivity.avg_speed,
        mapPolyline: selectedActivity.map_polyline,
        note: selectedActivity.note || "Activité enregistrée dans FitMAS.",
        loadBand: selectedActivity.perceived_load && selectedActivity.perceived_load >= 4 ? "hard" : "moderate",
        subtitle: sportLabel(selectedActivity.sport_type),
      };
    }
    return null;
  }, [data, selectedActivity, selectedSession]);

  const close = () => {
    setSelectedSession(null);
    setSelectedActivity(null);
  };

  const routePath = buildSvgPath(decodePolyline(payload?.mapPolyline));
  const zones = buildZoneDistribution(payload?.loadBand);

  return (
    <AnimatePresence>
      {payload ? (
        <motion.div
          className="modal-backdrop"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={close}
        >
          <motion.div
            className="workout-modal"
            initial={{ opacity: 0, y: 40, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 30, scale: 0.98 }}
            transition={{ duration: 0.32, ease: [0.22, 1, 0.36, 1] }}
            onClick={(event) => event.stopPropagation()}
          >
            <button className="modal-close" type="button" onClick={close}>
              <X size={20} />
            </button>

            <div className="modal-date">{formatDateLong(payload.date || undefined)}</div>
            <div className="modal-title-row">
              <span className="modal-pulse" />
              <h3>{payload.title.toUpperCase()}</h3>
            </div>

            <div className="route-card">
              <div className="route-card-overlay" />
              {routePath ? (
                <svg viewBox="0 0 100 48" preserveAspectRatio="none">
                  <path d={routePath} className="route-line-shadow" />
                  <path d={routePath} className="route-line" />
                </svg>
              ) : (
                <div className="route-placeholder" />
              )}
            </div>

            <div className="modal-stat-grid">
              <div className="modal-stat-card">
                <Route size={16} />
                <strong>{formatDistance(payload.distance) || "—"}</strong>
              </div>
              <div className="modal-stat-card">
                <Clock3 size={16} />
                <strong>{payload.duration ? `${payload.duration} min` : "—"}</strong>
              </div>
              <div className="modal-stat-card">
                <Mountain size={16} />
                <strong>{payload.elevation ? `+${Math.round(payload.elevation)}m` : "—"}</strong>
              </div>
              <div className="modal-stat-card">
                <HeartPulse size={16} />
                <strong>{payload.avgHr ? `${Math.round(payload.avgHr)} bpm` : formatPace(payload.avgSpeed) || "—"}</strong>
              </div>
            </div>

            <div className="zone-card">
              <div className="zone-label-row">
                {["Z1", "Z2", "Z3", "Z4", "Z5"].map((zone) => (
                  <span key={zone}>{zone}</span>
                ))}
              </div>
              <div className="zone-bar">
                {zones.map((value, index) => (
                  <div
                    key={`${index}-${value}`}
                    className={`zone-segment zone-${index + 1}`}
                    style={{ width: `${value}%` }}
                  />
                ))}
              </div>
              <p>Répartition intensité estimée · {loadBandLabel(payload.loadBand)}</p>
            </div>

            <button className="primary-cta" type="button" onClick={close}>
              Détails complets
            </button>
            <p className="modal-note">{payload.subtitle} · {payload.note}</p>
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
