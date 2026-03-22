---
summary: vision produit, wedge multisport, scope actuel, ICP, parcours utilisateur et critères de succès
read_when:
  - comprendre le produit
  - arbitrer le scope
  - vérifier si une idée rentre dans le scope
  - designer une feature
---

# FitMAS Product

## Une phrase

FitMAS est un coach IA multisport proactif qui ajuste ton entraînement selon ta vraie vie.

## Promesse

- mieux performer sur la durée
- moins réfléchir, moins planifier
- avoir le sentiment d'être suivi par quelqu'un qui te connaît

La promesse externe est "mieux performer".
Le mécanisme interne ressenti est "moins de charge mentale".

## Contrat produit

- **Telegram = le coach** : conversation naturelle, adaptations, questions, proactivité
- **App = le cockpit** : calendrier, charge, exécution, progression, graphes
- Le chat ne vit pas dans l'app
- L'app doit pouvoir être ouverte sans contexte conversationnel et rester immédiatement utile

## ICP

- sportif engagé multisport (3+ séances/semaine)
- agenda parfois instable
- intéressé par la personnalisation
- à l'aise avec un setup initial de 15-20 minutes
- tone preference : direct, pas cheerleader

## Wedge : multisport personnel

Sports supportés :
- running (trail / route)
- cycling (route / gravel)
- swimming (piscine / eau libre)
- climbing (bloc / voie)
- strength (renfo fonctionnel)
- rest

Pourquoi multisport et pas running seul :
- c'est la vraie pratique de l'ICP
- la charge cross-sport est le vrai enjeu d'arbitrage
- l'escalade et le renfo ne sont pas sur Strava → le manuel est indispensable
- un coach qui gère le multi est bien plus crédible qu'un coach running

Ce qu'on ne fait pas encore :
- périodisation avancée par discipline
- nutrition complexe / meal planning
- triathlon structuré
- SaaS multi-user

## Ce que FitMAS sait faire aujourd'hui

### 1. Onboarding (Telegram, ~15 min)

Via `/start` sur le bot Telegram :
1. **Sports pratiqués** — sélection multiple
2. **Objectif principal** — texte libre
3. **Réalité de semaine** — créneaux, jours forts/fragiles
4. **Contraintes** — blessures, matériel, horaires
5. **Préférences** — terrain, style de renfo, etc.
6. **Création du coach** — nom, style, do/dont, âme
7. **Preview de voix** — le coach parle avant que tu valides
8. **Récap final** — ce que FitMAS a compris

### 2. Plan hebdomadaire multisport

- Généré par un planner déterministe (`planner.py`)
- Enrichi par le LLM (intention, wording, arbitrages)
- 7 jours avec : sport, type, durée, intensité, charge, priorité, note coach
- Régénération à la demande ou automatique le lundi matin
- Limite actuelle : le modèle reste encore hebdomadaire et pas vraiment calendaire

### 3. App (6 onglets)

**Aujourd'hui** — écran quotidien
- séance du jour + objectif + note coach
- actions rapides : Fait / Trop fatigué / Décaler
- métriques : sport, durée, intensité, priorité
- lecture de forme : CTL / ATL / TSB
- dernier repère du même sport
- ce qui a changé + ce que le coach regarde

**Calendrier** — vue plan vivant
- séance du jour mise en avant en haut
- navigation semaine par semaine
- liste hebdo inversée : plus récent en haut, plus ancien en bas
- semaine lisible avec statut et date réelle affichée
- une séance terminée se reloge sur son jour réel d'exécution
- tri chrono sur la date réellement affichée
- une activité du mauvais sport apparaît comme entrée distincte `hors plan` et ne valide pas la séance prévue
- tableau de bord exécution / charge / lecture de la semaine
- barre de charge visuelle
- bouton régénérer
- direction cible : vraie timeline persistée + vue performance

**Performance** — cockpit charge
- CTL / ATL / TSB sur 12 semaines
- volume multisport hebdo
- complétion de la semaine en cours
- records simples par sport
- premier split démarré : `utils.js`, `charts.js`

**Activités** — réel vs prévu
- formulaire activité manuelle
- connexion Strava (OAuth + synchro)
- journal brut des activités importées / loggées
- le comparatif prévu vs fait se lit d'abord dans le calendrier
- raccourci depuis une activité rattachée vers sa séance dans le calendrier

**Profil** — double numérique
- objectif, sports, contraintes, préférences
- carte coach : nom, style, do/dont, âme

**Debug** — mémoire
- facts actifs avec catégorie, source, confiance

### 4. Messagerie proactive (Telegram)

3 triggers programmés :
1. **Briefing matin** (7h30) — séance du jour + statut veille
2. **Rappel pré-séance** (18h) — veille d'une séance clé
3. **Revue hebdo** (dimanche 20h) — bilan

Puis :
4. **Nouvelle semaine** (lundi matin) — nouveau plan

4 types de messages :
1. **Adaptation** — ce qui change, pourquoi, impact
2. **Clarification** — question courte quand info manque
3. **Feedback** — question simple après séance clé
4. **Spontané contextuel** — reconnaissance d'effort

### 5. Adaptation

Via message naturel au coach :
- déplacer une séance
- alléger une journée
- échanger deux jours
- mettre à jour une séance
- marquer comme fait

### 6. Boucle activité

- Import Strava automatique (toutes les 2h)
- Logging manuel (escalade, renfo, oublis)
- Matching activité → jour du plan (heuristique : sport +4, jour +3, durée +1-2)
- Marquage automatique "fait" quand match

## Ce que FitMAS ne fait pas encore

- chat web (chat = Telegram uniquement)
- nutrition / meal planning
- coaching mental profond
- multi-agent visible
- mémoire sémantique avancée (vector DB)
- recommandations médicales
- Android natif / iOS natif
- WhatsApp (prévu après validation Telegram)
- webhook Strava (actuellement polling)
- Apple Health
- vrai calendrier persistant daté
- dashboard performance avancé dans `Today`, split frontend modulaire, drag & drop calendrier
- périodisation explicite

## Boucle produit

1. `/start` → onboarding → récap → plan
2. Vue Today + calendrier vivant chaque matin
3. Briefing proactif sur Telegram
4. Adaptation si besoin (message ou action rapide)
5. Activité réelle → import ou log manuel
6. Revue dimanche → nouveau plan lundi matin

## Critères de succès

La V0 est bonne si :
- "le plan me ressemble"
- "j'ai compris quoi faire"
- "les messages tombent juste"
- "j'ai moins à gérer"

## Critères d'échec

La V0 échoue si :
- le plan paraît standard
- les messages paraissent génériques
- l'app paraît complexe
- il faut trop d'actions manuelles
- la personnalisation n'est pas ressentie vite

## Positionnement

Le marché a déjà : Humango (plans adaptatifs), Runna (exécution running), Oura Advisor (data wearable), WHOOP Coach (IA wearable).

Ce qui manque : une expérience qui combine plan adaptatif + personnalisation durable + voix cohérente + proactivité utile + faible charge mentale + vrai multisport.

FitMAS ne bat personne sur un axe. FitMAS gagne sur l'orchestration, la délégation mentale, et la sensation de suivi premium continu.

## Cap produit maintenant

Ordre recommandé :
1. Fiabiliser Telegram et réduire le bruit
2. Introduire un calendrier persistant daté
3. Transformer l'app en dashboard de performance inspiré Runna
4. Ajouter la périodisation et l'adaptation data-driven
5. N'envisager une architecture multi-agent qu'après stabilisation des domaines
