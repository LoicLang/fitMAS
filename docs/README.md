---
summary: point d'entrée documentaire du projet
read_when:
  - commencer à travailler sur le projet
  - chercher un document
---

# Docs

6 documents essentiels :

| Document | Contenu |
|----------|---------|
| `PRODUCT.md` | Vision, wedge multisport, scope, parcours utilisateur, critères de succès |
| `ARCHITECTURE.md` | Stack, modèle de données, flux techniques, décisions tranchées |
| `APP-UX.md` | Contrat UX de la webapp : calendrier, today, performance, journal |
| `SOUL.md` | Voix FitMAS, heartbeat, messagerie, exemples de ton |
| `BUILD-ORDER.md` | État actuel, roadmap recommandée, ordre de priorités |
| `RUNBOOK.md` | Commandes, flux à tester, debug, déploiement, mapping rapide du code |

## Règles

- Chaque doc a un front matter `summary` + `read_when`
- Quand le comportement change, mettre à jour le doc concerné
- Pas de doc jetable. Si ça ne survit pas à la conversation, ça ne rentre pas ici.

## Ordre de lecture conseillé

Pour un nouvel agent :
1. `README.md`
2. `PRODUCT.md`
3. `ARCHITECTURE.md`
4. `APP-UX.md`
5. `SOUL.md`
6. `BUILD-ORDER.md`
7. `RUNBOOK.md`

Raccourci utile :
- si le sujet est "que faut-il construire maintenant ?", lire `BUILD-ORDER.md`
- si le sujet est "quel est le bon contrat produit ?", lire `PRODUCT.md`
- si le sujet est "quelle fondation technique avant d'ajouter de la sophistication ?", lire `ARCHITECTURE.md`
- si le sujet est "comment l'app doit se comporter ?", lire `APP-UX.md`

## Archive

Les anciens documents de cadrage (30+ fichiers v1) sont dans `docs/archive/`.
Ils ont été condensés dans les 5 docs ci-dessus.
Le runbook actuel complète ces docs pour l'exploitation quotidienne.
