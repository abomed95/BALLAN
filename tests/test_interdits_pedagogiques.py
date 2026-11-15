"""Interdits pedagogiques — NE JAMAIS RETIRER (§3, §8.1).

BALLAN ne communique ni note, ni appreciation, ni comportement, et ne
traite ni la garde ni la sante. Ce fichier verifie la detection ; le
comportement de l'agent face a ces sujets est verifie dans
``tests/test_agent_conversation.py``.
"""

from __future__ import annotations

import pytest

from verticals.school.interdits import (
    SUJETS_A_ESCALADER,
    SujetInterdit,
    detecter_sujet_interdit,
)


@pytest.mark.parametrize(
    ("texte", "sujet"),
    [
        ("Quelles sont les notes d'Ahmed ce trimestre ?", SujetInterdit.RESULTATS),
        ("Je voudrais sa MOYENNE", SujetInterdit.RESULTATS),
        ("Le bulletin est-il prêt ?", SujetInterdit.RESULTATS),
        ("Est-ce qu'il va redoubler ?", SujetInterdit.RESULTATS),
        ("أريد درجات ابني", SujetInterdit.RESULTATS),
        ("Natiijada wiilkayga", SujetInterdit.RESULTATS),
        ("Comment est son comportement en classe ?", SujetInterdit.COMPORTEMENT),
        ("Pourquoi a-t-il été puni ?", SujetInterdit.COMPORTEMENT),
        ("ما هي عقوبة ابني", SujetInterdit.COMPORTEMENT),
        ("Son père n'a plus le droit de venir chercher l'enfant", SujetInterdit.GARDE),
        ("Question de garde suite au divorce", SujetInterdit.GARDE),
        ("Ma fille est malade aujourd'hui", SujetInterdit.SANTE),
        ("Il doit prendre un médicament à midi", SujetInterdit.SANTE),
        ("ابني مريض", SujetInterdit.SANTE),
    ],
)
def test_les_sujets_interdits_sont_detectes(texte, sujet):
    assert detecter_sujet_interdit(texte) is sujet


@pytest.mark.parametrize(
    "texte",
    [
        "Bonjour",
        "Je voudrais un rendez-vous avec la maîtresse",
        "1",
        "Notez mon nouveau créneau s'il vous plaît",
        "Il faut ranger la classe",
        "هذا صحيح",
        "",
        "   ",
    ],
)
def test_les_messages_ordinaires_ne_sont_pas_detectes(texte):
    assert detecter_sujet_interdit(texte) is None


def test_la_garde_l_emporte_sur_les_notes():
    texte = "Je veux ses notes et savoir qui peut venir chercher mon fils"
    assert detecter_sujet_interdit(texte) is SujetInterdit.GARDE


def test_garde_et_sante_sont_escaladees_sans_traitement():
    assert SUJETS_A_ESCALADER == {SujetInterdit.GARDE, SujetInterdit.SANTE}
