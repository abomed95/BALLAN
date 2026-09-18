"""Garde-fous du noyau qui vivent dans la base, pas dans le code.

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

import subprocess

import pytest

from tests.integration.outils_pg import RAISON_SAUT, base_disponible, psql, valeurs

pytestmark = pytest.mark.skipif(not base_disponible(), reason=RAISON_SAUT)

ETAB = "11111111-1111-1111-1111-111111111111"
ENS_A = "22222222-2222-2222-2222-222222222222"
ENS_B = "33333333-3333-3333-3333-333333333333"


@pytest.fixture(autouse=True)
def jeu_d_essai(base_vide):
    pose = psql(
        f"INSERT INTO etablissement (id, nom) VALUES ('{ETAB}', 'Ecole Al-Nour'); "
        "INSERT INTO ressource (id, etablissement_id, libelle) VALUES "
        f"('{ENS_A}', '{ETAB}', 'Mme B.'), ('{ENS_B}', '{ETAB}', 'M. A.');"
    )
    assert pose.returncode == 0, pose.stderr


def inserer_rdv(
    debut: str, fin: str, statut: str, ressource: str = ENS_A
) -> subprocess.CompletedProcess[str]:
    return psql(
        "INSERT INTO rendez_vous "
        "(etablissement_id, ressource_id, debut_at, fin_at, statut) VALUES "
        f"('{ETAB}', '{ressource}', '{debut}', '{fin}', '{statut}')"
    )


# -- contrainte d'exclusion -------------------------------------------


def test_les_migrations_s_appliquent_sur_une_base_vierge():
    assert valeurs(
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = 'rendez_vous'"
    ) == ["1"]


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


def test_une_langue_par_defaut_hors_des_langues_actives_est_refusee():
    incoherent = psql(
        "INSERT INTO etablissement (nom, langues_actives, langue_defaut) VALUES "
        "('Ecole X', ARRAY['fr','ar'], 'so')"
    )
    assert incoherent.returncode != 0
    assert "etablissement_langue_defaut_active" in incoherent.stderr


def test_un_jour_ouvre_hors_de_la_semaine_est_refuse():
    absurde = psql(
        "INSERT INTO etablissement (nom, jours_ouvres) VALUES "
        "('Ecole X', ARRAY[6,0,1,2,9]::smallint[])"
    )
    assert absurde.returncode != 0
    assert "etablissement_jours_ouvres_valides" in absurde.stderr
