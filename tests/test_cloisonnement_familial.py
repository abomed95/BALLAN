"""Cloisonnement familial — NE JAMAIS RETIRER (BALLAN.md §8.2, §10, §11).

« C'est le risque technique le plus serieux du produit : divulguer a un
numero des informations sur un enfant qui n'est pas le sien. »

Ce fichier est la seule chose qui garantit que la regle tient encore apres
six mois de modifications. Le lot 1 n'est pas termine tant qu'il n'est pas
vert, et aucun lot ulterieur ne le fait passer.

Criteres §12 couverts ici :

* un numero rattache a deux enfants declenche la desambiguisation,
  systematiquement ;
* un numero non rattache n'obtient aucune information nominative, y compris
  implicite.
"""

from __future__ import annotations

import dataclasses
import inspect

import pytest

from core.errors import AccesRefuse, ActeurNonAutorise
from core.models import Acteur, Contact, Langue
from tests import fixtures_ecole as fx
from verticals.school.family import ServiceFamille, StatutIdentification
from verticals.school.models import LienParentEleve, Parent
from verticals.school.rules import PERIMETRE_VIDE, Perimetre, message_acces_refuse


@pytest.fixture
def depot():
    return fx.depot()


@pytest.fixture
def service(depot):
    return ServiceFamille(depot)


@pytest.fixture
def halima(service) -> Perimetre:
    """Mere de trois enfants dans trois classes differentes."""
    return service.perimetre_du_numero(fx.ETAB, fx.NUM_HALIMA)


@pytest.fixture
def ismail(service) -> Perimetre:
    """Pere d'un seul enfant, dans une autre famille."""
    return service.perimetre_du_numero(fx.ETAB, fx.NUM_ISMAIL)


# =====================================================================
# 1. Identification : combien d'enfants derriere ce numero ?
# =====================================================================


def test_un_parent_de_trois_enfants_dans_trois_classes(service):
    """§13, premier jeu de test."""
    identification = service.identifier(fx.ETAB, fx.NUM_HALIMA)
    assert identification.statut is StatutIdentification.MULTIPLE
    assert identification.exige_desambiguisation
    assert [e.prenom for e in identification.eleves] == ["Ahmed", "Nasra", "Sagal"]
    assert len({e.classe_id for e in identification.eleves}) == 3


def test_un_parent_d_un_seul_enfant_ne_declenche_pas_de_desambiguisation(service):
    identification = service.identifier(fx.ETAB, fx.NUM_ISMAIL)
    assert identification.statut is StatutIdentification.UNIQUE
    assert not identification.exige_desambiguisation
    assert [e.prenom for e in identification.eleves] == ["Mouna"]


def test_la_desambiguisation_est_systematique_quelle_que_soit_l_ecriture(service):
    """Un numero mal ecrit ne doit pas court-circuiter la regle."""
    for ecriture in ("+25377111111", "77111111", "0025377111111", "77 11 11 11"):
        identification = service.identifier(fx.ETAB, ecriture)
        assert identification.statut is StatutIdentification.MULTIPLE, ecriture
        assert len(identification.eleves) == 3, ecriture


def test_les_deux_parents_d_un_meme_enfant_y_ont_acces(service):
    for numero in (fx.NUM_ISMAIL, fx.NUM_FATOUMA):
        identification = service.identifier(fx.ETAB, numero)
        assert identification.statut is StatutIdentification.UNIQUE
        assert identification.eleves[0].id == fx.MOUNA.id


# =====================================================================
# 2. Un numero non rattache n'obtient rien
# =====================================================================


def test_un_numero_inconnu_n_obtient_aucune_donnee(service):
    identification = service.identifier(fx.ETAB, fx.NUM_INCONNU)
    assert identification.statut is StatutIdentification.INCONNU
    assert identification.eleves == ()
    assert identification.perimetre is PERIMETRE_VIDE
    assert identification.doit_escalader


def test_un_numero_inconnu_n_obtient_pas_confirmation_qu_un_eleve_est_inscrit(service):
    """Le coeur du §8.2 : meme une confirmation implicite est une fuite.

    « Ce numero ne correspond a aucun eleve » et « cet eleve n'est pas le
    votre » doivent etre indiscernables de l'exterieur.
    """
    eleve_existant = fx.AHMED.id
    eleve_imaginaire = "el-inexistant"

    with pytest.raises(AccesRefuse) as sur_existant:
        service.eleve(PERIMETRE_VIDE, eleve_existant)
    with pytest.raises(AccesRefuse) as sur_imaginaire:
        service.eleve(PERIMETRE_VIDE, eleve_imaginaire)

    assert type(sur_existant.value) is type(sur_imaginaire.value)
    assert str(sur_existant.value) == str(sur_imaginaire.value)


def test_un_contact_connu_mais_rattache_a_aucun_eleve_est_traite_comme_inconnu(service):
    """Sinon, un numero connu deviendrait un oracle : « je vous connais,
    mais vous n'avez pas d'enfant ici » en dit deja trop."""
    identification = service.identifier(fx.ETAB, fx.NUM_SANS_ENFANT)
    assert identification.statut is StatutIdentification.INCONNU
    assert identification.eleves == ()
    assert identification.doit_escalader


def test_une_famille_dont_l_enfant_est_sorti_n_ouvre_plus_la_conversation(service):
    identification = service.identifier(fx.ETAB, fx.NUM_ANCIENNE_FAMILLE)
    assert identification.statut is StatutIdentification.INCONNU
    assert identification.eleves == ()


def test_un_numero_illisible_se_comporte_comme_un_numero_inconnu(service):
    for saisie in ("", "allo", "12", "+33612345678"):
        assert service.perimetre_du_numero(fx.ETAB, saisie) is PERIMETRE_VIDE


def test_le_message_de_refus_ne_nomme_rien_et_existe_dans_les_quatre_langues():
    interdits = ("Ahmed", "Sagal", "Nasra", "Mouna", "CM1", "CE2", "Ali", "Osman")
    for langue in Langue:
        message = message_acces_refuse(langue)
        assert message
        for mot in interdits:
            assert mot not in message


def test_l_erreur_d_acces_ne_transporte_aucune_identite(service, halima):
    """Les journaux d'un produit qui traite des mineurs restent anonymes."""
    with pytest.raises(AccesRefuse) as erreur:
        service.eleve(halima, fx.MOUNA.id)
    trace = f"{erreur.value} {erreur.value.motif_technique}"
    for mot in ("Mouna", "Osman", fx.MOUNA.identifiant_interne):
        assert mot not in trace


# =====================================================================
# 3. Etancheite entre familles
# =====================================================================


def test_une_famille_ne_voit_pas_l_enfant_d_une_autre(halima, ismail, service):
    assert not halima.couvre(fx.MOUNA.id)
    assert not ismail.couvre(fx.AHMED.id)
    with pytest.raises(AccesRefuse):
        service.eleve(halima, fx.MOUNA.id)
    with pytest.raises(AccesRefuse):
        service.eleve(ismail, fx.AHMED.id)


def test_partager_une_classe_ne_donne_aucun_droit(service, ismail):
    """Ahmed et Mouna sont tous les deux en CM1 B.

    C'est le piege le plus naturel : filtrer par classe au lieu de filtrer
    par lien familial donnerait acces a vingt-six eleves.
    """
    assert fx.AHMED.classe_id == fx.MOUNA.classe_id
    with pytest.raises(AccesRefuse):
        service.eleve(ismail, fx.AHMED.id)


@pytest.mark.parametrize(
    "methode",
    ["eleve", "classe_de", "niveau_de", "enseignant_principal_de", "famille_de", "coparents"],
)
def test_toutes_les_lectures_refusent_un_eleve_hors_perimetre(service, ismail, methode):
    """Une seule methode qui oublierait la garde suffirait a perdre le client."""
    with pytest.raises(AccesRefuse):
        getattr(service, methode)(ismail, fx.AHMED.id)


@pytest.mark.parametrize(
    "methode",
    ["eleve", "classe_de", "niveau_de", "enseignant_principal_de", "famille_de", "coparents"],
)
def test_toutes_les_lectures_refusent_un_perimetre_vide(service, methode):
    with pytest.raises(AccesRefuse):
        getattr(service, methode)(PERIMETRE_VIDE, fx.AHMED.id)


def test_un_parent_legitime_obtient_bien_ce_qui_le_concerne(service, halima):
    assert service.eleve(halima, fx.AHMED.id).prenom == "Ahmed"
    assert service.classe_de(halima, fx.AHMED.id).libelle == "CM1 B"
    assert service.niveau_de(halima, fx.AHMED.id).libelle_i18n["fr"] == "CM1"
    assert service.enseignant_principal_de(halima, fx.AHMED.id).nom == "Mme B."
    assert service.famille_de(halima, fx.AHMED.id).nom_affiche == "Famille Ali"


def test_le_perimetre_ne_contient_que_les_eleves_relies(halima):
    assert halima.eleve_ids == {fx.AHMED.id, fx.SAGAL.id, fx.NASRA.id}


def test_un_numero_connu_d_une_autre_ecole_n_ouvre_rien(service):
    """Le meme numero peut exister dans deux etablissements clients."""
    assert service.perimetre_du_numero("etab-2", fx.NUM_HALIMA) is PERIMETRE_VIDE


# =====================================================================
# 4. Le perimetre se recalcule a chaque requete
# =====================================================================


def test_un_lien_retire_ferme_l_acces_des_la_requete_suivante(depot, service):
    """Le perimetre n'est pas un jeton : il n'est ni mis en cache, ni
    transporte depuis le client."""
    avant = service.perimetre_du_numero(fx.ETAB, fx.NUM_HALIMA)
    assert avant.couvre(fx.NASRA.id)

    depot.liens = [
        lien
        for lien in depot.liens
        if not (lien.parent_id == "pa-halima" and lien.eleve_id == fx.NASRA.id)
    ]

    apres = service.perimetre_du_numero(fx.ETAB, fx.NUM_HALIMA)
    assert not apres.couvre(fx.NASRA.id)
    with pytest.raises(AccesRefuse):
        service.eleve(apres, fx.NASRA.id)


def test_un_eleve_sorti_reste_dans_le_perimetre_mais_pas_dans_les_propositions(service):
    """Le lien survit au depart de l'eleve, la conversation non.

    Le lien doit subsister : c'est lui qui permet au secretariat de traiter
    un export ou une suppression de donnees de famille (§8.3). Mais
    l'identification conversationnelle, elle, ne s'ouvre plus.
    """
    perimetre = service.perimetre_du_contact(fx.ETAB, "ct-robleh")
    assert perimetre.couvre(fx.IDRIS.id)
    assert [e.prenom for e in service.eleves(perimetre)] == ["Idris"]
    assert service.eleves_inscrits(perimetre) == ()
    assert service.identifier(fx.ETAB, fx.NUM_ANCIENNE_FAMILLE).statut is (
        StatutIdentification.INCONNU
    )


# =====================================================================
# 5. Ce que l'agent n'a pas le droit de faire
# =====================================================================


def test_l_agent_ne_peut_pas_rattacher_un_contact(service):
    """§8.2 : « Un changement de numero se fait uniquement par le
    secretariat, jamais par l'agent. »"""
    parent = Parent(id="pa-nouveau", famille_id="fam-ali")
    contact = Contact(id="ct-nouveau", etablissement_id=fx.ETAB, numero="+25377000000")
    with pytest.raises(ActeurNonAutorise):
        service.rattacher_contact(Acteur.AGENT, parent, contact)


def test_le_secretariat_peut_rattacher_un_contact(service, depot):
    parent = Parent(id="pa-nouveau", famille_id="fam-ali")
    depot.enregistrer_parent(parent)
    contact = Contact(id="ct-nouveau", etablissement_id=fx.ETAB, numero="+25377000000")
    rattache = service.rattacher_contact(Acteur.SECRETARIAT, parent, contact)
    assert rattache.contact_id == "ct-nouveau"


def test_l_agent_ne_peut_pas_changer_un_numero(service, depot):
    contact = depot.contact("ct-halima")
    with pytest.raises(ActeurNonAutorise):
        service.changer_numero(Acteur.AGENT, contact, "+25377888888")


def test_l_agent_ne_peut_pas_modifier_un_lien_parent_eleve(service):
    with pytest.raises(ActeurNonAutorise):
        service.definir_lien(
            Acteur.AGENT, LienParentEleve(parent_id="pa-ismail", eleve_id=fx.AHMED.id)
        )


def test_l_agent_ne_peut_pas_lire_l_autorisation_de_recuperer(service):
    """§8.2 : les situations de garde sont escaladees, jamais traitees.

    Il n'existe donc aucun chemin de lecture pour l'agent, meme avec un
    perimetre valide.
    """
    with pytest.raises(ActeurNonAutorise):
        service.autorisation_de_recuperer(Acteur.AGENT, "pa-fatouma", fx.MOUNA.id)


def test_le_secretariat_lit_l_autorisation_de_recuperer(service):
    assert service.autorisation_de_recuperer(Acteur.SECRETARIAT, "pa-ismail", fx.MOUNA.id)
    assert not service.autorisation_de_recuperer(
        Acteur.SECRETARIAT, "pa-fatouma", fx.MOUNA.id
    )


# =====================================================================
# 6. Garde structurelle : aucune porte derobee ajoutee par inadvertance
# =====================================================================


def test_aucune_lecture_d_eleve_ne_se_passe_de_perimetre():
    """Verifie la forme des signatures, pas seulement le comportement.

    Une methode ajoutee demain avec ``eleve_id`` mais sans ``perimetre``
    serait un contournement du cloisonnement. Ce test la refuse avant
    qu'elle n'atteigne la production.
    """
    reservees_au_secretariat = {
        "autorisation_de_recuperer",  # exige un Acteur habilite, pas un perimetre
    }
    for nom, methode in inspect.getmembers(ServiceFamille, inspect.isfunction):
        if nom.startswith("_") or nom in reservees_au_secretariat:
            continue
        parametres = set(inspect.signature(methode).parameters)
        if "eleve_id" in parametres:
            assert "perimetre" in parametres, (
                f"ServiceFamille.{nom} lit un eleve sans exiger de perimetre"
            )


def test_le_perimetre_vide_est_vraiment_vide():
    assert not PERIMETRE_VIDE.est_rattache
    assert PERIMETRE_VIDE.eleve_ids == frozenset()
    assert PERIMETRE_VIDE.parent_ids == frozenset()
    assert PERIMETRE_VIDE.contact_id is None
    assert not PERIMETRE_VIDE.couvre(fx.AHMED.id)


def test_un_perimetre_est_immuable(halima):
    """Personne ne doit pouvoir elargir un perimetre apres coup."""
    with pytest.raises(dataclasses.FrozenInstanceError):
        halima.eleve_ids = frozenset({fx.MOUNA.id})
