import { useAppState } from "../state/app-state";
import { sportLabel } from "../lib/format";

export function ProfilePage() {
  const { data } = useAppState();

  if (!data) return null;

  return (
    <section className="two-col-page">
      <article className="glass-card">
        <span className="card-label">Profil</span>
        <h2>{data.profile.name}</h2>
        <p className="muted-copy">{data.profile.objective || data.profile.primary_objective}</p>
        <div className="pill-row">
          {data.profile.sports.map((sport) => (
            <span key={sport} className="meta-chip">{sportLabel(sport)}</span>
          ))}
        </div>
      </article>

      <article className="glass-card">
        <span className="card-label">Coach</span>
        <h2>{data.profile.coach_name || "FitMAS"}</h2>
        <div className="detail-list">
          <div><span>Style</span><strong>{data.profile.coach_style || "—"}</strong></div>
          <div><span>Do</span><strong>{data.profile.coach_do || "—"}</strong></div>
          <div><span>Don't</span><strong>{data.profile.coach_dont || "—"}</strong></div>
          <div><span>Âme</span><strong>{data.profile.coach_soul || "—"}</strong></div>
        </div>
      </article>

      <article className="glass-card">
        <span className="card-label">Contraintes</span>
        <ul className="bullet-list">
          {(data.profile.constraints.length ? data.profile.constraints : ["Aucune contrainte renseignée."]).map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </article>

      <article className="glass-card">
        <span className="card-label">Préférences</span>
        <ul className="bullet-list">
          {(data.profile.preferences.length ? data.profile.preferences : ["Aucune préférence renseignée."]).map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </article>
    </section>
  );
}
