"""Objets de la verticale scolaire.

La difference de fond avec MAWID tient en une phrase : une ecole n'a pas de
patients, elle a des **familles**. Un parent peut avoir trois enfants dans
trois classes, et tout le modele tourne autour de cette relation plutot
qu'autour d'un contact isole.

Le §8.1 impose une seconde contrainte, plus severe : ces donnees concernent
des mineurs. La classe ``Eleve`` porte donc le strict minimum, et
``tests/test_donnees_minimales_eleve.py`` echoue si on lui ajoute un champ.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum

from core.errors import ErreurConfiguration
from core.i18n.libelles import LibelleI18n
from core.models.agenda import Occupation
from core.models.enums import Acteur, Langue, StatutRendezVous
from core.models.etablissement import Ressource
from core.temps import exiger_conscient

#: Bornes de bon sens pour l'annee de naissance d'un eleve.
ANNEE_NAISSANCE_MIN = 1990
ANNEE_NAISSANCE_MAX = 2100


class TypePeriode(StrEnum):
    TRIMESTRE = "trimestre"
    SEMESTRE = "semestre"
    VACANCES = "vacances"
    EXAMENS = "examens"


class LienParente(StrEnum):
    PERE = "pere"
    MERE = "mere"
    TUTEUR = "tuteur"


class StatutEleve(StrEnum):
    INSCRIT = "inscrit"
    SORTI = "sorti"


class DestinataireRendezVous(StrEnum):
    ENSEIGNANT = "enseignant"
    DIRECTION = "direction"
    VIE_SCOLAIRE = "vie_scolaire"


# -- calendrier scolaire ----------------------------------------------


@dataclass(frozen=True)
class AnneeScolaire:
    id: str
    etablissement_id: str
    libelle: str
    date_debut: date
    date_fin: date
    active: bool = False

    def __post_init__(self) -> None:
        if self.date_fin <= self.date_debut:
            raise ErreurConfiguration("une annee scolaire doit se terminer apres son debut")

    def couvre(self, jour: date) -> bool:
        return self.date_debut <= jour <= self.date_fin


@dataclass(frozen=True)
class Periode:
    """Trimestre, semestre, vacances ou examens."""

    id: str
    annee_scolaire_id: str
    libelle_i18n: LibelleI18n
    type: TypePeriode
    date_debut: date
    date_fin: date

    def __post_init__(self) -> None:
        if self.date_fin < self.date_debut:
            raise ErreurConfiguration("une periode doit se terminer apres son debut")
        if not self.libelle_i18n:
            raise ErreurConfiguration("une periode doit avoir un libelle")

    def couvre(self, jour: date) -> bool:
        return self.date_debut <= jour <= self.date_fin

    @property
    def est_vacances(self) -> bool:
        return self.type is TypePeriode.VACANCES


# -- structure pedagogique --------------------------------------------


@dataclass(frozen=True)
class Niveau:
    """Un niveau de l'ecole (CP, CM1, 6eme...).

    Les libelles sont officiels et propres a chaque etablissement : ils ne
    sont jamais traduits par le modele de langue (§7).
    """

    id: str
    etablissement_id: str
    libelle_i18n: LibelleI18n
    ordre: int

    def __post_init__(self) -> None:
        if not self.libelle_i18n:
            raise ErreurConfiguration("un niveau doit avoir un libelle officiel")


@dataclass(frozen=True)
class Classe:
    id: str
    etablissement_id: str
    niveau_id: str
    annee_scolaire_id: str
    libelle: str
    enseignant_principal_id: str | None = None
    effectif: int = 0

    def __post_init__(self) -> None:
        if self.effectif < 0:
            raise ErreurConfiguration("un effectif ne peut pas etre negatif")


@dataclass(frozen=True)
class Enseignant:
    """Remplace le ``praticien`` du noyau : c'est la ressource qui se reserve.

    ``vers_ressource`` produit la vue que le moteur de creneaux attend, ce
    qui evite au noyau d'avoir a connaitre la notion d'enseignant.
    """

    id: str
    etablissement_id: str
    nom: str
    matieres: tuple[str, ...] = ()
    classes: tuple[str, ...] = ()
    langues: frozenset[Langue] = frozenset()
    duree_creneau_min: int = 30
    actif: bool = True

    def __post_init__(self) -> None:
        if self.duree_creneau_min <= 0:
            raise ErreurConfiguration("la duree de creneau doit etre strictement positive")

    def vers_ressource(self) -> Ressource:
        return Ressource(
            id=self.id,
            etablissement_id=self.etablissement_id,
            libelle=self.nom,
            duree_creneau_min=self.duree_creneau_min,
            langues=self.langues,
            actif=self.actif,
        )


@dataclass(frozen=True)
class Eleve:
    """Un eleve. Mineur, donc reduit au strict minimum (§8.1).

    Ce qui n'est **pas** ici, et ne doit jamais y entrer : date de naissance
    complete, photo, donnee de sante, note, moyenne, appreciation, element
    de comportement, adresse. BALLAN prend des rendez-vous et communique ;
    il ne tient pas le dossier scolaire.

    ``date_naissance_annee`` ne contient que l'annee. Elle suffit a tout ce
    que fait BALLAN, et une annee seule ne permet pas de reidentifier un
    enfant.
    """

    id: str
    etablissement_id: str
    classe_id: str
    prenom: str
    nom: str
    identifiant_interne: str
    date_naissance_annee: int | None = None
    statut: StatutEleve = StatutEleve.INSCRIT

    def __post_init__(self) -> None:
        annee = self.date_naissance_annee
        if annee is None:
            return
        # Refuse explicitement un objet date : c'est l'erreur qu'on veut
        # attraper a la construction plutot qu'en relecture de schema.
        if not isinstance(annee, int) or isinstance(annee, bool):
            raise ErreurConfiguration(
                "date_naissance_annee ne contient qu'une annee, jamais une date complete"
            )
        if not ANNEE_NAISSANCE_MIN <= annee <= ANNEE_NAISSANCE_MAX:
            raise ErreurConfiguration(
                "date_naissance_annee doit etre une annee seule, "
                f"entre {ANNEE_NAISSANCE_MIN} et {ANNEE_NAISSANCE_MAX}"
            )

    @property
    def est_inscrit(self) -> bool:
        return self.statut is StatutEleve.INSCRIT


# -- familles ----------------------------------------------------------


@dataclass(frozen=True)
class Famille:
    id: str
    etablissement_id: str
    nom_affiche: str


@dataclass(frozen=True)
class Parent:
    """Un parent : une personne rattachee a une famille et a un numero.

    ``contact_id`` peut etre absent : une ecole connait parfois un parent
    sans avoir son numero. Un parent sans contact ne recoit rien et ne peut
    identifier personne.
    """

    id: str
    famille_id: str
    contact_id: str | None = None
    lien: LienParente = LienParente.TUTEUR
    est_referent: bool = False
    langue_preferee: Langue | None = None


@dataclass(frozen=True)
class LienParentEleve:
    """Le lien qui autorise tout. C'est la table la plus sensible du produit.

    Un parent ne voit que les eleves auxquels cette table le rattache, et
    cette verification est refaite cote serveur a chaque requete (§8.2).

    ``autorise_a_recuperer`` est gere par l'ecole, jamais par l'agent : il
    touche a des situations de garde. Toute question sur ce sujet est
    escaladee sans etre traitee.
    """

    parent_id: str
    eleve_id: str
    autorise_a_recuperer: bool = True


# -- catalogue administratif ------------------------------------------


@dataclass(frozen=True)
class MotifRendezVous:
    """Catalogue de motifs defini par l'ecole, jamais invente par l'agent.

    Un motif adresse a l'enseignant se resout vers l'enseignant principal de
    la classe de l'enfant. Un motif adresse a la direction ou a la vie
    scolaire designe explicitement la ressource qui recoit (``ressource_id``) :
    l'agent ne devine jamais a qui envoyer un parent.
    """

    id: str
    etablissement_id: str
    libelle_i18n: LibelleI18n
    duree_min: int = 30
    destinataire: DestinataireRendezVous = DestinataireRendezVous.ENSEIGNANT
    ressource_id: str | None = None
    actif: bool = True
    ordre: int = 0

    def __post_init__(self) -> None:
        if not self.libelle_i18n:
            raise ErreurConfiguration("un motif doit avoir un libelle")
        if self.duree_min <= 0:
            raise ErreurConfiguration("la duree d'un motif doit etre strictement positive")
        if self.destinataire is not DestinataireRendezVous.ENSEIGNANT and not self.ressource_id:
            raise ErreurConfiguration(
                f"un motif adresse a {self.destinataire.value} doit designer sa ressource"
            )


# -- rendez-vous -------------------------------------------------------


@dataclass(frozen=True)
class RendezVous:
    """Un rendez-vous scolaire : le rendez-vous du noyau, plus l'eleve.

    Il ne porte ni texte libre ni commentaire : un champ « remarque » serait
    la porte d'entree d'appreciations et d'informations de comportement,
    exactement ce que le §3 exclut.
    """

    id: str
    etablissement_id: str
    ressource_id: str
    eleve_id: str
    debut: datetime
    fin: datetime
    motif_id: str | None = None
    parent_id: str | None = None
    contact_id: str | None = None
    statut: StatutRendezVous = StatutRendezVous.CONFIRME
    cree_par: Acteur = Acteur.AGENT
    rappel_envoye_at: datetime | None = None

    def __post_init__(self) -> None:
        exiger_conscient(self.debut, "RendezVous.debut")
        exiger_conscient(self.fin, "RendezVous.fin")
        if self.fin <= self.debut:
            raise ErreurConfiguration("un rendez-vous doit se terminer apres son debut")

    @property
    def est_confirme(self) -> bool:
        return self.statut is StatutRendezVous.CONFIRME

    def vers_occupation(self) -> Occupation:
        return Occupation(
            ressource_id=self.ressource_id,
            debut=self.debut,
            fin=self.fin,
            statut=self.statut,
            reference_id=self.id,
        )


@dataclass(frozen=True)
class StructureScolaire:
    """Vue assemblee d'une annee : ce que le tableau de bord affiche."""

    annee: AnneeScolaire
    niveaux: tuple[Niveau, ...] = field(default_factory=tuple)
    classes: tuple[Classe, ...] = field(default_factory=tuple)

    def classes_du_niveau(self, niveau_id: str) -> tuple[Classe, ...]:
        return tuple(c for c in self.classes if c.niveau_id == niveau_id)

    def niveaux_ordonnes(self) -> tuple[Niveau, ...]:
        return tuple(sorted(self.niveaux, key=lambda n: n.ordre))
