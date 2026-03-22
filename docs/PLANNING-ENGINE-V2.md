---
summary: plan d'implementation adapte du moteur de planification V2, aligne sur le code et l'architecture actuels
read_when:
  - preparer le chantier planner v2
  - modifier planner.py ou llm.py
  - ajouter readiness, decision engine ou periodization
  - refondre l'onboarding sportif
---

# FitMAS Planning Engine V2

## But

Faire evoluer FitMAS d'un planner hebdo deterministe simple vers un moteur de planification plus robuste, sans casser les principes actuels du repo :

- un seul orchestrateur LLM
- structure du plan determinee hors LLM
- persistance SQL comme verite
- domaine testable et lisible
- pas de multi-agent
- pas d'event bus

## Ce qu'on garde du plan propose

- single orchestrator
- decision explicite avant generation detaillee
- scheduler deterministe
- validation avant persistance
- readiness et fitness separes
- onboarding plus sportif et plus structure
- templates de seances comme fallback et garde-fou
- seuils metier externalises

## Ce qu'on n'adopte pas tel quel

### 1. Pas de gros bloc de dataclasses dans `models.py`

Dans FitMAS aujourd'hui :
- `schema.py` = SQLAlchemy ORM
- `models.py` = Pydantic / vues API
- les agregats domaine doivent vivre dans des modules dedies

Donc :
- on ne remplace pas `models.py` par une foret de dataclasses
- on ajoute des objets domaine purs dans de nouveaux modules quand c'est utile

### 2. Pas de `onboarding.py` ex nihilo

Le repo a deja :
- `telegram_onboarding.py`
- `api_onboarding.py`
- `api_support.py`

Donc le bon move est :
- enrichir l'onboarding existant
- factoriser le coeur structurant dans un module partage
- ne pas creer un second systeme parallele

### 3. Pas de `scheduler.py` generique

Le scheduler d'entrainement V1 existe deja dans `planner.py`.
Le V2 doit partir de cet existant et l'extraire progressivement :

- `planner.py` garde l'entree principale
- `periodization.py` decide la semaine
- `planning_decision.py` produit la decision
- `session_templates.py` fournit la bibliotheque
- `plan_validator.py` controle le resultat

### 4. Pas de "facts V2" qui cassent `UserFact`

`UserFact` existe deja et tourne.
On ne le remplace pas brutalement.

V2 :
- garder `UserFact` compatible
- ajouter seulement les colonnes strictement necessaires
- sinon calculer les usages via une couche d'assemblage

## Cartographie du repo actuel

Le moteur V2 doit s'appuyer sur ces briques deja en place :

- `planner.py` : squelette hebdo actuel
- `llm.py` : orchestrateur unique
- `training_load.py` : TSS + CTL/ATL/TSB
- `signals.py` : signaux derives
- `mutations.py` + `plan_actions.py` : adaptations deterministes
- `schema.py` + `repository.py` : persistance
- `telegram_onboarding.py` + `api_onboarding.py` : onboarding existant
- `api_read.py` + `api_stats.py` : vues app
- `heartbeat.py` : coaching proactif

## Cible V2 adaptee a FitMAS

### A. Etat athlete structure

On ne cree pas une grosse table `AthleteProfile` separee d'emblee.
On garde `User`, `UserSport`, `UserConstraint`, `UserPreference` comme source principale.

On ajoute au besoin :
- quelques champs utilisateur manquants si vraiment necessaires
- un module pur `athlete_profile.py` qui assemble un profil exploitable par le planner

Sortie cible :
- `AthleteProfileSnapshot` domaine pur, pas verite SQL autonome dans un premier temps

### B. Snapshots persistants

Ce qui merite vraiment une table :
- `FitnessSnapshot`
- `ReadinessSnapshot`
- `PlanningDecision`

Pourquoi :
- auditabilite
- debuggage
- comparaison avant/apres
- support des explications coach

### C. Plan actif

Le plan V2 ne remplace pas `ScheduledSession`.
Au contraire :

- `WeeklyPlan` reste l'enveloppe de generation
- `ScheduledSession` reste la verite execution/calendrier
- le planner V2 alimente les deux

## Modules a creer

Ordre recommande :

1. `planning_config.py`
2. `athlete_profile.py`
3. `fitness_snapshot.py`
4. `readiness.py`
5. `planning_decision.py`
6. `session_templates.py`
7. `periodization.py`
8. `plan_validator.py`
9. evolution de `planner.py`
10. evolution de `llm.py`
11. evolution onboarding
12. integration `heartbeat.py`

## Progression actuelle

### Fait

- `planning_config.py` pose les seuils et overrides V1 centralises par sport et par niveau
- `athlete_profile.py` assemble un `AthleteProfileSnapshot` deterministe depuis `User`, `UserSport`, `UserConstraint`, `UserPreference` et `UserFact`
- tests cibles ajoutes pour ces deux briques domaine

### Prochaines briques

- `fitness_snapshot.py`
- tables de snapshots / decisions en SQL
- `readiness.py`
- `planning_decision.py`

## Details par module

### `planning_config.py`

But :
- centraliser les seuils V2

Contient :
- defaults globaux
- overrides par sport
- overrides par niveau
- garde-fous V1

Format recommande :
- Python simple au debut
- pas de YAML/JSON externe tant qu'on n'a pas besoin de reload dynamique

### `athlete_profile.py`

But :
- assembler un profil athlete coherant depuis la DB actuelle

Fonctions attendues :
- `build_athlete_profile(db, user_id) -> AthleteProfileSnapshot`
- `summarize_athlete_identity(...)`

Responsabilites :
- sport principal
- niveau par sport
- objectifs
- disponibilites
- contraintes
- ton coach
- materiel

### `fitness_snapshot.py`

But :
- produire un snapshot exploitable par le decision engine

Entree :
- activites recentes
- eventuellement plan recent

Sortie :
- CTL / ATL / TSB
- adherence recente
- charge hebdo cible / reelle
- breakdown par sport

Important :
- reutiliser `training_load.py`
- ne pas dupliquer les calculs de charge

### `readiness.py`

But :
- transformer les signaux existants en etat lisible et testable

Dimensions V1 :
- physical
- mental
- logistical
- injury_risk
- risk_flags

Important :
- logique deterministe
- pas de score opaque

### `planning_decision.py`

But :
- produire une `PlanningDecision` explicite avant generation

Modes V1 :
- `increase_load`
- `maintain_load`
- `reduce_load`
- `deload`
- `tactical_adjustment`
- `injury_protection`

Ordre de priorite :
1. securite / blessure
2. deload programme
3. surcharge
4. sous-completion
5. progression normale
6. maintien

### `session_templates.py`

But :
- bibliotheque minimale de seances
- fallback robuste
- reference pour le LLM

Volume V1 recommande :
- running : 6
- cycling : 4
- swimming : 5
- strength : 3
- climbing : 2

### `periodization.py`

But :
- regler le type de semaine
- definir cible de charge
- preparer la progression

Important :
- demarrer simple
- pas de solveur
- deload explicite

### `plan_validator.py`

But :
- rejeter un plan invalide avant persistance

Familles de checks :
- charge
- structure
- profil
- risque

## Evolution de `planner.py`

`planner.py` doit devenir l'entree unique :

1. assemble le profil
2. calcule le fitness snapshot
3. calcule readiness
4. produit la planning decision
5. construit le squelette hebdo deterministe
6. demande au LLM le detail borne des seances
7. valide
8. persiste

Interface publique a garder si possible :
- `build_week_plan(...)`

## Evolution de `llm.py`

`llm.py` reste l'orchestrateur unique.

Ce qui change :
- nouveau prompt de detailing de seance
- contexte plus propre selon pipeline
- pas d'injection brute du monde entier

Pipelines distincts a garder :
- onboarding extraction
- conversation coach
- planning detail

## Evolution onboarding

Objectif :
- garder le flow Telegram existant
- enrichir les questions sportives
- persister plus proprement ce qui manque au planner V2

Approche :
- etendre `telegram_onboarding.py`
- factoriser extraction / completion dans un module partage
- ne pas tout recrire

## Etat SQL cible

Tables a ajouter en premier :
- `fitness_snapshots`
- `readiness_snapshots`
- `planning_decisions`

Tables a ajouter plus tard si besoin reel :
- `goals`
- `training_cycles`
- `mesocycles`

Decision CTO :
- ne pas tout creer d'un coup
- commencer par ce qui sert directement le planner V2

## Plan executable

### Phase 1 — Fondations domaine

Livrables :
- `planning_config.py`
- `athlete_profile.py`
- `fitness_snapshot.py`
- tables `fitness_snapshots`, `readiness_snapshots`, `planning_decisions`

Definition of done :
- snapshots testables
- aucune regression API
- compile + tests unitaires passes

### Phase 2 — Readiness + Decision Engine

Livrables :
- `readiness.py`
- `planning_decision.py`
- persistance de la decision

Definition of done :
- une semaine peut produire une decision explicite sans LLM
- les raisons sont lisibles

### Phase 3 — Templates + Validator

Livrables :
- `session_templates.py`
- `plan_validator.py`

Definition of done :
- fallback full deterministic possible
- guardrails V1 centralises

### Phase 4 — Planner V2

Livrables :
- refactor `planner.py`
- integration `periodization.py`
- squelette hebdo base sur `PlanningDecision`

Definition of done :
- `build_week_plan()` garde une interface compatible
- la structure de semaine ne depend pas du LLM

### Phase 5 — LLM session detailing

Livrables :
- prompt de detailing borne dans `llm.py`
- 2 retries max
- fallback template si validation KO

Definition of done :
- un plan detaille valide peut etre genere
- les blocs de seance sont coherents

### Phase 6 — Onboarding V2

Livrables :
- enrichment de `telegram_onboarding.py`
- completion explicite d'onboarding
- nouvelles donnees utiles au planner

Definition of done :
- un user incomplet ne recoit pas un "vrai" plan V2
- reprise d'onboarding possible

### Phase 7 — Conversation + Heartbeat

Livrables :
- `heartbeat.py` et conversation utilisent `PlanningDecision` et `Readiness`
- explication des changements de plan

Definition of done :
- le coach explique les grosses adaptations avec le bon contexte

## Ce qu'on ne fait pas dans V2

- multi-agent
- event bus
- solveur de planning complexe
- modele probabiliste readiness
- refonte complete de la DB facts
- nouvelle app native

## Fichiers a toucher en premier

- `backend/src/fitmas/schema.py`
- `backend/src/fitmas/repository.py`
- `backend/src/fitmas/planner.py`
- `backend/src/fitmas/llm.py`
- `backend/src/fitmas/telegram_onboarding.py`
- `backend/src/fitmas/api_onboarding.py`
- `backend/src/fitmas/heartbeat.py`

## Verification minimale par phase

- `.venv/bin/python -m compileall backend/src/fitmas`
- tests unitaires des modules purs
- smoke onboarding si phase onboarding
- smoke generation plan si phase planner
- smoke message coach si phase heartbeat

## Decision de sequencing

Le prochain chantier moteur ne doit pas commencer par le LLM.

Ordre impose :
1. etat structure + snapshots
2. readiness
3. decision
4. templates + validator
5. planner
6. detailing LLM
7. onboarding enrichi
8. conversation / heartbeat

Autrement dit :
- d'abord la verite metier
- ensuite la generation
- ensuite seulement le raffinement conversationnel
