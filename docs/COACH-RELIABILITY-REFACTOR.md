---
summary: refactor fiabilite coach Phase A, pour retirer la parole aux guards backend tout en gardant validation, commit et audit deterministes
read_when:
  - corriger une reponse coach fausse ou backend-like
  - modifier conversation_pipeline.py
  - modifier heartbeat.py ou roles heartbeat
  - ajouter une couche de reply finale
  - traiter une contestation utilisateur de la verite systeme
---

# Coach Reliability Refactor

## Phrase guide

On ne libere pas le coach en supprimant le harnais ; on retire le micro au harnais.

## Diagnostic

Le dogfood Telegram du 3 mai 2026 montre que le coach n'est pas assez fiable
pour une semaine reelle :

- il peut recadrer avec trop d'assurance sur une verite incomplete ;
- il gere mal une contestation utilisateur ("reverifie", "ce n'est pas a jour") ;
- il peut traiter une contrainte externe comme une faute d'adhesion ;
- des helpers backend peuvent encore produire la phrase finale visible.

La doctrine reste correcte :

- le LLM comprend le langage humain ;
- le code comprend l'etat systeme ;
- le backend valide, bloque, commit et audite ;
- la phrase utilisateur normale appartient au LLM.

Le probleme actif est la forme runtime : `CoachDecision.fitmas_message` est
produit avant commit/block, puis plusieurs chemins backend peuvent remplacer la
reply finale par une template.

## Ordre CTO

### 0. No canned final replies + heartbeat read-only guard ✅ shippe 3 mai 2026

But : retirer immediatement les sorties user-facing backend-like.

Scope :

- ✅ creer une couche `FinalReplyContext` mince ;
- ✅ composer par LLM les replies de blocage / confirmation depuis le resultat reel ;
- ✅ garder seulement un fallback outage minimal si le composer LLM echoue ;
- ✅ interdire au heartbeat read-only de claim un commit sans event ;
- ✅ invalider/reparer une reply LLM qui reconnait une execution manquee sans
  `execution_actions`.

Hors scope :

- pas de write tools natifs ;
- pas de refonte provider ;
- pas de retrait massif des rules voix ;
- pas de Phase B.

### 1. Truth source runtime

`ScheduledSession` devient la seule verite runtime. `WeeklyPlan` / `DayPlan`
restent template, onboarding, compat admin. Voir `docs/COACH-COHERENCE-REFACTOR.md`.

### 2. Reality dispute / recheck path

Quand le LLM comprend que le user conteste la verite systeme, il emet un artefact
structure `reality_check`. Le code impose alors des read-tools de verite avant
toute reply finale. Pas de regex sur texte user.

### 3. Tool-use loop 3A

Multi-round read-tools, `PlanPatch` conserve comme artefact d'action, commit ou
block par backend, puis prose finale libre post-resultat.

### 4. Heartbeat agency boundary complete

Un heartbeat est soit read-only et parle en suggestion, soit action-capable et
parle apres event. Pas d'entre-deux.

### 5. Action-tools natives 3B

Seulement apres truth source, tool-loop, telemetry et prose finale stables.

### 6. Allegement prompt voix

Deplacer progressivement les few-shots vers evals/tests apres stabilisation de
la prose finale libre. Ne pas le faire avant.

## Gates du slice 0

- [x] aucune reply normale de blocage ne sort directement de `_BLOCK_REASON_REPLIES` ;
- [x] aucune confirmation normale ne dit "Reponds oui ou non" ;
- [x] aucun heartbeat read-only ne peut envoyer "on verrouille", "je pose",
  "je mets", "c'est cale", "c'est pose", "je deplace" sans event ;
- [x] les fallbacks restants sont clairement outage/systeme et courts ;
- [x] tests unitaires verrouillent les patterns visibles ;
- [x] smoke reel `heartbeat_non_completion` applique bien `skipped` via
  `execution_actions`.
