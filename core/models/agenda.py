"""Disponibilites, exceptions d'agenda et occupations.

Trois objets suffisent a decrire l'agenda d'une ressource :

* ``Disponibilite`` — la grille hebdomadaire normale ;
* ``ExceptionAgenda`` — ce qui deroge a la grille sur une plage de dates
  (vacances, jour ferie, journee de Ramadan raccourcie, ouverture
  exceptionnelle un samedi de reunion) ;
* ``Occupation`` — ce qui est deja pris.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time

from core.errors import ErreurConfiguration
from core.models.enums import Jour, StatutRendezVous, TypeException
from core.temps import exiger_conscient


@dataclass(frozen=True)
class Disponibilite:
    """Plage hebdomadaire recurrente d'ouverture d'une ressource."""

    id: str
    etablissement_id: str
    ressource_id: str
    jour: Jour
    heure_debut: time
    heure_fin: time
    actif: bool = True

    def __post_init__(self) -> None:
        if self.heure_fin <= self.heure_debut:
            raise ErreurConfiguration(
                "une disponibilite doit se terminer apres son debut "
                f"({self.heure_debut}-{self.heure_fin})"
            )


@dataclass(frozen=True)
class ExceptionAgenda:
    """Derogation a la grille normale, sur une plage de dates inclusive.

    ``ressource_id`` a ``None`` signifie « tout l'etablissement » : c'est
    ainsi que s'expriment les vacances scolaires et les jours feries.

    Selon ``type`` :

    * ``FERMETURE`` — sans heures, la journee entiere est fermee ; avec
      heures, seule cette tranche est retiree ;
    * ``HORAIRE_REDUIT`` — les plages normales sont rognees a la tranche
      indiquee (mecanisme des horaires de Ramadan) ;
    * ``OUVERTURE`` — la tranche indiquee est ouverte meme si le jour n'est
      pas ouvre.
    """

    id: str
    etablissement_id: str
    type: TypeException
    date_debut: date
    date_fin: date
    ressource_id: str | None = None
    heure_debut: time | None = None
    heure_fin: time | None = None
    motif: str = ""

    def __post_init__(self) -> None:
        if self.date_fin < self.date_debut:
            raise ErreurConfiguration("une exception doit se terminer apres son debut")
        bornes_partielles = (self.heure_debut is None) != (self.heure_fin is None)
        if bornes_partielles:
            raise ErreurConfiguration(
                "une exception horaire exige a la fois une heure de debut et une heure de fin"
            )
        if (
            self.heure_debut is not None
            and self.heure_fin is not None
            and self.heure_fin <= self.heure_debut
        ):
            raise ErreurConfiguration("l'heure de fin doit suivre l'heure de debut")
        if self.type in (TypeException.OUVERTURE, TypeException.HORAIRE_REDUIT):
            if self.heure_debut is None:
                raise ErreurConfiguration(
                    f"une exception de type {self.type.value} exige une tranche horaire"
                )

    def couvre_date(self, jour: date) -> bool:
        return self.date_debut <= jour <= self.date_fin

    def vise(self, ressource_id: str) -> bool:
        """Vrai si l'exception s'applique a cette ressource."""
        return self.ressource_id is None or self.ressource_id == ressource_id

    @property
    def journee_entiere(self) -> bool:
        return self.heure_debut is None


@dataclass(frozen=True)
class Occupation:
    """Un intervalle deja pris sur une ressource.

    C'est la projection minimale d'un rendez-vous telle que le moteur de
    creneaux a besoin de la voir. La verticale y ajoute ses colonnes
    (eleve, motif, parent) sans que le noyau ait a les connaitre.
    """

    ressource_id: str
    debut: datetime
    fin: datetime
    statut: StatutRendezVous = StatutRendezVous.CONFIRME
    reference_id: str | None = None

    def __post_init__(self) -> None:
        exiger_conscient(self.debut, "Occupation.debut")
        exiger_conscient(self.fin, "Occupation.fin")
        if self.fin <= self.debut:
            raise ErreurConfiguration("une occupation doit se terminer apres son debut")

    def chevauche(self, debut: datetime, fin: datetime) -> bool:
        """Intersection d'intervalles semi-ouverts [debut, fin).

        Deux creneaux jointifs (10:00-10:30 et 10:30-11:00) ne se chevauchent
        donc pas — c'est la convention de ``tstzrange`` cote Postgres.
        """
        return self.debut < fin and debut < self.fin
