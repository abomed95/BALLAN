"""Normalisation des numeros de telephone.

Un parent ecrit son numero de dix facons : ``77 12 34 56``, ``077123456``,
``00253 77123456``, ``+253-77-12-34-56``. Le rattachement d'un contact a une
famille repose entierement sur l'egalite de ce numero ; toute tolerance
introduite ailleurs que dans cette fonction est un trou de securite.

Forme canonique retenue : ``+253XXXXXXXX`` (indicatif + 8 chiffres pour
Djibouti). La longueur nationale reste un parametre, le produit n'etant pas
promis a Djibouti pour toujours.
"""

from __future__ import annotations

import re

from core.errors import ErreurConfiguration

INDICATIF_DEFAUT = "253"
LONGUEUR_NATIONALE_DEFAUT = 8

_NON_CHIFFRE = re.compile(r"[^0-9+]")


class NumeroInvalide(ErreurConfiguration):
    """Numero impossible a ramener a une forme canonique."""

    code = "telephone.invalide"


def normaliser(
    numero: str,
    indicatif: str = INDICATIF_DEFAUT,
    longueur_nationale: int = LONGUEUR_NATIONALE_DEFAUT,
) -> str:
    """Retourne le numero sous la forme ``+<indicatif><national>``.

    Leve ``NumeroInvalide`` plutot que de deviner : mieux vaut escalader au
    secretariat qu'associer un message a la mauvaise famille.
    """
    if not numero or not numero.strip():
        raise NumeroInvalide("numero vide")

    brut = _NON_CHIFFRE.sub("", numero.strip())

    # 00253... -> +253...
    if brut.startswith("00"):
        brut = "+" + brut[2:]
    # Un '+' ailleurs qu'en tete n'a pas de sens.
    if "+" in brut[1:]:
        raise NumeroInvalide("caractere '+' mal place")

    if brut.startswith("+"):
        chiffres = brut[1:]
        if not chiffres.startswith(indicatif):
            raise NumeroInvalide("indicatif pays non pris en charge")
        national = chiffres[len(indicatif) :]
    else:
        chiffres = brut
        if chiffres.startswith(indicatif) and len(chiffres) == len(indicatif) + longueur_nationale:
            national = chiffres[len(indicatif) :]
        else:
            # Zero de service en tete d'un numero compose localement.
            national = chiffres.lstrip("0") if len(chiffres) > longueur_nationale else chiffres

    if not national.isdigit() or len(national) != longueur_nationale:
        raise NumeroInvalide(f"longueur nationale attendue : {longueur_nationale} chiffres")

    return f"+{indicatif}{national}"


def est_valide(
    numero: str,
    indicatif: str = INDICATIF_DEFAUT,
    longueur_nationale: int = LONGUEUR_NATIONALE_DEFAUT,
) -> bool:
    try:
        normaliser(numero, indicatif, longueur_nationale)
    except NumeroInvalide:
        return False
    return True
