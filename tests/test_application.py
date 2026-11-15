"""Couche application : API HTTP, webhook WhatsApp, rappels, reglages, journaux.

Tout tourne sur le conteneur de demonstration (memoire + fichiers d'exemple),
avec une horloge fixe : dimanche 15 novembre 2026, 09:00 a Djibouti.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from application.api import creer_app
from application.api.securite import jeton_csrf
from application.config import Reglages
from application.conteneur import construire_conteneur, conteneur_demo
from application.journal import FormatJson, masquer_numeros
from application.whatsapp import ClientWhatsApp, ErreurEnvoi, extraire_messages
from application.whatsapp.client import decouper
from core.errors import ErreurConfiguration
from core.escalade import MotifEscalade

MAINTENANT = datetime(2026, 11, 15, 6, 0, tzinfo=UTC)
SECRET_APP = "secret-de-l-application-meta"
JETON_ADMIN = "jeton-admin-suffisamment-long-0123456789"
JETON_VERIF = "jeton-verification-webhook-0123456789"
NUM_OSMAN = "+25377202020"


def reglages(**surcharges) -> Reglages:
    valeurs = dict(
        mode="demo", wa_app_secret=SECRET_APP, wa_verify_token=JETON_VERIF,
        wa_phone_number_id="PNID", admin_token=JETON_ADMIN,
    )
    valeurs.update(surcharges)
    return Reglages(**valeurs)


@pytest.fixture
def conteneur():
    return conteneur_demo(reglages(), horloge=lambda: MAINTENANT)


@pytest.fixture
def client(conteneur):
    with TestClient(creer_app(conteneur)) as c:
        yield c


def webhook(numero: str, texte: str, message_id: str = "wamid.1", pnid: str = "PNID") -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": "WABA", "changes": [{"field": "messages", "value": {
            "messaging_product": "whatsapp",
            "metadata": {"phone_number_id": pnid},
            "messages": [{"from": numero.lstrip("+"), "id": message_id,
                          "timestamp": str(int(MAINTENANT.timestamp())),
                          "type": "text", "text": {"body": texte}}],
        }}]}],
    }


def signer(corps: bytes, secret: str = SECRET_APP) -> str:
    return "sha256=" + hmac.new(secret.encode(), corps, hashlib.sha256).hexdigest()


def poster(client, payload: dict, signature: str | None = None):
    corps = json.dumps(payload).encode()
    entetes = {"content-type": "application/json",
               "x-hub-signature-256": signature or signer(corps)}
    return client.post("/webhook/whatsapp", content=corps, headers=entetes)


def basic(mdp: str = JETON_ADMIN, user: str = "secretariat") -> dict:
    return {"authorization": "Basic " + base64.b64encode(f"{user}:{mdp}".encode()).decode()}


# -- sante et verification du webhook ---------------------------------


def test_sondes_de_sante(client):
    assert client.get("/sante").json() == {"statut": "ok"}
    assert client.get("/sante/pret").json() == {"statut": "pret"}


def test_meta_verifie_le_webhook_avec_le_bon_jeton(client):
    r = client.get("/webhook/whatsapp", params={
        "hub.mode": "subscribe", "hub.verify_token": JETON_VERIF, "hub.challenge": "12345"})
    assert r.status_code == 200 and r.text == "12345"


def test_un_mauvais_jeton_de_verification_est_refuse(client):
    r = client.get("/webhook/whatsapp", params={
        "hub.mode": "subscribe", "hub.verify_token": "faux", "hub.challenge": "x"})
    assert r.status_code == 403


def test_la_documentation_de_l_api_est_fermee_par_defaut(client):
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


# -- webhook entrant ---------------------------------------------------


def test_un_message_signe_recoit_une_reponse(client, conteneur):
    assert poster(client, webhook(NUM_OSMAN, "bonjour")).status_code == 200
    (numero, texte), = conteneur.messagerie.envois
    assert numero == NUM_OSMAN and "École Sahan" in texte


def test_un_message_non_signe_est_rejete_sans_traitement(client, conteneur):
    r = poster(client, webhook(NUM_OSMAN, "bonjour"), signature="sha256=" + "0" * 64)
    assert r.status_code == 403
    assert conteneur.messagerie.envois == []


def test_un_message_signe_avec_un_autre_secret_est_rejete(client, conteneur):
    corps = json.dumps(webhook(NUM_OSMAN, "1")).encode()
    r = client.post("/webhook/whatsapp", content=corps,
                    headers={"x-hub-signature-256": signer(corps, "autre-secret")})
    assert r.status_code == 403


def test_un_webhook_relivre_n_est_traite_qu_une_fois(client, conteneur):
    for _ in range(3):
        poster(client, webhook(NUM_OSMAN, "bonjour", message_id="wamid.MEME"))
    assert len(conteneur.messagerie.envois) == 1


def test_un_message_pour_un_autre_numero_d_entreprise_est_ignore(client, conteneur):
    poster(client, webhook(NUM_OSMAN, "bonjour", pnid="AUTRE"))
    assert conteneur.messagerie.envois == []


def test_un_inconnu_recoit_le_refus_par_whatsapp(client, conteneur):
    poster(client, webhook("+25377999999", "Je suis le père d'Ahmed"))
    (_, texte), = conteneur.messagerie.envois
    assert "Ahmed" not in texte
    assert [e.motif for e in conteneur.secretariat.escalades()] == [MotifEscalade.NUMERO_INCONNU]


def test_lecture_des_messages_interactifs_et_medias():
    payload = webhook(NUM_OSMAN, "x")
    valeur = payload["entry"][0]["changes"][0]["value"]
    valeur["messages"] = [
        {"from": "25377202020", "id": "a", "timestamp": "1", "type": "interactive",
         "interactive": {"type": "button_reply", "button_reply": {"id": "2", "title": "Deux"}}},
        {"from": "25377202020", "id": "b", "timestamp": "1", "type": "audio", "audio": {}},
    ]
    valeur["statuses"] = [{"id": "c", "status": "read"}]
    messages = extraire_messages(payload, "PNID")
    assert [(m.texte, m.est_texte) for m in messages] == [("2", True), ("", False)]


# -- API et page du secretariat ---------------------------------------


def _reserver(conteneur):
    for texte in ("bonjour", "1", "1", "1", "1"):
        conteneur.agent.traiter(NUM_OSMAN, texte, MAINTENANT)


def test_l_api_admin_exige_le_jeton(client):
    assert client.get("/admin/escalades").status_code == 401
    assert client.get("/admin/escalades",
                      headers={"authorization": "Bearer faux"}).status_code == 401
    assert client.get("/admin/escalades",
                      headers={"authorization": f"Bearer {JETON_ADMIN}"}).status_code == 200


def test_l_agenda_du_secretariat_montre_le_rendez_vous(client, conteneur):
    _reserver(conteneur)
    r = client.get("/admin/rendez-vous", headers={"authorization": f"Bearer {JETON_ADMIN}"})
    (ligne,) = r.json()
    assert ligne["eleve"] == "Mouna Osman" and ligne["avec"] == "Mme Aïcha"
    assert ligne["statut"] == "confirme"


def test_le_secretariat_annule_un_rendez_vous(client, conteneur):
    _reserver(conteneur)
    entete = {"authorization": f"Bearer {JETON_ADMIN}"}
    rdv_id = client.get("/admin/rendez-vous", headers=entete).json()[0]["id"]
    annulation = client.post(f"/admin/rendez-vous/{rdv_id}/annuler", headers=entete)
    assert annulation.json() == {"ok": True}
    assert client.get("/admin/rendez-vous", headers=entete).json()[0]["statut"] == "annule"
    assert client.post("/admin/rendez-vous/inconnu/annuler", headers=entete).status_code == 404


def test_la_page_du_secretariat_exige_une_authentification(client):
    r = client.get("/secretariat")
    assert r.status_code == 401 and "Basic" in r.headers["www-authenticate"]
    assert client.get("/secretariat", headers=basic("faux")).status_code == 401
    assert client.get("/secretariat", headers=basic(user="admin")).status_code == 401


def test_la_page_du_secretariat_liste_escalades_et_rendez_vous(client, conteneur):
    _reserver(conteneur)
    conteneur.agent.traiter("+25377999999", "bonjour", MAINTENANT)
    r = client.get("/secretariat", headers=basic())
    assert r.status_code == 200
    assert "Mouna Osman" in r.text and "+25377999999" in r.text
    assert r.headers["x-frame-options"] == "DENY"


def test_un_formulaire_sans_jeton_csrf_est_refuse(client, conteneur):
    conteneur.agent.traiter("+25377999999", "bonjour", MAINTENANT)
    (esc,) = conteneur.secretariat.escalades()
    url = f"/secretariat/escalades/{esc.id}/traiter"
    assert client.post(url, headers=basic(), content="csrf=faux").status_code == 403
    r = client.post(url, headers={**basic(), "content-type": "application/x-www-form-urlencoded"},
                    content=f"csrf={jeton_csrf(JETON_ADMIN)}", follow_redirects=False)
    assert r.status_code == 303
    assert conteneur.secretariat.escalades() == []


# -- rappels -----------------------------------------------------------


def test_rappel_la_veille_puis_plus_jamais(conteneur):
    _reserver(conteneur)  # lundi 16 novembre 11:00, Djibouti
    veille = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)  # dimanche 15:00 a Djibouti
    bilan = conteneur.rappels.envoyer(veille)
    assert bilan.envoyes == 1
    ((numero, texte),) = [e for e in conteneur.messagerie.envois if "Rappel" in e[1]]
    assert numero == NUM_OSMAN and "Mouna" in texte and "Mme Aïcha" in texte
    assert conteneur.rappels.envoyer(veille + timedelta(minutes=30)).envoyes == 0


def test_aucun_rappel_pendant_la_fenetre_de_silence(conteneur):
    _reserver(conteneur)
    nuit = datetime(2026, 11, 15, 19, 30, tzinfo=UTC)  # 22:30 a Djibouti
    assert conteneur.rappels.envoyer(nuit).silence


def test_aucun_rappel_apres_stop(conteneur):
    _reserver(conteneur)
    conteneur.agent.traiter(NUM_OSMAN, "STOP", MAINTENANT)
    bilan = conteneur.rappels.envoyer(datetime(2026, 11, 15, 12, 0, tzinfo=UTC))
    assert bilan.envoyes == 0 and bilan.sans_consentement == 1


def test_le_rappel_passe_par_le_modele_quand_il_est_configure():
    c = conteneur_demo(reglages(wa_template_rappel="rappel_rdv"), horloge=lambda: MAINTENANT)
    _reserver(c)
    c.rappels.envoyer(datetime(2026, 11, 15, 12, 0, tzinfo=UTC))
    ((numero, modele, langue, params),) = c.messagerie.modeles
    assert (numero, modele, langue) == (NUM_OSMAN, "rappel_rdv", "fr")
    assert params[0] == "Mouna"


# -- client WhatsApp ---------------------------------------------------


def test_le_client_envoie_au_format_de_l_api_graph():
    recues = []

    def repondre(requete: httpx.Request) -> httpx.Response:
        recues.append(requete)
        return httpx.Response(200, json={"messages": [{"id": "wamid.x"}]})

    client = ClientWhatsApp("TOKEN", "PNID", "v23.0", transport=httpx.MockTransport(repondre))
    client.envoyer_texte("+25377202020", "Bonjour")
    (requete,) = recues
    assert requete.url.path == "/v23.0/PNID/messages"
    assert requete.headers["authorization"] == "Bearer TOKEN"
    corps = json.loads(requete.content)
    assert corps["to"] == "25377202020" and corps["text"]["body"] == "Bonjour"


def test_le_client_reessaie_une_fois_sur_erreur_serveur():
    reponses = iter([httpx.Response(503), httpx.Response(200, json={})])
    client = ClientWhatsApp("T", "P", transport=httpx.MockTransport(lambda r: next(reponses)),
                            delai_reessai_s=0)
    client.envoyer_texte("+25377202020", "x")


def test_le_client_ne_reessaie_pas_une_requete_refusee():
    appels = []

    def refuser(requete):
        appels.append(requete)
        return httpx.Response(400, json={"error": {"code": 131047}})

    client = ClientWhatsApp("T", "P", transport=httpx.MockTransport(refuser), delai_reessai_s=0)
    with pytest.raises(ErreurEnvoi) as erreur:
        client.envoyer_texte("+25377202020", "x")
    assert len(appels) == 1 and "131047" in str(erreur.value)
    assert "25377202020" not in str(erreur.value)


def test_un_texte_trop_long_est_decoupe_aux_sauts_de_ligne():
    morceaux = decouper("ligne\n" * 1000, longueur=100)
    assert all(len(m) <= 100 for m in morceaux)
    assert "".join(morceaux).count("ligne") == 1000


# -- reglages ----------------------------------------------------------


def test_la_production_refuse_de_demarrer_sans_ses_reglages():
    with pytest.raises(ErreurConfiguration) as erreur:
        Reglages.depuis_environnement({"BALLAN_MODE": "production"})
    assert "WHATSAPP_APP_SECRET" in str(erreur.value)


def test_la_production_refuse_un_secret_trop_court():
    env = {
        "BALLAN_MODE": "production", "BALLAN_DATABASE_URL": "postgresql://x",
        "BALLAN_ETABLISSEMENT_ID": "e", "BALLAN_ADMIN_TOKEN": "court",
        "WHATSAPP_TOKEN": "t", "WHATSAPP_PHONE_NUMBER_ID": "p", "WHATSAPP_APP_SECRET": "s",
        "WHATSAPP_VERIFY_TOKEN": JETON_VERIF,
    }
    with pytest.raises(ErreurConfiguration):
        Reglages.depuis_environnement(env)


def test_les_secrets_n_apparaissent_pas_dans_la_representation():
    texte = repr(reglages(wa_token="TRES-SECRET"))
    assert "TRES-SECRET" not in texte and JETON_ADMIN not in texte


def test_les_langues_non_relues_sont_signalees_en_demo(caplog):
    with caplog.at_level(logging.WARNING):
        c = construire_conteneur(reglages())
    assert [lg.value for lg in c.verifier_langues()] == ["ar", "so"]
    assert "non relues" in caplog.text


# -- journaux ----------------------------------------------------------


def test_les_numeros_sont_masques_dans_les_journaux():
    enregistrement = logging.LogRecord(
        "ballan", logging.INFO, __file__, 1, "message de %s", ("+25377202020",), None
    )
    ligne = json.loads(FormatJson().format(enregistrement))
    assert "77202020" not in ligne["message"] and "2020" in ligne["message"]
    assert masquer_numeros("le 2026-11-15") == "le 2026-11-15"
