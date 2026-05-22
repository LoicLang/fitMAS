---
summary: source de verite courte sur l'etat actuel et le prochain chantier
read_when:
  - commencer un chantier
  - verifier la suite immediate
  - recadrer le refactor avant de coder
---

# Build Order

## Phrase Guide

Je ne veux pas un refactor plus complet.
Je veux un runtime plus petit.

## Etat Actuel — 22 mai 2026

FitMAS est en refactor Decision Runtime.

Le cap produit reste :

- Telegram = coach conversationnel et proactif.
- App = cockpit de lecture.
- `ScheduledSession + Activity + Events` = verite runtime.
- Le LLM comprend le langage utilisateur.
- Le backend arbitre, valide, commit et audite.
- Les replies visibles doivent venir d'un outcome/verdict, pas d'un helper qui improvise.

## Ce Qui Est Vraiment En Place

Le repo contient maintenant :

- `decision/` : types centraux, `DecisionOutcome`, `DecisionReplyComposer`, `OutputVerifier`, `CommandBus`.
- `domain/planning/` : reference resolver, candidates, evaluator, policy, mutation service canonique.
- `llm/` : gateway, prompts, compat legacy LLM isolee, reply backend LLM.
- `skills/heartbeat/` : heartbeat runtime, reply composer, tool loop et generation proactive.
- `app/api/` et `app/telegram/` : deplacement progressif des entrypoints.
- `legacy/` : plus aucun module source actif.

Les cuts physiques recents :

- root wrappers supprimes : `api_messages.py`, `telegram_scheduler.py`, `llm_gateway.py`, `tool_*`, `plan_patch_tools.py`, `state.py`.
- root `final_reply.py` supprime.
- `legacy/conversation_reply_adapter.py` supprime.
- `legacy/final_reply_backend.py` supprime.
- `legacy/heartbeat_runtime_adapter.py` supprime.
- `legacy/heartbeat_skill_bridge.py` supprime.
- `legacy/conversation_command_bridge.py` supprime.
- `legacy/conversation_command_bus.py` supprime.
- `legacy/conversation_canonical_readonly_bridge.py` supprime.
- `legacy/conversation_readonly_reply_bridge.py` supprime.
- `legacy/conversation_understanding_bridge.py` supprime.
- `legacy/conversation_decide_bridge.py` supprime.
- `legacy/coach_decision_provider.py` supprime : plus de provider
  `CoachDecision` callable depuis la conversation.
- `legacy/coach_command_adapter.py` supprime.
- `legacy/coach_decision_artifact.py` supprime.
- `legacy/coach_understanding_adapter.py` supprime.
- `legacy/understanding_shadow.py` supprime.
- `llm/decision_legacy.py` supprime.
- `llm/legacy_{parser,prompt,action_compile,provider,schema_repair,tool_loop}.py`
  supprimes.
- `legacy/decision_contracts.py` supprime.
- `MutationDecision` vit temporairement dans `domain/planning/mutation_decision.py`
  tant que le vieux writer planning racine existe.
- `plan_mutation_service.py` racine supprime.
- Le writer PlanPatch vit dans `domain/planning/patch_mutation_service.py`.
- `mutations.py`, `mutation_hooks.py`, `mutation_permissions.py` racine
  supprimes.
- Les executors planning vivent dans `domain/planning/`.
- Les helpers de reply PlanPatch conversationnels sont sortis de
  `conversation_pipeline.py` vers `decision/plan_patch_reply.py`.
- `conversation_pipeline.py` est passe de `1819` a `78` lignes et delegue
  aux owners `decision/turn_*`.
- `decision/turn_router.py` est passe de `444` a `361` lignes : la route
  planning canonique vit maintenant dans `decision/turn_planning_route.py`.
- Les anciens modules root du pipeline candidat planning ont disparu :
  `plan_patch_candidates.py`, `plan_patch_candidate_evaluator.py`,
  `plan_patch_candidate_reviewer.py`, `plan_patch_adaptation_policy.py`.
  Le code actif vit sous `domain/planning/`.
- Le generateur root mort `plan_patch_backend_candidates.py` et ses tests
  dedies ont ete supprimes.
- Les routes et helpers API root ont ete deplaces sous `app/api/` :
  `routes_activities.py`, `routes_app.py`, `routes_debug.py`,
  `routes_onboarding.py`, `routes_ops.py`, `routes_plan.py`,
  `routes_read.py`, `routes_static.py`, `routes_stats.py`, `payloads.py`,
  `support.py`, `app_views.py`, `onboarding_contract.py`.
- Les modules Telegram root ont ete deplaces sous `app/telegram/` :
  `api.py`, `bot.py`, `channel.py`, `commands.py`, `debounce.py`,
  `onboarding.py`, `shared.py`, plus `scheduler.py`.
- Les modules execution root ont ete deplaces sous `domain/execution/` :
  `activities.py`, `claims.py`, `helpers.py`, `clarification.py`,
  `context.py`, `evidence.py`, `mutation_service.py`, `recent_reality.py`.
- Les modules memory root ont ete deplaces sous `domain/memory/` :
  `availability_constraints.py`, `fact_memory.py`, `maintenance.py`,
  `mutation_service.py`, `patterns.py`, `profile_memory.py`, `routing.py`,
  `profile_summary.py`.
- Les modules athlete root ont ete deplaces sous `domain/athlete/` :
  `profile.py`, `zones.py`, `fitness_snapshot.py`, `load_projection.py`,
  `performance_overview.py`, `performance_stats.py`, `readiness.py`,
  `strength_engine.py`, `strength_exercise_bank.py`, `strength_signals.py`,
  `threshold_estimation.py`, `training_load.py`.
- Les modules coaching root ont ete deplaces sous `domain/coaching/` :
  `adaptation_log.py`, `calibration_needs.py`, `calibration_status.py`,
  `coach_reading_digest.py`, `coach_voice.py`,
  `generated_week_coherence.py`, `repo_conversation.py`, `week_context.py`.
- Les modules core/integrations root ont ete deplaces :
  `core/calendar_resolution.py`, `core/db.py`, `core/seed.py`,
  `core/temporal_resolver.py`, `core/time_context.py`,
  `integrations/strava.py`.
- Les modules support LLM root ont ete deplaces sous `llm/` :
  `calibration.py`, `prompt_contracts.py`, `prompt_observability.py`.
- Les primitives planning root ont ete deplacees sous `domain/planning/` :
  `intensity_distribution.py`, `interference.py`, `periodization.py`,
  `planner.py`, `planning_config.py`, `planning_decision.py`,
  `planning_state.py`, `session_similarity.py`, `session_templates.py`,
  `workout_content.py`.
- Le langage de mutation et la review qualite semaine vivent maintenant sous
  `domain/planning/` : `plan_patch.py`, `week_coherence.py`.
- Le routeur d'intention de tour vit maintenant sous `decision/turn_planner.py`
  et recoit le provider LLM par injection depuis l'API.
- Les mini-modules metadata planning root ont ete absorbes :
  `compute_load_band` dans `domain/planning/models.py`,
  `build_week_label` dans `domain/planning/periodization.py`.
- La resolution de fenetre planning pour tools vit maintenant dans
  `domain/planning/window_resolution.py`.
- Le grounding visible des replies vit maintenant dans `decision/grounding.py`.
- La detection anti-claim d'action non committee vit maintenant dans
  `decision/output_verifier.py`; root `claim_guard.py` est supprime.
- Les contrats de tour conversationnel vivent maintenant dans
  `decision/conversation_contract.py`; root `conversation_contract.py` est
  supprime.
- Le context pack d'observabilite prompt vit maintenant dans
  `decision/context_pack.py`; root `context_pack.py` est supprime.
- Le contexte de tour conversationnel vit maintenant dans
  `decision/conversation_context.py`; root `conversation_context.py` est
  supprime.
- La policy de prompt conversationnel vit maintenant dans
  `llm/prompts/conversation_policy.py`; root `conversation_prompting.py` est
  supprime.
- La resolution pending canonique normalise les aliases d'enum provider
  (`confirm`, `accepted`, etc.) vers `accept_pending` avant application.
  Un type inconnu devient une clarification pending, jamais un trou vers
  `llm_unavailable`.
- La route planning canonique tolere maintenant les signaux preference
  sidecar sans scope : une demande planning supportee ne retombe plus en
  clarification provider parce que le LLM a varie la forme metadata.
- Le readonly plan lookup remplace maintenant une reply LLM non grounded par
  le fallback construit depuis les facts `PlanWindow`.
- Le fallback execution parle depuis l'event machine applique quand le
  composer LLM sort une reply invalide.
- Le planning canonique prend maintenant l'autorite sur un
  `CoachUnderstanding` actionable meme si l'ancien `turn_plan` a rate
  `plan_mutation`; les refs insuffisantes finissent en `planning_runtime_block`,
  pas en clarification provider.
- `docs/superpowers/plans/` supprime : l'historique d'execution reste dans git, pas dans la memoire active.

Etat chiffre au dernier check local :

- root modules : `17`.
- legacy modules : `0` fichier source actif.
- backend complet : `1347 passed, 11 skipped, 14 subtests passed`.
- smoke canonical planning default : OK `10/10`.
- smoke A+ API cible post root-cleanup : OK `4/4`, fallback scenario count `0`.
- fallback census core : `0`.

## Prochain Chantier

10M CoachDecision compat / old LLM path delete est maintenant applique.

Commande :

```bash
./scripts/decision-runtime-conversation-bridge-census \
  --json-out /tmp/fitmas-10j-conversation-bridge-census.json
```

Etat conversation bridge courant :

```text
runtime_active_count=0
legacy_internal_count=0
test_only_count=0
deleted_count=10
```

Tous les bridges conversationnels mesures ont ete supprimes physiquement :

```text
legacy/conversation_activity_highlight_bridge.py
legacy/conversation_canonical_clarification_bridge.py
legacy/conversation_canonical_readonly_bridge.py
legacy/conversation_coach_decision_reply_bridge.py
legacy/conversation_command_bridge.py
legacy/conversation_command_bus.py
legacy/conversation_decide_bridge.py
legacy/conversation_decision_bridge.py
legacy/conversation_readonly_reply_bridge.py
legacy/conversation_understanding_bridge.py
```

Commands vivent maintenant dans :

```text
decision/command_actions.py
decision/command_mapping.py
decision/command_application.py
```

Readonly/reply vit maintenant dans :

```text
decision/readonly_reply.py
```

Understanding runtime vit maintenant dans :

```text
decision/understanding_runtime.py
```

Trace de provider CoachDecision supprime vit maintenant dans :

```text
decision/coach_decision_runtime.py
```

Mais il ne lance plus aucun provider legacy :

```text
legacy_provider_skip_reason -> canonical_provider_clarification_outcome
```

Prochain chantier logique :

- il n'y a plus de bridge `legacy/conversation_*` runtime-active ;
- il n'y a plus de provider ou artifact `CoachDecision` ;
- `conversation_pipeline.py` est mince, donc le nouveau hotspot est
  `decision/turn_context.py`, puis le reste des petites routes dans
  `decision/turn_router.py` ;
- garder la priorite runtime plus petit, pas refactor plus complet.

## Ordre De Lecture Pour Un Agent

1. `PROJECT.md`
2. `docs/README.md`
3. `docs/BUILD-ORDER.md`
4. `docs/DECISION-RUNTIME-REFACTOR.md`
5. `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md`
6. `docs/SYSTEM-MAP.md`
7. doc domaine pertinent

## Regles De Travail

- Ne pas ouvrir Phase B progression/prescription sans demande explicite.
- Ne pas ajouter de fallback local.
- Ne pas ajouter de prompt long pour compenser une frontiere floue.
- Ne pas parser le texte utilisateur libre par regex/keywords.
- Ne pas faire de write hors command/writer service.
- Ne pas faire parler un helper hors composer/reply layer.
- Tout nouveau module doit avoir un owner clair dans l'organisation cible.

## Verification Minimale

Pour un changement backend :

```bash
./scripts/test-backend
```

Pour un changement runtime conversation/planning :

```bash
./scripts/smoke-a-plus-api --skip-generated-week \
  --scenario lookup_current_plan \
  --scenario create_easy_free_day \
  --fallback-census-json /tmp/fitmas-core-census.json \
  --timeout 420

./scripts/decision-runtime-fallback-census-summary \
  /tmp/fitmas-core-census.json \
  --json-out /tmp/fitmas-core-summary.json
```
