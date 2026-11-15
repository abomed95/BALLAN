"""Calendrier : jours ouvres, vacances, Ramadan, ouvertures exceptionnelles."""

from __future__ import annotations

from datetime import date, time

from core.models import Jour, TypeException
from core.scheduling import Intervalle
from tests.conftest import (
    DIMANCHE,
    LUNDI,
    SAMEDI,
    VENDREDI,
    calendrier,
    dispo,
    exception_agenda,
    instant,
)


def _grille(enseignante):
    """08:00-12:00 et 14:00-16:00, du dimanche au jeudi."""
    plages = ((time(8, 0), time(12, 0)), (time(14, 0), time(16, 0)))
    return [
        dispo(enseignante.id, jour, debut, fin, identifiant=f"d-{jour.value}-{debut.hour}")
        for jour in (Jour.DIMANCHE, Jour.LUNDI, Jour.MARDI, Jour.MERCREDI, Jour.JEUDI)
        for debut, fin in plages
    ]


def test_semaine_ouvree_par_defaut_dimanche_a_jeudi(ecole):
    cal = calendrier(ecole)
    assert cal.est_ouvert(DIMANCHE)
    assert cal.est_ouvert(LUNDI)
    assert not cal.est_ouvert(VENDREDI)
    assert not cal.est_ouvert(SAMEDI)


def test_plages_du_jour_ouvre(ecole, enseignante):
    cal = calendrier(ecole, _grille(enseignante))
    assert cal.plages(enseignante.id, LUNDI) == [
        Intervalle(instant(LUNDI, time(8, 0)), instant(LUNDI, time(12, 0))),
        Intervalle(instant(LUNDI, time(14, 0)), instant(LUNDI, time(16, 0))),
    ]


def test_aucune_plage_un_jour_non_ouvre(ecole, enseignante):
    cal = calendrier(ecole, _grille(enseignante))
    assert cal.plages(enseignante.id, VENDREDI) == []


def test_vacances_ferment_l_etablissement_entier(ecole, enseignante):
    vacances = exception_agenda(
        TypeException.FERMETURE,
        du=date(2025, 9, 21),
        au=date(2025, 9, 25),
        motif="vacances",
    )
    cal = calendrier(ecole, _grille(enseignante), [vacances])
    assert not cal.est_ouvert(LUNDI)
    assert cal.est_ferme(LUNDI)
    assert cal.plages(enseignante.id, LUNDI) == []


def test_absence_d_une_enseignante_ne_ferme_pas_l_ecole(ecole, enseignante):
    absence = exception_agenda(
        TypeException.FERMETURE,
        du=LUNDI,
        ressource_id=enseignante.id,
        motif="absence",
    )
    cal = calendrier(ecole, _grille(enseignante), [absence])
    assert cal.plages(enseignante.id, LUNDI) == []
    assert cal.est_ouvert(LUNDI)  # l'etablissement, lui, reste ouvert
    assert not cal.est_ferme(LUNDI)


def test_fermeture_partielle_creuse_un_trou(ecole, enseignante):
    conseil = exception_agenda(
        TypeException.FERMETURE,
        du=LUNDI,
        debut=time(10, 0),
        fin=time(11, 0),
        motif="conseil de classe",
    )
    cal = calendrier(ecole, _grille(enseignante), [conseil])
    assert cal.plages(enseignante.id, LUNDI) == [
        Intervalle(instant(LUNDI, time(8, 0)), instant(LUNDI, time(10, 0))),
        Intervalle(instant(LUNDI, time(11, 0)), instant(LUNDI, time(12, 0))),
        Intervalle(instant(LUNDI, time(14, 0)), instant(LUNDI, time(16, 0))),
    ]


def test_horaire_de_ramadan_rogne_la_journee(ecole, enseignante):
    ramadan = exception_agenda(
        TypeException.HORAIRE_REDUIT,
        du=date(2025, 9, 21),
        au=date(2025, 9, 25),
        debut=time(8, 0),
        fin=time(13, 0),
        motif="ramadan",
    )
    cal = calendrier(ecole, _grille(enseignante), [ramadan])
    # La matinee est conservee, l'apres-midi disparait entierement.
    assert cal.plages(enseignante.id, LUNDI) == [
        Intervalle(instant(LUNDI, time(8, 0)), instant(LUNDI, time(12, 0)))
    ]


def test_ouverture_exceptionnelle_un_samedi_de_reunion(ecole, enseignante):
    reunion = exception_agenda(
        TypeException.OUVERTURE,
        du=SAMEDI,
        debut=time(9, 0),
        fin=time(12, 0),
        motif="reunion parents-professeurs",
    )
    cal = calendrier(ecole, _grille(enseignante), [reunion])
    assert cal.est_ouvert(SAMEDI)
    assert cal.plages(enseignante.id, SAMEDI) == [
        Intervalle(instant(SAMEDI, time(9, 0)), instant(SAMEDI, time(12, 0)))
    ]


def test_une_fermeture_gagne_toujours_sur_une_ouverture(ecole, enseignante):
    """L'ordre d'application n'est pas negociable : fermer est plus sur."""
    reunion = exception_agenda(
        TypeException.OUVERTURE, du=SAMEDI, debut=time(9, 0), fin=time(12, 0)
    )
    ferie = exception_agenda(TypeException.FERMETURE, du=SAMEDI, motif="jour ferie")
    cal = calendrier(ecole, _grille(enseignante), [reunion, ferie])
    assert not cal.est_ouvert(SAMEDI)
    assert cal.plages(enseignante.id, SAMEDI) == []


def test_exception_d_une_autre_ecole_est_ignoree(ecole, enseignante):
    ailleurs = exception_agenda(
        TypeException.FERMETURE, du=LUNDI, etablissement_id="etab-2"
    )
    cal = calendrier(ecole, _grille(enseignante), [ailleurs])
    assert cal.est_ouvert(LUNDI)
    assert cal.plages(enseignante.id, LUNDI) != []
