---
summary: carte simple du systeme FitMAS, flux, frontieres LLM/tools/skills/orchestrateurs et points d'extension
read_when:
  - comprendre comment fonctionne FitMAS
  - ajouter une capacite metier
  - brancher un tool ou une skill
  - modifier une mutation planning
  - expliquer l'architecture a un nouvel agent
---

# FitMAS System Map

## Vision courte

FitMAS n'est pas "un LLM qui fait un plan".

FitMAS est un systeme de coaching LLM-first, encadre par du determinisme :

- le LLM comprend le texte utilisateur libre, l'ambiguite, la negation et l'intention
- les tools lisent des slices bornees
- le backend porte la verite, les garde-fous, les validations, les permissions, les effets de bord et l'audit
- les skills orchestrent des workflows limites sans devenir des cerveaux conversationnels caches
- `PlanMutationService` est le point de commit des changements planning visibles

Regle canonique : aucun regex, keyword, parser maison, classifieur deterministe ou short-circuit ne lit le texte utilisateur libre pour decider l'intention. Voir `docs/LLM-FIRST-CONVERSATION.md`.

## Flux principal

```text
Telegram / App / Cron
        |
        v
Orchestrateurs
api_messages.py / api_plan.py / api_activities.py / heartbeat
        |
        v
Coach LLM unique
comprend le tour, garde le fil, choisit les read-tools utiles
sort CoachDecision structure
        |
        v
Validation backend
schema, permissions, hooks, confirmations, coherence guards
        |
        v
Writers bornes
PlanMutationService / MemoryMutationService cible
        |
        v
DB + events d'audit
        |
        v
Reply derivee de la decision LLM + resultat reel valide
```

## Frontieres

### LLM

Le LLM peut :

- comprendre un message flou
- aider a classer une intention
- proposer une adaptation
- formuler une reponse coach
- utiliser des tools read-only bornes

Le LLM ne peut pas :

- ecrire en DB directement
- choisir seul une seance future sans grounding
- modifier le planning sans `PlanMutationService`
- arbitrer entre deux verites planning concurrentes
- recevoir un write tool libre

### Tools

Un tool runtime est une lecture bornee exposee au LLM.

Exemples actuels / cibles :

- `resolve_planning_window`
- `get_recent_reality_window`
- `get_load_context`
- `get_relevant_facts`
- `get_user_constraints`
- `suggest_replan_candidates`
- `validate_plan_patch` (validation-only cible)
- `get_coach_state` (macro read-only optionnelle, plus tard)

Regles :

- read-only, candidate ou validation-only
- whitelist par pipeline
- peu nombreux
- semantiques
- audites via metrics
- jamais de write DB libre expose au modele

### Skills

Une skill produit est un workflow borne qui combine plusieurs capacites.

Exemple actuel :

- `skills/heartbeat/` pour briefing, reminder, review et signal check
- `replan_after_constraint` formalise comme workflow de prompt : tools atomiques -> candidate optionnelle -> `PlanPatch | no_change | requires_confirmation`

Exemples futurs :

- review de semaine
- analyse d'activite
- adaptation apres indispo
- briefing retour de blessure
- construction d'une seance compatible fatigue / kine / nutrition

Une skill ne doit pas contourner les orchestrateurs et le writer.

### Orchestrateurs

Les orchestrateurs possedent les effets de bord :

- `api_messages.py` / `conversation_pipeline.py` : conversation coach
- `api_plan.py` : actions app explicites
- `api_activities.py` / `strava.py` : activites et matching
- `skills/heartbeat/heartbeat.py` : messages proactifs
- `telegram_scheduler.py` : jobs planifies

Ils peuvent demander une mutation.
Ils ne doivent pas appliquer directement en bricolant la DB.

### Writer

`PlanMutationService` est la porte officielle pour les mutations planning visibles.

Responsabilites :

- appliquer les decisions autorisees
- appeler les hooks de coherence
- produire `plan_mutation_events`
- exposer le resume visible issu de l'evenement applique
- eviter les writes silencieux

## Verites du systeme

### Planning runtime

Verite live :

- `ScheduledSession`

Compat / template :

- `WeeklyPlan`
- `DayPlan`
- `/api/v0/week` avec `runtime_role=template_compat`

Regle :

- app, coach et heartbeat ne lisent pas `WeeklyPlan` / `DayPlan` comme verite runtime

### Execution

Sources :

- `Activity`
- claims utilisateur bornes
- `ExecutionEvidence`
- `RecentRealityWindow`

Regle :

- une seance n'est `done` que si la preuve est forte
- mauvais sport = off-plan, pas validation de la seance prevue
- passe sans preuve = `missing`

### Memoire

Couches :

- profil durable : `UserFact` utile au profil
- court terme : `working_memory_entries`
- patterns : `user_patterns`
- audit : transcript + events

Regle :

- les events ne sont pas une memoire brute a dumper dans le prompt
- ils deviennent des inputs pour digest / audit / explication

## Modules par domaine

### Runtime app / coach

- `coach_state_bundle.py` : bundle de lecture partage
- `app_views.py` : payloads app
- `calendar_resolution.py` : statut calendrier `planned / done / missing / offplan`
- `performance_overview.py` : charge, completion, distribution
- `week_context.py` : lecture narrative de semaine

### Conversation

- `conversation_pipeline.py` : tour de conversation, orchestrateur principal
- `conversation_context.py` : contexte machine seulement ; ne parse plus claims / non-completion depuis `user_text`
- `conversation_turn_planner.py` : legacy / transition ; la cible Phase A est une sortie `CoachDecision` unique plutot qu'un pre-classifieur qui repond deja a la question
- `conversation_prompting.py` : politique de prompt
- `llm_prompt_builder.py` / `prompt_layers.py` : prompt structure
- `llm_gateway.py` : client LLM + parseur JSON robuste partage (eea74e7)
- `user_indications.py` / `user_indication_llm.py` : types + pre-step LLM transitoire. Plus de fallback deterministe ; cible = actions structurees dans `CoachDecision`
- `mutation_hooks.py` : pre-hooks de coherence avec `block_reason` typed
- `coach_reading_digest.py` : contexte pre-digere (faits + lens Haiku JSON) injecte dans briefing matin et `decide()` sur intents lookup/report/availability (12b4bf8)

Regle conversation :

- le texte utilisateur libre va d'abord au coach LLM
- le LLM choisit les read-tools utiles dans le budget autorise
- le LLM sort une decision structuree unique : reply, actions memoire/execution, `PlanPatch | no_change | requires_confirmation`, resolution pending eventuelle
- le backend valide et applique seulement des artefacts machine-generes par le LLM
- aucun side-effect planning ou memoire ne doit arriver depuis un regex/keyword/parser sur le texte user
- `plan_mutation_request = heuristic OR llm`, `low_signal`, `rich_signal`, pending `oui/non` deterministe et `_sanitize_no_change_reply` sont retires du runtime conversation. Ne pas les recreer.

### Feedback bloquant mutations

Quand un pre-hook bloque une mutation, `PlanMutationService` expose un `PlanBlockedMutationEvent` avec un `block_reason` typed (`same_sport_proximity`, `occupied_training_target`). Les repos/recuperations ne sont plus des hard-blocks runtime ; la review semaine juge leur deplacement ou consommation.

Regle :
- le blocage est une verite machine post-validation
- la cible Phase A est une reponse coach issue du LLM ou d'un rendu d'event reel strictement auditable
- les dictionnaires de replies canned (`_BLOCK_REASON_REPLIES`) sont acceptables comme filet provisoire, mais ne doivent pas devenir le cerveau conversationnel
- chaque blocage emit `logger.info("mutation_blocked ...")` pour audit
- ajouter une nouvelle raison implique d'ajouter un rendu auditable ou une explication LLM fondee sur le `block_reason`

### Failles conversation documentees

Historique 15-17 avril : ces closures expliquent le code existant, pas la cible 30 avril.

| Faille | Closure | Ref |
|--------|---------|-----|
| A divergence heuristique/LLM | OR des deux + WARNING structure | b78db28 |
| B LLM ignore mutation heuristique | Force routage LLM pour availability/adaptation/health si heuristic=True | af54eda |
| C pas de classifieur intent | conversation_turn_planner dedie | e79d734 |
| D erreurs LLM opaques | `_classify_llm_exception` → labels stables | e81c3da |

### Planning

- `planner.py` : planner hebdo deterministe
- `planning_state.py` : construction des snapshots planning
- `planning_decision.py` : decision de charge / mode
- `planning_contract.py` : mission, roles, confidence, budget
- `session_templates.py` : templates de seances
- `plan_validator.py` : garde-fous generation

### Mutations

- `plan_mutation_service.py` : writer unique
- `mutations.py` : executeur interne historique
- `plan_actions.py` : operations concretes sur `ScheduledSession`
- `mutation_permissions.py` : confirmation high-impact
- `mutation_hooks.py` : coherence guards pre/post
- `session_similarity.py` : similarite initiale pour bloquer quasi-doublons

### Reality / performance

- `activities.py` : normalisation et matching activites
- `strava.py` : OAuth, import, sync Strava
- `execution_evidence.py` : preuve d'execution
- `recent_reality.py` : fenetre prevu vs fait
- `training_load.py` : TSS, CTL, ATL, TSB
- `fitness_snapshot.py` : snapshot performance
- `readiness.py` : lecture physique / mentale / logistique
- `calibration_status.py` : maturite de la connaissance utilisateur

### Memoire

- `fact_memory.py`
- `memory_profile.py`
- `memory_routing.py`
- `memory_patterns.py`
- `memory_maintenance.py`
- `profile_summary.py`

### Telegram / heartbeat

- `telegram_*.py` : bot, commandes, onboarding, scheduler, channel
- `skills/heartbeat/heartbeat.py` : facade heartbeat
- `skills/heartbeat/evaluation.py` : gating cooldowns
- `skills/heartbeat/roles.py` : prompts par role

### Tools runtime

- `tools/contract.py`
- `tools/registry.py`
- `tools/routing.py`
- `tools/runtime.py`
- `tools/metrics.py`

Wrappers de compat encore presents :

- `tool_contract.py`
- `tool_registry.py`
- `tool_routing.py`
- `tool_runtime.py`
- `tool_metrics.py`
- `heartbeat.py`
- `heartbeat_evaluation.py`
- `heartbeat_roles.py`

## Ajouter une capacite

Question a poser avant de coder :

1. Est-ce une lecture deterministe reutilisable ?
   - creer une capacite metier dans un module domaine

2. Est-ce une lecture utile au LLM ?
   - exposer un wrapper read-only dans `tools/`

3. Est-ce un workflow multi-etapes ?
   - creer une skill / orchestration bornee

4. Est-ce une mutation visible ?
   - passer par `PlanMutationService`

5. Est-ce flou cote utilisateur ?
   - grounder, clarifier ou demander confirmation

## Direction long terme

La cible est un coach ultra adaptatif avec equipe perf.

Architecture cible :

```text
Health / Perf data
        |
        v
Reality + Readiness layer
        |
        v
Expert advisors
nutrition / physio / endurance / recovery
        |
        v
Planning decision engine
        |
        v
PlanMutationService
        |
        v
Coach conversation + App cockpit
```

Les experts peuvent produire observations, contraintes, recommandations et flags.
Ils ne doivent pas ecrire directement dans le plan.

## Ce qu'on ne doit pas faire

- donner un write tool libre au LLM
- exposer tout le catalogue sport au modele
- ajouter une mutation cachee dans un module de scoring
- faire du prompt une source de verite
- recreer un dump geant de memoire dans le prompt
- refactorer en dossiers cosmetiques sans frontiere de responsabilite claire

## Prochaine lecture utile

- etat reel / priorites : `BUILD-ORDER.md`
- architecture detaillee : `ARCHITECTURE.md`
- refactor coherence : `COACH-COHERENCE-REFACTOR.md`
- tools LLM : `RUNTIME-TOOLS.md`
- indications utilisateur : `USER-INDICATIONS.md`
