"""Configuration d'une ecole : ce qui change rarement et sert a chaque requete.

Le moteur de creneaux a besoin de l'etablissement, de la grille hebdomadaire,
des exceptions, de l'annee active et de ses periodes ; l'agent a besoin des
motifs et du libelle des ressources. ``ConfigurationEcole`` les rassemble en
un seul objet immuable, charge par un ``DepotConfiguration`` (memoire ou
PostgreSQL).

Aucune donnee d'eleve ici : la configuration se charge sans perimetre.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from core.errors import ErreurConfiguration
from core.models.agenda import Disponibilite, ExceptionAgenda
from core.models.etablissement import Etablissement, Ressource
from core.scheduling.calendrier import Calendrier
from verticals.school.calendar_school import CalendrierScolaire
from verticals.school.models import AnneeScolaire, MotifRendezVous, Periode


@dataclass(frozen=True)
class ConfigurationEcole:
    etablissement: Etablissement
    annee: AnneeScolaire
    periodes: tuple[Periode, ...] = ()
    disponibilites: tuple[Disponibilite, ...] = ()
    exceptions: tuple[ExceptionAgenda, ...] = ()
    ressources: tuple[Ressource, ...] = ()
    motifs: tuple[MotifRendezVous, ...] = ()

    def __post_init__(self) -> None:
        if self.annee.etablissement_id != self.etablissement.id:
            raise ErreurConfiguration("l'annee scolaire n'appartient pas a l'etablissement")
        ressources = {r.id for r in self.ressources}
        for motif in self.motifs:
            if motif.ressource_id is not None and motif.ressource_id not in ressources:
                raise ErreurConfiguration("un motif designe une ressource inconnue")

    def calendrier_scolaire(self) -> CalendrierScolaire:
        """Calendrier neuf a chaque appel : aucun etat partage entre requetes."""
        calendrier = Calendrier(
            etablissement=self.etablissement,
            disponibilites=list(self.disponibilites),
            exceptions=list(self.exceptions),
        )
        return CalendrierScolaire.depuis_configuration(self.annee, self.periodes, calendrier)

    def ressource(self, ressource_id: str) -> Ressource | None:
        for ressource in self.ressources:
            if ressource.id == ressource_id:
                return ressource
        return None

    def motif(self, motif_id: str) -> MotifRendezVous | None:
        for motif in self.motifs:
            if motif.id == motif_id:
                return motif
        return None

    def motifs_actifs(self) -> tuple[MotifRendezVous, ...]:
        return tuple(
            sorted((m for m in self.motifs if m.actif), key=lambda m: (m.ordre, m.id))
        )


class DepotConfiguration(Protocol):
    def configuration(self, etablissement_id: str) -> ConfigurationEcole: ...


class DepotConfigurationMemoire:
    """Configuration fixe, pour les tests, la demo et le simulateur."""

    def __init__(self, configuration: ConfigurationEcole) -> None:
        self._configuration = configuration

    def configuration(self, etablissement_id: str) -> ConfigurationEcole:
        if etablissement_id != self._configuration.etablissement.id:
            raise ErreurConfiguration("etablissement inconnu")
        return self._configuration
