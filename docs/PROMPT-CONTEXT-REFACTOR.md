---
summary: chantier global prompt/contexte pour transformer les prompts accumules en contrats LLM explicites
read_when:
  - auditer les prompts conversation ou heartbeat
  - reduire les decide returned None
  - modifier llm_prompt_builder.py ou prompt_layers.py
  - modifier conversation_prompting.py ou les policies par intent
  - modifier heartbeat roles ou heartbeat final speech
  - refactorer le contexte donne a decide, final_reply, verifiers ou heartbeat
  - ajouter un PromptContract ou ConversationContextPack
---

# Prompt / Context Runtime Refactor

## Statut

Prochain chantier dogfood apres la stabilisation A+ adaptation candidates.

Objectif : passer d'une architecture de prompts accumules a une architecture de
**contrats LLM explicites**. Chaque appel LLM doit savoir :

- quel est son role ;
- quel contexte il a le droit de voir ;
- quels tools et actions il peut utiliser ;
- quel output est attendu ;
- quelle couche parle reellement au user.

Non-objectifs :

- pas de Phase B progression/prescription ;
- pas de gros refactor memoire ;
- pas de parser deterministe sur texte utilisateur libre ;
- pas de sanitizer de sortie pour masquer une mauvaise frontiere de contexte.

## Diagnostic

FitMAS a deja les bonnes briques :

1. `coach_voice.py` centralise la voix, les few-shots bons/mauvais et les guards
   user-facing.
2. `ConversationPromptPolicy` module une partie du contexte par intent.
3. `prompt_layers.py` pose un debut de couches identity/profile/plan/memory.
4. La conversation et le heartbeat chargent beaucoup de verite runtime :
   calendrier date, activites, facts actifs, signaux, bundle coach, contrat de
   planning, realite recente, grounding packet.

Le probleme n'est pas "un mauvais prompt". Le probleme est que le prompt est
devenu le produit. FitMAS fonctionne encore trop par accumulation intelligente,
pas par contrat clair entre phases.

### Symptome recents

- Conversation : `_CONVERSATION_SYSTEM_TEXT` reste un mega-prompt qui melange
  identite, voix, verite, memoire, tools, mutation, confirmation, examples,
  JSON contract et compat legacy.
- `build_layered_conversation_prompt()` ajoute les layers autour du mega-prompt
  au lieu de le remplacer vraiment.
- Les policies par intent changent surtout les blocs contextuels, pas assez le
  contrat cognitif donne au modele.
- `decide()` recoit encore beaucoup de parametres separes et reconstruit la
  hierarchie du contexte implicitement.
- `fitmas_message` existe encore dans la phase decisionnelle ; le runtime doit
  ensuite verifier, reparer ou remplacer cette parole selon ce qui a vraiment
  ete commit.
- Heartbeat : les roles sont mieux bornes, mais les builders injectent encore
  de gros blocs voix/few-shots et demandent souvent au LLM de parler directement
  au user.
- Exemple dogfood 8 mai : le briefing a bien compris le fond sportif, mais a
  recycle des labels internes de facts (`health`) dans le message visible. Ce
  n'est pas un bug de sport, c'est une fuite de format de contexte.

## Doctrine

```text
Moins de prompt par phase.
Plus de contrats types.
Plus de contexte structure.
Plus de composition finale post-runtime.
```

Le LLM ne doit pas etre la source de verite brute. Il peut comprendre,
explorer, reviewer et composer, mais chaque appel doit etre borne par un
contrat local.

Architecture cible :

```text
turn_planner
-> context_pack_builder
-> prompt_contract
-> decision_llm ou composer terminal
-> runtime validation / commit / block / pending
-> final_reply_composer
-> factual/style/read-only verifier
-> user
```

Pour les mutations planning :

```text
LLM propose decision / PlanPatch / candidate
-> runtime valide, simule, commit ou bloque
-> final composer explique le resultat reel
```

Pour les conversations simples :

```text
LLM intent leger ou runtime read-only truth
-> composer terminal
-> user
```

## Frontieres Non Negociables

- Pas de regex, keywords ou parser deterministe pour comprendre le texte user :
  intention, confirmation, douleur, fatigue, disponibilite, execution, cible
  planning.
- Determinisme autorise uniquement sur artefacts structures : JSON LLM, IDs, DB,
  permissions, validation, commit, audit, TTL, snapshots.
- Un helper ne produit pas de reponse finale visible sauf outage ou resume d'un
  evenement reellement commit.
- Pas de scrub de sortie type `replace("[health]", "")`. Si un label interne
  fuit, on corrige la frontiere entre contexte interne et message visible.
- Les guards de sortie restent utiles, mais ils ne doivent pas devenir la couche
  principale de qualite conversationnelle.

## Cible Technique

### 1. Prompt Snapshots Et Observabilite D'abord

Avant de refactorer, capturer l'existant.

Livrables :

- snapshots de prompts par route ;
- taille system/user prompt par route ;
- blocs contextuels inclus ;
- tools/actions autorises ;
- mode de sortie attendu ;
- trace des `decide() returned None`.

Raisons normalisees pour `decide()` None :

```text
no_client
provider_error
timeout
empty_output
tool_loop_failed
tool_result_missing
invalid_json
schema_invalid
repair_failed
fallback_failed
voice_guard_invalid
factual_verifier_blocked
prompt_too_long
unknown
```

### 2. PromptContract Par Route

`ConversationPromptPolicy` dit combien de contexte injecter. Il manque un
contrat qui dise ce que le LLM est autorise a faire.

Contrat minimal :

```python
@dataclass(frozen=True, slots=True)
class PromptContract:
    route: str
    capability: str                 # read_only, draft_action, write_after_validation, terminal_text
    allowed_tools: tuple[str, ...]
    allowed_actions: tuple[str, ...]
    required_truth_blocks: tuple[str, ...]
    optional_truth_blocks: tuple[str, ...]
    output_schema: str              # text, CoachDecision, PlanPatchCandidateSet, FinalReply
    final_reply_mode: str           # direct, post_runtime, terminal_composer
    max_context_blocks: tuple[str, ...]
```

Exemples :

```text
close_turn
  capability = terminal_text
  tools = []
  actions = []
  truth = conversation_frame
  output = final_text
  final_reply_mode = terminal_composer

plan_lookup
  capability = read_only
  tools = read_plan_window, get_session_detail
  actions = []
  truth = temporal + plan_window + grounding_packet
  output = grounded_final_reply
  final_reply_mode = terminal_composer

execution_report
  capability = write_after_validation
  tools = read_execution_reality, resolve_target_session
  actions = record_execution_update, record_memory
  truth = temporal + execution_reality + active_thread
  output = CoachDecision
  final_reply_mode = post_runtime

plan_negotiation
  capability = draft_action
  tools = planning reads + validate_plan_patch + candidate helpers
  actions = PlanPatch draft / pending_resolution
  truth = planning + execution + constraints + pending
  output = CoachDecision or PlanPatchCandidateSet
  final_reply_mode = post_runtime

health_signal
  capability = write_after_validation
  tools = health/fatigue/context reads + planning candidates if mutation requested
  actions = record_health_signal, PlanPatch candidate
  truth = working_memory + recent_execution + planning window
  output = CoachDecision, then optional candidate flow
  final_reply_mode = post_runtime
```

### 3. ContextPack Type

Objectif : arreter de passer 15 parametres separes a `decide()` et aux builders.
Le premier diff doit etre read-only et sans changement comportemental.

```python
@dataclass(frozen=True, slots=True)
class ConversationContextPack:
    turn_scope: TurnScope
    temporal: TemporalContext
    planning: PlanningContext
    execution: ExecutionReality
    memory: MemoryContext
    active_thread: ActiveThreadContext
    coach_profile: CoachProfileContext
    tool_budget: ToolBudget
    grounding: ReplyGroundingPacket | None
```

Decoupage memoire conceptuel, sans migration structurelle dans ce chantier :

```text
DurableProfile
  objectifs, sports, preferences stables, contraintes recurrentes

WorkingMemory
  douleur recente, fatigue recente, indisponibilite temporaire, voyage

ExecutionReality
  fait, pas fait, partiel, offplan, claims utilisateur, activites reelles

ConversationFrame
  question ouverte, pending confirmation, fil actif, hypothese en cours
```

### 4. Decoupage Du Mega-Prompt

Le mega-prompt `_CONVERSATION_SYSTEM_TEXT` doit devenir une composition de
modules. Les routes ne doivent plus toutes recevoir le meme contrat global.

Modules cibles :

```text
identity_voice_system
truth_hierarchy_system
turn_scope_capability_system
action_contract_system
output_schema_system
tool_use_system
final_speech_system
```

Regle : un intent recoit seulement les modules dont il a besoin.

Exemples :

```text
close_turn
  identity_voice + terminal_text + conversation_frame
  pas de plan_patch, pas de memory_actions, pas de tool-use contract

plan_lookup
  identity_voice + truth_hierarchy + read_only + factual_output
  pas de mutation contract

plan_negotiation
  identity_voice + truth_hierarchy + draft_action + PlanPatch schema + tool-use
  pas de terminal speech libre avant runtime
```

### 5. Split Decision Vs Final Reply

La parole visible ne doit plus etre produite trop tot.

Etat actuel utile :

- `final_reply.py` compose deja `close_turn`, `no_change`, `plan_lookup`,
  `plan_adaptation` et plusieurs replies post-mutation.
- `conversation_pipeline.py` applique deja runtime validation / pending /
  commit avant plusieurs composers.

Cible :

```text
decision_llm
  -> intention / patch / actions / pending_resolution / message_intent
runtime
  -> applique, bloque, demande confirmation, ou no-op
final_reply
  -> parle seulement a partir du resultat reel
```

Pour les actions planning, `fitmas_message` devient provisoire ou disparait du
chemin final. Pour les routes purement conversationnelles, le composer terminal
peut parler directement.

### 6. Heartbeat Terminal Composer

Le bug `health` dans le briefing est rattache a ce chantier.

Flux cible :

```text
heartbeat role
-> truth bundle structure
-> heartbeat intent / angle / facts utiles
-> compose_heartbeat_reply()
-> read-only judge + factual verifier + style guard
-> Telegram
```

Le heartbeat ne doit pas demander a son role builder de produire directement le
message final. Le role prepare le contexte, l'angle et les limites ; le composer
terminal transforme en texte naturel.

`HeartbeatReplyContext` minimal :

```python
@dataclass(frozen=True, slots=True)
class HeartbeatReplyContext:
    role: str
    capability: str
    temporal: TemporalContext
    today_truth: dict
    yesterday_truth: dict | None
    week_digest: dict | None
    plan_window: tuple[PlanWindowFact, ...]
    active_facts: tuple[StructuredFact, ...]
    angle: str | None
    draft: str | None
    forbidden_claims: tuple[str, ...]
```

Exigences :

- les categories internes (`health`, `constraint`, `execution`, `patch`,
  `runtime`, `fallback`) sont des metadonnees, jamais du texte visible ;
- le composer ne claim aucun changement planning sans event commit ;
- le message reste court, naturel, non-fiche ;
- le fallback outage est rare et ne recopie pas les fact lines brutes.

### 7. Memoire : Cadrage Leger Seulement

Ce chantier ne refond pas la memoire. Il empeche seulement la memoire d'arriver
dans les prompts comme une soupe de facts.

Livrables raisonnables :

- rendre visible dans les snapshots quelle famille de memoire est injectee ;
- differencier durable / working / execution / conversation frame dans le
  contexte rendu ;
- ne pas changer le schema DB ni les policies de retention dans ce chantier.

## Roadmap Recommandee

### Phase 0 - Baseline Observability

But : savoir ce qu'on donne vraiment aux LLM avant de tout deplacer.

Livrables :

- logger prompt size, route, intent, provider, policy, contract, tool budget ;
- logger les raisons normalisees de `decide() returned None` ;
- ajouter snapshots golden pour conversation + heartbeat ;
- ajouter debug dump lisible pour comparer prompt avant/apres.

Tests :

```text
test_prompt_snapshot_close_turn_has_no_plan_contract
test_prompt_snapshot_plan_lookup_has_read_only_truth_contract
test_prompt_snapshot_plan_negotiation_has_plan_patch_contract
test_heartbeat_briefing_snapshot_contains_read_only_capability
test_decide_none_trace_records_failure_reason_and_events
```

### Phase 1 - PromptContract Registry

But : declarer les droits et outputs par route sans changer encore le rendu.

Fichiers probables :

```text
backend/src/fitmas/prompt_contracts.py
backend/src/fitmas/conversation_prompting.py
backend/src/fitmas/llm.py
backend/src/fitmas/skills/heartbeat/roles.py
tests/test_prompt_contracts.py
```

Sortie attendue : chaque appel LLM peut etre inspecte avec son contrat.

### Phase 2 - ContextPack V0

But : regrouper le contexte en objets structures, puis rendre les blocs par
contract.

Fichiers probables :

```text
backend/src/fitmas/context_pack.py
backend/src/fitmas/conversation_pipeline.py
backend/src/fitmas/llm_prompt_builder.py
backend/src/fitmas/prompt_layers.py
tests/test_context_pack.py
```

Regle : V0 read-only, aucun changement comportemental voulu.

### Phase 3 - Modular Conversation Prompt

But : remplacer progressivement `_CONVERSATION_SYSTEM_TEXT` par des modules.

Ordre conseille :

1. extraire identity/voice ;
2. extraire truth hierarchy ;
3. extraire capability scope ;
4. extraire action contracts ;
5. extraire output schemas.

Tests : snapshots doivent montrer que `close_turn`, `plan_lookup` et
`plan_negotiation` ne recoivent plus le meme system prompt.

Etat 8 mai 2026 :

- `identity/voice`, `truth hierarchy`, `turn scope`, `tool workflow`,
  `action contract` et `output schema` sont maintenant des modules separes.
- Les prompts conversation sont composes par `PromptContract`.
- Les routes `read_only` recoivent un schema `CoachDecision` no-action.
- `casual_chat` et `trivial_ack` restent, pour l'instant, dans `decide()` :
  ils doivent donc utiliser la policy `conversation_casual_chat`, sans tools,
  avec un `CoachDecision` no-action. Ils ne doivent pas heriter du contrat
  `close_turn` terminal.
- `close_turn` pur continue d'etre bypass via composer terminal dans
  `conversation_pipeline.py`, mais son prompt contract de fallback reste un
  `CoachDecision` no-action pour les cas ou un pending/calibration force un
  passage par `decide()`.
- Snapshots actifs : `conversation_plan_lookup`, `conversation_close_turn`,
  `conversation_casual_chat`, `heartbeat_briefing`.
- Heartbeat briefing : les facts actifs ne rendent plus les categories
  internes (`health`, `constraint`, etc.) dans les lignes recopiables du prompt.
- Heartbeat briefing/reminder/review/signal : le role produit encore un brouillon, mais
  `morning_briefing()`, `pre_session_reminder()`, `weekly_review()` et `signal_check()` le font maintenant repasser par
  `compose_heartbeat_reply()` avec un `HeartbeatReplyContext` structure avant
  read-only judge et factual verifier.
- Les role builders heartbeat ne portent plus les few-shots voix complets :
  ils ont un contrat de brouillon factuel, et la voix finale vit dans
  `compose_heartbeat_reply()`.
- Les facts, signaux et references sport dynamiques heartbeat ne sont plus
  colles dans le system prompt : ils sont rendus dans le contexte user du role
  draft.
- `format_signals_for_prompt()` ne rend plus les `kind`/`severity` internes :
  le brouillon recoit seulement des puces lisibles basees sur les summaries.
- Le `HeartbeatReplyContext` du role `signal` ne transmet plus `kind`/`severity`
  au composer terminal, seulement le summary humain du signal.
- Les turns conversation `llm_unavailable` enregistrent maintenant
  `context.decide_none.reason` avec une raison normalisee quand `decide()`
  rend `None`.
- `decide_none.events` conserve la chaine d'echec utile (`schema_invalid`,
  `repair_failed`, `fallback_failed`, `tool_loop_failed`, `empty_output`, etc.)
  pour diagnostiquer la cause racine, pas seulement le dernier fallback.
- Chaque appel `decide()` logue aussi `llm.decide_prompt_trace` avec route,
  intent, policy, contract, budget tools et tailles de prompt, sans exposer le
  prompt brut.

### Phase 4 - Final Speech Boundary

But : reduire la dependance de la parole finale a `CoachDecision.fitmas_message`.

Routes prioritaires :

```text
plan mutation applied / blocked / pending
execution_report with execution_actions
health_signal with memory_actions
casual_chat simple
```

La conversation finale doit partir du resultat runtime, pas du brouillon de
decision.

### Phase 5 - Heartbeat Terminal Composer

But : rattacher heartbeat au meme modele de sortie que conversation.

Livrables :

- `HeartbeatReplyContext` ; ✅ brique isolee ajoutee
- `compose_heartbeat_reply()` ; ✅ brique isolee ajoutee
- `morning_briefing()` -> role draft -> `compose_heartbeat_reply()` -> judges ;
  ✅ branche pour le briefing matin
- `pre_session_reminder()` -> role draft -> `compose_heartbeat_reply()` -> judges ;
  ✅ branche pour le rappel pre-seance
- `weekly_review()` -> role draft -> `compose_heartbeat_reply()` -> judges ;
  ✅ branche pour la revue hebdo read-only
- `signal_check()` -> role draft -> `compose_heartbeat_reply()` -> judges ;
  ✅ branche en `candidate_only` pour les signaux proactifs sans commit autonome
- role builders heartbeat allegés : ✅ plus de `COACH_VOICE_FEW_SHOTS_*` dans
  les prompts de brouillon ; le composer terminal applique la voix finale
- facts, signaux actifs et references sport heartbeat dans user context : ✅ le
  system reste un contrat stable
- signal prompt block sans tags internes recopiables (`kind`, `severity`, emoji
  statut) : ✅
- signal composer context sans tags internes recopiables : ✅
- log prompt size / route / intent / policy / contract / tool budget : ✅
- trace `decide_none.reason` dans `ConversationTurn.context_json` : ✅
- trace `decide_none.events` avec chaine schema / repair / fallback / tool-loop
  : ✅
- conversion des active facts en structures non recopiables telles quelles ; ✅
- debug dump heartbeat `flow` lisible : `truth`, `draft`, `composer`,
  `judges`, `decision`, `final` : ✅
- debug dump conversation ops lisible : `truth`, `draft`, `composer`,
  `runtime`, `decision`, `final` depuis le turn persiste : ✅
- debug dump conversation ops pour mutation/pending : ✅ `runtime` expose
  `pending_confirmation_record` et les `plan_mutation_events` correles, et
  `composer` distingue les reponses runtime `pending_confirmation`,
  `mutation_result` ou `mutation_blocked`
- fallback outage propre ;

Regression cible :

```text
active facts:
  category=health, value="tension tibias..."
  category=health, value="etirements mollets..."

message final:
  parle des tibias naturellement
  ne contient pas "health"
  ne ressemble pas a une fiche interne
```

### Phase 6 - Hardening Et Reduction

But : supprimer le contexte inutile, pas seulement le renommer.

Mesures :

- taille moyenne des prompts par route ;
- taux `decide() None` par route/provider ;
- taux repair JSON ;
- taux verifier/factual guard ;
- taux fuite jargon interne ;
- nombre de routes encore sur mega-prompt complet.

## Snapshots A Creer

```text
tests/snapshots/prompts/
  conversation_close_turn.txt
  conversation_casual_chat.txt
  conversation_plan_lookup.txt
  conversation_execution_report.txt
  conversation_health_signal.txt
  conversation_plan_negotiation.txt
  conversation_pending_resolution.txt
  final_reply_plan_lookup.txt
  final_reply_post_commit.txt
  heartbeat_briefing.txt
  heartbeat_reminder.txt
  heartbeat_review.txt
  heartbeat_signal.txt
```

Chaque snapshot doit inclure :

```text
route
contract
system prompt
user prompt
tool budget
truth blocks
output schema
```

## Tests De Non Regression

Contexte :

```text
test_context_pack_for_close_turn_has_no_plan
test_context_pack_for_plan_lookup_includes_plan_window
test_context_pack_for_execution_report_includes_recent_claims
test_plan_mutation_prompt_includes_pending_confirmation_when_present
test_health_signal_prompt_includes_working_memory_not_full_profile_dump
```

Contrats :

```text
test_close_turn_contract_has_no_tools_or_actions
test_plan_lookup_contract_is_read_only
test_plan_negotiation_contract_allows_plan_patch_draft_only
test_heartbeat_briefing_contract_is_read_only
test_heartbeat_signal_contract_can_emit_pending_but_not_commit
```

Sortie finale :

```text
test_final_reply_never_claims_commit_if_runtime_blocked
test_pending_reply_never_says_change_is_done
test_heartbeat_terminal_composer_does_not_leak_fact_categories
test_heartbeat_terminal_composer_blocks_internal_jargon
test_plan_lookup_final_reply_preserves_dates_days_statuses
```

Dogfood scenarios :

```text
Okay chef
nickel merci
J'ai quoi demain ?
redonne le plan actuel
oui je confirme
samedi
ok mais genou douloureux
Parfait on fait ca
T'es sur du planning que tu m'annonces ?
```

## Critères De Fin

Le chantier est ferme quand :

- chaque route LLM principale a un `PromptContract` inspectable ;
- les snapshots existent et echouent si un prompt grossit ou change de contrat
  sans intention explicite ;
- `decide() returned None` produit une raison normalisee ;
- `close_turn`, `plan_lookup`, `no_change`, adaptation candidates et heartbeat
  ont une frontiere finale claire ;
- le heartbeat ne parle plus directement depuis des facts bruts ;
- `_CONVERSATION_SYSTEM_TEXT` n'est plus le system prompt universel ;
- aucun nouveau determinisme sur texte utilisateur libre n'a ete introduit ;
- `./scripts/test-backend -q` et les smokes dogfood ciblés passent.

## Phrase Guide

FitMAS ne doit plus avoir "un gros prompt coach". Il doit avoir un runtime qui
sait quel cerveau appeler, avec quel contexte, quels droits, quel output, et qui
parle au user seulement apres avoir stabilise la verite du tour.
