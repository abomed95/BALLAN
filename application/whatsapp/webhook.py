"""Lecture des webhooks WhatsApp Cloud API.

Deux garanties avant de lire quoi que ce soit :

* **Signature.** Meta signe chaque appel avec le secret de l'application
  (en-tete ``X-Hub-Signature-256``). Sans signature valide, la requete est
  rejetee : n'importe qui sur Internet peut appeler l'URL du webhook, et
  sans cette verification n'importe qui pourrait ecrire « au nom » d'un
  numero de parent.
* **Bon numero d'entreprise.** On ne traite que les messages adresses au
  ``phone_number_id`` configure.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class MessageEntrant:
    id: str
    numero: str
    texte: str
    recu_at: datetime
    est_texte: bool = True


def verifier_signature(corps: bytes, entete: str | None, secret: str | None) -> bool:
    if not entete or not secret or not entete.startswith("sha256="):
        return False
    attendu = hmac.new(secret.encode(), corps, hashlib.sha256).hexdigest()
    return hmac.compare_digest(attendu, entete.removeprefix("sha256="))


def _texte(message: dict[str, Any]) -> tuple[str, bool]:
    genre = message.get("type")
    if genre == "text":
        return str(message.get("text", {}).get("body", "")), True
    if genre == "interactive":
        interactif = message.get("interactive", {})
        reponse = interactif.get("button_reply") or interactif.get("list_reply") or {}
        return str(reponse.get("id") or reponse.get("title") or ""), True
    if genre == "button":
        bouton = message.get("button", {})
        return str(bouton.get("payload") or bouton.get("text") or ""), True
    # image, audio, video, document, sticker, location... : non lus.
    return "", False


def extraire_messages(
    payload: dict[str, Any], phone_number_id: str | None
) -> list[MessageEntrant]:
    """Messages entrants d'un webhook. Les accuses de lecture sont ignores."""
    messages: list[MessageEntrant] = []
    if payload.get("object") != "whatsapp_business_account":
        return messages
    for entree in payload.get("entry", []) or []:
        for changement in entree.get("changes", []) or []:
            if changement.get("field") != "messages":
                continue
            valeur = changement.get("value", {}) or {}
            destinataire = (valeur.get("metadata") or {}).get("phone_number_id")
            if phone_number_id and destinataire != phone_number_id:
                continue
            for message in valeur.get("messages", []) or []:
                expediteur = message.get("from")
                identifiant = message.get("id")
                if not expediteur or not identifiant:
                    continue
                texte, est_texte = _texte(message)
                try:
                    recu = datetime.fromtimestamp(int(message.get("timestamp", "0")), UTC)
                except (TypeError, ValueError):
                    recu = datetime.now(UTC)
                messages.append(MessageEntrant(
                    id=str(identifiant), numero="+" + str(expediteur).lstrip("+"),
                    texte=texte, recu_at=recu, est_texte=est_texte,
                ))
    return messages
