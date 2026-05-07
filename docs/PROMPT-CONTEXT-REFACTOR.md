---
summary: cadrage court du chantier prompt/contexte et decide None
read_when:
  - auditer les prompts conversation ou heartbeat
  - reduire les decide returned None
  - modifier llm_prompt_builder.py ou prompt_layers.py
  - refactorer le contexte donne a decide, final_reply ou heartbeat
  - ajouter un PromptContract ou ConversationContextPack
---

# Prompt / Context Refactor

## Statut

Chantier a lancer apres la passe excellence sportive.

Objectif : rendre les couches LLM plus fiables en reduisant le contexte inutile
et en clarifiant la responsabilite de chaque phase.

Non-objectif : ne pas ouvrir le gros refactor memoire ici.

## Diagnostic Court

FitMAS a deja de bonnes briques :

- `coach_voice.py` centralise la voix ;
- `ConversationPromptPolicy` adapte une partie du contexte par intent ;
- `prompt_layers.py` commence a separer identity/profile/plan/memory ;
- conversation et heartbeat disposent maintenant de verites runtime riches.

Le probleme restant : `_CONVERSATION_SYSTEM_TEXT` reste un mega-prompt. Il
melange identite, voix, verite, memoire, tools, mutations, confirmations,
examples, JSON contract et compat legacy.

Effet produit : le LLM doit parler, router, decider, structurer, verifier et
rester naturel dans le meme espace. Quand ca coince, on ajoute encore du prompt.
La suite doit plutot reduire les contrats par phase.

## Cible

Architecture visee :

```text
turn_planner
-> context_builder
-> decision_llm ou composer terminal
-> runtime validation / commit / block
-> final_reply_composer
-> verifier final si besoin
-> user
```

Principe : moins de prompt par phase, plus de contexte structure, plus de
composition finale apres verite runtime.

## Ordre De Travail

1. Instrumenter `decide() returned None`
   - provider, intent, prompt policy, prompt size ;
   - tool-use path ;
   - classe d'echec : no client, empty output, invalid JSON, schema invalid,
     repair failed, fallback failed, timeout, prompt too long.

2. Introduire `ConversationContextPack`
   - d'abord read-only ;
   - pas de changement comportemental au premier diff ;
   - renderers par intent.

3. Introduire `PromptContract`
   - data-only au debut ;
   - brancher progressivement sur `ConversationPromptPolicy` ;
   - faire varier le contrat system selon l'intent.

4. Decouper le mega-prompt
   - identity / voice ;
   - truth hierarchy ;
   - turn scope / permissions ;
   - action contract ;
   - output schema.

5. Ajouter snapshots et golden prompts
   - mesurer la taille ;
   - verrouiller ce qui est injecte par intent ;
   - detecter les regressions de contexte.

6. Etendre prudemment les routes simples
   - `close_turn` existe deja ;
   - etudier `casual_chat` ;
   - etudier `simple_plan_lookup` ;
   - garder pending confirmation dans une voie structuree dediee.

## Context Pack Minimal

```python
@dataclass(frozen=True, slots=True)
class ConversationContextPack:
    turn_scope: TurnScope
    temporal: TemporalContext
    planning: PlanningContext
    execution: ExecutionReality
    memory: MemoryContext
    active_thread: ActiveThreadContext
    coach_profile: CoachProfileContext
```

Memoire : garder seulement la grille conceptuelle pendant ce chantier.

```text
DurableProfile     = objectifs, sports, preferences stables
WorkingMemory      = douleur, fatigue, contrainte temporaire
ExecutionReality   = fait / pas fait / partiel / offplan
ConversationFrame  = pending, question ouverte, fil actif
```

## Prompt Contract Minimal

```python
@dataclass(frozen=True, slots=True)
class PromptContract:
    allowed_actions: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    output_schema: str
    required_truth_blocks: tuple[str, ...]
    final_reply_mode: str
```

Exemples de contrats :

```text
close_turn:
  tools = []
  actions = []
  output = final_text
  context = social thread only

plan_lookup:
  tools = read-only planning
  actions = []
  output = grounded final reply
  context = plan window + temporal truth

plan_negotiation:
  tools = planning reads + validation
  actions = PlanPatch draft
  output = structured decision
  context = planning + execution + constraints
```

## Tests Et Snapshots

Tests de contexte :

```text
test_context_pack_for_close_turn_has_no_plan
test_context_pack_for_plan_lookup_includes_plan_window
test_plan_mutation_prompt_includes_pending_confirmation
test_final_reply_never_claims_commit_if_runtime_blocked
test_heartbeat_read_only_prompt_contains_read_only_capability
```

Snapshots a ajouter :

```text
tests/snapshots/prompts/
- close_turn.txt
- plan_lookup.txt
- execution_report.txt
- plan_negotiation.txt
- heartbeat_briefing.txt
```

## Frontieres

- Pas de parser deterministe sur texte utilisateur libre.
- Pas de regex/keywords pour comprendre intention, confirmation, douleur,
  disponibilite, execution ou cible planning.
- Pas de nouvelle couche de guards textuels pour masquer un probleme de
  contexte.
- Pas de Phase B progression/prescription dans ce chantier.
- Pas de migration memoire structurelle.

## Phrase Guide

Le prochain gain ne vient pas d'un prompt coach plus long. Il vient d'un runtime
qui sait quel cerveau appeler, avec quel contexte, pour quelle responsabilite.
