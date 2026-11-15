"""Moteur de creneaux : decoupage, passe, delai minimal, horizon.

Le lot 0 n'est pas termine tant que ce fichier n'est pas vert (BALLAN.md §11).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, time

import pytest

from core.errors import ErreurConfiguration, HorsOuverture
from core.models import Jour, Occupation, StatutRendezVous, TypeException
from tests.conftest import (
    DIMANCHE,
    LUNDI,
    MARDI,
    VENDREDI,
    dispo,
    exception_agenda,
    instant,
    moteur,
)


def test_une_plage_de_quatre_heures_donne_huit_creneaux_de_trente(
    semaine_type, enseignante
):
    creneaux = semaine_type.creneaux_du_jour(enseignante.id, LUNDI, duree_min=30)
    assert len(creneaux) == 8
    assert creneaux[0].debut == instant(LUNDI, time(8, 0))
    assert creneaux[0].fin == instant(LUNDI, time(8, 30))
    assert creneaux[-1].fin == instant(LUNDI, time(12, 0))


def test_les_creneaux_sont_ordonnes_et_jointifs(semaine_type, enseignante):
    creneaux = semaine_type.creneaux_du_jour(enseignante.id, LUNDI, duree_min=30)
    for precedent, suivant in zip(creneaux, creneaux[1:], strict=False):
        assert precedent.fin == suivant.debut


def test_le_reliquat_trop_court_est_abandonne(ecole, enseignante):
    """08:00-09:10 avec des creneaux de 30 min : deux creneaux, pas trois."""
    m = moteur(ecole, [dispo(enseignante.id, Jour.LUNDI, time(8, 0), time(9, 10))])
    creneaux = m.creneaux_du_jour(enseignante.id, LUNDI, duree_min=30)
    assert [c.debut.time() for c in creneaux] == [time(8, 0), time(8, 30)]


def test_un_pas_plus_court_que_la_duree_produit_des_departs_decales(
    semaine_type, enseignante
):
    creneaux = semaine_type.creneaux_du_jour(
        enseignante.id, LUNDI, duree_min=30, pas_min=15
    )
    assert [c.debut.time() for c in creneaux[:4]] == [
        time(8, 0),
        time(8, 15),
        time(8, 30),
        time(8, 45),
    ]


def test_aucun_creneau_un_jour_non_ouvre(semaine_type, enseignante):
    assert semaine_type.creneaux_du_jour(enseignante.id, VENDREDI, duree_min=30) == []


def test_un_rendez_vous_confirme_retire_son_creneau(semaine_type, enseignante):
    pris = Occupation(
        ressource_id=enseignante.id,
        debut=instant(LUNDI, time(9, 0)),
        fin=instant(LUNDI, time(9, 30)),
        statut=StatutRendezVous.CONFIRME,
        reference_id="rdv-1",
    )
    creneaux = semaine_type.creneaux_du_jour(
        enseignante.id, LUNDI, duree_min=30, occupations=[pris]
    )
    assert time(9, 0) not in [c.debut.time() for c in creneaux]
    assert len(creneaux) == 7


def test_un_rendez_vous_annule_libere_son_creneau(semaine_type, enseignante):
    annule = Occupation(
        ressource_id=enseignante.id,
        debut=instant(LUNDI, time(9, 0)),
        fin=instant(LUNDI, time(9, 30)),
        statut=StatutRendezVous.ANNULE,
        reference_id="rdv-1",
    )
    creneaux = semaine_type.creneaux_du_jour(
        enseignante.id, LUNDI, duree_min=30, occupations=[annule]
    )
    assert len(creneaux) == 8


def test_l_occupation_d_une_autre_enseignante_ne_bloque_rien(semaine_type, enseignante):
    ailleurs = Occupation(
        ressource_id="ens-2",
        debut=instant(LUNDI, time(9, 0)),
        fin=instant(LUNDI, time(9, 30)),
        reference_id="rdv-2",
    )
    creneaux = semaine_type.creneaux_du_jour(
        enseignante.id, LUNDI, duree_min=30, occupations=[ailleurs]
    )
    assert len(creneaux) == 8


def test_le_passe_n_est_jamais_propose(semaine_type, enseignante):
    creneaux = semaine_type.creneaux_du_jour(
        enseignante.id,
        LUNDI,
        duree_min=30,
        maintenant=instant(LUNDI, time(9, 45)),
    )
    assert [c.debut.time() for c in creneaux] == [
        time(10, 0),
        time(10, 30),
        time(11, 0),
        time(11, 30),
    ]


def test_le_delai_minimal_repousse_le_premier_creneau(ecole, enseignante):
    """Une ecole qui exige deux heures de preavis ne propose pas 10:00 a 09:00."""
    avec_preavis = replace(ecole, delai_minimal_min=120)
    m = moteur(
        avec_preavis,
        [dispo(enseignante.id, Jour.LUNDI, time(8, 0), time(12, 0))],
    )
    creneaux = m.creneaux_du_jour(
        enseignante.id, LUNDI, duree_min=30, maintenant=instant(LUNDI, time(9, 0))
    )
    assert [c.debut.time() for c in creneaux] == [time(11, 0), time(11, 30)]


def test_prochains_creneaux_traverse_le_week_end(semaine_type, enseignante):
    """Jeudi soir, les creneaux suivants sont dimanche : vendredi et samedi
    ne sont pas ouvres."""
    jeudi = date(2025, 9, 25)
    creneaux = semaine_type.prochains_creneaux(
        enseignante.id,
        duree_min=30,
        maintenant=instant(jeudi, time(17, 0)),
        nombre=3,
    )
    assert len(creneaux) == 3
    assert all(c.debut.date() == date(2025, 9, 28) for c in creneaux)  # dimanche


def test_prochains_creneaux_respecte_le_nombre_demande(semaine_type, enseignante):
    creneaux = semaine_type.prochains_creneaux(
        enseignante.id, duree_min=30, maintenant=instant(DIMANCHE, time(7, 0)), nombre=3
    )
    assert len(creneaux) == 3
    assert [c.debut.time() for c in creneaux] == [time(8, 0), time(8, 30), time(9, 0)]


def test_horizon_trop_large_refuse(semaine_type, enseignante):
    with pytest.raises(ErreurConfiguration):
        semaine_type.creneaux_periode(
            enseignante.id, LUNDI, date(2027, 1, 1), duree_min=30
        )


def test_duree_de_creneau_absurde_refusee(semaine_type, enseignante):
    with pytest.raises(ErreurConfiguration):
        semaine_type.creneaux_du_jour(enseignante.id, LUNDI, duree_min=1)


def test_verifier_reservable_refuse_hors_ouverture(semaine_type, enseignante):
    with pytest.raises(HorsOuverture):
        semaine_type.verifier_reservable(
            enseignante.id,
            instant(LUNDI, time(15, 0)),
            instant(LUNDI, time(15, 30)),
        )


def test_verifier_reservable_accepte_un_creneau_ouvert_et_libre(
    semaine_type, enseignante
):
    semaine_type.verifier_reservable(
        enseignante.id, instant(LUNDI, time(9, 0)), instant(LUNDI, time(9, 30))
    )


def test_le_ramadan_reduit_le_nombre_de_creneaux(ecole, enseignante):
    grille = [
        dispo(enseignante.id, Jour.LUNDI, time(8, 0), time(12, 0), identifiant="m"),
        dispo(enseignante.id, Jour.LUNDI, time(14, 0), time(16, 0), identifiant="a"),
    ]
    ramadan = exception_agenda(
        TypeException.HORAIRE_REDUIT,
        du=LUNDI,
        au=MARDI,
        debut=time(8, 0),
        fin=time(11, 0),
        motif="ramadan",
    )
    normal = moteur(ecole, grille)
    reduit = moteur(ecole, grille, [ramadan])
    assert len(normal.creneaux_du_jour(enseignante.id, LUNDI, duree_min=30)) == 12
    assert len(reduit.creneaux_du_jour(enseignante.id, LUNDI, duree_min=30)) == 6
