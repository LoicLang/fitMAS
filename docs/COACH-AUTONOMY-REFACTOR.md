---
summary: refonte de la pipeline coach pour libérer le LLM des court-circuits déterministes, lui donner les bons tools de lecture/action encadrée, et garder les bonnes pratiques training comme validation de sécurité
read_when:
  - lancer le refactor coach autonomy
  - corriger une hallucination du coach (plan futur, activités passées)
  - retirer un court-circuit déterministe dans api_messages
  - ajouter un tool de lecture pour le coach LLM
  - construire un flow PlanPatch / validation / commit
  - auditer ou réécrire un system prompt heartbeat ou conversation
  - adresser une posture coach "demande au user au lieu de décider"
---

# FitMAS — Coach Autonomy Refactor

## Pourquoi ce chantier

Le coach actuel **ne voit pas la réalité** et **ne décide pas**. Trois pathologies convergent :

1. **Court-circuits déterministes** : sur certains intents, le LLM principal n'est jamais appelé. Une réponse template f-string est envoyée à la place. Exemple : `_week_scope_reply` → "OK. Je n'ai rien de sensible planifié sur this_week. Rien à protéger là-dessus." (token interne `this_week` recopié brut, ton administratif, pas de creusage).
2. **Pré-digestion agrégée** : les helpers passent au LLM des compteurs (`actual_activity_count=5`, `actual_duration_min=220`) au lieu de la liste détaillée par sport/jour. Conséquence : weekly review dit "zéro natation cette semaine" alors qu'une nage existe en DB.
3. **Hallucination de plan** : aucun tool n'expose le plan futur au LLM. Le coach invente "natation prévue lundi 20 et mercredi 22" alors que la semaine est vide en DB.

**Diagnostic racine** : on a construit un système qui interprète et résume la donnée AVANT de la passer au LLM, au lieu de donner les **données brutes + tools** au LLM pour qu'il les explore lui-même.

## Vision cible — recalee le 24 avril 2026

La direction n'est pas "plus de determinisme".
La direction est : **coach libre, cadre strict**.

Le LLM principal reste le coach :

- il comprend l'intention floue
- il lit le contexte
- il arbitre
- il propose ou applique une adaptation
- il maintient le fil conversationnel
- il parle a Loic

Le determinisme ne joue plus le coach. Il tient seulement le terrain :

- verite planning / activites / contraintes
- IDs, dates, timezone, preuves
- validation training : charge, ATL/CTL/TSB, recuperation, proximite, blessure
- permissions et confirmations
- commit transactionnel
- audit `plan_mutation_events`

```
User
  -> Coach LLM
      -> tools atomiques          # plan, contraintes, activites, load
      -> get_coach_state optionnel# shortcut read-only quand il suffit
      -> draft PlanPatch          # intention structuree du coach
      -> validate_plan_patch      # bonnes pratiques training + coherence
      -> final decision           # appliquer, confirmer, ou proposer alternative
  -> Orchestrateur
      -> commit_plan_patch        # write DB + event, jamais depuis une reply fantasy
  -> Coach reply depuis le resultat reel
```

Regle centrale :

> Le coach garde le volant. Le determinisme est son harnais, pas son cerveau.

### Niveaux de validation

Toute validation training doit sortir un statut gradue :

- `valid` : applicable sans confirmation
- `warning` : suboptimal mais acceptable ; le coach peut trancher
- `requires_confirmation` : possible mais engage un trade-off lourd ; confirmation ciblee
- `blocked` : dangereux, incoherent, ou impossible techniquement

Une recuperation protegee ne doit plus etre traitee comme un mur systematique.
Souvent, le bon comportement est `requires_confirmation` ou une alternative structurée :

- "on echange avec vendredi et je deplace la recup samedi"
- "je peux le faire, mais tu perds la recuperation post-charge"
- "je refuse seulement si blessure/charge rend le patch dangereux"

### Non-negociable

Aucun module deterministe ne doit produire une reponse conversationnelle finale, sauf :

- indisponibilite LLM
- demande de confirmation pending deja construite par l'orchestrateur
- resume d'un event reel deja applique

Les helpers deterministes peuvent produire du contexte, des candidates, des validations ou des summaries d'event.
Ils ne doivent pas jouer l'interlocuteur.

### Regex et heuristiques

Les regex ne sont pas fiables a 100% sur l'intention utilisateur.
Elles ne doivent donc jamais devenir le juge d'une intention floue.

Regle produit :
- keyword / regex = surligneur de contexte
- LLM = extraction structuree de l'intention
- determinisme = validation, permission, safety rail, commit, audit

Exemples :
- `top pas de douleur` ne doit pas creer un fait sante parce que le mot `douleur` apparait
- `plutot le soir` ne doit etre resolu que par extraction LLM dans le contexte d'un besoin actif, pas par fallback lexical global
- les seules exceptions deterministes directes sont les protocoles fermes deja actifs (`oui/non` sur confirmation pending, clarification execution explicite)

## Sources d'inspiration

- Anthropic — [Building Effective Agents](https://www.anthropic.com/research/building-effective-agents) — workflow patterns simples
- Anthropic — [Advanced Tool Use](https://www.anthropic.com/engineering/advanced-tool-use)
- Pelaris — pipeline 5 layers (référence commerciale AI coaching)
- Athletica.ai — adaptation event-driven
- ConstraintLLM — neuro-symbolic LLM + solver (arXiv 2510.05774)
- HTAA — selective agentization (arXiv 2604.10917)

## Golden case — la conversation à corriger

Soirée du 19 avril 2026 (dimanche), Loïc + coach Telegram. Cette conversation est notre cas de test de bout en bout. Une fois le refactor fini, ces 4 tours doivent produire des réponses correctes.

### Tour 1 — Revue dimanche (briefing proactif)

**Coach actuel** :
> "Loïc, soyons directs : zéro séance de natation cette semaine, ça me dit que tu as encore basculé en mode IA mode ON, sport mode OFF — classique chez toi. Le jeudi en renfo adapté avec les 58min d'activité réelle, c'est pas rien, mais c'est loin de ce qu'on avait prévu ensemble."

**Bug** : "zéro natation cette semaine" est faux. Vérité semaine 13-19 avril :
- Lundi 13 : Natation technique 36min — skipped
- Mercredi 15 : Natation CSS 40min — skipped
- **Vendredi 17 : Afternoon Swim id=36 (offplan, faite, 22min, 1100m)**

**Coach cible** : reconnaître la nage offplan du vendredi 17 + les 2 nages prévues skipped + question ouverte sur ce qui s'est passé.

### Tour 2 — Correction utilisateur

User : "J'ai nagé vendredi regarde mes séances réel"

**Coach actuel** : reconnaît la nage mais hallucine "vendredi 10 avril (id=19)". id=19 = un running de janvier 2025. La vraie nage = id=36 du 17 avril 2026. Demande au user de "clarifier" inutilement.

**Coach cible** : reconnaît id=36, vendredi 17 avril, 22min, et continue le fil sans demander de clarification.

### Tour 3 — Aveu utilisateur

User : "J'ai eut des imprévu"

**Coach actuel** : "OK. Je n'ai rien de sensible planifié sur this_week. Rien à protéger là-dessus."

**Bugs** :
- Token interne `this_week` recopié brut
- Court-circuit `_week_scope_reply` empêche l'appel du coach LLM
- Ferme la conversation alors que le coach venait de DEMANDER ("qu'est-ce qui s'est passé pour rebondir")

**Coach cible** : creuser, reconnaître le contexte, pas de leak, pas de ton administratif.

### Tour 4 — Contrainte forte

User : "je ne peux pas nager les deux prochaines semaine ma piscine est fermé"

**Coach actuel** : "OK, piscine fermée deux semaines. Je vois que tu as natation prévue lundi 20 et mercredi 22 à minima. On fait comment : tu les décales après la réouverture, tu passes full renfo/course à la place, ou tu me dis jour par jour ce que tu veux mettre à la place ?"

**Bugs** :
- Hallucination : la semaine 20-26 avril est **vide** dans le calendrier réel
- Posture passive : 3 options, demande au user de choisir, ne décide pas

**Coach cible** : lit le plan futur via tool, propose UN replan validé argumenté, mémorise la contrainte avec date de fin, présente comme sa décision.

### Tour 5 — Acquiescement utilisateur (lendemain matin 20 avril)

User : "Oui" (en réponse à "T'es d'accord pour qu'on ajuste le plan maintenant au lieu d'attendre ?")

**Coach actuel** : enchaîne avec une question fermée à options : "Lundi 20 et mercredi 22, tu veux quoi à la place: du running ou du renfo? Dis-moi et je reorganise le calendrier avec du concret."

**Bug** : retombe dans la posture "options à choisir" alors que le user a déjà donné l'autorisation d'agir. Le coach DOIT décider à ce stade.

**Coach cible** : annonce le plan substitué (e.g. "Lundi je mets running 40min easy, mercredi renfo bas du corps 35min — j'évite la course deux jours d'affilée") + ouvre une dernière vérif si besoin.

### Tour 6 — Réponse libre courte

User : "Running"

**Coach actuel** : "Je peux ajuster, mais j'ai besoin d'un point de plus. Tu sais deja quels jours sont les plus compliques ?"

**Bug** : le LLM principal n'est jamais appelé. C'est `nlp.py:60 generate_reply()` qui hardcode cette réponse via le fallback de `conversation_pipeline.py:843-844`. Le mot "Running" ne matche aucun token de `extract_reply()` (pas de jour, pas de feeling) → `needs_clarification = True` → réplique en dur. Le contexte du tour précédent (question fermée du coach) est totalement ignoré.

**Coach cible** : interprète "Running" comme la réponse à la question précédente, applique le replan, confirme.

### Tour 7 — Phantom action

User : "Mercredi"

**Coach actuel** : "OK. Je libere ce creneau et je garde la suite propre. Le cap de la semaine ne bouge pas."

**Bugs** :
- Token templaté de `replan_from_life_change.py:500` `_build_user_message()` (chemin `lighten` scenario)
- **Le coach AFFIRME une action mais aucune mutation réelle n'est faite** : les deux séances de natation lundi 20 et mercredi 22 sont toujours planifiées dans la DB après ce tour
- Probable cause : soit le `lighten_day` cible la mauvaise session_id (current week au lieu de mercredi 22), soit `route_adaptation_context_to_llm=True` et le LLM régurgite le `message candidate` du contexte sans produire un `mutation_type ≠ no_change` réel
- Anti-pattern racine : il n'y a aucune garde "dire = faire". Le coach peut prononcer "je libere" sans qu'aucun `plan_mutation_event` ne soit émis

**Coach cible** : applique réellement la mutation (remplace les 2 nages par les sports demandés) ou refuse explicitement de prononcer une affirmation d'action si aucune mutation n'a été commitée.

## Plan d'attaque — 7 chantiers ordonnés

### Chantier 0 — Pré-requis ✅ (fait le 20 avril 2026)
- ✅ Golden case gelé comme smoke scenario : `scripts/smoke-real-conversations --scenario golden_case_autonomy` rejoue les 7 tours
- ✅ Inventaire des system prompts → `docs/COACH-AUTONOMY-AUDIT.md` § 1 (11 prompts en jeu)
- ✅ Audit exhaustif des court-circuits → `docs/COACH-AUTONOMY-AUDIT.md` § 2 (9 court-circuits, dont 4 transactionnels à garder, 5 non-transactionnels à réécrire, + 1 cas hybride `_build_user_message`)

### Chantier 1 — Suppression court-circuits non-transactionnels ✅ (fait le 20 avril 2026)
- ✅ Routing guards `_should_route_availability_context_to_llm` / `_should_route_adaptation_context_to_llm` généralisées : True dès qu'un grounding existe, indépendamment du turn_plan
- ✅ N5 `_execution_contestation_reply` réécrit en contexte de prompt via `_execution_contestation_context_for_prompt`
- ✅ N2 `_maybe_low_signal_reply` renommé `_maybe_low_signal_label` (ack/greeting/motivation) ; injecté via `_low_signal_context_for_prompt` (3 hints anti-phantom-action)
- ✅ N1 `nlp.py extract_reply` + `generate_reply` supprimés ; module `backend/src/fitmas/nlp.py` deleted ; le fallback restant n'est plus qu'une réponse "LLM indisponible, reessaie" sobre
- ✅ N3 / N4 elif branches supprimées ; les groundings sont en contexte de prompt
- ✅ Seul court-circuit non-mutation restant : `calibration_only_reply` (transactionnel par définition)
- ✅ Tests core flows mis à jour (test_low_signal_ack, test_message_flow_can_replan_*, test_explicit_non_completion_correction, test_contextual_non_answer, test_adaptation_routing : 415 passent)

### Chantier 1bis — Anti-mensonge "dire = faire" ✅ (fait le 20 avril 2026)
- ✅ Module `backend/src/fitmas/claim_guard.py` créé : `looks_like_action_claim(reply_text)` détecte les verbes 1ère personne du présent (`libere`, `deplace`, `remplace`, `supprime`, `decale`, `bascule`, `echange`, `retire`, `annule`, `ajoute`, `swap`, `swappe`) précédés de `je` ou `j'`, en excluant les négations (`ne`, `n'`) et les marqueurs de proposition (`je propose`, `je peux`, `je pourrais`, `veux-tu`, `tu confirmes`, `ok pour`, etc.)
- ✅ Garde sortie pipeline (`conversation_pipeline.py`) : si `looks_like_action_claim(outcome.reply_text)` ET ni `outcome.mutation_applied` ni `outcome.pending_confirmation` → réécriture par `safe_rewrite_for_claim_without_mutation()` ("Je n'ai applique aucun changement sur ce tour. Dis-moi explicitement ce que tu veux...") + log warning `conversation_pipeline.claim_without_mutation user=… text=… reply=…` + `response_mode="claim_without_mutation_blocked"`
- ✅ Couvre le cas hybride `_build_user_message` (replan_from_life_change.py:474-507) au runtime sans toucher au template lui-même : si la mutation downstream est appliquée, la phrase reste ; si elle est bloquée, le garde rewrite avant envoi
- ✅ Tests : 23 unit tests sur claim_guard (verbes/négations/proposals/elision droite et typographique) + 2 integration tests sur le pipeline (tour "Mercredi" rewrite vs tour neutre passe-through). 440 tests passent au total
- ⏳ Reste hors scope 1bis : forcer côté prompt le pattern "tool call mutation OU formulation non-affirmative". Couvert en partie par le Chantier 3 (rewrite postures `decide()` + `signal_check`)

### Chantier 2 — Tools de lecture brute pour le coach ✅ (fait le 20 avril 2026)
- ✅ `get_plan_window` (existait déjà — ScheduledSession futures, JSON strict, ISO dates)
- ✅ `get_activities_detailed` couvert par `get_recent_activities` existant (id/local_date/sport_type/title/duration_min/distance_m/avg_speed)
- ✅ `get_user_constraints` créé : filtre `active_facts` par catégories (`availability`, `schedule`, `constraint`, `health`, `fatigue`), exclut inactifs et expirés, retourne id/key/value/urgency/expires_at ISO. Wired dans budgets `PLAN_NEGOTIATION` et `PLAN_LOOKUP` (routing.py + llm.py)
- ✅ `get_load_context` enrichi avec ATL/CTL/TSB (snapshot via `compute_ctl_atl_tsb`) + label `frais`/`neutre`/`fatigue` (TSB > 5 / -10 ≤ TSB ≤ 5 / TSB < -10). TSS estimé à la volée si absent des activités.
- ✅ Pré-fetch via `ToolContext.scheduled_sessions` / `activities` / `active_facts` (déjà en place)
- ✅ Routing : turn_planner intent `availability_constraint` → `PLAN_NEGOTIATION` → 5 tools dont `get_plan_window` + `get_user_constraints`. Le coach LLM reçoit donc plan futur + contraintes mémorisées sur "piscine fermée 2 semaines"
- ✅ Tests : 3 nouveaux unit tests sur `get_load_context` ATL/CTL/TSB et `get_user_constraints` (filtrage actif/expiré + categories override). Tests routing et llm_tools mis à jour pour le budget enrichi. 443 tests passent
- ✅ Chantier 4 (mémoire des contraintes temporelles avec `expires_at` ancré sur la fin de fenêtre) — parser de durée "X semaines/jours" branché dans le fallback, `IndicationTimeReference.window_end_date` ajouté, `build_availability_fact_payloads_from_indication` produit un `UserFact` category=availability avec `expires_at = end + 1 jour` (00:00) et une clé `unavailable_<sport>_<start>_<end>` parseable en inverse, et `_targeted_execution_clarification` saute la clarification quand la séance d'hier est recouverte par un fact availability actif

### Chantier 2bis — Heartbeat utilise les mêmes capacités ✅ (fait le 21 avril 2026)
- ✅ `weekly_review()` (heartbeat.py:281-368) construit `recent_reality` puis `coach_reading_digest` (mêmes appels que `morning_briefing`), avec dégradation gracieuse en log warning si l'un échoue
- ✅ `build_review_prompt()` (roles.py:347-401) accepte `digest: CoachReadingDigest | None` et l'injecte via `render_digest_for_prompt(digest)` après les compteurs agrégés (qui restent pour compat des tests existants)
- ✅ Anti-hallu rule miroir du briefing matin ajoutée dans le system prompt review : "N'invente jamais un comptage hebdomadaire et ne dis pas 'zero <sport>' si une sortie de ce sport apparait dans le bloc, meme hors plan"
- ✅ Le digest expose déjà `real_entries` détaillés (dataclass `RealEntry` avec `linked_to_plan`) — `render_digest_for_prompt` produit `swimming 45' jeu (offplan)` lisible par le LLM
- ✅ Test `test_weekly_review_surfaces_offplan_swimming_entry` : nage offplan en DB → prompt review contient "Lecture de la semaine", "swimming", "(offplan)" + system prompt contient l'anti-hallu rule. 444 tests passent
- ⏳ Reste hors scope 2bis : faire passer weekly_review et morning_briefing par `route_tools_for_query` + `execute_tool_call` comme la conversation (aujourd'hui ils consomment les builders directement, pas le tool runtime)

### Chantier 3 — Audit + rewrite system prompts ✅ (fait le 21 avril 2026)

Audit prealable : la pathologie "demande au user au lieu de décider" est moins lexicale qu'architecturale. Les prompts contiennent peu de "propose deux options", mais :
- Aucune **posture explicite** "tu DÉCIDES, tu défends, tu ne renvoies pas la balle" → ajoutée
- Aucun **marker de continuation de fil** (le coach pose une question, le user répond à côté, le coach change de sujet en silence) → ajouté
- Court-circuit `clarification` du pipeline (`conversation_pipeline.py:375-399`) qui shunte `decide()` reste un risque architectural — laissé tel quel pour ce chantier (couvert par 1bis sur la sortie ; à reprendre si la posture LLM ne suffit pas)

Livré :
- ✅ Bloc **"Posture coach (non-negociable)"** ajouté à `_CONVERSATION_SYSTEM_TEXT` (`backend/src/fitmas/llm_prompt_builder.py`) : "Tu DECIDES. Tu defends ton choix. Tu ne renvoies pas la balle au user pour un arbitrage que tu peux trancher avec le contexte fourni." + "Tu n'ouvres pas par 'Tu veux que je...', 'Tu preferes A ou B ?', 'Je propose deux options'." + clause "Imprevu n'est pas une demande de menu, c'est un signal a creuser ou a integrer dans une decision claire." + clause **continuation de fil** ("si le tour precedent contenait une question ouverte de ta part et que le user n'y a pas repondu, soit tu la reformules, soit tu decides avec ton hypothese explicite").
- ✅ Helper `detect_open_question(coach_text)` (`backend/src/fitmas/llm_prompt_builder.py`) : déterministe, retourne la dernière phrase interrogative significative ; ignore les confirmations administratives (`ok ?`, `tu confirmes ?`, `ca te va ?`, etc.).
- ✅ Marker injecté dans le **user prompt** (pas system) des deux builders `build_conversation_prompt_bundle` et `build_layered_conversation_prompt` : si la dernière entrée `agent` de l'historique se termine sur une vraie question, le bloc `Question ouverte du tour precedent (a toi, pas au user) : "..."` est ajouté avec consigne "ne change pas de sujet en silence".
- ✅ Marker équivalent côté **morning_briefing** : `_pending_open_question_for_user(db, user)` regarde le dernier message agent en DB ; si la dernière interaction utilisateur est antérieure à cette question, le bloc est passé via `pending_open_question` à `build_briefing_prompt` et injecté en queue de prompt.
- ✅ Tests : 1 test posture (`CoachPostureTest`) + 5 tests détection (`OpenQuestionDetectionTest`) + 4 tests injection prompt (`OpenQuestionMarkerInjectionTest` couvrant classique/layered/statement/confirmation) + 2 tests heartbeat (`test_morning_briefing_surfaces_pending_open_question_from_last_agent` et `..._omits_open_question_marker_when_user_already_replied`). 456 tests passent.
- ⏳ Hors scope 3 : tester via un golden-case "imprevu" end-to-end avec LLM réel — couvert au moment du dogfood post-refactor

### Chantier 3bis — Court-circuit clarification → contexte pour decide() ✅ (fait le 21 avril 2026)

Symptôme remonté en dogfood : sur une séance manquée, le canned `"Tu l'as faite ou pas ?"` court-circuitait `decide()` et bouclait à chaque tour suivant ; le user avait l'impression de parler à un disque rayé.

Cause : `conversation_pipeline.py:375-399` faisait un `_reply_and_record_turn(reply_text=clarification.question)` au lieu de laisser le LLM arbitrer. Aucun garde n'empêchait la pose répétée tour après tour côté pipeline (le seul garde, `looks_like_execution_clarification_prompt`, vit à l'intérieur du helper et ne s'applique que si l'agent a posé la question texto au tour précédent — ce qui était toujours vrai, mais une fois la question posée elle restait "non resolue" tant que le user ne répondait pas par "oui"/"non" propre).

Refactor :
- ✅ Helper `render_unresolved_execution_followup(clarification, *, target_date_iso)` (`backend/src/fitmas/execution_clarification.py`) : produit un bloc soft "Suivi execution non resolu (a toi de juger : creuser, integrer ou ignorer ce tour) : ..." avec id session, question candidate, raison d'impact et consigne anti-répétition.
- ✅ Param `unresolved_execution_followup: str | None` ajouté à `build_conversation_prompt_bundle` et `build_layered_conversation_prompt` (`llm_prompt_builder.py`), injecté en queue de user prompt à côté du marker open-question.
- ✅ `llm.py` lit `coach_context["unresolved_execution_followup"]` et le passe au builder layered.
- ✅ `conversation_pipeline.py` : suppression du `return _reply_and_record_turn(...)` ; le clarification est rendu via `render_unresolved_execution_followup` puis attaché à `coach_context["unresolved_execution_followup"]` dans le payload `decide()`. Le garde `looks_like_execution_clarification_prompt(previous_agent_text)` à l'intérieur de `_targeted_execution_clarification` reste actif → si le LLM a posé la question au tour précédent, le helper retourne `None` et aucun bloc n'est injecté → la boucle est cassée déterministiquement.
- ✅ Tests pipeline (`test_core_flows.py`) : `test_message_flow_surfaces_targeted_clarification_as_prompt_context_to_llm` (decide est appelé + coach_context contient le bloc), `test_targeted_clarification_does_not_block_fatigue_adaptation_anymore` (la fatigue passe maintenant sans être avalée par la clarification), `test_targeted_clarification_followup_breaks_loop_after_first_turn` (anti-loop : second tour reçoit `None`), `test_contextual_non_answer_resolves_clarification_via_decide` + `test_health_reply_after_clarification_is_ingested_normally` (les flux aval continuent de fonctionner quand le LLM relaye la question).
- ✅ Tests prompt (`test_llm_prompt_builder.py`) : `UnresolvedExecutionFollowupInjectionTest` couvre classique/layered/None.
- 460 tests passent.

### Chantier 4 — Mémoire des contraintes temporelles ✅ (fait le 21 avril 2026)

Symptôme remonté en dogfood (screenshot Telegram) : après "imprevu, piscine fermee 2 semaines", le coach continuait de reposer la clarification execution "tu l'as faite ou pas ?" sur la natation de lundi, et au tour suivant il ne se souvenait plus de la contrainte. Aucune mémoire persistante de la fenêtre d'indisponibilité.

Cause racine : l'interprétation d'une contrainte multi-jours produisait bien un `UserIndication(kind=AVAILABILITY_CONSTRAINT)`, mais (1) aucune durée n'était extraite (pas de `window_end_date`), (2) rien ne la persistait en `UserFact` avec `expires_at`, (3) le garde anti-clarification ne connaissait pas ces faits pour sauter la question sur les séances couvertes par la fenêtre.

Refactor :
- ✅ Schéma : `IndicationTimeReference.window_end_date: date | None` ajouté (`user_indications.py`), propagé dans `_time_reference_from_payload` pour les parses LLM.
- ✅ Parser durée : `_extract_constraint_duration_days` gère "2 semaines", "15 jours", "une semaine", "la semaine" (quelques regex ciblées). Branché dans `_fallback_availability_indication` : `window_end = resolved_date + timedelta(days=max(0, duration - 1))`, scope upgradé à WEEK.
- ✅ Builder : `build_availability_fact_payloads_from_indication(indication)` produit un `UserFact` category=`availability`, key `unavailable_<sport|general>_<start-iso>_<end-iso>` (encoding complet pour pouvoir retrouver start/end/sport depuis la clé, les extras sont silencieusement ignorés par le schéma), value explicite, `expires_at = datetime.combine(end + timedelta(days=1), time.min)`. Skippe les contraintes single-day et les polarités non-UNAVAILABLE. Sport détecté via `_TRIGGER_ACTIVITY_PATTERNS` sur le texte normalisé.
- ✅ Parse inverse : `parse_availability_fact_key(key) → AvailabilityConstraintKey{sport_type, start_date, end_date}` pour que le garde anti-clarification puisse comparer la date d'hier à la fenêtre sans relire l'indication d'origine.
- ✅ Pipeline : `conversation_pipeline.py` appelle `build_availability_fact_payloads_from_indication` AVANT le traitement health, persiste via `_persist_turn_memory_updates`, puis refresh `_active_memory_payloads` (même pattern que le flux santé).
- ✅ Garde clarification : `_yesterday_session_covered_by_active_constraint` dans `api_messages.py` parcourt `repo.get_active_facts` (filtré par `fact_is_current(expires_at)`), parse les clés `unavailable_*`, et retourne True si la date d'hier tombe dans la fenêtre ET (sport match ou contrainte générale). Wiré dans `_targeted_execution_clarification` après le check `yesterday_sessions` et avant le `build_execution_clarification`.
- ✅ Tests (`test_user_indications.py`) : 3 tests parser (`AvailabilityConstraintDurationTest` : "2 semaines", "15 jours", pas de durée → window_end None) + 7 tests builder/parser inverse (`AvailabilityFactBuilderTest` : produit le fact avec expires_at correct, fallback `general` sans activité, skip single-day, skip LIMITED polarity, roundtrip clé, `general` sport None, clés malformées).
- ✅ Tests pipeline (`test_core_flows.py`) : `test_availability_constraint_persists_as_fact_with_window_anchored_expires_at` (mock interpret → UserFact en DB avec bonne clé + expires_at) + `test_execution_clarification_skipped_when_active_availability_fact_covers_yesterday` (séance natation hier + fact actif → `_targeted_execution_clarification` retourne None).
- 472 tests passent.

### Etat code actuel du chantier 5 — slice partiel livre le 22 avril 2026

Commit `40bf4a1` a deja pose une premiere brique :

- `backend/src/fitmas/replan_proposal.py`
- tool runtime `propose_replan` dans `backend/src/fitmas/tools/registry.py`
- budget `PLAN_NEGOTIATION` enrichi dans `backend/src/fitmas/llm.py`
- guidance prompt dans `backend/src/fitmas/llm_prompt_builder.py`
- tests dans `tests/test_tool_runtime.py`, `tests/test_llm_tools.py`, `tests/test_plan_mutation_service.py`

Ce slice est utile, mais il ne doit pas devenir la cible finale.

Limites actuelles :

- `propose_replan` choisit une mutation candidate de maniere assez deterministe (`swimming -> strength/running`)
- il couvre surtout la premiere seance impactee, meme si la contrainte couvre plusieurs jours
- il retourne une `recommended_mutation`, donc il peut redevenir un mini-coach cache
- `MutationDecision` reste mono-operation dans le chemin conversationnel courant
- `validate_week_plan()` valide une semaine reconstruite, mais pas un patch utilisateur multi-operations avec statut gradue
- `run_pre_mutation_hooks()` reste binaire (`allowed` / blocked) avec warnings, pas `valid / warning / requires_confirmation / blocked`
- `PlanMutationService.apply_decisions_for_user()` accepte une sequence, mais le pipeline conversation applique surtout une decision unique et les confirmations stockent une decision unique
- le runtime tool LLM actuel fait un seul tool call par tour ; il ne supporte pas encore une vraie boucle draft -> validate -> correct -> revalidate

Conclusion :

`propose_replan` devient un **helper de candidates / compat**, pas le cerveau du replan.
La cible du chantier 5 est maintenant `PlanPatch`.

Priorite produit court terme :

- on ne cherche pas encore un coach sportivement parfait
- on cherche d'abord un agent fiable pour planifier, reagir aux questions/remarques/contraintes et garder le fil
- "fiable" veut dire : lire la verite, ne pas halluciner le planning, ne pas demander un menu quand il peut decider, ne pas dire qu'il a applique sans event reel
- les bonnes pratiques sportives restent des garde-fous gradues ; elles ne doivent pas redevenir le cerveau conversationnel

## Plan d'attaque recale — Agent fiable, tools atomiques, PlanPatch audite

### Chantier 5A — Regressions conversationnelles depuis dogfood

But :

- transformer les captures Telegram en gates de comportement
- proteger la direction produit avant de refactorer le moteur
- mesurer la fiabilite agentique avant l'optimisation sportive fine

Fichiers :

- `scripts/smoke_real_conversations.py`
- `tests/test_core_flows.py`
- `tests/test_llm_prompt_builder.py`
- `tests/test_plan_mutation_service.py`
- eventuellement `tests/test_tool_runtime.py`

Cas a couvrir :

- pas de token interne (`this_week`) en sortie
- pas de plan futur hallucine quand la semaine est vide
- "piscine fermee 2 semaines" memorise une contrainte et ne relance pas "tu l'as faite ou pas ?"
- "Oui" puis "Running" puis "Mercredi" reste un seul fil de continuation
- aucune phrase "je libere / je mets / je deplace" sans event mutation ou confirmation pending
- swap avec recuperation protegee propose un chemin (`swap` ou deplacement recup), pas une boucle defensive
- reponses aux questions simples (`tu vois ma seance ?`, `c'est quoi demain ?`, `pourquoi repos ?`) lisent les bonnes sources et restent courtes

Gate :

- smoke `golden_case_autonomy` enrichi avec les captures 15/17/19/20/21 avril
- tests unitaires ciblant les failures sans dependre d'un LLM reel quand possible

### Recalage 5B+ — DeepSeek, tools atomiques, skills

Le smoke DeepSeek du 24 avril a change l'ordre du chantier.

Observation :

- DeepSeek V4 demande spontanement les bons tools pour une contrainte comme "piscine fermee 2 semaines" : `get_plan_window`, `get_user_constraints`, `get_load_context`, puis parfois `propose_replan`
- le provider Anthropic-compatible DeepSeek ignore `disable_parallel_tool_use`
- le code a ete durci pour satisfaire tous les `tool_use_id`, mais il n'execute encore qu'un seul tool et renvoie les autres en erreur `single_tool_per_turn`

Conclusion :

Le probleme n'est pas "il faut un gros `get_coach_state` qui remplace tout".
Le probleme est : **la surface tools est bonne mais le runtime est trop etroit**.

Les smokes reels DeepSeek ajoutent un prerequis :

- l'API DeepSeek V4 repond bien et ne reprovoque plus le 400 tool-use
- le modele demande souvent les bons tools
- mais la reponse finale apres tool-use revient parfois en prose au lieu du JSON contractuel
- le fallback actuel evite le crash, mais ce n'est pas assez fiable pour un coach quotidien

Donc la sequence devient :

1. stabiliser le contrat provider DeepSeek
2. seulement ensuite elargir le runtime multi-tool
3. puis brancher l'action sur `PlanPatch`

Nouvelle doctrine tools :

- garder les tools atomiques : testables, auditables, reutilisables par chat / API / heartbeat
- autoriser une composition bornee quand le modele intelligent la demande
- introduire des skills metier pour les workflows repetes
- garder `get_coach_state` comme macro-tool / shortcut optionnel, pas comme fondation unique
- toute action reste `PlanPatch -> validation -> orchestration`, jamais write DB libre depuis le tool loop

Flux cible :

```
User
  -> turn intent / skill routing
  -> Coach LLM
      -> read tools atomiques (multi-tool borne)
      -> CoachDecision
      -> PlanPatch
  -> validate_plan_patch
  -> conversation_pipeline / PlanMutationService.apply_patch_for_user
  -> reply depuis event reel ou confirmation pending
```

### Chantier 5B0 — Stabilisation DeepSeek provider contract

But :

- garder DeepSeek V4 comme provider principal si son rapport perf/prix tient
- ne pas confondre compatibilite Anthropic et comportement Claude natif
- rendre les sorties structurees fiables avant d'augmenter l'autonomie tools

Evidence du smoke reel 24 avril :

- `tests/test_integration_real.py` : 15 tests + 5 subtests passent avec DeepSeek
- `smoke-real-conversations` : 22 tours reels, aucun crash, aucun 400 tool-use
- instabilite principale : 5 reponses finales en prose au lieu de JSON, surtout apres tool-use
- fallback actuel recupere, mais masque le probleme au lieu de le rendre observable

Evidence du spike OpenAI SDK 24 avril :

- script : `scripts/spike_deepseek_openai_sdk.py`
- `deepseek-v4-flash` fonctionne sur `https://api.deepseek.com` avec `response_format={"type":"json_object"}`
- JSON direct : OK avec budget de sortie suffisant
- tool-use -> JSON final : OK apres avoir rejoue `reasoning_content` dans le message assistant
- tool-use -> JSON final : peut produire des `mutation_type` hors enum FitMAS (`replace`, `unplanned_skip`)
- function-call final strict :
  - `deepseek-v4-flash` peut fonctionner avec budget de sortie suffisant
  - il reste a tester en matrice plus large avant de le considerer stable
  - `deepseek-chat` peut emettre le tool final, mais n'est pas identique a V4
- `deepseek-v4-pro` ne passe pas encore le probe JSON OpenAI-compatible local
- conclusion : l'OpenAI SDK est prometteur pour les appels structurels, mais il faut un adapter teste par model/capability, pas une migration globale aveugle

Slice livre le 24 avril :

- `llm_gateway.request_structured_json(...)` ajoute le chemin DeepSeek OpenAI-compatible `response_format=json_object`
- `FITMAS_USE_DEEPSEEK_OPENAI_STRUCTURED=1` active ce chemin dans `llm.decide()`
- `llm.decide()` valide localement les decisions FitMAS avant `MutationDecision`
- prose apres tool-use : tentative de repair structuree avant fallback general
- schema invalide : fallback Claude via `ANTHROPIC_API_KEY` si disponible
- le flag reste desactive par defaut tant que la matrice smoke n'est pas assez stable

Renfort du 24 avril soir :

- DeepSeek structured output passe a 3 tentatives et 3072 tokens minimum
- le prompt JSON interdit explicitement les promesses de mutation quand `mutation_type=no_change`
- validation locale supplementaire :
  - `no_change` ne peut pas dire que le plan est ajuste / modifie / libere / mis a jour
  - `no_change` ne peut pas promettre de construire, poser, placer ou ajouter une seance
  - `fitmas_message` tronque ou finissant sur une clarification coupee est rejete
  - le vouvoiement (`vous` / `vos` / `votre`) est rejete sur les messages coach
- repair apres tool-use :
  - convertit la prose en JSON canonique
  - ignore le markup provider DSML pur pour revenir au chemin structured direct
  - doit reformuler en clarification neutre si la prose promet une action sans mutation valide
  - budget porte a 1024 tokens
- le parser JSON ne log plus de faux `NoneType: None` quand un payload est simplement invalide

Decision provider :

- DeepSeek-first pour conversation et petits arbitrages
- DeepSeek Flash pour low-risk / lecture / extraction si la qualite locale tient
- DeepSeek Pro pour planning, contraintes, replan, validation complexe
- DeepSeek OpenAI-compatible pour structured output si le smoke local confirme un gain
- DeepSeek Anthropic-compatible conserve pour les chemins deja branches et V4 Pro tant que l'OpenAI-compatible Pro n'est pas stable
- Claude Haiku comme fallback de format rapide
- Claude Sonnet comme fallback rare pour cas complexes ou regression DeepSeek

Cible technique :

- budget complexite :
  - ne pas introduire un nouveau chemin LLM dans les modules domaine
  - garder `llm_gateway` comme unique frontiere provider
  - limiter le premier slice a DeepSeek OpenAI structured-output + fallback Claude
  - ne pas migrer heartbeat/planning/onboarding tant que conversation n'est pas stabilise
  - supprimer ou archiver le spike une fois l'adapter produit livre
- gateway multi-adapter :
  - `DeepSeekOpenAIAdapter`
  - `DeepSeekAnthropicAdapter`
  - `ClaudeAnthropicAdapter`
- capability matrix par modele :
  - `json_object`
  - `tool_call`
  - `tool_followup_json`
  - `forced_final_tool`
  - `requires_reasoning_content_replay`
- wrapper de sortie structuree :
  - tente `message_json`
  - si `None`, lance une repair pass courte avec le texte brut et le schema attendu
  - si repair impossible, fallback provider
- schema validation stricte avant d'accepter une decision
  - champs requis non vides
  - enums FitMAS canoniques seulement
  - `target_session_id` obligatoire pour les mutations qui modifient une seance existante
- metrics par appel :
  - `provider`
  - `model`
  - `structured_output_ok`
  - `json_repair_used`
  - `provider_fallback_used`
  - `tool_json_failure`
  - `raw_stop_reason`
- tests reels bornes :
  - casual
  - plan lookup
  - execution report
  - availability constraint
  - short continuation (`Oui`, `Running`, `Mercredi`)
  - tool-use final JSON

Fichiers probables :

- `backend/src/fitmas/llm_gateway.py`
  - router provider/model
  - isoler les adapters SDK
  - repair structured output
  - metrics provider
- `scripts/spike_deepseek_openai_sdk.py`
- `backend/src/fitmas/llm.py`
  - utiliser le wrapper sur les decisions conversation
  - ne plus traiter "prose apres tool" comme simple fallback silencieux
- `tests/test_llm_gateway_json.py`
- `tests/test_integration_real.py`
- `scripts/smoke_real_conversations.py`

Gate :

- 0 sortie non-JSON acceptee comme decision finale
- 0 crash API
- 0 erreur 400 tool-use
- toutes les sorties prose apres tool-use sont soit reparees, soit reroutees vers fallback provider
- la matrice smoke ciblee tourne avec moins de 5% de fallback provider
- chaque fallback est trace avec le texte brut tronque et le schema attendu
- aucun import `openai` / `anthropic` hors gateway/adapters et tests
- aucun changement de comportement domaine dans ce slice, seulement provider contract + validation

### Chantier 5B — Runtime tools V2 multi-tool borne ✅ slice 1 livre le 25 avril 2026

But :

- tirer parti de DeepSeek V4 quand il demande plusieurs tools coherents
- respecter le protocole Anthropic-compatible : chaque `tool_use_id` recoit un `tool_result`
- rester borne : pas de boucle agentique libre, pas de write DB, pas d'explosion cout/latence

Etat code actuel :

- `_request_json_with_tools()` dans `backend/src/fitmas/llm.py` accepte plusieurs `tool_use` dans le meme tour
- `execute_tool_calls()` dans `backend/src/fitmas/tools/runtime.py` execute un batch borne et preserve un resultat par tool demande
- budget actuel : max 3 tools executes par tour ; les surplus recoivent `tool_budget_exceeded`
- tous les `tool_use_id` recoivent un `tool_result`, y compris les tools bloques
- `ToolTrace` trace encore surtout la session outillee ; la trace session-level detaillee reste a enrichir

Cible :

- `ToolExecutionPolicy` par intent :
  - `max_tools_per_round`
  - `max_round_trips`
  - `allowed_parallel`
  - `tool_categories` (`read`, `validation`, `write` plus tard)
- execution de tous les tools read-only / validation-only demandes tant qu'ils sont autorises et sous budget
- blocage explicite des surplus et des writes :
  - `tool_result.is_error = true`
  - payload `{error: "tool_budget_exceeded" | "tool_not_allowed" | "write_tool_not_allowed"}`
- traces session-level :
  - `requested_tools`
  - `executed_tools`
  - `blocked_tools`
  - `tool_result_count`
  - `tool_loop_round_trips`

Fichiers touches / probables :

- `backend/src/fitmas/tools/contract.py`
  - ajouter metadata `kind: read | validation | write`
  - ajouter une policy simple si necessaire
- ✅ `backend/src/fitmas/tools/runtime.py`
  - `execute_tool_calls(...)` batch ajoute
  - `execute_tool_call(...)` conserve pour compat
- `backend/src/fitmas/tools/metrics.py`
  - etendre `ToolTrace` ou ajouter `ToolSessionTrace`
- `backend/src/fitmas/llm.py`
  - remplacer le "premier tool uniquement" par batch borne
- `tests/test_llm_tools.py`
- `tests/test_tool_runtime.py`

Gate :

- ✅ si DeepSeek renvoie `get_plan_window` + `get_user_constraints`, les deux sont executes et renvoyes au follow-up
- ✅ si DeepSeek renvoie plus de 3 tools, les 3 premiers valides sont executes, les autres ont un `tool_result` d'erreur controlee
- aucun tool write ne peut etre execute par le runtime conversationnel
- ⏳ les logs session-level doivent encore mieux distinguer tools demandes/executés/bloqués
- le smoke `golden_case_autonomy` ne produit plus de 400 tool-use

### Chantier 5C — Surface tools atomique + shortcut optionnel

But :

- garder une interface agent-machine claire
- eviter a la fois le "gros blob magique" et le catalogue de 40 micro-tools
- transformer `get_coach_state` en shortcut utile, pas en cerveau cache

Etat actuel a reutiliser :

- `ConversationTurnState` assemble deja `scheduled_sessions`, `activities`, `active_facts`
- `coach_state_bundle.py` produit deja un bundle partage pour app/coach
- tools existants : `get_plan_window`, `resolve_planning_window`, `get_recent_activities`, `get_load_context`, `get_user_constraints`, `get_relevant_facts`
- `propose_replan` existe mais agit encore comme une recommandation mono-cible

Cible :

- ameliorer descriptions et payloads des tools existants :
  - descriptions 3-4 phrases quand le comportement est subtil
  - champs high-signal seulement
  - erreurs actionnables
- classer chaque tool :
  - `read`: lit une verite
  - `validation`: valide un draft sans write
  - `candidate`: propose des options, ne tranche pas
  - `write`: interdit au runtime LLM pour l'instant
- `get_coach_state` optionnel :
  - macro-tool read-only pour les conversations simples et heartbeat
  - payload compact : `clock`, `today`, `next_72h`, `week_sessions`, `active_constraints`, `load`, `recent_activities`, `truth_notes`
  - ne remplace pas les tools atomiques dans les cas ambigus

Fichiers probables :

- `backend/src/fitmas/tools/registry.py`
- `backend/src/fitmas/tools/contract.py`
- `backend/src/fitmas/coach_state_bundle.py`
- `tests/test_tool_runtime.py`
- `tests/test_llm_tools.py`

Gate :

- pour "piscine fermee 2 semaines", les tools atomiques permettent de reconstruire : fenetre, seances impactees, contrainte active, load/recovery
- `get_coach_state` ne lit jamais `WeeklyPlan` / `DayPlan` comme verite runtime
- les tool descriptions n'incitent plus le modele a considerer `propose_replan` comme autorite finale

### Chantier 5D — Skill metier `replan_after_constraint`

But :

- formaliser les workflows repetes sans rendre le runtime libre
- donner au coach une routine actionnable pour les cas dogfood : piscine fermee, voyage, indispo, swap, recuperation protegee

La skill n'est pas un write DB.
C'est un protocole de raisonnement outille :

```
replan_after_constraint
  trigger:
    - availability_constraint
    - plan_mutation avec contrainte temporelle/sportive
    - continuation "oui" / "running" / "mercredi" apres question de replan
  tools autorises:
    - get_plan_window
    - get_user_constraints
    - get_load_context
    - get_recent_activities si le user conteste le reel
    - suggest_replan_candidates
    - validate_plan_patch
  sortie:
    - CoachDecision(response_type="plan_patch", plan_patch=...)
    - ou CoachDecision(response_type="requires_confirmation", ...)
    - ou CoachDecision(response_type="no_change", reason clair)
```

Fichiers probables :

- documentation dans `docs/RUNTIME-TOOLS.md` et ce doc
- prompt guidance dans `backend/src/fitmas/llm_prompt_builder.py`
- routing dans `backend/src/fitmas/llm.py` ou nouveau module de policy
- tests `tests/test_llm_prompt_builder.py`

Gate :

- la skill dit explicitement "ne demande pas un menu si les tools suffisent"
- la skill force la sortie `PlanPatch` quand une action est decidee
- la skill ne permet aucun commit direct

### Chantier 5E — Contrat `PlanPatch` ⏳ slices 1-2 livres les 24-25 avril 2026

But :

- remplacer la decision mono-operation implicite par une intention structuree batchable
- laisser le LLM exprimer une adaptation complete sans que le code choisisse a sa place

Cible domaine :

```python
PlanPatch {
  reason: str
  operations: list[PlanPatchOperation]
  user_visible_intent: str
}

PlanPatchOperation {
  operation_type: replace_session | move_session | swap_sessions | update_session | lighten_day | create_session
  target_session_id: int | None
  second_session_id: int | None
  target_date: str | None
  new_sport_type: str | None
  new_session_type: str | None
  new_duration_min: int | None
  new_intensity: str | None
  new_title: str | None
  new_goal: str | None
  rationale: str
}
```

Approche progressive :

- ✅ garder `MutationDecision` comme wire format legacy
- ⏳ creer un adaptateur `MutationDecision -> PlanPatch`
- ✅ creer un adaptateur `PlanPatchOperation -> MutationDecision` pour reutiliser `mutations.py` au debut
- ✅ ne pas casser les endpoints app existants

Slice livre :

- `backend/src/fitmas/plan_patch.py`
- `PlanPatch` + `PlanPatchOperation` batchable
- operations supportees au depart : `move_session`, `swap_sessions`, `replace_session`, `update_session`, `lighten_day`, `create_session`
- `adapt_plan_patch_to_mutation_decisions(patch)` conserve l'ordre et injecte `coach_message` comme `fitmas_message` legacy
- `create_session` sort du legacy adapter et passe par `PlanMutationService` pour creer une `ScheduledSession` datee + event audite
- validation locale `create_session` : date future, sport/titre/duree requis, blocage si le jour contient deja une seance training stable
- aucun write DB dans le module

Fichiers probables :

- ✅ create `backend/src/fitmas/plan_patch.py`
- modify `backend/src/fitmas/llm.py` ensuite, pas au premier slice
- modify `backend/src/fitmas/mutation_permissions.py` pour serialiser pending confirmations patch
- ✅ tests : `tests/test_plan_patch.py`

Gate :

- ✅ un patch single operation round-trippe vers l'ancien `MutationDecision`
- ✅ un patch multi-operation conserve l'ordre et les IDs
- ✅ aucun write DB dans ce module

### Chantier 5F — `validate_plan_patch` ⏳ slice 1 livre le 24 avril 2026

But :

- transformer les bonnes pratiques training en validation graduee
- ne plus confondre "suboptimal" avec "impossible"

Cible :

```json
{
  "status": "valid | warning | requires_confirmation | blocked",
  "issues": [
    {
      "code": "protected_recovery_moved",
      "severity": "requires_confirmation",
      "message": "Vendredi protege ta recuperation post-charge.",
      "suggested_fix": "Deplacer la recuperation samedi."
    }
  ],
  "normalized_patch": {},
  "summary": "Patch applicable avec confirmation ciblee."
}
```

Sources de validation a composer :

- `plan_validator.validate_week_plan`
- ✅ `mutation_hooks.run_pre_mutation_hooks`
- `mutation_permissions.assess_mutation_impact`
- `training_load.compute_ctl_atl_tsb`
- `session_similarity.find_same_sport_proximity_conflict`
- active facts health / availability

Regle de classification :

- danger sante/blessure ou cible inexistante -> `blocked`
- recuperation protegee modifiee mais preservable ailleurs -> `requires_confirmation`
- proximite meme sport / load dense mais acceptable -> `warning` ou `requires_confirmation` selon gravite
- patch propre -> `valid`

Slice livre :

- `validate_plan_patch(...)` dans `plan_patch.py`
- statut global et statut par operation
- `allowed=False` des pre-hooks -> `blocked`
- warnings pre-hooks -> `requires_confirmation`
- aucun commit quand le statut global n'est pas `valid`

Fichiers probables :

- ⏳ create `backend/src/fitmas/plan_patch_validator.py` si le wrapper devient trop riche
- modify `backend/src/fitmas/mutation_hooks.py` seulement si necessaire ; preferer d'abord un wrapper pour limiter le risque
- expose tool read-only `validate_plan_patch` dans `tools/registry.py`
- ✅ tests : `tests/test_plan_patch.py`
- tests suivants : `tests/test_plan_patch_validator.py`, `tests/test_tool_runtime.py`

Gate :

- swap avec recuperation protegee n'est pas bloque si la recup reste dans la semaine
- replace d'une recuperation protegee sans preservation sort `requires_confirmation` ou `blocked` selon contexte
- piscine fermee multi-jours produit un patch qui couvre toutes les nages impactees ou indique explicitement les restes
- le LLM peut recevoir des `suggested_fixes` exploitables

### Chantier 5G — Commit patch par orchestrateur ⏳ slice 1 livre le 24 avril 2026

But :

- donner au coach une capacite d'action reelle sans write libre dans un tool LLM
- garantir "dire = faire"

Cible :

- `commit_plan_patch` est une capacite orchestrateur, pas un tool runtime DB libre dans le premier slice
- le LLM finalise un `PlanPatch`
- le pipeline revalide le patch cote serveur
- si `valid` / `warning` acceptable -> commit via `PlanMutationService`
- si `requires_confirmation` -> pending confirmation stocke le patch complet
- si `blocked` -> pas de commit ; le coach recoit les raisons et propose alternative

Fichiers probables :

- ✅ modify `backend/src/fitmas/plan_mutation_service.py`
  - ✅ add `apply_patch_for_user(...)`
  - one event per operation au debut, puis summary patch si besoin
- modify `backend/src/fitmas/conversation_pipeline.py`
  - branch `PlanPatchDecision`
  - pending confirmation patch
  - reply derivee des applied events
- modify `backend/src/fitmas/mutation_permissions.py`
  - serialize / deserialize patch confirmations
- tests : `tests/test_plan_mutation_service.py`, `tests/test_core_flows.py`

Gate :

- ✅ patch `valid` passe par `apply_decisions_for_user`
- ✅ patch `requires_confirmation` refuse proprement avant write
- ⏳ patch batch applique toutes ses operations ou refuse proprement avant write
- ⏳ `event_count == applied_count`
- reply finale vient des events appliques
- claim guard reste en defense-in-depth

### Chantier 5H — Brancher le coach LLM sur PlanPatch ⏳ slice contrat livre le 25 avril 2026

But :

- sortir du JSON `MutationDecision` mono-operation comme seule forme d'action
- permettre au coach de decider vraiment sur les demandes complexes

Approche progressive :

1. ✅ Ajouter un nouveau schema `CoachDecision` :
   - `response_type`: `reply | no_change | mutation_decision | plan_patch | requires_confirmation`
   - `plan_patch`: optionnel, valide comme `PlanPatch` non vide quand `response_type=plan_patch`
   - `mutation_decision`: optionnel, garde legacy valide quand `response_type=mutation_decision`
   - `fitmas_message`: brouillon non fiable tant que non commit
   - parser local `parse_coach_decision_payload(...)` dans `llm.py`, non branche comme sortie primaire de `decide()` a ce stade
2. Le pipeline ignore toute promesse d'action du brouillon avant commit.
3. Apres commit, la reply finale est regeneree ou reconstruite depuis event summary.
4. Garder `MutationDecision` en fallback legacy pendant la transition.

Fichiers probables :

- ✅ `backend/src/fitmas/llm.py`
- `backend/src/fitmas/llm_prompt_builder.py`
- `backend/src/fitmas/conversation_pipeline.py`
- `tests/test_llm_prompt_builder.py`
- `tests/test_core_flows.py`
- ✅ `tests/test_llm_tools.py`

Gate :

- "Oui / Running / Mercredi" peut produire un patch coherent sans nouvelle clarification inutile
- "piscine fermee 2 semaines" produit soit un patch batch complet, soit un patch partiel explicitement scoped
- aucune reponse finale ne sort du brouillon LLM si le commit echoue

### Chantier 5I — Reclasser `propose_replan`

But :

- eviter un nouveau determinisme coach cache

Options :

- renommer en `suggest_replan_candidates`
- ou garder `propose_replan` temporairement mais changer sa description :
  - retourne des candidates + impacts
  - ne tranche pas
  - ne pretend pas couvrir toute la fenetre sauf si c'est vrai

Gate :

- le prompt ne dit plus "pars de cette recommandation et tranche" comme si le tool avait raison par autorite
- le tool n'est plus le seul chemin pour replanifier
- toute decision finale passe par `PlanPatch` + validation

### Chantier 6 — Audit pipeline LLM préliminaires (différé)
- Aujourd'hui : 3 LLM en cascade (turn_planner + indication_parser + decide)
- Une fois decide() libéré et outillé, les 2 préliminaires sont-ils encore nécessaires ?
- Probablement turn_planner reste utile (routing + tools selection), indication_parser peut être absorbé
- À évaluer en post-mortem du refactor

## Guardrails pendant le refactor

- **Confirmations writes maintenues** : tout `apply_plan` ou `set_completion_status` initié par le coach demande encore une confirmation oui/non Telegram. Filet de sécurité pendant la montée en autonomie.
- **Latence acceptée** : un tour peut passer de 3s à 8-12s. Le gain en autonomie/fiabilité justifie le coût.
- **Validation stricte mais graduee** : le validator refuse seulement les vrais dangers / impossibilites. Les bons compromis imparfaits remontent en `warning` ou `requires_confirmation`, puis le coach decide.
- **Pas de write libre dans un runtime tool LLM au premier slice** : le LLM peut proposer et valider un `PlanPatch`; le commit reste possede par `conversation_pipeline.py` / `PlanMutationService` pour garder transaction, events et permissions.
- **Dual-write surveillé** : pendant la migration, `plan_actions.py` mute encore `DayPlan` en parallèle. Tout nouveau tool de lecture doit lire la source canonique `ScheduledSession` via `CoachStateBundle` pour éviter divergence.
- **Determinisme en fond seulement** : pas de nouveau template conversationnel, pas de helper qui choisit a la place du coach et parle ensuite a l'utilisateur.

## Définition de done

Le refactor est fini quand le golden case (7 tours ci-dessus) produit toutes les réponses cibles, ET :
- Aucun token interne ne leak dans la sortie utilisateur
- Aucun compteur agrégé n'est passé au LLM en remplacement de données détaillées
- Le coach principal LLM est appelé sur 100% des tours conversationnels (sauf transactionnels purs)
- Le coach repond correctement aux questions simples de planning/reel/contraintes sans ouvrir un replan inutile
- Le coach garde le fil sur les continuations courtes (`oui`, `running`, `mercredi`) au lieu de les traiter comme des tours isoles
- Le coach peut produire un `PlanPatch` multi-operation valide, partiel explicitement scoped, ou une alternative expliquee
- Les validations training sortent `valid / warning / requires_confirmation / blocked`, pas seulement "allowed / blocked"
- Une recuperation protegee peut etre deplacee ou preservee via patch quand c'est coherent ; elle n'est bloquee dur que si la recuperation disparait ou si le risque est trop fort
- **Toute affirmation d'action ("je libere", "je deplace", "je mets") est garantie d'être suivie d'une mutation réelle auditée dans `plan_mutation_events`** ; sinon la phrase est bloquée
- La weekly review utilise les mêmes données que la conversation (cohérence)
- Une contrainte temporelle ("piscine fermée 2 semaines") est mémorisée et respectée 7 jours plus tard
- Les conversations issues des captures 15/17/19/20/21 avril passent en regression

## Suivi

- BUILD-ORDER.md → ce chantier devient la priorité courante, remplace "dogfood guidé" comme étape 0
- Une fois `PlanPatch` + `validate_plan_patch` + `apply_patch_for_user` stables, mettre à jour PLANNING.md
- Une fois tous les court-circuits supprimés, mettre à jour CONVERSATION.md
- Une fois les tools heartbeat alignés, mettre à jour SOUL.md
