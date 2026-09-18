"""Outils partages par les tests d'integration PostgreSQL.

Volontairement sans psycopg : ces tests verifient des contraintes de schema,
pas du code Python. Passer par ``psql`` garde la suite installable partout et
rejoue les fichiers de migration exactement comme le fera un deploiement.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

DSN = os.environ.get("BALLAN_TEST_DSN")
RACINE_MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"

RAISON_SAUT = "BALLAN_TEST_DSN non defini ou psql absent"


def base_disponible() -> bool:
    return bool(DSN) and shutil.which("psql") is not None


def psql(sql: str, *, fichier: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Execute du SQL et rend le resultat sans lever.

    Les tests regardent ``returncode`` et ``stderr`` : un echec attendu est
    une assertion, pas une exception.
    """
    commande = ["psql", "-v", "ON_ERROR_STOP=1", "-q", "-X", DSN]
    commande += ["-f", str(fichier)] if fichier else ["-c", sql]
    return subprocess.run(commande, capture_output=True, text=True, timeout=60)


def valeurs(sql: str) -> list[str]:
    """Execute une requete et rend ses lignes, sans en-tete ni decorations.

    ``-t -A`` evite d'avoir a deviner la mise en forme de psql : un test qui
    analyse un tableau ASCII finit par passer alors qu'il ne verifie plus rien.
    """
    commande = ["psql", "-v", "ON_ERROR_STOP=1", "-t", "-A", "-X", DSN, "-c", sql]
    resultat = subprocess.run(commande, capture_output=True, text=True, timeout=60)
    assert resultat.returncode == 0, resultat.stderr
    return [ligne.strip() for ligne in resultat.stdout.splitlines() if ligne.strip()]


def reconstruire_schema() -> None:
    """Detruit et rejoue toutes les migrations, dans l'ordre."""
    remise_a_zero = psql("DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;")
    assert remise_a_zero.returncode == 0, remise_a_zero.stderr

    fichiers = sorted(RACINE_MIGRATIONS.glob("[0-9]*.sql"))
    assert fichiers, "aucun fichier de migration trouve"
    for fichier in fichiers:
        applique = psql("", fichier=fichier)
        assert applique.returncode == 0, f"{fichier.name} : {applique.stderr}"
