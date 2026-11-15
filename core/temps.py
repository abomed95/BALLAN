"""Temps et fuseau horaire.

Une seule regle, appliquee partout : les ``datetime`` qui circulent dans le
noyau sont **toujours** conscients du fuseau (aware). Un naive datetime est
une erreur de programmation, pas une valeur par defaut a rattraper.

Le fuseau de reference du produit est ``Africa/Djibouti`` (UTC+3, sans heure
d'ete), mais il reste une donnee d'etablissement : rien n'est code en dur.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from core.errors import ErreurConfiguration

FUSEAU_DEFAUT = "Africa/Djibouti"

#: Duree minimale d'un creneau exploitable, en minutes.
DUREE_CRENEAU_MIN_PLANCHER = 5


def fuseau(nom: str = FUSEAU_DEFAUT) -> ZoneInfo:
    """Retourne le fuseau nomme, avec une erreur metier lisible s'il est faux."""
    try:
        return ZoneInfo(nom)
    except Exception as exc:  # noqa: BLE001 - on retraduit en erreur metier
        raise ErreurConfiguration(f"fuseau horaire inconnu : {nom!r}") from exc


def maintenant(tz: ZoneInfo) -> datetime:
    """Instant present dans le fuseau donne."""
    return datetime.now(tz)


def combiner(jour: date, heure: time, tz: ZoneInfo) -> datetime:
    """Compose une date locale et une heure locale en datetime conscient."""
    return datetime.combine(jour, heure, tzinfo=tz)


def exiger_conscient(valeur: datetime, nom: str = "datetime") -> datetime:
    """Refuse un datetime naif. Utilise aux frontieres du noyau."""
    if valeur.tzinfo is None or valeur.utcoffset() is None:
        raise ErreurConfiguration(f"{nom} doit etre conscient du fuseau horaire")
    return valeur


def jours_entre(du: date, au: date):
    """Itere les dates de ``du`` a ``au``, bornes incluses."""
    if au < du:
        return
    courant = du
    while courant <= au:
        yield courant
        courant += timedelta(days=1)
