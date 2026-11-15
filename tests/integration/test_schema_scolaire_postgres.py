"""Le schema scolaire refuse-t-il vraiment ce qu'il doit refuser ?

Les regles du §8 sont trop importantes pour ne vivre que dans du Python.
Une ligne inseree par un script d'import, par un outil d'administration ou
par une requete manuelle doit rencontrer les memes refus qu'un appel a
``ServiceFamille``.
"""

from __future__ import annotations

import pytest

from tests.integration.outils_pg import RAISON_SAUT, base_disponible, psql, valeurs

pytestmark = pytest.mark.skipif(not base_disponible(), reason=RAISON_SAUT)

ETAB = "11111111-1111-1111-1111-111111111111"
ENS = "22222222-2222-2222-2222-222222222222"
ANNEE = "44444444-4444-4444-4444-444444444444"
NIVEAU = "55555555-5555-5555-5555-555555555555"
CLASSE = "66666666-6666-6666-6666-666666666666"
ELEVE = "77777777-7777-7777-7777-777777777777"
FAMILLE = "88888888-8888-8888-8888-888888888888"
PARENT = "99999999-9999-9999-9999-999999999999"

#: Fragments interdits dans tout nom de colonne du schema (§3, §8.1).
FRAGMENTS_INTERDITS = (
    "note",
    "moyenne",
    "bulletin",
    "appreciation",
    "comportement",
    "discipline",
    "sanction",
    "photo",
    "sante",
    "medical",
    "maladie",
    "allergie",
)

REQUETE_COLONNES_INTERDITES = (
    "SELECT table_name || '.' || column_name FROM information_schema.columns "
    "WHERE table_schema = 'public' AND ("
    + " OR ".join(f"column_name ILIKE '%{fragment}%'" for fragment in FRAGMENTS_INTERDITS)
    + ")"
)


@pytest.fixture(autouse=True)
def ecole(base_vide):
    pose = psql(
        f"INSERT INTO etablissement (id, nom) VALUES ('{ETAB}', 'Ecole Al-Nour');"
        f"INSERT INTO ressource (id, etablissement_id, libelle) "
        f"VALUES ('{ENS}', '{ETAB}', 'Mme B.');"
        f"INSERT INTO enseignant (id, etablissement_id, nom) "
        f"VALUES ('{ENS}', '{ETAB}', 'Mme B.');"
        f"INSERT INTO annee_scolaire (id, etablissement_id, libelle, date_debut, date_fin, active)"
        f" VALUES ('{ANNEE}', '{ETAB}', '2025-2026', '2025-09-07', '2026-06-25', true);"
        f"INSERT INTO niveau (id, etablissement_id, libelle_i18n, ordre) "
        f"VALUES ('{NIVEAU}', '{ETAB}', '{{\"fr\": \"CM1\"}}'::jsonb, 4);"
        f"INSERT INTO classe (id, etablissement_id, niveau_id, annee_scolaire_id, libelle,"
        f" enseignant_principal_id) "
        f"VALUES ('{CLASSE}', '{ETAB}', '{NIVEAU}', '{ANNEE}', 'CM1 B', '{ENS}');"
        f"INSERT INTO eleve (id, etablissement_id, classe_id, prenom, nom, identifiant_interne,"
        f" date_naissance_annee) "
        f"VALUES ('{ELEVE}', '{ETAB}', '{CLASSE}', 'Ahmed', 'Ali', '2025-0101', 2015);"
        f"INSERT INTO famille (id, etablissement_id, nom_affiche) "
        f"VALUES ('{FAMILLE}', '{ETAB}', 'Famille Ali');"
        f"INSERT INTO parent (id, famille_id, lien, est_referent) "
        f"VALUES ('{PARENT}', '{FAMILLE}', 'mere', true);"
    )
    assert pose.returncode == 0, pose.stderr


# -- minimisation des donnees de mineurs (§8.1) ------------------------


def test_une_date_de_naissance_complete_ne_rentre_pas_en_base():
    """Le type entier rend la fuite impossible, pas seulement improbable.

    C'est la protection qui compte face a un import de tableur : personne
    n'aura relu les 1 200 lignes du fichier de l'ecole.
    """
    complete = psql(
        "INSERT INTO eleve (etablissement_id, classe_id, prenom, nom, identifiant_interne, "
        "date_naissance_annee) VALUES "
        f"('{ETAB}', '{CLASSE}', 'Sagal', 'Ali', '2025-0102', '2017-03-04')"
    )
    assert complete.returncode != 0


@pytest.mark.parametrize("annee", [1800, 1989, 2101])
def test_une_annee_de_naissance_invraisemblable_est_refusee(annee):
    hors_bornes = psql(
        "INSERT INTO eleve (etablissement_id, classe_id, prenom, nom, identifiant_interne, "
        "date_naissance_annee) VALUES "
        f"('{ETAB}', '{CLASSE}', 'Sagal', 'Ali', '2025-0102', {annee})"
    )
    assert hors_bornes.returncode != 0
    assert "eleve_annee_naissance_plausible" in hors_bornes.stderr


def test_aucune_colonne_du_schema_ne_touche_au_hors_perimetre():
    """Vue d'ensemble : ce que le §3 exclut definitivement n'existe nulle part.

    Le pendant SQL de ``tests/test_donnees_minimales_eleve.py``.
    """
    fautives = valeurs(REQUETE_COLONNES_INTERDITES)
    assert not fautives, f"colonnes hors perimetre (§3, §8.1) : {fautives}"


def test_la_recherche_de_colonnes_interdites_detecte_vraiment_quelque_chose():
    """Un test de garde qui ne detecte rien passe pour toujours.

    On ajoute une colonne fautive, on verifie qu'elle est vue, on la retire.
    """
    assert psql("ALTER TABLE eleve ADD COLUMN moyenne_generale numeric").returncode == 0
    try:
        assert "eleve.moyenne_generale" in valeurs(REQUETE_COLONNES_INTERDITES)
    finally:
        assert psql("ALTER TABLE eleve DROP COLUMN moyenne_generale").returncode == 0
    assert valeurs(REQUETE_COLONNES_INTERDITES) == []


def test_l_annee_de_naissance_reste_facultative():
    """Un tableau d'ecole incomplet ne doit pas bloquer l'import (§11, lot 8)."""
    sans_annee = psql(
        "INSERT INTO eleve (etablissement_id, classe_id, prenom, nom, identifiant_interne) "
        f"VALUES ('{ETAB}', '{CLASSE}', 'Sagal', 'Ali', '2025-0102')"
    )
    assert sans_annee.returncode == 0, sans_annee.stderr


# -- cloisonnement familial (§8.2) -------------------------------------


def test_un_lien_parent_eleve_ne_peut_pas_etre_cree_deux_fois():
    premier = psql(
        f"INSERT INTO lien_parent_eleve (parent_id, eleve_id) VALUES ('{PARENT}', '{ELEVE}')"
    )
    assert premier.returncode == 0, premier.stderr
    doublon = psql(
        f"INSERT INTO lien_parent_eleve (parent_id, eleve_id) VALUES ('{PARENT}', '{ELEVE}')"
    )
    assert doublon.returncode != 0


def test_un_lien_vers_un_eleve_inexistant_est_refuse():
    """Le cloisonnement ne vaut que si la table de liens est integre."""
    orphelin = psql(
        "INSERT INTO lien_parent_eleve (parent_id, eleve_id) VALUES "
        f"('{PARENT}', '00000000-0000-0000-0000-000000000000')"
    )
    assert orphelin.returncode != 0


def test_supprimer_un_eleve_supprime_ses_liens():
    """Export et suppression des donnees d'une famille (§8.3, critere §12)."""
    assert (
        psql(
            f"INSERT INTO lien_parent_eleve (parent_id, eleve_id) "
            f"VALUES ('{PARENT}', '{ELEVE}')"
        ).returncode
        == 0
    )
    assert psql(f"DELETE FROM eleve WHERE id = '{ELEVE}'").returncode == 0
    assert valeurs(
        f"SELECT count(*) FROM lien_parent_eleve WHERE eleve_id = '{ELEVE}'"
    ) == ["0"]


def test_l_autorisation_de_recuperer_vaut_vrai_par_defaut():
    assert (
        psql(
            f"INSERT INTO lien_parent_eleve (parent_id, eleve_id) "
            f"VALUES ('{PARENT}', '{ELEVE}')"
        ).returncode
        == 0
    )
    assert valeurs(
        f"SELECT autorise_a_recuperer FROM lien_parent_eleve WHERE eleve_id = '{ELEVE}'"
    ) == ["t"]


# -- coherence de la structure scolaire --------------------------------


def test_une_seule_annee_scolaire_active_par_etablissement():
    seconde = psql(
        "INSERT INTO annee_scolaire (etablissement_id, libelle, date_debut, date_fin, active) "
        f"VALUES ('{ETAB}', '2026-2027', '2026-09-06', '2027-06-24', true)"
    )
    assert seconde.returncode != 0
    assert "annee_scolaire_une_seule_active" in seconde.stderr


def test_une_annee_inactive_supplementaire_est_permise():
    archive = psql(
        "INSERT INTO annee_scolaire (etablissement_id, libelle, date_debut, date_fin, active) "
        f"VALUES ('{ETAB}', '2024-2025', '2024-09-08', '2025-06-26', false)"
    )
    assert archive.returncode == 0, archive.stderr


def test_deux_eleves_ne_partagent_pas_un_identifiant_interne():
    doublon = psql(
        "INSERT INTO eleve (etablissement_id, classe_id, prenom, nom, identifiant_interne) "
        f"VALUES ('{ETAB}', '{CLASSE}', 'Homonyme', 'Ali', '2025-0101')"
    )
    assert doublon.returncode != 0
    assert "eleve_identifiant_unique" in doublon.stderr


def test_deux_classes_ne_partagent_pas_un_libelle_dans_une_annee():
    doublon = psql(
        "INSERT INTO classe (etablissement_id, niveau_id, annee_scolaire_id, libelle) "
        f"VALUES ('{ETAB}', '{NIVEAU}', '{ANNEE}', 'CM1 B')"
    )
    assert doublon.returncode != 0
    assert "classe_libelle_unique" in doublon.stderr


def test_un_libelle_de_niveau_vide_est_refuse():
    """Un niveau sans libelle officiel casserait l'affichage dans les quatre
    langues (§7)."""
    vide = psql(
        "INSERT INTO niveau (etablissement_id, libelle_i18n, ordre) "
        f"VALUES ('{ETAB}', '{{}}'::jsonb, 9)"
    )
    assert vide.returncode != 0
    assert "niveau_libelle_non_vide" in vide.stderr


def test_un_enseignant_est_necessairement_une_ressource_du_noyau():
    """C'est ce qui garantit que le moteur de creneaux sait le reserver."""
    orphelin = psql(
        "INSERT INTO enseignant (id, etablissement_id, nom) VALUES "
        f"('00000000-0000-0000-0000-000000000000', '{ETAB}', 'M. Fantome')"
    )
    assert orphelin.returncode != 0


def test_un_niveau_utilise_ne_peut_pas_etre_supprime():
    """Supprimer un niveau deplacerait silencieusement des eleves."""
    suppression = psql(f"DELETE FROM niveau WHERE id = '{NIVEAU}'")
    assert suppression.returncode != 0


# -- specialisation scolaire du rendez-vous ----------------------------


def test_le_rendez_vous_porte_desormais_l_eleve_le_parent_et_le_motif():
    colonnes = valeurs(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = 'rendez_vous' "
        "AND column_name IN ('eleve_id', 'parent_id', 'motif_id') ORDER BY column_name"
    )
    assert colonnes == ["eleve_id", "motif_id", "parent_id"]


def test_un_rendez_vous_scolaire_complet_s_enregistre():
    complet = psql(
        "INSERT INTO rendez_vous (etablissement_id, ressource_id, eleve_id, parent_id, "
        "debut_at, fin_at, statut) VALUES "
        f"('{ETAB}', '{ENS}', '{ELEVE}', '{PARENT}', "
        "'2025-09-22 10:00+03', '2025-09-22 10:30+03', 'confirme')"
    )
    assert complet.returncode == 0, complet.stderr
