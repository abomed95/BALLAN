"""Acces aux donnees scolaires.

``DepotEcole`` est volontairement bas niveau et **sans aucun controle
d'acces** : il sait lire une ligne, pas decider qui a le droit de la lire.
Tout le cloisonnement familial est au-dessus, dans ``family.py``.

Cette separation est un choix de securite : il n'existe qu'un seul chemin
vers une donnee d'eleve, et ce chemin exige un ``Perimetre``. Un depot qui
saurait aussi filtrer inviterait a l'oublier une fois sur deux.

Personne n'appelle un depot directement depuis l'agent ou l'API.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from datetime import datetime
from typing import Protocol

from core.models.contact import Contact
from core.models.enums import Langue
from core.telephone import normaliser
from verticals.school.models import (
    AnneeScolaire,
    Classe,
    Eleve,
    Enseignant,
    Famille,
    LienParentEleve,
    Niveau,
    Parent,
    Periode,
)


class DepotEcole(Protocol):
    """Contrat commun aux implementations memoire et PostgreSQL."""

    def contact_par_numero(self, etablissement_id: str, numero: str) -> Contact | None: ...

    def contact(self, contact_id: str) -> Contact | None: ...

    def parents_du_contact(self, etablissement_id: str, contact_id: str) -> list[Parent]: ...

    def parent(self, parent_id: str) -> Parent | None: ...

    def liens_du_parent(self, parent_id: str) -> list[LienParentEleve]: ...

    def liens_de_l_eleve(self, eleve_id: str) -> list[LienParentEleve]: ...

    def eleve(self, eleve_id: str) -> Eleve | None: ...

    def classe(self, classe_id: str) -> Classe | None: ...

    def niveau(self, niveau_id: str) -> Niveau | None: ...

    def enseignant(self, enseignant_id: str) -> Enseignant | None: ...

    def famille(self, famille_id: str) -> Famille | None: ...

    # -- preferences du contact sur son propre numero ------------------
    #
    # Ce sont les seules ecritures ouvertes a l'agent : elles ne touchent
    # que le numero qui ecrit, jamais un lien familial (§8.2, §8.3).

    def marquer_stop(self, contact_id: str, instant: datetime) -> None: ...

    def marquer_consentement(self, contact_id: str, instant: datetime) -> None: ...

    def definir_langue_contact(self, contact_id: str, langue: Langue) -> None: ...


class DepotEcoleMemoire:
    """Depot en memoire : tests, simulateur en ligne de commande, demo."""

    def __init__(
        self,
        contacts: Iterable[Contact] = (),
        familles: Iterable[Famille] = (),
        parents: Iterable[Parent] = (),
        liens: Iterable[LienParentEleve] = (),
        eleves: Iterable[Eleve] = (),
        classes: Iterable[Classe] = (),
        niveaux: Iterable[Niveau] = (),
        enseignants: Iterable[Enseignant] = (),
        annees: Iterable[AnneeScolaire] = (),
        periodes: Iterable[Periode] = (),
    ) -> None:
        self.contacts = {c.id: c for c in contacts}
        self.familles = {f.id: f for f in familles}
        self.parents = {p.id: p for p in parents}
        self.liens = list(liens)
        self.eleves = {e.id: e for e in eleves}
        self.classes = {c.id: c for c in classes}
        self.niveaux = {n.id: n for n in niveaux}
        self.enseignants = {e.id: e for e in enseignants}
        self.annees = {a.id: a for a in annees}
        self.periodes = list(periodes)

    # -- contacts et parents -------------------------------------------

    def contact_par_numero(self, etablissement_id: str, numero: str) -> Contact | None:
        canonique = normaliser(numero)
        for contact in self.contacts.values():
            if contact.etablissement_id == etablissement_id and contact.numero == canonique:
                return contact
        return None

    def contact(self, contact_id: str) -> Contact | None:
        return self.contacts.get(contact_id)

    def parents_du_contact(self, etablissement_id: str, contact_id: str) -> list[Parent]:
        parents = []
        for parent in self.parents.values():
            if parent.contact_id != contact_id:
                continue
            famille = self.familles.get(parent.famille_id)
            # Un parent d'une autre ecole ne doit rien ouvrir ici, meme si
            # le meme numero y est connu.
            if famille is None or famille.etablissement_id != etablissement_id:
                continue
            parents.append(parent)
        return parents

    def parent(self, parent_id: str) -> Parent | None:
        return self.parents.get(parent_id)

    # -- liens familiaux -----------------------------------------------

    def liens_du_parent(self, parent_id: str) -> list[LienParentEleve]:
        return [lien for lien in self.liens if lien.parent_id == parent_id]

    def liens_de_l_eleve(self, eleve_id: str) -> list[LienParentEleve]:
        return [lien for lien in self.liens if lien.eleve_id == eleve_id]

    # -- structure -----------------------------------------------------

    def eleve(self, eleve_id: str) -> Eleve | None:
        return self.eleves.get(eleve_id)

    def classe(self, classe_id: str) -> Classe | None:
        return self.classes.get(classe_id)

    def niveau(self, niveau_id: str) -> Niveau | None:
        return self.niveaux.get(niveau_id)

    def enseignant(self, enseignant_id: str) -> Enseignant | None:
        return self.enseignants.get(enseignant_id)

    def famille(self, famille_id: str) -> Famille | None:
        return self.familles.get(famille_id)

    # -- preferences du contact ----------------------------------------

    def marquer_stop(self, contact_id: str, instant: datetime) -> None:
        contact = self.contacts.get(contact_id)
        if contact is not None:
            self.contacts[contact_id] = replace(contact, stoppe_at=instant)

    def marquer_consentement(self, contact_id: str, instant: datetime) -> None:
        contact = self.contacts.get(contact_id)
        if contact is not None:
            self.contacts[contact_id] = replace(contact, consenti_at=instant, stoppe_at=None)

    def definir_langue_contact(self, contact_id: str, langue: Langue) -> None:
        contact = self.contacts.get(contact_id)
        if contact is not None:
            self.contacts[contact_id] = replace(contact, langue_preferee=langue)

    # -- ecriture, reservee au secretariat -----------------------------
    #
    # Ces methodes ne sont jamais appelees par l'agent : ``ServiceFamille``
    # exige un acteur habilite avant de les atteindre.

    def enregistrer_contact(self, contact: Contact) -> Contact:
        self.contacts[contact.id] = contact
        return contact

    def enregistrer_parent(self, parent: Parent) -> Parent:
        self.parents[parent.id] = parent
        return parent

    def enregistrer_lien(self, lien: LienParentEleve) -> LienParentEleve:
        self.liens = [
            existant
            for existant in self.liens
            if not (
                existant.parent_id == lien.parent_id and existant.eleve_id == lien.eleve_id
            )
        ]
        self.liens.append(lien)
        return lien
