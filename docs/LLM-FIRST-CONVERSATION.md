---
summary: doctrine zero determinisme sur texte utilisateur libre et plan de migration conversation LLM-first
read_when:
  - modifier conversation_pipeline.py
  - modifier api_messages.py
  - modifier conversation_context.py
  - modifier user_indications.py ou user_indication_llm.py
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
- valider les types et les champs requis
- verifier qu'un `target_ref` LLM correspond a une seule seance
- refuser si la cible est ambigue
- dedoublonner une action memoire
- calculer `expires_at` depuis une date deja extraite par le LLM
- appliquer une mutation via un writer officiel
- logguer un audit event
- reparer du JSON invalide de forme avant validation schema
- comparer une reply LLM avec des events post-LLM pour detecter une promesse non committee

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

## Plan de migration

### Phase 0 - Stopper les degats

Objectif : retirer les decisions deterministes les plus visibles du chemin
conversation sans construire encore toute l'infra memoire.

Fichiers principaux :

- `backend/src/fitmas/conversation_pipeline.py`
- `backend/src/fitmas/api_messages.py`
- `backend/src/fitmas/conversation_context.py`
- `backend/src/fitmas/user_indication_llm.py`
- `backend/src/fitmas/user_indications.py`
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
- [x] Supprimer le fallback regex historique de `user_indications.py`. Les tests
  creent maintenant des `UserIndication` structurees, comme une sortie LLM.
- [x] Remplacer `_sanitize_no_change_reply` par le bloc de sortie `claim_guard`
  post-LLM. Il ne lit pas le texte user.
- [ ] Faire passer le scenario du matin par le contrat cible :
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
- [ ] Creer `MemoryMutationService` :
  validation, dedoublonnage, TTL, write UserFact / working memory, audit.
- [ ] Creer ou isoler le writer execution :
  resolution cible DB, `skipped/done` seulement si cible unique, audit.
- [ ] Ajouter `memory_mutation_events` ou une table audit equivalente.
- [ ] Ne brancher aucun write tant que les tests schema/service ne sont pas verts.

### Phase 2 - Bascule LLM

Objectif : le LLM unique produit les actions et remplace les extracteurs.

Fichiers principaux :

- `backend/src/fitmas/llm_prompt_builder.py`
- `backend/src/fitmas/prompt_layers.py`
- `backend/src/fitmas/llm.py`
- `backend/src/fitmas/conversation_pipeline.py`
- `backend/src/fitmas/tools/routing.py`

Taches :

- [ ] Enrichir le system prompt : le coach doit emettre des actions structurees
  pour sante, dispo, execution, preference et pending.
- [ ] Ajouter few-shots pour :
  "j'ai pas eu le temps hier", "j'ai mal au genou", "je peux pas nager 2 semaines",
  "oui mais finalement vendredi", "running", "mercredi".
- [ ] Brancher les writers apres validation de `CoachDecision`.
- [ ] Remplacer `parse_confirmation_reply` par `pending_resolution`.
- [ ] Laisser le LLM choisir les read-tools ; le routing deterministe ne doit plus
  classer le texte user.
- [ ] Ajouter metriques :
  `memory_actions_per_turn`, `execution_actions_per_turn`,
  `pending_resolution_per_turn`, `llm_understanding_missing_action`.

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

## Acceptation

La migration est terminee quand :

- aucun texte user libre n'est classe par regex/keyword dans le runtime conversation
- un pending ne se resout jamais par parser `oui/non`
- les faits sante/dispo/execution/preference viennent de `CoachDecision`
- les writes passent par services bornes et auditables
- le scenario du heartbeat du 30 avril passe en smoke reel
- les docs ne recommandent plus "regex comme hint" sur texte utilisateur libre
