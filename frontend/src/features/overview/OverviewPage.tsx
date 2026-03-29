import useEmblaCarousel from "embla-carousel-react";
import { motion, useScroll, useTransform } from "motion/react";
import { Activity, ArrowUpRight, ChevronLeft, ChevronRight, RefreshCcw, Send } from "lucide-react";
import { type FormEvent, useRef, useState } from "react";
import { Link, type LoaderFunctionArgs, useLoaderData, useNavigate } from "react-router-dom";
import { loadOverview } from "../../shared/api";
import { formatDateTime, loadBandLabel, percent, sportLabel } from "../../shared/format";
import { sessionBackdrop } from "../../shared/session-visuals";
import { useAppActions } from "../../state/app-actions";
import type { OverviewView } from "../../types";
import { overviewCompletionRatio, overviewHeroLabel, overviewHeroTitle } from "./view-model";

export async function overviewLoader(_: LoaderFunctionArgs) {
  return loadOverview();
}

export function OverviewPage() {
  const data = useLoaderData() as OverviewView;
  const navigate = useNavigate();
  const { actOnSession, addActivity, runStravaSync, pendingKey } = useAppActions();
  const [emblaRef, emblaApi] = useEmblaCarousel({ loop: false, dragFree: true, align: "start" });
  const [submitting, setSubmitting] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const { scrollYProgress } = useScroll({ target: containerRef });
  const sectionsY = useTransform(scrollYProgress, [0, 1], ["0px", "-100px"]);

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
    <div className="relative flex w-full flex-col overflow-hidden selection:bg-[var(--accent)] selection:text-white" ref={containerRef}>
      <section className="relative flex min-h-[calc(100vh-4rem)] flex-col items-center justify-center px-6 pb-10 pt-8">
        <div className="mx-auto flex h-[60vh] w-full max-w-7xl flex-col justify-between gap-10 md:h-[70vh]">
          <motion.div
            initial={{ opacity: 0, x: -36 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.75, ease: [0.2, 0.65, 0.3, 0.9] }}
            className="self-start pt-8 md:pt-12"
          >
            <div className="inline-flex items-center gap-2 rounded-full border border-black/8 bg-white/70 px-4 py-2 shadow-sm backdrop-blur-md">
              <span className="h-2 w-2 rounded-full bg-[var(--accent)] shadow-[0_0_10px_rgba(255,107,53,0.45)]" />
              <span className="eyebrow">{data.today ? "Séance du jour" : "Prochaine séance"}</span>
            </div>
            <p className="mt-8 text-sm font-bold uppercase tracking-[0.3em] text-zinc-500">{overviewHeroLabel(data)}</p>
            <h1 className="mt-4 text-[clamp(4.2rem,16vw,9rem)] font-black uppercase tracking-[-0.09em] text-zinc-950">
              {heroTitle.title}
            </h1>
          </motion.div>

          <div className="pointer-events-none flex flex-1 items-center justify-center">
            <motion.div
              initial={{ opacity: 0, scale: 0.85 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ duration: 0.8, delay: 0.2 }}
              className="relative flex h-40 w-40 items-center justify-center rounded-full border border-black/6 bg-white/35 shadow-[0_16px_50px_rgba(0,0,0,0.06)] backdrop-blur-md md:h-64 md:w-64"
            >
              <div className="absolute inset-6 rounded-full border border-black/5" />
              <div className="absolute h-24 w-24 rounded-full bg-[rgba(255,107,53,0.18)] blur-3xl md:h-36 md:w-36" />
              <div className="relative text-center">
                <Activity className="mx-auto h-8 w-8 text-[var(--accent)] md:h-12 md:w-12" />
                <div className="mt-4 text-3xl font-black tracking-[-0.06em] text-zinc-950 md:text-5xl">{Math.round(data.tss.actual)}</div>
                <div className="mt-1 text-xs font-bold uppercase tracking-[0.24em] text-zinc-500">TSS réel</div>
              </div>
            </motion.div>
          </div>

          <motion.div
            initial={{ opacity: 0, x: 36 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.75, delay: 0.08, ease: [0.2, 0.65, 0.3, 0.9] }}
            className="hidden self-end text-right md:block"
          >
            <h2 className="text-[clamp(3rem,10vw,7rem)] font-light uppercase tracking-[-0.08em] text-zinc-700">
              {heroTitle.suffix}
            </h2>
            <p className="mt-4 max-w-sm text-lg font-medium text-zinc-500">
              {leadSession?.goal || "L’aperçu se recentre sur la séance utile et les prochains jours à fort impact."}
            </p>
          </motion.div>
        </div>

        <motion.div
          initial={{ opacity: 0, y: 18 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.4 }}
          className="absolute bottom-24 left-1/2 z-10 flex w-[calc(100%-3rem)] max-w-md -translate-x-1/2 flex-wrap items-center justify-center gap-3 md:bottom-8 md:w-auto md:max-w-none"
        >
          {leadSession ? (
            <button
              type="button"
              onClick={() => navigate(`/workout/${leadSession.id}`)}
              className="relative flex items-center justify-center gap-3 rounded-full border border-black/6 bg-white/80 px-7 py-4 text-sm font-bold uppercase tracking-[0.1em] text-zinc-900 shadow-lg backdrop-blur-xl transition active:scale-95"
            >
              <span className="h-2 w-2 rounded-full bg-[var(--accent)]" />
              <span>Détails séance</span>
              <ArrowUpRight className="h-5 w-5 text-[var(--accent)]" />
            </button>
          ) : null}
          {data.today ? (
            <>
              <button
                type="button"
                className="hidden md:inline-flex action-button-ghost"
                onClick={() => void actOnSession("done", data.today!.scheduled_session_id)}
                disabled={pendingKey === `done:${data.today.scheduled_session_id}`}
              >
                Fait
              </button>
              <button
                type="button"
                className="hidden md:inline-flex action-button-ghost"
                onClick={() => void actOnSession("skip", data.today!.scheduled_session_id)}
                disabled={pendingKey === `skip:${data.today.scheduled_session_id}`}
              >
                Fatigué
              </button>
              <button
                type="button"
                className="hidden md:inline-flex action-button-ghost"
                onClick={() => void actOnSession("move", data.today!.scheduled_session_id)}
                disabled={pendingKey === `move:${data.today.scheduled_session_id}`}
              >
                Décaler
              </button>
            </>
          ) : null}
        </motion.div>
      </section>

      {data.week_context ? (
        <motion.section
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.15 }}
          className="relative z-10 px-6 pb-10"
        >
          <div className="mx-auto max-w-7xl">
            <div className="rounded-[2rem] border border-black/5 bg-white p-6 shadow-sm md:p-8">
              <div className="flex flex-col gap-6 md:flex-row md:items-start md:gap-10">
                <div className="flex-1">
                  <p className="eyebrow">Lecture coach</p>
                  <p className="mt-4 text-lg font-medium text-zinc-700 leading-relaxed">
                    {data.week_context.coach_reading}
                  </p>
                </div>
                <div className="grid grid-cols-2 gap-3 md:w-72 md:shrink-0">
                  <div className="rounded-[1.2rem] border border-black/6 bg-zinc-50/80 p-4">
                    <p className="text-[0.65rem] font-bold uppercase tracking-[0.18em] text-zinc-500">Cycle</p>
                    <div className="mt-2 text-2xl font-black tracking-[-0.04em] text-zinc-950">{data.week_context.planning.cycle_position}</div>
                  </div>
                  <div className="rounded-[1.2rem] border border-black/6 bg-zinc-50/80 p-4">
                    <p className="text-[0.65rem] font-bold uppercase tracking-[0.18em] text-zinc-500">Mode</p>
                    <div className="mt-2 text-2xl font-black tracking-[-0.04em] text-zinc-950">{data.week_context.planning.mode}</div>
                  </div>
                  <div className="rounded-[1.2rem] border border-black/6 bg-zinc-50/80 p-4">
                    <p className="text-[0.65rem] font-bold uppercase tracking-[0.18em] text-zinc-500">Séances</p>
                    <div className="mt-2 text-2xl font-black tracking-[-0.04em] text-zinc-950">{data.week_context.summary.done}/{data.week_context.summary.total_sessions}</div>
                  </div>
                  <div className="rounded-[1.2rem] border border-black/6 bg-zinc-50/80 p-4">
                    <p className="text-[0.65rem] font-bold uppercase tracking-[0.18em] text-zinc-500">S+1</p>
                    <div className="mt-2 text-2xl font-black tracking-[-0.04em] text-zinc-950">{data.week_context.next_week.focus}</div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </motion.section>
      ) : null}

      <motion.section
        style={{ y: sectionsY }}
        initial={{ opacity: 0, y: 24 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.75, delay: 0.2 }}
        className="relative z-10 overflow-hidden px-6 pb-20"
      >
        <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-transparent to-[#f8f9fa]" />
        <div className="mx-auto max-w-7xl">
          <div className="mb-12 flex items-center justify-between">
            <h2 className="text-4xl font-light tracking-tight text-zinc-950">
              Cycle <span className="font-black">Hebdomadaire</span>
            </h2>
            <div className="hidden gap-3 md:flex">
              <button type="button" onClick={() => emblaApi?.scrollPrev()} className="flex h-12 w-12 items-center justify-center rounded-full border border-black/8 bg-white/70 text-zinc-900 shadow-sm transition hover:bg-white">
                <ChevronLeft className="h-5 w-5" />
              </button>
              <button type="button" onClick={() => emblaApi?.scrollNext()} className="flex h-12 w-12 items-center justify-center rounded-full border border-black/8 bg-white/70 text-zinc-900 shadow-sm transition hover:bg-white">
                <ChevronRight className="h-5 w-5" />
              </button>
            </div>
          </div>

          <div className="overflow-hidden" ref={emblaRef}>
            <div className="-ml-6 flex">
              {data.upcoming_sessions.map((session, index) => (
                <motion.div
                  key={`${session.kind}-${session.id}`}
                  initial={{ opacity: 0, y: 40, scale: 0.96 }}
                  whileInView={{ opacity: 1, y: 0, scale: 1 }}
                  viewport={{ once: true, margin: "-80px" }}
                  transition={{ duration: 0.6, delay: index * 0.12 }}
                  className="min-w-0 flex-[0_0_90%] pl-6 md:flex-[0_0_46%] lg:flex-[0_0_35%]"
                >
                  <Link to={`/workout/${session.id}`} className="group relative block h-[26rem] overflow-hidden rounded-[2.5rem] border border-black/6 bg-white shadow-xl transition-all duration-500 hover:-translate-y-1 hover:shadow-2xl">
                    <div className="absolute left-0 right-0 top-0 h-[54%] overflow-hidden">
                      <img
                        src={sessionBackdrop(session.sport_type)}
                        alt={session.title}
                        className="h-full w-full object-cover brightness-[0.95] transition-transform duration-700 group-hover:scale-105"
                      />
                      <div className="absolute inset-0 bg-gradient-to-b from-transparent via-transparent to-white" />
                    </div>

                    <div className="absolute inset-0 flex flex-col justify-between p-8">
                      <div className="flex items-start justify-between gap-4">
                        <span className="rounded-full border border-black/6 bg-white/90 px-4 py-2 text-xs font-bold uppercase tracking-[0.14em] text-zinc-900 shadow-sm backdrop-blur-xl">
                          {session.label}
                        </span>
                        <div className="flex h-12 w-12 items-center justify-center rounded-full border border-black/6 bg-white/90 text-[var(--accent)] shadow-sm backdrop-blur-xl transition-transform group-hover:rotate-45">
                          <ArrowUpRight className="h-5 w-5" />
                        </div>
                      </div>

                      <div className="-mx-8 mt-auto bg-white/55 px-8 pb-5 pt-6 backdrop-blur-sm">
                        <h3 className="text-4xl font-black uppercase tracking-[-0.07em]" style={{ color: accentForSport(session.sport_type) }}>
                          {session.title}
                        </h3>
                        <p className="mt-3 line-clamp-2 text-base font-medium text-zinc-600">{session.goal}</p>
                        <div className="mt-5 flex flex-wrap gap-2">
                          <span className="rounded-xl border border-black/5 bg-zinc-100 px-3 py-1.5 text-xs font-bold text-zinc-700">
                            {session.duration_min ? `${session.duration_min} min` : "Libre"}
                          </span>
                          <span className="rounded-xl border border-black/5 bg-zinc-100 px-3 py-1.5 text-xs font-bold text-zinc-700">
                            {sportLabel(session.sport_type)}
                          </span>
                          <span className="rounded-xl border border-black/5 bg-zinc-100 px-3 py-1.5 text-xs font-bold text-zinc-700">
                            {loadBandLabel(session.load_band)}
                          </span>
                        </div>
                      </div>
                    </div>
                  </Link>
                </motion.div>
              ))}
            </div>
          </div>
        </div>
      </motion.section>

      <section id="utility" className="px-6 pb-24">
        <div className="mx-auto grid max-w-7xl gap-5 lg:grid-cols-[0.9fr_1.1fr]">
          <article className="surface-panel p-6">
            <p className="eyebrow">Signal cockpit</p>
            <div className="mt-5 grid gap-4 sm:grid-cols-3">
              <InfoStat label="Bloc" value={data.week.label} />
              <InfoStat label="Complétion" value={percent(completionRatio)} />
              <InfoStat label="Freshness" value={data.load.freshness} />
            </div>
            <div className="mt-6 flex flex-wrap gap-3">
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
                {data.strava.connected ? `Dernière synchro ${formatDateTime(data.strava.last_sync_at || undefined)}` : "Le log manuel reste disponible ici."}
              </span>
            </div>
          </article>

          <article className="surface-panel p-6">
            <p className="eyebrow">Log manuel</p>
            <h3 className="mt-3 text-3xl font-black tracking-[-0.05em] text-zinc-950">Ajouter une activité</h3>
            <form className="mt-6 grid gap-3" onSubmit={handleActivitySubmit}>
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
                  <option value="">Charge ressentie</option>
                  <option value="1">1</option>
                  <option value="2">2</option>
                  <option value="3">3</option>
                  <option value="4">4</option>
                  <option value="5">5</option>
                </select>
              </div>
              <input name="started_at" type="datetime-local" className="rounded-2xl border border-black/6 bg-zinc-50 px-4 py-3 text-zinc-900" />
              <textarea name="note" rows={4} placeholder="Note rapide" className="rounded-[1.4rem] border border-black/6 bg-zinc-50 px-4 py-3 text-zinc-900 placeholder:text-zinc-400" />
              <button type="submit" className="action-button-primary w-full" disabled={submitting || pendingKey === "add-activity"}>
                <Send className="mr-2 h-4 w-4" />
                {submitting || pendingKey === "add-activity" ? "Ajout…" : "Ajouter l'activité"}
              </button>
            </form>
          </article>
        </div>
      </section>
    </div>
  );
}

function InfoStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[1.6rem] border border-black/6 bg-zinc-50/80 p-5">
      <p className="text-[0.72rem] font-bold uppercase tracking-[0.2em] text-zinc-500">{label}</p>
      <div className="mt-3 text-3xl font-black tracking-[-0.05em] text-zinc-950">{value}</div>
    </div>
  );
}

function accentForSport(sportType?: string | null) {
  if (sportType === "swimming") return "#9d4edd";
  if (sportType === "cycling") return "#ffd166";
  if (sportType === "strength") return "#18181b";
  return "#ff6b35";
}
