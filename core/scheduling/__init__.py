"""Moteur de creneaux : calendrier, generation, conflits, agenda.

Commun a MAWID et a BALLAN. Si une verticale a besoin d'un comportement
different, c'est un parametre a ajouter ici, pas une copie a faire la-bas.
"""

from core.scheduling.agenda import Agenda, AgendaMemoire
from core.scheduling.calendrier import Calendrier
from core.scheduling.conflits import (
    chevauchement,
    detecter_conflit,
    garantir_libre,
    occupations_bloquantes,
)
from core.scheduling.creneaux import Creneau, MoteurCreneaux
from core.scheduling.intervalles import (
    Intervalle,
    fusionner,
    intersecter_tous,
    soustraire_tous,
)

__all__ = [
    "Agenda",
    "AgendaMemoire",
    "Calendrier",
    "Creneau",
    "Intervalle",
    "MoteurCreneaux",
    "chevauchement",
    "detecter_conflit",
    "fusionner",
    "garantir_libre",
    "intersecter_tous",
    "occupations_bloquantes",
    "soustraire_tous",
]
