import { Activity, Flame, Target, TrendingUp } from "lucide-react";
import { motion } from "motion/react";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis } from "recharts";
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
  const history = data.history.map((point) => ({
    label: point.date.slice(5),
    ctl: point.ctl,
    atl: point.atl,
  }));

  return (
    <div className="min-h-screen px-5 pb-24 pt-6 md:px-8">
      <div className="mx-auto max-w-6xl">
        <motion.header initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} className="mb-5">
          <p className="eyebrow">Progression</p>
          <h1 className="mt-2 text-4xl font-black uppercase tracking-[-0.06em] text-zinc-950 md:text-6xl">Charge</h1>
          <p className="mt-2 text-base font-medium text-zinc-500">
            {data.week.label} · {data.load.freshness} · {Math.round(data.tss.actual)} / {Math.round(data.tss.target)} TSS
          </p>
        </motion.header>

        <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard label="CTL" value={ctlNow.toFixed(1)} icon={TrendingUp} />
          <StatCard label="TSS semaine" value={`${Math.round(data.tss.actual)} / ${Math.round(data.tss.target)}`} icon={Target} />
          <StatCard label="Complétion" value={percent(executionRatio)} icon={Activity} />
          <StatCard label="Fatigue" value={`${data.load.atl.toFixed(1)} ATL`} icon={Flame} />
        </section>

        <section className="mt-5 grid gap-4 lg:grid-cols-[1.1fr_0.9fr]">
          <article className="surface-panel p-5 md:p-6">
            <div className="mb-4 flex items-center justify-between gap-3">
              <div>
                <p className="eyebrow">Tendance</p>
                <h2 className="mt-2 text-2xl font-black tracking-[-0.04em] text-zinc-950">Tendance récente</h2>
              </div>
              <span className="meta-chip">{data.load.freshness}</span>
            </div>
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={history} margin={{ top: 8, right: 4, left: -20, bottom: 0 }}>
                  <defs>
                    <linearGradient id="fitmasLoadArea" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#ff6b35" stopOpacity={0.28} />
                      <stop offset="95%" stopColor="#ff6b35" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <XAxis dataKey="label" stroke="#a1a1aa" fontSize={12} tickLine={false} axisLine={false} fontWeight="bold" />
                  <Tooltip contentStyle={tooltipStyle} />
                  <Area type="monotone" dataKey="ctl" stroke="#ff6b35" strokeWidth={3} fill="url(#fitmasLoadArea)" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </article>

          <article className="surface-panel p-5 md:p-6">
            <div className="mb-4">
              <p className="eyebrow">Prévu vs fait</p>
              <h2 className="mt-2 text-2xl font-black tracking-[-0.04em] text-zinc-950">Semaine</h2>
            </div>
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data.week_daily} margin={{ top: 8, right: 4, left: -20, bottom: 0 }}>
                  <CartesianGrid stroke="rgba(0,0,0,0.05)" vertical={false} />
                  <XAxis dataKey="label" tickLine={false} axisLine={false} stroke="#a1a1aa" fontSize={12} />
                  <Tooltip contentStyle={tooltipStyle} />
                  <Bar dataKey="planned_tss" fill="#9d4edd" radius={[8, 8, 0, 0]} name="Prévu" />
                  <Bar dataKey="actual_tss" fill="#ff6b35" radius={[8, 8, 0, 0]} name="Fait" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </article>
        </section>

        <section className="mt-5 grid gap-4 lg:grid-cols-[0.9fr_1.1fr]">
          <article className="surface-panel p-5 md:p-6">
            <p className="eyebrow">Répartition</p>
            <div className="mt-4 grid gap-3">
              {Object.entries(data.distribution.planned).map(([band, value]) => {
                const completed = data.distribution.completed[band]?.count || 0;
                const ratio = value.count ? Math.min(100, (completed / value.count) * 100) : 0;
                return (
                  <div key={band} className="rounded-[1.2rem] border border-black/6 bg-zinc-50/80 p-4">
                    <div className="flex items-center justify-between gap-3">
                      <span className="font-bold text-zinc-900">{loadBandLabel(band)}</span>
                      <span className="text-sm font-semibold text-zinc-500">{completed} / {value.count}</span>
                    </div>
                    <div className="mt-3 h-2 overflow-hidden rounded-full bg-zinc-200">
                      <div className="h-full rounded-full bg-[var(--accent)]" style={{ width: `${ratio}%` }} />
                    </div>
                  </div>
                );
              })}
            </div>
          </article>

          <article className="surface-panel p-5 md:p-6">
            <p className="eyebrow">Prochaines semaines</p>
            <div className="mt-4 grid gap-3">
              {data.forecast.slice(0, 4).map((forecast) => (
                <div key={`${forecast.week_index}-${forecast.cycle_week}`} className="flex items-center justify-between gap-4 rounded-[1.2rem] border border-black/6 bg-zinc-50/80 p-4">
                  <div>
                    <p className="text-sm font-black tracking-[-0.03em] text-zinc-950">Semaine +{forecast.week_index}</p>
                    <p className="mt-1 text-sm font-medium text-zinc-500">{forecast.focus}</p>
                  </div>
                  <div className="text-right">
                    <p className="text-xl font-black tracking-[-0.04em] text-zinc-950">{Math.round(forecast.target_tss)}</p>
                    <p className="text-xs font-bold uppercase tracking-[0.14em] text-zinc-500">TSS</p>
                  </div>
                </div>
              ))}
            </div>
          </article>
        </section>
      </div>
    </div>
  );
}

const tooltipStyle = {
  backgroundColor: "#ffffff",
  borderColor: "#f4f4f5",
  borderRadius: "14px",
  boxShadow: "0 10px 25px -5px rgba(0, 0, 0, 0.08)",
};

function StatCard({ label, value, icon: Icon }: { label: string; value: string; icon: typeof TrendingUp }) {
  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="surface-panel p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-[0.64rem] font-bold uppercase tracking-[0.16em] text-zinc-500">{label}</p>
          <p className="mt-2 text-3xl font-black tracking-[-0.05em] text-zinc-950">{value}</p>
        </div>
        <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-zinc-50 text-[var(--accent)]">
          <Icon className="h-5 w-5" />
        </div>
      </div>
    </motion.div>
  );
}
