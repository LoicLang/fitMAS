---
summary: contrat court de review sportive et coherence semaine
read_when:
  - modifier week_coherence.py
  - modifier domain/planning/reviewer.py
  - toucher a validate_week_coherence
  - juger une mutation planning significative
  - travailler sur coherence sportive sans ouvrir Phase B prescription
---

# Sport Quality Review

## Role

La review sportive evite les plans techniquement valides mais sportivement
mediocres.

Elle repond a :

```text
Si on applique ce changement, est-ce encore une bonne semaine ?
```

Elle ne doit pas devenir un second coach conversationnel.

## Frontieres

| Couche | Role |
| --- | --- |
| Deterministic facts | construire les faits semaine |
| Reviewer LLM | juger un compromis deja construit |
| Policy backend | commit / pending / block |
| Mutation service | appliquer si autorise |
| Reply composer | expliquer apres outcome |

Le reviewer ne parle pas au user.
Il ne write pas.
Il ne cree pas de patch.

## Verites D'Entree

- `ScheduledSession` pour le planning runtime.
- `Activity` / execution events pour le reel.
- facts memoire actifs avec TTL/statut.
- candidate ou `PlanPatch` deja construit.
- score/finding deterministes quand disponibles.

`WeeklyPlan` / `DayPlan` restent template/archive/compat.

## Modules Actuels

- `domain/planning/week_coherence.py`
- `domain/planning/reviewer.py`
- `domain/coaching/generated_week_coherence.py`

Prompts reviewer :

- `llm/prompts/reviewer.py`

## Signaux A Proteger

- trop de hard sessions ;
- recuperation mal placee ;
- remplacement d'une seance cle par stimulus faible ;
- densite trop forte apres fatigue/douleur ;
- cible deja faite ;
- incoherence sport/duree/intensite ;
- perte de mission semaine.

Les repos/recuperations ne sont pas des hard locks locaux par defaut.
Ils sont juges dans le compromis semaine.

## Runtime Tool

`validate_week_coherence` est validation-only.

Il peut aider planning/heartbeat.
Il ne doit pas rallonger inutilement le tour conversationnel user.
Si un smoke montre des timeouts, sortir la review longue du chemin synchrone ou
reduire les lanes exposees.

## Phase B

Ce document ne lance pas Phase B prescription/progression.

Phase B future :

- progression structuree ;
- prescription comme source de verite ;
- rendu seance apres prescription ;
- zones/VMA/FTP/CSS plus riches.

Lane active actuelle :

```text
Produit V0 dogfoodable.
Sport Core minimal avant prescription.
```

## Tests

Sur modification :

- tests `week_coherence` ;
- tests candidate evaluator/policy ;
- tests tool runtime si `validate_week_coherence` bouge ;
- smoke API si une mutation planning peut changer.
