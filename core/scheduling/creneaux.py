"""Moteur de creneaux.

Genere les creneaux reservables d'une ressource : on decoupe les plages
d'ouverture rendues par le ``Calendrier``, on retire ce qui est deja pris,
on retire le passe et le delai minimal, et on rend une liste ordonnee.

Le moteur ne decide rien : il n'ecrit pas, ne reserve pas, ne connait ni
parent ni eleve. Il repond a « qu'est-ce qui est libre ».
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from core.errors import ErreurConfiguration, HorsOuverture
from core.models.agenda import Occupation
from core.models.enums import STATUTS_BLOQUANTS_DEFAUT, StatutRendezVous
from core.scheduling.calendrier import Calendrier
from core.scheduling.conflits import detecter_conflit, garantir_libre
from core.scheduling.intervalles import Intervalle
from core.temps import DUREE_CRENEAU_MIN_PLANCHER, exiger_conscient, jours_entre

#: Garde-fou : nombre maximal de jours explores par ``creneaux_periode``.
HORIZON_MAX_JOURS = 180


@dataclass(frozen=True, order=True)
class Creneau:
    """Un creneau libre, propose a un parent."""

    debut: datetime
    fin: datetime
    ressource_id: str = field(compare=False, default="")

    @property
    def duree_min(self) -> float:
        return (self.fin - self.debut).total_seconds() / 60

    @property
    def intervalle(self) -> Intervalle:
        return Intervalle(self.debut, self.fin)


@dataclass
class MoteurCreneaux:
    """Decoupe les plages d'ouverture en creneaux reservables."""

    calendrier: Calendrier
    statuts_bloquants: frozenset[StatutRendezVous] = STATUTS_BLOQUANTS_DEFAUT

    # -- generation ----------------------------------------------------

    def creneaux_du_jour(
        self,
        ressource_id: str,
        jour: date,
        duree_min: int,
        occupations: Iterable[Occupation] = (),
        maintenant: datetime | None = None,
        pas_min: int | None = None,
        delai_minimal_min: int | None = None,
    ) -> list[Creneau]:
        """Creneaux libres de la ressource, pour une date donnee."""
        if duree_min < DUREE_CRENEAU_MIN_PLANCHER:
            raise ErreurConfiguration(
                f"duree de creneau trop courte (< {DUREE_CRENEAU_MIN_PLANCHER} min)"
            )
        pas = pas_min or duree_min
        if pas <= 0:
            raise ErreurConfiguration("le pas de la grille doit etre strictement positif")

        occupations = list(occupations)
        plancher = self._plancher(maintenant, delai_minimal_min)

        creneaux: list[Creneau] = []
        for plage in self.calendrier.plages(ressource_id, jour):
            creneaux.extend(self._decouper(ressource_id, plage, duree_min, pas))

        libres = [
            c
            for c in creneaux
            if (plancher is None or c.debut >= plancher)
            and detecter_conflit(
                ressource_id, c.debut, c.fin, occupations, self.statuts_bloquants
            )
            is None
        ]
        return sorted(libres)

    def creneaux_periode(
        self,
        ressource_id: str,
        du: date,
        au: date,
        duree_min: int,
        occupations: Iterable[Occupation] = (),
        maintenant: datetime | None = None,
        pas_min: int | None = None,
        delai_minimal_min: int | None = None,
        limite: int | None = None,
    ) -> list[Creneau]:
        """Creneaux libres sur une plage de dates, bornes incluses.

        ``limite`` arrete la recherche des que le compte est atteint : on ne
        propose jamais plus de trois creneaux a un parent, inutile de
        calculer un trimestre entier.
        """
        if (au - du).days > HORIZON_MAX_JOURS:
            raise ErreurConfiguration(
                f"horizon de recherche trop large (> {HORIZON_MAX_JOURS} jours)"
            )
        occupations = list(occupations)
        resultat: list[Creneau] = []
        for jour in jours_entre(du, au):
            resultat.extend(
                self.creneaux_du_jour(
                    ressource_id,
                    jour,
                    duree_min,
                    occupations,
                    maintenant=maintenant,
                    pas_min=pas_min,
                    delai_minimal_min=delai_minimal_min,
                )
            )
            if limite is not None and len(resultat) >= limite:
                return resultat[:limite]
        return resultat

    def prochains_creneaux(
        self,
        ressource_id: str,
        duree_min: int,
        maintenant: datetime,
        occupations: Iterable[Occupation] = (),
        nombre: int = 3,
        horizon_jours: int = 30,
        pas_min: int | None = None,
        delai_minimal_min: int | None = None,
    ) -> list[Creneau]:
        """Les ``nombre`` prochains creneaux libres — la forme utile en
        conversation : « trois creneaux sont libres ... »."""
        exiger_conscient(maintenant, "maintenant")
        debut = maintenant.astimezone(self.calendrier.tz).date()
        return self.creneaux_periode(
            ressource_id,
            debut,
            debut + timedelta(days=horizon_jours),
            duree_min,
            occupations,
            maintenant=maintenant,
            pas_min=pas_min,
            delai_minimal_min=delai_minimal_min,
            limite=nombre,
        )

    # -- verification --------------------------------------------------

    def est_ouvert_sur(self, ressource_id: str, debut: datetime, fin: datetime) -> bool:
        """Vrai si ``[debut, fin)`` tient entierement dans une plage d'ouverture."""
        exiger_conscient(debut, "debut")
        exiger_conscient(fin, "fin")
        candidat = Intervalle(debut, fin)
        jour_local = debut.astimezone(self.calendrier.tz).date()
        # Un creneau peut theoriquement enjamber minuit : on regarde aussi
        # le lendemain avant de conclure.
        for jour in (jour_local, jour_local + timedelta(days=1)):
            for plage in self.calendrier.plages(ressource_id, jour):
                if plage.contient(candidat):
                    return True
        return False

    def verifier_reservable(
        self,
        ressource_id: str,
        debut: datetime,
        fin: datetime,
        occupations: Iterable[Occupation] = (),
        ignorer_reference_id: str | None = None,
    ) -> None:
        """Leve si le creneau est hors ouverture ou deja pris.

        Appele avant toute ecriture. La contrainte Postgres reste le dernier
        rempart en cas de course entre deux reservations simultanees.
        """
        if not self.est_ouvert_sur(ressource_id, debut, fin):
            raise HorsOuverture(
                f"creneau hors des plages d'ouverture de la ressource {ressource_id}"
            )
        garantir_libre(
            ressource_id,
            debut,
            fin,
            occupations,
            self.statuts_bloquants,
            ignorer_reference_id,
        )

    # -- interne -------------------------------------------------------

    def _plancher(
        self, maintenant: datetime | None, delai_minimal_min: int | None
    ) -> datetime | None:
        if maintenant is None:
            return None
        exiger_conscient(maintenant, "maintenant")
        delai = (
            delai_minimal_min
            if delai_minimal_min is not None
            else self.calendrier.etablissement.delai_minimal_min
        )
        return maintenant + timedelta(minutes=delai)

    @staticmethod
    def _decouper(
        ressource_id: str, plage: Intervalle, duree_min: int, pas_min: int
    ) -> Sequence[Creneau]:
        creneaux: list[Creneau] = []
        duree = timedelta(minutes=duree_min)
        pas = timedelta(minutes=pas_min)
        curseur = plage.debut
        while curseur + duree <= plage.fin:
            creneaux.append(Creneau(curseur, curseur + duree, ressource_id))
            curseur += pas
        return creneaux
