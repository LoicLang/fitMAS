import { ArrowLeft, Gauge, HeartPulse, Mountain, Route as RouteIcon } from "lucide-react";
import { motion } from "motion/react";
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

  return (
    <div className="min-h-screen">
      <section
        className="relative flex min-h-[65vh] items-end overflow-hidden border-b border-white/10"
        style={{
          backgroundImage: `linear-gradient(180deg, rgba(0,0,0,0.32), rgba(0,0,0,0.86)), radial-gradient(circle at 50% 45%, rgba(103,232,249,0.22), transparent 20%), url("${sessionBackdrop(session.sport_type)}")`,
          backgroundSize: "cover",
          backgroundPosition: "center",
        }}
      >
        <div className="absolute inset-0 bg-[linear-gradient(180deg,rgba(255,255,255,0.02),transparent_24%,rgba(3,5,8,0.64)_100%)]" />
        <div className="relative z-10 mx-auto flex w-full max-w-6xl flex-col justify-between gap-10 px-5 pb-10 pt-8 md:px-8 md:pb-14">
          <div className="flex items-start justify-between gap-4">
            <button type="button" onClick={() => navigate(-1)} className="action-button-ghost h-12 w-12 rounded-full p-0">
              <ArrowLeft className="h-5 w-5" />
            </button>
          </div>

          <motion.div
            initial={{ opacity: 0, y: 22 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
            className="max-w-4xl"
          >
            <div className="inline-flex items-center gap-2 rounded-full border border-cyan-300/20 bg-black/45 px-4 py-2 backdrop-blur-md">
              <span className="h-2.5 w-2.5 rounded-full bg-cyan-300 shadow-[0_0_14px_rgba(103,232,249,0.6)]" />
              <span className="eyebrow">{session.status === "done" ? "Séance réalisée" : "Séance planifiée"}</span>
            </div>
            <p className="mt-6 eyebrow">{formatDateLong(session.display_date || session.scheduled_date || undefined)}</p>
            <div className="mt-3 flex flex-wrap items-end gap-x-4 gap-y-2">
              <h1 className="text-[clamp(3rem,10vw,6rem)] font-bold uppercase tracking-[-0.08em]">{session.title}</h1>
              <span className="text-[clamp(2rem,7vw,4rem)] font-light tracking-[-0.08em] text-white/42">
                _{(session.session_type || "session").replaceAll("_", " ").toUpperCase()}
              </span>
            </div>
            <p className="mt-4 max-w-2xl text-lg text-white/70">
              {data.coach.goal}
            </p>
            <div className="mt-6 flex flex-wrap gap-2">
              <span className="meta-chip">{sportLabel(session.sport_type)}</span>
              <span className="meta-chip">{loadBandLabel(session.load_band)}</span>
              {data.metrics.tss ? <span className="meta-chip">{Math.round(data.metrics.tss)} TSS</span> : null}
              {data.linked_activity?.started_at ? <span className="meta-chip">réel {formatDateLong(data.linked_activity.started_at.slice(0, 10))}</span> : null}
            </div>
          </motion.div>
        </div>
      </section>

      <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-5 py-8 md:px-8 md:py-12">
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {stats.map((stat, index) => (
            <motion.article
              key={stat.label}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.28, delay: index * 0.04 }}
              className="surface-panel p-5"
            >
              <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full border border-cyan-300/20 bg-cyan-300/10 text-cyan-100">
                {index === 0 ? <RouteIcon className="h-5 w-5" /> : index === 1 ? <Gauge className="h-5 w-5" /> : index === 2 ? <Mountain className="h-5 w-5" /> : <HeartPulse className="h-5 w-5" />}
              </div>
              <div className="text-3xl font-bold tracking-[-0.05em]">{stat.value}</div>
              <p className="mt-2 text-sm text-white/46">{stat.label}</p>
            </motion.article>
          ))}
        </div>

        <section className="grid gap-6 lg:grid-cols-[1.05fr_0.95fr]">
          <article className="surface-panel p-5 md:p-6">
            <p className="eyebrow">Trace / carte</p>
            <div className="mt-5">
              <RoutePreview polyline={data.map_polyline} />
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              {formatDistance(data.metrics.distance_m) ? <span className="meta-chip">{formatDistance(data.metrics.distance_m)}</span> : null}
              {data.metrics.elevation_m ? <span className="meta-chip">+{Math.round(data.metrics.elevation_m)} m</span> : null}
              {data.metrics.tss ? <span className="meta-chip">{Math.round(data.metrics.tss)} TSS</span> : null}
            </div>
          </article>

          <article className="surface-panel p-6">
            <p className="eyebrow">Répartition intensité</p>
            <div className="mt-6 flex gap-1.5 overflow-hidden rounded-full bg-white/7 p-1">
              {data.zone_distribution.map((segment, index) => (
                <div
                  key={`${segment}-${index}`}
                  className={`h-4 rounded-full ${ZONE_COLORS[index]}`}
                  style={{ width: `${segment}%` }}
                />
              ))}
            </div>
            <div className="mt-3 flex justify-between font-mono text-[0.72rem] font-semibold uppercase tracking-[0.18em] text-white/42">
              {["Z1", "Z2", "Z3", "Z4", "Z5"].map((zone) => <span key={zone}>{zone}</span>)}
            </div>

            <div className="mt-8 grid gap-4">
              {data.coach.change_notes.length ? (
                <div>
                  <p className="eyebrow">Ajustements</p>
                  <div className="mt-3 grid gap-3">
                    {data.coach.change_notes.map((note) => (
                      <div key={`${note.title}-${note.detail}`} className="rounded-[1.4rem] border border-white/8 bg-black/20 p-4">
                        <div className="font-semibold text-white">{note.title}</div>
                        <p className="mt-2 text-white/66">{note.detail}</p>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}

              <div className="rounded-[1.6rem] border border-cyan-300/15 bg-cyan-300/[0.06] p-5">
                <p className="eyebrow">Consignes coach</p>
                <p className="mt-4 text-white/76">{data.coach.note || data.coach.description || data.coach.goal}</p>
                {data.coach.nutrition_focus ? <p className="mt-4 text-sm text-cyan-100/80">Nutrition: {data.coach.nutrition_focus}</p> : null}
              </div>
            </div>
          </article>
        </section>
      </div>
    </div>
  );
}

const ZONE_COLORS = [
  "bg-slate-200/80",
  "bg-cyan-300",
  "bg-sky-400",
  "bg-orange-400",
  "bg-rose-500",
];
