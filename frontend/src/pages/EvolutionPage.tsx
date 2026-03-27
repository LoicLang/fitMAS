import { ArrowUpRight, TrendingUp } from "lucide-react";
import { motion } from "motion/react";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useMemo } from "react";
import { useAppState } from "../state/app-state";
import { formatWeekAxis } from "../lib/format";

export function EvolutionPage() {
  const { data } = useAppState();

  const hasLoadHistory = useMemo(() => {
    return (data?.trainingLoad.series || []).some((point) => point.ctl > 0 || point.atl > 0);
  }, [data?.trainingLoad.series]);

  const chartData = useMemo(() => {
    if (!data) return [];
    if (hasLoadHistory) {
      return (data.trainingLoad.series || []).slice(-8).map((point) => ({
        label: formatWeekAxis(point.date),
        charge: Math.round(point.ctl),
        fatigue: Math.round(point.atl),
      }));
    }

    let cumulativeHours = 0;
    return data.week.days.map((day) => {
      cumulativeHours += (day.duration_min || 0) / 60;
      return {
        label: day.label.slice(0, 3),
        charge: Number(cumulativeHours.toFixed(1)),
        fatigue: Number((cumulativeHours * 0.78).toFixed(1)),
      };
    });
  }, [data, hasLoadHistory]);

  if (!data) return null;

  const { performanceOverview } = data;
  const plannedHours = Number((data.week.days.reduce((total, day) => total + (day.duration_min || 0), 0) / 60).toFixed(1));
  const plannedSessions = data.week.days.filter((day) => day.sport_type !== "rest").length;
  const progressPercent = Math.min(
    100,
    Math.max(
      plannedSessions ? 12 : 8,
      performanceOverview.completion.sessions_this_week
        ? (performanceOverview.completion.done_this_week / performanceOverview.completion.sessions_this_week) * 100
        : 8,
    ),
  );
  const chartMetric = hasLoadHistory ? Math.round(performanceOverview.load.ctl) : plannedHours;
  const chartUnit = hasLoadHistory ? "CTL actuel" : "heures planifiées";
  const chartLabel = hasLoadHistory ? "Charge pilotée" : "Volume semaine";
  const chartBadge = hasLoadHistory ? performanceOverview.load.ramp_rate : `+${plannedSessions} séances`;

  return (
    <section className="evolution-page">
      <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} className="page-heading">
        <h1>Évolution</h1>
        <p>
          La constance crée l&apos;endurance. Analyse la progression réelle de ta charge et la montée prévue sur le bloc actif.
        </p>
      </motion.div>

      <div className="evolution-grid">
        <motion.article className="glass-card chart-hero-card" initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }}>
          <div className="chart-hero-head">
            <div>
              <span className="card-label">{chartLabel}</span>
              <div className="headline-metric">
                <strong>{chartMetric}</strong>
                <small>{chartUnit}</small>
              </div>
            </div>
            <div className="trend-badge">
              <TrendingUp size={16} />
              {chartBadge}
            </div>
          </div>

          <div className="chart-wrap">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartData}>
                <defs>
                  <linearGradient id="fitmasCharge" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#22d3ee" stopOpacity={0.55} />
                    <stop offset="95%" stopColor="#22d3ee" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="rgba(255,255,255,0.04)" vertical={false} />
                <XAxis dataKey="label" tickLine={false} axisLine={false} stroke="#666" />
                <YAxis tickLine={false} axisLine={false} stroke="#666" />
                <Tooltip
                  contentStyle={{
                    background: "#0d0f14",
                    border: "1px solid rgba(255,255,255,0.08)",
                    borderRadius: "16px",
                  }}
                />
                <Area type="monotone" dataKey="charge" stroke="#22d3ee" strokeWidth={3} fill="url(#fitmasCharge)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </motion.article>

        <div className="evolution-side">
          <article className="glass-card side-metric-card">
            <span className="card-label">Vision bloc</span>
            <div className="side-metric-stack">
              <strong>{performanceOverview.week.label}</strong>
              <small>{performanceOverview.completion.done_this_week} / {plannedSessions} séances engagées</small>
            </div>
            <div className="thin-progress">
              <div style={{ width: `${progressPercent}%` }} />
            </div>
            <div className="metric-footer">
              <span>{performanceOverview.completion.done_this_week} faites</span>
              <span>{plannedSessions} prévues</span>
            </div>
          </article>

          <article className="glass-card image-metric-card">
            <div className="image-scrim" />
            <span className="card-label">Montée de charge</span>
            <strong>{Math.round(performanceOverview.tss.target || 0)}</strong>
            <small>TSS cible semaine · réel {Math.round(performanceOverview.tss.actual || 0)}</small>
            <button type="button" className="inline-link">
              Voir le pilotage <ArrowUpRight size={14} />
            </button>
          </article>
        </div>
      </div>

      <div className="dashboard-row">
        <div className="glass-card stats-panel">
          <p className="card-label">Répartition prévue</p>
          <div className="stats-grid compact">
            {Object.entries(performanceOverview.distribution.planned).map(([band, value]) => (
              <div key={band} className="stat-box">
                <span>{band}</span>
                <strong>{value.count}</strong>
              </div>
            ))}
          </div>
        </div>

        <div className="glass-card stats-panel">
          <p className="card-label">Lecture coach</p>
          <ul className="bullet-list">
            {(performanceOverview.rationale.length ? performanceOverview.rationale : ["Bloc actif sans risque majeur signalé."]).map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}
