"""Ce que voit et fait le secretariat : agenda nominatif, annulations, escalades.

Le secretariat est l'ecole : il voit les noms des eleves, sans perimetre
familial. Chaque operation est donc faite au nom d'un ``Acteur`` humain,
verifie par le domaine, et l'acces a ce service est authentifie par l'API.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from core.errors import AccesRefuse
from core.escalade import DepotEscalade, Escalade
from core.i18n.libelles import resoudre_libelle
from core.models.enums import Acteur, Langue
from verticals.school.depot import DepotEcole
from verticals.school.rendez_vous import ServiceRendezVous


@dataclass(frozen=True)
class LigneAgenda:
    id: str
    debut: datetime
    fin: datetime
    statut: str
    eleve: str
    classe: str
    avec: str
    motif: str
    rappel_envoye: bool


class ServiceSecretariat:
    def __init__(
        self,
        rendez_vous: ServiceRendezVous,
        depot_ecole: DepotEcole,
        escalades: DepotEscalade,
        horloge: Callable[[], datetime],
        acteur: Acteur = Acteur.SECRETARIAT,
    ) -> None:
        self._rdv = rendez_vous
        self._depot = depot_ecole
        self._escalades = escalades
        self._horloge = horloge
        self._acteur = acteur

    def agenda(self, du: date, au: date) -> list[LigneAgenda]:
        conf = self._rdv.configuration()
        tz = conf.etablissement.tz
        debut = datetime.combine(du, time(0, 0), tzinfo=tz)
        fin = datetime.combine(au + timedelta(days=1), time(0, 0), tzinfo=tz)
        lignes = []
        for rdv in self._rdv.sur_periode(self._acteur, debut, fin):
            eleve = self._depot.eleve(rdv.eleve_id)
            classe = self._depot.classe(eleve.classe_id) if eleve else None
            ressource = conf.ressource(rdv.ressource_id)
            motif = conf.motif(rdv.motif_id) if rdv.motif_id else None
            lignes.append(LigneAgenda(
                id=rdv.id,
                debut=rdv.debut.astimezone(tz),
                fin=rdv.fin.astimezone(tz),
                statut=rdv.statut.value,
                eleve=f"{eleve.prenom} {eleve.nom}" if eleve else "?",
                classe=classe.libelle if classe else "",
                avec=ressource.libelle if ressource else "",
                motif=resoudre_libelle(motif.libelle_i18n, Langue.FR) if motif else "",
                rappel_envoye=rdv.rappel_envoye_at is not None,
            ))
        return lignes

    def annuler(self, rdv_id: str) -> None:
        self._rdv.annuler_par_l_ecole(self._acteur, rdv_id)

    def escalades(self) -> list[Escalade]:
        conf = self._rdv.configuration()
        return self._escalades.ouvertes(conf.etablissement.id)

    def traiter_escalade(self, escalade_id: str) -> Escalade:
        traitee = self._escalades.traiter(escalade_id, self._acteur, self._horloge())
        if traitee is None:
            raise AccesRefuse("escalade inconnue")
        return traitee
