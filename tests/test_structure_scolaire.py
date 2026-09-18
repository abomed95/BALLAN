"""Structure scolaire : annee, niveaux, classes, enseignants, libelles.

Le fil conducteur : l'ecole declare sa propre structure. Rien n'est en dur,
et les libelles officiels ne passent jamais par le modele de langue (§7).
"""

from __future__ import annotations

from datetime import date, time

import pytest

from core.errors import ErreurConfiguration
from core.i18n.libelles import resoudre_libelle, verifier_libelle
from core.models import Langue
from core.scheduling import MoteurCreneaux
from tests import fixtures_ecole as fx
from verticals.school.family import ServiceFamille
from verticals.school.models import (
    AnneeScolaire,
    Classe,
    DestinataireRendezVous,
    Enseignant,
    MotifRendezVous,
    Niveau,
    Periode,
    StructureScolaire,
    TypePeriode,
)


@pytest.fixture
def service():
    return ServiceFamille(fx.depot())


# -- l'enseignant est la ressource du noyau ----------------------------


def test_un_enseignant_se_convertit_en_ressource_du_noyau():
    """C'est ainsi que le noyau ignore la notion d'enseignant."""
    enseignante = fx.ENSEIGNANTS[0]
    ressource = enseignante.vers_ressource()
    assert ressource.id == enseignante.id
    assert ressource.libelle == enseignante.nom
    assert ressource.duree_creneau_min == enseignante.duree_creneau_min
    assert ressource.langues == enseignante.langues


def test_le_moteur_de_creneaux_fonctionne_sur_un_enseignant():
    moteur = MoteurCreneaux(calendrier=fx.calendrier_noyau())
    creneaux = moteur.creneaux_du_jour("ens-b", date(2025, 9, 22), duree_min=30)
    assert [c.debut.time() for c in creneaux] == [
        time(8, 0),
        time(8, 30),
        time(9, 0),
        time(9, 30),
    ]


def test_chaque_enseignant_recoit_un_jour_different():
    moteur = MoteurCreneaux(calendrier=fx.calendrier_noyau())
    lundi = date(2025, 9, 22)
    assert moteur.creneaux_du_jour("ens-b", lundi, duree_min=30)
    assert moteur.creneaux_du_jour("ens-a", lundi, duree_min=30) == []


def test_une_duree_de_creneau_nulle_est_refusee():
    with pytest.raises(ErreurConfiguration):
        Enseignant(id="x", etablissement_id=fx.ETAB, nom="X", duree_creneau_min=0)


# -- libelles officiels ------------------------------------------------


def test_les_niveaux_portent_leur_libelle_officiel_par_langue():
    cm1 = next(n for n in fx.NIVEAUX if n.id == "niv-cm1")
    assert resoudre_libelle(cm1.libelle_i18n, Langue.FR) == "CM1"
    assert resoudre_libelle(cm1.libelle_i18n, Langue.AR) == "السنة الرابعة"


def test_un_libelle_manquant_replie_sans_traduire():
    """Le somali n'est pas saisi : on montre le libelle francais tel quel,
    on ne demande pas au modele de le traduire."""
    cm1 = next(n for n in fx.NIVEAUX if n.id == "niv-cm1")
    assert resoudre_libelle(cm1.libelle_i18n, Langue.SO) == "CM1"


def test_le_tableau_de_bord_sait_ce_qui_reste_a_saisir():
    cm1 = next(n for n in fx.NIVEAUX if n.id == "niv-cm1")
    assert verifier_libelle(cm1.libelle_i18n, frozenset(Langue)) == {Langue.SO, Langue.AA}


def test_un_niveau_sans_libelle_est_refuse():
    with pytest.raises(ErreurConfiguration):
        Niveau(id="x", etablissement_id=fx.ETAB, libelle_i18n={}, ordre=1)


# -- coherence de la structure ----------------------------------------


def test_les_niveaux_s_ordonnent_par_leur_champ_ordre():
    structure = StructureScolaire(
        annee=fx.ANNEE,
        niveaux=tuple(reversed(fx.NIVEAUX)),
        classes=tuple(fx.CLASSES),
    )
    assert [n.id for n in structure.niveaux_ordonnes()] == ["niv-ce2", "niv-cm1", "niv-cm2"]


def test_les_classes_se_regroupent_par_niveau():
    structure = StructureScolaire(
        annee=fx.ANNEE, niveaux=tuple(fx.NIVEAUX), classes=tuple(fx.CLASSES)
    )
    assert [c.libelle for c in structure.classes_du_niveau("niv-cm1")] == ["CM1 B"]


def test_une_annee_scolaire_inversee_est_refusee():
    with pytest.raises(ErreurConfiguration):
        AnneeScolaire(
            id="x",
            etablissement_id=fx.ETAB,
            libelle="2025-2026",
            date_debut=date(2026, 6, 25),
            date_fin=date(2025, 9, 7),
        )


def test_une_periode_inversee_est_refusee():
    with pytest.raises(ErreurConfiguration):
        Periode(
            id="x",
            annee_scolaire_id="annee-2025",
            libelle_i18n={"fr": "Trimestre"},
            type=TypePeriode.TRIMESTRE,
            date_debut=date(2025, 12, 11),
            date_fin=date(2025, 9, 7),
        )


def test_un_effectif_negatif_est_refuse():
    with pytest.raises(ErreurConfiguration):
        Classe(
            id="x",
            etablissement_id=fx.ETAB,
            niveau_id="niv-cm1",
            annee_scolaire_id="annee-2025",
            libelle="CM1 C",
            effectif=-1,
        )


# -- motifs de rendez-vous --------------------------------------------


def test_un_motif_est_un_choix_de_l_ecole_pas_une_invention_de_l_agent():
    motif = MotifRendezVous(
        id="mo-suivi",
        etablissement_id=fx.ETAB,
        libelle_i18n={"fr": "Suivi scolaire", "ar": "المتابعة الدراسية"},
        duree_min=20,
        destinataire=DestinataireRendezVous.ENSEIGNANT,
    )
    assert resoudre_libelle(motif.libelle_i18n, Langue.FR) == "Suivi scolaire"
    assert motif.destinataire is DestinataireRendezVous.ENSEIGNANT


def test_un_motif_sans_libelle_est_refuse():
    with pytest.raises(ErreurConfiguration):
        MotifRendezVous(id="x", etablissement_id=fx.ETAB, libelle_i18n={})


# -- langue de la conversation ----------------------------------------


def test_la_langue_du_parent_prime_sur_celle_de_l_ecole(service):
    perimetre = service.perimetre_du_numero(fx.ETAB, fx.NUM_HALIMA)
    assert service.langue_du_perimetre(perimetre, Langue.FR) is Langue.SO


def test_la_langue_de_l_ecole_sert_de_repli(service):
    perimetre = service.perimetre_du_numero(fx.ETAB, fx.NUM_ISMAIL)
    assert service.langue_du_perimetre(perimetre, Langue.FR) is Langue.FR


def test_les_deux_parents_d_un_eleve_peuvent_avoir_des_langues_differentes(service):
    ismail = service.perimetre_du_numero(fx.ETAB, fx.NUM_ISMAIL)
    fatouma = service.perimetre_du_numero(fx.ETAB, fx.NUM_FATOUMA)
    assert service.langue_du_perimetre(ismail, Langue.FR) is Langue.FR
    assert service.langue_du_perimetre(fatouma, Langue.FR) is Langue.AR


def test_le_parent_referent_arrive_en_tete_des_coparents(service):
    perimetre = service.perimetre_du_numero(fx.ETAB, fx.NUM_FATOUMA)
    coparents = service.coparents(perimetre, fx.MOUNA.id)
    assert [p.id for p in coparents] == ["pa-ismail", "pa-fatouma"]
