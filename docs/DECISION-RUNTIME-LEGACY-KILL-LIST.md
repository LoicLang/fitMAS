---
summary: inventaire Phase 8A des surfaces legacy qui bloquent le runtime canonique et ordre de suppression
read_when:
  - lancer Phase 8 du refactor Decision Runtime
  - supprimer MutationDecision, CoachDecision ou PlanPatch direct du runtime
  - migrer conversation_pipeline.py vers un adapter mince
  - retirer final_reply.py, heartbeat legacy ou tools compat
  - verifier qu'une PR ne recrée pas une route legacy
---

# Decision Runtime Legacy Kill List

## Statut

Phase 8T-A / 8T-B / 8T-C est livree localement.

Phase 8A ne supprime pas de code runtime ; elle a rendu le legacy visible.
Phase 8B a prouve la parite sous flags.
Phase 8C a retire ou isole les routes runtime legacy principales :

- conversation : plus de route active `MutationDecision` mutante ;
- conversation : plus d'import direct `fitmas.final_reply` hors bridges legacy ;
- heartbeat Telegram : adapter runtime par defaut ;
- tools registry : plus de `propose_replan` ni `draft_*` en surface par defaut ;
- planning read/write runtime : plus de lecture `WeeklyPlan` / `DayPlan` dans les fichiers runtime controles ;
- contrats `CoachDecision` / `MutationDecision` archives derriere `legacy/decision_contracts.py`.

Phase 8D n'a pas supprime `final_reply.py` ni `llm/decision_legacy.py`.
Elle a reduit l'autorite restante des bridges :

- `DecisionRuntimeService` existe comme shell pur dans `decision/runtime.py` ;
- `/api/v0/messages` est deplace vers `app/api/routes_messages.py` avec
  `api_messages.py` en wrapper compat ;
- planning cutover conversation :
  `legacy/conversation_planning_bridge.py` ;
- replies read-only/no-change :
  `legacy/conversation_readonly_reply_bridge.py` ;
- helpers `CoachDecision` / legacy readonly :
  `legacy/conversation_decision_bridge.py` ;
- wrappers heartbeat skill-loop :
  `legacy/heartbeat_skill_bridge.py`.

Phase 8E rapproche le cutover Understanding sans supprimer
`llm/decision_legacy.py` :

- `LLMUnderstandingService` produit un `CoachUnderstanding` canonique ;
- le parser neutralise les champs cross-intent avant toute consommation
  planning ;
- `legacy/conversation_understanding_bridge.py` appelle ce service en shadow
  opt-in ;
- `FITMAS_UNDERSTANDING_RUNTIME_SHADOW` est off par defaut ;
- `FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER` est off par defaut ;
- le planning runtime peut consommer l'Understanding canonique si le flag est
  active et que l'intent est `plan_change` ;
- le provider legacy `CoachDecision` reste utilise pour memory/execution/pending
  tant que ces commandes ne sont pas sorties du contrat historique.

Phase 8F extrait les actions memoire/execution :

- les writes memoire/execution conversation passent par
  `legacy/conversation_command_bus.py` ;
- `conversation_pipeline.py` ne possede plus ces writes ;
- `CoachDecision.memory_actions` et `CoachDecision.execution_actions` restent
  provider-compat, mais ne sont plus une route de write directe depuis
  l'orchestrateur conversation ;
- `legacy/coach_command_adapter.py` convertit les artefacts types en
  `Command` ;
- les `CommandResult` appliques referencent un event persiste ;
- `FITMAS_COMMANDS_FROM_UNDERSTANDING` prepare la compilation depuis
  `CoachUnderstanding`, off par defaut ;
Phase 8G extrait la resolution pending :

- `legacy/conversation_pending_bridge.py` applique `pending_resolution` ;
- `conversation_pipeline.py` ne possede plus les helpers pending actifs ;
- `FITMAS_PENDING_FROM_UNDERSTANDING` prepare la source canonique, off par
  defaut ;
- `CoachDecision.pending_resolution` reste provider-compat par defaut.

Phase 8H extrait les replies pending non commitantes :

- `legacy/pending_reply_adapter.py` transforme les modes pending en
  `DecisionOutcome` ;
- `legacy/conversation_pending_bridge.py` ne lit plus `decision.fitmas_message`
  et ne possede plus les textes visibles reject/ignore/clarification ;
- les pending creees demandent confirmation via le contrat de reply commun ;
- les sentinelles techniques `await_user_confirmation` /
  `await_user_choice` ne sortent plus comme `next_step` visible.

Phase 8I dogfood les chemins canoniques sous flags explicites :

- `FITMAS_COMMANDS_FROM_UNDERSTANDING` peut compiler des commandes memoire et
  execution depuis `CoachUnderstanding` ;
- `FITMAS_PENDING_FROM_UNDERSTANDING` peut faire gagner une resolution pending
  canonique ;
- le fallback `CoachDecision` reste explicite quand l'artefact canonique est
  absent ou inexploitable ;
- `scripts/smoke-decision-runtime-canonical-flags` active shadow
  Understanding, commandes canoniques et pending canonique, mais exclut
  volontairement le planning cutover ;
- `FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER` reste non active par defaut ;
- le gap duplicate pending observe sous planning cutover explicite est corrige :
  une confirmation pending canonique peut etre appliquee meme si le vieux
  `decide()` retourne `None`, et les fallbacks adaptation post-decide respectent
  la gate pending active.

Phase 8J dogfood le planning cutover canonique :

- wrapper dedie `scripts/smoke-decision-runtime-canonical-planning` ;
- `FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER=1` reste opt-in et separe du
  wrapper 8I ;
- duplicate pending devient un hard fail du smoke evaluator ;
- `confirm_without_pending` reste no-write strict sous cutover canonique ;
- `move_easy_then_confirm` accepte la pending existante sans en creer une
  deuxieme ;
- les scenarios planning larges passent la matrice API reelle :
  move/confirm, swap, lighten, replace, indisponibilite, fatigue,
  anti back-to-back, indisponibilite natation longue ;
- les fuites `Candidate backend`, `Candidate possible` et
  `pas une reponse finale` sont bloquees par le guard voix et le smoke
  harness ;
- les builders backend n'ecrivent plus de `coach_message` interne dans les
  `PlanPatch` candidates ;
- `planning_outcome_adapter.py` ne donne plus les ids `backend:*` au reply
  composer comme summaries user-facing.

Phase 8K default-enable les lanes canoniques non-planning :

- `FITMAS_COMMANDS_FROM_UNDERSTANDING` est on par defaut, opt-out `0` ;
- `FITMAS_PENDING_FROM_UNDERSTANDING` est on par defaut, opt-out `0` ;
- `FITMAS_CANONICAL_NON_PLANNING_CUTOVER` est on par defaut, opt-out `0` ;
- `FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER` reste off par defaut ;
- commands/pending peuvent consommer `CoachUnderstanding` sans activer le
  planning cutover complet.

Phase 8L shrink l'autorite directe de `decide()` :

- `CoachDecision` reste provider actif ;
- son autorite runtime est limitee aux bridges legacy ;
- `conversation_pipeline.py` ne call plus `dependencies.decide` directement ;
- `conversation_pipeline.py` ne depend plus de `llm_runtime` ;
- `conversation_pipeline.py` ne lit plus `decision.fitmas_message`
  directement ;
- `legacy/coach_decision_provider.py` porte l'appel legacy et renvoie un
  resultat au lieu de laisser les erreurs provider traverser l'orchestrateur ;
- `legacy/conversation_decide_bridge.py` construit la request legacy depuis
  les artefacts machine du tour ;
- `legacy/conversation_coach_decision_reply_bridge.py` porte la fallback reply
  `CoachDecision` restante ;
- `llm/decision_legacy.py` reste a splitter en Phase 8M.

Phase 8M split les internals de `llm/decision_legacy.py` :

- `llm/legacy_models.py` porte les contrats Pydantic legacy ;
- `llm/legacy_parser.py` porte parsing, normalisation et guards payload ;
- `llm/legacy_prompt.py` porte la construction du prompt conversation legacy ;
- `llm/legacy_action_compile.py` porte les compilers/repairs action-only ;
- `decision_legacy.py` reste l'orchestrateur legacy provider/tool-loop ;
- imports publics `fitmas.llm` restent compatibles ;
- le planning cutover canonique reste opt-in.

Phase 8N extrait provider, schema repair et tool-loop :

- `llm/legacy_provider.py` porte les wrappers provider patchables ;
- `llm/legacy_schema_repair.py` porte repair payload invalide, fallback Claude
  schema, prose -> JSON et resumes de resultats tools ;
- `llm/legacy_tool_loop.py` porte la boucle tool-use conversation legacy,
  le compiler JSON, le retry format et les traces tool ;
- `decision_legacy.py` garde les shims prives compatibles et descend a 941
  lignes ;
- `CoachDecision` reste contrat provider actif ;
- le planning cutover canonique reste opt-in.

Phase 8O cree la frontiere artifact `CoachDecision` :

- `legacy/coach_decision_artifact.py` renomme la reply legacy
  `fitmas_message` en `reply_hint` au bord provider/runtime ;
- `CoachDecisionResult` expose `artifact` au runtime et garde `raw_decision`
  seulement pour compat ;
- `conversation_pipeline.py` et les bridges conversation-facing ne consomment
  plus le raw `CoachDecision` ;
- command, pending, planning, reply et shadow Understanding lisent l'artifact ;
- les `MutationDecision` mutantes legacy deviennent
  `unsupported_mutation_decision` et restent bloquees par le contrat disabled ;
- le planning cutover canonique reste opt-in.

Phase 8P extrait les helpers support de `llm/decision_legacy.py` :

- `llm/legacy_summaries.py` porte les summaries plan/timeline ;
- `llm/legacy_onboarding.py` porte preview coach, recap onboarding et
  enrichment week-plan ;
- `llm/legacy_fact_memory.py` porte extraction/selection facts ;
- `decision_legacy.py` descend a 556 lignes et garde l'orchestration
  provider/tool-loop/schema repair/action compile de `decide()` ;
- les imports publics `fitmas.llm` restent compatibles via wrappers ;
- le planning cutover canonique reste opt-in.

Phase 8Q pivote le provider canonique non-planning :

- `conversation_pipeline.py` lance l'Understanding canonique avant le provider
  legacy `CoachDecision` ;
- si l'Understanding est non-planning et produit un pending resolution ou des
  commandes memoire/execution consommables, `decide()` est saute ;
- `LegacyCoachDecisionArtifact(source="coach_understanding")` sert seulement
  de compat pour les bridges downstream ;
- `legacy_decide.legacy_skipped=True` trace le contournement du provider
  legacy ;
- `CoachDecision` reste fallback pour planning et tours non actionnables ;
- le planning cutover canonique reste opt-in.

Phases 8R / 8S pivotent les replies read-only canoniques :

- `legacy/conversation_canonical_readonly_bridge.py` porte le gate read-only ;
- les tours `plan_lookup` / truth-read supportes peuvent produire un
  `DecisionOutcome(kind="answer")` puis passer par `DecisionReplyComposer`
  sans `CoachDecision` ;
- `FITMAS_CANONICAL_READONLY_PROVIDER` est on par defaut avec opt-out `0` ;
- planning, pending actif, commands memoire/execution et close-turn restent
  hors scope ;
- `CoachDecision` reste fallback explicite si la composition canonique echoue
  ou si le tour n'est pas admissible.

Phase 8T-A / 8T-B ouvre le provider planning canonique en opt-in :

- `legacy/conversation_canonical_planning_bridge.py` porte le gate planning ;
- `FITMAS_CANONICAL_PLANNING_PROVIDER` est off par defaut, opt-in explicite
  `1` ;
- les tours planning supportes peuvent sauter `CoachDecision` et appeler
  directement le runtime domaine depuis `CoachUnderstanding.requested_change` ;
- les references libres restent refusees : seules les refs typees
  `session_id:*`, `date:*` et `day:*` admises par `ReferenceResolver` passent
  le gate ;
- un echec applicable bloque explicitement en `planning_runtime_unhandled`,
  sans fallthrough `PlanPatch`, `MutationDecision`, pending legacy ou candidate
  fallback ;
- `PlanningCommandService` dedup les pending actives identiques ;
- `planning_outcome_adapter.py` exige une preuve de commit/pending avant
  d'autoriser les claims visibles correspondants.

Phase 8T-C dogfood le provider planning canonique avec le vrai stack API/LLM :

- `FITMAS_CANONICAL_PLANNING_PROVIDER=1` passe
  `scripts/smoke-decision-runtime-canonical-planning` sur 9 scenarios API ;
- les tours planning supportes preemptent le flow candidates pre-decide et
  ne passent plus par `CoachDecision` ;
- les confirmations pending actives passent par `CoachUnderstanding` avant le
  flow candidates, puis gardent un seul recheck LLM de securite avant write ;
- les refs provider `session:*` et les refs objet (`session_id`, `date`,
  `day`) sont normalisees avant le gate planning ;
- les metadata preference planning sont admises, les signaux qui compilent des
  commandes memoire/execution restent bloquants ;
- le flag planning provider reste off par defaut tant que le default-on
  progressif n'est pas decide.

Regle d'arbitrage :

```text
Un chemin legacy documente peut survivre temporairement.
Un chemin legacy non documente est une regression.
```

## Invariants Phase 8

```text
1. Aucun nouveau fallback local dans conversation_pipeline.py.
2. Aucun nouveau texte visible hors ReplyComposer.
3. Aucun nouveau write hors CommandService.
4. Aucun nouveau PlanPatch produit directement par Understanding.
5. Aucun nouveau MutationDecision dans le runtime cible.
6. Aucun nouveau import legacy dans decision/.
7. Aucun nouveau parser regex sur texte utilisateur libre.
8. ScheduledSession reste la verite runtime visee.
```

## Flags de cutover actuels

| Flag | Statut | Role |
|------|--------|------|
| `FITMAS_PLANNING_RUNTIME_CUTOVER` | on par defaut, opt-out explicite | route le planning conversationnel applicable vers le runtime Phase 4/5 |
| `FITMAS_HEARTBEAT_RUNTIME_CUTOVER` | on par defaut, opt-out explicite | route scheduler, `/heartbeat`, debug et ops heartbeat via l'adapter Phase 7 |
| `FITMAS_HEARTBEAT_RUNTIME_VERIFY_ENFORCE` | off par defaut | rend bloquant le verifier commun sur les replies heartbeat adaptees |
| `FITMAS_UNDERSTANDING_RUNTIME_SHADOW` | off par defaut | force le shadow Understanding all-turns pour observability explicite |
| `FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER` | off par defaut | autorise le planning a consommer `CoachUnderstanding.requested_change` |
| `FITMAS_CANONICAL_NON_PLANNING_CUTOVER` | on par defaut, opt-out explicite | lance Understanding seulement si pending ou commands peuvent consommer l'artefact |
| `FITMAS_CANONICAL_PROVIDER_NON_PLANNING` | on par defaut, opt-out explicite | saute le provider legacy quand l'Understanding non-planning est directement consommable |
| `FITMAS_CANONICAL_READONLY_PROVIDER` | on par defaut, opt-out explicite | saute le provider legacy pour les replies read-only supportees via DecisionOutcome + ReplyComposer |
| `FITMAS_CANONICAL_PLANNING_PROVIDER` | off par defaut, opt-in explicite | saute le provider legacy pour les plan_change supportes par RequestedPlanChange type |
| `FITMAS_COMMANDS_FROM_UNDERSTANDING` | on par defaut, opt-out explicite | autorise les commandes memoire/execution depuis `CoachUnderstanding.extracted_signals` |
| `FITMAS_PENDING_FROM_UNDERSTANDING` | on par defaut, opt-out explicite | autorise la resolution pending depuis `CoachUnderstanding.pending_resolution` |

Ces flags restent des leviers de rollback localises, pas une architecture
parallele.

## P0 — Legacy qui bloque le runtime canonique

Ces fichiers peuvent encore decider, parler, muter ou convertir par l'ancien
contrat. Ils doivent etre coupes avant activation par defaut du runtime complet.

| Surface | Fichiers | Probleme | Sortie attendue |
|---------|----------|----------|-----------------|
| Mega orchestrateur conversation | `conversation_pipeline.py` | Charge encore contexte, actions, runtime adapter, reply et persistence | Devenir adapter mince vers `DecisionRuntime` complet |
| Contrat LLM legacy | `llm/decision_legacy.py`, `llm/legacy_*`, `conversation_prompt_modules.py`, `prompt_contracts.py` | `CoachDecision`, `fitmas_message`, `PlanPatch` direct, actions et prompts longs | Understanding canonique + prompts `llm/prompts/*` |
| `MutationDecision` runtime | `legacy/decision_contracts.py`, `legacy/coach_understanding_adapter.py`, anciens modules domaine qui importent le bridge | Deuxieme langage archive mais encore present en compat | Supprimer les anciens modules qui dependent du bridge |
| Reply legacy | `legacy/conversation_reply_adapter.py`, `legacy/final_reply_backend.py`, `skills/heartbeat/heartbeat.py`, `skills/heartbeat/reply_context.py` | Bridges legacy controles, heartbeat skills historiques encore presents | `DecisionOutcome -> DecisionReplyComposer -> DecisionOutputVerifier` partout |
| Heartbeat legacy interne | `heartbeat.py`, `skills/heartbeat/heartbeat.py`, `skills/heartbeat/tool_loop.py`, `skills/heartbeat/reply_context.py` | Code historique encore dans le repo, hors chemin Telegram actif | Suppression physique apres dogfood runtime |
| Tools planning legacy | `legacy/tools_compat.py`, `plan_patch_tools.py` | `propose_replan` et `draft_*` isoles hors registry par defaut | Supprimer quand les prompts legacy seront retires |
| Verite planning duale | `repository.py`, `api_onboarding.py` | `WeeklyPlan` / `DayPlan` restent pour template/archive/onboarding | `ScheduledSession + Activity + Events` en runtime |

## Importeurs `CoachDecision` / `MutationDecision`

Les fichiers suivants importent encore explicitement les anciens contrats depuis
`fitmas.llm` :

```text
legacy/coach_understanding_adapter.py
legacy/decision_contracts.py
```

Regle Phase 8C :

```text
Aucun import direct de CoachDecision ou MutationDecision depuis fitmas.llm hors legacy/.
Les anciens modules qui n'ont pas encore ete reecrits utilisent le bridge legacy/decision_contracts.py.
```

## Callers de `fitmas.final_reply`

Les callers directs restants du module legacy sont :

```text
legacy/conversation_reply_adapter.py
legacy/final_reply_backend.py
skills/heartbeat/heartbeat.py
skills/heartbeat/reply_context.py
```

`legacy/conversation_reply_adapter.py` et `legacy/final_reply_backend.py` sont les
ponts volontaires Phase 8C. Les surfaces heartbeat legacy doivent disparaitre du
runtime actif quand le heartbeat ne dependra plus de ses prompts historiques.

## WeeklyPlan / DayPlan

`WeeklyPlan` et `DayPlan` restent acceptables pour :

- onboarding ;
- templates ;
- archive ;
- compat read model temporaire.

Ils ne doivent plus influencer :

- conversation runtime ;
- heartbeat runtime ;
- mutation planning ;
- activity matching ;
- app cockpit runtime.

Surfaces a traiter :

```text
repository.py             porte les helpers compat get_active_plan/get_day_plan/to_pydantic_plan/replace_plan
api_onboarding.py         usage accepte comme template/generation pour l'instant
```

## Tools compat

Statut actuel :

- `suggest_replan_candidates` : helper candidat historique, non-writer.
- `propose_replan` : isole dans `legacy/tools_compat.py`, non expose par defaut.
- `draft_move_session` : isole dans `legacy/tools_compat.py`, non expose par defaut.
- `draft_swap_sessions` : isole dans `legacy/tools_compat.py`, non expose par defaut.
- `draft_replace_session` : isole dans `legacy/tools_compat.py`, non expose par defaut.
- `draft_lighten_day` : isole dans `legacy/tools_compat.py`, non expose par defaut.
- `draft_create_session` : isole dans `legacy/tools_compat.py`, non expose par defaut.

Regle cible :

```text
ReadTools lisent.
CandidateBuilder construit.
Evaluator/Reviewer jugent.
CommandServices ecrivent.
Le registry ne donne plus au LLM un chemin de mutation autonome.
```

## Ordre Phase 8 recommande

### Phase 8A — Audit verrouille

- creer ce document ;
- ajouter les tests d'audit statiques ;
- mettre `BUILD-ORDER.md`, `README.md` et le canon de refactor a jour ;
- ne supprimer aucun comportement.

### Phase 8B — Cutover runtime flag-on

- activer les cutovers local/staging pour conversations planning + heartbeat ;
- rejouer les golden conversations et smokes reels ;
- corriger uniquement dans la couche responsable : context, understanding,
  planning, command, reply ou verifier.

Resultat local 2026-05-14 :

- `scripts/smoke-decision-runtime-cutover` existe et active explicitement les
  trois flags de cutover ;
- planning : une decision applicable au runtime ne retombe plus silencieusement
  dans les branches planning legacy sous flag ;
- planning : un cas applicable mais non gere devient
  `planning_runtime_unhandled` bloque ;
- heartbeat : scheduler cutover teste avec metadata et verifier enforce ;
- preuves :
  - flag-on unit gate -> 30 passed ;
  - `./scripts/smoke-decision-runtime-cutover` -> exit 0 ;
  - A+ API `move_easy_then_confirm` -> OK ;
  - full backend -> 1111 passed, 11 skipped, 11 subtests passed ;
- legacy toujours present physiquement : Phase 8C peut commencer les coupes
  route par route, pas en suppression massive.

### Phase 8C — Kill legacy runtime

Resultat local 2026-05-14 :

- `conversation_pipeline.py` bloque les `MutationDecision` mutantes comme
  `legacy_decision_contract_disabled` ; le no-change legacy reste read-only et
  passe par le composer commun ;
- `conversation_pipeline.py` passe par `legacy/conversation_reply_adapter.py`
  au lieu d'importer `fitmas.final_reply` directement ;
- `app/telegram/scheduler.py` et `telegram_commands.py` utilisent l'adapter
  heartbeat runtime par defaut ;
- `tools/registry.py` n'expose plus `propose_replan` ni les `draft_*` ;
- `plan_mutation_service.py` et `api_read.py` ne lisent plus
  `WeeklyPlan` / `DayPlan` pour le runtime controle ;
- `prompt_contracts.py` retire les tools `draft_*` du contrat health signal ;
- preuves :
  - `./scripts/test-backend -q` -> 1116 passed, 11 skipped, 11 subtests passed ;
  - `./scripts/smoke-decision-runtime-cutover` -> exit 0 ;
  - gates architecture Phase 8 -> 24 passed.

Legacy restant volontaire :

- `final_reply.py` existe encore comme backend legacy appele via bridge ;
- `llm/decision_legacy.py` existe encore comme contrat provider historique ;
- `conversation_prompt_modules.py` et certains prompts legacy parlent encore
  `CoachDecision` / `PlanPatch` ;
- `repository.py` garde les helpers `WeeklyPlan` / `DayPlan` pour template,
  archive, onboarding et compat tests.

### Phase 8D — Bridge shrink

Resultat local 2026-05-14 :

- `conversation_pipeline.py` descend a 3459 lignes ;
- les ponts conversation restants sont nommes et isoles dans `legacy/` ;
- `decision/runtime.py` porte le shell runtime pur sans import legacy ;
- les routes messages avancent vers l'organisation cible `app/api/` ;
- les wrappers heartbeat racine ne pointent plus directement sur
  `skills/heartbeat`.
- preuves :
  - `./scripts/test-backend -q` -> 1130 passed, 11 skipped,
    11 subtests passed ;
  - `./scripts/smoke-decision-runtime-cutover` -> RESULT: OK.

Legacy restant volontaire :

- `final_reply.py` reste backend legacy appele par bridge ;
- `llm/decision_legacy.py` reste contrat provider historique ;
- `conversation_prompt_modules.py` reste legacy jusqu'au cutover
  Understanding ;
- `skills/heartbeat/*` reste code historique appelle via bridge legacy.

### Phase 8E — Understanding cutover preparation

Resultat local 2026-05-14 :

- `fitmas.llm.understanding_service.LLMUnderstandingService` existe ;
- le parser refuse les champs de reply visible, patch planning, mutation legacy
  et commandes ;
- le parser neutralise les champs planning/pending/clarification si l'intent ne
  correspond pas ;
- `conversation_pipeline.py` appelle uniquement
  `legacy/conversation_understanding_bridge.py`, pas le service LLM directement ;
- Understanding shadow est opt-in, off par defaut ;
- planning peut utiliser `CoachUnderstanding.requested_change` uniquement sous
  `FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER=1` et `intent=plan_change` ;
- preuves :
  - `./scripts/test-backend -q` -> 1153 passed, 11 skipped,
    11 subtests passed ;
  - `./scripts/smoke-decision-runtime-cutover` -> unit gates 28 passed ;
    tentative full harness final interrompue pendant `smoke-real-conversations`
    apres stall provider, sans assertion code exploitable ;
  - `FITMAS_UNDERSTANDING_RUNTIME_SHADOW=1 ./scripts/smoke-real-conversations --scenario heartbeat_non_completion`
    -> exit 0, log `decision_runtime.canonical_understanding`
    avec `requested_change=0` sur `execution_report`.

Legacy restant volontaire :

- `llm/decision_legacy.py` reste actif pour `CoachDecision` ;
- `conversation_prompt_modules.py` reste le prompt historique de decision ;
- `pending_resolution` reste porte par `CoachDecision` jusqu'a extraction ;
- `memory_actions` et `execution_actions` restent dans `CoachDecision` pour
  compat provider, mais leur application passe par `ConversationCommandBus`.

### Phase 8F — Command extraction

Resultat local 2026-05-14 :

- `legacy/coach_command_adapter.py` compile `CoachDecision` actions ou
  `CoachUnderstanding` signals en `Command` ;
- `legacy/conversation_command_bus.py` applique les commandes memoire/execution
  via les services existants ;
- `legacy/conversation_command_bridge.py` preserve les metriques conversation ;
- `conversation_pipeline.py` ne call plus directement les writers
  memoire/execution ;
- `memory_mutation_service` et `execution_mutation_service` retournent les ids
  d'events ;
- preuves :
  - targeted 8F -> 35 passed ;
  - architecture pack Phase 8 -> 45 passed ;
  - `./scripts/test-backend -q` -> 1167 passed, 11 skipped,
    11 subtests passed ;
  - `FITMAS_UNDERSTANDING_RUNTIME_SHADOW=1 ./scripts/smoke-real-conversations --scenario heartbeat_non_completion`
    -> exit 0, action execution via `command_source=coach_decision` ;
  - `./scripts/smoke-decision-runtime-cutover` -> unit gates 28 passed ;
    run interrompu ensuite pendant un stall provider DeepSeek JSON sur un cas
    planning, sans assertion code exploitable.

Legacy restant volontaire :

- `pending_resolution` reste l'ancien chemin actif ;
- `llm/decision_legacy.py` reste contrat provider ;
- `conversation_prompt_modules.py` reste schema d'action legacy ;
- les services root memoire/execution restent a deplacer vers `domain/*`.

### Phase 8G — Pending resolution extraction

Resultat local 2026-05-14 :

- `legacy/conversation_pending_bridge.py` devient la frontiere unique pending ;
- `conversation_pipeline.py` delegue apply/recheck/accept/keep/supersede ;
- `conversation_pipeline.py` ne lit plus `decision.pending_resolution`
  directement ;
- `plan_patch` et `plan_patch_choice` pending restent appliques via
  `apply_patch_for_user` ;
- le recheck accept/reject reste LLM JSON-only, sans regex/keyword sur texte
  utilisateur libre ;
- `FITMAS_PENDING_FROM_UNDERSTANDING` permet de lire
  `CoachUnderstanding.pending_resolution` sous flag ;
- `conversation_pipeline.py` descend a 2731 lignes ;
- preuves :
  - gates 8G -> 8 passed ;
  - parite pending/confirmation -> 33 passed ;
  - architecture pack Phase 8 -> 49 passed ;
  - full backend -> 1175 passed, 11 skipped, 11 subtests passed ;
  - smokes API `move_easy_then_confirm` et `confirm_without_pending`
    -> RESULT: OK.

Legacy restant volontaire :

- `CoachDecision.pending_resolution` reste source par defaut tant que le flag
  canonique est off ;
- les replies pending reject/ignore/clarification sont encore legacy-compat
  dans le bridge ;
- le contrat provider `llm/decision_legacy.py` et les prompts historiques
  restent actifs.

### Phase 8H — Pending reply cleanup

Resultat local 2026-05-15 :

- `legacy/pending_reply_adapter.py` porte les `DecisionOutcome` de pending
  reply ;
- `conversation_pending_bridge.py` ne consomme plus `decision.fitmas_message`
  pour les replies pending ;
- reject / ignore / modify / needs_clarification / expired / inactive /
  choice-error passent par `DecisionReplyComposer` ;
- les pending `PlanPatch` acceptees / bloquees restent event-backed ;
- `DecisionReplyComposer` force une demande de confirmation quand une pending
  vient d'etre creee ;
- preuves :
  - gates ciblees 8H -> 24 passed ;
  - parite pending/confirmation -> 33 passed ;
  - architecture pack Phase 8 -> 52 passed ;
  - full backend -> 1187 passed, 11 skipped, 11 subtests passed ;
  - smokes API `move_easy_then_confirm` et `confirm_without_pending`
    -> RESULT: OK.

Legacy restant volontaire :

- `CoachDecision.pending_resolution` reste source par defaut tant que le flag
  canonique est off ;
- `llm/decision_legacy.py` reste contrat provider ;
- `conversation_prompt_modules.py` reste schema d'action legacy ;
- `final_reply.py` reste backend legacy pour certaines replies composees ;
- les services root memoire/execution/planning restent a deplacer vers
  `domain/*`.

### Phase 8I — Canonical flag dogfood

Resultat local 2026-05-15 :

- `tests/test_phase8i_canonical_flag_dogfood_architecture.py` verrouille que
  les flags canoniques restent opt-in et que `decision/` reste pur ;
- `tests/test_conversation_command_bridge.py` prouve les commandes memoire et
  execution depuis `CoachUnderstanding` sous
  `FITMAS_COMMANDS_FROM_UNDERSTANDING=1` ;
- `tests/test_conversation_pending_bridge.py` prouve la precedence pending
  canonique sous `FITMAS_PENDING_FROM_UNDERSTANDING=1` ;
- `scripts/smoke-decision-runtime-canonical-flags` dogfood shadow
  Understanding + commands + pending sans activer le planning cutover ;
- preuves :
  - targeted 8I -> 21 passed ;
  - architecture pack Phase 8 -> 55 passed ;
  - full backend -> 1197 passed, 11 skipped, 11 subtests passed ;
  - hardening duplicate pending -> 2 passed ;
  - pending/core gate -> 40 passed ;
  - wrapper canonical -> unit gates 18 passed, smokes conversation termines,
    API `move_easy_then_confirm` / `confirm_without_pending` -> RESULT: OK ;
  - probe planning cutover explicite -> RESULT: OK, `events=+1`,
    `pending=+1`, `mode=pending_accepted`, aucune deuxieme pending creee.

Legacy restant volontaire :

- les flags canoniques restent off par defaut ;
- `CoachDecision` reste contrat provider actif ;
- certains tours reels restent `command_source=coach_decision` si
  l'Understanding canonique ne compile pas encore de commande exploitable ;
- `FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER` reste a dogfooder plus
  largement avant activation globale ;
- `conversation_pipeline.py` et les services root doivent encore shrinker vers
  l'organisation cible.

### Phase 8J — Canonical planning cutover dogfood

Resultat local 2026-05-15 :

- `scripts/smoke-decision-runtime-canonical-planning` active les quatre flags
  canoniques, planning cutover inclus ;
- `tests/test_phase8j_canonical_planning_cutover_architecture.py` verrouille
  que 8J reste opt-in et que le wrapper 8I ne contient pas le flag planning ;
- `scripts/smoke_a_plus_api.py` refuse maintenant :
  duplicate pending, confirmation nue qui write, et jargon `Candidate backend`
  dans la reply visible ;
- `PlanCandidateBuilder` et `plan_patch_backend_candidates.py` utilisent un
  `coach_message` user-safe pour les PlanPatch candidates ;
- `planning_outcome_adapter.py` ne transmet plus les ids `backend:*` comme
  summaries visibles au reply composer ;
- preuves :
  - targeted 8J -> 8 passed ;
  - pending/core cutover -> 3 passed ;
  - architecture pack Phase 8 -> 59 passed ;
  - wrapper canonical planning -> RESULT: OK (9 checks) ;
  - full backend -> 1207 passed, 11 skipped, 11 subtests passed.

Legacy restant volontaire :

- tous les flags canoniques restent off par defaut ;
- `CoachDecision` reste provider actif ;
- `decide()` reste a refactorer apres decision 8K ;
- `conversation_pipeline.py` et les services root doivent encore shrinker vers
  l'organisation cible.

### Phase 8K — Canonical default lanes

Resultat local 2026-05-15 :

- `FITMAS_COMMANDS_FROM_UNDERSTANDING` est default-on avec opt-out `0` ;
- `FITMAS_PENDING_FROM_UNDERSTANDING` est default-on avec opt-out `0` ;
- `FITMAS_CANONICAL_NON_PLANNING_CUTOVER` est default-on avec opt-out `0` ;
- le bridge Understanding lance l'appel canonique par defaut seulement pour
  les tours consommables par pending ou commands, ou si shadow explicite est
  active ;
- `FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER` reste off par defaut ;
- `scripts/smoke-decision-runtime-canonical-defaults` prouve les defaults sans
  exporter les flags commands/pending.
- preuves :
  - targeted 8K -> 33 passed ;
  - architecture pack Phase 8 -> 64 passed ;
  - wrapper defaults -> RESULT: OK (2 checks API, smokes conversation OK) ;
  - wrapper planning opt-in -> RESULT: OK (9 checks) ;
  - full backend -> 1222 passed, 11 skipped, 11 subtests passed.

Legacy restant volontaire :

- `CoachDecision` reste provider actif et fallback explicite ;
- le planning cutover canonique reste opt-in ;
- `decide()` reste a refactorer apres ce cutover partiel ;
- `conversation_pipeline.py` et les services root doivent encore shrinker vers
  l'organisation cible.

## Tests d'audit

`tests/test_phase8a_legacy_audit.py` verifie que :

- le document existe et garde son front matter ;
- tous les importeurs `CoachDecision` / `MutationDecision` sont listes ici ;
- tous les callers directs de `fitmas.final_reply` sont listes ici ;
- les flags et tools legacy connus sont explicitement suivis ;
- Phase 8A reste un audit, pas une suppression de code deguisee.

Ces tests sont volontairement statiques. Leur role est de forcer une mise a jour
de la kill list quand une surface legacy change.

`tests/test_phase8c_legacy_kill_architecture.py` verifie en plus que :

- `conversation_pipeline.py` ne contient plus de routes planning
  `MutationDecision` actives ;
- seuls les modules legacy autorises importent `fitmas.final_reply` ;
- le heartbeat Telegram passe par l'adapter runtime par defaut ;
- le registry tools par defaut n'offre plus les tools mutation legacy ;
- les fichiers runtime controles ne lisent plus `WeeklyPlan` / `DayPlan`.

`tests/test_phase8d_bridge_shrink_architecture.py` verifie que :

- `DecisionRuntimeService` existe sans imports legacy ;
- `conversation_pipeline.py` reste sous budget 8D ;
- la route messages vit sous `app/api/routes_messages.py` ;
- `api_messages.py` reste wrapper compat uniquement ;
- les bridges planning, read-only reply et decision shape vivent dans
  `legacy/` ;
- aucun entrypoint heartbeat actif ne repart sur le skill-loop directement.

`tests/test_phase8g_pending_resolution_architecture.py` verifie que :

- `conversation_pipeline.py` ne definit plus les helpers pending actifs ;
- `conversation_pipeline.py` ne lit plus `decision.pending_resolution`
  directement ;
- `legacy/conversation_pending_bridge.py` possede la frontiere pending ;
- le bridge pending ne parse pas le texte utilisateur libre par regex/keywords ;
- `decision/` reste pur.

`tests/test_phase8i_canonical_flag_dogfood_architecture.py` verifie que :

- les flags canoniques Understanding/commands/pending existent et suivent la
  politique de defaults courante ;
- le wrapper dogfood canonique existe ;
- le wrapper active les trois flags canoniques utiles ;
- le wrapper n'active pas le planning cutover canonique par defaut ;
- `decision/` reste pur.

`tests/test_phase8k_canonical_default_lanes_architecture.py` verifie que :

- commands et pending depuis Understanding sont default-on ;
- le planning cutover canonique reste default-off ;
- le gate non-planning canonique est scope ;
- le wrapper defaults n'exporte pas les flags commands/pending ;
- `decision/` reste pur.
