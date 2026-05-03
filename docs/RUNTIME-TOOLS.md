---
summary: contrat des tools runtime FitMAS, limites, registry V1 read-only et métriques associées
read_when:
  - ajouter un tool runtime
  - brancher le LLM sur des tools
  - mesurer la latence ou le coût des tool calls
  - modifier tool_runtime.py ou tool_registry.py
---

# Runtime Tools

## But

Donner au coach FitMAS des tools runtime cibles sans passer a un systeme agentique libre.

Objectifs :
- lire une verite metier ponctuelle quand le prompt statique ne suffit pas
- garder un seul orchestrateur LLM
- rester auditables
- mesurer l'impact reel avant d'augmenter la liberte du modele
- permettre la composition de quelques tools atomiques quand le modele en a besoin
- laisser le LLM choisir les tools utiles ; le code fixe seulement les capacites autorisees

## Ce qu'on fait

- tools LLM-facing `read-only` ou validation-only
- whitelist par pipeline
- 1 registre explicite
- 1 executor borne, qui doit maintenant supporter plusieurs tool calls read-only / validation-only par tour
- metriques systematiques a chaque appel tool
- skills metier documentees quand un workflow se repete

## Ce qu'on ne fait pas

- pas de multi-agent
- pas d'acces DB brut donne au modele
- pas de write tool DB libre expose directement au modele
- pas de boucle infinie de tool calls : max tools et max round-trips par policy
- pas de `multi_mutate` DB libre pour l'instant ; le batch passe par `PlanPatch` valide puis orchestrateur
- pas de skill qui commit directement en DB

## Ce qu'on distingue

Pour la suite, il faut garder 3 couches separées :

### 1. Capacités métier internes

Ce sont des fonctions / modules deterministes reutilisables par :

- conversation
- planner
- heartbeat
- app read models
- ops / CLI

Elles peuvent etre nombreuses et atomiques.

### 2. Runtime tools exposes au LLM

Ils doivent rester :

- assez peu nombreux pour etre navigables
- semantiques
- auditables
- bornes

Le registre runtime est volontairement **plus petit** que le nombre de capacités metier du repo.
Le bon grain est atomique mais metier : `get_plan_window` est bon, `get_everything_blob` est suspect, `run_swim_specific_replan_v7` est trop specifique.

### 3. Orchestrateurs de write / side effects

Les mutations, deliveries et persistance restent sous controle des orchestrateurs.
Un tool runtime ne doit pas devenir un cheval de Troie pour ecrire partout.

## Modules

### `tool_contract.py`

Contrat minimal :
- `ToolCall`
- `ToolResult`
- `ToolContext`
- `ToolSpec`

Evolution V2 :
- typer chaque tool : `read`, `validation`, `candidate`, `write`
- ajouter une policy par intent : max tools, max round-trips, categories autorisees
- garder les writes interdits dans le runtime LLM conversationnel

### `tool_registry.py`

Registry V1 :
- `get_today_context`
- `get_plan_window`
- `resolve_planning_window`
- `get_recent_activities`
- `get_activity_highlights`
- `get_recent_reality_window`
- `get_load_context`
- `get_user_constraints`
- `get_relevant_facts`
- `propose_replan` (a reclasser en `suggest_replan_candidates`)
- `validate_plan_patch` (validation-only, ajoute en Chantier 3A)

Tous ces tools lisent des objets deja charges par l'orchestrateur.
Le registre actuel reste volontairement tres compact.

Direction V2 :
- conserver les tools atomiques utiles
- enrichir leurs descriptions et leurs payloads
- garder `validate_plan_patch` comme tool validation-only : il aide le LLM a tester un `PlanPatch`, mais le backend revalide toujours au commit
- ajouter `get_coach_state` seulement comme macro-tool read-only optionnel, pas comme remplacement des tools atomiques

### `tool_runtime.py`

Role :
- valider le tool demande
- verifier qu'il est autorise pour le pipeline
- executer
- produire une trace metrique

Etat actuel :
- `execute_tool_call()` execute un seul tool pour compatibilite et tests unitaires
- `execute_tool_calls()` execute un batch borne, conserve l'ordre, et renvoie un resultat par call
- `llm.py` accepte plusieurs `tool_use` dans le meme tour et renvoie un `tool_result` pour chaque id

Cible V2 :
- max 3 rounds outilles et max 6 tool calls par tour conversationnel (Chantier 3A)
- tous les `tool_use_id` recoivent un `tool_result`
- les surplus / interdits recoivent une erreur actionnable (`tool_budget_exceeded`, tool inconnu, pipeline interdit)
- aucun tool `write` ne s'execute dans la conversation

### `tool_routing.py`

Role :
- exposer une surface de tools autorisee par pipeline / scope / prompt policy
- borner le nombre de tools et les categories executables
- refuser les tools inconnus, hors budget ou hors pipeline

Dette actuelle :
- `classify_intent()` et les categories deterministes sont historiques
- ils ne doivent plus etre utilises pour comprendre un texte utilisateur libre
- toute classification d'intention, de confirmation, de sante, de disponibilite, d'execution ou de preference doit venir du LLM dans `CoachDecision`

Cible Phase A :
- `route_tools_for_query()` devient une policy de capacites, pas un lecteur du message user
- l'orchestrateur fournit au LLM une whitelist de tools read-only / validation-only
- le LLM demande les tools pertinents
- `execute_tool_calls()` accepte ou bloque chaque demande selon budget

Categories historiques a ne pas reproduire comme classifieur user-text :
| Intent | Tools offerts |
|--------|--------------|
| `casual_chat` | aucun |
| `execution_report` | today_context, recent_activities |
| `plan_negotiation` | today_context, plan_window, load_context, relevant_facts |
| `plan_lookup` | today_context, plan_window |
| `activity_review` | recent_activities |
| `activity_highlights` | activity_highlights, recent_activities |
| `load_review` | load_context, recent_reality_window |
| `fact_recall` | relevant_facts |
| `generic_question` | today_context, plan_window, recent_activities |

V2 :
- le routing ne choisit pas l'intention ; il choisit une **surface autorisee**
- l'execution decide ensuite combien de tools demandes sont acceptes selon la policy
- `plan_negotiation` doit accepter plusieurs reads dans le meme tour, typiquement plan + contraintes + load

### `conversation_prompting.py`

Role :
- choisir une politique de prompt selon l'intent (preferred) ou le routing_reason (legacy)
- reduire le `context dump` pour les requetes de lecture outillees
- garder un comportement full-context pour les cas mutation / conversation libre

Etat actuel :
- chaque `IntentCategory` a une policy dediee (`_INTENT_POLICIES` map)
- `casual_chat` utilise un prompt minimal (pas de timeline, pas de signals)
- `plan_negotiation` utilise le prompt le plus riche (signals + facts + timeline + execution)
- le fallback legacy par `routing_reason` reste pour la compatibilite arriere
- la policy choisie remonte dans les traces tools via `context_policy`
- le chemin live `llm.decide()` utilise maintenant le builder layered plutot que l'ancien builder monobloc

### `prompt_layers.py`

Role :
- structurer le prompt en 5 couches explicites avec budgets token independants
- permettre le prompt caching Anthropic sur les couches stables (L0, L1)
- compacter automatiquement les couches qui depassent leur budget

Couches :
| Level | Nom | Budget | Cacheable | Frequence de changement |
|-------|-----|--------|-----------|------------------------|
| 0 | identity | 300 tok | oui | jamais |
| 1 | profile | 400 tok | oui | par session |
| 2 | plan | 800 tok | non | par semaine |
| 3 | immediate | 600 tok | non | par tour |
| 4 | memory | 500 tok | non | par tour |

### `mutation_hooks.py`

Role :
- valider les mutations avant application (pre-hooks)
- calculer l'impact apres application (post-hooks)
- declencher une recalibration si seuil franchi

Pre-hooks :
- `plausibility_check` : bloque les moves vers une date passee
- `fragile_day_check` : warn si collision avec une seance intense
- `load_coherence_check` : warn si depassement du max hard sessions/week

Post-hooks :
- `calculate_impact` : delta charge, duree, seances cle affectees, recovery perdu
- `build_mutation_log` : entree structuree pour audit
- `recalibration_trigger` : flag si impact significatif

### `api_ops.py`

Role :
- surface operateur separee du tool plane conversationnel
- endpoints `/ops/` pour debug, inspection et triggers manuels
- auth debug distincte

Endpoints :
- `GET /ops/signals` : signaux actifs
- `POST /ops/heartbeat/{kind}` : trigger manuel heartbeat
- `GET /ops/memory` : etat memoire complet
- `GET /ops/mutations/recent` : log mutations recentes
- `GET /ops/tool-stats` : stats d'usage tools
- `POST /ops/reset` : reset destructif

### `tool_metrics.py`

Trace minimale :
- `tool_offered`
- `context_policy`
- `tool_requested`
- `tool_called`
- `tool_count_offered`
- `history_messages_used`
- `prompt_char_count`
- `tool_name`
- `tool_latency_ms`
- `tool_success`
- `tool_error`
- `fallback_used`
- `llm_round_trips`
- `prompt_tokens_estimate`
- `response_tokens_estimate`
- `total_duration_ms`
- `response_stop_reason`

Trace V2 a ajouter :
- `requested_tools`
- `executed_tools`
- `blocked_tools`
- `tool_result_count`
- `tool_loop_round_trips`
- `tool_budget_exceeded`

V1 :
- logs structures uniquement
- pas de table SQL dediee pour l'instant
- `tool_runtime.py` logge toujours l'execution d'un tool concret
- `llm.py` logge maintenant aussi la session tool-use du chat :
  - tools offerts mais non utilises
  - boucle tool complete
  - fallback JSON apres tool loop casse
  - erreur de premier ou second round-trip

## Pipelines

### Conversation

Premiere cible.

Le chat reste sur son pipeline actuel :
- context assembly
- decide
- mutation / reponse

Les tools sont une extension future, pas un remplacement.

Etat actuel :
- le chat peut maintenant executer plusieurs tools read-only / validation-only dans un meme tour
- compat DeepSeek : si le modele emet plusieurs `tool_use`, tous les ids recoivent un `tool_result`
- budget actuel Chantier 3A : max 3 rounds outilles et max 6 tool calls executes ; les tools au-dela du budget recoivent `tool_budget_exceeded`
- activation bornee par `tool_routing.py`
- le prompt du chat passe maintenant par `conversation_prompting.py` + `prompt_layers.py` sur le chemin live
- puis decision structuree JSON comme avant, mais les replies de commit/block passent par le final reply composer post-resultat quand possible
- chaque tour outille produit maintenant une trace session-level exploitable pour mesurer :
  - si les tools ont ete seulement offres
  - si le modele les a effectivement demandes
  - si le 2e round-trip a abouti
  - combien de tokens ont ete consommes sur la boucle

Cas typiques :
- "c'etait quoi ma plus longue sortie ?"
- "il me reste quoi cette semaine ?"
- "qu'est-ce que tu sais de mes contraintes ?"

Cas futur prepare :
- `je ne suis pas dispo demain soir`
- le LLM n'a pas a deviner la seance cible
- il peut s'appuyer sur `resolve_planning_window`

Ce que le chat ne fait pas encore :
- pas de write tool natif pour les mutations simples
- pas de write tool DB libre

Note DeepSeek 3 mai 2026 :
- DeepSeek Anthropic API supporte `tools`, `tool_use`, `tool_result`; `disable_parallel_tool_use` est ignore, donc FitMAS doit accepter plusieurs tool calls en un tour.
- FitMAS desactive `thinking` par defaut sur DeepSeek. Si thinking est reactive, les blocs assistant `thinking` sont preserves dans le replay de tool loop pour respecter la contrainte DeepSeek de renvoyer le contenu assistant complet entre tool calls.
- En smoke reel, DeepSeek peut encore tenter de repartir en prose / syntaxe tool texte apres plusieurs rounds. Le backend garde donc une instruction JSON terminale stricte et une repair qui recoit les payloads tools compacts.
- Avant le repair structure lourd, FitMAS tente maintenant un retry format court dans le meme fil tool-use : "format incorrect, tools termines, meme intention, JSON CoachDecision uniquement". Ce retry peut rattraper une prose simple ou du markup DSML sans traiter ce markup comme un fait utilisateur.
- Micro-chantier experimental : `FITMAS_DEEPSEEK_TOOL_THINKING=1` active `thinking={"type":"enabled"}` uniquement sur la boucle tools conversation. `FITMAS_DEEPSEEK_TOOL_THINKING_EFFORT=high|max` pilote `output_config.effort`. Par defaut, rien ne change.
- Smoke reel du 3 mai 2026 : `thinking=high` ameliore parfois la prudence factuelle mais augmente fortement la latence sur les tours planning (30-56s observes) et ne supprime pas les repairs JSON. Garder en flag de bench, pas en defaut Telegram.
- Smoke reel retry format du 3 mai 2026 : sur `compound_non_completion_swap`, le retry court n'est pas suffisant a lui seul. Les echecs restants sont souvent des payloads metier invalides (`requires_confirmation` sans `PlanPatch`) plutot qu'un simple format non-JSON ; le repair structure reste donc necessaire.

Mise a jour 24 avril 2026 :

- le produit a besoin de capacites d'action plus fortes, mais pas d'un write tool DB libre expose directement au modele
- la bonne forme d'action est `PlanPatch` :
  - le LLM lit la verite
  - le LLM draft un patch structure
  - `validate_plan_patch` classe le patch
  - l'orchestrateur commit via `PlanMutationService`
- slice 1 livre : `backend/src/fitmas/plan_patch.py` + `PlanMutationService.apply_patch_for_user`
- `commit_plan_patch` reste donc une capacite orchestrateur, pas un runtime tool Anthropic executant des writes pendant le tool call
- le tool runtime peut exposer `get_coach_state`, `suggest_replan_candidates` et `validate_plan_patch` car ils sont read-only / validation-only
- le passage a un vrai write tool ne devra arriver qu'apres permissions explicites, transactions, replay tests et audit events robustes

Recalage produit :
- la cible court terme n'est pas un coach sportivement parfait
- la cible est un agent fiable pour planifier, reagir aux questions/remarques/contraintes et ne jamais mentir sur les actions
- les regles sportives sont des garde-fous gradues, pas le coeur du raisonnement conversationnel
- le succes se mesure d'abord par : comprend le contexte, lit la verite, repond au bon fil, applique ou refuse proprement

Recalage multi-tool DeepSeek :
- DeepSeek V4 via l'endpoint Anthropic-compatible peut demander plusieurs tools dans une seule reponse
- `disable_parallel_tool_use` est ignore cote DeepSeek
- donc FitMAS ne doit pas compter sur "un seul tool demande" comme invariance provider
- la bonne invariance devient : **tous les tools demandes sont soit executes si autorises, soit explicitement bloques, et tous les ids ont un result**

Recalage stabilite DeepSeek :
- les smokes reels du 24 avril valident l'API DeepSeek, mais pas encore la stabilite du format final
- le pattern fragile est : tool-use OK, puis reponse finale en prose au lieu de JSON
- le fallback actuel recupere, mais ce doit devenir un contrat explicite :
  - `message_json`
  - repair pass structuree courte
  - fallback Claude si repair impossible
  - metrics provider et repair visibles
- avant de donner plus d'autonomie au runtime multi-tool, FitMAS doit garantir qu'une decision finale non-JSON n'est jamais acceptee silencieusement

Spike OpenAI SDK 24 avril :
- `scripts/spike_deepseek_openai_sdk.py` teste DeepSeek via `openai.OpenAI(base_url="https://api.deepseek.com")`
- `deepseek-v4-flash` :
  - JSON direct OK avec `response_format=json_object` et budget de sortie suffisant
  - tool-use puis JSON final OK si on rejoue `reasoning_content`
  - enums FitMAS pas garanties sans validation locale
  - final function call possible, a confirmer en matrice plus large
- `deepseek-chat` :
  - final function call possible
  - tool-use puis JSON final moins stable dans le spike
- `deepseek-v4-pro` :
  - probe JSON OpenAI-compatible local non concluant
- decision : ajouter un adapter OpenAI-compatible comme capability ciblee, pas remplacer tout le gateway d'un bloc
- garde-fou complexite :
  - `llm_gateway` reste la seule frontiere provider
  - les modules tools/conversation manipulent un contrat structure, jamais un SDK
  - l'adapter OpenAI-compatible est active par capability, pas par migration globale
  - le spike reste un outil de mesure ; le code produit doit rester petit et testable

### Heartbeat

Pas encore branche sur le runtime tools.
Le heartbeat reste surtout deterministic + contexte preassemble.

### Planning

Pas encore branche sur le runtime tools.
Le planner V2 doit d'abord passer par `planning_state.py` et `PlanningDecision`.

## Decision CTO

Le bon ordre :
1. prompt 2 zones + caching sur la partie stable
2. policy de capacites : tres peu de tools offerts, sans classifier le texte user
3. runtime tools read-only semantiques + metrics
4. tool use borne dans `decide()` pour quelques questions de lecture
5. transcript structure de session avant toute sophistication plus large

Addendum 24 avril :

6. ✅ `PlanPatch` comme langage d'action du coach (contrat pur pose, branchement LLM a suivre)
7. ✅ `validate_plan_patch` comme validation training graduee (premier wrapper pre-hooks pose)
8. ✅ commit par orchestrateur seulement (`PlanMutationService.apply_patch_for_user`, commit seulement si `valid`)
9. ✅ stabilisation DeepSeek structured-output + fallback Claude trace
10. ✅ runtime tools V2 multi-tool borne, car le smoke DeepSeek a prouve que le single-call coupe une intention outillee correcte
11. skill metier `replan_after_constraint` pour encoder le workflow, sans write DB libre

Addendum 25 avril :

12. ✅ `create_session` entre dans le langage d'action : le LLM peut demander une creation de seance future, validee par `PlanPatch`, puis committee par `PlanMutationService` avec event audite
13. ✅ cap suivant prepare : brancher `CoachDecision` / `PlanPatch` comme sortie principale de `decide()`, sans exposer de write tool libre

Addendum 26 avril :

14. ✅ `CoachDecision(plan_patch)` branche dans la conversation via orchestrateur
15. ✅ confirmation pending avec `PlanPatch` complet serialise ; dette 30 avril : remplacer le parsing `oui` par `CoachDecision.pending_resolution`
16. ✅ skill `replan_after_constraint` formalisee dans le prompt + reclassification de `propose_replan`

Addendum 30 avril :

17. `docs/LLM-FIRST-CONVERSATION.md` devient le contrat conversation : le LLM choisit les tools utiles, le routing borne seulement la surface autorisee.
18. Aucun router, classifier ou fallback local ne doit lire le texte utilisateur libre pour determiner intention, confirmation, sante, disponibilite, execution ou preference.

## Direction pour la prochaine tranche

Le prochain chantier tools doit partir de la question :

`quelle capacite metier partagee manque au repo ?`

et non :

`quel tool par sport veut-on exposer au modele ?`

Direction recommandee, recalee :

### 0. Stabilisation provider / structured output

- DeepSeek-first, Claude fallback
- repair JSON obligatoire apres tool-use si la reponse finale est en prose
- aucune decision finale non-JSON acceptee silencieusement
- metrics `provider / model / json_repair_used / provider_fallback_used`
- matrice smoke reelle avant/apres sur les cas dogfood

### 1. Runtime multi-tool borne

- max 3 tools executes par tour conversationnel
- max 2 round-trips LLM outilles
- execute uniquement `read`, `candidate`, `validation`
- bloque `write`
- trace tout

### 2. Substrate partage par capacite

Premieres familles candidates :

- `reality`
- `planning`
- `session_drafting`
- `session_analysis`
- `plan_review`

### 3. Adapters par sport derriere ce substrate

Les sports implementent les memes contrats, par exemple :

- running
- cycling
- swimming
- climbing
- strength

On ne donne pas directement au modele un catalogue `run_* / swim_* / bike_*`.

### 4. Wrappers runtime eventuels ensuite

Si une capacite est utile au LLM, on expose ensuite un wrapper borne, par exemple :

- `resolve_target_session`
- `review_current_week`
- `build_session_draft`
- `analyze_completed_activity`
- `get_coach_state`
- `validate_plan_patch`
- `suggest_replan_candidates`

### 5. Skills metier

Une skill est un workflow outille et borne, pas un nouveau cerveau deterministe.

Etat actuel :
- aucune skill runtime formelle n'est encore branchee comme objet separe
- la doctrine existe dans les docs et dans le prompt conversationnel
- `suggest_replan_candidates` est le tool canonique route pour les candidates ; `propose_replan` reste alias compat
- le workflow est explicite dans le prompt/routing, sans write tool

`replan_after_constraint`

Role :
- reconnaitre les contraintes d'indisponibilite / sport ferme / voyage / continuation de replan
- appeler les tools atomiques utiles
- produire un `PlanPatch` ou un `no_change` justifie
- demander confirmation seulement pour les vrais trade-offs

Interdits :
- aucun commit DB
- aucun texte final promettant une action avant validation/commit
- pas de menu d'options si les tools suffisent pour trancher

Notes de sequencing :

- `transcript structure > compaction` a ce stade
- les tools doivent rester etroits : plan, reel recent, charge, contraintes, contrat seance
- decomposition par capacite avant decomposition par sport
- pas de write tools directs avant d'avoir des permission tiers propres sur les mutations ; commit via orchestrateur en attendant

Pas de liberte large du modele avant d'avoir :
- mesure
- logs
- cas d'usage prouvés
