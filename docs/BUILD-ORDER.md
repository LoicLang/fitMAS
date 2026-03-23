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

## État actuel — 22 mars 2026

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

- 6 onglets : Aujourd'hui, Calendrier, Performance, Activités, Profil, Debug
- Navigation mobile bottom bar
- Passe mobile iPhone-proof : safe areas, touch targets, hiérarchie resserrée
- Actions rapides : Fait / Trop fatigué / Décaler
- Badges statut : fait ✓ / prévu / sauté / adapté
- Barre de charge semaine
- Calendrier vivant : passé récent, aujourd'hui, à venir
- Onglet Performance initial : CTL / ATL / TSB, volume, complétion, records
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

## Principes de séquencement

- Telegram reste le canal coach : conversation naturelle, adaptation, proactivité
- L'app devient le cockpit performance : calendrier, charge, exécution, graphes
- On stabilise d'abord la vérité des données avant de sophistiquer l'UI ou le LLM
- Pas de multi-agent tant que le mono-agent n'est pas un vrai frein produit

## Priorité transversale — Conversation Grounding

Le chantier planner V2 continue, mais un sujet remonte avant son branchement complet :
- le coach Telegram doit mieux lire le reel execute
- le coach Telegram doit mieux resoudre `aujourd'hui`, `demain`, `hier`
- le coach Telegram doit mieux gerer une correction utilisateur immediate

Document de reference :
- `CONVERSATION-GROUNDING.md`

Objectif :
- eviter les messages factuellement faux
- ne plus confondre `seance prevue manquee` avec `aucune activite reelle`
- ne plus reutiliser une duree planifiee comme si c'etait la duree executee

Deja pose :
- `execution_context.py` pour resumer `prevu vs reel` sur aujourd'hui
- `temporal_resolver.py` pour ancrer `aujourd'hui / demain / hier`
- `activity_claims.py` pour lire les declarations d'activite recentes
- `conversation_context.py` pour assembler temps + execution + claims + memoire de conversation
- `conversation_context.py` filtre aussi maintenant quelques signaux utiles au chat
- `api_messages.py` branche maintenant execution + temps + claims dans le prompt coach
- les claims activite du message courant sont maintenant persistés en `UserFact(category="execution")` avec TTL courte quand aucune vraie `Activity` n'existe encore
- `signals.py` et `heartbeat.py` tiennent mieux compte des activites reelles hors plan
- `signals.py` et `heartbeat.py` lisent aussi les activites declarees non loggees pour eviter les faux `rien fait`
- les corrections explicites (`non c'etait hier`) mettent a jour et archivent le claim execution precedent
- `UserFact` porte maintenant une vraie sémantique mémoire `urgency / ttl / affects / expires_at`
- le chat et le heartbeat privilegient maintenant le calendrier date / app comme source de verite planning, avec `WeeklyPlan` seulement en fallback transitoire

Socle runtime tools pose :
- `tool_contract.py`
- `tool_registry.py`
- `tool_runtime.py`
- `tool_metrics.py`
- `tool_routing.py`
- `conversation_prompting.py`
- registry V1 read-only avec metrics/logs structures
- `llm.py` peut maintenant faire 1 tool call max pour certaines questions de lecture via le chat
- les traces tools couvrent maintenant aussi `tools offerts mais non utilises`, `tool loop complete` et `fallback de tool loop`
- les tools offerts au chat sont maintenant routes de facon deterministe par type de requete au lieu d'envoyer tout le registry
- les contestations explicites du planning app (`ce n'est pas ce qui est dans l'app`) sont maintenant routees vers les tools planning au lieu de rester un message flou
- la reduction du `context dump` a commence pour les requetes de lecture outillees, avec policy de prompt deterministe
- les traces exposent aussi maintenant le volume de prompt (`prompt_char_count`, `history_messages_used`, `tool_count_offered`)

## Roadmap recommandée

### Sprint 1 — Telegram Fix + Fondation Charge

**Objectif : supprimer les irritants quotidiens et commencer à accumuler une donnée charge exploitable.**

| # | Tâche | Fichiers | Impact |
|---|-------|----------|--------|
| 1A1 | Supprimer le déclenchement direct `signal_check_cron()` après sync Strava | `telegram_scheduler.py` | Plus de risque de doublons immédiats |
| 1A2 | Ajouter un `asyncio.Lock` module-level sur les séquences draft → send → persist | `telegram_scheduler.py` | Sérialisation locale des envois Telegram |
| 1A3 | Ajouter un guard timestamp module-level en plus du check DB | `heartbeat.py` | Déduplication plus robuste en mono-process |
| 1B1 | Ajouter un jitter de ±15 min aux jobs au boot | `telegram_scheduler.py` | Messages moins robotisés |
| 1C1 | Passer `PROACTIVE_COOLDOWN_HOURS` de 4h à 6h | `heartbeat.py` | Moins de spam |
| 1C2 | Supprimer le cron `signal_check` de 14h | `telegram_scheduler.py` | Moins de bruit |
| 1C3 | Garder les signaux dans briefing matin + rappel pré-séance seulement | `heartbeat.py`, `signals.py` | Max 2 messages/jour, souvent 1 |
| 1D1 | Ajouter `Activity.tss` nullable | `schema.py`, `db.py` | Fondation CTL/ATL/TSB |
| 1D2 | Créer `training_load.py` avec `estimate_tss()` | `training_load.py` | Fonction pure réutilisable |
| 1D3 | Créer `compute_ctl_atl_tsb()` | `training_load.py` | Base dashboard + planner |
| 1D4 | Calculer et persister le TSS à l'import Strava et au log manuel | `strava.py`, `api_activities.py` | Donnée exploitable partout |

**Notes d'architecture :**
- Le verrou in-memory est acceptable tant que Fly tourne sur une seule machine
- Documenter explicitement que ce n'est pas une garantie multi-instance
- `training_load.py` doit rester 100% pur et réutilisable

### Sprint 1.5 — Calendrier Persistant

**Objectif : remplacer le modèle hebdo destructif par une vérité planning persistée et datée.**

**Statut : EN COURS**

Déjà posé :
- table `ScheduledSession`
- sync plan actif -> séances datées futures
- lien activité -> séance datée
- endpoint lecture `GET /api/v0/timeline`
- endpoint `Today` par séance datée
- CTA app déterministes : `done / skip / move`
- app branchée sur la timeline persistée pour le calendrier
- boucle coach enrichie avec timeline datée et mutations par `session_id`
- `swap_sessions` daté supporté aussi

Reste à finir :
- réduire encore les fallback `day key`
- lineage plus propre entre générations de plans

C'est la fondation manquante. Sans ça, le dashboard et la périodisation resteront bancals.

| # | Tâche | Fichiers | Impact |
|---|-------|----------|--------|
| 1.5A1 | Introduire `ScheduledSession` datée | `schema.py`, `models.py` | Vérité calendrier |
| 1.5A2 | Garder l'historique au lieu de `replace_plan()` destructif | `repository.py` | Continuité visible |
| 1.5A3 | Lier activité ↔ séance de façon stable | `activities.py`, `strava.py`, `repository.py` | Matching fiable |
| 1.5A4 | Exposer une timeline datée en lecture | `api_read.py` | Base de l'app cockpit |
| 1.5A5 | Adapter les mutations pour agir sur des dates réelles | `mutations.py`, nouveau router plan si utile | Déplacements fiables |
| 1.5A6 | Conserver la compatibilité UI/API tant que la migration n'est pas terminée | `api_read.py`, `repository.py` | Migration progressive |

**Règle produit :**
- une séance passée reste visible
- une séance future peut être ajustée sans effacer le reste
- la revue hebdo ne détruit jamais le passé

### Sprint 2 — Dashboard Performance

**Objectif : transformer la webapp en vrai tableau de bord d'entraînement inspiré Runna.**

**Statut : EN COURS**

Déjà posé :
- endpoints stats `training-load`, `volume`, `records`
- Chart.js via CDN
- onglet `Performance` dans la webapp
- graphes charge / volume / complétion
- cartes records simples par sport
- `Today` enrichi avec forme + repère récent du même sport
- premier split frontend lancé : `utils.js`, `charts.js`

Reste à faire :
- poursuivre le split du frontend single-file en modules
- renforcer calendrier semaine/mois et interactions

| # | Tâche | Fichiers | Impact |
|---|-------|----------|--------|
| 2A1 | Éclater `frontend/index.html` en shell + CSS + modules JS | `frontend/`, `api_static.py` | Maintenabilité UI |
| 2A2 | Garder vanilla JS, pas de bundler | `frontend/js/*.js` | Simplicité |
| 2B1 | Ajouter l'onglet `Performance` | `frontend/index.html` | Valeur perçue immédiate |
| 2B2 | Intégrer Chart.js via CDN | `frontend/index.html` | Graphes charge / volume / completion |
| 2B3 | Créer `GET /api/v0/stats/training-load` | `api_stats.py`, `training_load.py` | CTL / ATL / TSB |
| 2B4 | Créer `GET /api/v0/stats/volume` | `api_stats.py`, `performance_stats.py` | Volume multisport |
| 2B5 | Créer `GET /api/v0/stats/records` | `api_stats.py`, `performance_stats.py` | PRs |
| 2C1 | Enrichir `Today` avec activité comparable du même sport | `api_read.py`, `today.js` | Exécution guidée |
| 2C2 | Afficher la forme via `TSB` | `api_read.py`, `today.js` | Lecture fatigue/fraîcheur |
| 2D1 | Renforcer la vue calendrier semaine/mois | `calendar.js` | Vision claire du plan |
| 2D2 | Ajouter un endpoint move explicite | nouveau router plan, `mutations.py` | Interactions plus propres |
| 2E1 | Afficher le TSS estimé au niveau séance | `today.js`, `calendar.js`, planner | Cohérence charge |

**Règle produit :**
- pas de chat dans l'app
- l'app montre la performance, l'exécution et la lecture de charge
- Telegram garde la relation coach

### Sprint 3 — Périodisation

**Objectif : faire passer le planner de “squelette hebdo” à “moteur d'entraînement”.**

Le plan detaille de ce chantier vit maintenant dans `PLANNING-ENGINE-V2.md`.
Ce document remplace toute tentative de repartir de zero avec une architecture generique non alignee sur le repo.

**Statut : EN COURS (fondations domaine lancees)**

Deja pose :
- `planning_config.py` pour centraliser les seuils V2
- `athlete_profile.py` pour assembler un snapshot athlete depuis la DB actuelle
- `fitness_snapshot.py` pour produire un etat de charge exploitable par le futur decision engine
- `readiness.py` pour transformer charge + contraintes + facts en etat lisible
- `planning_decision.py` pour choisir explicitement le mode de semaine avant le planner
- tables SQL d'audit V2 pour `fitness_snapshots`, `readiness_snapshots`, `planning_decisions`
- helpers repository pour persister / relire les objets domaine V2
- `planning_state.py` comme pipeline partagee build + persist
- `session_templates.py` pour la librairie V1 multisport
- `plan_validator.py` pour les garde-fous structure / charge
- `planner.py` consomme maintenant `PlanningDecision` et produit des seances deterministes deja actionnables
- `api_onboarding.py` et `regenerate_week` passent maintenant par `planning_state.py`
- tests unitaires et integration pour les briques moteur V2 et le flow onboarding/regeneration

| # | Tâche | Fichiers | Impact |
|---|-------|----------|--------|
| 3A1 | Ajouter `TrainingCycle` et `Mesocycle` | `schema.py`, `models.py`, `repository.py` | Structure long terme |
| 3A2 | Étendre les plans/séances avec `target_tss`, `week_number`, `is_deload` | `schema.py`, `models.py` | Pilotage de charge |
| 3B1 | Créer `periodization.py` | `periodization.py` | Règles de cycle |
| 3B2 | Réécrire `build_week_plan()` avec type de semaine + TSS cible | `planner.py` | Planner V2 |
| 3B3 | Enrichir le prompt planner avec contexte de phase et charge | `llm.py` | Sorties plus crédibles |
| 3C1 | Créer `session_templates.py` | `session_templates.py` | Base de séances robuste |
| 3C2 | Couvrir running / cycling / swimming / climbing / strength | `session_templates.py` | Multisport réel |
| 3D1 | Créer `adaptation.py` | `adaptation.py`, `signals.py` | Lecture actual vs planned |
| 3D2 | Détecter fatigue / progression post-activité | `adaptation.py`, `strava.py` | Ajustement fin |
| 3E1 | Envoyer un message coach seulement pour les gros changements de plan | `heartbeat.py`, `telegram_scheduler.py` | Telegram sharp |

### Sprint 4 — Tests, Docs, Hardening

**Objectif : fiabiliser avant d'ajouter de la sophistication LLM.**

| # | Tâche | Fichiers | Impact |
|---|-------|----------|--------|
| 4A1 | Tests unitaires `training_load.py` | `tests/` | Confiance charge |
| 4A2 | Tests unitaires `periodization.py` | `tests/` | Confiance planner |
| 4A3 | Tests unitaires `session_templates.py` | `tests/` | Cohérence templates |
| 4A4 | Tests unitaires `adaptation.py` | `tests/` | Cohérence signaux |
| 4A5 | Tests heartbeat doublons / cooldown / fréquence | `tests/` | Fiabilité Telegram |
| 4B1 | Mettre à jour `ARCHITECTURE.md` | `docs/ARCHITECTURE.md` | Repo auto-explicatif |
| 4B2 | Mettre à jour `PRODUCT.md` | `docs/PRODUCT.md` | Contrat produit clair |
| 4B3 | Mettre à jour `BUILD-ORDER.md` | `docs/BUILD-ORDER.md` | Roadmap vivante |
| 4B4 | Ajouter CI minimale | `.github/workflows/` | Régression moins probable |

### Sprint 5 — Architecture Agents

**Objectif : introduire plusieurs agents seulement si les domaines sont déjà stables.**

Ce sprint est volontairement repoussé. Avant ça, la priorité est d'avoir :
- un calendrier persistant fiable
- un planner périodisé stable
- des messages Telegram bien calibrés

| # | Tâche | Fichiers | Impact |
|---|-------|----------|--------|
| 5A1 | Créer `agents/base.py` | `agents/base.py` | Abstraction commune |
| 5A2 | Créer `PlanningAgent` | `agents/planning.py` | Plans / périodisation |
| 5A3 | Créer `CoachingAgent` | `agents/coaching.py` | Messages coach |
| 5A4 | Créer `ExtractionAgent` | `agents/extraction.py` | Facts / mémoire |
| 5A5 | Créer `AnalysisAgent` | `agents/analysis.py` | Insights perf |
| 5B1 | Faire de `llm.py` un wrapper de délégation | `llm.py` | Compat backward |

**Décision tranchée :**
- pas de multi-agent visible tant que le mono-agent n'est pas un goulot prouvé

### Sprint 6 — Stretch

**Objectif : ajouter ce qui devient pertinent une fois le coeur prouvé.**

| # | Tâche | Fichiers | Impact |
|---|-------|----------|--------|
| 6A1 | Goal / race targeting | `schema.py`, `periodization.py`, `planner.py` | Préparation orientée objectif |
| 6A2 | Webhook Strava | `strava.py`, `api.py` | Réactivité |
| 6A3 | WhatsApp | nouveau module | Canal éventuel |
| 6A4 | Multi-user | `schema.py`, `api.py` | Scale |
| 6A5 | Native iOS | nouveau projet | Premium UX |

---

## Ordre d'exécution recommandé

```text
Sprint 1    Telegram fix + TSS
Sprint 1.5  Calendrier persistant
Sprint 2    Dashboard performance
Sprint 3    Périodisation + adaptation
Sprint 4    Tests + docs + hardening
Sprint 5    Agents (seulement si besoin réel)
Sprint 6    Stretch
```

**Pourquoi cet ordre :**
- Sprint 1 règle la douleur quotidienne
- Sprint 1.5 pose la vérité planning
- Sprint 2 habille une base correcte
- Sprint 3 rend le moteur vraiment intelligent
- Sprint 5 n'arrive qu'une fois le produit stabilisé

---

## Risques principaux

### 1. On enrichit le dashboard sur une mauvaise vérité planning
- **Mitigation** : faire Sprint 1.5 avant Sprint 2 riche
- **Test** : l'historique reste visible et aucune régénération n'efface le passé

### 2. Telegram reste trop bavard
- **Mitigation** : cooldown 6h, suppression du cron 14h, max 2 messages/jour
- **Test** : une journée normale = 0 à 1 message ; une journée chargée = 2 max

### 3. Le TSS est trop approximatif pour être utile
- **Mitigation** : fallbacks simples assumés, pas de pseudo-précision
- **Test** : les courbes charge/fatigue suivent grossièrement le ressenti réel

### 4. Le planner devient plus complexe que lisible
- **Mitigation** : templates explicites + petites fonctions pures + objectifs TSS visibles
- **Test** : on peut expliquer une semaine générée sans lire 500 lignes de code

### 5. Le multi-agent arrive trop tôt
- **Mitigation** : le repousser après stabilisation domaine
- **Test** : prouver que le mono-agent limite vraiment qualité ou vitesse avant de le remplacer

---

## Vérification concrète par sprint

### Sprint 1
- [ ] Pas de doublons Telegram lors d'un import Strava suivi d'un heartbeat
- [ ] Pas de `signal_check` autonome à 14h
- [ ] Jamais plus de 2 messages proactifs dans une journée
- [ ] `tss` est calculé sur les nouvelles activités
- [ ] `compute_ctl_atl_tsb()` retourne des valeurs plausibles

### Sprint 1.5
- [ ] Une séance passée reste visible après revue hebdo
- [ ] Une régénération n'efface pas l'historique
- [ ] Une activité matche une séance datée stable
- [ ] Un déplacement agit sur une date réelle

### Sprint 2
- [ ] L'app charge en mobile sans régression
- [ ] Les graphes s'affichent
- [ ] `Today` est plus exécutable qu'un simple texte
- [ ] Le calendrier aide à lire la semaine sans passer par Telegram

### Sprint 3
- [ ] Une semaine deload est identifiable et justifiable
- [ ] Le TSS cible semaine est cohérent avec la charge récente
- [ ] Les templates de séance sont actionnables
- [ ] Un gros écart actual vs planned produit une adaptation visible

### Sprint 4
- [ ] Les modules critiques ont des tests
- [ ] La doc raconte la vraie architecture
- [ ] Une régression planner/heartbeat est détectée avant deploy

### Sprint 5
- [ ] Le comportement externe reste identique malgré le refactor interne
- [ ] Chaque agent a une responsabilité claire
- [ ] `llm.py` garde une interface stable pour le reste du code
