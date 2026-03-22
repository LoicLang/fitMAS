---
summary: état actuel de chaque phase, plan de priorités et prochaines étapes
read_when:
  - commencer un chantier
  - donner du contexte à un agent de code
  - vérifier l'avancement
  - recadrer les priorités produit
---

# FitMAS — Build Order

## Phrase guide

**Un premier coach que Loïc reconnaît, comprend, et a envie de rouvrir demain.**

---

## État actuel — 20 mars 2026

### ✅ Phase 1 — Onboarding + création du coach

**Statut : TERMINÉ**

- `/start` sur Telegram → flow conversationnel complet
- Création du coach : nom, style, relation, do/dont, âme
- Preview de voix avant validation
- Récap + génération plan
- Endpoint `POST /api/v0/onboard` + `POST /api/v0/onboard/preview`
- Seed intelligent si pas d'utilisateur (profil multisport complet Loïc)

### ✅ Phase 2 — Planner multisport déterministe

**Statut : TERMINÉ**

- `planner.py` : squelette hebdo déterministe
- Règles : max 1 dur/jour, pas 2 durs d'affilée, repos, respect contraintes
- Alternance cross-sport, charge lisible
- LLM formulation : intention, summary, notes coach
- Régénération via `/newweek` ou revue hebdo

### ✅ Phase 3 — App webapp

**Statut : TERMINÉ**

- 5 onglets : Aujourd'hui, Calendrier, Activités, Profil, Debug
- Navigation mobile bottom bar
- Passe mobile iPhone-proof : safe areas, touch targets, hiérarchie resserrée
- Actions rapides : Fait / Trop fatigué / Décaler
- Badges statut : fait ✓ / prévu / sauté / adapté
- Barre de charge semaine
- Calendrier vivant : passé récent, aujourd'hui, à venir
- Contexte temps local visible dans le top bar
- Strava connect button + synchro
- Formulaire activité manuelle
- Textes en français avec accents corrects
- Déployée sur https://the deployed app/

### ✅ Phase 4 — Activités réelles

**Statut : TERMINÉ**

- Logging manuel (webapp)
- Strava OAuth + import + synchro auto (2h)
- Matching activité → jour plan (heuristique sport+jour+durée)
- Marquage automatique "done"
- `POST /api/v0/activities/manual`, `GET /api/v0/activities`
- `POST /api/v0/strava/sync`, Strava status/auth/callback

### ✅ Phase 5 — Heartbeat proactif

**Statut : TERMINÉ (base)**

- Briefing matin 7h30 (contexte veille + séance du jour)
- Rappel pré-séance 18h (séances clé seulement)
- Revue dimanche 20h (bilan + régénération)
- Cooldown 4h entre messages proactifs seulement (`CoachMessage.proactive`)
- Skip si échange récent (<2h)
- Voix du coach dans tous les messages (system prompt = coach soul)
- Debug endpoint live : `POST /api/v0/debug/heartbeat/{kind}`
- Debug endpoint protégé : désactivé par défaut sur Fly / prod, activable explicitement

### ✅ Phase 6 — Mémoire utile

**Statut : TERMINÉ (base)**

- UserFact : category, key, value, source, confidence, confirmed
- Extraction LLM après chaque échange
- Upsert intelligent (merge, pas overwrite)
- Sélection pour prompt (12 facts max, tri par confiance)
- Facts onboarding pré-remplis
- Onglet Debug pour visualiser

### ✅ Phase 7 — Revue hebdomadaire

**Statut : TERMINÉ**

- Bilan avec comptage fait/prévu/sauté
- LLM génère le récap avec voix coach
- Régénération automatique du plan suivant
- Message Telegram + persist en DB

---

## Ce qui reste — Plan de priorités

### ✅ Sprint A — Dogfooding & Strava

**Objectif : utiliser FitMAS chaque jour pendant 2 semaines sans friction.**

| # | Tâche | Fichiers | Statut |
|---|-------|----------|--------|
| A1 | Configurer STRAVA_CLIENT_ID/SECRET sur Fly.io | Fly.io secrets | ✅ fait |
| A2 | Créer app Strava (callback → the deployed app) | strava.com/settings/api | ✅ fait (ID 214266) |
| A3 | Tester flow complet : /start → semaine → activité → revue | Tous | 🔄 en cours |
| A4 | Fixer bugs trouvés en dogfood | Variable | 🔄 en cours |
| A5 | Vérifier heartbeat en prod (briefing 7h30, rappel 18h, signal 14h) | heartbeat.py, telegram_scheduler.py | ⏳ observer demain |
| A6 | Callback Strava OAuth → redirect webapp (pas JSON) | api.py | ✅ fait |
| A7 | Ajouter /help sur le bot Telegram | telegram_commands.py | ✅ fait |
| A8 | Stocker plus de données Strava (avg_hr, avg_speed, calories) | strava.py, schema.py | ✅ fait |

**Bugs connus :**
- ~~Bot perd le ConversationHandler state au restart~~ → fixé (PicklePersistence)
- ~~Fly.io auto-stop tuait le bot~~ → fixé (min_machines_running = 1)
- ~~Activités Strava anciennes (13 mois) matchées sur plan courant~~ → fixé (filtre 7 jours)
- ~~Thursday marqué "done" à tort par vieille activité~~ → fixé (plan régénéré)
- ~~Cooldown heartbeat bloquait après réponse normale~~ → fixé (flag `proactive`)
- ~~Rappel pré-séance 18h non planifié~~ → fixé
- Vérifier que la preview onboarding reste stable après plusieurs restarts bot

### ✅ Sprint B — Signaux et intelligence

**Objectif : le coach réagit au réel, pas juste au plan.**

| # | Tâche | Fichiers | Statut |
|---|-------|----------|--------|
| B1 | Créer `signals.py` : dériver signaux utiles | signals.py | ✅ fait |
| B2 | Signal "séance clé manquée" → message proactif | signals.py, heartbeat.py | ✅ fait |
| B3 | Signal "3 jours sans activité" → check-in | signals.py, heartbeat.py | ✅ fait |
| B4 | Signal "charge cumulée haute" → suggestion repos | signals.py, heartbeat.py | ✅ fait |
| B5 | Post-activité : feedback contextuel après grosse séance | signals.py, heartbeat.py | ✅ fait |
| B6 | Signal check cron (14h) + après Strava sync | telegram_scheduler.py | ✅ fait |

**Architecture signaux :**
- `signals.py` : 5 détecteurs (missed_key, silence_3d, high_load, big_session, streak)
- `heartbeat.signal_check()` : évalue les signaux, génère un message LLM si actionable
- Intégré dans : morning briefing (enrichi), cron 14h, post-Strava sync
- Debug : `GET /api/v0/signals` + `POST /api/v0/debug/heartbeat/signal_check`

### Sprint B+ — Emprunts OpenClaw (EN COURS)

**Objectif : rendre le coach plus intelligent dans ses silences et plus vivant dans sa personnalité.**

Inspiré de [OpenClaw](https://github.com/openclaw/openclaw) — deux patterns clés.

| # | Tâche | Fichiers | Statut |
|---|-------|----------|--------|
| B+1 | Pattern NO_SEND : LLM peut décider de ne pas envoyer | heartbeat.py | ✅ fait |
| B+2 | Soul mutation : coach affine sa voix au fil des échanges | llm.py, schema.py, api.py | ⏳ |
| B+3 | Soul version tracking (historique des évolutions) | schema.py, repository.py | ⏳ |
| B+4 | Prompt "soul refinement" après échanges marquants | llm.py | ⏳ |

**Pattern NO_SEND (implémenté) :**
- Chaque prompt heartbeat inclut : "Si tu estimes qu'il n'y a rien d'utile, reponds NO_SEND"
- `_llm_generate()` détecte NO_SEND (exact, avec markup, ou avec ack court <100 chars)
- NO_SEND + contenu substantiel → le token est strippé, le contenu est envoyé
- Weekly review = `allow_no_send=False` (toujours un bilan)

**Soul mutation (à faire) :**
- Après N échanges, le LLM peut proposer un affinement de `coach_soul`
- L'utilisateur valide ou refuse via Telegram
- Historique des versions de soul tracé
- Inspiré du SOUL.md mutable d'OpenClaw, mais contrôlé par l'utilisateur

### Sprint C — Enrichissement plan

**Objectif : le plan est plus intelligent et plus précis.**

| # | Tâche | Fichiers | Impact |
|---|-------|----------|--------|
| C1 | Planner V2 : progression charge semaine sur semaine | planner.py | Volume progressif |
| C2 | Lineage de plans : garder l'historique des semaines | schema.py, repository.py | Continuité |
| C3 | Périodisation légère : alternance charge/décharge | planner.py | Récupération |
| C4 | Nutrition focus plus pertinent par sport | planner.py, llm.py | Valeur ajoutée |
| C5 | Détail séance : échauffement, corps, retour au calme | llm.py | Précision |

### Sprint D — Qualité et tests

**Objectif : le code est fiable et maintenable.**

| # | Tâche | Fichiers | Impact |
|---|-------|----------|--------|
| D1 | Tests unitaires : planner, mutations, activities, signals | tests/ | Confiance |
| D2 | Tests d'intégration : flux message → mutation → réponse | tests/ | Régression |
| D3 | Test heartbeat : cooldowns, NO_SEND, triggers | tests/ | Fiabilité proactive |
| D4 | CI/CD : tests automatiques avant deploy | .github/workflows/ | Qualité continue |
| D5 | Decision log : tracer chaque décision LLM | Nouveau module | Debugging |

### Sprint E — Polish et scale

**Objectif : prêt pour les premiers beta testers.**

| # | Tâche | Fichiers | Impact |
|---|-------|----------|--------|
| E1 | Webhook Strava (vs polling) | strava.py, api.py | Réactivité |
| E2 | WhatsApp migration (si produit validé) | Nouveau module | Canal principal |
| E3 | Multi-user : auth simple, isolation données | schema.py, api.py | Scale |
| E4 | App native iOS (si webapp validée) | Nouveau projet | Expérience premium |
| E5 | Mémoire sémantique (vector DB, si masse de données) | Nouveau module | Intelligence long-terme |

---

## Ordre d'exécution recommandé

```
Sprint A   ✅ FAIT : dogfood, Strava config, bugs, /help, données enrichies
Sprint B   ✅ FAIT : signaux, intelligence proactive (5 détecteurs)
Sprint B+  🔄 EN COURS : NO_SEND ✅, soul mutation ⏳
                → 2 semaines de dogfood pour valider signaux + NO_SEND en conditions réelles
Sprint C   ← APRÈS DOGFOOD : planner V2, périodisation, lineage
Sprint D   ← En parallèle : tests, CI (commencer pendant dogfood)
Sprint E   ← Quand le produit est prouvé : scale, WhatsApp, natif
```

**Séquence immédiate :**
1. Deploy Sprint A+B+B+(NO_SEND) sur Fly.io
2. Dogfood 2 semaines : utiliser FitMAS chaque jour, observer les signaux/NO_SEND
3. Implémenter soul mutation (B+2-4) quand le coach aura assez d'historique
4. Sprint C une fois que la boucle quotidienne est rodée

---

## Risques principaux

### 1. Le coach sonne faux
- **Mitigation** : preview de voix + coach_do/coach_dont + exemples concrets + soul mutation
- **Test** : est-ce que le message ressemble à "ton" coach ?

### 2. Le heartbeat spam
- **Mitigation** : cooldowns déterministes + NO_SEND LLM + pas de message sans signal
- **Test** : jamais plus de 2-3 messages proactifs par jour

### 3. L'escalade disparaît du système
- **Mitigation** : logging manuel first-class, matching même sans Strava
- **Test** : une séance d'escalade loggée manuellement se reflète dans le plan

### 4. La mémoire hallucine
- **Mitigation** : facts simples, confidence, confirmation si sensible
- **Test** : les facts en DB correspondent à des faits réels

### 5. Le plan devient rigide
- **Mitigation** : mutations souples, jours flexibles, no-op acceptable
- **Test** : "décale ma séance" fonctionne proprement

### 6. Le bot Telegram perd l'état
- **Mitigation** : PicklePersistence, retry sur ConnectError, min_machines_running=1
- **Test** : un /start complet survit à un restart de la machine

---

## Vérification concrète par phase

### Dogfood (Sprint A)
- [x] `/start` sur Telegram → profil + plan générés
- [x] Onboarding complet (coach soul, sports, contraintes sauvés)
- [ ] Webapp affiche le plan correct
- [ ] Briefing matin reçu sur Telegram à 7h30
- [ ] "Fait" dans l'app → jour marqué done
- [x] Strava connecté, 20 activités importées (historique)
- [ ] Activité Strava récente → jour matché correctement
- [ ] Revue dimanche → nouveau plan
- [ ] Pas de message proactif quand on vient de parler au coach

### Signaux + NO_SEND (Sprint B/B+)
- [ ] Séance clé manquée → message de relance approprié
- [ ] 3 jours silence → check-in contextuel
- [ ] Grosse séance Strava → feedback coach
- [ ] Charge haute cumulée → suggestion repos automatique
- [ ] NO_SEND activé au moins 1x sur un heartbeat sans rien à dire
- [ ] Morning briefing jour de repos → NO_SEND (le coach se tait)
