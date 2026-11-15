"""Fixtures des tests d'integration.

Le schema est reconstruit une fois par session, puis chaque test repart
d'une base vide : les contraintes se testent sur des inserts propres, pas
sur un etat herite du test precedent.
"""

from __future__ import annotations

import pytest

from tests.integration.outils_pg import psql, reconstruire_schema


@pytest.fixture(scope="session")
def schema():
    reconstruire_schema()
    return True


@pytest.fixture
def base_vide(schema):
    """Vide toutes les tables avant chaque test."""
    remise = psql("TRUNCATE etablissement CASCADE;")
    assert remise.returncode == 0, remise.stderr
    return psql
