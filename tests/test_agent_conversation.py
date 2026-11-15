"""Agent conversationnel : parcours de bout en bout, en memoire.

Chaque test rejoue une conversation WhatsApp reelle : un numero, des
messages, des reponses. Les garanties de cloisonnement sont reverifiees ici
au niveau du dialogue, la ou un defaut serait visible d'un parent.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timedelta

import pytest

from application.conversation import Agent, DepotConversationMemoire, Etape, normaliser_saisie
from core.escalade import DepotEscaladeMemoire, MotifEscalade
from core.i18n.catalogue import catalogue
from core.models.enums import Langue, StatutRendezVous
from tests import fixtures_ecole as fx
from verticals.school.configuration import DepotConfigurationMemoire
from verticals.school.family import ServiceFamille
from verticals.school.rendez_vous import DepotRendezVousMemoire, ServiceRendezVous

TZ = fx.ecole().tz
MAINTENANT = datetime(2025, 9, 21, 9, 0, tzinfo=TZ)


class Banc:
    """Une ecole en memoire et un agent branche dessus."""

    def __init__(self) -> None:
        compteur = itertools.count(1)
        self.depot = fx.depot()
        self.famille = ServiceFamille(self.depot)
        self.rdv_depot = DepotRendezVousMemoire()
        self.rdv = ServiceRendezVous(
            fx.ETAB,
            self.famille,
            DepotConfigurationMemoire(fx.configuration()),
            self.rdv_depot,
            generer_id=lambda: f"rdv-{next(compteur)}",
        )
        self.conversations = DepotConversationMemoire()
        self.escalades = DepotEscaladeMemoire()
        self.notifiees = []
        self.agent = Agent(
            fx.ETAB,
            self.famille,
            self.rdv,
            self.depot,
            self.conversations,
            self.escalades,
            notifier_escalade=self.notifiees.append,
        )
        self.horloge = MAINTENANT

    def dire(self, numero: str, texte: str, est_texte: bool = True) -> str:
        self.horloge += timedelta(seconds=30)
        return "\n---\n".join(self.agent.traiter(numero, texte, self.horloge, est_texte))

    def etape(self, numero: str) -> Etape:
        etat = self.conversations.charger(fx.ETAB, numero)
        return etat.etape if etat else Etape.MENU


@pytest.fixture
def banc() -> Banc:
    return Banc()


def fr(cle: str, **params) -> str:
    return catalogue().t(cle, Langue.FR, **params)


# -- accueil et identification ----------------------------------------


def test_un_parent_connu_recoit_le_menu_dans_sa_langue(banc):
    reponse = banc.dire(fx.NUM_ISMAIL, "Bonjour")
    assert "Ecole Al-Nour" in reponse
    assert "1." in reponse and "4." in reponse
    # Halima a choisi le somali a l'inscription.
    assert catalogue().t("agent.menu", Langue.SO) in banc.dire(fx.NUM_HALIMA, "salam")


def test_un_numero_inconnu_ne_recoit_que_le_refus_et_part_en_escalade(banc):
    reponse = banc.dire(fx.NUM_INCONNU, "Bonjour, je suis la maman d'Ahmed Ali")
    assert reponse == fr("acces.refuse")
    assert "Ahmed" not in reponse
    ouvertes = banc.escalades.ouvertes(fx.ETAB)
    assert [e.motif for e in ouvertes] == [MotifEscalade.NUMERO_INCONNU]
    assert ouvertes[0].numero == fx.NUM_INCONNU
    assert banc.notifiees == ouvertes


def test_un_inconnu_qui_insiste_ne_cree_pas_dix_escalades(banc):
    for _ in range(5):
        banc.dire(fx.NUM_INCONNU, "1")
    assert len(banc.escalades.ouvertes(fx.ETAB)) == 1


def test_un_inconnu_n_obtient_rien_meme_en_suivant_le_menu(banc):
    for message in ("1", "2", "1", "1"):
        assert banc.dire(fx.NUM_INCONNU, message) == fr("acces.refuse")


def test_un_contact_sans_enfant_inscrit_est_traite_comme_un_inconnu(banc):
    assert banc.dire(fx.NUM_ANCIENNE_FAMILLE, "1") == fr("acces.refuse")
    assert banc.dire(fx.NUM_SANS_ENFANT, "1") == fr("acces.refuse")


def test_un_numero_ecrit_autrement_est_reconnu(banc):
    assert "Ecole Al-Nour" in banc.dire("00253 77 22 22 22", "menu")


def test_un_numero_illisible_recoit_le_refus(banc):
    assert banc.dire("n'importe quoi", "1") == fr("acces.refuse")


# -- prise de rendez-vous de bout en bout -----------------------------


def test_parcours_complet_un_seul_enfant(banc):
    banc.dire(fx.NUM_ISMAIL, "bonjour")
    motifs = banc.dire(fx.NUM_ISMAIL, "1")
    assert "Mouna" in motifs and "Suivi de la scolarite" in motifs
    assert "Ancien motif" not in motifs
    creneaux = banc.dire(fx.NUM_ISMAIL, "1")
    assert "Mme B." in creneaux  # enseignante principale du CM1 B, classe de Mouna
    assert "lundi" in creneaux
    confirmation = banc.dire(fx.NUM_ISMAIL, "1")
    assert "Mouna" in confirmation and "1. Confirmer" in confirmation
    confirme = banc.dire(fx.NUM_ISMAIL, "1")
    assert confirme.startswith("C'est confirmé")
    rdvs = banc.rdv_depot.a_venir([fx.MOUNA.id], MAINTENANT)
    assert len(rdvs) == 1 and rdvs[0].statut is StatutRendezVous.CONFIRME
    assert rdvs[0].contact_id == "ct-ismail"
    assert banc.etape(fx.NUM_ISMAIL) is Etape.MENU


def test_un_parent_de_trois_enfants_choisit_d_abord_l_enfant(banc):
    banc.dire(fx.NUM_HALIMA, "langue")
    banc.dire(fx.NUM_HALIMA, "1")  # francais
    liste = banc.dire(fx.NUM_HALIMA, "1")
    for prenom in ("Ahmed", "Sagal", "Nasra"):
        assert prenom in liste
    assert "CM1 B" in liste
    assert "Mouna" not in liste
    assert banc.etape(fx.NUM_HALIMA) is Etape.CHOIX_ENFANT


def test_un_motif_direction_propose_les_creneaux_de_la_direction(banc):
    banc.dire(fx.NUM_ISMAIL, "1")
    creneaux = banc.dire(fx.NUM_ISMAIL, "2")
    assert "Direction" in creneaux and "mercredi" in creneaux


def test_choisir_un_autre_creneau_a_la_confirmation(banc):
    banc.dire(fx.NUM_ISMAIL, "1")
    banc.dire(fx.NUM_ISMAIL, "1")
    banc.dire(fx.NUM_ISMAIL, "1")
    assert banc.etape(fx.NUM_ISMAIL) is Etape.CONFIRMATION
    banc.dire(fx.NUM_ISMAIL, "2")
    assert banc.etape(fx.NUM_ISMAIL) is Etape.CHOIX_CRENEAU


def test_un_creneau_pris_entre_temps_est_signale_et_d_autres_sont_proposes(banc):
    # Ismail et Fatouma visent le meme creneau pour Mouna.
    for numero in (fx.NUM_ISMAIL, fx.NUM_FATOUMA):
        banc.dire(numero, "menu")
        banc.dire(numero, "1")
        banc.dire(numero, "1")
        banc.dire(numero, "1")
    assert banc.dire(fx.NUM_ISMAIL, "1").startswith("C'est confirmé")
    reponse = banc.dire(fx.NUM_FATOUMA, "1")
    assert catalogue().t("agent.creneau_pris", Langue.AR) in reponse
    assert banc.etape(fx.NUM_FATOUMA) is Etape.CHOIX_CRENEAU
    assert len(banc.rdv_depot.a_venir([fx.MOUNA.id], MAINTENANT)) == 1


def test_une_reponse_hors_liste_redemande_sans_perdre_l_etape(banc):
    banc.dire(fx.NUM_ISMAIL, "1")
    banc.dire(fx.NUM_ISMAIL, "1")
    assert banc.dire(fx.NUM_ISMAIL, "7") == fr("agent.choix_invalide")
    assert banc.etape(fx.NUM_ISMAIL) is Etape.CHOIX_CRENEAU


def test_les_chiffres_arabes_sont_compris(banc):
    banc.dire(fx.NUM_ISMAIL, "١")
    assert banc.etape(fx.NUM_ISMAIL) is Etape.CHOIX_MOTIF


def test_zero_ramene_au_menu(banc):
    banc.dire(fx.NUM_ISMAIL, "1")
    banc.dire(fx.NUM_ISMAIL, "0")
    assert banc.etape(fx.NUM_ISMAIL) is Etape.MENU


def test_la_session_expire_apres_trente_minutes(banc):
    banc.dire(fx.NUM_ISMAIL, "1")
    banc.horloge += timedelta(minutes=45)
    # « 1 » est relu au menu : c'est une nouvelle demande de rendez-vous.
    banc.dire(fx.NUM_ISMAIL, "1")
    assert banc.etape(fx.NUM_ISMAIL) is Etape.CHOIX_MOTIF


# -- consultation et annulation ---------------------------------------


def _reserver_pour_mouna(banc):
    for message in ("menu", "1", "1", "1", "1"):
        banc.dire(fx.NUM_ISMAIL, message)


def test_annuler_un_rendez_vous(banc):
    _reserver_pour_mouna(banc)
    liste = banc.dire(fx.NUM_ISMAIL, "2")
    assert "Mouna" in liste
    assert "Annuler" in banc.dire(fx.NUM_ISMAIL, "1")
    assert "annulé" in banc.dire(fx.NUM_ISMAIL, "1")
    assert banc.rdv.a_venir(banc.famille.perimetre_du_numero(fx.ETAB, fx.NUM_ISMAIL),
                            banc.horloge) == []


def test_garder_un_rendez_vous(banc):
    _reserver_pour_mouna(banc)
    banc.dire(fx.NUM_ISMAIL, "2")
    banc.dire(fx.NUM_ISMAIL, "1")
    assert banc.dire(fx.NUM_ISMAIL, "2") == fr("agent.rdv_conserve")


def test_le_coparent_voit_et_peut_annuler(banc):
    _reserver_pour_mouna(banc)
    assert "Mouna" in banc.dire(fx.NUM_FATOUMA, "2")


def test_une_autre_famille_ne_voit_pas_le_rendez_vous(banc):
    _reserver_pour_mouna(banc)
    banc.dire(fx.NUM_HALIMA, "langue")
    banc.dire(fx.NUM_HALIMA, "1")
    reponse = banc.dire(fx.NUM_HALIMA, "2")
    assert "Mouna" not in reponse
    assert fr("agent.aucun_rdv") in reponse


def test_un_etat_falsifie_ne_donne_acces_a_rien(banc):
    """Meme si l'etat stocke pointait vers l'enfant d'une autre famille."""
    banc.dire(fx.NUM_ISMAIL, "1")
    etat = banc.conversations.charger(fx.ETAB, fx.NUM_ISMAIL)
    etat.eleve_id = fx.AHMED.id
    banc.conversations.enregistrer(fx.ETAB, fx.NUM_ISMAIL, etat)
    reponse = banc.dire(fx.NUM_ISMAIL, "1")
    assert reponse == fr("acces.refuse")
    assert "Ahmed" not in reponse
    assert banc.rdv_depot.a_venir([fx.AHMED.id], MAINTENANT) == []


# -- sujets interdits --------------------------------------------------


def test_une_question_de_notes_est_redirigee_vers_un_rendez_vous(banc):
    reponse = banc.dire(fx.NUM_ISMAIL, "Quelle est la moyenne de Mouna ?")
    assert reponse == fr("agent.sujet_resultats")
    assert banc.escalades.ouvertes(fx.ETAB) == []
    banc.dire(fx.NUM_ISMAIL, "1")
    assert banc.etape(fx.NUM_ISMAIL) is Etape.CHOIX_MOTIF


def test_une_question_de_garde_est_escaladee_sans_etre_traitee(banc):
    reponse = banc.dire(fx.NUM_ISMAIL, "Est-ce que son oncle peut venir chercher Mouna ?")
    assert reponse == fr("agent.sujet_escalade")
    assert [e.motif for e in banc.escalades.ouvertes(fx.ETAB)] == [MotifEscalade.SUJET_SENSIBLE]


def test_une_question_de_sante_est_escaladee(banc):
    banc.dire(fx.NUM_ISMAIL, "Mouna est malade")
    assert [e.motif for e in banc.escalades.ouvertes(fx.ETAB)] == [MotifEscalade.SUJET_SENSIBLE]


def test_un_sujet_interdit_en_cours_de_parcours_est_aussi_traite(banc):
    banc.dire(fx.NUM_ISMAIL, "1")
    assert banc.dire(fx.NUM_ISMAIL, "et ses notes ?") == fr("agent.sujet_resultats")


# -- secretariat, langue, consentement --------------------------------


def test_demander_le_secretariat_cree_une_escalade(banc):
    assert banc.dire(fx.NUM_ISMAIL, "3") == fr("escalade.transmis")
    assert [e.motif for e in banc.escalades.ouvertes(fx.ETAB)] == [MotifEscalade.DEMANDE_PARENT]


def test_changer_de_langue_est_memorise(banc):
    banc.dire(fx.NUM_ISMAIL, "4")
    reponse = banc.dire(fx.NUM_ISMAIL, "2")  # arabe, deuxieme langue active
    assert catalogue().t("agent.langue_changee", Langue.AR) in reponse
    assert banc.depot.contact("ct-ismail").langue_preferee is Langue.AR
    assert catalogue().t("agent.menu", Langue.AR) in banc.dire(fx.NUM_ISMAIL, "menu")


def test_stop_coupe_les_envois_et_start_les_retablit(banc):
    assert banc.depot.contact("ct-ismail").accepte_envois
    assert banc.dire(fx.NUM_ISMAIL, "STOP") == fr("consentement.stop")
    assert not banc.depot.contact("ct-ismail").accepte_envois
    assert banc.dire(fx.NUM_ISMAIL, "start") == fr("consentement.reprise")
    assert banc.depot.contact("ct-ismail").accepte_envois


def test_stop_d_un_inconnu_ne_revele_rien(banc):
    assert banc.dire(fx.NUM_INCONNU, "stop") == fr("consentement.stop")


def test_un_message_vocal_recoit_une_consigne(banc):
    assert banc.dire(fx.NUM_ISMAIL, "", est_texte=False) == fr("agent.message_non_texte")


def test_un_incident_technique_ne_laisse_pas_le_parent_sans_reponse(banc, monkeypatch):
    def panne(*args, **kwargs):
        raise RuntimeError("base indisponible")

    monkeypatch.setattr(banc.rdv, "proposer", panne)
    banc.dire(fx.NUM_ISMAIL, "1")
    assert banc.dire(fx.NUM_ISMAIL, "1") == fr("agent.incident")
    assert [e.motif for e in banc.escalades.ouvertes(fx.ETAB)] == [MotifEscalade.INCIDENT]


# -- normalisation -----------------------------------------------------


@pytest.mark.parametrize(
    ("brut", "attendu"),
    [("  Bonjour ! ", "bonjour"), ("MENU.", "menu"), ("٢", "2"), ("Arrêt", "arret")],
)
def test_normaliser_saisie(brut, attendu):
    assert normaliser_saisie(brut) == attendu
