"""Catalogue de chaines, quatre langues.

Aucune chaine destinee a un parent ne doit apparaitre ailleurs que dans
``core/i18n/locales/*.json`` (BALLAN.md §14). Le francais est la langue de
reference : toute cle existe d'abord en francais, et ``verifier_completude``
dit ce qui manque dans les autres — c'est l'outil de suivi du lot 7.

Convention de nommage des cles : ``domaine.objet.variante``, en minuscules.
Acces imbrique par points, donc le fichier reste lisible.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.errors import CleI18nInconnue, ErreurConfiguration
from core.models.enums import LANGUE_REPLI, Langue

RACINE_LOCALES = Path(__file__).parent / "locales"

#: Cle de metadonnees presente dans chaque fichier, exclue des traductions.
CLE_META = "_meta"


def _aplatir(valeur: Any, prefixe: str = "") -> dict[str, Any]:
    """Transforme un dictionnaire imbrique en dictionnaire de cles pointees."""
    plat: dict[str, Any] = {}
    for cle, sous_valeur in valeur.items():
        chemin = f"{prefixe}.{cle}" if prefixe else cle
        if isinstance(sous_valeur, dict):
            plat.update(_aplatir(sous_valeur, chemin))
        else:
            plat[chemin] = sous_valeur
    return plat


@dataclass
class Catalogue:
    """Chaines chargees en memoire, indexees par langue puis par cle."""

    chaines: dict[Langue, dict[str, Any]] = field(default_factory=dict)
    meta: dict[Langue, dict[str, Any]] = field(default_factory=dict)
    langue_repli: Langue = LANGUE_REPLI

    @classmethod
    def charger(cls, racine: Path | None = None, langue_repli: Langue = LANGUE_REPLI) -> Catalogue:
        racine = racine or RACINE_LOCALES
        chaines: dict[Langue, dict[str, Any]] = {}
        meta: dict[Langue, dict[str, Any]] = {}
        for langue in Langue:
            fichier = racine / f"{langue.value}.json"
            if not fichier.exists():
                continue
            contenu = json.loads(fichier.read_text(encoding="utf-8"))
            meta[langue] = contenu.pop(CLE_META, {})
            chaines[langue] = _aplatir(contenu)
        if langue_repli not in chaines:
            raise ErreurConfiguration(
                f"la langue de repli {langue_repli.value} n'a pas de fichier de traduction"
            )
        return cls(chaines=chaines, meta=meta, langue_repli=langue_repli)

    # -- lecture -------------------------------------------------------

    def brut(self, cle: str, langue: Langue) -> Any:
        """Valeur brute (chaine ou liste), avec repli sur le francais."""
        for candidate in (langue, self.langue_repli):
            valeur = self.chaines.get(candidate, {}).get(cle)
            if valeur is not None:
                return valeur
        raise CleI18nInconnue(f"cle de traduction inconnue : {cle!r}")

    def t(self, cle: str, langue: Langue, **params: Any) -> str:
        """Chaine traduite et formatee.

        Une cle absente leve plutot que de laisser fuir un identifiant
        technique dans un message envoye a un parent.
        """
        valeur = self.brut(cle, langue)
        if not isinstance(valeur, str):
            raise CleI18nInconnue(f"la cle {cle!r} n'est pas une chaine")
        if not params:
            return valeur
        try:
            return valeur.format(**params)
        except KeyError as exc:
            raise CleI18nInconnue(
                f"parametre manquant {exc.args[0]!r} pour la cle {cle!r}"
            ) from exc

    def liste(self, cle: str, langue: Langue) -> list[str]:
        valeur = self.brut(cle, langue)
        if not isinstance(valeur, list):
            raise CleI18nInconnue(f"la cle {cle!r} n'est pas une liste")
        return valeur

    # -- suivi de traduction -------------------------------------------

    def langues_chargees(self) -> set[Langue]:
        return set(self.chaines)

    def cles_reference(self) -> set[str]:
        return set(self.chaines[self.langue_repli])

    def verifier_completude(self) -> dict[Langue, set[str]]:
        """Cles manquantes par langue, par rapport au francais."""
        reference = self.cles_reference()
        return {
            langue: reference - set(self.chaines.get(langue, {}))
            for langue in Langue
            if langue != self.langue_repli
        }

    def cles_orphelines(self) -> dict[Langue, set[str]]:
        """Cles presentes dans une langue mais absentes du francais.

        Signale une cle renommee dans la reference et oubliee ailleurs.
        """
        reference = self.cles_reference()
        return {
            langue: set(self.chaines.get(langue, {})) - reference
            for langue in Langue
            if langue != self.langue_repli
        }

    def statut(self, langue: Langue) -> str:
        """``reference``, ``relu`` ou ``a_relire`` — voir le lot 7."""
        return self.meta.get(langue, {}).get("statut", "inconnu")


#: Catalogue partage du processus. Charge a la demande.
_catalogue: Catalogue | None = None


def catalogue() -> Catalogue:
    global _catalogue
    if _catalogue is None:
        _catalogue = Catalogue.charger()
    return _catalogue


def t(cle: str, langue: Langue, **params: Any) -> str:
    return catalogue().t(cle, langue, **params)
