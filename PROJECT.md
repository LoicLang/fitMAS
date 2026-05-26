# FitMAS

Coach IA multisport proactif qui ajuste l'entrainement selon la vraie vie.

## Statut — 26 mai 2026

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

Dernier signal exporte :

```text
fake matrix: 6/6
provider matrix 5x: 114/120
danger metrics: 0 wrong_write, 0 old_plan, 0 wrong_correction_target,
                0 claim_without_event
```

Providers cibles :

```text
DeepSeek
Mistral
Gemini
Grok
```

Pas d'autre provider cible dans la matrice V0 actuelle.

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
