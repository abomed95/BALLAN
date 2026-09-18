"""Detection de conflits entre un creneau candidat et l'existant.

Deux parents ne doivent jamais pouvoir reserver le meme creneau d'un
enseignant. La garantie reelle est la contrainte d'exclusion Postgres posee
sur ``rendez_vous`` ; ce module en est le miroir applicatif, qui permet
d'echouer proprement, de proposer autre chose, et de tester la regle sans
base de donnees.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from core.errors import CreneauIndisponible
from core.models.agenda import Occupation
from core.models.enums import STATUTS_BLOQUANTS_DEFAUT, StatutRendezVous


def chevauchement(debut_a: datetime, fin_a: datetime, debut_b: datetime, fin_b: datetime) -> bool:
    """Intersection de deux intervalles semi-ouverts ``[debut, fin)``.

    Jointif n'est pas chevauchant : 10:00-10:30 et 10:30-11:00 coexistent.
    """
    return debut_a < fin_b and debut_b < fin_a


def occupations_bloquantes(
    occupations: Iterable[Occupation],
    statuts_bloquants: frozenset[StatutRendezVous] = STATUTS_BLOQUANTS_DEFAUT,
) -> list[Occupation]:
    """Ne garde que les occupations dont le statut immobilise le creneau."""
    return [o for o in occupations if o.statut in statuts_bloquants]


def detecter_conflit(
    ressource_id: str,
    debut: datetime,
    fin: datetime,
    occupations: Iterable[Occupation],
    statuts_bloquants: frozenset[StatutRendezVous] = STATUTS_BLOQUANTS_DEFAUT,
    ignorer_reference_id: str | None = None,
) -> Occupation | None:
    """Retourne la premiere occupation en conflit, ou ``None``.

    ``ignorer_reference_id`` permet de deplacer un rendez-vous sans qu'il
    entre en conflit avec lui-meme.
    """
    for occupation in occupations:
        if occupation.ressource_id != ressource_id:
            continue
        if occupation.statut not in statuts_bloquants:
            continue
        if ignorer_reference_id is not None and occupation.reference_id == ignorer_reference_id:
            continue
        if occupation.chevauche(debut, fin):
            return occupation
    return None


def garantir_libre(
    ressource_id: str,
    debut: datetime,
    fin: datetime,
    occupations: Iterable[Occupation],
    statuts_bloquants: frozenset[StatutRendezVous] = STATUTS_BLOQUANTS_DEFAUT,
    ignorer_reference_id: str | None = None,
) -> None:
    """Leve ``CreneauIndisponible`` si le creneau est deja pris."""
    conflit = detecter_conflit(
        ressource_id,
        debut,
        fin,
        occupations,
        statuts_bloquants,
        ignorer_reference_id,
    )
    if conflit is not None:
        raise CreneauIndisponible(
            f"creneau deja occupe sur la ressource {ressource_id} "
            f"({conflit.debut.isoformat()} -> {conflit.fin.isoformat()})"
        )
