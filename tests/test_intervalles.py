"""Algebre d'intervalles — la base arithmetique du moteur de creneaux."""

from __future__ import annotations

from datetime import time

import pytest

from core.errors import ErreurConfiguration
from core.scheduling import Intervalle, fusionner, intersecter_tous, soustraire_tous
from tests.conftest import LUNDI, instant


def iv(debut: time, fin: time) -> Intervalle:
    return Intervalle(instant(LUNDI, debut), instant(LUNDI, fin))


def test_un_intervalle_vide_ou_inverse_est_refuse():
    with pytest.raises(ErreurConfiguration):
        iv(time(10, 0), time(10, 0))
    with pytest.raises(ErreurConfiguration):
        iv(time(11, 0), time(10, 0))


def test_datetime_naif_refuse():
    from datetime import datetime

    with pytest.raises(ErreurConfiguration):
        Intervalle(datetime(2025, 9, 22, 8, 0), datetime(2025, 9, 22, 9, 0))


def test_intervalles_jointifs_ne_se_chevauchent_pas():
    a = iv(time(10, 0), time(10, 30))
    b = iv(time(10, 30), time(11, 0))
    assert not a.chevauche(b)
    assert a.est_jointif(b)


def test_chevauchement_partiel():
    assert iv(time(10, 0), time(11, 0)).chevauche(iv(time(10, 30), time(11, 30)))


def test_intersection():
    commun = iv(time(8, 0), time(12, 0)).intersection(iv(time(10, 0), time(14, 0)))
    assert commun == iv(time(10, 0), time(12, 0))
    assert iv(time(8, 0), time(9, 0)).intersection(iv(time(9, 0), time(10, 0))) is None


def test_soustraction_creuse_un_trou():
    morceaux = iv(time(8, 0), time(12, 0)).soustraire(iv(time(10, 0), time(10, 30)))
    assert morceaux == [iv(time(8, 0), time(10, 0)), iv(time(10, 30), time(12, 0))]


def test_soustraction_totale_ne_laisse_rien():
    assert iv(time(10, 0), time(11, 0)).soustraire(iv(time(9, 0), time(12, 0))) == []


def test_fusion_des_plages_jointives_et_chevauchantes():
    fusionnes = fusionner(
        [
            iv(time(10, 0), time(11, 0)),
            iv(time(8, 0), time(9, 0)),
            iv(time(9, 0), time(10, 30)),
            iv(time(14, 0), time(15, 0)),
        ]
    )
    assert fusionnes == [iv(time(8, 0), time(11, 0)), iv(time(14, 0), time(15, 0))]


def test_soustraire_tous_applique_chaque_retrait():
    restants = soustraire_tous(
        [iv(time(8, 0), time(12, 0))],
        [iv(time(9, 0), time(9, 30)), iv(time(11, 0), time(13, 0))],
    )
    assert restants == [iv(time(8, 0), time(9, 0)), iv(time(9, 30), time(11, 0))]


def test_intersecter_tous_sans_masque_ne_garde_rien():
    assert intersecter_tous([iv(time(8, 0), time(12, 0))], []) == []
