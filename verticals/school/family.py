"""Resolution parent -> eleves, et controle d'acces familial.

C'est le module le plus sensible du produit. Le §14 le dit sans detour :
laisser sortir une information sur un eleve sans verifier le lien familial
est « le seul defaut qui ferait perdre le client immediatement et
durablement ».

Trois regles de conception en decoulent.

**Un seul chemin.** Toute lecture concernant un eleve passe par une methode
de ``ServiceFamille`` qui exige un ``Perimetre``. Le depot, lui, ne filtre
rien et n'est jamais appele ailleurs qu'ici.

**Le perimetre se recalcule.** Il n'est ni mis en cache, ni deduit du seul
numero, ni transporte depuis le client : il se reconstruit depuis
``lien_parent_eleve`` a chaque requete.

**Un inconnu n'apprend rien.** Pas de nom, pas de classe, pas de
confirmation qu'un eleve est inscrit, meme implicite : le refus est
identique que l'eleve existe ou non.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from core.errors import AccesRefuse
from core.models.contact import Contact
from core.models.enums import Acteur, Langue
from core.telephone import NumeroInvalide, normaliser
from verticals.school.depot import DepotEcole
from verticals.school.models import (
    Classe,
    Eleve,
    Enseignant,
    Famille,
    LienParentEleve,
    Niveau,
    Parent,
)
from verticals.school.rules import (
    PERIMETRE_VIDE,
    Perimetre,
    exiger_acces_eleve,
    exiger_secretariat,
)


class StatutIdentification(StrEnum):
    """Issue de l'identification d'un numero entrant."""

    #: Numero rattache a un seul eleve : on continue directement.
    UNIQUE = "unique"
    #: Numero rattache a plusieurs eleves : il faut desambiguiser (§5.1).
    MULTIPLE = "multiple"
    #: Numero inconnu, ou connu mais rattache a aucun eleve. On ne divulgue
    #: rien et on escalade au secretariat pour rattachement manuel.
    INCONNU = "inconnu"


@dataclass(frozen=True)
class Identification:
    """Resultat de l'identification d'un numero.

    Quand ``statut`` vaut ``INCONNU``, ``eleves`` est vide et ``perimetre``
    n'ouvre rien : il n'y a litteralement rien a divulguer dans cet objet.
    """

    statut: StatutIdentification
    perimetre: Perimetre
    eleves: tuple[Eleve, ...] = ()
    doit_escalader: bool = False

    @property
    def est_rattache(self) -> bool:
        return self.statut is not StatutIdentification.INCONNU

    @property
    def exige_desambiguisation(self) -> bool:
        return self.statut is StatutIdentification.MULTIPLE


class ServiceFamille:
    """Le seul acces autorise aux donnees d'eleves.

    Toutes les methodes de lecture prennent un ``Perimetre`` en premier
    argument. Ce n'est pas une convention de style :
    ``tests/test_cloisonnement_familial.py`` verifie par introspection
    qu'aucune methode publique ne prend un ``eleve_id`` sans perimetre.
    """

    def __init__(self, depot: DepotEcole) -> None:
        self._depot = depot

    # -- construction du perimetre -------------------------------------

    def perimetre_du_numero(self, etablissement_id: str, numero: str) -> Perimetre:
        """Perimetre d'un numero entrant.

        Un numero illisible ou inconnu rend ``PERIMETRE_VIDE`` : le cas
        « je n'ai pas compris ce numero » et le cas « ce numero ne connait
        personne » doivent se comporter pareil.
        """
        try:
            canonique = normaliser(numero)
        except NumeroInvalide:
            return PERIMETRE_VIDE
        contact = self._depot.contact_par_numero(etablissement_id, canonique)
        if contact is None:
            return PERIMETRE_VIDE
        return self.perimetre_du_contact(etablissement_id, contact.id)

    def perimetre_du_contact(self, etablissement_id: str, contact_id: str) -> Perimetre:
        """Reconstruit le perimetre depuis ``lien_parent_eleve``.

        Recalcule a chaque requete, jamais mis en cache : un lien retire
        par le secretariat doit produire un refus des la requete suivante.
        """
        parents = self._depot.parents_du_contact(etablissement_id, contact_id)
        if not parents:
            return PERIMETRE_VIDE

        parent_ids: set[str] = set()
        eleve_ids: set[str] = set()
        for parent in parents:
            parent_ids.add(parent.id)
            for lien in self._depot.liens_du_parent(parent.id):
                eleve = self._depot.eleve(lien.eleve_id)
                # Un lien qui pointerait vers un eleve d'une autre ecole
                # n'ouvre rien : la verification ne se fie pas au lien seul.
                if eleve is not None and eleve.etablissement_id == etablissement_id:
                    eleve_ids.add(eleve.id)

        if not eleve_ids:
            # Contact connu mais rattache a aucun eleve : traite comme un
            # inconnu, pour ne pas laisser deduire qu'il est « presque » connu.
            return PERIMETRE_VIDE

        return Perimetre(
            etablissement_id=etablissement_id,
            contact_id=contact_id,
            parent_ids=frozenset(parent_ids),
            eleve_ids=frozenset(eleve_ids),
        )

    # -- identification ------------------------------------------------

    def identifier(self, etablissement_id: str, numero: str) -> Identification:
        """Point d'entree d'une conversation : qui ecrit, et pour quel enfant ?

        Le flux du §5.1 en decoule directement : un seul enfant, on
        continue ; plusieurs, on demande lequel ; aucun, on escalade sans
        rien dire.
        """
        perimetre = self.perimetre_du_numero(etablissement_id, numero)
        if not perimetre.est_rattache:
            return Identification(
                statut=StatutIdentification.INCONNU,
                perimetre=PERIMETRE_VIDE,
                eleves=(),
                doit_escalader=True,
            )

        eleves = self.eleves_inscrits(perimetre)
        if not eleves:
            # Tous les enfants rattaches sont sortis de l'ecole : rien a
            # proposer, un humain doit regarder.
            return Identification(
                statut=StatutIdentification.INCONNU,
                perimetre=PERIMETRE_VIDE,
                eleves=(),
                doit_escalader=True,
            )

        statut = (
            StatutIdentification.UNIQUE
            if len(eleves) == 1
            else StatutIdentification.MULTIPLE
        )
        return Identification(statut=statut, perimetre=perimetre, eleves=eleves)

    # -- lectures, toutes soumises au perimetre ------------------------

    def eleves(self, perimetre: Perimetre) -> tuple[Eleve, ...]:
        """Tous les eleves du perimetre, sortis compris."""
        trouves = [self._depot.eleve(eleve_id) for eleve_id in sorted(perimetre.eleve_ids)]
        return tuple(sorted((e for e in trouves if e is not None), key=_ordre_eleve))

    def eleves_inscrits(self, perimetre: Perimetre) -> tuple[Eleve, ...]:
        """Ceux qui sont encore a l'ecole — la liste proposee a un parent."""
        return tuple(eleve for eleve in self.eleves(perimetre) if eleve.est_inscrit)

    def eleve(self, perimetre: Perimetre, eleve_id: str) -> Eleve:
        """Un eleve du perimetre.

        Leve ``AccesRefuse`` si l'eleve n'y est pas — et la meme erreur
        s'il n'existe pas du tout.
        """
        exiger_acces_eleve(perimetre, eleve_id)
        eleve = self._depot.eleve(eleve_id)
        if eleve is None:
            raise AccesRefuse("eleve introuvable")
        return eleve

    def classe_de(self, perimetre: Perimetre, eleve_id: str) -> Classe:
        eleve = self.eleve(perimetre, eleve_id)
        classe = self._depot.classe(eleve.classe_id)
        if classe is None:
            raise AccesRefuse("classe introuvable")
        return classe

    def niveau_de(self, perimetre: Perimetre, eleve_id: str) -> Niveau:
        classe = self.classe_de(perimetre, eleve_id)
        niveau = self._depot.niveau(classe.niveau_id)
        if niveau is None:
            raise AccesRefuse("niveau introuvable")
        return niveau

    def enseignant_principal_de(self, perimetre: Perimetre, eleve_id: str) -> Enseignant:
        """L'enseignant avec qui un rendez-vous se prend par defaut."""
        classe = self.classe_de(perimetre, eleve_id)
        if classe.enseignant_principal_id is None:
            raise AccesRefuse("classe sans enseignant principal")
        enseignant = self._depot.enseignant(classe.enseignant_principal_id)
        if enseignant is None:
            raise AccesRefuse("enseignant introuvable")
        return enseignant

    def famille_de(self, perimetre: Perimetre, eleve_id: str) -> Famille:
        exiger_acces_eleve(perimetre, eleve_id)
        for lien in self._depot.liens_de_l_eleve(eleve_id):
            if not perimetre.couvre_parent(lien.parent_id):
                continue
            parent = self._depot.parent(lien.parent_id)
            if parent is None:
                continue
            famille = self._depot.famille(parent.famille_id)
            if famille is not None:
                return famille
        raise AccesRefuse("famille introuvable")

    def coparents(self, perimetre: Perimetre, eleve_id: str) -> tuple[Parent, ...]:
        """Les autres parents rattaches au meme eleve.

        Utile au secretariat et aux rappels : un rappel de rendez-vous peut
        partir au parent referent plutot qu'a celui qui a ecrit.
        """
        exiger_acces_eleve(perimetre, eleve_id)
        parents = []
        for lien in self._depot.liens_de_l_eleve(eleve_id):
            parent = self._depot.parent(lien.parent_id)
            if parent is not None:
                parents.append(parent)
        return tuple(sorted(parents, key=lambda p: (not p.est_referent, p.id)))

    # -- ecritures, reservees au secretariat ---------------------------

    def rattacher_contact(
        self,
        acteur: Acteur,
        parent: Parent,
        contact: Contact,
    ) -> Parent:
        """Rattache un numero a un parent. Jamais fait par l'agent (§8.2).

        C'est l'aboutissement d'une escalade sur numero inconnu : un humain
        verifie l'identite, puis rattache.
        """
        exiger_secretariat(acteur, "rattacher_contact")
        self._depot.enregistrer_contact(contact)
        rattache = Parent(
            id=parent.id,
            famille_id=parent.famille_id,
            contact_id=contact.id,
            lien=parent.lien,
            est_referent=parent.est_referent,
            langue_preferee=parent.langue_preferee,
        )
        return self._depot.enregistrer_parent(rattache)

    def changer_numero(self, acteur: Acteur, contact: Contact, nouveau_numero: str) -> Contact:
        """Change le numero d'un contact. Jamais fait par l'agent (§8.2).

        Un changement de numero est un transfert de droits d'acces a toute
        une famille : il ne se fait pas sur declaration dans une
        conversation.
        """
        exiger_secretariat(acteur, "changer_numero")
        modifie = Contact(
            id=contact.id,
            etablissement_id=contact.etablissement_id,
            numero=nouveau_numero,
            langue_preferee=contact.langue_preferee,
            consenti_at=contact.consenti_at,
            stoppe_at=contact.stoppe_at,
        )
        return self._depot.enregistrer_contact(modifie)

    def definir_lien(self, acteur: Acteur, lien: LienParentEleve) -> LienParentEleve:
        """Cree ou modifie un lien parent-eleve. Reserve au secretariat."""
        exiger_secretariat(acteur, "modifier_lien_parent_eleve")
        return self._depot.enregistrer_lien(lien)

    def autorisation_de_recuperer(
        self, acteur: Acteur, parent_id: str, eleve_id: str
    ) -> bool:
        """Lit ``autorise_a_recuperer``. Interdit a l'agent.

        Ce champ touche a des situations de garde. Le §8.2 est explicite :
        toute question sur ce sujet est escaladee sans etre traitee. Il
        n'existe donc aucun chemin qui permette a l'agent de le lire, meme
        avec un perimetre valide.
        """
        exiger_secretariat(acteur, "lire_autorisation_de_recuperer")
        for lien in self._depot.liens_de_l_eleve(eleve_id):
            if lien.parent_id == parent_id:
                return lien.autorise_a_recuperer
        raise AccesRefuse("lien inexistant")

    # -- langue --------------------------------------------------------

    def langue_du_perimetre(self, perimetre: Perimetre, defaut: Langue) -> Langue:
        """Langue preferee du parent, sinon celle de l'etablissement."""
        for parent_id in sorted(perimetre.parent_ids):
            parent = self._depot.parent(parent_id)
            if parent is not None and parent.langue_preferee is not None:
                return parent.langue_preferee
        if perimetre.contact_id is not None:
            contact = self._depot.contact(perimetre.contact_id)
            if contact is not None and contact.langue_preferee is not None:
                return contact.langue_preferee
        return defaut


def _ordre_eleve(eleve: Eleve) -> tuple[str, str, str]:
    return (eleve.prenom, eleve.nom, eleve.id)
