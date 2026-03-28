import { createBrowserRouter } from "react-router-dom";
import { AppLayout } from "./AppLayout";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <AppLayout />,
    children: [
      {
        index: true,
        lazy: async () => {
          const module = await import("../features/overview/OverviewPage");
          return {
            loader: module.overviewLoader,
            Component: module.OverviewPage,
          };
        },
      },
      {
        path: "calendar",
        lazy: async () => {
          const module = await import("../features/calendar/CalendarPage");
          return {
            loader: module.calendarLoader,
            Component: module.CalendarPage,
          };
        },
      },
      {
        path: "evolution",
        lazy: async () => {
          const module = await import("../features/evolution/EvolutionPage");
          return {
            loader: module.evolutionLoader,
            Component: module.EvolutionPage,
          };
        },
      },
      {
        path: "workout/:sessionId",
        lazy: async () => {
          const module = await import("../features/workout-detail/WorkoutDetailPage");
          return {
            loader: module.workoutDetailLoader,
            Component: module.WorkoutDetailPage,
          };
        },
      },
    ],
  },
]);
