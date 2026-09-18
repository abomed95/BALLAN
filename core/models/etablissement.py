"""L'etablissement : la racine de toute configuration.

Tout ce que BALLAN sait d'une ecole vient d'ici ou des tables qui s'y
rattachent. Aucune valeur d'exploitation (horaires, langues, devise, heures
de silence) n'est codee en dur ailleurs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from zoneinfo import ZoneInfo

from core.errors import ErreurConfiguration
from core.models.enums import JOURS_OUVRES_DEFAUT, Jour, Langue
from core.temps import FUSEAU_DEFAUT, fuseau


@dataclass(frozen=True)
class FenetreSilence:
    """Plage nocturne pendant laquelle aucun envoi automatique ne part.

    Par defaut 21:00 -> 07:00, donc une fenetre qui enjambe minuit : la
    comparaison doit en tenir compte (BALLAN.md §6).
    """

    debut: time = time(21, 0)
    fin: time = time(7, 0)

    def couvre(self, heure: time) -> bool:
        if self.debut == self.fin:
            return False
        if self.debut < self.fin:
            return self.debut <= heure < self.fin
        # Fenetre a cheval sur minuit.
        return heure >= self.debut or heure < self.fin


@dataclass(frozen=True)
class Etablissement:
    """Fiche etablissement. Immuable en memoire, modifiee en base."""

    id: str
    nom: str
    fuseau_nom: str = FUSEAU_DEFAUT
    langues_actives: frozenset[Langue] = frozenset({Langue.FR})
    langue_defaut: Langue = Langue.FR
    jours_ouvres: frozenset[Jour] = JOURS_OUVRES_DEFAUT
    silence: FenetreSilence = field(default_factory=FenetreSilence)
    devise: str = "FDJ"
    #: Delai minimal entre l'instant present et le debut d'un creneau
    #: reservable. Evite de proposer un rendez-vous dans dix minutes.
    delai_minimal_min: int = 0

    def __post_init__(self) -> None:
        if not self.langues_actives:
            raise ErreurConfiguration("un etablissement doit avoir au moins une langue active")
        if self.langue_defaut not in self.langues_actives:
            raise ErreurConfiguration("la langue par defaut doit faire partie des langues actives")
        if not self.jours_ouvres:
            raise ErreurConfiguration("un etablissement doit avoir au moins un jour ouvre")
        if self.delai_minimal_min < 0:
            raise ErreurConfiguration("le delai minimal ne peut pas etre negatif")

    @property
    def tz(self) -> ZoneInfo:
        return fuseau(self.fuseau_nom)

    def est_jour_ouvre(self, jour: Jour | int) -> bool:
        return Jour(jour) in self.jours_ouvres

    def langue_ou_defaut(self, langue: Langue | None) -> Langue:
        if langue is not None and langue in self.langues_actives:
            return langue
        return self.langue_defaut


@dataclass(frozen=True)
class Ressource:
    """Ce qui se reserve : un praticien dans MAWID, un enseignant dans BALLAN.

    Le noyau ne connait que cet objet. La specialisation metier (matieres,
    classes) vit dans la verticale.
    """

    id: str
    etablissement_id: str
    libelle: str
    duree_creneau_min: int = 30
    #: Pas de la grille. Egal a la duree par defaut (creneaux jointifs) ;
    #: un pas plus court permet des departs decales.
    pas_min: int | None = None
    langues: frozenset[Langue] = frozenset()
    actif: bool = True

    def __post_init__(self) -> None:
        if self.duree_creneau_min <= 0:
            raise ErreurConfiguration("la duree de creneau doit etre strictement positive")
        if self.pas_min is not None and self.pas_min <= 0:
            raise ErreurConfiguration("le pas de la grille doit etre strictement positif")

    @property
    def pas_effectif(self) -> int:
        return self.pas_min or self.duree_creneau_min
