---
summary: spec Slice 0+1 du moteur sport V0 — modèle typé Meso + vérificateur déterministe (5 propriétés), prouvé en fixtures dont le rejeu "TSS qui chute" de l'app.
read_when:
  - coder le modèle typé Meso (semaine) ou le vérificateur
  - ajouter/modifier une propriété de semaine running saine
  - écrire les tests fixtures du vérificateur
---

# Spec — Moteur Sport V0, Slice 0 + 1

Contexte : `docs/PLANNING-V0.md` (archi cible), `docs/superpowers/specs/2026-06-05-moteur-sport-plan.md` (plan du jour).

## Objectif

Poser le **modèle typé Meso** (Slice 0) et un **vérificateur déterministe** de
semaine running (Slice 1) qui enforce 5 propriétés numériques/typées, **prouvé en
fixtures** — dont le rejeu de la semaine "TSS qui chute" de l'app, qu'il doit
attraper.

Pur domaine : **pas de DB, pas de LLM, pas de réseau**. Entrées typées, sortie
typée. Rapide à tester, isolé.

## Non-Objectifs (explicitement hors slice)

- Pas de **générateur** (Slice 2).
- Pas de **context-pack** ni de distillation snapshot (Slice 2).
- Pas de **wiring runtime** / tool coach-callable (Slice 3).
- Pas de **résolution de fact** (Slice 1.5).
- Pas de mode **transition** complet : seulement un **hook** (param `mode`) + un
  chemin sécurité-only minimal. Le code complet de la transition = plus tard.
- Pas de multi-sport. **Running-only.**

## Décisions Arrêtées (defaults V0)

- **Charge** : `load(session) = duration_min × weight[intensity]`,
  `weight = {easy:1.0, moderate:1.5, hard:2.0}`. `week_load = Σ load(session)`.
- **Cible en continuité** dérivée de la semaine passée réelle (voir §Dérivation).
- **Mode** par défaut = `continuity`. `transition` = hook sécurité-only.

## Modèle De Données (Slice 0)

Enums (running V0) :

```
Sport      = "run"                      # V0 mono-sport
SessionType= "rest" | "easy_run" | "long_run" | "threshold" | "intervals" | "recovery_run"
Intensity  = "easy" | "moderate" | "hard"
Phase      = "build" | "recovery" | "taper"
Restrict   = "intensity" | "impact" | "all"
Severity   = "mild" | "moderate" | "severe"
```

Types (dataclasses frozen) :

```
TypedSession:
    date: date
    sport: Sport                  # "run" en V0
    type: SessionType
    duration_min: int
    intensity: Intensity
    detail: str = ""              # prose libre, JAMAIS lue par le vérif
    # dérivés (propriétés/fonctions, pas stockés) :
    #   load          = duration_min × weight[intensity]   (rest → 0)
    #   is_quality_key = type in {"threshold","intervals"}
    #   is_hard        = is_quality_key or intensity=="hard"   # charge d'intensité
    #   is_high_stress = is_hard or type=="long_run"           # stress global (vol inclus)
    #   is_impact      = type != "rest"     # running : toute séance court = impact

PlannedWeek:
    sessions: tuple[TypedSession, ...]     # ordonnées par date
    # week_load = Σ session.load

WeekActuals:                                # la semaine N-1 réellement faite
    total_load: float                       # charge réellement réalisée
    key_type: SessionType                   # type de la séance clé qualité prescrite N-1

WeekTarget:
    phase: Phase
    key_type: SessionType                   # type clé PRESCRIT (pas choisi par le LLM)
    load_band: tuple[float, float]          # (min, max)
    progression_axis: "volume" | "intensity"   # V0 default "volume"

TypedConstraint:                            # santé typée (issue de l'ingestion runtime)
    severity: Severity
    restricts: tuple[Restrict, ...]
    active: bool                            # déjà filtré expiré/résolu en amont
```

Note : en Slice 0+1 on **construit ces types à la main** dans les fixtures. Le
mapping `WorldSnapshot → ces types` (et `v0_facts → TypedConstraint`) est un adapter
de Slice 2/3, hors scope ici.

## Dérivation De Cible — Continuité (Slice 0)

`derive_continuity_target(actuals: WeekActuals, phase: Phase = "build") -> WeekTarget`

```
key_type        = actuals.key_type                 # on porte le type (continuité)
progression_axis= "volume"
load_band selon phase, base = actuals.total_load :
    build    → (base × 1.00, base × 1.10)          # tient ou progresse, borné
    recovery → (base × 0.50, base × 0.70)
    taper    → (base × 0.40, base × 0.60)
```

Coefficients = defaults V0, hand-tunables, révisables empiriquement.

## Vérificateur (Slice 1)

Signature :

```
verify_week(
    week: PlannedWeek,
    target: WeekTarget,
    constraints: tuple[TypedConstraint, ...] = (),
    mode: "continuity" | "transition" = "continuity",
) -> WeekVerdict
```

Sortie :

```
Violation:
    code: str
    detail: str            # message structuré pour la boucle de régénération
    severity: "low" | "medium" | "high"

WeekVerdict:
    ok: bool               # True ssi aucune violation
    violations: tuple[Violation, ...]
    requires_pending: bool # toujours True en Meso (jamais d'auto-commit semaine)
```

### Les 5 propriétés (mode continuity)

1. **`key_type_drift`** — la séance clé qualité de la semaine doit avoir
   `type == target.key_type`. Attrape `seuil 3×8 → 20×30sec`. Severity `high`.
   - Sous-check `key_session_count` : il doit y avoir **exactement une** séance
     `is_quality_key`. Zéro ou >1 → violation `key_session_count` (severity `medium`).
   - **Scope** : 1 et son sous-check ne s'appliquent qu'en phase `build` (une semaine
     `recovery`/`taper` peut légitimement n'avoir aucune séance qualité).
2. **`load_drop`** (anti-TSS-drop) — `week_load >= target.load_band.min`. En dessous
   → violation. **C'est le cas app.** Severity `high`.
3. **`load_spike`** — `week_load <= target.load_band.max`. Au-dessus → violation.
   Severity `medium`.
4. **`hard_back_to_back`** — pas deux séances `is_high_stress` sur des jours
   **adjacents** (Δ ≤ 1 jour). Severity `medium`.
5. **`health_conflict`** — pour chaque `constraint.active` : si `constraint.restricts`
   intersecte les attributs des séances de la semaine →
   - `restricts` contient `impact` → conflit avec toute séance `is_impact` ;
   - `restricts` contient `intensity` → conflit avec toute séance `is_hard` ;
   - `restricts` contient `all` → conflit avec toute séance non-`rest`.
   - severity de la violation = `high` si `constraint.severity=="severe"`, sinon `medium`.

### Mode transition (hook minimal, Slice 1)

Quand `mode=="transition"` (discontinuité déclarée) :
- on **n'applique pas** `load_drop` (la discontinuité vers le haut est permise) ;
- la borne haute reste enforced mais devient une **borne de sécurité** : `week_load >
  target.load_band.max` → violation `unsafe_jump` (severity `high`) au lieu de
  `load_spike`. La largeur de bande déclarée porte la discontinuité permise ; au-delà
  = saut non sécuritaire. (`verify_week` n'a pas besoin des actuals : la bande, dérivée
  en amont, les encode déjà.)
- on applique toujours `health_conflict` et `hard_back_to_back` ;
- `requires_pending = True` (déjà le cas).

Le reste de la logique transition (déclaration justifiée, périodisation) = Slice 2+.

## Architecture / Fichiers

```
backend/src/fitmas/runtime_v0/meso/__init__.py
backend/src/fitmas/runtime_v0/meso/model.py      # enums, types, load, derive_continuity_target
backend/src/fitmas/runtime_v0/meso/verifier.py   # verify_week, Violation, WeekVerdict
tests/runtime_v0/test_meso_model.py
tests/runtime_v0/test_meso_verifier.py
```

Contraintes :
- `meso/` n'importe **que** depuis la stdlib (pas de snapshot/DB/LLM en Slice 0+1) →
  domaine pur, testable sans I/O.
- `runtime_v0` reste isolé (pas d'import `fitmas.decision/domain/llm/skills/tools/app`).
- Budget LOC : viser ~120 (model) + ~120 (verifier). Surveiller le ratchet (core déjà
  au-delà de la cible saine 2500).

## Plan De Test (la preuve du slice)

Fixtures `test_meso_verifier.py` (chaque semaine construite à la main) :

1. **Semaine build saine** (1 séance seuil + 1 longue + footings, charge dans la
   bande, pas de stress collé) → `ok=True`, `violations=()`.
2. **Dérive de type** : séance clé = `intervals` alors que `target.key_type="threshold"`
   → `key_type_drift`.
3. **TSS qui chute (cas app)** : `week_load < band.min` → `load_drop`. ← preuve phare.
4. **Spike** : `week_load > band.max` → `load_spike`.
5. **Deux stress collés** : seuil samedi + longue dimanche → `hard_back_to_back`.
6. **Compte de séance clé** : zéro séance qualité → `key_session_count` ; deux → idem.
7. **Santé sévère + impact** : `TypedConstraint(severe, restricts=[impact])` actif +
   semaine running → `health_conflict` severity `high`.
8. **Santé résolue/inactive** : même contrainte mais `active=False` → pas de
   `health_conflict` (prouve la dépendance au cycle de vie — motive Slice 1.5).
9. **Mode transition** : une semaine en `load_drop` mais `mode="transition"` → pas de
   `load_drop` ; un saut > plafond sécurité → `unsafe_jump`.

Fixtures `test_meso_model.py` :
- `load(session)` pour chaque intensité + `rest → 0`.
- `week_load` somme correcte.
- dérivés `is_quality_key / is_high_stress / is_impact`.
- `derive_continuity_target` : bandes build/recovery/taper, `key_type` porté.

## Critère "Done" Du Slice

- `pytest tests/runtime_v0/test_meso_*` vert.
- La fixture "TSS qui chute" est **attrapée** (`load_drop`).
- `pytest tests/runtime_v0` global toujours vert (pas de régression).
- Aucune entrée/sortie réseau ou DB dans `meso/`.
- Doc à jour si le comportement diverge de cette spec.

## Suite

Slice 1.5 (résolution de fact) ou Slice 2 (context-pack + générateur) selon le test
couche 2. Décidé après revue de ce slice.
