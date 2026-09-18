"""Regles non negociables de la verticale scolaire.

Ce module ne contient que des gardes : des fonctions qui laissent passer ou
qui levent. Elles sont appelees par ``family.py`` avant toute lecture et
avant toute ecriture, et jamais contournees.

Deux familles de regles y vivront :

* le **cloisonnement familial** (§8.2) — ci-dessous, lot 1 ;
* les **interdits pedagogiques** (§3, §8.1) — lot 3, avec
  ``tests/test_interdits_pedagogiques.py``.

Le point commun : ce sont des regles qu'aucun prompt ne doit avoir a
rappeler au modele, parce qu'elles sont appliquees dans le code.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from core.errors import AccesRefuse, ActeurNonAutorise
from core.i18n.catalogue import Catalogue, catalogue
from core.models.enums import Acteur, Langue

#: Actions qu'un agent ne fait jamais, quoi qu'on lui demande et quelle que
#: soit la formulation. Elles touchent a l'identite d'une famille ou a des
#: situations de garde : seul un humain de l'ecole les traite (§8.2).
ACTIONS_RESERVEES_SECRETARIAT = frozenset(
    {
        "rattacher_contact",
        "changer_numero",
        "modifier_lien_parent_eleve",
        "lire_autorisation_de_recuperer",
    }
)


@dataclass(frozen=True)
class Perimetre:
    """Ce qu'un contact a le droit de voir, calcule cote serveur.

    Un perimetre n'est jamais deduit du seul numero de telephone : il est
    reconstruit a partir de ``lien_parent_eleve`` a chaque requete. Un
    numero inconnu produit ``PERIMETRE_VIDE``, qui n'ouvre rien.
    """

    etablissement_id: str
    contact_id: str | None = None
    parent_ids: frozenset[str] = frozenset()
    eleve_ids: frozenset[str] = frozenset()

    @property
    def est_rattache(self) -> bool:
        return bool(self.eleve_ids)

    def couvre(self, eleve_id: str) -> bool:
        return eleve_id in self.eleve_ids

    def couvre_parent(self, parent_id: str) -> bool:
        return parent_id in self.parent_ids


#: Perimetre d'un numero inconnu. N'ouvre rien, pas meme une confirmation.
PERIMETRE_VIDE = Perimetre(etablissement_id="")


def exiger_acces_eleve(perimetre: Perimetre, eleve_id: str) -> None:
    """Garde posee avant toute lecture concernant un eleve.

    Leve toujours la meme erreur, que l'eleve n'existe pas ou qu'il
    appartienne a une autre famille. C'est essentiel : une erreur qui
    distinguerait les deux cas permettrait a un inconnu de verifier qu'un
    enfant est inscrit, ce que le §8.2 interdit explicitement.
    """
    if not perimetre.couvre(eleve_id):
        raise AccesRefuse("eleve hors perimetre du contact")


def exiger_acteur(acteur: Acteur, autorises: Iterable[Acteur], action: str) -> None:
    """Refuse une action a un acteur qui n'y a pas droit.

    Sert notamment a interdire a l'agent ce que seul le secretariat fait :
    rattacher un contact, changer un numero, toucher a un lien familial.
    """
    if acteur not in set(autorises):
        raise ActeurNonAutorise(f"action reservee : {action}")


def exiger_secretariat(acteur: Acteur, action: str) -> None:
    if action not in ACTIONS_RESERVEES_SECRETARIAT:
        raise ActeurNonAutorise(f"action inconnue du catalogue reserve : {action}")
    exiger_acteur(acteur, (Acteur.SECRETARIAT, Acteur.DIRECTION), action)


def message_acces_refuse(langue: Langue, cat: Catalogue | None = None) -> str:
    """Le seul message qu'un contact non autorise recoit.

    Volontairement identique dans tous les cas de refus : il ne dit ni ce
    qui a ete demande, ni si cela existe. Il annonce une reprise humaine,
    parce qu'un refus sec laisse un parent legitime sans solution.
    """
    return (cat or catalogue()).t("acces.refuse", langue)
