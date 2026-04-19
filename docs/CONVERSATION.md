---
summary: grounding conversationnel, hierarchie de verite, pipeline indications utilisateur et modules de contexte
read_when:
  - corriger un bug de contexte conversationnel
  - modifier api_messages.py
  - modifier heartbeat.py ou signals.py
  - ajouter un nouveau type de signal utilisateur
  - traiter une indisponibilite future, un signal sante ou un update d'execution
  - brancher des tools de lecture pour le coach Telegram
---

# Conversation

## But

Rendre le coach Telegram factuellement fiable et reactif quand il parle de ce qui a ete fait, de ce qui etait prevu, et du contexte temporel.

Le sujet n'est pas d'ajouter "plus de contexte" au LLM.
Le sujet est de lui donner une verite structuree et parcimonieuse.

## Priorite relative

Le gros du grounding conversationnel est pose.
La priorite repo-wide a bouge vers substrate partage et weekly reality digest.
Voir `BUILD-ORDER.md`.

---

## Hierarchie de verite

Ordre strict pour le coach :

1. activite reelle persistee (`Activity`)
2. declaration explicite utilisateur dans le message courant
3. correction explicite recente dans la conversation
4. seance planifiee (`ScheduledSession`)
5. heuristique faible

Regle :
- le coach ne presente jamais 4 ou 5 comme un fait si 1, 2 ou 3 disent autre chose
- une confirmation future (`demain piscine j'y serai`) ne declenche pas de mutation si le planning est deja coherent
- si l'utilisateur aligne `demain` avec un jour explicite, le systeme repond avec la date absolue

## Sources de verite

| Source | Force | Usage | Limites |
|--------|-------|-------|---------|
| `Activity` | Plus forte sur le reel | Sport, duree, distance, FC, TSS, date, lien session | Pas toujours rattachee a une seance |
| `ScheduledSession` | Plus forte sur le plan date | Seance prevue, sport, duree cible, statut | Statut centre sur le prevu, pas le reel hors plan |
| `CoachMessage` | Contexte conversationnel | Derniere consigne, correction, referents | Historique trop brut si pas structure |
| `UserFact` | Contraintes stables | Dispo, preferences, patterns | Pas un journal d'activite |
| `WeeklyPlan`/`DayPlan` | Template/compat seulement | Generation planner, onboarding | Ne doit plus etre verite runtime |

---

## Pipeline indications utilisateur

Un message utilisateur n'est pas une instruction directe.
Avant toute mutation, FitMAS produit un objet structure.

### Flux

1. **Interpreter** — `user_indication_llm.py` produit un `UserIndication` structure
2. **Grounder** — `planning_window_resolution.py` ancre la contrainte contre le vrai planning
3. **Decider** — `replan_from_life_change.py` ou `adaptation.py` produisent des actions autorisees
4. **Expliquer** — `llm.py` formule la reponse naturelle

### Triage du tour

`conversation_turn_planner.py` est un classifieur LLM read-only (`claude-haiku-4-5`) invoque avant les side-effects d'execution. Il produit un `ConversationTurnPlan` structure.

Entrees bornees :
- `user_text`
- `temporal_summary`, `execution_summary`, `activity_claim_summary`, `signal_summary`

Sortie (`ConversationTurnPlan`) :
- `primary_intent` — whitelist `{trivial_ack, casual_chat, plan_lookup, plan_mutation, execution_report, availability_constraint, health_signal, calibration_answer, preference_signal, needs_clarification}`
- `secondary_intents` — whitelist `{non_completion_claim, activity_claim, availability_constraint, health_signal, plan_mutation, preference_signal, calibration_answer}`
- `mutation_signal`, `execution_claim`, `needs_clarification`, `clarification_question`, `confidence`
- propriete derivee `has_plan_mutation = mutation_signal OR primary=plan_mutation OR 'plan_mutation' in secondary`

Role :
- detecter l'intention principale du tour
- conserver les intentions secondaires quand le message est compose
- proteger les demandes de mutation implicites (`vendredi a la place ?`) que les marqueurs deterministes ne savent pas fiabiliser

Interdits :
- aucun write DB
- aucune reply finale
- aucune mutation planning
- le parseur JSON cascade (`llm_gateway._robust_json_loads`) absorbe les queues tronquees et les prose residuels; un payload ambigu retourne None → fallback heuristique seul

### Arbitrage heuristique vs LLM

Pour `plan_mutation`, deux signaux sont combines :
- `heuristic_plan_mutation_request` — marqueurs lexicaux (`decale`, `swap`, `remplace`, `echange`, etc.) dans `api_messages._looks_like_plan_mutation_request()`
- `llm_plan_mutation_request` — `turn_plan.has_plan_mutation`

Regle (closure faille A + B) :
- `plan_mutation_request = heuristic OR llm` — aucun des deux ne peut silencieusement supprimer l'intention
- divergence (`heuristic != llm`) → `logger.warning("pipeline.intent_divergence ...")` avec etat `True|False|unavailable` pour audit offline
- `llm=unavailable` (timeout / JSON vide) ne dowgrade pas le flag a False : l'heuristique seule suffit a declencher l'arbitrage LLM

Consequences sur les early-exits deterministes quand `plan_mutation_request == true` :
- pas de resolution auto de `non_completion_claim` (le claim reste du contexte)
- pas de `targeted_execution_clarification`
- pas de `execution_contestation_reply`
- pas d'adaptation sante silencieuse — le fait est persiste, le LLM arbitre
- `week_scope_reply` et `no_candidate_reply` deviennent du grounding injecte dans le prompt decide, avec fallback deterministe si le LLM echoue
- `adaptation` candidate devient du contexte passe a decide plutot que d'etre appliquee directement

Pour les messages composes `health_signal + plan_mutation`, le fait sante est persiste et injecte dans le contexte, mais l'adaptation sante automatique ne court-circuite pas le tour.

### Failles conversation documentees (15-17 avril 2026)

| Faille | Symptome | Closure | Ref commit |
|--------|---------|---------|-----------|
| A | Heuristique et LLM peuvent diverger sur `plan_mutation` | `OR` des deux flags + WARNING structure sur divergence | b78db28 |
| B | Heuristique flagge mutation, LLM l'ignore silencieusement | Force le routage LLM des contextes availability/adaptation/health quand heuristic=True | af54eda |
| C | Aucun classifieur d'intention avant decide() | `conversation_turn_planner` — classifieur read-only dedie | e79d734 |
| D | Erreurs LLM masquees (logs generiques) | `_classify_llm_exception` → labels stables `timeout / rate_limit / bad_request / auth / connection / api_other / json_parse / unknown` + `llm_plan_mutation_state = unavailable\|True\|False` | e81c3da |

### Feedback block_reason typed

Quand `PlanMutationService` rejette une mutation via un pre-hook, l'event bloque est surface avec `block_reason` typed :
- `protected_recovery_target` — move vers recup protegee
- `same_sport_proximity` — quasi-doublon meme sport < 48h
- `occupied_training_target` — jour cible a deja une vraie seance

La reply utilisateur est derivee du `block_reason` via `_BLOCK_REASON_REPLIES` (conversation_pipeline.py), pas improvisee par le LLM. Chaque blocage alimente aussi `logger.info("mutation_blocked ...")` pour audit.

### Types d'indication

| Type | Exemples | Comportement |
|------|----------|-------------|
| `availability_constraint` | Indispo ponctuelle, voyage, creneau impossible | Resolve planning window → replan si seance cible claire |
| `health_signal` | Douleur, gene, fatigue locale | Normalise signal → ecrit fait sante → adaptation protective |
| `execution_update` | Activite faite, correction | Reconcile le reel → claims d'activite / memoire courte |

### Implementation dans api_messages.py

1. Presque tous les messages non triviaux passent par le parseur structure
2. Si `health_signal` fort : ecrit fait sante → adaptation protective → fallback conservateur si LLM ne sort rien de propre
3. Si `availability_constraint` future : resolve fenetre → replan borne → repond honnetement si rien a bouger
4. Sinon : pipeline conversation normal

Comportements importants :
- `voyage`, `deplacement` = `availability_constraint`
- `demain soir` sans seance cible ne doit jamais inventer une mutation sur un autre jour
- `douleur epaule + natation` force adaptation hors natation
- reponse courte a clarification (`oui`/`non`) interpretee dans le contexte de la question precedente
- si un message combine un claim d'execution et une demande explicite de mutation (`swap`, `echange`, `decale`, `deplace`, `remplace`, `change`), le claim enrichit le contexte mais ne produit pas de reply finale et ne doit pas muter la seance avant arbitrage LLM
- les contestations d'execution pures peuvent encore etre resolues par l'orchestrateur, mais les messages composes donnent la priorite a l'intention de mutation

---

## Modules de grounding

| Module | Role | Etat |
|--------|------|------|
| `execution_context.py` | Resume prevu vs reel sur la journee | Pose, pur, teste |
| `execution_evidence.py` | Preuve prudente (observed/claimed/candidate/none) | Pose, utilise par heartbeat |
| `execution_clarification.py` | Demande `faite ou non ?` quand l'incertitude est structurante | Pose |
| `temporal_resolver.py` | Resout aujourd'hui/demain/hier/ce soir depuis timezone user | Pose, pur, teste |
| `activity_claims.py` | Extrait sport/duree/date/certitude des messages | Pose, fusionne claims, teste |
| `conversation_context.py` | Assemble minimum utile pour le LLM | Pose, utilise par api_messages |
| `calibration_needs.py` | Detecte trous d'info qui changent la qualite du plan | Pose, branche heartbeat + messages |
| `user_indications.py` | Contrat ferme des signaux user | Pose |
| `user_indication_llm.py` | Extraction structuree LLM | Pose |
| `planning_window_resolution.py` | Grounding contrainte future contre planning reel | Pose, aussi tool read-only |
| `conversation_turn_planner.py` | Classifieur LLM read-only intent primaire + secondaires | Pose (e79d734), gate orchestration pipeline |
| `llm_gateway.py` | Parseur JSON robuste (strip fences, balanced prefix, truncated repair) partage par tous les chemins LLM | Pose (eea74e7) |
| `recent_reality.py` | Compteurs `planned / confirmed / claimed / missed_streak` semaine | Injecte dans briefing matin (910f47a) — empeche confabulation de decompte hebdo |

## Ce que le LLM recoit

Oui :
- `temporal_context`
- `today_execution_context`
- `recent_activity_context`
- `relevant_timeline_context`
- `recent_user_corrections`
- `calibration_need` eventuel (comme doute interne, pas question formulaire)
- `turn_primary_intent` + `turn_secondary_intents` depuis le planner (pour router la prompt policy et le budget de tools dans `llm.decide()`)
- contexte `availability` (week_scope / no_candidate) injecte si `primary_intent in {availability_constraint, plan_mutation}`
- contexte `adaptation` candidate injecte si `turn_plan.has_plan_mutation` et une adaptation deterministe existe
- dans le briefing matin : `recent_reality` compteurs (planned/confirmed/claimed/missed_streak) pour empecher la confabulation de decompte hebdo

Non :
- tout l'historique brut
- toute la DB brute
- tout le plan brut

---

## Trous restants

1. **Digest hebdo** — manque un digest canonique de semaine pour eviter de recomposer transcript + activites + events a plusieurs endroits
2. **Referents** — a dogfooder : est-ce que `30 min`, `celle de demain`, `la piscine` restent ambigus ?
3. **Tools** — garder bornes, ne pas exposer trop de catalogue avant d'avoir stabilise les besoins reels
4. **Claims temporels** — observer si d'autres claims meritent la meme approche que les claims d'activite
5. **Chemins compat** — `WeeklyPlan`/`DayPlan` ne doivent plus etre lus comme verite runtime
6. **Turn planner fragile quand LLM indispo** — en cas de `llm=unavailable`, seule l'heuristique lexicale decide. Les intentions implicites (`vendredi a la place ?`) peuvent etre ratees. Envisager retry borne ou cache de decisions sur phrasings recurrents.
7. **Block_reason tied to hardcoded replies** — l'ajout d'une raison pre-hook impose d'editer le dict `_BLOCK_REASON_REPLIES`. Faire emerger une reply builder parametree quand le set depassera 4-5 entrees.
8. **Couche health_signal secondaire non arbitree** — un `health_signal` en intention secondaire d'un tour `plan_mutation` est injecte comme fact, mais il n'existe pas encore de contrat clair sur la facon dont le LLM doit trancher (prioriser sante ? refuser la mutation ?).

## Regles non negociables

- le coach ne dit jamais "rien fait" si une activite reelle existe dans la fenetre pertinente
- une correction utilisateur immediate prime sur la duree planifiee
- `aujourd'hui` et `demain` resolus depuis le temps local exact
- un prompt ne remplace pas un tool de verite
- le LLM n'ecrit jamais directement en memoire
- les mutations passent toujours par les orchestrateurs
- les detecteurs de claims ne doivent pas voler le tour quand le message contient aussi une intention planning explicite

## Anti-patterns

- laisser le LLM choisir seul la seance du futur sans grounding
- parser toute la langue naturelle avec des regex
- muter le plan directement depuis une extraction LLM
- ecrire un signal utilisateur flou en memoire durable
- appliquer un side-effect DB avant que l'intention principale du tour soit arbitree
