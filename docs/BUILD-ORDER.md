---
summary: état actuel de chaque phase, plan de priorités et prochaines étapes
read_when:
  - commencer un chantier
  - donner du contexte à un agent de code
  - vérifier l'avancement
  - recadrer les priorités produit
---

# FitMAS — Build Order

## Role canonique

Ce document est la **source de verite** pour :

- ce qui existe vraiment dans le code
- ce qui reste partiel, legacy ou trompeur
- l'ordre de construction recommande a partir de maintenant

Si un autre doc diverge :

- `BUILD-ORDER.md` gagne sur **l'etat reel** et **la suite**
- `PRODUCT.md` decrit la promesse et le scope
- `ARCHITECTURE.md` decrit la structure technique et les contraintes
- les docs domaine decrivent les contrats locaux

## Phrase guide

**Un premier coach que Loïc reconnaît, comprend, et a envie de rouvrir demain.**

## Roadmap Active — 7 mai 2026

Ordre courant :

```text
1. Excellence sportive
2. Observabilite decide() None
3. Prompt/contexte
4. Cadrage memoire leger
5. Refactor global
6. UX/UI
```

Regle d'arbitrage : sport d'abord. Le prochain gros gain produit reste une
semaine sportivement credible, adaptable et relue. Le chantier prompt/contexte
vient ensuite pour fiabiliser les couches LLM. La memoire reste en cadrage
conceptuel seulement : pas de refactor structurel tant que le comportement
sportif cible n'est pas stabilise.

Docs a ouvrir selon le chantier :
- excellence sportive : `docs/SPORT-QUALITY-REVIEW.md`
- prompt/contexte + `decide() None` : `docs/PROMPT-CONTEXT-REFACTOR.md`
- memoire : `docs/MEMORY-V2.md`

## Checkpoint courant — 4 mai 2026

### Incident dogfood briefing matin du 2 mai

Le briefing du 2 mai a hallucine des chiffres factuels (`"2 sorties offplan cette semaine"` alors que zero offplan existe en DB pour la semaine en cours). Pas un bug de voix, un bug de **grounding factuel**.

Cause racine identifiee : `_recent_proactive_context()` (`backend/src/fitmas/skills/heartbeat/heartbeat.py:535-553`) reinjecte les 2 derniers messages proactifs **sans aucun TTL** — un briefing d'une semaine anterieure ressort dans le prompt actuel, et le LLM recopie ses chiffres perimes au lieu de lire le bundle Truth (qui dit `offplan_count=0`).

L'audit declenche par cet incident a confirme 3 failles structurelles connexes :

- **Voix coach fragmentee entre pipelines** : Phase 1 voix conversation a durci `_CONVERSATION_SYSTEM_TEXT` mais le briefing/reminder/weekly review gardent leurs propres regles, sans few-shots BONS/MAUVAIS, sans detecteur receipt-style. Pas de source unique de doctrine voix en code.
- **Dual-source de verite runtime** : ✅ core ferme le 3 mai. `plan_actions.py` et `mutations.py` ne mutent plus `DayPlan`; `signals.py` lit `ScheduledSession`; `activities.py` matche les activites contre `ScheduledSession`; `api_activities.py` et `strava.py` ne chargent plus le plan hebdo pour matcher ou marquer une activite.
- **Lectures `DayPlan/WeeklyPlan` restantes** : limitees au template/onboarding/admin/compat (`schema.py`, `models.py`, `repository.py`, `api_onboarding.py`, `api_read.py` endpoint legacy `/week`, `seed.py`, `state.py`, `api_debug.py`, `api_ops.py`).

### Acquis recents — Phase A LLM-first

- Phase 1 voix conversation : ✅ shippe 30 avril 2026 — bloc "Voix coach (regles imperatives sur fitmas_message)" + 8 few-shots BONS et 9 MAUVAIS dans `_CONVERSATION_SYSTEM_TEXT` (`backend/src/fitmas/llm_prompt_builder.py`), detecteur `_message_looks_receipt_style` log-only avec 6 patterns dans `backend/src/fitmas/llm.py`.
- Phase 2 `pending_resolution` typed + `memory_actions` + `execution_actions` : ✅ shippe 1 mai 2026 (commits anterieurs) — confirmations resolues structurellement par le LLM (`accept_pending` / `reject_pending` / `modify_pending` / `ignore`), plus de re-decision sauvage. Memory/execution actions executees par writers bornes post-validation.

### Plan en cours — 5 chantiers

| # | Chantier | Effort | Doc canonique |
|---|---|---|---|
| 0 | ✅ Fix TTL `_recent_proactive_context` (heartbeat) — shippe 2 mai 2026 | 1h | section ci-dessous |
| 1 | ✅ Voix coach unifiee (module `coach_voice.py` partage tous pipelines) — shippe 3 mai 2026 | 1.5j | `docs/SOUL.md` section "Voix unifiee partagee" |
| 1bis | ✅ Claim guard via LLM repair (plus de canned "Je n'ai applique aucun changement...") — shippe 3 mai 2026 | 2h | section ci-dessous |
| 1ter | ✅ Capture indirecte de constraints dans le prompt conversation — shippe 3 mai 2026 | 1h | section ci-dessous |
| - | ✅ Cleanup DB prod : 395 rows obsoletes purgees, memoire propre — 3 mai 2026 | 1h | section ci-dessous |
| 1quater | ✅ Coach reliability slice 0 — final reply composer + guards backend/heartbeat + execution receipt hardening — shippe 3 mai 2026 | 1j | `docs/COACH-RELIABILITY-REFACTOR.md` |
| 2 | ✅ Truth source runtime core — `ScheduledSession` seul pour mutations/signals/activity matching — shippe 3 mai 2026 | 1j | `docs/COACH-COHERENCE-REFACTOR.md` section "Plan 2 mai 2026" |
| 3A | ✅ Conversation tool loop partiel — multi-round read/validation + `validate_plan_patch`, `PlanPatch` conserve — shippe 3 mai, deploye 4 mai 2026 | 1.5j | section ci-dessous |
| 3A-bis | ✅ Heartbeat read-only fake-action guard — LLM judge systematique `ALLOW/BLOCK` sur chaque sortie heartbeat, sans regex fake-action — 4 mai 2026 | 0.5j | section ci-dessous |
| 4 | ✅ Observabilite proactive coach loop — dump contexte, prompt, decision `send/no_send`, judge, message final — deploye 4 mai 2026 | 0.5j | section ci-dessous |
| P1 | ✅ Post-event reply verifier — verifier/reparer toute phrase finale post-mutation contre `events_committed + session_changes` — deploye 4 mai 2026 | 0.5j | section ci-dessous |
| P1-bis | ✅ PlanPatch confirmation parity — changement de sport sur seance cle repasse par confirmation, comme `MutationDecision` — deploye 4 mai 2026 | 0.5h | section ci-dessous |
| 3B-A | ✅ Tool-use loop proactive heartbeat read-only — le coach relit la verite recente avant de parler — deploye 4 mai 2026 | 0.5j | `docs/LLM-FIRST-CONVERSATION.md` section "Phase 5 - Tool-use loop unifie" |
| P1-ter | ✅ Execution receipt repair hardening — plus d'outage generique si le LLM reconnait "pas fait hier" sans `execution_actions` et qu'une cible follow-up est structuree — deploye 4 mai 2026 | 0.5j | section ci-dessous |
| P1-quater | ✅ Dogfood API fallout — execution action verifier + post-event date facts + target ambiguity + durable availability memory — deploye 4 mai 2026 | 0.5-1j | section ci-dessous |
| 3B-B | ✅ Proactive PlanPatch propose + confirmation Telegram pending, pas de commit autonome — implemente localement 5 mai 2026 | 1j | section ci-dessous |
| A+0 | ✅ Documentation Sport Quality / Week Coherence — doctrine reviewer sportif, policy runtime, progression par stimulus | 0.5j | `docs/SPORT-QUALITY-REVIEW.md` |
| A+1-A+3 | ✅ **Phase A+ core gate** — simulation, contexte deterministe, LLM reviewer/fallback type, gate runtime dans `apply_patch_for_user`, smoke API reel `scripts/smoke-a-plus-api` — implemente localement 5 mai 2026 | 3-4j | `docs/SPORT-QUALITY-REVIEW.md` + section "Phase A+" ci-dessous |
| 3B-C | ✅ Action-tools natifs bornes, **apres A+ core gate** — `draft_move_session`, `draft_swap_sessions`, `draft_replace_session`, `draft_lighten_day`, `draft_create_session`, candidates PlanPatch sans write — implemente localement 5 mai 2026 | 2-3j | `docs/RUNTIME-TOOLS.md` |
| A+4 | ✅ Tool `validate_week_coherence` validation-only conversation/planning/heartbeat + capture pending heartbeat reviewee — implemente localement 5 mai 2026 | 0.5-1j | `docs/SPORT-QUALITY-REVIEW.md` |
| A+5 | ✅ Review semaine generee avant commit — guard avant `replace_plan` / `ScheduledSession`, fallback conservative si policy review non `valid`, fallback persistable sauf `blocked` — implemente localement 5 mai 2026 | 1j | `docs/SPORT-QUALITY-REVIEW.md` |
| P1-quinquies | ✅ Lane terminale `close_turn` — clotures sociales sans tools, sans marker question ouverte, composer final via `final_reply.py` — implemente localement 5 mai 2026 | 0.5j | `docs/superpowers/plans/2026-05-05-terminal-close-lane.md` |
| P1-sexies | ✅ Composer final `no_change` — `CoachDecision(no_change)` + compat legacy passent par `final_reply.py`, avec faits memoire/execution appliques — implemente localement 5 mai 2026 | 0.5j | `docs/superpowers/plans/2026-05-05-no-change-final-composer.md` |
| P1-septies | ✅ Composer final `plan_lookup` — lecture factuelle via `final_reply.py` avec guard anti-drift chiffres/jours/zones/statuts — implemente localement 5 mai 2026 | 0.5j | `docs/superpowers/plans/2026-05-05-plan-lookup-final-composer.md` |
| P1-nonies | ✅ Grounded final speech + heartbeat future truth — temporal refs typees, grounding packet partage, verifier semantique LLM pour lookup planning/confirmation, idempotency key durable, `PlanWindowTruth` heartbeat — implemente localement 7 mai 2026 | 0.5-1j | `docs/superpowers/plans/2026-05-07-grounded-final-speech-and-heartbeat.md` |
| P1-octies | 🔥 Prompt/context optimization pass + `decide() returned None` reduction — reduire et specialiser le contexte donne a chaque couche LLM (`turn_planner`, `decide`, composers, verifiers, heartbeat), auditer les prompts qui diluent la decision, et mesurer/reduire les retours `None` du decisionnaire — prochain chantier dogfood | 1-2j | `docs/PROMPT-CONTEXT-REFACTOR.md` + section ci-dessous |

**Total restant avant B0 : 1-2 jours**. Phase A+ est fermee localement, et P1-nonies a retire les contradictions factuelles visibles les plus dangereuses. La prochaine lane reste P1-octies : audit prompt/contexte et baisse des `decide() returned None`, puis dogfood court et B0 si stable.

### Chantier P1-nonies — Grounded final speech + heartbeat future truth ✅

Objectif livre le 7 mai 2026 : ne plus laisser une phrase finale visible
contredire une verite planning deja connue du backend.

Fix livres :
- `conversation_turn_planner.py` peut maintenant retourner des
  `temporal_references` typees, `requires_truth_read` et `truth_scope`, que le
  backend resout ensuite sans parser le texte utilisateur libre ;
- nouveau `grounding_contract.py` : `ReplyGroundingPacket`, temporal refs
  resolues et `PlanWindowFact` partages entre conversation, final reply et
  heartbeat ;
- `plan_lookup` planning passe par un verifier semantique LLM contre le
  grounding DB, plus par un tracking deterministe de tokens/chiffres du
  brouillon LLM ;
- les confirmations `PlanPatch` recoivent local date + plan window, puis sont
  verifiees contre ces facts avant sortie ;
- acceptance de pending `PlanPatch` utilise la reply post-event verifier, pas le
  vieux `patch.coach_message` ;
- les closes sociaux recoivent un grounding et traitent le dernier message coach
  comme contexte social, pas comme source de verite planning ;
- idempotence Telegram durable : `conversation_turns.client_message_key` et
  `source` sont des colonnes, plus seulement un champ fragile de `context_json` ;
- heartbeat matin recoit `PlanWindowTruth` 7 jours et le vrai `_llm_generate`
  peut verifier la phrase proactive contre ce plan futur.

Frontiere doctrine : aucune regex/keyword sur texte utilisateur libre. La
comprehension reste LLM ; le code resout et verifie uniquement des artefacts
LLM/DB structures.

### Chantier P1-octies — Prompt/context optimization pass 🔥

Prochain chantier dogfood apres la passe sportive.

But : donner a chaque couche LLM juste le contexte et le contrat dont elle a
besoin. Commencer par tracer les `decide() returned None`, puis introduire un
`ConversationContextPack`, un `PromptContract` par intent et des snapshots de
prompts.

Frontiere : pas de parser deterministe sur texte utilisateur libre, pas de gros
refactor memoire, pas de nouvelles regles de prompt pour masquer une cause
structurelle.

Doc canonique : `docs/PROMPT-CONTEXT-REFACTOR.md`.

### Deploiement prod — 4 mai 2026

`main` est deploye sur Fly.io avec le bloc Phase A/P1-quater du 4 mai 2026.

Livres ensemble :
- Chantier 2 truth source runtime core ;
- Chantier 3A conversation tool loop partiel ;
- retry JSON court apres tool-use DeepSeek avant repair lourd ;
- idempotence Telegram/API via `client_message_key` pour eviter double traitement apres timeout ou reponse perdue ;
- heartbeat read-only fake-action guard via LLM judge `ALLOW/BLOCK`, sans regex fake-action ;
- P1-quater dogfood API fallout : coherence `execution_actions`, facts date/day post-event, confirmation cible planning ambigue, memoire disponibilite.

Verification avant deploy :
- `./scripts/test-backend -q` : 648 passed, 11 skipped, 6 subtests passed ;
- `.venv/bin/python -m compileall backend/src/fitmas` : OK ;
- `git diff --check` : OK ;
- smoke reel DeepSeek `heartbeat_non_completion` : exit 0, renfo J-1 marque `skipped`.

Dette observee dans le smoke reel : `weekly_review` pouvait encore dire "regarde ton app demain matin, j'ai ajuste le planning" alors qu'aucune mutation n'etait appliquee. Traitement 3A-bis : LLM judge `ALLOW/BLOCK` systematique sur chaque sortie heartbeat read-only.

### Chantier 0 — Fix TTL `_recent_proactive_context` ✅ shippe 2 mai 2026

Symptome : briefing du 2 mai a recopie les chiffres d'un proactif anterieur.

Cause exacte (`heartbeat.py:535-553`) : query sur `CoachMessage` sans `filter(created_at >= cutoff)`. Un briefing J-7 etait reinjecte tel quel et le LLM recopiait ses chiffres comme s'ils s'appliquaient a la semaine en cours.

Fix livre :
- TTL de **48 heures** ajoute a `_recent_proactive_context` (`backend/src/fitmas/skills/heartbeat/heartbeat.py`) ; constante exposee `RECENT_PROACTIVE_TTL_HOURS = 48`, parametrable via kwarg `ttl_hours`
- Le choix 48h couvre "hier + aujourd'hui" pour novelty avoidance (eviter de recycler la meme attaque jour apres jour) tout en excluant les chiffres > 2 jours
- Cutoff calcule en UTC naive depuis `get_local_now(user.timezone)` pour match le shape `created_at` en DB
- Nouveau test `tests/test_briefing_proactive_context.py` : 6 cas (within TTL inclus / older excluded / mixed only recent kept / boundary +1h excluded / parametrable / non-proactive ignores)
- Test existant `test_morning_briefing_includes_recent_proactive_messages_for_novelty` ajuste : utilise `hours=30` (dans 48h TTL, hors today daily cap)

Garanties verrouillees :
- aucun message proactif > 48h n'apparait dans le prompt heartbeat
- les chiffres presents dans le bundle (YesterdayTruth, TodayTruth, WeekDigest) restent l'unique source des stats hebdo
- regression test verrouille : retirer le TTL fait echouer le test

Bug isole au briefing matin (verifie : `_recent_proactive_context` est seulement utilise dans `heartbeat.py:187`, pas dans conversation/reminder/weekly review).

A faire en suivi (audit similaire) :
- recherche systematique des injections texte dans des prompts sans TTL (autres helpers `recent_*` / `pending_*` / `latest_*`)

### Chantier 1bis — Claim guard via LLM repair ✅ shippe 3 mai 2026

Symptome (3 mai dogfood Telegram) : conversation a affiche "Je n'ai applique aucun changement sur ce tour. Dis-moi explicitement ce que tu veux que je deplace, remplace ou liberes...". Receipt-style canned visible juste apres Chantier 1 voix unifiee — preuve que les regles voix dans le prompt ne suffisent pas si une template canned override la sortie LLM en aval.

Cause exacte : `claim_guard.safe_rewrite_for_claim_without_mutation()` (`backend/src/fitmas/claim_guard.py`) retournait une chaine fixe quand `looks_like_action_claim(reply)` matchait sans qu'aucune mutation soit committee. La detection (anti-mensonge "dire = faire") est saine, l'implementation viole `LLM-FIRST-CONVERSATION` ("no helper produces a final conversational reply unless it is outage").

Fix livre :
- `claim_guard.build_claim_repair_prompt(original_reply, user_text)` construit un `(system, user_prompt)` pour repair LLM
- `conversation_pipeline._llm_repair_claim_reply(...)` appelle `gw.request_text` + valide (non vide, longueur 5-500, plus de claim, pas de violation voix coach)
- `claim_guard.outage_fallback_reply()` est la ligne minimale coach-voice pour le cas LLM down ("Vu — rien de bouge sur ce tour. Tu veux que je bouge quoi concretement ?") — JAMAIS la vieille canned
- `safe_rewrite_for_claim_without_mutation` garde un alias compat qui delegue maintenant a `outage_fallback_reply`
- Pipeline tracking : `response_mode="claim_without_mutation_repaired"` ou `"claim_without_mutation_outage_fallback"`

Tests : `test_claim_without_mutation_is_repaired_via_llm` + `test_claim_without_mutation_falls_back_when_repair_fails` + `TestOutageFallback`. 583 tests verts.

### Chantier 1ter — Capture indirecte de constraints ✅ shippe 3 mai 2026

Symptome (3 mai dogfood) : user dit "la piscine c'est parce qu'elle etait en vidange" pour expliquer une nage manquee. Pas de `memory_actions=[record_availability]` emis — info perdue.

Cause : Phase 2 capability (`memory_actions`) est branchee, mais les few-shots du prompt couvrent uniquement les annonces directes ("je peux pas nager 2 semaines"). Pas les mentions indirectes / explications.

Fix livre dans `_CONVERSATION_SYSTEM_TEXT` :
- Regle generale "capture meme en passant, meme pour expliquer le passe, mieux vaut faible confidence que perdre l'info"
- 6 nouveaux few-shots couvrant : piscine vidange/fermee, explication seance manquee, voyage, douleur ongoing, preference, pattern explication via fait stable

Tests : 82 conversation/contract/voice verts.

### Cleanup DB prod ✅ 3 mai 2026

Apres dogfood Telegram, 395 rows obsoletes purgees de la prod Fly :

| Table | Avant | Apres | Supprime |
|---|---|---|---|
| `user_facts` | 104 | 34 | 70 (expires < now OR time-sensitive >14d) |
| `working_memory_entries` | 50 | 11 | 39 (>7d) |
| `conversation_turns` | 72 | 20 | 52 (>7d, legacy pre-step) |
| `coach_messages` | 299 | 67 | 232 (>14d) |
| `pending_mutation_confirmations` | 2 | 0 | 2 (status != pending) |

Espace : 1560 KB -> 804 KB (754 KB reclaim, ~50%). VACUUM execute.

Touche a zero (par doctrine) : `plan_mutation_events` (audit forward-only), `activities`, `scheduled_sessions`, `snapshots`, `strava_connections`, `day_plans`, `weekly_plans`.

Effet : la mémoire repart propre. Plus d'observations one-shot mars/avril traitees comme patterns persistants. Plus de fact "dispersion IA" qui injectait "Avec l'energie que tu mets sur l'IA" off-tone.

Cleanup principles applied :
- **Time-sensitive facts** (constraint, execution, fatigue, health, availability, pattern) : purge si > 14j OU expires_at < now
- **Identity / coaching style** (coaching, preference) : keep durables, purge uniquement si explicitement expires
- **Working memory** : > 7j (court terme par contrat)
- **Conversation turns** : > 7j (legacy)
- **Coach messages** : > 14j (history_limit prend le recent)
- **Pending confirmations** : drop tout sauf `status='pending'`

A ré-appliquer périodiquement en mode "garbage collect prod" — peut etre un cron mensuel automatise (chantier futur si dogfood le justifie).

### Chantier 1quater — Coach reliability slice 0 ✅ shippe 3 mai 2026

Symptome : le coach est inutilisable en dogfood quand il combine faits fragiles,
recadrage trop assure et templates backend visibles. La correction `claim_guard`
a retire la vieille phrase "Je n'ai applique aucun changement...", mais la meme
classe reste presente dans les blocages planning, confirmations et heartbeat
read-only qui parle comme s'il pouvait commit.

Direction : **le backend garde validation / block / commit / audit, mais ne
parle plus coach en chemin normal**.

Scope immediat :
- ✅ creer un `FinalReplyContext` mince pour les chemins bloque / confirmation ;
- ✅ composer la phrase finale par LLM a partir du resultat reel ;
- ✅ garder un fallback outage minimal si composer impossible ;
- ✅ interdire au heartbeat read-only de dire "on verrouille", "je pose",
  "c'est cale", "je deplace" sans event reel ;
- ✅ tests anti-template et anti-fake-commit ;
- ✅ hardening execution receipt : une reply LLM qui reconnait une seance manquee
  hier sans `execution_actions` est invalidee/reparee au lieu d'etre acceptee.

Verification locale :
- `./scripts/test-backend -q` : 600 passed, 11 skipped, 6 subtests passed
- `./scripts/smoke-real-conversations --scenario heartbeat_non_completion` :
  seance renfo J-1 marquee `skipped` via `execution_actions`
- `./scripts/smoke-real-conversations --scenario golden_case_autonomy` : passe

Hors scope :
- pas de write tools natifs ;
- pas de Phase B ;
- pas d'allegement massif du prompt voix avant prose finale stable.

### Chantier 2 — Truth source runtime core ✅ shippe 3 mai 2026

Objectif : fermer la dette "deux verites planning" sur les chemins runtime
qui alimentent le coach, heartbeat, activites et mutations visibles.

Fix livre :
- `plan_actions.py` mute uniquement `ScheduledSession`.
  - `complete_session` / `skip_session` ne synchronisent plus `DayPlan`.
  - `lighten_session`, `update_session_details`, `replace_session`, `swap_sessions` ne lisent plus le plan hebdo.
  - `move_session` garde l'ID de la seance deplacee et cree un placeholder repos flexible sur la date source quand la destination est libre.
- `mutations.py` ne contient plus les writes legacy `from_day/to_day` vers `DayPlan`.
  - une mutation planning doit cibler une vraie `target_session_id`.
- `signals.py` derive les signaux depuis `ScheduledSession` + activites/claims.
  - plus de `get_active_plan`, plus de `get_day_plan`, plus de `WeeklyPlan/DayPlan`.
- `activities.py` matche les activites contre les `ScheduledSession` datees.
  - `api_activities.py` et `strava.py` ne chargent plus `to_pydantic_plan`.
- `plan_mutation_service.mark_day_completed_for_user()` devient un no-op compat.
  - les completions d'activite completent la session runtime et gardent `matched_day` comme contexte d'event, sans write legacy.

Garde-fous ajoutes :
- test statique interdisant `WeeklyPlan/DayPlan` et les helpers legacy dans `plan_actions.py`, `mutations.py`, `signals.py`, `activities.py`.
- test statique interdisant `repo.get_active_plan`, `repo.to_pydantic_plan`, `week_days` et `mark_day_completed_for_user` dans `api_activities.py` / `strava.py`.
- tests comportementaux : mutation ScheduledSession sans toucher DayPlan, signal missed key sans active plan, activity matching ScheduledSession, no-op legacy day completion.

Verification locale :
- `./scripts/test-backend -q` : 608 passed, 11 skipped, 6 subtests passed
- `./scripts/smoke-real-conversations --scenario golden_case_autonomy` : passe
- `./scripts/smoke-real-conversations --scenario heartbeat_non_completion` : passe, renfo J-1 marque skipped
- `./scripts/smoke-real-conversations --scenario compound_non_completion_swap` : passe, clarification quand aucune seance vendredi n'existe

### Chantier 3A — Conversation tool loop partiel ✅ shippe 3 mai / deploye 4 mai 2026

Objectif : donner au coach plus d'agence de lecture/validation sans ouvrir les
write tools natifs.

Fix livre :
- `validate_plan_patch` expose au runtime tools conversation/planning comme
  validation-only.
- La conversation peut enchainer jusqu'a 3 rounds outilles et 6 tool calls total.
- Tous les `tool_use_id` demandes recoivent un `tool_result` ou un blocage
  `tool_budget_exceeded`.
- Le replay assistant preserve les blocs `thinking` si DeepSeek thinking est
  reactive plus tard ; aujourd'hui FitMAS garde `thinking={"type":"disabled"}`
  par defaut sur DeepSeek.
- Les `PlanPatch` appliques passent par `FinalReplyContext` post-event quand le
  composer LLM est disponible ; le resume d'event reste fallback auditable.

Hors scope :
- pas de write tool natif (`commit_plan_patch`, `move_session`, `swap_sessions`) ;
- pas de boucle tools heartbeat ;
- pas de suppression du `CoachDecision` JSON interne.

Verification locale :
- `tests/test_tool_runtime.py` : `validate_plan_patch` valid/blocked ;
- `tests/test_llm_tools.py` : second round tool-use + canonical tools ;
- `tests/test_llm_gateway_json.py` : preservation blocs `thinking` ;
- `tests/test_final_reply.py` + `tests/test_blocked_mutation_reply.py` : replies
  post-resultat.

### Chantier 3A-bis — Heartbeat read-only fake-action guard ✅ shippe 4 mai 2026

Objectif : fermer la classe vue dans le smoke reel du 4 mai :

> "Regarde ton app demain matin, j'ai ajuste le planning..."

Sans event de mutation, le heartbeat doit pouvoir :
- constater ;
- proposer ;
- demander confirmation ;
- dire qu'il faudra ajuster dans le chat.

Il ne doit pas claim :
- "j'ai ajuste" ;
- "j'ai bascule" ;
- "j'ai tout remplace" ;
- "c'est pose / cale / verrouille" ;
- "regarde ton app" quand cette phrase implique un changement deja fait.

Fix livre :
- `_llm_generate(... pipeline="heartbeat_*")` appelle un LLM judge `ALLOW/BLOCK`
  sur chaque sortie heartbeat read-only, sans regex fake-action ;
- si le judge dit `BLOCK`, echoue ou repond autre chose, le heartbeat retourne
  `None`, donc il ne part pas plutot qu'envoyer un faux commit ;
- suggestions explicites toujours autorisees : `je te propose de basculer...`,
  `si tu veux...`, `il faudra ajuster...`, `sinon on continue d'empiler...`.

Verification locale :
- `./scripts/test-backend -q` : 627 passed, 11 skipped, 6 subtests passed ;
- `.venv/bin/python -m compileall backend/src/fitmas` : OK ;
- smoke reel DeepSeek `heartbeat_non_completion` : exit 0, renfo J-1 marque
  `skipped` via `execution_actions` ;
- smoke reel DeepSeek `golden_case_autonomy` : exit 0, `weekly_review` ne claim
  plus "j'ai ajuste" sans event et propose explicitement de regarder ensemble.

Ce guard lit uniquement la sortie LLM heartbeat, jamais le texte utilisateur.
Il reste donc conforme a la doctrine : determinisme sur artefact machine, pas
sur comprehension user.

### Vision heartbeat — proactive coach loop

Le mot `heartbeat` est historique. La cible produit n'est pas un message fixe
tous les matins a la meme heure. C'est une **initiative coach bornee** :

```text
scheduler / evenement
  -> le coach se reveille
  -> lit la verite recente avec tools
  -> decide send/no_send
  -> compose un message utile ou se tait
  -> guard anti-harcelement + judge read-only
```

Sources de reveil :
- routine planifiee : briefing matin, revue semaine, pre-session ;
- evenement : nouvelle activite Strava, seance tres sous/sur-attendue,
  seance cle manquee, silence prolonge ;
- opportunite : fenetre utile pour recadrer, proteger la recup, demander une
  clarification courte.

Regles produit :
- `NO_SEND` est un resultat normal, pas un echec ;
- pas de harcelement : cooldown, cap journalier, nouveaute reelle, pas deux
  recadrages sur le meme sujet ;
- le coach ne doit pas claim une action planning sans event ;
- tant que le heartbeat est read-only, il propose ou demande confirmation.

### Chantier 4 — Observabilite proactive coach loop ✅ implemente localement 4 mai 2026

Endpoint debug `POST /api/v0/debug/heartbeat/{kind}?dump=true` qui retourne :

- contexte lu par le heartbeat (`heartbeat_bundle`, signals, sessions,
  activites, time_context selon le kind) ;
- prompt systeme rendu ;
- prompt user rendu ;
- response LLM brute ;
- decision `send/no_send` et raison ;
- sortie du judge read-only `ALLOW/BLOCK` ;
- message final envoye ou raison de silence.

Kinds supportes : `morning`, `pre_session`, `signal_check`, `weekly_review`.
Le meme `dump=true` existe aussi sur `POST /ops/heartbeat/{kind}`.

Implementation :
- `llm_gateway.generate_heartbeat_text_with_debug()` expose `raw_text`,
  `text`, `reason`, `allow_no_send` sans changer le helper historique ;
- `heartbeat.capture_debug_trace(kind)` trace gate, contexte, prompt, LLM,
  judge et decision finale via `ContextVar` local au tour ;
- les endpoints ajoutent le bloc `debug` seulement si `dump=true`.

Permet diagnostic d'incident en 5 minutes au lieu de 2h d'audit. Active uniquement quand `FITMAS_ENABLE_DEBUG_ENDPOINTS` est set.

Tests :
- `tests/test_heartbeat_debug_endpoint.py` verrouille prompt + raw LLM +
  judge + decision finale ;
- test no-op : sans seance du jour, le dump expose `no_today_session`.
- verification 4 mai : `./scripts/test-backend -q` -> 630 passed,
  11 skipped, 6 subtests ; dump reel DeepSeek OK (`prompt`, `raw_text`,
  `judge`, `decision` presents).

Dogfood parallele 4 mai :
- P1 post-event : certaines replies post-mutation pouvaient encore contredire
  les events reels (`week_scope_constraint`, sous-performance severe).
  Correctif local : verifier / repair sur `events_committed +
  events_blocked + session_changes + final_reply`.
- P1 heartbeat read-only : fuite "on replace les deux seances..." observee
  dans un weekly review. Mitigation immediate : prompt du judge durci avec
  `events_committed: []`, exemples BLOCK, et smoke direct DeepSeek confirme
  `BLOCK` sur la phrase fautive.
- P1-bis PlanPatch : les smokes reels ont montre qu'un remplacement de seance
  cle via `PlanPatch` pouvait s'appliquer sans confirmation. Correctif local :
  pre-hook `replace_key_session_changes_sport` partage par `validate_plan_patch`.

### P1 — Post-event reply verifier ✅ implemente localement 4 mai 2026

Bloquant avant 3B-A. Ferme localement : plus on libere le coach, plus il faut
verifier que sa phrase finale colle aux mutations effectivement appliquees.

Bug observe :

```text
events reels = mercredi et jeudi remplaces par Journee flexible
reply finale = "J'ai decale le fractionne a jeudi"
```

L'etat DB est correct, mais la voix ment sur l'etat. C'est plus dangereux qu'un
simple mauvais ton : le user croit qu'une action differente a ete commit.

Contrat implemente :

```text
events_committed + events_blocked + session_changes + final_reply
  -> verifier LLM
  -> ALLOW si la phrase colle aux events
  -> REPAIR si elle invente / inverse / ajoute une mutation
  -> fallback outage court si repair impossible
```

Exemple :

```json
{
  "events_committed": [
    {"command": "replace_session", "before": "Fractionne", "after": "Journee flexible"},
    {"command": "replace_session", "before": "Renfo", "after": "Journee flexible"}
  ],
  "final_reply": "J'ai decale le fractionne a jeudi."
}
```

Verdict attendu :

```json
{
  "verdict": "repair",
  "reason": "La reply claim un deplacement a jeudi, non present dans les events.",
  "repaired_reply": "J'ai libere mercredi et jeudi en journees flexibles. On garde de la marge cette semaine au lieu de forcer le fractionne."
}
```

Frontiere doctrine : ce verifier ne lit jamais le texte user libre. Il juge
uniquement des artefacts machine produits apres mutation : events DB, diff de
sessions, phrase sortante. Il est donc conforme a LLM-first.

Implementation :
- `final_reply.verify_post_event_reply()` demande un verdict JSON
  `allow|repair` a partir des artefacts post-mutation ;
- `_applied_plan_patch_reply()` passe la sortie du final composer dans ce
  verifier avant envoi ;
- si le verifier est invalide ou outage, fallback sur les summaries d'events
  commités, pas sur la phrase inventee ;
- `PlanAppliedMutationEvent` transporte maintenant `before_snapshot` /
  `after_snapshot` quand disponible ; le verifier recoit un diff compact en
  `extra_facts`.

Tests ajoutes :
- reply qui mentionne un jour/session/action absent des events -> repair ;
- reply qui colle aux events -> allow ;
- LLM verifier invalide/outage -> fallback summary commit sans claim inventee ;
- contexte verifier enrichi avec `before -> after` pour distinguer
  `replace_session` de `move_session`.

### P1-bis — PlanPatch confirmation parity ✅ implemente localement 4 mai 2026

Bug observe par smoke reel DeepSeek : `Tu peux remplacer ma seance cle par une
natation ?` pouvait produire un `PlanPatch.replace_session` applique directement.
La route legacy `MutationDecision` passait bien par `assess_mutation_impact`,
mais `PlanPatch` s'appuyait sur les pre-hooks et ne signalait pas encore ce cas.

Fix :
- pre-hook `replace_key_session_changes_sport` quand `replace_session` change
  le sport d'une seance cle ;
- `validate_plan_patch` transforme ce warning en `requires_confirmation` ;
- suggested fix explicite : demander confirmation avant de changer le sport
  d'une seance cle.

Test : `test_plan_patch_validation_requires_confirmation_when_replacing_key_session_sport`.

### Chantier 3B-A — Heartbeat read-tools read-only ✅ implemente localement 4 mai 2026

Objectif : le heartbeat n'est plus un one-shot texte uniquement. Avant de
parler, il peut demander des read-tools pour relire la verite recente :

- `get_plan_window`
- `get_recent_activities`
- `get_activity_highlights`
- `get_recent_reality_window`
- `get_load_context`
- `get_user_constraints`
- `get_relevant_facts`

Frontiere :
- aucun write tool ;
- pas de `validate_plan_patch`, `suggest_replan_candidates` ou
  `propose_replan` dans le pipeline heartbeat ;
- le guard read-only `ALLOW/BLOCK` reste en aval de la phrase finale ;
- `NO_SEND` reste un resultat sain.

Implementation :
- module dedie `skills/heartbeat/tool_loop.py` ;
- max 2 rounds tools, max 4 tool calls ;
- `HeartbeatDebugTrace.tools` expose offered/requested/results dans
  `dump=true` ;
- tous les roles heartbeat (`morning`, `pre_session`, `weekly_review`,
  `signal_check`) construisent un `ToolContext(pipeline="heartbeat")`.

Tests :
- registry heartbeat expose seulement les read-tools utiles ;
- boucle `tool_use -> tool_result -> prose finale` ;
- debug endpoint expose la surface tools ;
- tests heartbeat existants conserves.

### Chantier 3B-B — Heartbeat PlanPatch + confirmation ✅ implemente localement 5 mai 2026

Objectif : le heartbeat peut proposer un vrai ajustement planning sans jamais
committer tout seul.

Implementation :
- pipeline `heartbeat` expose maintenant `suggest_replan_candidates` et
  `validate_plan_patch` en plus des read-tools ;
- si le LLM heartbeat appelle `validate_plan_patch` et obtient
  `valid|warning|requires_confirmation`, le draft transporte une
  `DraftPendingConfirmation(plan_patch)` ;
- `persist_draft()` cree la `PendingMutationConfirmation` seulement apres
  livraison/persistance du message proactif, ce qui evite les ghost pending si
  Telegram echoue ;
- `signal_check()` convertit les anciennes candidates `MutationDecision`
  proactives (`tsb_alert`, missed cascade) en `PlanPatch`, valide, puis demande
  confirmation au lieu d'envoyer une simple suggestion non actionnable ;
- aucune ligne ne cree de `plan_mutation_event` avant acceptation explicite du
  pending par conversation.

Frontiere :
- pas de write tool natif ;
- pas de commit autonome heartbeat ;
- acceptation toujours traitee par le pipeline conversation existant
  `pending_resolution -> apply_patch_for_user`, avec revalidation avant commit.

Verification locale :
- `tests/test_heartbeat_tool_loop.py` : capture d'un `validate_plan_patch`
  heartbeat en pending candidate ;
- `tests/test_heartbeat_grounding.py` : `signal_check` cree une pending apres
  `persist_draft`, sans event mutation ;
- suite proche heartbeat/tools/core/plan patch : 123 passed.

### P1-ter — Execution receipt repair hardening ✅ implemente localement 4 mai 2026

Smoke reel du 4 mai apres 3B-A :

```bash
FITMAS_USE_DEEPSEEK_OPENAI_STRUCTURED=1 ./scripts/smoke-real-conversations --scenario heartbeat_non_completion
```

Symptome traite : DeepSeek/Claude pouvaient produire une reply qui reconnait
implicitement "pas fait hier" sans `execution_actions`. Le guard
`execution_receipt_without_action` invalidait correctement cette sortie, mais le
repair/fallback pouvait encore finir en outage user-facing au lieu de reconstruire
un `record_execution_update`.

Fix livre :
- la pipeline transmet maintenant au LLM la cible follow-up sous forme structuree
  (`unresolved_execution_followup_session_id`, target date) en plus du bloc texte ;
- si le payload LLM invalide dit lui-meme que la seance d'hier est manquee et
  qu'une cible follow-up structuree existe, `llm.py` reconstruit un
  `CoachDecision(no_change)` avec `execution_actions=[record_execution_update]` ;
- extension P1-quater : si une CoachDecision **valide** parle d'une execution
  d'hier mais oublie `execution_actions`, `llm.py` relance un repair LLM; sans
  session id certain, le repair peut utiliser `target_ref="seance d'hier"` et
  le writer resout ensuite contre la DB ;
- extension 5 mai : le meme repair se declenche aussi si l'artefact LLM dit
  explicitement qu'une seance/renfo/footing/etc. n'a pas ete fait, meme sans
  employer le mot "hier" (`renfo de mercredi id=... non realise`) ;
- extension 5 mai bis : le repair semantique couvre aussi le payload **invalide**
  qui reconnait "pas fait hier" sans `unresolved_execution_followup_session_id` :
  il emet seulement `target_ref="seance d'hier"` et laisse le writer resoudre
  une cible DB unique ;
- ce repair ne lit jamais le texte utilisateur libre : il se base uniquement sur
  l'artefact LLM invalide/valide + la cible DB deja identifiee par le contexte systeme ;
- si aucun session id certain n'existe, le repair peut seulement emettre une
  reference naturelle bornee (`target_ref="seance d'hier"`), que le writer doit
  resoudre contre la DB ; sans resolution unique, pas d'action synthetisee.

Frontiere doctrine :
- ne pas parser le texte user ;
- reparer uniquement la sortie LLM structuree / rationale / reply fautive ;
- si la cible DB est unique dans le contexte, repair en `execution_actions` ;
- sinon clarification courte, pas outage generique.

Verification :
- test rouge/passe sur repair apres echec du JSON repair ;
- test rouge/passe sur artefact LLM non-completion sans mot "hier" ;
- test pipeline sur propagation de la cible follow-up structuree ;
- smoke reel DeepSeek `heartbeat_non_completion` : exit 0, renfo J-1 marque
  `skipped`, reply conversationnelle.

Ce P1 est distinct de 3B-A : il touche la conversation reactive, pas le
heartbeat read-tools. Il ferme la base execution avant 3B-B.

### P1-quater — Dogfood API fallout ✅ deploye 4 mai 2026

Tests reels API/DeepSeek du 4 mai (agent de test read-only) apres 3B-A/P1-ter.
`heartbeat_non_completion` etait deja corrige cote agent principal, mais quatre
risques restaient a fermer avant 3B-B.

Fix livre :
- **Execution completion incoherente** : `llm.py` verifie/repare les
  `execution_actions` quand la reply/rationale contredit le statut structure
  (`completed` vs `not_completed`), via LLM repair sur CoachDecision.
- **Reply post-mutation date/day fausse** : les facts du post-event verifier
  incluent maintenant `YYYY-MM-DD (jour)` dans les snapshots before/after.
- **Cible planning ambigue trop vite mutee** : `validate_plan_patch` force
  `requires_confirmation` si une operation `move_session`/`swap_sessions`
  cible une seance d'un sport qui a plusieurs candidats actifs et que la source
  n'est pas disambiguisee (`from_day` absent).
- **Contrainte piscine pas toujours durable** : sur intent LLM
  `availability_constraint`, `llm.py` peut reparer une CoachDecision sans
  `record_availability` en ajoutant une `memory_actions.record_availability`.

Frontiere : ne pas corriger par regex sur texte utilisateur. Les fixes doivent
passer par artefacts LLM, results tools, validation DB, verifiers LLM ou
prompts/evals.

Verification locale :
- tests rouges/passes : `test_decide_repairs_valid_yesterday_execution_reply_without_followup_id`,
  `test_decide_repairs_execution_action_status_contradicting_reply`,
  `test_decide_repairs_missing_availability_memory_for_availability_intent`,
  `test_plan_patch_validation_requires_confirmation_for_ambiguous_same_sport_move_target`,
  `test_plan_patch_applied_verifier_context_includes_calendar_day_label`.
- suite proche : `tests/test_llm_tools.py tests/test_plan_patch.py
  tests/test_blocked_mutation_reply.py tests/test_core_flows.py` -> 142 passed.
- smoke reel DeepSeek `heartbeat_non_completion` : exit 0, renfo J-1 marque
  `skipped`.

### Ordre propose

1. ~~**Chantier 0-3A-bis**~~ ✅ shippe/deploye 2-4 mai 2026.
2. ~~**Chantier 4**~~ ✅ observabilite proactive coach loop.
3. ~~**P1 post-event reply verifier + P1-bis PlanPatch confirmation parity**~~ ✅ implemente localement.
4. ~~**Chantier 3B-A**~~ ✅ heartbeat tool-use read-only.
5. ~~**P1-ter execution receipt repair hardening**~~ ✅ smoke
   `heartbeat_non_completion` ferme.
6. ~~**P1-quater dogfood API fallout**~~ ✅ incoherences test reel fermees.
7. ~~**Chantier 3B-B**~~ ✅ PlanPatch propose + confirmation Telegram, sans
   commit autonome.
8. **Maintenant : dogfood court 3B-B** — verifier pending heartbeat PlanPatch,
   sans commit autonome.
9. ~~**Phase A+ core gate (A+1-A+3)**~~ ✅ implemente localement 5 mai 2026 —
   simulation, reviewer LLM/fallback type, gate runtime. Objectif : aucun
   `PlanPatch` significatif ne commit sans review sportive.
10. ~~**Smoke API reel A+**~~ ✅ `./scripts/smoke-a-plus-api` — serveur HTTP
   local + vrai provider + DB temporaire ; verrouille les regressions
   `move_hard_close` et `replace_key_running_swim_easy`.
11. ~~**Chantier 3B-C**~~ ✅ action-tools natifs bornes, conversation/planning
   only, candidates PlanPatch sans write. Commit toujours derriere
   `validate_plan_patch -> WeekCoherenceReviewer -> policy -> writer`.
12. ~~**A+4**~~ ✅ tool `validate_week_coherence` validation-only,
   conversation/planning/heartbeat, pending heartbeat possible seulement apres
   review sportive confirmable.
13. ~~**A+5**~~ ✅ semaine generee relue avant commit, fallback conservative si
   policy review non `valid`.
14. **Maintenant : dogfood court Phase A+** — verifier conversation, heartbeat,
   onboarding/regenerate et app sur donnees reelles.
15. **Apres seulement : B0/B1/B2** — prescription structuree, session quality,
   performance signals et calibration.

### Phase A — etat apres chantiers 0+1+2

Apres ces 3 chantiers, Phase A est *vraiment* fermee :

- doctrine LLM-first runtime ✅ (deja fait)
- voix coach uniforme tous pipelines ✅ (chantier 1)
- verite runtime unique ✅ (chantier 2 ferme la dette truth source)
- aucune classe de bug "hallucination factuelle" residuelle

A ce moment-la, la priorite change : ouvrir A+ core avant 3B-C. La raison est simple : ne pas donner plus d'autonomie d'action au coach avant que la gate sportive soit en place. Phase B reste differee.

### Phase A+ — Sport Quality / Week Coherence Review

Doc canonique : `docs/SPORT-QUALITY-REVIEW.md`.

Concept inspire d'un brainstorm strategique du 2 mai 2026, puis recadre le 5 mai 2026 : pas un second coach, pas Phase B prescription complete, mais une **couche de review sportive** entre `PlanPatch` et commit.

**Probleme adressé** : aujourd'hui le coach est bon en *reaction locale* (constraint -> mutation locale -> validate -> commit). Il ne raisonne pas au niveau *semaine entiere*. Il sait swap mardi/jeudi, il ne sait pas dire "ce swap surcharge ta fin de semaine, je propose plutot X".

**Exemple produit** :

| Niveau | User says | Coach reaction |
|---|---|---|
| Aujourd'hui (Phase A) | "Je ne peux pas courir mercredi" | move Wed -> Thu, commit |
| Phase A+ | "Je ne peux pas courir mercredi" | "Move Wed->Thu cree trop d'intensite fin de semaine. Je preserve samedi key, convertis jeudi en easy, drop le support optionnel." |

C'est de la **qualite de decision week-level**, distinct de la fiabilite (Phase A) et de la prescription intra-seance (Phase B).

Doctrine :

```text
Le coach propose.
Le reviewer sportif challenge.
La policy backend tranche.
Le writer applique.
Le coach explique.
```

Frontiere d'autorite :

```text
Reviewer = autorite sportive.
Runtime = autorite systeme.
PlanMutationService = effet DB.
Coach = relation + explication.
```

Le reviewer n'est pas juste un critique. Il rend un verdict et une policy recommandee (`commit_original`, `confirm_original`, `block_original`, puis V2 `retry_with_revised_patch` / `confirm_revised`). Mais il ne parle pas au user, ne write pas, ne commit rien et ne supprime jamais un hard block deterministe.

**Triggers Phase A+** : appel quasi systematique sur tout `PlanPatch` sportivement significatif :
- `move_session`, `swap_sessions`, `replace_session`, `lighten_day`, `create_session`
- patch multi-operations ou heartbeat proactif
- changement sport / duree / intensite
- seance key / support / recovery touchee
- fatigue / douleur / maladie / contrainte active
- validation runtime `warning` ou `requires_confirmation`

Skip acceptable seulement pour execution pure (`done` / `skipped`), lookup, memoire, clarification, ou accept/reject pending deja reviewe si patch inchange et review version actuelle.

**Capacites cibles a livrer** :

| Tool | Role |
|---|---|
| `get_session_detail(session_id)` | inspecter une seance en profondeur (titre, objectif, type, intensite, priority, completion) — manque aujourd'hui |
| `resolve_target_session(query)` | resoudre une ref floue ("la sortie longue", "le fractionne") en `session_id` ou candidates |
| `get_planning_contract()` | lire week_mission, key_sessions, protected_sessions, change_budget |
| `validate_week_coherence(patch)` | "si on applique ce patch, la semaine fait-elle encore sens ?" — distinct de `validate_plan_patch` (legalite) ; couvre `too_many_hard_sessions`, `recovery_gap_too_short`, `key_session_lost`, `weekly_load_too_high`, `mission_not_preserved`, etc. |

**Contrats / modules cibles** :
- `backend/src/fitmas/week_coherence.py` : `simulate_plan_patch`, `build_week_coherence_context`, `evaluate_week_invariants`, `review_week_coherence_with_llm`, `aggregate_week_coherence_policy`
- `WeekCoherenceReview` : status, sport_quality, confidence, findings, `recommended_policy`, optional `revised_patch`
- `PlanPatchServiceResult` porte la week gate pour pending/replies
- pending confirmation stocke patch hash + review status + recommended policy + review version

**Skill enrichie** :
- `replan_after_constraint` recoit le branchement Phase A+ : pour tout patch significatif, le LLM peut appeler `validate_week_coherence` avant sa decision finale
- le backend re-run toujours `validate_plan_patch` + `WeekCoherenceReviewer` avant commit

**Effort A+ core : 3-4 jours**. **Effort A+ hardening : 1.5-2 jours**.

**Dependances** :
- Chantier 3A/3B-A/3B-B donnent assez de boucle tool-use pour livrer A+ core maintenant
- Chantier 3B-C doit attendre A+ core : plus d'action-tools sans reviewer sportif augmente trop le risque de patchs techniquement valides mais mauvais
- Chantier 2 (truth source unifie) est **prerequis** pour `get_planning_contract` et `validate_week_coherence` — sans ScheduledSession seul truth, le scoring week donne des resultats incoherents

**Differentiateur produit** : Phase A+ est ce qui transforme FitMAS d'un "outil qui swap" en "coach qui sauve la semaine". C'est probablement le wedge produit le plus important a moyen terme. Pas urgent, mais dimensionnant.

Ordre detaille :
1. 3B-B dogfood court : confirmer que les pending heartbeat PlanPatch sont propres
2. A+0 docs + contrats (`SPORT-QUALITY-REVIEW.md`) — fait localement
3. A+1 simulation / context / checks deterministes — implemente localement
4. A+2 LLM `WeekCoherenceReviewer` / fallback type — implemente localement
5. A+3 gate runtime dans `apply_patch_for_user` — implemente localement
6. 3B-C action-tools natifs bornes, maintenant proteges par la gate
7. A+4 tool validation-only `validate_week_coherence`
8. A+5 review semaine generee
9. B0 `SessionPrescriptionEngine`
10. B1 `SessionQualityReviewer`
11. B2 `PerformanceSignalService` + `CalibrationProposal`

Decoupage mental :
- **MVP** : A+1 -> A+3. Le coach ne commit plus de patch significatif sans reviewer.
- **Hardening** : 3B-C -> A+5. Plus d'autonomie, mais toujours sous gate.
- **Scale sportif** : B0 -> B2. Prescription, seance, progression, calibration.

## Historique — 30 avril 2026

La suite de Phase A est recadree par l'incident heartbeat / conversation du 30 avril :

> Aucun texte utilisateur libre ne passe par regex, keyword, classifieur
> deterministe, parser maison ou short-circuit avant le coach LLM.

Doc canonique : `docs/LLM-FIRST-CONVERSATION.md`.

Le tunnel DeepSeek / tools / `PlanPatch` a livre le socle attendu pour un agent de planning fiable :

- DeepSeek est le provider principal configure, avec fallback Claude possible si le schema final casse
- le chemin OpenAI-compatible DeepSeek pour structured output est le defaut quand `DEEPSEEK_API_KEY` existe ; `FITMAS_USE_DEEPSEEK_OPENAI_STRUCTURED=0` permet de le desactiver temporairement
- le runtime tools accepte maintenant plusieurs `tool_use` dans un meme tour et renvoie un `tool_result` pour chaque id demande
- `CoachDecision` est le nouveau contrat de decision, avec fallback legacy `MutationDecision`
- `CoachDecision` porte maintenant `memory_actions`, `execution_actions` et `pending_resolution` ; les actions memoire/execution sont executees par writers bornes post-validation, et `pending_resolution` accepte/refuse les pending sans parser `oui/non`
- le parsing `CoachDecision` tolere maintenant les petites derives de schema LLM sur les artefacts structures (`confidence="high"`, `completed="false"`, `operation_type=record_execution_update`) sans relire le texte utilisateur ; les actions inconnues restent refusees
- `PlanPatch -> validate_plan_patch -> PlanMutationService.apply_patch_for_user` est branche cote conversation
- les confirmations pending serialisent maintenant le `PlanPatch` complet ; la resolution deterministe `oui/non` a ete retiree du runtime et remplacee par `CoachDecision.pending_resolution`
- le briefing matin a maintenant un catch-up borne jusqu'a 10h locale si le creneau jitter est rate et qu'aucun proactif n'a deja ete envoye
- `suggest_replan_candidates` est le tool principal de candidate replan ; `propose_replan` reste alias compat, non route par defaut
- le prompt formalise le workflow `replan_after_constraint` : tools atomiques -> candidate optionnelle -> `PlanPatch | no_change | requires_confirmation`
- Phase 0 LLM-first est passee sur le chemin conversation : plus de `low_signal`, `rich_signal`, `heuristic OR LLM`, pending `oui/non`, `_sanitize_no_change_reply`, extracteurs claim/non-completion ou fallback regex `user_indications.py` dans le runtime conversation
- Phase 3 a retire le pre-step `UserIndication` du runtime conversation :
  `conversation_pipeline.py` ne l'appelle plus, ne persiste plus de facts depuis
  cet objet et ne declenche plus `maybe_replan_from_user_indication`
- Cleanup repo du 1 mai 2026 : `user_indication_llm.py`,
  `user_indications.py`, `replan_from_life_change.py`, le wrapper
  `tool_routing.py` et leurs tests historiques ont ete supprimes. Le fichier
  `tools/routing.py` ne contient plus de classifieur texte; il garde seulement
  l'enum `IntentCategory`.

Ce que ca change produit :

- le coach peut enfin proposer une action structuree sans que le code lui mette une phrase deterministe dans la bouche
- l'orchestrateur reste proprietaire du commit, des events et des confirmations
- le coach LLM est le seul detecteur d'intention, de negation, de confirmation, de sante, de disponibilite, d'execution et de preference
- le determinisme intervient apres la decision LLM : schema, permissions, validation, commit, audit, dedup, integrite

Suite prioritaire :

1. Rejouer les smokes reels : `golden_case_autonomy`, `piscine fermee`, continuations courtes (`oui`, `running`, `mercredi`) et contraintes simples type `demain soir`.
2. Durcir `validate_plan_patch` : atomicite batch, suggested fixes, charge/recup/sante plus fines.
3. Dogfood reel Telegram sur la semaine, en classant chaque echec : trust blocker, bug Phase A, besoin Phase A+, besoin Phase B, polish.

Smoke reel DeepSeek du 1 mai 2026 :

- ✅ `heartbeat_non_completion` : heartbeat demande "renfo 34min faite ou pas ?", user repond "J'ai pas eu le temps hier...", `execution_actions` applique `skipped` sur la seance d'hier et la reply reste conversationnelle.

### Phase B en reflexion — refonte planning / progression

Discussion en cours (27 avril 2026) sur une refonte de la planification : passer de "planner hebdo deterministe + texte LLM" a "moteur de progression + LLM coach contextualisant". Pas encore de chantier ouvert. A garder en tete pendant la fin de Phase A pour ne pas creer de dette refactor evitable.

Idee centrale (a confirmer par dogfood Phase A + design pose) :

- separer `placement` (deja deterministe), `prescription` (blocs exacts, zones, cut rule) et `rendering` (LLM explique)
- introduire un `ProgressionArc` par type de seance (ex: `running_intervals_400m`) qui memorise l'axe de progression (`current_reps`, `last_completion`, `next_target`) et applique une regle bornee
- introduire une table `SessionExecution` (planned vs actual + completion ratio + subjective) que le ProgressionEngine consomme
- LLM ne **decide** jamais le contenu des blocs ; il peut **proposer** une variante quand l'espace est riche (strength, climbing) sous validation deterministe
- session_description en DB devient le **rendu** d'une prescription structuree, pas la verite

Pourquoi c'est coherent avec Phase A :

- `PlanPatch`, `validate_plan_patch`, `PlanMutationService`, `plan_mutation_events`, multi-tool runtime, tools read-only, posture coach, claim_guard, memoire contraintes : tout survit. Phase A construit le **commit pipeline**, Phase B construit le **content engine**. Axes orthogonaux.
- Phase A est un prerequis : sans le commit pipeline durci, ajouter une couche progression sur un commit fragile ne tient pas.

Discipline pour finir Phase A sans dette envers Phase B :

- **`suggest_replan_candidates`** : interface = `(slot, sport_type, session_type, intensity_hint, reason)` seulement, **pas** de blocks/zones/duration figee. Le contenu se compose downstream (templates aujourd'hui, ProgressionArc demain).
- **`replan_after_constraint` skill** : prescrire l'ordre des tools, **pas** de few-shots content-aware ("si jeudi nage tombe alors easy run") qui encodent du metier qui vivra dans les arcs.
- **`validate_plan_patch` hardening** : charge / sante / recup / atomicite / suggested fixes oui ; regles intra-seance (`8x400 trop lourd`, `tempo trop long`) **non** — elles vivront dans le ProgressionEngine.
- **`session_templates.py`** : freeze, pas d'ajout. Module sur la sellette pour Phase B.
- **`propose_replan` actuel** : garder l'implementation derriere la nouvelle interface jusqu'a Phase B, pas de reecriture maintenant.
- **Capture exécution dogfood** : verifier que ce qu'on logge (`ExecutionEvidence`, `RecentRealityWindow`) est un sur-ensemble de ce que `SessionExecution` exigera (planned vs actual prescription, completion_ratio, subjective). Si gap (ex: pas de subjective structure), noter pour Phase B sans bloquer Phase A.

Regle d'or :

> Si la decision depend du contenu intra-seance (reps, blocks, zones), c'est Phase B. Tout le reste est Phase A.

Phase B ne s'ouvre qu'apres :

- dogfood Phase A confirme que le pipeline coach autonomy tient
- `suggest_replan_candidates`, `replan_after_constraint`, `validate_plan_patch` durci sont livres
- design Phase B est ecrit dans un doc dedie (probable `docs/PROGRESSION.md` ou section dans `PLANNING.md`)

Etat Phase A 28 avril :

- ✅ `suggest_replan_candidates` livre comme surface canonique, `propose_replan` garde la compat
- ✅ `replan_after_constraint` formalise dans le prompt comme workflow, pas comme write tool
- ✅ heartbeat matin plus fiable pour dogfood grace au catch-up et aux logs de skip
- ⏳ reste : validation patch plus riche + smoke reel dedie avant de basculer en dogfood semaine complete

Smoke reel 26 avril (`FITMAS_USE_DEEPSEEK_OPENAI_STRUCTURED=1 ./scripts/smoke-real-conversations --scenario golden_case_autonomy --scenario today_unavailability`) :

- ✅ pas de crash API
- ✅ DeepSeek tape bien l'API et demande plusieurs tools coherents
- ✅ le dernier tour `Mercredi` produit un `CoachDecision(plan_patch)` puis un event reel : creation d'un footing easy mercredi 22 avril
- ✅ pas de 400 tool-use
- ⚠️ sorties non-JSON apres tools encore observees ; repair/fallback rattrape, mais la stabilite JSON reste a blinder
- ⚠️ le milieu du golden case reste trop defensif/passif (`Oui`, `Running`) ; prochaine tranche = skill `replan_after_constraint` + reclassification `propose_replan`
- ⚠️ classification memoire bruitée observee (`Running` -> health general running) ; a traiter comme signal de dogfood, pas comme blocker deploy

## Historique du refactor — 20 avril 2026

### Diagnostic dogfood (19-20 avril)

Une session de dogfood réelle a confirmé trois pathologies convergentes du coach (briefing dimanche + conversation Telegram autour de "piscine fermée 2 semaines") :

1. **Court-circuits déterministes** : sur les intents `availability_constraint` et apparentés, le LLM principal `decide()` n'est jamais appelé. Une réponse template f-string est envoyée à la place (`_week_scope_reply` dans `api_messages.py:317-326`). Conséquences : token interne `this_week` recopié brut, ton administratif, pas de creusage du contexte conversationnel précédent.
2. **Pré-digestion agrégée en heartbeat** : `weekly_review()` (heartbeat.py:281) passe au LLM des compteurs (`actual_activity_count`, `actual_duration_min`) au lieu du détail par sport/jour. Conséquence : "zéro natation cette semaine" alors qu'une nage offplan existe en DB (id=36, vendredi 17 avril). Le `coach_reading_digest` qui exposerait `real_entries` détaillés existe mais n'est branché que dans le briefing matin.
3. **Hallucination de plan futur** : aucun tool n'expose `ScheduledSession` futures au coach LLM. Sur "piscine fermée 2 semaines" le coach affirme "natation prévue lundi 20 et mercredi 22" alors que la semaine 20-26 avril est **vide** dans le calendrier réel.

### Diagnostic dogfood — addendum 20 avril matin (turns 5-7)

Suite de la même conversation Telegram, le matin du 20 avril, deux nouvelles pathologies confirmées :

4. **Court-circuit `nlp.py:60 generate_reply()` sur réponses courtes** : User répond "Running" à la question fermée du coach. `extract_reply()` ne trouve aucun token connu (pas de jour, pas de feeling), passe `needs_clarification=True`, et `generate_reply` retourne en dur "Je peux ajuster, mais j'ai besoin d'un point de plus. Tu sais déjà quels jours sont les plus compliqués ?". Le LLM principal n'est **jamais** appelé. Le coach ignore totalement la question fermée qu'il avait posée au tour précédent et boucle. Cablé dans `conversation_pipeline.py:843-844`.
5. **Phantom action — anti-pattern "dire sans faire"** : User répond "Mercredi". Le coach affirme "OK. Je libere ce creneau et je garde la suite propre. Le cap de la semaine ne bouge pas." (template `replan_from_life_change.py:500 _build_user_message()`). **Aucune mutation réelle n'est appliquée** : les deux nages lundi 20 / mercredi 22 sont toujours planifiées en DB. Le coach ment au user. Aucune garde "dire = faire" n'existe dans le pipeline.

**Diagnostic racine** : le système interprète et résume la donnée AVANT de la passer au LLM, au lieu de donner les **données brutes + tools** au LLM pour qu'il les explore lui-même. Le LLM est utilisé comme générateur de phrases sur un contexte appauvri, pas comme orchestrateur autonome. **Pire** : sur certains chemins, le LLM affirme une action sans qu'aucune mutation ne soit auditée — l'app et le coach divergent silencieusement.

**Conséquence sur le sequencing** : la décision "dogfood guidé d'abord" est consommée. Le dogfood a livré son verdict. Le prochain chantier canonique devient `COACH-AUTONOMY-REFACTOR.md` — il remplace "dogfood guidé" comme étape 0. Le doc a été enrichi des turns 5-7 dans le golden case, et un nouveau **Chantier 1bis "Anti-mensonge dire = faire"** a été ajouté entre la suppression des court-circuits et l'ajout des tools de lecture.

### Chantier 0 du refactor — fait

Le Chantier 0 (pré-requis) est livré le 20 avril 2026 :
- Golden case gelé comme smoke scenario : `./scripts/smoke-real-conversations --scenario golden_case_autonomy`
- Inventaire system prompts + audit court-circuits → `docs/COACH-AUTONOMY-AUDIT.md`

### Chantier 1 du refactor — fait

Suppression des 5 court-circuits non-transactionnels, livré le 20 avril 2026 (4 commits atomiques `chantier 1: ...`) :
- Routing guards `_should_route_*_context_to_llm` généralisées : `decide()` est appelé sur 100 % des tours conversationnels (sauf calibration_only_reply)
- N5 execution_contestation, N2 low_signal, N3 week_scope, N4 no_candidate routés en contexte de prompt (helpers `_*_context_for_prompt`)
- N1 nlp.py fallback supprimé ; module `backend/src/fitmas/nlp.py` deleted ; le fallback restant est une réponse sobre "LLM indisponible" qui ne ment pas sur l'état du plan
- 415 tests passent, smoke `golden_case_autonomy` toujours rejouable
- Détails par chantier dans `docs/COACH-AUTONOMY-AUDIT.md` et `docs/COACH-AUTONOMY-REFACTOR.md`

### Chantier 1bis du refactor — fait

Anti-mensonge "dire = faire", livré le 20 avril 2026 :
- Nouveau module `backend/src/fitmas/claim_guard.py` : détection 1ère personne présent de 12 verbes mutationnels (`libere`, `deplace`, `remplace`, `supprime`, `decale`, `bascule`, `echange`, `retire`, `annule`, `ajoute`, `swap`, `swappe`), exclut négations (`ne`, `n'`) et marqueurs de proposition (`je propose`, `je peux`, `je pourrais`, `veux-tu`, `tu confirmes`, `ok pour`, etc.)
- Garde sortie pipeline (`conversation_pipeline.py`) : si `looks_like_action_claim(reply)` ET aucune mutation committee ce tour → réécriture en demande de clarification + log `conversation_pipeline.claim_without_mutation` + `response_mode="claim_without_mutation_blocked"`
- Couvre le cas hybride `_build_user_message` de `replan_from_life_change.py:474-507` au runtime : si la mutation downstream est appliquée, la phrase reste ; sinon elle est rewrite avant envoi Telegram/app
- 440 tests passent (25 nouveaux : 23 unit tests sur claim_guard + 2 integration tests pipeline)

### Chantier 2 du refactor — fait

Tools de lecture brute pour le coach LLM, livré le 20 avril 2026. Scope recalibré : 3 des 4 tools du plan existaient déjà, le vrai gap était `get_user_constraints` (manquant) et l'enrichissement ATL/CTL/TSB de `get_load_context`.
- ✅ `get_user_constraints` créé (`backend/src/fitmas/tools/registry.py`) : filtre `active_facts` par catégories (availability/schedule/constraint/health/fatigue), exclut inactifs et expirés via `fact_is_current`, retourne payload structuré JSON-strict
- ✅ `get_load_context` enrichi avec `ctl`/`atl`/`tsb` + label `frais`/`neutre`/`fatigue` via `compute_ctl_atl_tsb` (TSS estimé à la volée si absent)
- ✅ Historique : les routing budgets par intent ont ete poses ici, puis supersedes le 30 avril par Phase 2 LLM-first. `llm.decide()` offre maintenant un budget conversationnel canonique stable et laisse le LLM choisir les read-tools.
- ✅ Tests : 3 nouveaux unit tests + tests routing/llm_tools mis à jour. 443 tests passent
- ⏳ Hors scope chantier 2 : que l'extracteur d'indications pose un `expires_at` cohérent avec la durée annoncée ("2 semaines", "demain", "ce mois") — couvert par chantier 4

### Chantier 2bis du refactor — fait

Heartbeat utilise les mêmes capacités que la conversation pour la lecture de la semaine, livré le 21 avril 2026 :
- ✅ `weekly_review()` (`backend/src/fitmas/skills/heartbeat/heartbeat.py`) construit `recent_reality` via `build_recent_reality_window` puis les faits deterministes `build_coach_reading_facts(..., lens=None)` — pas de pre-pass LLM heartbeat — avec degradation gracieuse en log warning si l'un echoue
- ✅ `build_review_prompt()` (`backend/src/fitmas/skills/heartbeat/roles.py`) accepte `digest: CoachReadingDigest | None` et l'injecte via `render_digest_for_prompt(digest)` après les compteurs agrégés (qui restent pour compat des tests existants)
- ✅ Anti-hallu rule miroir du briefing matin ajoutée dans le system prompt review : "N'invente jamais un comptage hebdomadaire et ne dis pas 'zero <sport>' si une sortie de ce sport apparait dans le bloc, meme hors plan"
- ✅ Le digest expose déjà `real_entries` détaillés (`RealEntry` avec `linked_to_plan`) — `render_digest_for_prompt` produit `swimming 45' jeu (offplan)` lisible par le LLM
- ✅ Tests : nouveau `test_weekly_review_surfaces_offplan_swimming_entry` qui ajoute une nage offplan et vérifie que le prompt contient "Lecture de la semaine", "swimming", "(offplan)" + system prompt contient l'anti-hallu rule. 444 tests passent
- ⏳ Hors scope 2bis historique : faire passer weekly_review et morning_briefing par des bundles de contexte explicites ou tools read-only bornes. Ne pas recreer `route_tools_for_query` depuis texte user.

### Chantier 3 du refactor — fait

Audit + rewrite system prompts pour la posture coach "DÉCIDE et défends", livré le 21 avril 2026 :
- ✅ Audit : la pathologie est moins lexicale qu'architecturale. Les prompts contiennent peu de "propose deux options" mais aucune posture explicite "tu décides, tu défends" et aucun marker de continuation de fil
- ✅ Bloc **"Posture coach (non-negociable)"** ajouté à `_CONVERSATION_SYSTEM_TEXT` : "Tu DECIDES. Tu defends ton choix. Tu ne renvoies pas la balle au user pour un arbitrage que tu peux trancher avec le contexte fourni." + "Tu n'ouvres pas par 'Tu veux que je...', 'Tu preferes A ou B ?'." + "Imprevu n'est pas une demande de menu, c'est un signal a creuser." + clause continuation de fil
- ✅ Helper déterministe `detect_open_question(coach_text)` (`backend/src/fitmas/llm_prompt_builder.py`) : retourne la dernière phrase interrogative significative ; ignore les confirmations (`ok ?`, `tu confirmes ?`, `ca te va ?`...)
- ✅ Marker injecté dans le user prompt des deux builders conversation (classique + layered) : `Question ouverte du tour precedent (a toi, pas au user) : "..."` + consigne "ne change pas de sujet en silence"
- ✅ Marker équivalent côté heartbeat morning_briefing : `_pending_open_question_for_user(db, user)` détecte la question en attente seulement si le user n'a rien écrit depuis ; injecté via `pending_open_question` à `build_briefing_prompt`
- ✅ Tests : 12 nouveaux (1 posture + 5 détection + 4 injection prompt + 2 heartbeat). **456 tests passent**.
- ⏳ Hors scope 3 : court-circuit `clarification` du pipeline — repris immédiatement en Chantier 3bis (voir ci-dessous, dogfood ayant remonté la boucle "Tu l'as faite ou pas ?" sur séance manquée)

### Chantier 3bis du refactor — fait

Court-circuit `clarification` du pipeline converti en contexte soft pour `decide()`, livré le 21 avril 2026 :
- ✅ Symptôme dogfood : sur séance manquée, le canned `"Tu l'as faite ou pas ?"` court-circuitait `decide()` et bouclait — coach perçu comme "disque rayé"
- ✅ Helper `render_unresolved_execution_followup(clarification, *, target_date_iso)` (`backend/src/fitmas/execution_clarification.py`) : produit un bloc soft "Suivi execution non resolu (a toi de juger : creuser, integrer ou ignorer ce tour)" avec id session, question candidate, raison d'impact et consigne anti-répétition
- ✅ Param `unresolved_execution_followup` ajouté aux deux builders (`build_conversation_prompt_bundle` + `build_layered_conversation_prompt`), injecté dans le user prompt aux côtés du marker open-question (`llm_prompt_builder.py`)
- ✅ `llm.py` lit `coach_context["unresolved_execution_followup"]` et le passe au builder layered
- ✅ `conversation_pipeline.py:375-399` : suppression du `_reply_and_record_turn(reply_text=clarification.question)` ; le bloc est désormais attaché à `coach_context` pour `decide()`. Le garde déterministe `looks_like_execution_clarification_prompt(previous_agent_text)` (déjà dans `_targeted_execution_clarification`) casse la boucle au tour suivant
- ✅ Tests pipeline (`test_core_flows.py`) refactorisés : `..._surfaces_targeted_clarification_as_prompt_context_to_llm`, `..._does_not_block_fatigue_adaptation_anymore`, `..._followup_breaks_loop_after_first_turn`, `..._resolves_clarification_via_decide`, `..._after_clarification_is_ingested_normally`
- ✅ Tests prompt (`test_llm_prompt_builder.py`) : `UnresolvedExecutionFollowupInjectionTest` (classique/layered/None). **460 tests passent**.

### Chantier 4 du refactor — fait

Mémoire des contraintes temporelles avec `expires_at` ancré sur la fin de fenêtre, livré le 21 avril 2026 :
- ✅ Symptôme dogfood (screenshot Telegram) : après "imprevu, piscine fermee 2 semaines", le coach continuait de reposer "tu l'as faite ou pas ?" sur la natation couverte par la contrainte, et au tour suivant il ne se souvenait plus de la fenêtre. Zéro persistence des contraintes multi-jours.
- ✅ Historique : `IndicationTimeReference.window_end_date` avait servi a ancrer les contraintes multi-jours. Ce chemin est maintenant remplace par `CoachDecision.memory_actions`.
- ✅ Parser durée (`_extract_constraint_duration_days`) : "2 semaines", "15 jours", "une/la semaine". Branché dans `_fallback_availability_indication` → `window_end = resolved_date + (duration - 1)`, scope upgradé à WEEK.
- ✅ Builder `build_availability_fact_payloads_from_indication` : produit un `UserFact` category=`availability`, key `unavailable_<sport|general>_<start-iso>_<end-iso>` (sport détecté via `_TRIGGER_ACTIVITY_PATTERNS`), `expires_at = datetime.combine(end + 1 jour, time.min)`. Skippe single-day + polarités non-UNAVAILABLE.
- ✅ Parse inverse `parse_availability_fact_key` : retrouve sport + start + end depuis la clé, sans relire l'indication d'origine.
- ✅ Pipeline (`conversation_pipeline.py`) : persiste les availability facts AVANT le flux health, refresh `_active_memory_payloads`.
- ✅ Garde clarification (`_yesterday_session_covered_by_active_constraint` dans `api_messages.py`) : parcourt `repo.get_active_facts` (filtré par `fact_is_current`), retourne True si hier ∈ fenêtre ET (sport match ou contrainte générale). Wiré dans `_targeted_execution_clarification` après le check `yesterday_sessions`.
- ✅ Les tests historiques `test_user_indications.py` ont ete retires avec le module. Les garanties actives sont dans `test_llm_first_conversation_contract.py`, `test_memory_mutation_service.py` et `test_core_flows.py`.

### Recalage du 24 avril 2026 — coach libre, cadre strict

Les captures Telegram des 15/17/19/20/21 avril et la revue du code courant changent le cadrage du prochain chantier.

Le probleme initial n'etait pas "pas assez de regles".
Le probleme etait "des regles locales qui parlaient et decidaient a la place du coach".

Nouvelle doctrine :

- le coach LLM arbitre l'intention, garde le fil conversationnel et decide quoi faire
- le determinisme tient la verite, la validation training, les permissions, le commit et l'audit
- aucune reponse conversationnelle finale ne doit venir d'un helper deterministe, sauf outage LLM minimal ou resume d'un event reel
- une confirmation pending est resolue par le LLM via `pending_resolution`, puis validee par le backend
- les contraintes training sortent en `valid / warning / requires_confirmation / blocked`, pas en mur binaire par defaut

Etat code au 24 avril :

- `propose_replan` existe (`replan_proposal.py`, commit `40bf4a1`)
- c'est un helper read-only qui propose une mutation candidate et la valide avec `validate_week_plan`
- il reste trop mono-cible et trop deterministe pour etre le cerveau du replan
- `MutationDecision` est encore mono-operation
- `PlanPatch` existe maintenant comme contrat batchable pur (`backend/src/fitmas/plan_patch.py`)
- `validate_plan_patch` existe en premier wrapper gradue autour des pre-hooks
- `PlanMutationService.apply_patch_for_user` existe et commit seulement les patchs `valid`
- `PlanMutationService` sait accepter une sequence, mais le pipeline conversation applique surtout une decision unique
- le runtime LLM offre plusieurs tools par intent et execute maintenant un batch borne de tools demandes par le modele
- DeepSeek V4 peut demander plusieurs tools dans la meme reponse et ignore `disable_parallel_tool_use` cote Anthropic-compatible ; le runtime execute les tools autorises sous budget et satisfait tous les ids en `tool_result`
- les smokes reels DeepSeek du 24 avril montrent une API stable, mais un format final fragile apres tool-use :
  - `tests/test_integration_real.py` : 15 tests + 5 subtests passent
  - `smoke-real-conversations` : 22 tours reels, aucun crash, aucun 400 tool-use
  - 5 sorties prose au lieu de JSON apres tool-use ou continuation courte, recuperees par fallback
- spike OpenAI SDK du 24 avril :
  - `deepseek-v4-flash` passe en OpenAI-compatible avec `response_format=json_object`
  - le cas tool-use -> JSON final sort bien en JSON apres replay de `reasoning_content`
  - `response_format=json_object` garantit surtout le format ; il ne garantit pas les enums FitMAS ni les champs utiles non vides
  - `deepseek-v4-pro` ne passe pas encore le probe JSON OpenAI-compatible local
  - `deepseek-chat` gere mieux le function-call final, mais moins bien le tool -> JSON final
  - conclusion : garder un gateway multi-adapter, ne pas basculer tout le runtime d'un coup
- les pre-hooks mutation restent `allowed / blocked` + warnings

Le prochain chantier canonique n'est donc plus "finir `propose_replan`".
Il devient :

> **Tools atomiques + runtime multi-tool borne + skill de replan + PlanPatch audite.**

Raison : DeepSeek a montre dans le smoke qu'il demande les bons tiroirs (`get_plan_window`, `get_user_constraints`, `get_load_context`, `propose_replan`), mais l'interface actuelle le force a en utiliser un seul. Le probleme n'est pas de creer un gros tool magique ; c'est d'autoriser une composition bornee, observable, puis de faire sortir l'action via `PlanPatch`.

Le critere court terme n'est pas "coach sportivement parfait".
Le critere est : **agent de planning fiable**.

Il doit :

- repondre aux questions simples sans confabuler
- reagir aux remarques et contraintes utilisateur
- garder le fil conversationnel
- appliquer ou refuser proprement
- ne jamais promettre une action sans event mutation ou confirmation pending

La qualite sportive fine vient apres ; pour l'instant les regles training sont un cadre de securite gradue.

Ordre precis :

1. Ajouter / enrichir les regressions conversationnelles issues des captures dogfood.
2. Stabiliser le contrat provider DeepSeek avant d'augmenter l'autonomie :
   - DeepSeek-first, Claude fallback
   - adapter DeepSeek OpenAI SDK a evaluer pour les appels structurels
   - conserver Anthropic-compatible tant que le runtime produit n'a pas migre
   - contenir la complexite : un seul point d'entree `llm_gateway`, adapters SDK caches derriere la meme interface
   - aucun module domaine ne doit connaitre OpenAI vs Anthropic
   - repair JSON obligatoire quand la reponse finale apres tool-use est en prose
   - fallback Haiku/Sonnet si repair impossible ou schema invalide
   - metrics `provider / model / json_repair_used / provider_fallback_used / tool_json_failure`
   - gate : moins de 5% de fallback provider sur la matrice smoke conversationnelle ciblee
3. Passer le runtime tools en V2 multi-tool **read-only / validation-only** borne :
   - ✅ `execute_tool_calls()` execute un batch borne et preserve un resultat par tool demande
   - ✅ `llm.py` renvoie un `tool_result` pour chaque `tool_use_id`
   - ✅ max 3 tools executes par tour ; le surplus devient `tool_budget_exceeded`
   - max 2 round-trips LLM outilles
   - traces `requested_tools / executed_tools / blocked_tools`
4. Nettoyer la surface tools :
   - garder les tools atomiques utiles
   - ameliorer descriptions et payloads
   - reclasser `propose_replan` en `suggest_replan_candidates`
   - garder `get_coach_state` comme shortcut optionnel, pas comme fondation unique
5. Ajouter une skill metier `replan_after_constraint` :
   - quand l'utiliser
   - tools autorises
   - ordre recommande
   - sortie obligatoire `PlanPatch` ou `no_change` justifie
6. ✅ Brancher `llm.decide()` vers un schema `CoachDecision` capable de retourner un `PlanPatch`.
7. ✅ Brancher le pipeline conversation sur `PlanPatch -> validate_plan_patch -> apply_patch_for_user`.
8. Durcir `validate_plan_patch` au-dela du wrapper pre-hooks : suggestions de fix, batch complet, health/load/recovery.

Slicings deja livres :

- ✅ contrat `PlanPatch` batchable + adaptateur `PlanPatchOperation -> MutationDecision`
- ✅ `validate_plan_patch` slice 1 avec statuts gradues depuis pre-hooks
- ✅ `PlanMutationService.apply_patch_for_user`, commit seulement si `valid`
- ✅ compat protocole DeepSeek : si plusieurs `tool_use` sont emis, tous les ids recoivent un `tool_result`
- ✅ runtime multi-tool borne : `execute_tool_calls()` execute jusqu'a 3 tools et renvoie une erreur controlee aux surplus
- ✅ action `create_session` : decision LLM / PlanPatch peut creer une `ScheduledSession` future via orchestrateur, avec validation et `plan_mutation_event`
- ✅ calibration/fatigue guard : correction du biais `thursday` dans le prompt calibration et suppression du court-circuit sante qui shuntait `decide()` avant fallback
- ✅ contrat `CoachDecision` actif en compat/shadow : `decide()` accepte le nouveau schema (`reply/no_change/mutation_decision/plan_patch/requires_confirmation`) et garde le vieux JSON `mutation_type` en fallback legacy
- ✅ pipeline `PlanPatch` conversation : si le coach retourne `response_type=plan_patch`, le pipeline revalide cote serveur puis applique via `PlanMutationService.apply_patch_for_user`; la reply vient des events appliques, pas du brouillon LLM
- ✅ confirmations `PlanPatch` : un patch `requires_confirmation` est serialise en pending confirmation complet, puis revalide et applique avec `allow_requires_confirmation=True` seulement apres un `oui` explicite
- ✅ slice provider contract :
  - `DeepSeekOpenAI` structured output disponible derriere `FITMAS_USE_DEEPSEEK_OPENAI_STRUCTURED`
  - validation locale des decisions FitMAS (`mutation_type`, champs requis, targets)
  - repair structuree sur prose apres tool-use
  - fallback Claude sur schema invalide si `ANTHROPIC_API_KEY` est disponible

Reste explicitement ouvert :

- dogfood reel avant nouvelle couche d'autonomie
- reclasser `propose_replan` en candidate helper, pas decision helper
- formaliser `replan_after_constraint` comme skill metier reusable
- durcir `validate_plan_patch` avec batch atomicite / suggested fixes / health-load-recovery fin
- enrichir les traces tools session-level (`requested/executed/blocked`, round trips, fallback provider)

Le plan detaille vit dans `docs/COACH-AUTONOMY-REFACTOR.md`, section "Plan d'attaque recale — Agent fiable, tools atomiques, PlanPatch audite".

### Vérité repo

Le repo est deja plus avance que plusieurs TODO historiques.

Ce qui est vrai dans le code aujourd'hui :

- onboarding Telegram complet avec preview coach
- coach conversationnel Telegram = surface principale de relation
- webapp React/Vite mobile-first = cockpit performance a 3 surfaces :
  - `Aperçu`
  - `Calendrier`
  - `Évolution`
  - détail séance sur `/workout/:sessionId`
- read models backend dédiés aux écrans app :
  - `overview`
  - `calendar`
  - `evolution`
  - `session detail`
- vérité planning runtime app/chat/heartbeat = `ScheduledSession` datées
- `WeeklyPlan` / `DayPlan` existent encore comme template planner et compat, pas comme vérité runtime
- `/api/v0/week` est marqué `runtime_role=template_compat`
- planner déterministe multisport + `PlanningDecision` + `planning_state`
- activités réelles : manuel + Strava + matching + vues app
- couche planning contract déjà visible dans l'app :
  - `PlanningContract`
  - `WeekMission`
  - `AvailabilityState`
  - `SessionPolicy`
  - `change_budget`
- boucle conversationnelle déjà modernisée :
  - prompt layers
  - prompt caching sur la partie stable
  - debounce Telegram
  - runtime tools V2 ; dette 30 avril : le routing ne doit plus classifier le texte user, seulement borner les tools autorises
  - runtime tools V2 : plusieurs tools read-only / validation-only executes dans un meme tour, budget actuel max 3
  - confirmations pending serialisees ; dette 30 avril : resolution par `CoachDecision.pending_resolution`, pas parser `oui/non`
  - transcript structuré persisté dans `conversation_turns`
- couche réalité déjà posée :
  - `ExecutionEvidence`
  - `RecentRealityWindow`
  - `WorkoutContent`
  - `strength_engine`
  - distinction `planned / done / missing / offplan` côté backend app
- mémoire V2 déjà active :
  - `UserFact` surtout pour le profil utile
  - `working_memory_entries` pour le court terme
  - `user_patterns` pour les patterns promus
  - cron de maintenance mémoire toutes les 6h
- heartbeat proactif déjà en prod :
  - briefing matin
  - rappel pré-séance
  - review dimanche
  - nouveau plan lundi
- surface ops / debug distincte du tool plane conversationnel :
  - `api_ops.py`
  - `api_debug.py`
- refactor coherence — etat reel :
  - `CoachStateBundle` = lecture partagée pour app, conversation, heartbeat ✓
  - `PlanMutationService` = gateway unique des mutations visibles ✓
  - `plan_mutation_events` = audit forward-only ✓
  - guards writer : `same_sport_proximity` + `occupied_training_target` ; repos/recuperation arbitres par review semaine ✓
  - `plan_actions.py` / `mutations.py` mutent uniquement `ScheduledSession` ✓
  - `signals.py` et `activities.py` lisent `ScheduledSession`, plus `WeeklyPlan/DayPlan` ✓
  - `adaptation.py` produit des propositions, mais certains chemins (fatigue low-impact) auto-appliquent encore via orchestrateur
  - heartbeat = suggestion-only ✓

### Ce qui est déjà fait et ne doit plus revenir comme gros TODO

- migration React/Vite + app mobile-first
- calendrier daté persistant + timeline backend
- détail séance dédié
- prompt 2 zones + caching
- debounce Telegram
- `profile_summary` compact
- permission tiers initiale sur mutations
- runtime tools V1 read-only
- transcript structuré de conversation
- `execution_evidence` / `recent_reality` / `workout_content`
- split heartbeat en cluster `skills/heartbeat`
- mémoire V2 base + maintenance périodique
- `CoachStateBundle`
- `PlanMutationService` + `plan_mutation_events`
- retrait de `WeeklyPlan` / `DayPlan` des lectures runtime app, conversation et heartbeat
- `/api/v0/week` clarifié comme compat template
- adaptation background suggestion-only
- guard `same_sport_proximity` sur moves datés
- ancien guard `protected_recovery_target` deprecie : repos/récupération = contrainte de plan, plus verrou runtime
- `SYSTEM-MAP.md` comme carte d'architecture pour les agents
- `skills/heartbeat/context.py` : `HeartbeatContextBundle` injecte `YesterdayTruth` / `TodayTruth` / `WeekDigest` dans le briefing matin ; pas de lens LLM dans heartbeat
- `coach_reading_digest` : contexte pré-digéré (facts déterministes + lens Haiku JSON) injecté dans `decide()` sur intents lookup/report/availability, avec voice rules anti-bullshit (12b4bf8)

### Dette technique vivante

#### Truth source runtime (sous surveillance)

Core ferme le 3 mai 2026 : mutations visibles, signals et matching activites
passent par `ScheduledSession`.

Surveillance restante :
- garder les tests statiques anti-retour legacy ;
- ne pas rebrancher `repo.get_active_plan` / `to_pydantic_plan` dans conversation, heartbeat, app runtime, activites ou strava ;
- separer plus tard les helpers template/compat de `repository.py` pour rendre la frontiere plus lisible.

#### repository.py hotspot (1 453 lignes, 72 fonctions)

Seul `repo_conversation.py` a ete extrait. Tout le reste du backend depend de ce fichier.
Candidats d'extraction : session queries, memory queries, converters to_pydantic_*.

#### Frontend code mort

Supprime le 13 avril 2026 :
- `frontend/src/pages/` (5 fichiers morts remplaces par `features/`)
- `frontend/src/state/app-state.tsx`
- `frontend/src/lib/api.ts`, `planning.ts`, `visuals.ts`
- `frontend/src/components/WorkoutModal.tsx`

#### conversation_pipeline.py (853 lignes)

Prochain hotspot. Orchestre message → signals → LLM → mutation → reponse. Pas encore sur le radar docs.

#### Couverture tests

Legere au regard de la richesse du domaine. Le systeme fait des mutations automatiques (adaptation) sans filet de tests suffisant.

### Ce qui reste partiel ou fragile

- le runtime tools plane reste volontairement etroit cote LLM-facing (read-only / validation-only, max 3 tools par tour aujourd'hui) ; l'action passe ensuite par `PlanPatch` + orchestrateur
- le heartbeat reste principalement cron + gating, pas encore tick-based
- le verrou anti-doublon reste surtout mono-process / best effort
- le savoir sport existe en contenu et heuristiques, pas encore comme **substrate canonique de capacites partagees**
- le `WeeklyRealityDigest` canonique n'existe pas encore
- la similarite de seance est encore simple (`sport_type + session_type`)

## Décision de sequencing

- la prochaine douleur n'est pas “plus d'intelligence planner”
- la prochaine douleur est “meilleure lecture du réel, meilleure adaptation, meilleure mémoire, moins de duplication métier”
- FitMAS gagne si le coach paraît juste, pas si l'algorithme paraît sophistiqué
- `transcript structuré > compaction` reste la bonne priorité
- `dogfood > gros refactor abstrait` tant que la boucle coach n'est pas observée proprement sur une vraie semaine
- pas de multi-agent visible tant que le mono-agent et le substrate déterministe ne sont pas un goulot prouvé

## Politique tools pour la suite

Le prochain chantier tools ne doit **pas** partir d'un catalogue exposé par sport.

Ordre canonique :

### 1. Capacités métier partagées

Construire d'abord des modules déterministes, atomiques, réutilisables par :

- conversation
- planner
- heartbeat
- app read models
- CLI / ops

Capacités candidates :

- `reality`
- `planning`
- `session_drafting`
- `session_analysis`
- `plan_review`

### 2. Adapters par sport derrière ces capacités

Les sports implémentent le substrate, ils ne définissent pas le tool plane.

Exemples :

- `running`
- `cycling`
- `swimming`
- `climbing`
- `strength`

### 3. Runtime tools LLM-facing très peu nombreux

Le LLM ne doit voir que des wrappers sémantiques et bornés.

Exemples cibles à terme :

- `resolve_target_session`
- `get_recent_reality_window`
- `review_current_week`
- `build_session_draft`
- `analyze_completed_activity`

Mais la règle reste :

- expose peu
- implémente beaucoup
- pas de catalogue `run_* / swim_* / bike_*` directement donné au modèle

### 4. Write / commit séparés

Les mutations à effet de bord restent possédées par les orchestrateurs tant que les permission tiers ne sont pas plus riches.

## Plan canonique — maintenant

Le chantier prioritaire qui detaille cette remise en coherence vit dans `docs/COACH-COHERENCE-REFACTOR.md`.
Il traduit le plan OMX courant en doc durable repo et fixe l'ordre :

- une verite planning runtime
- un writer unique
- un bundle de lecture partage
- des mutations expliquees depuis des events reels

Point de verite au 13 avril 2026 :

- la convergence principale de phase 1 est en place
- les phases 1 a 5 du refactor coherence sont fermees sur leurs gates courants
- le prochain sujet n'est pas Phase 6 par défaut
- le prochain sujet est dogfood guide sur le profil reel pour verifier la coherence coach/app/planning apres refactor
- Phase 6 ne doit demarrer que si le dogfood confirme une douleur memoire/tools/digest

### 0. Dogfood guidé et alignement vérité

But :

- vérifier le comportement réel de la boucle coach
- ne plus laisser des docs raconter un état antérieur
- confirmer ou corriger les prochaines priorités avec usage réel

Observer surtout :

- calendrier app : `missing / adapted / done / offplan`
- conversation fatigue/douleur/indisponibilite
- confirmations de mutation forte
- events `plan_mutation_events`
- review du dimanche
- négociations de déplacement
- briefings matinaux réels

Décision si douleur confirmée :

- lancer le `WeeklyRealityDigest` canonique
- ou prioriser le substrate capabilities si la douleur dominante est la duplication métier

### 1. Substrate de capacités métier partagé

But :

- sortir la logique réutilisable du duo `conversation + planner + heartbeat + app`
- préparer des tools atomiques sans donner trop de liberté au modèle

Premiers modules cibles :

- `resolve_target_session`
- `build_session_draft`
- `analyze_completed_activity`
- `review_current_week`
- `propose_adaptation`

Principe :

- décomposition par capacité, pas par sport
- implémentation sport-spécifique derrière interface partagée
- zéro write side effect dans ces modules

### 2. Weekly reality digest canonique + mémoire utile

But :

- avoir une lecture causale unique de la semaine
- arrêter de recomposer facts + transcript + adaptations à plusieurs endroits
- rendre la review du dimanche et le lundi matin plus cohérents

Scope :

- digest explicite à partir de transcript, mémoire utile, activités, claims et adaptations
- meilleur tri `profile / working / patterns`
- dates absolues partout quand un fait est temporel
- garder `profile_summary` petit, stable, injectable partout

Docs de référence :

- `MEMORY-V2.md`
- `CONVERSATION.md`

### 3. Unifier revue hebdo, briefings et adaptation sur le même substrate

But :

- donner la même lecture du réel au chat, au heartbeat et à l'app
- éviter que chaque surface rederive sa propre vérité

Scope :

- week review
- monday new week intro
- morning brief
- adaptation summaries

### 4. Split progressif du repository et nettoyage des chemins legacy

But :

- sortir les bounded contexts du hotspot
- clarifier quelle couche possède quelle vérité
- supprimer ou isoler les derniers consommateurs compat de `WeeklyPlan`

Cibles :

- `memory`
- `planning`
- `activities`
- `adaptation`
- `read models`

### 5. Heartbeat scoring tick-based + verrou anti-doublon plus robuste

But :

- remplacer la rigidité cron par une lecture plus situationnelle
- réduire les doublons si on sort du mono-process simple

### 6. Ensuite seulement : enrichissement planner et expansion tools

But :

- planner plus riche
- explications plus lisibles dans l'app
- éventuelle exposition de nouveaux runtime tools sémantiques

## Ce qui n'est pas le prochain sujet

- multi-agent visible
- write tools LLM-facing
- catalogue de tools par sport exposé au modèle
- multiplication des tabs app
- planner V3 avant clarification du substrate partagé

## Tracks domaine à reprendre après ce socle

### `PLANNING.md`

Quand le track planner redevient prioritaire :

- enrichir `periodization.py` au-dela du simple `3+1`
- mieux distribuer la charge par sport
- porter l'explication de `PlanningDecision` jusque dans coach + app
- enrichir l'onboarding sportif seulement apres ca

### Workout / strength

Le gros chantier reality-workout est absorbe.
Le vrai next domain, si on y revient :

- `strength_signals` plus riches
- variations renfo depuis reel recent + fatigue + sante + temps dispo
- sans ouvrir un moteur de progression force complexe

### `APP-UX.md`

Le polish Figma reste un track parallèle utile.
Mais :

- on ne repolit pas sur une vérité encore mouvante
- d'abord le harness
- ensuite le rendu premium

## Pas maintenant

- pas de skills formels tant qu'on n'a pas assez de workflows distincts
- pas de plan mode systématique sur chaque micro-adaptation
- pas de write tools libres côté coach
- pas de V2.5 “LLM adaptatif partout” tant que le contrat mutation n'est pas durci
- pas de subagents / swarm
- pas de "liberté coach" non validee ; la liberte passe par substrates metier, validation et commit audite

## Vérification concrète avant de monter à l'étape suivante

### Harness

- [ ] les traces montrent une baisse nette du prompt dynamique injecté
- [ ] la zone statique est cacheable sans changer le comportement produit
- [ ] 3 messages Telegram rapides déclenchent 1 seule décision LLM

### Mémoire

- [ ] un fait du type `demain je ne peux pas` est stocké avec date absolue
- [ ] le coach lit un `profile_summary` compact au lieu d'une pile brute de facts
- [ ] transcript et mémoire durable restent deux choses séparées

### Mutations

- [ ] un simple move ne demande pas une confirmation inutile
- [ ] une réorganisation de semaine ne s'applique pas silencieusement

### Proactivité

- [ ] le heartbeat sait aussi ne rien dire pour une bonne raison
- [ ] les observations silencieuses alimentent ensuite la consolidation ou le scoring
