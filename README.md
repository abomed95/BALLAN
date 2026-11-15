# BALLAN

> **Ballan** — en somali : « rendez-vous », et aussi « engagement, parole donnée ».
> Produit AMD Digital · Djibouti

Agent conversationnel qui gère les rendez-vous parents-enseignants, les
rappels et la communication courante d'une école privée, sur WhatsApp, en
français, arabe, somali et afar.

- **Mettre en service une école** : [`docs/DEPLOIEMENT.md`](docs/DEPLOIEMENT.md)
- **Voir le produit sans rien installer** : `python -m application simuler`

---

## Ce que fait la version 0.2

Un parent écrit au numéro WhatsApp de l'école. BALLAN :

1. **l'identifie** par son numéro, côté serveur, à chaque message ; un
   numéro inconnu n'apprend rien et part au secrétariat ;
2. lui propose un **menu numéroté** dans sa langue : prendre un rendez-vous,
   voir ou annuler ses rendez-vous, parler au secrétariat, changer de langue ;
3. pour un rendez-vous : choix de l'enfant (si plusieurs), du motif défini par
   l'école, puis de **trois créneaux libres sur trois jours différents**, hors
   vacances, fériés et horaires de Ramadan ; confirmation ;
4. **rappelle** le rendez-vous la veille (avec consentement, jamais la nuit) ;
5. **refuse** de parler de notes, comportement, garde ou santé : il redirige
   vers un rendez-vous ou transmet au secrétariat.

Le secrétariat dispose d'une page web (`/secretariat`) : demandes à rappeler
(numéro cliquable), agenda des deux semaines à venir, annulation.

| Lot | Contenu | État |
|---|---|---|
| 0 | Noyau : moteur de créneaux, calendrier, i18n, téléphone | fait |
| 1 | Structure scolaire, familles, cloisonnement familial | fait |
| 2 | Canal WhatsApp, identification du parent, escalade | **fait** |
| 3 | Rendez-vous, interdits pédagogiques | **fait** |
| 4 | Réunions parents-professeurs (sessions collectives) | à faire |
| 5 | Rappels **(fait)** et annonces (à faire) | partiel |
| 6 | Tableau de bord secrétariat : page minimale **(faite)**, saisie en ligne (à faire) | partiel |
| 7 | Relecture arabe, somali et afar par des locuteurs natifs | **à faire — bloquant** |
| 8 | Mise en service pilote : Docker, HTTPS, sauvegardes, CI **(faits)** | prêt |

---

## Architecture

Architecture hexagonale (« ports et adaptateurs ») : le domaine définit des
interfaces (`Protocol`), l'infrastructure les implémente, et une seule racine
de composition décide qui parle à qui.

```
core/                 noyau commun MAWID / BALLAN — Python pur, aucune dépendance
  models/  scheduling/  i18n/  telephone.py  escalade.py
verticals/school/     domaine scolaire — Python pur
  family.py           cloisonnement familial (le seul chemin vers un élève)
  rendez_vous.py      prise de rendez-vous soumise au périmètre
  interdits.py        sujets dont l'agent ne parle jamais
  configuration.py    ce que l'école paramètre
application/          cas d'usage et adaptateurs
  conversation/       agent : machine à états à menus numérotés
  persistance/        PostgreSQL (+ migrations suivies)
  whatsapp/           WhatsApp Cloud API : webhook signé, envoi
  api/                FastAPI : webhook, page et API du secrétariat
  rappels.py  secretariat.py  importation.py  config.py  journal.py
  conteneur.py        racine de composition (production / démonstration)
  cli.py              commande `ballan`
migrations/           schéma PostgreSQL, un fichier par lot
exemples/             école fictive : modèle de configuration et de CSV
```

Les dépendances vont dans un seul sens : `application → verticals → core`.
Le domaine se teste sans base ni réseau ; chaque port a un adaptateur mémoire
(tests, simulateur) et un adaptateur PostgreSQL (production), vérifiés par la
même suite.

**Pourquoi un agent déterministe, sans modèle de langue ?** Pour un pilote
qui touche aux données de mineurs, c'est le choix sûr : aucune
hallucination possible sur un créneau ou un élève, comportement identique
dans les quatre langues et testable exhaustivement, menus utilisables par un
parent peu à l'aise à l'écrit. Un LLM pourra ensuite être branché **en
amont**, pour traduire un message libre en une option du menu — jamais pour
rédiger une réponse ou lire une donnée.

---

## Faire tourner

```sh
python -m pip install -r requirements/serveur.lock -e ".[dev]"
python -m pytest              # suite complète, sans base (< 2 s)
python -m ruff check .
python -m application simuler # conversation de démonstration dans le terminal
```

Tests d'intégration (PostgreSQL jetable) :

```sh
make db-up
make test-integration
```

Commandes du service (voir `ballan --help`) :

| Commande | Rôle |
|---|---|
| `ballan verifier` | liste de contrôle avant mise en service |
| `ballan migrer` | applique les migrations manquantes |
| `ballan importer ecole.json familles.csv [--essai]` | charge l'école |
| `ballan servir` | API HTTP (webhook + secrétariat) |
| `ballan rappels --boucle 1800` | rappels J-1 |
| `ballan purger --jours 30` | efface les états de conversation anciens |
| `ballan simuler` | démonstration sans WhatsApp ni base |

---

## Ce que le code refuse de faire

Ces règles sont vérifiées par des tests qui ne doivent jamais être retirés.

- **Aucune information nominative sur un élève ne sort sans vérification du
  lien familial**, recalculée côté serveur à chaque message
  (`tests/test_cloisonnement_familial.py`, `tests/test_agent_conversation.py`).
  Un numéro non rattaché n'obtient rien, pas même la confirmation qu'un élève
  est inscrit. Un état de conversation falsifié n'ouvre rien.
- **Date de naissance réduite à l'année**, pas de photo, pas de donnée de
  santé, pas d'appréciation (`tests/test_donnees_minimales_eleve.py`).
- **Deux parents ne peuvent pas réserver le même créneau**, même au même
  instant sur deux connexions : la contrainte d'exclusion PostgreSQL tranche
  (`tests/integration/test_adaptateurs_postgres.py`).
- **Un changement de numéro passe par le secrétariat** (import CSV), jamais
  par l'agent ; l'agent n'a aucun chemin vers `autorise_a_recuperer`.
- **Aucune note, appréciation ou information de comportement** ne transite
  par BALLAN (`tests/test_interdits_pedagogiques.py`).
- **Aucun webhook non signé par Meta n'est traité.**
- **Aucun rappel sans consentement, après STOP, ou la nuit.**
- **Aucune langue non relue par un locuteur natif** face à de vrais parents,
  sauf dérogation explicite (`BALLAN_AUTORISER_LANGUES_NON_RELUES`).
- **Aucun numéro de téléphone ni paramètre d'URL en clair dans les journaux.**

---

## Conventions

- **Jours de la semaine** : lundi = 0, dimanche = 6 (convention Python).
- **Semaine ouvrée par défaut** : dimanche → jeudi, à confirmer école par école.
- **Fuseau** : `Africa/Djibouti`. Tout `datetime` du noyau est conscient du
  fuseau ; un `datetime` naïf lève une erreur.
- **Intervalles semi-ouverts** `[début, fin)`.
- **Chaînes** : rien en dur. Tout ce qu'un parent lit vient de
  `core/i18n/locales/`. Les libellés officiels (niveaux, matières, motifs)
  sont saisis par l'école et ne passent jamais par un modèle de langue.
- **Code et commentaires en français sans accents**, chaînes destinées aux
  parents en français accentué.
- **Aucune erreur ne transporte de donnée nominative.**

La spécification fonctionnelle de référence est `BALLAN.md` (tenue hors de ce
dépôt) ; les références `§n` du code y renvoient.
