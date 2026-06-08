---
summary: code map detaillee du Runtime V0 — architecture, boucle, role de chaque fichier, agent / tools / prompts, moteur Meso, policy / executor, guard, tests
read_when:
  - comprendre en profondeur le fonctionnement interne de runtime_v0
  - naviguer ou modifier un fichier du noyau V0
  - onboarder un agent ou un humain sur l'architecture V0
  - localiser ou vit une responsabilite (perception, raisonnement, autorite, execution, voix, audit)
---

# Runtime V0 — Code Map

Carte detaillee du noyau `backend/src/fitmas/runtime_v0/`. Pour le *quoi / pourquoi*
(scope, preuves, budget), lire `RUNTIME-V0.md`, `V0-DOGFOOD-SCOPE.md`, `PLANNING-V0.md`.
Ce document est le *comment* : l'architecture interne et le role de chaque fichier.

## 1. Doctrine en une phrase

> Le LLM **comprend** le texte et **genere** des artefacts typés ; le backend **valide,
> autorise, commit et audite**. Le determinisme ne vit que du cote **verification /
> validation / commit / audit**, jamais sur la comprehension du texte utilisateur ni sur
> la generation imposee.

Conséquences structurelles :

- **Aucun regex / keyword sur le texte utilisateur libre.** Le coach (LLM) interprete ;
  le backend agit sur des artefacts typés (`ActionProposal`).
- **Aucun write DB hors de l'executor officiel.**
- **Aucune reply ne ment sur un write** (le guard tient cette ligne).
- Le noyau reste **isolé** : il n'importe jamais `fitmas.decision / domain / llm / skills /
  tools / app` (test `tests/runtime_v0/test_import_boundaries.py`). Le pont vers le produit
  existant vit dans `adapters/` (hors budget, peut dependre du legacy).

## 2. La boucle

Un message utilisateur = un `InputEvent` -> un tour. Le tour traverse :

```text
InputEvent          event.py           ce qui entre (message, source, occurred_at)
  -> WorldSnapshot  snapshot.py        photo lue de la DB (plan, facts, pending, etat)
  -> CoachAgent     agent.py           le LLM lit, raisonne, appelle des tools
  -> ActionProposal proposals.py       l'artefact typé que le coach emet
  -> RuntimePolicy  policy.py          l'AUTORITE : valide, grounde, decide l'action + commands
  -> CommandExecutor executor.py       applique les commands en DB (transactionnel, audité)
  -> RuntimeResult  result.py          ce qui s'est reellement passe + contrat de reply
  -> ReplyComposer  reply.py           la VOIX : le LLM formule la reponse
  -> OutputGuard    guard.py           la VERITE : bloque une reply qui ment / fuite
  -> Audit          audit.py           persiste tout le tour (rejouable)
```

L'orchestration de cette boucle vit dans **`runtime.py`** (`handle_event`). Étapes
exactes de `handle_event` :

1. `acquire_event_lock` (idempotency.py) sur `event.id` : si le tour est déjà complet,
   on renvoie le resultat existant ; si un lock tourne encore, on renvoie un resultat
   « processing » ; un lock `failed` ou stale (>15 min) autorise un retry.
2. `SnapshotBuilder.build` -> `WorldSnapshot`.
3. `CoachAgent.run(event, snapshot.header(), for_event(event, snapshot), tool_context)`
   -> `ActionProposal`.
4. `RuntimePolicy().evaluate(proposal, snapshot)` -> `PolicyDecision`.
5. `CommandExecutor.execute(policy.commands, turn_id)` -> `tuple[CommandEvent]`.
6. `build_runtime_result(...)` -> `RuntimeResult` (+ `pending` extrait des events).
7. `ReplyComposer.compose(result, snapshot)` -> texte ; puis `OutputGuard.verify` ;
   si non-ok, **une** tentative de reparation, sinon `guard.sanitized_reply`.
8. `persist_turn` (audit.py) + `mark_event_lock("completed")`.

## 3. Carte des fichiers (par couche)

### Orchestration / entrée
- **`runtime.py`** — `handle_event`, `RuntimeDeps` (db_path, `coach_llm`, `reply_llm`,
  `generation_llm`, `max_steps=6`), `HandleEventResult`. Cable les couches, gere les locks
  et la reparation de reply. `RuntimeDeps.generation_llm` = client dédié (gros budget
  tokens) pour la generation Meso, distinct du `coach_llm` (1024) et `reply_llm`.
- **`event.py`** — `InputEvent` (id, user_id, source, type, text, payload, occurred_at).
- **`idempotency.py`** — `EventLock`, `acquire_event_lock` (INSERT unique sur event_id),
  `mark_event_lock`, `lock_allows_retry` (retry si `failed` ou lock `running` stale).

### Perception (lecture DB -> modele typé en mémoire)
- **`snapshot.py`** — le cœur de la perception.
  - Vues immuables : `SessionView`, `ActivityView`, `FactView`, `PendingView`,
    `CommandEventView`.
  - `WorldSnapshot` : photo complete d'un user à un instant (today, now, timezone,
    `current_plan` [today..+14j], `recent_plan` [−7j..−1j], `recent_activities`,
    `active_facts` [non expirés, non résolus, ≤10], `active_pending` [1 ouvert non
    expiré], `recent_execution_events`, `recent_plan_events`, `conversation_state`,
    `last_planned_week` [derniere semaine Meso committée, pour le chaînage forward]).
  - `SnapshotHeader` (`header()`) : le distillat **texte** donné au coach (`to_prompt_text`)
    — today, prochaines séances, `recent_training` (= `recent_plan[:6]`, seed semaine),
    `active_facts` (≤5), `pending`, `last_unresolved_intent`, dernier event d'exécution.
    Borné à 500 mots (assert).
  - `SnapshotBuilder.build` : les requetes SQL de lecture (`_load_sessions`,
    `_load_active_facts`, `_load_pending`, `_load_last_planned_week`, …).
- **`state.py`** — `ConversationState` (last_unresolved_intent, last_execution_event_id,
  last_pending_id, last_user_turn_id, expires_at) + `active_at(now)` (périme l'intention).

### Raisonnement (le coach LLM + ses outils)
- **`agent.py`** — `CoachAgent.run` : la boucle ReAct bornée (`max_steps`). Détail § 4.
- **`tool_catalog.py`** — `for_event(event, snapshot)` : construit la liste des `ToolSchema`
  exposés ce tour. Gating : `resolve_pending` n'apparait **que si** un pending est ouvert ;
  sous une intention `move_session` active, on restreint à un sous-ensemble (`allowed`).
- **`tools_read.py`** — `ToolContext` (db_path, snapshot, scratchpad, `generation_llm`) +
  les tools **read-only** : `get_current_plan`, `get_plan_day`, `get_session`,
  `get_recent_execution_events`, `get_active_facts`, `resolve_date_reference`.
- **`tools_proposal.py`** — les tools qui **emettent une `ActionProposal`** (mutation
  proposée, jamais appliquée ici) : `propose_execution_update`,
  `propose_execution_correction`, `propose_plan_patch`, `propose_memory_update`,
  `propose_fact_resolution`, `ask_clarification`, `resolve_pending`. `_normalize_intensity`
  / `_normalize_sport` reparent l'enum produit par le modele (garder la sortie du modele
  est permis ; ce n'est pas du regex sur texte user). `_record` / `_trace` = le journal
  d'appels dans le scratchpad.
- **`meso/runtime_tool.py`** — `propose_week` : le tool coach-callable qui appelle le
  moteur Meso (§ 9).

### Artefacts de décision
- **`proposals.py`** — `ActionProposal` (le seul type que le coach emet) + ses *drafts* :
  `MemoryFactDraft`, `ExecutionUpdateDraft`, `ExecutionCorrectionDraft`, `PlanPatchDraft` /
  `PlanPatchOperation`, `FactResolutionDraft`, `WeekProposalDraft`, `PendingResolutionDraft`.
  `proposal_to_dict` / `proposal_from_dict` = (dé)sérialisation (audit + payload de pending).
  `ActionProposal.type` ∈ {answer, ask_clarification, memory_update, execution_update,
  execution_correction, plan_patch, fact_resolution, week_proposal, pending_resolution,
  no_send}.

### Autorité (la décision déterministe)
- **`policy.py`** — `RuntimePolicy.evaluate` : prend une `ActionProposal` + le snapshot,
  rend une `PolicyDecision` (action ∈ {allow_commit, create_pending, block,
  ask_clarification, answer_only, no_send}, reason, risk_level, `commands`, `reply_facts`).
  Définit aussi les **Commands** typées (`SetSessionStatusCommand`,
  `CorrectSessionStatusCommand`, `ApplyPlanPatchCommand`, `CreatePendingConfirmationCommand`,
  `UpsertMemoryFactCommand`, `ResolveMemoryFactCommand`, `UpdateConversationStateCommand`,
  `ResolvePendingConfirmationCommand`). Détail § 7.
- **`sport_rules.py`** — `evaluate_plan_patch_sport_rules` : les garde-fous sportifs
  (source `done` protégée ; hard collé à un hard/long bloqué ; fact santé bloque un hard ;
  multi-op / séance clé / swap -> `pending`). Appelé par `policy._plan_patch`.

### Exécution (le seul endroit qui écrit)
- **`executor.py`** — `CommandExecutor.execute` : applique chaque command dans une
  **transaction** (`_execute_one` : connect -> `_apply_command` -> insert `v0_command_events`
  -> commit ; exception -> rollback + event `blocked` + stop). `_apply_*` par type de
  command ; idempotence via `UNIQUE(turn_id, command_type, target_id)` ; chaque commande
  produit un `CommandEvent` (before/after/reason) = l'audit trail des mutations.
- **`db.py`** — `SCHEMA` (tables `v0_*`), `connect`, `init_db`, `reset_db`, `V0_TABLES`.
  Tables : `v0_input_events`, `v0_turns`, `v0_command_events`, `v0_scheduled_sessions`,
  `v0_activities`, `v0_facts`, `v0_conversation_state`, `v0_pending_confirmations`,
  `v0_idempotency_locks`, `v0_planned_weeks` (store typé Meso, Slice 3b).

### Sortie (voix + vérité)
- **`result.py`** — `RuntimeResult` (ce qui s'est passé : committed_events, blocked_reasons,
  pending, read_facts) + `ReplyContract` (must_include, must_not_claim, tone, max_sentences).
  `build_runtime_result` calcule `read_facts = policy.reply_facts or proposal.answer_facts`
  et le contrat (must_not_claim injecte « c'est fait » quand un pending est ouvert ou
  qu'aucun event n'est appliqué).
- **`reply.py`** — `ReplyComposer.compose` : **tous** les cas passent par le LLM (la voix
  vit ici). Les templates ne servent plus que de filet : `_fallback` (meilleure vérité
  dispo si le LLM échoue), re-prompt si la voix omet un fait porteur (`_commit_omits_fact`)
  ou une séance lue (`_omits_plan_sessions`).
- **`guard.py`** — `OutputGuard.verify` : lit la **sortie du modele** (jamais le texte
  user) et rend oui/non. Motifs bloquants : `claim_without_event`, `pending_action_claim`,
  `internal_jargon`, `meta_opening`, `english_leak`, `raw_json_visible`,
  `technical_id_visible`, `truncated_reply`, `unsupported_date`, `old_plan_date`. Sur non,
  `_safe_reply` rend une vérité sobre.

### Audit
- **`audit.py`** — `persist_turn` (snapshot + proposal + policy + result + reply + guard +
  tokens + latence dans `v0_turns`), `persist_input_event`, `load_turn`. C'est ce qui rend
  un tour **rejouable**.

### Moteur Meso (`meso/`)
- **`meso/model.py`** — modele typé : `TypedSession` (date, type, duration_min, intensity,
  detail), `PlannedWeek`, `WeekActuals`, `WeekTarget`, `TypedConstraint`, `Signal`,
  `ContextPack`. Charge pondérée (`load` = durée × poids), `derive_continuity_target`,
  `actuals_from_week` (chaînage forward).
- **`meso/verifier.py`** — `verify_week` déterministe = l'autorité du moteur. Propriétés :
  non-vide (tous modes), séance clé prescrite, anti-drop de charge, ramp/spike, espacement
  des séances dures, conflit santé. Modes `continuity` / `transition`. `limits_intensity`
  pilote la **réduction-sous-contrainte** (relâche clé + plancher).
- **`meso/generator.py`** — `generate_week` : boucle **generate -> verify** (max 3), tool
  `emit_week`, sinon `_template_week` (filet déterministe sizé à la bande).
- **`meso/context.py`** — pont `fact -> TypedConstraint` (`constraints_from_snapshot`,
  santé->intensité, conservateur) + `build_context_pack` (seam du context-pack ; le
  chaînage forward y branchera côté store).
- **`meso/runtime_tool.py`** — `propose_week` (§ 9).

### Prompts (`prompts/`)
- **`prompts/coach_system.py`** — `COACH_SYSTEM_PROMPT` : règles dures + world view + liste
  des tools + exemples. C'est ici qu'on **enseigne** au coach (jamais de regex). Détail § 6.
- **`prompts/reply_system.py`** — `REPLY_SYSTEM_PROMPT` : la voix (tons, honnêteté).
- **`prompts/week_generation.py`** — `GENERATION_SYSTEM` + `render_generation_prompt` :
  le prompt du générateur Meso (constraint-aware : la clé saute sous restriction d'intensité).

### Clients LLM (`llm_clients/`)
- **`llm_clients/base.py`** — `ToolCall`, `LLMResponse`, `ToolSchema`, protocole `LLMClient`
  (`chat_with_tools(system, messages, tools) -> LLMResponse`).
- **`llm_clients/fake.py`** — `FakeLLMClient` (réponses scriptées) pour les tests couche 1.

### Pont legacy (`adapters/`, hors noyau)
- **`adapters/current_db_snapshot.py`** — `materialize_v0_db` : bootstrap one-shot du
  store live depuis la DB legacy (plan -> `v0_scheduled_sessions`, activites ->
  `v0_activities`, faits -> `v0_facts`). Utilisé pour la mise en prod le 8 juin 2026.
  **Point critique** : remap `users.id=1 -> telegram_chat_id` ; faits legacy jetes
  (bruit accumule) ; plan futur legacy supprime (V0 planifie l'avenir). Hors budget LOC ;
  le noyau ne l'importe jamais (dépendance `adapters -> core`, jamais l'inverse).
- **`adapters/strava_v0_sync.py`** — `sync_strava_to_v0` : tire les activites Strava
  recentes via le token legacy (`strava_connections`), upserte dans `v0_activities`,
  dedoublon par Strava activity id. Import paresseux. **Seul writer de `v0_activities`**
  (hors bootstrap). Actif en prod via le job periodique du runner.

## 4. L'agent coach en détail (`agent.py`)

`CoachAgent.run` est une boucle ReAct bornée à `max_steps` (défaut 6, justifié : les
modèles à lecture sérielle dépensent des tours en reads). À chaque step :

1. `llm_client.chat_with_tools(system, messages, tools)`.
2. Si la réponse contient des **read tools** (`is_proposal=False`), on les exécute
   (`_execute_read_tool_calls`), on injecte leurs résultats dans `messages`, et on continue
   à chercher un proposal.
3. `_merged_proposal` assemble le résultat : il cumule **tous** les `propose_memory_update`
   (note durable) + le **premier** proposal d'action (first-action-wins). Les notes
   « chevauchent » l'action (**fact-rider** : noter un fait ET agir dans le même tour).
4. Garde-fous de contrat (re-prompt une fois sinon `no_send`) : intention move active ->
   pousse `propose_plan_patch` ; `plan_patch` sans `get_session` source ; date de planning
   non résolue ; clarification `move_session` au `target_date` incohérent.
5. Sans proposal mais avec du texte : c'est un `answer` seulement si supporté par un read
   (sinon `no_send` / re-prompt).

Sorties possibles : une `ActionProposal` typée, ou `no_send` (sous-action sûre : le coach
préfère ne rien faire plutôt qu'un write erroné).

## 5. Les tools

Un tool = un `ToolSchema(name, description, parameters, handler, is_proposal)`. Deux
familles :

- **Read** (`is_proposal=False`) : lisent le snapshot/DB, renvoient des données. Le coach
  s'en sert pour **se grounder** avant de parler ou d'agir.
- **Proposal** (`is_proposal=True`) : renvoient une `ActionProposal`. Ils ne mutent **rien** ;
  c'est la policy qui décide, l'executor qui écrit.

Gating (`tool_catalog.for_event`) : `propose_week` exposé sur tout `user_message` ;
`resolve_pending` **seulement** si `snapshot.active_pending` ; sous `move_session` actif,
liste restreinte. La référence courte des tools vit dans `RUNTIME-TOOLS.md`.

## 6. Les prompts — voix vs vérité

Doctrine « Voix Vs Vérité » (`LLM-FIRST-CONVERSATION.md`) : la **voix** (formulation) vit
dans le LLM (coach + reply) ; la **vérité** (ce qui est écrit, ce qu'on peut affirmer) est
tenue par le backend (policy + executor + guard).

- `COACH_SYSTEM_PROMPT` enseigne **quoi appeler** (jamais comment parser) : grounding par
  read tools, choix d'adaptation, `propose_week`, et la résolution de pending (un
  « oui mais [contrainte] » n'est **pas** un accept — voir § 9).
- `REPLY_SYSTEM_PROMPT` : la voix finale, chaleureuse, qui ne ment pas sur un write.
- `GENERATION_SYSTEM` + `render_generation_prompt` : le générateur Meso, constraint-aware.

## 7. Policy & commands (`policy.py`)

`evaluate` route par `proposal.type` puis applique le **fact-rider** (les notes mémoire
chevauchent l'action) et un plafond de 3 commands. Chaque branche valide/groundé contre la
**vérité DB** du snapshot :

- `answer` -> `answer_only`.
- `ask_clarification` -> persiste l'intention non résolue.
- `memory_update` / `fact_resolution` -> `allow_commit` (fact_resolution **grounde** le
  fact_id contre `active_facts`).
- `execution_update` / `execution_correction` -> grounde la séance / l'event, compile une
  mise à jour en correction si un event récent existe.
- `plan_patch` -> grounde la source, compile, passe par `sport_rules` (allow / block /
  pending).
- `week_proposal` -> **`create_pending`** (stocke `proposal_to_dict` en payload).
- `pending_resolution` -> **grounde** `pending_id` contre `active_pending.id` (sinon
  clarification) ; accept/reject -> `ResolvePendingConfirmationCommand`.

`reply_facts` = les faits que la reply doit porter (ils deviennent `result.read_facts`).

## 8. Executor & DB (`executor.py`, `db.py`)

Chaque command -> un `_apply_*` qui fait le SQL, lit `before`/`after`, et renvoie
`(before, after, reason)`. `_insert_event` écrit un `v0_command_events` (l'audit des
mutations). Tout est **transactionnel par command** et **idempotent** par
`(turn_id, command_type, target_id)`. Le `pending` créé par la policy stocke le
`payload_json` complet ; à la résolution accept, `_apply_resolve_pending` relit ce payload
et **dispatch par type** (`week_proposal` -> `_apply_commit_week` écrit `v0_planned_weeks`
+ marque le pending `accepted` ; type non câblé -> **fail loud**).

## 9. Le moteur Meso & le flux semaine (Slice 0→3b)

Le moteur est une **boîte à outils coach-callable**, même paradigme que le runtime
(`PLANNING-V0.md`). Le LLM génère/personnalise ; le **vérificateur tient l'autorité**.

Flux complet d'une semaine (running-only) :

```text
"fais-moi ma semaine"  -> coach declare le seed (last_week_load, key_type) depuis recent_training
  propose_week (runtime_tool):
     seed = snapshot.last_planned_week  (chaînage forward)  OU  seed declaré (cold-start)
     ContextPack{target, last_week_actuals, constraints(=facts santé typés), signals}
     generate_week:  LLM emit_week -> verify_week  (boucle max 3)  -> sinon template filet
  -> ActionProposal(type=week_proposal, week_proposal=WeekProposalDraft)
  policy: create_pending  (payload = la semaine vérifiée ; reply = "je te propose, je cale ?")
TOUR SUIVANT  "oui" / "non" / "oui mais ..."
  coach -> resolve_pending(pending_id, accept|reject)
  policy: grounde l'id -> ResolvePendingConfirmationCommand
  executor: accept -> ecrit v0_planned_weeks (+ pending accepted) ; reject -> pending rejected
```

**Réduction-sous-contrainte** : un fact santé actif -> `TypedConstraint(restricts=intensity)`.
Le générateur (prompt) **et** le vérificateur **suppriment la séance clé** cette semaine
(volume facile only) ; le vérif relâche le plancher de charge mais **rejette une semaine
vide** (invariant non-vide, tous modes). Prouvé couche 2 (`probe_constrained_week`, 4/4).

**Comportement « okay mais [contrainte] » (état courant — à connaître).**

**Blessure / douleur** (tranche #1, 8 juin 2026) : le coach note le fait santé ET appelle
`propose_week(intensity_restricted=true)` **dans le même tour**. Le LLM *déclare* la
contrainte qu'il a comprise ce tour (`intensity_restricted: bool`) ; le snapshot-stale
ne bloque plus car la contrainte est déclarée directement au générateur (pas relue depuis
le snapshot). Un nouveau pending `week_proposal` **supersede** l'ancien ouvert :
`executor._apply_create_pending` passe le précédent au status `superseded` — un seul pending
vit à la fois. Le fact-rider committe la note santé en parallèle. Le vérificateur produit
la semaine sans intensité (réduction-sous-contrainte existante). État : *blessure
ré-adaptée same-turn*.

**Indispo** (8 juin 2026, tranche #2 livrée) : same-turn note availability +
`propose_week(blocked_days=[...])` -> semaine avec REST sur les jours bloqués, clé sur un
jour disponible. Vérificateur `_check_blocked_days` (rejette toute séance sur un jour
bloqué, tous modes) + plancher de charge relâché (garde la clé prescrite). Générateur et
template blocked-days-aware. Prouvé couche 2 (`probe_live_simulation --persona indispo`) :
PASS, juge LLM 5/5/5/5. Résiduel : persistance cross-tour différée.

**Cibles résolues.** Spécs : `docs/superpowers/specs/2026-06-08-readapt-blessure-same-turn-design.md` (tranche #1),
`docs/superpowers/specs/2026-06-08-v0-dogfood-wiring-design.md` (tranche #2 + dogfood).
Détails : `BUILD-ORDER.md`.

**Différés (accommodés, pas codés)** : persistance cross-tour de l'availability ; matérialisation
de la semaine committée vers `v0_scheduled_sessions` (plan exécutable) ; handler de commit
`plan_patch` ; décision `modify` (« fais plus varié ») ; suivi d'exécution (phase 2).

## 10. Tests & sondes (deux couches)

Doctrine : `V0-TEST-DOCTRINE.md`.

- **Couche 1 — `tests/runtime_v0/` + fake matrix** (`scripts/v0_eval/run_matrix.py`) : filet
  mécanique d'anti-régression + danger metrics. **Pas** une boussole de qualité (la matrice
  scripte les deux côtés). `FakeLLMClient` scripte les réponses.
- **Couche 2 — sondes live, vrai provider** (`scripts/v0_eval/`) : là où la qualité réelle
  se juge. Sondes actuelles :
  - `probe_propose_week.py` — propose_week se déclenche et ancre le seed dans le réel.
  - `probe_resolve_pending.py` — propose -> confirme/refuse -> commit/drop.
  - `probe_constrained_week.py` — contrainte active : la semaine respecte + régénère.
  - `probe_live_simulation.py` — **self-play** : un LLM joue un athlète non scripté
    (indispo / blessure / lassitude) face au vrai coach ; oracles déterministes + transcript
    + juge LLM. C'est la sonde qui révèle le comportement réel multi-tour.

## 11. Deploiement / live (8 juin 2026)

V0 est le coach Telegram de Loïc depuis le soir du 8 juin 2026.

- **Entrypoint prod** : `scripts/dogfood_telegram.py` — poll Telegram (long-poll),
  `handle_event` sur le store v0_*, reply, allowlist (`FITMAS_V0_DOGFOOD_CHAT_IDS`).
  Job periodique integre : `sync_strava_to_v0` toutes les `FITMAS_V0_STRAVA_SYNC_SECONDS`
  secondes (defaut 900). Lancé via `scripts/start-prod` (remplace l'ancien bot legacy).
- **Store live** : `FITMAS_V0_DB_PATH` -> `/data/fitmas_v0_dogfood.db` (volume Fly CDG).
  Tables `v0_*` = source de verite. La DB legacy FastAPI tourne encore mais ses donnees
  ne sont plus utilisees par le coach.
- **Bootstrap (one-shot, 8 juin)** : `materialize_v0_db` a injecte le plan courant, les
  activites et des faits propres depuis la DB legacy. Remap `user_id 1 -> chat_id` ;
  faits legacy jetes (accumulation de bruit) ; plan futur legacy supprime.
- **Lacunes connues** : run<->session non matchees automatiquement ; voix terse ;
  `propose_week` cible prochain lundi uniquement ; pas de proactivite (briefings off) ;
  solo (`legacy_user=1` hardcode dans `strava_v0_sync`).

## 12. Isolation & budget

- **Isolation** (test `test_import_boundaries.py`) : le noyau n'importe aucun layer legacy ;
  `adapters/` est le seul pont et ne compte pas dans le budget.
- **Budget LOC** : objectif sain `~2500` pour la boucle conversationnelle nue ; le moteur
  Meso est une **enveloppe acquise** (re-baseline 7 juin) ; le cap dur ne monte que sur
  capacité **prouvée**, justification loggée dans le test. Détail : `RUNTIME-V0.md` Budget.

## 13. Où vit quoi (réflexe rapide)

| Je veux… | Fichier |
|---|---|
| changer ce que le coach a le droit d'appeler | `tool_catalog.py` |
| enseigner un comportement au coach | `prompts/coach_system.py` |
| ajouter un tool de lecture | `tools_read.py` |
| lire la semaine committée (get_planned_week) | `tools_read.py` → `v0_planned_weeks` |
| ajouter un tool d'action (proposal) | `tools_proposal.py` (+ draft dans `proposals.py`) |
| changer une règle d'autorité / un grounding | `policy.py` |
| ajouter une règle sportive de sécurité | `sport_rules.py` |
| écrire / migrer une table | `db.py` (+ `_apply_*` dans `executor.py`) |
| changer ce que le coach voit | `snapshot.py` (`header()` pour le texte) |
| durcir une honnêteté de reply | `guard.py` |
| toucher la génération de semaine | `meso/generator.py` + `prompts/week_generation.py` |
| changer une propriété de semaine saine | `meso/verifier.py` |
| brancher le produit réel | `adapters/` (hors noyau) |
| runner Telegram V0 (prod + local) | `scripts/dogfood_telegram.py` (hors noyau) |
| sync Strava -> v0_activities | `adapters/strava_v0_sync.py` |
| bootstrap store depuis legacy (one-shot) | `adapters/current_db_snapshot.py` `materialize_v0_db` |
