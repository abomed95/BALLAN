"""Une ecole complete, en memoire, pour les tests de la verticale.

Elle est construite autour des cas qui font mal (§13) :

* la famille Ahmed a **trois enfants dans trois classes differentes** ;
* la famille Osman a deux parents rattaches au meme enfant ;
* un contact est connu de l'ecole mais rattache a aucun eleve ;
* une famille n'a plus qu'un enfant sorti de l'etablissement ;
* un numero est totalement inconnu.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time

from core.models import Contact, Disponibilite, Etablissement, Jour, Langue, Ressource
from core.scheduling import Calendrier
from verticals.school.configuration import ConfigurationEcole
from verticals.school.depot import DepotEcoleMemoire
from verticals.school.models import (
    AnneeScolaire,
    Classe,
    DestinataireRendezVous,
    Eleve,
    Enseignant,
    Famille,
    LienParente,
    LienParentEleve,
    MotifRendezVous,
    Niveau,
    Parent,
    Periode,
    StatutEleve,
    TypePeriode,
)

ETAB = "etab-1"

# -- numeros -----------------------------------------------------------

NUM_HALIMA = "+25377111111"  # mere de trois enfants
NUM_ISMAIL = "+25377222222"  # pere, famille Osman
NUM_FATOUMA = "+25377333333"  # mere, famille Osman (coparent)
NUM_SANS_ENFANT = "+25377444444"  # contact connu, rattache a personne
NUM_ANCIENNE_FAMILLE = "+25377555555"  # seul enfant sorti de l'ecole
NUM_INCONNU = "+25377999999"  # jamais vu

CONSENTI_LE = datetime(2025, 9, 1, 8, 0, tzinfo=UTC)


def ecole() -> Etablissement:
    return Etablissement(
        id=ETAB,
        nom="Ecole Al-Nour",
        langues_actives=frozenset(Langue),
        langue_defaut=Langue.FR,
    )


# -- annee et periodes -------------------------------------------------

ANNEE = AnneeScolaire(
    id="annee-2025",
    etablissement_id=ETAB,
    libelle="2025-2026",
    date_debut=date(2025, 9, 7),
    date_fin=date(2026, 6, 25),
    active=True,
)

PERIODES = [
    Periode(
        id="t1",
        annee_scolaire_id="annee-2025",
        libelle_i18n={"fr": "Premier trimestre", "ar": "الفصل الأول"},
        type=TypePeriode.TRIMESTRE,
        date_debut=date(2025, 9, 7),
        date_fin=date(2025, 12, 11),
    ),
    Periode(
        id="vac-t1",
        annee_scolaire_id="annee-2025",
        libelle_i18n={"fr": "Vacances de fin de trimestre", "ar": "عطلة نهاية الفصل"},
        type=TypePeriode.VACANCES,
        date_debut=date(2025, 12, 14),
        date_fin=date(2026, 1, 3),
    ),
    Periode(
        id="t2",
        annee_scolaire_id="annee-2025",
        libelle_i18n={"fr": "Deuxieme trimestre", "ar": "الفصل الثاني"},
        type=TypePeriode.TRIMESTRE,
        date_debut=date(2026, 1, 4),
        date_fin=date(2026, 3, 26),
    ),
    Periode(
        id="examens-t2",
        annee_scolaire_id="annee-2025",
        libelle_i18n={"fr": "Examens du deuxieme trimestre", "ar": "امتحانات الفصل الثاني"},
        type=TypePeriode.EXAMENS,
        date_debut=date(2026, 3, 22),
        date_fin=date(2026, 3, 26),
    ),
    Periode(
        id="vac-t2",
        annee_scolaire_id="annee-2025",
        libelle_i18n={"fr": "Vacances de printemps", "ar": "عطلة الربيع"},
        type=TypePeriode.VACANCES,
        date_debut=date(2026, 3, 29),
        date_fin=date(2026, 4, 11),
    ),
    Periode(
        id="t3",
        annee_scolaire_id="annee-2025",
        libelle_i18n={"fr": "Troisieme trimestre", "ar": "الفصل الثالث"},
        type=TypePeriode.TRIMESTRE,
        date_debut=date(2026, 4, 12),
        date_fin=date(2026, 6, 25),
    ),
]

# -- structure ---------------------------------------------------------

# Libelles officiels en francais et en arabe, jamais traduits par le modele (§7).
# Le somali et l'afar ne sont pas saisis : le tableau de bord doit pouvoir le
# signaler a l'ecole plutot que d'inventer.
NIVEAUX = [
    Niveau(
        id="niv-ce2",
        etablissement_id=ETAB,
        libelle_i18n={"fr": "CE2", "ar": "السنة الثالثة"},
        ordre=3,
    ),
    Niveau(
        id="niv-cm1",
        etablissement_id=ETAB,
        libelle_i18n={"fr": "CM1", "ar": "السنة الرابعة"},
        ordre=4,
    ),
    Niveau(
        id="niv-cm2",
        etablissement_id=ETAB,
        libelle_i18n={"fr": "CM2", "ar": "السنة الخامسة"},
        ordre=5,
    ),
]

ENSEIGNANTS = [
    Enseignant(
        id="ens-b",
        etablissement_id=ETAB,
        nom="Mme B.",
        matieres=("polyvalent",),
        classes=("cl-cm1-b",),
        langues=frozenset({Langue.FR, Langue.AR}),
    ),
    Enseignant(
        id="ens-a",
        etablissement_id=ETAB,
        nom="M. A.",
        matieres=("polyvalent",),
        classes=("cl-ce2-a",),
        langues=frozenset({Langue.FR, Langue.SO}),
    ),
    Enseignant(
        id="ens-c",
        etablissement_id=ETAB,
        nom="Mme C.",
        matieres=("polyvalent",),
        classes=("cl-cm2-a",),
        langues=frozenset({Langue.FR}),
    ),
]

CLASSES = [
    Classe(
        id="cl-ce2-a",
        etablissement_id=ETAB,
        niveau_id="niv-ce2",
        annee_scolaire_id="annee-2025",
        libelle="CE2 A",
        enseignant_principal_id="ens-a",
        effectif=28,
    ),
    Classe(
        id="cl-cm1-b",
        etablissement_id=ETAB,
        niveau_id="niv-cm1",
        annee_scolaire_id="annee-2025",
        libelle="CM1 B",
        enseignant_principal_id="ens-b",
        effectif=26,
    ),
    Classe(
        id="cl-cm2-a",
        etablissement_id=ETAB,
        niveau_id="niv-cm2",
        annee_scolaire_id="annee-2025",
        libelle="CM2 A",
        enseignant_principal_id="ens-c",
        effectif=30,
    ),
]

# -- eleves ------------------------------------------------------------

AHMED = Eleve(
    id="el-ahmed",
    etablissement_id=ETAB,
    classe_id="cl-cm1-b",
    prenom="Ahmed",
    nom="Ali",
    identifiant_interne="2025-0101",
    date_naissance_annee=2015,
)
SAGAL = Eleve(
    id="el-sagal",
    etablissement_id=ETAB,
    classe_id="cl-ce2-a",
    prenom="Sagal",
    nom="Ali",
    identifiant_interne="2025-0102",
    date_naissance_annee=2017,
)
NASRA = Eleve(
    id="el-nasra",
    etablissement_id=ETAB,
    classe_id="cl-cm2-a",
    prenom="Nasra",
    nom="Ali",
    identifiant_interne="2025-0103",
    date_naissance_annee=2014,
)
MOUNA = Eleve(
    id="el-mouna",
    etablissement_id=ETAB,
    classe_id="cl-cm1-b",
    prenom="Mouna",
    nom="Osman",
    identifiant_interne="2025-0201",
    date_naissance_annee=2015,
)
IDRIS = Eleve(
    id="el-idris",
    etablissement_id=ETAB,
    classe_id="cl-cm2-a",
    prenom="Idris",
    nom="Robleh",
    identifiant_interne="2023-0301",
    date_naissance_annee=2013,
    statut=StatutEleve.SORTI,
)

ELEVES = [AHMED, SAGAL, NASRA, MOUNA, IDRIS]

# -- familles ----------------------------------------------------------

FAMILLES = [
    Famille(id="fam-ali", etablissement_id=ETAB, nom_affiche="Famille Ali"),
    Famille(id="fam-osman", etablissement_id=ETAB, nom_affiche="Famille Osman"),
    Famille(id="fam-nomade", etablissement_id=ETAB, nom_affiche="Famille sans enfant inscrit"),
    Famille(id="fam-robleh", etablissement_id=ETAB, nom_affiche="Famille Robleh"),
]

CONTACTS = [
    Contact(
        id="ct-halima",
        etablissement_id=ETAB,
        numero=NUM_HALIMA,
        langue_preferee=Langue.SO,
        consenti_at=CONSENTI_LE,
    ),
    Contact(id="ct-ismail", etablissement_id=ETAB, numero=NUM_ISMAIL, consenti_at=CONSENTI_LE),
    Contact(
        id="ct-fatouma",
        etablissement_id=ETAB,
        numero=NUM_FATOUMA,
        langue_preferee=Langue.AR,
        consenti_at=CONSENTI_LE,
    ),
    Contact(id="ct-sans-enfant", etablissement_id=ETAB, numero=NUM_SANS_ENFANT),
    Contact(id="ct-robleh", etablissement_id=ETAB, numero=NUM_ANCIENNE_FAMILLE),
]

PARENTS = [
    Parent(
        id="pa-halima",
        famille_id="fam-ali",
        contact_id="ct-halima",
        lien=LienParente.MERE,
        est_referent=True,
        langue_preferee=Langue.SO,
    ),
    Parent(
        id="pa-ismail",
        famille_id="fam-osman",
        contact_id="ct-ismail",
        lien=LienParente.PERE,
        est_referent=True,
    ),
    Parent(
        id="pa-fatouma",
        famille_id="fam-osman",
        contact_id="ct-fatouma",
        lien=LienParente.MERE,
        langue_preferee=Langue.AR,
    ),
    Parent(
        id="pa-sans-enfant",
        famille_id="fam-nomade",
        contact_id="ct-sans-enfant",
        lien=LienParente.TUTEUR,
    ),
    Parent(
        id="pa-robleh",
        famille_id="fam-robleh",
        contact_id="ct-robleh",
        lien=LienParente.PERE,
        est_referent=True,
    ),
]

LIENS = [
    LienParentEleve(parent_id="pa-halima", eleve_id="el-ahmed"),
    LienParentEleve(parent_id="pa-halima", eleve_id="el-sagal"),
    LienParentEleve(parent_id="pa-halima", eleve_id="el-nasra"),
    LienParentEleve(parent_id="pa-ismail", eleve_id="el-mouna"),
    LienParentEleve(parent_id="pa-fatouma", eleve_id="el-mouna", autorise_a_recuperer=False),
    LienParentEleve(parent_id="pa-robleh", eleve_id="el-idris"),
]


def depot() -> DepotEcoleMemoire:
    return DepotEcoleMemoire(
        contacts=CONTACTS,
        familles=FAMILLES,
        parents=PARENTS,
        liens=LIENS,
        eleves=ELEVES,
        classes=CLASSES,
        niveaux=NIVEAUX,
        enseignants=ENSEIGNANTS,
        annees=[ANNEE],
        periodes=PERIODES,
    )


def disponibilites() -> list[Disponibilite]:
    """Chaque enseignant recoit les parents une matinee par semaine."""
    grille = {
        "ens-a": Jour.DIMANCHE,
        "ens-b": Jour.LUNDI,
        "ens-c": Jour.MARDI,
    }
    return [
        Disponibilite(
            id=f"dispo-{enseignant_id}",
            etablissement_id=ETAB,
            ressource_id=enseignant_id,
            jour=jour,
            heure_debut=time(8, 0),
            heure_fin=time(10, 0),
        )
        for enseignant_id, jour in grille.items()
    ]


def calendrier_noyau() -> Calendrier:
    return Calendrier(
        etablissement=ecole(),
        disponibilites=disponibilites(),
        exceptions=[],
    )


# -- configuration et motifs (lot 3) -----------------------------------

DIRECTION = Ressource(id="direction", etablissement_id=ETAB, libelle="Direction")

MOTIFS = [
    MotifRendezVous(
        id="motif-suivi",
        etablissement_id=ETAB,
        libelle_i18n={"fr": "Suivi de la scolarite", "ar": "متابعة الدراسة"},
        duree_min=30,
        ordre=1,
    ),
    MotifRendezVous(
        id="motif-direction",
        etablissement_id=ETAB,
        libelle_i18n={"fr": "Rencontre avec la direction"},
        duree_min=30,
        destinataire=DestinataireRendezVous.DIRECTION,
        ressource_id="direction",
        ordre=2,
    ),
    MotifRendezVous(
        id="motif-ancien",
        etablissement_id=ETAB,
        libelle_i18n={"fr": "Ancien motif"},
        actif=False,
        ordre=3,
    ),
]


def configuration() -> ConfigurationEcole:
    dispos = disponibilites() + [
        Disponibilite(
            id="dispo-direction",
            etablissement_id=ETAB,
            ressource_id="direction",
            jour=Jour.MERCREDI,
            heure_debut=time(10, 0),
            heure_fin=time(11, 0),
        )
    ]
    return ConfigurationEcole(
        etablissement=ecole(),
        annee=ANNEE,
        periodes=tuple(PERIODES),
        disponibilites=tuple(dispos),
        ressources=tuple([e.vers_ressource() for e in ENSEIGNANTS] + [DIRECTION]),
        motifs=tuple(MOTIFS),
    )
