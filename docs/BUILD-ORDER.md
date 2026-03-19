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

## État actuel — 19 mars 2026

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
- Actions rapides : Fait / Trop fatigué / Décaler
- Badges statut : fait ✓ / prévu / sauté / adapté
- Barre de charge semaine
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
- Cooldown 4h entre messages proactifs
- Skip si échange récent (<2h)
- Voix du coach dans tous les messages (system prompt = coach soul)

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

### Sprint A — Robustesse et dogfooding (PRIORITAIRE)

**Objectif : utiliser FitMAS chaque jour pendant 2 semaines sans friction.**

| Tâche | Fichiers | Impact |
|-------|----------|--------|
| Configurer STRAVA_CLIENT_ID/SECRET sur Fly.io | Fly.io secrets | Strava end-to-end |
| Tester le flow complet : /start → semaine → activité → revue | Tous | Valider la boucle produit |
| Fixer les bugs trouvés en dogfood | Variable | Fiabilité |
| Vérifier que le heartbeat se déclenche bien en prod | heartbeat.py, telegram_bot.py | Proactivité |
| Callback Strava OAuth redirect → webapp plutôt que JSON | api.py | UX |
| Ajouter /help sur le bot Telegram | telegram_bot.py | Discoverability |

### Sprint B — Signaux et intelligence

**Objectif : le coach réagit au réel, pas juste au plan.**

| Tâche | Fichiers | Impact |
|-------|----------|--------|
| Créer `signals.py` : dériver signaux utiles | Nouveau fichier | Base intelligence |
| Signal "séance clé manquée" → message proactif | signals.py, heartbeat.py | Relance juste |
| Signal "3 jours sans activité" → check-in | signals.py, heartbeat.py | Détection décrochage |
| Signal "charge cumulée haute" → suggestion repos | signals.py, mutations.py | Protection |
| Post-activité : feedback contextuel après grosse séance | heartbeat.py, strava.py | Boucle utile |
| Ajustement next-day basé sur activité réelle | signals.py, heartbeat.py | Adaptation réelle |

### Sprint C — Enrichissement plan

**Objectif : le plan est plus intelligent et plus précis.**

| Tâche | Fichiers | Impact |
|-------|----------|--------|
| Planner V2 : progression charge semaine sur semaine | planner.py | Volume progressif |
| Lineage de plans : garder l'historique des semaines | schema.py, repository.py | Continuité |
| Périodisation légère : alternance charge/décharge | planner.py | Récupération |
| Nutrition focus plus pertinent par sport | planner.py, llm.py | Valeur ajoutée |
| Détail séance : échauffement, corps, retour au calme | llm.py | Précision |

### Sprint D — Qualité et tests

**Objectif : le code est fiable et maintenable.**

| Tâche | Fichiers | Impact |
|-------|----------|--------|
| Tests unitaires : planner, mutations, activities | tests/ | Confiance |
| Tests d'intégration : flux message → mutation → réponse | tests/ | Régression |
| Test heartbeat : cooldowns, triggers, edge cases | tests/ | Fiabilité proactive |
| CI/CD : tests automatiques avant deploy | .github/workflows/ | Qualité continue |
| Decision log : tracer chaque décision LLM | Nouveau module | Debugging |

### Sprint E — Polish et scale

**Objectif : prêt pour les premiers beta testers.**

| Tâche | Fichiers | Impact |
|-------|----------|--------|
| Webhook Strava (vs polling) | strava.py, api.py | Réactivité |
| WhatsApp migration (si produit validé) | Nouveau module | Canal principal |
| Multi-user : auth simple, isolation données | schema.py, api.py | Scale |
| App native iOS (si webapp validée) | Nouveau projet | Expérience premium |
| Mémoire sémantique (vector DB, si masse de données) | Nouveau module | Intelligence long-terme |

---

## Ordre d'exécution recommandé

```
Sprint A  ← MAINTENANT : dogfood, bugs, Strava end-to-end
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

---

## Vérification concrète par phase

### Dogfood (Sprint A)
- [ ] `/start` sur Telegram → profil + plan générés
- [ ] Webapp affiche le plan correct
- [ ] Briefing matin reçu sur Telegram à 7h30
- [ ] "Fait" dans l'app → jour marqué done
- [ ] Activité Strava importée → jour matché
- [ ] Revue dimanche → nouveau plan
- [ ] Pas de message proactif quand on vient de parler au coach

### Signaux (Sprint B)
- [ ] Séance clé manquée → message de relance approprié
- [ ] 3 jours silence → check-in contextuel
- [ ] Grosse séance Strava → feedback coach
- [ ] Charge haute cumulée → suggestion repos automatique
