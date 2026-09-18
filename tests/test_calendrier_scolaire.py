"""Calendrier scolaire : periodes, vacances, reprise, et pont vers le noyau.

« Le calendrier scolaire est le coeur de la configuration — tout le reste en
depend » (§2). Le test le plus important de ce fichier est le dernier : il
verifie que les vacances declarees par l'ecole suffisent a faire taire le
moteur de creneaux, sans qu'une regle « vacances » ait ete ajoutee au noyau.
"""

from __future__ import annotations

from datetime import date

import pytest

from core.errors import ErreurConfiguration
from tests import fixtures_ecole as fx
from verticals.school.calendar_school import CalendrierScolaire, PeriodeNonScolaire
from verticals.school.models import Periode, TypePeriode

# Reperes du calendrier de fixtures_ecole.
JOUR_DE_CLASSE = date(2025, 9, 22)  # lundi du premier trimestre
VENDREDI = date(2025, 9, 26)  # jour non ouvre
EN_VACANCES = date(2025, 12, 22)  # lundi, pendant les vacances de fin de trimestre
JOUR_D_EXAMENS = date(2026, 3, 23)  # lundi de la semaine d'examens
HORS_ANNEE = date(2026, 8, 10)


@pytest.fixture
def scolaire() -> CalendrierScolaire:
    return CalendrierScolaire.depuis_configuration(
        annee=fx.ANNEE, periodes=fx.PERIODES, calendrier=fx.calendrier_noyau()
    )


# -- periodes ----------------------------------------------------------


def test_la_periode_principale_est_la_plus_specifique(scolaire):
    """Une semaine d'examens tombe dans un trimestre : c'est elle qu'on annonce."""
    couvrantes = {p.id for p in scolaire.periodes_du_jour(JOUR_D_EXAMENS)}
    assert couvrantes == {"t2", "examens-t2"}
    assert scolaire.periode_principale(JOUR_D_EXAMENS).id == "examens-t2"


def test_la_periode_principale_d_un_jour_ordinaire(scolaire):
    assert scolaire.periode_principale(JOUR_DE_CLASSE).id == "t1"


def test_aucune_periode_hors_annee(scolaire):
    assert scolaire.periodes_du_jour(HORS_ANNEE) == []
    assert scolaire.periode_principale(HORS_ANNEE) is None


def test_une_periode_d_une_autre_annee_est_refusee():
    intruse = Periode(
        id="t1-ancien",
        annee_scolaire_id="annee-2024",
        libelle_i18n={"fr": "Premier trimestre"},
        type=TypePeriode.TRIMESTRE,
        date_debut=date(2024, 9, 8),
        date_fin=date(2024, 12, 12),
    )
    with pytest.raises(ErreurConfiguration):
        CalendrierScolaire(
            annee=fx.ANNEE, calendrier=fx.calendrier_noyau(), periodes=[intruse]
        )


# -- jours de classe ---------------------------------------------------


def test_un_lundi_de_trimestre_est_un_jour_de_classe(scolaire):
    assert scolaire.est_jour_de_classe(JOUR_DE_CLASSE)


def test_le_vendredi_n_est_pas_un_jour_de_classe(scolaire):
    assert not scolaire.est_jour_de_classe(VENDREDI)


def test_les_vacances_ne_sont_pas_des_jours_de_classe(scolaire):
    assert scolaire.est_en_vacances(EN_VACANCES)
    assert not scolaire.est_jour_de_classe(EN_VACANCES)


def test_hors_annee_scolaire_rien_n_est_jour_de_classe(scolaire):
    assert not scolaire.est_jour_de_classe(HORS_ANNEE)


def test_les_jours_d_examens_restent_des_jours_de_classe(scolaire):
    assert scolaire.est_jour_de_classe(JOUR_D_EXAMENS)


def test_une_semaine_ordinaire_compte_cinq_jours_de_classe(scolaire):
    jours = scolaire.jours_de_classe(date(2025, 9, 21), date(2025, 9, 27))
    assert len(jours) == 5
    assert jours[0] == date(2025, 9, 21)  # dimanche
    assert jours[-1] == date(2025, 9, 25)  # jeudi


# -- garde posee avant de placer quoi que ce soit ----------------------


def test_une_reunion_pendant_les_vacances_est_refusee(scolaire):
    """§13 : « Reunion creee pendant les vacances — refus ou alerte. »"""
    with pytest.raises(PeriodeNonScolaire) as erreur:
        scolaire.exiger_jour_de_classe(EN_VACANCES)
    assert "vacances" in str(erreur.value)


def test_une_reunion_hors_annee_scolaire_est_refusee(scolaire):
    with pytest.raises(PeriodeNonScolaire) as erreur:
        scolaire.exiger_jour_de_classe(HORS_ANNEE)
    assert "annee scolaire" in str(erreur.value)


def test_une_reunion_un_jour_non_ouvre_est_refusee(scolaire):
    with pytest.raises(PeriodeNonScolaire) as erreur:
        scolaire.exiger_jour_de_classe(VENDREDI)
    assert "jour ouvre" in str(erreur.value)


def test_un_jour_de_classe_passe_la_garde(scolaire):
    scolaire.exiger_jour_de_classe(JOUR_DE_CLASSE)


# -- reprise des cours -------------------------------------------------


def test_la_reprise_apres_les_vacances_est_le_premier_jour_ouvre(scolaire):
    """Alimente le rappel « reprise des cours » a J-2 (§6)."""
    assert scolaire.prochaine_reprise(date(2025, 12, 20)) == date(2026, 1, 4)


def test_la_reprise_apres_un_jeudi_saute_le_week_end(scolaire):
    assert scolaire.prochaine_reprise(date(2025, 9, 25)) == date(2025, 9, 28)


def test_aucune_reprise_apres_la_fin_de_l_annee(scolaire):
    assert scolaire.prochaine_reprise(date(2026, 6, 25)) is None


# -- pont vers le noyau ------------------------------------------------


def test_les_vacances_deviennent_des_fermetures_d_etablissement():
    exceptions = CalendrierScolaire.exceptions_depuis_periodes(fx.PERIODES, fx.ETAB)
    assert {e.motif for e in exceptions} == {"vacances"}
    assert all(e.ressource_id is None for e in exceptions)
    assert len(exceptions) == 2


def test_le_moteur_de_creneaux_se_tait_pendant_les_vacances(scolaire):
    """Le test qui compte : le noyau n'a aucune notion de vacances scolaires,
    et pourtant il cesse de proposer des creneaux."""
    from core.scheduling import MoteurCreneaux

    moteur = MoteurCreneaux(calendrier=scolaire.calendrier)
    ordinaire = moteur.creneaux_du_jour("ens-b", JOUR_DE_CLASSE, duree_min=30)
    pendant_vacances = moteur.creneaux_du_jour("ens-b", EN_VACANCES, duree_min=30)

    assert len(ordinaire) == 4  # 08:00 -> 10:00
    assert pendant_vacances == []


def test_injecter_deux_fois_les_vacances_ne_les_duplique_pas():
    calendrier = fx.calendrier_noyau()
    CalendrierScolaire.depuis_configuration(fx.ANNEE, fx.PERIODES, calendrier)
    CalendrierScolaire.depuis_configuration(fx.ANNEE, fx.PERIODES, calendrier)
    assert len(calendrier.exceptions) == 2
