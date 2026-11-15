"""Normalisation des numeros.

Le rattachement d'un contact a une famille repose sur l'egalite de cette
chaine. Une tolerance de trop ici, et un message atterrit dans la mauvaise
famille — exactement le defaut decrit au §14.
"""

from __future__ import annotations

import pytest

from core.telephone import NumeroInvalide, est_valide, normaliser

CANONIQUE = "+25377123456"


@pytest.mark.parametrize(
    "saisie",
    [
        "+25377123456",
        "+253 77 12 34 56",
        "+253-77-12-34-56",
        "0025377123456",
        "25377123456",
        "77123456",
        "77 12 34 56",
        "077123456",
        "  +25377123456  ",
    ],
)
def test_toutes_les_ecritures_courantes_donnent_la_meme_forme(saisie):
    assert normaliser(saisie) == CANONIQUE


@pytest.mark.parametrize(
    "saisie",
    [
        "",
        "   ",
        "7712345",  # trop court
        "771234567",  # trop long
        "+33612345678",  # indicatif non pris en charge
        "77+123456",
        "allo",
    ],
)
def test_une_saisie_douteuse_est_refusee_plutot_que_devinee(saisie):
    with pytest.raises(NumeroInvalide):
        normaliser(saisie)
    assert not est_valide(saisie)


def test_deux_numeros_differents_ne_se_confondent_pas():
    assert normaliser("77123456") != normaliser("77123457")
