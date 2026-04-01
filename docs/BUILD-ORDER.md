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

## État actuel — 31 mars 2026

### Socle produit déjà solide

- onboarding Telegram complet avec preview coach
- bridge Telegram debounced sur rafales courtes
- planner déterministe + fondations `PlanningDecision`
- calendrier daté persistant via `ScheduledSession`
- webapp React/Vite déployée avec `Aperçu / Calendrier / Évolution`
- activités réelles : manuel + Strava + matching + vues app
- heartbeat proactif de base
- revue hebdo auto
- mémoire V2 base : `profile / working / patterns`

### Chantiers transversaux déjà largement absorbés

- `REALITY-WORKOUT-CONTRACT.md`
  - vérité d'exécution durcie
  - `RecentRealityWindow` posé
  - `WorkoutContent` posé
  - `strength_engine` déterministe MVP posé
  - app remappée sur le contrat séance
- `CONVERSATION-GROUNDING.md`
  - résolution `aujourd'hui / demain / hier`
  - `execution_context`, `execution_evidence`, `activity_claims`
  - meilleure lecture du réel hors plan
  - runtime tools V1 read-only branchés au chat
- `PLANNING-ENGINE-V2.md`
  - snapshots + readiness + decision engine posés
  - templates + validator posés
  - planner déjà recentré hors LLM

### Ce qui ne doit plus apparaître comme “à faire”

- migration React/Vite
- calendrier persistant
- cockpit app de base
- séparation `profile / working / patterns`
- sprint “agents”

Ces sujets sont des acquis ou des pistes dépriorisées, plus des TODO immédiats.

## Décision de sequencing

- la prochaine douleur n'est pas “plus d'intelligence planner”
- la prochaine douleur est “meilleur harness conversationnel, meilleure mémoire, moins d'appels inutiles”
- `transcript structuré > compaction` pour l'état actuel du produit
- le plan mode ne vaut que pour les mutations à impact fort
- les skills formels attendent assez de workflows distincts
- pas de multi-agent tant que le mono-agent n'est pas un goulot prouvé

## Plan canonique — maintenant

### 1. Prompt 2 zones + prompt caching

But :

- sortir le contexte stable du flux quotidien
- réduire coût + latence des appels coach
- garder une base de prompt plus lisible

Scope :

- zone statique : rôle, ton, règles, tools, doctrine
- zone dynamique : temps local, planning utile, mémoire utile, réel récent
- brancher le caching Anthropic sur la zone statique

Docs de référence :

- `RUNTIME-TOOLS.md`
- `SOUL.md`
- `CONVERSATION-GROUNDING.md`

### 2. Debounce Telegram

But :

- éviter 3 appels LLM pour 3 messages rapides
- répondre sur le bon paquet conversationnel

Scope :

- buffer court `2-3s`
- une seule décision LLM par rafale courte
- garde-fous pour ne pas retarder inutilement un vrai échange isolé

Etat :

- fait en bridge Telegram
- buffer configurable via `FITMAS_TELEGRAM_DEBOUNCE_SECONDS`

Docs de référence :

- `BUILD-ORDER.md`
- `CONVERSATION-GROUNDING.md`

### 3. Mémoire utile — dates absolues + contrat typed + profil résumé

But :

- ne plus écrire de mémoire relative qui devient du bruit
- garder un `profile_summary` compact toujours injectable
- rendre `UserFact` plus prédictible pour le coach

Scope :

- normaliser les faits temporels en date absolue avant `upsert_facts`
- consolider la frontière `profile` vs `working`
- produire un résumé profil court, stable, cheap à injecter

Docs de référence :

- `MEMORY-V2.md`
- `CONVERSATION-GROUNDING.md`

### 4. Permission tiers sur les mutations

But :

- auto-exécuter les adaptations triviales
- demander confirmation sur les vraies mutations à impact

Règle :

- low impact : exécuter puis confirmer
- high impact : proposer puis attendre validation

Exemples high impact :

- réorganisation de plusieurs jours
- remplacement de sport
- adaptation santé qui touche la semaine

Docs de référence :

- `USER-INDICATIONS.md`
- `PLANNING-CONTRACT.md`
- `CLAUDE-CODE-LEARNINGS.md`

### 5. Transcript structuré persistant

But :

- rendre le système débuggable
- préparer une vraie consolidation mémoire
- garder une trace exploitable des tours importants

Scope :

- persister un transcript structuré, pas juste du texte brut
- relier message, contexte utilisé, décision, mutation, tool calls éventuels
- ne pas confondre transcript et mémoire durable

Docs de référence :

- `MEMORY-V2.md`
- `RUNTIME-TOOLS.md`

### 6. Consolidation mémoire périodique

But :

- dédupliquer le durable
- remonter un profil plus propre
- éviter l'accumulation de bruit

Pré-requis :

- transcript structuré en place
- écriture temporelle fiable
- frontière `profile / working` plus ferme

Docs de référence :

- `MEMORY-V2.md`

### 7. Heartbeat scoring tick-based

But :

- remplacer les crons trop rigides par une lecture plus contextuelle
- capter aussi les observations silencieuses quand le coach ne parle pas

Scope :

- scoring de proactivité
- log d'observations silencieuses
- meilleure priorisation des moments où parler

Docs de référence :

- `CLAUDE-CODE-LEARNINGS.md`
- `SOUL.md`

## Tracks domaine à reprendre après ce socle

### `PLANNING-ENGINE-V2.md`

Quand le track planner redevient prioritaire :

- enrichir `periodization.py` au-delà du simple `3+1`
- mieux distribuer la charge par sport
- porter l'explication de `PlanningDecision` jusque dans coach + app
- enrichir l'onboarding sportif seulement après ça

### `REALITY-WORKOUT-CONTRACT.md`

Le gros chantier est absorbé.
Le vrai next domain, si on y revient :

- `strength_signals` plus riches
- variations renfo depuis réel récent + fatigue + santé + temps dispo
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
