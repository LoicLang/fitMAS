import { NavLink, Outlet, ScrollRestoration, useNavigation } from "react-router-dom";
import { motion } from "motion/react";
import { CalendarRange, ChartSpline, Home, Layers3 } from "lucide-react";
import { AppActionsProvider } from "../state/app-actions";

const NAV_ITEMS = [
  { to: "/", label: "Aperçu", icon: Home },
  { to: "/calendar", label: "Calendrier", icon: CalendarRange },
  { to: "/evolution", label: "Évolution", icon: ChartSpline },
];

export function AppLayout() {
  const navigation = useNavigation();

  return (
    <AppActionsProvider>
      <div className="min-h-screen bg-[var(--app-bg)] text-white">
        <div className="pointer-events-none fixed inset-0 overflow-hidden">
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_top,rgba(15,115,139,0.24),transparent_30%),linear-gradient(180deg,#030507_0%,#06090d_38%,#020303_100%)]" />
          <div className="absolute inset-0 opacity-40 [background-image:linear-gradient(to_right,rgba(255,255,255,0.03)_1px,transparent_1px),linear-gradient(to_bottom,rgba(255,255,255,0.03)_1px,transparent_1px)] [background-size:3.5rem_3.5rem] [mask-image:radial-gradient(circle_at_center,black_8%,transparent_70%)]" />
          <div className="absolute left-[18%] top-[8%] h-[32rem] w-[32rem] rounded-full bg-cyan-400/12 blur-[150px]" />
          <div className="absolute bottom-[-8rem] right-[12%] h-[26rem] w-[26rem] rounded-full bg-sky-600/12 blur-[150px]" />
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,transparent_0%,rgba(3,5,8,0.88)_76%)]" />
        </div>

        <header className="sticky top-0 z-40">
          <motion.div
            initial={{ y: -24, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
            className="mx-auto flex w-full max-w-7xl items-center justify-between px-5 py-5 md:px-8"
          >
            <NavLink to="/" className="tracking-[0.24em] text-sm font-extrabold text-white">
              PACE
            </NavLink>

            <nav className="hidden items-center gap-8 md:flex">
              {NAV_ITEMS.map(({ to, label }) => (
                <NavLink
                  key={to}
                  to={to}
                  end={to === "/"}
                  className={({ isActive }) =>
                    `text-sm font-semibold tracking-wide transition ${
                      isActive ? "text-white" : "text-white/40 hover:text-white/70"
                    }`
                  }
                >
                  {label}
                </NavLink>
              ))}
              <a
                href="/#utility"
                className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-4 py-2 text-xs font-semibold uppercase tracking-[0.2em] text-cyan-200 transition hover:bg-white/10"
              >
                <Layers3 className="h-4 w-4" />
                Utilitaires
              </a>
            </nav>
          </motion.div>
          {navigation.state !== "idle" ? <div className="h-px w-full bg-cyan-300/50 shadow-[0_0_18px_rgba(103,232,249,0.5)]" /> : null}
        </header>

        <main className="relative z-10 pb-28 md:pb-16">
          <Outlet />
        </main>

        <nav className="fixed inset-x-0 bottom-0 z-50 border-t border-white/8 bg-black/55 px-4 pb-[max(env(safe-area-inset-bottom),1rem)] pt-3 backdrop-blur-xl md:hidden">
          <div className="mx-auto grid max-w-md grid-cols-3 gap-2 rounded-[1.75rem] border border-white/10 bg-white/5 p-2 shadow-[0_-18px_60px_rgba(0,0,0,0.25)]">
            {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                end={to === "/"}
                className={({ isActive }) =>
                  `flex flex-col items-center gap-1 rounded-[1.1rem] px-2 py-3 text-[0.65rem] font-semibold uppercase tracking-[0.18em] transition ${
                    isActive ? "bg-cyan-400/14 text-cyan-200" : "text-white/45"
                  }`
                }
              >
                <Icon className="h-5 w-5" />
                {label}
              </NavLink>
            ))}
          </div>
        </nav>
        <ScrollRestoration />
      </div>
    </AppActionsProvider>
  );
}
