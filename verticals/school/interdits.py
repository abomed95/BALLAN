"""Interdits pedagogiques (§3, §8.1) : ce dont BALLAN ne parle jamais.

BALLAN prend des rendez-vous et communique ; il ne donne ni note, ni
moyenne, ni appreciation, ni information de comportement, et il ne traite
pas les questions de garde ou de sante. Quand un parent aborde ces sujets,
l'agent ne repond pas sur le fond :

* **notes, comportement** : il explique qu'il ne communique pas ces
  informations et propose un rendez-vous avec l'enseignant — c'est
  exactement le bon canal ;
* **garde, sante** : il escalade au secretariat sans rien traiter.

La detection est volontairement large (mots-cles, quatre langues) : un faux
positif coute un message de redirection, un faux negatif coute la confiance
de l'ecole. Ce n'est pas un filtre de securite — l'agent n'a de toute facon
aucun chemin vers ces donnees, qui n'existent pas dans le schema — c'est une
regle de conduite.
"""

from __future__ import annotations

import re
import unicodedata
from enum import StrEnum


class SujetInterdit(StrEnum):
    RESULTATS = "resultats"
    COMPORTEMENT = "comportement"
    GARDE = "garde"
    SANTE = "sante"


#: Sujets que l'agent ne traite pas du tout : escalade immediate.
SUJETS_A_ESCALADER = frozenset({SujetInterdit.GARDE, SujetInterdit.SANTE})

# Mots-cles sans accents, en minuscules. Un mot se cherche entier (pluriel
# en -s/-x tolere) ; une racine suivie de ``*`` se cherche en debut de mot.
# L'arabe, sans frontieres de mots fiables avec les clitiques, se cherche
# en sous-chaine. Somali : premiere liste, a completer au lot 7 avec l'afar.
_LATIN: dict[SujetInterdit, tuple[str, ...]] = {
    SujetInterdit.RESULTATS: (
        "note", "moyenne", "bulletin", "resultat", "classement", "examen",
        "controle", "evaluation", "redoubl*",
        "natiij*", "dhibco*", "buundo*", "imtixaan*",  # somali
    ),
    SujetInterdit.COMPORTEMENT: (
        "comportement", "conduite", "sanction", "punition", "puni", "exclusion",
        "exclu", "renvoi", "renvoye", "discipline", "avertissement", "bagarre",
        "dhaqan*", "ciqaab*", "edbin*",  # somali
    ),
    SujetInterdit.GARDE: (
        "garde", "recuperer", "recuperation", "divorce", "autorisation de sortie",
        "venir chercher", "kafaalo", "furriin",
    ),
    SujetInterdit.SANTE: (
        "malade", "maladie", "medicament", "allergie", "allergique", "sante",
        "hopital", "fievre", "blesse", "blessure", "infirmerie",
        "jirran*", "isbitaal*", "daawo",  # somali
    ),
}

_ARABE: dict[SujetInterdit, tuple[str, ...]] = {
    SujetInterdit.RESULTATS: ("درجات", "علامات", "نتيجة", "نتائج", "معدل", "كشف الدرجات",
                              "امتحان", "اختبار"),
    SujetInterdit.COMPORTEMENT: ("سلوك", "عقوبة", "عقاب", "طرد", "انضباط"),
    SujetInterdit.GARDE: ("حضانة", "طلاق", "استلام"),
    SujetInterdit.SANTE: ("مريض", "مرض", "دواء", "حساسية", "مستشفى", "صحة"),
}


def _sans_accents(texte: str) -> str:
    decompose = unicodedata.normalize("NFKD", texte)
    return "".join(c for c in decompose if not unicodedata.combining(c))


def _motif_latin(mots: tuple[str, ...]) -> re.Pattern[str]:
    alternatives = []
    for mot in sorted(mots, key=len, reverse=True):
        if mot.endswith("*"):
            alternatives.append(re.escape(mot[:-1]) + "[a-z]*")
        else:
            alternatives.append(re.escape(mot) + "[sx]?")
    return re.compile(rf"(?<![a-z])(?:{'|'.join(alternatives)})(?![a-z])", re.IGNORECASE)


_MOTIFS_LATINS = {sujet: _motif_latin(mots) for sujet, mots in _LATIN.items()}

#: Ordre de priorite : un message qui parle a la fois de notes et de garde
#: est traite comme une question de garde, la plus sensible.
_PRIORITE = (
    SujetInterdit.GARDE,
    SujetInterdit.SANTE,
    SujetInterdit.COMPORTEMENT,
    SujetInterdit.RESULTATS,
)


def detecter_sujet_interdit(texte: str) -> SujetInterdit | None:
    """Rend le sujet interdit le plus sensible aborde par le message, ou ``None``."""
    if not texte or not texte.strip():
        return None
    latin = _sans_accents(texte.lower())
    for sujet in _PRIORITE:
        if _MOTIFS_LATINS[sujet].search(latin):
            return sujet
        if any(racine in texte for racine in _ARABE[sujet]):
            return sujet
    return None
