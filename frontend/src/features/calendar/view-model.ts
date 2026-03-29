import type { CalendarDay } from "../../types";

export function initialSelectedDate(days: CalendarDay[]) {
  return days.find((day) => day.is_today)?.date || days.find((day) => day.items.length)?.date || days[0]?.date || "";
}

export function calendarStatusCount(day: CalendarDay) {
  return {
    planned: day.items.filter((item) => item.status === "planned").length,
    done: day.items.filter((item) => item.status === "done").length,
    adapted: day.items.filter((item) => item.status === "adapted").length,
    missing: day.items.filter((item) => item.status === "missing").length,
    offplan: day.items.filter((item) => item.status === "offplan").length,
  };
}
