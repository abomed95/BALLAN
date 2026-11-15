"""Prise de rendez-vous scolaire (lot 3).

Trois regles, appliquees ici et pas dans un prompt :

* **Le perimetre d'abord.** Proposer, reserver, lister ou annuler exige un
  ``Perimetre`` recalcule par ``ServiceFamille``. Un rendez-vous d'un autre
  enfant est refuse avec la meme erreur qu'un rendez-vous inexistant.
* **L'agent ne choisit pas la ressource.** Elle decoule du motif : enseignant
  principal de la classe, ou ressource designee par l'ecole.
* **La base tranche.** Le service verifie le creneau avant d'ecrire, mais la
  contrainte d'exclusion PostgreSQL reste l'arbitre des courses entre deux
  parents ; son echec remonte en ``CreneauIndisponible``.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Protocol

from core.errors import AccesRefuse, CreneauIndisponible, ErreurConfiguration
from core.models.agenda import Occupation
from core.models.enums import STATUTS_BLOQUANTS_DEFAUT, Acteur, StatutRendezVous
from core.scheduling.conflits import detecter_conflit
from core.scheduling.creneaux import Creneau, MoteurCreneaux
from core.temps import exiger_conscient
from verticals.school.configuration import ConfigurationEcole, DepotConfiguration
from verticals.school.family import ServiceFamille
from verticals.school.models import DestinataireRendezVous, MotifRendezVous, RendezVous
from verticals.school.rules import Perimetre, exiger_acces_eleve, exiger_acteur

#: Horizon de recherche des creneaux proposes a un parent.
HORIZON_PROPOSITION_JOURS = 21


class DepotRendezVous(Protocol):
    """Persistance des rendez-vous. Sans controle d'acces, comme ``DepotEcole``."""

    def occupations(self, ressource_id: str, du: datetime, au: datetime) -> list[Occupation]: ...

    def inserer(self, rdv: RendezVous) -> RendezVous:
        """Insere ou leve ``CreneauIndisponible`` si le creneau est pris."""
        ...

    def rendez_vous(self, rdv_id: str) -> RendezVous | None: ...

    def a_venir(self, eleve_ids: Iterable[str], depuis: datetime) -> list[RendezVous]: ...

    def changer_statut(self, rdv_id: str, statut: StatutRendezVous) -> RendezVous | None: ...

    def sur_periode(
        self, etablissement_id: str, du: datetime, au: datetime
    ) -> list[RendezVous]: ...

    def a_rappeler(
        self, etablissement_id: str, du: datetime, au: datetime
    ) -> list[RendezVous]: ...

    def marquer_rappel(self, rdv_id: str, instant: datetime) -> None: ...


class DepotRendezVousMemoire:
    """Miroir memoire de la table ``rendez_vous`` et de sa contrainte d'exclusion."""

    def __init__(self, rendez_vous: Iterable[RendezVous] = ()) -> None:
        self._rdv: dict[str, RendezVous] = {r.id: r for r in rendez_vous}
        self._verrou = threading.Lock()

    def occupations(self, ressource_id: str, du: datetime, au: datetime) -> list[Occupation]:
        with self._verrou:
            return [
                r.vers_occupation()
                for r in self._rdv.values()
                if r.ressource_id == ressource_id and r.debut < au and du < r.fin
            ]

    def inserer(self, rdv: RendezVous) -> RendezVous:
        with self._verrou:
            conflit = detecter_conflit(
                rdv.ressource_id,
                rdv.debut,
                rdv.fin,
                [r.vers_occupation() for r in self._rdv.values()],
                STATUTS_BLOQUANTS_DEFAUT,
                ignorer_reference_id=rdv.id,
            )
            if conflit is not None and rdv.statut in STATUTS_BLOQUANTS_DEFAUT:
                raise CreneauIndisponible("creneau deja occupe")
            self._rdv[rdv.id] = rdv
            return rdv

    def rendez_vous(self, rdv_id: str) -> RendezVous | None:
        return self._rdv.get(rdv_id)

    def a_venir(self, eleve_ids: Iterable[str], depuis: datetime) -> list[RendezVous]:
        ids = set(eleve_ids)
        return sorted(
            (r for r in self._rdv.values() if r.eleve_id in ids and r.fin > depuis),
            key=lambda r: (r.debut, r.id),
        )

    def changer_statut(self, rdv_id: str, statut: StatutRendezVous) -> RendezVous | None:
        with self._verrou:
            rdv = self._rdv.get(rdv_id)
            if rdv is None:
                return None
            self._rdv[rdv_id] = replace(rdv, statut=statut)
            return self._rdv[rdv_id]

    def sur_periode(self, etablissement_id: str, du: datetime, au: datetime) -> list[RendezVous]:
        return sorted(
            (
                r
                for r in self._rdv.values()
                if r.etablissement_id == etablissement_id and r.debut < au and du < r.fin
            ),
            key=lambda r: (r.debut, r.id),
        )

    def a_rappeler(self, etablissement_id: str, du: datetime, au: datetime) -> list[RendezVous]:
        return [
            r
            for r in self.sur_periode(etablissement_id, du, au)
            if r.est_confirme and r.rappel_envoye_at is None and du <= r.debut < au
        ]

    def marquer_rappel(self, rdv_id: str, instant: datetime) -> None:
        with self._verrou:
            rdv = self._rdv.get(rdv_id)
            if rdv is not None:
                self._rdv[rdv_id] = replace(rdv, rappel_envoye_at=instant)


@dataclass(frozen=True)
class Proposition:
    """Un creneau propose, avec ce qu'il faut pour l'afficher et le reserver."""

    creneau: Creneau
    ressource_id: str
    ressource_libelle: str


class ServiceRendezVous:
    """Le seul chemin par lequel un rendez-vous scolaire se lit ou s'ecrit."""

    def __init__(
        self,
        etablissement_id: str,
        famille: ServiceFamille,
        configuration: DepotConfiguration,
        depot: DepotRendezVous,
        generer_id: Callable[[], str] = lambda: str(uuid.uuid4()),
    ) -> None:
        self._etablissement_id = etablissement_id
        self._famille = famille
        self._configuration = configuration
        self._depot = depot
        self._generer_id = generer_id

    # -- configuration -------------------------------------------------

    def configuration(self) -> ConfigurationEcole:
        return self._configuration.configuration(self._etablissement_id)

    def motifs(self) -> tuple[MotifRendezVous, ...]:
        return self.configuration().motifs_actifs()

    def _motif(self, conf: ConfigurationEcole, motif_id: str) -> MotifRendezVous:
        motif = conf.motif(motif_id)
        if motif is None or not motif.actif:
            raise ErreurConfiguration("motif inconnu ou inactif")
        return motif

    def ressource_pour(self, perimetre: Perimetre, eleve_id: str, motif_id: str) -> str:
        """La ressource qui recoit, deduite du motif — jamais choisie par l'agent."""
        conf = self.configuration()
        motif = self._motif(conf, motif_id)
        if motif.destinataire is DestinataireRendezVous.ENSEIGNANT:
            return self._famille.enseignant_principal_de(perimetre, eleve_id).id
        exiger_acces_eleve(perimetre, eleve_id)
        assert motif.ressource_id is not None  # garanti par MotifRendezVous
        return motif.ressource_id

    # -- proposition ---------------------------------------------------

    def proposer(
        self,
        perimetre: Perimetre,
        eleve_id: str,
        motif_id: str,
        maintenant: datetime,
        nombre: int = 3,
        horizon_jours: int = HORIZON_PROPOSITION_JOURS,
    ) -> list[Proposition]:
        """Les prochains creneaux libres, de preference sur des jours distincts.

        Trois creneaux colles le meme matin n'offrent pas de vrai choix a un
        parent qui travaille : on prend d'abord le premier creneau de chaque
        jour, puis on complete.
        """
        exiger_conscient(maintenant, "maintenant")
        eleve = self._famille.eleve(perimetre, eleve_id)
        if not eleve.est_inscrit:
            raise AccesRefuse("eleve sorti")
        conf = self.configuration()
        motif = self._motif(conf, motif_id)
        ressource_id = self.ressource_pour(perimetre, eleve_id, motif_id)
        ressource = conf.ressource(ressource_id)
        if ressource is None or not ressource.actif:
            raise ErreurConfiguration("ressource inconnue ou inactive")

        scolaire = conf.calendrier_scolaire()
        moteur = MoteurCreneaux(calendrier=scolaire.calendrier)
        tz = conf.etablissement.tz
        debut = maintenant.astimezone(tz).date()
        fin = debut + timedelta(days=horizon_jours)
        occupations = self._depot.occupations(
            ressource_id, maintenant, maintenant + timedelta(days=horizon_jours + 1)
        )
        candidats = [
            c
            for c in moteur.creneaux_periode(
                ressource_id,
                debut,
                fin,
                motif.duree_min,
                occupations,
                maintenant=maintenant,
                pas_min=ressource.pas_effectif if ressource.pas_min else motif.duree_min,
            )
            if scolaire.est_jour_de_classe(c.debut.astimezone(tz).date())
        ]
        retenus = _repartir_sur_jours(candidats, nombre, tz)
        return [Proposition(c, ressource_id, ressource.libelle) for c in retenus]

    # -- reservation ---------------------------------------------------

    def reserver(
        self,
        perimetre: Perimetre,
        eleve_id: str,
        motif_id: str,
        debut: datetime,
        maintenant: datetime,
        acteur: Acteur = Acteur.AGENT,
    ) -> RendezVous:
        exiger_conscient(debut, "debut")
        exiger_conscient(maintenant, "maintenant")
        eleve = self._famille.eleve(perimetre, eleve_id)
        if not eleve.est_inscrit:
            raise AccesRefuse("eleve sorti")
        conf = self.configuration()
        motif = self._motif(conf, motif_id)
        ressource_id = self.ressource_pour(perimetre, eleve_id, motif_id)
        fin = debut + timedelta(minutes=motif.duree_min)

        plancher = maintenant + timedelta(minutes=conf.etablissement.delai_minimal_min)
        if debut < plancher:
            raise CreneauIndisponible("creneau passe ou trop proche")

        scolaire = conf.calendrier_scolaire()
        scolaire.exiger_jour_de_classe(debut.astimezone(conf.etablissement.tz).date())
        moteur = MoteurCreneaux(calendrier=scolaire.calendrier)
        moteur.verifier_reservable(
            ressource_id, debut, fin, self._depot.occupations(ressource_id, debut, fin)
        )

        rdv = RendezVous(
            id=self._generer_id(),
            etablissement_id=self._etablissement_id,
            ressource_id=ressource_id,
            eleve_id=eleve.id,
            debut=debut,
            fin=fin,
            motif_id=motif.id,
            parent_id=self._parent_demandeur(perimetre, eleve_id),
            contact_id=perimetre.contact_id,
            statut=StatutRendezVous.CONFIRME,
            cree_par=acteur,
        )
        return self._depot.inserer(rdv)

    def _parent_demandeur(self, perimetre: Perimetre, eleve_id: str) -> str | None:
        for parent in self._famille.coparents(perimetre, eleve_id):
            if perimetre.couvre_parent(parent.id):
                return parent.id
        return None

    # -- consultation et annulation par un parent ----------------------

    def a_venir(self, perimetre: Perimetre, maintenant: datetime) -> list[RendezVous]:
        """Rendez-vous confirmes a venir, pour les seuls enfants du perimetre."""
        if not perimetre.est_rattache:
            return []
        return [
            r
            for r in self._depot.a_venir(perimetre.eleve_ids, maintenant)
            if r.est_confirme and perimetre.couvre(r.eleve_id)
        ]

    def rendez_vous(self, perimetre: Perimetre, rdv_id: str) -> RendezVous:
        rdv = self._depot.rendez_vous(rdv_id)
        # Meme erreur que le rendez-vous existe ou non (§8.2).
        if rdv is None or not perimetre.couvre(rdv.eleve_id):
            raise AccesRefuse("rendez-vous hors perimetre")
        return rdv

    def annuler(self, perimetre: Perimetre, rdv_id: str) -> RendezVous:
        rdv = self.rendez_vous(perimetre, rdv_id)
        if not rdv.est_confirme:
            return rdv
        annule = self._depot.changer_statut(rdv.id, StatutRendezVous.ANNULE)
        assert annule is not None
        return annule

    # -- secretariat ---------------------------------------------------

    def sur_periode(self, acteur: Acteur, du: datetime, au: datetime) -> list[RendezVous]:
        exiger_acteur(acteur, (Acteur.SECRETARIAT, Acteur.DIRECTION), "consulter_agenda_ecole")
        return self._depot.sur_periode(self._etablissement_id, du, au)

    def annuler_par_l_ecole(self, acteur: Acteur, rdv_id: str) -> RendezVous:
        exiger_acteur(acteur, (Acteur.SECRETARIAT, Acteur.DIRECTION), "annuler_rendez_vous")
        rdv = self._depot.rendez_vous(rdv_id)
        if rdv is None or rdv.etablissement_id != self._etablissement_id:
            raise AccesRefuse("rendez-vous inconnu")
        annule = self._depot.changer_statut(rdv_id, StatutRendezVous.ANNULE)
        assert annule is not None
        return annule


def _repartir_sur_jours(candidats: list[Creneau], nombre: int, tz) -> list[Creneau]:
    premiers: list[Creneau] = []
    vus = set()
    for creneau in candidats:
        jour = creneau.debut.astimezone(tz).date()
        if jour not in vus:
            vus.add(jour)
            premiers.append(creneau)
        if len(premiers) == nombre:
            return premiers
    reste = [c for c in candidats if c not in premiers]
    return sorted(premiers + reste[: nombre - len(premiers)])
