---
summary: plan d implementation front mobile-first FitMAS dogfood
read_when:
  - simplifier le frontend FitMAS
  - modifier aperçu, calendrier ou évolution
---

# Mobile-First Front Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Simplifier les trois écrans front principaux pour un dogfood mobile clair, sans toucher au backend.

**Architecture:** Garder React Router, loaders existants et read models backend. Remplacer seulement la composition UI des pages `OverviewPage`, `CalendarPage` et `EvolutionPage`, avec CSS local minimal si nécessaire.

**Tech Stack:** React 18, React Router 7, Tailwind v4, motion, lucide-react, Recharts, Vitest.

---

### Task 1: Tests de contrat UX

**Files:**
- Modify: `frontend/src/test/routes.test.tsx`

- [ ] **Step 1: Write failing tests**

Add expectations that `Aperçu` shows `À venir`, `Calendrier` shows `Planning`, and `Évolution` shows `Progression`.

- [ ] **Step 2: Run tests**

Run: `npm test -- --run frontend/src/test/routes.test.tsx` from `frontend`.

Expected: fail before UI labels are changed.

### Task 2: Simplifier `Aperçu`

**Files:**
- Modify: `frontend/src/features/overview/OverviewPage.tsx`

- [ ] Replace the large editorial hero with a compact training-first header.
- [ ] Show lead session and upcoming sessions as direct cards.
- [ ] Keep session actions and Strava/manual log secondary.

### Task 3: Simplifier `Calendrier`

**Files:**
- Modify: `frontend/src/features/calendar/CalendarPage.tsx`

- [ ] Keep month navigation.
- [ ] Make status legend and day grid denser.
- [ ] Keep selected-day entries below the grid.

### Task 4: Simplifier `Évolution`

**Files:**
- Modify: `frontend/src/features/evolution/EvolutionPage.tsx`

- [ ] Keep key stats at the top.
- [ ] Keep small Recharts graphs for load and weekly planned vs actual.
- [ ] Keep forecast and distribution compact.

### Task 5: Verify

Run:

```bash
cd frontend && npm test -- --run src/test/routes.test.tsx
cd frontend && npm run build
```

Then start the local dev server and visually inspect the three pages.
