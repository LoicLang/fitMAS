import { useRef } from "react";
import { ArrowLeft, Clock, Flame, Gauge, HeartPulse, Mountain, Route as RouteIcon, TrendingUp } from "lucide-react";
import { motion, useScroll, useTransform } from "motion/react";
import { type LoaderFunctionArgs, useLoaderData, useNavigate } from "react-router-dom";
import { loadWorkoutDetail } from "../../shared/api";
import { formatDateLong, formatDistance, loadBandLabel, sportLabel } from "../../shared/format";
import { sessionBackdrop } from "../../shared/session-visuals";
import { RoutePreview } from "../../shared/ui/RoutePreview";
import type { WorkoutDetailView } from "../../types";
import { workoutStats } from "./view-model";

export async function workoutDetailLoader({ params }: LoaderFunctionArgs) {
  if (!params.sessionId) {
    throw new Error("Missing sessionId");
  }
  return loadWorkoutDetail(params.sessionId);
}

export function WorkoutDetailPage() {
  const data = useLoaderData() as WorkoutDetailView;
  const navigate = useNavigate();
  const stats = workoutStats(data);
  const session = data.session;
  const content = data.content;
  const containerRef = useRef<HTMLDivElement | null>(null);
  const { scrollYProgress } = useScroll({ target: containerRef });
  const y = useTransform(scrollYProgress, [0, 1], ["0%", "50%"]);
  const opacity = useTransform(scrollYProgress, [0, 0.5], [1, 0]);
  const showRouteProfile = shouldShowRouteProfile({
    sportType: session.sport_type,
    polyline: data.map_polyline,
    elevationM: data.metrics.elevation_m,
  });

  return (
    <div className="min-h-screen overflow-x-hidden bg-[var(--app-bg)] text-zinc-900" ref={containerRef}>
      <div className="pointer-events-none fixed inset-0 z-0">
        <motion.div
          animate={{ scale: [1, 1.2, 1], opacity: [0.15, 0.3, 0.15], rotate: [0, 90, 0] }}
          transition={{ duration: 15, repeat: Infinity, ease: "linear" }}
          className="absolute -right-[10%] -top-[10%] h-[70vw] w-[70vw] rounded-full bg-[#ff6b35] opacity-20 blur-[140px] mix-blend-multiply"
        />
        <motion.div
          animate={{ scale: [1, 1.5, 1], opacity: [0.1, 0.2, 0.1], x: ["0%", "-20%", "0%"] }}
          transition={{ duration: 20, repeat: Infinity, ease: "easeInOut" }}
          className="absolute -left-[20%] top-[40%] h-[80vw] w-[80vw] rounded-full bg-[#9d4edd] opacity-15 blur-[150px] mix-blend-multiply"
        />
      </div>

      <div className="relative z-10">
        <header className="fixed left-0 right-0 top-0 z-50 p-6">
          <button
            type="button"
            onClick={() => navigate(-1)}
            className="flex h-12 w-12 items-center justify-center rounded-full border border-black/10 bg-white/80 text-zinc-900 shadow-sm backdrop-blur-md transition hover:bg-white"
          >
            <ArrowLeft className="h-6 w-6" />
          </button>
        </header>

        <section className="relative flex h-[60vh] w-full items-end overflow-hidden px-6 pb-12 pt-24">
          <motion.div
            style={{ y, opacity }}
            className="absolute inset-0 z-0 bg-zinc-200"
          >
            <img src={sessionBackdrop(session.sport_type)} alt={session.title} className="h-full w-full object-cover opacity-35 grayscale [mix-blend-mode:multiply]" />
            <div className="absolute inset-0 bg-gradient-to-t from-[#f8f9fa] via-[#f8f9fa]/82 to-transparent" />
          </motion.div>

          <div className="relative z-10 mx-auto w-full max-w-5xl">
            <motion.div initial={{ opacity: 0, y: 28 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.7, delay: 0.12 }}>
              <div className="inline-flex items-center space-x-2 rounded-full border border-black/6 bg-white/80 px-4 py-2 shadow-sm backdrop-blur-md">
                <span className="h-2 w-2 rounded-full bg-[var(--accent-alt)]" />
                <span className="text-xs font-bold uppercase tracking-[0.18em] text-[var(--accent-alt)]">
                  {session.status === "done" ? "Séance réalisée" : "Séance planifiée"}
                </span>
              </div>
              <p className="mt-8 text-sm font-bold uppercase tracking-[0.3em] text-[var(--accent)]">
                {formatDateLong(session.display_date || session.scheduled_date || undefined)}
              </p>
              <h1 className="mt-3 text-5xl font-black uppercase tracking-[-0.08em] text-zinc-950 md:text-7xl">
                {session.title} <span className="font-light text-[var(--accent)]">_{(session.session_type || "session").replaceAll("_", " ").toUpperCase()}</span>
              </h1>
              <p className="mt-4 max-w-3xl text-xl font-medium text-zinc-600">{content.objective || data.coach.goal}</p>
            </motion.div>
          </div>
        </section>

        <section className="relative z-10 mx-auto max-w-5xl px-6 pb-24">
          <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
            {stats.map((stat, index) => {
              const Icon = STAT_ICONS[index] ?? Mountain;
              return (
                <motion.article
                  key={stat.label}
                  initial={{ opacity: 0, y: 20 }}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true }}
                  transition={{ duration: 0.5, delay: index * 0.08 }}
                  className="rounded-[2rem] border border-black/5 bg-white p-6 shadow-sm transition-all hover:shadow-xl hover:border-transparent"
                >
                  <div className={`mb-4 flex h-14 w-14 items-center justify-center rounded-2xl ${STAT_BACKGROUNDS[index % STAT_BACKGROUNDS.length]}`}>
                    <Icon className={`h-6 w-6 ${STAT_COLORS[index % STAT_COLORS.length]}`} />
                  </div>
                  <div className="text-3xl font-black tracking-[-0.05em] text-zinc-950">{stat.value}</div>
                  <div className="mt-1 text-xs font-bold uppercase tracking-[0.18em] text-zinc-500">{stat.label}</div>
                </motion.article>
              );
            })}
          </div>

          <div className="mt-12 grid gap-5 lg:grid-cols-2">
            <DetailCard
              title="Objectif du jour"
              eyebrow="Objectif"
              content={content.objective || data.coach.goal}
            />
            <DetailCard
              title="Pourquoi aujourd'hui"
              eyebrow="Placement"
              content={content.rationale || content.objective || data.coach.goal}
            />
          </div>

          <DetailListCard title="Séance" eyebrow="Exécution" items={content.execution} />

          <div className="mt-5 grid gap-5 lg:grid-cols-2">
            <DetailAccentCard
              title="Consigne coach"
              content={content.coach_cue || data.coach.goal}
            />
            {content.nutrition_note ? (
              <DetailCard
                title="Nutrition"
                eyebrow="Simple"
                content={content.nutrition_note}
              />
            ) : null}
          </div>

          {showRouteProfile ? (
            <motion.div
              initial={{ opacity: 0, y: 30 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.7 }}
              className="mt-12"
            >
              <h2 className="mb-6 flex items-center text-2xl font-bold text-zinc-950">
                <Mountain className="mr-3 h-6 w-6 text-[var(--accent)]" />
                Trace et profil
              </h2>
              <div className="rounded-[2rem] border border-black/5 bg-white p-6 shadow-sm">
                <RoutePreview polyline={data.map_polyline} />
                <div className="mt-4 flex flex-wrap gap-2">
                  {formatDistance(data.metrics.distance_m) ? <span className="meta-chip">{formatDistance(data.metrics.distance_m)}</span> : null}
                  {data.metrics.elevation_m ? <span className="meta-chip">+{Math.round(data.metrics.elevation_m)} m</span> : null}
                  {data.metrics.tss ? <span className="meta-chip">{Math.round(data.metrics.tss)} TSS</span> : null}
                  <span className="meta-chip">{sportLabel(session.sport_type)}</span>
                  <span className="meta-chip">{loadBandLabel(session.load_band)}</span>
                </div>
              </div>
            </motion.div>
          ) : null}
        </section>
      </div>
    </div>
  );
}

function DetailCard({ title, eyebrow, content }: { title: string; eyebrow: string; content: string }) {
  return (
    <motion.article
      initial={{ opacity: 0, y: 24 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true }}
      transition={{ duration: 0.6 }}
      className="rounded-[2rem] border border-black/5 bg-white p-7 shadow-sm"
    >
      <p className="text-[0.72rem] font-bold uppercase tracking-[0.2em] text-zinc-500">{eyebrow}</p>
      <h2 className="mt-3 text-2xl font-bold text-zinc-950">{title}</h2>
      <p className="mt-4 text-base font-medium leading-relaxed text-zinc-700">{content}</p>
    </motion.article>
  );
}

function DetailListCard({ title, eyebrow, items }: { title: string; eyebrow: string; items: string[] }) {
  return (
    <motion.article
      initial={{ opacity: 0, y: 24 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true }}
      transition={{ duration: 0.6 }}
      className="mt-5 rounded-[2rem] border border-black/5 bg-white p-7 shadow-sm"
    >
      <p className="text-[0.72rem] font-bold uppercase tracking-[0.2em] text-zinc-500">{eyebrow}</p>
      <h2 className="mt-3 text-2xl font-bold text-zinc-950">{title}</h2>
      <ol className="mt-5 space-y-3">
        {items.map((item, index) => (
          <li key={`${index}-${item}`} className="flex gap-4 rounded-[1.4rem] border border-black/5 bg-zinc-50/80 px-4 py-4">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-white text-sm font-black text-[var(--accent)] shadow-sm">
              {index + 1}
            </span>
            <p className="pt-1 text-base font-medium leading-relaxed text-zinc-700">{item}</p>
          </li>
        ))}
      </ol>
    </motion.article>
  );
}

function DetailAccentCard({ title, content }: { title: string; content: string }) {
  return (
    <motion.article
      initial={{ opacity: 0, y: 24 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true }}
      transition={{ duration: 0.6 }}
      className="relative overflow-hidden rounded-[2rem] border border-[rgba(255,107,53,0.18)] bg-gradient-to-br from-[rgba(255,107,53,0.10)] to-[rgba(255,209,102,0.12)] p-8"
    >
      <div className="absolute right-0 top-0 h-64 w-64 rounded-full bg-white/50 blur-[80px]" />
      <p className="relative text-[0.72rem] font-bold uppercase tracking-[0.2em] text-zinc-500">Coach</p>
      <h2 className="relative mt-3 flex items-center text-2xl font-bold text-zinc-950">
        <TrendingUp className="mr-3 h-5 w-5 text-[var(--accent)]" />
        {title}
      </h2>
      <p className="relative mt-5 text-base font-medium leading-relaxed text-zinc-700">{content}</p>
    </motion.article>
  );
}

function shouldShowRouteProfile({
  sportType,
  polyline,
  elevationM,
}: {
  sportType: string;
  polyline?: string | null;
  elevationM?: number | null;
}) {
  if (sportType === "swimming" || sportType === "strength") {
    return false;
  }
  return Boolean(polyline || elevationM);
}

// Order matches workoutStats: Distance, Durée, Allure, Dénivelé, FC moy, Calories.
const STAT_ICONS = [RouteIcon, Clock, Gauge, Mountain, HeartPulse, Flame];
const STAT_BACKGROUNDS = ["bg-purple-50", "bg-orange-50", "bg-sky-50", "bg-yellow-50", "bg-red-50", "bg-amber-50"];
const STAT_COLORS = ["text-[#9d4edd]", "text-[#ff6b35]", "text-[#0ea5e9]", "text-[#ffd166]", "text-red-500", "text-[#f59e0b]"];
