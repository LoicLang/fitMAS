---
summary: comment FitMAS interprete les reponses utilisateur en langage naturel sans casser la fluidite conversationnelle
read_when:
  - gerer les reponses WhatsApp libres
  - implementer l'extraction de feedback
  - comprendre comment traduire du langage naturel en actions produit
  - preparer une V0 conversationnelle
---

# Natural Language Replies V1

## Principe

L'utilisateur doit pouvoir parler naturellement.

FitMAS ne doit pas lui imposer:

- des boutons
- des formats rigides
- des menus caches

Mais cela ne veut pas dire que le systeme doit "tout comprendre".

Le bon systeme V1 fait quelque chose de plus simple:

- il extrait quelques signaux utiles
- il garde le reste comme contexte
- il demande une clarification si besoin

## Ce que FitMAS cherche vraiment dans une reponse

Dans beaucoup de cas, FitMAS n'a besoin que de 1 a 3 elements:

- disponibilite
- contrainte
- ressenti
- niveau d'adhesion
- incertitude

Pas besoin d'une comprehension parfaite de toute la phrase.

## Exemples

### Exemple 1

Message user:

- "mardi ca sent pas bon, plutot jeudi"

Extraction utile:

- creneau mardi negatif
- jeudi possible
- confiance assez haute

Action:

- ajuster la seance
- confirmer dans l'app

### Exemple 2

Message user:

- "la semaine prochaine je bouge beaucoup"

Extraction utile:

- semaine prochaine contrainte
- planning incertain
- besoin de clarification

Action:

- poser une question courte
- "Tu sais deja quels jours sont les plus compliques ?"

### Exemple 3

Message user:

- "j'ai un diner jeudi"

Extraction utile:

- jeudi soir contraint

Action:

- mettre a jour la semaine
- eventuellement enrichir une memoire si le pattern se repete

### Exemple 4

Message user:

- "jambes lourdes mais cardio ok"

Extraction utile:

- fatigue musculaire
- cardio acceptable

Action:

- ajuster la suite si necessaire
- enrichir le modele de recuperation

## Pipeline recommande

Quand une reponse libre arrive:

1. stocker le message brut
2. generer un petit resume thread si utile
3. lancer un extracteur structure
4. obtenir une sortie simple et bornée
5. decider:
   - action directe
   - clarification
   - no-op

## Sortie attendue de l'extracteur

L'extracteur ne doit pas produire un roman.

Il doit produire un schema court du type:

- intent principal
- contraintes mentionnees
- disponibilites mentionnees
- ressenti mentionne
- niveau de confiance
- memoire potentielle a ecrire ou non
- besoin de clarification ou non

## Regle critique

Ne pas transformer automatiquement chaque phrase en memoire durable.

Exemple:

- "cette semaine c'est le bazar"

Ce n'est pas necessairement une preference durable.
C'est peut-etre seulement un contexte temporaire.

## Ce qui doit devenir memoire durable

Oui, si:

- c'est stable
- c'est personnel
- c'est actionnable
- c'est repete ou confirme

Non, si:

- c'est ponctuel
- trop ambigu
- trop contextuel

## Que faire quand ce n'est pas clair

Ne pas deviner trop loin.

Envoyer une clarification courte.

Exemple:

- "Je peux deplacer jeudi, mais j'ai besoin de savoir si vendredi reste dispo."

## Ambition V0

La V0 n'a pas besoin d'une extraction conversationnelle parfaite.

Elle a besoin de bien comprendre:

- disponibilites
- contraintes
- ressenti simple
- feedback seance
- signaux d'adherence

Si FitMAS est bon la-dessus,
la conversation paraitra deja tres naturelle.

## Architecture conseillee

V0:

- extracteur simple a sortie structuree
- quelques intents cibles
- fallback clarification

Plus tard:

- extraction plus riche
- meilleure distinction entre contexte temporaire et trait durable
- apprentissage plus fin

## Ce qu'il faut eviter

- surinterpreter
- memoriser trop vite
- faire semblant de tout comprendre
- repondre avec trop d'assurance quand le message est ambigu

## Regle simple

En V0, FitMAS doit etre meilleur pour:

- bien comprendre l'utile

que pour:

- tout comprendre
