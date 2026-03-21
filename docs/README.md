---
summary: point d'entrée documentaire du projet
read_when:
  - commencer à travailler sur le projet
  - chercher un document
---

# Docs

5 documents essentiels :

| Document | Contenu |
|----------|---------|
| `PRODUCT.md` | Vision, wedge multisport, scope, parcours utilisateur, critères de succès |
| `ARCHITECTURE.md` | Stack, modèle de données, flux techniques, décisions tranchées |
| `SOUL.md` | Voix FitMAS, heartbeat, messagerie, exemples de ton |
| `BUILD-ORDER.md` | État actuel, plan de priorités, prochaines phases |
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
4. `SOUL.md`
5. `BUILD-ORDER.md`
6. `RUNBOOK.md`

## Archive

Les anciens documents de cadrage (30+ fichiers v1) sont dans `docs/archive/`.
Ils ont été condensés dans les 5 docs ci-dessus.
Le runbook actuel complète ces docs pour l'exploitation quotidienne.
