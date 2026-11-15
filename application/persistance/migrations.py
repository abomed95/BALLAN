"""Application des migrations SQL, une seule fois chacune, dans l'ordre.

Les fichiers ``migrations/NNNN_*.sql`` restent la source de verite (lisibles,
rejouables a la main avec ``psql``). Ce module ajoute seulement ce qu'un
deploiement exige :

* la table ``schema_migrations`` retient ce qui est deja applique ;
* chaque fichier s'applique dans sa propre transaction : une migration qui
  echoue ne laisse pas un schema a moitie modifie ;
* un verrou consultatif empeche deux conteneurs demarres en meme temps
  d'appliquer la meme migration deux fois.
"""

from __future__ import annotations

import logging
from pathlib import Path

import psycopg

journal = logging.getLogger("ballan.migrations")

RACINE_MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"

#: Cle arbitraire du verrou consultatif PostgreSQL reserve aux migrations.
_CLE_VERROU = 0x0BA11A4


class MigrationImpossible(RuntimeError):
    pass


def fichiers_migration(racine: Path = RACINE_MIGRATIONS) -> list[Path]:
    return sorted(racine.glob("[0-9][0-9][0-9][0-9]_*.sql"))


def appliquer_migrations(dsn: str, racine: Path = RACINE_MIGRATIONS) -> list[str]:
    """Applique les migrations manquantes et rend la liste des versions appliquees."""
    appliquees: list[str] = []
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (_CLE_VERROU,))
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                " version text PRIMARY KEY,"
                " appliquee_at timestamptz NOT NULL DEFAULT now())"
            )
            deja = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
            if not deja and _schema_existant(conn):
                raise MigrationImpossible(
                    "des tables BALLAN existent deja mais schema_migrations est vide : "
                    "base creee a la main. Renseignez schema_migrations avant de continuer."
                )
            for fichier in fichiers_migration(racine):
                version = fichier.stem
                if version in deja:
                    continue
                journal.info("application de la migration %s", version)
                with conn.transaction():
                    conn.execute(fichier.read_text(encoding="utf-8"))
                    conn.execute(
                        "INSERT INTO schema_migrations (version) VALUES (%s)", (version,)
                    )
                appliquees.append(version)
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (_CLE_VERROU,))
    return appliquees


def _schema_existant(conn: psycopg.Connection) -> bool:
    r = conn.execute("SELECT to_regclass('public.etablissement') IS NOT NULL").fetchone()
    return bool(r and r[0])
