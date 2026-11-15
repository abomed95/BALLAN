# Migrations

Fichiers SQL numerotes, appliques dans l'ordre lexicographique, une seule
fois, sans retour arriere. Pas d'outil de migration pour l'instant : le
schema est encore jeune et un fichier SQL lisible vaut mieux qu'une couche
d'abstraction de plus.

| Fichier | Lot | Contenu |
|---|---|---|
| `0001_core.sql` | 0 | Noyau : etablissement, ressource, disponibilite, exception_agenda, contact, rendez_vous |
| `0002_school.sql` | 1 | Structure scolaire : annee, periodes, niveaux, classes, enseignants, eleves, familles, liens parent-eleve |
| `0003_conversation.sql` | 2, 3, 5 | Conversation, escalade, anti-doublon WhatsApp, motif -> ressource, rappels |

## Appliquer

En production, `ballan migrer` (lance automatiquement par le service
`migrations` de docker-compose) applique les fichiers manquants, chacun dans
sa transaction, et les inscrit dans `schema_migrations`. Un verrou
consultatif empeche deux conteneurs de migrer en meme temps.

A la main, sur une base de developpement :

```sh
for f in migrations/0*.sql; do psql -v ON_ERROR_STOP=1 -d "$DATABASE_URL" -f "$f"; done
```

Une migration publiee ne se modifie plus : on en ajoute une nouvelle.

## Regles

- **Une migration ne cree pas de table sans code qui l'utilise.** Les tables
  `session_reunion`, `annonce`, `echeance_scolarite` et `signalement_absence`
  arriveront avec les lots 4 et 5, en meme temps que leur code.
- **Aucun texte de message de parent n'est stocke** : `conversation` ne garde
  que l'etape et des identifiants, `message_entrant` que l'identifiant
  technique WhatsApp. Les deux sont purges apres 30 jours (`ballan purger`).
- **Les contraintes vivent dans la base.** Le cloisonnement familial, le
  non-chevauchement des rendez-vous et le minimum de donnees sur un mineur
  ne sont pas des conventions : ce sont des contraintes `CHECK`, `UNIQUE`,
  `EXCLUDE` et des cles etrangeres. Le code Python les double pour echouer
  proprement, il ne les remplace pas.
- **Convention des jours de la semaine** : lundi = 0, dimanche = 6
  (convention Python). Elle differe de `extract(dow)` de PostgreSQL
  (dimanche = 0). Le moteur de creneaux est en Python : c'est lui qui fait
  autorite, et toute requete SQL convertit dans ce sens.

## Verification

`tests/integration/test_contraintes_postgres.py` rejoue les migrations sur
une base jetable et verifie que les garde-fous refusent bien ce qu'ils
doivent refuser :

```sh
BALLAN_TEST_DSN="postgresql://user:pass@localhost/ballan_test" \
  python -m pytest tests/integration
```

Sans `BALLAN_TEST_DSN`, ces tests sont ignores — le reste de la suite ne
demande aucune base.

## Acces et RLS

Le cloisonnement familial (§8.2) est applique cote serveur, a chaque
requete, par `verticals/school/family.py`. L'API se connecte avec un role
de service ; **aucune cle publique Supabase ne doit donner acces direct a
ces tables**. Les politiques RLS seront posees avec l'API (lot 6) et ne
remplaceront pas la verification applicative, elles la doubleront.
