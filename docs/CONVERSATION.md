---
summary: grounding conversationnel, doctrine LLM-first et frontieres de validation pour les messages utilisateur
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
La priorite repo-wide est maintenant la fin de Phase A : coach fiable pour dogfood reel avant toute Phase B progression.
Voir `BUILD-ORDER.md`.

---

## Hierarchie de verite

Ordre strict pour le coach :

1. activite reelle persistee (`Activity`)
2. declaration explicite utilisateur comprise par le LLM et sortie en action structuree
3. correction explicite recente dans la conversation, comprise par le LLM
4. seance planifiee (`ScheduledSession`)

Regle :
- le coach ne presente jamais 4 comme un fait si 1, 2 ou 3 disent autre chose
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
Il doit d'abord etre compris par le LLM.

Regle canonique : voir `LLM-FIRST-CONVERSATION.md`.

### Flux cible

1. **Coach LLM unique** — comprend le tour, lit les tools read-only si besoin,
   puis sort un `CoachDecision` structure.
2. **Validation backend** — parse le JSON LLM, valide schema, resout les refs
   contre la DB, refuse si ambigu.
3. **Writers bornes** — `PlanMutationService`, puis `MemoryMutationService` /
   execution writer quand ils seront poses.
4. **Audit** — events de mutation / memoire / execution.
5. **Reply** — issue du LLM, ou reconstruite depuis un event reel. Aucun helper
   deterministe ne parle a la place du coach.

### Interdits runtime

- pas de regex / keyword / parser sur texte utilisateur libre
- pas de classifieur `low_signal`, `rich_signal`, `ack`, `motivation`
- pas de parsing deterministe `oui/non` sur pending
- pas d'extraction sante / disponibilite / execution / preference hors LLM
- pas de write memoire declenche par pattern texte
- pas de `_sanitize_no_change_reply` ou phrase canned de reparation
- pas de `heuristic OR LLM`

### Actions structurees

Le `CoachDecision` cible porte :

- `memory_actions[]` : sante, disponibilite, preference, contexte utile
- `execution_actions[]` : fait / pas fait, cible a resoudre contre le calendrier
- `plan_action` : `PlanPatch | no_change | requires_confirmation`
- `pending_resolution` : `accept_pending | reject_pending | modify_pending | ignore | needs_clarification`

Le LLM propose ces actions.
Le backend les valide et les applique via services officiels.

### Etat actuel

Phase 0 du chantier LLM-first a retire les plus gros chemins user-text du
runtime conversation :

- `conversation_context.py` ne parse plus claims / non-completion depuis `user_text`
- `user_indication_llm.py` n'a plus de fallback deterministe ni hint lexical
- `user_indications.py` n'expose plus `fallback_interpret_user_indication`
- `conversation_pipeline.py` ne combine plus `heuristic OR LLM`, ne parse plus
  les confirmations pending en `oui/non`, et ne route plus les tools depuis le
  texte user brut
- `_sanitize_no_change_reply` et les classifieurs `low_signal` / `rich_signal`
  ont ete retires
- Phase 1A a ajoute le schema strict dans `CoachDecision` pour
  `memory_actions`, `execution_actions` et `pending_resolution`. Ces champs sont
  acceptes/valides par le parser et visibles dans le prompt, mais les writers ne
  sont pas encore branches.

Dettes restantes :

- `user_indication_llm.py` reste un pre-step LLM separe. Cible Phase 2 : une
  seule sortie `CoachDecision` porte aussi l'extraction aujourd'hui faite par ce
  pre-step.
- Les confirmations pending ne s'appliquent plus par parser deterministe.
  Cible Phase 2 : appliquer `pending_resolution` via writer borne.
- `claim_guard` bloque encore en sortie si une reply promet une mutation sans
  event. Cible : repair LLM contraint puis outage minimal.

### Feedback block_reason typed

Quand `PlanMutationService` rejette une mutation via un pre-hook, l'event bloque est surface avec `block_reason` typed :
- `protected_recovery_target` — move vers recup protegee
- `same_sport_proximity` — quasi-doublon meme sport < 48h
- `occupied_training_target` — jour cible a deja une vraie seance

La reply utilisateur doit etre derivee d'un resultat valide ou reparee par le LLM sous contrainte. Les anciennes replies canned par `_BLOCK_REASON_REPLIES` restent de la dette a retirer pour eviter qu'un helper parle a la place du coach. Chaque blocage alimente aussi `logger.info("mutation_blocked ...")` pour audit.

### Types d'indication

| Type | Exemples | Comportement |
|------|----------|-------------|
| `availability_constraint` | Indispo ponctuelle, voyage, creneau impossible | Le LLM emet `memory_actions` / `plan_action`; le backend resout la fenetre contre le planning reel puis valide avant write |
| `health_signal` | Douleur, gene, fatigue locale | Le LLM emet une action sante structuree; le backend valide et enregistre via writer borne |
| `execution_update` | Activite faite, pas faite, correction | Le LLM emet `execution_actions`; le backend resout la cible et applique seulement si unique |

### Implementation dans api_messages.py

1. Le chemin actuel ne doit plus ajouter de parseur user-text en runtime.
2. La cible est un `CoachDecision` unique qui porte reply, memory actions, execution actions, plan action et pending resolution.
3. Les tools lus par le LLM restent read-only / validation-only.
4. Les writes passent apres validation par services bornes.

Depuis le 26 avril 2026, `decide()` accepte deux formats en compat :
- legacy `MutationDecision` root (`mutation_type`) pour les chemins existants et fallback provider
- `CoachDecision` (`response_type`) pour les nouveaux chemins agentiques

Quand `CoachDecision.response_type=plan_patch`, le pipeline ne fait confiance ni au brouillon `fitmas_message` ni au patch tel quel : il revalide avec `validate_plan_patch`, applique via `PlanMutationService.apply_patch_for_user` seulement si le statut est `valid`, puis répond depuis les `plan_mutation_events` appliqués. Un patch `requires_confirmation` est stocké comme pending confirmation complet. Cible migration : la reponse au pending est resolue par `pending_resolution` LLM, pas par parsing deterministe `oui/non`.

Depuis le 28 avril 2026 :
- `suggest_replan_candidates` est la surface canonique quand le coach a besoin d'une candidate de replan ; `propose_replan` reste alias compat
- `replan_after_constraint` est un workflow de prompt, pas un write tool : tools atomiques utiles → candidate optionnelle → sortie `PlanPatch | no_change | requires_confirmation`
- la candidate ne decide jamais a la place du coach, et le coach ne commit jamais directement

Comportements importants :
- `demain soir` sans seance cible ne doit jamais inventer une mutation sur un autre jour
- `douleur epaule + natation` doit etre compris par le LLM comme sante + contexte sport, puis valide avant write
- reponse courte a clarification (`oui`, `non`, `pas eu le temps`) doit etre interpretee par le LLM dans le contexte de la question precedente
- si un message combine execution, sante et mutation, le LLM porte toutes les actions structurees dans la meme decision

Semantique des statuts calendrier dans les prompts :
- `planned` = prevu, pas encore fait
- `adapted` = modifie/remplace/deplace par FitMAS, pas une preuve d'execution
- `done` = fait, seulement avec activite reelle, claim utilisateur explicite ou commit d'execution
- `skipped` = manque/annule
- `rest` = repos planifie

Le coach ne doit jamais transformer `adapted` en "tu as fait / marque comme fait". Pour dire qu'une seance est faite aujourd'hui, il faut une activite ou une preuve d'execution explicite.

---

## Modules de grounding

| Module | Role | Etat |
|--------|------|------|
| `execution_context.py` | Resume prevu vs reel sur la journee | Pose, pur, teste |
| `execution_evidence.py` | Preuve prudente (observed/claimed/candidate/none) | Pose, utilise par heartbeat |
| `execution_clarification.py` | Demande `faite ou non ?` quand l'incertitude est structurante | Pose |
| `temporal_resolver.py` | Resout des references temporelles structurees | Dette si appele directement sur texte user libre dans le runtime conversation |
| `activity_claims.py` | Ancien extracteur claims depuis texte user | Dette runtime ; doit etre remplace par `execution_actions` LLM |
| `conversation_context.py` | Assemble minimum utile pour le LLM | Dette partielle : ne doit plus parser `user_text` pour claims/non-completion |
| `calibration_needs.py` | Detecte trous d'info qui changent la qualite du plan | Pose, branche heartbeat + messages |
| `user_indications.py` | Types historiques de signaux user | A fusionner dans `CoachDecision.memory_actions` / `execution_actions` |
| `user_indication_llm.py` | Extraction structuree LLM separee | A fusionner dans le LLM coach unique |
| `planning_window_resolution.py` | Grounding contrainte future contre planning reel | Pose, aussi tool read-only |
| `conversation_turn_planner.py` | Classifieur LLM read-only intent primaire + secondaires | Dette cible : fusion dans le Coach LLM unique, pas un pre-cerveau separe |
| `llm_gateway.py` | Parseur JSON robuste (strip fences, balanced prefix, truncated repair) partage par tous les chemins LLM | Pose (eea74e7) |
| `recent_reality.py` | Compteurs `planned / confirmed / claimed / missed_streak` semaine | Injecte dans briefing matin (910f47a) — empeche confabulation de decompte hebdo |
| `skills/heartbeat/context.py` | Bundle verite heartbeat (`YesterdayTruth` / `TodayTruth` / `WeekDigest`) | Injecte dans briefing matin. Separe hier d'un agregat 7j pour eviter de projeter des sorties offplan hebdo sur "hier". |
| `coach_reading_digest.py` | Contexte pre-digere (faits + lens Haiku JSON `sens_du_jour / angle / ne_pas_faire`) | Utilise par `decide()` quand `primary_intent in {plan_lookup, execution_report, availability_constraint}`. Le heartbeat n'appelle plus le lens LLM ; la revue hebdo reutilise seulement les faits deterministes (`lens=None`) pour les sorties offplan detaillees. |

## Ce que le LLM recoit

Oui :
- `temporal_context`
- `today_execution_context`
- `recent_activity_context`
- `relevant_timeline_context`
- `recent_user_corrections`
- `calibration_need` eventuel (comme doute interne, pas question formulaire)
- contexte systeme borne : calendrier, execution verifiee, facts actifs, derniers tours utiles
- tools read-only disponibles selon capability budget, sans classification deterministe du texte user
- dans le briefing matin : `HeartbeatContextBundle` (`YesterdayTruth`, `TodayTruth`, `WeekDigest`) sans lens LLM
- dans `decide()` pour `plan_lookup / execution_report / availability_constraint` : `coach_reading_digest` (faits offplan-aware + lens pre-pass `sens_du_jour / angle / ne_pas_faire`). Ne recoit PAS le digest pour les intents mutation (leur prompt a deja son grounding)

Non :
- tout l'historique brut
- toute la DB brute
- tout le plan brut

---

## Trous restants

1. ~~**Digest hebdo**~~ — pose le 19 avril (`coach_reading_digest.py`, 12b4bf8), puis resserre le 29 avril : `decide()` garde les faits offplan-aware + lens pre-pass ; heartbeat morning utilise maintenant `HeartbeatContextBundle` sans lens LLM ; weekly review reutilise les faits deterministes avec `lens=None`.
2. **Referents** — a dogfooder : est-ce que `30 min`, `celle de demain`, `la piscine` restent ambigus ?
3. **Tools** — `suggest_replan_candidates` est branche comme candidate helper. Prochaines surfaces utiles : `validate_plan_patch` comme validation-only visible au LLM et, plus tard, `get_coach_state` comme macro read-only optionnelle.
4. **Actions execution** — remplacer claims temporels par `execution_actions` LLM + writer borne
5. **Chemins compat** — `WeeklyPlan`/`DayPlan` ne doivent plus etre lus comme verite runtime
6. ~~**Purge zero-determinisme Phase 0**~~ — parseurs user-text runtime,
   low_signal, pending oui/non, `_sanitize_no_change_reply`, `heuristic OR LLM`
   retires. Reste a fusionner les pre-steps LLM dans `CoachDecision`.
7. **Block_reason tied to hardcoded replies** — l'ajout d'une raison pre-hook impose d'editer le dict `_BLOCK_REASON_REPLIES`. Le chantier `PlanPatch` doit plutot remonter `valid / warning / requires_confirmation / blocked` au coach, puis deriver la reply finale depuis validation ou repair LLM.
8. **Actions sante/dispo/preference** — remplacer facts ecrits depuis extracteurs par `memory_actions` LLM + `MemoryMutationService`.

## Regles non negociables

- le coach ne dit jamais "rien fait" si une activite reelle existe dans la fenetre pertinente
- une correction utilisateur immediate prime sur la duree planifiee
- `aujourd'hui` et `demain` resolus depuis le temps local exact
- un prompt ne remplace pas un tool de verite
- le LLM n'ecrit jamais directement en memoire
- les mutations passent toujours par les orchestrateurs
- aucun detecteur deterministe ne lit le texte user libre pour comprendre le tour

## Anti-patterns

- laisser le LLM choisir seul la seance du futur sans grounding
- parser toute la langue naturelle avec des regex
- utiliser des regex comme "hints" sur texte utilisateur libre dans le runtime conversation
- muter le plan directement depuis une extraction LLM
- ecrire un signal utilisateur flou en memoire durable
- appliquer un side-effect DB avant que l'intention principale du tour soit arbitree
- laisser un helper deterministe choisir et formuler le replan a la place du coach
