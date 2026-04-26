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

## État actuel — 20 avril 2026

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
- ✅ Routing budgets enrichis (`tools/routing.py` + `llm.py:_TURN_INTENT_TOOL_BUDGETS`) : `PLAN_NEGOTIATION` reçoit 5 tools dont `get_user_constraints` ; `PLAN_LOOKUP` reçoit 3 tools dont `get_user_constraints`. L'intent `availability_constraint` du turn_planner mappe sur PLAN_NEGOTIATION
- ✅ Tests : 3 nouveaux unit tests + tests routing/llm_tools mis à jour. 443 tests passent
- ⏳ Hors scope chantier 2 : que l'extracteur d'indications pose un `expires_at` cohérent avec la durée annoncée ("2 semaines", "demain", "ce mois") — couvert par chantier 4

### Chantier 2bis du refactor — fait

Heartbeat utilise les mêmes capacités que la conversation pour la lecture de la semaine, livré le 21 avril 2026 :
- ✅ `weekly_review()` (`backend/src/fitmas/skills/heartbeat/heartbeat.py`) construit `recent_reality` via `build_recent_reality_window` puis `coach_reading_digest` via `build_coach_reading_digest` — même pattern que `morning_briefing` — avec dégradation gracieuse en log warning si l'un échoue
- ✅ `build_review_prompt()` (`backend/src/fitmas/skills/heartbeat/roles.py`) accepte `digest: CoachReadingDigest | None` et l'injecte via `render_digest_for_prompt(digest)` après les compteurs agrégés (qui restent pour compat des tests existants)
- ✅ Anti-hallu rule miroir du briefing matin ajoutée dans le system prompt review : "N'invente jamais un comptage hebdomadaire et ne dis pas 'zero <sport>' si une sortie de ce sport apparait dans le bloc, meme hors plan"
- ✅ Le digest expose déjà `real_entries` détaillés (`RealEntry` avec `linked_to_plan`) — `render_digest_for_prompt` produit `swimming 45' jeu (offplan)` lisible par le LLM
- ✅ Tests : nouveau `test_weekly_review_surfaces_offplan_swimming_entry` qui ajoute une nage offplan et vérifie que le prompt contient "Lecture de la semaine", "swimming", "(offplan)" + system prompt contient l'anti-hallu rule. 444 tests passent
- ⏳ Hors scope 2bis : faire passer weekly_review et morning_briefing par `route_tools_for_query` + `execute_tool_call` (aujourd'hui ils consomment les builders directement, pas le tool runtime — étape ultérieure)

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
- ✅ Schéma : `IndicationTimeReference.window_end_date: date | None` ajouté (`user_indications.py`), propagé dans `_time_reference_from_payload` pour les parses LLM.
- ✅ Parser durée (`_extract_constraint_duration_days`) : "2 semaines", "15 jours", "une/la semaine". Branché dans `_fallback_availability_indication` → `window_end = resolved_date + (duration - 1)`, scope upgradé à WEEK.
- ✅ Builder `build_availability_fact_payloads_from_indication` : produit un `UserFact` category=`availability`, key `unavailable_<sport|general>_<start-iso>_<end-iso>` (sport détecté via `_TRIGGER_ACTIVITY_PATTERNS`), `expires_at = datetime.combine(end + 1 jour, time.min)`. Skippe single-day + polarités non-UNAVAILABLE.
- ✅ Parse inverse `parse_availability_fact_key` : retrouve sport + start + end depuis la clé, sans relire l'indication d'origine.
- ✅ Pipeline (`conversation_pipeline.py`) : persiste les availability facts AVANT le flux health, refresh `_active_memory_payloads`.
- ✅ Garde clarification (`_yesterday_session_covered_by_active_constraint` dans `api_messages.py`) : parcourt `repo.get_active_facts` (filtré par `fact_is_current`), retourne True si hier ∈ fenêtre ET (sport match ou contrainte générale). Wiré dans `_targeted_execution_clarification` après le check `yesterday_sessions`.
- ✅ Tests `test_user_indications.py` : 3 duration parser + 7 builder/parser inverse. Tests pipeline `test_core_flows.py` : `test_availability_constraint_persists_as_fact_with_window_anchored_expires_at` + `test_execution_clarification_skipped_when_active_availability_fact_covers_yesterday`. **472 tests passent**.

### Recalage du 24 avril 2026 — coach libre, cadre strict

Les captures Telegram des 15/17/19/20/21 avril et la revue du code courant changent le cadrage du prochain chantier.

Le probleme initial n'etait pas "pas assez de regles".
Le probleme etait "des regles locales qui parlaient et decidaient a la place du coach".

Nouvelle doctrine :

- le coach LLM arbitre l'intention, garde le fil conversationnel et decide quoi faire
- le determinisme tient la verite, la validation training, les permissions, le commit et l'audit
- aucune reponse conversationnelle finale ne doit venir d'un helper deterministe, sauf outage LLM, confirmation pending ou resume d'un event reel
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
- le runtime LLM offre deja plusieurs tools par intent, mais n'execute encore qu'un seul tool par tour
- DeepSeek V4 peut demander plusieurs tools dans la meme reponse et ignore `disable_parallel_tool_use` cote Anthropic-compatible ; le runtime satisfait les ids en erreur controlee, mais ne tire pas encore parti du multi-tool
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
- ✅ slice provider contract :
  - `DeepSeekOpenAI` structured output disponible derriere `FITMAS_USE_DEEPSEEK_OPENAI_STRUCTURED`
  - validation locale des decisions FitMAS (`mutation_type`, champs requis, targets)
  - repair structuree sur prose apres tool-use
  - fallback Claude sur schema invalide si `ANTHROPIC_API_KEY` est disponible

Reste explicitement ouvert :

- pending confirmation pour `PlanPatch requires_confirmation` : aujourd'hui le patch non `valid` est refuse proprement avant write, mais il n'est pas encore serialise comme confirmation pending complete
- durcir `validate_plan_patch` avec batch atomicite / suggested fixes / health-load-recovery fin

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
  - routing déterministe des tools
  - runtime tools V2 : plusieurs tools read-only / validation-only executes dans un meme tour, budget actuel max 3
  - confirmations `oui/non` pour mutations à impact fort
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
  - guards writer : `same_sport_proximity` et `protected_recovery_target` ✓
  - **dual-write actif** : `plan_actions.py` mute `DayPlan` dans tous ses chemins en parallele de `ScheduledSession`
  - **lectures legacy actives** : `signals.py` lit `WeeklyPlan`/`DayPlan`, `activities.py` matche contre `DayPlan`
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
- guard `protected_recovery_target` sur repos/récupération stable
- `SYSTEM-MAP.md` comme carte d'architecture pour les agents
- `coach_reading_digest` : contexte pré-digéré (facts déterministes + lens Haiku JSON) injecté dans briefing matin et `decide()` sur intents lookup/report/availability, avec voice rules anti-bullshit (12b4bf8)

### Dette technique vivante

#### Dual-write ScheduledSession / DayPlan (critique)

Le systeme mute `DayPlan` et `ScheduledSession` en parallele. Ce n'est pas du compat — c'est le coeur du mutation path.

Writers actifs :
- `plan_actions.py` : lighten, modify, replace, swap, move, set_completion_status — tous mutent DayPlan
- `plan_mutation_service.py` : appelle `mark_day_completed()` a chaque completion
- `strava.py`, `api_activities.py` : marquent DayPlan done via `mark_day_completed_for_user()`

Readers actifs :
- `signals.py` : 5 detecteurs lisent `WeeklyPlan` / `DayPlan` pour alimenter le heartbeat
- `activities.py` : `match_activity_to_day()` matche contre DayPlan

Resolution cible : migrer `plan_actions.py` pour muter uniquement `ScheduledSession`, puis retirer les readers legacy.

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
