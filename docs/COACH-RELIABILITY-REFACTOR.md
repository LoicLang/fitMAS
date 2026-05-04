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
- [x] extension 4 mai : aucun heartbeat read-only ne peut envoyer
  "j'ai ajuste", "j'ai bascule", "j'ai tout remplace",
  ou "regarde ton app... j'ai ajuste" sans event ; chaque sortie heartbeat
  read-only passe par un LLM judge `ALLOW/BLOCK`, sans regex fake-action ;
- [x] les fallbacks restants sont clairement outage/systeme et courts ;
- [x] tests unitaires verrouillent les patterns visibles ;
- [x] smoke reel `heartbeat_non_completion` applique bien `skipped` via
  `execution_actions`.

## P1-ter — Execution receipt repair ✅ implemente localement 4 mai 2026

Apres 3B-A, un smoke reel a isole un cas residuel : le LLM pouvait reconnaitre
"pas fait hier" dans `fitmas_message` / `rationale` mais oublier
`execution_actions`. La sortie etait justement invalidee par
`execution_receipt_without_action`, puis pouvait finir en outage si le repair
JSON renvoyait encore le meme oubli.

Fix livre :
- `conversation_pipeline.py` transmet la cible follow-up sous forme structuree
  (`unresolved_execution_followup_session_id`) au lieu de seulement injecter un
  bloc texte dans le prompt ;
- `llm.py` ajoute un repair semantique local apres echec du JSON repair :
  uniquement si l'artefact LLM invalide reconnait lui-meme l'execution manquee
  et qu'une cible follow-up structuree existe ;
- extension P1-quater : le meme principe couvre maintenant une CoachDecision
  valide mais incomplete. Si elle parle d'une execution d'hier sans
  `execution_actions`, un repair LLM peut ajouter un `target_ref` naturel
  (`seance d'hier`) que le writer resout ensuite contre la DB ;
- le repair produit `CoachDecision(no_change)` +
  `execution_actions=[record_execution_update(status=not_completed)]`.

Frontiere : aucun parsing du texte utilisateur libre. Le code repare un artefact
LLM fautif contre une cible DB deja identifiee ou une reference naturelle bornee
que le writer doit resoudre contre la DB ; sans resolution unique, il ne
synthetise pas d'action.

## P1-quater — Dogfood API fallout ✅ implemente localement 4 mai 2026

Apres les tests API reels, quatre incoherences restaient trop fragiles avant
3B-B :

- `execution_actions` pouvait contredire la reply/rationale visible ;
- la reply post-mutation pouvait citer le mauvais jour malgre un event correct ;
- une cible planning vague pouvait etre mutee trop vite si plusieurs seances du
  meme sport existaient ;
- une contrainte de disponibilite pouvait etre comprise puis non memorisee.

Fix livre :
- verification/reparation LLM de `execution_actions` sur CoachDecision, sans
  parser le texte user ;
- enrichissement des facts post-event avec `YYYY-MM-DD (jour)` pour que le
  verifier puisse bloquer les contradictions calendaires ;
- `validate_plan_patch` passe en `requires_confirmation` sur target ambigu non
  disambiguise ;
- repair LLM de `record_availability` quand l'intent LLM est
  `availability_constraint` et que la CoachDecision a oublie la memoire.

Frontiere : tout part d'artefacts LLM, de validation DB ou de facts
post-mutation. Aucun regex/keyword sur texte utilisateur libre.

## P1 prioritaire — Post-event reply verifier ✅ implemente localement 4 mai 2026

Apres Chantier 4, le dogfood a isole une classe plus dangereuse que la voix
backend-like : **la reply post-mutation peut contredire les events reels**.

Exemple :

```text
events reels = deux sessions remplacees par Journee flexible
reply finale = "J'ai decale le fractionne a jeudi"
```

Objectif livre : avant tout envoi user apres mutation, verifier que la phrase finale
ne claim que ce qui existe dans `events_committed`, `events_blocked` et le diff
de sessions. Si elle ajoute, inverse ou transforme une action, la faire reparer
par LLM ; si le repair echoue, utiliser un fallback court sans claim inventee.

Pipeline cible :

```text
PlanPatch valide / commit
  -> events_committed + session_changes
  -> final reply composer LLM
  -> post-event reply verifier
     -> ALLOW | REPAIR | outage fallback
  -> send
```

Ce verifier ne lit pas le texte utilisateur libre. Il juge seulement des
artefacts machine post-mutation + la phrase sortante, donc il respecte la
doctrine LLM-first.

Acceptance :
- [x] une reply qui mentionne un jour/session/action absent des events est reparee ;
- [x] une reply fidele aux events passe sans modification ;
- [x] un verifier invalide/outage tombe sur un fallback court, auditable, sans faux
  claim d'action ;
- [x] le contexte verifier recoit un diff compact `before_snapshot` /
  `after_snapshot` quand disponible, pour distinguer `replace_session` de
  `move_session`.
- [ ] smoke `week_scope_constraint` reel a relancer apres commit/deploy : la
  phrase finale ne doit plus dire "decale a jeudi" si l'event reel est un
  remplacement par `Journee flexible`.
