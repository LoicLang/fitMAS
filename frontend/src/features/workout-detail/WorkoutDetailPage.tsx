import { useRef } from "react";
import { ArrowLeft, Clock, HeartPulse, Mountain, Route as RouteIcon, TrendingUp } from "lucide-react";
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
  const containerRef = useRef<HTMLDivElement | null>(null);
  const { scrollYProgress } = useScroll({ target: containerRef });
  const y = useTransform(scrollYProgress, [0, 1], ["0%", "50%"]);
  const opacity = useTransform(scrollYProgress, [0, 0.5], [1, 0]);

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
              <p className="mt-4 text-xl font-medium text-zinc-600">{data.coach.goal}</p>
            </motion.div>
          </div>
        </section>

        <section className="relative z-10 mx-auto max-w-5xl px-6 pb-24">
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            {stats.map((stat, index) => (
              <motion.article
                key={stat.label}
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ duration: 0.5, delay: index * 0.08 }}
                className="rounded-[2rem] border border-black/5 bg-white p-6 shadow-sm transition-all hover:shadow-xl hover:border-transparent"
              >
                <div className={`mb-4 flex h-14 w-14 items-center justify-center rounded-2xl ${STAT_BACKGROUNDS[index]}`}>
                  {index === 0 ? (
                    <RouteIcon className={`h-6 w-6 ${STAT_COLORS[index]}`} />
                  ) : index === 1 ? (
                    <Clock className={`h-6 w-6 ${STAT_COLORS[index]}`} />
                  ) : index === 2 ? (
                    <TrendingUp className={`h-6 w-6 ${STAT_COLORS[index]}`} />
                  ) : index === 3 ? (
                    <HeartPulse className={`h-6 w-6 ${STAT_COLORS[index]}`} />
                  ) : (
                    <Mountain className={`h-6 w-6 ${STAT_COLORS[index]}`} />
                  )}
                </div>
                <div className="text-3xl font-black tracking-[-0.05em] text-zinc-950">{stat.value}</div>
                <div className="mt-1 text-xs font-bold uppercase tracking-[0.18em] text-zinc-500">{stat.label}</div>
              </motion.article>
            ))}
          </div>

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

          <motion.div
            initial={{ opacity: 0, y: 30 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.7 }}
            className="relative mt-12 overflow-hidden rounded-[2rem] border border-[rgba(255,107,53,0.18)] bg-gradient-to-br from-[rgba(255,107,53,0.10)] to-[rgba(255,209,102,0.12)] p-8"
          >
            <div className="absolute right-0 top-0 h-64 w-64 rounded-full bg-white/50 blur-[80px]" />
            <h3 className="flex items-center text-xl font-bold text-zinc-950">
              <TrendingUp className="mr-2 h-5 w-5 text-[var(--accent)]" />
              Consignes coach
            </h3>
            <p className="mt-5 text-base font-medium leading-relaxed text-zinc-700">
              {data.coach.note || data.coach.description || data.coach.goal}
            </p>
            {data.coach.nutrition_focus ? <p className="mt-4 text-sm font-medium text-zinc-600">Nutrition: {data.coach.nutrition_focus}</p> : null}
          </motion.div>
        </section>
      </div>
    </div>
  );
}

const STAT_BACKGROUNDS = ["bg-purple-50", "bg-orange-50", "bg-yellow-50", "bg-red-50"];
const STAT_COLORS = ["text-[#9d4edd]", "text-[#ff6b35]", "text-[#ffd166]", "text-red-500"];
