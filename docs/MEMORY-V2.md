---
summary: contrat court de memoire FitMAS profile, working et patterns
read_when:
  - modifier la memoire utilisateur
  - ajouter une action memory_actions
  - separer fait durable, contexte court et pattern
  - toucher aux contraintes voyage, sante, disponibilite ou preference
---

# Memory V2

## Statut

Gros chantier memoire : pas maintenant.

La priorite reste :

```text
Produit V0 dogfoodable autour du Runtime V0.
Pas de gros chantier memoire avant preuve Telegram.
```

On garde ce contrat pour ne pas salir la memoire pendant l'integration V0.

## Couches

| Couche | Role | Horizon |
| --- | --- | --- |
| Event truth | activites, events, messages persistants | permanent |
| Profile memory | objectifs, preferences fortes, contraintes stables | long |
| Working memory | fatigue, douleur, voyage, indispo temporaire | heures/jours |
| Pattern memory | habitudes observees et promues lentement | semaines/mois |

`UserFact` reste un backing store de transition, surtout durable.
Working memory et patterns existent mais ne doivent pas devenir un fourre-tout.

## Ecriture Conversation

Flux obligatoire :

```text
texte user libre
-> Understanding/Coach LLM
-> memory_actions structurees
-> validation / dedup / TTL / permissions
-> writer memoire borne
-> audit
```

Interdit :

- creer fatigue/douleur/dispo/preference depuis regex ;
- promouvoir un pattern depuis une phrase unique ;
- transformer un voyage en code special planning ;
- injecter toute la memoire brute dans un prompt.

## Voyage / Contrainte Temporaire

Un voyage est d'abord une working memory :

- fenetre temporelle ;
- contrainte logistique ;
- sports ou lieux impactes si le LLM les extrait ;
- TTL clair ;
- statut actif/expire.

Le planning peut ensuite lire cette contrainte structuree et construire des
candidates.

Le voyage n'est pas un workflow special qui comprend le texte a part.

## Lecture

Le `CoachContext` doit recevoir une memoire compacte :

- profile facts pertinents ;
- working facts actifs ;
- patterns utiles au planning ;
- jamais un dump complet.

Le contexte doit expliquer assez pour decider, pas assez pour halluciner.

## Promotion Pattern

Autorise :

- promotion lente depuis activites reelles ;
- recurrence observee ;
- events d'adaptation logistiques ;
- signaux LLM structures valides.

Interdit :

- pattern lexical local ;
- promotion sur un seul message ;
- pattern sans evidence temporelle.

## Organisation Actuelle

La memoire vit sous :

```text
domain/memory/
  availability_constraints.py
  fact_memory.py
  maintenance.py
  mutation_service.py
  patterns.py
  profile_memory.py
  profile_summary.py
  repository.py
  routing.py
  view_models.py
```

Tout nouveau deplacement doit reduire le runtime, pas seulement renommer.
