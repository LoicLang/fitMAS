---
summary: refonte de la pipeline coach pour libérer le LLM des court-circuits déterministes, lui donner les bons tools de lecture, un skill de planification validée et une vraie posture de coach
read_when:
  - lancer le refactor coach autonomy
  - corriger une hallucination du coach (plan futur, activités passées)
  - retirer un court-circuit déterministe dans api_messages
  - ajouter un tool de lecture pour le coach LLM
  - construire un skill de replan validé
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

## Vision cible

```
                    ┌─────────────────────┐
                    │  COACH LLM (Sonnet) │
                    │  prompt minimal +   │
                    │  vraie autonomie    │
                    └──────────┬──────────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
        TOOLS LECTURE    SKILLS DÉCISION   POSTURE
        ─────────────    ────────────────  ────────
        get_plan_window  propose_replan    "tu DÉCIDES"
        get_activities   (LLM-génère       pas
        get_constraints   + validator)     "tu DEMANDES"
        get_load_context
```

**Pattern** : LLM-orchestrator + symbolic validator (état de l'art neuro-symbolic 2025-2026).
- LLM **génère** le plan candidat (créativité, langage, négociation)
- Validator déterministe **valide** (charge progressive, récupération, périodisation)
- Si KO → diff structuré → LLM corrige → re-soumet (CEGIS loop, max 3 itérations)
- Si OK → coach présente le plan validé comme SA décision

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
- ⏳ Chantier 4 (mémoire des contraintes temporelles avec `valid_until`) — `expires_at` existe déjà sur `UserFact`/`WorkingMemoryEntry` et est respecté par `get_user_constraints` ; reste à connecter le LLM extracteur d'indications pour qu'il pose `expires_at` cohérent avec la durée de la contrainte

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

### Chantier 4 — Mémoire des contraintes temporelles (2h)
- Indication de type "indispo période X-Y" → écrite en `working_memory_entries` avec `valid_until`
- `get_user_constraints()` filtre uniquement les contraintes encore actives à la date courante
- Test : dans 7 jours le coach se rappelle de la piscine fermée et ne propose pas de natation

### Chantier 5 — Skill `propose_replan` avec validator (1-2j)
- Extraire un module `validator.py` testable seul :
  - `validate_week(plan, context) → ValidationResult{ok, violations[]}`
  - règles dures : charge progressive ≤ +10%/sem, 48h post-quality, balance des sports, périodisation respectée
- Skill agent `propose_replan(constraints, scope) → ValidatedPlan` :
  - LLM rédige plan candidat
  - Submit au validator
  - Si violations → diff structuré → LLM corrige → boucle (max 3 itérations)
  - Si OK → retourne plan structuré
- Exposé au coach LLM comme tool `propose_replan`
- Test : sur "piscine fermée 2 semaines" le coach reçoit UN plan validé et le présente comme sa décision

### Chantier 6 — Audit pipeline LLM préliminaires (différé)
- Aujourd'hui : 3 LLM en cascade (turn_planner + indication_parser + decide)
- Une fois decide() libéré et outillé, les 2 préliminaires sont-ils encore nécessaires ?
- Probablement turn_planner reste utile (routing + tools selection), indication_parser peut être absorbé
- À évaluer en post-mortem du refactor

## Guardrails pendant le refactor

- **Confirmations writes maintenues** : tout `apply_plan` ou `set_completion_status` initié par le coach demande encore une confirmation oui/non Telegram. Filet de sécurité pendant la montée en autonomie.
- **Latence acceptée** : un tour peut passer de 3s à 8-12s. Le gain en autonomie/fiabilité justifie le coût.
- **Validator strict** : même si le coach LLM rédige un plan agressif sous pression user, le validator déterministe refuse. Le coach reçoit le diff et propose autre chose.
- **Dual-write surveillé** : pendant la migration, `plan_actions.py` mute encore `DayPlan` en parallèle. Tout nouveau tool de lecture doit lire la source canonique `ScheduledSession` via `CoachStateBundle` pour éviter divergence.

## Définition de done

Le refactor est fini quand le golden case (7 tours ci-dessus) produit toutes les réponses cibles, ET :
- Aucun token interne ne leak dans la sortie utilisateur
- Aucun compteur agrégé n'est passé au LLM en remplacement de données détaillées
- Le coach principal LLM est appelé sur 100% des tours conversationnels (sauf transactionnels purs)
- Le coach présente UN plan validé argumenté au lieu de demander au user de choisir
- **Toute affirmation d'action ("je libere", "je deplace", "je mets") est garantie d'être suivie d'une mutation réelle auditée dans `plan_mutation_events`** ; sinon la phrase est bloquée
- La weekly review utilise les mêmes données que la conversation (cohérence)
- Une contrainte temporelle ("piscine fermée 2 semaines") est mémorisée et respectée 7 jours plus tard

## Suivi

- BUILD-ORDER.md → ce chantier devient la priorité courante, remplace "dogfood guidé" comme étape 0
- Une fois `validator.py` + `propose_replan` stables, mettre à jour PLANNING.md
- Une fois tous les court-circuits supprimés, mettre à jour CONVERSATION.md
- Une fois les tools heartbeat alignés, mettre à jour SOUL.md
