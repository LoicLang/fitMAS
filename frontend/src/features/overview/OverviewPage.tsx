import { motion } from "motion/react";
import { Activity, ArrowUpRight, Check, Clock3, MoveRight, RefreshCcw, Send } from "lucide-react";
import { type FormEvent, useState } from "react";
import { Link, type LoaderFunctionArgs, useLoaderData } from "react-router-dom";
import { loadOverview } from "../../shared/api";
import { formatDateShort, formatDateTime, loadBandLabel, percent, sportLabel } from "../../shared/format";
import { sessionBackdrop } from "../../shared/session-visuals";
import { useAppActions } from "../../state/app-actions";
import type { CalendarItem, OverviewView } from "../../types";
import { overviewCompletionRatio, overviewHeroTitle } from "./view-model";

export async function overviewLoader(_: LoaderFunctionArgs) {
  return loadOverview();
}

export function OverviewPage() {
  const data = useLoaderData() as OverviewView;
  const { actOnSession, addActivity, runStravaSync, pendingKey } = useAppActions();
  const [submitting, setSubmitting] = useState(false);

  const leadSession = data.lead_session;
  const title = overviewHeroTitle(leadSession);
  const completionRatio = overviewCompletionRatio(data);
  const upcoming = leadSession
    ? [leadSession, ...data.upcoming_sessions.filter((session) => session.id !== leadSession.id)].slice(0, 5)
    : data.upcoming_sessions.slice(0, 5);

  async function handleActivitySubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setSubmitting(true);
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
      setSubmitting(false);
    }
  }

  return (
    <div className="min-h-screen px-5 pb-24 pt-6 md:px-8">
      <div className="mx-auto max-w-6xl">
        <motion.header
          initial={{ opacity: 0, y: 18 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.45 }}
          className="mb-6"
        >
          <p className="eyebrow">À venir</p>
          <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h1 className="text-5xl font-black uppercase tracking-[-0.06em] text-zinc-950 md:text-7xl">{title.title}</h1>
              <p className="mt-2 max-w-2xl text-base font-medium leading-relaxed text-zinc-600">
                {data.today?.session_note || leadSession?.goal || "La prochaine séance utile, claire et prête à lancer."}
              </p>
            </div>
            <div className="grid grid-cols-3 gap-2 sm:min-w-[22rem]">
              <Metric label="Semaine" value={data.week.label} />
              <Metric label="Réalisé" value={percent(completionRatio)} />
              <Metric label="Forme" value={data.load.freshness} />
            </div>
          </div>
        </motion.header>

        {leadSession ? (
          <section className="grid gap-4 lg:grid-cols-[1.08fr_0.92fr]">
            <LeadWorkoutCard
              session={leadSession}
              today={data.today}
              pendingKey={pendingKey}
              onDone={(sessionId) => void actOnSession("done", sessionId)}
              onSkip={(sessionId) => void actOnSession("skip", sessionId)}
              onMove={(sessionId) => void actOnSession("move", sessionId)}
            />

            <article className="surface-panel p-5 md:p-6">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="eyebrow">Planning</p>
                  <h2 className="mt-2 text-2xl font-black tracking-[-0.04em] text-zinc-950">Prochaines séances</h2>
                </div>
                <Link to="/calendar" className="action-button-ghost px-4 py-2">
                  Calendrier
                </Link>
              </div>
              <div className="mt-5 grid gap-3">
                {upcoming.map((session) => (
                  <CompactSessionRow key={`${session.kind}-${session.id}-${session.display_date}`} session={session} />
                ))}
              </div>
            </article>
          </section>
        ) : (
          <section className="surface-panel p-6">
            <h2 className="text-3xl font-black tracking-[-0.05em] text-zinc-950">Aucune séance imminente</h2>
            <p className="mt-2 text-base font-medium text-zinc-600">Le calendrier reste disponible pour relire le plan.</p>
            <Link to="/calendar" className="action-button-primary mt-5">
              Ouvrir le planning
            </Link>
          </section>
        )}

        <section className="mt-5 grid gap-4 lg:grid-cols-[0.9fr_1.1fr]">
          <article className="surface-panel p-5 md:p-6">
            <p className="eyebrow">Accès rapide</p>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <Link to="/calendar" className="rounded-[1.4rem] border border-black/6 bg-zinc-50/80 p-4 transition hover:bg-white">
                <Clock3 className="h-5 w-5 text-[var(--accent)]" />
                <p className="mt-3 text-lg font-black tracking-[-0.03em] text-zinc-950">Planning</p>
                <p className="mt-1 text-sm font-medium text-zinc-500">Prévu, fait, manqué.</p>
              </Link>
              <Link to="/evolution" className="rounded-[1.4rem] border border-black/6 bg-zinc-50/80 p-4 transition hover:bg-white">
                <Activity className="h-5 w-5 text-[var(--accent-alt)]" />
                <p className="mt-3 text-lg font-black tracking-[-0.03em] text-zinc-950">Progression</p>
                <p className="mt-1 text-sm font-medium text-zinc-500">Charge et tendance.</p>
              </Link>
            </div>
            <div className="mt-5 flex flex-wrap items-center gap-3">
              {data.strava.connected ? (
                <button type="button" className="action-button-primary" onClick={() => void runStravaSync()} disabled={pendingKey === "sync-strava"}>
                  <RefreshCcw className="mr-2 h-4 w-4" />
                  Synchroniser Strava
                </button>
              ) : data.strava.configured ? (
                <a href="/api/v0/strava/auth" className="action-button-primary">
                  Connecter Strava
                </a>
              ) : null}
              <span className="soft-copy text-sm">
                {data.strava.connected ? `Dernière synchro ${formatDateTime(data.strava.last_sync_at || undefined)}` : "Strava ou log manuel."}
              </span>
            </div>
          </article>

          <article className="surface-panel p-5 md:p-6">
            <p className="eyebrow">Log manuel</p>
            <form className="mt-4 grid gap-3" onSubmit={handleActivitySubmit}>
              <div className="grid gap-3 sm:grid-cols-2">
                <select name="sport_type" defaultValue="running" className="rounded-2xl border border-black/6 bg-zinc-50 px-4 py-3 text-zinc-900">
                  <option value="running">Course</option>
                  <option value="cycling">Vélo</option>
                  <option value="swimming">Natation</option>
                  <option value="climbing">Escalade</option>
                  <option value="strength">Renfo</option>
                </select>
                <input name="duration_min" type="number" min="0" placeholder="Durée (min)" className="rounded-2xl border border-black/6 bg-zinc-50 px-4 py-3 text-zinc-900 placeholder:text-zinc-400" />
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <input name="distance_m" type="number" min="0" placeholder="Distance (m)" className="rounded-2xl border border-black/6 bg-zinc-50 px-4 py-3 text-zinc-900 placeholder:text-zinc-400" />
                <select name="perceived_load" defaultValue="" className="rounded-2xl border border-black/6 bg-zinc-50 px-4 py-3 text-zinc-900">
                  <option value="">Ressenti</option>
                  <option value="1">1 facile</option>
                  <option value="2">2</option>
                  <option value="3">3 moyen</option>
                  <option value="4">4</option>
                  <option value="5">5 dur</option>
                </select>
              </div>
              <input name="started_at" type="datetime-local" className="rounded-2xl border border-black/6 bg-zinc-50 px-4 py-3 text-zinc-900" />
              <textarea name="note" rows={3} placeholder="Note rapide" className="rounded-[1.4rem] border border-black/6 bg-zinc-50 px-4 py-3 text-zinc-900 placeholder:text-zinc-400" />
              <button type="submit" className="action-button-primary w-full" disabled={submitting || pendingKey === "add-activity"}>
                <Send className="mr-2 h-4 w-4" />
                {submitting || pendingKey === "add-activity" ? "Ajout..." : "Ajouter"}
              </button>
            </form>
          </article>
        </section>
      </div>
    </div>
  );
}

function LeadWorkoutCard({
  session,
  today,
  pendingKey,
  onDone,
  onSkip,
  onMove,
}: {
  session: CalendarItem;
  today: OverviewView["today"];
  pendingKey: string | null;
  onDone: (sessionId: number) => void;
  onSkip: (sessionId: number) => void;
  onMove: (sessionId: number) => void;
}) {
  return (
    <article className="surface-panel overflow-hidden">
      <div className="relative h-52 md:h-64">
        <img src={sessionBackdrop(session.sport_type)} alt={session.title} className="h-full w-full object-cover" />
        <div className="absolute inset-0 bg-gradient-to-t from-black/70 via-black/20 to-transparent" />
        <div className="absolute inset-x-0 bottom-0 p-5 text-white md:p-6">
          <div className="flex flex-wrap gap-2">
            <Pill dark>{session.label || formatDateShort(session.display_date || session.scheduled_date)}</Pill>
            <Pill dark>{sportLabel(session.sport_type)}</Pill>
            <Pill dark>{session.duration_min ? `${session.duration_min} min` : "Libre"}</Pill>
          </div>
          <h2 className="mt-4 text-4xl font-black uppercase tracking-[-0.06em] md:text-5xl">{session.title}</h2>
        </div>
      </div>
      <div className="p-5 md:p-6">
        <p className="text-base font-medium leading-relaxed text-zinc-600">{today?.session_goal || session.goal}</p>
        <div className="mt-4 flex flex-wrap gap-2">
          <Pill>{statusLabel(session.status)}</Pill>
          <Pill>{loadBandLabel(session.load_band)}</Pill>
          {session.role ? <Pill>{roleLabel(session.role)}</Pill> : null}
          {session.confidence ? <Pill>{confidenceLabel(session.confidence)}</Pill> : null}
        </div>
        <div className="mt-5 flex flex-wrap gap-3">
          <Link to={`/workout/${session.id}`} className="action-button-primary">
            Ouvrir la séance
            <ArrowUpRight className="ml-2 h-4 w-4" />
          </Link>
          {today ? (
            <>
              <button type="button" className="action-button-ghost" onClick={() => onDone(today.scheduled_session_id)} disabled={pendingKey === `done:${today.scheduled_session_id}`}>
                <Check className="mr-2 h-4 w-4" />
                Fait
              </button>
              <button type="button" className="action-button-ghost" onClick={() => onSkip(today.scheduled_session_id)} disabled={pendingKey === `skip:${today.scheduled_session_id}`}>
                Fatigué
              </button>
              <button type="button" className="action-button-ghost" onClick={() => onMove(today.scheduled_session_id)} disabled={pendingKey === `move:${today.scheduled_session_id}`}>
                Décaler
              </button>
            </>
          ) : null}
        </div>
      </div>
    </article>
  );
}

function CompactSessionRow({ session }: { session: CalendarItem }) {
  return (
    <Link to={`/workout/${session.id}`} className="group flex items-center gap-3 rounded-[1.4rem] border border-black/6 bg-zinc-50/80 p-3 transition hover:bg-white">
      <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-white text-lg font-black text-[var(--accent)] shadow-sm">
        {formatDateShort(session.display_date || session.scheduled_date).split(" ").slice(0, 2).join(" ")}
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-base font-black tracking-[-0.03em] text-zinc-950">{session.title}</p>
        <p className="mt-1 truncate text-sm font-medium text-zinc-500">
          {sportLabel(session.sport_type)} · {session.duration_min ? `${session.duration_min} min` : "Libre"} · {loadBandLabel(session.load_band)}
        </p>
      </div>
      <MoveRight className="h-5 w-5 shrink-0 text-zinc-400 transition group-hover:text-[var(--accent)]" />
    </Link>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[1.2rem] border border-black/6 bg-white/70 p-3 shadow-sm backdrop-blur-xl">
      <p className="text-[0.64rem] font-bold uppercase tracking-[0.16em] text-zinc-500">{label}</p>
      <p className="mt-1 truncate text-lg font-black tracking-[-0.04em] text-zinc-950">{value}</p>
    </div>
  );
}

function Pill({ children, dark = false }: { children: string; dark?: boolean }) {
  return (
    <span className={`rounded-full px-3 py-1.5 text-xs font-bold uppercase tracking-[0.12em] ${dark ? "bg-white/18 text-white backdrop-blur" : "border border-black/6 bg-zinc-50 text-zinc-700"}`}>
      {children}
    </span>
  );
}

function statusLabel(status: string) {
  if (status === "planned") return "prévu";
  if (status === "adapted") return "adapté";
  if (status === "done") return "fait";
  if (status === "missing") return "manqué";
  if (status === "offplan") return "hors plan";
  return status;
}

function confidenceLabel(confidence: string) {
  if (confidence === "committed") return "ferme";
  if (confidence === "tentative") return "probable";
  return "projeté";
}

function roleLabel(role: string) {
  if (role === "key") return "clé";
  if (role === "support") return "support";
  if (role === "recovery") return "récup";
  if (role === "optional") return "option";
  return role;
}
