---
summary: mapping v1 des objets de memoire FitMAS, leur stockage, leur format, qui les ecrit et qui les lit
read_when:
  - decider ou stocker une information
  - implementer la memoire produit
  - arbitrer entre SQL, Markdown et retrieval
  - definir les writers et readers de contexte
---

# Memory Objects V1

## Principe

Ce document repond a une question simple:

`pour chaque type d'information, ou la stocke-t-on et pourquoi ?`

Regle generale:

- SQL si c'est de la verite produit
- Markdown si c'est une regle ou identite stable du systeme
- retrieval si c'est un mecanisme de rappel
- pas de stockage si l'information n'a pas de valeur durable

## 1. Ame FitMAS

### Exemple

- mission
- ton
- garde-fous
- posture de coaching

### Stockage

- Markdown

### Format

- `SOUL.md`
- `IDENTITY.md`
- `HEARTBEAT.md`

### Writer

- equipe produit / engineering

### Reader

- service IA
- heartbeat logic

### Pourquoi

- stable
- lisible
- editable a la main
- proche des bons patterns OpenClaw

## 2. Profil utilisateur de base

### Exemple

- timezone
- locale
- onboarding status
- preferences de communication

### Stockage

- SQL

### Format

- colonnes + JSONB leger

### Writer

- app mobile
- backend onboarding

### Reader

- API
- orchestrateur
- service IA

### Pourquoi

- source de verite relationnelle

## 3. Double numerique

### Exemple

- objectifs
- contraintes
- preferences sport
- preferences nutrition
- gouts
- style de motivation
- tolerance a la charge

### Stockage

- SQL

### Format

- colonnes stables + JSONB

### Writer

- onboarding
- memory writer
- orchestrateur apres validation

### Reader

- agent sport
- agent nutrition
- orchestrateur
- app

### Pourquoi

- coeur du produit
- doit etre corrigeable
- doit etre versionnable
- doit etre requetable

## 4. Faits utilisateur

### Exemple

- n'aime pas courir le mercredi soir
- prefere les sorties longues le dimanche matin
- adhere mieux a un ton direct

### Stockage

- SQL

### Format

- table de facts

### Writer

- extraction depuis onboarding
- extraction depuis conversation
- inference confirmee

### Reader

- context builder
- orchestrateur
- app profil

### Pourquoi

- ce sont des traits actionnables
- ils doivent survivre aux conversations

## 5. Hypotheses utilisateur

### Exemple

- semble mieux adherer avec une semaine visible des le dimanche
- pourrait mal tolerer les intensites tardives

### Stockage

- SQL

### Format

- table d'hypotheses avec confidence et statut

### Writer

- service IA
- orchestrateur

### Reader

- context builder
- orchestrateur

### Pourquoi

- utile mais pas encore "verite"
- doit pouvoir etre invalide

## 6. Evenements bruts

### Exemple

- activite Strava
- sleep signal HealthKit
- message WhatsApp entrant
- conflit calendrier

### Stockage

- SQL

### Format

- raw events en JSONB + metadata

### Writer

- webhooks
- app mobile

### Reader

- pipelines d'ingestion
- deriveur de signaux
- audit

### Pourquoi

- indispensable pour replay et traçabilité

## 7. Signaux derives

### Exemple

- workout_completed
- sleep_degraded_2d
- adherence_drop_risk
- plan_conflict_for_tomorrow

### Stockage

- SQL

### Format

- table de signals + payload

### Writer

- pipeline de derivation

### Reader

- orchestrateur
- context builder
- service IA

### Pourquoi

- beaucoup plus utile au systeme que le raw data seul

## 8. Plan courant

### Exemple

- plan hebdo sport
- plan nutrition hebdo
- plan du jour

### Stockage

- SQL

### Format

- JSONB + metadata

### Writer

- orchestrateur

### Reader

- app
- context builder
- service IA

### Pourquoi

- objet produit principal
- doit etre versionne

## 9. Pourquoi le plan a change

### Exemple

- fatigue elevee + conflit agenda
- maintien de l'objectif global

### Stockage

- SQL

### Format

- `rationale` en texte + liens triggers

### Writer

- orchestrateur
- service IA

### Reader

- app
- context builder
- audit produit

### Pourquoi

- indispensable pour la continuite

## 10. Historique des plans

### Exemple

- plan parent
- plan enfant
- changements successifs

### Stockage

- SQL

### Format

- lineage via `parent_plan_id`

### Writer

- orchestrateur

### Reader

- app
- context builder
- outils d'analyse

### Pourquoi

- permet la cohérence longitudinale

## 11. Messages conversationnels bruts

### Exemple

- message WhatsApp sortant
- reponse utilisateur

### Stockage

- SQL

### Format

- texte + metadata de canal

### Writer

- messaging provider
- webhook inbound

### Reader

- thread summarizer
- audit
- support

### Pourquoi

- historique court terme
- pas source de verite comportementale

## 12. Resume de conversation

### Exemple

- l'utilisateur a refuse la seance de jeudi
- prefere un ton plus direct cette semaine
- question ouverte sur samedi

### Stockage

- SQL

### Format

- `TEXT` + open questions

### Writer

- thread summarizer

### Reader

- context builder
- messaging layer

### Pourquoi

- compresse la conversation utile

## 13. Memoire episodique

### Exemple

- semaine difficile a cause du travail
- bon adherence pendant la semaine pre-course

### Stockage

- SQL

### Format

- texte structure court + tags

### Writer

- summarizer quotidien / hebdo
- orchestrateur

### Reader

- context builder
- retrieval plus tard

### Pourquoi

- garde les apprentissages sans relire tout l'historique

## 14. Index de retrieval

### Exemple

- embeddings de resumes episodiques
- embeddings de facts textuels

### Stockage

- derive de SQL

### Format

- pgvector plus tard ou autre index

### Writer

- pipeline d'indexation

### Reader

- memory retriever

### Pourquoi

- rappel semantique
- jamais source de verite

## 15. Donnees a ne pas garder durablement

### Exemple

- bruit conversationnel sans valeur
- reflexion intermediaire du modele
- contexte assemble pour un run
- prompts temporaires

### Stockage

- pas de stockage durable par defaut

### Pourquoi

- eviter la pollution memoire
- eviter de faire d'un contexte temporaire une pseudo-verite

## Regle simple de decision

Si une information doit:

- survivre a plusieurs runs
- etre retrouvee proprement
- etre explicable
- etre liee a une decision

alors elle va probablement en SQL.

Si elle decrit le systeme lui-meme,
elle va probablement en Markdown.

Si elle sert juste a retrouver un souvenir parmi beaucoup d'autres,
elle peut alimenter le retrieval.
