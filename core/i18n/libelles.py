"""Libelles officiels multilingues (``libelle_i18n_json``).

Les niveaux, les matieres et les motifs de rendez-vous ont des libelles
officiels que l'ecole fixe elle-meme, en francais et en arabe. Ils ne se
traduisent pas librement : « CM1 » n'est pas « quatrieme annee » pour
l'administration, et le modele de langue n'a pas a s'en meler (§7).

Ces libelles sont donc stockes tels quels et seulement *resolus* ici.
"""

from __future__ import annotations

from collections.abc import Mapping

from core.errors import ErreurConfiguration
from core.models.enums import LANGUE_REPLI, Langue

#: Type du contenu des colonnes ``libelle_i18n_json``.
LibelleI18n = Mapping[str, str]


def resoudre_libelle(
    libelle: LibelleI18n,
    langue: Langue,
    repli: Langue = LANGUE_REPLI,
) -> str:
    """Retourne le libelle officiel dans la langue demandee.

    Repli sur le francais, puis sur n'importe quelle valeur presente : un
    libelle affiche dans la mauvaise langue reste preferable a un ecran
    vide devant un parent.
    """
    if not libelle:
        raise ErreurConfiguration("libelle multilingue vide")
    for candidate in (langue.value, repli.value):
        valeur = libelle.get(candidate)
        if valeur:
            return valeur
    for valeur in libelle.values():
        if valeur:
            return valeur
    raise ErreurConfiguration("libelle multilingue sans aucune valeur exploitable")


def verifier_libelle(libelle: LibelleI18n, langues_actives: frozenset[Langue]) -> set[Langue]:
    """Langues actives pour lesquelles ce libelle manque.

    Sert au tableau de bord : l'ecole doit pouvoir voir ce qu'il lui reste
    a saisir avant d'activer une langue.
    """
    return {langue for langue in langues_actives if not libelle.get(langue.value)}
