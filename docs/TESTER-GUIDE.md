---
summary: guide pour les premiers testeurs de FitMAS
read_when:
  - accueillir un nouveau testeur
  - preparer un closed alpha
  - expliquer le produit a quelqu'un
---

# FitMAS — Guide Testeur

## Ce que tu testes

Un coach IA qui comprend ton profil sportif, te donne une semaine credible, et s'adapte quand la vraie vie bouge.

Ce n'est pas une app de tracking. Ce n'est pas un programme generique. C'est un coach personnel qui apprend de toi.

## Comment demarrer

1. **Ouvre Telegram** et cherche le bot FitMAS (lien fourni par Loic)
2. **Tape `/start`** — le coach te pose des questions sur tes sports, tes contraintes, ton objectif
3. **Personnalise ton coach** — donne-lui un nom, un style, une ame
4. **Valide** — le coach te genere ta premiere semaine

Ca prend 3-5 minutes.

## Ou regarder apres

- **Telegram** : c'est ton canal de conversation avec le coach. Tu lui parles, il adapte.
- **L'app web** (the deployed app) : c'est ton cockpit. Plan de la semaine, calendrier, activites, evolution.

Pas de chat dans l'app. L'app montre, Telegram ecoute.

## Ce que tu peux faire

### Parler au coach (Telegram)

- "Je suis creve, allegeons demain"
- "Je peux pas courir mardi, on decale ?"
- "J'ai fait 1h de velo ce matin"
- "Comment je devrais aborder la seance de demain ?"

Le coach comprend le contexte et adapte le plan quand c'est pertinent.

### Actions rapides (app)

- Marquer une seance comme faite
- Signaler que tu es trop fatigue
- Voir ta semaine et tes activites

### Strava

- Connecte Strava dans l'onglet Profil
- Les activites s'importent automatiquement toutes les 2h
- Les seances se marquent faites quand une activite matche

## Ce que le coach fait tout seul

- **Briefing matin** (~7h30) : rappel de la seance du jour si pertinent
- **Rappel pre-seance** (~18h) : seulement avant les seances importantes
- **Revue hebdo** (dimanche soir) : bilan de la semaine
- **Nouveau plan** (lundi matin) : nouvelle semaine generee

Le coach ne spamme pas. Max 2 messages proactifs par jour, souvent 0 ou 1.

## Ce qu'on veut savoir

Apres 3-5 jours d'utilisation :

1. **L'onboarding etait clair ?** Tu as compris ce qu'on te demandait ?
2. **La premiere semaine te parait credible ?** Volumes, sports, equilibre ?
3. **Tu comprends l'interet du coach ?** Ou c'est flou ?
4. **Tu as envie de revenir ?** Pourquoi oui / pourquoi non ?
5. **Le coach est utile ou il parle pour rien ?** Des messages qui t'ont aide vs des messages inutiles ?
6. **Quelque chose t'a gene ou bloque ?**

Pas besoin d'un rapport formel. Un message Telegram ou un voice memo suffisent.

## Limites connues

- C'est un MVP. L'UI est sobre, pas luxueuse.
- Le coach est en francais.
- Le plan ne gere pas encore les objectifs de course (10k, marathon).
- Les activites Strava anciennes (>30 jours) n'ont pas de carte.
- Le coach apprend mais il n'a pas encore une memoire longue parfaite.

## En cas de probleme

- Si quelque chose semble casse : dis-le a Loic directement.
- Si le coach dit une betise : dis-le au coach, il apprend.
- Si l'app ne charge pas : force-refresh (tirer vers le bas sur mobile, Ctrl+Shift+R sur desktop).
