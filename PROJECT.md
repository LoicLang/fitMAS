# FitMAS

Coach IA multisport proactif qui ajuste ton entraînement selon ta vraie vie.

## Statut — 10 mai 2026

**Déployé et fonctionnel sur https://the deployed app/**

Ce qui est dans `main` et doit rester la reference de lecture :
- Onboarding Telegram conversationnel complet (/start → profil + coach + plan)
- Planner hebdomadaire multisport déterministe (running, cycling, swimming, climbing, strength)
- Boucle message → LLM → tools/read/candidates → validation → mutation/pending/block → composer final
- Webapp mobile-first React/Vite + Tailwind v4
- App React Router recentrée sur 3 tabs primaires : `Aperçu`, `Calendrier`, `Évolution`
- Détail séance en page dédiée : `/workout/:sessionId`
- Read models backend dédiés aux écrans app : `overview`, `calendar`, `evolution`, `session detail`
- Activités manuelles + Strava OAuth + import + synchro automatique
- Proactive coach loop avec cooldowns : le coach peut se reveiller, relire la verite recente, choisir `send/no_send`, puis envoyer un message utile sans horaire fixe obligatoire
- Mémoire V2 base : `profile / working / patterns`
- Runtime tools multi-tool borné : read-only / candidate / validation-only, aucun write DB libre
- Conversation tool loop 3A : multi-round read/validation tools, `validate_plan_patch`, replay DeepSeek tool-use, retry JSON court avant repair lourd
- Runtime conversationnel branché sur `PromptContract`, prompt layers filtrés par capability et traces de contexte
- `CoachDecision` + `PlanPatch` branchés sur la conversation : validation serveur, confirmation pending, commit via `PlanMutationService`
- `ScheduledSession` est la vérité runtime pour mutations/signals/activity matching ; `WeeklyPlan`/`DayPlan` restent template/compat
- Idempotence Telegram/API sur `client_message_key` : un timeout ou retry Telegram ne relance plus une mutation déjà traitée
- Doctrine conversation renforcee : zero determinisme sur texte utilisateur libre ; le LLM est le seul detecteur d'intention
- Routes terminales/read-only plus courtes : `close_turn`, `casual_chat`, `plan_lookup`, `execution_report`, `health_signal`, `general_answer`
- `general_answer` peut lire `get_coach_lens` : contexte coach compact sans charger tout le planning brut
- Adaptation candidates Phase A : `candidate_ref` backend pour `move`, `swap`, `lighten`, `replace`, evaluation moteur, reviewer LLM borne qui choisit seulement un `candidate_id`
- Phase 1 voix conversation shippée 30 avril : règles "Voix coach" + few-shots BONS/MAUVAIS sur `fitmas_message`, détecteur receipt-style log-only
- Phase 2 `pending_resolution` typed + `memory_actions` + `execution_actions` shippée 1 mai : confirmations résolues structurellement, plus de re-décision sauvage
- Anciens chemins `UserIndication`, replan legacy et tool routing deterministe supprimes du repo
- DeepSeek principal avec fallback Claude possible sur sorties structurées fragiles
- `suggest_replan_candidates` est le helper canonique de candidates replan ; `propose_replan` reste alias compat
- Workflow `replan_after_constraint` formalisé dans le prompt : tools atomiques → candidate optionnelle → `PlanPatch | no_change | requires_confirmation`
- Revue hebdomadaire + régénération automatique du plan le lundi matin
- Bot Telegram avec commandes (/start, /plan, /today, /newweek, /sync, /log)

La vérité "état réel + suite" vit dans `docs/BUILD-ORDER.md`.

Chantiers Phase A/A+ clos à ce jour :
- ✅ **Chantier 0** — TTL `_recent_proactive_context` (heartbeat) — shippé 2 mai 2026 — fix hallucination + 6 tests
- ✅ **Chantier 1** — Voix coach unifiée `coach_voice.py` partagée tous pipelines (conversation + briefing + reminder + review + signal) — shippé 3 mai 2026 — 5 commits atomiques (étapes A-E), 36 tests nouveaux
- ✅ **Chantier 1bis** — claim_guard via LLM repair (plus de canned "Je n'ai applique aucun changement...") — shippé 3 mai 2026
- ✅ **Chantier 1ter** — Capture indirecte de constraints dans le prompt conversation (piscine vidange, voyage, douleur ongoing) — shippé 3 mai 2026
- ✅ **Cleanup DB prod** — 395 rows obsolètes purgées, mémoire repart propre — 3 mai 2026
- ✅ **Chantier 2** — Truth source unifié runtime — `ScheduledSession` seul runtime pour mutations/signals/activity matching — shippé + déployé 4 mai 2026
- ✅ **Chantier 3A** — Conversation tool loop partiel — multi-round read/validation tools + `validate_plan_patch`, `PlanPatch` conservé — shippé + déployé 4 mai 2026
- ✅ **Correctif Telegram** — idempotence `client_message_key` + retry réponse perdue après commit — shippé + déployé 4 mai 2026
- ✅ **Heartbeat fake-action guard** — LLM judge systématique `ALLOW/BLOCK` sur chaque sortie heartbeat read-only, sans regex fake-action — 4 mai 2026
- ✅ **Chantier 4** — Observabilité proactive coach loop — `dump=true` expose contexte, prompt, decision `send/no_send`, judge, message final — 4 mai 2026
- ✅ **P1 post-event reply verifier** — verifier/réparer une réponse finale post-mutation contre les events réellement commités avant envoi
- ✅ **P1 PlanPatch confirmation parity** — un `replace_session` qui change le sport d’une séance clé repasse par confirmation, comme la route `MutationDecision`
- ✅ **Chantier 3B-A** — Heartbeat read-tools read-only : plan, activités, réalité récente, charge, contraintes et mémoire avant `send/no_send`
- ✅ **Chantier 3B-B** — Heartbeat peut proposer un `PlanPatch` proactif avec confirmation Telegram pending, sans commit autonome
- ✅ **P1 execution receipt repair** — si le LLM reconnait “pas fait hier” sans `execution_actions`, repair sémantique sur artefact LLM ; cible follow-up structurée si dispo, sinon `target_ref` borné résolu par le writer
- ✅ **P1-quater** — dogfood API fallout : verifier `execution_actions`, date/day dans facts post-event, confirmation cible planning ambiguë, repair mémoire disponibilité — déployé 4 mai 2026
- ✅ **Phase A+ core** — Sport Quality / Week Coherence gate avant nouveaux action-tools : simulation, reviewer LLM/fallback typé, gate runtime dans `apply_patch_for_user`, smoke API réel `scripts/smoke-a-plus-api` — `docs/SPORT-QUALITY-REVIEW.md`
- ✅ **Chantier 3B-C** — Action-tools natifs bornés : `draft_move_session`, `draft_swap_sessions`, `draft_replace_session`, `draft_lighten_day`, `draft_create_session`, tous candidates PlanPatch sans write, seulement derrière la gate A+ core — `docs/RUNTIME-TOOLS.md`
- ✅ **A+4** — tool `validate_week_coherence` validation-only conversation/planning/heartbeat + pending heartbeat seulement après review sportive confirmable — `docs/SPORT-QUALITY-REVIEW.md`
- ✅ **A+5** — semaine générée/régénérée relue avant `replace_plan` / création des `ScheduledSession`, fallback conservative si policy review non `valid`, fallback persistable sauf `blocked` — `docs/SPORT-QUALITY-REVIEW.md`
- ✅ **P1-quinquies** — lane terminale conversation `close_turn` : clôtures sociales sans tools, sans relance de question ouverte, réponse finale via `final_reply.py`
- ✅ **P1-sexies** — composer final `no_change` : tours sans mutation planning reformulés via `final_reply.py`, avec faits mémoire/exécution appliqués
- ✅ **P1-septies** — composer final `plan_lookup` : lectures factuelles reformulées via `final_reply.py` avec guard anti-drift chiffres/jours/zones/statuts
- ✅ **P1-nonies** — grounding final speech + heartbeat truth : refs temporelles typées, grounding partagé, verifier LLM sémantique, idempotence durable — `docs/BUILD-ORDER.md`
- ✅ **P1-octies** — prompt/context diet : `PromptContract`, layers filtrés, schemas par capability, `get_coach_lens`, snapshots et traces `decide_none`
- ✅ **A+6** — adaptation candidate pipeline : refs backend, evaluator, policy, pending choice, reviewer LLM borne `candidate_id` only — `docs/ADAPTATION-CANDIDATE-PIPELINE.md`

Cap produit actuel :
- Telegram = coach conversationnel
- App = cockpit performance
- priorité immédiate : dogfood réel sur Telegram + observation des `decide_none` restants + correction ciblée si le problème existe encore
- Phase B long terme : progression/prescription structurée, documentée mais pas ouverte sans demande explicite

## Stack

| Composant | Choix |
|-----------|-------|
| Backend | Python 3.13 + FastAPI + SQLAlchemy 2.0 + SQLite |
| Front | React 18 + Vite + React Router + Tailwind CSS v4 + motion + Embla + Recharts |
| Messagerie | Telegram bot (python-telegram-bot 21) |
| IA | DeepSeek V4 — `deepseek-v4-flash` quotidien, `deepseek-v4-pro` pour plans/coach |
| Cron | APScheduler (briefing 7h30, synchro Strava 2h, revue dimanche 20h) |
| Déploiement | Fly.io (CDG), Docker, volume SQLite persistant |

## Ordre de lecture

1. `AGENTS.md` — regles de travail
2. `PROJECT.md` — ce fichier
3. `docs/README.md` — carte des docs
4. `docs/BUILD-ORDER.md` — source de verite sur l'etat reel et la suite
5. `docs/PROMPT-CONTEXT-REFACTOR.md` — contrats LLM, contexte par capability, état prompt diet
6. `docs/ADAPTATION-CANDIDATE-PIPELINE.md` — adaptation par candidats bornés + reviewer `candidate_id`
7. `docs/SPORT-QUALITY-REVIEW.md` — Phase A+ reviewer sportif, coherence semaine, progression par stimulus
8. `docs/LLM-FIRST-CONVERSATION.md` — doctrine zero determinisme sur texte user + plan de migration
9. `docs/SYSTEM-MAP.md` — carte rapide des flux et frontières
10. `docs/ARCHITECTURE.md` — stack, principes de harness, modele de donnees, flux
11. `docs/PRODUCT.md` — vision, scope, parcours utilisateur
12. `docs/RUNBOOK.md` — commandes, smokes, deploy

## Structure du repo

```
AGENTS.md            — regles agentiques
PROJECT.md           — point d'entree
docs/                — docs actifs + README (anciens docs en docs/archive/ si besoin)
backend/src/fitmas/  — API + bot + domaines partages
backend/src/fitmas/tools/ — tools runtime read-only + contrats ; pas de routing deterministe depuis le texte user
backend/src/fitmas/skills/heartbeat/ — cluster heartbeat (evaluation, roles, generation)
frontend/            — webapp React/Vite/Tailwind (3 tabs + detail seance)
scripts/             — dev, dev-web, start-prod, docs:list
Dockerfile           — image Docker multi-stage
fly.toml             — config Fly.io
```

## Dev local

```bash
rm -rf .venv && python3 -m venv .venv && .venv/bin/python -m pip install -e .
./scripts/dev
./scripts/dev-web
```

Local API via `./scripts/dev` démarre sur `127.0.0.1:8033` par défaut pour éviter les faux conflits avec un autre service en `:8000`.
Override possible : `PORT=8040 ./scripts/dev`
Frontend Vite via `./scripts/dev-web` sur `127.0.0.1:5173`, avec proxy API vers `:8033`.

DB : `fitmas.db` à la racine. Supprimer pour re-seeder.
Variables : `DEEPSEEK_API_KEY`, `TELEGRAM_BOT_TOKEN`, `STRAVA_CLIENT_ID`, `STRAVA_CLIENT_SECRET`

Stabilisation LLM :
- le chemin DeepSeek OpenAI-compatible structured output est le defaut quand `DEEPSEEK_API_KEY` existe
- `FITMAS_USE_DEEPSEEK_OPENAI_STRUCTURED=0` sert de kill switch temporaire
- `ANTHROPIC_API_KEY` sert de fallback schema Claude quand DeepSeek retourne un JSON invalide metier
`ANTHROPIC_API_KEY` reste un fallback temporaire pendant la migration provider.

## Principes

- LLM-first pour l'intention floue ; déterminisme pour vérité, validation, permissions, commit et audit
- Zero determinisme sur texte utilisateur libre : pas de regex, keyword, classifieur, parsing oui/non, extraction sante/dispo/execution/preference ou routing de tools hors LLM
- Le LLM produit des actions structurees ; le backend valide, resout, ecrit et audite
- Pas de reply conversationnelle finale depuis un helper déterministe, sauf outage minimal ou résumé d'event réel
- Tools atomiques et bornés avant gros tool magique
- `PlanPatch` est le langage d'action ; le write reste orchestré par `PlanMutationService`
- Mono-agent propre avant toute tentation multi-agent
- Telegram pour valider la proactivité, WhatsApp quand prouvé
- Telegram = relation coach, app = tableau de bord performance
- Build perso d'abord : single-user, multisport, usage quotidien réel
- Hotspots splittés par domaine : `api_*`, `telegram_*`, modules partagés transverses
- Les écrans app lisent des payloads dédiés backend, pas des objets bruts réassemblés côté front
