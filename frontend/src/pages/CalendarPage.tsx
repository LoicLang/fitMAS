import { addMonths, eachDayOfInterval, endOfMonth, endOfWeek, isSameDay, isToday, startOfMonth, startOfWeek, subMonths } from "date-fns";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { motion } from "motion/react";
import { useMemo, useState } from "react";
import { useAppState } from "../state/app-state";
import { formatMonth, sameVisibleMonth } from "../lib/format";
import { getVisibleTimeline } from "../lib/planning";

const DOT_CLASS: Record<string, string> = {
  running: "dot dot-cyan",
  swimming: "dot dot-blue",
  cycling: "dot dot-orange",
  climbing: "dot dot-red",
  strength: "dot dot-slate",
};

export function CalendarPage() {
  const { data, setSelectedSession, setSelectedActivity } = useAppState();
  const [visibleMonth, setVisibleMonth] = useState(startOfMonth(new Date()));
  const visibleTimeline = useMemo(() => getVisibleTimeline(data), [data]);

  const days = useMemo(() => {
    const monthStart = startOfMonth(visibleMonth);
    const monthEnd = endOfMonth(visibleMonth);
    return eachDayOfInterval({
      start: startOfWeek(monthStart, { weekStartsOn: 1 }),
      end: endOfWeek(monthEnd, { weekStartsOn: 1 }),
    });
  }, [visibleMonth]);

  const sessionMap = useMemo(() => {
    const map = new Map<string, typeof visibleTimeline>();
    visibleTimeline.forEach((session) => {
      const key = session.scheduled_date;
      const list = map.get(key) || [];
      map.set(key, [...list, session]);
    });
    return map;
  }, [visibleTimeline]);

  const activityMap = useMemo(() => {
    const map = new Map<string, typeof data.activities>();
    data?.activities.forEach((activity) => {
      if (!activity.started_at) return;
      const key = activity.started_at.slice(0, 10);
      const list = map.get(key) || [];
      map.set(key, [...list, activity]);
    });
    return map;
  }, [data?.activities]);

  if (!data) return null;

  return (
    <section className="calendar-page">
      <div className="section-head calendar-head">
        <div>
          <h2 className="calendar-title">{formatMonth(visibleMonth)}</h2>
        </div>
        <div className="carousel-actions">
          <button className="round-button" type="button" onClick={() => setVisibleMonth(subMonths(visibleMonth, 1))}><ChevronLeft size={18} /></button>
          <button className="round-button" type="button" onClick={() => setVisibleMonth(addMonths(visibleMonth, 1))}><ChevronRight size={18} /></button>
        </div>
      </div>

      <div className="calendar-weekdays">
        {["LUN", "MAR", "MER", "JEU", "VEN", "SAM", "DIM"].map((day) => (
          <span key={day}>{day}</span>
        ))}
      </div>

      <motion.div className="calendar-grid" initial={{ opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }}>
        {days.map((day) => {
          const key = day.toISOString().slice(0, 10);
          const sessions = sessionMap.get(key) || [];
          const activities = activityMap.get(key) || [];
          const active = isToday(day);
          return (
            <button
              key={key}
              type="button"
              className={[
                "calendar-day",
                sameVisibleMonth(day, visibleMonth) ? "" : "muted",
                active ? "active" : "",
                sessions.length || activities.length ? "has-plan" : "",
                key >= data.performanceOverview.week.week_start && key <= data.performanceOverview.week.week_end ? "week-focus" : "",
              ].filter(Boolean).join(" ")}
              onClick={() => {
                if (sessions[0]) setSelectedSession(sessions[0]);
                else if (activities[0]) setSelectedActivity(activities[0]);
              }}
            >
              <span>{day.getDate()}</span>
              <div className="calendar-dots">
                {sessions.slice(0, 2).map((session) => (
                  <i key={session.id} className={DOT_CLASS[session.sport_type] || "dot dot-cyan"} />
                ))}
                {!sessions.length && activities.slice(0, 2).map((activity) => (
                  <i key={activity.id} className={DOT_CLASS[activity.sport_type] || "dot dot-slate"} />
                ))}
              </div>
            </button>
          );
        })}
      </motion.div>

      <div className="calendar-feed">
        {(data.timeline.length ? data.timeline : visibleTimeline)
          .filter((session) => {
            const date = new Date(`${session.scheduled_date}T12:00:00`);
            return isSameDay(startOfMonth(date), startOfMonth(visibleMonth));
          })
          .slice(0, 6)
          .map((session) => (
            <button key={session.id} className="calendar-feed-card" type="button" onClick={() => setSelectedSession(session)}>
              <div>
                <span className="card-label">{session.label}</span>
                <strong>{session.session_title}</strong>
              </div>
              <span>{session.scheduled_date}</span>
            </button>
          ))}
      </div>
    </section>
  );
}
