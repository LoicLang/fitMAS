import { addMonths, subMonths } from "date-fns";
import { ChevronLeft, ChevronRight, MoveRight } from "lucide-react";
import { motion } from "motion/react";
import { useEffect, useMemo, useState } from "react";
import { Link, type LoaderFunctionArgs, useLoaderData, useNavigate, useSearchParams } from "react-router-dom";
import { loadCalendar } from "../../shared/api";
import { formatDateLong, formatMonthLabel, loadBandLabel, sportLabel } from "../../shared/format";
import type { CalendarItem, CalendarView } from "../../types";
import { calendarStatusCount, initialSelectedDate } from "./view-model";

export async function calendarLoader({ request }: LoaderFunctionArgs) {
  const url = new URL(request.url);
  return loadCalendar(url.searchParams.get("month"));
}

const STATUS_STYLES: Record<string, string> = {
  done: "bg-[rgba(157,78,221,0.14)] text-[#7c2bbf]",
  planned: "bg-zinc-100 text-zinc-700",
  adapted: "bg-[rgba(255,107,53,0.15)] text-[#c24f1f]",
  missing: "bg-[rgba(212,24,61,0.10)] text-[#d4183d]",
  offplan: "bg-[rgba(255,209,102,0.30)] text-[#8a6100]",
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
    <div className="min-h-screen px-5 pb-24 pt-6 md:px-8">
      <div className="mx-auto max-w-6xl">
        <header className="mb-5 flex items-end justify-between gap-4">
          <motion.div initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }}>
            <p className="eyebrow">Planning</p>
            <h1 className="mt-2 text-4xl font-black uppercase tracking-[-0.06em] text-zinc-950 md:text-6xl">
              {formatMonthLabel(data.month.key)}
            </h1>
            <p className="mt-2 text-sm font-bold uppercase tracking-[0.14em] text-zinc-500">
              {data.month.week_label} · S{data.month.mesocycle_week} · Cycle {data.month.mesocycle_number}
            </p>
          </motion.div>
          <div className="flex gap-2">
            <button type="button" onClick={() => shiftMonth(-1)} className="flex h-11 w-11 items-center justify-center rounded-full border border-black/8 bg-white/70 shadow-sm">
              <ChevronLeft className="h-5 w-5" />
            </button>
            <button type="button" onClick={() => shiftMonth(1)} className="flex h-11 w-11 items-center justify-center rounded-full border border-black/8 bg-white/70 shadow-sm">
              <ChevronRight className="h-5 w-5" />
            </button>
          </div>
        </header>

        <div className="mb-4 flex gap-2 overflow-x-auto pb-1">
          {[
            ["planned", "prévu"],
            ["adapted", "adapté"],
            ["done", "fait"],
            ["missing", "manqué"],
            ["offplan", "hors plan"],
          ].map(([status, label]) => (
            <span key={status} className={`shrink-0 rounded-full px-3 py-1.5 text-xs font-bold uppercase tracking-[0.12em] ${STATUS_STYLES[status]}`}>
              {label}
            </span>
          ))}
        </div>

        <section className="surface-panel p-3 md:p-4">
          <div className="mb-2 grid grid-cols-7">
            {["L", "M", "M", "J", "V", "S", "D"].map((dayName, index) => (
              <div key={`${dayName}-${index}`} className="py-2 text-center text-xs font-bold uppercase tracking-[0.18em] text-zinc-500">
                {dayName}
              </div>
            ))}
          </div>
          <div className="grid grid-cols-7 gap-1.5 md:gap-2">
            {data.days.map((day) => {
              const counts = calendarStatusCount(day);
              const isSelected = day.date === selectedDay?.date;
              return (
                <button
                  key={day.date}
                  type="button"
                  onClick={() => setSelectedDate(day.date)}
                  className={`relative min-h-[4.8rem] rounded-[1rem] border p-2 text-left transition md:min-h-[6.2rem] md:p-3 ${
                    isSelected ? "border-black/12 bg-white shadow-sm" : "border-black/5 bg-zinc-50/60 hover:bg-white"
                  } ${day.in_month ? "text-zinc-900" : "text-zinc-300"}`}
                >
                  <span className={`text-sm font-black md:text-base ${day.is_today ? "text-[var(--accent)]" : ""}`}>{day.day_number}</span>
                  <div className="absolute inset-x-2 bottom-2 flex flex-wrap gap-1">
                    {counts.done ? <Dot color="#9d4edd" /> : null}
                    {counts.planned ? <Dot color="#a1a1aa" /> : null}
                    {counts.adapted ? <Dot color="#ff6b35" /> : null}
                    {counts.missing ? <Dot color="#d4183d" /> : null}
                    {counts.offplan ? <Dot color="#ffd166" /> : null}
                  </div>
                </button>
              );
            })}
          </div>
        </section>

        <section className="mt-5 grid gap-4 lg:grid-cols-[0.78fr_1.22fr]">
          <article className="surface-panel p-5">
            <p className="eyebrow">{formatDateLong(selectedDay?.date)}</p>
            <h2 className="mt-2 text-3xl font-black tracking-[-0.05em] text-zinc-950">
              {selectedDay?.items.length ? `${selectedDay.items.length} entrée${selectedDay.items.length > 1 ? "s" : ""}` : "Jour libre"}
            </h2>
            <div className="mt-5 grid grid-cols-2 gap-2">
              <SmallCount label="Fait" value={countStatus(selectedDay?.items, "done")} />
              <SmallCount label="Prévu" value={countStatus(selectedDay?.items, "planned")} />
              <SmallCount label="Manqué" value={countStatus(selectedDay?.items, "missing")} />
              <SmallCount label="Hors plan" value={countKind(selectedDay?.items, "offplan")} />
            </div>
          </article>

          <div className="grid gap-3">
            {selectedDay?.items.length ? (
              selectedDay.items.map((item) => <DayEntry key={`${item.kind}-${item.id}-${item.display_date}`} item={item} />)
            ) : (
              <div className="surface-panel p-5 text-sm font-medium text-zinc-500">Aucune séance ni activité sur ce jour.</div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

function DayEntry({ item }: { item: CalendarItem }) {
  const content = (
    <div data-calendar-entry className="surface-panel flex w-full max-w-full min-w-0 items-center gap-3 overflow-hidden p-3 transition hover:bg-white sm:gap-4 sm:p-4">
      <span className={`shrink-0 rounded-full px-2.5 py-1.5 text-[0.65rem] font-bold uppercase tracking-[0.1em] sm:px-3 sm:text-xs ${STATUS_STYLES[item.status] || STATUS_STYLES.planned}`}>
        {statusLabel(item.status)}
      </span>
      <div className="min-w-0 flex-1">
        <h3 className="truncate text-xl font-black tracking-[-0.04em] text-zinc-950">{item.title}</h3>
        <p className="mt-1 truncate text-sm font-medium text-zinc-500">
          {sportLabel(item.sport_type)} · {item.duration_min ? `${item.duration_min} min` : "Libre"} · {loadBandLabel(item.load_band)}
        </p>
      </div>
      <MoveRight className="h-5 w-5 shrink-0 text-zinc-400" />
    </div>
  );

  if (item.kind === "session" || item.kind === "offplan") {
    return <Link to={`/workout/${item.id}`} className="block w-full min-w-0 max-w-full">{content}</Link>;
  }

  return content;
}

function Dot({ color }: { color: string }) {
  return <span className="h-2 w-2 rounded-full" style={{ backgroundColor: color }} />;
}

function SmallCount({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-[1.1rem] border border-black/6 bg-zinc-50/80 p-3">
      <p className="text-[0.62rem] font-bold uppercase tracking-[0.14em] text-zinc-500">{label}</p>
      <p className="mt-1 text-2xl font-black tracking-[-0.04em] text-zinc-950">{value}</p>
    </div>
  );
}

function countStatus(items: CalendarItem[] | undefined, status: string) {
  return items?.filter((item) => item.status === status).length || 0;
}

function countKind(items: CalendarItem[] | undefined, kind: string) {
  return items?.filter((item) => item.kind === kind).length || 0;
}

function statusLabel(status: string) {
  if (status === "planned") return "prévu";
  if (status === "adapted") return "adapté";
  if (status === "done") return "fait";
  if (status === "missing") return "manqué";
  if (status === "offplan") return "hors plan";
  return status;
}
