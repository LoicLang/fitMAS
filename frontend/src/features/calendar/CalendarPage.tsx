import { addMonths, subMonths } from "date-fns";
import { CalendarClock, ChevronLeft, ChevronRight } from "lucide-react";
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
  done: "border-cyan-300/30 bg-cyan-300/12 text-cyan-100",
  planned: "border-white/10 bg-white/[0.04] text-white/80",
  missing: "border-rose-300/25 bg-rose-400/10 text-rose-100",
  offplan: "border-amber-300/25 bg-amber-400/10 text-amber-100",
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
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-8 px-5 pb-14 md:px-8">
      <section className="flex flex-wrap items-start justify-between gap-6 pt-6 md:pt-10">
        <div>
          <p className="eyebrow">Calendrier cockpit</p>
          <h1 className="mt-3 text-[clamp(3rem,10vw,5.8rem)] font-bold uppercase tracking-[-0.08em] text-white">
            {formatMonthLabel(data.month.key)}
          </h1>
          <p className="mt-4 max-w-2xl text-lg font-medium text-white/64">
            {data.month.week_label} · semaine {data.month.mesocycle_week} du cycle {data.month.mesocycle_number}
            {data.month.is_deload ? " · récupération active" : ""}
          </p>
        </div>
        <div className="flex gap-3">
          <button type="button" className="action-button-ghost h-12 w-12 rounded-full p-0" onClick={() => shiftMonth(-1)}>
            <ChevronLeft className="h-5 w-5" />
          </button>
          <button type="button" className="action-button-ghost h-12 w-12 rounded-full p-0" onClick={() => shiftMonth(1)}>
            <ChevronRight className="h-5 w-5" />
          </button>
        </div>
      </section>

      <section className="surface-panel overflow-hidden p-4 md:p-6">
        <div className="grid grid-cols-7 gap-2 pb-4 text-center font-mono text-[0.72rem] font-semibold uppercase tracking-[0.22em] text-white/34">
          {["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"].map((dayName) => (
            <span key={dayName}>{dayName}</span>
          ))}
        </div>
        <motion.div initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} className="grid grid-cols-7 gap-2">
          {data.days.map((day) => {
            const counts = calendarStatusCount(day);
            return (
              <button
                key={day.date}
                type="button"
                onClick={() => setSelectedDate(day.date)}
                className={`min-h-[6.5rem] rounded-[1.5rem] border p-3 text-left transition ${
                  day.date === selectedDay?.date
                    ? "border-cyan-300/30 bg-white/[0.08] shadow-[0_0_0_1px_rgba(103,232,249,0.16)]"
                    : "border-white/8 bg-black/20 hover:bg-white/[0.04]"
                } ${day.in_month ? "text-white" : "text-white/24"}`}
              >
                <div className="flex items-start justify-between gap-2">
                  <span className={`text-lg font-semibold ${day.is_today ? "text-cyan-200" : ""}`}>{day.day_number}</span>
                  {day.is_current_week ? <span className="h-2.5 w-2.5 rounded-full bg-cyan-300/75" /> : null}
                </div>
                <div className="mt-5 flex flex-wrap gap-1.5">
                  {counts.done ? <span className="h-2 w-2 rounded-full bg-cyan-300" /> : null}
                  {counts.planned ? <span className="h-2 w-2 rounded-full bg-white/45" /> : null}
                  {counts.missing ? <span className="h-2 w-2 rounded-full bg-rose-300" /> : null}
                  {counts.offplan ? <span className="h-2 w-2 rounded-full bg-amber-300" /> : null}
                </div>
              </button>
            );
          })}
        </motion.div>
      </section>

      <section className="grid gap-5 lg:grid-cols-[0.9fr_1.1fr]">
        <article className="surface-panel p-6">
          <p className="eyebrow">Jour sélectionné</p>
          <h2 className="mt-3 text-3xl font-bold tracking-[-0.06em]">{formatDateLong(selectedDay?.date)}</h2>
          <p className="mt-3 soft-copy">
            Prévu vs réel. Une activité hors plan reste distincte et ne valide pas une séance du mauvais sport.
          </p>
        </article>

        <div className="grid gap-4">
          {(selectedDay?.items.length ? selectedDay.items : data.feed.slice(0, 5)).map((item, index) => (
            <motion.div
              key={`${item.kind}-${item.id}-${item.display_date}`}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.32, delay: index * 0.05 }}
            >
              {item.kind === "session" ? (
                <Link to={`/workout/${item.id}`} className="surface-panel block p-5 hover:bg-white/[0.07]">
                  <div className="flex flex-wrap items-start justify-between gap-4">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className={`meta-chip ${STATUS_STYLES[item.status] || ""}`}>{item.status}</span>
                        <span className="meta-chip">{item.label}</span>
                      </div>
                      <h3 className="mt-4 text-2xl font-bold tracking-[-0.05em]">{item.title}</h3>
                      <p className="mt-2 soft-copy">{item.goal}</p>
                    </div>
                    <ArrowLink />
                  </div>
                  <div className="mt-5 flex flex-wrap gap-2">
                    <span className="meta-chip">{sportLabel(item.sport_type)}</span>
                    <span className="meta-chip">{item.duration_min ? `${item.duration_min} min` : "Libre"}</span>
                    <span className="meta-chip">{loadBandLabel(item.load_band)}</span>
                    {item.executed_date ? <span className="meta-chip">réalisée {item.executed_date}</span> : null}
                  </div>
                </Link>
              ) : (
                <div className="surface-panel border-amber-300/15 p-5">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <span className={`meta-chip ${STATUS_STYLES.offplan}`}>offplan</span>
                      <h3 className="mt-4 text-2xl font-bold tracking-[-0.05em]">{item.title}</h3>
                      <p className="mt-2 soft-copy">{sportLabel(item.sport_type)} · {item.display_date}</p>
                    </div>
                    <CalendarClock className="h-5 w-5 text-amber-200" />
                  </div>
                  <div className="mt-5 flex flex-wrap gap-2">
                    <span className="meta-chip">{item.duration_min ? `${item.duration_min} min` : "Durée inconnue"}</span>
                    <span className="meta-chip">{loadBandLabel(item.load_band)}</span>
                  </div>
                </div>
              )}
            </motion.div>
          ))}
        </div>
      </section>
    </div>
  );
}

function ArrowLink() {
  return (
    <span className="inline-flex h-11 w-11 items-center justify-center rounded-full border border-cyan-300/25 bg-cyan-300/10 text-cyan-100">
      <ChevronRight className="h-5 w-5" />
    </span>
  );
}
