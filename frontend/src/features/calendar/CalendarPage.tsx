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
            <p className="eyebrow">Calendrier cockpit</p>
            <h1 className="mt-6 text-5xl font-black tracking-[-0.08em] text-zinc-950 md:text-7xl">
              {formatMonthLabel(data.month.key)}
            </h1>
            <p className="mt-6 text-xl font-medium text-zinc-500">
              {data.month.week_label} · semaine {data.month.mesocycle_week} du cycle {data.month.mesocycle_number}
            </p>
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
              Le prévu et le réalisé restent distincts. Une activité hors plan ne valide pas une séance du mauvais sport.
            </p>
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
                            {item.status}
                          </span>
                          <h3 className="mt-5 text-3xl font-black uppercase tracking-[-0.06em] text-zinc-950">{item.title}</h3>
                          <p className="mt-3 text-base font-medium text-zinc-500">{item.goal}</p>
                        </div>
                        <div className="flex h-12 w-12 items-center justify-center rounded-full border border-black/6 bg-zinc-50 text-[var(--accent)]">
                          <ChevronRight className="h-5 w-5" />
                        </div>
                      </div>
                      <div className="mt-5 flex flex-wrap gap-2">
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
