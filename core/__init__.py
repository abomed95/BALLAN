"""Noyau BALLAN / MAWID.

Ce paquet est commun aux deux produits. Toute difference qui ne tient pas au
metier est un bug : un correctif de creneaux doit profiter aux deux. Rien
d'ici ne connait la notion d'eleve, de famille ou de patient — ces notions
vivent dans ``verticals/``.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
