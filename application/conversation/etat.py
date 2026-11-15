"""Etat d'une conversation entre deux messages.

L'etat ne contient que des identifiants et des horodatages : pas de prenom,
pas de texte du parent. Il est relu a chaque message, et rien de ce qu'il
contient n'ouvre un droit — l'``eleve_id`` memorise est reverifie contre le
perimetre recalcule a chaque requete.
"""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol


class Etape(StrEnum):
    MENU = "menu"
    CHOIX_ENFANT = "choix_enfant"
    CHOIX_MOTIF = "choix_motif"
    CHOIX_CRENEAU = "choix_creneau"
    CONFIRMATION = "confirmation"
    CHOIX_ANNULATION = "choix_annulation"
    CONFIRMATION_ANNULATION = "confirmation_annulation"
    CHOIX_LANGUE = "choix_langue"


@dataclass
class EtatConversation:
    etape: Etape = Etape.MENU
    eleve_id: str | None = None
    motif_id: str | None = None
    #: Options numerotees affichees au dernier message (ids ou instants ISO).
    options: list[str] = field(default_factory=list)
    #: Choix retenu a l'etape precedente (instant ISO ou id de rendez-vous).
    selection: str | None = None
    maj_at: datetime | None = None

    def vers_dict(self) -> dict[str, Any]:
        donnees = asdict(self)
        donnees["etape"] = self.etape.value
        donnees["maj_at"] = self.maj_at.isoformat() if self.maj_at else None
        return donnees

    @classmethod
    def depuis_dict(cls, donnees: dict[str, Any]) -> EtatConversation:
        try:
            etape = Etape(donnees.get("etape", Etape.MENU))
        except ValueError:
            # Etat ecrit par une version anterieure : on repart du menu.
            return cls()
        maj = donnees.get("maj_at")
        return cls(
            etape=etape,
            eleve_id=donnees.get("eleve_id"),
            motif_id=donnees.get("motif_id"),
            options=list(donnees.get("options") or []),
            selection=donnees.get("selection"),
            maj_at=datetime.fromisoformat(maj) if maj else None,
        )


class DepotConversation(Protocol):
    def charger(self, etablissement_id: str, numero: str) -> EtatConversation | None: ...

    def enregistrer(self, etablissement_id: str, numero: str, etat: EtatConversation) -> None: ...


class DepotConversationMemoire:
    def __init__(self) -> None:
        self._etats: dict[tuple[str, str], dict[str, Any]] = {}
        self._verrou = threading.Lock()

    def charger(self, etablissement_id: str, numero: str) -> EtatConversation | None:
        with self._verrou:
            donnees = self._etats.get((etablissement_id, numero))
        return EtatConversation.depuis_dict(donnees) if donnees else None

    def enregistrer(self, etablissement_id: str, numero: str, etat: EtatConversation) -> None:
        with self._verrou:
            self._etats[(etablissement_id, numero)] = etat.vers_dict()
