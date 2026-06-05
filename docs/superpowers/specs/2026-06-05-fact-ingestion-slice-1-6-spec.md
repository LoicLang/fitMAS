---
summary: spec Slice 1.6 — ingestion fiable des facts ; noter un fait durable ne bloque jamais l'action (note + act dans le même tour).
read_when:
  - fiabiliser l'écriture des facts utilisateurs (indispo, douleur, fatigue)
  - permettre un tour qui note un fait ET agit sur le plan
  - modifier l'agent (fusion de proposals) ou la policy (rider mémoire)
---

# Spec — Slice 1.6 : Ingestion Fiable Des Facts (note + act)

Contexte : sonde couche 2 du 5 juin 2026 — une indispo de 3 jours n'était **jamais
notée** (no_send / skip ad-hoc), parce qu'un tour ne porte **qu'une seule** action
(`ActionProposal.type` unique). La douleur, elle, est bien notée. Cf.
`docs/PLANNING-V0.md` Q5 (couches de contexte).

## Objectif

Un fait **durable** (indispo fenêtre, blessure, fatigue marquée) est **noté de façon
fiable**, et **noter ne bloque jamais l'action** : "indispo 3 jours" → le coach
**note le fact ET propose l'adaptation du plan, dans le même tour**.

## Principe — "Fact rider" (Option 1 validée)

`ActionProposal.memory_updates` devient un **rider universel** : n'importe quelle
proposal d'action peut porter des faits à noter. L'agent **fusionne** un
`propose_memory_update` + une action (`propose_plan_patch` / `propose_execution_*` /
`ask_clarification`) du même tour ; la policy commit **le(s) fait(s) PUIS l'action**.

Réutilise le modèle existant (le champ est déjà là). Pas de nouveau type composite,
pas de réécriture de la boucle agent.

## Changements

### 1. Agent (`agent.py`) — fusion
Remplacer `_first_proposal` par `_merged_proposal` :
- parcourt les tool calls dans l'ordre ;
- construit **toutes** les proposals `propose_memory_update` (cumule les drafts) ;
- construit **la première** proposal d'action (les actions suivantes sont ignorées —
  comportement "first action wins" préservé, pas de build superflu) ;
- **merge** : `action` + `memory_updates = drafts cumulés + drafts de l'action` ;
- si aucune action → proposal `memory_update` (drafts cumulés) ;
- erreur de build d'un outil → même chemin d'erreur/retry qu'aujourd'hui.

Invariant préservé : 2 actions sans mémoire → la première gagne, **un seul** build
(donc `scratchpad["calls"]` inchangé pour ce cas).

### 2. Policy (`policy.py`) — rider mémoire
- extraire la validation des faits en `_validate_fact_commands(memory_updates) ->
  (commands | None, reason)` ; `_memory_update` l'utilise (réutilise les raisons
  granulaires existantes).
- déplacer le corps de `evaluate` dans `_evaluate_type` (sans le cap) ; le nouveau
  `evaluate` : calcule la décision du type, **puis** si `proposal.memory_updates` et
  `type ∉ {memory_update, no_send}` → **préfixe** les commandes de faits (validées ;
  invalide → block), **puis** applique le cap ≤ 3.
- effet : le fait est noté **quel que soit le sort de l'action** (commit / pending /
  ask_clarification / block) — noter et agir sont indépendants.

### 3. Contrat d'ingestion (`prompts/coach_system.py`) — LLM-first
Instruire : une **contrainte durable** (indispo plusieurs jours, blessure, fatigue
marquée) → **noter un fact typé** (`propose_memory_update`, `kind` availability/health,
`expires_at` si fenêtre) **ET**, si des séances sont touchées, **adapter**
(`propose_plan_patch`) **dans le MÊME tour**. Noter n'empêche pas d'agir. Zéro keyword
sur le texte user ; le LLM décide quoi/quand.

## Décisions arrêtées

- **Santé = résolution-only** (pas d'auto-expiry sur une blessure) — observé exp=∅,
  validé. Elle disparaît quand l'user dit que c'est passé (Slice 1.5).
- **Modèle availability structuré (fenêtre du/au) = différé** : pour l'instant
  `text + expires_at` suffit à noter la fenêtre. On enrichira quand le **générateur
  (2.1)** consommera "quels jours sont bloqués" — pas avant son consommateur.

## Non-objectifs
- Pas de type composite multi-action généralisé (Option 2 écartée).
- Pas de modèle availability structuré (différé).
- Pas de refonte du reply (filet chaleureux résolution ramassé seulement si retombe
  en couche 2).

## Plan de test

Unitaires :
- agent : `propose_memory_update` + `propose_plan_patch` → proposal mergée
  `type=plan_patch`, `memory_updates` peuplé ; 2 actions sans mémoire → première gagne,
  1 seul call (non-régression de `test_first_proposal_tool_wins`).
- policy : plan_patch + rider mémoire → commandes = `UpsertMemoryFactCommand` +
  action ; execution_update + rider ; fait invalide dans le rider → block ;
  memory_update seul inchangé.

Couche 2 (DeepSeek, le juge) :
- re-sonder "indispo 3 jours" → doit **noter un fact ET proposer une adaptation**
  (≥ majorité sur reps) ; non-régression matrice (danger metrics 0).

## Critère "done"
- `pytest tests/runtime_v0` vert (dont non-régression agent/policy).
- Couche 2 : indispo 3j note + adapte de façon répétée.
- Docs à jour.
