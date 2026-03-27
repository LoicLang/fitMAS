import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AnimatePresence, motion } from "motion/react";
import { AppStateProvider, useAppState } from "../state/app-state";
import { OverviewPage } from "../pages/OverviewPage";
import { CalendarPage } from "../pages/CalendarPage";
import { EvolutionPage } from "../pages/EvolutionPage";
import { ActivitiesPage } from "../pages/ActivitiesPage";
import { ProfilePage } from "../pages/ProfilePage";
import { WorkoutModal } from "../components/WorkoutModal";

const NAV_ITEMS = [
  { to: "/", label: "Aperçu" },
  { to: "/calendar", label: "Calendrier" },
  { to: "/evolution", label: "Évolution" },
  { to: "/activities", label: "Activités" },
  { to: "/profile", label: "Profil" },
];

function AppLayout() {
  const location = useLocation();
  const { data, error, loading } = useAppState();

  if (loading) {
    return <div className="loading-screen">Chargement FitMAS…</div>;
  }

  if (error || !data) {
    return (
      <div className="loading-screen">
        <div className="empty-state-panel">
          <strong>FitMAS n&apos;est pas prêt</strong>
          <span>{error || "Aucune donnée disponible."}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <div className="ambient ambient-grid" />
      <div className="ambient ambient-glow ambient-glow-cyan" />
      <div className="ambient ambient-glow ambient-glow-blue" />
      <div className="ambient ambient-glow ambient-glow-teal" />
      <div className="ambient ambient-vignette" />

      <header className="site-header">
        <div className="brand-block">
          <div className="brand-mark">PACE</div>
        </div>
        <nav className="site-nav">
          {NAV_ITEMS.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.to === "/"} className={({ isActive }) => `site-link${isActive ? " active" : ""}`}>
              {item.label}
            </NavLink>
          ))}
        </nav>
      </header>

      <AnimatePresence mode="wait">
        <motion.main
          key={location.pathname}
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -14 }}
          transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
          className="page-shell"
        >
          <Routes>
            <Route path="/" element={<OverviewPage />} />
            <Route path="/calendar" element={<CalendarPage />} />
            <Route path="/evolution" element={<EvolutionPage />} />
            <Route path="/activities" element={<ActivitiesPage />} />
            <Route path="/profile" element={<ProfilePage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </motion.main>
      </AnimatePresence>

      <WorkoutModal />
      <nav className="mobile-nav">
        {NAV_ITEMS.map((item) => (
          <NavLink key={item.to} to={item.to} end={item.to === "/"} className={({ isActive }) => `mobile-link${isActive ? " active" : ""}`}>
            {item.label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}

export function App() {
  return (
    <AppStateProvider>
      <AppLayout />
    </AppStateProvider>
  );
}
