"""Chaine complete sur un vrai PostgreSQL : migrations, import, adaptateurs, agent.

Ce que la suite memoire ne peut pas prouver : que les requetes SQL rendent
les memes objets que les depots memoire, que la contrainte d'exclusion
tranche une vraie course entre deux parents, et que le cloisonnement tient
avec de vrais uuid.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tests.integration.outils_pg import DSN, RAISON_SAUT, base_disponible, psql, valeurs

pytestmark = pytest.mark.skipif(not base_disponible(), reason=RAISON_SAUT)

if base_disponible():
    from application.conversation import Agent, Etape
    from application.importation import charger_fichiers, ecrire_postgres, identifiant
    from application.persistance.migrations import appliquer_migrations
    from application.persistance.postgres import (
        DedoublonnagePostgres,
        DepotConfigurationPostgres,
        DepotConversationPostgres,
        DepotEcolePostgres,
        DepotEscaladePostgres,
        DepotRendezVousPostgres,
        creer_pool,
    )
    from core.errors import AccesRefuse, CreneauIndisponible
    from core.escalade import MotifEscalade
    from core.models.enums import Acteur, StatutRendezVous
    from verticals.school.family import ServiceFamille, StatutIdentification
    from verticals.school.rendez_vous import ServiceRendezVous

RACINE = Path(__file__).resolve().parents[2]
EXEMPLES = RACINE / "exemples"
NUM_MERE_ALI = "+25377101010"
NUM_PERE_OSMAN = "+25377202020"
NUM_MERE_OSMAN = "+25377202021"
NUM_INCONNU = "+25377999999"
#: Dimanche 15 novembre 2026, 06:00 UTC (09:00 a Djibouti).
MAINTENANT = datetime(2026, 11, 15, 6, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def pool():
    reset = psql("DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;")
    assert reset.returncode == 0, reset.stderr
    assert appliquer_migrations(DSN) == [
        "0001_core", "0002_school", "0003_conversation",
    ]
    # Rejouer ne fait rien : chaque migration ne s'applique qu'une fois.
    assert appliquer_migrations(DSN) == []
    p = creer_pool(DSN, taille_max=4)
    yield p
    p.close()


@pytest.fixture(scope="module")
def donnees(pool):
    d = charger_fichiers(
        EXEMPLES / "ecole.exemple.json", EXEMPLES / "familles.exemple.csv", MAINTENANT
    )
    ecrire_postgres(DSN, d)
    return d


@pytest.fixture
def services(pool, donnees):
    psql("TRUNCATE rendez_vous, escalade, conversation, message_entrant;")
    etab = donnees.etablissement_id
    depot = DepotEcolePostgres(pool)
    famille = ServiceFamille(depot)
    rdv = ServiceRendezVous(
        etab, famille, DepotConfigurationPostgres(pool, duree_cache_s=0),
        DepotRendezVousPostgres(pool),
    )
    escalades = DepotEscaladePostgres(pool)
    agent = Agent(etab, famille, rdv, depot, DepotConversationPostgres(pool), escalades)
    return {"etab": etab, "depot": depot, "famille": famille, "rdv": rdv,
            "agent": agent, "escalades": escalades}


# -- migrations et import ---------------------------------------------


def test_les_migrations_sont_suivies(pool):
    assert valeurs("SELECT version FROM schema_migrations ORDER BY version") == [
        "0001_core", "0002_school", "0003_conversation",
    ]


def test_l_import_est_idempotent(donnees):
    avant = valeurs("SELECT count(*) FROM eleve UNION ALL SELECT count(*) FROM lien_parent_eleve")
    ecrire_postgres(DSN, donnees)
    apres = valeurs("SELECT count(*) FROM eleve UNION ALL SELECT count(*) FROM lien_parent_eleve")
    assert avant == apres == ["5", "9"]


def test_la_configuration_relue_de_la_base_est_complete(services, donnees):
    conf = services["rdv"].configuration()
    assert conf.etablissement.nom == "École Sahan"
    assert conf.annee.libelle == "2026-2027"
    assert len(conf.periodes) == 5
    assert [m.ordre for m in conf.motifs_actifs()] == [1, 2]
    assert conf.calendrier_scolaire().est_en_vacances(datetime(2026, 12, 20).date())


# -- cloisonnement avec de vrais uuid ---------------------------------


def test_identification_depuis_la_base(services):
    famille, etab = services["famille"], services["etab"]
    assert famille.identifier(etab, NUM_MERE_ALI).statut is StatutIdentification.MULTIPLE
    assert famille.identifier(etab, "77 20 20 20").statut is StatutIdentification.UNIQUE
    assert famille.identifier(etab, NUM_INCONNU).statut is StatutIdentification.INCONNU


def test_un_identifiant_malforme_est_un_refus_pas_une_erreur_sql(services):
    perimetre = services["famille"].perimetre_du_numero(services["etab"], NUM_MERE_ALI)
    with pytest.raises(AccesRefuse):
        services["famille"].eleve(perimetre, "pas-un-uuid' OR 1=1 --")
    with pytest.raises(AccesRefuse):
        services["rdv"].annuler(perimetre, "pas-un-uuid")


def test_l_eleve_d_une_autre_famille_est_refuse(services, donnees):
    osman = services["famille"].perimetre_du_numero(services["etab"], NUM_PERE_OSMAN)
    ahmed = identifiant(donnees.cle, "eleve", "2026-001")
    with pytest.raises(AccesRefuse):
        services["famille"].eleve(osman, ahmed)


def test_un_numero_retire_du_csv_perd_l_acces_au_reimport(services, donnees, tmp_path):
    csv = (EXEMPLES / "familles.exemple.csv").read_text(encoding="utf-8")
    csv = csv.replace("0025377202021", "77 40 40 40")  # la mere Osman change de numero
    fichier = tmp_path / "familles.csv"
    fichier.write_text(csv, encoding="utf-8")
    d = charger_fichiers(EXEMPLES / "ecole.exemple.json", fichier, MAINTENANT)
    ecrire_postgres(DSN, d)
    try:
        famille, etab = services["famille"], services["etab"]
        assert not famille.perimetre_du_numero(etab, NUM_MERE_OSMAN).est_rattache
        assert famille.perimetre_du_numero(etab, "+25377404040").est_rattache
    finally:
        ecrire_postgres(DSN, donnees)


def test_un_eleve_absent_du_csv_passe_sorti(services, donnees, tmp_path):
    lignes = (EXEMPLES / "familles.exemple.csv").read_text(encoding="utf-8").splitlines()
    fichier = tmp_path / "familles.csv"
    fichier.write_text("\n".join(x for x in lignes if "2026-005" not in x), encoding="utf-8")
    d = charger_fichiers(EXEMPLES / "ecole.exemple.json", fichier, MAINTENANT)
    resume = ecrire_postgres(DSN, d)
    try:
        assert resume["eleves_sortis"] == 1
        assert not services["famille"].identifier(services["etab"], "+25377303030").est_rattache
    finally:
        ecrire_postgres(DSN, donnees)


# -- rendez-vous et contrainte d'exclusion -----------------------------


def test_reservation_et_annulation_en_base(services, donnees):
    rdv, famille, etab = services["rdv"], services["famille"], services["etab"]
    perimetre = famille.perimetre_du_numero(etab, NUM_PERE_OSMAN)
    mouna = identifiant(donnees.cle, "eleve", "2026-004")
    motif = identifiant(donnees.cle, "motif", "suivi")
    proposition = rdv.proposer(perimetre, mouna, motif, MAINTENANT, nombre=1)[0]
    reserve = rdv.reserver(perimetre, mouna, motif, proposition.creneau.debut, MAINTENANT)
    coparent = famille.perimetre_du_numero(etab, NUM_MERE_OSMAN)
    assert [r.id for r in rdv.a_venir(coparent, MAINTENANT)] == [reserve.id]
    assert rdv.annuler(coparent, reserve.id).statut is StatutRendezVous.ANNULE
    assert len(rdv.sur_periode(Acteur.SECRETARIAT, MAINTENANT,
                               MAINTENANT + timedelta(days=30))) == 1


def test_deux_parents_au_meme_instant_un_seul_passe(services, donnees):
    """La vraie course : deux threads, deux connexions, un seul creneau."""
    rdv, famille, etab = services["rdv"], services["famille"], services["etab"]
    motif = identifiant(donnees.cle, "motif", "suivi")
    sagal = identifiant(donnees.cle, "eleve", "2026-002")  # CE1 A, Mme Aicha
    mouna = identifiant(donnees.cle, "eleve", "2026-004")  # CE1 A, Mme Aicha
    ali = famille.perimetre_du_numero(etab, NUM_MERE_ALI)
    osman = famille.perimetre_du_numero(etab, NUM_PERE_OSMAN)
    debut = rdv.proposer(ali, sagal, motif, MAINTENANT, nombre=1)[0].creneau.debut

    depart = threading.Barrier(2)
    resultats: list[str] = []

    def reserver(perimetre, eleve):
        depart.wait()
        try:
            rdv.reserver(perimetre, eleve, motif, debut, MAINTENANT)
            resultats.append("ok")
        except CreneauIndisponible:
            resultats.append("pris")

    fils = [threading.Thread(target=reserver, args=a) for a in ((ali, sagal), (osman, mouna))]
    for f in fils:
        f.start()
    for f in fils:
        f.join()
    assert sorted(resultats) == ["ok", "pris"]
    assert valeurs("SELECT count(*) FROM rendez_vous WHERE statut = 'confirme'") == ["1"]


# -- agent de bout en bout sur la base --------------------------------


def test_parcours_agent_sur_la_base(services):
    agent = services["agent"]
    t = MAINTENANT
    reponses = []
    for message in ("bonjour", "1", "1", "1", "1"):
        t += timedelta(seconds=20)
        reponses.append("\n".join(agent.traiter(NUM_PERE_OSMAN, message, t)))
    assert "École Sahan" in reponses[0]
    assert "Mme Aïcha" in reponses[2]
    assert reponses[-1].startswith("C'est confirmé")
    etat = DepotConversationPostgres(services["depot"]._pool).charger(
        services["etab"], NUM_PERE_OSMAN
    )
    assert etat is not None and etat.etape is Etape.MENU


def test_un_inconnu_cree_une_seule_escalade_en_base(services):
    for _ in range(3):
        services["agent"].traiter(NUM_INCONNU, "bonjour", MAINTENANT)
    ouvertes = services["escalades"].ouvertes(services["etab"])
    assert [e.motif for e in ouvertes] == [MotifEscalade.NUMERO_INCONNU]
    traitee = services["escalades"].traiter(ouvertes[0].id, Acteur.SECRETARIAT, MAINTENANT)
    assert traitee is not None and not traitee.est_ouverte


def test_stop_est_persiste(services):
    services["agent"].traiter(NUM_MERE_ALI, "STOP", MAINTENANT)
    contact = services["depot"].contact_par_numero(services["etab"], NUM_MERE_ALI)
    assert contact is not None and not contact.accepte_envois
    # Un re-import ne doit pas effacer le STOP d'un parent.
    services["agent"].traiter(NUM_MERE_ALI, "START", MAINTENANT)
    assert services["depot"].contact_par_numero(services["etab"], NUM_MERE_ALI).accepte_envois


def test_dedoublonnage_des_messages(pool):
    d = DedoublonnagePostgres(pool)
    assert d.premiere_reception("wamid.TEST1")
    assert not d.premiere_reception("wamid.TEST1")
