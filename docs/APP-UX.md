---
summary: contrat UX de la webapp React, focalisé sur les 3 tabs primaires, le détail séance et les surfaces secondaires
read_when:
  - modifier le frontend de l'app
  - toucher au calendrier
  - toucher a l'aperçu ou a evolution
  - changer la relation entre plan et activites
---

# FitMAS App UX

## Contrat produit

- Telegram = le coach relationnel
- App = le cockpit performance
- pas de chat dans l'app
- l'app doit rester utile en 5 secondes, sans contexte conversationnel

## Surfaces primaires

### Aperçu

But :
- montrer la séance du jour ou, à défaut, la prochaine séance utile
- servir de `daily brief`
- permettre `fait / trop fatigué / décaler`
- donner un contexte de forme court
- montrer le dernier ajustement de plan quand la semaine a bougé
- rendre visible les prochains jours sans basculer d'écran

Règles :
- c'est l'écran exécutable
- pas de surcharge analytics ici
- le type de séance doit être visible immédiatement, sans lire la description
- le top fold doit répondre à `qu'est-ce qui compte maintenant ?`
- la mission de semaine, le niveau de certitude et le dernier changement doivent être lisibles sans scroll long
- le statut de calibration global (`draft / calibrating / stable`) doit être visible sans casser le hero
- si une adaptation récente existe, elle doit exposer `ce qui a changé / ce qui est protégé / impact`
- l'écran est construit autour d'un hero immersif
- le rail des prochains jours est visuel, rapide à scanner, limité au futur proche utile (`~72h`)
- si aucune séance n'est prévue, l'état vide doit rester propre et rassurant
- les surfaces `log manuel` et `sync Strava` restent accessibles, mais secondaires
- le bloc `Pourquoi aujourd'hui` doit expliquer la logique de la séance dans la semaine, pas afficher le protocole brut
- le protocole détaillé d'une séance n'a pas sa place dans le hero ou le brief aperçu : il vit dans le détail séance

### Calendrier

But :
- être la source principale de lecture `prévu vs fait`
- montrer le réel, pas juste le plan
- permettre de comprendre vite la semaine
- montrer aussi le degré de certitude du plan

Règles :
- vue mois d'abord
- navigation mois par mois
- la semaine courante doit exposer clairement son contexte mésocycle (`week_label`, deload ou non)
- le statut de calibration global doit rester visible dans l'écran
- les cellules doivent rendre visibles `planned`, `adapted`, `done`, `missing`, `offplan`
- les entrées calendrier doivent aussi rendre visibles `committed`, `tentative`, `projected` et le rôle `key / support / recovery / optional`
- la date affichée d'une séance suit son jour réel d'exécution si elle a été faite dans le bon sport
- une activité du mauvais sport ne valide pas la séance prévue
- une activité hors plan apparaît comme une entrée distincte `hors plan`
- une séance adaptée reste visible comme telle, elle ne doit pas se faire passer pour du `planned`
- l'ouverture du détail séance se fait dans une page dédiée, pas une modal
- le calendrier doit rester cliquable et mobile-first

### Évolution

But :
- montrer la charge et les tendances
- servir de cockpit froid de pilotage
- commencer par la preuve lisible avant les graphes
- montrer aussi la vision de montée en charge à venir, pas seulement l'historique
- garder trace des adaptations recentes qui expliquent pourquoi la semaine a bouge
- rapprocher la lecture de TrainingPeaks sans perdre la DA du Figma

Règles :
- CTL / ATL / TSB visibles sans changer d'écran
- le haut d'écran doit répondre à `est-ce que je vais dans la bonne direction ?`
- si le système est encore en calibration, le haut d'écran doit le dire explicitement
- la page doit exposer la cible TSS semaine, le réel, le delta et le ramp rate
- la page doit montrer le contexte bloc / mésocycle, pas seulement des charts isolés
- la page doit expliciter si on construit, maintient ou allège la charge sur la semaine / le bloc en cours
- la répartition de charge prévue vs encaissée doit être lisible sans interprétation longue
- volume et complétion lisibles sans explication longue
- la performance lit la semaine courante réelle, pas un artefact UI
- la page n'est pas un simple historique: c'est le tableau de bord de pilotage de la charge
- la projection future est une projection calculée backend sur 4 semaines, pas une fausse timeline UI

## Surfaces secondaires

### Activités / utilitaires

But :
- être un journal brut
- servir au log manuel et à la sync

Règles :
- ce n'est pas la surface principale de lecture coaching
- ce n'est plus un onglet primaire
- la surface est accessible depuis `Aperçu` ou depuis un accès utilitaire
- si une activité est rattachée à une séance, un raccourci doit permettre d'ouvrir la bonne semaine calendrier
- si le journal et le calendrier se contredisent, le calendrier doit être privilégié pour la lecture produit

### Profil / réglages

But :
- regrouper identité, préférences, état Strava, réglages secondaires

Règles :
- ce n'est pas un tab primaire
- pas de logique critique d'exécution ici
- la page peut servir de point d'entrée aux actions admin/utilitaires non quotidiennes

## Détail séance

But :
- ouvrir une séance prévue ou réalisée dans une page dédiée immersive
- rendre la séance rechargeable directement via URL

Règles :
- route dédiée `/workout/:sessionId`
- doit fonctionner sans état mémoire préalable
- doit fusionner plan + activité liée si présente
- les métriques utiles doivent être visibles immédiatement : durée, distance, dénivelé, cardio, charge
- la DA peut être spectaculaire, mais la lisibilité et l'action priment
- la page doit séparer explicitement `objectif`, `pourquoi aujourd'hui`, `séance`, `consigne coach`, `nutrition`
- `pourquoi aujourd'hui` = rationale de placement dans la semaine, jamais le déroulé brut
- `séance` = protocole exécutable, immédiatement actionnable
- `consigne coach` = texte court athlète-facing, jamais une instruction interne système
- `trace et profil` ne doit apparaître que si une trace ou un profil a une vraie valeur pour le sport et la séance
- une séance renfo sans exercices / séries / reps / récup est considérée incomplète côté produit

## Sémantique calendrier

### Séance faite

- si une activité liée est du même sport que la séance, la séance peut se reloger sur son jour réel
- elle est alors comptée comme `faite`

### Activité hors plan

- cas 1 : aucune séance liée
- cas 2 : séance liée mais sport différent

Dans ces cas :
- on affiche une carte `hors plan`
- on garde la séance prévue séparée
- on ne compte pas cette activité comme complétion du plan

### Séance manquée

- séance passée
- pas d'activité liée du bon sport

Affichage :
- badge / bloc explicite `manqué`

## Principes de design

- mobile first
- lecture en un coup d'oeil
- peu de texte décoratif
- priorité aux dates, statuts, sport, durée, action
- une même grammaire visuelle doit traverser tous les onglets: même famille de surfaces, même hiérarchie typographique, même logique de badges
- l'app doit ressembler à un instrument de pilotage, pas à une collection de cartes disparates
- pas de patterns génériques "AI dashboard"
- la DA Figma sert de source de vérité visuelle : hero plein écran, profondeur de fond, contrastes forts, motion maîtrisée

## Règles d'implémentation frontend

- éviter d'enterrer la logique produit dans du CSS implicite
- préférer des read models backend dédiés par écran plutôt que d'assembler des objets bruts côté React
- préférer des loaders par route à un bootstrap global monolithique
- nommer explicitement les états UI : `offplan`, `planned`, `done`, `missing`
- quand une règle devient subtile, la documenter ici
- si un agent change le contrat `prévu / fait / hors plan`, il doit mettre à jour `PRODUCT.md` et ce document

## Anti-patterns

- faire apparaître une activité du mauvais sport comme séance faite
- utiliser l'onglet activités comme vérité principale
- laisser des compteurs de complétion mentir par rapport au calendrier
- ajouter du chat dans l'app
- casser la navigation semaine sans doc de remplacement
