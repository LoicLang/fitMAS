---
summary: ordre de construction concret de la V0, par phase, avec les premieres taches ce soir
read_when:
  - commencer a coder
  - choisir le prochain chantier
  - verifier l'avancement
---

# FitMAS Build Order

## Phase 1 — Ce soir: squelette API + modele de donnees

Objectif: un backend qui tourne avec les vrais objets produit.

### 1.1 Modele de donnees SQLite

Creer les tables:
- User
- DigitalTwin
- WeeklyPlan
- DailySnapshot
- RawEvent
- CoachMessage
- UserFact
- Decision

Utiliser SQLAlchemy ou SQL brut. Garder simple.

### 1.2 API endpoints de base

```
POST /onboarding          → cree User + DigitalTwin
GET  /today/{user_id}     → retourne DailySnapshot du jour
GET  /plan/{user_id}      → retourne WeeklyPlan actif
GET  /profile/{user_id}   → retourne DigitalTwin
POST /plan/generate       → genere un premier WeeklyPlan
```

### 1.3 Moteur de planification V0

Heuristiques deterministes:
- Placer les seances selon les jours dispo du user
- 80/20: majoritairement facile, 1 qualite, 1 sortie longue
- Respecter les contraintes (jours bloques, creneaux)
- Progression volume ~10%/semaine
- LLM appele pour: intention de la semaine + formulation des arbitrages

### 1.4 Premier appel LLM

Un seul prompt qui recoit:
- SOUL (system prompt)
- DigitalTwin du user
- Squelette de plan (genere par heuristiques)
- Tache: "personnalise ce plan et formule l'intention"

Retour: plan enrichi avec intention + arbitrages en langage naturel.

## Phase 2 — Webapp mobile-first

### 2.1 Today screen
- Decision du jour
- Focus nutrition
- Ce qui a change
- Feedback simple

### 2.2 Plan screen
- Vue semaine
- Intention
- Jours avec seances

### 2.3 Profil screen
- DigitalTwin lisible
- Preferences editables

### 2.4 Onboarding flow
- 6 blocs de questions
- Recap
- Generation du plan

## Phase 3 — Messagerie proactive (Telegram)

### 3.1 Bot Telegram
- Envoyer des messages proactifs
- Recevoir des reponses libres
- Webhook → RawEvent

### 3.2 Extracteur de feedback
- 1 appel LLM sur le message entrant
- Sortie structuree: intent, contraintes, ressenti, confidence

### 3.3 Heartbeat simple
- Cron 2x/jour par user
- Checklist: changement? adapter? question? message? no-op?
- Persister la decision

## Phase 4 — Integrations reelles

### 4.1 Strava
- OAuth flow
- Webhook pour activity.create
- Fetch detail + normalisation en RawEvent

### 4.2 Adaptation automatique
- Seance detectee via Strava → comparer au plan
- Adapter si ecart significatif

## Phase 5 — Hardening

- Migration SQLite → PostgreSQL
- Auth robuste
- WhatsApp Business API (si Telegram valide)
- App iOS native (si webapp validee)
- Memoire episodique et retrieval

## Questions d'audit — reponses tranchees

### "Quelle est la source de verite pour la logique d'entrainement?"
→ Heuristiques deterministes. Pas le LLM. Regles codees en dur: progression 10%, 80/20, cycles charge/decharge, placement contraint. Le LLM personnalise et formule par-dessus.

### "Comment trouver les 10 premiers utilisateurs?"
→ Reseau personnel de coureurs motives. Pas besoin de landing page. 5-10 personnes en beta privee, contact direct, feedback hebdo en face-a-face ou par message. L'acquisition viendra apres la preuve de valeur.

### "Quel est le modele de cout LLM?"
→ Haiku/GPT-4o-mini pour heartbeat et extraction (~$0.05/jour/user). Sonnet/GPT-4o pour generation de plan et messages importants (~$0.10/jour/user). Total: ~$2-4/mois/user. Viable avec pricing $10-15/mois.

### "Comment gerer le cold start?"
→ L'onboarding de 20 min EST le cold start fix. Les heuristiques produisent un plan structurellement correct. Le LLM ajoute la personnalisation visible (arbitrages, ton, intention). Le plan n'est pas magique au jour 1 — il est "correct et comprehensible". La magie vient a J2-J4 avec les premieres adaptations.

### "WhatsApp est-il un risque de dependance?"
→ Oui. C'est pourquoi on commence par Telegram. Interface abstraite des le jour 1. Migration WhatsApp quand le produit est prouve et le process Meta complete. Si WhatsApp s'avere impossible, Telegram ou SMS restent viables.
