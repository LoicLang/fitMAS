---
summary: bilan du dogfood API reel du 12 mai 2026, diagnostic DeepSeek/gateway et plan de remediation Phase A
read_when:
  - analyser les echecs du dogfood API reel du 12 mai 2026
  - modifier llm_gateway.py ou les appels JSON DeepSeek
  - separer tool-use et decision JSON finale
  - corriger execution_actions, memory_actions sante ou disponibilite sport-specific
  - verifier les priorites Phase A avant de coder
---

# API Dogfood Reliability - 12 mai 2026

## Contexte

Objectif : tester FitMAS comme Loic va le dogfooder sur Telegram, avec des
scenarios realistes, sans s'appuyer sur les tests existants.

Setup utilise :

- serveur local `uvicorn` sur `127.0.0.1:8097`;
- DB SQLite temporaire :
  `/var/folders/lq/dv0kdg090rs83r4b2wx019lw0000gn/T/fitmas-api-dogfood-ce5vy72x/fitmas-dogfood.db`;
- log serveur :
  `/var/folders/lq/dv0kdg090rs83r4b2wx019lw0000gn/T/fitmas-api-dogfood-ce5vy72x/uvicorn.log`;
- vrais appels LLM via `.env`;
- simulation avec fausse DB, seed de plan/seances/facts/activites;
- 42 checks automatiques, plus relecture manuelle des traces.

Le script etait volontairement ad hoc. Il ne remplace pas les tests du repo :
il sert a capter les ruptures d'integration et de protocole sur des messages
naturels.

## Scenarios couverts

- questions courantes : plan actuel, demain, mercredi, historique recent;
- modifications simples : echange mardi/mercredi, ajout ou remplacement de
  seance;
- imprevus larges : indisponibilite soir, voyage, pas de natation pendant deux
  semaines;
- execution : seance faite aujourd'hui, correction "non c'etait hier", seance
  non faite;
- sante : douleur genou legere, douleur resolue, blessure epaule, maladie;
- generation de semaine complete : onboarding/regeneration avec contraintes;
- memoire : preference horaire, disponibilite durable, faits a retenir;
- continuations courtes et pending : "oui", nouveau sujet alors qu'une pending
  existe, message ambigu.

## Ce qui tient

- Les endpoints API repondent et le setup fake DB suffit pour rejouer des flux
  proches du reel.
- Les lectures factuelles simples passent souvent : le coach sait globalement
  redonner le plan et lire les activites.
- Une activite manuelle matchee a bien pu marquer une seance comme faite.
- Les gros changements planning tombent souvent en pending/confirmation, ce qui
  est preferable a un commit silencieux.
- L'onboarding/regeneration de semaine reste persistable grace au fallback
  conservateur.

## Echecs observes

### 1. Execution comprise mais non persistee

Messages du type :

- `J'ai fait le footing aujourd'hui...`
- `Non c'etait hier`
- `J'ai pas pu faire la seance d'hier...`

Le coach comprend dans la rationale/reponse, mais `execution_actions_per_turn=0`
et `execution_applied=0`. Le writer n'est pas la cause principale :
`ExecutionMutationService` sait appliquer l'action si elle existe.

Conclusion : le trou est entre comprehension LLM et contrat structure.

### 2. Drift factuel sur plan lookup

Une seance natation DB de 40 min a ete restituee comme "50 min environ".

Conclusion : le grounding existe, mais il n'est pas toujours utilise, et le
verifier semantique LLM ne suffit pas pour les chiffres exacts.

### 3. Sante resolue mal traitee

`Petite douleur genou` puis `douleur passee` ne resout pas proprement la memoire.
Le systeme repart vers une adaptation/pending.

Conclusion : la route sante melange trop vite `record_health_signal` et
`PlanPatch`. Pour une resolution, le bon output est memory-only.

### 4. Disponibilite sport-specific mal ciblee

`Je ne peux pas nager deux semaines` a mene a une proposition sur une seance
running/seuil.

Conclusion : les backend candidates sont surtout date/session based. Il manque
des candidats `sport + fenetre`, par exemple toutes les seances swimming sur
14 jours.

### 5. Fragilite provider/tool protocol

Traces observees :

- `truncated_fitmas_message`;
- `unknown_mutation_type`;
- `tool_budget_exceeded`;
- tool calls/provider markup dans la sortie finale;
- fallback Claude;
- replies propres mais actions absentes.

Conclusion : DeepSeek n'est pas necessairement trop faible. Le protocole FitMAS
le met en echec : trop de responsabilites dans un tour, trop de tools, sortie
JSON stricte apres tool-use, et gateway partiellement contradictoire.

### 6. Generated week fallback frequent

`generated_week.week_coherence_fallback` apparait sur les generations testees.

Conclusion : le fallback rend le systeme persistable mais masque une faiblesse
du reviewer/generation policy. Le reviewer runtime `requires_confirmation`
n'est pas adapte tel quel a la generation de semaine.

## Diagnostic gateway verifie dans le code

### System prompt listifie

`ConversationPromptBundle.system` est une `list[dict]`. `decide()` la passe a
`_request_structured_json()`. La voie DeepSeek OpenAI JSON fait ensuite :

```python
{"role": "system", "content": f"{system}\n\n{json_contract}"}
```

Donc DeepSeek peut recevoir une representation Python de liste, pas un system
prompt rendu proprement.

Fichiers concernes :

- `backend/src/fitmas/llm_prompt_builder.py`
- `backend/src/fitmas/llm.py`
- `backend/src/fitmas/llm_gateway.py`

### Exemple JSON legacy global

`_deepseek_json_messages()` injecte encore un exemple :

```json
{
  "mutation_type": "no_change",
  "rationale": "raison courte",
  "fitmas_message": "message utilisateur court"
}
```

Mais les routes modernes attendent souvent :

```json
{
  "response_type": "no_change",
  "rationale": "...",
  "fitmas_message": "...",
  "memory_actions": [],
  "execution_actions": []
}
```

Conclusion : la gateway contredit les PromptContracts modernes et peut pousser
DeepSeek vers `unknown_mutation_type`.

### JSON mode et tool-use divergent

Sans tools, certains appels passent par DeepSeek OpenAI-compatible avec
`response_format={"type":"json_object"}`.

Avec tools, `decide()` passe par la surface Anthropic-compatible, puis attend
un JSON final strict apres plusieurs rounds de tools. Cette phase finale n'a pas
le meme verrou JSON.

Conclusion : le chemin le plus complexe est aussi le moins strict sur la sortie.

### `request_json()` reste texte + parsing

Le turn planner et le week reviewer utilisent encore `gw.request_json()`, donc
Anthropic-compatible text + robust parser, pas forcement JSON mode OpenAI.

Conclusion : il faut distinguer `request_json()` legacy et structured JSON mode.

## Conclusion produit/architecture

Le probleme principal n'est pas "DeepSeek V4 ne sait pas raisonner".

Le probleme actuel est :

```text
un gros contrat metier
+ des tools nombreux
+ une sortie JSON stricte
+ un exemple legacy contradictoire
+ un system prompt parfois listifie
+ des repairs/fallbacks en cascade
```

Le LLM comprend souvent l'intention. Il echoue surtout a compiler cette
comprehension dans le bon champ, au bon format, apres avoir deja lu des tools.

Direction : garder JSON, mais reduire les schemas par lane et separer tool-use
de la compilation finale.

## Plan de remediation

### P0 - Gateway JSON reliability

But : tester DeepSeek sur un protocole propre avant de conclure sur le modele.

Etat 12 mai : implemente localement.

Actions :

- `render_system_text(system: Any) -> str` ajoute dans la gateway;
- DeepSeek OpenAI JSON et Claude structured JSON recoivent un system rendu en
  texte propre;
- l'exemple global `mutation_type` a ete retire de `_deepseek_json_messages()`;
- le contrat global est remplace par une consigne neutre :
  `JSON strict, pas de prose, respecte le schema demande dans le prompt`;
- `schema_hint` optionnel ajoute aux appels structured JSON, fourni par le
  caller, sans import domaine FitMAS dans `llm_gateway.py`;
- `request_json()` prefere maintenant structured JSON mode quand DeepSeek est
  configure et que `request_text` n'est pas monkey-patche, ce qui couvre les
  appels JSON-only comme turn planner et week reviewer en runtime DeepSeek.

Verification P0 :

- test rouge observe avant patch sur system listifie, mutation_type legacy,
  schema_hint absent et `request_json()` legacy;
- `./scripts/test-backend tests/test_llm_gateway_json.py -q` : 25 passed;
- `./scripts/test-backend tests/test_conversation_turn_planner.py tests/test_week_coherence.py tests/test_llm_tools.py -q` : 77 passed.

Mesure attendue :

- baisse `unknown_mutation_type`;
- baisse `truncated_fitmas_message`;
- baisse fallback Claude;
- payloads plus proches des PromptContracts.

### P1 - Rejouer le meme dogfood API

But : isoler le gain gateway avant de refactorer les lanes.

Etat 12 mai : passe de mesure lancee apres P0.

Commandes :

- `./scripts/smoke-a-plus-api --daily --keep-db --db-path /tmp/fitmas-p1-daily.db --port 8097 --timeout 180 --startup-timeout 45`
- `./scripts/smoke-a-plus-api --keep-db --db-path /tmp/fitmas-p1-core.db --port 8098 --timeout 180 --startup-timeout 45`
  - interrompu apres deux scenarios A+ core consecutifs en timeout;
- `./scripts/smoke-a-plus-api --scenario close_turn_ack --generated-workflow onboard_loaded_running --keep-db --db-path /tmp/fitmas-p1-generated.db --port 8099 --timeout 180 --startup-timeout 45`

Resultats :

- Daily-life : `FAIL (4/26)`.
  - `trip_constraint` timeout.
  - `lighten_tomorrow` timeout.
  - `move_easy_then_confirm` timeout sur confirmation.
  - `confirm_without_pending` a commit un `move_session` sur une confirmation
    nue, alors que le scenario attendait no-write.
  - Warning manuel : `fatigue_tomorrow` a rendu `llm_unavailable` mais le smoke
    l'a compte OK; c'est quand meme une regression experience.
- A+ core partiel : les deux premiers scenarios de mutation risquee ont timeout.
  La passe a ete stoppee pour eviter de bruler du temps sur la meme pathologie.
- Generated week : close-turn OK, onboarding/generated workflow timeout avant
  verdict exploitable.

Compteurs logs P1 :

| Log | unknown_mutation_type | truncated_fitmas_message | tool_budget_exceeded | schema_fallback | decide_none | slow tool rows >60s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| daily `.tmp-smoke-a-plus-api-74898.log` | 0 | 0 | 0 | 1 | 1 | 7 |
| core partiel `.tmp-smoke-a-plus-api-76115.log` | 0 | 0 | 0 | 0 | 0 | 2 |
| generated `.tmp-smoke-a-plus-api-76315.log` | 0 | 0 | 0 | 0 | 0 | 0 |

Lecture :

- P0 a corrige la fragilite de forme observee avant : plus de
  `unknown_mutation_type`, plus de `truncated_fitmas_message`, plus de
  `tool_budget_exceeded` dans cette passe.
- Les routes read-only compactes sont rapides et stables :
  `plan_lookup_compact` autour de 4-9s, `activity_highlights_compact` autour de
  4s, `execution_report` autour de 6-10s.
- Le goulot restant est la boucle tool-use/review :
  `health_signal` monte a 98-115s, `plan_negotiation_full` a 87-106s,
  `default_full` a 105s. Les outils lents sont surtout
  `validate_week_coherence` apres un draft.
- Execution reste partiellement non resolue : un tour a produit
  `execution_actions_per_turn=1`, mais `execution_applied=0`. Les autres claims
  execution restent souvent a zero action.
- Memory availability simple s'ameliore : deux tours ont produit
  `memory_actions_per_turn=1` et `memory_applied=1`.
- Generated week ne montre plus de fallback exploitable dans cette passe :
  l'onboarding timeout avant la fin. Le probleme est donc aussi latence/protocole,
  pas seulement reviewer fallback.

Conclusion P1 :

```text
Gateway JSON P0 = gain clair sur erreurs de format.
Reste critique = routes complexes tool-use + week review + confirmations.
```

Comparer avant/apres :

- `schema_invalid`;
- `unknown_mutation_type`;
- `truncated_fitmas_message`;
- `tool_budget_exceeded`;
- fallback Claude;
- production de `execution_actions`;
- production de `memory_actions` sante/resolution;
- drift plan lookup;
- latence et cout.

Gate : ne pas ouvrir un gros refactor si P0 explique deja une part majeure des
echecs.

Decision apres P1 : ouvrir P2. Le refactor doit viser les routes encore lentes
et fragiles, pas les routes read-only compactes.

### P2 - Split tool-use puis compiler JSON

But : ne plus demander tools + decision finale stricte dans le meme appel.

Etat 12 mai : coeur implemente localement dans `decide()`.

Cible :

```text
appel A: tool-use / collecte facts / candidats
appel B: aucun tool / JSON mode strict / schema petit
```

Regles :

- le tool loop ne parle pas au user;
- le compiler final ne peut pas appeler de tools;
- le compiler final recoit les facts/candidats deja structures;
- le backend valide puis commit/pending/block;
- la reponse visible vient des events/facts appliques.

Implementation :

- `_request_json_with_tools()` ne parse plus directement la derniere reponse de
  la phase tool si au moins un tool a ete execute;
- un compiler `_compile_tool_decision_json()` appelle `_request_structured_json`
  sans tools avec :
  - le contexte original;
  - les resultats tools structures, payloads inclus;
  - la derniere reponse de la phase tool comme simple brouillon non fiable;
- si le compiler echoue ou retourne `None`, l'ancien chemin reste fallback :
  parse direct, retry format JSON sans tools, puis repair structuree;
- les traces comptent maintenant ce compiler comme un round-trip LLM et peuvent
  exposer `response_stop_reason=tool_compiler_json`.

Verification P2 locale :

- test rouge observe : un JSON final produit par la phase tool etait parse
  directement au lieu de passer par un compiler;
- `./scripts/test-backend tests/test_llm_tools.py -q` : 60 passed;
- `./scripts/test-backend tests/test_llm_gateway_json.py tests/test_conversation_turn_planner.py tests/test_week_coherence.py tests/test_llm_tools.py -q` : 104 passed.
- `./scripts/test-backend -q` : 902 passed, 11 skipped, 11 subtests passed.

Smoke API reel cible apres P2 :

- `./scripts/smoke-a-plus-api --scenario trip_constraint --scenario lighten_tomorrow --keep-db --db-path /tmp/fitmas-p2-targeted.db --port 8100 --timeout 240 --startup-timeout 45`
  -> `OK (2 check(s))`;
- `./scripts/smoke-a-plus-api --scenario confirm_without_pending --keep-db --db-path /tmp/fitmas-p2-confirm.db --port 8101 --timeout 240 --startup-timeout 45`
  -> `OK (1 check(s))`;
- logs `.tmp-smoke-a-plus-api-78649.log` : les deux tours tool-use finissent
  avec `response_stop_reason=tool_compiler_json`, `fallback_used=false`, pas de
  `unknown_mutation_type`, pas de `truncated_fitmas_message`, pas de
  `tool_budget_exceeded`;
- `lighten_tomorrow` reste long : `validate_week_coherence` prend environ
  48s, tour total environ 76s;
- `trip_constraint` passe les assertions et produit une memoire appliquee, mais
  la clarification visible reste manuellement suspecte : elle parle de plusieurs
  seances de natation alors que le message utilisateur portait sur un voyage.

Reste a mesurer / corriger :

- timeouts `health_signal` / `plan_negotiation_full`;
- production de `memory_actions` et `execution_actions`;
- qualite de clarification sur indisponibilite large;
- scenario `move_easy_then_confirm` et replay daily complet.

Replay `move_easy_then_confirm` apres P2 :

- `./scripts/smoke-a-plus-api --scenario move_easy_then_confirm --keep-db --db-path /tmp/fitmas-p2-move-easy-confirm.db --port 8102 --timeout 240 --startup-timeout 45`
  -> `FAIL (1/1)`, timeout;
- trace : `plan_mutation` / `plan_negotiation_full`, tools
  `get_plan_window`, `draft_move_session`, puis `validate_week_coherence`;
- `validate_week_coherence` declenche un warning JSON decode et consomme la
  majorite du temps; le compiler P2 n'est pas atteint avant timeout client.

Conclusion : P2 stabilise la frontiere tool-use -> JSON, mais ne corrige pas
les tours qui restent bloques dans la boucle planning/review avant la decision.

### P3 - Compilers dedies Phase A

Etat 12 mai : compilers execution/sante/disponibilite implementes localement.

Implementation :

- `conversation_pipeline.py` passe maintenant le `turn_plan` complet dans
  `coach_context`;
- apres un `CoachDecision` valide, `decide()` lance des compilers action-only
  quand l'action attendue manque :
  - `EXECUTION_COMPILER` : produit uniquement `execution_actions`;
  - `HEALTH_MEMORY_COMPILER` : produit uniquement
    `memory_actions.record_health_signal`;
  - `AVAILABILITY_MEMORY_COMPILER` : produit uniquement
    `memory_actions.record_availability`;
- les compilers n'ont aucun tool, interdisent `PlanPatch`, mutation, pending et
  reponse utilisateur;
- les compilers action-only passent par le modele fort (`claude-sonnet-4-6`,
  mappe DeepSeek V4 Pro quand DeepSeek est configure);
- si un compiler memoire retourne `[]` alors que le scope est confirme par le
  turn planner, un retry strict re-evalue seulement la memoire;
- normalisation deterministe ajoutee sur artefact LLM structure :
  `action` est accepte comme alias de `type` pour `memory_actions` et
  `execution_actions`.

Verification P3 locale :

- tests rouges ajoutes pour execution claim -> `execution_actions`, sante
  resolved -> `record_health_signal`, disponibilite + `PlanPatch` ->
  `record_availability`, retry strict quand le premier compiler memoire rend
  `[]`, et alias `action -> type`;
- `./scripts/test-backend tests/test_llm_tools.py -q` : 64 passed;
- `./scripts/test-backend tests/test_llm_gateway_json.py tests/test_conversation_turn_planner.py tests/test_week_coherence.py tests/test_llm_tools.py tests/test_memory_mutation_service.py tests/test_core_flows.py::FitMASCoreFlowsTest::test_coach_decision_execution_action_marks_session_skipped tests/test_core_flows.py::FitMASCoreFlowsTest::test_availability_constraint_persists_as_fact_with_window_anchored_expires_at tests/test_core_flows.py::FitMASCoreFlowsTest::test_execution_action_survives_blocked_plan_patch_reply -q`
  : 116 passed.

Verification P3 vraie API :

- `execution_done_today`, `missed_session_report`,
  `future_evening_unavailable` -> `OK (3 check(s))`;
  - `execution_done_today` : `llm.execution_action_compiler actions=1`;
  - `future_evening_unavailable` : memoire appliquee, mais une passe a encore
    montre le vieux repair sauver l'action apres un compiler vide;
- `shin_pain_signal` -> `OK (1 check(s))`, memoire appliquee dans le tour
  complet quand la decision principale fournit deja l'action;
- smoke compiler isole vraie API, sans tools/DB :
  - health : 1 `record_health_signal`;
  - availability : 1 `record_availability`;
  - execution : 1 `record_execution_update`.

Limites observees :

- les routes `plan_negotiation_full` restent trop lentes et peuvent timeout
  avant d'atteindre les compilers P3;
- `future_evening_unavailable` a encore produit des warnings JSON decode et un
  timeout sur une passe longue;
- `validate_week_coherence` reste le principal goulot quand la route part en
  draft planning.

Conclusion P3 :

```text
Les compilers dedies savent produire les actions manquantes quand ils sont
atteints. Le prochain risque n'est plus le schema action-only, mais le fait que
certaines routes planning n'arrivent pas assez vite a cette phase.
```

### P4 - Sortir `validate_week_coherence` du tool loop conversation

Etat 12 mai : implemente localement.

Decision :

- `validate_week_coherence` n'est plus offert au LLM dans les conversations;
- le tool reste disponible pour `planning` et `heartbeat`;
- le backend garde la review sportive obligatoire avant commit/pending via la
  gate runtime;
- les contrats `conversation_plan_negotiation` et `conversation_health_signal`
  gardent `validate_plan_patch`, mais plus `validate_week_coherence`;
- les prompts conversationnels disent maintenant que la review sportive longue
  est une responsabilite backend, pas un tool a appeler dans le tour.

Verification :

- tests rouges ajoutes sur les contrats, registry conversation/planning,
  prompts workflow et budget canonical conversation;
- `./scripts/test-backend tests/test_prompt_contracts.py tests/test_tool_runtime.py tests/test_conversation_prompt_modules.py tests/test_llm_tools.py tests/test_prompt_snapshots.py tests/test_llm_prompt_builder.py -q`
  : 144 passed;
- `./scripts/smoke-a-plus-api --scenario move_easy_then_confirm --keep-db --db-path /tmp/fitmas-p4-move-easy-confirm.db --port 8110 --timeout 240 --startup-timeout 45`
  -> `OK (1 check(s))`;
- `./scripts/smoke-a-plus-api --scenario shin_pain_signal --scenario future_evening_unavailable --keep-db --db-path /tmp/fitmas-p4-health-dispo.db --port 8111 --timeout 240 --startup-timeout 45`
  -> `OK (2 check(s))`;
- trace smoke :
  - turn 1 `tool_count_offered=16`, tools appeles
    `get_plan_window,draft_move_session`, `total_duration_ms=11843`;
  - turn 2 `tool_count_offered=16`, tools appeles
    `resolve_planning_window,get_plan_window`, `total_duration_ms=16381`;
  - `shin_pain_signal` : `tool_count_offered=7`, tools appeles
    `get_today_context,get_plan_window,get_load_context,draft_replace_session`,
    `total_duration_ms=22042`, `memory_applied=1`;
  - `future_evening_unavailable` : `tool_count_offered=16`, tool appele
    `resolve_planning_window`, `total_duration_ms=11413`, `memory_applied=1`;
  - aucune offre `validate_week_coherence` dans les traces conversation.

Limite :

- la gate backend reste synchrone apres `PlanPatch`; elle peut encore prendre
  du temps avant de produire la pending ou le commit;
- cette passe corrige le timeout du tool loop, pas encore le cout de la review
  backend elle-meme.

### P5 - Reduire les autres tools par route

Etat 12 mai : implemente localement.

Objectif : reduire les routes encore larges sans redonner du parsing
deterministe sur le texte user.

Actions :

- ajout d'un contrat dedie `conversation_availability_constraint`;
- le turn planner route maintenant une disponibilite datee claire
  (`demain soir impossible`, voyage, sport impossible temporairement) vers
  `availability_constraint`, pas `needs_clarification`;
- `availability_constraint` pure devient memory-only : tools
  `resolve_planning_window`, `get_plan_window`, `get_user_constraints`; pas de
  `PlanPatch`, pas de `suggest_replan_candidates`;
- si le user demande explicitement d'adapter/bouger/remplacer, le routeur garde
  la lane `plan_mutation`, avec `availability_constraint` en signal secondaire;
- `health_signal` passe de 7 a 5 tools :
  `get_plan_window`, `get_user_constraints`, `draft_lighten_day`,
  `draft_replace_session`, `validate_plan_patch`;
- `plan_negotiation_full` passe de 16 a 10 tools : plan/window/constraints,
  `suggest_replan_candidates`, `draft_*`, `validate_plan_patch`;
- le fallback canonical conversation utilise aussi cette surface reduite.

Verification :

- tests rouges ajoutes sur contrats, prompt policy availability, prompt system
  availability, budget tools LLM et turn planner;
- suite cible :
  `./scripts/test-backend tests/test_prompt_snapshots.py tests/test_llm_tools.py tests/test_conversation_prompting.py tests/test_conversation_prompt_modules.py tests/test_prompt_contracts.py tests/test_conversation_turn_planner.py -q`
  -> 125 passed, 5 subtests passed;
- smoke API `future_evening_unavailable` apres fix planner/contrat :
  `OK (1 check(s))`, route `availability_constraint`, `tool_count_offered=3`,
  tools appeles `resolve_planning_window,get_plan_window`,
  `response_stop_reason=tool_compiler_json`, `memory_applied=1`;
- smoke API `swim_unavailable_two_weeks` :
  `OK (1 check(s))`, route `plan_mutation`, `tool_count_offered=10`, tools
  appeles `get_plan_window,get_user_constraints,suggest_replan_candidates,draft_replace_session`,
  pending creee, `memory_applied=1`;
- smoke API `future_evening_unavailable + shin_pain_signal + move_easy_then_confirm`
  avant le dernier resserrage availability :
  `OK (3 check(s))`; il a confirme les budgets 5/10 et revele que la dispo
  pure devait etre memory-only.

Limites :

- les tours avec `PlanPatch` restent lents apres la decision, car la gate
  sportive backend est toujours synchrone avant pending/commit;
- `health_signal` peut encore produire une memory action invalide avant que le
  compiler P3 ne repare;
- deduplication des appels tool identiques reste a faire;
- la disponibilite sport-specific multi-seances reste P6.

### P6a - Pending hygiene + disponibilite sport-specific candidates

Etat 12 mai : implemente localement.

Pending hygiene :

- `get_active_pending_mutation_confirmation()` expire d'abord les pending
  depassees, puis exige une seule pending active; si plusieurs lignes actives
  existent, aucune n'est exposee au LLM;
- `accept_pending` revalide `status=pending` et `expires_at` juste avant
  d'appliquer le payload stocke;
- `modify_pending`, `needs_clarification` et choix invalide gardent le meme
  pending ouvert et l'inscrivent dans `ConversationTurnRecord`;
- le cleanup final ne supersede plus un pending explicitement garde ouvert par
  l'outcome;
- aucune comprehension deterministe de `oui/non` n'a ete ajoutee : tout part de
  `pending_resolution` LLM et d'artefacts DB.

Disponibilite sport-specific :

- `ConversationTurnPlan` porte maintenant un artefact typé
  `availability_constraint` (`availability`, `sport_type`, `starts_on`,
  `ends_on`, `scope`);
- `build_backend_candidate_refs_for_turn()` accepte `turn_plan` et, si une
  indisponibilite sport + fenetre est presente, genere uniquement des candidats
  pour les seances planifiees de ce sport dans cette fenetre;
- les candidats generiques `lighten_day` / `replace recovery` sont court-
  circuites dans cette lane pour eviter de cibler une seance running quand la
  contrainte porte sur swimming;
- les patches backend sont references par `candidate_ref`, puis materialises
  par l'evaluator comme avant.

Verification :

- tests rouges ajoutes pour pending ambigu, pending expire, modify pending
  garde ouvert, choix pending invalide garde ouvert;
- test rouge ajoute pour `sport_type=swimming` + fenetre 14 jours : seuls les
  sessions swimming dans la fenetre recoivent un candidat `replace_session`;
- `./scripts/test-backend -q tests/test_core_flows.py -k 'pending or choice' tests/test_conversation_candidate_refs.py tests/test_conversation_turn_planner.py`
  -> 16 passed, 86 deselected.
- `./scripts/test-backend -q` -> 916 passed, 11 skipped, 11 subtests passed.
- smoke API reel `swim_unavailable_two_weeks` :
  `./scripts/smoke-a-plus-api --scenario swim_unavailable_two_weeks --keep-db --db-path /tmp/fitmas-p6a-swim-unavailable.db --port 8112 --timeout 240 --startup-timeout 45`
  -> `OK (1 check(s))`; pending `plan_patch` creee sur la seance DB id 5
  `sport_type=swimming`, remplacée par `new_sport_type=strength`, sans cible
  running.

### P6b - Hygiene tool-loop + memoire dispo sport-specific

Changements 13 mai 2026 :

- `execute_tool_calls()` dedup les appels exacts `tool_name + arguments` dans
  un meme tour. Un doublon recoit quand meme un `tool_result`, pour satisfaire
  le protocole Anthropic, mais le handler n'est pas relance et le budget tools
  n'est pas consomme.
- Le cache de resultats est partage entre les rounds tool-use conversationnels
  et heartbeat.
- `record_availability` accepte `sport_type` et `scope`.
- `MemoryMutationService` produit la cle canonique
  `unavailable_<sport>_<start>_<end>` quand la contrainte est une indisponibilite
  sport-specific datee.
- La candidate-flow qui sort avant `decide()` persiste maintenant aussi une
  memoire disponibilite depuis l'artefact LLM `turn_plan.availability_constraint`
  (`source=turn_plan`). Cela evite le cas "reponse propre + pending creee mais
  contrainte non memorisee".

Verification locale :

- `./scripts/test-backend -q tests/test_tool_runtime.py` -> 24 passed.
- `./scripts/test-backend -q tests/test_memory_mutation_service.py` -> 6 passed.
- `./scripts/test-backend -q tests/test_coach_decision_actions.py` -> 16 passed.
- `./scripts/test-backend -q tests/test_conversation_prompt_modules.py tests/test_llm_prompt_builder.py tests/test_coach_decision_actions.py`
  -> 59 passed.
- `./scripts/test-backend -q tests/test_llm_tools.py -k 'availability or memory or compiler or tool'`
  -> 65 passed.
- `./scripts/test-backend -q tests/test_heartbeat_tool_loop.py tests/test_heartbeat_debug_endpoint.py`
  -> 8 passed.
- smoke API reel `swim_unavailable_two_weeks` :
  `./scripts/smoke-a-plus-api --scenario swim_unavailable_two_weeks --keep-db --db-path /tmp/fitmas-p6b2-swim-unavailable.db --port 8114 --timeout 240 --startup-timeout 45`
  -> `OK (1 check(s))`; DB :
  `working_memory_entries.key=unavailable_swimming_2026-05-13_2026-05-27`,
  `source=turn_plan`, `signal_kind=availability_unavailable`.

### P6c - Plan lookup hard guard + no-session sport constraint

Changements 13 mai 2026 :

- `verify_factual_reply()` garde son verifier LLM, mais `plan_lookup` passe
  maintenant aussi par un hard guard deterministe sur la sortie assistant :
  durees `min/minute`, dates ISO, claims de jour vide/repos, sport et statut
  cites contre `ReplyGroundingPacket`.
- Si le verifier LLM repond `allow` sur une sortie qui dit `50 minutes` alors
  que le grounding DB dit `40 min`, la sortie est rejetee.
- Si composer et brouillon initial restent invalides, `compose_plan_lookup_reply`
  rend un fallback compact depuis le grounding DB au lieu de renvoyer une phrase
  hallucinee.
- La candidate-flow sport-specific s'arrete maintenant avant le candidate
  generator quand `turn_plan.availability_constraint` porte un sport indisponible
  mais qu'aucune seance de ce sport n'existe dans la fenetre. Le tour persiste
  la memoire `unavailable_<sport>_<start>_<end>`, ne cree pas de pending et ne
  mute aucune seance hors sport cible.
- Nouveau smoke nomme :
  `swim_unavailable_no_session`
  (`Je ne peux pas nager du 2026-05-13 au 2026-05-14, adapte si besoin.`)
  pour verifier le cas sans seance swimming touchee dans la fenetre du seed A+.

Verification locale :

- `./scripts/test-backend -q tests/test_final_reply_grounded_verifier.py tests/test_final_reply.py`
  -> 38 passed.
- `./scripts/test-backend -q tests/test_core_flows.py -k 'availability or candidate or plan_lookup or pending or choice'`
  -> 28 passed, 60 deselected.
- `./scripts/test-backend -q tests/test_smoke_a_plus_api.py` -> 11 passed.
- `./scripts/test-backend -q` -> 924 passed, 11 skipped, 11 subtests passed.
- smoke API reel `swim_unavailable_two_weeks + swim_unavailable_no_session` :
  `./scripts/smoke-a-plus-api --scenario swim_unavailable_two_weeks --scenario swim_unavailable_no_session --keep-db --db-path /tmp/fitmas-p6c-swim-rerun2.db --port 8117 --timeout 240 --startup-timeout 45`
  -> `OK (2 check(s))`.
  - `swim_unavailable_two_weeks` cree une pending PlanPatch ciblee natation.
  - `swim_unavailable_no_session` rend `availability_no_affected_session`,
    sans pending ni event planning, avec memoire
    `unavailable_swimming_2026-05-13_2026-05-14`.
- smoke API reel `lookup_current_plan` :
  `./scripts/smoke-a-plus-api --scenario lookup_current_plan --keep-db --db-path /tmp/fitmas-p6c-lookup.db --port 8118 --timeout 180 --startup-timeout 45`
  -> `OK (1 check(s))`, aucune mutation. Note : la trace DeepSeek est sortie en
  `response_mode=reply`; le hard guard est couvert par les tests de
  `compose_plan_lookup_reply` / `verify_factual_reply`, mais il faudra aussi
  surveiller les reponses directes `reply` sur plan lookup en dogfood reel.

### P6 - Corrections domaine

Execution :

- passer `turn_plan.execution_claim` dans `coach_context`;
- si cible unique et `decide()` oublie `execution_actions`, lancer
  `execution_compiler` au lieu d'une grosse repair CoachDecision.

Sante :

- ajouter une lane `health_resolution` ou `health_memory_only`;
- resoudre les facts ouverts par `body_area/signal_kind/status`, pas seulement
  par cle exacte;
- ne pas renouveler une pending adaptation quand le signal vient d'etre resolu.

Disponibilite sport-specific :

- ✅ memoire : `record_availability` porte `sport_type`/`scope` et produit des
  keys canoniques `unavailable_<sport>_<start>_<end>` quand le sport est connu;
- brancher cette memoire sport-specific sur les clarifications execution et les
  futurs replans;
- ✅ si aucune seance du sport cible n'existe dans la fenetre, repondre
  no-change + memoire, sans candidat planning.

Plan lookup :

- ✅ hard guard deterministe sur la reponse sortante pour durees, dates,
  jours/sports/statuts supportes par le grounding DB;
- reste a etendre si besoin : distances, zones physiologiques hors titre de
  seance, et coverage complet des jours vides.

Generated week :

- separer policy generation de policy mutation runtime;
- remplacer `requires_confirmation` par `persistable_with_adjustments` dans le
  contexte generation;
- fallback propre par templates, pas suffixe artificiel.

## Ordre recommande

```text
P0 gateway
P1 replay dogfood
P2 split tools/compiler sur routes qui echouent encore
P3 execution + health/dispo compilers
P4 retirer validate_week_coherence du tool loop conversation
P5 tool budgets par route
P6a pending hygiene + candidats sport-window
P6b memoire sport-window
P6c lookup guard + no-session sport constraint
```

Ne pas ouvrir Phase B progression/prescription pendant ce chantier. Le but reste
Phase A : un coach fiable pour dogfood reel.
