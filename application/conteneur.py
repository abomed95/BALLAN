"""Racine de composition : le seul endroit ou les adaptateurs sont choisis.

Le domaine ne sait pas s'il parle a PostgreSQL ou a la memoire, a WhatsApp
ou a un terminal. Ce module decide, une fois, au demarrage :

* ``conteneur_production`` — PostgreSQL + WhatsApp Cloud API ;
* ``conteneur_demo`` — memoire + messagerie factice, charge depuis les
  fichiers d'exemple : c'est ce que fait tourner le simulateur et ce qui
  permet de montrer le produit a une ecole sans rien installer.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from application.config import Reglages
from application.conversation import Agent, DepotConversationMemoire
from application.persistance.memoire import DedoublonnageMemoire
from application.rappels import ServiceRappels
from application.secretariat import ServiceSecretariat
from application.whatsapp import MessageEntrant, Messagerie, MessagerieMemoire
from application.whatsapp.client import ErreurEnvoi
from core.errors import ErreurConfiguration
from core.escalade import DepotEscaladeMemoire, Escalade
from core.i18n.catalogue import catalogue
from core.models.enums import Langue
from verticals.school.family import ServiceFamille
from verticals.school.rendez_vous import DepotRendezVousMemoire, ServiceRendezVous

journal = logging.getLogger("ballan")

RACINE = Path(__file__).resolve().parents[1]
EXEMPLE_ECOLE = RACINE / "exemples" / "ecole.exemple.json"
EXEMPLE_FAMILLES = RACINE / "exemples" / "familles.exemple.csv"

#: Statuts de relecture qui autorisent une langue face a de vrais parents.
STATUTS_VALIDES = {"reference", "relu"}


class Dedoublonnage(Protocol):
    def premiere_reception(self, message_id: str) -> bool: ...

    def sante(self) -> bool: ...


def horloge_systeme() -> datetime:
    return datetime.now(UTC)


@dataclass
class Conteneur:
    reglages: Reglages
    etablissement_id: str
    agent: Agent
    rendez_vous: ServiceRendezVous
    secretariat: ServiceSecretariat
    rappels: ServiceRappels
    messagerie: Messagerie
    dedoublonnage: Dedoublonnage
    horloge: Callable[[], datetime] = horloge_systeme
    a_fermer: list[Callable[[], Any]] = field(default_factory=list)
    purger: Callable[[datetime], dict[str, int]] | None = None
    invalider_configuration: Callable[[], None] = lambda: None

    def traiter_message_entrant(self, message: MessageEntrant) -> None:
        """Du webhook a la reponse : anti-doublon, agent, envoi."""
        if not self.dedoublonnage.premiere_reception(message.id):
            return
        reponses = self.agent.traiter(
            message.numero, message.texte, self.horloge(), est_texte=message.est_texte
        )
        for reponse in reponses:
            try:
                self.messagerie.envoyer_texte(message.numero, reponse)
            except ErreurEnvoi as exc:
                journal.error("reponse non envoyee : %s", exc)
                return

    def verifier_langues(self) -> list[Langue]:
        """Langues actives non relues par un locuteur natif (locales/RELECTURE.md)."""
        conf = self.rendez_vous.configuration()
        cat = catalogue()
        return sorted(
            (lg for lg in conf.etablissement.langues_actives
             if cat.statut(lg) not in STATUTS_VALIDES),
            key=lambda lg: lg.value,
        )

    def fermer(self) -> None:
        for fermer in reversed(self.a_fermer):
            try:
                fermer()
            except Exception:  # noqa: BLE001 - arret du processus
                journal.warning("fermeture incomplete")


def _notificateur(
    reglages: Reglages, messagerie_ref: list[Messagerie]
) -> Callable[[Escalade], None] | None:
    if not reglages.numero_secretariat:
        return None

    def notifier(escalade: Escalade) -> None:
        texte = catalogue().t(
            "secretariat.nouvelle_escalade", Langue.FR,
            motif=escalade.motif.value, numero=escalade.numero,
        )
        messagerie_ref[0].envoyer_texte(reglages.numero_secretariat, texte)

    return notifier


def _assembler(
    reglages: Reglages,
    etablissement_id: str,
    depot_ecole,
    configuration,
    depot_rdv,
    conversations,
    escalades,
    messagerie: Messagerie,
    dedoublonnage: Dedoublonnage,
    horloge: Callable[[], datetime],
) -> Conteneur:
    famille = ServiceFamille(depot_ecole)
    rendez_vous = ServiceRendezVous(etablissement_id, famille, configuration, depot_rdv)
    agent = Agent(
        etablissement_id, famille, rendez_vous, depot_ecole, conversations, escalades,
        notifier_escalade=_notificateur(reglages, [messagerie]),
    )
    return Conteneur(
        reglages=reglages,
        etablissement_id=etablissement_id,
        agent=agent,
        rendez_vous=rendez_vous,
        secretariat=ServiceSecretariat(rendez_vous, depot_ecole, escalades, horloge),
        rappels=ServiceRappels(
            etablissement_id, configuration, depot_rdv, depot_ecole, famille, messagerie,
            modele=reglages.wa_template_rappel,
        ),
        messagerie=messagerie,
        dedoublonnage=dedoublonnage,
        horloge=horloge,
    )


def conteneur_demo(
    reglages: Reglages | None = None,
    chemin_ecole: Path = EXEMPLE_ECOLE,
    chemin_familles: Path = EXEMPLE_FAMILLES,
    horloge: Callable[[], datetime] = horloge_systeme,
) -> Conteneur:
    """Tout en memoire, a partir des fichiers d'exemple. Rien n'est persiste."""
    from application.importation import charger_fichiers

    reglages = reglages or Reglages(mode="demo")
    donnees = charger_fichiers(chemin_ecole, chemin_familles, horloge())
    depot_ecole, configuration = donnees.vers_memoire()
    return _assembler(
        reglages, donnees.etablissement_id, depot_ecole, configuration,
        DepotRendezVousMemoire(), DepotConversationMemoire(), DepotEscaladeMemoire(),
        MessagerieMemoire(), DedoublonnageMemoire(), horloge,
    )


def conteneur_production(
    reglages: Reglages, horloge: Callable[[], datetime] = horloge_systeme
) -> Conteneur:
    from application.persistance.postgres import (
        DedoublonnagePostgres,
        DepotConfigurationPostgres,
        DepotConversationPostgres,
        DepotEcolePostgres,
        DepotEscaladePostgres,
        DepotRendezVousPostgres,
        creer_pool,
    )
    from application.whatsapp import ClientWhatsApp

    if not reglages.database_url or not reglages.etablissement_id:
        raise ErreurConfiguration("BALLAN_DATABASE_URL et BALLAN_ETABLISSEMENT_ID sont requis")
    pool = creer_pool(reglages.database_url, reglages.taille_pool)
    if reglages.whatsapp_configure:
        client = ClientWhatsApp(
            reglages.wa_token or "", reglages.wa_phone_number_id or "", reglages.wa_api_version
        )
        messagerie: Messagerie = client
        fermer_client: Callable[[], Any] = client.fermer
    else:
        journal.warning("WhatsApp non configure : les reponses ne partent pas")
        messagerie, fermer_client = MessagerieMemoire(), (lambda: None)

    configuration = DepotConfigurationPostgres(pool)
    conversations = DepotConversationPostgres(pool)
    dedoublonnage = DedoublonnagePostgres(pool)
    conteneur = _assembler(
        reglages, reglages.etablissement_id, DepotEcolePostgres(pool), configuration,
        DepotRendezVousPostgres(pool), conversations, DepotEscaladePostgres(pool),
        messagerie, dedoublonnage, horloge,
    )

    def purger(avant: datetime) -> dict[str, int]:
        return {
            "conversations": conversations.purger(avant),
            "messages_entrants": dedoublonnage.purger(avant),
        }

    conteneur.purger = purger
    conteneur.invalider_configuration = configuration.invalider
    conteneur.a_fermer = [pool.close, fermer_client]
    return conteneur


def construire_conteneur(reglages: Reglages) -> Conteneur:
    """Choisit les adaptateurs selon le mode, puis verifie les langues actives."""
    conteneur = (
        conteneur_production(reglages) if reglages.database_url else conteneur_demo(reglages)
    )
    non_relues = conteneur.verifier_langues()
    if non_relues:
        codes = ", ".join(lg.value for lg in non_relues)
        message = (
            f"langues actives non relues par un locuteur natif : {codes} "
            "(voir core/i18n/locales/RELECTURE.md)"
        )
        if reglages.est_production and not reglages.autoriser_langues_non_relues:
            conteneur.fermer()
            raise ErreurConfiguration(
                message + ". Pour un pilote encadre : BALLAN_AUTORISER_LANGUES_NON_RELUES=1"
            )
        journal.warning(message)
    return conteneur
