---
summary: brancher les vues cœur de la webapp (calendar/today/session/activités) sur le store V0 via un flag FITMAS_APP_SOURCE=v0, pour qu'elle montre le vrai plan du coach V0 (dogfood) — approche A
read_when:
  - travailler sur l'affichage webapp des données V0
  - toucher routes_app.py / routes_read.py en mode V0
  - ajouter un V0 source pour les app-views
---

# Webapp → V0 store (approche A)

> Suite du dogfood : la webapp lit aujourd'hui la DB legacy ; on veut qu'elle montre le **plan
> réel du coach V0**. Décision : approche A (vues cœur sur V0, overview legacy-only stubbé).

## Contexte / finding

La webapp est live et à jour, **mais elle lit la DB legacy** (`FITMAS_DB_PATH`) — un chemin de
données séparé du coach Telegram V0 (`FITMAS_V0_DB_PATH`). Le coach V0 n'écrit jamais dans la DB
legacy. Donc le plan affiché n'est pas celui du coach V0.

**Couplage découvert** : même l'endpoint `calendar` (pas seulement `overview`) tire
`build_coach_state_bundle` → `planning_contract`, `availability_state`, `week_mission`,
`calibration_status`, `recent_adaptations`, `session_policies`, `readiness` — **tous des concepts
legacy sans équivalent V0**. La DB V0 n'a que `v0_scheduled_sessions`, `v0_activities`, `v0_facts`,
`v0_planned_weeks`. Donc « brancher la DB V0 » ≠ swap de chemin : il faut un adaptateur + stub des
agrégats legacy-only.

## Approche A (retenue)

Sous le flag **`FITMAS_APP_SOURCE=v0`**, les endpoints de lecture cœur servent les données V0 :
- **calendar**, **today**, **détail séance**, **activités** ← mappés depuis `v0_*` (ils mappent proprement).
- **overview** : sert les séances/today V0 + les champs legacy-only en **défauts sûrs** (null/empty)
  que le front tolère déjà (`… else None` dans le code actuel).

**Mécanique** : un **V0 source** (module côté legacy, ex. `legacy/app/api/v0_source.py`) lit les tables
`v0_*` (sqlite brut, read-only, via `FITMAS_V0_DB_PATH`) et produit les **objets domaine** que les
builders existants attendent (`ScheduledSession`, `Activity`). On **réutilise** `build_app_calendar` /
`build_app_overview` / `build_performance_overview` inchangés, et on **stubbe** le `CoachStateBundle`
(valeurs neutres). Le V0 source **n'importe pas `runtime_v0`** (il lit les tables sqlite directement) →
`runtime_v0` reste intouché ; et le legacy ne dépend que de lui-même.

**Mapping** (déjà confirmé pour la réconciliation) : `v0_scheduled_sessions` (date, sport, title,
duration_min, intensity_label, priority, status) → `ScheduledSession` ; `v0_activities` (date, sport,
duration_min, distance_km, notes, source) → `Activity`.

## Slices

- **Slice 1 — V0 source (TDD, backend pur).** `v0_source` lit `v0_*` → objets domaine pour
  sessions + activités. Tests : seed `v0_*` → asserts sur les objets produits (dates, types, statut).
- **Slice 2 — câblage flag + endpoints (TestClient).** `FITMAS_APP_SOURCE=v0` route calendar/today/
  session/activities/overview vers le V0 source + bundle stubbé ; tests FastAPI `TestClient` contre
  une DB V0 (l'endpoint renvoie les séances V0, ne crashe pas sur les champs stubbés).
- **Slice 3 — rendu front + deploy. PENDING / hors session.** Le rendu React **n'est pas vérifiable**
  cette session (extension Chrome down) ; le deploy (`FITMAS_APP_SOURCE=v0` dans fly.toml + redeploy)
  est l'étape de Loïc.

## Gate de vérification

- Slice 1 : tests unitaires V0 source verts ; `pytest tests/runtime_v0` toujours 265 (rien touché côté V0).
- Slice 2 : tests TestClient verts (calendar/today en mode V0 renvoient les données V0 ; pas de crash
  sur bundle stubbé) ; le mode legacy (flag absent) inchangé (non-régression des tests legacy existants).
- Slice 3 : **non vérifiable cette session** (browser + prod).

## Limite d'honnêteté (explicite)

Le backend (Slices 1-2) sera **construit et prouvé par tests en local**. Le **« la webapp affiche bien
les données V0 » (rendu React) n'est PAS vérifié** cette session (extension Chrome indisponible), ni le
deploy. Risque résiduel : un champ overview mal stubbé casse le front, invisible sans rendu. À vérifier
end-to-end quand le navigateur est dispo / au deploy.

## Hors scope

- Les agrégats legacy-only (readiness, calibration, week_mission, coach_bundle riche) — stubbés, pas
  reconstruits sur V0 (V0 est délibérément minimal).
- L'écriture depuis la webapp (complete/skip/move) en mode V0 — lecture d'abord ; les mutations V0
  passeront par l'executor V0 (tranche séparée).
- Le deploy (couplé prod, étape Loïc).
