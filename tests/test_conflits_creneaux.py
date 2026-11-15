"""Conflits de creneaux — deux parents ne prennent jamais le meme rendez-vous.

Critere d'acceptation §12 : « Deux parents ne peuvent pas reserver le meme
creneau d'un enseignant ».

Ce fichier teste le miroir applicatif de la contrainte d'exclusion Postgres.
La contrainte elle-meme (``EXCLUDE USING gist``, migrations/0001_core.sql)
reste l'autorite en production, ou plusieurs instances de l'API tournent en
parallele : elle se verifie en integration, pas ici.
"""

from __future__ import annotations

import threading
from datetime import time

import pytest

from core.errors import CreneauIndisponible
from core.models import Occupation, StatutRendezVous
from core.scheduling import AgendaMemoire, chevauchement, detecter_conflit, garantir_libre
from tests.conftest import LUNDI, instant


def occupation(
    debut: time,
    fin: time,
    ressource_id: str = "ens-1",
    statut: StatutRendezVous = StatutRendezVous.CONFIRME,
    reference_id: str | None = None,
) -> Occupation:
    return Occupation(
        ressource_id=ressource_id,
        debut=instant(LUNDI, debut),
        fin=instant(LUNDI, fin),
        statut=statut,
        reference_id=reference_id or f"rdv-{debut.hour}{debut.minute:02d}",
    )


# -- arithmetique de chevauchement -------------------------------------


def test_creneaux_jointifs_ne_sont_pas_en_conflit():
    assert not chevauchement(
        instant(LUNDI, time(10, 0)),
        instant(LUNDI, time(10, 30)),
        instant(LUNDI, time(10, 30)),
        instant(LUNDI, time(11, 0)),
    )


@pytest.mark.parametrize(
    ("debut", "fin"),
    [
        (time(10, 0), time(10, 30)),  # identique
        (time(9, 45), time(10, 15)),  # deborde au debut
        (time(10, 15), time(10, 45)),  # deborde a la fin
        (time(9, 0), time(12, 0)),  # englobe
        (time(10, 5), time(10, 10)),  # inclus
    ],
)
def test_toutes_les_formes_de_chevauchement_sont_detectees(debut, fin):
    existant = occupation(time(10, 0), time(10, 30))
    conflit = detecter_conflit(
        "ens-1", instant(LUNDI, debut), instant(LUNDI, fin), [existant]
    )
    assert conflit is existant


def test_pas_de_conflit_entre_enseignants_differents():
    existant = occupation(time(10, 0), time(10, 30), ressource_id="ens-2")
    assert (
        detecter_conflit(
            "ens-1", instant(LUNDI, time(10, 0)), instant(LUNDI, time(10, 30)), [existant]
        )
        is None
    )


def test_un_rendez_vous_annule_ne_bloque_pas():
    annule = occupation(time(10, 0), time(10, 30), statut=StatutRendezVous.ANNULE)
    assert (
        detecter_conflit(
            "ens-1", instant(LUNDI, time(10, 0)), instant(LUNDI, time(10, 30)), [annule]
        )
        is None
    )


def test_un_rendez_vous_peut_etre_deplace_sans_entrer_en_conflit_avec_lui_meme():
    existant = occupation(time(10, 0), time(10, 30), reference_id="rdv-x")
    garantir_libre(
        "ens-1",
        instant(LUNDI, time(10, 0)),
        instant(LUNDI, time(11, 0)),
        [existant],
        ignorer_reference_id="rdv-x",
    )


def test_garantir_libre_leve_sans_divulguer_l_autre_famille():
    existant = occupation(time(10, 0), time(10, 30))
    with pytest.raises(CreneauIndisponible) as erreur:
        garantir_libre(
            "ens-1", instant(LUNDI, time(10, 0)), instant(LUNDI, time(10, 30)), [existant]
        )
    # Le message part dans les journaux : il ne doit contenir aucune identite.
    assert "ens-1" in str(erreur.value)
    assert "rdv-1000" not in str(erreur.value)


# -- agenda : verification et ecriture atomiques -----------------------


def test_deux_reservations_du_meme_creneau_la_seconde_echoue():
    agenda = AgendaMemoire()
    agenda.reserver(occupation(time(10, 0), time(10, 30), reference_id="famille-a"))
    with pytest.raises(CreneauIndisponible):
        agenda.reserver(occupation(time(10, 0), time(10, 30), reference_id="famille-b"))
    assert len(agenda.toutes("ens-1")) == 1


def test_deux_reservations_jointives_passent_toutes_les_deux():
    agenda = AgendaMemoire()
    agenda.reserver(occupation(time(10, 0), time(10, 30), reference_id="famille-a"))
    agenda.reserver(occupation(time(10, 30), time(11, 0), reference_id="famille-b"))
    assert len(agenda.toutes("ens-1")) == 2


def test_annuler_libere_le_creneau():
    agenda = AgendaMemoire()
    agenda.reserver(occupation(time(10, 0), time(10, 30), reference_id="famille-a"))
    assert agenda.annuler("famille-a")
    agenda.reserver(occupation(time(10, 0), time(10, 30), reference_id="famille-b"))
    confirmes = [
        o for o in agenda.toutes("ens-1") if o.statut is StatutRendezVous.CONFIRME
    ]
    assert [o.reference_id for o in confirmes] == ["famille-b"]


def test_deux_parents_reservent_simultanement_un_seul_passe():
    """§13 : « Deux parents reservant le meme creneau simultanement ».

    La verification et l'ecriture sont faites sous un meme verrou. Sans cela,
    les deux fils liraient « libre » avant que l'un des deux n'ecrive.
    """
    agenda = AgendaMemoire()
    depart = threading.Barrier(2)
    resultats: list[str] = []
    verrou_resultats = threading.Lock()

    def reserver(reference: str) -> None:
        depart.wait()
        try:
            agenda.reserver(occupation(time(10, 0), time(10, 30), reference_id=reference))
            issue = f"{reference}:ok"
        except CreneauIndisponible:
            issue = f"{reference}:refuse"
        with verrou_resultats:
            resultats.append(issue)

    fils = [
        threading.Thread(target=reserver, args=("famille-a",)),
        threading.Thread(target=reserver, args=("famille-b",)),
    ]
    for f in fils:
        f.start()
    for f in fils:
        f.join(timeout=5)

    assert sorted(r.split(":")[1] for r in resultats) == ["ok", "refuse"]
    assert len(agenda.toutes("ens-1")) == 1


def test_course_repetee_sur_beaucoup_de_fils():
    """Le meme scenario a huit familles : un seul rendez-vous en sort."""
    agenda = AgendaMemoire()
    depart = threading.Barrier(8)
    succes: list[str] = []
    verrou = threading.Lock()

    def reserver(indice: int) -> None:
        depart.wait()
        try:
            agenda.reserver(
                occupation(time(10, 0), time(10, 30), reference_id=f"famille-{indice}")
            )
        except CreneauIndisponible:
            return
        with verrou:
            succes.append(f"famille-{indice}")

    fils = [threading.Thread(target=reserver, args=(i,)) for i in range(8)]
    for f in fils:
        f.start()
    for f in fils:
        f.join(timeout=5)

    assert len(succes) == 1
    assert len(agenda.toutes("ens-1")) == 1
