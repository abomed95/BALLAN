"""Catalogue multilingue, dates en clair, libelles officiels."""

from __future__ import annotations

import json
from datetime import date, time

import pytest

from core.errors import CleI18nInconnue, ErreurConfiguration
from core.i18n import Catalogue, formater_date, formater_datetime, formater_heure
from core.i18n.catalogue import RACINE_LOCALES
from core.i18n.libelles import resoudre_libelle, verifier_libelle
from core.models import Langue
from tests.conftest import LUNDI, instant

CHIFFRES_ARABO_INDIENS = "٠١٢٣٤٥٦٧٨٩"


@pytest.fixture
def cat() -> Catalogue:
    return Catalogue.charger()


# -- catalogue ---------------------------------------------------------


def test_les_quatre_langues_sont_presentes(cat):
    assert cat.langues_chargees() == set(Langue)


def test_aucune_cle_ne_manque_dans_aucune_langue(cat):
    """Une cle absente ferait tomber un parent dans une autre langue.

    Ce test ne dit rien de la *justesse* des traductions — c'est le role du
    relecteur natif au lot 7, suivi dans locales/RELECTURE.md.
    """
    manquantes = cat.verifier_completude()
    assert manquantes == {langue: set() for langue in manquantes}


def test_aucune_cle_orpheline(cat):
    assert cat.cles_orphelines() == {langue: set() for langue in cat.cles_orphelines()}


def test_chaque_langue_non_reference_declare_son_statut_de_relecture(cat):
    for langue in Langue:
        if langue is cat.langue_repli:
            continue
        assert cat.statut(langue) in {"a_relire", "relu"}, (
            f"la langue {langue.value} doit declarer son statut de relecture"
        )


def test_une_cle_inconnue_leve_plutot_que_de_fuir(cat):
    with pytest.raises(CleI18nInconnue):
        cat.t("cle.qui.n.existe.pas", Langue.FR)


def test_un_parametre_manquant_leve(cat):
    with pytest.raises(CleI18nInconnue):
        cat.t("date.format_date", Langue.FR, jour="lundi")


def test_repli_sur_le_francais_si_la_langue_manque():
    """Une langue partiellement traduite ne casse pas la conversation."""
    cat = Catalogue.charger()
    cat.chaines[Langue.SO].pop("escalade.transmis")
    assert cat.t("escalade.transmis", Langue.SO) == cat.t("escalade.transmis", Langue.FR)


# -- dates -------------------------------------------------------------


def test_date_en_clair_en_francais(cat):
    assert formater_date(LUNDI, Langue.FR, cat) == "lundi 22 septembre"


def test_date_en_clair_en_somali(cat):
    assert formater_date(LUNDI, Langue.SO, cat) == "Isniin 22 Sebtembar"


def test_heure_sur_deux_positions(cat):
    assert formater_heure(time(8, 5), Langue.FR, cat) == "08:05"


def test_datetime_complet(cat):
    moment = instant(LUNDI, time(10, 0))
    assert formater_datetime(moment, Langue.FR, cat) == "lundi 22 septembre à 10:00"


@pytest.mark.parametrize("langue", list(Langue))
def test_chiffres_occidentaux_dans_toutes_les_langues(cat, langue):
    """§7 : chiffres occidentaux partout, y compris en arabe."""
    rendu = formater_datetime(instant(LUNDI, time(14, 30)), langue, cat)
    assert "22" in rendu
    assert "14:30" in rendu
    assert not any(chiffre in rendu for chiffre in CHIFFRES_ARABO_INDIENS)


@pytest.mark.parametrize("langue", list(Langue))
def test_chaque_langue_nomme_les_sept_jours_et_les_douze_mois(cat, langue):
    assert len(cat.liste("date.jours", langue)) == 7
    assert len(cat.liste("date.mois", langue)) == 12


def test_le_premier_jour_de_la_liste_est_bien_lundi(cat):
    """Aligne sur ``date.weekday()`` : un decalage ici decalerait tout."""
    for langue in Langue:
        assert formater_date(date(2025, 9, 22), langue, cat).startswith(
            cat.liste("date.jours", langue)[0]
        )


# -- libelles officiels ------------------------------------------------


def test_un_libelle_officiel_n_est_jamais_traduit_a_la_volee():
    niveau = {"fr": "CM1", "ar": "السنة الرابعة"}
    assert resoudre_libelle(niveau, Langue.FR) == "CM1"
    assert resoudre_libelle(niveau, Langue.AR) == "السنة الرابعة"


def test_libelle_absent_replie_sur_le_francais():
    niveau = {"fr": "CM1"}
    assert resoudre_libelle(niveau, Langue.SO) == "CM1"


def test_libelle_totalement_vide_est_une_erreur_de_configuration():
    with pytest.raises(ErreurConfiguration):
        resoudre_libelle({}, Langue.FR)


def test_verifier_libelle_signale_ce_qui_reste_a_saisir():
    niveau = {"fr": "CM1", "ar": "السنة الرابعة"}
    manquantes = verifier_libelle(niveau, frozenset(Langue))
    assert manquantes == {Langue.SO, Langue.AA}


# -- fichiers ----------------------------------------------------------


@pytest.mark.parametrize("langue", list(Langue))
def test_chaque_fichier_de_langue_declare_ses_metadonnees(langue):
    contenu = json.loads((RACINE_LOCALES / f"{langue.value}.json").read_text("utf-8"))
    meta = contenu["_meta"]
    assert meta["langue"] == langue.value
    assert "statut" in meta
