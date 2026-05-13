---
summary: doctrine zero determinisme sur texte utilisateur libre et plan de migration conversation LLM-first
read_when:
  - modifier conversation_pipeline.py
  - modifier api_messages.py
  - modifier conversation_context.py
  - modifier conversation_turn_planner.py
  - ajouter une action memoire, sante, disponibilite, execution ou preference
  - corriger un bug de comprehension du message utilisateur
---

# LLM-First Conversation

## Regle dure

Aucun sens humain ne vient du code.

Le texte utilisateur libre ne doit jamais etre lu par un regex, keyword,
classifieur deterministe, short-circuit ou parser maison pour decider :

- intention
- negation
- sante / douleur / fatigue
- disponibilite
- execution faite ou non faite
- preference
- confirmation pending
- mutation planning
- sport vise
- date ou fenetre visee

Le LLM est le seul detecteur d'intention utilisateur.

Le determinisme s'applique uniquement a des artefacts machine-generes :

- sortie LLM structuree
- IDs, slugs, keys et events stockes en DB
- schema Pydantic / JSON
- objets plan / activite / memoire deja structures
- permissions, validation, dedoublonnage, TTL, audit

Phrase canonique :

```text
Le LLM comprend le langage humain.
Le code comprend l'etat systeme.
```

## Architecture cible

```text
User text
  -> Coach LLM unique
     - lit le contexte conversationnel borne
     - appelle des tools read-only si besoin
     - produit un CoachDecision structure
  -> Backend validation
     - schemas stricts
     - resolution des refs contre DB
     - permissions
     - dedoublonnage
     - TTL / confiance / ambiguite
  -> Writers bornes
     - PlanMutationService
     - MemoryMutationService
     - ExecutionMutationService si separe de MemoryMutationService
  -> Audit events
  -> Reply utilisateur
```

Un seul agent decisionnaire par tour.
Les loops de tools read-only sont autorisees : ce n'est pas un deuxieme cerveau,
c'est le meme LLM qui lit la verite systeme avant de decider.

Exception d'orchestration terminale (5 mai 2026) : si le turn planner LLM sort
`primary_intent=close_turn`, le backend peut fermer le tour sans appeler le gros
`decide()` quand aucun pending, calibration ouverte ou signal secondaire n'est
actif. Cette branche ne comprend pas le texte user elle-meme : elle applique une
policy sur un artefact LLM et l'etat machine, puis confie la phrase finale a
`final_reply.py`. Depuis le 6 mai 2026, la phrase fallback technique
`Carre, on garde ca.` est invalide comme sortie composee : si le composer la
propose, il retente une phrase contextualisee avant de laisser le backend
utiliser le fallback outage. La sortie candidate passe par un verifier LLM
`allow|repair` : il juge si la phrase ferme vraiment le tour, sans relance,
sans meta-routage visible et sans nouveau fait planning absent du dernier
message coach/user. Le backend applique le verdict structure ; il ne comprend
pas lui-meme le texte libre.

Extension prose finale (5 mai 2026) : apres une decision `no_change`, le backend
peut confier la phrase visible a `final_reply.py` avec le brouillon LLM initial
et les faits machine deja appliques (`memory_actions`, `execution_actions`).
Le composer ne redecide pas : il reformule le resultat valide.

Extension `plan_lookup` (5 mai 2026, durcie 13 mai 2026) : les tours lus comme
questions factuelles par le turn planner LLM utilisent un composer final dedie.
La sortie composee est verifiee contre le grounding DB autoritaire
(`ReplyGroundingPacket`) : durees en minutes, dates ISO, jours, sport et statut
ne doivent pas contredire le planning lu. Si le verifier LLM laisse passer une
duree/date/sport/statut impossible, le hard guard deterministe bloque quand
meme la sortie. Si le composer et le brouillon initial restent invalides, une
reponse fallback compacte est rendue depuis le grounding DB. Cette verification
ne lit pas le texte utilisateur libre ; elle juge seulement une sortie assistant
contre des artefacts machine.

Compat confirmations pending (5 mai 2026) : si le LLM comprend une acceptation
mais sort encore une `MutationDecision` legacy identique a la pending `plan_patch`
active au lieu d'un `pending_resolution.accept_pending`, le backend accepte la
pending. La gate compare seulement les artefacts machine deja structures
(operation, IDs, dates, champs mutation), jamais le texte utilisateur libre. Les
anciennes pending legacy restent sur le contrat strict `pending_resolution`.

Hygiene pending (12 mai 2026) : une confirmation nue ne peut etre appliquee que
si le repository expose une seule pending active. Les pending expirees sont
fermees avant exposition, l'accept revalide `status/expires_at`, et les
outcomes `modify_pending` / `needs_clarification` / choix invalide gardent le
meme pending ouvert. Ce garde-fou ne lit pas `oui/non` : il ne travaille que sur
`pending_resolution` LLM et les lignes DB.

Disponibilite sport-specific (12 mai 2026) : le backend peut generer des
candidats `sport + fenetre` seulement depuis l'artefact LLM
`turn_plan.availability_constraint` et les sessions DB. Il ne cherche jamais un
sport dans le texte libre; si le planner n'a pas extrait `sport_type`, la lane
sport-specific ne s'active pas.

## Contrat CoachDecision cible

Le LLM peut proposer plusieurs actions dans une seule sortie structuree.
Il ne write jamais directement.

```json
{
  "response_type": "no_change | plan_patch | requires_confirmation | reply | mutation_decision",
  "rationale": "execution manquee, aucune mutation planning immediate",
  "fitmas_message": "Note. Hier n'est pas fait; ce matin on garde le Z2 leger.",
  "memory_actions": [
    {
      "type": "record_health_signal",
      "health_signal": "fatigue ou contrainte contextuelle",
      "confidence": 0.72
    }
  ],
  "execution_actions": [
    {
      "type": "record_execution_update",
      "target_ref": "yesterday strength session",
      "target_session_id": 123,
      "status": "not_completed",
      "completed": false,
      "confidence": 0.94,
      "evidence": "J'ai pas eu le temps hier malheureusement"
    }
  ],
  "plan_patch": null,
  "confirmation_reason": null,
  "pending_resolution": {
    "type": "ignore",
    "reason": "le message ne repond pas au pending"
  }
}
```

Regles :

- `memory_actions` propose des faits sante, disponibilite, preference ou contexte.
- `execution_actions` propose des mises a jour d'execution. Elles peuvent modifier
  `ScheduledSession.completion_status` si la cible DB est unique et valide.
- le planning reste exprime via `response_type` + `plan_patch` /
  `requires_confirmation`.
- `pending_resolution` remplace tout parsing deterministe `oui/non`.
- `modify_pending` ne peut modifier que le pending existant. Il ne peut pas forger
  un nouveau patch libre.

## Determinisme autorise

Autorise :

- parser la sortie LLM structuree
- appliquer une policy d'orchestration sur un intent LLM structure (`close_turn`)
  et sur l'etat machine (pending/calibration/signaux secondaires)
- valider les types et les champs requis
- verifier qu'un `target_ref` LLM correspond a une seule seance
- refuser si la cible est ambigue
- dedoublonner une action memoire
- calculer `expires_at` depuis une date deja extraite par le LLM
- appliquer une mutation via un writer officiel
- logguer un audit event
- reparer du JSON invalide de forme avant validation schema
- comparer une reply LLM avec des events post-LLM pour detecter une promesse non committee
- reformuler une reply finale via `final_reply.py` depuis un brouillon LLM et des
  faits machine deja valides/appliques
- comparer un brouillon LLM factuel et sa reply composee pour refuser une derive
  de chiffre, jour, date relative, zone ou statut

Interdit :

- regex / keyword sur texte utilisateur libre
- classifieur `low_signal`, `rich_signal`, `is_ack`, `is_motivation`
- parsing deterministe `oui/non` sur pending confirmation
- extraction sante / dispo / execution depuis texte user hors LLM
- ecriture memoire declenchee par pattern texte
- reply finale canned issue d'un helper deterministe
- routing de tools base sur une classification deterministe du message user
- `heuristic OR LLM` pour upgrader un scope

## Outils et writes

Les tools runtime exposes au LLM restent read-only ou validation-only.

Les writes passent apres decision :

```text
CoachDecision.memory_actions -> MemoryMutationService
CoachDecision.execution_actions -> ExecutionMutationService ou MemoryMutationService
CoachDecision.plan_action -> PlanMutationService
```

Le LLM propose.
Le backend dispose.

## Claim guard

`claim_guard` peut rester seulement comme safety rail post-LLM :

```text
reply LLM + events appliques
  -> detection incoherence
  -> repair LLM contraint avec les faits valides
  -> si repair impossible: outage minimal
```

Il ne doit plus produire de phrase canned comme reponse utilisateur normale.

### Etat 3 mai 2026 — Chantier 1bis livre

Avant 3 mai 2026 : `claim_guard.safe_rewrite_for_claim_without_mutation()` retournait une chaine fixe doctrine-violante ("Je n'ai applique aucun changement sur ce tour. Dis-moi explicitement ce que tu veux que je deplace, remplace ou liberes..."). Cette template a ete observee en prod le 3 mai et fixee dans la foulee.

Apres Chantier 1bis :
- `build_claim_repair_prompt(original_reply, user_text)` construit un repair prompt LLM avec voix coach + interdiction explicite de re-emettre la canned
- Pipeline `_llm_repair_claim_reply` appelle `gw.request_text` + valide (non vide, longueur 5-500, plus de claim, pas de violation voix)
- `outage_fallback_reply()` est l'outage minimal coach-voice (pas la vieille template) : "Vu — rien de bouge sur ce tour. Tu veux que je bouge quoi concretement ?"
- Telemetrie : `response_mode="claim_without_mutation_repaired"` ou `"claim_without_mutation_outage_fallback"`

## Plan de migration

### Phase 0 - Stopper les degats

Objectif : retirer les decisions deterministes les plus visibles du chemin
conversation sans construire encore toute l'infra memoire.

Fichiers principaux :

- `backend/src/fitmas/conversation_pipeline.py`
- `backend/src/fitmas/api_messages.py`
- `backend/src/fitmas/conversation_context.py`
- anciens modules `user_indication_llm.py` / `user_indications.py`
- `backend/src/fitmas/claim_guard.py`
- `tests/test_core_flows.py`
- nouveau test possible : `tests/test_llm_first_conversation_contract.py`

Etat Phase 0 au 30 avril 2026 :

- [x] Ajouter un test statique qui interdit, dans le chemin conversation runtime,
  les appels a `_looks_like_plan_mutation_request`, `_maybe_low_signal_label`,
  `extract_activity_claim`, `extract_non_completion_claim`,
  `fallback_interpret_user_indication`, `parse_confirmation_reply` et
  `_sanitize_no_change_reply`.
- [x] Supprimer `heuristic_plan_mutation_request` et le `OR` avec le planner LLM.
- [x] Supprimer `low_signal_label` / `_RICH_SIGNAL_MARKERS` du pipeline runtime.
- [x] Retirer `current_activity_claim`, `recent_activity_claim` et
  `non_completion_claim` de `ConversationContextBundle` tant qu'ils viennent du
  texte user par regex.
- [x] Supprimer le fallback regex historique de `user_indications.py`; le module
  entier a ensuite ete supprime pendant le cleanup repo.
- [x] Remplacer `_sanitize_no_change_reply` par le bloc de sortie `claim_guard`
  post-LLM. Il ne lit pas le texte user.
- [x] Faire passer le scenario du matin par le contrat cible :
  heartbeat demande "renfo faite ou pas ?", user repond "J'ai pas eu le temps
  hier malheureusement", le LLM sort `execution_actions=[completed=false]`, le
  backend marque la seance comme `skipped`, la reply reste humaine.
- [ ] Transformer `claim_guard` : log violation + repair LLM contraint, puis
  outage minimal si repair impossible.

Smoke minimal :

```bash
./scripts/test-backend tests/test_core_flows.py::FitMASCoreFlowsTest::test_contextual_non_answer_stays_llm_only_without_parser_side_effect -q
./scripts/test-backend tests/test_llm_first_conversation_contract.py -q
```

### Phase 1 - Actions structurees

Objectif : ajouter les actions non-planning au contrat LLM sans les executer
librement.

Fichiers principaux :

- `backend/src/fitmas/llm.py`
- `backend/src/fitmas/conversation_contract.py`
- `backend/src/fitmas/memory_mutation_service.py`
- `backend/src/fitmas/execution_mutation_service.py` si separe
- `backend/src/fitmas/schema.py`
- tests dedies service + pipeline

Taches :

- [x] Ajouter les schemas Pydantic stricts :
  `HealthSignalAction`, `AvailabilityConstraintAction`,
  `PreferenceSignalAction`, `ExecutionUpdateAction`.
- [x] Etendre `CoachDecision` avec `memory_actions`, `execution_actions` et
  `pending_resolution`.
- [x] Creer `MemoryMutationService` :
  validation, dedoublonnage, TTL, write UserFact / working memory, audit.
- [x] Creer ou isoler le writer execution :
  resolution cible DB, `skipped/done` seulement si cible unique, audit.
- [x] Ajouter `memory_mutation_events` ou une table audit equivalente.
- [x] Brancher les writes `memory_actions` / `execution_actions` apres validation
  de `CoachDecision`; les inputs restent des artefacts LLM structures, jamais le
  texte user libre.

### Phase 2 - Bascule LLM

Objectif : le LLM unique produit les actions et remplace les extracteurs.

Fichiers principaux :

- `backend/src/fitmas/llm_prompt_builder.py`
- `backend/src/fitmas/prompt_layers.py`
- `backend/src/fitmas/llm.py`
- `backend/src/fitmas/conversation_pipeline.py`
- `backend/src/fitmas/tools/routing.py` (enum seulement, pas de classifieur texte)

Taches :

- [x] Enrichir le system prompt : le coach doit emettre des actions structurees
  pour sante, dispo, execution, preference et pending.
- [x] Ajouter few-shots pour :
  "j'ai pas eu le temps hier", "j'ai mal au genou", "je peux pas nager 2 semaines",
  "oui mais finalement vendredi", "running", "mercredi".
- [x] Brancher les writers apres validation de `CoachDecision`.
- [x] Remplacer `parse_confirmation_reply` par `pending_resolution` pour les
  confirmations pending : `accept_pending` applique l'artefact pending apres
  revalidation, `reject_pending` le ferme sans mutation, `modify_pending` ne
  commit rien en V1.
- [x] Laisser le LLM choisir les read-tools ; le routing deterministe ne doit plus
  classer le texte user.
- [x] Ajouter metriques :
  `memory_actions_per_turn`, `execution_actions_per_turn`,
  `pending_resolution_per_turn`, `llm_understanding_missing_action`.
- [x] Durcir le parsing des artefacts LLM `CoachDecision` :
  repair JSON des decisions invalides, normalisation de `confidence="high"`,
  `completed="false"` et `operation_type=record_execution_update`, drop des
  actions connues incompletes sans perdre les actions valides, rejet des actions
  inconnues.
- [x] Interdire `requires_confirmation` libre sans `PlanPatch` /
  `mutation_decision`; une question de clarification doit sortir en `no_change`,
  pas rouvrir un protocole de confirmation.

### Phase 3 - Purge

Objectif : supprimer le vieux code pour eviter la rechute.

Fichiers a supprimer ou degrader hors runtime :

- `fallback_interpret_user_indication`
- `_fallback_health_indication`
- `_fallback_availability_indication`
- `_HEALTH_PATTERNS`, `_UNAVAILABLE_PATTERNS`, `_EXECUTION_PATTERNS`
- `_POST_REPLY_HEALTH_TEXT_MARKERS`
- `_NO_CHANGE_MUTATION_MARKERS`
- `_LOAD_RECALIBRATION_MARKERS`
- `extract_life_change_event(user_text=...)`
- `tool_routing.classify_intent(query=...)`

Regle : si une fonction lit `user_text` et retourne une intention, elle sort du
runtime conversation ou devient un outil de test/diagnostic explicitement non-prod.

Etat Phase 3 au 1 mai 2026 :

- [x] `conversation_pipeline.py` n'appelle plus `interpret_user_indication` avant
  `decide()`.
- [x] `ConversationPipelineDependencies` n'expose plus de pre-step
  `interpret_user_indication`.
- [x] `api_messages.post_message` ne branche plus `interpret_user_indication`
  dans le runtime conversation.
- [x] Le pipeline ne persiste plus de facts sante/dispo depuis
  `UserIndication`; ces writes viennent de `CoachDecision.memory_actions`.
- [x] Le pipeline ne produit plus d'adaptation/replan depuis
  `maybe_replan_from_user_indication`; les mutations viennent de
  `CoachDecision` / `PlanPatch`.
- [x] Le pipeline ne route plus de contexte final depuis `_week_scope_reply`,
  `_no_candidate_constraint_reply` ou `_execution_contestation_reply`.
- [x] Garde-fous statiques ajoutes dans
  `tests/test_llm_first_conversation_contract.py`.
- [x] Cleanup repo : suppression physique de `user_indication_llm.py`,
  `user_indications.py`, `replan_from_life_change.py` et du wrapper
  `tool_routing.py`.
- [x] `tools/routing.py` ne contient plus de `classify_intent` ni de
  `route_tools_for_query`; il ne garde que l'enum `IntentCategory` pour les
  policies de prompt deja produites par artefacts LLM.
- [x] Les tests historiques de ces modules ont ete supprimes; le verrouillage se
  fait maintenant par `test_llm_first_conversation_contract.py`.

### Phase 4 - Verrouillage

Objectif : empecher les regressions.

Taches :

- [ ] Ajouter un test statique global :
  aucun fichier du chemin `api_messages -> conversation_pipeline -> llm` ne peut
  importer les extracteurs regex de texte user.
- [ ] Ajouter un test doc :
  `AGENTS.md`, `PROJECT.md`, `docs/README.md`, `docs/CONVERSATION.md` doivent
  pointer vers ce doc.
- [ ] Ajouter smokes dogfood :
  `heartbeat_non_completion`, `health_signal`, `availability_multi_day`,
  `pending_modified_confirmation`, `short_continuation`.
- [ ] Ajouter revue hebdo manuelle des tours ou le LLM n'a pas emis d'action alors
  que le user mentionne sante/dispo/execution. Cette revue est diagnostic, pas un
  nouveau parser runtime.

Etat 4 mai 2026 : `heartbeat_non_completion` est verrouille par un repair
semantique qui ne lit pas le texte utilisateur. Si le LLM reconnait dans son
artefact invalide que la seance d'hier est manquee mais oublie
`execution_actions`, et si le contexte systeme contient une cible follow-up
structuree, le backend reconstruit un `record_execution_update` borne. Sans
cible structuree, pas d'action synthetisee.

### Phase 5 - Tool-use loop unifie (Chantier 3 du plan 2 mai 2026)

Objectif : passer le runtime conversation **et** le runtime heartbeat d'un modele "structured output JSON terminal" vers un **vrai tool-use loop multi-rounds** ou les actions deviennent des tools natifs et la reponse finale au user est de la prose libre.

Source canonique du plan : `docs/BUILD-ORDER.md` section "Plan en cours — 5 chantiers". Le present doc detaille la migration cote LLM-first.

#### Etat actuel verifie le 2 mai 2026

Le tool-use loop ([llm.py:732-875](../backend/src/fitmas/llm.py:732)) existe mais est borne :

- max 3 tools par tour (`max_tools=3`)
- 1 seul round de tools : la requete followup ne renvoie pas `tools=`, donc le LLM ne peut pas demander un autre tool apres avoir vu un resultat
- terminaison forcee en JSON `CoachDecision` parse par le pipeline ; le `fitmas_message` est un *champ* du JSON, pas une emission texte libre
- toutes les actions planning sont encodees en JSON `PlanPatch` (un artefact de donnees) et appliquees par `validate_plan_patch -> PlanMutationService.apply_patch_for_user`

Le briefing matin (heartbeat) est un appel LLM **one-shot sans tools** — pas de grounding tool-use, le LLM doit decider sur la base du seul contexte injecte dans le prompt. C'est ce qui a permis l'hallucination factuelle du 2 mai (LLM recopie un texte injecte au lieu de verifier).

#### Etat Chantier 3A au 3 mai 2026

Conversation a maintenant une premiere boucle outillee 3A :

- `validate_plan_patch` est expose comme tool validation-only ;
- le LLM peut enchainer jusqu'a 3 rounds de read/candidate/validation tools ;
- le budget total est 6 tool calls par tour ;
- tous les `tool_use_id` demandes recoivent un `tool_result` ou un blocage explicite ;
- `PlanPatch` reste l'artefact d'action : aucun write tool natif n'est expose ;
- apres commit/block d'un `PlanPatch`, la reply visible peut etre composee par LLM depuis les events reels via `FinalReplyContext`.

Ce n'est pas encore la Phase 5 complete :

- heartbeat utilise maintenant une boucle 3B-B avec read-tools +
  `suggest_replan_candidates` + `validate_plan_patch`. Il peut creer une
  pending confirmation `PlanPatch` apres delivery, mais ne commit toujours pas
  de mutation autonome ;
- les actions planning ne sont pas encore des tools natifs ;
- la decision interne reste un `CoachDecision` JSON pendant la migration ;
- la prose libre finale est livree sur les chemins planning post-resultat, pas encore comme unique terminaison universelle.

#### Architecture cible Phase 5

Pour les **deux pipelines** (conversation + heartbeat) :

```text
Round 1 : LLM voit prompt + read-tools + action-tools dispo
         -> peut emettre N tool_use blocks dans un meme tour (read OU action)

Backend : execute les tools demandes (cap par-round, jusqu'a ~3 tools)
         -> chaque tool valide, commit si action, retourne payload structure

Round 2 : LLM voit les results
         -> peut redemander d'autres tools (read pour grounding, OU action)
         -> OU emettre du texte libre = reponse finale au user

[ ... boucle jusqu'a stop_reason="end_turn", hard cap 5-6 rounds ... ]

Round N : LLM emet texte libre = message final envoye TEL QUEL au user
         -> plus de wrapper JSON, plus de fitmas_message field
```

Action-tools cibles (ce qui etait jusque-la dans `PlanPatch`) :

- planning : `swap_sessions`, `move_session`, `replace_session`, `lighten_day`, `update_session`, `create_session`, `cancel_session`
- pending : `confirm_pending`, `dismiss_pending` (alternatives a `pending_resolution` typed)
- memory / execution : possiblement exposes comme tools si le pattern le justifie ; sinon restent traites par writers internes apres validation `CoachDecision` (pattern actuel Phase 1)

Chaque action-tool :

- valide ses args (logique actuelle de `validate_plan_patch`)
- commit via `PlanMutationService` (writer unique conserve)
- emet `plan_mutation_event`
- retourne au LLM `{status: "committed", session_after: {...}, summary: "..."}` ou `{status: "blocked", reason: "..."}`

#### Bug classes resolues par Phase 5

- **Voix structurellement libre** : plus de wrapper JSON terminal -> la voix coach n'est plus contrainte cognitive ("remplir un champ"). Phase 1 calibre la voix dans le wrapper, Phase 5 supprime le wrapper.
- **Hallucination factuelle briefing** : le briefing peut grounder ses claims via tools (`get_recent_activities`, `get_load_context`...) avant de parler. *"J'allais dire offplan=2, je verifie via tool... payload dit 0... je corrige."*
- **Multi-step reasoning** : `read -> reason -> read encore -> mutate -> voir result -> respond`. Aujourd'hui impossible (1 round only).
- **Pushback structure** : le coach peut refuser une mutation en lisant le contexte via tools puis en repondant en prose ("non, ton long run dimanche encaisse mal — propose plutot X"). Aujourd'hui pas de chemin propre (no_change ou requires_confirmation, deux statuts qui ne correspondent pas).
- **Confirmation pending propre** : `confirm_pending` / `dismiss_pending` deviennent des tools comme les autres. `pending_resolution` typed (Phase 2 deja livree) reste utilisable mais devient redondant.
- **Provider portability** : tool-use est primitive standard (Anthropic, OpenAI, DeepSeek). Plus de quirks structured output.
- **Foundation Phase B** : prescription/progression engine se branche directement sur le tool-use loop (`prescribe_week`, `apply_progression`, etc.) sans refondre l'archi.

#### Decoupe Phase 5

**Etape A — Refactor LLM client (1j)**
- retirer `max_tools=3` (ou passer a un cap par-round)
- garder `tools=` dans la requete followup
- boucler tant que `stop_reason="tool_use"`, hard-cap 5 rounds, fail-safe en `no_change` reply en cas de loop
- accepter terminaison en **texte libre** (pas en JSON)

**Etape B — Action-tools planning (1.5j)**
- definir les ~9 tools mutants, schemas + delegate vers `PlanMutationService`
- chaque tool valide / commit / event / retourne payload
- tests unit par tool

**Etape C — Pipeline conversation (1j)**
- retirer parse `CoachDecision` terminal -> reply = last assistant text content
- retirer `fitmas_message` field et templates `_BLOCK_REASON_REPLIES`
- compatibilite : garder un fallback JSON parser pendant migration au cas ou le LLM regresse vers JSON

**Etape D — Pipeline heartbeat (1j)**
- exposer un sous-set read-tools au briefing/reminder/weekly review
- meme loop refactor
- terminaison texte libre

**Etape E — Refonte prompt (1j)**
- voice rules Phase 1 conservees (ils s'appliquent universellement)
- remplacer la sematique JSON `CoachDecision` par la semantique tools
- few-shots adaptes au pattern tool-call (quand swap vs move vs replace, comment rediger `reason`)

**Etape F — Tests + telemetrie (1.5j)**
- E2E sur 5 scenarios doctrine + edge cases
- metriques par-loop : rounds/turn, tokens/turn, tool failure rate, fallback usage
- fallback Claude si DeepSeek tool-use casse (pattern deja en place pour structured output, a etendre au tool-use loop)

**Total Phase 5 : ~6-7 jours.**

#### Risques + mitigations

- **LLM boucle infiniment** -> cap dur 5 rounds, fail-safe en `no_change` reply
- **LLM call action sans lire d'abord** -> regle prompt + detecteur log
- **DeepSeek tool-use casse en prod** -> fallback Claude deja en place pour structured, a etendre au tool-use loop
- **Cout explose** -> telemetry par-loop cost, alerte si moyenne > seuil

#### Quand declencher Phase 5

Pas speculativement. Trois signaux qui declenchent :

1. **Apres dogfood Phase 1** : la voix sonne encore wrapper-contrainte malgre le prompt -> preuve que le wrapper EST le blocker
2. **Avant Phase B** : prescription engine se branche naturellement sur tool-use loop ; autant ne pas faire Phase B sur l'ancien shape
3. **Bug recurrent grounding heartbeat** : tools de lecture deviennent necessaires pour eviter d'autres hallucinations comme celle du 2 mai

L'incident du 2 mai est un signal partiel pour (3), mais Chantier 0 (TTL fix) est le fix immediat ; Phase 5 reste justifiee sur le moyen-long terme.

## Acceptation

La migration est terminee quand :

- aucun texte user libre n'est classe par regex/keyword dans le runtime conversation
- un pending ne se resout jamais par parser `oui/non`
- les faits sante/dispo/execution/preference viennent de `CoachDecision`
- les writes passent par services bornes et auditables
- le scenario du heartbeat du 30 avril passe en smoke reel
- les docs ne recommandent plus "regex comme hint" sur texte utilisateur libre

Cloture Phase 5 acceptee quand :

- les actions planning sortent en tool calls natifs, pas en JSON `PlanPatch` terminal
- la reponse finale user est du texte libre, pas un champ d'un JSON wrapper
- briefing matin et conversation partagent le meme loop tool-use
- aucune hallucination factuelle observee sur 14 jours de dogfood post-Phase 5
