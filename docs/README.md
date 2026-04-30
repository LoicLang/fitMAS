---
summary: point d'entree documentaire du projet
read_when:
  - commencer a travailler sur le projet
  - chercher un document
---

# Docs

## Set documentaire actuel

| Document | Contenu |
|----------|---------|
| `BUILD-ORDER.md` | Source de verite sur l'etat reel, les priorites et la dette technique |
| `LLM-FIRST-CONVERSATION.md` | Doctrine zero determinisme sur texte utilisateur libre + plan de migration conversation |
| `ARCHITECTURE.md` | Stack, principes de harness, modele de donnees, flux techniques |
| `SYSTEM-MAP.md` | Carte du systeme : flux, frontieres LLM/tools/skills, points d'extension |
| `PRODUCT.md` | Vision, wedge multisport, scope, parcours utilisateur |
| `COACH-COHERENCE-REFACTOR.md` | Gouvernance etat : verite runtime unique, writer unique, bundle partage, gates |
| `PLANNING.md` | Contrat produit + moteur V2 de la planification adaptative |
| `CONVERSATION.md` | Grounding conversationnel, doctrine LLM-first, dette active des anciens extracteurs |
| `MEMORY-V2.md` | Architecture memoire : profile vs working vs patterns, regles et migration |
| `RUNTIME-TOOLS.md` | Contrat des tools runtime multi-tool bornes, registre read-only/candidate/validation, limites et metriques |
| `APP-UX.md` | Contrat UX de la webapp : calendrier, today, performance |
| `SOUL.md` | Voix FitMAS, heartbeat, messagerie, ton |
| `RUNBOOK.md` | Commandes, flux a tester, debug, deploiement, mapping du code |
| `TESTER-GUIDE.md` | Guide d'onboarding pour les testeurs alpha |
| `CONVERSATION-AUDIT-2026-04-17.md` | Audit architecture conversation + contexte post-passe de fiabilite |
| `COACH-AUTONOMY-REFACTOR.md` | Refonte coach : suppression court-circuits, tools de lecture brute, skill replan validé, posture "DÉCIDE" |
| `COACH-AUTONOMY-AUDIT.md` | Inventaire system prompts + court-circuits du pipeline coach (sortie du Chantier 0) |

## Hierarchie de verite

Quand plusieurs docs semblent raconter des choses differentes :

1. `BUILD-ORDER.md` gagne pour l'etat reel et les priorites
2. `LLM-FIRST-CONVERSATION.md` gagne sur la doctrine conversation : aucun regex/keyword/parser deterministe sur texte utilisateur libre
3. `PRODUCT.md` gagne pour la promesse produit et le scope
4. `ARCHITECTURE.md` gagne pour la structure technique et les contraintes
5. les docs domaine gagnent pour leur contrat local

## Ordre de lecture

Pour un nouvel agent :

1. `BUILD-ORDER.md` — etat reel et suite Phase A / Phase B
2. `LLM-FIRST-CONVERSATION.md` — doctrine zero determinisme sur texte user
3. `COACH-AUTONOMY-REFACTOR.md` — historique de refactor autonomie
4. `SYSTEM-MAP.md` — carte d'ensemble
5. `RUNTIME-TOOLS.md` — tools multi-tool bornes et workflow `replan_after_constraint`
6. `CONVERSATION.md` — grounding + indications
7. `RUNBOOK.md` — ops, smokes, debug prod
8. `ARCHITECTURE.md` — stack, principes, modules
9. `PRODUCT.md` — vision et scope
10. `COACH-COHERENCE-REFACTOR.md` — gouvernance state/mutations
11. `PLANNING.md` — contrat + moteur planning
12. `MEMORY-V2.md` — memoire utilisateur
13. `APP-UX.md` — contrat UX app
14. `SOUL.md` — voix coach

## Raccourcis

| Question | Doc |
|----------|-----|
| Ou en est le repo et que construit-on ensuite ? | `BUILD-ORDER.md` |
| Quelle est la doctrine conversation LLM-first ? | `LLM-FIRST-CONVERSATION.md` |
| Comment fonctionne FitMAS dans son ensemble ? | `SYSTEM-MAP.md` |
| Quel contrat produit ? | `PRODUCT.md` |
| Quelle fondation technique ? | `ARCHITECTURE.md` |
| Comment retablir une verite unique coach/app/planning ? | `COACH-COHERENCE-REFACTOR.md` |
| Comment evoluer le planner ? | `PLANNING.md` |
| Pourquoi le coach se trompe sur le reel, le temps ou l'intention ? | `CONVERSATION.md` |
| Comment evoluer la memoire sans fourre-tout ? | `MEMORY-V2.md` |
| Comment brancher des tools runtime ? | `RUNTIME-TOOLS.md` |
| Quelle est la prochaine tranche avant dogfood ? | `BUILD-ORDER.md` |
| Comment l'app doit se comporter ? | `APP-UX.md` |
| Pourquoi le coach hallucine, agrege au lieu de detailler, demande au lieu de decider ? | `COACH-AUTONOMY-REFACTOR.md` |

## Regles

- Chaque doc a un front matter `summary` + `read_when`
- Quand le comportement change, mettre a jour le doc concerne
- Pas de doc jetable

## Archive

Les anciens documents (cadrage v1, docs absorbes, journaux de refactor termines) sont dans `docs/archive/`.
