import useEmblaCarousel from "embla-carousel-react";
import { motion } from "motion/react";
import { ArrowUpRight, ChevronLeft, ChevronRight, RefreshCcw, Send } from "lucide-react";
import { type FormEvent, useState } from "react";
import { Link, type LoaderFunctionArgs, useLoaderData } from "react-router-dom";
import { loadOverview } from "../../shared/api";
import { formatDateLong, formatDateTime, loadBandLabel, percent, sportLabel } from "../../shared/format";
import { sessionBackdrop } from "../../shared/session-visuals";
import { useAppActions } from "../../state/app-actions";
import type { OverviewView } from "../../types";
import { overviewCompletionRatio, overviewHeroLabel, overviewHeroTitle } from "./view-model";

export async function overviewLoader(_: LoaderFunctionArgs) {
  return loadOverview();
}

export function OverviewPage() {
  const data = useLoaderData() as OverviewView;
  const { actOnSession, addActivity, runStravaSync, pendingKey } = useAppActions();
  const [emblaRef, emblaApi] = useEmblaCarousel({ loop: false, dragFree: true, align: "start" });
  const [submitting, setSubmitting] = useState(false);

  const leadSession = data.lead_session;
  const heroTitle = overviewHeroTitle(leadSession);
  const completionRatio = overviewCompletionRatio(data);

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
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-10 px-5 pb-12 md:px-8">
      <section
        className="surface-panel-strong relative min-h-[88vh] overflow-hidden rounded-[2.6rem] border border-white/10"
        style={{
          backgroundImage: `linear-gradient(180deg, rgba(0,0,0,0.18), rgba(0,0,0,0.76)), radial-gradient(circle at 50% 40%, rgba(103,232,249,0.22), transparent 22%), linear-gradient(90deg, rgba(3,5,7,0.88), rgba(3,5,7,0.26), rgba(3,5,7,0.88)), url("${sessionBackdrop(leadSession?.sport_type)}")`,
          backgroundSize: "cover",
          backgroundPosition: "center",
        }}
      >
        <div className="absolute inset-0 bg-[linear-gradient(180deg,rgba(255,255,255,0.02),transparent_20%,rgba(2,3,4,0.4)_100%)]" />
        <div className="relative flex min-h-[88vh] flex-col justify-between px-6 py-8 md:px-10 md:py-10">
          <div className="flex items-start justify-between gap-4">
            <div className="inline-flex items-center gap-2 rounded-full border border-cyan-300/20 bg-black/45 px-4 py-2 shadow-[0_0_18px_rgba(103,232,249,0.16)] backdrop-blur-md">
              <span className="h-2.5 w-2.5 rounded-full bg-cyan-300 shadow-[0_0_14px_rgba(103,232,249,0.65)]" />
              <span className="eyebrow">Séance du jour</span>
            </div>
            <div className="hidden items-center gap-2 md:flex">
              <span className="meta-chip">{data.week.label}</span>
              <span className="meta-chip">{Math.round(data.tss.target)} TSS cible</span>
            </div>
          </div>

          <motion.div
            initial={{ opacity: 0, y: 34 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.55, ease: [0.22, 1, 0.36, 1] }}
            className="max-w-5xl"
          >
            <p className="eyebrow mb-5">{overviewHeroLabel(data)}</p>
            <div className="flex flex-wrap items-end gap-x-4 gap-y-1">
              <h1 className="text-[clamp(3.8rem,13vw,9rem)] font-bold uppercase leading-[0.88] tracking-[-0.09em] text-white">
                {heroTitle.title}
              </h1>
              <span className="text-[clamp(2.5rem,9vw,5.8rem)] font-light tracking-[-0.08em] text-white/38">
                {heroTitle.suffix}
              </span>
            </div>
            <p className="mt-6 max-w-2xl text-lg font-medium leading-relaxed text-white/72 md:text-2xl">
              {leadSession?.goal || "Le cockpit est prêt. Appuie-toi sur la séance phare du jour et la vision bloc pour tenir la semaine."}
            </p>

            <div className="mt-8 flex flex-wrap gap-3">
              {leadSession ? (
                <Link to={`/workout/${leadSession.id}`} className="action-button-primary">
                  Détails complets <ArrowUpRight className="ml-2 h-4 w-4" />
                </Link>
              ) : null}
              {data.today ? (
                <>
                  <button
                    type="button"
                    className="action-button-ghost"
                    onClick={() => void actOnSession("done", data.today!.scheduled_session_id)}
                    disabled={pendingKey === `done:${data.today.scheduled_session_id}`}
                  >
                    Fait
                  </button>
                  <button
                    type="button"
                    className="action-button-ghost"
                    onClick={() => void actOnSession("skip", data.today!.scheduled_session_id)}
                    disabled={pendingKey === `skip:${data.today.scheduled_session_id}`}
                  >
                    Fatigué
                  </button>
                  <button
                    type="button"
                    className="action-button-ghost"
                    onClick={() => void actOnSession("move", data.today!.scheduled_session_id)}
                    disabled={pendingKey === `move:${data.today.scheduled_session_id}`}
                  >
                    Décaler
                  </button>
                </>
              ) : null}
            </div>
          </motion.div>

          <div className="grid gap-4 md:grid-cols-3">
            <div className="surface-panel bg-black/35 p-5">
              <p className="eyebrow">Bloc actif</p>
              <div className="mt-4 text-3xl font-bold tracking-[-0.06em]">{data.week.label}</div>
              <p className="mt-2 soft-copy">Volume planifié {data.weekly_hours.toFixed(1)} h</p>
            </div>
            <div className="surface-panel bg-black/35 p-5">
              <p className="eyebrow">Charge semaine</p>
              <div className="mt-4 flex items-end gap-2">
                <span className="text-4xl font-bold tracking-[-0.06em]">{Math.round(data.tss.actual)}</span>
                <span className="pb-1 text-white/45">/ {Math.round(data.tss.target)} TSS</span>
              </div>
              <p className="mt-2 soft-copy">Ramp rate {data.load.ramp_rate}</p>
            </div>
            <div className="surface-panel bg-black/35 p-5">
              <p className="eyebrow">Exécution</p>
              <div className="mt-4 text-4xl font-bold tracking-[-0.06em]">{percent(completionRatio)}</div>
              <p className="mt-2 soft-copy">
                {data.completion.done_this_week} / {data.completion.sessions_this_week} séances bouclées
              </p>
            </div>
          </div>
        </div>
      </section>

      <section className="flex flex-col gap-6">
        <div className="flex items-center justify-between">
          <div>
            <p className="eyebrow">Programme semaine</p>
            <h2 className="mt-2 text-3xl font-bold tracking-[-0.06em] text-white md:text-5xl">
              Prochaines <span className="text-cyan-200">séances</span>
            </h2>
          </div>
          <div className="hidden gap-3 md:flex">
            <button type="button" className="action-button-ghost h-12 w-12 rounded-full p-0" onClick={() => emblaApi?.scrollPrev()}>
              <ChevronLeft className="h-5 w-5" />
            </button>
            <button type="button" className="action-button-ghost h-12 w-12 rounded-full p-0" onClick={() => emblaApi?.scrollNext()}>
              <ChevronRight className="h-5 w-5" />
            </button>
          </div>
        </div>

        <div className="overflow-hidden" ref={emblaRef}>
          <div className="-ml-5 flex">
            {data.upcoming_sessions.map((session, index) => (
              <motion.div
                key={`${session.kind}-${session.id}`}
                initial={{ opacity: 0, y: 24, scale: 0.97 }}
                whileInView={{ opacity: 1, y: 0, scale: 1 }}
                viewport={{ once: true, margin: "-10%" }}
                transition={{ duration: 0.42, delay: index * 0.06 }}
                className="min-w-0 flex-[0_0_88%] pl-5 md:flex-[0_0_42%] xl:flex-[0_0_32%]"
              >
                <Link
                  to={`/workout/${session.id}`}
                  className="group relative flex h-[25rem] flex-col justify-between overflow-hidden rounded-[2.3rem] border border-white/10 bg-black/55 p-6 shadow-[0_24px_80px_rgba(0,0,0,0.35)]"
                  style={{
                    backgroundImage: `linear-gradient(180deg,rgba(0,0,0,0.16),rgba(0,0,0,0.84)), url("${sessionBackdrop(session.sport_type)}")`,
                    backgroundSize: "cover",
                    backgroundPosition: "center",
                  }}
                >
                  <div className="flex items-start justify-between gap-3">
                    <span className="meta-chip">{session.label}</span>
                    <span className="inline-flex h-11 w-11 items-center justify-center rounded-full border border-cyan-300/30 bg-black/45 text-cyan-200 transition group-hover:rotate-45">
                      <ArrowUpRight className="h-4 w-4" />
                    </span>
                  </div>
                  <div>
                    <div className="text-4xl font-bold uppercase tracking-[-0.07em] text-white">{session.title}</div>
                    <p className="mt-3 max-w-sm text-sm font-medium leading-relaxed text-white/70">{session.goal}</p>
                    <div className="mt-5 flex flex-wrap gap-2">
                      <span className="meta-chip">{sportLabel(session.sport_type)}</span>
                      <span className="meta-chip">{session.duration_min ? `${session.duration_min} min` : "Libre"}</span>
                      <span className="meta-chip">{loadBandLabel(session.load_band)}</span>
                    </div>
                  </div>
                </Link>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      <section id="utility" className="grid gap-5 lg:grid-cols-[1.05fr_0.95fr]">
        <div className="grid gap-5">
          <article className="surface-panel p-6">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <p className="eyebrow">Sync réel</p>
                <h3 className="mt-2 text-2xl font-bold tracking-[-0.05em]">
                  {data.strava.connected ? "Strava connecté" : "Import d'activités"}
                </h3>
                <p className="mt-3 max-w-xl soft-copy">
                  {data.strava.connected
                    ? `Dernière synchro ${formatDateTime(data.strava.last_sync_at || undefined)}`
                    : data.strava.configured
                      ? "Branche Strava pour alimenter automatiquement prévu vs réalisé."
                      : "Le serveur ne dispose pas encore de Strava."}
                </p>
              </div>
              {data.strava.connected ? (
                <button
                  type="button"
                  className="action-button-primary"
                  onClick={() => void runStravaSync()}
                  disabled={pendingKey === "sync-strava"}
                >
                  <RefreshCcw className="mr-2 h-4 w-4" />
                  Synchroniser
                </button>
              ) : data.strava.configured ? (
                <a href="/api/v0/strava/auth" className="action-button-primary">
                  Connecter Strava
                </a>
              ) : null}
            </div>
          </article>

          <article className="surface-panel p-6">
            <p className="eyebrow">Profil cockpit</p>
            <div className="mt-4 grid gap-5 md:grid-cols-[1fr_auto]">
              <div>
                <h3 className="text-3xl font-bold tracking-[-0.06em]">{data.profile.name}</h3>
                <p className="mt-3 max-w-xl soft-copy">
                  {data.profile.objective || "Objectif non précisé"} · coach {data.profile.coach_name || "FitMAS"}
                </p>
                <div className="mt-5 flex flex-wrap gap-2">
                  {data.profile.sports.map((sport) => (
                    <span key={sport} className="meta-chip">{sportLabel(sport)}</span>
                  ))}
                </div>
              </div>
              <div className="rounded-[1.6rem] border border-white/10 bg-white/[0.03] p-4 text-right">
                <p className="eyebrow">Freshness</p>
                <div className="mt-3 text-4xl font-bold tracking-[-0.06em]">{data.load.tsb.toFixed(1)}</div>
                <p className="mt-2 text-sm text-cyan-200">{data.load.freshness}</p>
              </div>
            </div>
          </article>
        </div>

        <article className="surface-panel p-6">
          <p className="eyebrow">Log manuel</p>
          <h3 className="mt-2 text-3xl font-bold tracking-[-0.06em]">Ajouter une activité</h3>
          <p className="mt-3 soft-copy">Surface utilitaire secondaire. Le cockpit reste centré sur le plan et l’exécution.</p>
          <form className="mt-6 grid gap-3" onSubmit={handleActivitySubmit}>
            <div className="grid gap-3 sm:grid-cols-2">
              <select name="sport_type" defaultValue="running" className="rounded-2xl border border-white/10 bg-white/[0.04] px-4 py-3 text-white">
                <option value="running">Course</option>
                <option value="cycling">Vélo</option>
                <option value="swimming">Natation</option>
                <option value="climbing">Escalade</option>
                <option value="strength">Renfo</option>
              </select>
              <input name="duration_min" type="number" min="0" placeholder="Durée (min)" className="rounded-2xl border border-white/10 bg-white/[0.04] px-4 py-3 text-white placeholder:text-white/30" />
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <input name="distance_m" type="number" min="0" placeholder="Distance (m)" className="rounded-2xl border border-white/10 bg-white/[0.04] px-4 py-3 text-white placeholder:text-white/30" />
              <select name="perceived_load" defaultValue="" className="rounded-2xl border border-white/10 bg-white/[0.04] px-4 py-3 text-white">
                <option value="">Charge ressentie</option>
                <option value="1">1</option>
                <option value="2">2</option>
                <option value="3">3</option>
                <option value="4">4</option>
                <option value="5">5</option>
              </select>
            </div>
            <input name="started_at" type="datetime-local" className="rounded-2xl border border-white/10 bg-white/[0.04] px-4 py-3 text-white" />
            <textarea name="note" rows={4} placeholder="Note rapide" className="rounded-[1.4rem] border border-white/10 bg-white/[0.04] px-4 py-3 text-white placeholder:text-white/30" />
            <button type="submit" className="action-button-primary w-full" disabled={submitting || pendingKey === "add-activity"}>
              <Send className="mr-2 h-4 w-4" />
              {submitting || pendingKey === "add-activity" ? "Ajout…" : "Ajouter l'activité"}
            </button>
          </form>
        </article>
      </section>
    </div>
  );
}
