---
summary: plan d'évolution prioritaire pour fiabiliser la vérité d'exécution, adapter la semaine au réel et rendre les séances app actionnables
read_when:
  - corriger un faux "done" ou une validation fantôme
  - rendre le coach Telegram plus fiable sur hier / aujourd'hui / la semaine passée
  - brancher le planner sur la réalité récente au lieu du plan seul
  - refondre le détail séance app ou le contrat de contenu des séances
  - implémenter le renfo de manière déterministe mais réellement adaptative
---

# Reality Layer + Workout Contract

## Pourquoi ce document existe

Ce document cadre le prochain chantier prioritaire FitMAS.

Le problème n'est pas un simple bug UI ou un simple prompt à retoucher.
Le problème est un contrat de vérité encore trop faible entre :

- le réel exécuté
- le plan daté
- le statut persisté
- le message coach
- le rendu app

Tant que ce contrat n'est pas strict, FitMAS peut :

- raconter des faits faux
- considérer une séance "faite" alors que la preuve est faible
- repartir sur une semaine trop dense après une semaine peu réalisée
- afficher le mauvais contenu au mauvais endroit dans l'app
- laisser fuiter du langage interne système dans un texte user-facing

## Symptômes initiaux observés

### Telegram / vérité d'exécution

- heartbeat qui affirme `running facile hier, nickel` alors que l'utilisateur n'a pas couru
- coach qui parle comme si une séance était validée alors que seule une heuristique de matching a tourné
- adaptation de la semaine suivante insuffisante malgré une semaine très incomplète

### App / détail séance

- `Pourquoi aujourd'hui` affiche parfois le plan exécutable brut de la séance au lieu de la rationale
- détail natation avec contenu utile injecté dans la mauvaise zone
- détail renfo sans protocole exploitable : peu ou pas d'exercices / séries / reps / récup
- `Consigne coach` qui affiche parfois un bout de langage système ou de prompt interne
- bloc `Trace et profil` affiché même quand il n'y a pas de trace utile à montrer

## Diagnostic

Le système mélange encore trop facilement :

1. `ScheduledSession.completion_status`
2. activité réelle persistée
3. claim utilisateur récent
4. heuristique de matching

Le système parle ensuite avec un niveau de certitude supérieur à ses preuves.

Le problème produit n'est donc pas seulement "mieux prompter le coach".
Le vrai chantier est :

`evidence -> decision -> structured workout -> render`

et non :

`plan -> message -> adaptation légère`

## Objectifs produit

### 1. Fiabilité d'abord

- ne jamais dire `fait` sans preuve forte
- ne jamais présenter le plan comme la réalité
- séparer ce qui est `observé`, `déclaré`, `candidate match`, `non prouvé`

### 2. Adaptation branchée sur le réel récent

- si la réalité récente est faible, FitMAS simplifie avant de recharger
- la semaine suivante ne repart pas comme si tout le plan précédent avait été encaissé
- les séances `committed` baissent quand la réalité récente est basse

### 3. Contrat de séance strict

- l'app ne doit plus deviner quel texte va dans quel bloc
- le détail séance doit exposer séparément :
  - l'objectif
  - la rationale
  - le plan exécutable
  - la consigne coach
  - la note nutrition

### 4. Renfo utile

- le renfo ne doit pas être un intitulé vague
- il doit rester déterministe et testable
- il doit s'adapter au contexte réel : symptômes, fatigue, sport protégé, semaine récente, matériel, durée

## Non-objectifs immédiats

- pas de refonte DB globale des statuts dès le premier sprint
- pas de planner V2 complet avant d'avoir fiabilisé la vérité d'exécution
- pas de dépendance à un second passage LLM pour "nettoyer" les textes user-facing
- pas de système musculation hyper sophistiqué type progression charge/reps long terme dès le MVP

## Décisions d'architecture

### 1. Ne pas casser `completion_status` tout de suite

Premier principe :

- garder `planned / done / skipped / adapted` pour la compatibilité existante
- ajouter un read-model parallèle de vérité d'exécution
- brancher chat, heartbeat et app sur ce read-model

Pourquoi :

- moins de blast radius
- livraison incrémentale
- migration plus sûre

### 2. Introduire une couche `ExecutionEvidence`

Nouveau module cible :

- `backend/src/fitmas/execution_evidence.py`

Contrat cible :

```python
@dataclass(frozen=True, slots=True)
class ExecutionEvidence:
    evidence_state: Literal["observed", "claimed", "candidate", "none"]
    plan_relation: Literal["linked", "same_sport", "offplan", "unknown"]
    display_status: Literal[
        "confirmed_done",
        "claimed_done",
        "planned_pending",
        "offplan_done",
        "uncertain",
    ]
    reason: str
    activity_id: int | None
```

Règle :

- `confirmed_done` seulement si preuve forte
- `claimed_done` si l'utilisateur l'affirme mais qu'aucune activité persistée ne le confirme encore
- `uncertain` si le système soupçonne quelque chose mais ne peut pas l'affirmer

### 3. Introduire une vue `RecentRealityWindow`

Nouveau module cible :

- `backend/src/fitmas/recent_reality.py`

Contrat cible :

```python
@dataclass(frozen=True, slots=True)
class RecentRealityWindow:
    planned_sessions_7d: int
    confirmed_sessions_7d: int
    claimed_sessions_7d: int
    key_sessions_salvaged_7d: int
    planned_tss_7d: float
    observed_tss_7d: float
    compliance_confirmed: float
    load_ratio: float
    missed_streak_days: int
```

Cette vue sert à piloter :

- readiness
- planning mode
- message coach
- surfaces app explicatives

### 4. Introduire un contrat de contenu séance structuré

Nouveau module cible :

- `backend/src/fitmas/workout_content.py`

Contrat cible :

```python
@dataclass(frozen=True, slots=True)
class WorkoutContent:
    objective: str
    rationale: str
    execution: tuple[str, ...]
    coach_cue: str
    nutrition_note: str
```

Règle :

- `objective` = ce que la séance construit
- `rationale` = pourquoi elle est là aujourd'hui / cette semaine
- `execution` = protocole exécutable
- `coach_cue` = consigne courte athlète-facing
- `nutrition_note` = note simple et user-facing

L'UI ne recompose pas ces champs librement.

### 5. Le renfo doit être déterministe et adaptatif

Le renfo ne doit pas être toujours la même séance.

Mais il ne doit pas non plus être généré en freestyle opaque.

Le bon modèle MVP :

`signal réel + contexte semaine + sport protégé + matériel + durée -> strength context -> blueprint -> rendu`

#### Modules cibles

- `backend/src/fitmas/strength_engine.py`
- `backend/src/fitmas/strength_exercise_bank.py`

#### Contrats cibles

```python
@dataclass(frozen=True, slots=True)
class StrengthContext:
    goal: str
    symptom_flags: tuple[str, ...]
    fatigue_level: str
    duration_min: int
    equipment: tuple[str, ...]
    next_key_session_sport: str | None
    load_mode: str
```

```python
@dataclass(frozen=True, slots=True)
class StrengthBlueprint:
    key: str
    blocks: tuple[StrengthBlock, ...]
```

#### Blueprints MVP

- `full_body_support`
- `upper_core_protect_legs`
- `lower_stability_protect_shoulders`
- `mobility_restore`
- `minimum_effective_dose`
- `restart_consistency_strength`

#### Règle métier

Le symptôme ne drive pas seul la séance.
La sélection dépend de :

- symptômes / douleur
- fatigue
- semaine réellement réalisée
- séance clé protégée demain / hier
- matériel disponible
- durée disponible

Donc :

`symptôme + contexte semaine + voisinage planning + matériel -> séance renfo`

et non :

`symptôme -> séance spéciale isolée`

## Plan de mise en oeuvre

### Slice 1 — Truth Hardening

Objectif :

- supprimer les validations fantômes
- empêcher le coach de dire `fait` sans preuve forte

Fichiers principaux :

- `backend/src/fitmas/repository.py`
- `backend/src/fitmas/api_activities.py`
- `backend/src/fitmas/strava.py`
- `backend/src/fitmas/heartbeat.py`
- `backend/src/fitmas/conversation_context.py`
- `backend/src/fitmas/execution_context.py`
- nouveau `backend/src/fitmas/execution_evidence.py`

Changements :

- rendre `find_scheduled_session_for_activity()` strict
- supprimer le fallback "première séance non done du jour"
- ne marquer `done` automatiquement que sur match fort
- sinon persister l'activité sans la promouvoir silencieusement en preuve définitive
- utiliser `ExecutionEvidence` dans le heartbeat et le chat

Définition MVP d'un match fort :

- même date locale
- même sport
- lien explicite ou proximité durée / contexte raisonnable

Critères de succès :

- une natation ne peut plus valider une course prévue le même jour
- une activité sport différent reste `offplan` ou `uncertain`
- le heartbeat n'affirme plus `fait` sans preuve forte

Tests concrets à jouer :

- log manuel natation un jour course
- sync Strava vélo un jour course
- message user `je n'ai pas couru hier`
- activité du bon sport mais sans lien explicite

### Slice 2 — Recent Reality Window

Objectif :

- brancher la planification sur le réel confirmé récent

Fichiers principaux :

- nouveau `backend/src/fitmas/recent_reality.py`
- `backend/src/fitmas/readiness.py`
- `backend/src/fitmas/planning_decision.py`
- `backend/src/fitmas/week_context.py`
- `backend/src/fitmas/performance_overview.py`

Changements :

- construire `RecentRealityWindow`
- faire entrer cette vue dans readiness
- ajouter un nouveau planning mode `restart_consistency`
- baisser target TSS et densité engagée si la réalité récente est faible
- exposer cette logique dans les textes app / coach

Règles MVP :

- pas de hausse de charge si complétion confirmée basse
- moins de séances `committed`
- plus de séances `optional`
- expliciter pourquoi la semaine est allégée

Critères de succès :

- après une semaine 2/5 confirmées, FitMAS ne repart pas sur une semaine "forte" par défaut
- le système explique la simplification avec une base factuelle lisible

### Slice 3 — Workout Content Contract

Objectif :

- séparer clairement contenu interne, contenu structuré, rendu user-facing

Fichiers principaux :

- nouveau `backend/src/fitmas/workout_content.py`
- `backend/src/fitmas/session_templates.py`
- `backend/src/fitmas/app_views.py`
- `backend/src/fitmas/llm.py`

Changements :

- convertir `session_goal`, `session_note`, `session_description`, `nutrition_focus` vers `WorkoutContent`
- parser `session_description` en steps d'exécution
- durcir la sanitization des textes user-facing
- rejeter ou fallback sur tout texte qui ressemble à une instruction système

Patterns à filtrer en sortie user-facing :

- nom d'agent interne
- verbes de pilotage système
- formulations méta comme `garde cette séance lisible`
- champs ou termes de schema (`session_note`, `session_title`, etc.)

Critères de succès :

- `Pourquoi aujourd'hui` n'affiche plus le plan brut
- `Consigne coach` n'affiche plus de texte type prompt interne
- une natation détaille sa structure dans `Séance`

### Slice 4 — Strength Engine MVP

Objectif :

- rendre le renfo actionnable et contextuel sans passer par un LLM libre

Fichiers principaux :

- nouveau `backend/src/fitmas/strength_engine.py`
- nouveau `backend/src/fitmas/strength_exercise_bank.py`
- `backend/src/fitmas/session_templates.py`
- `backend/src/fitmas/workout_content.py`

Changements :

- dériver un `StrengthContext`
- choisir un `StrengthBlueprint`
- rendre un `WorkoutContent` complet
- prévoir substitutions sûres selon symptômes / fatigue / matériel

Critères de succès :

- un renfo affiche exercices, séries, reps, récup, consigne
- le rendu varie selon le contexte
- le rendu reste déterministe et testable

Exemples attendus :

- jambes rincées + séance course clé demain -> upper/core/mobilité, peu de jambes
- gêne épaule + natation importante -> pas d'overhead, plus de contrôle scapulaire / tronc
- semaine faible + restart -> `minimum_effective_dose` ou `restart_consistency_strength`

### Slice 5 — Front Remap

Objectif :

- remettre le bon contenu au bon endroit

Fichiers principaux :

- `frontend/src/types.ts`
- `frontend/src/features/workout-detail/WorkoutDetailPage.tsx`
- `frontend/src/features/workout-detail/view-model.ts`
- `frontend/src/features/overview/OverviewPage.tsx`

Changements :

- `Pourquoi aujourd'hui` lit `rationale`, plus `session_description`
- nouvelle section `Séance` avec liste de steps
- `Consigne coach` lit `coach_cue`
- `Trace et profil` uniquement si trace utile
- badges / labels plus honnêtes côté vérité (`confirmé`, `déclaré`, `incertain`) si pertinent

Critères de succès :

- natation : hiérarchie claire
- renfo : protocole visible
- pas de faux bloc carto vide

## Contrat cible du détail séance app

Structure cible :

### Titre

- `Natation technique — 36 min`

### Objectif du jour

- ce que la séance construit réellement

### Pourquoi aujourd'hui

- pourquoi cette séance existe dans la logique de la semaine
- jamais le protocole brut

### Séance

- steps exécutable immédiatement

### Consigne coach

- consigne courte, utile, athlète-facing

### Nutrition

- note simple, pas méta

### Trace et profil

- seulement si une trace ou un profil a du sens

## Contrat de reprise pour un prochain agent

Si un agent reprend ce chantier, il doit :

1. lire `BUILD-ORDER.md`
2. lire `CONVERSATION-GROUNDING.md`
3. lire ce document
4. relire `APP-UX.md` avant de toucher le front
5. commencer par Slice 1, pas par l'UI

Ordre recommandé de livraison :

1. Slice 1 — Truth Hardening
2. Slice 2 — Recent Reality Window
3. Slice 3 — Workout Content Contract
4. Slice 4 — Strength Engine MVP
5. Slice 5 — Front Remap

## Règles de mise en oeuvre

- privilégier des modules purs réutilisables
- éviter de cacher des side effects dans le moteur de décision
- ne pas laisser le front "deviner" le sens d'un champ texte libre
- tester sur des flux réels CLI / app / heartbeat
- documenter tout nouveau contrat dans la doc correspondante

## Scénarios de test minimum avant merge

### Telegram / vérité

- aucune activité hier + séance planifiée hier -> message prudent, pas `fait`
- claim user `j'ai couru hier` sans activité persistée -> message `déclaré`, pas `observé`
- activité vélo hier avec course planifiée -> `offplan`, pas validation course

### Adaptation

- semaine précédente très incomplète -> semaine suivante simplifiée
- semaine bien réalisée -> maintien ou progression légère

### App

- natation : `Pourquoi aujourd'hui` et `Séance` bien séparés
- renfo : protocole exploitable
- aucune fuite de prompt / texte système en surface user-facing
