"""Adaptateurs PostgreSQL des ports du domaine.

Chaque classe implemente un ``Protocol`` defini dans le domaine
(``DepotEcole``, ``DepotConfiguration``, ``DepotRendezVous``,
``DepotConversation``, ``DepotEscalade``) et ne fait **que** de la
traduction ligne <-> objet. Aucun controle d'acces ici : il est dans
``ServiceFamille`` et ``ServiceRendezVous``, au-dessus.

Deux regles propres a cet adaptateur :

* **Un identifiant malforme ne leve pas.** Le domaine manipule des ``str`` ;
  la base, des ``uuid``. Un id qui n'est pas un uuid (etat de conversation
  falsifie, URL bricolee) est traite comme un id inexistant — le domaine
  repond alors par son refus habituel, indiscernable.
* **La contrainte d'exclusion tranche.** Une violation de
  ``rendez_vous_sans_chevauchement`` remonte en ``CreneauIndisponible``.
"""

from __future__ import annotations

import json
import threading
import time as horloge
import uuid
from collections.abc import Iterable
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from application.conversation.etat import EtatConversation
from core.errors import CreneauIndisponible, ErreurConfiguration
from core.escalade import Escalade, MotifEscalade
from core.models.agenda import Disponibilite, ExceptionAgenda, Occupation
from core.models.contact import Contact
from core.models.enums import Acteur, Jour, Langue, StatutRendezVous, TypeException
from core.models.etablissement import Etablissement, FenetreSilence, Ressource
from verticals.school.configuration import ConfigurationEcole
from verticals.school.models import (
    AnneeScolaire,
    Classe,
    DestinataireRendezVous,
    Eleve,
    Enseignant,
    Famille,
    LienParente,
    LienParentEleve,
    MotifRendezVous,
    Niveau,
    Parent,
    Periode,
    RendezVous,
    StatutEleve,
    TypePeriode,
)


def creer_pool(dsn: str, taille_max: int = 10) -> ConnectionPool:
    """Pool de connexions partage par tous les adaptateurs d'un processus."""
    pool = ConnectionPool(
        dsn,
        min_size=1,
        max_size=taille_max,
        kwargs={"row_factory": dict_row},
        open=False,
    )
    pool.open(wait=True, timeout=30)
    return pool


def _uuid(valeur: str | None) -> str | None:
    """Rend l'uuid canonique, ou ``None`` si la valeur n'en est pas un."""
    if valeur is None:
        return None
    try:
        return str(uuid.UUID(str(valeur)))
    except ValueError:
        return None


def _s(valeur: Any) -> str | None:
    return None if valeur is None else str(valeur)


def _langue(code: str | None) -> Langue | None:
    try:
        return Langue(code) if code else None
    except ValueError:
        return None


class _Adaptateur:
    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def _un(self, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
        with self._pool.connection() as conn:
            return conn.execute(sql, tuple(params)).fetchone()

    def _tous(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        with self._pool.connection() as conn:
            return conn.execute(sql, tuple(params)).fetchall()

    def _executer(self, sql: str, params: Iterable[Any] = ()) -> int:
        with self._pool.connection() as conn:
            return conn.execute(sql, tuple(params)).rowcount


# =====================================================================
# Ecole : contacts, familles, eleves, structure
# =====================================================================


def _contact(r: dict[str, Any]) -> Contact:
    return Contact(
        id=str(r["id"]),
        etablissement_id=str(r["etablissement_id"]),
        numero=r["numero"],
        langue_preferee=_langue(r["langue_preferee"]),
        consenti_at=r["consenti_at"],
        stoppe_at=r["stoppe_at"],
    )


def _parent(r: dict[str, Any]) -> Parent:
    return Parent(
        id=str(r["id"]),
        famille_id=str(r["famille_id"]),
        contact_id=_s(r["contact_id"]),
        lien=LienParente(r["lien"]),
        est_referent=r["est_referent"],
        langue_preferee=_langue(r["langue_preferee"]),
    )


def _lien(r: dict[str, Any]) -> LienParentEleve:
    return LienParentEleve(
        parent_id=str(r["parent_id"]),
        eleve_id=str(r["eleve_id"]),
        autorise_a_recuperer=r["autorise_a_recuperer"],
    )


class DepotEcolePostgres(_Adaptateur):
    """Implemente ``verticals.school.depot.DepotEcole``."""

    def contact_par_numero(self, etablissement_id: str, numero: str) -> Contact | None:
        etab = _uuid(etablissement_id)
        if etab is None:
            return None
        r = self._un(
            "SELECT * FROM contact WHERE etablissement_id = %s AND numero = %s", (etab, numero)
        )
        return _contact(r) if r else None

    def contact(self, contact_id: str) -> Contact | None:
        cid = _uuid(contact_id)
        r = self._un("SELECT * FROM contact WHERE id = %s", (cid,)) if cid else None
        return _contact(r) if r else None

    def parents_du_contact(self, etablissement_id: str, contact_id: str) -> list[Parent]:
        etab, cid = _uuid(etablissement_id), _uuid(contact_id)
        if etab is None or cid is None:
            return []
        lignes = self._tous(
            "SELECT p.* FROM parent p JOIN famille f ON f.id = p.famille_id "
            "WHERE p.contact_id = %s AND f.etablissement_id = %s ORDER BY p.id",
            (cid, etab),
        )
        return [_parent(r) for r in lignes]

    def parent(self, parent_id: str) -> Parent | None:
        pid = _uuid(parent_id)
        r = self._un("SELECT * FROM parent WHERE id = %s", (pid,)) if pid else None
        return _parent(r) if r else None

    def liens_du_parent(self, parent_id: str) -> list[LienParentEleve]:
        pid = _uuid(parent_id)
        if pid is None:
            return []
        return [_lien(r) for r in self._tous(
            "SELECT * FROM lien_parent_eleve WHERE parent_id = %s", (pid,)
        )]

    def liens_de_l_eleve(self, eleve_id: str) -> list[LienParentEleve]:
        eid = _uuid(eleve_id)
        if eid is None:
            return []
        return [_lien(r) for r in self._tous(
            "SELECT * FROM lien_parent_eleve WHERE eleve_id = %s", (eid,)
        )]

    def eleve(self, eleve_id: str) -> Eleve | None:
        eid = _uuid(eleve_id)
        r = self._un("SELECT * FROM eleve WHERE id = %s", (eid,)) if eid else None
        if r is None:
            return None
        return Eleve(
            id=str(r["id"]),
            etablissement_id=str(r["etablissement_id"]),
            classe_id=str(r["classe_id"]),
            prenom=r["prenom"],
            nom=r["nom"],
            identifiant_interne=r["identifiant_interne"],
            date_naissance_annee=r["date_naissance_annee"],
            statut=StatutEleve(r["statut"]),
        )

    def classe(self, classe_id: str) -> Classe | None:
        cid = _uuid(classe_id)
        r = self._un("SELECT * FROM classe WHERE id = %s", (cid,)) if cid else None
        if r is None:
            return None
        return Classe(
            id=str(r["id"]),
            etablissement_id=str(r["etablissement_id"]),
            niveau_id=str(r["niveau_id"]),
            annee_scolaire_id=str(r["annee_scolaire_id"]),
            libelle=r["libelle"],
            enseignant_principal_id=_s(r["enseignant_principal_id"]),
            effectif=r["effectif"],
        )

    def niveau(self, niveau_id: str) -> Niveau | None:
        nid = _uuid(niveau_id)
        r = self._un("SELECT * FROM niveau WHERE id = %s", (nid,)) if nid else None
        if r is None:
            return None
        return Niveau(
            id=str(r["id"]),
            etablissement_id=str(r["etablissement_id"]),
            libelle_i18n=r["libelle_i18n"],
            ordre=r["ordre"],
        )

    def enseignant(self, enseignant_id: str) -> Enseignant | None:
        eid = _uuid(enseignant_id)
        r = self._un("SELECT * FROM enseignant WHERE id = %s", (eid,)) if eid else None
        if r is None:
            return None
        classes = self._tous(
            "SELECT classe_id FROM enseignant_classe WHERE enseignant_id = %s ORDER BY classe_id",
            (eid,),
        )
        return Enseignant(
            id=str(r["id"]),
            etablissement_id=str(r["etablissement_id"]),
            nom=r["nom"],
            matieres=tuple(r["matieres"]),
            classes=tuple(str(c["classe_id"]) for c in classes),
            langues=frozenset(lg for lg in map(_langue, r["langues"]) if lg),
            duree_creneau_min=r["duree_creneau_min"],
            actif=r["actif"],
        )

    def famille(self, famille_id: str) -> Famille | None:
        fid = _uuid(famille_id)
        r = self._un("SELECT * FROM famille WHERE id = %s", (fid,)) if fid else None
        if r is None:
            return None
        return Famille(
            id=str(r["id"]), etablissement_id=str(r["etablissement_id"]),
            nom_affiche=r["nom_affiche"],
        )

    # -- preferences du contact ----------------------------------------

    def marquer_stop(self, contact_id: str, instant: datetime) -> None:
        if cid := _uuid(contact_id):
            self._executer("UPDATE contact SET stoppe_at = %s WHERE id = %s", (instant, cid))

    def marquer_consentement(self, contact_id: str, instant: datetime) -> None:
        if cid := _uuid(contact_id):
            self._executer(
                "UPDATE contact SET consenti_at = %s, stoppe_at = NULL WHERE id = %s",
                (instant, cid),
            )

    def definir_langue_contact(self, contact_id: str, langue: Langue) -> None:
        if cid := _uuid(contact_id):
            self._executer(
                "UPDATE contact SET langue_preferee = %s WHERE id = %s", (langue.value, cid)
            )

    # -- ecritures du secretariat (appelees via ServiceFamille) --------

    def enregistrer_contact(self, contact: Contact) -> Contact:
        self._executer(
            "INSERT INTO contact (id, etablissement_id, numero, langue_preferee, consenti_at, "
            "stoppe_at) VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO UPDATE SET "
            "numero = EXCLUDED.numero, langue_preferee = EXCLUDED.langue_preferee, "
            "consenti_at = EXCLUDED.consenti_at, stoppe_at = EXCLUDED.stoppe_at",
            (contact.id, contact.etablissement_id, contact.numero,
             contact.langue_preferee.value if contact.langue_preferee else None,
             contact.consenti_at, contact.stoppe_at),
        )
        return contact

    def enregistrer_parent(self, parent: Parent) -> Parent:
        self._executer(
            "INSERT INTO parent (id, famille_id, contact_id, lien, est_referent, langue_preferee) "
            "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO UPDATE SET "
            "contact_id = EXCLUDED.contact_id, lien = EXCLUDED.lien, "
            "est_referent = EXCLUDED.est_referent, langue_preferee = EXCLUDED.langue_preferee",
            (parent.id, parent.famille_id, parent.contact_id, parent.lien.value,
             parent.est_referent,
             parent.langue_preferee.value if parent.langue_preferee else None),
        )
        return parent

    def enregistrer_lien(self, lien: LienParentEleve) -> LienParentEleve:
        self._executer(
            "INSERT INTO lien_parent_eleve (parent_id, eleve_id, autorise_a_recuperer) "
            "VALUES (%s, %s, %s) ON CONFLICT (parent_id, eleve_id) DO UPDATE SET "
            "autorise_a_recuperer = EXCLUDED.autorise_a_recuperer",
            (lien.parent_id, lien.eleve_id, lien.autorise_a_recuperer),
        )
        return lien


# =====================================================================
# Configuration
# =====================================================================


class DepotConfigurationPostgres(_Adaptateur):
    """Implemente ``DepotConfiguration``, avec un cache court.

    La configuration change quelques fois par an ; la relire a chaque
    message coute sept requetes. Le cache de ``duree_cache_s`` secondes
    garde un import visible presque immediatement.
    """

    def __init__(self, pool: ConnectionPool, duree_cache_s: float = 30.0) -> None:
        super().__init__(pool)
        self._duree_cache_s = duree_cache_s
        self._cache: dict[str, tuple[float, ConfigurationEcole]] = {}
        self._verrou = threading.Lock()

    def invalider(self) -> None:
        with self._verrou:
            self._cache.clear()

    def configuration(self, etablissement_id: str) -> ConfigurationEcole:
        with self._verrou:
            en_cache = self._cache.get(etablissement_id)
        if en_cache and horloge.monotonic() - en_cache[0] < self._duree_cache_s:
            return en_cache[1]
        conf = self._charger(etablissement_id)
        with self._verrou:
            self._cache[etablissement_id] = (horloge.monotonic(), conf)
        return conf

    def _charger(self, etablissement_id: str) -> ConfigurationEcole:
        etab_id = _uuid(etablissement_id)
        e = self._un("SELECT * FROM etablissement WHERE id = %s", (etab_id,)) if etab_id else None
        if e is None:
            raise ErreurConfiguration("etablissement introuvable en base")
        etablissement = Etablissement(
            id=str(e["id"]),
            nom=e["nom"],
            fuseau_nom=e["fuseau"],
            langues_actives=frozenset(Langue(x) for x in e["langues_actives"]),
            langue_defaut=Langue(e["langue_defaut"]),
            jours_ouvres=frozenset(Jour(j) for j in e["jours_ouvres"]),
            silence=FenetreSilence(e["silence_debut"], e["silence_fin"]),
            devise=e["devise"],
            delai_minimal_min=e["delai_minimal_min"],
        )
        a = self._un(
            "SELECT * FROM annee_scolaire WHERE etablissement_id = %s AND active", (etab_id,)
        )
        if a is None:
            raise ErreurConfiguration("aucune annee scolaire active")
        annee = AnneeScolaire(
            id=str(a["id"]), etablissement_id=str(a["etablissement_id"]), libelle=a["libelle"],
            date_debut=a["date_debut"], date_fin=a["date_fin"], active=True,
        )
        periodes = tuple(
            Periode(
                id=str(r["id"]), annee_scolaire_id=str(r["annee_scolaire_id"]),
                libelle_i18n=r["libelle_i18n"], type=TypePeriode(r["type"]),
                date_debut=r["date_debut"], date_fin=r["date_fin"],
            )
            for r in self._tous(
                "SELECT * FROM periode WHERE annee_scolaire_id = %s ORDER BY date_debut",
                (a["id"],),
            )
        )
        disponibilites = tuple(
            Disponibilite(
                id=str(r["id"]), etablissement_id=str(r["etablissement_id"]),
                ressource_id=str(r["ressource_id"]), jour=Jour(r["jour"]),
                heure_debut=r["heure_debut"], heure_fin=r["heure_fin"], actif=True,
            )
            for r in self._tous(
                "SELECT * FROM disponibilite WHERE etablissement_id = %s AND actif", (etab_id,)
            )
        )
        exceptions = tuple(
            ExceptionAgenda(
                id=str(r["id"]), etablissement_id=str(r["etablissement_id"]),
                type=TypeException(r["type"]), date_debut=r["date_debut"],
                date_fin=r["date_fin"], ressource_id=_s(r["ressource_id"]),
                heure_debut=r["heure_debut"], heure_fin=r["heure_fin"], motif=r["motif"],
            )
            for r in self._tous(
                "SELECT * FROM exception_agenda WHERE etablissement_id = %s", (etab_id,)
            )
        )
        ressources = tuple(
            Ressource(
                id=str(r["id"]), etablissement_id=str(r["etablissement_id"]),
                libelle=r["libelle"], duree_creneau_min=r["duree_creneau_min"],
                pas_min=r["pas_min"],
                langues=frozenset(lg for lg in map(_langue, r["langues"]) if lg),
                actif=r["actif"],
            )
            for r in self._tous("SELECT * FROM ressource WHERE etablissement_id = %s", (etab_id,))
        )
        motifs = tuple(
            MotifRendezVous(
                id=str(r["id"]), etablissement_id=str(r["etablissement_id"]),
                libelle_i18n=r["libelle_i18n"], duree_min=r["duree_min"],
                destinataire=DestinataireRendezVous(r["destinataire"]),
                ressource_id=_s(r["ressource_id"]), actif=r["actif"], ordre=r["ordre"],
            )
            for r in self._tous(
                "SELECT * FROM motif_rendez_vous WHERE etablissement_id = %s", (etab_id,)
            )
        )
        return ConfigurationEcole(
            etablissement=etablissement, annee=annee, periodes=periodes,
            disponibilites=disponibilites, exceptions=exceptions,
            ressources=ressources, motifs=motifs,
        )


# =====================================================================
# Rendez-vous
# =====================================================================


def _rdv(r: dict[str, Any]) -> RendezVous:
    return RendezVous(
        id=str(r["id"]),
        etablissement_id=str(r["etablissement_id"]),
        ressource_id=str(r["ressource_id"]),
        eleve_id=str(r["eleve_id"]),
        debut=r["debut_at"],
        fin=r["fin_at"],
        motif_id=_s(r["motif_id"]),
        parent_id=_s(r["parent_id"]),
        contact_id=_s(r["contact_id"]),
        statut=StatutRendezVous(r["statut"]),
        cree_par=Acteur(r["cree_par"]),
        rappel_envoye_at=r["rappel_envoye_at"],
    )


class DepotRendezVousPostgres(_Adaptateur):
    """Implemente ``DepotRendezVous``. Seuls les rendez-vous scolaires (eleve_id non nul)."""

    def occupations(self, ressource_id: str, du: datetime, au: datetime) -> list[Occupation]:
        rid = _uuid(ressource_id)
        if rid is None:
            return []
        lignes = self._tous(
            "SELECT id, ressource_id, debut_at, fin_at, statut FROM rendez_vous "
            "WHERE ressource_id = %s AND debut_at < %s AND fin_at > %s",
            (rid, au, du),
        )
        return [
            Occupation(
                ressource_id=str(r["ressource_id"]), debut=r["debut_at"], fin=r["fin_at"],
                statut=StatutRendezVous(r["statut"]), reference_id=str(r["id"]),
            )
            for r in lignes
        ]

    def inserer(self, rdv: RendezVous) -> RendezVous:
        try:
            r = self._un(
                "INSERT INTO rendez_vous (id, etablissement_id, ressource_id, contact_id, "
                "debut_at, fin_at, statut, cree_par, eleve_id, parent_id, motif_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *",
                (rdv.id, rdv.etablissement_id, rdv.ressource_id, rdv.contact_id, rdv.debut,
                 rdv.fin, rdv.statut.value, rdv.cree_par.value, rdv.eleve_id, rdv.parent_id,
                 rdv.motif_id),
            )
        except psycopg.errors.ExclusionViolation as exc:
            raise CreneauIndisponible("creneau deja occupe (contrainte d'exclusion)") from exc
        assert r is not None
        return _rdv(r)

    def rendez_vous(self, rdv_id: str) -> RendezVous | None:
        rid = _uuid(rdv_id)
        r = self._un(
            "SELECT * FROM rendez_vous WHERE id = %s AND eleve_id IS NOT NULL", (rid,)
        ) if rid else None
        return _rdv(r) if r else None

    def a_venir(self, eleve_ids: Iterable[str], depuis: datetime) -> list[RendezVous]:
        ids = [i for i in map(_uuid, eleve_ids) if i]
        if not ids:
            return []
        return [_rdv(r) for r in self._tous(
            "SELECT * FROM rendez_vous WHERE eleve_id = ANY(%s::uuid[]) AND fin_at > %s "
            "ORDER BY debut_at, id",
            (ids, depuis),
        )]

    def changer_statut(self, rdv_id: str, statut: StatutRendezVous) -> RendezVous | None:
        rid = _uuid(rdv_id)
        if rid is None:
            return None
        try:
            r = self._un(
                "UPDATE rendez_vous SET statut = %s, maj_at = now() WHERE id = %s RETURNING *",
                (statut.value, rid),
            )
        except psycopg.errors.ExclusionViolation as exc:
            raise CreneauIndisponible("creneau deja occupe (contrainte d'exclusion)") from exc
        return _rdv(r) if r else None

    def sur_periode(self, etablissement_id: str, du: datetime, au: datetime) -> list[RendezVous]:
        etab = _uuid(etablissement_id)
        if etab is None:
            return []
        return [_rdv(r) for r in self._tous(
            "SELECT * FROM rendez_vous WHERE etablissement_id = %s AND eleve_id IS NOT NULL "
            "AND debut_at < %s AND fin_at > %s ORDER BY debut_at, id",
            (etab, au, du),
        )]

    def a_rappeler(self, etablissement_id: str, du: datetime, au: datetime) -> list[RendezVous]:
        etab = _uuid(etablissement_id)
        if etab is None:
            return []
        return [_rdv(r) for r in self._tous(
            "SELECT * FROM rendez_vous WHERE etablissement_id = %s AND eleve_id IS NOT NULL "
            "AND statut = 'confirme' AND rappel_envoye_at IS NULL "
            "AND debut_at >= %s AND debut_at < %s ORDER BY debut_at",
            (etab, du, au),
        )]

    def marquer_rappel(self, rdv_id: str, instant: datetime) -> None:
        if rid := _uuid(rdv_id):
            self._executer(
                "UPDATE rendez_vous SET rappel_envoye_at = %s WHERE id = %s", (instant, rid)
            )


# =====================================================================
# Conversation, escalade, anti-doublon
# =====================================================================


class DepotConversationPostgres(_Adaptateur):
    def charger(self, etablissement_id: str, numero: str) -> EtatConversation | None:
        etab = _uuid(etablissement_id)
        r = self._un(
            "SELECT etat FROM conversation WHERE etablissement_id = %s AND numero = %s",
            (etab, numero),
        ) if etab else None
        return EtatConversation.depuis_dict(r["etat"]) if r else None

    def enregistrer(self, etablissement_id: str, numero: str, etat: EtatConversation) -> None:
        self._executer(
            "INSERT INTO conversation (etablissement_id, numero, etat, maj_at) "
            "VALUES (%s, %s, %s, now()) ON CONFLICT (etablissement_id, numero) "
            "DO UPDATE SET etat = EXCLUDED.etat, maj_at = now()",
            (etablissement_id, numero, json.dumps(etat.vers_dict())),
        )

    def purger(self, avant: datetime) -> int:
        return self._executer("DELETE FROM conversation WHERE maj_at < %s", (avant,))


def _escalade(r: dict[str, Any]) -> Escalade:
    return Escalade(
        id=str(r["id"]),
        etablissement_id=str(r["etablissement_id"]),
        numero=r["numero"],
        motif=MotifEscalade(r["motif"]),
        cree_at=r["cree_at"],
        traitee_at=r["traitee_at"],
        traitee_par=Acteur(r["traitee_par"]) if r["traitee_par"] else None,
    )


class DepotEscaladePostgres(_Adaptateur):
    def creer(self, escalade: Escalade) -> Escalade:
        r = self._un(
            "INSERT INTO escalade (id, etablissement_id, numero, motif, cree_at) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (etablissement_id, numero, motif) WHERE traitee_at IS NULL "
            "DO NOTHING RETURNING *",
            (escalade.id, escalade.etablissement_id, escalade.numero, escalade.motif.value,
             escalade.cree_at),
        )
        if r is None:
            # Course avec une autre instance : l'escalade ouverte existe deja.
            existante = self.ouverte(escalade.etablissement_id, escalade.numero, escalade.motif)
            return existante or escalade
        return _escalade(r)

    def ouverte(self, etablissement_id: str, numero: str, motif: MotifEscalade) -> Escalade | None:
        etab = _uuid(etablissement_id)
        r = self._un(
            "SELECT * FROM escalade WHERE etablissement_id = %s AND numero = %s "
            "AND motif = %s AND traitee_at IS NULL",
            (etab, numero, motif.value),
        ) if etab else None
        return _escalade(r) if r else None

    def ouvertes(self, etablissement_id: str) -> list[Escalade]:
        etab = _uuid(etablissement_id)
        if etab is None:
            return []
        return [_escalade(r) for r in self._tous(
            "SELECT * FROM escalade WHERE etablissement_id = %s AND traitee_at IS NULL "
            "ORDER BY cree_at",
            (etab,),
        )]

    def traiter(self, escalade_id: str, acteur: Acteur, instant: datetime) -> Escalade | None:
        eid = _uuid(escalade_id)
        r = self._un(
            "UPDATE escalade SET traitee_at = %s, traitee_par = %s WHERE id = %s RETURNING *",
            (instant, acteur.value, eid),
        ) if eid else None
        return _escalade(r) if r else None


class DedoublonnagePostgres(_Adaptateur):
    """Retient les identifiants de messages WhatsApp deja traites."""

    def premiere_reception(self, message_id: str) -> bool:
        r = self._un(
            "INSERT INTO message_entrant (id) VALUES (%s) ON CONFLICT DO NOTHING RETURNING id",
            (message_id,),
        )
        return r is not None

    def purger(self, avant: datetime) -> int:
        return self._executer("DELETE FROM message_entrant WHERE recu_at < %s", (avant,))

    def sante(self) -> bool:
        return self._un("SELECT 1 AS ok") is not None
