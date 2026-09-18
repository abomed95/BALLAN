"""Erreurs du noyau.

Regle : aucune erreur ne transporte de donnee nominative. Les messages
d'exception finissent dans les journaux, et les journaux d'un produit qui
manipule des donnees de mineurs ne doivent pas contenir de prenom, de nom
ni d'identifiant d'eleve (cf. BALLAN.md §8). Les erreurs portent un code ;
c'est la couche i18n qui produit le texte lu par un parent.
"""

from __future__ import annotations


class ErreurBallan(Exception):
    """Racine de toutes les erreurs metier du produit."""

    code = "erreur.interne"


class ErreurConfiguration(ErreurBallan):
    """Configuration d'etablissement incoherente ou incomplete."""

    code = "erreur.configuration"


class CreneauIndisponible(ErreurBallan):
    """Le creneau demande chevauche une occupation bloquante.

    Miroir applicatif de la contrainte d'exclusion Postgres posee sur
    ``rendez_vous`` (cf. migrations/0001_core.sql). La contrainte reste
    l'autorite : cette erreur sert a echouer proprement avant d'y arriver.
    """

    code = "creneau.indisponible"


class HorsOuverture(ErreurBallan):
    """Le creneau demande tombe hors des plages d'ouverture de la ressource."""

    code = "creneau.hors_ouverture"


class AccesRefuse(ErreurBallan):
    """Un contact a demande une donnee qui ne le concerne pas.

    Le message est volontairement constant et non discriminant : il ne doit
    jamais permettre de distinguer « cet eleve n'existe pas » de « cet eleve
    existe mais vous n'y avez pas droit ». C'est le coeur du §8.2.
    """

    code = "acces.refuse"

    def __init__(self, motif_technique: str = "") -> None:
        # motif_technique n'est destine qu'au journal d'audit interne, jamais
        # a un message sortant, et ne doit pas contenir d'identite d'eleve.
        super().__init__("acces refuse")
        self.motif_technique = motif_technique


class ActeurNonAutorise(ErreurBallan):
    """L'acteur (agent, secretariat, direction) n'a pas le droit d'agir ainsi."""

    code = "acteur.non_autorise"


class CleI18nInconnue(ErreurBallan):
    """Cle de traduction absente de toutes les langues, repli compris."""

    code = "i18n.cle_inconnue"
