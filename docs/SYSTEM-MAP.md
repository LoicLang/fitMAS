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

FitMAS est un systeme de coaching deterministe et adaptatif :

- le backend porte la verite, les garde-fous et les effets de bord
- le LLM comprend l'ambiguite, propose et formule
- les tools lisent des slices bornees
- les skills orchestrent des workflows limites
- `PlanMutationService` est le point de commit des changements planning visibles

## Flux principal

```text
Telegram / App / Cron
        |
        v
Orchestrateurs
api_messages.py / api_plan.py / api_activities.py / heartbeat
        |
        v
Capacites metier deterministes
reality / planning / readiness / analysis / drafting
        |
        v
Turn planner (LLM read-only, conversation seulement)
conversation_turn_planner.plan_conversation_turn()
primary_intent + secondary_intents + has_plan_mutation
        |
        v
Arbitrage heuristique OR LLM
plan_mutation_request = heuristic OR llm
divergence logguee, llm=unavailable toleree
        |
        v
LLM decide()
comprehension, proposition, formulation
tool budget route par primary_intent
        |
        v
Validation backend
permissions, hooks, confirmations, coherence guards
        |
        v
PlanMutationService
        |
        v
DB + plan_mutation_events (+ blocked_events typed)
        |
        v
Reply derivee de l'event applique ou block_reason typed
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
- `review_current_week`
- `resolve_target_session`

Regles :

- read-only
- whitelist par pipeline
- peu nombreux
- semantiques
- audites via metrics

### Skills

Une skill produit est un workflow borne qui combine plusieurs capacites.

Exemple actuel :

- `skills/heartbeat/` pour briefing, reminder, review et signal check

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
- `conversation_context.py` : grounding temps / claims / activites
- `conversation_turn_planner.py` : classifieur LLM read-only pour intention primaire / intentions secondaires (e79d734)
- `conversation_prompting.py` : politique de prompt
- `llm_prompt_builder.py` / `prompt_layers.py` : prompt structure
- `llm_gateway.py` : client LLM + parseur JSON robuste partage (eea74e7)
- `user_indications.py` / `user_indication_llm.py` : message user -> indication structuree
- `mutation_hooks.py` : pre-hooks de coherence avec `block_reason` typed

Regle de routage :

- pour un message non trivial ou compose, le LLM arbitre l'intention principale
- le routeur de tour ne fait aucun write; il ne sert qu'a proteger les gates du pipeline
- l'intention du routeur peut surclasser la classification deterministe pour choisir la prompt policy et le budget de tools (`_TURN_INTENT_TO_PROMPT_INTENT` dans `llm.py`)
- les extracteurs deterministes ajoutent du contexte, mais ne doivent pas produire de reply finale quand une intention planning explicite est presente
- les replies deterministes de disponibilite large / absence de candidat sont du grounding LLM quand le routeur reconnait une contrainte de planning, avec fallback deterministe si le LLM echoue
- les signaux sante restent prioritaires comme faits de contexte, mais une demande composee sante + mutation ne doit pas lancer d'adaptation sante automatique avant l'arbitrage LLM
- aucun side-effect planning ne doit arriver avant l'arbitrage du tour si le message contient une demande de mutation (`swap`, `echange`, `decale`, `deplace`, `remplace`, `change`)
- `plan_mutation_request = heuristic OR llm` — divergence → WARNING (`pipeline.intent_divergence`), `llm=unavailable` accepte sans downgrade

### Feedback bloquant mutations

Quand un pre-hook bloque une mutation, `PlanMutationService` expose un `PlanBlockedMutationEvent` avec un `block_reason` typed (`protected_recovery_target`, `same_sport_proximity`, `occupied_training_target`).

Regle :
- la reply utilisateur est derivee du `block_reason` via un dict `_BLOCK_REASON_REPLIES` — jamais improvisee par le LLM
- chaque blocage emit `logger.info("mutation_blocked ...")` pour audit
- ajouter une nouvelle raison implique d'ajouter la reply associee

### Failles conversation documentees

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
