---
summary: contrat produit, moteur et etat de la planification adaptative FitMAS
read_when:
  - lancer un refactor du planner
  - rendre la planification plus lisible dans l'app
  - ajouter des adaptations suite a un imprevu utilisateur
  - definir ce qui est ferme, adaptable ou projete
  - modifier planner.py ou les prompts planning LLM
  - ajouter readiness, decision engine ou periodization
---

# FitMAS Planning

## But

Faire de FitMAS un coach ultra adaptatif mais stable.

Le systeme ne doit pas recalculer tout le plan a chaque message.
Il doit :

- comprendre la contrainte reelle
- proteger l'intention d'entrainement
- modifier le moins possible
- expliquer clairement ce qui change

## Priorite relative

Ce document reste la reference planner.
Mais le prochain chantier repo-wide n'est plus ici — voir `BUILD-ORDER.md`.

Le planner V2 n'est plus en rattrapage. Il est en phase de raffinement.

---

## Contrat produit

### Principe directeur

Le vrai plan n'est pas le calendrier.

Le vrai plan est compose de :

1. `block_intent` — ce qu'on construit sur 4 a 6 semaines
2. `week_mission` — ce qu'il faut sauver cette semaine
3. `session_policy` — ce qui est protege, compressible ou remplacable
4. `calendar_instantiation` — la meilleure organisation actuelle des seances

Le calendrier est une instanciation datee. Il peut bouger.
L'intention ne doit pas bouger sans raison explicite.

### Horizons de verite

| Horizon | Certitude | Traitement |
|---------|-----------|------------|
| Aujourd'hui | Exact, actionnable | committed |
| Cette semaine | Engage, reconfigurable sous contraintes | committed / tentative |
| J+8 a J+14 | Probable | tentative |
| Bloc 4-6 semaines | Intention strategique | projected |
| Objectif long terme | Cap et jalons | projected |

### Week Mission

Chaque semaine doit exposer :

- objectif de semaine
- 2 a 3 seances cles
- critere de reussite dimanche
- risque principal a eviter
- seuil minimum acceptable si la semaine se degrade

La mission est plus importante que le placement exact des seances.

### Session Policy

Chaque seance datee porte une politique exploitable par le moteur :

- `role` : `key` | `support` | `recovery` | `optional`
- `plan_confidence` : `committed` | `tentative` | `projected`
- `move_window_hours`
- `minimum_effective_dose`
- `allowed_substitutions`
- `drop_cost`

### Availability State

Etat vivant minimal :

- creneaux preferes, creneaux impossibles
- flexibilite par jour, temps disponible
- equipement / modalites
- source et fraicheur (`confirmed` / `inferred` / `sparse`)

### Budget de changement

Un plan trop vivant devient anxiogene.

- `change_budget_week` + `adaptation_stability_penalty`
- penaliser les deplacements multiples, remplacements successifs, changements de mission

Principe : **modifier le moins possible pour sauver le plus important**

### Niveaux d'adaptation

| Niveau | Cas | Droits | Interdit |
|--------|-----|--------|----------|
| Micro | Indispo ponctuelle, fatigue legere, meteo | Deplacer, compresser, substituer | Changer mission semaine |
| Meso | Plusieurs seances touchees, semaine contrainte | Adoucir mission, reviser semaine | Changer block intent sans signal fort |
| Macro | Blessure, maladie, voyage lourd | Recalibrer bloc, reevaluer trajectoire | — |

### Reponse a un imprevu

Avant toute mutation, un message utilisateur devient un event candidate structure :

- `UserIndication(kind="availability_constraint")` → `resolve_planning_window` → moteur de replan

Le LLM ne choisit jamais seul la seance future touchee.

FitMAS repond toujours a 4 questions :

1. Qu'est-ce qui change ?
2. Qu'est-ce qu'on protege ?
3. La mission de semaine reste-t-elle la meme ?
4. Quel est l'impact sur la trajectoire ?

---

## Moteur V2

### Principes

- single orchestrator LLM (pas de multi-agent)
- decision explicite avant generation detaillee
- scheduler deterministe
- validation avant persistance
- readiness et fitness separes
- templates de seances comme fallback et garde-fou
- seuils metier externalises

### Ce qui n'est pas adopte

- pas de gros bloc de dataclasses dans `models.py` (agregats domaine dans modules dedies)
- pas de `onboarding.py` ex nihilo (enrichir l'existant)
- pas de `scheduler.py` generique (partir de `planner.py`)
- pas de remplacement brutal de `UserFact`

### Pipeline planner

1. assemble le profil (`athlete_profile.py`)
2. calcule le fitness snapshot (`fitness_snapshot.py`)
3. calcule readiness (`readiness.py`)
4. produit la planning decision (`planning_decision.py`)
5. construit le squelette hebdo deterministe (`planner.py`)
6. demande au LLM le detail borne des seances via le gateway/prompts LLM
7. valide (`plan_validator.py`)
8. relit la qualite sportive de la semaine generee (`generated_week_coherence.py`)
9. persiste

### Modules

| Module | Role | Etat |
|--------|------|------|
| `planning_config.py` | Seuils et overrides V1 par sport/niveau | Fait |
| `athlete_profile.py` | `AthleteProfileSnapshot` depuis DB | Fait |
| `fitness_snapshot.py` | `FitnessSnapshot` depuis activites + seances | Fait |
| `readiness.py` | `ReadinessState` avec flags auditables | Fait |
| `planning_decision.py` | Decision explicite avant generation | Fait |
| `planning_state.py` | Pipeline V2 complete depuis DB | Fait |
| `session_templates.py` | Librairie running/cycling/swimming/strength/climbing | Fait |
| `plan_validator.py` | Garde-fous charge/structure/profil | Fait |
| `periodization.py` | Mesocycle 3+1, progression automatique | Fait |
| `planning_contract.py` | Horizons, confidence, week mission, availability, session policy | Fait |
| `replan_from_life_change.py` | Replan suite a changement de vie | Fait |

Tables SQL ajoutees : `fitness_snapshots`, `readiness_snapshots`, `planning_decisions`.

### Separation des responsabilites

| Acteur | Role |
|--------|------|
| LLM | Comprend, clarifie, reformule, aide a classer, explique |
| Moteur | Genere scenarios valides, applique garde-fous, score, limite instabilite |
| Persistance | Garde verite datee, trace changements, alimente app + Telegram |

---

## Ce qui reste ouvert

### Quand ce track redevient prioritaire

1. enrichir `periodization.py` au-dela du 3+1
2. mieux distribuer la charge par sport dans `planner.py`
3. faire remonter l'explication de `PlanningDecision` dans heartbeat, chat, app
4. enrichir l'onboarding sportif seulement apres

### Ce qu'on ne fait pas

- multi-agent, event bus, solveur complexe
- modele probabiliste readiness
- refonte complete de la DB facts
- app native

## Regle produit

FitMAS ne doit jamais donner l'impression :

- que le plan bouge au hasard
- que le futur lointain est ferme alors qu'il ne l'est pas
- qu'une belle explication remplace une mauvaise logique

Le luxe produit est : `le systeme comprend ma vie, protege l'essentiel, et me dit franchement ce qu'il vient de changer`
