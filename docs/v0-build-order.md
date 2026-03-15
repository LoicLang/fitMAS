---
summary: ordre de construction recommande pour la V0 apres nettoyage du repo et reprise de l'implementation
read_when:
  - reprendre le code apres la phase de cadrage
  - choisir le premier chantier technique
  - garder un ordre d'execution sobre
  - aligner produit et implementation
---

# V0 Build Order

## Point de depart

Le repo est volontairement reparti propre.

Le premier chantier code recommande n'est pas encore l'app iOS complete,
car l'environnement local n'a pas Xcode actif.

Donc le meilleur point de depart est:

- une API V0 simple
- avec les vrais objets produit
- et une logique basique de reponse naturelle

## Pourquoi commencer ici

Cela permet de figer:

- `Today`
- `Plan`
- `Profil`
- le fil WhatsApp
- l'extraction de contraintes / ressenti

Sans se perdre tout de suite dans:

- l'infrastructure iOS
- les integrations reelles
- la persistance finale

## Ordre recommande

1. API V0 mockable
2. front prototype ou iOS branchant cette API
3. persistance
4. integrations reelles
5. heartbeat plus riche
