import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { AlertTriangle, ArrowUpRight, Gauge, Target, TrendingUp } from "lucide-react";
import { motion } from "motion/react";
import { type LoaderFunctionArgs, useLoaderData } from "react-router-dom";
import { loadEvolution } from "../../shared/api";
import { loadBandLabel } from "../../shared/format";
import type { EvolutionView } from "../../types";
import { latestCtl, weeklyExecutionRatio } from "./view-model";

export async function evolutionLoader(_: LoaderFunctionArgs) {
  return loadEvolution();
}

export function EvolutionPage() {
  const data = useLoaderData() as EvolutionView;
  const executionRatio = weeklyExecutionRatio(data);
  const ctlNow = latestCtl(data);

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-8 px-5 pb-14 md:px-8">
      <section className="pt-6 md:pt-10">
        <p className="eyebrow">Cockpit de charge</p>
        <h1 className="mt-3 text-[clamp(3rem,10vw,5.8rem)] font-bold uppercase tracking-[-0.08em] text-white">
          Évolution
        </h1>
        <p className="mt-4 max-w-3xl text-lg font-medium text-white/64">
          Lecture froide du bloc. Charge réelle, prévu vs réalisé, contexte mésocycle et vision de montée à 4 semaines.
        </p>
      </section>

      <section className="grid gap-5 xl:grid-cols-[1.2fr_0.8fr]">
        <article className="surface-panel p-6 md:p-8">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="eyebrow">Historique charge réelle</p>
              <div className="mt-3 flex items-end gap-3">
                <span className="text-5xl font-bold tracking-[-0.08em]">{ctlNow.toFixed(1)}</span>
                <span className="pb-2 text-white/42">CTL</span>
              </div>
            </div>
            <span className="inline-flex items-center gap-2 rounded-full border border-cyan-300/20 bg-cyan-300/10 px-4 py-2 text-sm font-semibold text-cyan-100">
              <TrendingUp className="h-4 w-4" />
              ramp {data.load.ramp_rate}
            </span>
          </div>

          <div className="mt-8 h-[22rem]">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={data.history}>
                <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
                <XAxis dataKey="date" tickLine={false} axisLine={false} stroke="rgba(255,255,255,0.4)" tickFormatter={(value) => value.slice(5)} />
                <YAxis tickLine={false} axisLine={false} stroke="rgba(255,255,255,0.4)" />
                <Tooltip
                  contentStyle={{
                    background: "rgba(5,8,11,0.96)",
                    border: "1px solid rgba(255,255,255,0.08)",
                    borderRadius: "18px",
                    color: "white",
                  }}
                />
                <Legend />
                <Line type="monotone" dataKey="ctl" stroke="#67e8f9" strokeWidth={3} dot={false} name="CTL" />
                <Line type="monotone" dataKey="atl" stroke="#fb923c" strokeWidth={2.4} dot={false} name="ATL" />
                <Line type="monotone" dataKey="tsb" stroke="#94a3b8" strokeWidth={2} dot={false} name="TSB" />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </article>

        <div className="grid gap-5">
          <StatCard
            eyebrow="Semaine bloc"
            title={data.week.label}
            detail={`${data.completion.done_this_week} / ${data.completion.sessions_this_week} séances réalisées`}
            accent={`${Math.round(executionRatio * 100)}%`}
            icon={Target}
          />
          <StatCard
            eyebrow="Prévu vs réalisé"
            title={`${Math.round(data.tss.actual)} / ${Math.round(data.tss.target)} TSS`}
            detail={`reste ${Math.round(data.tss.remaining)} · delta ${Math.round(data.tss.delta)}`}
            accent={data.week.planning_mode || "maintain_load"}
            icon={Gauge}
          />
          <StatCard
            eyebrow="État"
            title={`${data.load.freshness}`}
            detail={`ATL ${data.load.atl.toFixed(1)} · TSB ${data.load.tsb.toFixed(1)}`}
            accent={data.week.is_deload ? "deload" : data.week.adaptation_level || "stable"}
            icon={TrendingUp}
          />
        </div>
      </section>

      <section className="grid gap-5 xl:grid-cols-[0.95fr_1.05fr]">
        <article className="surface-panel p-6 md:p-8">
          <div className="flex items-center justify-between">
            <div>
              <p className="eyebrow">Prévu vs réalisé</p>
              <h2 className="mt-3 text-3xl font-bold tracking-[-0.06em]">Semaine en cours</h2>
            </div>
            <span className="meta-chip">{data.week.intensity_distribution || "balanced"}</span>
          </div>
          <div className="mt-8 h-[21rem]">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data.week_daily}>
                <CartesianGrid stroke="rgba(255,255,255,0.05)" vertical={false} />
                <XAxis dataKey="label" tickLine={false} axisLine={false} stroke="rgba(255,255,255,0.4)" />
                <YAxis tickLine={false} axisLine={false} stroke="rgba(255,255,255,0.4)" />
                <Tooltip
                  contentStyle={{
                    background: "rgba(5,8,11,0.96)",
                    border: "1px solid rgba(255,255,255,0.08)",
                    borderRadius: "18px",
                    color: "white",
                  }}
                />
                <Legend />
                <Bar dataKey="planned_tss" fill="#67e8f9" radius={[8, 8, 0, 0]} name="Prévu" />
                <Bar dataKey="actual_tss" fill="#fb923c" radius={[8, 8, 0, 0]} name="Réalisé" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </article>

        <article className="surface-panel p-6 md:p-8">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="eyebrow">Projection bloc</p>
              <h2 className="mt-3 text-3xl font-bold tracking-[-0.06em]">4 semaines à venir</h2>
            </div>
            <span className="meta-chip">{data.week.mesocycle_week}/4</span>
          </div>
          <div className="mt-6 grid gap-4 md:grid-cols-2">
            {data.forecast.map((forecast, index) => (
              <motion.div
                key={`${forecast.week_index}-${forecast.cycle_week}`}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.28, delay: index * 0.05 }}
                className="rounded-[1.7rem] border border-white/10 bg-white/[0.04] p-5"
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="eyebrow">Semaine +{forecast.week_index}</p>
                    <div className="mt-3 text-3xl font-bold tracking-[-0.06em]">{Math.round(forecast.target_tss)}</div>
                    <p className="mt-1 text-sm text-white/46">TSS cible</p>
                  </div>
                  <span className="meta-chip">{forecast.focus}</span>
                </div>
                <div className="mt-5 flex items-end gap-2">
                  <span className="text-2xl font-bold tracking-[-0.05em]">{forecast.projected_ctl.toFixed(1)}</span>
                  <span className="pb-1 text-white/40">CTL projeté</span>
                </div>
                <p className="mt-2 soft-copy">
                  cycle {forecast.cycle_week}/4 · {forecast.is_deload ? "assimilation" : forecast.planning_mode}
                </p>
              </motion.div>
            ))}
          </div>
        </article>
      </section>

      <section className="grid gap-5 xl:grid-cols-[0.9fr_1.1fr]">
        <article className="surface-panel p-6">
          <p className="eyebrow">Distribution charge</p>
          <div className="mt-6 grid gap-3">
            {Object.entries(data.distribution.planned).map(([band, value]) => {
              const completed = data.distribution.completed[band]?.count || 0;
              return (
                <div key={band} className="rounded-[1.4rem] border border-white/8 bg-black/20 p-4">
                  <div className="flex items-center justify-between gap-3">
                    <span className="font-semibold text-white">{loadBandLabel(band)}</span>
                    <span className="text-sm text-white/48">{completed} / {value.count} séances</span>
                  </div>
                  <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/7">
                    <div className="h-full rounded-full bg-cyan-300" style={{ width: `${value.count ? (completed / value.count) * 100 : 0}%` }} />
                  </div>
                </div>
              );
            })}
          </div>
        </article>

        <article className="surface-panel p-6">
          <p className="eyebrow">Lecture coach</p>
          <div className="mt-6 grid gap-4">
            {(data.rationale.length ? data.rationale : ["Bloc actif sans alerte majeure."]).map((item) => (
              <div key={item} className="rounded-[1.4rem] border border-white/8 bg-black/20 p-4 text-white/74">
                {item}
              </div>
            ))}
            {data.risk_flags.length ? (
              <div className="rounded-[1.4rem] border border-amber-300/20 bg-amber-400/8 p-4 text-amber-100">
                <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-[0.18em]">
                  <AlertTriangle className="h-4 w-4" />
                  Flags
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  {data.risk_flags.map((flag) => (
                    <span key={flag} className="meta-chip border-amber-300/20 bg-amber-400/8 text-amber-100">{flag}</span>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        </article>
      </section>
    </div>
  );
}

function StatCard({
  eyebrow,
  title,
  detail,
  accent,
  icon: Icon,
}: {
  eyebrow: string;
  title: string;
  detail: string;
  accent: string;
  icon: typeof TrendingUp;
}) {
  return (
    <article className="surface-panel p-6">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="eyebrow">{eyebrow}</p>
          <h2 className="mt-3 text-3xl font-bold tracking-[-0.05em]">{title}</h2>
          <p className="mt-3 soft-copy">{detail}</p>
        </div>
        <div className="flex h-12 w-12 items-center justify-center rounded-full border border-cyan-300/20 bg-cyan-300/10 text-cyan-100">
          <Icon className="h-5 w-5" />
        </div>
      </div>
      <div className="mt-5 inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.2em] text-white/72">
        {accent}
        <ArrowUpRight className="h-3.5 w-3.5" />
      </div>
    </article>
  );
}
