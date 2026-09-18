"""Algebre d'intervalles de temps.

Tout le moteur de creneaux se ramene a trois operations sur des intervalles
semi-ouverts ``[debut, fin)`` : fusionner, intersecter, soustraire. Les
isoler ici evite de refaire l'arithmetique de bornes dans chaque regle
metier — c'est la ou se cachent les bugs d'un jour ou d'une minute.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from core.errors import ErreurConfiguration
from core.temps import exiger_conscient


@dataclass(frozen=True, order=True)
class Intervalle:
    """Intervalle semi-ouvert ``[debut, fin)``, conscient du fuseau."""

    debut: datetime
    fin: datetime

    def __post_init__(self) -> None:
        exiger_conscient(self.debut, "Intervalle.debut")
        exiger_conscient(self.fin, "Intervalle.fin")
        if self.fin <= self.debut:
            raise ErreurConfiguration("un intervalle doit se terminer apres son debut")

    @property
    def duree(self) -> timedelta:
        return self.fin - self.debut

    @property
    def duree_min(self) -> float:
        return self.duree.total_seconds() / 60

    def chevauche(self, autre: Intervalle) -> bool:
        return self.debut < autre.fin and autre.debut < self.fin

    def contient(self, autre: Intervalle) -> bool:
        return self.debut <= autre.debut and autre.fin <= self.fin

    def est_jointif(self, autre: Intervalle) -> bool:
        return self.fin == autre.debut or autre.fin == self.debut

    def intersection(self, autre: Intervalle) -> Intervalle | None:
        debut = max(self.debut, autre.debut)
        fin = min(self.fin, autre.fin)
        if fin <= debut:
            return None
        return Intervalle(debut, fin)

    def soustraire(self, autre: Intervalle) -> list[Intervalle]:
        """Retire ``autre`` de ``self``. Peut rendre 0, 1 ou 2 morceaux."""
        if not self.chevauche(autre):
            return [self]
        morceaux: list[Intervalle] = []
        if self.debut < autre.debut:
            morceaux.append(Intervalle(self.debut, autre.debut))
        if autre.fin < self.fin:
            morceaux.append(Intervalle(autre.fin, self.fin))
        return morceaux


def fusionner(intervalles: Iterable[Intervalle]) -> list[Intervalle]:
    """Trie et fusionne les intervalles qui se chevauchent ou se touchent."""
    ordonnes = sorted(intervalles)
    if not ordonnes:
        return []
    resultat = [ordonnes[0]]
    for courant in ordonnes[1:]:
        dernier = resultat[-1]
        if courant.debut <= dernier.fin:
            resultat[-1] = Intervalle(dernier.debut, max(dernier.fin, courant.fin))
        else:
            resultat.append(courant)
    return resultat


def soustraire_tous(
    base: Iterable[Intervalle], retraits: Iterable[Intervalle]
) -> list[Intervalle]:
    """Retire de ``base`` tout ce que couvre ``retraits``."""
    restants = list(base)
    for retrait in retraits:
        suivants: list[Intervalle] = []
        for morceau in restants:
            suivants.extend(morceau.soustraire(retrait))
        restants = suivants
    return fusionner(restants)


def intersecter_tous(
    base: Iterable[Intervalle], masques: Iterable[Intervalle]
) -> list[Intervalle]:
    """Ne garde de ``base`` que ce qui tombe dans l'un des ``masques``."""
    masques = list(masques)
    if not masques:
        return []
    resultat: list[Intervalle] = []
    for morceau in base:
        for masque in masques:
            commun = morceau.intersection(masque)
            if commun is not None:
                resultat.append(commun)
    return fusionner(resultat)
