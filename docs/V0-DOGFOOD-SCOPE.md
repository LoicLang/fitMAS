---
summary: scope produit du FitMAS V0 dogfoodable construit autour du Runtime V0
read_when:
  - arbitrer une feature V0
  - ajouter un scenario runtime_v0
  - decider si Telegram peut utiliser le nouveau runtime
  - eviter d'ouvrir Phase B progression ou prescription
---

# V0 Dogfood Scope

## Decision

FitMAS V0 dogfoodable est un coach Telegram fiable sur une semaine simple.

But :

```text
Loic peut utiliser FitMAS pendant 1 a 2 semaines sans perdre confiance.
```

Le Runtime V0 devient le noyau cible.
Le repo actuel reste l'enveloppe produit : DB, Telegram, API, app, scripts,
deploy.

## Capacites Incluses

V0 fait peu, mais proprement :

1. Lire le plan actuel, aujourd'hui, demain et les prochains jours.
2. Enregistrer `done`, `skipped` et `partial`.
3. Corriger une erreur d'execution.
4. Adapter une seance simple sur demande explicite.
5. Demander confirmation pour une seance cle ou une mutation risquee.
6. Bloquer une mutation sportivement douteuse.
7. Garder une coherence sportive minimale de semaine.

Heartbeat V0 autorise seulement :

- briefing read-only ;
- question courte apres seance manquante ;
- aucun patch proactif auto-commit.

## Hors Scope

Ne pas ouvrir en V0 :

- progression/prescription Phase B ;
- replan complet long terme ;
- changement d'objectif structure complet ;
- nutrition ;
- multi-agent ;
- memoire reflexive ou vector DB ;
- periodisation multi-mois ;
- Telegram proactif qui modifie le plan sans demande user ;
- UI complexe de choix multiples ;
- migration globale prod.

## Sport Core V0

Le Sport Core V0 est un garde-fou, pas un moteur de prescription.

Modele seance minimal :

```text
id
date
sport
title
duration_min
intensity: easy | moderate | hard
priority: key | secondary | optional
status: planned | done | skipped | partial
flexibility: fixed | flexible
```

Regles V0 :

- pas deux seances `hard` collees sans `pending` ou `block` ;
- modifier ou supprimer une seance `key` demande confirmation ;
- modifier une seance `done` est bloque, sauf correction de statut ;
- fatigue severe, maladie ou douleur active bloque l'ajout de `hard` ;
- apres long/hard recent, privilegier easy/rest et bloquer le hard opportuniste ;
- move/lighten/replace easy sur `secondary` ou `optional` peut commit si la cible est claire ;
- multi-operation, seance cle ou risque sportif moyen passe en `pending`.

## Scenarios De Validation

Le noyau Runtime V0 protege deja 6 scenarios :

```text
current_plan
tomorrow
skipped_yesterday
execution_correction
followup_planning_turn1
key_session_pending
```

Pack produit a ajouter avant dogfood Telegram :

```text
today
next_3_days
week_key_session
done_yesterday
partial_yesterday
undo_wrong_status
explicit_move_secondary
explicit_lighten
replace_by_easy_bike
hard_unsafe_block
fatigue_signal
knee_pain_signal
sport_unavailable_two_weeks
time_preference
cancel_followup
```

## Gates

Etat de preuve actuel :

- fake matrix : `6/6` ;
- provider matrix 5x : `114/120` correctness ;
- danger metrics : `0 wrong_write`, `0 old_plan`, `0 wrong_correction_target`,
  `0 claim_without_event`.

Gate dogfood Telegram :

```text
>= 90% correctness sur scenarios V0 produit
0 danger metrics
0 duplicate command sur retry
guard fallback rate < 15%
```

La latence est mesuree, mais pas bloquante tant que le message reste fiable.

## Regles Non Negotiables

- Pas de regex/keywords sur texte utilisateur libre.
- Pas de write DB hors executor/mutation service officiel.
- Pas de claim visible sans event committe.
- Pas de fallback metier improvise.
- Le LLM comprend et propose.
- Le backend valide, autorise, commit, audite.

## Sortie De V0

V0 peut devenir le runtime produit quand :

- Telegram passe par le runtime pour les users dogfood ;
- les writes planning/execution/memory passent par `proposal -> policy -> executor`;
- les snapshots viennent de la DB actuelle sans vieux contexte ;
- les scenarios produit passent avec les providers cibles ;
- le legacy ne recoit plus de nouveaux chemins de decision.
