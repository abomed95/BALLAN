"""Verticale scolaire : ce qui est propre a une ecole.

Le noyau parle de ressources et de contacts. Ici on parle de familles,
d'eleves et de classes — et on pose les regles qui vont avec, a commencer
par le cloisonnement familial.
"""

from verticals.school.calendar_school import CalendrierScolaire, PeriodeNonScolaire
from verticals.school.depot import DepotEcole, DepotEcoleMemoire
from verticals.school.family import Identification, ServiceFamille, StatutIdentification
from verticals.school.rules import (
    PERIMETRE_VIDE,
    Perimetre,
    exiger_acces_eleve,
    message_acces_refuse,
)

__all__ = [
    "PERIMETRE_VIDE",
    "CalendrierScolaire",
    "DepotEcole",
    "DepotEcoleMemoire",
    "Identification",
    "Perimetre",
    "PeriodeNonScolaire",
    "ServiceFamille",
    "StatutIdentification",
    "exiger_acces_eleve",
    "message_acces_refuse",
]
