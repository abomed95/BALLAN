"""Application FastAPI.

Routes :

* ``GET  /sante``                   — vivant (pour Docker et la supervision)
* ``GET  /sante/pret``              — pret : base joignable
* ``GET  /webhook/whatsapp``        — verification du webhook par Meta
* ``POST /webhook/whatsapp``        — messages entrants (signature exigee)
* ``GET  /secretariat``             — page du secretariat (HTTP Basic)
* ``/admin/...``                    — API JSON du secretariat (Bearer)

Le webhook repond 200 immediatement et traite les messages en tache de
fond : Meta re-livre un webhook qui tarde, l'anti-doublon absorbe ces
re-livraisons.
"""

from __future__ import annotations

import html
import json
import logging
from contextlib import asynccontextmanager
from datetime import date, timedelta
from urllib.parse import parse_qs

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from application.api.securite import egal, exiger_admin, jeton_csrf, verifier_csrf
from application.conteneur import Conteneur
from application.whatsapp import extraire_messages, verifier_signature
from core.errors import AccesRefuse, ActeurNonAutorise

journal = logging.getLogger("ballan.api")

LIBELLES_ESCALADE = {
    "numero_inconnu": "Numéro inconnu — à rattacher à une famille",
    "demande_parent": "Le parent demande à parler au secrétariat",
    "sujet_sensible": "Sujet sensible (garde, santé) — à traiter par un humain",
    "aucun_creneau": "Aucun créneau libre à proposer",
    "incident": "Incident technique pendant la conversation",
}


def creer_app(conteneur: Conteneur) -> FastAPI:
    reglages = conteneur.reglages

    @asynccontextmanager
    async def cycle_de_vie(_app: FastAPI):
        yield
        conteneur.fermer()

    app = FastAPI(
        title="BALLAN",
        version="0.2.0",
        lifespan=cycle_de_vie,
        docs_url="/docs" if reglages.docs_api else None,
        redoc_url=None,
        openapi_url="/openapi.json" if reglages.docs_api else None,
    )

    @app.middleware("http")
    async def entetes_securite(request: Request, appel_suivant):
        reponse = await appel_suivant(request)
        reponse.headers["X-Content-Type-Options"] = "nosniff"
        reponse.headers["X-Frame-Options"] = "DENY"
        reponse.headers["Referrer-Policy"] = "no-referrer"
        reponse.headers["Cache-Control"] = "no-store"
        return reponse

    # -- sante ---------------------------------------------------------

    @app.get("/sante")
    def sante() -> dict:
        return {"statut": "ok"}

    @app.get("/sante/pret")
    def pret() -> dict:
        try:
            ok = conteneur.dedoublonnage.sante()
            conteneur.rendez_vous.configuration()
        except Exception as exc:  # noqa: BLE001 - la sonde rend un statut, pas une trace
            journal.warning("sonde de disponibilite en echec : %s", type(exc).__name__)
            ok = False
        if not ok:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "base indisponible")
        return {"statut": "pret"}

    # -- webhook WhatsApp ----------------------------------------------

    @app.get("/webhook/whatsapp", response_class=PlainTextResponse)
    def verifier_webhook(
        mode: str = Query("", alias="hub.mode"),
        jeton: str = Query("", alias="hub.verify_token"),
        defi: str = Query("", alias="hub.challenge"),
    ) -> str:
        attendu = reglages.wa_verify_token
        if mode == "subscribe" and attendu and egal(jeton, attendu):
            return defi
        raise HTTPException(status.HTTP_403_FORBIDDEN, "jeton de verification invalide")

    @app.post("/webhook/whatsapp")
    async def recevoir(request: Request, taches: BackgroundTasks) -> dict:
        corps = await request.body()
        if not verifier_signature(
            corps, request.headers.get("x-hub-signature-256"), reglages.wa_app_secret
        ):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "signature invalide")
        try:
            payload = json.loads(corps)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "JSON invalide") from exc
        for message in extraire_messages(payload, reglages.wa_phone_number_id):
            taches.add_task(_traiter, conteneur, message)
        return {"ok": True}

    # -- API JSON du secretariat ---------------------------------------

    def admin(request: Request) -> None:
        exiger_admin(request, reglages.admin_token)

    @app.get("/admin/rendez-vous")
    def lister_rendez_vous(request: Request, du: date | None = None, au: date | None = None):
        admin(request)
        du = du or _aujourd_hui(conteneur)
        au = au or du + timedelta(days=7)
        if (au - du).days > 92:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "periode trop longue (92 jours max)")
        return [
            {**ligne.__dict__, "debut": ligne.debut.isoformat(), "fin": ligne.fin.isoformat()}
            for ligne in conteneur.secretariat.agenda(du, au)
        ]

    @app.post("/admin/rendez-vous/{rdv_id}/annuler")
    def annuler(request: Request, rdv_id: str):
        admin(request)
        _ou_404(lambda: conteneur.secretariat.annuler(rdv_id))
        return {"ok": True}

    @app.get("/admin/escalades")
    def escalades(request: Request):
        admin(request)
        return [
            {"id": e.id, "numero": e.numero, "motif": e.motif.value,
             "cree_at": e.cree_at.isoformat()}
            for e in conteneur.secretariat.escalades()
        ]

    @app.post("/admin/escalades/{escalade_id}/traiter")
    def traiter(request: Request, escalade_id: str):
        admin(request)
        _ou_404(lambda: conteneur.secretariat.traiter_escalade(escalade_id))
        return {"ok": True}

    @app.post("/admin/configuration/recharger")
    def recharger(request: Request):
        """A appeler apres un import pour que l'agent voie la nouvelle configuration."""
        admin(request)
        conteneur.invalider_configuration()
        return {"ok": True}

    # -- page du secretariat -------------------------------------------

    @app.get("/secretariat", response_class=HTMLResponse)
    def page(request: Request) -> str:
        exiger_admin(request, reglages.admin_token, page=True)
        return _page_secretariat(conteneur, jeton_csrf(reglages.admin_token or ""))

    @app.post("/secretariat/{genre}/{ident}/{action}")
    async def action(request: Request, genre: str, ident: str, action: str):
        exiger_admin(request, reglages.admin_token, page=True)
        champs = parse_qs((await request.body()).decode())
        verifier_csrf((champs.get("csrf") or [None])[0], reglages.admin_token or "")
        if (genre, action) == ("escalades", "traiter"):
            _ou_404(lambda: conteneur.secretariat.traiter_escalade(ident))
        elif (genre, action) == ("rendez-vous", "annuler"):
            _ou_404(lambda: conteneur.secretariat.annuler(ident))
        else:
            raise HTTPException(status.HTTP_404_NOT_FOUND)
        return RedirectResponse("/secretariat", status_code=status.HTTP_303_SEE_OTHER)

    return app


def _traiter(conteneur: Conteneur, message) -> None:
    try:
        conteneur.traiter_message_entrant(message)
    except Exception as exc:  # noqa: BLE001 - une tache de fond ne doit pas mourir en silence
        journal.exception("traitement du message impossible : %s", type(exc).__name__)


def _ou_404(operation) -> None:
    try:
        operation()
    except (AccesRefuse, ActeurNonAutorise) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "introuvable") from exc


def _aujourd_hui(conteneur: Conteneur) -> date:
    tz = conteneur.rendez_vous.configuration().etablissement.tz
    return conteneur.horloge().astimezone(tz).date()


# =====================================================================
# Page HTML du secretariat (volontairement sans JavaScript ni dependance)
# =====================================================================

_STYLE = """
:root{--fond:#f7f7f5;--carte:#fff;--texte:#1d1d1b;--doux:#6b6b66;--accent:#0b6e4f;
--alerte:#b3261e;--trait:#e4e4df}
@media (prefers-color-scheme:dark){:root{--fond:#161615;--carte:#20201e;--texte:#ededea;
--doux:#a3a39d;--accent:#4fc59a;--alerte:#ff8a80;--trait:#33332f}}
*{box-sizing:border-box}body{margin:0;font:16px/1.5 system-ui,sans-serif;background:var(--fond);
color:var(--texte)}main{max-width:960px;margin:0 auto;padding:16px}
h1{font-size:1.4rem;margin:.5rem 0 1rem}h2{font-size:1.1rem;margin:1.5rem 0 .5rem}
.carte{background:var(--carte);border:1px solid var(--trait);border-radius:10px;padding:12px 14px;
margin:8px 0;display:flex;gap:12px;align-items:center;justify-content:space-between;flex-wrap:wrap}
.doux{color:var(--doux);font-size:.9rem}.vide{color:var(--doux);font-style:italic}
a{color:var(--accent)}button{font:inherit;border:1px solid var(--trait);background:var(--carte);
color:var(--texte);border-radius:8px;padding:6px 12px;cursor:pointer}
button.alerte{color:var(--alerte)}.annule{opacity:.55;text-decoration:line-through}
.jour{margin-top:1rem;font-weight:600}
"""


def _formulaire(action: str, libelle: str, csrf: str, classe: str = "") -> str:
    return (
        f'<form method="post" action="{html.escape(action)}">'
        f'<input type="hidden" name="csrf" value="{csrf}">'
        f'<button class="{classe}" type="submit">{html.escape(libelle)}</button></form>'
    )


def _page_secretariat(conteneur: Conteneur, csrf: str) -> str:
    conf = conteneur.rendez_vous.configuration()
    aujourd_hui = _aujourd_hui(conteneur)
    e = html.escape
    blocs = [f"<h1>{e(conf.etablissement.nom)} — secrétariat BALLAN</h1>"]

    escalades = conteneur.secretariat.escalades()
    blocs.append(f"<h2>À rappeler ({len(escalades)})</h2>")
    if not escalades:
        blocs.append('<p class="vide">Aucune demande en attente.</p>')
    tz = conf.etablissement.tz
    for esc in escalades:
        quand = esc.cree_at.astimezone(tz).strftime("%d/%m %H:%M")
        blocs.append(
            '<div class="carte"><div>'
            f'<a href="tel:{e(esc.numero)}">{e(esc.numero)}</a><br>'
            f'<span class="doux">{e(LIBELLES_ESCALADE.get(esc.motif.value, esc.motif.value))}'
            f" · {quand}</span></div>"
            + _formulaire(f"/secretariat/escalades/{esc.id}/traiter", "Traité", csrf)
            + "</div>"
        )

    lignes = conteneur.secretariat.agenda(aujourd_hui, aujourd_hui + timedelta(days=13))
    blocs.append("<h2>Rendez-vous des deux prochaines semaines</h2>")
    if not lignes:
        blocs.append('<p class="vide">Aucun rendez-vous.</p>')
    jour_courant = None
    for ligne in lignes:
        if ligne.debut.date() != jour_courant:
            jour_courant = ligne.debut.date()
            blocs.append(f'<div class="jour">{jour_courant.strftime("%d/%m/%Y")}</div>')
        annule = ligne.statut == "annule"
        rappel = " · rappel envoyé" if ligne.rappel_envoye else ""
        bouton = "" if annule else _formulaire(
            f"/secretariat/rendez-vous/{ligne.id}/annuler", "Annuler", csrf, "alerte"
        )
        blocs.append(
            f'<div class="carte{" annule" if annule else ""}"><div>'
            f'<strong>{ligne.debut.strftime("%H:%M")}–{ligne.fin.strftime("%H:%M")}</strong> '
            f"{e(ligne.eleve)} <span class=\"doux\">({e(ligne.classe)})</span><br>"
            f'<span class="doux">avec {e(ligne.avec)} · {e(ligne.motif)} · '
            f"{e(ligne.statut)}{rappel}</span></div>{bouton}</div>"
        )
    corps = "\n".join(blocs)
    return (
        '<!doctype html><html lang="fr"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>Secrétariat BALLAN</title><style>{_STYLE}</style></head>"
        f"<body><main>{corps}</main></body></html>"
    )
