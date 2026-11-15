"""Calendrier scolaire : annee, periodes, vacances, reprise.

« C'est le coeur de la configuration — tout le reste en depend » (§2). Ce
module est la traduction de cette phrase : il transforme le calendrier
declare par l'ecole en exceptions d'agenda que le moteur de creneaux du
noyau comprend deja.

C'est le point important de conception : les vacances scolaires ne sont pas
une regle de plus dans le moteur de creneaux, ce sont des ``FERMETURE``
d'etablissement. Le noyau n'a rien a apprendre de l'ecole, et MAWID
beneficie des memes corrections.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta

from core.errors import ErreurBallan, ErreurConfiguration
from core.models.agenda import ExceptionAgenda
from core.models.enums import TypeException
from core.scheduling.calendrier import Calendrier
from verticals.school.models import AnneeScolaire, Periode, TypePeriode

#: Garde-fou de ``prochaine_reprise`` : au-dela, la configuration est fausse.
HORIZON_REPRISE_JOURS = 120


class PeriodeNonScolaire(ErreurBallan):
    """La date visee tombe hors annee scolaire, en vacances ou un jour ferme.

    Levee notamment quand on tente de placer une reunion parents-professeurs
    pendant les vacances (§13).
    """

    code = "calendrier.periode_non_scolaire"


@dataclass
class CalendrierScolaire:
    """Vue scolaire posee sur le calendrier du noyau."""

    annee: AnneeScolaire
    calendrier: Calendrier
    periodes: list[Periode] = field(default_factory=list)

    def __post_init__(self) -> None:
        for periode in self.periodes:
            if periode.annee_scolaire_id != self.annee.id:
                raise ErreurConfiguration(
                    "une periode d'une autre annee scolaire a ete fournie"
                )

    # -- periodes ------------------------------------------------------

    def periodes_du_jour(self, jour: date) -> list[Periode]:
        """Toutes les periodes qui couvrent cette date.

        Elles se superposent legitimement : une semaine d'examens tombe
        dans un trimestre.
        """
        return [periode for periode in self.periodes if periode.couvre(jour)]

    def periode_principale(self, jour: date) -> Periode | None:
        """La periode la plus specifique — la plus courte de celles qui couvrent.

        C'est celle qu'on affiche a un parent : « semaine d'examens » est
        plus utile que « deuxieme trimestre ».
        """
        couvrantes = self.periodes_du_jour(jour)
        if not couvrantes:
            return None
        return min(couvrantes, key=lambda p: (p.date_fin - p.date_debut, p.id))

    def est_en_vacances(self, jour: date) -> bool:
        return any(periode.est_vacances for periode in self.periodes_du_jour(jour))

    def est_dans_l_annee(self, jour: date) -> bool:
        return self.annee.couvre(jour)

    # -- jours de classe -----------------------------------------------

    def est_jour_de_classe(self, jour: date) -> bool:
        """Vrai si l'ecole accueille ce jour-la.

        Quatre conditions, dans cet ordre : dans l'annee scolaire, hors
        vacances, jour ouvre, et pas de fermeture exceptionnelle.
        """
        return (
            self.est_dans_l_annee(jour)
            and not self.est_en_vacances(jour)
            and self.calendrier.est_ouvert(jour)
        )

    def exiger_jour_de_classe(self, jour: date) -> None:
        """Garde a poser avant de creer une reunion ou un rendez-vous.

        Le message distingue les cas, parce qu'il est destine au
        secretariat, pas a un parent : « cette date tombe pendant les
        vacances » est exactement ce qu'un humain a besoin de lire.
        """
        if not self.est_dans_l_annee(jour):
            raise PeriodeNonScolaire(f"{jour.isoformat()} est hors de l'annee scolaire")
        if self.est_en_vacances(jour):
            raise PeriodeNonScolaire(f"{jour.isoformat()} tombe pendant les vacances")
        if not self.calendrier.est_ouvert(jour):
            raise PeriodeNonScolaire(f"{jour.isoformat()} n'est pas un jour ouvre")

    def jours_de_classe(self, du: date, au: date) -> list[date]:
        jours = []
        courant = du
        while courant <= au:
            if self.est_jour_de_classe(courant):
                jours.append(courant)
            courant += timedelta(days=1)
        return jours

    def prochaine_reprise(self, depuis: date) -> date | None:
        """Premier jour de classe strictement apres ``depuis``.

        Alimente le rappel « reprise des cours » a J-2 (§6).
        """
        for decalage in range(1, HORIZON_REPRISE_JOURS + 1):
            candidat = depuis + timedelta(days=decalage)
            if candidat > self.annee.date_fin:
                return None
            if self.est_jour_de_classe(candidat):
                return candidat
        return None

    # -- pont vers le noyau --------------------------------------------

    @staticmethod
    def exceptions_depuis_periodes(
        periodes: Iterable[Periode], etablissement_id: str
    ) -> list[ExceptionAgenda]:
        """Traduit les periodes de vacances en fermetures d'etablissement.

        Le moteur de creneaux du noyau cesse alors de proposer des creneaux
        pendant les vacances sans rien savoir du calendrier scolaire.
        """
        return [
            ExceptionAgenda(
                id=f"vacances-{periode.id}",
                etablissement_id=etablissement_id,
                type=TypeException.FERMETURE,
                date_debut=periode.date_debut,
                date_fin=periode.date_fin,
                ressource_id=None,
                motif=periode.type.value,
            )
            for periode in periodes
            if periode.type is TypePeriode.VACANCES
        ]

    @classmethod
    def depuis_configuration(
        cls,
        annee: AnneeScolaire,
        periodes: Iterable[Periode],
        calendrier: Calendrier,
    ) -> CalendrierScolaire:
        """Assemble le calendrier scolaire et injecte les vacances dans le noyau.

        A utiliser plutot que le constructeur : c'est ce qui garantit que
        les vacances sont connues du moteur de creneaux.
        """
        periodes = list(periodes)
        vacances = cls.exceptions_depuis_periodes(periodes, annee.etablissement_id)
        deja_posees = {exc.id for exc in calendrier.exceptions}
        calendrier.exceptions.extend(
            exc for exc in vacances if exc.id not in deja_posees
        )
        return cls(annee=annee, calendrier=calendrier, periodes=periodes)
