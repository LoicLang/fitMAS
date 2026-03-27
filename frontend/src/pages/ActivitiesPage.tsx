import { useState } from "react";
import { useAppState } from "../state/app-state";
import { formatDateTime, formatDistance, formatPace, sportLabel } from "../lib/format";

export function ActivitiesPage() {
  const { data, addActivity, runStravaSync, setSelectedActivity } = useAppState();
  const [pending, setPending] = useState(false);

  if (!data) return null;

  return (
    <section className="two-col-page">
      <article className="glass-card form-card">
        <span className="card-label">Journal réel</span>
        <h2>Logger une activité</h2>
        <form
          className="activity-form"
          onSubmit={async (event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            setPending(true);
            try {
              await addActivity({
                sport_type: form.get("sport_type"),
                duration_min: form.get("duration_min") ? Number(form.get("duration_min")) : null,
                distance_m: form.get("distance_m") ? Number(form.get("distance_m")) : null,
                perceived_load: form.get("perceived_load") ? Number(form.get("perceived_load")) : null,
                note: String(form.get("note") || ""),
                started_at: form.get("started_at") ? new Date(String(form.get("started_at"))).toISOString() : null,
              });
              event.currentTarget.reset();
            } finally {
              setPending(false);
            }
          }}
        >
          <select name="sport_type" defaultValue="running">
            <option value="running">Course</option>
            <option value="cycling">Vélo</option>
            <option value="swimming">Natation</option>
            <option value="climbing">Escalade</option>
            <option value="strength">Renfo</option>
          </select>
          <input name="duration_min" type="number" min="0" placeholder="Durée (min)" />
          <input name="distance_m" type="number" min="0" placeholder="Distance (m)" />
          <select name="perceived_load" defaultValue="">
            <option value="">Charge ressentie</option>
            <option value="1">1</option>
            <option value="2">2</option>
            <option value="3">3</option>
            <option value="4">4</option>
            <option value="5">5</option>
          </select>
          <input name="started_at" type="datetime-local" />
          <textarea name="note" placeholder="Note rapide" rows={4} />
          <button className="primary-cta" type="submit" disabled={pending}>
            {pending ? "Ajout…" : "Ajouter l'activité"}
          </button>
        </form>
      </article>

      <div className="stacked-column">
        <article className="glass-card">
          <span className="card-label">Strava</span>
          <h2>{data.stravaStatus.connected ? "Connecté" : "Connexion"}</h2>
          <p className="muted-copy">
            {data.stravaStatus.connected
              ? `Dernière synchro: ${formatDateTime(data.stravaStatus.last_sync_at || undefined)}`
              : data.stravaStatus.configured
                ? "Connecte Strava pour importer tes activités automatiquement."
                : "Strava n'est pas configuré sur ce serveur."}
          </p>
          {data.stravaStatus.connected ? (
            <button className="ghost-cta" type="button" onClick={() => void runStravaSync()}>Synchroniser</button>
          ) : data.stravaStatus.configured ? (
            <a className="primary-cta link-button" href="/api/v0/strava/auth">Connecter Strava</a>
          ) : null}
        </article>

        <article className="glass-card">
          <span className="card-label">Journal</span>
          <div className="activity-list">
            {data.activities.map((activity) => (
              <button key={activity.id} className="activity-card" type="button" onClick={() => setSelectedActivity(activity)}>
                <div>
                  <strong>{activity.title}</strong>
                  <span>{sportLabel(activity.sport_type)} · {formatDateTime(activity.started_at || undefined)}</span>
                </div>
                <small>
                  {[activity.duration_min ? `${activity.duration_min} min` : null, formatDistance(activity.distance_m), formatPace(activity.avg_speed)].filter(Boolean).join(" · ")}
                </small>
              </button>
            ))}
          </div>
        </article>
      </div>
    </section>
  );
}
