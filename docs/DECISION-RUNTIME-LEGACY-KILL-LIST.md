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

Phase 8Y est livree localement.

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

Phase 8U-A / 8U-B / 8U-C default-enable le provider planning canonique :

- `FITMAS_CANONICAL_PLANNING_PROVIDER` est on par defaut, opt-out `0` ;
- le provider planning trace toujours son etat : `prepared`, `handled`,
  `blocked` ou `fallback_legacy` avec `fallback_reason` ;
- le smoke API hard-fail les tours supportes qui ecrivent ou confirment sans
  trace canonique `handled` ;
- le wrapper
  `scripts/smoke-decision-runtime-canonical-planning-default` prouve le
  default-on sans exporter le flag provider ;
- `LLMUnderstandingService` canonicalise les refs typees observees en prod-like
  dogfood : `session_3`, `date_YYYY-MM-DD`, `day:YYYY-MM-DD`, ISO brut, et
  `target_session_id` porte par `extracted_signals.payload` ;
- `ReferenceResolver` accepte ces variantes machine et continue de refuser les
  references libres non typees ;
- `CoachDecision` reste fallback planning seulement pour les demandes non
  supportees ou les fallbacks explicites documentes.

Phase 8V reduit les fallbacks planning restants sans rouvrir `decide()` :

- `ReferenceResolver` transforme une ref `date:` / `day:` en ref session
  seulement si le role planning exige une seance et qu'une seule
  `ScheduledSession` existe sur cette date ;
- `swap_by_day` est maintenant un scenario obligatoire du smoke canonique ;
- le read-only provider ne peut plus preempter un `plan_mutation` meme si
  l'Understanding sort `general_answer` ;
- le planning provider peut utiliser un `TurnPlan` type pour reconstruire un
  `RequestedPlanChange(kind="swap")` quand l'Understanding a des refs non
  exploitables ;
- les sidecars faibles de planning ne forcent plus un fallback legacy, mais les
  vrais signaux commande restent bloquants.

Phase 8W rend tout fallback actif audit-able avant suppression :

- `decision/fallback_census.py` est le ledger unique des fallbacks runtime
  encore actifs ;
- `CoachDecision` ne peut plus etre appele par `conversation_decide_bridge`
  sans inscrire `owner`, `source`, `reason`, `legacy_path`, `next_step` et
  `severity` dans `turn_context.fallback_census` ;
- le smoke API fail tout `legacy_decide.legacy_skipped=false` sans census ;
- un fallback documente peut rester temporairement, mais un fallback non
  classe est une regression bloquante.

Phase 8X / 8Y retirent l'autorite legacy de la lane `move_hard_close` :

- `TurnPlan.planning_action="move_session"` peut produire un
  `RequestedPlanChange(kind="move")` depuis refs source/target typees ;
- un move vers une date occupee par une seule seance devient une candidate
  canonique `swap_sessions` ;
- `move_hard_close` est dans la liste des scenarios smoke qui exigent
  `canonical_planning_provider.result=handled` et `legacy_skipped=true` ;
- le wrapper default-on execute `move_hard_close`, donc une regression vers le
  candidate flow legacy est bloquante.

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
| `FITMAS_HEARTBEAT_RUNTIME_CUTOVER` | on par defaut, opt-out explicite | route scheduler, `/heartbeat`, debug et ops heartbeat via l'adapter Phase 7 |
| `FITMAS_HEARTBEAT_RUNTIME_VERIFY_ENFORCE` | off par defaut | rend bloquant le verifier commun sur les replies heartbeat adaptees |
| `FITMAS_UNDERSTANDING_RUNTIME_SHADOW` | off par defaut | force le shadow Understanding all-turns pour observability explicite |
| `FITMAS_CANONICAL_NON_PLANNING_CUTOVER` | on par defaut, opt-out explicite | lance Understanding seulement si pending ou commands peuvent consommer l'artefact |
| `FITMAS_CANONICAL_PROVIDER_NON_PLANNING` | on par defaut, opt-out explicite | saute le provider legacy quand l'Understanding non-planning est directement consommable |
| `FITMAS_CANONICAL_READONLY_PROVIDER` | on par defaut, opt-out explicite | saute le provider legacy pour les replies read-only supportees via DecisionOutcome + ReplyComposer |
| `FITMAS_CANONICAL_PLANNING_PROVIDER` | on par defaut, opt-out explicite | saute le provider legacy pour les plan_change supportes par RequestedPlanChange type |
| `FITMAS_COMMANDS_FROM_UNDERSTANDING` | on par defaut, opt-out explicite | autorise les commandes memoire/execution depuis `CoachUnderstanding.extracted_signals` |
| `FITMAS_PENDING_FROM_UNDERSTANDING` | on par defaut, opt-out explicite | autorise la resolution pending depuis `CoachUnderstanding.pending_resolution` |

Ces flags restent des leviers de rollback localises, pas une architecture
parallele.

Flags retires en Phase 9A :

- `FITMAS_PLANNING_RUNTIME_CUTOVER` ;
- `FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER`.

La route historique `CoachDecision -> planning runtime cutover` n'existe plus.
Le planning canonique passe uniquement par
`CoachUnderstanding -> canonical_planning_provider -> PlanningCommandService`.

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

## Phase 9A — Premiere suppression physique

Supprime localement :

- `conversation_pipeline.py` n'appelle plus
  `conversation_planning_bridge.maybe_handle_planning_runtime_cutover` ;
- `legacy/conversation_planning_bridge.py` ne definit plus le handler cutover
  post-`CoachDecision` ;
- `legacy/planning_runtime_adapter.py` ne convertit plus un
  `LegacyCoachDecisionArtifact` en tentative planning runtime ;
- les wrappers actifs n'utilisent plus
  `FITMAS_UNDERSTANDING_RUNTIME_PLANNING_CUTOVER`.
- `scripts/smoke-decision-runtime-cutover` ne re-exporte plus
  `FITMAS_PLANNING_RUNTIME_CUTOVER` et inclut la gate Phase 9A.

Correction prealable imposee par le census :

- un run reel `move_easy_then_confirm` a fallback parce que l'LLM avait emis
  `source_ref=session_id_3` ;
- `domain/planning/reference_tokens.py` centralise maintenant les refs machine
  acceptees pour eviter les divergences entre Understanding, provider canonique
  et resolver.
- un `source_ref` libre ne masque plus un `target_session_id` type dans les
  signaux Understanding ;
- les signaux `preference`/`availability` planning implicites ne bloquent plus
  le provider planning canonique ;
- le bridge `CoachDecision` ne route plus les decisions planning legacy pures
  vers une reponse visible : elles deviennent
  `legacy_decision_contract_disabled` sans write.

Verification locale :

- `./scripts/test-backend -q` passe (`1385 passed, 11 skipped`) ;
- `./scripts/smoke-decision-runtime-canonical-planning-default` passe
  (`10 check(s)`) ;
- le scenario `replace_swim_with_bike` reste un residu planning-owner visible
  en `legacy_decision_contract_disabled`, donc pas encore eligible a une
  suppression legacy plus large.

Prochaines suppressions :

- relire `fallback_census` sur les smokes/dogfood ;
- classer les fallbacks restants par owner ;
- supprimer uniquement les routes dont le census est vide sur lanes couvertes.

## Phase 9B — Planning replace coverage

Gap ferme localement :

- `replace_swim_with_bike` ne tombe plus dans
  `legacy_decision_contract_disabled` ;
- `TurnPlan.replace_session` fournit une source typee quand l'Understanding a
  bien extrait l'intention et le sport, mais laisse des refs libres ;
- les sidecars `preference` scope `sport` sont traites comme metadata planning
  non bloquante quand une demande planning supportee existe ;
- `PlanCandidateBuilder` normalise les artefacts types `velo -> cycling` et
  `facile -> easy` avant de construire `replace_session`.
- `ReferenceResolver` accepte les refs relatives typees `day:tomorrow` /
  `day:demain` et les blocks issus d'une date vide restent user-safe, sans
  fuite de codes internes.

Preuve :

```text
replace_swim_with_bike
response_mode=planning_runtime_pending_confirmation
canonical_planning_provider.result=handled
legacy_decide.legacy_skipped=true
fallback_census=None
```

Cette phase ne supprime toujours pas tout `legacy/` : elle retire un owner
planning concret de la liste des fallbacks actifs.

## Phase 9C — Sport constraint planning coverage

Gap ferme localement :

- `swim_unavailable_two_weeks` rejoint les lanes planning couvertes par le
  provider canonique ;
- la contrainte sport-window devient un artefact machine :
  `sport_window:<sport>:<start>:<end>` ;
- `ReferenceResolver` resout cette ref typee sans parser le texte utilisateur ;
- `PlanCandidateBuilder` construit les remplacements uniquement pour les
  seances planifiees, non terminees et du sport indisponible ;
- la memoire availability reste appliquee dans le chemin canonical planning ;
- `avoid_back_to_back` ne doit plus deriver vers `legacy_decision_contract_disabled`
  quand l'Understanding porte un signal commandable mais un changement planning
  non specifique.

Preuve :

```text
swim_unavailable_two_weeks
response_mode=planning_runtime_pending_confirmation
canonical_planning_provider.result=handled
legacy_decide.legacy_skipped=true
fallback_census=None
memory_writes_json includes unavailable_swimming_2026-05-18_2026-06-01
./scripts/test-backend -q -> 1399 passed, 11 skipped
```

## Phase 9D — Fallback census global et premiere coupe candidate vide

Census global :

- `scripts/smoke_a_plus_api.py` accepte `--fallback-census-json` et ecrit un
  rapport par scenario avec owners, sources, `canonical_planning_provider`,
  `planning_snapshot_flow`, `adaptation_candidate_flow` et refs typees ;
- les smokes core et daily servent maintenant a classer les restes par owner
  avant toute suppression.

Suppression / durcissement livres :

- `availability_no_affected_session` et ses helpers conversation pipeline sont
  retires : ce cas ne doit plus etre une route candidate legacy ;
- le fallback candidate/snapshot legacy est bloque quand le canonique a deja
  compris une demande planning mais que les refs typees minimales sont
  absentes ou peu fiables ;
- `session_id=3` / `session=3` / `id=3` rejoignent les refs machine supportees
  dans `domain/planning/reference_tokens.py` ;
- `planning_snapshot_flow` est maintenant enregistre dans `fallback_census`
  pour que les routes snapshot restantes soient visibles au meme titre que le
  candidate generator.

Preuves :

```text
./scripts/test-backend -q
1405 passed, 11 skipped, 11 subtests passed

./scripts/smoke-a-plus-api --skip-generated-week --fallback-census-json ...
RESULT: OK (15 check(s))

./scripts/smoke-a-plus-api --daily --skip-generated-week --fallback-census-json ...
RESULT: OK (26 check(s))
```

Residus apres 9D :

- planning : `planning_snapshot_flow` reste actif sur certains creates /
  contraintes larges ; il est maintenant classe et devra migrer dans le
  `PlanningDecisionPipeline` canonique avant suppression ;
- planning : `adaptation_candidate_flow` ne peut plus inventer une pending sur
  refs manquantes, mais reste visible comme owner a migrer quand le canonique ne
  sait pas encore resoudre une demande ;
- legacy provider : quelques replies read-only / clarification restent
  `legacy_decide` (`activity_highlight_lookup`, `short_slot_preference`) ;
- reply quality : certaines reponses canoniques sont encore trop brutes
  (`sport=course`, phrases anglaises), a traiter cote composer.

## Phase 9E — Create hard dense migre vers planning canonique

Resultat local 2026-05-19 :

- `add_hard_dense` ne passe plus par `planning_snapshot_flow` ni
  `adaptation_candidate_flow` ;
- `scripts/smoke_a_plus_api.py` classe `add_hard_dense` comme lane qui exige
  `canonical_planning_provider.result=handled` et
  `legacy_decide.legacy_skipped=true` ;
- `TurnPlan.create_session` avec date cible typee peut alimenter le planning
  canonique meme si l'Understanding LLM sort `intent=clarification` parce que
  le sport est manquant ;
- les creates target-only sont maintenant decides dans
  `domain/planning/decision_service.py` :
  - jour de training stable deja occupe -> block canonique ;
  - sport manquant sur jour libre -> block canonique ;
  - create hard sur jour/semaine dense -> block canonique avant evaluation ;
- les intensites typees `high` sont normalisees en `hard` avant candidate
  building/policy.

Preuves :

```text
./scripts/smoke-a-plus-api --skip-generated-week --scenario add_hard_dense --fallback-census-json ...
RESULT: OK (1 check(s))
latest_response_mode=planning_runtime_block
fallback_scenario_count=0

./scripts/test-backend -q
1419 passed, 11 skipped, 11 subtests passed
```

Residus apres 9E :

- planning : contraintes larges type voyage / fenetre generale restent a
  modeliser dans un artefact canonique dedie avant suppression ;
- planning : demandes incompletes non `create_session` doivent encore passer
  par clarification/block canonique owner par owner ;
- reply legacy/read-only : hors scope 9E.

## Phase 9F — Contraintes larges voyage/fenetre generale canoniques

Resultat local 2026-05-19 :

- `trip_constraint` est classe comme lane qui exige le provider planning
  canonique ;
- les payloads typees `availability_constraint` avec `scope=general|time|location`
  et fenetre ISO deviennent :

```text
RequestedPlanChange(kind="constraint_window")
source_ref="availability_window:<scope>:<starts_on>:<ends_on>"
```

- `domain/planning/reference_resolver.py` resout cette ref machine sans
  heuristique sur texte libre ;
- `domain/planning/decision_service.py` retourne un block canonique conservateur
  avant evaluator/policy : il compte les seances actives touchees et refuse de
  recomposer automatiquement une fenetre large tant que le builder multi-jours
  n'existe pas ;
- aucun write planning, aucune pending et aucun fallback snapshot ne sont
  autorises sur cette lane canonique.

Preuves :

```text
./scripts/test-backend \
  tests/test_conversation_canonical_planning_bridge.py::test_turn_plan_general_unavailability_can_supply_constraint_window \
  tests/test_domain_planning_reference_resolver.py::test_resolver_accepts_typed_availability_window_ref \
  tests/test_domain_planning_decision_service.py::test_decide_plan_change_blocks_general_window_before_evaluator \
  tests/test_smoke_a_plus_api.py::test_default_planning_provider_requires_canonical_trace_for_trip_constraint -q
4 passed

./scripts/test-backend tests/test_conversation_canonical_planning_bridge.py \
  tests/test_domain_planning_reference_resolver.py \
  tests/test_domain_planning_decision_service.py \
  tests/test_smoke_a_plus_api.py -q
85 passed

./scripts/smoke-a-plus-api --skip-generated-week --scenario trip_constraint --fallback-census-json ...
RESULT: OK (1 check(s))
latest_response_mode=planning_runtime_block
fallback_scenario_count=0

./scripts/test-backend -q
1424 passed, 11 skipped, 11 subtests passed
```

Residus apres 9F :

- planning : builder multi-jours pour `constraint_window` encore a concevoir ;
- planning : demandes incompletes hors create/window encore a router en
  clarification/block canonique ;
- legacy : `planning_snapshot_flow` reste present tant que le census global
  n'est pas vide sur toutes les lanes planning couvertes.

## Phase 9G — Split disponibilite memoire-only / planning

Resultat local 2026-05-19 :

- une contrainte availability typee pure (`Je voyage de mercredi a vendredi`)
  reste memory-first et ne prepare plus le provider planning ;
- une contrainte availability avec demande d'adaptation (`..., adapte si
  besoin`) reste une lane planning canonique `constraint_window` ;
- le predicat ne lit jamais le texte utilisateur libre : il consomme seulement
  `primary_intent`, `secondary_intents`, `mutation_signal`, `planning_action`
  et `availability_constraint` ;
- le prompt TurnPlan encode explicitement la difference entre disponibilite
  seule et disponibilite + adaptation.

Preuves :

```text
./scripts/smoke-a-plus-api --skip-generated-week --scenario trip_memory_only --fallback-census-json /tmp/fitmas-9g-trip-memory.json --timeout 240 --startup-timeout 45
RESULT: OK (1 check(s))
latest_response_mode=no_change_composed
memory_applied=1
fallback_scenario_count=0
events=0
pending=0

./scripts/smoke-a-plus-api --skip-generated-week --scenario trip_constraint --fallback-census-json /tmp/fitmas-9g-trip-adapt.json --timeout 240 --startup-timeout 45
RESULT: OK (1 check(s))
latest_response_mode=planning_runtime_block
fallback_scenario_count=0
events=0
pending=0

./scripts/test-backend -q
1427 passed, 11 skipped, 11 subtests passed
```

Residus apres 9G :

- planning : `constraint_window` reste en block conservateur ;
- prochain slice logique : builder multi-jours borne, avec pending seulement ;
- deletion physique de `planning_snapshot_flow` attend encore census vide
  global.

## Phase 9H — Candidates `constraint_window` bornes

Resultat local 2026-05-19 :

- les fenetres larges avec demande planning ne sont plus seulement reconnues et
  bloquees : elles peuvent produire un candidat backend borne ;
- la reference canonique devient
  `availability_window:unavailable:<scope>:<starts_on>:<ends_on>`, avec compat
  v1 maintenue dans le resolver ;
- `domain/planning/candidate_builder.py` possede la premiere strategie
  multi-jours : deplacer les sessions actives touchees apres la fenetre,
  préserver l'ordre, ignorer done/skipped/canceled/rest/off ;
- `domain/planning/policy.py` force ces decisions en pending confirmation ;
- `domain/planning/mutation_service.py` reste le seul writer et stocke le patch
  multi-operation comme pending `plan_patch`.

Preuves :

```text
./scripts/test-backend tests/test_domain_planning_reference_resolver.py tests/test_conversation_canonical_planning_bridge.py tests/test_domain_planning_candidate_builder.py tests/test_domain_planning_decision_service.py tests/test_domain_planning_evaluator_policy.py tests/test_domain_planning_mutation_service.py tests/test_smoke_a_plus_api.py -q
109 passed

./scripts/smoke-a-plus-api --skip-generated-week --scenario trip_memory_only --scenario trip_constraint --timeout 420
RESULT: OK (2 check(s))
trip_memory_only: no_change_composed, events=+0, pending=+0
trip_constraint: planning_runtime_pending_confirmation, events=+0, pending=+1
```

Legacy restant apres 9H :

- `planning_snapshot_flow` / `adaptation_candidate_flow` restent a supprimer
  par census quand les lanes couvertes sont vides ;
- les strategies riches de contrainte large ne doivent pas revenir dans les
  prompts ou le pipeline conversation : elles appartiennent a `domain/planning`.

## Phase 9I — Reply multi-op et hygiene prompt/census

Resultat local 2026-05-19 :

- `domain/planning/patch_summary.py` porte le resume user-safe des patchs
  planning, construit depuis les operations machine ;
- les patchs multi-move de `constraint_window` parlent maintenant de plusieurs
  seances et listent toutes les dates ciblees ;
- `planning_outcome_adapter.py` enrichit `DecisionExplanation.impact` avec les
  compteurs d'operations et les dates ciblees ;
- `final_reply_backend.py` utilise la synthese machine deja user-safe au lieu
  de redemander au LLM de reformuler ;
- `tests/test_phase9i_prompt_hygiene_architecture.py` interdit les leaks de
  scenarios de smoke dans les prompts canoniques / modules conversation.

Preuves :

```text
./scripts/test-backend tests/test_domain_planning_patch_summary.py tests/test_planning_outcome_adapter.py tests/test_conversation_planning_runtime_reply_composer.py tests/test_phase9i_prompt_hygiene_architecture.py tests/test_smoke_a_plus_api.py -q
49 passed

./scripts/smoke-a-plus-api --skip-generated-week --scenario trip_memory_only --scenario trip_constraint --fallback-census-json /tmp/fitmas-9i-trip-census.json --timeout 420
RESULT: OK (2 check(s))
fallback_scenario_count=0

./scripts/smoke-a-plus-api --skip-generated-week --scenario trip_memory_only --scenario trip_constraint --scenario swim_unavailable_two_weeks --scenario replace_swim_with_bike --scenario move_easy_then_confirm --scenario swap_by_day --scenario add_hard_dense --fallback-census-json /tmp/fitmas-9i-planning-census.json --timeout 420
RESULT: OK (7 check(s))
fallback_scenario_count=0
```

Legacy restant apres 9I :

- les lanes planning couvertes ne justifient plus un fallback legacy ;
- on ne supprime pas encore un bloc legacy global uniquement sur ces 7 lanes ;
- prochain slice : supprimer la premiere route legacy dont le census owner est
  vide de bout en bout, puis ajouter le test d'architecture qui interdit son
  retour.

## Phase 9J — Suppression runtime de `planning_snapshot_flow`

Resultat local 2026-05-19 :

- `conversation_pipeline.py` ne possede plus la route active
  `planning_snapshot_flow` ;
- les appels `build_planning_snapshot`, `generate_adaptation_proposal` et
  `compile_adaptation_proposal` sont retires de l'orchestrateur conversation ;
- les modules purs `planning_snapshot` et `adaptation_proposal` restent dans le
  repo pour historique/tests hors runtime, mais ne peuvent plus decider dans le
  tour conversation ;
- les tests anciens qui imposaient le snapshot ont ete convertis en tests de
  non-retour snapshot et de census explicite `adaptation_candidate_flow`.

Preuves :

```text
./scripts/test-backend tests/test_core_flows.py::FitMASCoreFlowsTest::test_plan_mutation_no_longer_uses_snapshot_proposal_route tests/test_core_flows.py::FitMASCoreFlowsTest::test_plan_mutation_with_health_secondary_no_longer_uses_snapshot_route tests/test_core_flows.py::FitMASCoreFlowsTest::test_low_confidence_canonical_planning_blocks_legacy_candidate_fallback tests/test_core_flows.py::FitMASCoreFlowsTest::test_high_confidence_canonical_planning_fallback_keeps_legacy_candidate_census_open tests/test_core_flows.py::FitMASCoreFlowsTest::test_missing_typed_source_blocks_legacy_candidate_fallback tests/test_phase9j_snapshot_route_delete_architecture.py tests/test_smoke_a_plus_api.py -q
36 passed

./scripts/smoke-a-plus-api --skip-generated-week --scenario trip_memory_only --scenario trip_constraint --scenario swim_unavailable_two_weeks --scenario replace_swim_with_bike --scenario move_easy_then_confirm --scenario swap_by_day --scenario add_hard_dense --fallback-census-json /tmp/fitmas-9j-planning-census.json --timeout 420
RESULT: OK (7 check(s))
fallback_scenario_count=0
```

Legacy restant apres 9J :

- `adaptation_candidate_flow` reste le fallback planning actif et cense ;
- `planning_snapshot` / `adaptation_proposal` peuvent etre deplaces sous
  `legacy/` ou supprimes plus tard si aucun test/domain use utile ne subsiste ;
- prochaine suppression logique : reduire `adaptation_candidate_flow` par
  owner/census, ou le transformer en block canonique quand la reference typee
  manque.

## Phase 9K — Suppression runtime de `adaptation_candidate_flow`

Resultat local 2026-05-19 :

- `conversation_pipeline.py` ne possede plus la route active
  `adaptation_candidate_flow` ;
- les appels au generateur LLM legacy `plan_patch_candidate_generator` sont
  retires de l'orchestrateur conversation ;
- les helpers `_maybe_handle_plan_adaptation_candidates`,
  `_should_use_plan_adaptation_candidate_flow`, `_adaptation_candidate_trace` et
  le fallback post-`decide()` `plan_adaptation_candidates` ont ete supprimes ;
- les cas non couverts ne peuvent plus creer une pending via le fallback
  candidat : ils doivent etre traites par le PlanningDecisionPipeline,
  bloques/clarifies canoniquement, ou rester visibles dans un census explicite
  hors candidate fallback.

Preuves :

```text
./scripts/test-backend tests/test_core_flows.py tests/test_conversation_candidate_refs.py tests/test_phase9k_adaptation_candidate_flow_delete_architecture.py -q
111 passed

./scripts/smoke-a-plus-api --skip-generated-week --scenario trip_memory_only --scenario trip_constraint --scenario swim_unavailable_two_weeks --scenario replace_swim_with_bike --scenario move_easy_then_confirm --scenario swap_by_day --scenario add_hard_dense --fallback-census-json /tmp/fitmas-9k-planning-census.json --timeout 420
RESULT: OK (7 check(s))
fallback_scenario_count=0
```

Legacy restant apres 9K :

- `plan_patch_candidate_generator.py` reste dans le repo, mais n'a plus de caller
  conversation runtime ;
- `plan_patch_candidate_evaluator.py`, `plan_patch_candidate_reviewer.py` et
  `plan_patch_adaptation_policy.py` restent utilises par `domain/planning/*` ;
- prochaine suppression logique : census global hors lanes couvertes, puis
  classement des modules candidats entre domain utile, legacy pur, ou deletion.

## Phase 9L — Census global core + daily

Resultat local 2026-05-19 :

- ajout de `scripts/decision-runtime-fallback-census-summary` ;
- core smoke complet avec census : 15 scenarios OK ;
- daily smoke complet avec census : 27 scenarios OK ;
- synthese globale :

```text
scenario_count=42
fallback_scenario_count=4
fallback_turn_count=4
owner legacy_provider=1
owner planning=3
source canonical_planning_provider=3
source legacy_decide=1
```

Fallbacks restants :

```text
swap_key_and_recovery       owner=planning         source=canonical_planning_provider
lighten_key_after_fatigue   owner=planning         source=canonical_planning_provider
ambiguous_move              owner=planning         source=canonical_planning_provider
short_slot_preference       owner=legacy_provider  source=legacy_decide
```

Diagnostic :

- les routes snapshot et candidate fallback sont bien mortes ;
- le legacy planning restant vient du canonique qui refuse certains
  `RequestedPlanChange`, puis laisse encore `CoachDecision` repondre ;
- `short_slot_preference` n'est pas planning : c'est un fragment court encore
  non prepare par le provider canonique.

Classement des fichiers restants :

| Fichier | Statut 9L | Action suivante |
| --- | --- | --- |
| `planning_snapshot.py` | historique/pur, aucun caller runtime conversation | deplacer sous `legacy/` ou supprimer apres verification tests |
| `adaptation_proposal.py` | historique/pur, aucun caller runtime conversation | deplacer sous `legacy/` ou supprimer avec `planning_snapshot` |
| `plan_patch_candidate_generator.py` | historique/pur, aucun caller runtime conversation | supprimer ou archiver apres retrait des tests dedies |
| `plan_patch_candidate_evaluator.py` | domain utile | garder ou deplacer sous `domain/planning/` plus tard |
| `plan_patch_candidate_reviewer.py` | domain utile | garder ou deplacer sous `domain/planning/` plus tard |
| `plan_patch_adaptation_policy.py` | domain utile | garder ou deplacer sous `domain/planning/` plus tard |
| `legacy/conversation_decide_bridge.py` | runtime actif | garder jusqu'a disparition des 4 fallbacks |
| `llm/decision_legacy.py` | runtime actif | garder jusqu'a disparition des 4 fallbacks |

Preuves :

```text
./scripts/smoke-a-plus-api --skip-generated-week --fallback-census-json /tmp/fitmas-9l-core-census.json --timeout 900
RESULT: OK (15 check(s))

./scripts/smoke-a-plus-api --daily --skip-generated-week --fallback-census-json /tmp/fitmas-9l-daily-census.json --timeout 1200
RESULT: OK (27 check(s))

./scripts/decision-runtime-fallback-census-summary /tmp/fitmas-9l-core-census.json /tmp/fitmas-9l-daily-census.json --allow-fallbacks --json-out /tmp/fitmas-9l-global-summary.json
```

Prochaine suppression logique :

- Phase 9M : traiter `swap_key_and_recovery`, `lighten_key_after_fatigue` et
  `ambiguous_move` dans le canonique planning ;
- Phase 9N : traiter `short_slot_preference`, puis supprimer/archiver
  `planning_snapshot.py`, `adaptation_proposal.py` et
  `plan_patch_candidate_generator.py`.

## Phase 9M / 9N — Zero fallback core + daily

Resultat local 2026-05-19 :

```text
./scripts/smoke-a-plus-api --skip-generated-week --fallback-census-json /tmp/fitmas-9mn-core-census.json --timeout 900
scenario_count=15
fallback_scenario_count=0
fallback_turn_count=0

./scripts/smoke-a-plus-api --daily --skip-generated-week --fallback-census-json /tmp/fitmas-9mn-daily-census.json --timeout 1200
scenario_count=27
fallback_scenario_count=0
fallback_turn_count=0

./scripts/decision-runtime-fallback-census-summary /tmp/fitmas-9mn-core-census.json /tmp/fitmas-9mn-daily-census.json --json-out /tmp/fitmas-9mn-global-summary.json
scenario_count=42
fallback_scenario_count=0
fallback_turn_count=0
```

Fallbacks elimines :

| Scenario | Ancien owner/source | Nouveau chemin |
| --- | --- | --- |
| `swap_key_and_recovery` | `planning / canonical_planning_provider` | `planning_runtime_pending_confirmation` |
| `lighten_key_after_fatigue` | `planning / canonical_planning_provider` | `planning_runtime_pending_confirmation` |
| `ambiguous_move` | `planning / canonical_planning_provider` | `planning_runtime_unhandled` no-write |
| `short_slot_preference` | `legacy_provider / legacy_decide` | `canonical_clarification` |
| `activity_highlight_lookup` | `legacy_provider / legacy_decide` | `canonical_activity_highlight` |
| `load_review_lookup` | `legacy_provider / legacy_decide` | `canonical_readonly_answer` |

Nouvelles garanties :

- les `RequestedPlanChange` types peuvent etre normalises sans parser le texte
  utilisateur libre ;
- un planning incomplet retourne une clarification/block canonique no-write ;
- les read-only couverts ne sont plus autorises a tomber vers `CoachDecision` ;
- le summary script peut maintenant tourner sans `--allow-fallbacks` sur les
  42 scenarios core+daily.

Suite logique :

- supprimer ou archiver `planning_snapshot.py`, `adaptation_proposal.py` et
  `plan_patch_candidate_generator.py` si les gates d'import confirment qu'ils
  n'ont plus de caller runtime ;
- ajouter des tests d'architecture interdisant le retour des routes
  `planning_snapshot_flow` et `adaptation_candidate_flow` ;
- commencer la reduction physique de `legacy/conversation_decide_bridge.py`
  seulement apres un census etendu hors core+daily.

## Phase 9O — Suppression physique des modules historiques planning

Resultat local 2026-05-19 :

- `backend/src/fitmas/planning_snapshot.py` est supprime ;
- `backend/src/fitmas/adaptation_proposal.py` est supprime ;
- `backend/src/fitmas/plan_patch_candidate_generator.py` est supprime ;
- les tests dedies a ces anciens contrats sont supprimes :
  `tests/test_planning_snapshot.py`,
  `tests/test_adaptation_proposal.py`,
  `tests/test_plan_patch_candidate_generator.py` ;
- `tests/test_phase9o_historical_module_delete_architecture.py` interdit le
  retour de ces modules a la racine `fitmas.*`, leur import par le backend et
  leur preservation par des tests historiques ;
- les primitives encore utiles au domaine restent en place :
  `plan_patch_candidate_evaluator.py`, `plan_patch_candidate_reviewer.py`,
  `plan_patch_adaptation_policy.py` et `plan_patch_candidates.py`.

Preuves :

```text
rg import census for planning_snapshot/adaptation_proposal/plan_patch_candidate_generator
no output

targeted 9O gate
35 passed

./scripts/test-backend -q
1413 passed, 11 skipped, 11 subtests passed

core smoke strict
scenario_count=15
fallback_scenario_count=0
fallback_turn_count=0

daily smoke strict
scenario_count=27
fallback_scenario_count=0
fallback_turn_count=0

global core+daily strict
scenario_count=42
fallback_scenario_count=0
fallback_turn_count=0
```

Suite logique :

- ne pas supprimer `legacy/conversation_decide_bridge.py` ni
  `llm/decision_legacy.py` sur la seule base des 42 scenarios core+daily ;
- lancer un census etendu hors core+daily, puis reduire les derniers usages
  reels du provider legacy par owner ;
- traiter separement les dettes de qualite reply observees en smoke
  (`sport=course`, troisieme personne sur execution, formulations trop brutes).

## Phase 9P — Census etendu avant reduction du provider legacy

Resultat local 2026-05-19 :

- `scripts/smoke_a_plus_api.py` expose maintenant `EXTENDED_SCENARIOS` et
  `--extended` ;
- `scripts/smoke-decision-runtime-extended-census` lance core + daily +
  extended avec rapports `fallback_census` separes, puis un summary global ;
- `tests/test_phase9p_extended_census_architecture.py` verrouille la surface
  extended, l'unicite des noms et l'existence du wrapper ;
- `tests/test_smoke_a_plus_api.py` couvre la selection `--extended` et les
  scenarios nommes extended ;
- pendant le premier run 9P, `close_turn_ack` a revele un fallback
  `legacy_provider / legacy_decide` parce qu'un ack LLM pouvait sortir en
  `trivial_ack` au lieu de `close_turn` ;
- correction appliquee : `trivial_ack` sans pending, sans secondaire et sans
  mutation utilise maintenant le terminal close path. Cette correction reste
  deterministe sur artefact `TurnPlan`, pas sur texte utilisateur brut.

Preuves apres correction :

```text
./scripts/test-backend tests/test_phase9p_extended_census_architecture.py tests/test_smoke_a_plus_api.py -q
38 passed

./scripts/test-backend -q
1421 passed, 11 skipped, 11 subtests passed

core + daily strict
scenario_count=42
fallback_scenario_count=0
fallback_turn_count=0

core + daily + extended discovery
scenario_count=62
fallback_scenario_count=1
fallback_turn_count=1
owner pending=1
source canonical_pending_provider=1
fallback scenario pending_reject_move turns=1
```

Fallback restant :

| Scenario | Owner | Source | Reason | Legacy path | Next step |
| --- | --- | --- | --- | --- | --- |
| `pending_reject_move` | `pending` | `canonical_pending_provider` | `fallback_legacy` | `CoachDecision` | migrer reject/cancel pending vers outcome canonique sans `CoachDecision` |

Decision de deletion :

- `legacy/conversation_decide_bridge.py` ne doit pas encore etre supprime :
  le rejet pending utilise encore `CoachDecision.pending_resolution` ;
- `llm/decision_legacy.py` ne doit pas encore etre supprime ;
- la prochaine suppression viable passe par Phase 9Q :
  `pending_reject_move -> canonical_pending_provider handled`, puis rerun
  strict core + daily + extended ;
- les dettes de qualite reply observees restent separees :
  summaries planning trop generiques (`sport=course`, `Option possible`),
  quelques replies execution en troisieme personne, availability qui suggere
  verbalement sans artifact.

## Phase 9Q / 9R — Pending reject canonique et census strict

Resultat local 2026-05-20 :

- `pending_reject_move` est maintenant traite par le provider pending
  canonique, sans `CoachDecision` ;
- `LLMUnderstandingService` promeut un `pending_resolution` structure en
  `intent=pending_response` quand l'event machine porte `pending_active=True` ;
- cette promotion ne lit pas le texte utilisateur libre : elle valide un
  artefact LLM sur metadata runtime typee ;
- une demande planning reconnue par `TurnPlan` mais non consommable par le
  `PlanningDecisionPipeline` retourne maintenant un block / clarification
  canonique au lieu de fallback legacy ;
- `scripts/smoke-decision-runtime-extended-census` est strict par defaut :
  `--allow-fallbacks` est retire du wrapper.

Preuves :

```text
targeted 9Q/9R gate:
73 passed

./scripts/smoke-decision-runtime-extended-census
scenario_count=62
fallback_scenario_count=0
fallback_turn_count=0
```

Decision de deletion :

- les lanes core + daily + extended ne justifient plus de garder
  `CoachDecision` comme fallback runtime generaliste ;
- ne pas supprimer encore tout `llm/decision_legacy.py` sans audit d'import et
  callers hors corpus ;
- prochaine coupe : reduire `conversation_decide_bridge.py` et le provider
  legacy aux chemins non couverts ou explicitement compat, puis ajouter une
  gate d'architecture anti-retour ;
- les dettes de reply quality ne doivent pas servir d'excuse pour rouvrir un
  fallback legacy.

## Phase 9S — Gate explicite du provider legacy

Resultat local 2026-05-20 :

- `conversation_pipeline.py` verifie maintenant une gate avant
  `run_legacy_coach_decision` ;
- la gate lit seulement des artefacts runtime (`canonical_*`, `legacy_decide`),
  jamais le texte utilisateur libre ;
- une lane canonique peut interdire explicitement le provider via
  `deny_legacy_provider=True` ;
- `fallback_legacy` reste un resultat compat mesure et classe : il n'est pas
  automatiquement bloque, sinon les tests historiques non migres cassent alors
  qu'ils ne representent pas les lanes dogfood couvertes ;
- si la gate bloque, le tour rend un `DecisionOutcome` no-write via
  `ReplyComposer`, avec `legacy_decide.legacy_skipped=True` ;
- `llm/decision_legacy.py` porte maintenant un docstring indiquant qu'il est
  compat provider uniquement.

Preuves :

```text
targeted 9S:
123 passed

full backend:
1441 passed, 11 skipped, 11 subtests passed

./scripts/smoke-decision-runtime-extended-census
scenario_count=62
fallback_scenario_count=0
fallback_turn_count=0
```

Decision de deletion :

- `CoachDecision` n'est plus un fallback generaliste sur les lanes core + daily
  + extended ;
- `conversation_decide_bridge.py` reste necessaire comme adapter provider
  compat, mais son appel est maintenant garde ;
- `llm/decision_legacy.py` ne doit pas encore etre supprime : il exporte encore
  des shims publics onboarding, fact memory, parser/model compat et summaries ;
- prochaine coupe logique : reply quality via `ReplyComposer`, puis audit des
  shims `fitmas.llm` non-conversation pour les sortir de la compat legacy.

## Phase 9T — Reply quality avant grand nettoyage legacy

Resultat local 2026-05-20 :

- les leaks analytiques visibles sont bloques par `coach_voice` ;
- les fallbacks no-change ne recopient plus les brouillons invalides ;
- les claims memoire / execution sans event sont refuses en sortie finale ;
- `create_session` ne sort plus `sport=course` ;
- `Option possible, confirmation recommandee` n'est plus un fallback visible
  pending.

Preuves :

```text
targeted reply:
83 passed

full backend:
1447 passed, 11 skipped, 11 subtests passed

real smoke cible:
3 scenarios OK
fallback census 0
```

Decision de deletion :

- 9T ne supprime pas de legacy physique ;
- le prochain chantier doit etre un vrai cleanup import graph, pas un nouveau
  patch reply : sortir les shims `fitmas.llm` non-conversation et prouver quels
  modules `legacy/` peuvent etre supprimes sans toucher les lanes dogfood.

## Phase 9U — Legacy runtime shrink

Resultat local 2026-05-20 :

- `fitmas.llm` n'est plus un alias module vers `llm/decision_legacy.py` ;
- `legacy/decision_contracts.py` possede les contrats `CoachDecision`,
  `MutationDecision`, pending et action models ;
- les chemins source runtime ne doivent plus importer largement
  `from fitmas.llm import ...` ;
- `LegacyCoachDecisionProvider` est default-off hors opt-in explicite
  `FITMAS_ENABLE_LEGACY_COACH_DECISION_PROVIDER=1` ou injection de test/debug ;
- `decision_legacy.py` descend a 495 lignes et reste compat provider/parser ;
- les scopes machine `travel` / `trip` / `journey` sont normalises comme
  availability window `location` dans le planning canonique.

Preuves :

```text
full backend:
1457 passed, 11 skipped

./scripts/smoke-decision-runtime-extended-census
scenario_count=62
fallback_scenario_count=0
fallback_turn_count=0
```

Legacy restant volontaire :

- `conversation_pipeline.py` reste un orchestrateur volumineux ;
- `legacy/conversation_*` contient encore les bridges de migration ;
- `final_reply.py` reste backend legacy derriere `LegacyFinalReplyBackend`.

## Phase 9V / 9W — LLM import graph et outcomes safe canoniques

Resultat local 2026-05-20 :

- `fitmas.llm` est maintenant un package marker mince ;
- `CoachDecision`, `MutationDecision`, pending et action models ne sont plus
  re-exportes depuis `fitmas.llm` ;
- `llm/legacy_models.py` est supprime ;
- les tests historiques importent le provider explicitement via
  `fitmas.llm.decision_legacy` quand ils testent le legacy ;
- les contrats viennent de `fitmas.legacy.decision_contracts` ;
- `legacy_provider_denied` est remplace par
  `canonical_provider_clarification` ;
- `planning_runtime_unhandled` est remplace par
  `canonical_planning_blocked` ;
- `no_change_safe_fallback` est remplace par
  `canonical_no_action_safe_reply`.

Preuves :

```text
architecture 9V/9W + compat:
30 passed

targeted regressions:
378 passed

full backend:
1464 passed, 11 skipped

core API smoke rerun:
RESULT: OK (15 check(s))

core fallback census:
scenario_count=15
fallback_scenario_count=0
fallback_turn_count=0
```

Observation :

- un run complet `smoke-decision-runtime-extended-census` a observe une
  variabilite provider sur `add_hard_dense` avant de s'arreter ;
- le scenario isole, la sequence courte et le core smoke complet ont ensuite
  repasse ;
- la kill list ne doit pas traiter ce point comme une regression 9V/9W, mais
  comme un signal de hardening provider/smoke pour la suite.

Suite logique :

- Phase 9X : shrinker `conversation_pipeline.py` en deplacant les blocs
  d'outcome safe maintenant canoniques vers des bridges plus petits ou vers
  `decision/` quand la frontiere est pure.

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
