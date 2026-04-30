---
summary: audit architecture conversation + contexte, focus sur residus deterministes et qualite de grounding apres la passe 15-17 avril 2026
read_when:
  - preparer le prochain chantier conversation
  - evaluer si un early-exit deterministe doit passer par le LLM
  - debugguer un trou de contexte coach
  - decider du periode tool runtime a etendre
---

# Audit conversation + contexte — 17 avril 2026

> Statut — audit historique. Depuis le 30 avril 2026,
> `docs/LLM-FIRST-CONVERSATION.md` supersede toute option qui conserve
> `_looks_like_plan_mutation_request`, `low_signal`, `rich_signal`,
> fallback deterministe ou parsing pending `oui/non` sur texte utilisateur libre.

## Cadre

Post-passe de fiabilite (15-17 avril). Le pipeline conversationnel est passe de "heuristiques lexicales → decide LLM" a "heuristiques + classifieur LLM d'intention → arbitrage OR → decide LLM avec contexte route". Les failles identifiees (A/B/C/D) sont closes. Cet audit regarde ce qui reste.

Scope : tout ce qui concerne `run_conversation_turn()`, construction du contexte LLM, memoire courte utilisee dans le prompt, et la feedback loop pre-hooks → reply.

Hors scope : planner, adaptation.py interne, heartbeat (sauf briefing grounding).

## Verdict synthetique

La chaine est saine sur les grosses failles. Les risques residuels sont **des fragilites et des duplications**, pas des incoherences de verite. Trois axes prioritaires :

1. **Turn planner single-point-of-failure** quand le LLM est indisponible
2. **Heuristique `_looks_like_plan_mutation_request` fragile** et maintenu en parallele du LLM
3. **Contexte envoye au decide() est grossier** : le planner classe proprement, mais le prompt final recoit encore `coach_context` complet sans slicing par intent

## Carte des points chauds

### 1. Residus deterministes toujours actifs dans le pipeline

Ordre des early-exits dans `conversation_pipeline.run_conversation_turn()` :

| # | Early-exit | Fichier:ligne | Trigger | Gatee sur `plan_mutation_request` ? | Verdict |
|---|-----------|--------------|---------|-------------------------------------|---------|
| 1 | `pending_confirmation` reply | pipeline:81 | Confirmation en attente | Non (a priori correct) | OK — ACK/rejet explicit |
| 2 | `low_signal` reply | pipeline:153 | Ack / greeting / motivation simple | Non | Risque bas — `_has_rich_signal_marker` stoppe les cas limites |
| 3 | `standalone_calibration_answer` ack | pipeline:549 | Reponse courte a calibration ouverte | **Oui** (via condition `not plan_mutation_request`) | OK |
| 4 | `targeted_execution_clarification` | pipeline:385 | Doute structurant sur execution hier | **Oui** | OK |
| 5 | `execution_contestation_reply` | pipeline:604 | Contestation sur activite visible | **Oui** | OK |
| 6 | `health_adaptation` auto-apply | pipeline:423 | Fait sante + low-impact | **Oui** (via `defer_health_adaptation_to_llm`) | OK |
| 7 | `adaptation` pre-computee | pipeline:509 | `maybe_replan_from_life_change` | Contexte route au LLM si `has_plan_mutation` | OK |
| 8 | `availability` week_scope / no_candidate | pipeline:560 | Indispo sans seance cible | Contexte route au LLM si `has_plan_mutation` | OK |

**Points restant a surveiller** :

- **`low_signal_reply` n'est pas gatee** sur le turn planner. Un message `ok` envoye pendant qu'une question de calibration est ouverte est protege par `has_open_calibration_need`, mais un `ok` qui est en fait une acceptation implicite d'une suggestion passee (sans pending confirmation) tombe en low-signal. A verifier en dogfooding.
- **La chaine de early-exits est sequentielle** : chaque etape lit l'etat mute par la precedente. Reorganiser en "collect → arbitre → execute" serait plus lisible mais non urgent.

### 2. L'heuristique `_looks_like_plan_mutation_request` est maintenue en parallele du LLM

Localisation : `api_messages.py:268`.

Pattern actuel : 10 marqueurs lexicaux (`decale`, `deplace`, `bascule`, `remplace`, `change`, etc.) + swap markers.

**Observations** :

- Le commit `b78db28` a instrumente la divergence heuristique/LLM via un WARNING structure. La passe n'a **pas** retire l'heuristique — au contraire, elle est conservee en filet de securite ("neither can silently drop the intent").
- En l'etat, elle a donc une double fonction : (a) detecteur de mutation secondaire, (b) declencheur du forcage LLM quand elle flagge True et que le planner dit False.
- **Risque** : cette heuristique est un pattern qui pourrit avec le temps. Chaque nouveau phrasing utilisateur (`on inverse mardi et jeudi ?`, `bouge la de 2h ?`) demande un ajout manuel.

**Decision 30 avril** :

Ces options sont closes. On ne garde pas l'heuristique en filet, on ne l'inverse
pas, et on ne la remplace pas par un fallback plus petit. Le LLM est le seul
detecteur d'intention ; le backend valide ensuite la decision structuree.

### 3. Le turn planner est un single-point-of-failure muet

Quand `gw.request_json()` retourne None (timeout, auth, JSON casse au-dela du robust parser), le pipeline fait :

```python
if turn_plan is None:
    llm_plan_mutation_request = False
    llm_plan_mutation_state = "unavailable"
```

Et continue. Consequences :

- Les **intentions implicites** (`vendredi a la place ?`, `on inverse mardi jeudi ?`) que l'heuristique ne detecte pas sont alors ratees → le pipeline tombe en mode heuristique + decide direct sans primary_intent → tool budget par defaut → reponse generique.
- Pas de retry, pas de cache.
- Pas de metrique compteur (juste un WARNING sur divergence).

**Decision 30 avril** :

Si le LLM est indisponible, on degrade en clarification / outage minimal.
On ne cree pas de fallback deterministe qui lit le texte user.
4. **Metrique `turn_planner_unavailable_rate`** — si ça depasse 1 %, c'est un incident a traiter.

Recommendation : (4) d'abord pour mesurer l'ampleur reelle. Puis (2) si le taux justifie.

### 4. Le contexte envoye a `decide()` n'est pas encore slicer par intent

Aujourd'hui, `turn_plan.primary_intent` controle :

- le tool budget offert au LLM (`_TURN_INTENT_TO_PROMPT_INTENT` dans `llm.py:70`)
- le routage du contexte availability / adaptation au prompt

Mais `coach_context` recu par `decide()` contient **toujours** :
- `planning_contract`, `availability_state`, `week_mission`, `recent_reality`, `last_adaptation`, `week_context` (`summary`, `planning`, `next_week`, `coach_reading`), profile_summary, selected_facts

Tout, pour chaque intent. Pour un `plan_lookup` ou un `trivial_ack`, on injecte le contrat de planning complet. Pour un `execution_report`, on injecte le contexte availability. **Pas dramatique** (les budgets token Anthropic absorbent), mais :

- pollue le prompt et dilue l'attention du modele
- rend le comportement moins auditable (qu'est-ce qui a fait bouger la reponse ?)
- facture plus que necessaire

**Options** :

1. Introduire une couche `coach_context_slicer(primary_intent, full_bundle)` qui retourne un sous-ensemble semantiquement pertinent.
2. Etendre `prompt_layers.py` pour filtrer L2 (etat plan) et L4 (memoire episodique) en fonction de l'intent.

Recommendation : commencer par (2) — c'est deja la ou le prompt est structure en couches. Target : reduction de 30-40 % de tokens L2/L3 sur `trivial_ack` et `plan_lookup`.

### 5. Extractions en double sur un meme tour

Dans un tour, on peut ecrire en memoire/contexte :
- `claim_facts` + `supplemental_claim_facts` (pipeline:285-330)
- `health_indication_facts` (pipeline:411)
- `calibration_resolution` memory updates (via `build_resolution_memory_updates`)
- `extracted_facts` post-reply (pipeline:843)
- `health_adaptation_facts` post-reply si `_should_run_post_reply_health_adaptation`

Chaque famille appelle `_persist_turn_memory_updates` separement → 3-5 INSERTs possibles par tour, et plusieurs reloads de `active_memory_rows`.

**Observations** :

- Pas de bug fonctionnel connu, mais la multiplication des sources augmente le risque de **doublons semantiques** en memoire (ex: un fait `fatigue` cree cote indication, un autre cree cote extraction post-reply avec un wording different).
- La deduplication est faite au niveau `repo.upsert_user_fact` via `(category, key)`. Si les cles convergent, OK. Si elles divergent, on pollue.

**Options** :

1. Collecter tous les payloads dans une liste unique a la fin du tour, puis un seul commit batch → plus lisible, et permet une dedup semantique en une passe.
2. Audit offline : lancer un script qui inspecte les `working_memory_entries` sur 1 semaine de dogfooding pour reperer les doublons.

Recommendation : (2) d'abord pour mesurer. Si le taux de doublons semantiques > 5 %, faire (1).

### 6. Le grounding de briefing est corrige, mais le grounding de `decide()` ne l'est pas encore

Le fix `910f47a` a injecte `recent_reality` dans le briefing matin pour empecher `"tu as sorti 4 seances cette semaine"`. Probleme similaire potentiel dans `decide()` :

- `recent_reality` est bien passe a `decide()` via `coach_context["recent_reality"]` (pipeline:683)
- mais pas explicitement en tant que "compteurs bruts", plutot sous forme de `as_dict()` — pas garanti que le modele lise cela comme une source numerique ground-truth.

**Risque** : si l'utilisateur demande en conversation *"j'en suis a combien cette semaine ?"*, le modele pourrait confabuler malgre la presence du bundle. Le prompt system de `decide()` ne porte pas l'interdiction explicite qui vit dans le briefing.

**Options** :

1. Propager la meme regle systeme ("interdit de citer un decompte sans compteur explicite") au prompt `decide()`.
2. Formater `recent_reality` dans `decide()` comme un bloc texte numerique explicite quand `primary_intent in {plan_lookup, execution_report, trivial_ack}`.

Recommendation : (1) immediat (couteux de 0), (2) si `primary_intent == plan_lookup` reveut des compteurs.

### 7. Memoire et selected_facts : pas de feedback sur utilite

Le pipeline selectionne 6 facts max (`pipeline:640`) pour le prompt. Pas de mecanisme pour savoir si ces facts ont reellement influence la reponse.

**Observations** :

- `memory_patterns.py` promeut deterministiquement des patterns. Bien.
- `memory_maintenance.py` purge les working entries expirees. Bien.
- Mais aucune mesure : **est-ce que les 6 facts selectionnes etaient pertinents ?** Le coach peut ignorer completement un fact clef parce qu'il a ete noye par 5 facts de bas signal.

**Options** :

1. Ajouter un post-hook leger : si la reply contient une reference lexicale a un `selected_fact`, incrementer un score d'utilite du fact.
2. Periodiquement reduire les facts a 3-4 pour voir si la qualite baisse — mesure empirique du surdimensionnement.

Recommendation : (2) facile a tester en A/B local.

## Matrice routage actuelle

| Intent planner | Heuristique matches | Tool budget | Contexte route au LLM | Early-exit gate |
|---------------|--------------------|-----------  |---------------------|-----------------|
| plan_mutation | swap/decale/etc. | PLAN_NEGOTIATION (4 tools) | availability + adaptation | **Tous skipes** |
| plan_lookup | — | PLAN_LOOKUP (2 tools) | — | Aucun skip |
| execution_report | — | EXECUTION_REPORT (a completer) | — | Clarification + contestation actives |
| availability_constraint | — | PLAN_NEGOTIATION | availability route | Early-exit actif si pas de `has_plan_mutation` |
| health_signal | — | PLAN_NEGOTIATION | — | Auto-apply actif si pas de `plan_mutation` |
| calibration_answer | — | default | — | Standalone ack actif |
| casual_chat / trivial_ack | greeting / ack / motivation | default | — | low_signal actif |
| preference_signal | — | PLAN_NEGOTIATION | — | — |
| needs_clarification | — | default | — | — |

**Trous visibles** :

- `calibration_answer`, `preference_signal`, `casual_chat`, `trivial_ack`, `needs_clarification` n'ont pas de tool budget dedie → defaut = tous les tools offerts → coute plus cher et dilue la decision.
- `needs_clarification` comme intent primaire n'a pas de path dedie dans le pipeline — il est traite implicitement par `decide()`. Risque : le LLM a un flag "needs_clarification" mais doit quand meme prendre une decision.

**Recommendation** : cartographier les 9 intents x les 7 early-exits → matrice explicite dans un test de verite (`tests/test_intent_routing_matrix.py`).

## Recommendations priorisees

**Priorite 1 (semaine qui vient)** :

1. Ajouter metrique `turn_planner_unavailable_rate` et `intent_divergence_rate` comptees par heure/jour.
2. Propager la regle "interdit de confabuler un decompte" au prompt system de `decide()`.
3. Ecrire `tests/test_intent_routing_matrix.py` pour verrouiller les gates par intent.

**Priorite 2 (2-3 semaines)** :

4. Slicer `coach_context` par `primary_intent` dans `prompt_layers.py`.
5. Collecter les WARNINGs `pipeline.intent_divergence` sur 2 semaines → decider si on retire l'heuristique (option 2 ou 3 de la section 2).
6. Audit doublons semantiques en memoire (section 5 option 2).

**Priorite 3 (plus tard, apres dogfooding)** :

7. Cache LRU sur classifieur planner si `turn_planner_unavailable_rate > 1 %`.
8. Retry borne sur planner.
9. Post-hook utilite `selected_facts`.

## Hors audit — a ne pas confondre

- Dual-write `ScheduledSession` + `DayPlan` (dette critique documentee dans COACH-COHERENCE-REFACTOR.md).
- `signals.py` lit encore `WeeklyPlan` / `DayPlan` pour 5 detecteurs (hors scope conversation pure).
- Tool runtime V1 borne (volontairement).

## Verification suggeree

Avant de declencher un chantier, dogfood 1 semaine avec :
- logs `pipeline.intent_divergence` actives
- un compteur `turn_planner_unavailable` simple
- inspection manuelle des tours ou `llm_plan_mutation_state == "unavailable"`

Ces metriques decident si les priorites 1 sont urgentes ou simplement utiles.
