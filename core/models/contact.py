"""Le contact : un numero de telephone connu de l'etablissement.

Le noyau s'arrete la. Savoir *qui* est derriere ce numero — un patient dans
MAWID, un parent rattache a des eleves dans BALLAN — est l'affaire de la
verticale.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from core.models.enums import Langue
from core.telephone import normaliser
from core.temps import exiger_conscient


@dataclass(frozen=True)
class Contact:
    """Un numero, sa langue, son consentement.

    ``numero`` est stocke sous forme canonique : la normalisation se fait a
    la construction, jamais au moment de la comparaison.
    """

    id: str
    etablissement_id: str
    numero: str
    langue_preferee: Langue | None = None
    #: Horodatage du consentement aux rappels et annonces (§8.3). Sans lui,
    #: aucun envoi sortant non sollicite.
    consenti_at: datetime | None = None
    #: Positionne quand le contact a repondu STOP, dans n'importe quelle
    #: des quatre langues. Coupe tous les rappels.
    stoppe_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "numero", normaliser(self.numero))
        if self.consenti_at is not None:
            exiger_conscient(self.consenti_at, "Contact.consenti_at")
        if self.stoppe_at is not None:
            exiger_conscient(self.stoppe_at, "Contact.stoppe_at")

    @property
    def accepte_envois(self) -> bool:
        return self.consenti_at is not None and self.stoppe_at is None
