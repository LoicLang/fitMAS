---
summary: design Slice 2.0 (voie b forward-only) du moteur sport V0 — type ContextPack en couches + builder snapshot->pack + réduction actuals forward-only. Finit le context-pack minimal avant le générateur 2.1.
read_when:
  - coder le context-pack Meso (ContextPack, build_context_pack)
  - comprendre la voie b forward-only pour les actuals (semaine N-1 typée -> WeekActuals)
  - décider d'où viennent target / actuals / constraints / signals dans le pack
  - préparer le générateur Slice 2.1 (ce qu'il consomme)
---

# Design — Moteur Sport V0, Slice 2.0 (voie b forward-only)

Contexte : `docs/PLANNING-V0.md` (archi cible), `docs/superpowers/specs/2026-06-05-moteur-sport-plan.md`
(plan + Décisions, dont #4 voie b), `docs/superpowers/specs/2026-06-05-moteur-sport-slice-0-1-spec.md`
(modèle typé + vérificateur déjà codés).

## Objectif

Finir le **context-pack minimal en couches** : un type `ContextPack`
`{target, last_week_actuals, constraints[], signals[]}` + son builder
`build_context_pack(snapshot, prev_week)`. C'est le **seam stable** que le
générateur (Slice 2.1) et le vérificateur consomment. Le moteur de contexte
profond (`PLANNING-V0.md` Q5) se branchera derrière sans toucher au reste.

Déjà fait avant ce slice :
- `constraints[]` — `constraints_from_snapshot` (bridge fact santé -> TypedConstraint), `meso/context.py`.
- `target` — `derive_continuity_target(actuals, phase)`, `meso/model.py`.

Reste (ce slice) : le type `ContextPack`, le slot `last_week_actuals` (forward-only),
le slot `signals[]` (vide, typé), et le builder qui assemble les quatre couches.

## Voie b forward-only — pourquoi, et ce que ça impose

`WeekActuals = {total_load, key_type}` nourrit la dérivation de cible : le générateur
doit savoir d'où **rampe** la semaine suivante. `key_type` est un `SessionType`
**typé** (enum).

Les séances du runtime legacy (`SessionView`) ne sont **pas typées** : `title` /
`intensity_label` sont du texte libre, `priority` est key/secondary/optional, il
n'y a **aucun champ `SessionType`**. Impossible d'en lire proprement un `key_type`.

Deux voies (Décision #4, 5 juin 2026) :
- **voie a** — typer l'historique legacy à la source (colonne `SessionType` + backfill).
  Gros, touche le schéma + le legacy. **Différée** jusqu'au branchement du vrai
  historique (Slice 3 / dogfood).
- **voie b (retenue)** — **forward-only**. On ne type **jamais** le passé. Seules les
  semaines que le **générateur** produit sont typées. `actuals(N)` = la semaine typée
  générée en `N-1`, réduite. La chaîne ne coule que vers l'avant, de typé en typé.

```
semaine N-1 (typée, générée) --réduit--> WeekActuals --> cible N --> semaine N (typée) --> ...
   ^
   |__ première semaine : rien avant elle => cold-start (None)
```

Conséquence d'archi : le builder n'est **pas** `build(snapshot)` seul. `constraints`
et `signals` viennent du snapshot ; `last_week_actuals` **entre par chaînage** (la
semaine typée précédente), pas du snapshot.

## Décision de seam (option A — réduction pure + Optional)

En Slice 2.0 il n'y a **ni générateur ni stockage** de semaines typées. On modélise
donc le seam sans DB :

- une **fonction pure** `actuals_from_week(PlannedWeek) -> WeekActuals` (juste du
  calcul, aucune I/O) ;
- le builder reçoit la semaine typée précédente en **argument** (`prev_week`) ;
- **cold-start** = `prev_week is None` -> `last_week_actuals = None` et `target = None`.
  Le **seed** de la première semaine est géré par le générateur en 2.1, pas ici.

Rejeté : un store typé en DB dès 2.0 (anticipe 2.1, casse la pureté de `meso/`) ;
un seed obligatoire sans `Optional` (cache le cold-start).

## Décision signals (slot vide, typé)

`signals[]` n'a **aucun consommateur** tant que le générateur 2.1 n'existe pas (le
vérificateur lit `target` + `constraints`, jamais `signals`). Construire la dérivation
maintenant = typage spéculatif non exercé par un test (anti-doctrine).

Donc : le champ `signals` **existe et est typé** (`tuple[Signal, ...]`), mais le
builder le laisse **vide** `()`. La dérivation depuis les facts actifs non-santé se
code en 2.1, quand le générateur le consomme — même seam, rien de jeté.

## Modèle (ajouts à `meso/model.py`, pur stdlib)

```python
@dataclass(frozen=True)
class Signal:
    kind: str          # "fatigue" | "soreness" | "preference" — non sur-enumé en V0
    text: str          # le fait, en advisory pour le générateur (jamais un gate)

@dataclass(frozen=True)
class ContextPack:
    target: WeekTarget | None              # None au cold-start
    last_week_actuals: WeekActuals | None  # None au cold-start
    constraints: tuple[TypedConstraint, ...]
    signals: tuple[Signal, ...] = ()       # slot typé, vide en 2.0
```

`Signal` = shape irréductible d'un fact-en-hint (`kind` + `text`), pas une structure
inventée. Volontairement **pas** d'enum figé sur `kind` tant que le générateur n'en a
pas besoin (évite de figer un vocabulaire qu'on jettera).

## Réduction forward-only (ajout à `meso/model.py`, pur)

```python
def actuals_from_week(week: PlannedWeek) -> WeekActuals:
    keys = [s for s in week.sessions if s.is_quality_key]
    if len(keys) != 1:
        raise ValueError(
            f"forward-only actuals need exactly one quality key, got {len(keys)}"
        )
    return WeekActuals(total_load=week.week_load, key_type=keys[0].type)
```

- Une semaine **générée + vérifiée** en phase `build` a **exactement une** séance
  qualité (le vérificateur l'enforce via `key_session_count`) -> précondition tenue
  par construction.
- `0` ou `>1` clé -> `ValueError` (précondition violée, jamais sur une semaine valide).
- **Hors scope 2.0** : recovery/taper (0 clé légitime) — quel `key_type` porter alors
  est une décision du générateur 2.1. La réduction reste stricte ici ; on l'assouplit
  **sur preuve**, pas d'avance.

## Builder (ajout à `meso/context.py`, bridge snapshot->pack)

```python
def build_context_pack(
    snapshot: WorldSnapshot,
    prev_week: PlannedWeek | None = None,
    phase: Phase = "build",
) -> ContextPack:
    actuals = actuals_from_week(prev_week) if prev_week is not None else None
    target = derive_continuity_target(actuals, phase) if actuals is not None else None
    return ContextPack(
        target=target,
        last_week_actuals=actuals,
        constraints=constraints_from_snapshot(snapshot),
        signals=(),  # rempli en Slice 2.1 (générateur consommateur)
    )
```

- Assemblage **pur**, zéro DB : le `WorldSnapshot` est déjà chargé en amont.
- `prev_week=None` -> cold-start propre (`target`/`actuals` à `None`).
- `phase` défaut `build` ; le mode `transition` (déclaré par le LLM) = Slice 2.1.

## Placement / carte d'autorité

```
meso/model.py   (pur, stdlib)        : ContextPack, Signal, actuals_from_week
meso/context.py (bridge snapshot)    : build_context_pack  [constraints_from_snapshot déjà là]
```

`meso/` reste **isolé** (aucun import `fitmas.decision/domain/llm/skills/tools/app`).
Seul `context.py` voit `WorldSnapshot` — déjà le cas aujourd'hui.

## Plan de test (la preuve du slice — couche 1)

`tests/runtime_v0/test_meso_model.py` :
- `actuals_from_week` : semaine build (1 seuil + footings) -> `total_load` correct +
  `key_type == "threshold"`.
- `actuals_from_week` : **0** séance qualité -> `ValueError` ; **2** -> `ValueError`.

`tests/runtime_v0/test_meso_context.py` (réutilise la fixture snapshot des constraints) :
- **cold-start** (`prev_week=None`) -> `target is None`, `last_week_actuals is None`,
  `constraints` peuplées depuis un fact santé actif, `signals == ()`.
- **avec `prev_week`** -> `last_week_actuals` réduite, `target` dérivée (bande build
  `1.00..1.10 × total_load`), `constraints` présentes, `signals == ()`.
- **fact santé résolu/inactif** -> `constraints == ()` dans le pack (re-vérifie la
  dépendance au cycle de vie via le pack).
- `signals` **toujours** `()` en 2.0.

## Critère "Done"

- `pytest tests/runtime_v0` vert (aucune régression).
- Aucune I/O réseau/DB dans `meso/` (réduction + pack purs ; le builder n'utilise
  qu'un snapshot déjà chargé).
- LOC core surveillée : ~35 LOC ajoutées (~3646 -> ~3681, cap 3700). **Tight** —
  vérifier le compte exact à l'implé ; si dépassement, couper (`Signal` minimal aide).
- Doc à jour : marquer Slice 2.0 **fait** dans `BUILD-ORDER.md` + le plan du jour ;
  pointer vers ce design.

## Hors scope (différé, accommodé pas codé)

- Le **générateur** `propose_week` LLM + boucle generate->verify (Slice 2.1).
- Le **seed** cold-start de la première semaine (générateur 2.1).
- La dérivation **signals** depuis les facts non-santé (2.1, quand consommée).
- Le mode **transition** déclaré + anti-gaming contrainte-aware (2.1, cf. PLANNING-V0).
- Le **store** de semaines typées + le branchement de l'historique réel (Slice 3 / dogfood).
- Le **rework profond du contexte** (couches, distillation long-terme) — chantier dédié
  APRÈS le moteur (`PLANNING-V0.md` Q5).

## Règles dures (rappel)

- Le LLM comprend/génère ; le vérificateur + la policy tiennent l'autorité.
- Aucun regex/keyword sur texte user libre. La réduction ne lit que des **champs typés**.
- Aucun write DB hors executor officiel ; aucune reply ne ment sur un write.
- `runtime_v0` reste isolé ; tout Meso reste **pending** (jamais d'auto-commit semaine).
