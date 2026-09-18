# BALLAN

> **Ballan** — en somali : « rendez-vous », et aussi « engagement, parole donnée ».
> Produit AMD Digital · Djibouti

Agent conversationnel qui gère les rendez-vous parents-enseignants, les
rappels et la communication courante d'une école privée, sur WhatsApp, en
français, arabe, somali et afar.

La spécification fonctionnelle complète est `BALLAN.md`. Ce fichier ne décrit
que l'état du code et la façon de le faire tourner.

---

## État d'avancement

Le produit se construit par lots (`BALLAN.md` §11).

| Lot | Contenu | État |
|---|---|---|
| 0 | Noyau : moteur de créneaux, calendrier, i18n, téléphone | **fait** |
| 1 | Structure scolaire, familles, cloisonnement familial | **fait** |
| 2 | Canal WhatsApp, identification du parent, escalade | à faire |
| 3 | Rendez-vous, interdits pédagogiques | à faire |
| 4 | Réunions parents-professeurs | à faire |
| 5 | Rappels et annonces | à faire |
| 6 | Tableau de bord secrétariat | à faire |
| 7 | Relecture arabe et afar | à faire |
| 8 | Mise en service pilote | à faire |

---

## Architecture

```
core/          noyau commun à MAWID et BALLAN — ne doit jamais diverger
  models/      objets de domaine, Python pur
  scheduling/  intervalles, calendrier, moteur de créneaux, conflits, agenda
  i18n/        catalogue quatre langues, dates en clair, libellés officiels
  telephone.py normalisation des numéros

verticals/
  school/      ce qui est propre à une école : familles, accès, calendrier scolaire

migrations/    schéma PostgreSQL, un fichier par lot
tests/         suite sans base de données
tests/integration/   ce qui exige un vrai PostgreSQL
```

Deux principes structurent le dépôt.

**Le noyau ne connaît pas l'école.** Il parle de *ressource* et de *contact*.
La notion d'élève, de famille et de classe vit dans `verticals/school/`. Un
correctif de créneaux profite ainsi aux deux produits, comme l'exige
`BALLAN.md` §0.

**Le domaine est en Python pur, sans dépendance.** Le moteur de créneaux et
les règles d'accès se testent sans base de données ni réseau : la suite
complète tourne en moins d'une seconde, sur n'importe quel poste. La
persistance n'est qu'un adaptateur au-dessus.

---

## Faire tourner

```sh
python -m pip install -e ".[dev]"
python -m pytest              # suite complète, sans base
python -m ruff check .
```

Les tests d'intégration ont besoin d'un PostgreSQL jetable :

```sh
docker compose -f docker/docker-compose.dev.yml up -d
BALLAN_TEST_DSN="postgresql://ballan:ballan@localhost:5433/ballan_test" \
  python -m pytest tests/integration
```

Rapport de complétude des traductions :

```sh
python -m core.i18n.rapport
```

---

## Ce que le code refuse de faire

Ces règles sont vérifiées par des tests qui ne doivent jamais être retirés.

- **Aucune information nominative sur un élève ne sort sans vérification du
  lien familial**, faite côté serveur à chaque requête
  (`tests/test_cloisonnement_familial.py`). Un numéro non rattaché n'obtient
  rien, pas même la confirmation qu'un élève est inscrit : le refus est
  identique que l'élève existe ou non.
- **Date de naissance réduite à l'année**, pas de photo, pas de donnée de
  santé, pas d'appréciation (`tests/test_donnees_minimales_eleve.py`). Le
  test inspecte la *forme* des modèles et du schéma : ajouter un champ
  `moyenne` ou `photo_url` fait échouer la suite.
- **Deux parents ne peuvent pas réserver le même créneau**
  (`tests/test_conflits_creneaux.py`, doublé par une contrainte d'exclusion
  PostgreSQL vérifiée dans `tests/integration/`).
- **Un changement de numéro passe par le secrétariat**, jamais par l'agent —
  et l'agent n'a aucun chemin de lecture vers `autorise_a_recuperer`, qui
  touche à des situations de garde.
- **Aucune note, appréciation ou information de comportement** ne transite
  par BALLAN (`tests/test_interdits_pedagogiques.py`, lot 3).

---

## Conventions

- **Jours de la semaine** : lundi = 0, dimanche = 6 (convention Python).
  Différente de `extract(dow)` de PostgreSQL ; c'est le Python qui fait foi.
- **Semaine ouvrée par défaut** : dimanche → jeudi, à confirmer école par
  école.
- **Fuseau** : `Africa/Djibouti`. Tous les `datetime` du noyau sont
  conscients du fuseau ; un `datetime` naïf lève une erreur.
- **Intervalles semi-ouverts** `[début, fin)` : deux créneaux jointifs ne se
  chevauchent pas.
- **Chaînes** : rien en dur. Tout ce qu'un parent lit vient de
  `core/i18n/locales/`. Les libellés officiels (niveaux, matières, motifs)
  sont saisis par l'école dans `libelle_i18n_json` et ne passent jamais par
  le modèle de langue.
- **Code et commentaires en français sans accents**, chaînes destinées aux
  parents en français accentué. Les journaux et les terminaux des serveurs
  ne sont pas toujours en UTF-8 ; les messages des parents, si.
- **Aucune erreur ne transporte de donnée nominative** : les journaux d'un
  produit qui manipule des données de mineurs ne contiennent ni prénom, ni
  nom, ni identifiant d'élève.
