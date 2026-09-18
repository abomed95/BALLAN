"""Verification des garde-fous qui vivent dans la base, pas dans le code.

``core/scheduling/conflits.py`` est le miroir applicatif de la contrainte
d'exclusion : il permet d'echouer poliment et de proposer autre chose. Mais
c'est la base qui tranche quand deux instances de l'API ecrivent en meme
temps. Une regle dont on depend a ce point se verifie contre un vrai
PostgreSQL, pas contre une reimplementation.

Ces tests sont ignores si aucune base n'est fournie :

    BALLAN_TEST_DSN=postgresql://.../ballan_test python -m pytest tests/integration

Ils detruisent et recreent le schema ``public`` de cette base : ne la faites
jamais pointer vers autre chose qu'une base jetable.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

DSN = os.environ.get("BALLAN_TEST_DSN")
RACINE_MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"

pytestmark = pytest.mark.skipif(
    not DSN or shutil.which("psql") is None,
    reason="BALLAN_TEST_DSN non defini ou psql absent",
)

ETAB = "11111111-1111-1111-1111-111111111111"
ENS_A = "22222222-2222-2222-2222-222222222222"
ENS_B = "33333333-3333-3333-3333-333333333333"


def psql(sql: str, *, fichier: Path | None = None) -> subprocess.CompletedProcess[str]:
    commande = ["psql", "-v", "ON_ERROR_STOP=1", "-q", "-X", DSN]
    commande += ["-f", str(fichier)] if fichier else ["-c", sql]
    return subprocess.run(commande, capture_output=True, text=True, timeout=60)


def inserer_rdv(
    debut: str, fin: str, statut: str, ressource: str = ENS_A
) -> subprocess.CompletedProcess[str]:
    return psql(
        "INSERT INTO rendez_vous "
        "(etablissement_id, ressource_id, debut_at, fin_at, statut) VALUES "
        f"('{ETAB}', '{ressource}', '{debut}', '{fin}', '{statut}')"
    )


@pytest.fixture(scope="module", autouse=True)
def schema():
    """Reconstruit le schema a partir des fichiers de migration."""
    remise_a_zero = psql("DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;")
    assert remise_a_zero.returncode == 0, remise_a_zero.stderr

    fichiers = sorted(RACINE_MIGRATIONS.glob("[0-9]*.sql"))
    assert fichiers, "aucun fichier de migration trouve"
    for fichier in fichiers:
        applique = psql("", fichier=fichier)
        assert applique.returncode == 0, f"{fichier.name} : {applique.stderr}"
    yield


@pytest.fixture(autouse=True)
def jeu_d_essai():
    psql(
        "TRUNCATE etablissement CASCADE; "
        f"INSERT INTO etablissement (id, nom) VALUES ('{ETAB}', 'Ecole Al-Nour'); "
        "INSERT INTO ressource (id, etablissement_id, libelle) VALUES "
        f"('{ENS_A}', '{ETAB}', 'Mme B.'), ('{ENS_B}', '{ETAB}', 'M. A.');"
    )
    yield


# -- contrainte d'exclusion -------------------------------------------


def test_les_migrations_s_appliquent_sur_une_base_vierge():
    tables = psql(
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = 'rendez_vous'"
    )
    assert tables.returncode == 0
    assert "1" in tables.stdout


def test_deux_reservations_du_meme_creneau_la_seconde_est_refusee_par_la_base():
    """Critere §12, verifie la ou il compte : dans PostgreSQL."""
    assert inserer_rdv("2025-09-22 10:00+03", "2025-09-22 10:30+03", "confirme").returncode == 0
    seconde = inserer_rdv("2025-09-22 10:00+03", "2025-09-22 10:30+03", "confirme")
    assert seconde.returncode != 0
    assert "rendez_vous_sans_chevauchement" in seconde.stderr


def test_un_chevauchement_partiel_est_refuse():
    assert inserer_rdv("2025-09-22 10:00+03", "2025-09-22 10:30+03", "confirme").returncode == 0
    debordant = inserer_rdv("2025-09-22 10:15+03", "2025-09-22 10:45+03", "confirme")
    assert debordant.returncode != 0
    assert "rendez_vous_sans_chevauchement" in debordant.stderr


def test_deux_creneaux_jointifs_coexistent():
    """La convention des intervalles semi-ouverts, cote base."""
    assert inserer_rdv("2025-09-22 10:00+03", "2025-09-22 10:30+03", "confirme").returncode == 0
    assert inserer_rdv("2025-09-22 10:30+03", "2025-09-22 11:00+03", "confirme").returncode == 0


def test_un_rendez_vous_propose_ne_bloque_pas_le_creneau():
    """La contrainte ne porte que sur les confirmes, comme
    ``STATUTS_BLOQUANTS_DEFAUT`` cote Python. Les deux doivent rester
    synchronises."""
    assert inserer_rdv("2025-09-22 10:00+03", "2025-09-22 10:30+03", "confirme").returncode == 0
    assert inserer_rdv("2025-09-22 10:00+03", "2025-09-22 10:30+03", "propose").returncode == 0


def test_un_rendez_vous_annule_libere_le_creneau():
    assert inserer_rdv("2025-09-22 10:00+03", "2025-09-22 10:30+03", "confirme").returncode == 0
    assert psql("UPDATE rendez_vous SET statut = 'annule'").returncode == 0
    assert inserer_rdv("2025-09-22 10:00+03", "2025-09-22 10:30+03", "confirme").returncode == 0


def test_deux_enseignants_peuvent_recevoir_a_la_meme_heure():
    debut, fin = "2025-09-22 10:00+03", "2025-09-22 10:30+03"
    assert inserer_rdv(debut, fin, "confirme", ENS_A).returncode == 0
    assert inserer_rdv(debut, fin, "confirme", ENS_B).returncode == 0


# -- autres garde-fous de schema ---------------------------------------


def test_un_rendez_vous_qui_finit_avant_de_commencer_est_refuse():
    inverse = inserer_rdv("2025-09-22 10:30+03", "2025-09-22 10:00+03", "confirme")
    assert inverse.returncode != 0
    assert "rendez_vous_bornes" in inverse.stderr


def test_un_numero_non_canonique_est_refuse():
    mauvais = psql(
        f"INSERT INTO contact (etablissement_id, numero) VALUES ('{ETAB}', '77123456')"
    )
    assert mauvais.returncode != 0
    assert "contact_numero_canonique" in mauvais.stderr


def test_le_meme_numero_ne_peut_pas_etre_cree_deux_fois_dans_une_ecole():
    assert (
        psql(
            f"INSERT INTO contact (etablissement_id, numero) VALUES ('{ETAB}', '+25377123456')"
        ).returncode
        == 0
    )
    doublon = psql(
        f"INSERT INTO contact (etablissement_id, numero) VALUES ('{ETAB}', '+25377123456')"
    )
    assert doublon.returncode != 0


def test_une_ouverture_exceptionnelle_sans_tranche_horaire_est_refusee():
    sans_heures = psql(
        "INSERT INTO exception_agenda "
        "(etablissement_id, type, date_debut, date_fin) VALUES "
        f"('{ETAB}', 'ouverture', '2025-09-27', '2025-09-27')"
    )
    assert sans_heures.returncode != 0
    assert "exception_tranche_obligatoire" in sans_heures.stderr
