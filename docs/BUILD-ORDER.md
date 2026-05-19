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

## Roadmap Active — 15 mai 2026

Le chantier actif bascule sur le refactor canonique
`docs/DECISION-RUNTIME-REFACTOR.md`.

Ordre courant :

```text
1. Phase 8 : kill legacy et activation progressive du runtime complet
2. Parite flag-on planning + heartbeat avant suppression des wrappers
3. Dogfood reel Telegram avec runtime cutovers actives en local/staging
```

Etat local 15 mai :

- Phase 0/1 initiale livree localement :
  - `backend/src/fitmas/decision/` cree comme package pur ;
  - types centraux poses sans DB, sans LLM, sans prompt, sans legacy ;
  - `tests/test_decision_types.py` et
    `tests/test_decision_runtime_architecture.py` verrouillent les frontieres ;
  - aucun comportement runtime branche sur le nouveau package.
- Phase 2 initiale livree localement :
  - `CoachContext` decoupe en contextes domaines ;
  - `DecisionContextBuilder` read-only dans `fitmas.decision.context_builder` ;
  - le builder construit depuis `InputEvent + DB` via `ScheduledSession`,
    `Activity`, memoire active et `CoachStateBundle` ;
  - le root package `fitmas.decision` ne charge pas le builder pour garder les
    imports purs legers ;
  - aucun comportement runtime branche sur le builder.
- Phase 3 initiale livree localement :
  - `CoachUnderstanding` porte maintenant `UserSignal`, `PendingResolution` et
    `ClarificationNeed` ;
  - `CoachDecision -> CoachUnderstanding` existe uniquement dans `legacy/` ;
  - `conversation_pipeline.py` logge un shadow understanding apres `decide()`,
    sans l'utiliser pour write, reply ou commit ;
  - la bascule planning reste reservee a Phase 4.
- Phase 4 initiale livree localement :
  - `backend/src/fitmas/domain/planning/` existe comme bounded context cible ;
  - `RequestedPlanChange` passe par
    `ReferenceResolver -> PlanCandidateBuilder -> PlanCandidateEvaluator -> SportPolicy` ;
  - `PlanningCommandService` est le seul writer introduit par Phase 4 ;
  - `decide_plan_change()` expose l'entrypoint domaine sans write direct ;
  - `legacy/planning_runtime_adapter.py` relie l'ancien contrat au nouveau
    pipeline planning ;
  - le cutover conversation est opt-in via `FITMAS_PLANNING_RUNTIME_CUTOVER=1`
    pour garder le dogfood stable jusqu'a Phase 5 ReplyComposer.
- Phase 5 initiale livree localement :
  - `ReplyRequest`, `ReplyResult`, `DecisionReplyComposer` et
    `DecisionOutputVerifier` existent dans `decision/` ;
  - `legacy/final_reply_backend.py` est le seul pont Phase 5 vers l'ancien
    `final_reply.py` ;
  - `planning_outcome_adapter.py` et `plan_patch_reply_adapter.py`
    convertissent les resultats legacy en `DecisionOutcome` avant parole ;
  - les helpers visibles PlanPatch de `conversation_pipeline.py` deleguent au
    composer ;
  - les verifications legacy PlanPatch restent preservees derriere l'adapter :
    post-event, uncommitted et factual grounding ;
  - `FITMAS_PLANNING_RUNTIME_CUTOVER` reste off par defaut.
  - verification locale : `./scripts/test-backend -q` -> 1052 passed,
    11 skipped, 11 subtests passed.
- Phase 6 initiale livree localement :
  - plan :
    `docs/superpowers/plans/2026-05-14-decision-runtime-phase-6-prompts.md` ;
  - `fitmas.llm` est converti en package compatible ;
  - `fitmas.llm.gateway` porte l'implementation gateway ;
  - `fitmas.llm_gateway` reste wrapper compat temporaire ;
  - `fitmas.llm.prompts.{understanding,reviewer,reply}` existe ;
  - reviewer/reply routent vers les nouveaux builders ;
  - Understanding reste en shadow avant cutover ;
  - ne pas migrer heartbeat ni supprimer les prompts legacy dans cette phase.
  - verification locale : `./scripts/test-backend -q` -> 1070 passed,
    11 skipped, 11 subtests passed.
- Phase 7 initiale livree localement :
  - plan :
    `docs/superpowers/plans/2026-05-14-decision-runtime-phase-7-heartbeat-runtime.md` ;
  - `legacy/heartbeat_runtime_adapter.py` mappe heartbeat legacy vers
    `InputEvent + DecisionOutcome + CoachDraft` ;
  - outcomes proactifs couverts : `answer`, `plan_pending`, `no_send` ;
  - verifier commun disponible en shadow, enforcement via
    `FITMAS_HEARTBEAT_RUNTIME_VERIFY_ENFORCE=1` ;
  - scheduler Telegram deplace vers `fitmas.app.telegram.scheduler` ;
  - root `fitmas.telegram_scheduler` reste wrapper compat ;
  - `FITMAS_HEARTBEAT_RUNTIME_CUTOVER=1` route scheduler, `/heartbeat`,
    debug heartbeat et ops heartbeat via l'adapter ;
  - cutover off par defaut pour proteger le dogfood ;
  - stabilisation associee : `execution_mutation_service` accepte les
    `target_ref` dates ISO produits par le LLM (`YYYY-MM-DD` ou
    `date:YYYY-MM-DD`) pour appliquer les execution updates contre
    `ScheduledSession` ;
  - legacy restant : `skills/heartbeat/heartbeat.py`, prompts/tool-loop,
    guards heartbeat, root `heartbeat.py`, debug trace internals.
  - verification heartbeat existante :
    `./scripts/test-backend -q tests/test_heartbeat_tool_loop.py tests/test_heartbeat_debug_endpoint.py tests/test_heartbeat_grounding.py`
    -> 40 passed.
  - smoke reel :
    `./scripts/smoke-real-conversations --scenario heartbeat_non_completion`
    -> exit 0, renfo J-1 marque `skipped`.
  - verification locale complete : `./scripts/test-backend -q` ->
    1094 passed, 11 skipped, 11 subtests passed.
- Phase 8A livree localement :
  - plan :
    `docs/superpowers/plans/2026-05-14-decision-runtime-phase-8a-legacy-audit.md` ;
  - kill list canonique :
    `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md` ;
  - importeurs `CoachDecision` / `MutationDecision` listes et testes ;
  - callers directs de `fitmas.final_reply` listes et testes ;
  - flags de cutover et tools legacy documentes ;
  - aucune suppression runtime, aucun cutover active par defaut.
  - verification ciblee :
    `./scripts/test-backend -q tests/test_phase8a_legacy_audit.py`
    -> 5 passed.
- Phase 8B livree localement :
  - plan :
    `docs/superpowers/plans/2026-05-14-decision-runtime-phase-8b-cutover-parity.md` ;
  - harness :
    `scripts/smoke-decision-runtime-cutover` ;
  - `PlanningRuntimeAdapterAttempt` ajoute la distinction
    applicable / non applicable / applicable non gere ;
  - sous `FITMAS_PLANNING_RUNTIME_CUTOVER=1`, une demande planning applicable
    passe par le runtime avant les branches legacy mixed adaptation ;
  - les demandes applicables non gerees deviennent
    `planning_runtime_unhandled`, sans commit ni pending legacy silencieux ;
  - heartbeat cutover teste avec verifier enforce ;
  - aucun cutover active par defaut, aucun legacy supprime.
  - verification flag-on :
    `FITMAS_PLANNING_RUNTIME_CUTOVER=1 FITMAS_HEARTBEAT_RUNTIME_CUTOVER=1 FITMAS_HEARTBEAT_RUNTIME_VERIFY_ENFORCE=1 ./scripts/test-backend -q tests/test_conversation_planning_runtime_adapter.py tests/test_conversation_planning_runtime_reply_composer.py tests/test_phase8b_planning_cutover.py tests/test_heartbeat_runtime_adapter.py tests/test_telegram_scheduler_runtime_adapter.py tests/test_phase8b_heartbeat_cutover.py`
    -> 30 passed.
  - harness reel :
    `./scripts/smoke-decision-runtime-cutover`
    -> exit 0 ; unit gates 28 passed ; smokes conversation critiques executes ;
    A+ API `move_easy_then_confirm` -> OK.
  - verification locale complete : `./scripts/test-backend -q` ->
    1111 passed, 11 skipped, 11 subtests passed.
- Phase 8C livree localement :
  - plan :
    `docs/superpowers/plans/2026-05-14-decision-runtime-phase-8c-legacy-kill.md` ;
  - `conversation_pipeline.py` ne write plus depuis les routes directes
    `MutationDecision`, `plan_patch` ou `requires_confirmation` legacy ;
  - les `MutationDecision` mutantes sont bloquees sans write, le no-change
    legacy reste read-only via composer commun ;
  - heartbeat Telegram passe par l'adapter runtime par defaut ;
  - `tools/registry.py` n'expose plus `propose_replan` ni les `draft_*` ;
  - `plan_mutation_service.py` et `api_read.py` ne lisent plus
    `WeeklyPlan` / `DayPlan` dans les chemins runtime controles ;
  - `legacy/{decision_contracts,tools_compat,weekly_plan_compat}.py`
    concentre les ponts historiques restants.
  - verification architecture Phase 8 :
    `./scripts/test-backend -q tests/test_decision_runtime_architecture.py tests/test_phase8a_legacy_audit.py tests/test_phase8b_cutover_architecture.py tests/test_phase8c_legacy_kill_architecture.py`
    -> 24 passed.
  - verification locale complete : `./scripts/test-backend -q` ->
    1116 passed, 11 skipped, 11 subtests passed.
  - harness reel :
    `./scripts/smoke-decision-runtime-cutover` -> exit 0.
- Phase 8D livree localement :
  - plan :
    `docs/superpowers/plans/2026-05-14-decision-runtime-phase-8d-bridge-shrink.md` ;
  - `DecisionRuntimeService` existe dans `decision/runtime.py` comme shell
    pur, sans import legacy ;
  - `/api/v0/messages` vit sous `fitmas.app.api.routes_messages` ;
    `fitmas.api_messages` reste wrapper compat ;
  - `conversation_pipeline.py` descend a 3459 lignes, sous le budget 8D ;
  - `legacy/conversation_planning_bridge.py` porte les helpers cutover
    planning ;
  - `legacy/conversation_readonly_reply_bridge.py` porte les replies
    read-only/no-change ;
  - `legacy/conversation_decision_bridge.py` porte les helpers de forme
    `CoachDecision` / legacy readonly ;
  - `legacy/heartbeat_skill_bridge.py` isole les wrappers racine vers
    `skills/heartbeat`.
  - verification ciblee :
    `./scripts/test-backend -q tests/test_phase8d_bridge_shrink_architecture.py tests/test_app_api_routes_messages.py tests/test_decision_runtime_service.py`
    -> passed.
  - verification locale complete :
    `./scripts/test-backend -q` -> 1130 passed, 11 skipped,
    11 subtests passed.
  - harness cutover :
    `./scripts/smoke-decision-runtime-cutover` -> unit gates 28 passed ;
    tentative full harness final interrompue pendant `smoke-real-conversations`
    apres stall provider, sans assertion code exploitable.
- Phase 8E livree localement :
  - plan :
    `docs/superpowers/plans/2026-05-14-decision-runtime-phase-8e-understanding-cutover.md` ;
  - `LLMUnderstandingService` existe sous `fitmas.llm.understanding_service` ;
  - `CoachUnderstanding` canonique est produit en shadow opt-in apres
    `CoachDecision` legacy, mais avant toute consommation planning runtime ;
  - le parser neutralise les artefacts planning/pending/clarification quand
    l'intent canonique ne correspond pas ;
  - `FITMAS_UNDERSTANDING_RUNTIME_SHADOW` est off par defaut ;
  - `FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER` est off par defaut ;
  - `planning_runtime_adapter.py` peut consommer le
    `RequestedPlanChange` canonique si le flag cutover est actif et que
    l'intent est `plan_change` ;
  - `conversation_pipeline.py` ne depend que du bridge
    `legacy/conversation_understanding_bridge.py` ;
  - le legacy provider reste en place pour memory/execution/pending jusqu'a la
    phase suivante.
  - verification locale complete :
    `./scripts/test-backend -q` -> 1153 passed, 11 skipped,
    11 subtests passed.
  - harness reel :
    `./scripts/smoke-decision-runtime-cutover` -> RESULT: OK.
  - smoke Understanding shadow :
    `FITMAS_UNDERSTANDING_RUNTIME_SHADOW=1 ./scripts/smoke-real-conversations --scenario heartbeat_non_completion`
    -> exit 0, log `decision_runtime.canonical_understanding`
    avec `requested_change=0` sur `execution_report`.
- Phase 8F livree localement :
  - plan :
    `docs/superpowers/plans/2026-05-14-decision-runtime-phase-8f-command-extraction.md` ;
  - `legacy/coach_command_adapter.py` compile les artefacts types en
    `Command` ;
  - `legacy/conversation_command_bus.py` applique memoire/execution via les
    services existants ;
  - `legacy/conversation_command_bridge.py` devient la frontiere conversation
    des actions memoire/execution ;
  - `conversation_pipeline.py` ne call plus directement
    `apply_memory_actions_for_user` ni `apply_execution_actions_for_user` ;
  - `conversation_pipeline.py` descend a 3219 lignes ;
  - `CommandResult` applique reference un event persiste ;
  - `FITMAS_COMMANDS_FROM_UNDERSTANDING` est off par defaut ;
  - le prompt Understanding documente les payloads types sans autoriser de
    write ;
  - dette restante : `pending_resolution` et provider `CoachDecision`.
  - verification ciblee 8F :
    35 passed.
  - architecture pack Phase 8 :
    45 passed.
  - verification locale complete :
    `./scripts/test-backend -q` -> 1167 passed, 11 skipped,
    11 subtests passed.
  - smoke Understanding shadow :
    `FITMAS_UNDERSTANDING_RUNTIME_SHADOW=1 ./scripts/smoke-real-conversations --scenario heartbeat_non_completion`
    -> exit 0, `command_source=coach_decision`, session renfo marquee
    `skipped`.
  - harness cutover :
    `./scripts/smoke-decision-runtime-cutover` -> unit gates 28 passed ;
    run interrompu ensuite pendant un stall provider DeepSeek JSON sur un cas
    planning, sans assertion code exploitable.
- Phase 8G livree localement :
  - plan :
    `docs/superpowers/plans/2026-05-14-decision-runtime-phase-8g-pending-resolution.md` ;
  - `legacy/conversation_pending_bridge.py` devient la frontiere conversation
    des confirmations pending ;
  - `conversation_pipeline.py` ne definit plus les helpers apply/recheck/accept
    pending et ne lit plus `decision.pending_resolution` directement ;
  - `plan_patch` et `plan_patch_choice` pending restent appliques via
    `apply_patch_for_user` / `PlanMutationService` ;
  - `FITMAS_PENDING_FROM_UNDERSTANDING` est off par defaut et prepare la
    consommation de `CoachUnderstanding.pending_resolution` ;
  - `conversation_pipeline.py` descend a 2731 lignes ;
  - verification ciblee 8G :
    8 passed.
  - parite pending/confirmation :
    33 passed.
  - architecture pack Phase 8 :
    49 passed.
  - verification locale complete :
    `./scripts/test-backend -q` -> 1175 passed, 11 skipped,
    11 subtests passed.
  - smokes API reels :
    `move_easy_then_confirm` -> RESULT: OK, clarification provider sans pending ;
    `confirm_without_pending` -> RESULT: OK, events=+0, pending=+0.
  - dette restante : `CoachDecision` provider par defaut, replies pending
    legacy-compat, migration finale des writes domaine.
- Phase 8H livree localement :
  - plan :
    `docs/superpowers/plans/2026-05-15-decision-runtime-phase-8h-pending-reply-cleanup.md` ;
  - `legacy/pending_reply_adapter.py` convertit les replies pending non
    commitantes en `DecisionOutcome` ;
  - `legacy/conversation_pending_bridge.py` ne lit plus
    `decision.fitmas_message` pour parler au user ;
  - reject / ignore / modify / clarification / expired / inactive /
    choice-error passent par `DecisionReplyComposer` ;
  - pending creee = demande de confirmation explicite via le contrat commun ;
  - `await_user_confirmation` / `await_user_choice` ne sortent plus comme
    `next_step` visible ;
  - verification ciblee 8H :
    24 passed.
  - parite pending/confirmation :
    33 passed.
  - architecture pack Phase 8 :
    52 passed.
  - verification locale complete :
    `./scripts/test-backend -q` -> 1187 passed, 11 skipped,
    11 subtests passed.
  - smokes API reels :
    `move_easy_then_confirm` -> RESULT: OK, pending plan_patch creee,
    events=+0 ;
    `confirm_without_pending` -> RESULT: OK, events=+0, pending=+0.
  - dette restante : `CoachDecision` provider par defaut,
    `FITMAS_PENDING_FROM_UNDERSTANDING` off, shrink final de
    `conversation_pipeline.py`, migration finale des services domaine.
- Phase 8I livree localement :
  - plan :
    `docs/superpowers/plans/2026-05-15-decision-runtime-phase-8i-canonical-flag-dogfood.md` ;
  - `tests/test_phase8i_canonical_flag_dogfood_architecture.py` verrouille les
    flags canoniques et le wrapper dogfood ;
  - `FITMAS_COMMANDS_FROM_UNDERSTANDING=1` peut appliquer des commandes memoire
    et execution depuis `CoachUnderstanding` dans les tests de bridge ;
  - `FITMAS_PENDING_FROM_UNDERSTANDING=1` peut faire gagner une resolution
    pending canonique dans les tests de bridge ;
  - les fallbacks vers `CoachDecision` restent explicites quand l'understanding
    canonique ne fournit pas d'artefact exploitable ;
  - `scripts/smoke-decision-runtime-canonical-flags` active
    `FITMAS_UNDERSTANDING_RUNTIME_SHADOW=1`,
    `FITMAS_COMMANDS_FROM_UNDERSTANDING=1` et
    `FITMAS_PENDING_FROM_UNDERSTANDING=1` ;
  - `FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER=1` reste volontairement hors
    wrapper par defaut.
  - verification ciblee 8I :
    21 passed.
  - architecture pack Phase 8 :
    55 passed.
  - verification locale complete :
    `./scripts/test-backend -q` -> 1197 passed, 11 skipped,
    11 subtests passed.
  - wrapper canonical :
    `./scripts/smoke-decision-runtime-canonical-flags` -> unit gates
    18 passed, smokes conversation termines, smokes API
    `move_easy_then_confirm` et `confirm_without_pending` -> RESULT: OK
    (2 checks).
  - durcissement duplicate pending :
    tests rouges/verts `canonical_pending_accept_survives_legacy_decide_none`
    et `canonical_pending_accept_preempts_legacy_decide` -> 2 passed.
  - gate pending/core apres durcissement :
    40 passed.
  - probe planning cutover explicite :
    `FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER=1 ./scripts/smoke-a-plus-api --scenario move_easy_then_confirm --timeout 240`
    -> RESULT: OK, `events=+1`, `pending=+1`, `mode=pending_accepted` ;
    plus de deuxieme pending creee.
  - dette restante : flags canoniques off par defaut, provider `CoachDecision`
    toujours actif, latence shadow Understanding, certains tours reels restent
    `command_source=coach_decision`, planning cutover canonique a dogfooder
    plus largement avant activation globale.
- Phase 8J livree localement :
  - plan :
    `docs/superpowers/plans/2026-05-15-decision-runtime-phase-8j-canonical-planning-cutover.md` ;
  - `scripts/smoke-decision-runtime-canonical-planning` active shadow
    Understanding, commandes canoniques, pending canonique et planning cutover ;
  - gates ajoutees : duplicate pending = hard fail,
    `confirm_without_pending` = no-write strict, `move_easy_then_confirm`
    = acceptation sans deuxieme pending ;
  - le smoke harness bloque maintenant les fuites de jargon visible
    `Candidate backend`, `Candidate possible` et `pas une reponse finale` ;
  - les `PlanPatch` candidates backend ne portent plus de `coach_message`
    interne ; `planning_outcome_adapter.py` ne donne plus les ids `backend:*`
    au composer comme summaries visibles ;
  - scenarios API passes : `move_easy_then_confirm`, `swap_by_day`,
    `lighten_tomorrow`, `replace_swim_with_bike`,
    `future_evening_unavailable`, `fatigue_tomorrow`, `avoid_back_to_back`,
    `swim_unavailable_two_weeks`, `confirm_without_pending` ;
  - verification ciblee 8J :
    8 passed.
  - pending/core cutover :
    3 passed.
  - architecture pack Phase 8 :
    59 passed.
  - wrapper canonical planning :
    `./scripts/smoke-decision-runtime-canonical-planning` -> RESULT: OK
    (9 checks).
  - verification locale complete :
    `./scripts/test-backend -q` -> 1207 passed, 11 skipped,
    11 subtests passed.
  - decision apres 8J :
    8K default-enable un sous-ensemble canonique si la matrice passe ;
    sinon 8J-fix par classification avant de toucher a `decide()`.
- Phase 8K livree localement :
  - plan :
    `docs/superpowers/plans/2026-05-15-decision-runtime-phase-8k-canonical-default-lanes.md` ;
  - decision CTO : default-enable commands/pending depuis
    `CoachUnderstanding`, pas le planning cutover complet ;
  - `FITMAS_COMMANDS_FROM_UNDERSTANDING` et
    `FITMAS_PENDING_FROM_UNDERSTANDING` deviennent default-on avec opt-out
    `0` ;
  - `FITMAS_CANONICAL_NON_PLANNING_CUTOVER` lance Understanding par defaut
    uniquement si un consumer non-planning peut utiliser l'artefact :
    pending actif, execution, sante, disponibilite, preference, memoire ;
  - `FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER` reste off par defaut ;
  - wrapper cible :
    `scripts/smoke-decision-runtime-canonical-defaults`, qui prouve les
    defaults sans exporter les flags commands/pending ;
  - tests ajoutes :
    `tests/test_phase8k_canonical_default_lanes_architecture.py` ;
  - tests de bridge ajoutes :
    default-on / opt-out commands, pending, gate Understanding scope ;
  - verification ciblee 8K :
    33 passed.
  - architecture pack Phase 8 :
    64 passed.
  - wrapper defaults :
    `./scripts/smoke-decision-runtime-canonical-defaults` -> RESULT: OK
    (2 checks API, smokes conversation OK).
  - wrapper planning opt-in :
    `./scripts/smoke-decision-runtime-canonical-planning` -> RESULT: OK
    (9 checks).
  - verification locale complete :
    `./scripts/test-backend -q` -> 1222 passed, 11 skipped,
    11 subtests passed.
  - decision apres 8K :
    preferer 8L = shrink/refactor `decide()` avant de default-enable le
    planning cutover.
- Phase 8L livree localement :
  - plan :
    `docs/superpowers/plans/2026-05-15-decision-runtime-phase-8l-decide-authority-shrink.md` ;
  - decision CTO : ne pas splitter `decision_legacy.py` en aveugle ;
    retirer d'abord son autorite directe dans le runtime conversation ;
  - `conversation_pipeline.py` ne call plus `dependencies.decide`
    directement, ne depend plus de `llm_runtime`, et ne lit plus
    `decision.fitmas_message` ;
  - nouveaux ponts livres :
    `legacy/coach_decision_provider.py`,
    `legacy/conversation_decide_bridge.py`,
    `legacy/conversation_coach_decision_reply_bridge.py` ;
  - tests ajoutes :
    `tests/test_phase8l_decide_authority_architecture.py`,
    `tests/test_coach_decision_provider.py`,
    `tests/test_conversation_decide_bridge.py`,
    `tests/test_conversation_coach_decision_reply_bridge.py` ;
  - verification ciblee 8L :
    40 passed.
  - architecture pack Phase 8 :
    70 passed.
  - wrapper decide shrink :
    `./scripts/smoke-decision-runtime-decide-shrink` -> RESULT: OK
    (8L gates, defaults canoniques, planning opt-in).
  - verification locale complete :
    `./scripts/test-backend -q` -> 1234 passed, 11 skipped,
    11 subtests passed.
  - commands/pending canoniques restent default-on ;
  - planning cutover canonique reste opt-in ;
  - prochaine phase probable : 8M split interne de `decision_legacy.py`
    une fois son autorite runtime bornee.
- Phase 8M livree localement :
  - plan :
    `docs/superpowers/plans/2026-05-16-decision-runtime-phase-8m-decision-legacy-split.md` ;
  - decision CTO : splitter `decision_legacy.py` par responsabilite sans
    changer le comportement runtime ni supprimer `CoachDecision` ;
  - `decision_legacy.py` passe de 2873 a 1467 lignes ;
  - modules livres :
    `llm/legacy_models.py`,
    `llm/legacy_parser.py`,
    `llm/legacy_prompt.py`,
    `llm/legacy_action_compile.py` ;
  - tests ajoutes :
    `tests/test_phase8m_decision_legacy_split_architecture.py`,
    `tests/test_llm_legacy_parser.py`,
    `tests/test_llm_legacy_action_compile.py` ;
  - verification ciblee 8M :
    31 passed.
  - tool/decide regression :
    67 passed, 126 deselected.
  - pending compat regression :
    18 passed.
  - wrapper decision legacy split :
    `./scripts/smoke-decision-runtime-decision-legacy-split` -> RESULT: OK
    (8M, 8L, defaults canoniques, planning opt-in).
  - architecture pack Phase 8 complet :
    76 passed.
  - verification locale complete :
    `./scripts/test-backend -q` -> 1245 passed, 11 skipped,
    11 subtests passed.
  - commands/pending canoniques restent default-on ;
  - planning cutover canonique reste opt-in.
- Phase 8N livree localement :
  - plan :
    `docs/superpowers/plans/2026-05-17-decision-runtime-phase-8n-provider-tool-loop-extraction.md` ;
  - decision CTO : extraire provider, schema repair et tool-loop de
    `decision_legacy.py` sans changer le comportement runtime ;
  - `decision_legacy.py` passe de 1467 a 941 lignes ;
  - modules livres :
    `llm/legacy_provider.py`,
    `llm/legacy_schema_repair.py`,
    `llm/legacy_tool_loop.py` ;
  - tests ajoutes :
    `tests/test_phase8n_provider_tool_loop_architecture.py`,
    `tests/test_llm_legacy_provider.py`,
    `tests/test_llm_legacy_schema_repair.py`,
    `tests/test_llm_legacy_tool_loop.py` ;
  - verification provider/schema/tool-loop/compat :
    23 passed.
  - prompt observability :
    8 passed.
  - decide/tools/CoachDecision regression :
    87 passed.
  - tool-loop regression :
    70 passed.
  - wrapper provider/tool-loop :
    `./scripts/smoke-decision-runtime-provider-tool-loop` -> RESULT: OK
    (8N, 8M, 8L, defaults canoniques, planning opt-in).
  - architecture pack Phase 8 complet :
    83 passed.
  - verification locale complete :
    `./scripts/test-backend -q` -> 1266 passed, 11 skipped,
    11 subtests passed.
  - commands/pending canoniques restent default-on ;
  - planning cutover canonique reste opt-in.
- Phase 8O livree localement :
  - plan :
    `docs/superpowers/plans/2026-05-17-decision-runtime-phase-8o-coachdecision-artifact-boundary.md` ;
  - decision CTO : interdire au runtime conversation de consommer directement
    le raw `CoachDecision` / `MutationDecision` ;
  - module livre :
    `backend/src/fitmas/legacy/coach_decision_artifact.py` ;
  - provider legacy :
    `CoachDecisionResult` expose `artifact` et conserve `raw_decision` pour
    compat seulement ;
  - conversation :
    `conversation_pipeline.py` manipule `legacy_decision_artifact` ;
  - bridges migres :
    command, pending, planning, reply, readonly, shadow Understanding et
    planning runtime adapter ;
  - tests ajoutes :
    `tests/test_phase8o_coachdecision_artifact_architecture.py`,
    `tests/test_coach_decision_artifact.py` ;
  - verification artifact/provider/bridges :
    57 passed.
  - core conversation regression :
    122 passed.
  - architecture pack Phase 8 complet :
    93 passed.
  - wrapper 8O :
    deterministe uniquement : 52 tests 8O + 118 tests 8N, puis `RESULT: OK`.
    Il ne lance plus de smoke API/LLM reel herite ; le dogfood reel reste dans
    les wrappers explicites.
  - verification locale complete :
    `./scripts/test-backend` -> 1281 passed, 11 skipped.
  - commands/pending canoniques restent default-on ;
  - planning cutover canonique reste opt-in.
- Phase 8P livree localement :
  - plan :
    `docs/superpowers/plans/2026-05-17-decision-runtime-phase-8p-decision-legacy-support-split.md` ;
  - decision CTO : continuer Option A avant le pivot provider canonique ;
  - `decision_legacy.py` ne porte plus les corps support onboarding,
    week-plan enrichment, fact memory extraction ni timeline summaries ;
  - modules livres :
    `llm/legacy_summaries.py`,
    `llm/legacy_onboarding.py`,
    `llm/legacy_fact_memory.py` ;
  - imports publics `fitmas.llm` preserves via wrappers patchables ;
  - `decision_legacy.py` descend a 556 lignes et reste centre sur
    `decide()` / provider / tool-loop / schema repair / action compile ;
  - verification architecture 8P :
    5 passed.
  - support modules :
    14 passed.
  - compat llm :
    28 passed.
  - wrapper 8P :
    deterministe uniquement : 21 tests 8P + wrapper 8O imbrique
    (52 tests 8O + 118 tests 8N), puis `RESULT: OK`.
  - architecture pack Phase 8 complet :
    98 passed.
  - verification locale complete :
    `./scripts/test-backend` -> 1300 passed, 11 skipped.
  - commands/pending canoniques restent default-on ;
  - planning cutover canonique reste opt-in.
- Phase 8Q livree localement :
  - plan :
    `docs/superpowers/plans/2026-05-17-decision-runtime-phase-8q-canonical-provider-pivot.md` ;
  - decision CTO : couper `decide()` du chemin heureux non-planning quand
    `CoachUnderstanding` porte deja un pending ou des commandes consommables ;
  - nouveau flag rollback :
    `FITMAS_CANONICAL_PROVIDER_NON_PLANNING`, on par defaut, opt-out explicite ;
  - `conversation_pipeline.py` lance l'Understanding canonique avant
    `run_legacy_coach_decision(...)` ;
  - `should_use_canonical_understanding_without_legacy(...)` refuse planning,
    `requested_change`, Understanding vide, pending non actif et commandes
    absentes ;
  - `LegacyCoachDecisionArtifact(source="coach_understanding")` reste un shim
    compat, sans `plan_patch`, sans actions legacy et sans texte visible
    legacy ;
  - trace :
    `turn_context["legacy_decide"]["legacy_skipped"] = True` quand le provider
    legacy est contourne ;
  - verification pivot bridge + architecture :
    18 passed.
  - wrapper 8Q :
    deterministe uniquement : 35 tests 8Q/bridges + wrapper 8P imbrique
    (21 tests 8P + 52 tests 8O + 118 tests 8N), puis `RESULT: OK`.
  - architecture pack Phase 8 complet :
    101 passed.
  - verification locale complete :
    `./scripts/test-backend` -> 1307 passed, 11 skipped.
  - `CoachDecision` reste fallback provider/parser pour planning et tours
    canoniques non actionnables ;
  - planning cutover canonique reste opt-in.
- Phases 8R / 8S livrees localement :
  - plans :
    `docs/superpowers/plans/2026-05-17-decision-runtime-phase-8r-canonical-readonly-reply.md`,
    `docs/superpowers/plans/2026-05-17-decision-runtime-phase-8s-readonly-default.md` ;
  - decision CTO : couper `decide()` des read-only truth lanes avant
    d'attaquer le planning ;
  - nouveau bridge :
    `backend/src/fitmas/legacy/conversation_canonical_readonly_bridge.py` ;
  - `CoachUnderstanding` peut produire un `DecisionOutcome(kind="answer")`
    compose par `DecisionReplyComposer` sans `CoachDecision` ;
  - `FITMAS_CANONICAL_READONLY_PROVIDER` est on par defaut, opt-out `0` ;
  - le gate refuse planning, `requested_change`, pending actif,
    `pending_resolution`, commands memoire/execution et close-turn ;
  - si la composition read-only canonique echoue, fallback legacy `decide()`
    conserve ;
  - verification bridge + architecture :
    11 passed.
  - regressions conversation ciblees :
    160 passed.
  - wrapper 8R/8S :
    deterministe uniquement : 28 tests read-only + wrapper 8Q imbrique
    (35 tests 8Q/bridges + 21 tests 8P + 52 tests 8O + 118 tests 8N), puis
    `RESULT: OK`.
  - architecture pack Phase 8 complet :
    105 passed.
  - verification locale complete :
    `./scripts/test-backend` -> 1318 passed, 11 skipped.
  - `CoachDecision` reste fallback provider/parser pour planning, close-turn et
    tours canoniques non supportes ;
  - planning cutover canonique reste opt-in.
- Phase 8T-A / 8T-B / 8T-C livree localement :
  - plan :
    `docs/superpowers/plans/2026-05-17-decision-runtime-phase-8t-canonical-planning-provider.md` ;
  - decision CTO : ouvrir le provider planning canonique en opt-in, sans
    default-enable avant dogfood reel ;
  - nouveau bridge :
    `backend/src/fitmas/legacy/conversation_canonical_planning_bridge.py` ;
  - `FITMAS_CANONICAL_PLANNING_PROVIDER` est off par defaut, opt-in `1` ;
  - le gate accepte seulement `CoachUnderstanding.intent=plan_change` avec un
    `RequestedPlanChange` supporte et des refs typees (`session_id:*`,
    `date:*`, `day:*`) ;
  - pending actif, `pending_resolution`, commands memoire/execution, refs
    libres et tours non planning restent exclus ;
  - le pipeline route ce chemin avant `run_legacy_coach_decision(...)` ;
  - en cas d'echec runtime applicable, le tour bloque en
    `planning_runtime_unhandled`, sans fallthrough legacy ;
  - `PlanningCommandService` reutilise une pending active identique au lieu de
    recreer un doublon ;
  - `planning_outcome_adapter.py` exige `event_count > 0` pour commit et un
    `pending_confirmation_id` pour pending avant d'autoriser les claims ;
  - 8T-C a passe le smoke API/LLM reel sous
    `FITMAS_CANONICAL_PLANNING_PROVIDER=1` ;
  - le provider planning canonique preempte maintenant le flow candidates
    pre-decide pour les demandes planning supportees ;
  - un pending actif est resolu par `CoachUnderstanding` avant candidate flow,
    puis verifie par un seul recheck LLM avant write ;
  - le parser Understanding normalise les refs provider `session:*` et les
    refs objet (`session_id`, `date`, `day`) avant le gate planning ;
  - les metadata preferences planning sont admises dans ce provider, tandis
    que les signaux memoire/execution bloquent toujours le skip legacy ;
  - verification bridge + hardening + architecture :
    25 passed.
  - hardening 8T-C cible :
    15 passed.
  - smoke API/LLM 8T-C :
    `FITMAS_CANONICAL_PLANNING_PROVIDER=1 ./scripts/smoke-decision-runtime-canonical-planning`
    -> `RESULT: OK (9 check(s))`.
  - wrapper 8T :
    deterministe uniquement : tests 8T/planning + refs Understanding + pending
    preemption + wrapper 8R/8S imbrique
    (28 tests read-only + 35 tests 8Q/bridges + 21 tests 8P + 52 tests 8O +
    118 tests 8N), puis `RESULT: OK`.
  - architecture pack Phase 8 complet :
    111 passed.
  - verification locale complete :
    `./scripts/test-backend -q` -> 1337 passed, 11 skipped, 11 subtests passed.
  - prochaine etape : default-on progressif du provider planning canonique,
    sans faire de la latence un gate produit.
- Phase 8U-A / 8U-B / 8U-C livree localement :
  - `FITMAS_CANONICAL_PLANNING_PROVIDER` est on par defaut, opt-out `0` ;
  - `conversation_understanding_bridge` lance l'Understanding planning par
    defaut pour les tours `plan_mutation` ;
  - `canonical_planning_provider` trace toujours `prepared`, `handled` ou
    `fallback_legacy` avec `fallback_reason` explicite ;
  - le smoke API hard-fail `move_easy_then_confirm` si le tour supporte n'a
    pas `canonical_planning_provider.result=handled` et `legacy_skipped=true` ;
  - le pending multi-turn hard-fail si la confirmation supportee ne porte pas
    `canonical_pending_provider.result=handled` ;
  - `LLMUnderstandingService` normalise les refs typees reelles observees :
    `session_3`, `date_YYYY-MM-DD`, `day:YYYY-MM-DD`, ISO brut, et peut
    completer `requested_change.source_ref` depuis
    `extracted_signals.payload.target_session_id` ;
  - `ReferenceResolver` accepte ces variantes typees sans parser le texte
    utilisateur libre ;
  - le recheck pending considere `oui je confirme si tu penses que c'est
    propre` comme une acceptation conditionnelle valide, puis laisse le backend
    revalider sportivement avant write ;
  - nouveau wrapper :
    `scripts/smoke-decision-runtime-canonical-planning-default`, sans export
    `FITMAS_CANONICAL_PLANNING_PROVIDER=1` ;
  - wrapper default-on reel :
    `./scripts/smoke-decision-runtime-canonical-planning-default`
    -> `RESULT: OK (9 check(s))` ;
  - verification ciblee :
    `./scripts/test-backend -q tests/test_conversation_canonical_planning_bridge.py tests/test_conversation_understanding_bridge.py tests/test_llm_understanding_service.py tests/test_domain_planning_reference_resolver.py tests/test_conversation_pending_bridge.py::ConversationPendingBridgeTest::test_pending_recheck_prompt_treats_coach_judgment_condition_as_acceptance tests/test_smoke_a_plus_api.py tests/test_phase8t_canonical_planning_provider_architecture.py`
    -> 70 passed.
  - verification locale complete :
    `./scripts/test-backend -q` -> 1357 passed, 11 skipped,
    11 subtests passed.
  - prochaine etape recommandee : Phase 8V, reduire le fallback legacy
    planning pour les refs typees supportees qui retombent encore en
    `fallback_legacy`.
- Phase 8V livree localement :
  - `ReferenceResolver` promeut les refs typees `date:` / `day:` vers une
    `ScheduledSession` quand le role planning exige une seance et qu'une seule
    seance existe ce jour-la ;
  - le provider planning canonique accepte maintenant `move`, `swap`,
    `lighten` et `replace` avec refs date/day machine, sans parser le texte
    utilisateur libre ;
  - `conversation_canonical_readonly_bridge` refuse un tour
    `primary_intent=plan_mutation` meme si l'Understanding LLM sort
    `general_answer` ;
  - `conversation_canonical_planning_bridge` peut reconstruire un
    `RequestedPlanChange(kind="swap")` depuis le `TurnPlan` type quand
    l'Understanding a bien vu un plan change mais a renvoye des refs non
    exploitables ;
  - les sidecars faibles du planning (`record_preference` day/week/general,
    `record_availability` available sans date/sport durable) ne bloquent plus
    le provider ; les vrais signaux commande comme `unavailable + sport/date`
    restent bloquants ;
  - `swap_by_day` rejoint les scenarios qui hard-fail si le provider canonique
    n'a pas `result=handled` et `legacy_skipped=true` ;
  - smoke reel cible :
    `./scripts/smoke-a-plus-api --skip-generated-week --scenario swap_by_day`
    -> `RESULT: OK (1 check)` avec
    `mode=planning_runtime_pending_confirmation` ;
  - wrapper default-on reel :
    `./scripts/smoke-decision-runtime-canonical-planning-default`
    -> `RESULT: OK (9 check(s))`.
- Phase 8W livree localement :
  - nouveau registre canonique `decision/fallback_census.py` ;
  - tout fallback actif vers `CoachDecision` doit maintenant porter une entree
    `fallback_census` avec `owner`, `source`, `reason`, `legacy_path`,
    `next_step` et `severity` ;
  - `conversation_decide_bridge.run_legacy_coach_decision()` classe le fallback
    avant persistance : planning, pending, reply/read-only ou provider legacy
    generique ;
  - `scripts/smoke_a_plus_api.py` hard-fail un turn avec
    `legacy_decide.legacy_skipped=false` sans `fallback_census` ;
  - cette phase ne supprime pas encore le legacy : elle rend la suppression
    pilotable. Le critere futur est simple : les lanes dogfood doivent avoir
    zero fallback legacy actif, ou un fallback explicitement possede avec une
    prochaine action de migration.
  - verification :
    tests census/bridge/smoke -> 25 passed ;
    wrapper default-on reel -> `RESULT: OK (9 check(s))` ;
    backend complet -> 1371 passed, 11 skipped, 11 subtests passed.
- Phase 8X livree localement :
  - le provider planning canonique recupere maintenant les demandes
    `move_session` depuis le `TurnPlan` type quand l'Understanding a bien vu
    un changement planning mais sort des refs libres ;
  - un move vers un jour deja occupe par une seule autre seance construit une
    candidate `swap_sessions` canonique, au lieu de retomber dans le candidate
    flow legacy ;
  - `move_hard_close` passe en `planning_runtime_pending_confirmation` avec
    `canonical_planning_provider.result=handled` et `legacy_skipped=true`.
- Phase 8Y livree localement :
  - `move_hard_close` rejoint les lanes couvertes par la gate de suppression
    legacy planning avec `move_easy_then_confirm` et `swap_by_day` ;
  - le wrapper `scripts/smoke-decision-runtime-canonical-planning-default`
    inclut maintenant `move_hard_close` ;
  - 8Y ne supprime pas tout `legacy/` : il supprime l'autorite legacy sur les
    lanes couvertes, et laisse les fichiers legacy restants derriere des gates
    mesurables.
  - verification :
    tests cibles planning/smoke -> 50 passed ;
    wrapper default-on reel -> `RESULT: OK (10 check(s))` ;
    backend complet -> 1376 passed, 11 skipped, 11 subtests passed.
- Phase 9A en cours/livree localement :
  - avant suppression, le fallback census a expose un trou reel sur
    `move_easy_then_confirm` : l'Understanding sortait parfois
    `source_ref=session_id_3`, non reconnu par les refs planning canoniques ;
  - correction long terme : `domain/planning/reference_tokens.py` centralise
    les refs typées (`session_id:3`, `session_id_3`, `session:3`,
    `session_3`, `id:3`, dates et jours) pour Understanding, provider
    canonique et resolver domaine ;
  - suppression physique ciblee :
    l'ancien `CoachDecision -> maybe_handle_planning_runtime_cutover` est
    retire de `conversation_pipeline.py`, `conversation_planning_bridge.py`,
    `planning_runtime_adapter.py`, des wrappers et des tests ;
  - `FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER` et
    `FITMAS_PLANNING_RUNTIME_CUTOVER` sont retires des chemins actifs ;
  - `scripts/smoke-decision-runtime-cutover` ne re-exporte plus le vieux flag
    planning et inclut la gate Phase 9A ;
  - le bridge `CoachDecision` ne route plus les decisions planning legacy
    pures vers une reponse visible : elles tombent en
    `legacy_decision_contract_disabled` sans write ;
  - verification locale :
    `./scripts/test-backend -q` -> 1385 passed, 11 skipped ;
    smoke reel cible 3 lanes -> RESULT: OK (3 check(s)) ;
    `./scripts/smoke-decision-runtime-canonical-planning-default` ->
    RESULT: OK (10 check(s)).
- Phase 9B en cours/livree localement :
  - le residu planning `replace_swim_with_bike` ne tombe plus en
    `legacy_decision_contract_disabled` ;
  - `TurnPlan.replace_session` peut fournir la source typee `day:sunday`
    quand l'Understanding contient des refs libres, tout en conservant
    `desired_sport` / `desired_intensity` ;
  - les sidecars `preference` scope `sport` ne bloquent plus le provider
    planning canonique quand ils accompagnent une demande planning supportee ;
  - `candidate_builder` normalise les artefacts types `velo -> cycling` et
    `facile -> easy`, puis produit une candidate `replace_session` bornee ;
  - `ReferenceResolver` resout aussi les refs typees `day:tomorrow` /
    `day:demain` depuis `CoachContext.local_time`, et les blocks planning ne
    renvoient plus de codes internes comme `unresolved_source_ref` au user ;
  - verification ciblee :
    replace smoke reel -> `planning_runtime_pending_confirmation`,
    `canonical_planning_provider.result=handled`, `legacy_skipped=true`,
    aucun `fallback_census` ;
    `./scripts/test-backend -q` -> 1393 passed, 11 skipped ;
    `./scripts/smoke-decision-runtime-canonical-planning-default` ->
    RESULT: OK (10 check(s)).
- Phase 9C en cours/livree localement :
  - `swim_unavailable_two_weeks` ne passe plus par le candidate fallback legacy ;
  - introduction d'une ref planning machine `sport_window:<sport>:<start>:<end>`
    resolue dans `domain/planning/reference_resolver.py` ;
  - `PlanCandidateBuilder` construit des candidates `replace_session` pour les
    seances planifiees et non terminees du sport indisponible dans la fenetre ;
  - les sidecars availability sport-window sont consommes par le provider
    planning canonique et la memoire availability reste appliquee avant
    l'enregistrement du tour ;
  - `avoid_back_to_back` est stabilise comme signal non-planning canonique quand
    l'Understanding sort un changement planning non specifique mais commandable ;
  - verification ciblee :
    `swim_unavailable_two_weeks` -> `planning_runtime_pending_confirmation`,
    `canonical_planning_provider.result=handled`, `legacy_skipped=true`,
    `memory_writes_json` contient `unavailable_swimming_2026-05-18_2026-06-01` ;
    `./scripts/smoke-decision-runtime-canonical-planning-default` ->
    RESULT: OK (10 check(s)) ;
    `./scripts/test-backend -q` -> 1399 passed, 11 skipped.
- Phase 9D livree localement :
  - le smoke API sait maintenant produire un rapport JSON de `fallback_census`
    par scenario via `--fallback-census-json` ;
  - la route candidate vide `availability_no_affected_session` est supprimee
    du pipeline conversation : le no-session sport-window est desormais gere
    par le planning canonique ou par un block/no-change sans candidate legacy ;
  - le fallback candidate/snapshot legacy est bloque quand l'Understanding
    canonique fournit une demande planning avec refs minimales absentes
    (`source_ref`/`target_ref`) ou confiance trop faible ;
  - aucune heuristique sur texte utilisateur libre n'a ete ajoutee : le blocage
    s'appuie uniquement sur `CoachUnderstanding.requested_change` type ;
  - les refs machine `session_id=3`, `session=3`, `id=3` sont normalisees avec
    les autres aliases dans `domain/planning/reference_tokens.py` ;
  - `planning_snapshot_flow` est maintenant classe dans `fallback_census` pour
    les sorties `compiled`, `needs_clarification`, `compile_failed` et `none`.
  - verification locale :
    `./scripts/test-backend -q` -> 1405 passed, 11 skipped ;
    smoke core + census -> RESULT: OK (15 check(s)) ;
    smoke daily + census -> RESULT: OK (26 check(s)).
- Phase 9E livree localement :
  - `add_hard_dense` est migre hors `planning_snapshot_flow` et
    `adaptation_candidate_flow` vers le `PlanningDecisionPipeline`
    canonique ;
  - le smoke API exige maintenant une trace canonique pour `add_hard_dense` ;
  - `TurnPlan.create_session` avec date cible typee peut produire un
    `RequestedPlanChange(kind="create")` canonique meme si l'Understanding LLM
    demande une clarification faute de sport ;
  - les creates target-only sont arbitres dans `domain/planning` :
    jour stable occupe -> block canonique, sport manquant sur jour libre ->
    block canonique, aucun fallback legacy ;
  - les intensites typees `high` / `hard` sont normalisees avant candidate
    building et policy ;
  - verification locale :
    `add_hard_dense` smoke reel -> `planning_runtime_block`,
    `canonical_planning_provider.result=handled`, `legacy_skipped=true`,
    `fallback_scenario_count=0`, aucun event, aucune pending ;
    `./scripts/test-backend -q` -> 1419 passed, 11 skipped.
- Phase 9F livree localement :
  - les contraintes larges type voyage / fenetre generale ont maintenant un
    artefact planning canonique :
    `RequestedPlanChange(kind="constraint_window")` avec
    `source_ref=availability_window:<scope>:<starts_on>:<ends_on>` ;
  - `ReferenceResolver` resout `availability_window` sans parser le texte
    utilisateur libre ;
  - `decision_service` bloque ces fenetres larges avant evaluator/policy :
    aucun event, aucune pending, aucun fallback snapshot ;
  - `trip_constraint` devient une lane smoke qui exige
    `canonical_planning_provider.result=handled` et
    `legacy_decide.legacy_skipped=true` ;
  - verification locale :
    targeted 9F gate -> 4 passed ;
    planning/bridge/smoke unit gate -> 85 passed ;
    `trip_constraint` smoke reel -> `planning_runtime_block`,
    `fallback_scenario_count=0`, aucun event, aucune pending ;
    `./scripts/test-backend -q` -> 1424 passed, 11 skipped.
- Phase 9G livree localement :
  - les tours disponibilite pure sont memory-first : une fenetre voyage typee
    est persistée comme availability, sans entrer dans le planning runtime ;
  - les tours disponibilite + demande d'adaptation restent routes vers le
    planning canonique via `constraint_window` ;
  - le routeur ne s'appuie que sur artifacts typees (`primary_intent`,
    `secondary_intents`, `mutation_signal`, `planning_action`,
    `availability_constraint`), jamais sur un parsing texte libre ;
  - le prompt TurnPlan distingue explicitement "Disponibilite seule" de
    "demande d'adapter" ;
  - verification locale :
    `trip_memory_only` smoke reel -> `no_change_composed`, `memory_applied=1`,
    `fallback_scenario_count=0`, aucun event, aucune pending ;
    `trip_constraint` smoke reel -> `planning_runtime_block`,
    `fallback_scenario_count=0`, aucun event, aucune pending ;
    `./scripts/test-backend -q` -> 1427 passed, 11 skipped.
- Phase 9H livree localement :
  - `availability_window` passe en reference v2 avec statut explicite :
    `availability_window:unavailable:<scope>:<starts_on>:<ends_on>` ;
  - la compat v1 `availability_window:<scope>:<starts_on>:<ends_on>` reste
    acceptee par le resolver ;
  - `constraint_window` ne bloque plus par defaut quand une option bornee est
    possible : `PlanCandidateBuilder` construit un candidat multi-move qui
    deplace les sessions actives touchees apres la fenetre, en gardant l'ordre ;
  - les fenetres larges forcent toujours `pending_confirmation`, meme si la
    policy/evaluation les jugent commit-safe ;
  - `PlanningCommandService` persiste le `PlanPatch` multi-operation comme
    pending `plan_patch`, sans event et sans commit direct ;
  - verification locale :
    targeted 9H gate -> 109 passed ;
    `trip_memory_only` smoke reel -> `no_change_composed`, aucun write
    planning ;
    `trip_constraint` smoke reel -> `planning_runtime_pending_confirmation`,
    pending `plan_patch` +1, event +0, mutation_applied=false.
- Phase 9I livree localement :
  - les `PlanPatch` multi-operation ont un resume user-safe construit depuis
    les operations machine, sans passer par un prompt ;
  - la reply `trip_constraint` parle au pluriel et liste les dates ciblees :
    plus de "seance ciblee" quand plusieurs sessions bougent ;
  - `DecisionExplanation.impact` expose `operation_count`,
    `move_session_count`, `target_dates`, `requires_confirmation` et
    `pending_confirmation_id` quand applicable ;
  - un test d'architecture interdit de copier des scenarios de smoke dans les
    prompts comme examples ; le vieux leak voyage a ete remplace par une regle
    generique ;
  - verification locale :
    targeted 9I gate -> 49 passed ;
    planning smoke census 7 lanes -> `RESULT: OK`, `fallback_scenario_count=0`
    pour `trip_memory_only`, `trip_constraint`, `swim_unavailable_two_weeks`,
    `replace_swim_with_bike`, `move_easy_then_confirm`, `swap_by_day`,
    `add_hard_dense`.
- Phase 9J livree localement :
  - `planning_snapshot_flow` est retire de `conversation_pipeline.py` :
    l'orchestrateur conversation n'appelle plus `build_planning_snapshot`,
    `generate_adaptation_proposal` ni `compile_adaptation_proposal` ;
  - les modules `planning_snapshot` / `adaptation_proposal` restent disponibles
    comme code historique/pur, mais ne sont plus une route runtime active ;
  - un test d'architecture interdit le retour de la route snapshot dans
    `conversation_pipeline.py` ;
  - les anciens tests qui exigeaient "snapshot avant candidate" verifient
    maintenant que snapshot est absent et que le fallback restant est explicite
    sous `adaptation_candidate_flow` ;
  - verification locale :
    targeted 9J gate -> 36 passed ;
    planning smoke census 7 lanes -> `RESULT: OK`, `fallback_scenario_count=0`.
- Phase 9K livree localement :
  - `adaptation_candidate_flow` est retire de `conversation_pipeline.py` :
    l'orchestrateur conversation n'importe plus `plan_patch_candidate_generator`
    et ne peut plus generer/evaluer/persister une adaptation via ce fallback ;
  - les helpers conversationnels de candidate fallback ont ete supprimes :
    plus de `_maybe_handle_plan_adaptation_candidates`, plus de
    `_should_use_plan_adaptation_candidate_flow`, plus de fallback
    `plan_adaptation_candidates` apres `decide()` ;
  - les primitives candidates restent autorisees dans `domain/planning/*` et
    dans les confirmations de choix, comme artefacts backend structures ;
  - un test d'architecture interdit le retour de cette route dans
    `conversation_pipeline.py` ;
  - verification locale :
    targeted 9K gate -> 111 passed ;
    planning smoke census 7 lanes -> `RESULT: OK`, `fallback_scenario_count=0`.
- Phase 9L livree localement :
  - ajout de `scripts/decision-runtime-fallback-census-summary` pour combiner
    plusieurs JSON de smoke et faire echouer le run si des fallbacks existent
    hors `--allow-fallbacks` ;
  - smoke core complet : 15 scenarios OK, 3 scenarios avec fallback census ;
  - smoke daily complet : 27 scenarios OK, 1 scenario avec fallback census ;
  - synthese globale core+daily :
    `scenario_count=42`, `fallback_scenario_count=4`,
    `fallback_turn_count=4` ;
  - owners restants : `planning=3`, `legacy_provider=1` ;
  - sources restantes : `canonical_planning_provider=3`, `legacy_decide=1` ;
  - scenarios restants :
    `swap_key_and_recovery`, `lighten_key_after_fatigue`,
    `ambiguous_move`, `short_slot_preference`.
- Phase 9M/9N livree localement :
  - suppression des derniers fallbacks actifs du census core+daily ;
  - `swap_key_and_recovery`, `lighten_key_after_fatigue` et
    `ambiguous_move` ne tombent plus vers legacy planning ;
  - `short_slot_preference` passe par `canonical_clarification` ;
  - `activity_highlight_lookup` passe par `canonical_activity_highlight` ;
  - `load_review_lookup` passe par `canonical_readonly_answer` ;
  - smoke core strict : `scenario_count=15`,
    `fallback_scenario_count=0`, `fallback_turn_count=0` ;
  - smoke daily strict : `scenario_count=27`,
    `fallback_scenario_count=0`, `fallback_turn_count=0` ;
  - summary global strict : `scenario_count=42`,
    `fallback_scenario_count=0`, `fallback_turn_count=0`.
- Phase 9O livree localement :
  - suppression physique de `backend/src/fitmas/planning_snapshot.py`,
    `backend/src/fitmas/adaptation_proposal.py` et
    `backend/src/fitmas/plan_patch_candidate_generator.py` ;
  - suppression des tests historiques dedies a ces trois modules ;
  - ajout de
    `tests/test_phase9o_historical_module_delete_architecture.py` pour
    interdire le retour de ces modules racine et de leurs imports ;
  - les modules candidates encore utiles au domaine planning restent gardes :
    evaluator, reviewer, adaptation policy et contrats de candidates ;
  - verification locale :
    targeted 9O gate -> 35 passed ;
    full backend -> 1413 passed, 11 skipped, 11 subtests passed ;
    core smoke strict -> `scenario_count=15`, `fallback_scenario_count=0`,
    `fallback_turn_count=0` ;
    daily smoke strict -> `scenario_count=27`, `fallback_scenario_count=0`,
    `fallback_turn_count=0` ;
    summary global strict -> `scenario_count=42`,
    `fallback_scenario_count=0`, `fallback_turn_count=0`.
- Suite logique :
  - lancer un census etendu hors core+daily avant toute coupe de
    `legacy/conversation_decide_bridge.py` ou `llm/decision_legacy.py` ;
  - traiter en slice separe les dettes de qualite reply observees en smoke
    (`sport=course`, troisieme personne sur execution, formulations trop
    brutes).
- Phase 9P livree localement :
  - ajout de `EXTENDED_SCENARIOS` et `--extended` au smoke API ;
  - ajout de `scripts/smoke-decision-runtime-extended-census` ;
  - ajout de
    `tests/test_phase9p_extended_census_architecture.py` et extension de
    `tests/test_smoke_a_plus_api.py` ;
  - correction d'un fallback `close_turn_ack` observe pendant le census :
    `trivial_ack` peut maintenant utiliser le terminal close path quand il n'y
    a pas de pending, secondaire, mutation ou calibration ouverte ;
  - verification locale :
    targeted 9P gate -> 38 passed ;
    full backend -> 1421 passed, 11 skipped, 11 subtests passed ;
    core+daily strict -> `scenario_count=42`,
    `fallback_scenario_count=0`, `fallback_turn_count=0` ;
    core+daily+extended discovery -> `scenario_count=62`,
    `fallback_scenario_count=1`, `fallback_turn_count=1`,
    owner `pending=1`, source `canonical_pending_provider=1` ;
  - fallback restant mesure :
    `pending_reject_move` passe encore par
    `canonical_pending_provider -> fallback_legacy -> CoachDecision`.
- Suite logique apres 9P :
  - Phase 9Q : migrer le rejet/cancel pending vers un outcome canonique sans
    `CoachDecision` ;
  - relancer core+daily+extended en strict ;
  - seulement ensuite commencer la reduction de
    `legacy/conversation_decide_bridge.py` / `llm/decision_legacy.py` ;
  - garder les dettes de reply quality dans un slice separe.
- Les anciens plans PlanningSnapshot / prompt-context / candidate-flow restent
  lisibles comme historique mais ne tranchent plus la cible.

## Roadmap precedente — 13 mai 2026

Ordre courant :

```text
1. Stabilisation dogfood restante : memoire dispo stale, legacy availability, claims sans event
2. Refactor PlanningSnapshot -> AdaptationProposal sur branche codex/planning-snapshot-adaptation
3. Replays API reels du scenario courbatures/running demain/piscine vendredi
4. Generated week policy si encore observee en dogfood reel
5. Phase B progression/prescription seulement sur demande explicite
```

Regle d'arbitrage : le dogfood API reel du 12 mai a confirme des echecs
integration/protocole concrets. P0 gateway JSON reliability est implemente
localement le 12 mai, P1 a ete rejoue, et P2 core split est implemente
localement. P3 compilers dedies execution/sante/disponibilite est implemente
localement. P4 a retire `validate_week_coherence` de la surface tools
conversation. P5 a reduit les tools par route et isole la disponibilite pure en
memory-only. La prochaine tranche prioritaire est l'hygiene pending, puis les
candidats sport-specific pour les indisponibilites longues. Ces deux points
sont implementes localement en P6a. P6b a ferme l'hygiene tool-loop et la
memoire disponibilite sport-window. P6c a ajoute le hard guard plan lookup et
le cas no-session sport-specific. Le fallout dogfood du 13 mai est traite
localement : target-date empty guard action-aware, no-write sur tour obsolete,
cleanup generated rest/off, et hard guard post-event sur ancienne date de move.
Le replay courbatures/running demain/piscine vendredi du 13 mai montre que la
candidate-flow outillee casse encore la latitude de raisonnement : memoire
disponibilite stale, menu flou, claim sans commit et timeout sur la proposition
multi-session. La prochaine tranche est le refactor
`PlanningSnapshot -> AdaptationProposal -> ProposalCompiler`, documente dans
`docs/PLANNING-SNAPSHOT-ADAPTATION-REFACTOR.md`, sur la branche
`codex/planning-snapshot-adaptation`.

Docs a ouvrir selon le chantier :
- excellence sportive : `docs/SPORT-QUALITY-REVIEW.md`
- adaptation LLM bornee : `docs/ADAPTATION-CANDIDATE-PIPELINE.md`
- refactor snapshot adaptation : `docs/PLANNING-SNAPSHOT-ADAPTATION-REFACTOR.md`
- prompt/contexte + `decide() None` : `docs/PROMPT-CONTEXT-REFACTOR.md`
- dogfood API/gateway 12 mai : `docs/API-DOGFOOD-RELIABILITY-2026-05-12.md`
- memoire : `docs/MEMORY-V2.md`

## Checkpoint courant — 13 mai 2026

Etat du code sur `main` :

- Phase A fiabilite coach : fermee pour le dogfood courant.
- Phase A+ sport quality gate : livree. Les `PlanPatch` significatifs passent
  par simulation/review/policy avant commit ou pending.
- Prompt/context diet : livree. Les prompts sont maintenant gouvernes par
  `PromptContract`, filtres par capability, et couverts par snapshots.
- Adaptation candidate pipeline : livree. Le LLM explore des options bornees,
  le backend fournit des `candidate_ref`, l'evaluator simule/score, et le
  reviewer LLM ne choisit qu'un `candidate_id`.
- `general_answer` a une lane naturelle avec `get_coach_lens` optionnel pour
  lire le contexte coach compact sans noyer la reponse dans le planning.
- Heartbeat : le composer terminal existe et bloque les fuites de categories
  internes, mais le style doit rester surveille en dogfood reel.
- Memoire/readiness : en cours de durcissement. Les facts portent maintenant
  statut, temporalite, severite et `signal_kind`. `readiness.py` ne doit pas
  retransformer des textes libres ou des vieux facts en flags via mots-cles :
  il consomme seulement des facts ouverts, temporellement valides et
  explicitement `affects=["readiness"]`.
- Dogfood API reel du 12 mai : 42 checks ad hoc sur serveur local + fausse DB
  + vrais appels LLM. Les endpoints et plusieurs lectures tiennent, mais les
  echecs critiques montrent une fragilite de protocole : `system` listifie dans
  la gateway DeepSeek JSON, exemple global legacy `mutation_type`, tool-use
  final non verrouille en JSON mode, contrat `CoachDecision` trop large pour
  execution/sante/disponibilite. Diagnostic et plan :
  `docs/API-DOGFOOD-RELIABILITY-2026-05-12.md`.
- P0 gateway 12 mai : `render_system_text(system)`, contrat JSON neutre sans
  exemple legacy `mutation_type`, `schema_hint` structured JSON, et
  `request_json()` route vers structured JSON mode quand DeepSeek est configure
  et que le chemin legacy n'est pas monkey-patche.
- P1 replay 12 mai : daily-life `FAIL (4/26)`, A+ core partiel timeout sur les
  deux premiers scenarios mutation, generated-week timeout. Les erreurs de
  format ont disparu dans les logs (`unknown_mutation_type=0`,
  `truncated_fitmas_message=0`, `tool_budget_exceeded=0`), mais les routes
  `health_signal` / `plan_negotiation_full` restent a 80-115s et les
  confirmations nues peuvent encore commit un `move_session`.
- P2 core 12 mai : apres au moins un tool execute, `decide()` passe par un
  compiler `_request_structured_json()` sans tools avant tout parse direct de
  la reponse tool-use. La phase tool collecte facts/candidats; le compiler
  produit le `CoachDecision` final. Si le compiler echoue, l'ancien parse/retry
  reste fallback.
- Replay `move_easy_then_confirm` apres P2 : timeout avant decision finale,
  concentre sur `validate_week_coherence` dans `plan_negotiation_full`.
- P3 compilers dedies 12 mai : `EXECUTION_COMPILER`,
  `HEALTH_MEMORY_COMPILER` et `AVAILABILITY_MEMORY_COMPILER` action-only apres
  `CoachDecision`, sans tools ni `PlanPatch`. Ils utilisent le modele fort,
  acceptent l'alias structure `action -> type`, et retry strictement la memoire
  quand le scope LLM est confirme mais le premier compiler rend `[]`.
- P4 conversation tool budget 12 mai : `validate_week_coherence` n'est plus
  offert dans `conversation_plan_negotiation`, `conversation_health_signal`, la
  registry conversation ni le fallback canonical budget. Le tool reste
  disponible pour `planning` et `heartbeat`; la gate backend continue de
  reviewer les `PlanPatch` avant pending/commit.
- P5 route budgets 12 mai : `conversation_availability_constraint` est un
  contrat dedie memory-only avec 3 tools (`resolve_planning_window`,
  `get_plan_window`, `get_user_constraints`). `health_signal` passe a 5 tools.
  `plan_negotiation_full` passe a 10 tools. Les demandes dispo qui disent
  explicitement "adapte/bouge/remplace" restent en `plan_mutation`.
- P7 fallout 13 mai : replay API reel daily `OK (26)`, generated workflow
  `OK (4)` avec `count(rest/off actif)=0`, `lighten_tomorrow` bloque maintenant
  sans tool-loop quand aucune seance n'existe sur la date cible, et
  `move_easy_then_confirm` commit avec phrase finale coherente avec l'event DB.
  Tests locaux : `tests/test_core_flows.py` 93 passed,
  `tests/test_onboarding_planner_flow.py tests/test_generated_week_coherence.py`
  8 passed, `tests/test_smoke_a_plus_api.py` 11 passed.
- P6a pending hygiene 12 mai : une pending nue n'est plus applicable sauf si
  une seule pending active est exposee. Les pending expirees sont fermees avant
  exposition, l'accept revalide `status/expires_at`, et les outcomes
  `modify_pending` / `needs_clarification` / choix invalide gardent le meme
  pending ouvert au lieu d'etre supersedes par le cleanup final.
- P6a disponibilite sport-specific 12 mai : le turn planner porte maintenant
  `availability_constraint` (`availability`, `sport_type`, `starts_on`,
  `ends_on`, `scope`). Les backend candidates utilisent cet artefact type pour
  cibler uniquement les seances du sport concerne dans la fenetre; si swimming
  est indisponible, aucune seance running n'est proposee par les candidats
  backend.
- P6b memoire/tool-loop 13 mai : dedup exact des tool calls
  `tool_name + arguments` sans consommer de budget, cache partage conversation
  + heartbeat, `record_availability.sport_type/scope`, cle memoire canonique
  `unavailable_<sport>_<start>_<end>`, et persistance depuis
  `turn_plan.availability_constraint` quand la candidate-flow sort avant
  `decide()`.
- P6c lookup/no-session 13 mai : hard guard deterministe des reponses
  `plan_lookup` contre `ReplyGroundingPacket` pour durees minutes, dates ISO,
  claims de jour vide/repos, sport et statut; fallback DB compact; scenario
  `swim_unavailable_no_session` qui note l'indisponibilite sport-specific sans
  pending quand aucune seance du sport cible n'existe dans la fenetre.
- PlanningSnapshot refactor 13 mai : plan pose pour redonner au LLM une vue
  semaine complete avant compilation PlanPatch. Le refactor cible les scenarios
  larges ou imprevus : snapshot complet, `AdaptationProposal` JSON-only sans
  tools d'ecriture, compiler backend vers `PlanPatch`, validation/pending/commit
  existants, et invariant strict sur `rest_total` / `active_recovery` /
  `unscored_recovery`.
- PlanningSnapshot tranche initiale 13 mai : `planning_snapshot.py` +
  `adaptation_proposal.py` branches dans `plan_mutation` avant l'ancien
  generator candidate, apres les exits typed. La gateway preserve maintenant
  les schemas custom `AdaptationProposal`. Le compiler sait ignorer le
  recovery non scoree `rest/rest` non supporte et transformer une chaine
  `move A -> jour de B` + `move B -> autre jour` en `swap(A,B)` + `move(B)`.
  Replay API cible "running demain et piscine vendredi" : pending confirmation
  creee via `planning_snapshot_flow`, sans legacy candidate, en ~79s.
- PlanningSnapshot polish 13 mai : `health_signal` secondaire ne force plus le
  vieux `decide()` avant snapshot, `AdaptationProposal` est compile par
  `deepseek-v4-flash` avec schema hint explicite, un `move` vers un jour occupe
  peut devenir `swap_sessions`, l'evaluator preserve les metadata du patch
  unique, `pending_resolution=ignore` garde la pending active, et les summaries
  de final reply portent maintenant les operations + dates DB. Replay reel
  courbatures + deplacement vendredi : `planning_snapshot_flow=compiled`,
  pending creee, pas de commit ni fallback legacy; formulation encore a
  surveiller en dogfood.
- PlanningSnapshot boundary fix 13 mai : `conversation_plan_negotiation` n'offre
  plus les tools candidats qui se chevauchent (`suggest_replan_candidates`,
  `draft_*`). La surface LLM planning est maintenant lecture + validation
  seulement (`get_plan_window`, `resolve_planning_window`,
  `get_user_constraints`, `validate_plan_patch`), tandis que les adaptations
  larges passent par `PlanningSnapshot -> AdaptationProposal -> compiler
  backend`. Meme tranche : `unavailable_general_*` legacy est resolu par une
  disponibilite generale qui overlap, les clarifications gardent la pending
  active, et une action execution `not_completed` est differee si le meme tour
  porte une disponibilite + PlanPatch sur la meme seance. Un
  `accept_pending` doit maintenant etre confirme par un verifier LLM JSON-only
  dedie avant commit; doute ou verifier indisponible = pending gardee ouverte.
- Multi-tour dogfood hardening 13 mai : ajout d'un sas LLM
  `pending_pre_adaptation_gate` avant de relancer PlanningSnapshot quand une
  pending active existe. Seul `modify_pending` peut lancer une nouvelle
  adaptation; `j'attends`, statut, question ou accept/reject ambigu gardent la
  pending ouverte et ne commitent rien. Le compiler PlanningSnapshot ne deplace
  plus les placeholders `rest/off`, dedup les operations identiques, et les
  replies adaptation ont un hard guard sur durees et dates relatives avant
  d'etre affichees. Replay multi-tour reel final : aucun event sans confirmation,
  ancienne indispo `unavailable_general_*` resolue, pending finale ouverte.
  Reste qualite : certains runs gardent une proposition ancienne au lieu de
  produire la meilleure nouvelle option apres correction de disponibilite.

Verification recente :

- `./scripts/test-backend -q` : 947 passed, 11 skipped, 11 subtests passed.
- Snapshot adaptation local 13 mai :
  `tests/test_llm_gateway_json.py tests/test_adaptation_proposal.py tests/test_planning_snapshot.py`
  -> 35 passed ;
  `tests/test_core_flows.py tests/test_llm_tools.py tests/test_conversation_turn_planner.py`
  -> 171 passed ;
  `tests/test_memory_mutation_service.py` + candidate/PlanPatch suites
  -> 49 passed.
- Snapshot polish local 13 mai :
  `tests/test_adaptation_proposal.py tests/test_planning_snapshot.py
  tests/test_plan_patch_candidate_evaluator.py tests/test_core_flows.py
  tests/test_blocked_mutation_reply.py` -> 140 passed.
- Pending accept recheck local 13 mai :
  `tests/test_core_flows.py -q -k "pending"` -> 20 passed ; replay API reel
  force-false-accept + `j'attends` -> `pending_ignore`, pending ouverte, aucun
  event ; replay API reel + `oui confirme le deplacement` ->
  `pending_accepted`, event cree.
- Multi-tour hardening local 13 mai :
  `./scripts/test-backend tests/test_prompt_snapshots.py tests/test_prompt_contracts.py
  tests/test_conversation_prompt_modules.py tests/test_llm_tools.py
  tests/test_llm_prompt_builder.py tests/test_memory_mutation_service.py
  tests/test_claim_guard.py tests/test_core_flows.py tests/test_adaptation_proposal.py
  tests/test_planning_snapshot.py tests/test_plan_patch_candidate_evaluator.py -q`
  -> 301 passed.
- `main` contient le merge `ee4a313 Merge prompt context and adaptation candidates`.
- Dogfood API reel 12 mai : 42 checks ad hoc, 3 fails bruts stricts, plusieurs
  conclusions manuelles a corriger avant de juger DeepSeek.
- P0 gateway local : `./scripts/test-backend tests/test_llm_gateway_json.py -q`
  -> 25 passed ; `./scripts/test-backend tests/test_conversation_turn_planner.py
  tests/test_week_coherence.py tests/test_llm_tools.py -q` -> 77 passed.
- P2 core local : `./scripts/test-backend tests/test_llm_tools.py -q`
  -> 60 passed ; `./scripts/test-backend tests/test_llm_gateway_json.py
  tests/test_conversation_turn_planner.py tests/test_week_coherence.py
  tests/test_llm_tools.py -q` -> 104 passed.
- P2 smoke API cible :
  - `trip_constraint` + `lighten_tomorrow` -> `OK (2 check(s))`, deux traces
    `response_stop_reason=tool_compiler_json`, zero erreur de format observee;
  - `confirm_without_pending` -> `OK (1 check(s))`, aucune mutation/pending;
  - warning manuel : `trip_constraint` reste mal clarifie en surface (natation
    mentionnee sur un message voyage), donc P2 stabilise le protocole mais ne
    remplace pas les compilers dedies.
- P3 local :
  - `./scripts/test-backend tests/test_llm_tools.py -q` -> 64 passed;
  - batterie cible gateway/planner/week/LLM/memory/core writers -> 116 passed;
  - smoke compiler isole vraie API -> health 1 action, availability 1 action,
    execution 1 action;
  - smoke API `execution_done_today`/`missed_session_report`/
    `future_evening_unavailable` -> `OK (3 check(s))`;
  - `shin_pain_signal` -> `OK (1 check(s))`, avant P4 la route restait lente
    quand elle appelait `validate_week_coherence`.
- P4 local :
  - prompt/runtime targeted -> 144 passed;
  - `move_easy_then_confirm` -> `OK (1 check(s))`;
  - traces : plus de `validate_week_coherence` offert, turn 1 tool loop
    `get_plan_window,draft_move_session` en ~12s, turn 2
    `resolve_planning_window,get_plan_window` en ~16s.
  - `shin_pain_signal` + `future_evening_unavailable` -> `OK (2 check(s))`;
    sante a `tool_count_offered=7`, dispo garde `tool_count_offered=16`, zero
    `validate_week_coherence` offert, memoires appliquees.
- P5 local :
  - prompt/planner/LLM targeted -> 125 passed, 5 subtests passed;
  - `future_evening_unavailable` -> `OK (1 check(s))`, route
    `availability_constraint`, `tool_count_offered=3`, `memory_applied=1`;
  - `swim_unavailable_two_weeks` -> `OK (1 check(s))`, route `plan_mutation`,
    `tool_count_offered=10`, pending creee, `memory_applied=1`;
  - `future_evening_unavailable + shin_pain_signal + move_easy_then_confirm`
    -> `OK (3 check(s))`, a revele puis confirme le besoin memory-only sur
    disponibilite pure.
- P6a local :
  - pending/candidates/planner targeted ->
    `./scripts/test-backend -q tests/test_core_flows.py -k 'pending or choice' tests/test_conversation_candidate_refs.py tests/test_conversation_turn_planner.py`
    -> 16 passed, 86 deselected.
  - full backend -> `./scripts/test-backend -q` -> 916 passed, 11 skipped,
    11 subtests passed.
  - smoke API reel `swim_unavailable_two_weeks` ->
    `OK (1 check(s))`; pending `plan_patch` sur session DB id 5
    `sport_type=swimming`, remplacement `new_sport_type=strength`, aucune cible
    running.
- P6b local :
  - tool runtime -> `./scripts/test-backend -q tests/test_tool_runtime.py`
    -> 24 passed.
  - memory mutation -> `./scripts/test-backend -q tests/test_memory_mutation_service.py`
    -> 6 passed.
  - coach action parse -> `./scripts/test-backend -q tests/test_coach_decision_actions.py`
    -> 16 passed.
  - prompt/action targeted ->
    `./scripts/test-backend -q tests/test_conversation_prompt_modules.py tests/test_llm_prompt_builder.py tests/test_coach_decision_actions.py`
    -> 59 passed.
  - LLM tool targeted ->
    `./scripts/test-backend -q tests/test_llm_tools.py -k 'availability or memory or compiler or tool'`
    -> 65 passed.
  - heartbeat tool loop/debug ->
    `./scripts/test-backend -q tests/test_heartbeat_tool_loop.py tests/test_heartbeat_debug_endpoint.py`
    -> 8 passed.
  - smoke API reel `swim_unavailable_two_weeks` ->
    `OK (1 check(s))`; DB confirme
    `working_memory_entries.key=unavailable_swimming_2026-05-13_2026-05-27`,
    `source=turn_plan`, `signal_kind=availability_unavailable`.
  - changements : dedup tool exact `tool_name + arguments` par tour sans
    consommer de budget; `record_availability.sport_type/scope`; cle memoire
    `unavailable_<sport>_<start>_<end>` pour indispo sport-specific datee;
    persistance de cette memoire depuis `turn_plan.availability_constraint`
    quand la candidate-flow sort avant `decide()`; normalisation des alias
    sportifs types (`natation` -> `swimming`).
- P6c local :
  - final reply grounded ->
    `./scripts/test-backend -q tests/test_final_reply_grounded_verifier.py tests/test_final_reply.py`
    -> 38 passed.
  - core availability/candidate/lookup targeted ->
    `./scripts/test-backend -q tests/test_core_flows.py -k 'availability or candidate or plan_lookup or pending or choice'`
    -> 28 passed, 60 deselected.
  - smoke harness -> `./scripts/test-backend -q tests/test_smoke_a_plus_api.py`
    -> 11 passed.
  - full backend -> `./scripts/test-backend -q` -> 924 passed, 11 skipped,
    11 subtests passed.
  - smoke API reel `swim_unavailable_two_weeks + swim_unavailable_no_session`
    ->
    `./scripts/smoke-a-plus-api --scenario swim_unavailable_two_weeks --scenario swim_unavailable_no_session --keep-db --db-path /tmp/fitmas-p6c-swim-rerun2.db --port 8117 --timeout 240 --startup-timeout 45`
    -> `OK (2 check(s))`; le premier cree une pending PlanPatch ciblee
    natation, le second rend `availability_no_affected_session` sans pending ni
    event planning et persiste
    `unavailable_swimming_2026-05-13_2026-05-14`.
  - smoke API reel `lookup_current_plan` ->
    `./scripts/smoke-a-plus-api --scenario lookup_current_plan --keep-db --db-path /tmp/fitmas-p6c-lookup.db --port 8118 --timeout 180 --startup-timeout 45`
    -> `OK (1 check(s))`, aucune mutation. La trace est sortie en
    `response_mode=reply`; le hard guard est couvert par les tests
    `compose_plan_lookup_reply` / `verify_factual_reply`, mais les reponses
    directes `reply` restent a surveiller en dogfood.
  - changements : hard guard `plan_lookup` contre `ReplyGroundingPacket` pour
    durees minutes, dates ISO, claims jour vide/repos, sport et statut; fallback
    DB compact si composer+brouillon ne sont pas reparables; scenario
    `swim_unavailable_no_session` ajoute au smoke; candidate-flow sport-specific
    stoppe sans pending quand aucune seance du sport cible n'est dans la fenetre.
- P1 replay local :
  - `./scripts/smoke-a-plus-api --daily ...` -> `FAIL (4/26)`;
  - `./scripts/smoke-a-plus-api ...` core -> stop apres deux timeouts mutation;
  - `./scripts/smoke-a-plus-api --scenario close_turn_ack --generated-workflow onboard_loaded_running ...` -> `FAIL (1/2)`;
  - logs : zero `unknown_mutation_type`, zero `truncated_fitmas_message`, zero
    `tool_budget_exceeded`; slow tool rows concentrees sur week review/tool-use.

Suite immediate :

1. Commit/push/deploy du lot P0-P6c si la revue de diff reste propre.
2. Dogfood Telegram reel sur `lookup_current_plan`, execution done/missed,
   sante resolue, dispo natation deux semaines, et no-session natation.
3. Refactor Phase A : separer les lanes stabilisees et reduire
   `conversation_pipeline.py` avant de continuer a ajouter des cas.
4. Garder Phase B fermee tant que le coach dogfood n'est pas stable plusieurs
   jours.

## Historique recent — incident 2-5 mai 2026

### Incident dogfood briefing matin du 2 mai

Le briefing du 2 mai a hallucine des chiffres factuels (`"2 sorties offplan cette semaine"` alors que zero offplan existe en DB pour la semaine en cours). Pas un bug de voix, un bug de **grounding factuel**.

Cause racine identifiee : `_recent_proactive_context()` (`backend/src/fitmas/skills/heartbeat/heartbeat.py:535-553`) reinjecte les 2 derniers messages proactifs **sans aucun TTL** — un briefing d'une semaine anterieure ressort dans le prompt actuel, et le LLM recopie ses chiffres perimes au lieu de lire le bundle Truth (qui dit `offplan_count=0`).

L'audit declenche par cet incident a confirme 3 failles structurelles connexes :

- **Voix coach fragmentee entre pipelines** : Phase 1 voix conversation a durci `_CONVERSATION_SYSTEM_TEXT` mais le briefing/reminder/weekly review gardent leurs propres regles, sans few-shots BONS/MAUVAIS, sans detecteur receipt-style. Pas de source unique de doctrine voix en code.
- **Dual-source de verite runtime** : ✅ core ferme le 3 mai. `plan_actions.py` et `mutations.py` ne mutent plus `DayPlan`; `signals.py` lit `ScheduledSession`; `activities.py` matche les activites contre `ScheduledSession`; `api_activities.py` et `strava.py` ne chargent plus le plan hebdo pour matcher ou marquer une activite.
- **Lectures `DayPlan/WeeklyPlan` restantes** : limitees au template/onboarding/admin/compat (`schema.py`, `models.py`, `repository.py`, `api_onboarding.py`, `api_read.py` fallback template de `/week`, `seed.py`, `state.py`, `api_debug.py`, `api_ops.py`).

### Acquis recents — Phase A LLM-first

- Phase 1 voix conversation : ✅ shippe 30 avril 2026 — bloc "Voix coach (regles imperatives sur fitmas_message)" + 8 few-shots BONS et 9 MAUVAIS dans `_CONVERSATION_SYSTEM_TEXT` (`backend/src/fitmas/llm_prompt_builder.py`), detecteur `_message_looks_receipt_style` log-only avec 6 patterns dans `backend/src/fitmas/llm.py`.
- Phase 2 `pending_resolution` typed + `memory_actions` + `execution_actions` : ✅ shippe 1 mai 2026 (commits anterieurs) — confirmations resolues structurellement par le LLM (`accept_pending` / `reject_pending` / `modify_pending` / `ignore`), plus de re-decision sauvage. Memory/execution actions executees par writers bornes post-validation.

### Historique des chantiers Phase A/A+

| # | Chantier | Effort | Doc canonique |
|---|---|---|---|
| 0 | ✅ Fix TTL `_recent_proactive_context` (heartbeat) — shippe 2 mai 2026 | 1h | section ci-dessous |
| 1 | ✅ Voix coach unifiee (module `coach_voice.py` partage tous pipelines) — shippe 3 mai 2026 | 1.5j | `docs/SOUL.md` section "Voix unifiee partagee" |
| 1bis | ✅ Claim guard via LLM repair (plus de canned "Je n'ai applique aucun changement...") — shippe 3 mai 2026 | 2h | section ci-dessous |
| 1ter | ✅ Capture indirecte de constraints dans le prompt conversation — shippe 3 mai 2026 | 1h | section ci-dessous |
| - | ✅ Cleanup DB prod : 395 rows obsoletes purgees, memoire propre — 3 mai 2026 | 1h | section ci-dessous |
| 1quater | ✅ Coach reliability slice 0 — final reply composer + guards backend/heartbeat + execution receipt hardening — shippe 3 mai 2026 | 1j | `docs/COACH-RELIABILITY-REFACTOR.md` |
| 2 | ✅ Truth source runtime core — `ScheduledSession` seul pour mutations/signals/activity matching — shippe 3 mai 2026 | 1j | `docs/COACH-COHERENCE-REFACTOR.md` section "Plan 2 mai 2026" |
| 3A | ✅ Conversation tool loop partiel — multi-round read/validation + `validate_plan_patch`, `PlanPatch` conserve — shippe 3 mai, deploye 4 mai 2026 | 1.5j | section ci-dessous |
| 3A-bis | ✅ Heartbeat read-only fake-action guard — LLM judge systematique `ALLOW/BLOCK` sur chaque sortie heartbeat, sans regex fake-action — 4 mai 2026 | 0.5j | section ci-dessous |
| 4 | ✅ Observabilite proactive coach loop — dump contexte, prompt, decision `send/no_send`, judge, message final — deploye 4 mai 2026 | 0.5j | section ci-dessous |
| P1 | ✅ Post-event reply verifier — verifier/reparer toute phrase finale post-mutation contre `events_committed + session_changes` — deploye 4 mai 2026 | 0.5j | section ci-dessous |
| P1-bis | ✅ PlanPatch confirmation parity — changement de sport sur seance cle repasse par confirmation, comme `MutationDecision` — deploye 4 mai 2026 | 0.5h | section ci-dessous |
| 3B-A | ✅ Tool-use loop proactive heartbeat read-only — le coach relit la verite recente avant de parler — deploye 4 mai 2026 | 0.5j | `docs/LLM-FIRST-CONVERSATION.md` section "Phase 5 - Tool-use loop unifie" |
| P1-ter | ✅ Execution receipt repair hardening — plus d'outage generique si le LLM reconnait "pas fait hier" sans `execution_actions` et qu'une cible follow-up est structuree — deploye 4 mai 2026 | 0.5j | section ci-dessous |
| P1-quater | ✅ Dogfood API fallout — execution action verifier + post-event date facts + target ambiguity + durable availability memory — deploye 4 mai 2026 | 0.5-1j | section ci-dessous |
| 3B-B | ✅ Proactive PlanPatch propose + confirmation Telegram pending, pas de commit autonome | 1j | section ci-dessous |
| A+0 | ✅ Documentation Sport Quality / Week Coherence — doctrine reviewer sportif, policy runtime, progression par stimulus | 0.5j | `docs/SPORT-QUALITY-REVIEW.md` |
| A+1-A+3 | ✅ **Phase A+ core gate** — simulation, contexte deterministe, LLM reviewer/fallback type, gate runtime dans `apply_patch_for_user`, smoke API reel `scripts/smoke-a-plus-api` | 3-4j | `docs/SPORT-QUALITY-REVIEW.md` + section "Phase A+" ci-dessous |
| 3B-C | ✅ Action-tools natifs bornes, **apres A+ core gate** — `draft_move_session`, `draft_swap_sessions`, `draft_replace_session`, `draft_lighten_day`, `draft_create_session`, candidates PlanPatch sans write | 2-3j | `docs/RUNTIME-TOOLS.md` |
| A+4/P4 | ✅ Tool `validate_week_coherence` validation-only, maintenant planning/heartbeat seulement + capture pending heartbeat reviewee | 0.5-1j | `docs/SPORT-QUALITY-REVIEW.md` |
| A+5 | ✅ Review semaine generee avant commit — guard avant `replace_plan` / `ScheduledSession`, fallback conservative si policy review non `valid`, fallback persistable sauf `blocked` | 1j | `docs/SPORT-QUALITY-REVIEW.md` |
| A+6 | ✅ Adaptation candidate pipeline — LLM propose 0-3 patch sets bornes, backend candidate refs, evaluator simule/score, reviewer LLM choisit seulement un `candidate_id` | 2-4j | `docs/ADAPTATION-CANDIDATE-PIPELINE.md` |
| P1-quinquies | ✅ Lane terminale `close_turn` — clotures sociales sans tools, sans marker question ouverte, composer final via `final_reply.py` | 0.5j | `docs/superpowers/plans/2026-05-05-terminal-close-lane.md` |
| P1-sexies | ✅ Composer final `no_change` — `CoachDecision(no_change)` + compat legacy passent par `final_reply.py`, avec faits memoire/execution appliques | 0.5j | `docs/superpowers/plans/2026-05-05-no-change-final-composer.md` |
| P1-septies | ✅ Composer final `plan_lookup` — lecture factuelle via `final_reply.py` avec guard anti-drift chiffres/jours/zones/statuts | 0.5j | `docs/superpowers/plans/2026-05-05-plan-lookup-final-composer.md` |
| P1-nonies | ✅ Grounded final speech + heartbeat future truth — temporal refs typees, grounding packet partage, verifier semantique LLM pour lookup planning/confirmation, idempotency key durable, `PlanWindowTruth` heartbeat | 0.5-1j | `docs/superpowers/plans/2026-05-07-grounded-final-speech-and-heartbeat.md` |
| P1-octies | ✅ Prompt/context optimization pass + `decide() returned None` observability — prompt diet par capability, snapshots, `get_coach_lens`, routes read-only/terminal simplifiees | 0.5-1j | `docs/PROMPT-CONTEXT-REFACTOR.md` + section ci-dessous |

**Total restant avant Phase B : dogfood, pas chantier structurel aveugle.**
Phase A/A+ est assez stable pour tester reellement. La prochaine decision doit
venir de traces et de conversations reelles, pas d'une dette theorique.

### Chantier P1-nonies — Grounded final speech + heartbeat future truth ✅

Objectif livre le 7 mai 2026 : ne plus laisser une phrase finale visible
contredire une verite planning deja connue du backend.

Fix livres :
- `conversation_turn_planner.py` peut maintenant retourner des
  `temporal_references` typees, `requires_truth_read` et `truth_scope`, que le
  backend resout ensuite sans parser le texte utilisateur libre ;
- nouveau `grounding_contract.py` : `ReplyGroundingPacket`, temporal refs
  resolues et `PlanWindowFact` partages entre conversation, final reply et
  heartbeat ;
- `plan_lookup` planning passe par un verifier semantique LLM contre le
  grounding DB, plus par un tracking deterministe de tokens/chiffres du
  brouillon LLM ;
- les confirmations `PlanPatch` recoivent local date + plan window, puis sont
  verifiees contre ces facts avant sortie ;
- acceptance de pending `PlanPatch` utilise la reply post-event verifier, pas le
  vieux `patch.coach_message` ;
- les closes sociaux recoivent un grounding et traitent le dernier message coach
  comme contexte social, pas comme source de verite planning ;
- idempotence Telegram durable : `conversation_turns.client_message_key` et
  `source` sont des colonnes, plus seulement un champ fragile de `context_json` ;
- heartbeat matin recoit `PlanWindowTruth` 7 jours et le vrai `_llm_generate`
  peut verifier la phrase proactive contre ce plan futur.

Frontiere doctrine : aucune regex/keyword sur texte utilisateur libre. La
comprehension reste LLM ; le code resout et verifie uniquement des artefacts
LLM/DB structures.

### Chantier P1-octies — Prompt/context optimization pass ✅

Livre sur `main` le 10 mai 2026.

But : donner a chaque couche LLM juste le contexte et le contrat dont elle a
besoin. Commencer par tracer les `decide() returned None`, puis introduire un
`ConversationContextPack`, un `PromptContract` par intent et des snapshots de
prompts.

Frontiere : pas de parser deterministe sur texte utilisateur libre, pas de gros
refactor memoire, pas de nouvelles regles de prompt pour masquer une cause
structurelle.

Slice 1 livre localement :
- system prompts `terminal_text` reduits pour `close_turn` et `casual_chat` :
  plus de calendrier-action, workflow replan, action contract ou examples
  mutation dans ces routes ;
- system prompts `read_only` reduits : verite factuelle compacte, no-action
  schema, pas d'exemples mutation/pending ;
- traces `truth_blocks` alignees sur le `PromptContract` de la route.

Slice 2 livre localement :
- layers rendus filtres par `PromptContract.max_context_blocks` ;
- plus de deuxieme bloc identite/profil sur les routes contractuelles ;
- terminal garde seulement temps + fil conversationnel ; plan lookup garde
  calendrier, execution recente, references temporelles et fil.

Slice 3 livre localement :
- le user prompt du builder layered ne repete plus les blocs de verite deja
  rendus en system layers ;
- la source de verite planning et le calendrier date restent dans les layers
  `immediate` / `plan`, tandis que le user prompt porte le message courant et
  les rares blocs actifs non layerises.

Slice 4 livre localement :
- routes `terminal_text` et `read_only` sur un pack voix no-action court ;
- suppression des regles de mutation/refus/confirmation dans ces prompts ;
- pack voix complet conserve pour legacy, `draft_action` et
  `write_after_validation`.

Slice 5 livre localement :
- routes `write_after_validation` sur schemas cibles ;
- `execution_report` ne recoit plus workflow replan, action contract ni
  PlanPatch ;
- `health_signal` garde un PlanPatch minimal prudent sans manuel replan.

Slice 6 livre :
- `health_signal` route vers son contrat dedie au lieu de `plan_negotiation` ;
- snapshots ajoutes pour `execution_report`, `health_signal` et
  `plan_negotiation`.

Slice 7 livre :
- `general_answer` remplace `generic_question` pour les questions hors planning
  et n'injecte plus le planning brut par defaut ;
- `get_coach_lens` donne au LLM une lentille coach compacte quand un contexte
  personnel est utile sans faire devier le tour vers une revue planning ;
- routes read-only sans mutation : pas de marker question ouverte, pas de
  `coach_context` complet, tools seulement si le contrat les autorise ;
- sortie visible sans commit/pending verifiee contre les artefacts runtime.

Slice 8 livre :
- `candidate_ref` backend pour `move_session`, `swap_sessions`, `lighten_day`,
  `replace_session` ;
- evaluator qui remplace une copie LLM equivalente par le patch backend
  canonique ;
- reviewer LLM optionnel borne a `preferred_candidate_id`, sans droit de
  produire un patch ;
- policy garde la responsabilite finale `commit | pending | pending_choice |
  block`.

Doc canonique : `docs/PROMPT-CONTEXT-REFACTOR.md`.

### Deploiement prod — 4 mai 2026

`main` est deploye sur Fly.io avec le bloc Phase A/P1-quater du 4 mai 2026.

Livres ensemble :
- Chantier 2 truth source runtime core ;
- Chantier 3A conversation tool loop partiel ;
- retry JSON court apres tool-use DeepSeek avant repair lourd ;
- idempotence Telegram/API via `client_message_key` pour eviter double traitement apres timeout ou reponse perdue ;
- heartbeat read-only fake-action guard via LLM judge `ALLOW/BLOCK`, sans regex fake-action ;
- P1-quater dogfood API fallout : coherence `execution_actions`, facts date/day post-event, confirmation cible planning ambigue, memoire disponibilite.

Verification avant deploy :
- `./scripts/test-backend -q` : 648 passed, 11 skipped, 6 subtests passed ;
- `.venv/bin/python -m compileall backend/src/fitmas` : OK ;
- `git diff --check` : OK ;
- smoke reel DeepSeek `heartbeat_non_completion` : exit 0, renfo J-1 marque `skipped`.

Dette observee dans le smoke reel : `weekly_review` pouvait encore dire "regarde ton app demain matin, j'ai ajuste le planning" alors qu'aucune mutation n'etait appliquee. Traitement 3A-bis : LLM judge `ALLOW/BLOCK` systematique sur chaque sortie heartbeat read-only.

### Chantier 0 — Fix TTL `_recent_proactive_context` ✅ shippe 2 mai 2026

Symptome : briefing du 2 mai a recopie les chiffres d'un proactif anterieur.

Cause exacte (`heartbeat.py:535-553`) : query sur `CoachMessage` sans `filter(created_at >= cutoff)`. Un briefing J-7 etait reinjecte tel quel et le LLM recopiait ses chiffres comme s'ils s'appliquaient a la semaine en cours.

Fix livre :
- TTL de **48 heures** ajoute a `_recent_proactive_context` (`backend/src/fitmas/skills/heartbeat/heartbeat.py`) ; constante exposee `RECENT_PROACTIVE_TTL_HOURS = 48`, parametrable via kwarg `ttl_hours`
- Le choix 48h couvre "hier + aujourd'hui" pour novelty avoidance (eviter de recycler la meme attaque jour apres jour) tout en excluant les chiffres > 2 jours
- Cutoff calcule en UTC naive depuis `get_local_now(user.timezone)` pour match le shape `created_at` en DB
- Nouveau test `tests/test_briefing_proactive_context.py` : 6 cas (within TTL inclus / older excluded / mixed only recent kept / boundary +1h excluded / parametrable / non-proactive ignores)
- Test existant `test_morning_briefing_includes_recent_proactive_messages_for_novelty` ajuste : utilise `hours=30` (dans 48h TTL, hors today daily cap)

Garanties verrouillees :
- aucun message proactif > 48h n'apparait dans le prompt heartbeat
- les chiffres presents dans le bundle (YesterdayTruth, TodayTruth, WeekDigest) restent l'unique source des stats hebdo
- regression test verrouille : retirer le TTL fait echouer le test

Bug isole au briefing matin (verifie : `_recent_proactive_context` est seulement utilise dans `heartbeat.py:187`, pas dans conversation/reminder/weekly review).

A faire en suivi (audit similaire) :
- recherche systematique des injections texte dans des prompts sans TTL (autres helpers `recent_*` / `pending_*` / `latest_*`)

### Chantier 1bis — Claim guard via LLM repair ✅ shippe 3 mai 2026

Symptome (3 mai dogfood Telegram) : conversation a affiche "Je n'ai applique aucun changement sur ce tour. Dis-moi explicitement ce que tu veux que je deplace, remplace ou liberes...". Receipt-style canned visible juste apres Chantier 1 voix unifiee — preuve que les regles voix dans le prompt ne suffisent pas si une template canned override la sortie LLM en aval.

Cause exacte : `claim_guard.safe_rewrite_for_claim_without_mutation()` (`backend/src/fitmas/claim_guard.py`) retournait une chaine fixe quand `looks_like_action_claim(reply)` matchait sans qu'aucune mutation soit committee. La detection (anti-mensonge "dire = faire") est saine, l'implementation viole `LLM-FIRST-CONVERSATION` ("no helper produces a final conversational reply unless it is outage").

Fix livre :
- `claim_guard.build_claim_repair_prompt(original_reply, user_text)` construit un `(system, user_prompt)` pour repair LLM
- `conversation_pipeline._llm_repair_claim_reply(...)` appelle `gw.request_text` + valide (non vide, longueur 5-500, plus de claim, pas de violation voix coach)
- `claim_guard.outage_fallback_reply()` est la ligne minimale coach-voice pour le cas LLM down ("Vu — rien de bouge sur ce tour. Tu veux que je bouge quoi concretement ?") — JAMAIS la vieille canned
- `safe_rewrite_for_claim_without_mutation` garde un alias compat qui delegue maintenant a `outage_fallback_reply`
- Pipeline tracking : `response_mode="claim_without_mutation_repaired"` ou `"claim_without_mutation_outage_fallback"`

Tests : `test_claim_without_mutation_is_repaired_via_llm` + `test_claim_without_mutation_falls_back_when_repair_fails` + `TestOutageFallback`. 583 tests verts.

### Chantier 1ter — Capture indirecte de constraints ✅ shippe 3 mai 2026

Symptome (3 mai dogfood) : user dit "la piscine c'est parce qu'elle etait en vidange" pour expliquer une nage manquee. Pas de `memory_actions=[record_availability]` emis — info perdue.

Cause : Phase 2 capability (`memory_actions`) est branchee, mais les few-shots du prompt couvrent uniquement les annonces directes ("je peux pas nager 2 semaines"). Pas les mentions indirectes / explications.

Fix livre dans `_CONVERSATION_SYSTEM_TEXT` :
- Regle generale "capture meme en passant, meme pour expliquer le passe, mieux vaut faible confidence que perdre l'info"
- 6 nouveaux few-shots couvrant : piscine vidange/fermee, explication seance manquee, voyage, douleur ongoing, preference, pattern explication via fait stable

Tests : 82 conversation/contract/voice verts.

### Cleanup DB prod ✅ 3 mai 2026

Apres dogfood Telegram, 395 rows obsoletes purgees de la prod Fly :

| Table | Avant | Apres | Supprime |
|---|---|---|---|
| `user_facts` | 104 | 34 | 70 (expires < now OR time-sensitive >14d) |
| `working_memory_entries` | 50 | 11 | 39 (>7d) |
| `conversation_turns` | 72 | 20 | 52 (>7d, legacy pre-step) |
| `coach_messages` | 299 | 67 | 232 (>14d) |
| `pending_mutation_confirmations` | 2 | 0 | 2 (status != pending) |

Espace : 1560 KB -> 804 KB (754 KB reclaim, ~50%). VACUUM execute.

Touche a zero (par doctrine) : `plan_mutation_events` (audit forward-only), `activities`, `scheduled_sessions`, `snapshots`, `strava_connections`, `day_plans`, `weekly_plans`.

Effet : la mémoire repart propre. Plus d'observations one-shot mars/avril traitees comme patterns persistants. Plus de fact "dispersion IA" qui injectait "Avec l'energie que tu mets sur l'IA" off-tone.

Cleanup principles applied :
- **Time-sensitive facts** (constraint, execution, fatigue, health, availability, pattern) : purge si > 14j OU expires_at < now
- **Identity / coaching style** (coaching, preference) : keep durables, purge uniquement si explicitement expires
- **Working memory** : > 7j (court terme par contrat)
- **Conversation turns** : > 7j (legacy)
- **Coach messages** : > 14j (history_limit prend le recent)
- **Pending confirmations** : drop tout sauf `status='pending'`

A ré-appliquer périodiquement en mode "garbage collect prod" — peut etre un cron mensuel automatise (chantier futur si dogfood le justifie).

### Chantier 1quater — Coach reliability slice 0 ✅ shippe 3 mai 2026

Symptome : le coach est inutilisable en dogfood quand il combine faits fragiles,
recadrage trop assure et templates backend visibles. La correction `claim_guard`
a retire la vieille phrase "Je n'ai applique aucun changement...", mais la meme
classe reste presente dans les blocages planning, confirmations et heartbeat
read-only qui parle comme s'il pouvait commit.

Direction : **le backend garde validation / block / commit / audit, mais ne
parle plus coach en chemin normal**.

Scope immediat :
- ✅ creer un `FinalReplyContext` mince pour les chemins bloque / confirmation ;
- ✅ composer la phrase finale par LLM a partir du resultat reel ;
- ✅ garder un fallback outage minimal si composer impossible ;
- ✅ interdire au heartbeat read-only de dire "on verrouille", "je pose",
  "c'est cale", "je deplace" sans event reel ;
- ✅ tests anti-template et anti-fake-commit ;
- ✅ hardening execution receipt : une reply LLM qui reconnait une seance manquee
  hier sans `execution_actions` est invalidee/reparee au lieu d'etre acceptee.

Verification locale :
- `./scripts/test-backend -q` : 600 passed, 11 skipped, 6 subtests passed
- `./scripts/smoke-real-conversations --scenario heartbeat_non_completion` :
  seance renfo J-1 marquee `skipped` via `execution_actions`
- `./scripts/smoke-real-conversations --scenario golden_case_autonomy` : passe

Hors scope :
- pas de write tools natifs ;
- pas de Phase B ;
- pas d'allegement massif du prompt voix avant prose finale stable.

### Chantier 2 — Truth source runtime core ✅ shippe 3 mai 2026

Objectif : fermer la dette "deux verites planning" sur les chemins runtime
qui alimentent le coach, heartbeat, activites et mutations visibles.

Fix livre :
- `plan_actions.py` mute uniquement `ScheduledSession`.
  - `complete_session` / `skip_session` ne synchronisent plus `DayPlan`.
  - `lighten_session`, `update_session_details`, `replace_session`, `swap_sessions` ne lisent plus le plan hebdo.
  - `move_session` garde l'ID de la seance deplacee et cree un placeholder repos flexible sur la date source quand la destination est libre.
- `mutations.py` ne contient plus les writes legacy `from_day/to_day` vers `DayPlan`.
  - une mutation planning doit cibler une vraie `target_session_id`.
- `signals.py` derive les signaux depuis `ScheduledSession` + activites/claims.
  - plus de `get_active_plan`, plus de `get_day_plan`, plus de `WeeklyPlan/DayPlan`.
- `activities.py` matche les activites contre les `ScheduledSession` datees.
  - `api_activities.py` et `strava.py` ne chargent plus `to_pydantic_plan`.
- `plan_mutation_service.mark_day_completed_for_user()` devient un no-op compat.
  - les completions d'activite completent la session runtime et gardent `matched_day` comme contexte d'event, sans write legacy.

Garde-fous ajoutes :
- test statique interdisant `WeeklyPlan/DayPlan` et les helpers legacy dans `plan_actions.py`, `mutations.py`, `signals.py`, `activities.py`.
- test statique interdisant `repo.get_active_plan`, `repo.to_pydantic_plan`, `week_days` et `mark_day_completed_for_user` dans `api_activities.py` / `strava.py`.
- tests comportementaux : mutation ScheduledSession sans toucher DayPlan, signal missed key sans active plan, activity matching ScheduledSession, no-op legacy day completion.

Verification locale :
- `./scripts/test-backend -q` : 608 passed, 11 skipped, 6 subtests passed
- `./scripts/smoke-real-conversations --scenario golden_case_autonomy` : passe
- `./scripts/smoke-real-conversations --scenario heartbeat_non_completion` : passe, renfo J-1 marque skipped
- `./scripts/smoke-real-conversations --scenario compound_non_completion_swap` : passe, clarification quand aucune seance vendredi n'existe

### Chantier 3A — Conversation tool loop partiel ✅ shippe 3 mai / deploye 4 mai 2026

Objectif : donner au coach plus d'agence de lecture/validation sans ouvrir les
write tools natifs.

Fix livre :
- `validate_plan_patch` expose au runtime tools conversation/planning comme
  validation-only.
- La conversation peut enchainer jusqu'a 3 rounds outilles et 6 tool calls total.
- Tous les `tool_use_id` demandes recoivent un `tool_result` ou un blocage
  `tool_budget_exceeded`.
- Le replay assistant preserve les blocs `thinking` si DeepSeek thinking est
  reactive plus tard ; aujourd'hui FitMAS garde `thinking={"type":"disabled"}`
  par defaut sur DeepSeek.
- Les `PlanPatch` appliques passent par `FinalReplyContext` post-event quand le
  composer LLM est disponible ; le resume d'event reste fallback auditable.

Hors scope :
- pas de write tool natif (`commit_plan_patch`, `move_session`, `swap_sessions`) ;
- pas de boucle tools heartbeat ;
- pas de suppression du `CoachDecision` JSON interne.

Verification locale :
- `tests/test_tool_runtime.py` : `validate_plan_patch` valid/blocked ;
- `tests/test_llm_tools.py` : second round tool-use + canonical tools ;
- `tests/test_llm_gateway_json.py` : preservation blocs `thinking` ;
- `tests/test_final_reply.py` + `tests/test_blocked_mutation_reply.py` : replies
  post-resultat.

### Chantier 3A-bis — Heartbeat read-only fake-action guard ✅ shippe 4 mai 2026

Objectif : fermer la classe vue dans le smoke reel du 4 mai :

> "Regarde ton app demain matin, j'ai ajuste le planning..."

Sans event de mutation, le heartbeat doit pouvoir :
- constater ;
- proposer ;
- demander confirmation ;
- dire qu'il faudra ajuster dans le chat.

Il ne doit pas claim :
- "j'ai ajuste" ;
- "j'ai bascule" ;
- "j'ai tout remplace" ;
- "c'est pose / cale / verrouille" ;
- "regarde ton app" quand cette phrase implique un changement deja fait.

Fix livre :
- `_llm_generate(... pipeline="heartbeat_*")` appelle un LLM judge `ALLOW/BLOCK`
  sur chaque sortie heartbeat read-only, sans regex fake-action ;
- si le judge dit `BLOCK`, echoue ou repond autre chose, le heartbeat retourne
  `None`, donc il ne part pas plutot qu'envoyer un faux commit ;
- suggestions explicites toujours autorisees : `je te propose de basculer...`,
  `si tu veux...`, `il faudra ajuster...`, `sinon on continue d'empiler...`.

Verification locale :
- `./scripts/test-backend -q` : 627 passed, 11 skipped, 6 subtests passed ;
- `.venv/bin/python -m compileall backend/src/fitmas` : OK ;
- smoke reel DeepSeek `heartbeat_non_completion` : exit 0, renfo J-1 marque
  `skipped` via `execution_actions` ;
- smoke reel DeepSeek `golden_case_autonomy` : exit 0, `weekly_review` ne claim
  plus "j'ai ajuste" sans event et propose explicitement de regarder ensemble.

Ce guard lit uniquement la sortie LLM heartbeat, jamais le texte utilisateur.
Il reste donc conforme a la doctrine : determinisme sur artefact machine, pas
sur comprehension user.

### Vision heartbeat — proactive coach loop

Le mot `heartbeat` est historique. La cible produit n'est pas un message fixe
tous les matins a la meme heure. C'est une **initiative coach bornee** :

```text
scheduler / evenement
  -> le coach se reveille
  -> lit la verite recente avec tools
  -> decide send/no_send
  -> compose un message utile ou se tait
  -> guard anti-harcelement + judge read-only
```

Sources de reveil :
- routine planifiee : briefing matin, revue semaine, pre-session ;
- evenement : nouvelle activite Strava, seance tres sous/sur-attendue,
  seance cle manquee, silence prolonge ;
- opportunite : fenetre utile pour recadrer, proteger la recup, demander une
  clarification courte.

Regles produit :
- `NO_SEND` est un resultat normal, pas un echec ;
- pas de harcelement : cooldown, cap journalier, nouveaute reelle, pas deux
  recadrages sur le meme sujet ;
- le coach ne doit pas claim une action planning sans event ;
- tant que le heartbeat est read-only, il propose ou demande confirmation.

### Chantier 4 — Observabilite proactive coach loop ✅ livre

Endpoint debug `POST /api/v0/debug/heartbeat/{kind}?dump=true` qui retourne :

- contexte lu par le heartbeat (`heartbeat_bundle`, signals, sessions,
  activites, time_context selon le kind) ;
- prompt systeme rendu ;
- prompt user rendu ;
- response LLM brute ;
- decision `send/no_send` et raison ;
- sortie du judge read-only `ALLOW/BLOCK` ;
- message final envoye ou raison de silence.

Kinds supportes : `morning`, `pre_session`, `signal_check`, `weekly_review`.
Le meme `dump=true` existe aussi sur `POST /ops/heartbeat/{kind}`.

Implementation :
- `llm_gateway.generate_heartbeat_text_with_debug()` expose `raw_text`,
  `text`, `reason`, `allow_no_send` sans changer le helper historique ;
- `heartbeat.capture_debug_trace(kind)` trace gate, contexte, prompt, LLM,
  judge et decision finale via `ContextVar` local au tour ;
- les endpoints ajoutent le bloc `debug` seulement si `dump=true`.

Permet diagnostic d'incident en 5 minutes au lieu de 2h d'audit. Active uniquement quand `FITMAS_ENABLE_DEBUG_ENDPOINTS` est set.

Tests :
- `tests/test_heartbeat_debug_endpoint.py` verrouille prompt + raw LLM +
  judge + decision finale ;
- test no-op : sans seance du jour, le dump expose `no_today_session`.
- verification 4 mai : `./scripts/test-backend -q` -> 630 passed,
  11 skipped, 6 subtests ; dump reel DeepSeek OK (`prompt`, `raw_text`,
  `judge`, `decision` presents).

Dogfood parallele 4 mai :
- P1 post-event : certaines replies post-mutation pouvaient encore contredire
  les events reels (`week_scope_constraint`, sous-performance severe).
  Correctif local : verifier / repair sur `events_committed +
  events_blocked + session_changes + final_reply`.
- P1 heartbeat read-only : fuite "on replace les deux seances..." observee
  dans un weekly review. Mitigation immediate : prompt du judge durci avec
  `events_committed: []`, exemples BLOCK, et smoke direct DeepSeek confirme
  `BLOCK` sur la phrase fautive.
- P1-bis PlanPatch : les smokes reels ont montre qu'un remplacement de seance
  cle via `PlanPatch` pouvait s'appliquer sans confirmation. Correctif local :
  pre-hook `replace_key_session_changes_sport` partage par `validate_plan_patch`.

### P1 — Post-event reply verifier ✅ livre

Bloquant avant 3B-A. Ferme localement : plus on libere le coach, plus il faut
verifier que sa phrase finale colle aux mutations effectivement appliquees.

Bug observe :

```text
events reels = mercredi et jeudi remplaces par Journee flexible
reply finale = "J'ai decale le fractionne a jeudi"
```

L'etat DB est correct, mais la voix ment sur l'etat. C'est plus dangereux qu'un
simple mauvais ton : le user croit qu'une action differente a ete commit.

Contrat implemente :

```text
events_committed + events_blocked + session_changes + final_reply
  -> verifier LLM
  -> ALLOW si la phrase colle aux events
  -> REPAIR si elle invente / inverse / ajoute une mutation
  -> fallback outage court si repair impossible
```

Exemple :

```json
{
  "events_committed": [
    {"command": "replace_session", "before": "Fractionne", "after": "Journee flexible"},
    {"command": "replace_session", "before": "Renfo", "after": "Journee flexible"}
  ],
  "final_reply": "J'ai decale le fractionne a jeudi."
}
```

Verdict attendu :

```json
{
  "verdict": "repair",
  "reason": "La reply claim un deplacement a jeudi, non present dans les events.",
  "repaired_reply": "J'ai libere mercredi et jeudi en journees flexibles. On garde de la marge cette semaine au lieu de forcer le fractionne."
}
```

Frontiere doctrine : ce verifier ne lit jamais le texte user libre. Il juge
uniquement des artefacts machine produits apres mutation : events DB, diff de
sessions, phrase sortante. Il est donc conforme a LLM-first.

Implementation :
- `final_reply.verify_post_event_reply()` demande un verdict JSON
  `allow|repair` a partir des artefacts post-mutation ;
- `_applied_plan_patch_reply()` passe la sortie du final composer dans ce
  verifier avant envoi ;
- si le verifier est invalide ou outage, fallback sur les summaries d'events
  commités, pas sur la phrase inventee ;
- `PlanAppliedMutationEvent` transporte maintenant `before_snapshot` /
  `after_snapshot` quand disponible ; le verifier recoit un diff compact en
  `extra_facts`.

Tests ajoutes :
- reply qui mentionne un jour/session/action absent des events -> repair ;
- reply qui colle aux events -> allow ;
- LLM verifier invalide/outage -> fallback summary commit sans claim inventee ;
- contexte verifier enrichi avec `before -> after` pour distinguer
  `replace_session` de `move_session`.

### P1-bis — PlanPatch confirmation parity ✅ livre

Bug observe par smoke reel DeepSeek : `Tu peux remplacer ma seance cle par une
natation ?` pouvait produire un `PlanPatch.replace_session` applique directement.
La route legacy `MutationDecision` passait bien par `assess_mutation_impact`,
mais `PlanPatch` s'appuyait sur les pre-hooks et ne signalait pas encore ce cas.

Fix :
- pre-hook `replace_key_session_changes_sport` quand `replace_session` change
  le sport d'une seance cle ;
- `validate_plan_patch` transforme ce warning en `requires_confirmation` ;
- suggested fix explicite : demander confirmation avant de changer le sport
  d'une seance cle.

Test : `test_plan_patch_validation_requires_confirmation_when_replacing_key_session_sport`.

### Chantier 3B-A — Heartbeat read-tools read-only ✅ livre

Objectif : le heartbeat n'est plus un one-shot texte uniquement. Avant de
parler, il peut demander des read-tools pour relire la verite recente :

- `get_plan_window`
- `get_recent_activities`
- `get_activity_highlights`
- `get_recent_reality_window`
- `get_load_context`
- `get_user_constraints`
- `get_relevant_facts`

Frontiere :
- aucun write tool ;
- pas de `validate_plan_patch`, `suggest_replan_candidates` ou
  `propose_replan` dans le pipeline heartbeat ;
- le guard read-only `ALLOW/BLOCK` reste en aval de la phrase finale ;
- `NO_SEND` reste un resultat sain.

Implementation :
- module dedie `skills/heartbeat/tool_loop.py` ;
- max 2 rounds tools, max 4 tool calls ;
- `HeartbeatDebugTrace.tools` expose offered/requested/results dans
  `dump=true` ;
- tous les roles heartbeat (`morning`, `pre_session`, `weekly_review`,
  `signal_check`) construisent un `ToolContext(pipeline="heartbeat")`.

Tests :
- registry heartbeat expose seulement les read-tools utiles ;
- boucle `tool_use -> tool_result -> prose finale` ;
- debug endpoint expose la surface tools ;
- tests heartbeat existants conserves.

### Chantier 3B-B — Heartbeat PlanPatch + confirmation ✅ livre

Objectif : le heartbeat peut proposer un vrai ajustement planning sans jamais
committer tout seul.

Implementation :
- pipeline `heartbeat` expose maintenant `suggest_replan_candidates` et
  `validate_plan_patch` en plus des read-tools ;
- si le LLM heartbeat appelle `validate_plan_patch` et obtient
  `valid|warning|requires_confirmation`, le draft transporte une
  `DraftPendingConfirmation(plan_patch)` ;
- `persist_draft()` cree la `PendingMutationConfirmation` seulement apres
  livraison/persistance du message proactif, ce qui evite les ghost pending si
  Telegram echoue ;
- `signal_check()` convertit les anciennes candidates `MutationDecision`
  proactives (`tsb_alert`, missed cascade) en `PlanPatch`, valide, puis demande
  confirmation au lieu d'envoyer une simple suggestion non actionnable ;
- aucune ligne ne cree de `plan_mutation_event` avant acceptation explicite du
  pending par conversation.

Frontiere :
- pas de write tool natif ;
- pas de commit autonome heartbeat ;
- acceptation toujours traitee par le pipeline conversation existant
  `pending_resolution -> apply_patch_for_user`, avec revalidation avant commit.

Verification locale :
- `tests/test_heartbeat_tool_loop.py` : capture d'un `validate_plan_patch`
  heartbeat en pending candidate ;
- `tests/test_heartbeat_grounding.py` : `signal_check` cree une pending apres
  `persist_draft`, sans event mutation ;
- suite proche heartbeat/tools/core/plan patch : 123 passed.

### P1-ter — Execution receipt repair hardening ✅ livre

Smoke reel du 4 mai apres 3B-A :

```bash
FITMAS_USE_DEEPSEEK_OPENAI_STRUCTURED=1 ./scripts/smoke-real-conversations --scenario heartbeat_non_completion
```

Symptome traite : DeepSeek/Claude pouvaient produire une reply qui reconnait
implicitement "pas fait hier" sans `execution_actions`. Le guard
`execution_receipt_without_action` invalidait correctement cette sortie, mais le
repair/fallback pouvait encore finir en outage user-facing au lieu de reconstruire
un `record_execution_update`.

Fix livre :
- la pipeline transmet maintenant au LLM la cible follow-up sous forme structuree
  (`unresolved_execution_followup_session_id`, target date) en plus du bloc texte ;
- si le payload LLM invalide dit lui-meme que la seance d'hier est manquee et
  qu'une cible follow-up structuree existe, `llm.py` reconstruit un
  `CoachDecision(no_change)` avec `execution_actions=[record_execution_update]` ;
- extension P1-quater : si une CoachDecision **valide** parle d'une execution
  d'hier mais oublie `execution_actions`, `llm.py` relance un repair LLM; sans
  session id certain, le repair peut utiliser `target_ref="seance d'hier"` et
  le writer resout ensuite contre la DB ;
- extension 5 mai : le meme repair se declenche aussi si l'artefact LLM dit
  explicitement qu'une seance/renfo/footing/etc. n'a pas ete fait, meme sans
  employer le mot "hier" (`renfo de mercredi id=... non realise`) ;
- extension 5 mai bis : le repair semantique couvre aussi le payload **invalide**
  qui reconnait "pas fait hier" sans `unresolved_execution_followup_session_id` :
  il emet seulement `target_ref="seance d'hier"` et laisse le writer resoudre
  une cible DB unique ;
- ce repair ne lit jamais le texte utilisateur libre : il se base uniquement sur
  l'artefact LLM invalide/valide + la cible DB deja identifiee par le contexte systeme ;
- si aucun session id certain n'existe, le repair peut seulement emettre une
  reference naturelle bornee (`target_ref="seance d'hier"`), que le writer doit
  resoudre contre la DB ; sans resolution unique, pas d'action synthetisee.

Frontiere doctrine :
- ne pas parser le texte user ;
- reparer uniquement la sortie LLM structuree / rationale / reply fautive ;
- si la cible DB est unique dans le contexte, repair en `execution_actions` ;
- sinon clarification courte, pas outage generique.

Verification :
- test rouge/passe sur repair apres echec du JSON repair ;
- test rouge/passe sur artefact LLM non-completion sans mot "hier" ;
- test pipeline sur propagation de la cible follow-up structuree ;
- smoke reel DeepSeek `heartbeat_non_completion` : exit 0, renfo J-1 marque
  `skipped`, reply conversationnelle.

Ce P1 est distinct de 3B-A : il touche la conversation reactive, pas le
heartbeat read-tools. Il ferme la base execution avant 3B-B.

### P1-quater — Dogfood API fallout ✅ deploye 4 mai 2026

Tests reels API/DeepSeek du 4 mai (agent de test read-only) apres 3B-A/P1-ter.
`heartbeat_non_completion` etait deja corrige cote agent principal, mais quatre
risques restaient a fermer avant 3B-B.

Fix livre :
- **Execution completion incoherente** : `llm.py` verifie/repare les
  `execution_actions` quand la reply/rationale contredit le statut structure
  (`completed` vs `not_completed`), via LLM repair sur CoachDecision.
- **Reply post-mutation date/day fausse** : les facts du post-event verifier
  incluent maintenant `YYYY-MM-DD (jour)` dans les snapshots before/after.
- **Cible planning ambigue trop vite mutee** : `validate_plan_patch` force
  `requires_confirmation` si une operation `move_session`/`swap_sessions`
  cible une seance d'un sport qui a plusieurs candidats actifs et que la source
  n'est pas disambiguisee (`from_day` absent).
- **Contrainte piscine pas toujours durable** : sur intent LLM
  `availability_constraint`, `llm.py` peut reparer une CoachDecision sans
  `record_availability` en ajoutant une `memory_actions.record_availability`.

Frontiere : ne pas corriger par regex sur texte utilisateur. Les fixes doivent
passer par artefacts LLM, results tools, validation DB, verifiers LLM ou
prompts/evals.

Verification locale :
- tests rouges/passes : `test_decide_repairs_valid_yesterday_execution_reply_without_followup_id`,
  `test_decide_repairs_execution_action_status_contradicting_reply`,
  `test_decide_repairs_missing_availability_memory_for_availability_intent`,
  `test_plan_patch_validation_requires_confirmation_for_ambiguous_same_sport_move_target`,
  `test_plan_patch_applied_verifier_context_includes_calendar_day_label`.
- suite proche : `tests/test_llm_tools.py tests/test_plan_patch.py
  tests/test_blocked_mutation_reply.py tests/test_core_flows.py` -> 142 passed.
- smoke reel DeepSeek `heartbeat_non_completion` : exit 0, renfo J-1 marque
  `skipped`.

### Ordre propose

1. ~~**Chantier 0-3A-bis**~~ ✅ shippe/deploye 2-4 mai 2026.
2. ~~**Chantier 4**~~ ✅ observabilite proactive coach loop.
3. ~~**P1 post-event reply verifier + P1-bis PlanPatch confirmation parity**~~ ✅ livre.
4. ~~**Chantier 3B-A**~~ ✅ heartbeat tool-use read-only.
5. ~~**P1-ter execution receipt repair hardening**~~ ✅ smoke
   `heartbeat_non_completion` ferme.
6. ~~**P1-quater dogfood API fallout**~~ ✅ incoherences test reel fermees.
7. ~~**Chantier 3B-B**~~ ✅ PlanPatch propose + confirmation Telegram, sans
   commit autonome.
8. **Maintenant : dogfood court 3B-B** — verifier pending heartbeat PlanPatch,
   sans commit autonome.
9. ~~**Phase A+ core gate (A+1-A+3)**~~ ✅ livre —
   simulation, reviewer LLM/fallback type, gate runtime. Objectif : aucun
   `PlanPatch` significatif ne commit sans review sportive.
10. ~~**Smoke API reel A+**~~ ✅ `./scripts/smoke-a-plus-api` — serveur HTTP
   local + vrai provider + DB temporaire ; verrouille les regressions
   `move_hard_close` et `replace_key_running_swim_easy`.
11. ~~**Chantier 3B-C**~~ ✅ action-tools natifs bornes, conversation/planning
   only, candidates PlanPatch sans write. Commit toujours derriere
   `validate_plan_patch -> WeekCoherenceReviewer -> policy -> writer`.
12. ~~**A+4/P4**~~ ✅ tool `validate_week_coherence` validation-only,
   planning/heartbeat seulement depuis P4, pending heartbeat possible seulement
   apres review sportive confirmable.
13. ~~**A+5**~~ ✅ semaine generee relue avant commit, fallback conservative si
   policy review non `valid`.
14. **Maintenant : dogfood court Phase A+** — verifier conversation, heartbeat,
   onboarding/regenerate et app sur donnees reelles.
15. **Apres seulement : B0/B1/B2** — prescription structuree, session quality,
   performance signals et calibration.

### Phase A — etat apres chantiers 0+1+2

Apres ces 3 chantiers, Phase A est *vraiment* fermee :

- doctrine LLM-first runtime ✅ (deja fait)
- voix coach uniforme tous pipelines ✅ (chantier 1)
- verite runtime unique ✅ (chantier 2 ferme la dette truth source)
- aucune classe de bug "hallucination factuelle" residuelle

A ce moment-la, la priorite change : ouvrir A+ core avant 3B-C. La raison est simple : ne pas donner plus d'autonomie d'action au coach avant que la gate sportive soit en place. Phase B reste differee.

### Phase A+ — Sport Quality / Week Coherence Review

Doc canonique : `docs/SPORT-QUALITY-REVIEW.md`.

Concept inspire d'un brainstorm strategique du 2 mai 2026, puis recadre le 5 mai 2026 : pas un second coach, pas Phase B prescription complete, mais une **couche de review sportive** entre `PlanPatch` et commit.

**Probleme adressé** : aujourd'hui le coach est bon en *reaction locale* (constraint -> mutation locale -> validate -> commit). Il ne raisonne pas au niveau *semaine entiere*. Il sait swap mardi/jeudi, il ne sait pas dire "ce swap surcharge ta fin de semaine, je propose plutot X".

**Exemple produit** :

| Niveau | User says | Coach reaction |
|---|---|---|
| Aujourd'hui (Phase A) | "Je ne peux pas courir mercredi" | move Wed -> Thu, commit |
| Phase A+ | "Je ne peux pas courir mercredi" | "Move Wed->Thu cree trop d'intensite fin de semaine. Je preserve samedi key, convertis jeudi en easy, drop le support optionnel." |

C'est de la **qualite de decision week-level**, distinct de la fiabilite (Phase A) et de la prescription intra-seance (Phase B).

Doctrine :

```text
Le coach propose.
Le reviewer sportif challenge.
La policy backend tranche.
Le writer applique.
Le coach explique.
```

Frontiere d'autorite :

```text
Reviewer = autorite sportive.
Runtime = autorite systeme.
PlanMutationService = effet DB.
Coach = relation + explication.
```

Le reviewer n'est pas juste un critique. Il rend un verdict et une policy recommandee (`commit_original`, `confirm_original`, `block_original`, puis V2 `retry_with_revised_patch` / `confirm_revised`). Mais il ne parle pas au user, ne write pas, ne commit rien et ne supprime jamais un hard block deterministe.

**Triggers Phase A+** : appel quasi systematique sur tout `PlanPatch` sportivement significatif :
- `move_session`, `swap_sessions`, `replace_session`, `lighten_day`, `create_session`
- patch multi-operations ou heartbeat proactif
- changement sport / duree / intensite
- seance key / support / recovery touchee
- fatigue / douleur / maladie / contrainte active
- validation runtime `warning` ou `requires_confirmation`

Skip acceptable seulement pour execution pure (`done` / `skipped`), lookup, memoire, clarification, ou accept/reject pending deja reviewe si patch inchange et review version actuelle.

**Capacites cibles a livrer** :

| Tool | Role |
|---|---|
| `get_session_detail(session_id)` | inspecter une seance en profondeur (titre, objectif, type, intensite, priority, completion) — manque aujourd'hui |
| `resolve_target_session(query)` | resoudre une ref floue ("la sortie longue", "le fractionne") en `session_id` ou candidates |
| `get_planning_contract()` | lire week_mission, key_sessions, protected_sessions, change_budget |
| `validate_week_coherence(patch)` | "si on applique ce patch, la semaine fait-elle encore sens ?" — distinct de `validate_plan_patch` (legalite) ; couvre `too_many_hard_sessions`, `recovery_gap_too_short`, `key_session_lost`, `weekly_load_too_high`, `mission_not_preserved`, etc. |

**Contrats / modules cibles** :
- `backend/src/fitmas/week_coherence.py` : `simulate_plan_patch`, `build_week_coherence_context`, `evaluate_week_invariants`, `review_week_coherence_with_llm`, `aggregate_week_coherence_policy`
- `WeekCoherenceReview` : status, sport_quality, confidence, findings, `recommended_policy`, optional `revised_patch`
- `PlanPatchServiceResult` porte la week gate pour pending/replies
- pending confirmation stocke patch hash + review status + recommended policy + review version

**Skill enrichie** :
- `replan_after_constraint` recoit le branchement Phase A+ : pour tout patch significatif, le LLM peut appeler `validate_week_coherence` avant sa decision finale
- le backend re-run toujours `validate_plan_patch` + `WeekCoherenceReviewer` avant commit

**Effort A+ core : 3-4 jours**. **Effort A+ hardening : 1.5-2 jours**.

**Dependances** :
- Chantier 3A/3B-A/3B-B donnent assez de boucle tool-use pour livrer A+ core maintenant
- Chantier 3B-C doit attendre A+ core : plus d'action-tools sans reviewer sportif augmente trop le risque de patchs techniquement valides mais mauvais
- Chantier 2 (truth source unifie) est **prerequis** pour `get_planning_contract` et `validate_week_coherence` — sans ScheduledSession seul truth, le scoring week donne des resultats incoherents

**Differentiateur produit** : Phase A+ est ce qui transforme FitMAS d'un "outil qui swap" en "coach qui sauve la semaine". C'est probablement le wedge produit le plus important a moyen terme. Pas urgent, mais dimensionnant.

Ordre detaille :
1. 3B-B dogfood court : confirmer que les pending heartbeat PlanPatch sont propres
2. A+0 docs + contrats (`SPORT-QUALITY-REVIEW.md`) — fait localement
3. A+1 simulation / context / checks deterministes — livre
4. A+2 LLM `WeekCoherenceReviewer` / fallback type — livre
5. A+3 gate runtime dans `apply_patch_for_user` — livre
6. 3B-C action-tools natifs bornes, maintenant proteges par la gate
7. A+4 tool validation-only `validate_week_coherence`
8. A+5 review semaine generee
9. B0 `SessionPrescriptionEngine`
10. B1 `SessionQualityReviewer`
11. B2 `PerformanceSignalService` + `CalibrationProposal`

Decoupage mental :
- **MVP** : A+1 -> A+3. Le coach ne commit plus de patch significatif sans reviewer.
- **Hardening** : 3B-C -> A+5. Plus d'autonomie, mais toujours sous gate.
- **Scale sportif** : B0 -> B2. Prescription, seance, progression, calibration.

## Historique — 30 avril 2026

La suite de Phase A est recadree par l'incident heartbeat / conversation du 30 avril :

> Aucun texte utilisateur libre ne passe par regex, keyword, classifieur
> deterministe, parser maison ou short-circuit avant le coach LLM.

Doc canonique : `docs/LLM-FIRST-CONVERSATION.md`.

Le tunnel DeepSeek / tools / `PlanPatch` a livre le socle attendu pour un agent de planning fiable :

- DeepSeek est le provider principal configure, avec fallback Claude possible si le schema final casse
- le chemin OpenAI-compatible DeepSeek pour structured output est le defaut quand `DEEPSEEK_API_KEY` existe ; `FITMAS_USE_DEEPSEEK_OPENAI_STRUCTURED=0` permet de le desactiver temporairement
- le runtime tools accepte maintenant plusieurs `tool_use` dans un meme tour et renvoie un `tool_result` pour chaque id demande
- `CoachDecision` est le nouveau contrat de decision, avec fallback legacy `MutationDecision`
- `CoachDecision` porte maintenant `memory_actions`, `execution_actions` et `pending_resolution` ; les actions memoire/execution sont executees par writers bornes post-validation, et `pending_resolution` accepte/refuse les pending sans parser `oui/non`
- le parsing `CoachDecision` tolere maintenant les petites derives de schema LLM sur les artefacts structures (`confidence="high"`, `completed="false"`, `operation_type=record_execution_update`) sans relire le texte utilisateur ; les actions inconnues restent refusees
- `PlanPatch -> validate_plan_patch -> PlanMutationService.apply_patch_for_user` est branche cote conversation
- les confirmations pending serialisent maintenant le `PlanPatch` complet ; la resolution deterministe `oui/non` a ete retiree du runtime et remplacee par `CoachDecision.pending_resolution`
- le briefing matin a maintenant un catch-up borne jusqu'a 10h locale si le creneau jitter est rate et qu'aucun proactif n'a deja ete envoye
- `suggest_replan_candidates` est le tool principal de candidate replan ; `propose_replan` reste alias compat, non route par defaut
- le prompt formalise le workflow `replan_after_constraint` : tools atomiques -> candidate optionnelle -> `PlanPatch | no_change | requires_confirmation`
- Phase 0 LLM-first est passee sur le chemin conversation : plus de `low_signal`, `rich_signal`, `heuristic OR LLM`, pending `oui/non`, `_sanitize_no_change_reply`, extracteurs claim/non-completion ou fallback regex `user_indications.py` dans le runtime conversation
- Phase 3 a retire le pre-step `UserIndication` du runtime conversation :
  `conversation_pipeline.py` ne l'appelle plus, ne persiste plus de facts depuis
  cet objet et ne declenche plus `maybe_replan_from_user_indication`
- Cleanup repo du 1 mai 2026 : `user_indication_llm.py`,
  `user_indications.py`, `replan_from_life_change.py`, le wrapper
  `tool_routing.py` et leurs tests historiques ont ete supprimes. Le fichier
  `tools/routing.py` ne contient plus de classifieur texte; il garde seulement
  l'enum `IntentCategory`.

Ce que ca change produit :

- le coach peut enfin proposer une action structuree sans que le code lui mette une phrase deterministe dans la bouche
- l'orchestrateur reste proprietaire du commit, des events et des confirmations
- le coach LLM est le seul detecteur d'intention, de negation, de confirmation, de sante, de disponibilite, d'execution et de preference
- le determinisme intervient apres la decision LLM : schema, permissions, validation, commit, audit, dedup, integrite

Suite prioritaire :

1. Rejouer les smokes reels : `golden_case_autonomy`, `piscine fermee`, continuations courtes (`oui`, `running`, `mercredi`) et contraintes simples type `demain soir`.
2. Durcir `validate_plan_patch` : atomicite batch, suggested fixes, charge/recup/sante plus fines.
3. Dogfood reel Telegram sur la semaine, en classant chaque echec : trust blocker, bug Phase A, besoin Phase A+, besoin Phase B, polish.

Smoke reel DeepSeek du 1 mai 2026 :

- ✅ `heartbeat_non_completion` : heartbeat demande "renfo 34min faite ou pas ?", user repond "J'ai pas eu le temps hier...", `execution_actions` applique `skipped` sur la seance d'hier et la reply reste conversationnelle.

### Phase B en reflexion — refonte planning / progression

Discussion en cours (27 avril 2026) sur une refonte de la planification : passer de "planner hebdo deterministe + texte LLM" a "moteur de progression + LLM coach contextualisant". Pas encore de chantier ouvert. A garder en tete pendant la fin de Phase A pour ne pas creer de dette refactor evitable.

Idee centrale (a confirmer par dogfood Phase A + design pose) :

- separer `placement` (deja deterministe), `prescription` (blocs exacts, zones, cut rule) et `rendering` (LLM explique)
- introduire un `ProgressionArc` par type de seance (ex: `running_intervals_400m`) qui memorise l'axe de progression (`current_reps`, `last_completion`, `next_target`) et applique une regle bornee
- introduire une table `SessionExecution` (planned vs actual + completion ratio + subjective) que le ProgressionEngine consomme
- LLM ne **decide** jamais le contenu des blocs ; il peut **proposer** une variante quand l'espace est riche (strength, climbing) sous validation deterministe
- session_description en DB devient le **rendu** d'une prescription structuree, pas la verite

Pourquoi c'est coherent avec Phase A :

- `PlanPatch`, `validate_plan_patch`, `PlanMutationService`, `plan_mutation_events`, multi-tool runtime, tools read-only, posture coach, claim_guard, memoire contraintes : tout survit. Phase A construit le **commit pipeline**, Phase B construit le **content engine**. Axes orthogonaux.
- Phase A est un prerequis : sans le commit pipeline durci, ajouter une couche progression sur un commit fragile ne tient pas.

Discipline pour finir Phase A sans dette envers Phase B :

- **`suggest_replan_candidates`** : interface = `(slot, sport_type, session_type, intensity_hint, reason)` seulement, **pas** de blocks/zones/duration figee. Le contenu se compose downstream (templates aujourd'hui, ProgressionArc demain).
- **`replan_after_constraint` skill** : prescrire l'ordre des tools, **pas** de few-shots content-aware ("si jeudi nage tombe alors easy run") qui encodent du metier qui vivra dans les arcs.
- **`validate_plan_patch` hardening** : charge / sante / recup / atomicite / suggested fixes oui ; regles intra-seance (`8x400 trop lourd`, `tempo trop long`) **non** — elles vivront dans le ProgressionEngine.
- **`session_templates.py`** : freeze, pas d'ajout. Module sur la sellette pour Phase B.
- **`propose_replan` actuel** : garder l'implementation derriere la nouvelle interface jusqu'a Phase B, pas de reecriture maintenant.
- **Capture exécution dogfood** : verifier que ce qu'on logge (`ExecutionEvidence`, `RecentRealityWindow`) est un sur-ensemble de ce que `SessionExecution` exigera (planned vs actual prescription, completion_ratio, subjective). Si gap (ex: pas de subjective structure), noter pour Phase B sans bloquer Phase A.

Regle d'or :

> Si la decision depend du contenu intra-seance (reps, blocks, zones), c'est Phase B. Tout le reste est Phase A.

Phase B ne s'ouvre qu'apres :

- dogfood Phase A confirme que le pipeline coach autonomy tient
- `suggest_replan_candidates`, `replan_after_constraint`, `validate_plan_patch` durci sont livres
- design Phase B est ecrit dans un doc dedie (probable `docs/PROGRESSION.md` ou section dans `PLANNING.md`)

Etat Phase A 28 avril :

- ✅ `suggest_replan_candidates` livre comme surface canonique, `propose_replan` garde la compat
- ✅ `replan_after_constraint` formalise dans le prompt comme workflow, pas comme write tool
- ✅ heartbeat matin plus fiable pour dogfood grace au catch-up et aux logs de skip
- ⏳ reste : validation patch plus riche + smoke reel dedie avant de basculer en dogfood semaine complete

Smoke reel 26 avril (`FITMAS_USE_DEEPSEEK_OPENAI_STRUCTURED=1 ./scripts/smoke-real-conversations --scenario golden_case_autonomy --scenario today_unavailability`) :

- ✅ pas de crash API
- ✅ DeepSeek tape bien l'API et demande plusieurs tools coherents
- ✅ le dernier tour `Mercredi` produit un `CoachDecision(plan_patch)` puis un event reel : creation d'un footing easy mercredi 22 avril
- ✅ pas de 400 tool-use
- ⚠️ sorties non-JSON apres tools encore observees ; repair/fallback rattrape, mais la stabilite JSON reste a blinder
- ⚠️ le milieu du golden case reste trop defensif/passif (`Oui`, `Running`) ; prochaine tranche = skill `replan_after_constraint` + reclassification `propose_replan`
- ⚠️ classification memoire bruitée observee (`Running` -> health general running) ; a traiter comme signal de dogfood, pas comme blocker deploy

## Historique du refactor — 20 avril 2026

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

### Chantier 1bis du refactor — fait

Anti-mensonge "dire = faire", livré le 20 avril 2026 :
- Nouveau module `backend/src/fitmas/claim_guard.py` : détection 1ère personne présent de 12 verbes mutationnels (`libere`, `deplace`, `remplace`, `supprime`, `decale`, `bascule`, `echange`, `retire`, `annule`, `ajoute`, `swap`, `swappe`), exclut négations (`ne`, `n'`) et marqueurs de proposition (`je propose`, `je peux`, `je pourrais`, `veux-tu`, `tu confirmes`, `ok pour`, etc.)
- Garde sortie pipeline (`conversation_pipeline.py`) : si `looks_like_action_claim(reply)` ET aucune mutation committee ce tour → réécriture en demande de clarification + log `conversation_pipeline.claim_without_mutation` + `response_mode="claim_without_mutation_blocked"`
- Couvre le cas hybride `_build_user_message` de `replan_from_life_change.py:474-507` au runtime : si la mutation downstream est appliquée, la phrase reste ; sinon elle est rewrite avant envoi Telegram/app
- 440 tests passent (25 nouveaux : 23 unit tests sur claim_guard + 2 integration tests pipeline)

### Chantier 2 du refactor — fait

Tools de lecture brute pour le coach LLM, livré le 20 avril 2026. Scope recalibré : 3 des 4 tools du plan existaient déjà, le vrai gap était `get_user_constraints` (manquant) et l'enrichissement ATL/CTL/TSB de `get_load_context`.
- ✅ `get_user_constraints` créé (`backend/src/fitmas/tools/registry.py`) : filtre `active_facts` par catégories (availability/schedule/constraint/health/fatigue), exclut inactifs et expirés via `fact_is_current`, retourne payload structuré JSON-strict
- ✅ `get_load_context` enrichi avec `ctl`/`atl`/`tsb` + label `frais`/`neutre`/`fatigue` via `compute_ctl_atl_tsb` (TSS estimé à la volée si absent)
- ✅ Historique : les routing budgets par intent ont ete poses ici, puis supersedes le 30 avril par Phase 2 LLM-first. `llm.decide()` offre maintenant un budget conversationnel canonique stable et laisse le LLM choisir les read-tools.
- ✅ Tests : 3 nouveaux unit tests + tests routing/llm_tools mis à jour. 443 tests passent
- ⏳ Hors scope chantier 2 : que l'extracteur d'indications pose un `expires_at` cohérent avec la durée annoncée ("2 semaines", "demain", "ce mois") — couvert par chantier 4

### Chantier 2bis du refactor — fait

Heartbeat utilise les mêmes capacités que la conversation pour la lecture de la semaine, livré le 21 avril 2026 :
- ✅ `weekly_review()` (`backend/src/fitmas/skills/heartbeat/heartbeat.py`) construit `recent_reality` via `build_recent_reality_window` puis les faits deterministes `build_coach_reading_facts(..., lens=None)` — pas de pre-pass LLM heartbeat — avec degradation gracieuse en log warning si l'un echoue
- ✅ `build_review_prompt()` (`backend/src/fitmas/skills/heartbeat/roles.py`) accepte `digest: CoachReadingDigest | None` et l'injecte via `render_digest_for_prompt(digest)` après les compteurs agrégés (qui restent pour compat des tests existants)
- ✅ Anti-hallu rule miroir du briefing matin ajoutée dans le system prompt review : "N'invente jamais un comptage hebdomadaire et ne dis pas 'zero <sport>' si une sortie de ce sport apparait dans le bloc, meme hors plan"
- ✅ Le digest expose déjà `real_entries` détaillés (`RealEntry` avec `linked_to_plan`) — `render_digest_for_prompt` produit `swimming 45' jeu (offplan)` lisible par le LLM
- ✅ Tests : nouveau `test_weekly_review_surfaces_offplan_swimming_entry` qui ajoute une nage offplan et vérifie que le prompt contient "Lecture de la semaine", "swimming", "(offplan)" + system prompt contient l'anti-hallu rule. 444 tests passent
- ⏳ Hors scope 2bis historique : faire passer weekly_review et morning_briefing par des bundles de contexte explicites ou tools read-only bornes. Ne pas recreer `route_tools_for_query` depuis texte user.

### Chantier 3 du refactor — fait

Audit + rewrite system prompts pour la posture coach "DÉCIDE et défends", livré le 21 avril 2026 :
- ✅ Audit : la pathologie est moins lexicale qu'architecturale. Les prompts contiennent peu de "propose deux options" mais aucune posture explicite "tu décides, tu défends" et aucun marker de continuation de fil
- ✅ Bloc **"Posture coach (non-negociable)"** ajouté à `_CONVERSATION_SYSTEM_TEXT` : "Tu DECIDES. Tu defends ton choix. Tu ne renvoies pas la balle au user pour un arbitrage que tu peux trancher avec le contexte fourni." + "Tu n'ouvres pas par 'Tu veux que je...', 'Tu preferes A ou B ?'." + "Imprevu n'est pas une demande de menu, c'est un signal a creuser." + clause continuation de fil
- ✅ Helper déterministe `detect_open_question(coach_text)` (`backend/src/fitmas/llm_prompt_builder.py`) : retourne la dernière phrase interrogative significative ; ignore les confirmations (`ok ?`, `tu confirmes ?`, `ca te va ?`...)
- ✅ Marker injecté dans le user prompt des deux builders conversation (classique + layered) : `Question ouverte du tour precedent (a toi, pas au user) : "..."` + consigne "ne change pas de sujet en silence"
- ✅ Marker équivalent côté heartbeat morning_briefing : `_pending_open_question_for_user(db, user)` détecte la question en attente seulement si le user n'a rien écrit depuis ; injecté via `pending_open_question` à `build_briefing_prompt`
- ✅ Tests : 12 nouveaux (1 posture + 5 détection + 4 injection prompt + 2 heartbeat). **456 tests passent**.
- ⏳ Hors scope 3 : court-circuit `clarification` du pipeline — repris immédiatement en Chantier 3bis (voir ci-dessous, dogfood ayant remonté la boucle "Tu l'as faite ou pas ?" sur séance manquée)

### Chantier 3bis du refactor — fait

Court-circuit `clarification` du pipeline converti en contexte soft pour `decide()`, livré le 21 avril 2026 :
- ✅ Symptôme dogfood : sur séance manquée, le canned `"Tu l'as faite ou pas ?"` court-circuitait `decide()` et bouclait — coach perçu comme "disque rayé"
- ✅ Helper `render_unresolved_execution_followup(clarification, *, target_date_iso)` (`backend/src/fitmas/execution_clarification.py`) : produit un bloc soft "Suivi execution non resolu (a toi de juger : creuser, integrer ou ignorer ce tour)" avec id session, question candidate, raison d'impact et consigne anti-répétition
- ✅ Param `unresolved_execution_followup` ajouté aux deux builders (`build_conversation_prompt_bundle` + `build_layered_conversation_prompt`), injecté dans le user prompt aux côtés du marker open-question (`llm_prompt_builder.py`)
- ✅ `llm.py` lit `coach_context["unresolved_execution_followup"]` et le passe au builder layered
- ✅ `conversation_pipeline.py:375-399` : suppression du `_reply_and_record_turn(reply_text=clarification.question)` ; le bloc est désormais attaché à `coach_context` pour `decide()`. Le garde déterministe `looks_like_execution_clarification_prompt(previous_agent_text)` (déjà dans `_targeted_execution_clarification`) casse la boucle au tour suivant
- ✅ Tests pipeline (`test_core_flows.py`) refactorisés : `..._surfaces_targeted_clarification_as_prompt_context_to_llm`, `..._does_not_block_fatigue_adaptation_anymore`, `..._followup_breaks_loop_after_first_turn`, `..._resolves_clarification_via_decide`, `..._after_clarification_is_ingested_normally`
- ✅ Tests prompt (`test_llm_prompt_builder.py`) : `UnresolvedExecutionFollowupInjectionTest` (classique/layered/None). **460 tests passent**.

### Chantier 4 du refactor — fait

Mémoire des contraintes temporelles avec `expires_at` ancré sur la fin de fenêtre, livré le 21 avril 2026 :
- ✅ Symptôme dogfood (screenshot Telegram) : après "imprevu, piscine fermee 2 semaines", le coach continuait de reposer "tu l'as faite ou pas ?" sur la natation couverte par la contrainte, et au tour suivant il ne se souvenait plus de la fenêtre. Zéro persistence des contraintes multi-jours.
- ✅ Historique : `IndicationTimeReference.window_end_date` avait servi a ancrer les contraintes multi-jours. Ce chemin est maintenant remplace par `CoachDecision.memory_actions`.
- ✅ Parser durée (`_extract_constraint_duration_days`) : "2 semaines", "15 jours", "une/la semaine". Branché dans `_fallback_availability_indication` → `window_end = resolved_date + (duration - 1)`, scope upgradé à WEEK.
- ✅ Builder `build_availability_fact_payloads_from_indication` : produit un `UserFact` category=`availability`, key `unavailable_<sport|general>_<start-iso>_<end-iso>` (sport détecté via `_TRIGGER_ACTIVITY_PATTERNS`), `expires_at = datetime.combine(end + 1 jour, time.min)`. Skippe single-day + polarités non-UNAVAILABLE.
- ✅ Parse inverse `parse_availability_fact_key` : retrouve sport + start + end depuis la clé, sans relire l'indication d'origine.
- ✅ Pipeline (`conversation_pipeline.py`) : persiste les availability facts AVANT le flux health, refresh `_active_memory_payloads`.
- ✅ Garde clarification (`_yesterday_session_covered_by_active_constraint` dans `api_messages.py`) : parcourt `repo.get_active_facts` (filtré par `fact_is_current`), retourne True si hier ∈ fenêtre ET (sport match ou contrainte générale). Wiré dans `_targeted_execution_clarification` après le check `yesterday_sessions`.
- ✅ Les tests historiques `test_user_indications.py` ont ete retires avec le module. Les garanties actives sont dans `test_llm_first_conversation_contract.py`, `test_memory_mutation_service.py` et `test_core_flows.py`.

### Recalage du 24 avril 2026 — coach libre, cadre strict

Les captures Telegram des 15/17/19/20/21 avril et la revue du code courant changent le cadrage du prochain chantier.

Le probleme initial n'etait pas "pas assez de regles".
Le probleme etait "des regles locales qui parlaient et decidaient a la place du coach".

Nouvelle doctrine :

- le coach LLM arbitre l'intention, garde le fil conversationnel et decide quoi faire
- le determinisme tient la verite, la validation training, les permissions, le commit et l'audit
- aucune reponse conversationnelle finale ne doit venir d'un helper deterministe, sauf outage LLM minimal ou resume d'un event reel
- une confirmation pending est resolue par le LLM via `pending_resolution`, puis validee par le backend
- les contraintes training sortent en `valid / warning / requires_confirmation / blocked`, pas en mur binaire par defaut

Etat code au 24 avril :

- `propose_replan` existe (`replan_proposal.py`, commit `40bf4a1`)
- c'est un helper read-only qui propose une mutation candidate et la valide avec `validate_week_plan`
- il reste trop mono-cible et trop deterministe pour etre le cerveau du replan
- `MutationDecision` est encore mono-operation
- `PlanPatch` existe maintenant comme contrat batchable pur (`backend/src/fitmas/plan_patch.py`)
- `validate_plan_patch` existe en premier wrapper gradue autour des pre-hooks
- `PlanMutationService.apply_patch_for_user` existe et commit seulement les patchs `valid`
- `PlanMutationService` sait accepter une sequence, mais le pipeline conversation applique surtout une decision unique
- le runtime LLM offre plusieurs tools par intent et execute maintenant un batch borne de tools demandes par le modele
- DeepSeek V4 peut demander plusieurs tools dans la meme reponse et ignore `disable_parallel_tool_use` cote Anthropic-compatible ; le runtime execute les tools autorises sous budget et satisfait tous les ids en `tool_result`
- les smokes reels DeepSeek du 24 avril montrent une API stable, mais un format final fragile apres tool-use :
  - `tests/test_integration_real.py` : 15 tests + 5 subtests passent
  - `smoke-real-conversations` : 22 tours reels, aucun crash, aucun 400 tool-use
  - 5 sorties prose au lieu de JSON apres tool-use ou continuation courte, recuperees par fallback
- spike OpenAI SDK du 24 avril :
  - `deepseek-v4-flash` passe en OpenAI-compatible avec `response_format=json_object`
  - le cas tool-use -> JSON final sort bien en JSON apres replay de `reasoning_content`
  - `response_format=json_object` garantit surtout le format ; il ne garantit pas les enums FitMAS ni les champs utiles non vides
  - `deepseek-v4-pro` ne passe pas encore le probe JSON OpenAI-compatible local
  - `deepseek-chat` gere mieux le function-call final, mais moins bien le tool -> JSON final
  - conclusion : garder un gateway multi-adapter, ne pas basculer tout le runtime d'un coup
- les pre-hooks mutation restent `allowed / blocked` + warnings

Le prochain chantier canonique n'est donc plus "finir `propose_replan`".
Il devient :

> **Tools atomiques + runtime multi-tool borne + skill de replan + PlanPatch audite.**

Raison : DeepSeek a montre dans le smoke qu'il demande les bons tiroirs (`get_plan_window`, `get_user_constraints`, `get_load_context`, `propose_replan`), mais l'interface actuelle le force a en utiliser un seul. Le probleme n'est pas de creer un gros tool magique ; c'est d'autoriser une composition bornee, observable, puis de faire sortir l'action via `PlanPatch`.

Le critere court terme n'est pas "coach sportivement parfait".
Le critere est : **agent de planning fiable**.

Il doit :

- repondre aux questions simples sans confabuler
- reagir aux remarques et contraintes utilisateur
- garder le fil conversationnel
- appliquer ou refuser proprement
- ne jamais promettre une action sans event mutation ou confirmation pending

La qualite sportive fine vient apres ; pour l'instant les regles training sont un cadre de securite gradue.

Ordre precis :

1. Ajouter / enrichir les regressions conversationnelles issues des captures dogfood.
2. Stabiliser le contrat provider DeepSeek avant d'augmenter l'autonomie :
   - DeepSeek-first, Claude fallback
   - adapter DeepSeek OpenAI SDK a evaluer pour les appels structurels
   - conserver Anthropic-compatible tant que le runtime produit n'a pas migre
   - contenir la complexite : un seul point d'entree `llm_gateway`, adapters SDK caches derriere la meme interface
   - aucun module domaine ne doit connaitre OpenAI vs Anthropic
   - repair JSON obligatoire quand la reponse finale apres tool-use est en prose
   - fallback Haiku/Sonnet si repair impossible ou schema invalide
   - metrics `provider / model / json_repair_used / provider_fallback_used / tool_json_failure`
   - gate : moins de 5% de fallback provider sur la matrice smoke conversationnelle ciblee
3. Passer le runtime tools en V2 multi-tool **read-only / validation-only** borne :
   - ✅ `execute_tool_calls()` execute un batch borne et preserve un resultat par tool demande
   - ✅ `llm.py` renvoie un `tool_result` pour chaque `tool_use_id`
   - ✅ max 3 tools executes par tour ; le surplus devient `tool_budget_exceeded`
   - max 2 round-trips LLM outilles
   - traces `requested_tools / executed_tools / blocked_tools`
4. Nettoyer la surface tools :
   - garder les tools atomiques utiles
   - ameliorer descriptions et payloads
   - reclasser `propose_replan` en `suggest_replan_candidates`
   - garder `get_coach_state` comme shortcut optionnel, pas comme fondation unique
5. Ajouter une skill metier `replan_after_constraint` :
   - quand l'utiliser
   - tools autorises
   - ordre recommande
   - sortie obligatoire `PlanPatch` ou `no_change` justifie
6. ✅ Brancher `llm.decide()` vers un schema `CoachDecision` capable de retourner un `PlanPatch`.
7. ✅ Brancher le pipeline conversation sur `PlanPatch -> validate_plan_patch -> apply_patch_for_user`.
8. Durcir `validate_plan_patch` au-dela du wrapper pre-hooks : suggestions de fix, batch complet, health/load/recovery.

Slicings deja livres :

- ✅ contrat `PlanPatch` batchable + adaptateur `PlanPatchOperation -> MutationDecision`
- ✅ `validate_plan_patch` slice 1 avec statuts gradues depuis pre-hooks
- ✅ `PlanMutationService.apply_patch_for_user`, commit seulement si `valid`
- ✅ compat protocole DeepSeek : si plusieurs `tool_use` sont emis, tous les ids recoivent un `tool_result`
- ✅ runtime multi-tool borne : `execute_tool_calls()` execute jusqu'a 3 tools et renvoie une erreur controlee aux surplus
- ✅ action `create_session` : decision LLM / PlanPatch peut creer une `ScheduledSession` future via orchestrateur, avec validation et `plan_mutation_event`
- ✅ calibration/fatigue guard : correction du biais `thursday` dans le prompt calibration et suppression du court-circuit sante qui shuntait `decide()` avant fallback
- ✅ contrat `CoachDecision` actif en compat/shadow : `decide()` accepte le nouveau schema (`reply/no_change/mutation_decision/plan_patch/requires_confirmation`) et garde le vieux JSON `mutation_type` en fallback legacy
- ✅ pipeline `PlanPatch` conversation : si le coach retourne `response_type=plan_patch`, le pipeline revalide cote serveur puis applique via `PlanMutationService.apply_patch_for_user`; la reply vient des events appliques, pas du brouillon LLM
- ✅ confirmations `PlanPatch` : un patch `requires_confirmation` est serialise en pending confirmation complet, puis revalide et applique avec `allow_requires_confirmation=True` seulement apres un `oui` explicite
- ✅ slice provider contract :
  - `DeepSeekOpenAI` structured output disponible derriere `FITMAS_USE_DEEPSEEK_OPENAI_STRUCTURED`
  - validation locale des decisions FitMAS (`mutation_type`, champs requis, targets)
  - repair structuree sur prose apres tool-use
  - fallback Claude sur schema invalide si `ANTHROPIC_API_KEY` est disponible

Reste explicitement ouvert :

- dogfood reel avant nouvelle couche d'autonomie
- reclasser `propose_replan` en candidate helper, pas decision helper
- formaliser `replan_after_constraint` comme skill metier reusable
- durcir `validate_plan_patch` avec batch atomicite / suggested fixes / health-load-recovery fin
- enrichir les traces tools session-level (`requested/executed/blocked`, round trips, fallback provider)

Le plan detaille vit dans `docs/COACH-AUTONOMY-REFACTOR.md`, section "Plan d'attaque recale — Agent fiable, tools atomiques, PlanPatch audite".

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
- `/api/v0/week` lit la semaine courante depuis `ScheduledSession` et expose `runtime_role=scheduled_runtime` quand le runtime date existe
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
  - runtime tools V2 ; dette 30 avril : le routing ne doit plus classifier le texte user, seulement borner les tools autorises
  - runtime tools V2 : plusieurs tools read-only / validation-only executes dans un meme tour, budget actuel max 3
  - confirmations pending serialisees ; dette 30 avril : resolution par `CoachDecision.pending_resolution`, pas parser `oui/non`
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
  - guards writer : `same_sport_proximity` + `occupied_training_target` ; repos/recuperation arbitres par review semaine ✓
  - `plan_actions.py` / `mutations.py` mutent uniquement `ScheduledSession` ✓
  - `signals.py` et `activities.py` lisent `ScheduledSession`, plus `WeeklyPlan/DayPlan` ✓
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
- `/api/v0/week` garde le contrat compat mais sert la verite runtime datee avant fallback template
- adaptation background suggestion-only
- guard `same_sport_proximity` sur moves datés
- ancien guard `protected_recovery_target` deprecie : repos/récupération = contrainte de plan, plus verrou runtime
- `SYSTEM-MAP.md` comme carte d'architecture pour les agents
- `skills/heartbeat/context.py` : `HeartbeatContextBundle` injecte `YesterdayTruth` / `TodayTruth` / `WeekDigest` dans le briefing matin ; pas de lens LLM dans heartbeat
- `coach_reading_digest` : contexte pré-digéré (facts déterministes + lens Haiku JSON) injecté dans `decide()` sur intents lookup/report/availability, avec voice rules anti-bullshit (12b4bf8)

### Dette technique vivante

#### Truth source runtime (sous surveillance)

Core ferme le 3 mai 2026 : mutations visibles, signals et matching activites
passent par `ScheduledSession`.

Surveillance restante :
- garder les tests statiques anti-retour legacy ;
- ne pas rebrancher `repo.get_active_plan` / `to_pydantic_plan` dans conversation, heartbeat, app runtime, activites ou strava ;
- separer plus tard les helpers template/compat de `repository.py` pour rendre la frontiere plus lisible.

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

- le runtime tools plane reste volontairement etroit cote LLM-facing (read-only / validation-only, max 3 tools par tour aujourd'hui) ; l'action passe ensuite par `PlanPatch` + orchestrateur
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
- pas de "liberté coach" non validee ; la liberte passe par substrates metier, validation et commit audite

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
