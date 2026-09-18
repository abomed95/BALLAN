"""Resolution des plages d'ouverture d'une ressource, jour par jour.

Le calendrier repond a une seule question, mais c'est celle dont tout le
reste depend : « le <date>, entre quelles heures cette ressource est-elle
ouverte ? »

L'ordre d'application est fixe et volontairement rigide :

1. la grille hebdomadaire (``Disponibilite``) du jour de la semaine ;
2. filtre des jours ouvres de l'etablissement ;
3. ``HORAIRE_REDUIT`` — on rogne (Ramadan, journees courtes) ;
4. ``OUVERTURE`` — on ajoute (samedi de reunion parents-professeurs) ;
5. ``FERMETURE`` — on retire (vacances, jour ferie, absence d'un enseignant).

La fermeture passe en dernier : une fermeture gagne toujours. C'est le
comportement qu'attend un secretariat, et c'est le seul qui soit sur.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, time
from zoneinfo import ZoneInfo

from core.models.agenda import Disponibilite, ExceptionAgenda
from core.models.enums import Jour, TypeException
from core.models.etablissement import Etablissement
from core.scheduling.intervalles import (
    Intervalle,
    fusionner,
    intersecter_tous,
    soustraire_tous,
)
from core.temps import combiner

_JOURNEE_ENTIERE = (time(0, 0), time(23, 59, 59, 999999))


@dataclass
class Calendrier:
    """Vue combinee de la grille hebdomadaire et des exceptions."""

    etablissement: Etablissement
    disponibilites: list[Disponibilite] = field(default_factory=list)
    exceptions: list[ExceptionAgenda] = field(default_factory=list)

    @property
    def tz(self) -> ZoneInfo:
        return self.etablissement.tz

    # -- exceptions ----------------------------------------------------

    def exceptions_du_jour(
        self, jour: date, ressource_id: str | None = None
    ) -> list[ExceptionAgenda]:
        """Exceptions applicables ce jour-la, etablissement et ressource.

        ``ressource_id`` a ``None`` ne retient que les exceptions
        d'etablissement (vacances, feries).
        """
        retenues = []
        for exc in self.exceptions:
            if exc.etablissement_id != self.etablissement.id:
                continue
            if not exc.couvre_date(jour):
                continue
            if exc.ressource_id is not None and exc.ressource_id != ressource_id:
                continue
            retenues.append(exc)
        return retenues

    def est_ferme(self, jour: date, ressource_id: str | None = None) -> bool:
        """Vrai si une fermeture couvre la journee entiere.

        Sert au calendrier scolaire (vacances) autant qu'aux absences d'un
        enseignant sur plusieurs jours.
        """
        return any(
            exc.type is TypeException.FERMETURE and exc.journee_entiere
            for exc in self.exceptions_du_jour(jour, ressource_id)
        )

    def est_ouvert(self, jour: date, ressource_id: str | None = None) -> bool:
        """Vrai si l'etablissement peut recevoir ce jour-la.

        Un jour non ouvre le devient si une ``OUVERTURE`` exceptionnelle le
        couvre ; un jour ouvre cesse de l'etre si une ``FERMETURE`` pleine
        le couvre.
        """
        exceptions = self.exceptions_du_jour(jour, ressource_id)
        if any(exc.type is TypeException.FERMETURE and exc.journee_entiere for exc in exceptions):
            return False
        if any(exc.type is TypeException.OUVERTURE for exc in exceptions):
            return True
        return self.etablissement.est_jour_ouvre(Jour(jour.weekday()))

    # -- plages --------------------------------------------------------

    def plages(self, ressource_id: str, jour: date) -> list[Intervalle]:
        """Plages d'ouverture effectives de la ressource, ce jour-la."""
        exceptions = self.exceptions_du_jour(jour, ressource_id)
        base = self._grille_hebdomadaire(ressource_id, jour)

        jour_ouvre = self.etablissement.est_jour_ouvre(Jour(jour.weekday()))
        ouvertures = [e for e in exceptions if e.type is TypeException.OUVERTURE]
        if not jour_ouvre and not ouvertures:
            return []
        if not jour_ouvre:
            # Jour normalement non ouvre : seules les ouvertures
            # exceptionnelles comptent, la grille habituelle ne s'applique pas.
            base = []

        for exc in exceptions:
            if exc.type is TypeException.HORAIRE_REDUIT:
                base = intersecter_tous(base, [self._tranche(exc, jour)])

        if ouvertures:
            base = fusionner(base + [self._tranche(exc, jour) for exc in ouvertures])

        fermetures = [e for e in exceptions if e.type is TypeException.FERMETURE]
        if fermetures:
            base = soustraire_tous(base, [self._tranche(exc, jour) for exc in fermetures])

        return fusionner(base)

    # -- interne -------------------------------------------------------

    def _grille_hebdomadaire(self, ressource_id: str, jour: date) -> list[Intervalle]:
        jour_semaine = Jour(jour.weekday())
        pertinentes: Iterable[Disponibilite] = (
            d
            for d in self.disponibilites
            if d.actif
            and d.ressource_id == ressource_id
            and d.etablissement_id == self.etablissement.id
            and d.jour is jour_semaine
        )
        return fusionner(
            Intervalle(
                combiner(jour, d.heure_debut, self.tz),
                combiner(jour, d.heure_fin, self.tz),
            )
            for d in pertinentes
        )

    def _tranche(self, exc: ExceptionAgenda, jour: date) -> Intervalle:
        """Convertit une exception en intervalle concret pour ce jour-la."""
        debut, fin = exc.heure_debut, exc.heure_fin
        if debut is None or fin is None:
            debut, fin = _JOURNEE_ENTIERE
        return Intervalle(combiner(jour, debut, self.tz), combiner(jour, fin, self.tz))
