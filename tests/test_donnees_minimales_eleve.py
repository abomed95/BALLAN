"""Minimisation des donnees de mineurs — NE JAMAIS RETIRER (BALLAN.md §8.1).

« Stocke le strict minimum sur l'eleve. » « Aucune note, aucune
appreciation, aucun element de comportement ne transite par BALLAN, ni en
base ni en message. » « Pas de photo d'eleve. »

Une regle ecrite dans une specification s'erode ; une regle qui fait echouer
la suite de tests tient. Ce fichier verifie la **forme des modeles**, pas
seulement leur comportement : le jour ou quelqu'un ajoutera ``moyenne`` ou
``photo_url`` a ``Eleve``, il le saura avant de pousser.
"""

from __future__ import annotations

import dataclasses
import inspect
from datetime import date

import pytest

from core.errors import ErreurConfiguration
from verticals.school import models as modeles_scolaires
from verticals.school.models import Eleve

#: Les seuls champs qu'un eleve porte. Toute addition est un choix qui se
#: discute avec l'ecole et le contrat de sous-traitance, pas une evidence.
CHAMPS_AUTORISES_ELEVE = {
    "id",
    "etablissement_id",
    "classe_id",
    "prenom",
    "nom",
    "identifiant_interne",
    "date_naissance_annee",
    "statut",
}

#: Fragments de noms de champs interdits dans toute la verticale scolaire.
#: Hors perimetre definitif (§3) ou interdits par le §8.1.
FRAGMENTS_INTERDITS = (
    "note",
    "moyenne",
    "bulletin",
    "appreciation",
    "comportement",
    "discipline",
    "sanction",
    "resultat",
    "photo",
    "sante",
    "medical",
    "maladie",
    "allergie",
    "traitement",
)


def modeles():
    """Toutes les dataclasses de la verticale scolaire."""
    return [
        objet
        for _, objet in inspect.getmembers(modeles_scolaires, inspect.isclass)
        if dataclasses.is_dataclass(objet) and objet.__module__ == modeles_scolaires.__name__
    ]


# -- forme de l'eleve --------------------------------------------------


def test_l_eleve_porte_exactement_les_champs_autorises():
    champs = {f.name for f in dataclasses.fields(Eleve)}
    en_trop = champs - CHAMPS_AUTORISES_ELEVE
    manquants = CHAMPS_AUTORISES_ELEVE - champs
    assert not en_trop, f"champs ajoutes a Eleve sans decision explicite : {sorted(en_trop)}"
    assert not manquants, f"champs retires de Eleve : {sorted(manquants)}"


def test_aucun_modele_scolaire_ne_porte_de_champ_interdit():
    fautifs = []
    for modele in modeles():
        for champ in dataclasses.fields(modele):
            nom = champ.name.lower()
            for fragment in FRAGMENTS_INTERDITS:
                if fragment in nom:
                    fautifs.append(f"{modele.__name__}.{champ.name}")
    assert not fautifs, f"champs hors perimetre (§3, §8.1) : {fautifs}"


def test_seule_l_annee_de_naissance_est_stockee():
    """Aucun champ de naissance autre que l'annee, nulle part."""
    for modele in modeles():
        for champ in dataclasses.fields(modele):
            if "naissance" in champ.name.lower():
                assert champ.name == "date_naissance_annee", (
                    f"{modele.__name__}.{champ.name} : seule l'annee de naissance "
                    "peut etre stockee (§8.1)"
                )


# -- comportement a la construction -----------------------------------


def _eleve(**remplacements):
    valeurs = {
        "id": "el-test",
        "etablissement_id": "etab-1",
        "classe_id": "cl-cm1-b",
        "prenom": "Ahmed",
        "nom": "Ali",
        "identifiant_interne": "2025-0101",
    }
    valeurs.update(remplacements)
    return Eleve(**valeurs)


def test_une_date_de_naissance_complete_est_refusee():
    """L'erreur la plus probable : quelqu'un passe un objet date."""
    with pytest.raises(ErreurConfiguration):
        _eleve(date_naissance_annee=date(2015, 3, 4))


def test_une_chaine_de_date_est_refusee():
    with pytest.raises(ErreurConfiguration):
        _eleve(date_naissance_annee="2015-03-04")


@pytest.mark.parametrize("annee", [1800, 1989, 2101, 15, -2015])
def test_une_annee_invraisemblable_est_refusee(annee):
    with pytest.raises(ErreurConfiguration):
        _eleve(date_naissance_annee=annee)


def test_une_annee_seule_est_acceptee():
    assert _eleve(date_naissance_annee=2015).date_naissance_annee == 2015


def test_l_annee_de_naissance_reste_facultative():
    """Une ecole qui ne la fournit pas dans son tableur n'est pas bloquee."""
    assert _eleve().date_naissance_annee is None
