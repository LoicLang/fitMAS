# FitMAS

Coach IA multisport proactif qui ajuste l'entrainement selon la vraie vie.

## Statut — 5 juin 2026

FitMAS sort du chantier "prototype runtime" et entre dans le chantier
**Produit V0 dogfoodable**.

Decision :

```text
repo actuel = enveloppe produit
runtime_v0 = noyau cible prouve
ancien pipeline = legacy a etrangler progressivement
```

Le but n'est pas de refaire FitMAS dans un nouveau repo.
Le but est de reconstruire la colonne vertebrale autour du Runtime V0, avec
des adapters vers la DB, Telegram, l'API et les writers existants.

## Cap Actuel

Phrase guide :

```text
Construire le plus petit coach Telegram auquel Loic peut faire confiance
pendant 1 a 2 semaines.
```

Le V0 dogfoodable doit :

- lire le bon plan ;
- noter et corriger l'execution ;
- adapter des seances simples ;
- demander confirmation pour les seances cles ;
- bloquer les mutations sportivement douteuses ;
- auditer chaque write ;
- rester LLM-first sur le texte utilisateur.

Ne pas ouvrir Phase B progression/prescription sans demande explicite.

## Preuve Runtime V0

Verifie offline le 5 juin 2026 :

```text
tests/runtime_v0 : 201 passed
fake matrix      : 11/11
danger metrics   : 0 wrong_write, 0 old_plan, 0 wrong_correction_target,
                   0 claim_without_event
core             : 3646 LOC (cap 3700, justifie par le moteur Meso)
```

Construit depuis : moteur Meso (`runtime_v0/meso/` — modele type + verificateur
5 proprietes dont anti-TSS-drop, bridge fact->TypedConstraint), resolution de fact
(douleur passee), fact-rider (noter un fait durable ET agir dans le meme tour).
Detail : `docs/PLANNING-V0.md`, `docs/BUILD-ORDER.md`,
`docs/superpowers/specs/2026-06-05-*`.

Provider matrix : le `114/120` historique vient d'une run a 6 scenarios
(4 providers x 6 x 5 reps = 120). La matrix par defaut compte aujourd'hui
11 scenarios x 3 providers cibles (165 runs en 5x) et l'export n'est pas committe. A rejouer
avant de citer un chiffre provider a jour.

Providers cibles :

```text
DeepSeek
Mistral
Grok
```

Gemini reste disponible en opt-in manuel, mais n'est plus dans la matrix par
defaut tant que le credit API est absent.

## Architecture De Travail

Le runtime valide suit :

```text
InputEvent
-> WorldSnapshot
-> CoachAgent
-> ActionProposal
-> Policy
-> Executor
-> RuntimeResult
-> Reply
-> Guard
-> Audit
```

Prochaine difficulte :

```text
DB actuelle -> WorldSnapshot
ActionProposal -> writes actuels audites
RuntimeResult -> Telegram/API
```

## Ordre De Lecture

1. `AGENTS.md`
2. `PROJECT.md`
3. `docs/README.md`
4. `docs/BUILD-ORDER.md`
5. `docs/V0-DOGFOOD-SCOPE.md`
6. `docs/RUNTIME-V0.md`
7. `docs/RUNTIME-MIGRATION-PLAN.md`
8. `docs/RUNBOOK.md`

## Commandes

```bash
./scripts/docs:list
pytest tests/runtime_v0
python3 scripts/v0_eval/run_matrix.py --provider fake --repetitions 1
python3 scripts/v0_eval/run_matrix.py --repetitions 5
```

## Principes

- Pas de regex/keywords sur texte utilisateur libre.
- Pas de write DB hors executor/writer officiel.
- Pas de reply visible qui affirme une mutation sans event committe.
- Pas de fallback metier improvise.
- Pas de big-bang migration.
- Pas de sophistication sportive avant fiabilite dogfood.
