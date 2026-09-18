"""Fiche etablissement, ressources, contacts.

Tout ce que BALLAN sait d'une ecole vient d'ici. Les valeurs par defaut de
ce fichier sont les seules valeurs « djiboutiennes » du produit, et elles
restent surchargeables etablissement par etablissement.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, time

import pytest

from core.errors import ErreurConfiguration
from core.models import (
    JOURS_OUVRES_DEFAUT,
    Contact,
    Etablissement,
    FenetreSilence,
    Jour,
    Langue,
)
from core.models.agenda import Occupation
from core.models.enums import StatutRendezVous
from core.scheduling import AgendaMemoire
from tests.conftest import LUNDI, instant

# -- fiche etablissement -----------------------------------------------


def test_la_semaine_par_defaut_va_du_dimanche_au_jeudi():
    assert JOURS_OUVRES_DEFAUT == {
        Jour.DIMANCHE,
        Jour.LUNDI,
        Jour.MARDI,
        Jour.MERCREDI,
        Jour.JEUDI,
    }


def test_une_ecole_peut_declarer_une_autre_semaine_ouvree():
    """« A confirmer etablissement par etablissement » (§2)."""
    ecole = Etablissement(
        id="etab-2",
        nom="Ecole B",
        jours_ouvres=frozenset({Jour.LUNDI, Jour.MARDI, Jour.MERCREDI}),
    )
    assert ecole.est_jour_ouvre(Jour.LUNDI)
    assert not ecole.est_jour_ouvre(Jour.DIMANCHE)


def test_une_langue_par_defaut_hors_des_langues_actives_est_refusee(ecole):
    with pytest.raises(ErreurConfiguration):
        replace(ecole, langues_actives=frozenset({Langue.FR}), langue_defaut=Langue.AR)


def test_une_ecole_sans_langue_active_est_refusee(ecole):
    with pytest.raises(ErreurConfiguration):
        replace(ecole, langues_actives=frozenset())


def test_une_ecole_sans_jour_ouvre_est_refusee(ecole):
    with pytest.raises(ErreurConfiguration):
        replace(ecole, jours_ouvres=frozenset())


def test_un_delai_minimal_negatif_est_refuse(ecole):
    with pytest.raises(ErreurConfiguration):
        replace(ecole, delai_minimal_min=-30)


def test_une_langue_non_active_replie_sur_la_langue_de_l_ecole():
    ecole = Etablissement(
        id="etab-3",
        nom="Ecole C",
        langues_actives=frozenset({Langue.FR, Langue.AR}),
        langue_defaut=Langue.FR,
    )
    assert ecole.langue_ou_defaut(Langue.AR) is Langue.AR
    assert ecole.langue_ou_defaut(Langue.SO) is Langue.FR
    assert ecole.langue_ou_defaut(None) is Langue.FR


def test_un_fuseau_inconnu_est_une_erreur_de_configuration(ecole):
    mal_configuree = replace(ecole, fuseau_nom="Mars/Olympus")
    with pytest.raises(ErreurConfiguration):
        _ = mal_configuree.tz


# -- fenetre de silence ------------------------------------------------


def test_la_fenetre_de_silence_enjambe_minuit():
    """21:00 -> 07:00 : la comparaison naive se trompe ici une fois sur deux."""
    silence = FenetreSilence()
    assert silence.couvre(time(22, 0))
    assert silence.couvre(time(3, 0))
    assert silence.couvre(time(21, 0))
    assert not silence.couvre(time(7, 0))
    assert not silence.couvre(time(12, 0))
    assert not silence.couvre(time(20, 59))


def test_une_fenetre_de_silence_ordinaire_ne_couvre_que_sa_tranche():
    silence = FenetreSilence(debut=time(12, 0), fin=time(14, 0))
    assert silence.couvre(time(13, 0))
    assert not silence.couvre(time(23, 0))


def test_une_fenetre_de_silence_nulle_ne_couvre_rien():
    silence = FenetreSilence(debut=time(0, 0), fin=time(0, 0))
    assert not silence.couvre(time(3, 0))


# -- ressources --------------------------------------------------------


def test_le_pas_de_la_grille_vaut_la_duree_par_defaut(enseignante):
    assert enseignante.pas_effectif == enseignante.duree_creneau_min


def test_un_pas_plus_court_permet_des_departs_decales(enseignante):
    assert replace(enseignante, pas_min=15).pas_effectif == 15


@pytest.mark.parametrize("champs", [{"duree_creneau_min": 0}, {"pas_min": 0}])
def test_une_grille_absurde_est_refusee(enseignante, champs):
    with pytest.raises(ErreurConfiguration):
        replace(enseignante, **champs)


# -- contacts ----------------------------------------------------------


def test_le_numero_est_normalise_a_la_construction():
    contact = Contact(id="ct-1", etablissement_id="etab-1", numero="77 12 34 56")
    assert contact.numero == "+25377123456"


def test_sans_consentement_aucun_envoi_sortant():
    """§8.3 : consentement horodate des parents pour rappels et annonces."""
    contact = Contact(id="ct-1", etablissement_id="etab-1", numero="+25377123456")
    assert not contact.accepte_envois


def test_un_stop_coupe_les_envois_malgre_le_consentement():
    contact = Contact(
        id="ct-1",
        etablissement_id="etab-1",
        numero="+25377123456",
        consenti_at=datetime(2025, 9, 1, tzinfo=UTC),
        stoppe_at=datetime(2025, 9, 15, tzinfo=UTC),
    )
    assert not contact.accepte_envois


def test_un_contact_consentant_accepte_les_envois():
    contact = Contact(
        id="ct-1",
        etablissement_id="etab-1",
        numero="+25377123456",
        consenti_at=datetime(2025, 9, 1, tzinfo=UTC),
    )
    assert contact.accepte_envois


def test_un_horodatage_naif_est_refuse():
    with pytest.raises(ErreurConfiguration):
        Contact(
            id="ct-1",
            etablissement_id="etab-1",
            numero="+25377123456",
            consenti_at=datetime(2025, 9, 1),
        )


# -- agenda ------------------------------------------------------------


def _occupation(reference_id: str = "rdv-1") -> Occupation:
    return Occupation(
        ressource_id="ens-1",
        debut=instant(LUNDI, time(10, 0)),
        fin=instant(LUNDI, time(10, 30)),
        reference_id=reference_id,
    )


def test_annuler_une_reference_inconnue_ne_fait_rien():
    agenda = AgendaMemoire()
    assert not agenda.annuler("rdv-fantome")


def test_un_rendez_vous_annule_reste_visible():
    """Le secretariat et le rapport mensuel ont besoin de le voir."""
    agenda = AgendaMemoire()
    agenda.reserver(_occupation())
    assert agenda.annuler("rdv-1")
    restantes = agenda.toutes("ens-1")
    assert len(restantes) == 1
    assert restantes[0].statut is StatutRendezVous.ANNULE


def test_les_occupations_sont_filtrees_par_ressource_et_par_periode():
    agenda = AgendaMemoire()
    agenda.reserver(_occupation())
    dans_la_fenetre = agenda.occupations(
        "ens-1", instant(LUNDI, time(9, 0)), instant(LUNDI, time(11, 0))
    )
    hors_fenetre = agenda.occupations(
        "ens-1", instant(LUNDI, time(14, 0)), instant(LUNDI, time(15, 0))
    )
    autre_ressource = agenda.occupations(
        "ens-2", instant(LUNDI, time(9, 0)), instant(LUNDI, time(11, 0))
    )
    assert len(dans_la_fenetre) == 1
    assert hors_fenetre == []
    assert autre_ressource == []


def test_reserver_deux_fois_la_meme_reference_deplace_le_rendez_vous():
    """Un parent qui deplace son rendez-vous ne cree pas un doublon."""
    agenda = AgendaMemoire()
    agenda.reserver(_occupation())
    deplace = Occupation(
        ressource_id="ens-1",
        debut=instant(LUNDI, time(11, 0)),
        fin=instant(LUNDI, time(11, 30)),
        reference_id="rdv-1",
    )
    agenda.reserver(deplace)
    assert [o.debut.time() for o in agenda.toutes("ens-1")] == [time(11, 0)]
