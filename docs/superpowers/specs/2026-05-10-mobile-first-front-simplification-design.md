---
summary: design front mobile-first pour dogfood FitMAS app
read_when:
  - simplifier le frontend FitMAS
  - modifier aperçu, calendrier ou évolution
---

# Mobile-First Front Simplification Design

## Goal

Rendre l'app FitMAS plus utile en dogfood quotidien sans toucher au backend.

## Scope

- `Aperçu` devient la surface `À venir` : séance du jour/prochaine séance, prochaines séances, accès entraînement.
- `Calendrier` reste le planning mensuel : prévu, fait, manqué, adapté, hors plan.
- `Évolution` devient un dashboard simple : stats clés et petits graphiques.
- Les routes, loaders et read models existants restent inchangés.

## Design

Conserver la DA actuelle : fond clair profond, Space Grotesk, accent orange, panels translucides, icônes lucide, motion sobre.

Réduire la narration coach dans l'app. Telegram porte la relation. L'app porte la lecture rapide :

- quoi faire maintenant ;
- ce qui arrive ensuite ;
- ce qui était prévu ou fait ;
- est-ce que la charge évolue correctement.

## Frontend Contract

- Aucun changement backend.
- Aucun assemblage de vérité métier nouvelle côté front.
- Utiliser seulement les payloads `overview`, `calendar`, `evolution`.
- Garder `/workout/:sessionId` comme accès détail.
- Mobile-first : les cartes doivent être lisibles sur largeur téléphone sans scroll horizontal obligatoire.

## Testing

- Tests route sur les libellés produit principaux.
- Build Vite.
- Vérification locale visuelle après lancement du serveur front.
