---
summary: vision produit, wedge V0, scope, ICP, parcours utilisateur et criteres de succes
read_when:
  - comprendre le produit
  - arbitrer le scope
  - verifier si une idee rentre dans la V0
  - designer une feature
---

# FitMAS Product

## Une phrase

FitMAS est une equipe IA proactive qui ajuste ton entrainement et ta nutrition selon ta vraie vie.

## Promesse

- mieux performer
- moins reflechir / moins planifier
- avoir le sentiment d'etre suivi par une equipe premium

La promesse externe est "mieux performer".
Le mecanisme interne ressenti est "moins de charge mentale".

## ICP V0

- coureur deja engage (3+ sorties/semaine)
- agenda parfois instable
- interesse par la personnalisation
- a l'aise avec un setup initial de 15-20 minutes
- tone preference: direct, pas cheerleader

## Wedge V0: running endurance

Pourquoi running en premier:
- meilleur fit avec Apple Health et Strava
- donnees plus riches et progression plus facile a mesurer
- adaptation quotidienne plus lisible
- boucle proactive plus naturelle

Pas en V0: musculation, hybrid, triathlon.

## Ce que la V0 sait faire

### 1. Onboarding (6 blocs, 15-20 min max)

1. **Cap et objectif** — objectif principal, echeance, ambition
2. **Realite de vie** — jours disponibles, creneaux, contraintes
3. **Niveau running** — volume recent, types de seances, fragilites
4. **Nutrition utile** — habitudes, contraintes, gouts (leger, pas de tracking)
5. **Style de coaching** — ton, niveau de challenge, tolerance aux relances
6. **Integrations** — Apple Health, Strava, calendrier, messagerie

Ecran recap final: ce que FitMAS a compris. Critique pour la confiance.

### 2. Premier plan hebdo running

- intention de la semaine
- 3-5 seances (footing, qualite, sortie longue, recup, repos)
- 2-3 arbitrages de personnalisation visibles
- focus nutrition leger attache au plan (timing, collations)

### 3. App (3 tabs)

**Today** — ecran principal quotidien
- decision du jour (seance + objectif)
- focus nutrition
- ce qui a change + pourquoi
- ce que FitMAS surveille
- feedback simple

**Plan** — vue semaine
- intention hebdo
- jours avec seances, charge, flexibilite
- arbitrages recents

**Profil** — double numerique visible
- objectifs, contraintes, preferences, style coaching
- integrations connectees
- ce que FitMAS croit savoir

### 4. Messagerie proactive

4 categories de messages:
1. **Adaptation** — ce qui change, pourquoi, impact
2. **Clarification** — question courte quand info manque
3. **Feedback** — question simple apres seance cle ou signal de fatigue
4. **Spontane contextuel** — reconnaissance d'effort, lecture situationnelle

### 5. Adaptation simple

- deplacer une seance
- alleger une journee
- ajuster la recuperation

### 6. Revue de fin de semaine

- ce qui a ete suivi
- ce qui a ete adapte
- ce que FitMAS a appris

## Ce que la V0 ne fait pas

- pas de nutrition riche / meal planning
- pas de chat in-app
- pas de coaching mental profond
- pas de multi-agent visible
- pas de memoire semantique avancee
- pas de recommandations medicales
- pas d'Android

## Boucle produit V0

1. onboarding → recap FitMAS
2. generation du premier plan
3. premiere vue Today
4. message de clarification si necessaire
5. adaptation simple visible dans l'app
6. message de feedback ou spontane contextuel
7. revue de fin de semaine

## Semaine 1 — scenario de reference

**Persona**: 31 ans, court 3x/semaine, veut progresser sur semi, agenda variable, mardi soir fragile, jeudi prefer leger, sortie longue dimanche, ton direct.

| Jour | Produit | Canal |
|------|---------|-------|
| J0 | Onboarding → premier plan. "J'ai evite un bloc mardi soir, jeudi leger, longue dimanche." | App |
| J1 | Footing facile 45 min. Pas de message. | App |
| J2 | Conflit agenda mardi. "Tu peux courir demain matin ou plutot jeudi?" → user: "jeudi" → adaptation | WhatsApp + App |
| J3 | Pas de signal utile. Silence. | — |
| J4 | Seance qualite (deplacee). Strava remonte. "Belle seance. Bloc valide. Demain plus souple." | WhatsApp |
| J5 | "Recup: jambes lourdes ou fatigue normale?" → user: "un peu lourdes" → ajustement | WhatsApp |
| J6 | User consulte Plan. Semaine coherente malgre les changements. Pas de message. | App |
| J7 | Sortie longue. "Belle sortie longue. Semaine propre malgre l'ajustement mardi." | WhatsApp |
| Fin | Revue: suivi, adapte, appris. "Mardi doit rester flexible. Tu recuperes bien mais besoin de legerete apres qualite." | App |

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

## Frontiere d'autonomie

**Sans validation humaine:**
- ordre/timing des seances
- ajustements moderes de volume
- repos/deload legers
- collations et timing alimentaire
- ajustements fins de macros
- niveau de challenge dans les messages

**Sous validation explicite:**
- changement d'objectif principal
- forte variation calorique
- suppression d'une seance cle
- bascule majeure de strategie
- situations de sante/blessure

## Positionnement concurrentiel

Le marche a deja: Humango (plans adaptatifs endurance), Runna (excellente execution running), Oura Advisor (data wearable + conversation), WHOOP Coach (IA sur wearable).

Ce qui manque: une experience qui combine plan adaptatif + personnalisation durable + voix coherente + proactivite utile + faible charge mentale.

FitMAS ne bat personne sur un axe. FitMAS gagne sur l'orchestration, la delegation mentale, et la sensation de suivi premium continu.
