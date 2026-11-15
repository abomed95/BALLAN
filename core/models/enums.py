"""Enumerations partagees par le noyau."""

from __future__ import annotations

from enum import IntEnum, StrEnum


class Langue(StrEnum):
    """Les quatre langues du produit."""

    FR = "fr"
    AR = "ar"
    SO = "so"
    AA = "aa"


#: Langue de repli quand une chaine manque dans la langue demandee.
LANGUE_REPLI = Langue.FR


class Jour(IntEnum):
    """Jour de la semaine, aligne sur ``datetime.date.weekday()``.

    Aligner sur la convention Python evite la classe de bugs la plus banale
    du domaine : un decalage d'un jour entre la configuration et le moteur.
    """

    LUNDI = 0
    MARDI = 1
    MERCREDI = 2
    JEUDI = 3
    VENDREDI = 4
    SAMEDI = 5
    DIMANCHE = 6


#: Semaine ouvree par defaut a Djibouti : dimanche -> jeudi.
#: A confirmer etablissement par etablissement (BALLAN.md §2).
JOURS_OUVRES_DEFAUT = frozenset(
    {Jour.DIMANCHE, Jour.LUNDI, Jour.MARDI, Jour.MERCREDI, Jour.JEUDI}
)


class TypeException(StrEnum):
    """Nature d'une exception d'agenda posee sur une plage de dates."""

    #: Ferme (journee entiere, ou seulement la tranche horaire indiquee).
    FERMETURE = "fermeture"
    #: Ouverture exceptionnelle un jour normalement non ouvre.
    OUVERTURE = "ouverture"
    #: Journee raccourcie : les plages normales sont rognees a la tranche
    #: indiquee. C'est le mecanisme des horaires de Ramadan.
    HORAIRE_REDUIT = "horaire_reduit"


class StatutRendezVous(StrEnum):
    PROPOSE = "propose"
    CONFIRME = "confirme"
    ANNULE = "annule"
    HONORE = "honore"
    ABSENT = "absent"


#: Statuts qui immobilisent un creneau. La contrainte d'exclusion Postgres
#: porte sur le meme ensemble — les deux doivent rester synchronises.
STATUTS_BLOQUANTS_DEFAUT = frozenset({StatutRendezVous.CONFIRME})


class Acteur(StrEnum):
    """Qui declenche une action. Certaines sont interdites a l'agent.

    Exemple : changer le numero rattache a une famille est reserve au
    secretariat (BALLAN.md §8.2), et cette regle est verifiee dans le code,
    pas seulement ecrite dans le prompt.
    """

    AGENT = "agent"
    SECRETARIAT = "secretariat"
    DIRECTION = "direction"
