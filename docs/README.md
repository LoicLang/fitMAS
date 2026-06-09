---
summary: point d'entree documentaire du projet
read_when:
  - commencer a travailler sur le projet
  - chercher un document
---

# Docs

## Regle

Les docs actives doivent aider un agent a agir vite.
Les journaux de refactor et plans termines vont dans `docs/archive/`.

```bash
./scripts/docs-list
./scripts/docs-list --all
```

## Lecture Recommandee

1. `PROJECT.md` — cap repo court.
2. `docs/BUILD-ORDER.md` — suite immediate.
3. `docs/V0-DOGFOOD-SCOPE.md` — produit V0 dogfoodable.
4. `docs/RUNTIME-V0.md` — noyau runtime prouve.
5. `docs/RUNTIME-MIGRATION-PLAN.md` — integration progressive.
6. `docs/RUNBOOK.md` — commandes.

Puis lire seulement le doc domaine utile.

## Docs Actives

| Doc | Role |
| --- | --- |
| `BUILD-ORDER.md` | etat court, prochain chantier, gates |
| `V0-DOGFOOD-SCOPE.md` | scope produit V0 et Sport Core minimal |
| `PLANNING-V0.md` | architecture moteur sport V0 : LLM genere, verif tient l'autorite, co-evolue runtime |
| `RUNTIME-V0.md` | reference courte du prototype runtime |
| `V0-CODE-MAP.md` | code map detaillee : architecture, role de chaque fichier, agent/tools/prompts, moteur Meso |
| `RUNTIME-MIGRATION-PLAN.md` | migration vers Telegram/API dogfood |
| `RUNTIME-V0-APP-COMPARISON.md` | resultats app-vs-V0 sur tours reels (legacy, voir doctrine) |
| `V0-TEST-DOCTRINE.md` | doctrine de test : matrice mecanique + simulation live |
| `LLM-FIRST-CONVERSATION.md` | doctrine zero determinisme sur texte user |
| `RUNTIME-TOOLS.md` | contrat des tools runtime |
| `CONVERSATION.md` | etat du runtime conversationnel existant |
| `PRODUCT.md` | promesse et scope produit general |
| `ARCHITECTURE.md` | stack et frontieres repo |
| `SYSTEM-MAP.md` | carte d'ensemble du systeme |
| `PLANNING.md` | contrat planner large, hors prochaine tranche |
| `ADAPTATION-CANDIDATE-PIPELINE.md` | pipeline planning historique/courant |
| `SPORT-QUALITY-REVIEW.md` | review sportive, utile mais pas Phase B |
| `MEMORY-V2.md` | architecture memoire |
| `APP-UX.md` | contrat UX app |
| `SOUL.md` | voix et ton FitMAS |
| `RUNBOOK.md` | commandes locales et smokes |
| `TESTER-GUIDE.md` | guide testeurs |

## Archive

Archive recente :

```text
docs/archive/runtime-v0-implementation-spec-2026-05-24.md
docs/archive/refactor-2026-05-22/
```

Ces fichiers expliquent le passe.
Ils ne tranchent plus le prochain chantier.

## Hierarchie De Verite

En cas de contradiction :

1. `BUILD-ORDER.md` gagne sur l'etat et la prochaine action.
2. `V0-DOGFOOD-SCOPE.md` gagne sur le scope V0.
3. `RUNTIME-MIGRATION-PLAN.md` gagne sur l'integration V0.
4. `RUNTIME-V0.md` gagne sur le noyau prototype.
5. `LLM-FIRST-CONVERSATION.md` gagne sur la doctrine user-text.
6. `PRODUCT.md` gagne sur la promesse produit large.
7. `V0-TEST-DOCTRINE.md` gagne sur la methodologie de test.

## Hygiene

- chaque doc active doit avoir front matter `summary` + `read_when` ;
- garder les docs actives courtes ;
- archiver les plans termines ;
- eviter les doublons de statut ;
- preferer un gate de test a une longue explication.
