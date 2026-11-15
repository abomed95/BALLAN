"""Escalade : la remise d'une conversation a un humain de l'etablissement.

Commun a MAWID et BALLAN. Une escalade porte le numero a rappeler et un code
de motif, rien d'autre : pas de contenu de message, pas d'identite d'eleve.
Le secretariat a le numero, il rappelle ; c'est la que l'humain reprend.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from core.models.enums import Acteur
from core.temps import exiger_conscient


class MotifEscalade(StrEnum):
    #: Numero inconnu ou rattache a aucun eleve : rattachement manuel.
    NUMERO_INCONNU = "numero_inconnu"
    #: Le parent a demande a parler a quelqu'un.
    DEMANDE_PARENT = "demande_parent"
    #: Garde, sante : sujets que l'agent ne traite jamais.
    SUJET_SENSIBLE = "sujet_sensible"
    #: Aucun creneau libre a proposer.
    AUCUN_CRENEAU = "aucun_creneau"
    #: Erreur technique pendant le traitement d'un message.
    INCIDENT = "incident"


@dataclass(frozen=True)
class Escalade:
    id: str
    etablissement_id: str
    numero: str
    motif: MotifEscalade
    cree_at: datetime
    traitee_at: datetime | None = None
    traitee_par: Acteur | None = None

    def __post_init__(self) -> None:
        exiger_conscient(self.cree_at, "Escalade.cree_at")

    @property
    def est_ouverte(self) -> bool:
        return self.traitee_at is None


class DepotEscalade(Protocol):
    def creer(self, escalade: Escalade) -> Escalade: ...

    def ouverte(self, etablissement_id: str, numero: str, motif: MotifEscalade) -> Escalade | None:
        """Escalade encore ouverte pour ce numero et ce motif, s'il y en a une."""
        ...

    def ouvertes(self, etablissement_id: str) -> list[Escalade]: ...

    def traiter(self, escalade_id: str, acteur: Acteur, instant: datetime) -> Escalade | None: ...


class DepotEscaladeMemoire:
    def __init__(self) -> None:
        self._escalades: dict[str, Escalade] = {}
        self._verrou = threading.Lock()

    def creer(self, escalade: Escalade) -> Escalade:
        with self._verrou:
            self._escalades[escalade.id] = escalade
        return escalade

    def ouverte(self, etablissement_id: str, numero: str, motif: MotifEscalade) -> Escalade | None:
        for e in self._escalades.values():
            if (e.etablissement_id, e.numero, e.motif) == (etablissement_id, numero, motif):
                if e.est_ouverte:
                    return e
        return None

    def ouvertes(self, etablissement_id: str) -> list[Escalade]:
        return sorted(
            (e for e in self._escalades.values()
             if e.etablissement_id == etablissement_id and e.est_ouverte),
            key=lambda e: e.cree_at,
        )

    def traiter(self, escalade_id: str, acteur: Acteur, instant: datetime) -> Escalade | None:
        with self._verrou:
            e = self._escalades.get(escalade_id)
            if e is None:
                return None
            self._escalades[escalade_id] = replace(e, traitee_at=instant, traitee_par=acteur)
            return self._escalades[escalade_id]
