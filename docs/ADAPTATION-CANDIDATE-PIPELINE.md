---
summary: plan du pipeline d adaptation sportive par candidats PlanPatch bornes LLM puis validation moteur
read_when:
  - permettre au LLM de proposer une adaptation de seance
  - modifier PlanPatch ou PlanMutationService
  - refactorer week_coherence vers facts, findings et score
  - brancher un candidate generator LLM
  - ajouter commit / pending / pending_choice / block pour une adaptation
---

# Adaptation Candidate Pipeline

## Doctrine

```text
Le LLM explore les compromis.
Le moteur mesure les consequences.
La policy prend la responsabilite.
Le composer raconte la verite.
```

FitMAS ne commit jamais une adaptation parce qu'un LLM l'a formulee.
Le LLM transforme une demande floue en options structurees. Le moteur simule
ces options, mesure leurs consequences, bloque l'invalide, score le compromis,
puis une policy decide `commit`, `pending_confirmation`, `pending_choice` ou
`block`. Le coach explique uniquement la decision réellement prise.

## Flux Cible

```text
User message
-> Intent parser
-> Current plan + constraints + WeekFacts
-> LLMPlanPatchCandidateGenerator
-> PlanPatchCandidate[]
-> Patch contract validation
-> Simulation
-> Plan validation
-> WeekFacts after
-> Score after + score delta
-> Findings
-> DecisionPolicy
-> commit / pending / pending_choice / block
-> PlanAdaptationTrace
-> FinalComposer
-> User reply
```

## Etat — 7 mai 2026

Implémente localement :

- `week_coherence`: `WeekFacts`, `CoherenceFinding`, `WeekCoherenceScore` ;
- `plan_patch_candidates`: `PlanPatchCandidate` + validation de contrat patch-set ;
- `plan_patch_candidate_generator`: generator LLM borné, mocké en tests ;
- `plan_patch_candidate_evaluator`: contrat -> flatten -> validation runtime -> facts/score/findings -> `policy_hint`.
- `plan_patch_adaptation_policy`: selection pure `commit` / `pending_confirmation` / `pending_choice` / `block`
  sur candidats deja evalues, sans write.

Pas encore branché :

- final composer adaptation ;
- conversation pipeline.

## Frontieres

- Le LLM ne parle pas au user dans la phase candidate.
- Le LLM ne commit rien.
- Le LLM ne produit que des candidats dans un DSL borne.
- Le moteur ne comprend pas le texte libre utilisateur.
- Le moteur valide, simule, mesure, score et applique.
- Le composer parle apres decision reelle, jamais avant.

## Phase 0 — Week Coherence Facts

Objectif : sortir les decisions sportives implicites de `week_coherence`.

Avant :

```text
flag -> severity implicite -> friction policy cachee
```

Apres :

```text
facts -> findings -> score -> policy explicite
```

Livrables :

```python
WeekFacts
CoherenceFinding
WeekCoherenceScore
```

`RECOVERY_AFTER_HARD_LOST` devient un finding + penalty de score. Ce n'est pas
un hard block et ne force pas seul une confirmation.

Hard blocks reserves aux bornes explicites :

- session deja faite touchee ;
- cible inexistante ;
- operation/schema invalide ;
- disponibilite hard violee ;
- duree impossible ;
- douleur/blessure explicitement incompatible ;
- readiness critique + haute intensite.

## Phase 1 — PlanPatchCandidate

Un candidat est une option proposable, pas applicable.

```python
@dataclass(frozen=True, slots=True)
class PlanPatchCandidate:
    id: str
    patches: tuple[PlanPatch, ...]
    rationale: str
    expected_tradeoff: str
    confidence: float
    assumptions: tuple[str, ...]
    risk_notes: tuple[str, ...]
    created_from_plan_id: str
    created_from_plan_version: int
```

Un candidat peut contenir plusieurs patches lies : move + reduce + mark
optional. Il ne contient jamais de final reply, event committe ou plan final.

## Phase 2 — Candidate Generator LLM

Le generator est separe du coach conversationnel, meme si le provider est le
meme.

Input :

```text
user_message
parsed_user_intent
current_plan_summary
current_plan_id/version
constraints
WeekFacts
CoherenceFinding[]
allowed_operations
forbidden_operations
pending_context
```

Output strict :

```json
{
  "candidates": [
    {
      "patches": [],
      "rationale": "...",
      "expected_tradeoff": "...",
      "confidence": 0.82,
      "assumptions": [],
      "risk_notes": []
    }
  ]
}
```

Regles :

- produire 0 a 3 candidats ;
- utiliser uniquement les operations autorisees ;
- signaler les hypotheses ;
- produire 0 candidat si l'intention est insuffisante ou dangereuse ;
- ne jamais claim qu'un changement est fait.

## Phase 3 — Evaluation

Pour chaque candidat :

```text
validate_patch_contract
-> simulate_patch_set
-> validate_resulting_plan
-> extract_week_facts
-> score_week_coherence
-> generate_findings
-> infer_policy_hint
```

Contrat :

```python
@dataclass(frozen=True, slots=True)
class EvaluatedPlanPatchCandidate:
    candidate: PlanPatchCandidate
    patch_validation: ValidationResult
    simulated_plan: TrainingPlan | None
    plan_validation: ValidationResult | None
    facts: WeekFacts | None
    score: WeekCoherenceScore | None
    findings: tuple[CoherenceFinding, ...]
    score_delta: float | None
    policy_hint: str
    evaluation_summary: str
```

`score_delta` est obligatoire : il explique si l'adaptation ameliore ou degrade
la coherence du plan courant.

## Phase 4 — Decision Policy

Etats produits :

```text
commit
pending_confirmation
pending_choice
block
```

Regles de depart :

- tous les candidats bloques -> `block` ;
- un seul candidat valide, risque bas, score correct -> `commit` ;
- un seul candidat valide, risque moyen -> `pending_confirmation` ;
- plusieurs candidats proches -> `pending_choice` ;
- score fortement degrade mais demande user plausible -> `pending_confirmation` ;
- douleur/blessure touchee -> `pending_confirmation` ou `block` selon gravite.

`pending` est un etat produit normal, pas un echec.

## Phase 5 — Final Composer

Mapping strict :

```text
commit -> "j'ai modifie..."
pending_confirmation -> "je te propose..."
pending_choice -> "j'ai deux options propres..."
block -> "je ne le fais pas..."
```

Tests anti-surclaim obligatoires :

- policy `pending` ne peut pas produire "j'ai deplace" ;
- policy `block` ne peut pas produire "c'est fait" ;
- aucun commit event -> aucune phrase de plan modifie ;
- pas de selected candidate -> pas de rationale inventee.

## Phase 6 — Observabilite

Chaque adaptation garde une trace :

```python
PlanAdaptationTrace:
    user_message
    parsed_user_intent
    plan_id_before
    plan_version_before
    week_facts_before
    score_before
    candidates_generated
    candidates_evaluated
    candidates_rejected
    selected_candidate_id
    final_policy
    plan_id_after
    plan_version_after
    composer_input
    final_reply_summary
```

Raisons normalisees :

```text
rejected_by_patch_contract
rejected_by_plan_validation
rejected_by_score
rejected_by_policy
requires_user_confirmation
committed
```

## Operations Autorisees V1

```text
move_session
swap_sessions
reduce_duration
reduce_intensity
reduce_volume
replace_session_type
mark_optional
remove_optional_session
add_recovery_session
```

Operations exclues en Phase A :

```text
add_hard_session
increase_intensity
increase_volume
change_goal
change_phase
```

## Commits Prevus

1. `week_coherence: split facts, findings and scoring`
2. `plan_patch: add candidate contract and patch-set validation`
3. `candidate_generator: add bounded LLM patch candidate generation`
4. `adaptation_evaluator: simulate, validate, score and decide policy`
5. `conversation: integrate adaptation flow and final composer`

## Dogfood

Scenarios a tester :

```text
je suis rincé demain
déplace la séance à vendredi
j'ai mal au genou
j'ai raté hier, je peux jeudi
raccourcis demain à 25 min
remplace la piscine
je veux éviter deux jours d'affilée
```
