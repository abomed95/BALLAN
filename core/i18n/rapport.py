"""Rapport de completude des traductions.

    python -m core.i18n.rapport

Sort la liste, par langue, des cles manquantes et des cles orphelines, ainsi
que le statut de relecture. C'est l'outil de suivi du lot 7 (§11) ; il sert
aussi de garde-fou avant d'activer une langue pour une ecole.

Code de sortie 1 si une langue est incomplete, pour pouvoir le brancher en
integration continue.
"""

from __future__ import annotations

import sys

from core.i18n.catalogue import Catalogue
from core.models.enums import Langue


def rapport(cat: Catalogue | None = None) -> int:
    cat = cat or Catalogue.charger()
    manquantes = cat.verifier_completude()
    orphelines = cat.cles_orphelines()
    incomplet = False

    print(f"Langue de reference : {cat.langue_repli.value} "
          f"({len(cat.cles_reference())} cles)")
    for langue in Langue:
        if langue == cat.langue_repli:
            continue
        absentes = sorted(manquantes.get(langue, set()))
        en_trop = sorted(orphelines.get(langue, set()))
        statut = cat.statut(langue)
        etat = "ok" if not absentes else f"{len(absentes)} cle(s) manquante(s)"
        print(f"\n[{langue.value}] statut={statut} — {etat}")
        for cle in absentes:
            incomplet = True
            print(f"  manquante : {cle}")
        for cle in en_trop:
            print(f"  orpheline : {cle}")

    return 1 if incomplet else 0


if __name__ == "__main__":  # pragma: no cover - point d'entree
    sys.exit(rapport())
