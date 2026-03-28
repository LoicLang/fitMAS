import { NavLink, Outlet, ScrollRestoration, useLocation, useNavigation } from "react-router-dom";
import { CalendarRange, ChartSpline, Home } from "lucide-react";
import { AppActionsProvider } from "../state/app-actions";
import { AmbientBackground } from "../shared/ui/AmbientBackground";

const NAV_ITEMS = [
  { to: "/", label: "Aperçu", icon: Home },
  { to: "/calendar", label: "Calendrier", icon: CalendarRange },
  { to: "/evolution", label: "Évolution", icon: ChartSpline },
];

export function AppLayout() {
  const navigation = useNavigation();
  const location = useLocation();
  const isWorkoutDetail = location.pathname.startsWith("/workout/");

  return (
    <AppActionsProvider>
      <div className="min-h-screen bg-[var(--app-bg)] text-[var(--text-main)]">
        <AmbientBackground />

        <header className="fixed inset-x-0 top-0 z-40">
          <div className="mx-auto flex h-16 w-full max-w-7xl items-center justify-between px-5 md:px-8">
            <NavLink to="/" className="text-sm font-extrabold tracking-[0.24em] text-zinc-950">
              FITMAS
              <span className="text-[var(--accent)]">.</span>
            </NavLink>

            <nav className="hidden items-center gap-8 md:flex">
              {NAV_ITEMS.map(({ to, label }) => (
                <NavLink
                  key={to}
                  to={to}
                  end={to === "/"}
                  className={({ isActive }) =>
                    `text-sm font-semibold tracking-wide transition ${
                      isActive ? "text-zinc-950" : "text-zinc-500 hover:text-zinc-800"
                    }`
                  }
                >
                  {label}
                </NavLink>
              ))}
            </nav>
          </div>
          {navigation.state !== "idle" ? <div className="h-px w-full bg-cyan-300/50 shadow-[0_0_18px_rgba(103,232,249,0.5)]" /> : null}
        </header>

        <main className="relative z-10 pb-36 pt-16 md:pb-16">
          <Outlet />
        </main>

        {isWorkoutDetail ? null : (
          <nav className="fixed inset-x-0 bottom-0 z-50 border-t border-black/5 bg-white/80 px-5 pb-[max(env(safe-area-inset-bottom),0.5rem)] pt-2 shadow-[0_-10px_40px_rgba(0,0,0,0.05)] backdrop-blur-xl md:hidden">
            <div className="mx-auto grid max-w-sm grid-cols-3 gap-1">
              {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
                <NavLink
                  key={to}
                  to={to}
                  end={to === "/"}
                  className={({ isActive }) =>
                    `flex flex-col items-center justify-center gap-1 rounded-2xl px-2 py-2.5 text-[0.6rem] font-bold uppercase tracking-[0.12em] transition ${
                      isActive ? "text-[var(--accent)]" : "text-zinc-400"
                    }`
                  }
                >
                  <Icon className="h-5 w-5" />
                  {label}
                </NavLink>
              ))}
            </div>
          </nav>
        )}
        <ScrollRestoration />
      </div>
    </AppActionsProvider>
  );
}
