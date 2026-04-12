---
summary: point d'entrée documentaire du projet
read_when:
  - commencer à travailler sur le projet
  - chercher un document
---

# Docs

Set documentaire actuel :

| Document | Contenu |
|----------|---------|
| `PRODUCT.md` | Vision, wedge multisport, scope, parcours utilisateur, critères de succès |
| `SYSTEM-MAP.md` | Carte simple du système : flux, frontières LLM/tools/skills/orchestrateurs et points d'extension |
| `ARCHITECTURE.md` | Stack, modèle de données, flux techniques, décisions tranchées |
| `APP-UX.md` | Contrat UX de la webapp : calendrier, today, performance, journal |
| `PLANNING-ENGINE-V2.md` | Plan adapte du moteur V2, sequence d'implementation et mapping avec le code actuel |
| `PLANNING-CONTRACT.md` | Contrat produit/technique de la planification adaptative, horizons de verite et ordre d'implementation |
| `MEMORY-V2.md` | Architecture memoire V2 : profile vs working vs patterns, regles d'ecriture/lecture et plan de migration |
| `CONVERSATION-GROUNDING.md` | Référence du grounding Telegram : hiérarchie de vérité, résolution temporelle et durcissements résiduels |
| `COACH-COHERENCE-REFACTOR.md` | Plan canonique du refactor coherence coach/app/planning : verite runtime unique, writer unique, bundle partage et gates de verification |
| `REALITY-WORKOUT-CONTRACT.md` | Référence du contrat vérité d'exécution et contenu séance, avec état du chantier désormais largement absorbé |
| `USER-INDICATIONS.md` | Contrat des indications utilisateur: interpretation, grounding planning, mutation et explication |
| `RUNTIME-TOOLS.md` | Contrat des tools runtime, registre V1 read-only, limites et métriques |
| `CLAUDE-CODE-LEARNINGS.md` | Analyse externe du harness Claude Code et patterns utiles pour faire évoluer FitMAS sans sur-réagir au multi-agent |
| `HARNESS-REFACTOR.md` | Plan de refactor du harness, phases, statut et checks de verification |
| `SOUL.md` | Voix FitMAS, heartbeat, messagerie, exemples de ton |
| `BUILD-ORDER.md` | Source de vérité sur l'état réel du repo, l'ordre de priorité et ce qui n'est plus un TODO |
| `RUNBOOK.md` | Commandes, flux à tester, debug, déploiement, mapping rapide du code |

## Hiérarchie de vérité

Quand plusieurs docs semblent raconter des choses différentes :

1. `BUILD-ORDER.md` gagne pour :
   - ce qui existe vraiment dans le code
   - ce qu'on construit ensuite
2. `PRODUCT.md` gagne pour :
   - la promesse produit
   - le wedge
   - le scope
3. `ARCHITECTURE.md` gagne pour :
   - la structure technique
   - les contraintes
   - les modules live
4. les docs domaine gagnent pour leur contrat local

## Règles

- Chaque doc a un front matter `summary` + `read_when`
- Quand le comportement change, mettre à jour le doc concerné
- Pas de doc jetable. Si ça ne survit pas à la conversation, ça ne rentre pas ici.

## Ordre de lecture conseillé

Pour un nouvel agent :
1. `README.md`
2. `BUILD-ORDER.md`
3. `SYSTEM-MAP.md`
4. `PRODUCT.md`
5. `ARCHITECTURE.md`
6. `APP-UX.md`
7. `PLANNING-ENGINE-V2.md`
8. `PLANNING-CONTRACT.md`
9. `MEMORY-V2.md`
10. `CONVERSATION-GROUNDING.md`
11. `REALITY-WORKOUT-CONTRACT.md`
12. `USER-INDICATIONS.md`
13. `RUNTIME-TOOLS.md`
14. `COACH-COHERENCE-REFACTOR.md`
15. `CLAUDE-CODE-LEARNINGS.md`
16. `HARNESS-REFACTOR.md`
17. `SOUL.md`
18. `RUNBOOK.md`

Raccourci utile :
- si le sujet est "où en est vraiment le repo et que construit-on ensuite ?", lire `BUILD-ORDER.md`
- si le sujet est "comment fonctionne FitMAS dans son ensemble ?", lire `SYSTEM-MAP.md`
- si le sujet est "quel est le bon contrat produit ?", lire `PRODUCT.md`
- si le sujet est "quelle fondation technique avant d'ajouter de la sophistication ?", lire `ARCHITECTURE.md`
- si le sujet est "comment l'app doit se comporter ?", lire `APP-UX.md`
- si le sujet est "comment faire evoluer le planner ?", lire `PLANNING-ENGINE-V2.md`
- si le sujet est "quel est le contrat exact de la planification adaptative ?", lire `PLANNING-CONTRACT.md`
- si le sujet est "comment evoluer la memoire utilisateur sans recreer un fourre-tout ?", lire `MEMORY-V2.md`
- si le sujet est "pourquoi le coach Telegram se trompe sur le reel ou le temps ?", lire `CONVERSATION-GROUNDING.md`
- si le sujet est "comment retablir une verite unique entre coach, app et planning live ?", lire `COACH-COHERENCE-REFACTOR.md`
- si le sujet est "comment fiabiliser le vrai/faux done, adapter la semaine au réel et remettre le bon contenu séance dans l'app ?", lire `REALITY-WORKOUT-CONTRACT.md`
- si le sujet est "comment transformer un message user en event candidate solide ?", lire `USER-INDICATIONS.md`
- si le sujet est "comment brancher des tools runtime au LLM sans casser l'architecture ?", lire `RUNTIME-TOOLS.md`
- si le sujet est "quels patterns agentiques/harness valent vraiment le coup pour FitMAS ?", lire `CLAUDE-CODE-LEARNINGS.md`
- si le sujet est "dans quel ordre refactorer le harness et quel est le statut ?", lire `HARNESS-REFACTOR.md`

## Archive

Les anciens documents de cadrage (30+ fichiers v1) sont dans `docs/archive/`.
Ils ont ete remplaces par le set documentaire actuel.
Le runbook actuel complete ces docs pour l'exploitation quotidienne.
