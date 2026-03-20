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

- 5 onglets : Aujourd'hui, Semaine, Activités, Profil, Debug
- Navigation mobile bottom bar
- Passe mobile iPhone-proof : safe areas, touch targets, hiérarchie resserrée
- Actions rapides : Fait / Trop fatigué / Décaler
- Badges statut : fait ✓ / prévu / sauté / adapté
- Barre de charge semaine
- Contexte temps local visible dans le top bar
- Strava connect button + synchro
- Formulaire activité manuelle
- Textes en français avec accents corrects
- Déployée sur https://the deployed app/

### ✅ Phase 4 — Activités réelles

**Statut : TERMINÉ**

- Logging manuel (webapp + Telegram `/log`)
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

### Sprint A — Dogfooding & Strava (EN COURS)

**Objectif : utiliser FitMAS chaque jour pendant 2 semaines sans friction.**

| # | Tâche | Fichiers | Statut |
|---|-------|----------|--------|
| A1 | Configurer STRAVA_CLIENT_ID/SECRET sur Fly.io | Fly.io secrets | ✅ fait |
| A2 | Créer app Strava (callback → the deployed app) | strava.com/settings/api | ✅ fait (ID 214266) |
| A3 | Tester flow complet : /start → semaine → activité → revue | Tous | 🔄 en cours |
| A4 | Fixer bugs trouvés en dogfood | Variable | 🔄 en cours |
| A5 | Vérifier heartbeat en prod (briefing 7h30, rappel 18h) | heartbeat.py, telegram_bot.py | ⏳ observer demain matin |
| A6 | Callback Strava OAuth → redirect webapp (pas JSON) | api.py | ⏳ |
| A7 | Ajouter /help sur le bot Telegram | telegram_bot.py | ⏳ |
| A8 | Stocker plus de données Strava (avg_hr, avg_speed, calories) | strava.py, schema.py | ⏳ |

**Bugs connus :**
- ~~Bot perd le ConversationHandler state au restart~~ → fixé (PicklePersistence)
- ~~Fly.io auto-stop tuait le bot~~ → fixé (min_machines_running = 1)
- ~~Activités Strava anciennes (13 mois) matchées sur plan courant~~ → fixé (filtre 7 jours)
- ~~Thursday marqué "done" à tort par vieille activité~~ → fixé (plan régénéré)
- ~~Cooldown heartbeat bloquait après réponse normale~~ → fixé (flag `proactive`)
- ~~Rappel pré-séance 18h non planifié~~ → fixé
- Onboarding preview "1" tombe dans handle_message au lieu du step suivant → à investiguer

### Sprint B — Signaux et intelligence

**Objectif : le coach réagit au réel, pas juste au plan.**

| # | Tâche | Fichiers | Impact |
|---|-------|----------|--------|
| B1 | Créer `signals.py` : dériver signaux utiles | Nouveau fichier | Base intelligence |
| B2 | Signal "séance clé manquée" → message proactif | signals.py, heartbeat.py | Relance juste |
| B3 | Signal "3 jours sans activité" → check-in | signals.py, heartbeat.py | Détection décrochage |
| B4 | Signal "charge cumulée haute" → suggestion repos | signals.py, mutations.py | Protection |
| B5 | Post-activité : feedback contextuel après grosse séance | heartbeat.py, strava.py | Boucle utile |
| B6 | Ajustement next-day basé sur activité réelle | signals.py, heartbeat.py | Adaptation réelle |

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
| D1 | Tests unitaires : planner, mutations, activities | tests/ | Confiance |
| D2 | Tests d'intégration : flux message → mutation → réponse | tests/ | Régression |
| D3 | Test heartbeat : cooldowns, triggers, edge cases | tests/ | Fiabilité proactive |
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
Sprint A  ← MAINTENANT : dogfood, Strava config, bugs
Sprint B  ← Semaine prochaine : signaux, intelligence
Sprint C  ← Ensuite : planner V2, périodisation
Sprint D  ← En parallèle : tests, CI
Sprint E  ← Quand le produit est prouvé : scale, WhatsApp, natif
```

Le Sprint A est le plus important. Pas de nouvelles features tant que la boucle quotidienne n'est pas rodée.

---

## Risques principaux

### 1. Le coach sonne faux
- **Mitigation** : preview de voix + coach_do/coach_dont + exemples concrets
- **Test** : est-ce que le message ressemble à "ton" coach ?

### 2. Le heartbeat spam
- **Mitigation** : cooldowns déterministes, no-op fréquent, pas de message sans signal
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

### Signaux (Sprint B)
- [ ] Séance clé manquée → message de relance approprié
- [ ] 3 jours silence → check-in contextuel
- [ ] Grosse séance Strava → feedback coach
- [ ] Charge haute cumulée → suggestion repos automatique
