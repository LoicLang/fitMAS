import { useRef } from "react";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis } from "recharts";
import { Activity, AlertTriangle, Flame, Target, TrendingUp } from "lucide-react";
import { motion, useScroll, useTransform } from "motion/react";
import { type LoaderFunctionArgs, useLoaderData } from "react-router-dom";
import { loadEvolution } from "../../shared/api";
import { loadBandLabel, percent } from "../../shared/format";
import type { EvolutionView } from "../../types";
import { latestCtl, weeklyExecutionRatio } from "./view-model";

export async function evolutionLoader(_: LoaderFunctionArgs) {
  return loadEvolution();
}

export function EvolutionPage() {
  const data = useLoaderData() as EvolutionView;
  const executionRatio = weeklyExecutionRatio(data);
  const ctlNow = latestCtl(data);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const { scrollYProgress } = useScroll({ target: containerRef });
  const orbY = useTransform(scrollYProgress, [0, 1], ["0%", "30%"]);
  const history = data.history.map((point) => ({
    month: point.date.slice(5),
    distance: point.ctl,
  }));

  return (
    <div className="min-h-screen px-6 pb-24 pt-8 text-zinc-900" ref={containerRef}>
      <div className="mx-auto max-w-5xl">
        <motion.div
          style={{ y: orbY }}
          className="pointer-events-none absolute right-[-6rem] top-0 h-72 w-72 rounded-full bg-[#ff6b35] opacity-20 blur-[110px]"
        />
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} className="mb-12">
          <h1 className="text-5xl font-black uppercase tracking-[-0.08em] text-zinc-950 md:text-7xl">Évolution</h1>
          <p className="mt-4 max-w-3xl text-xl font-medium text-zinc-500">
            Analyse de la montée en charge, du prévu vs réalisé et du bloc à venir.
          </p>
        </motion.div>

        <div className="mb-8 grid grid-cols-1 gap-4 md:grid-cols-3">
          <StatCard
            label="Charge d'entraînement"
            value={data.load.freshness}
            icon={Activity}
            iconColor="text-[#9d4edd]"
            iconBg="bg-purple-50"
          />
          <StatCard
            label="Prévu vs réalisé"
            value={`${Math.round(data.tss.actual)} / ${Math.round(data.tss.target)} TSS`}
            icon={Target}
            iconColor="text-[#ff6b35]"
            iconBg="bg-orange-50"
          />
          <StatCard
            label="Fatigue"
            value={`${data.load.atl.toFixed(1)} ATL`}
            icon={Flame}
            iconColor="text-[#ffd166]"
            iconBg="bg-yellow-50"
          />
        </div>

        <motion.section
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.15 }}
          className="rounded-[2rem] border border-black/5 bg-white p-6 shadow-sm md:p-8"
        >
          <div className="mb-8 flex items-center justify-between">
            <h2 className="flex items-center text-2xl font-bold text-zinc-950">
              <TrendingUp className="mr-3 h-6 w-6 text-[var(--accent)]" />
              Historique charge réelle
            </h2>
            <div className="text-right">
              <div className="text-4xl font-black tracking-[-0.06em] text-zinc-950">{ctlNow.toFixed(1)}</div>
              <div className="text-sm font-bold uppercase tracking-[0.18em] text-zinc-500">CTL</div>
            </div>
          </div>

          <div className="h-[350px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={history} margin={{ top: 10, right: 0, left: -20, bottom: 0 }}>
                <defs>
                  <linearGradient id="fitmasEvolutionArea" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#ff6b35" stopOpacity={0.28} />
                    <stop offset="95%" stopColor="#ff6b35" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="month" stroke="#a1a1aa" fontSize={12} tickLine={false} axisLine={false} fontWeight="bold" />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#ffffff",
                    borderColor: "#f4f4f5",
                    borderRadius: "16px",
                    boxShadow: "0 10px 25px -5px rgba(0, 0, 0, 0.08)",
                  }}
                />
                <Area type="monotone" dataKey="distance" stroke="#ff6b35" strokeWidth={4} fillOpacity={1} fill="url(#fitmasEvolutionArea)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </motion.section>

        <div className="mt-8 grid gap-5 lg:grid-cols-[1.05fr_0.95fr]">
          <article className="surface-panel p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="eyebrow">Prévu vs réalisé</p>
                <h2 className="mt-3 text-3xl font-black tracking-[-0.05em] text-zinc-950">Semaine en cours</h2>
              </div>
              <span className="meta-chip">{data.week.label}</span>
            </div>
            <div className="mt-8 h-[300px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data.week_daily}>
                  <CartesianGrid stroke="rgba(0,0,0,0.05)" vertical={false} />
                  <XAxis dataKey="label" tickLine={false} axisLine={false} stroke="#a1a1aa" />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#ffffff",
                      borderColor: "#f4f4f5",
                      borderRadius: "16px",
                      boxShadow: "0 10px 25px -5px rgba(0, 0, 0, 0.08)",
                    }}
                  />
                  <Bar dataKey="planned_tss" fill="#9d4edd" radius={[10, 10, 0, 0]} name="Prévu" />
                  <Bar dataKey="actual_tss" fill="#ff6b35" radius={[10, 10, 0, 0]} name="Réalisé" />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="mt-6 grid gap-3 sm:grid-cols-3">
              <MiniStat label="Complétion" value={percent(executionRatio)} />
              <MiniStat label="Ramp" value={String(data.load.ramp_rate)} />
              <MiniStat label="Delta" value={`${Math.round(data.tss.delta)}`} />
            </div>
          </article>

          <article className="rounded-[2rem] border border-black/5 bg-white p-6 shadow-sm">
            <p className="eyebrow">Vision bloc</p>
            <h2 className="mt-3 text-3xl font-black tracking-[-0.05em] text-zinc-950">4 semaines à venir</h2>
            <div className="mt-6 grid gap-4">
              {data.forecast.map((forecast, index) => (
                <motion.div
                  key={`${forecast.week_index}-${forecast.cycle_week}`}
                  initial={{ opacity: 0, y: 14 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: index * 0.06 }}
                  className="rounded-[1.8rem] border border-black/5 bg-zinc-50/80 p-5"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-xs font-bold uppercase tracking-[0.18em] text-zinc-500">Semaine +{forecast.week_index}</p>
                      <div className="mt-3 text-3xl font-black tracking-[-0.05em] text-zinc-950">{Math.round(forecast.target_tss)}</div>
                      <p className="mt-1 text-sm font-medium text-zinc-500">TSS cible</p>
                    </div>
                    <span className="meta-chip">{forecast.focus}</span>
                  </div>
                  <p className="mt-5 text-sm font-medium text-zinc-600">
                    CTL projeté {forecast.projected_ctl.toFixed(1)} · cycle {forecast.cycle_week}/4 · {forecast.is_deload ? "assimilation" : forecast.planning_mode}
                  </p>
                </motion.div>
              ))}
            </div>
          </article>
        </div>

        <div className="mt-8 grid gap-5 lg:grid-cols-[0.9fr_1.1fr]">
          <article className="rounded-[2rem] border border-black/5 bg-white p-6 shadow-sm">
            <p className="eyebrow">Distribution charge</p>
            <div className="mt-6 grid gap-3">
              {Object.entries(data.distribution.planned).map(([band, value]) => {
                const completed = data.distribution.completed[band]?.count || 0;
                return (
                  <div key={band} className="rounded-[1.4rem] border border-black/6 bg-zinc-50/80 p-4">
                    <div className="flex items-center justify-between gap-3">
                      <span className="font-semibold text-zinc-900">{loadBandLabel(band)}</span>
                      <span className="text-sm text-zinc-500">{completed} / {value.count} séances</span>
                    </div>
                    <div className="mt-3 h-2 overflow-hidden rounded-full bg-zinc-200">
                      <div className="h-full rounded-full bg-[var(--accent)]" style={{ width: `${value.count ? (completed / value.count) * 100 : 0}%` }} />
                    </div>
                  </div>
                );
              })}
            </div>
          </article>

          <article className="rounded-[2rem] border border-black/5 bg-white p-6 shadow-sm">
            <p className="eyebrow">Lecture coach</p>
            {data.week_context ? (
              <div className="mt-6">
                <p className="text-lg font-medium text-zinc-700 leading-relaxed">{data.week_context.coach_reading}</p>
                <div className="mt-6 grid grid-cols-2 gap-3">
                  <div className="rounded-[1.2rem] border border-black/6 bg-zinc-50/80 p-4">
                    <p className="text-[0.65rem] font-bold uppercase tracking-[0.18em] text-zinc-500">Cycle</p>
                    <div className="mt-2 text-xl font-black tracking-[-0.04em] text-zinc-950">{data.week_context.planning.cycle_position}</div>
                  </div>
                  <div className="rounded-[1.2rem] border border-black/6 bg-zinc-50/80 p-4">
                    <p className="text-[0.65rem] font-bold uppercase tracking-[0.18em] text-zinc-500">S+1</p>
                    <div className="mt-2 text-xl font-black tracking-[-0.04em] text-zinc-950">{data.week_context.next_week.focus}</div>
                  </div>
                </div>
                {data.week_context.planning.deload_in_weeks > 0 && !data.week_context.planning.is_deload ? (
                  <p className="mt-4 text-sm font-medium text-zinc-500">
                    Assimilation dans {data.week_context.planning.deload_in_weeks} semaine{data.week_context.planning.deload_in_weeks > 1 ? "s" : ""}
                  </p>
                ) : null}
              </div>
            ) : (
              <div className="mt-6 grid gap-4">
                {(data.rationale.length ? data.rationale : ["Bloc actif sans alerte majeure."]).map((item) => (
                  <div key={item} className="rounded-[1.4rem] border border-black/6 bg-zinc-50/80 p-4 text-zinc-700">
                    {item}
                  </div>
                ))}
              </div>
            )}
            {data.risk_flags.length ? (
              <div className="mt-4 rounded-[1.4rem] border border-[rgba(212,24,61,0.14)] bg-[rgba(212,24,61,0.05)] p-4 text-[#b31333]">
                <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-[0.18em]">
                  <AlertTriangle className="h-4 w-4" />
                  Flags
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  {data.risk_flags.map((flag) => (
                    <span key={flag} className="rounded-full bg-white px-3 py-1.5 text-xs font-bold uppercase tracking-[0.14em]">{flag}</span>
                  ))}
                </div>
              </div>
            ) : null}
          </article>
        </div>
      </div>
    </div>
  );
}

function StatCard({
  label,
  value,
  icon: Icon,
  iconColor,
  iconBg,
}: {
  label: string;
  value: string;
  icon: typeof TrendingUp;
  iconColor: string;
  iconBg: string;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.96 }}
      animate={{ opacity: 1, scale: 1 }}
      className="rounded-[2rem] border border-black/5 bg-white p-6 shadow-sm transition-shadow hover:shadow-md"
    >
      <div className={`mb-4 flex h-14 w-14 items-center justify-center rounded-2xl ${iconBg}`}>
        <Icon className={`h-7 w-7 ${iconColor}`} />
      </div>
      <div className="text-3xl font-black tracking-[-0.05em] text-zinc-950">{value}</div>
      <div className="mt-1 text-sm font-bold uppercase tracking-[0.14em] text-zinc-500">{label}</div>
    </motion.div>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[1.2rem] border border-black/6 bg-zinc-50/80 p-4">
      <p className="text-xs font-bold uppercase tracking-[0.18em] text-zinc-500">{label}</p>
      <div className="mt-2 text-2xl font-black tracking-[-0.04em] text-zinc-950">{value}</div>
    </div>
  );
}
