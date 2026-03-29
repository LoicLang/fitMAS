import { addMonths, subMonths } from "date-fns";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { motion } from "motion/react";
import { useEffect, useMemo, useState } from "react";
import { Link, type LoaderFunctionArgs, useLoaderData, useNavigate, useSearchParams } from "react-router-dom";
import { loadCalendar } from "../../shared/api";
import { formatDateLong, formatMonthLabel, loadBandLabel, sportLabel } from "../../shared/format";
import type { CalendarView } from "../../types";
import { calendarStatusCount, initialSelectedDate } from "./view-model";

export async function calendarLoader({ request }: LoaderFunctionArgs) {
  const url = new URL(request.url);
  return loadCalendar(url.searchParams.get("month"));
}

const STATUS_STYLES: Record<string, string> = {
  done: "bg-[rgba(157,78,221,0.12)] text-[#9d4edd]",
  planned: "bg-zinc-100 text-zinc-700",
  adapted: "bg-[rgba(255,107,53,0.14)] text-[#c24f1f]",
  missing: "bg-[rgba(212,24,61,0.10)] text-[#d4183d]",
  offplan: "bg-[rgba(255,209,102,0.28)] text-[#8a6100]",
};

export function CalendarPage() {
  const data = useLoaderData() as CalendarView;
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [selectedDate, setSelectedDate] = useState(initialSelectedDate(data.days));

  useEffect(() => {
    setSelectedDate(initialSelectedDate(data.days));
  }, [data.days]);

  const selectedDay = useMemo(
    () => data.days.find((day) => day.date === selectedDate) || data.days.find((day) => day.is_today) || data.days[0],
    [data.days, selectedDate],
  );

  function shiftMonth(offset: number) {
    const current = new Date(`${data.month.key}-01T12:00:00`);
    const next = offset > 0 ? addMonths(current, offset) : subMonths(current, Math.abs(offset));
    const key = next.toISOString().slice(0, 7);
    const nextParams = new URLSearchParams(searchParams);
    nextParams.set("month", key);
    navigate(`/calendar?${nextParams.toString()}`);
  }

  return (
    <div className="min-h-screen px-6 pb-24 pt-8">
      <div className="mx-auto max-w-6xl">
        <div className="mb-12 flex items-center justify-between gap-6">
          <motion.div initial={{ opacity: 0, x: -20 }} animate={{ opacity: 1, x: 0 }}>
            <p className="eyebrow">Plan vivant</p>
            <h1 className="mt-6 text-5xl font-black tracking-[-0.08em] text-zinc-950 md:text-7xl">
              {formatMonthLabel(data.month.key)}
            </h1>
            <p className="mt-6 text-xl font-medium text-zinc-500">
              {data.month.week_label} · semaine {data.month.mesocycle_week} du cycle {data.month.mesocycle_number}
            </p>
            {data.calibration_status ? (
              <div className="mt-4 inline-flex items-center gap-2 rounded-full border border-black/8 bg-white/70 px-4 py-2 shadow-sm backdrop-blur-md">
                <span className="h-2 w-2 rounded-full bg-[var(--accent)]" />
                <span className="text-xs font-bold uppercase tracking-[0.16em] text-zinc-700">
                  {phaseLabel(data.calibration_status.phase)} · {data.calibration_status.label}
                </span>
              </div>
            ) : null}
          </motion.div>

          <div className="flex gap-4 self-start">
            <button type="button" onClick={() => shiftMonth(-1)} className="rounded-full border border-black/10 bg-white/60 p-3 text-zinc-900 shadow-sm transition hover:bg-white">
              <ChevronLeft className="h-5 w-5" />
            </button>
            <button type="button" onClick={() => shiftMonth(1)} className="rounded-full border border-black/10 bg-white/60 p-3 text-zinc-900 shadow-sm transition hover:bg-white">
              <ChevronRight className="h-5 w-5" />
            </button>
          </div>
        </div>

        {data.planning_contract || data.week_mission || data.last_adaptation ? (
          <section className="mb-8 grid gap-4 lg:grid-cols-[1.05fr_0.95fr]">
            {data.planning_contract ? (
              <article className="surface-panel p-6">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="meta-chip">{data.planning_contract.phase_label}</span>
                  <span className="meta-chip">{data.planning_contract.block_focus}</span>
                  {data.calibration_status ? <span className="meta-chip">{phaseLabel(data.calibration_status.phase)}</span> : null}
                </div>
                <h2 className="mt-4 text-3xl font-black tracking-[-0.05em] text-zinc-950">{data.planning_contract.horizon_summary}</h2>
                <p className="mt-3 text-base font-medium leading-relaxed text-zinc-600">
                  {data.planning_contract.next_inflexion}
                  {data.calibration_status ? ` ${data.calibration_status.summary}` : ""}
                </p>
                <div className="mt-5 flex flex-wrap gap-2">
                  {data.planning_contract.horizons.map((horizon) => (
                    <span key={horizon.key} className="rounded-full border border-black/6 bg-zinc-50 px-3 py-1.5 text-xs font-bold uppercase tracking-[0.14em] text-zinc-700">
                      {horizon.label} · {planningConfidenceLabel(horizon.confidence)}
                    </span>
                  ))}
                </div>
              </article>
            ) : null}

            <div className="grid gap-4">
              {data.week_mission ? (
                <article className="surface-panel p-6">
                  <p className="eyebrow">Mission</p>
                  <h2 className="mt-3 text-3xl font-black tracking-[-0.05em] text-zinc-950">{data.week_mission.objective}</h2>
                  <p className="mt-3 text-base font-medium leading-relaxed text-zinc-600">{data.week_mission.success_criteria}</p>
                </article>
              ) : null}
              {data.last_adaptation ? (
                <article className="surface-panel p-6">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="meta-chip">{data.last_adaptation.reason_label}</span>
                    <span className="meta-chip">{data.last_adaptation.impact_label}</span>
                  </div>
                  <p className="mt-4 text-lg font-bold text-zinc-950">{data.last_adaptation.summary}</p>
                  <p className="mt-2 text-sm font-medium leading-relaxed text-zinc-600">{data.last_adaptation.what_changed}</p>
                </article>
              ) : null}
            </div>
          </section>
        ) : null}

        <div className="mb-4 flex flex-wrap gap-2">
          {[
            ["planned", "prévu"],
            ["adapted", "adapté"],
            ["done", "fait"],
            ["missing", "manqué"],
            ["offplan", "hors plan"],
          ].map(([status, label]) => (
            <span key={status} className={`rounded-full px-3 py-1.5 text-xs font-bold uppercase tracking-[0.14em] ${STATUS_STYLES[status] || STATUS_STYLES.planned}`}>
              {label}
            </span>
          ))}
          {[
            ["committed", "ferme"],
            ["tentative", "probable"],
            ["projected", "projeté"],
          ].map(([confidence, label]) => (
            <span key={confidence} className="rounded-full border border-black/6 bg-white px-3 py-1.5 text-xs font-bold uppercase tracking-[0.14em] text-zinc-700">
              {label}
            </span>
          ))}
        </div>

        <div className="mb-4 grid grid-cols-7">
          {["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"].map((dayName) => (
            <div key={dayName} className="text-center text-xs font-bold uppercase tracking-[0.22em] text-zinc-500">
              {dayName}
            </div>
          ))}
        </div>

        <motion.section
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="overflow-hidden rounded-[2rem] border border-black/6 bg-white/55 p-4 shadow-inner backdrop-blur-sm"
        >
          <div className="grid grid-cols-7 gap-2">
            {data.days.map((day) => {
              const counts = calendarStatusCount(day);
              return (
                <button
                  key={day.date}
                  type="button"
                  onClick={() => setSelectedDate(day.date)}
                  className={`relative min-h-[6.8rem] rounded-[1.5rem] border p-3 text-left transition ${
                    day.date === selectedDay?.date
                      ? "border-black/10 bg-white shadow-sm"
                      : "border-black/5 bg-white/35 hover:bg-white/70"
                  } ${day.in_month ? "text-zinc-900" : "text-zinc-400"}`}
                >
                  <span className={`text-lg font-medium ${day.is_today ? "text-[var(--accent)]" : ""}`}>{day.day_number}</span>
                  <div className="mt-4 flex flex-wrap gap-1.5">
                    {counts.done ? <span className="h-2.5 w-2.5 rounded-full bg-[#9d4edd]" /> : null}
                    {counts.planned ? <span className="h-2.5 w-2.5 rounded-full bg-zinc-400" /> : null}
                    {counts.adapted ? <span className="h-2.5 w-2.5 rounded-full bg-[#ff6b35]" /> : null}
                    {counts.missing ? <span className="h-2.5 w-2.5 rounded-full bg-[#d4183d]" /> : null}
                    {counts.offplan ? <span className="h-2.5 w-2.5 rounded-full bg-[#ffd166]" /> : null}
                  </div>
                </button>
              );
            })}
          </div>
        </motion.section>

        <section className="mt-8 grid gap-5 lg:grid-cols-[0.85fr_1.15fr]">
          <article className="surface-panel p-6">
            <p className="eyebrow">{formatDateLong(selectedDay?.date)}</p>
            <h2 className="mt-4 text-3xl font-black tracking-[-0.05em] text-zinc-950">
              {selectedDay?.items.length ? `${selectedDay.items.length} entrée${selectedDay.items.length > 1 ? "s" : ""}` : "Jour libre"}
            </h2>
            <p className="mt-4 text-base font-medium text-zinc-500">
              Le prévu, l'adapté et le réalisé restent distincts. Ici, le calendrier dit ce qui fait foi.
            </p>
            {selectedDay?.items.length ? (
              <div className="mt-6 grid gap-3">
                <SummaryRow label="Engagé" value={String(selectedDay.items.filter((item) => item.confidence === "committed").length)} />
                <SummaryRow label="Flexible" value={String(selectedDay.items.filter((item) => item.confidence === "tentative").length)} />
                <SummaryRow label="Projeté" value={String(selectedDay.items.filter((item) => item.confidence === "projected").length)} />
              </div>
            ) : null}
          </article>

          <div className="grid gap-4">
            {(selectedDay?.items.length ? selectedDay.items : []).map((item, index) => (
              <motion.div
                key={`${item.kind}-${item.id}-${item.display_date}`}
                initial={{ opacity: 0, y: 18, scale: 0.98 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                transition={{ duration: 0.4, delay: index * 0.06 }}
              >
                {item.kind === "session" ? (
                  <Link to={`/workout/${item.id}`} className="surface-panel block overflow-hidden">
                    <div className="p-6">
                      <div className="flex items-start justify-between gap-4">
                        <div>
                          <span className={`rounded-full px-4 py-2 text-xs font-bold uppercase tracking-[0.14em] ${STATUS_STYLES[item.status] || STATUS_STYLES.planned}`}>
                            {statusLabel(item.status)}
                          </span>
                          <h3 className="mt-5 text-3xl font-black uppercase tracking-[-0.06em] text-zinc-950">{item.title}</h3>
                          <p className="mt-3 text-base font-medium text-zinc-500">{item.goal}</p>
                        </div>
                        <div className="flex h-12 w-12 items-center justify-center rounded-full border border-black/6 bg-zinc-50 text-[var(--accent)]">
                          <ChevronRight className="h-5 w-5" />
                        </div>
                      </div>
                      <div className="mt-5 flex flex-wrap gap-2">
                        {item.confidence ? (
                          <span className="rounded-xl border border-black/5 bg-white px-3 py-1.5 text-xs font-bold uppercase tracking-[0.14em] text-zinc-700">
                            {planningConfidenceLabel(item.confidence)}
                          </span>
                        ) : null}
                        {item.role ? (
                          <span className="rounded-xl border border-black/5 bg-white px-3 py-1.5 text-xs font-bold uppercase tracking-[0.14em] text-zinc-700">
                            {roleLabel(item.role)}
                          </span>
                        ) : null}
                        <span className="rounded-xl border border-black/5 bg-zinc-100 px-3 py-1.5 text-xs font-bold text-zinc-700">
                          {sportLabel(item.sport_type)}
                        </span>
                        <span className="rounded-xl border border-black/5 bg-zinc-100 px-3 py-1.5 text-xs font-bold text-zinc-700">
                          {item.duration_min ? `${item.duration_min} min` : "Libre"}
                        </span>
                        <span className="rounded-xl border border-black/5 bg-zinc-100 px-3 py-1.5 text-xs font-bold text-zinc-700">
                          {loadBandLabel(item.load_band)}
                        </span>
                      </div>
                    </div>
                  </Link>
                ) : (
                  <div className="surface-panel p-6">
                    <span className={`rounded-full px-4 py-2 text-xs font-bold uppercase tracking-[0.14em] ${STATUS_STYLES.offplan}`}>offplan</span>
                    <h3 className="mt-5 text-3xl font-black uppercase tracking-[-0.06em] text-zinc-950">{item.title}</h3>
                    <p className="mt-3 text-base font-medium text-zinc-500">{sportLabel(item.sport_type)} · {item.display_date}</p>
                    <div className="mt-5 flex flex-wrap gap-2">
                      <span className="rounded-xl border border-black/5 bg-zinc-100 px-3 py-1.5 text-xs font-bold text-zinc-700">
                        {item.duration_min ? `${item.duration_min} min` : "Durée inconnue"}
                      </span>
                      <span className="rounded-xl border border-black/5 bg-zinc-100 px-3 py-1.5 text-xs font-bold text-zinc-700">
                        {loadBandLabel(item.load_band)}
                      </span>
                    </div>
                  </div>
                )}
              </motion.div>
            ))}

            {!selectedDay?.items.length ? (
              <div className="surface-panel p-6 text-zinc-500">Aucune séance ni activité sur ce jour.</div>
            ) : null}
          </div>
        </section>
      </div>
    </div>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[1.2rem] border border-black/6 bg-zinc-50/80 p-4">
      <p className="text-xs font-bold uppercase tracking-[0.18em] text-zinc-500">{label}</p>
      <div className="mt-2 text-2xl font-black tracking-[-0.04em] text-zinc-950">{value}</div>
    </div>
  );
}

function statusLabel(status: string) {
  if (status === "planned") return "prévu";
  if (status === "adapted") return "adapté";
  if (status === "done") return "fait";
  if (status === "missing") return "manqué";
  if (status === "offplan") return "hors plan";
  return status;
}

function planningConfidenceLabel(confidence: string) {
  if (confidence === "committed") return "ferme";
  if (confidence === "tentative") return "probable";
  if (confidence === "projected") return "projeté";
  return confidence;
}

function roleLabel(role: string) {
  if (role === "key") return "clé";
  if (role === "support") return "support";
  if (role === "recovery") return "récup";
  if (role === "optional") return "option";
  return role;
}

function phaseLabel(phase: string) {
  if (phase === "draft") return "first draft";
  if (phase === "calibrating") return "calibrage";
  if (phase === "stable") return "stable";
  return phase;
}
