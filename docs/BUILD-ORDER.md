---
summary: source de verite courte sur l'etat actuel et le prochain chantier
read_when:
  - commencer un chantier
  - verifier la suite immediate
  - recadrer le scope avant de coder
---

# Build Order

## Phrase Guide

```text
Le plus petit coach Telegram fiable pour 1 a 2 semaines de dogfood.
```

## Etat Actuel — 26 mai 2026

Le Runtime V0 a valide le noyau et le premier Sport Core minimal :

```text
InputEvent -> Snapshot -> Agent -> Proposal -> Policy -> Executor
-> Result -> Reply -> Guard -> Audit
```

Preuve (verifiee offline le 29 mai 2026) :

- `tests/runtime_v0` : 135 passed ;
- fake matrix : `11/11` ;
- danger metrics : `0 wrong_write`, `0 old_plan`,
  `0 wrong_correction_target`, `0 claim_without_event` ;
- core : 3053 LOC (zone acceptable).

Provider matrix : `114/120` est une ancienne run a 6 scenarios. La matrix
compte 11 scenarios aujourd'hui. Export non committe, a rejouer pour un
chiffre provider a jour.

Le chantier actif n'est plus un shrink de l'ancien runtime historique.
C'est la preparation d'un **Produit V0 dogfoodable** autour de
`backend/src/fitmas/runtime_v0/`.

## Decision D'Architecture

```text
repo actuel = enveloppe produit
runtime_v0 = noyau cible prouve
ancien pipeline = legacy a etrangler
```

Ne pas creer de nouveau repo.
Ne pas migrer Telegram en big-bang.
Ne pas supprimer l'ancien pipeline avant preuve sur adapters.

## Prochaine Tranche

Ordre recommande :

1. Relancer une provider matrix ciblee sur les 11 scenarios.
2. Construire un `WorldSnapshot` depuis une copie DB actuelle.
3. Construire un executor adapter vers les writers existants.
4. Brancher Telegram/API sous flag et allowlist user.

## Scope Actif

Lire :

- `docs/V0-DOGFOOD-SCOPE.md` pour le produit V0 ;
- `docs/RUNTIME-V0.md` pour le noyau actuel ;
- `docs/RUNTIME-MIGRATION-PLAN.md` pour l'integration ;
- `docs/LLM-FIRST-CONVERSATION.md` pour la doctrine texte utilisateur.

Le V0 couvre :

- plan actuel / aujourd'hui / demain ;
- execution `done`, `skipped`, `partial` ;
- correction d'execution ;
- move/lighten/replace simple ;
- pending pour seance cle ;
- block pour risque sportif clair ;
- heartbeat read-only ou question courte seulement.

## Hors Scope

Ne pas ouvrir sans demande explicite :

- Phase B progression/prescription ;
- replan complet long terme ;
- periodisation multi-mois ;
- nutrition ;
- multi-agent ;
- memoire vectorielle/reflexive ;
- heartbeat qui auto-commit une mutation ;
- UI de decision complexe.

## Providers

Providers a tester en V0 :

```text
DeepSeek
Mistral
Gemini
Grok
```

Pas d'autre provider cible dans la matrice V0 actuelle.

## Gates Dogfood

Avant Telegram V0 :

```text
>= 90% correctness sur scenarios V0 produit
0 danger metrics
0 duplicate command sur retry
guard fallback rate < 15%
```

La latence est mesuree, mais ne bloque pas le dogfood tant que la reponse est
fiable.

## Verification Minimale

```bash
./scripts/docs:list
pytest tests/runtime_v0
python3 scripts/v0_eval/run_matrix.py --provider fake --repetitions 1
python3 scripts/v0_eval/run_matrix.py --repetitions 5
```

Exports utiles :

```text
exports/runtime-v0/stability-fake-final
exports/runtime-v0/stability-providers-5x
```

## Regles Dures

- Le LLM comprend le texte utilisateur et produit des artefacts structures.
- Le backend valide, autorise, commit et audite.
- Aucun regex/keyword sur texte utilisateur libre.
- Aucun write DB hors executor/writer officiel.
- Aucune reply visible ne doit mentir sur un write.
- `runtime_v0` reste isole tant que les adapters ne sont pas prouves.
