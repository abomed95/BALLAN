"""Authentification du secretariat et protection des formulaires.

* API JSON : ``Authorization: Bearer <BALLAN_ADMIN_TOKEN>``.
* Page du secretariat : authentification HTTP Basic (utilisateur
  ``secretariat``, mot de passe ``BALLAN_ADMIN_TOKEN``), a servir
  exclusivement en HTTPS (Caddy dans docker-compose).
* Formulaires : jeton anti-CSRF derive du secret ; un navigateur
  authentifie en Basic renvoie ses identifiants a chaque requete, une page
  tierce pourrait donc sinon declencher une annulation a sa place.

Toutes les comparaisons sont a temps constant.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

from fastapi import HTTPException, Request, status

UTILISATEUR = "secretariat"


def egal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def jeton_csrf(secret: str) -> str:
    return hmac.new(secret.encode(), b"ballan-csrf", hashlib.sha256).hexdigest()


def exiger_admin(request: Request, secret: str | None, page: bool = False) -> None:
    """Leve 401 si la requete n'est pas authentifiee comme secretariat."""
    if not secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "administration desactivee")
    entete = request.headers.get("authorization", "")
    if entete.lower().startswith("bearer ") and egal(entete[7:].strip(), secret):
        return
    if entete.lower().startswith("basic "):
        try:
            decode = base64.b64decode(entete[6:].strip()).decode()
            utilisateur, _, mot_de_passe = decode.partition(":")
        except (ValueError, UnicodeDecodeError):
            utilisateur, mot_de_passe = "", ""
        if egal(utilisateur, UTILISATEUR) and egal(mot_de_passe, secret):
            return
    raise HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "authentification requise",
        headers={"WWW-Authenticate": 'Basic realm="BALLAN secretariat"'} if page else None,
    )


def verifier_csrf(valeur: str | None, secret: str) -> None:
    if not valeur or not egal(valeur, jeton_csrf(secret)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "jeton de formulaire invalide")


def nouveau_secret() -> str:
    return secrets.token_urlsafe(32)
