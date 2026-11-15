"""Journaux structures, sans donnee nominative.

Les journaux d'un service qui manipule des donnees de mineurs ne contiennent
ni prenom, ni nom, ni numero de telephone en clair (README, « Conventions »).
Le domaine s'y astreint deja ; ce module ajoute un filet : tout ce qui
ressemble a un numero est masque avant d'etre ecrit (``+253****1234``).
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime

#: 8 a 15 chiffres, eventuellement separes par des espaces, hors dates et uuid.
_NUMERO = re.compile(r"(?<![\w\-:])\+?\d(?: ?\d){7,14}(?![\w\-:])")


def masquer_numeros(texte: str) -> str:
    def masque(m: re.Match[str]) -> str:
        chiffres = re.sub(r"\D", "", m.group(0))
        if len(chiffres) < 8:
            return m.group(0)
        if len(chiffres) > 8:
            return f"+{chiffres[:3]}****{chiffres[-4:]}"
        return f"****{chiffres[-4:]}"

    return _NUMERO.sub(masque, texte)


#: Parametres d'URL : le webhook recoit le jeton de verification de Meta en
#: parametre (``hub.verify_token``). Rien de ce qui suit ``?`` n'est journalise.
_PARAMETRES_URL = re.compile(r"\?[^\s\"]*")


def masquer(texte: str) -> str:
    return masquer_numeros(_PARAMETRES_URL.sub("?…", texte))


class FormatJson(logging.Formatter):
    """Une ligne JSON par evenement : lisible par docker logs comme par un collecteur."""

    def format(self, record: logging.LogRecord) -> str:
        entree = {
            "t": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "niveau": record.levelname,
            "source": record.name,
            "message": masquer(record.getMessage()),
        }
        if record.exc_info:
            entree["exception"] = masquer(self.formatException(record.exc_info))
        return json.dumps(entree, ensure_ascii=False)


def configurer_journal(niveau: str = "INFO") -> None:
    gestionnaire = logging.StreamHandler(sys.stdout)
    gestionnaire.setFormatter(FormatJson())
    racine = logging.getLogger()
    racine.handlers[:] = [gestionnaire]
    racine.setLevel(niveau)
    # Les journaux d'acces d'uvicorn contiennent les URL : on les garde,
    # mais au format commun, et masques.
    for nom in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        journal = logging.getLogger(nom)
        journal.handlers[:] = [gestionnaire]
        journal.propagate = False
    # httpx journalise les URL de l'API Graph, qui ne contiennent pas de
    # numero de parent, mais on evite le bruit.
    logging.getLogger("httpx").setLevel("WARNING")
