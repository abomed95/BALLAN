"""Prise de rendez-vous scolaire (lot 3) — perimetre, ressource, conflits."""

from __future__ import annotations

import inspect
import itertools
from datetime import date, datetime, time, timedelta

import pytest

from core.errors import (
    AccesRefuse,
    ActeurNonAutorise,
    CreneauIndisponible,
    ErreurConfiguration,
    HorsOuverture,
)
from core.models.enums import Acteur, StatutRendezVous
from tests import fixtures_ecole as fx
from verticals.school.calendar_school import PeriodeNonScolaire
from verticals.school.configuration import DepotConfigurationMemoire
from verticals.school.family import ServiceFamille
from verticals.school.models import DestinataireRendezVous, MotifRendezVous
from verticals.school.rendez_vous import DepotRendezVousMemoire, ServiceRendezVous
from verticals.school.rules import PERIMETRE_VIDE

TZ = fx.ecole().tz
#: Dimanche 21 septembre 2025, 09:00 — veille du lundi de Mme B.
MAINTENANT = datetime(2025, 9, 21, 9, 0, tzinfo=TZ)
LUNDI = date(2025, 9, 22)


def a(jour: date, heure: time) -> datetime:
    return datetime.combine(jour, heure, tzinfo=TZ)


@pytest.fixture
def depot_ecole():
    return fx.depot()


@pytest.fixture
def famille(depot_ecole):
    return ServiceFamille(depot_ecole)


@pytest.fixture
def depot_rdv():
    return DepotRendezVousMemoire()


@pytest.fixture
def service(famille, depot_rdv):
    compteur = itertools.count(1)
    return ServiceRendezVous(
        fx.ETAB,
        famille,
        DepotConfigurationMemoire(fx.configuration()),
        depot_rdv,
        generer_id=lambda: f"rdv-{next(compteur)}",
    )


@pytest.fixture
def halima(famille):
    return famille.perimetre_du_numero(fx.ETAB, fx.NUM_HALIMA)


@pytest.fixture
def ismail(famille):
    return famille.perimetre_du_numero(fx.ETAB, fx.NUM_ISMAIL)


@pytest.fixture
def fatouma(famille):
    return famille.perimetre_du_numero(fx.ETAB, fx.NUM_FATOUMA)


# -- motifs et ressource ----------------------------------------------


def test_seuls_les_motifs_actifs_sont_proposes_dans_l_ordre_de_l_ecole(service):
    assert [m.id for m in service.motifs()] == ["motif-suivi", "motif-direction"]


def test_un_motif_enseignant_va_a_l_enseignant_principal_de_la_classe(service, halima):
    assert service.ressource_pour(halima, fx.AHMED.id, "motif-suivi") == "ens-b"


def test_un_motif_direction_va_a_la_ressource_designee(service, halima):
    assert service.ressource_pour(halima, fx.AHMED.id, "motif-direction") == "direction"


def test_un_motif_direction_sans_ressource_est_refuse_a_la_construction():
    with pytest.raises(ErreurConfiguration):
        MotifRendezVous(
            id="m",
            etablissement_id=fx.ETAB,
            libelle_i18n={"fr": "x"},
            destinataire=DestinataireRendezVous.DIRECTION,
        )


def test_un_motif_inactif_ne_se_reserve_pas(service, halima):
    with pytest.raises(ErreurConfiguration):
        service.proposer(halima, fx.AHMED.id, "motif-ancien", MAINTENANT)


# -- propositions -----------------------------------------------------


def test_les_propositions_tombent_dans_les_disponibilites_de_l_enseignant(service, halima):
    propositions = service.proposer(halima, fx.AHMED.id, "motif-suivi", MAINTENANT)
    assert len(propositions) == 3
    for p in propositions:
        assert p.ressource_id == "ens-b"
        assert p.ressource_libelle == "Mme B."
        local = p.creneau.debut.astimezone(TZ)
        assert local.weekday() == 0  # lundi
        assert time(8, 0) <= local.time() and p.creneau.fin.astimezone(TZ).time() <= time(10, 0)


def test_les_propositions_privilegient_des_jours_distincts(service, halima):
    propositions = service.proposer(halima, fx.AHMED.id, "motif-suivi", MAINTENANT)
    jours = {p.creneau.debut.date() for p in propositions}
    assert len(jours) == 3


def test_aucune_proposition_pendant_les_vacances(service, halima):
    veille_vacances = datetime(2025, 12, 12, 9, 0, tzinfo=TZ)
    propositions = service.proposer(
        halima, fx.AHMED.id, "motif-suivi", veille_vacances, nombre=10, horizon_jours=25
    )
    vacances = (date(2025, 12, 14), date(2026, 1, 3))
    assert propositions
    for p in propositions:
        assert not vacances[0] <= p.creneau.debut.date() <= vacances[1]


def test_un_creneau_pris_n_est_plus_propose(service, halima, ismail):
    premier = service.proposer(halima, fx.AHMED.id, "motif-suivi", MAINTENANT, nombre=1)[0]
    service.reserver(halima, fx.AHMED.id, "motif-suivi", premier.creneau.debut, MAINTENANT)
    suivants = service.proposer(halima, fx.SAGAL.id, "motif-suivi", MAINTENANT, nombre=20)
    assert all(p.creneau.debut != premier.creneau.debut for p in suivants)


def test_proposer_hors_perimetre_est_refuse(service, ismail):
    with pytest.raises(AccesRefuse):
        service.proposer(ismail, fx.AHMED.id, "motif-suivi", MAINTENANT)


def test_proposer_pour_un_perimetre_vide_est_refuse(service):
    with pytest.raises(AccesRefuse):
        service.proposer(PERIMETRE_VIDE, fx.AHMED.id, "motif-suivi", MAINTENANT)


def test_un_eleve_sorti_ne_recoit_pas_de_proposition(famille, service):
    robleh = famille.perimetre_du_numero(fx.ETAB, fx.NUM_ANCIENNE_FAMILLE)
    # Le perimetre de Robleh est vide car son seul enfant est sorti.
    with pytest.raises(AccesRefuse):
        service.proposer(robleh, fx.IDRIS.id, "motif-suivi", MAINTENANT)


# -- reservation ------------------------------------------------------


def test_reserver_un_creneau_libre(service, halima):
    rdv = service.reserver(halima, fx.AHMED.id, "motif-suivi", a(LUNDI, time(8, 0)), MAINTENANT)
    assert rdv.statut is StatutRendezVous.CONFIRME
    assert rdv.ressource_id == "ens-b"
    assert rdv.fin - rdv.debut == timedelta(minutes=30)
    assert rdv.parent_id == "pa-halima"
    assert rdv.contact_id == "ct-halima"
    assert rdv.cree_par is Acteur.AGENT


def test_deux_parents_ne_peuvent_pas_prendre_le_meme_creneau(service, halima, famille):
    service.reserver(halima, fx.AHMED.id, "motif-suivi", a(LUNDI, time(8, 0)), MAINTENANT)
    with pytest.raises(CreneauIndisponible):
        # Autre enfant de la meme classe : meme enseignante, meme creneau.
        service.reserver(halima, fx.AHMED.id, "motif-suivi", a(LUNDI, time(8, 15)), MAINTENANT)


def test_reserver_hors_disponibilite_est_refuse(service, halima):
    with pytest.raises(HorsOuverture):
        service.reserver(halima, fx.AHMED.id, "motif-suivi", a(LUNDI, time(14, 0)), MAINTENANT)


def test_reserver_pendant_les_vacances_est_refuse(service, halima):
    lundi_vacances = date(2025, 12, 15)
    with pytest.raises(PeriodeNonScolaire):
        service.reserver(
            halima,
            fx.AHMED.id,
            "motif-suivi",
            a(lundi_vacances, time(8, 0)),
            datetime(2025, 12, 1, 9, 0, tzinfo=TZ),
        )


def test_reserver_dans_le_passe_est_refuse(service, halima):
    with pytest.raises(CreneauIndisponible):
        service.reserver(
            halima,
            fx.AHMED.id,
            "motif-suivi",
            a(LUNDI, time(8, 0)),
            a(LUNDI, time(9, 0)),
        )


def test_reserver_pour_l_enfant_d_une_autre_famille_est_refuse(service, ismail):
    with pytest.raises(AccesRefuse):
        service.reserver(ismail, fx.AHMED.id, "motif-suivi", a(LUNDI, time(8, 0)), MAINTENANT)


# -- consultation et annulation ---------------------------------------


def test_un_parent_ne_voit_que_les_rendez_vous_de_ses_enfants(service, halima, ismail):
    service.reserver(halima, fx.AHMED.id, "motif-suivi", a(LUNDI, time(8, 0)), MAINTENANT)
    assert len(service.a_venir(halima, MAINTENANT)) == 1
    assert service.a_venir(ismail, MAINTENANT) == []
    assert service.a_venir(PERIMETRE_VIDE, MAINTENANT) == []


def test_un_coparent_voit_le_rendez_vous_pris_par_l_autre(service, ismail, fatouma):
    rdv = service.reserver(
        ismail, fx.MOUNA.id, "motif-direction", a(date(2025, 9, 24), time(10, 0)), MAINTENANT
    )
    assert [r.id for r in service.a_venir(fatouma, MAINTENANT)] == [rdv.id]


def test_annuler_libere_le_creneau(service, halima):
    rdv = service.reserver(halima, fx.AHMED.id, "motif-suivi", a(LUNDI, time(8, 0)), MAINTENANT)
    annule = service.annuler(halima, rdv.id)
    assert annule.statut is StatutRendezVous.ANNULE
    assert service.a_venir(halima, MAINTENANT) == []
    service.reserver(halima, fx.SAGAL.id, "motif-direction", a(date(2025, 9, 24), time(10, 0)),
                     MAINTENANT)
    service.reserver(halima, fx.AHMED.id, "motif-suivi", a(LUNDI, time(8, 0)), MAINTENANT)


def test_annuler_le_rendez_vous_d_une_autre_famille_est_refuse(service, halima, ismail):
    rdv = service.reserver(halima, fx.AHMED.id, "motif-suivi", a(LUNDI, time(8, 0)), MAINTENANT)
    with pytest.raises(AccesRefuse) as inexistant:
        service.annuler(ismail, "rdv-qui-n-existe-pas")
    with pytest.raises(AccesRefuse) as etranger:
        service.annuler(ismail, rdv.id)
    # Meme reponse dans les deux cas : on n'apprend pas qu'un rendez-vous existe.
    assert str(inexistant.value) == str(etranger.value)


# -- secretariat ------------------------------------------------------


def test_l_agenda_de_l_ecole_est_reserve_au_secretariat(service, halima):
    service.reserver(halima, fx.AHMED.id, "motif-suivi", a(LUNDI, time(8, 0)), MAINTENANT)
    du, au = a(LUNDI, time(0, 0)), a(LUNDI, time(23, 0))
    with pytest.raises(ActeurNonAutorise):
        service.sur_periode(Acteur.AGENT, du, au)
    assert len(service.sur_periode(Acteur.SECRETARIAT, du, au)) == 1


def test_le_secretariat_peut_annuler_mais_pas_l_agent(service, halima):
    rdv = service.reserver(halima, fx.AHMED.id, "motif-suivi", a(LUNDI, time(8, 0)), MAINTENANT)
    with pytest.raises(ActeurNonAutorise):
        service.annuler_par_l_ecole(Acteur.AGENT, rdv.id)
    assert service.annuler_par_l_ecole(Acteur.SECRETARIAT, rdv.id).statut is StatutRendezVous.ANNULE


# -- garde structurelle -----------------------------------------------


def test_aucune_methode_parent_ne_touche_un_eleve_sans_perimetre():
    """Meme garde que pour ``ServiceFamille`` (test_cloisonnement_familial.py)."""
    for nom, methode in inspect.getmembers(ServiceRendezVous, inspect.isfunction):
        if nom.startswith("_"):
            continue
        parametres = set(inspect.signature(methode).parameters)
        if parametres & {"eleve_id", "rdv_id"}:
            assert "perimetre" in parametres or "acteur" in parametres, (
                f"ServiceRendezVous.{nom} touche un eleve sans perimetre ni acteur"
            )
