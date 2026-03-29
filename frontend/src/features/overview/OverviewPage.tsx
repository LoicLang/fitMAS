import useEmblaCarousel from "embla-carousel-react";
import { motion, useScroll, useTransform } from "motion/react";
import { ArrowUpRight, ChevronLeft, ChevronRight, RefreshCcw, Send } from "lucide-react";
import { type FormEvent, useRef, useState } from "react";
import { Link, type LoaderFunctionArgs, useLoaderData, useNavigate } from "react-router-dom";
import { loadOverview } from "../../shared/api";
import { formatDateTime, loadBandLabel, percent, sportLabel } from "../../shared/format";
import { sessionBackdrop } from "../../shared/session-visuals";
import { useAppActions } from "../../state/app-actions";
import type { AdaptationLogEntry, AvailabilityState, CalibrationStatus, OverviewView, PlanningContract, WeekMission } from "../../types";
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
      <section className="relative overflow-hidden px-6 pb-10 pt-8 md:pt-10">
        <div className="pointer-events-none absolute left-1/2 top-10 h-80 w-80 -translate-x-1/2 rounded-full bg-[rgba(255,107,53,0.16)] blur-[120px]" />
        <div className="mx-auto grid min-h-[calc(100vh-8rem)] max-w-7xl gap-8 lg:grid-cols-[1.08fr_0.92fr] lg:items-end">
          <motion.div
            initial={{ opacity: 0, x: -36 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.75, ease: [0.2, 0.65, 0.3, 0.9] }}
            className="relative z-10 flex flex-col justify-between gap-8 py-8"
          >
            <div>
              <div className="inline-flex items-center gap-2 rounded-full border border-black/8 bg-white/70 px-4 py-2 shadow-sm backdrop-blur-md">
                <span className="h-2 w-2 rounded-full bg-[var(--accent)] shadow-[0_0_10px_rgba(255,107,53,0.45)]" />
                <span className="eyebrow">{data.today ? "Daily brief" : "Prochaine fenêtre utile"}</span>
              </div>
              <p className="mt-8 text-sm font-bold uppercase tracking-[0.3em] text-zinc-500">{overviewHeroLabel(data)}</p>
              <h1 className="mt-4 text-[clamp(3.6rem,12vw,7.2rem)] font-black uppercase tracking-[-0.09em] text-zinc-950">
                {heroTitle.title}
              </h1>
              <h2 className="mt-2 text-[clamp(2.1rem,7vw,4.2rem)] font-light uppercase tracking-[-0.08em] text-zinc-700">
                {heroTitle.suffix}
              </h2>
              <p className="mt-6 max-w-2xl text-lg font-medium leading-relaxed text-zinc-600">
                {leadSession?.goal || "L’aperçu doit dire ce qui compte maintenant, ce qu’on protège cette semaine, et comment la trajectoire bouge."}
              </p>
            </div>

            <div className="grid gap-3 sm:grid-cols-3">
              <InfoStat label="Bloc" value={data.week.label} />
              <InfoStat label="Complétion" value={percent(completionRatio)} />
              <InfoStat label="Freshness" value={data.load.freshness} />
            </div>
          </motion.div>

          <DailyBriefPanel
            leadSession={leadSession}
            today={data.today}
            planningContract={data.planning_contract}
            weekMission={data.week_mission}
            weekContext={data.week_context}
            lastAdaptation={data.last_adaptation}
            calibrationStatus={data.calibration_status}
            pendingKey={pendingKey}
            onDone={(sessionId) => void actOnSession("done", sessionId)}
            onSkip={(sessionId) => void actOnSession("skip", sessionId)}
            onMove={(sessionId) => void actOnSession("move", sessionId)}
            onOpenSession={(sessionId) => navigate(`/workout/${sessionId}`)}
          />
        </div>
      </section>

      {data.planning_contract || data.week_mission ? (
        <motion.section
          initial={{ opacity: 0, y: 18 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.18 }}
          className="relative z-10 px-6 pb-10"
        >
          <div className="mx-auto max-w-7xl space-y-5">
            <div className="grid gap-5 lg:grid-cols-[1.05fr_0.95fr]">
              <PlanningContractCard
                planningContract={data.planning_contract}
                availabilityState={data.availability_state}
              />
              <WeekMissionCard weekMission={data.week_mission} weekContext={data.week_context} />
            </div>
            <LatestAdaptationCard adaptation={data.last_adaptation} />
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
            <div>
              <p className="eyebrow">Plan</p>
              <h2 className="mt-3 text-4xl font-light tracking-tight text-zinc-950">
                Prochaines <span className="font-black">72h</span>
              </h2>
            </div>
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
                          {session.confidence ? (
                            <span className="rounded-xl border border-black/5 bg-white px-3 py-1.5 text-xs font-bold uppercase tracking-[0.14em] text-zinc-700">
                              {confidenceLabel(session.confidence)}
                            </span>
                          ) : null}
                          {session.role ? (
                            <span className="rounded-xl border border-black/5 bg-white px-3 py-1.5 text-xs font-bold uppercase tracking-[0.14em] text-zinc-700">
                              {roleLabel(session.role)}
                            </span>
                          ) : null}
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
            <p className="eyebrow">Certitude & exécution</p>
            <div className="mt-5 grid gap-4 sm:grid-cols-3">
              <InfoStat label="Bloc" value={data.week.label} />
              <InfoStat label="Complétion" value={percent(completionRatio)} />
              <InfoStat label="Freshness" value={data.load.freshness} />
            </div>
            {data.week_context ? (
              <div className="mt-6 rounded-[1.6rem] border border-black/6 bg-zinc-50/80 p-5">
                <p className="text-[0.72rem] font-bold uppercase tracking-[0.2em] text-zinc-500">Lecture coach</p>
                <p className="mt-3 text-base font-medium leading-relaxed text-zinc-700">{data.week_context.coach_reading}</p>
              </div>
            ) : null}
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

function DailyBriefPanel({
  leadSession,
  today,
  planningContract,
  weekMission,
  weekContext,
  lastAdaptation,
  calibrationStatus,
  pendingKey,
  onDone,
  onSkip,
  onMove,
  onOpenSession,
}: {
  leadSession: OverviewView["lead_session"];
  today: OverviewView["today"];
  planningContract?: PlanningContract;
  weekMission?: WeekMission;
  weekContext?: OverviewView["week_context"];
  lastAdaptation?: AdaptationLogEntry | null;
  calibrationStatus?: CalibrationStatus;
  pendingKey: string | null;
  onDone: (sessionId: number) => void;
  onSkip: (sessionId: number) => void;
  onMove: (sessionId: number) => void;
  onOpenSession: (sessionId: number) => void;
}) {
  const certainty = leadSession?.confidence ? confidenceLabel(leadSession.confidence) : null;

  return (
    <motion.aside
      initial={{ opacity: 0, x: 36 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.75, delay: 0.08, ease: [0.2, 0.65, 0.3, 0.9] }}
      className="surface-panel relative z-10 p-6 md:p-7"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="meta-chip">{dataLabel(today)}</span>
        {weekMission ? <span className="meta-chip">{missionStatusLabel(weekMission.mission_status)}</span> : null}
        {certainty ? <span className="meta-chip">{certainty}</span> : null}
      </div>

      <h3 className="mt-5 text-3xl font-black tracking-[-0.05em] text-zinc-950">
        {today?.session_title || leadSession?.title || "Brief du jour"}
      </h3>
      <p className="mt-3 text-base font-medium leading-relaxed text-zinc-600">
        {today?.session_goal || leadSession?.goal || weekMission?.objective_reason || "Le système garde le cap et affiche la meilleure prochaine décision utile."}
      </p>

        <div className="mt-6 grid gap-3 sm:grid-cols-2">
          <MissionBlock label="Mission" value={weekMission?.objective || planningContract?.block_focus || "Bloc actif"} />
          <MissionBlock label="Pourquoi aujourd'hui" value={today?.session_description || weekContext?.coach_reading || "La séance du jour sert la mission de semaine sans casser la suite."} />
        </div>

      {calibrationStatus ? (
        <div className="mt-6 rounded-[1.6rem] border border-black/6 bg-zinc-50/80 p-5">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-[0.68rem] font-bold uppercase tracking-[0.18em] text-zinc-500">Calibration</p>
            <span className="meta-chip">{phaseLabel(calibrationStatus.phase)}</span>
          </div>
          <p className="mt-3 text-sm font-semibold text-zinc-900">{calibrationStatus.summary}</p>
          <p className="mt-2 text-sm font-medium leading-relaxed text-zinc-600">{calibrationStatus.next_step}</p>
        </div>
      ) : null}

      {lastAdaptation ? (
        <div className="mt-6 rounded-[1.6rem] border border-[rgba(255,107,53,0.14)] bg-[rgba(255,107,53,0.06)] p-5">
          <p className="text-[0.68rem] font-bold uppercase tracking-[0.18em] text-zinc-500">Dernier changement</p>
          <p className="mt-2 text-sm font-semibold text-zinc-900">{lastAdaptation.summary}</p>
          <p className="mt-2 text-sm font-medium leading-relaxed text-zinc-600">{lastAdaptation.what_protected}</p>
          <p className="mt-3 text-xs font-bold uppercase tracking-[0.16em] text-zinc-500">{lastAdaptation.impact_label}</p>
        </div>
      ) : null}

      <div className="mt-6 flex flex-wrap gap-3">
        {leadSession ? (
          <button
            type="button"
            onClick={() => onOpenSession(leadSession.id)}
            className="relative flex items-center justify-center gap-3 rounded-full border border-black/6 bg-white/80 px-5 py-3 text-sm font-bold uppercase tracking-[0.1em] text-zinc-900 shadow-sm backdrop-blur-xl transition active:scale-95"
          >
            <span className="h-2 w-2 rounded-full bg-[var(--accent)]" />
            <span>Détails séance</span>
            <ArrowUpRight className="h-4 w-4 text-[var(--accent)]" />
          </button>
        ) : null}
        {today ? (
          <>
            <button
              type="button"
              className="action-button-ghost"
              onClick={() => onDone(today.scheduled_session_id)}
              disabled={pendingKey === `done:${today.scheduled_session_id}`}
            >
              Fait
            </button>
            <button
              type="button"
              className="action-button-ghost"
              onClick={() => onSkip(today.scheduled_session_id)}
              disabled={pendingKey === `skip:${today.scheduled_session_id}`}
            >
              Fatigué
            </button>
            <button
              type="button"
              className="action-button-ghost"
              onClick={() => onMove(today.scheduled_session_id)}
              disabled={pendingKey === `move:${today.scheduled_session_id}`}
            >
              Décaler
            </button>
          </>
        ) : null}
      </div>

      {weekContext ? (
        <div className="mt-6 grid gap-3 sm:grid-cols-3">
          <MissionBlock label="Cycle" value={weekContext.planning.cycle_position} />
          <MissionBlock label="Mode" value={weekContext.planning.mode} />
          <MissionBlock label="S+1" value={weekContext.next_week.focus} />
        </div>
      ) : null}
    </motion.aside>
  );
}

function PlanningContractCard({
  planningContract,
  availabilityState,
}: {
  planningContract?: PlanningContract;
  availabilityState?: AvailabilityState;
}) {
  if (!planningContract) return null;

  return (
    <article className="surface-panel p-6 md:p-7">
      <p className="eyebrow">Contrat planning</p>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <span className="meta-chip">{planningContract.phase_label}</span>
        <span className="meta-chip">{planningContract.block_focus}</span>
      </div>
      <p className="mt-5 text-3xl font-black tracking-[-0.05em] text-zinc-950">{planningContract.horizon_summary}</p>
      <p className="mt-3 text-base font-medium leading-relaxed text-zinc-600">{planningContract.next_inflexion}</p>

      <div className="mt-6 grid gap-3 sm:grid-cols-2">
        {planningContract.horizons.map((horizon) => (
          <div key={horizon.key} className="rounded-[1.4rem] border border-black/6 bg-zinc-50/80 p-4">
            <div className="flex items-center justify-between gap-3">
              <p className="text-xs font-bold uppercase tracking-[0.18em] text-zinc-500">{horizon.label}</p>
              <span className="rounded-full bg-white px-3 py-1 text-[0.68rem] font-bold uppercase tracking-[0.14em] text-zinc-700">
                {confidenceLabel(horizon.confidence)}
              </span>
            </div>
            <p className="mt-3 text-sm font-medium text-zinc-600">{horizon.summary}</p>
          </div>
        ))}
      </div>

      <div className="mt-6 grid gap-3 sm:grid-cols-3">
        <InfoStat label="Budget adapt" value={`${planningContract.change_budget.used}/${planningContract.change_budget.total}`} />
        <InfoStat label="Restant" value={String(planningContract.change_budget.remaining)} />
        <InfoStat label="Stabilité" value={stabilityLabel(planningContract.change_budget.status)} />
      </div>

      {availabilityState ? (
        <div className="mt-6 rounded-[1.6rem] border border-black/6 bg-zinc-50/70 p-5">
          <p className="text-[0.72rem] font-bold uppercase tracking-[0.2em] text-zinc-500">Disponibilités</p>
          <p className="mt-3 text-base font-medium leading-relaxed text-zinc-700">{availabilityState.summary}</p>
          {availabilityState.preferred_windows.length ? (
            <div className="mt-4 flex flex-wrap gap-2">
              {availabilityState.preferred_windows.slice(0, 4).map((window) => (
                <span key={window.day} className="rounded-full border border-black/6 bg-white px-3 py-1.5 text-xs font-bold text-zinc-700">
                  {window.label} · {window.windows.join(", ")}
                </span>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

function WeekMissionCard({
  weekMission,
  weekContext,
}: {
  weekMission?: WeekMission;
  weekContext?: OverviewView["week_context"];
}) {
  if (!weekMission) return null;

  return (
    <article className="surface-panel p-6 md:p-7">
      <p className="eyebrow">Mission hebdo</p>
      <h3 className="mt-4 text-3xl font-black tracking-[-0.05em] text-zinc-950">{weekMission.objective}</h3>
      <p className="mt-3 text-base font-medium leading-relaxed text-zinc-600">{weekMission.objective_reason}</p>

      <div className="mt-6 space-y-4">
        <MissionBlock label="Critère de réussite" value={weekMission.success_criteria} />
        <MissionBlock label="Succès minimal" value={weekMission.minimum_success} />
        <MissionBlock label="Risque principal" value={weekMission.primary_risk} />
      </div>

      {weekContext ? (
        <div className="mt-6 rounded-[1.6rem] border border-black/6 bg-zinc-50/80 p-5">
          <p className="text-[0.72rem] font-bold uppercase tracking-[0.2em] text-zinc-500">Lecture coach</p>
          <p className="mt-3 text-base font-medium leading-relaxed text-zinc-700">{weekContext.coach_reading}</p>
        </div>
      ) : null}

      {weekMission.key_sessions.length ? (
        <div className="mt-6">
          <p className="text-[0.72rem] font-bold uppercase tracking-[0.2em] text-zinc-500">Séances clés</p>
          <div className="mt-3 flex flex-wrap gap-2">
            {weekMission.key_sessions.map((session) => (
              <span key={session.session_id} className="rounded-full border border-black/6 bg-white px-3 py-1.5 text-xs font-bold text-zinc-800">
                {session.label} · {session.title}
              </span>
            ))}
          </div>
        </div>
      ) : null}
    </article>
  );
}

function LatestAdaptationCard({ adaptation }: { adaptation?: AdaptationLogEntry | null }) {
  if (!adaptation) return null;

  return (
    <article className="surface-panel p-6 md:p-7">
      <div className="flex flex-wrap items-center gap-3">
        <p className="eyebrow">Plan mis à jour</p>
        <span className="meta-chip">{adaptation.reason_label}</span>
        <span className="meta-chip">{adaptation.mission_label}</span>
        <span className="meta-chip">{adaptation.impact_label}</span>
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-[1.15fr_0.85fr]">
        <div>
          <h3 className="text-3xl font-black tracking-[-0.05em] text-zinc-950">{adaptation.summary}</h3>
          <p className="mt-3 text-base font-medium leading-relaxed text-zinc-600">{adaptation.what_changed}</p>
          <p className="mt-3 text-sm font-medium leading-relaxed text-zinc-500">Protégé : {adaptation.what_protected}</p>
        </div>

        <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-1">
          <MissionBlock label="Niveau" value={adaptation.adaptation_level} />
          <MissionBlock label="Coût du changement" value={String(adaptation.change_cost)} />
          <MissionBlock label="Pénalité stabilité" value={String(adaptation.stability_penalty)} />
        </div>
      </div>

      <div className="mt-6 rounded-[1.6rem] border border-black/6 bg-zinc-50/80 p-5">
        <p className="text-[0.68rem] font-bold uppercase tracking-[0.18em] text-zinc-500">Déclencheur</p>
        <p className="mt-2 text-sm font-medium text-zinc-700">{adaptation.source_text}</p>
        {adaptation.created_at ? (
          <p className="mt-3 text-xs font-bold uppercase tracking-[0.16em] text-zinc-500">
            {formatDateTime(adaptation.created_at)}
          </p>
        ) : null}
      </div>
    </article>
  );
}

function MissionBlock({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[1.4rem] border border-black/6 bg-zinc-50/80 p-4">
      <p className="text-[0.68rem] font-bold uppercase tracking-[0.18em] text-zinc-500">{label}</p>
      <p className="mt-2 text-sm font-medium leading-relaxed text-zinc-700">{value}</p>
    </div>
  );
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

function missionStatusLabel(status: string) {
  if (status === "committed") return "mission ferme";
  if (status === "softened") return "mission adoucie";
  if (status === "revised") return "mission révisée";
  return status;
}

function dataLabel(today: OverviewView["today"]) {
  return today ? "aujourd'hui" : "fenêtre à venir";
}

function stabilityLabel(status: string) {
  if (status === "stable") return "Stable";
  if (status === "watch") return "À surveiller";
  return "Limite";
}

function phaseLabel(phase: string) {
  if (phase === "draft") return "first draft";
  if (phase === "calibrating") return "calibrage";
  if (phase === "stable") return "stable";
  return phase;
}
