---
summary: état actuel de chaque phase, plan de priorités et prochaines étapes
read_when:
  - commencer un chantier
  - donner du contexte à un agent de code
  - vérifier l'avancement
  - recadrer les priorités produit
---

# FitMAS — Build Order

## Role canonique

Ce document est la **source de verite** pour :

- ce qui existe vraiment dans le code
- ce qui reste partiel, legacy ou trompeur
- l'ordre de construction recommande a partir de maintenant

Si un autre doc diverge :

- `BUILD-ORDER.md` gagne sur **l'etat reel** et **la suite**
- `PRODUCT.md` decrit la promesse et le scope
- `ARCHITECTURE.md` decrit la structure technique et les contraintes
- les docs domaine decrivent les contrats locaux

## Phrase guide

**Un premier coach que Loïc reconnaît, comprend, et a envie de rouvrir demain.**

## État actuel — 13 avril 2026

### Vérité repo

Le repo est deja plus avance que plusieurs TODO historiques.

Ce qui est vrai dans le code aujourd'hui :

- onboarding Telegram complet avec preview coach
- coach conversationnel Telegram = surface principale de relation
- webapp React/Vite mobile-first = cockpit performance a 3 surfaces :
  - `Aperçu`
  - `Calendrier`
  - `Évolution`
  - détail séance sur `/workout/:sessionId`
- read models backend dédiés aux écrans app :
  - `overview`
  - `calendar`
  - `evolution`
  - `session detail`
- vérité planning runtime app/chat/heartbeat = `ScheduledSession` datées
- `WeeklyPlan` / `DayPlan` existent encore comme template planner et compat, pas comme vérité runtime
- `/api/v0/week` est marqué `runtime_role=template_compat`
- planner déterministe multisport + `PlanningDecision` + `planning_state`
- activités réelles : manuel + Strava + matching + vues app
- couche planning contract déjà visible dans l'app :
  - `PlanningContract`
  - `WeekMission`
  - `AvailabilityState`
  - `SessionPolicy`
  - `change_budget`
- boucle conversationnelle déjà modernisée :
  - prompt layers
  - prompt caching sur la partie stable
  - debounce Telegram
  - routing déterministe des tools
  - 1 tool read-only max par tour outillé
  - confirmations `oui/non` pour mutations à impact fort
  - transcript structuré persisté dans `conversation_turns`
- couche réalité déjà posée :
  - `ExecutionEvidence`
  - `RecentRealityWindow`
  - `WorkoutContent`
  - `strength_engine`
  - distinction `planned / done / missing / offplan` côté backend app
- mémoire V2 déjà active :
  - `UserFact` surtout pour le profil utile
  - `working_memory_entries` pour le court terme
  - `user_patterns` pour les patterns promus
  - cron de maintenance mémoire toutes les 6h
- heartbeat proactif déjà en prod :
  - briefing matin
  - rappel pré-séance
  - review dimanche
  - nouveau plan lundi
- surface ops / debug distincte du tool plane conversationnel :
  - `api_ops.py`
  - `api_debug.py`
- refactor coherence phases 1-5 fermé sur le gate courant :
  - `CoachStateBundle` = lecture partagée
  - `PlanMutationService` = writer unique des mutations visibles
  - `plan_mutation_events` = audit forward-only
  - `adaptation.py` = propositions uniquement
  - heartbeat/background = suggestion-only sauf policy explicite future
  - guards writer : `same_sport_proximity` et `protected_recovery_target`

### Ce qui est déjà fait et ne doit plus revenir comme gros TODO

- migration React/Vite + app mobile-first
- calendrier daté persistant + timeline backend
- détail séance dédié
- prompt 2 zones + caching
- debounce Telegram
- `profile_summary` compact
- permission tiers initiale sur mutations
- runtime tools V1 read-only
- transcript structuré de conversation
- `execution_evidence` / `recent_reality` / `workout_content`
- split heartbeat en cluster `skills/heartbeat`
- mémoire V2 base + maintenance périodique
- `CoachStateBundle`
- `PlanMutationService` + `plan_mutation_events`
- retrait de `WeeklyPlan` / `DayPlan` des lectures runtime app, conversation et heartbeat
- `/api/v0/week` clarifié comme compat template
- adaptation background suggestion-only
- guard `same_sport_proximity` sur moves datés
- guard `protected_recovery_target` sur repos/récupération stable
- `SYSTEM-MAP.md` comme carte d'architecture pour les agents

### Ce qui reste partiel, legacy ou fragile

- `WeeklyPlan` / `DayPlan` restent utiles comme template planner et compat, mais les derniers consommateurs compat doivent rester isolés
- vieux bootstrap frontend inactif (`frontend/src/state/app-state.tsx` + `frontend/src/pages`) encore à supprimer ou isoler
- `repository.py` reste un hotspot trop gros, même si `repo_conversation.py` a commencé l'extraction
- le runtime tools plane reste volontairement étroit :
  - read-only
  - 1 tool call max
  - pas de write tools
- le heartbeat reste principalement cron + gating, pas encore tick-based
- le verrou anti-doublon reste surtout mono-process / best effort
- la couverture tests reste légère au regard de la richesse du domaine
- le savoir sport existe en contenu et heuristiques, pas encore comme **substrate canonique de capacités partagées**
- le `WeeklyRealityDigest` canonique n'existe pas encore
- la similarité de séance est encore simple (`sport_type + session_type`)

## Décision de sequencing

- la prochaine douleur n'est pas “plus d'intelligence planner”
- la prochaine douleur est “meilleure lecture du réel, meilleure adaptation, meilleure mémoire, moins de duplication métier”
- FitMAS gagne si le coach paraît juste, pas si l'algorithme paraît sophistiqué
- `transcript structuré > compaction` reste la bonne priorité
- `dogfood > gros refactor abstrait` tant que la boucle coach n'est pas observée proprement sur une vraie semaine
- pas de multi-agent visible tant que le mono-agent et le substrate déterministe ne sont pas un goulot prouvé

## Politique tools pour la suite

Le prochain chantier tools ne doit **pas** partir d'un catalogue exposé par sport.

Ordre canonique :

### 1. Capacités métier partagées

Construire d'abord des modules déterministes, atomiques, réutilisables par :

- conversation
- planner
- heartbeat
- app read models
- CLI / ops

Capacités candidates :

- `reality`
- `planning`
- `session_drafting`
- `session_analysis`
- `plan_review`

### 2. Adapters par sport derrière ces capacités

Les sports implémentent le substrate, ils ne définissent pas le tool plane.

Exemples :

- `running`
- `cycling`
- `swimming`
- `climbing`
- `strength`

### 3. Runtime tools LLM-facing très peu nombreux

Le LLM ne doit voir que des wrappers sémantiques et bornés.

Exemples cibles à terme :

- `resolve_target_session`
- `get_recent_reality_window`
- `review_current_week`
- `build_session_draft`
- `analyze_completed_activity`

Mais la règle reste :

- expose peu
- implémente beaucoup
- pas de catalogue `run_* / swim_* / bike_*` directement donné au modèle

### 4. Write / commit séparés

Les mutations à effet de bord restent possédées par les orchestrateurs tant que les permission tiers ne sont pas plus riches.

## Plan canonique — maintenant

Le chantier prioritaire qui detaille cette remise en coherence vit dans `docs/COACH-COHERENCE-REFACTOR.md`.
Il traduit le plan OMX courant en doc durable repo et fixe l'ordre :

- une verite planning runtime
- un writer unique
- un bundle de lecture partage
- des mutations expliquees depuis des events reels

Point de verite au 13 avril 2026 :

- la convergence principale de phase 1 est en place
- les phases 1 a 5 du refactor coherence sont fermees sur leurs gates courants
- le prochain sujet n'est pas Phase 6 par défaut
- le prochain sujet est dogfood guide sur le profil reel pour verifier la coherence coach/app/planning apres refactor
- Phase 6 ne doit demarrer que si le dogfood confirme une douleur memoire/tools/digest

### 0. Dogfood guidé et alignement vérité

But :

- vérifier le comportement réel de la boucle coach
- ne plus laisser des docs raconter un état antérieur
- confirmer ou corriger les prochaines priorités avec usage réel

Observer surtout :

- calendrier app : `missing / adapted / done / offplan`
- conversation fatigue/douleur/indisponibilite
- confirmations de mutation forte
- events `plan_mutation_events`
- review du dimanche
- négociations de déplacement
- briefings matinaux réels

Décision si douleur confirmée :

- lancer le `WeeklyRealityDigest` canonique
- ou prioriser le substrate capabilities si la douleur dominante est la duplication métier

### 1. Substrate de capacités métier partagé

But :

- sortir la logique réutilisable du duo `conversation + planner + heartbeat + app`
- préparer des tools atomiques sans donner trop de liberté au modèle

Premiers modules cibles :

- `resolve_target_session`
- `build_session_draft`
- `analyze_completed_activity`
- `review_current_week`
- `propose_adaptation`

Principe :

- décomposition par capacité, pas par sport
- implémentation sport-spécifique derrière interface partagée
- zéro write side effect dans ces modules

### 2. Weekly reality digest canonique + mémoire utile

But :

- avoir une lecture causale unique de la semaine
- arrêter de recomposer facts + transcript + adaptations à plusieurs endroits
- rendre la review du dimanche et le lundi matin plus cohérents

Scope :

- digest explicite à partir de transcript, mémoire utile, activités, claims et adaptations
- meilleur tri `profile / working / patterns`
- dates absolues partout quand un fait est temporel
- garder `profile_summary` petit, stable, injectable partout

Docs de référence :

- `MEMORY-V2.md`
- `CONVERSATION-GROUNDING.md`
- `REALITY-WORKOUT-CONTRACT.md`

### 3. Unifier revue hebdo, briefings et adaptation sur le même substrate

But :

- donner la même lecture du réel au chat, au heartbeat et à l'app
- éviter que chaque surface rederive sa propre vérité

Scope :

- week review
- monday new week intro
- morning brief
- adaptation summaries

### 4. Split progressif du repository et nettoyage des chemins legacy

But :

- sortir les bounded contexts du hotspot
- clarifier quelle couche possède quelle vérité
- supprimer ou isoler les derniers consommateurs compat de `WeeklyPlan`

Cibles :

- `memory`
- `planning`
- `activities`
- `adaptation`
- `read models`

### 5. Heartbeat scoring tick-based + verrou anti-doublon plus robuste

But :

- remplacer la rigidité cron par une lecture plus situationnelle
- réduire les doublons si on sort du mono-process simple

### 6. Ensuite seulement : enrichissement planner et expansion tools

But :

- planner plus riche
- explications plus lisibles dans l'app
- éventuelle exposition de nouveaux runtime tools sémantiques

## Ce qui n'est pas le prochain sujet

- multi-agent visible
- write tools LLM-facing
- catalogue de tools par sport exposé au modèle
- multiplication des tabs app
- planner V3 avant clarification du substrate partagé

## Tracks domaine à reprendre après ce socle

### `PLANNING-ENGINE-V2.md`

Quand le track planner redevient prioritaire :

- enrichir `periodization.py` au-delà du simple `3+1`
- mieux distribuer la charge par sport
- porter l'explication de `PlanningDecision` jusque dans coach + app
- enrichir l'onboarding sportif seulement après ça

### `REALITY-WORKOUT-CONTRACT.md`

Le gros chantier est absorbé.
Le vrai next domain, si on y revient :

- `strength_signals` plus riches
- variations renfo depuis réel récent + fatigue + santé + temps dispo
- sans ouvrir un moteur de progression force complexe

### `APP-UX.md`

Le polish Figma reste un track parallèle utile.
Mais :

- on ne repolit pas sur une vérité encore mouvante
- d'abord le harness
- ensuite le rendu premium

## Pas maintenant

- pas de skills formels tant qu'on n'a pas assez de workflows distincts
- pas de plan mode systématique sur chaque micro-adaptation
- pas de write tools libres côté coach
- pas de V2.5 “LLM adaptatif partout” tant que le contrat mutation n'est pas durci
- pas de subagents / swarm
- pas de "liberté coach" plus large tant que les substrates métier ne sont pas extraits

## Vérification concrète avant de monter à l'étape suivante

### Harness

- [ ] les traces montrent une baisse nette du prompt dynamique injecté
- [ ] la zone statique est cacheable sans changer le comportement produit
- [ ] 3 messages Telegram rapides déclenchent 1 seule décision LLM

### Mémoire

- [ ] un fait du type `demain je ne peux pas` est stocké avec date absolue
- [ ] le coach lit un `profile_summary` compact au lieu d'une pile brute de facts
- [ ] transcript et mémoire durable restent deux choses séparées

### Mutations

- [ ] un simple move ne demande pas une confirmation inutile
- [ ] une réorganisation de semaine ne s'applique pas silencieusement

### Proactivité

- [ ] le heartbeat sait aussi ne rien dire pour une bonne raison
- [ ] les observations silencieuses alimentent ensuite la consolidation ou le scoring
