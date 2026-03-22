---
summary: contrat UX de la webapp, surtout calendrier, aujourd'hui, performance et journal d'activités
read_when:
  - modifier le frontend de l'app
  - toucher au calendrier
  - toucher a today ou performance
  - changer la relation entre plan et activites
---

# FitMAS App UX

## Contrat produit

- Telegram = le coach relationnel
- App = le cockpit performance
- pas de chat dans l'app
- l'app doit rester utile en 5 secondes, sans contexte conversationnel

## Onglets

### Aujourd'hui

But :
- montrer la séance du jour
- permettre `fait / trop fatigué / décaler`
- donner un minimum de contexte de forme

Règles :
- c'est l'écran exécutable
- pas de surcharge analytics ici
- si aucune séance n'est prévue, l'état vide doit rester propre et rassurant

### Calendrier

But :
- être la source principale de lecture `prévu vs fait`
- montrer le réel, pas juste le plan
- permettre de comprendre vite la semaine

Règles :
- la séance du jour est mise en avant en haut
- navigation standard semaine par semaine
- la liste de la semaine est inversée : plus récent en haut, plus ancien en bas
- la date affichée d'une séance suit son jour réel d'exécution si elle a été faite dans le bon sport
- une activité du mauvais sport ne valide pas la séance prévue
- une activité hors plan apparaît comme une entrée distincte `hors plan`
- le calendrier doit rester cliquable et mobile-first

### Performance

But :
- montrer la charge et les tendances
- servir de cockpit froid

Règles :
- CTL / ATL / TSB visibles
- volume et complétion lisibles sans explication longue
- la performance lit la semaine courante réelle, pas un artefact UI

### Activités

But :
- être un journal brut
- servir au log manuel et à la sync

Règles :
- ce n'est pas la surface principale de lecture coaching
- si une activité est rattachée à une séance, un raccourci doit permettre d'ouvrir la bonne semaine calendrier
- si le journal et le calendrier se contredisent, le calendrier doit être privilégié pour la lecture produit

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
- pas de patterns génériques "AI dashboard"

## Règles d'implémentation frontend

- éviter d'enterrer la logique produit dans du CSS implicite
- nommer explicitement les états UI : `offplan`, `planned`, `done`, `missing`
- quand une règle devient subtile, la documenter ici
- si un agent change le contrat `prévu / fait / hors plan`, il doit mettre à jour `PRODUCT.md` et ce document

## Anti-patterns

- faire apparaître une activité du mauvais sport comme séance faite
- utiliser l'onglet activités comme vérité principale
- laisser des compteurs de complétion mentir par rapport au calendrier
- ajouter du chat dans l'app
- casser la navigation semaine sans doc de remplacement
