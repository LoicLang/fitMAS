import useEmblaCarousel from "embla-carousel-react";
import { motion } from "motion/react";
import { ArrowUpRight, ChevronLeft, ChevronRight } from "lucide-react";
import type { CSSProperties } from "react";
import { useMemo } from "react";
import { useAppState } from "../state/app-state";
import { loadBandLabel, SPORT_EMOJI, sessionTypeLabel, sportLabel } from "../lib/format";
import { getVisibleTimeline, getPrimarySession } from "../lib/planning";
import { getCardBackdrop, getHeroBackdrop } from "../lib/visuals";

export function OverviewPage() {
  const { data, setSelectedSession, actOnSession } = useAppState();
  const [emblaRef, emblaApi] = useEmblaCarousel({ loop: false, dragFree: true, align: "start" });

  const today = data?.today || null;
  const weekCards = useMemo(() => {
    return getVisibleTimeline(data).slice(0, 7).filter((session) => session.sport_type !== "rest");
  }, [data]);
  const leadSession = getPrimarySession(data);
  const heroStyle = {
    "--hero-image": `url("${getHeroBackdrop(leadSession?.sport_type)}")`,
  } as CSSProperties;

  if (!data) return null;

  return (
    <>
      <section className="hero-stage" style={heroStyle}>
        <div className="hero-image-mask" />
        <motion.div
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1] }}
          className="hero-content"
        >
          <div className="status-pill">Prochaine séance</div>
          <div className="hero-display">
            <h1>{leadSession ? leadSession.session_title.toUpperCase().replaceAll(" ", " ") : "PROGRAMME"}</h1>
            <span>{leadSession ? `_${sessionTypeLabel(leadSession.session_type).toUpperCase()}` : "_FITMAS"}</span>
          </div>
          <p className="hero-copy">
            {leadSession?.session_goal || "Le bloc est prêt. Génère ou synchronise les séances datées pour activer le cockpit complet."}
          </p>

          <div className="hero-actions">
            {leadSession ? (
              <>
                <button className="primary-cta hero-button" type="button" onClick={() => setSelectedSession(leadSession)}>
                  Détails de la séance <ArrowUpRight size={16} />
                </button>
                {today ? (
                  <div className="hero-inline-actions">
                    <button className="ghost-cta" type="button" onClick={() => void actOnSession("done", today.scheduled_session_id)}>Fait</button>
                    <button className="ghost-cta" type="button" onClick={() => void actOnSession("skip", today.scheduled_session_id)}>Fatigué</button>
                    <button className="ghost-cta" type="button" onClick={() => void actOnSession("move", today.scheduled_session_id)}>Décaler</button>
                  </div>
                ) : (
                  <div className="hero-inline-actions">
                    <span className="meta-chip">{sportLabel(leadSession.sport_type)}</span>
                    <span className="meta-chip">{leadSession.duration_min ? `${leadSession.duration_min} min` : "Libre"}</span>
                    <span className="meta-chip">{loadBandLabel(leadSession.load_band)}</span>
                  </div>
                )}
              </>
            ) : (
              <div className="hero-inline-actions">
                <span className="meta-chip">{data.week.week_label}</span>
                <span className="meta-chip">{data.week.days.length} séances prévues</span>
                <span className="meta-chip">Cockpit prêt</span>
              </div>
            )}
          </div>

          <div className="hero-metrics">
            <div className="hero-metric-card">
              <span>Bloc actif</span>
              <strong>{data.week.week_label}</strong>
            </div>
            <div className="hero-metric-card">
              <span>Volume prévu</span>
              <strong>{Math.round(data.week.days.reduce((total, day) => total + (day.duration_min || 0), 0) / 60)} h</strong>
            </div>
            <div className="hero-metric-card">
              <span>Charge cible</span>
              <strong>{Math.round(data.performanceOverview.tss.target || 0)}</strong>
            </div>
          </div>
        </motion.div>
      </section>

      <section className="rail-section">
        <div className="section-head">
          <div>
            <h2>Programme Semaine</h2>
            <p>{data.week.week_label} · {data.week.summary}</p>
          </div>
          <div className="carousel-actions">
            <button className="round-button" type="button" onClick={() => emblaApi?.scrollPrev()}><ChevronLeft size={18} /></button>
            <button className="round-button" type="button" onClick={() => emblaApi?.scrollNext()}><ChevronRight size={18} /></button>
          </div>
        </div>

        <div className="carousel-shell" ref={emblaRef}>
          <div className="carousel-track">
            {weekCards.map((session, index) => (
              <motion.article
                key={session.id}
                className="workout-card"
                initial={{ opacity: 0, y: 24 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, margin: "-20%" }}
                transition={{ duration: 0.5, delay: index * 0.06 }}
                onClick={() => setSelectedSession(session)}
              >
                <div
                  className="workout-card-media"
                  style={{ "--card-image": `url("${getCardBackdrop(session.sport_type)}")` } as CSSProperties}
                >
                  <div className="workout-card-gradient" />
                  <span className="card-kicker">{session.label}</span>
                  <button className="card-icon-button" type="button">
                    <ArrowUpRight size={16} />
                  </button>
                </div>

                <div className="workout-card-body">
                  <h3>{session.session_title.toUpperCase()}</h3>
                  <p>{session.session_goal}</p>
                  <div className="workout-chip-row">
                    <span className="meta-chip">{session.duration_min ? `${session.duration_min} min` : "Libre"}</span>
                    <span className="meta-chip">{sportLabel(session.sport_type)}</span>
                    <span className="meta-chip">{loadBandLabel(session.load_band)}</span>
                  </div>
                </div>
              </motion.article>
            ))}
          </div>
        </div>
      </section>

      <section className="dashboard-row">
        <div className="glass-card stats-panel">
          <p className="card-label">Aujourd&apos;hui</p>
          <div className="stats-grid">
            <div className="stat-box">
              <span>Sport</span>
              <strong>{today ? `${SPORT_EMOJI[today.sport_type] || ""} ${sportLabel(today.sport_type)}` : "Repos"}</strong>
            </div>
            <div className="stat-box">
              <span>Durée</span>
              <strong>{today?.duration_min ? `${today.duration_min} min` : "—"}</strong>
            </div>
            <div className="stat-box">
              <span>Charge</span>
              <strong>{loadBandLabel(today?.load_band)}</strong>
            </div>
            <div className="stat-box">
              <span>Bloc</span>
              <strong>{data.week.week_label}</strong>
            </div>
          </div>
        </div>

        <div className="glass-card stats-panel">
          <p className="card-label">Vision de charge</p>
          <div className="stats-grid">
            <div className="stat-box">
              <span>TSS cible</span>
              <strong>{data.performanceOverview.tss.target}</strong>
            </div>
            <div className="stat-box">
              <span>TSS réel</span>
              <strong>{data.performanceOverview.tss.actual}</strong>
            </div>
            <div className="stat-box">
              <span>Ramp rate</span>
              <strong>{data.performanceOverview.load.ramp_rate}</strong>
            </div>
            <div className="stat-box">
              <span>Freshness</span>
              <strong>{data.performanceOverview.load.freshness}</strong>
            </div>
          </div>
        </div>
      </section>
    </>
  );
}
