"""Mise en forme des dates et des heures, en clair, dans les quatre langues.

Deux regles du §7, appliquees ici et nulle part ailleurs :

* **chiffres occidentaux** partout, y compris en arabe — un numero de
  creneau doit rester lisible d'une langue a l'autre, et les claviers des
  telephones a Djibouti produisent des chiffres occidentaux ;
* **dates en clair** — « lundi 22 septembre », jamais « 22/09 », qui se lit
  a l'envers d'un pays a l'autre.
"""

from __future__ import annotations

from datetime import date, datetime, time

from core.i18n.catalogue import Catalogue, catalogue
from core.models.enums import Langue


def _cat(instance: Catalogue | None) -> Catalogue:
    return instance or catalogue()


def nom_jour(jour: date, langue: Langue, cat: Catalogue | None = None) -> str:
    """Nom du jour de la semaine. Index aligne sur ``date.weekday()``."""
    return _cat(cat).liste("date.jours", langue)[jour.weekday()]


def nom_mois(jour: date, langue: Langue, cat: Catalogue | None = None) -> str:
    return _cat(cat).liste("date.mois", langue)[jour.month - 1]


def formater_heure(heure: time | datetime, langue: Langue, cat: Catalogue | None = None) -> str:
    """``10:00`` — chiffres occidentaux, minutes toujours sur deux positions."""
    return _cat(cat).t(
        "date.format_heure",
        langue,
        heures=f"{heure.hour:02d}",
        minutes=f"{heure.minute:02d}",
    )


def formater_date(
    jour: date, langue: Langue, cat: Catalogue | None = None, avec_jour_semaine: bool = True
) -> str:
    """``lundi 22 septembre`` ou ``22 septembre``."""
    instance = _cat(cat)
    cle = "date.format_date" if avec_jour_semaine else "date.format_date_courte"
    return instance.t(
        cle,
        langue,
        jour=nom_jour(jour, langue, instance),
        numero=str(jour.day),
        mois=nom_mois(jour, langue, instance),
    )


def formater_datetime(
    instant: datetime, langue: Langue, cat: Catalogue | None = None
) -> str:
    """``lundi 22 septembre à 10:00``.

    L'instant est formate tel quel : c'est a l'appelant de l'avoir converti
    dans le fuseau de l'etablissement.
    """
    instance = _cat(cat)
    return instance.t(
        "date.format_datetime",
        langue,
        date=formater_date(instant.date(), langue, instance),
        heure=formater_heure(instant, langue, instance),
    )


def formater_plage_horaire(
    debut: datetime, fin: datetime, langue: Langue, cat: Catalogue | None = None
) -> str:
    """``10:00 – 10:30``."""
    instance = _cat(cat)
    return instance.t(
        "date.format_plage_horaire",
        langue,
        debut=formater_heure(debut, langue, instance),
        fin=formater_heure(fin, langue, instance),
    )
