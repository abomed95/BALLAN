"""Fixtures communes aux tests du noyau.

Tout est en memoire : le noyau domaine n'a besoin ni de base de donnees ni
de reseau, et les tests doivent rester executables sur le poste d'un
developpeur a Djibouti avec une connexion mediocre.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, time

import pytest

from core.models import (
    Disponibilite,
    Etablissement,
    ExceptionAgenda,
    Jour,
    Langue,
    Ressource,
    TypeException,
)
from core.scheduling import Calendrier, MoteurCreneaux
from core.temps import fuseau

#: 2025-09-22 est un lundi — c'est la semaine de l'exemple de BALLAN.md §5.1.
LUNDI = date(2025, 9, 22)
DIMANCHE = date(2025, 9, 21)
MARDI = date(2025, 9, 23)
VENDREDI = date(2025, 9, 26)  # jour non ouvre par defaut
SAMEDI = date(2025, 9, 27)  # jour non ouvre par defaut

TZ = fuseau("Africa/Djibouti")


@pytest.fixture
def tz():
    return TZ


@pytest.fixture
def ecole() -> Etablissement:
    """Ecole type : dimanche -> jeudi, quatre langues, Djibouti."""
    return Etablissement(
        id="etab-1",
        nom="Ecole Al-Nour",
        langues_actives=frozenset(Langue),
        langue_defaut=Langue.FR,
    )


@pytest.fixture
def enseignante() -> Ressource:
    return Ressource(
        id="ens-1",
        etablissement_id="etab-1",
        libelle="Mme B.",
        duree_creneau_min=30,
        langues=frozenset({Langue.FR, Langue.AR}),
    )


def dispo(
    ressource_id: str,
    jour: Jour,
    debut: time,
    fin: time,
    etablissement_id: str = "etab-1",
    identifiant: str | None = None,
) -> Disponibilite:
    return Disponibilite(
        id=identifiant or f"dispo-{ressource_id}-{jour.value}-{debut.hour}",
        etablissement_id=etablissement_id,
        ressource_id=ressource_id,
        jour=jour,
        heure_debut=debut,
        heure_fin=fin,
    )


def exception_agenda(
    type_: TypeException,
    du: date,
    au: date | None = None,
    debut: time | None = None,
    fin: time | None = None,
    ressource_id: str | None = None,
    etablissement_id: str = "etab-1",
    motif: str = "",
) -> ExceptionAgenda:
    return ExceptionAgenda(
        id=f"exc-{type_.value}-{du.isoformat()}-{ressource_id or 'etab'}",
        etablissement_id=etablissement_id,
        type=type_,
        date_debut=du,
        date_fin=au or du,
        ressource_id=ressource_id,
        heure_debut=debut,
        heure_fin=fin,
        motif=motif,
    )


def calendrier(
    ecole: Etablissement,
    disponibilites: Iterable[Disponibilite] = (),
    exceptions: Iterable[ExceptionAgenda] = (),
) -> Calendrier:
    return Calendrier(
        etablissement=ecole,
        disponibilites=list(disponibilites),
        exceptions=list(exceptions),
    )


def moteur(
    ecole: Etablissement,
    disponibilites: Iterable[Disponibilite] = (),
    exceptions: Iterable[ExceptionAgenda] = (),
) -> MoteurCreneaux:
    return MoteurCreneaux(calendrier=calendrier(ecole, disponibilites, exceptions))


def instant(jour: date, heure: time) -> datetime:
    return datetime.combine(jour, heure, tzinfo=TZ)


@pytest.fixture
def semaine_type(ecole, enseignante) -> MoteurCreneaux:
    """Une enseignante ouverte 08:00-12:00 du dimanche au jeudi."""
    disponibilites = [
        dispo(enseignante.id, jour, time(8, 0), time(12, 0))
        for jour in (Jour.DIMANCHE, Jour.LUNDI, Jour.MARDI, Jour.MERCREDI, Jour.JEUDI)
    ]
    return moteur(ecole, disponibilites)
