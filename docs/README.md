---
summary: point d'entree documentaire du projet
read_when:
  - commencer a travailler sur le projet
  - chercher un document
---

# Docs

## Regle

Les docs doivent aider un agent a agir vite.
Le journal de chantier n'est pas une source de verite active.

Pour tout audit complet :

```bash
./scripts/docs:list --all
```

Par defaut :

```bash
./scripts/docs:list
```

liste seulement les docs actives.

## Lecture Recommandee

1. `PROJECT.md` — entree repo courte.
2. `docs/BUILD-ORDER.md` — etat actuel et prochaine tranche.
3. `docs/DECISION-RUNTIME-REFACTOR.md` — architecture canonique.
4. `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md` — legacy restant.
5. `docs/SYSTEM-MAP.md` — carte rapide.
6. `docs/RUNBOOK.md` — commandes et smokes.

Puis lire seulement le doc domaine utile.

## Docs Actives

| Doc | Role |
| --- | --- |
| `BUILD-ORDER.md` | etat court, prochaine tranche, verification minimale |
| `DECISION-RUNTIME-REFACTOR.md` | architecture canonique du runtime |
| `DECISION-RUNTIME-LEGACY-KILL-LIST.md` | surfaces legacy restantes et ordre de coupe |
| `ROOT-MODULE-CENSUS.md` | ownership des modules root restants |
| `SYSTEM-MAP.md` | carte d'ensemble du systeme |
| `RUNBOOK.md` | commandes locales, smokes, debug |
| `PRODUCT.md` | promesse et scope produit |
| `ARCHITECTURE.md` | stack et contraintes techniques |
| `LLM-FIRST-CONVERSATION.md` | doctrine zero determinisme sur texte user |
| `PLANNING.md` | contrat planning produit/moteur |
| `ADAPTATION-CANDIDATE-PIPELINE.md` | adaptation planning par candidats |
| `SPORT-QUALITY-REVIEW.md` | review sportive et coherence semaine |
| `RUNTIME-TOOLS.md` | contrat des tools runtime |
| `CONVERSATION.md` | grounding conversationnel |
| `MEMORY-V2.md` | architecture memoire |
| `APP-UX.md` | contrat UX app |
| `SOUL.md` | voix et ton FitMAS |
| `TESTER-GUIDE.md` | guide testeurs |

## Archive

`docs/archive/` contient :

- anciens cadrages v1 ;
- longs journaux de refactor ;
- docs absorbes par le Decision Runtime ;
- audits historiques.

Ces fichiers peuvent expliquer le passe.
Ils ne tranchent plus l'architecture.

## Hierarchie De Verite

En cas de contradiction :

1. `BUILD-ORDER.md` gagne sur l'etat reel et la suite.
2. `DECISION-RUNTIME-REFACTOR.md` gagne sur l'architecture runtime.
3. `DECISION-RUNTIME-LEGACY-KILL-LIST.md` gagne sur la suppression legacy.
4. `LLM-FIRST-CONVERSATION.md` gagne sur la doctrine user-text.
5. `PRODUCT.md` gagne sur le scope produit.

## Hygiene

- chaque doc doit avoir front matter `summary` + `read_when`;
- ne pas ajouter de plan daté dans `docs/` sans intention durable ;
- si un doc devient historique, l'archiver ou le supprimer ;
- garder les docs actives courtes ;
- preferer un gate de test a une longue explication.
