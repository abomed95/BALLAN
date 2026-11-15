# Etat de relecture des traductions

Le champ `_meta.statut` de chaque fichier de langue vaut :

| statut | sens |
|---|---|
| `reference` | langue source, fait foi |
| `a_relire` | traduction de travail, **pas encore validee par un locuteur natif** |
| `relu` | validee, avec le nom du relecteur dans `_meta.revu_par` |

## Regle d'activation

Une ecole n'active une langue dans `etablissement.langues_actives` que si son
statut vaut `relu`. Tant qu'une langue est `a_relire`, elle sert au
developpement et aux demonstrations internes, pas a un parent reel.

Cette regle est ce qui protege le produit d'un message maladroit envoye a
plusieurs centaines de familles.

## Etat au lot 3

Le lot 3 a ajoute les messages de l'agent (`agent.*`), du consentement
(`consentement.*`), des rappels (`rappel.*`) et du secretariat
(`secretariat.*`) : 40 cles par langue.

| langue | statut | reste a faire |
|---|---|---|
| `fr` | `reference` | — |
| `ar` | `a_relire` | relecture arabe standard, verification des noms de mois en usage a Djibouti, registre (vouvoiement collectif employe) |
| `so` | `a_relire` | relecture somali complete |
| `aa` | `a_relire` | **reecriture** afar : les cles du lot 3 sont un premier jet non verifie, a reprendre entierement par un locuteur natif |

Le service refuse de demarrer en production avec une langue active dont le
statut n'est ni `reference` ni `relu` (sauf `BALLAN_AUTORISER_LANGUES_NON_RELUES=1`),
et `ballan verifier` le signale.

Les modeles de rappel WhatsApp (approuves par Meta, voir
`docs/DEPLOIEMENT.md`) sont des textes a part : ils doivent reprendre la cle
`rappel.rendez_vous` relue, langue par langue.

## Procedure (lot 7)

1. Exporter les cles : `python -m core.i18n.rapport` donne, par langue, les
   cles manquantes et les cles orphelines.
2. Faire relire le fichier entier, pas seulement le delta.
3. Renseigner `_meta.revu_par` et passer `_meta.statut` a `relu`.
4. `tests/test_i18n.py` et `python -m core.i18n.rapport` verifient la completude ; il ne verifie pas la
   justesse — c'est le role du relecteur.

## Ce qui ne se traduit jamais ici

Les libelles officiels (niveaux, matieres, motifs de rendez-vous) vivent dans
les colonnes `libelle_i18n_json` des tables concernees, saisis par l'ecole.
Ils ne passent ni par ce catalogue ni par le modele de langue (BALLAN.md §7).
