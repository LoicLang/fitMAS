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

## État actuel — 20 avril 2026

### Diagnostic dogfood (19-20 avril)

Une session de dogfood réelle a confirmé trois pathologies convergentes du coach (briefing dimanche + conversation Telegram autour de "piscine fermée 2 semaines") :

1. **Court-circuits déterministes** : sur les intents `availability_constraint` et apparentés, le LLM principal `decide()` n'est jamais appelé. Une réponse template f-string est envoyée à la place (`_week_scope_reply` dans `api_messages.py:317-326`). Conséquences : token interne `this_week` recopié brut, ton administratif, pas de creusage du contexte conversationnel précédent.
2. **Pré-digestion agrégée en heartbeat** : `weekly_review()` (heartbeat.py:281) passe au LLM des compteurs (`actual_activity_count`, `actual_duration_min`) au lieu du détail par sport/jour. Conséquence : "zéro natation cette semaine" alors qu'une nage offplan existe en DB (id=36, vendredi 17 avril). Le `coach_reading_digest` qui exposerait `real_entries` détaillés existe mais n'est branché que dans le briefing matin.
3. **Hallucination de plan futur** : aucun tool n'expose `ScheduledSession` futures au coach LLM. Sur "piscine fermée 2 semaines" le coach affirme "natation prévue lundi 20 et mercredi 22" alors que la semaine 20-26 avril est **vide** dans le calendrier réel.

### Diagnostic dogfood — addendum 20 avril matin (turns 5-7)

Suite de la même conversation Telegram, le matin du 20 avril, deux nouvelles pathologies confirmées :

4. **Court-circuit `nlp.py:60 generate_reply()` sur réponses courtes** : User répond "Running" à la question fermée du coach. `extract_reply()` ne trouve aucun token connu (pas de jour, pas de feeling), passe `needs_clarification=True`, et `generate_reply` retourne en dur "Je peux ajuster, mais j'ai besoin d'un point de plus. Tu sais déjà quels jours sont les plus compliqués ?". Le LLM principal n'est **jamais** appelé. Le coach ignore totalement la question fermée qu'il avait posée au tour précédent et boucle. Cablé dans `conversation_pipeline.py:843-844`.
5. **Phantom action — anti-pattern "dire sans faire"** : User répond "Mercredi". Le coach affirme "OK. Je libere ce creneau et je garde la suite propre. Le cap de la semaine ne bouge pas." (template `replan_from_life_change.py:500 _build_user_message()`). **Aucune mutation réelle n'est appliquée** : les deux nages lundi 20 / mercredi 22 sont toujours planifiées en DB. Le coach ment au user. Aucune garde "dire = faire" n'existe dans le pipeline.

**Diagnostic racine** : le système interprète et résume la donnée AVANT de la passer au LLM, au lieu de donner les **données brutes + tools** au LLM pour qu'il les explore lui-même. Le LLM est utilisé comme générateur de phrases sur un contexte appauvri, pas comme orchestrateur autonome. **Pire** : sur certains chemins, le LLM affirme une action sans qu'aucune mutation ne soit auditée — l'app et le coach divergent silencieusement.

**Conséquence sur le sequencing** : la décision "dogfood guidé d'abord" est consommée. Le dogfood a livré son verdict. Le prochain chantier canonique devient `COACH-AUTONOMY-REFACTOR.md` — il remplace "dogfood guidé" comme étape 0. Le doc a été enrichi des turns 5-7 dans le golden case, et un nouveau **Chantier 1bis "Anti-mensonge dire = faire"** a été ajouté entre la suppression des court-circuits et l'ajout des tools de lecture.

### Chantier 0 du refactor — fait

Le Chantier 0 (pré-requis) est livré le 20 avril 2026 :
- Golden case gelé comme smoke scenario : `./scripts/smoke-real-conversations --scenario golden_case_autonomy`
- Inventaire system prompts + audit court-circuits → `docs/COACH-AUTONOMY-AUDIT.md`

### Chantier 1 du refactor — fait

Suppression des 5 court-circuits non-transactionnels, livré le 20 avril 2026 (4 commits atomiques `chantier 1: ...`) :
- Routing guards `_should_route_*_context_to_llm` généralisées : `decide()` est appelé sur 100 % des tours conversationnels (sauf calibration_only_reply)
- N5 execution_contestation, N2 low_signal, N3 week_scope, N4 no_candidate routés en contexte de prompt (helpers `_*_context_for_prompt`)
- N1 nlp.py fallback supprimé ; module `backend/src/fitmas/nlp.py` deleted ; le fallback restant est une réponse sobre "LLM indisponible" qui ne ment pas sur l'état du plan
- 415 tests passent, smoke `golden_case_autonomy` toujours rejouable
- Détails par chantier dans `docs/COACH-AUTONOMY-AUDIT.md` et `docs/COACH-AUTONOMY-REFACTOR.md`

Prochain pas : Chantier 1bis (anti-mensonge "dire = faire") — bloquer toute affirmation d'action si aucun `plan_mutation_event` n'a été émis ce tour.

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
- refactor coherence — etat reel :
  - `CoachStateBundle` = lecture partagée pour app, conversation, heartbeat ✓
  - `PlanMutationService` = gateway unique des mutations visibles ✓
  - `plan_mutation_events` = audit forward-only ✓
  - guards writer : `same_sport_proximity` et `protected_recovery_target` ✓
  - **dual-write actif** : `plan_actions.py` mute `DayPlan` dans tous ses chemins en parallele de `ScheduledSession`
  - **lectures legacy actives** : `signals.py` lit `WeeklyPlan`/`DayPlan`, `activities.py` matche contre `DayPlan`
  - `adaptation.py` produit des propositions, mais certains chemins (fatigue low-impact) auto-appliquent encore via orchestrateur
  - heartbeat = suggestion-only ✓

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
- `coach_reading_digest` : contexte pré-digéré (facts déterministes + lens Haiku JSON) injecté dans briefing matin et `decide()` sur intents lookup/report/availability, avec voice rules anti-bullshit (12b4bf8)

### Dette technique vivante

#### Dual-write ScheduledSession / DayPlan (critique)

Le systeme mute `DayPlan` et `ScheduledSession` en parallele. Ce n'est pas du compat — c'est le coeur du mutation path.

Writers actifs :
- `plan_actions.py` : lighten, modify, replace, swap, move, set_completion_status — tous mutent DayPlan
- `plan_mutation_service.py` : appelle `mark_day_completed()` a chaque completion
- `strava.py`, `api_activities.py` : marquent DayPlan done via `mark_day_completed_for_user()`

Readers actifs :
- `signals.py` : 5 detecteurs lisent `WeeklyPlan` / `DayPlan` pour alimenter le heartbeat
- `activities.py` : `match_activity_to_day()` matche contre DayPlan

Resolution cible : migrer `plan_actions.py` pour muter uniquement `ScheduledSession`, puis retirer les readers legacy.

#### repository.py hotspot (1 453 lignes, 72 fonctions)

Seul `repo_conversation.py` a ete extrait. Tout le reste du backend depend de ce fichier.
Candidats d'extraction : session queries, memory queries, converters to_pydantic_*.

#### Frontend code mort

Supprime le 13 avril 2026 :
- `frontend/src/pages/` (5 fichiers morts remplaces par `features/`)
- `frontend/src/state/app-state.tsx`
- `frontend/src/lib/api.ts`, `planning.ts`, `visuals.ts`
- `frontend/src/components/WorkoutModal.tsx`

#### conversation_pipeline.py (853 lignes)

Prochain hotspot. Orchestre message → signals → LLM → mutation → reponse. Pas encore sur le radar docs.

#### Couverture tests

Legere au regard de la richesse du domaine. Le systeme fait des mutations automatiques (adaptation) sans filet de tests suffisant.

### Ce qui reste partiel ou fragile

- le runtime tools plane reste volontairement etroit (read-only, 1 tool call max, pas de write tools)
- le heartbeat reste principalement cron + gating, pas encore tick-based
- le verrou anti-doublon reste surtout mono-process / best effort
- le savoir sport existe en contenu et heuristiques, pas encore comme **substrate canonique de capacites partagees**
- le `WeeklyRealityDigest` canonique n'existe pas encore
- la similarite de seance est encore simple (`sport_type + session_type`)

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
- `CONVERSATION.md`

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

### `PLANNING.md`

Quand le track planner redevient prioritaire :

- enrichir `periodization.py` au-dela du simple `3+1`
- mieux distribuer la charge par sport
- porter l'explication de `PlanningDecision` jusque dans coach + app
- enrichir l'onboarding sportif seulement apres ca

### Workout / strength

Le gros chantier reality-workout est absorbe.
Le vrai next domain, si on y revient :

- `strength_signals` plus riches
- variations renfo depuis reel recent + fatigue + sante + temps dispo
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
