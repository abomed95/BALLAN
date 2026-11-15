"""Objets de domaine du noyau, en Python pur.

Aucun ORM ici volontairement : le moteur de creneaux et les regles d'acces
se testent sans base de donnees, et la persistance (SQLAlchemy / Supabase)
n'est qu'un adaptateur au-dessus de ces objets.
"""

from core.models.agenda import Disponibilite, ExceptionAgenda, Occupation
from core.models.contact import Contact
from core.models.enums import (
    JOURS_OUVRES_DEFAUT,
    LANGUE_REPLI,
    STATUTS_BLOQUANTS_DEFAUT,
    Acteur,
    Jour,
    Langue,
    StatutRendezVous,
    TypeException,
)
from core.models.etablissement import Etablissement, FenetreSilence, Ressource

__all__ = [
    "JOURS_OUVRES_DEFAUT",
    "LANGUE_REPLI",
    "STATUTS_BLOQUANTS_DEFAUT",
    "Acteur",
    "Contact",
    "Disponibilite",
    "Etablissement",
    "ExceptionAgenda",
    "FenetreSilence",
    "Jour",
    "Langue",
    "Occupation",
    "Ressource",
    "StatutRendezVous",
    "TypeException",
]
