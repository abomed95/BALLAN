"""Envoi de messages par l'API WhatsApp Cloud.

Deux types d'envoi, imposes par les regles de WhatsApp :

* **texte libre** — seulement dans les 24 h qui suivent le dernier message
  du parent. C'est le cas de toutes les reponses de l'agent ;
* **modele (template)** — pour ecrire en premier (rappels) : le texte doit
  avoir ete approuve par Meta au prealable, dans le WhatsApp Manager.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Protocol

import httpx

journal = logging.getLogger("ballan.whatsapp")

#: Limite de WhatsApp pour le corps d'un message texte.
LONGUEUR_MAX_TEXTE = 4096


class ErreurEnvoi(RuntimeError):
    """L'API a refuse l'envoi. Le message ne contient ni numero ni texte."""


class Messagerie(Protocol):
    def envoyer_texte(self, numero: str, texte: str) -> None: ...

    def envoyer_modele(
        self, numero: str, modele: str, langue: str, parametres: list[str]
    ) -> None: ...


def decouper(texte: str, longueur: int = LONGUEUR_MAX_TEXTE) -> list[str]:
    morceaux = []
    while len(texte) > longueur:
        coupure = texte.rfind("\n", 0, longueur)
        coupure = coupure if coupure > 0 else longueur
        morceaux.append(texte[:coupure])
        texte = texte[coupure:].lstrip("\n")
    return [*morceaux, texte]


class ClientWhatsApp:
    def __init__(
        self,
        token: str,
        phone_number_id: str,
        version: str = "v23.0",
        transport: httpx.BaseTransport | None = None,
        delai_reessai_s: float = 1.0,
    ) -> None:
        self._phone_number_id = phone_number_id
        self._delai_reessai_s = delai_reessai_s
        self._http = httpx.Client(
            base_url=f"https://graph.facebook.com/{version}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=httpx.Timeout(10.0, connect=5.0),
            transport=transport,
        )

    def fermer(self) -> None:
        self._http.close()

    def envoyer_texte(self, numero: str, texte: str) -> None:
        for morceau in decouper(texte):
            self._poster({
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": numero.lstrip("+"),
                "type": "text",
                "text": {"body": morceau, "preview_url": False},
            })

    def envoyer_modele(self, numero: str, modele: str, langue: str, parametres: list[str]) -> None:
        self._poster({
            "messaging_product": "whatsapp",
            "to": numero.lstrip("+"),
            "type": "template",
            "template": {
                "name": modele,
                "language": {"code": langue},
                "components": [{
                    "type": "body",
                    "parameters": [{"type": "text", "text": p} for p in parametres],
                }],
            },
        })

    def _poster(self, corps: dict) -> None:
        """Un reessai sur erreur reseau, 429 ou 5xx ; jamais sur 4xx (requete fausse)."""
        url = f"/{self._phone_number_id}/messages"
        for tentative in (1, 2):
            try:
                reponse = self._http.post(url, json=corps)
            except httpx.TransportError as exc:
                if tentative == 2:
                    raise ErreurEnvoi(f"reseau : {type(exc).__name__}") from exc
                time.sleep(self._delai_reessai_s)
                continue
            if reponse.status_code < 300:
                return
            if reponse.status_code in (429, 500, 502, 503, 504) and tentative == 1:
                time.sleep(self._delai_reessai_s)
                continue
            code = _code_erreur(reponse)
            raise ErreurEnvoi(f"API WhatsApp : HTTP {reponse.status_code}, code {code}")


def _code_erreur(reponse: httpx.Response) -> str:
    try:
        return str(reponse.json().get("error", {}).get("code", "?"))
    except ValueError:
        return "?"


@dataclass
class MessagerieMemoire:
    """Messagerie factice : demo, simulateur, tests."""

    envois: list[tuple[str, str]] = field(default_factory=list)
    modeles: list[tuple[str, str, str, list[str]]] = field(default_factory=list)

    def envoyer_texte(self, numero: str, texte: str) -> None:
        self.envois.append((numero, texte))

    def envoyer_modele(self, numero: str, modele: str, langue: str, parametres: list[str]) -> None:
        self.modeles.append((numero, modele, langue, parametres))
