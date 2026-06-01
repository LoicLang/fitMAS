---
summary: doctrine de test du Runtime V0 ; deux couches, matrice mecanique et simulation live
read_when:
  - prouver ou contester une evolution du runtime V0
  - choisir entre matrice et sonde sous-agent
  - lire un resultat de test sans le surinterpreter
---

# Doctrine De Test V0

Tester V0, c'est deux couches aux roles distincts. Ne pas les confondre.
La matrice est un filet mecanique, pas une preuve de qualite.
La vraie qualite ne se juge que dans la simulation live.

## Pourquoi

Barre de preuve : prouver le potentiel, pas battre l'app. Le profil d'echec
prime sur le taux brut : V0 doit echouer en **securite** la ou l'app echoue en
**danger**. Le verdict de verite se **prouve** (danger metrics a 0, guard
fallback < 15 %), il ne s'affirme pas.

## Couche 1 — Matrice Deterministe

```text
outil : scripts/v0_eval/run_matrix.py
forme : 11 scenarios x N reps x providers, scoring mecanique
```

Prouve :

- regression — un comportement connu tient-il encore ;
- danger — `wrong_write`, `old_plan_date`, `wrong_correction_target`,
  `claim_without_event` restent a 0 ;
- cout de la verite — guard fallback rate < 15 %.

Ne prouve PAS la qualite reelle. Elle **scripte les deux cotes** de l'echange,
donc elle ne verra jamais une reponse coach qui fait derailler une vraie
conversation. Vecu : elle scorait `followup_planning_turn1` a 5/5 pendant que
la conversation reelle s'effondrait en `no_send`.

Role : filet. Avant/apres un changement, prouver "rien casse, rien dangereux".
Jamais "c'est bon".

## Couche 2 — Simulation Live

```text
outil  : scripts/v0_eval/drive_turn.py  (seed | turn | state)
joueur : un sous-agent qui joue l'utilisateur, un tour a la fois
monde  : une shadow DB persistee (jamais la prod)
```

C'est **la** que se simule et se juge la vraie qualite, comparaison comprise.
La conversation n'est pas scriptee : le coach repond pour de vrai a chaque tour.
L'etat (pending, `last_unresolved_intent`) persiste entre tours via la shadow DB.
`today` vient du timestamp de l'event (`--date`), pas de l'horloge, donc un run
est reproductible.

A trouve le `no_send` au premier run aveugle, la ou la matrice scorait 5/5.

### Mecanisme d'honnetete (le coeur)

Separation **joueur / juge** :

- **Joueur** = le sous-agent. Aveugle aux internes V0. Joue un user realiste
  avec un objectif. Ne note JAMAIS le succes.
- **Juge** = oracle mecanique. Lit l'etat DB (`drive_turn.py state` : sessions,
  pending, commands), pas le ressenti d'une reponse. Tranche sur la structure.

Sans cette separation, le juge se fait berner par une reponse fluide-mais-fausse
et le joueur teleguide la conversation vers un pass.

## Lire Un Resultat Sans Se Tromper

- **Variance** : un LLM est non-deterministe. 4/5 vs 5/5 peut etre du bruit.
  Avant d'imputer un changement, pooler le MEME scenario sur plusieurs runs pour
  etablir le taux de panne de base. Vecu : `hard_unsafe_block` etait deja 3/5
  avant tout changement ; un run isole a 5/5 etait l'exception, pas la base.
- **Goal coherent** : l'objectif du joueur doit etre interne-coherent. Un
  objectif contradictoire (ex. une erreur de date) brouille l'oracle et invente
  de faux echecs.
- Un run de simulation = une anecdote riche, pas un chiffre. La couche 2 revele
  des classes de bug ; la couche 1 mesure si elles reviennent.

## Discipline

- Matrice = gate de regression/securite. Obligatoire avant de declarer un fix
  prouve. Ne pas la surinterpreter comme une mesure de qualite.
- Simulation = preuve de qualite. Obligatoire avant dogfood ; un chiffre matrice
  ne suffit pas. Ne pas la chiffrer comme une matrice.

## Legacy

`scripts/v0_eval/compare_app_vs_v0.py` (avec `spike_real_turn.py`,
`real_snapshot.py`, `oracle_compare.py`) rejouait des tours de prod captures
pour comparer V0 au pipeline app sur le meme monde. **Remplace par la simulation
sous-agent (couche 2).** Conserve pour reference, plus le chemin recommande.
