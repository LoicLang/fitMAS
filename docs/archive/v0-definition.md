---
summary: definition stricte de la V0 FitMAS, scope, boucle produit, non-objectifs et criteres de succes
read_when:
  - lancer l'execution de la V0
  - arbitrer le scope
  - verifier si une idee rentre dans la V0
  - aligner produit et implementation
---

# V0 Definition

## Une phrase

La V0 de `FitMAS` est un produit running iPhone-first qui construit un premier plan hebdomadaire personnel, l'affiche clairement dans l'app, puis l'ajuste avec quelques interactions WhatsApp bien choisies au cours de la semaine.

## User story principale

`En tant que coureur motive avec une vraie vie chargee, je veux un plan qui me ressemble deja des la premiere semaine et qui s'ajuste sans que j'aie a tout gerer seul.`

## Utilisateur cible

- coureur deja engage
- agenda parfois instable
- interesse par la personnalisation
- a l'aise avec un setup initial de 15 a 20 minutes

## Ce que la V0 doit faire

### 1. Onboarding

- collecter objectif, contraintes, preferences et ton
- connecter si possible Apple Health, Strava, calendrier, WhatsApp
- produire un recap credible

### 2. Premier plan

- generer un plan hebdo running simple
- rendre visibles 2 ou 3 arbitrages de personnalisation
- proposer un point du jour

### 3. App

L'app V0 doit contenir:

- `Today`
- `Plan`
- `Profil`

Et permettre:

- voir ce qu'il faut faire aujourd'hui
- comprendre la semaine
- voir ce qui a change
- corriger quelques preferences

### 4. WhatsApp

WhatsApp V0 doit servir a:

- clarifier une contrainte
- demander un feedback simple
- envoyer un message spontane contextuel apres un evenement notable

### 5. Adaptation simple

La V0 doit savoir faire une adaptation simple dans la semaine:

- deplacer une seance
- alleger une journee
- ajuster une logique simple de recuperation

### 6. Revue de fin de semaine

La V0 doit montrer:

- ce qui a ete suivi
- ce qui a ete adapte
- ce qu'elle a appris

## Ce que la V0 ne fait pas

- pas de nutrition riche
- pas de meal planning
- pas de chat in-app
- pas de coaching mental profond
- pas de multi-agent visible
- pas d'arbitrage complexe multi-domaines
- pas de memoire semantique avancee
- pas de recommandations medicales

## Boucle produit V0

1. onboarding
2. recap FitMAS
3. generation du premier plan
4. premiere vue `Today`
5. un message WhatsApp de clarification si necessaire
6. une adaptation simple visible dans l'app
7. un message de feedback ou spontane contextuel
8. revue de fin de semaine

## Boucle technique V0

1. user complete onboarding
2. systeme cree double numerique initial
3. systeme genere plan hebdo
4. app affiche `Today` et `Plan`
5. events entrants simples:
   - Strava
   - message user
   - event planning simple
6. orchestrateur reevalue
7. no-op, clarification ou adaptation
8. persistence en base

## Integrations V0

Prioritaires:

- Sign in with Apple
- Apple Health
- Strava
- WhatsApp

Optionnelle si elle ralentit trop:

- calendrier

## Ce qui rentre dans la V0

Une idee rentre dans la V0 si elle aide directement:

- la premiere semaine
- la lisibilite du plan
- l'ajustement simple
- la valeur relationnelle via WhatsApp

## Ce qui ne rentre pas dans la V0

Une idee ne rentre pas si elle demande:

- beaucoup d'explication
- beaucoup d'UI secondaire
- beaucoup de logique nutrition
- beaucoup de memoire long terme
- une orchestration trop ambitieuse

## Criteres de succes

La V0 est bonne si les premiers utilisateurs disent:

- "le plan me ressemble"
- "j'ai compris quoi faire"
- "les messages tombent juste"
- "j'ai moins a gerer"

## Criteres d'echec

La V0 echoue si:

- le plan parait standard
- les messages paraissent generiques
- l'app parait complexe
- il faut trop d'actions manuelles
- la personnalisation n'est pas ressentie vite

## Discipline d'execution

Si une fonctionnalite est seduisante mais n'augmente pas clairement:

- la justesse du premier plan
- la clarte du `Today`
- ou la qualite des interactions WhatsApp

alors elle doit probablement attendre apres la V0.
