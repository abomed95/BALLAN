"""Agenda : la seule porte par laquelle une reservation s'ecrit.

``AgendaMemoire`` reproduit en memoire la semantique de la contrainte
d'exclusion Postgres : la verification de conflit et l'insertion se font
sous un meme verrou, donc deux parents qui visent le meme creneau au meme
instant ne peuvent pas passer tous les deux.

En production, l'implementation adossee a Postgres remplace le verrou par la
contrainte ``EXCLUDE USING gist`` (migrations/0001_core.sql) : c'est elle qui
tranche, meme si deux instances de l'API tournent en parallele.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable
from datetime import datetime
from typing import Protocol

from core.errors import CreneauIndisponible
from core.models.agenda import Occupation
from core.models.enums import STATUTS_BLOQUANTS_DEFAUT, StatutRendezVous
from core.scheduling.conflits import detecter_conflit


class Agenda(Protocol):
    """Contrat commun aux implementations memoire et Postgres."""

    def occupations(
        self, ressource_id: str, du: datetime, au: datetime
    ) -> list[Occupation]: ...

    def reserver(self, occupation: Occupation) -> Occupation: ...

    def annuler(self, reference_id: str) -> bool: ...


class AgendaMemoire:
    """Agenda en memoire, utilisable en test et dans le simulateur."""

    def __init__(
        self,
        occupations: Iterable[Occupation] = (),
        statuts_bloquants: frozenset[StatutRendezVous] = STATUTS_BLOQUANTS_DEFAUT,
    ) -> None:
        self._occupations: list[Occupation] = list(occupations)
        self._statuts_bloquants = statuts_bloquants
        self._verrou = threading.Lock()

    def occupations(
        self, ressource_id: str, du: datetime, au: datetime
    ) -> list[Occupation]:
        with self._verrou:
            return [
                o
                for o in self._occupations
                if o.ressource_id == ressource_id and o.chevauche(du, au)
            ]

    def toutes(self, ressource_id: str | None = None) -> list[Occupation]:
        with self._verrou:
            if ressource_id is None:
                return list(self._occupations)
            return [o for o in self._occupations if o.ressource_id == ressource_id]

    def reserver(self, occupation: Occupation) -> Occupation:
        """Verifie puis insere, de facon atomique.

        Leve ``CreneauIndisponible`` si le creneau vient d'etre pris. C'est
        la meme erreur que remonterait la contrainte Postgres : l'appelant
        n'a pas a savoir laquelle des deux a tranche.
        """
        with self._verrou:
            conflit = detecter_conflit(
                occupation.ressource_id,
                occupation.debut,
                occupation.fin,
                self._occupations,
                self._statuts_bloquants,
                ignorer_reference_id=occupation.reference_id,
            )
            if conflit is not None:
                raise CreneauIndisponible(
                    f"creneau deja occupe sur la ressource {occupation.ressource_id}"
                )
            self._occupations = [
                o for o in self._occupations if o.reference_id != occupation.reference_id
            ] + [occupation]
            return occupation

    def annuler(self, reference_id: str) -> bool:
        """Passe le rendez-vous en annule, sans l'effacer.

        On garde la ligne : un rendez-vous annule doit rester visible au
        secretariat et dans le rapport mensuel. Rend ``False`` si la
        reference est inconnue.
        """
        with self._verrou:
            vises = [o for o in self._occupations if o.reference_id == reference_id]
            if not vises:
                return False
            self._occupations = [
                _annulee(o) if o.reference_id == reference_id else o for o in self._occupations
            ]
            return True


def _annulee(occupation: Occupation) -> Occupation:
    return Occupation(
        ressource_id=occupation.ressource_id,
        debut=occupation.debut,
        fin=occupation.fin,
        statut=StatutRendezVous.ANNULE,
        reference_id=occupation.reference_id,
    )
