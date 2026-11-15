"""Agent conversationnel BALLAN : une machine a etats a menus numerotes.

Choix de conception, assume pour le pilote : **l'agent est deterministe**.
Il ne fait pas appel a un modele de langue pour decider. Chaque reponse est
une chaine du catalogue i18n, chaque action passe par un service du domaine
qui verifie le perimetre familial. Consequences :

* aucune hallucination possible sur une donnee d'eleve, un creneau ou un
  motif — l'agent ne peut proposer que ce que le domaine lui rend ;
* comportement identique dans les quatre langues, testable exhaustivement ;
* menus numerotes : ils fonctionnent sur tous les telephones, avec tous les
  claviers, y compris pour un parent peu a l'aise a l'ecrit.

Un modele de langue pourra ensuite etre branche *en amont* pour traduire un
message libre (« je voudrais voir la maitresse de Sagal jeudi ») en une
intention du menu — jamais pour produire une reponse ou lire une donnee.

Flux d'un message : normalisation du numero -> STOP/START -> identification
(perimetre recalcule) -> refus sans divulgation si inconnu -> commandes
globales -> sujets interdits -> etape courante.
"""

from __future__ import annotations

import logging
import unicodedata
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta

from application.conversation.etat import DepotConversation, Etape, EtatConversation
from core.errors import AccesRefuse, CreneauIndisponible, HorsOuverture
from core.escalade import DepotEscalade, Escalade, MotifEscalade
from core.i18n.catalogue import Catalogue, catalogue
from core.i18n.dates import formater_datetime
from core.i18n.libelles import resoudre_libelle
from core.models.enums import Langue
from core.telephone import NumeroInvalide, normaliser
from core.temps import exiger_conscient
from verticals.school.calendar_school import PeriodeNonScolaire
from verticals.school.configuration import ConfigurationEcole
from verticals.school.depot import DepotEcole
from verticals.school.family import Identification, ServiceFamille
from verticals.school.interdits import SUJETS_A_ESCALADER, SujetInterdit, detecter_sujet_interdit
from verticals.school.rendez_vous import ServiceRendezVous
from verticals.school.rules import Perimetre

journal = logging.getLogger("ballan.agent")

#: Apres ce delai sans message, la conversation repart du menu.
DUREE_SESSION = timedelta(minutes=30)
#: Nombre maximal d'options numerotees dans une liste (un seul chiffre).
OPTIONS_MAX = 9

# Commandes reconnues dans toutes les langues, comparees apres normalisation
# (minuscules, sans accents). Ce ne sont pas des chaines lues par un parent :
# elles vivent dans le code, pas dans le catalogue.
_MENU = {
    "0", "menu", "accueil", "retour", "bonjour", "salut", "bonsoir", "salam", "salaam",
    "assalamu alaykum", "hello", "hi", "iska warran", "nabad", "مرحبا", "السلام عليكم",
    "سلام", "القائمة", "قائمة",
}
_STOP = {"stop", "arret", "arreter", "desabonner", "joogso", "jooji", "توقف", "ايقاف", "إيقاف"}
_START = {"start", "reprendre", "abonner", "bilow", "ابدأ", "ابدا"}
_LANGUE = {"langue", "language", "luqad", "luqadda", "afa", "لغة", "اللغة"}

_CHIFFRES_ARABES = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def normaliser_saisie(texte: str) -> str:
    """Minuscules, sans accents, chiffres occidentaux, espaces reduits.

    Les claviers arabes produisent souvent des chiffres arabo-indiens : un
    parent qui repond « ١ » a bien choisi l'option 1.
    """
    texte = (texte or "").translate(_CHIFFRES_ARABES).strip().lower()
    decompose = unicodedata.normalize("NFKD", texte)
    sans_accents = "".join(c for c in decompose if not unicodedata.combining(c))
    return " ".join(sans_accents.replace("!", " ").replace(".", " ").split())


def _choix(saisie: str) -> int | None:
    return int(saisie) if saisie.isdigit() and len(saisie) <= 2 else None


class Agent:
    """Traite un message entrant et rend les messages a renvoyer."""

    def __init__(
        self,
        etablissement_id: str,
        famille: ServiceFamille,
        rendez_vous: ServiceRendezVous,
        depot_ecole: DepotEcole,
        conversations: DepotConversation,
        escalades: DepotEscalade,
        cat: Catalogue | None = None,
        notifier_escalade: Callable[[Escalade], None] | None = None,
        duree_session: timedelta = DUREE_SESSION,
    ) -> None:
        self._etab_id = etablissement_id
        self._famille = famille
        self._rdv = rendez_vous
        self._depot = depot_ecole
        self._conversations = conversations
        self._escalades = escalades
        self._cat = cat or catalogue()
        self._notifier = notifier_escalade
        self._duree_session = duree_session

    # =================================================================
    # Point d'entree
    # =================================================================

    def traiter(
        self, numero: str, texte: str, maintenant: datetime, est_texte: bool = True
    ) -> list[str]:
        exiger_conscient(maintenant, "maintenant")
        conf = self._rdv.configuration()
        try:
            canonique = normaliser(numero)
        except NumeroInvalide:
            return [self._cat.t("acces.refuse", conf.etablissement.langue_defaut)]
        try:
            return self._traiter(conf, canonique, texte, maintenant, est_texte)
        except Exception as exc:  # noqa: BLE001 - un parent ne doit jamais rester sans reponse
            # Le type seul part au journal : jamais le texte du parent, ni le numero.
            journal.exception("incident de traitement : %s", type(exc).__name__)
            self._escalader(canonique, MotifEscalade.INCIDENT, maintenant)
            self._reinitialiser(canonique, maintenant)
            return [self._cat.t("agent.incident", conf.etablissement.langue_defaut)]

    def _traiter(
        self,
        conf: ConfigurationEcole,
        numero: str,
        texte: str,
        maintenant: datetime,
        est_texte: bool,
    ) -> list[str]:
        saisie = normaliser_saisie(texte)
        contact = self._depot.contact_par_numero(self._etab_id, numero)
        ident = self._famille.identifier(self._etab_id, numero)
        langue = self._langue(conf, ident, contact.langue_preferee if contact else None)

        # STOP et START valent pour tout numero connu, rattache ou non (§8.3).
        if saisie in _STOP:
            if contact is not None:
                self._depot.marquer_stop(contact.id, maintenant)
            return [self._t("consentement.stop", langue)]
        if saisie in _START and contact is not None:
            self._depot.marquer_consentement(contact.id, maintenant)
            return [self._t("consentement.reprise", langue)]

        # Un inconnu n'apprend rien, pas meme qu'un eleve est inscrit (§8.2).
        if not ident.est_rattache:
            self._escalader(numero, MotifEscalade.NUMERO_INCONNU, maintenant)
            return [self._t("acces.refuse", langue)]

        if not est_texte:
            return [self._t("agent.message_non_texte", langue)]

        etat = self._conversations.charger(self._etab_id, numero) or EtatConversation()
        if etat.maj_at is None or maintenant - etat.maj_at > self._duree_session:
            etat = EtatConversation()

        session = _Session(self, conf, ident, numero, langue, maintenant)
        try:
            reponses, etat = session.repondre(saisie, texte, etat)
        except AccesRefuse:
            # Lien retire en cours de conversation, ou id d'un autre enfant :
            # meme refus qu'un inconnu, et retour a zero.
            reponses, etat = [self._t("acces.refuse", langue)], EtatConversation()
        etat.maj_at = maintenant
        self._conversations.enregistrer(self._etab_id, numero, etat)
        return reponses

    # =================================================================
    # Outils partages avec la session
    # =================================================================

    def _t(self, cle: str, langue: Langue, **params) -> str:
        return self._cat.t(cle, langue, **params)

    def _langue(
        self, conf: ConfigurationEcole, ident: Identification, langue_contact: Langue | None
    ) -> Langue:
        etab = conf.etablissement
        if ident.est_rattache:
            return etab.langue_ou_defaut(
                self._famille.langue_du_perimetre(ident.perimetre, etab.langue_defaut)
            )
        return etab.langue_ou_defaut(langue_contact)

    def _escalader(self, numero: str, motif: MotifEscalade, maintenant: datetime) -> None:
        """Cree l'escalade si aucune n'est deja ouverte pour ce numero et ce motif."""
        if self._escalades.ouverte(self._etab_id, numero, motif) is not None:
            return
        escalade = self._escalades.creer(
            Escalade(
                id=str(uuid.uuid4()),
                etablissement_id=self._etab_id,
                numero=numero,
                motif=motif,
                cree_at=maintenant,
            )
        )
        journal.info("escalade creee : %s", motif.value)
        if self._notifier is not None:
            try:
                self._notifier(escalade)
            except Exception as exc:  # noqa: BLE001 - la notification est accessoire
                journal.warning("notification d'escalade impossible : %s", type(exc).__name__)

    def _reinitialiser(self, numero: str, maintenant: datetime) -> None:
        try:
            self._conversations.enregistrer(
                self._etab_id, numero, EtatConversation(maj_at=maintenant)
            )
        except Exception:  # noqa: BLE001 - deja en traitement d'incident
            pass


class _Session:
    """Le traitement d'un message, avec son contexte deja resolu."""

    def __init__(
        self,
        agent: Agent,
        conf: ConfigurationEcole,
        ident: Identification,
        numero: str,
        langue: Langue,
        maintenant: datetime,
    ) -> None:
        self.a = agent
        self.conf = conf
        self.ident = ident
        self.perimetre: Perimetre = ident.perimetre
        self.numero = numero
        self.langue = langue
        self.maintenant = maintenant
        self.tz = conf.etablissement.tz

    def t(self, cle: str, **params) -> str:
        return self.a._t(cle, self.langue, **params)

    # -- aiguillage ----------------------------------------------------

    def repondre(
        self, saisie: str, brut: str, etat: EtatConversation
    ) -> tuple[list[str], EtatConversation]:
        if saisie in _MENU:
            return self.menu(accueil=True)
        if saisie in _LANGUE:
            return self.proposer_langues()

        choix = _choix(saisie)
        if choix is None:
            sujet = detecter_sujet_interdit(brut)
            if sujet is not None:
                return self.sujet_interdit(sujet)
            if etat.etape is Etape.MENU:
                return self.menu(accueil=True)
            return [self.t("agent.choix_invalide")], etat

        gestionnaire = {
            Etape.MENU: self.au_menu,
            Etape.CHOIX_ENFANT: self.enfant_choisi,
            Etape.CHOIX_MOTIF: self.motif_choisi,
            Etape.CHOIX_CRENEAU: self.creneau_choisi,
            Etape.CONFIRMATION: self.confirmation,
            Etape.CHOIX_ANNULATION: self.annulation_choisie,
            Etape.CONFIRMATION_ANNULATION: self.confirmation_annulation,
            Etape.CHOIX_LANGUE: self.langue_choisie,
        }[etat.etape]
        return gestionnaire(choix, etat)

    # -- menu ----------------------------------------------------------

    def menu(self, accueil: bool = False) -> tuple[list[str], EtatConversation]:
        texte = self.t("agent.menu")
        if accueil:
            texte = self.t("agent.accueil", ecole=self.conf.etablissement.nom) + "\n\n" + texte
        return [texte], EtatConversation()

    def au_menu(self, choix: int, etat: EtatConversation):
        if choix == 1:
            return self.demarrer_rendez_vous()
        if choix == 2:
            return self.lister_rendez_vous()
        if choix == 3:
            self.a._escalader(self.numero, MotifEscalade.DEMANDE_PARENT, self.maintenant)
            return [self.t("escalade.transmis")], EtatConversation()
        if choix == 4:
            return self.proposer_langues()
        reponses, nouvel = self.menu()
        return [self.t("agent.choix_invalide"), *reponses], nouvel

    def sujet_interdit(self, sujet: SujetInterdit):
        if sujet in SUJETS_A_ESCALADER:
            self.a._escalader(self.numero, MotifEscalade.SUJET_SENSIBLE, self.maintenant)
            return [self.t("agent.sujet_escalade")], EtatConversation()
        cle = (
            "agent.sujet_resultats"
            if sujet is SujetInterdit.RESULTATS
            else "agent.sujet_comportement"
        )
        # On revient au menu : « 1 » y lance justement la prise de rendez-vous.
        return [self.t(cle)], EtatConversation()

    # -- prise de rendez-vous -----------------------------------------

    def demarrer_rendez_vous(self):
        eleves = self.ident.eleves[:OPTIONS_MAX]
        if len(eleves) == 1:
            return self.choisir_motif(eleves[0].id)
        lignes = [self.t("agent.choix_enfant")]
        for i, eleve in enumerate(eleves, start=1):
            classe = self.a._famille.classe_de(self.perimetre, eleve.id)
            lignes.append(
                self.t("agent.ligne_enfant", numero=i, prenom=eleve.prenom, classe=classe.libelle)
            )
        lignes.append(self.t("agent.retour_menu"))
        etat = EtatConversation(etape=Etape.CHOIX_ENFANT, options=[e.id for e in eleves])
        return ["\n".join(lignes)], etat

    def enfant_choisi(self, choix: int, etat: EtatConversation):
        eleve_id = _option(etat, choix)
        if eleve_id is None:
            return [self.t("agent.choix_invalide")], etat
        return self.choisir_motif(eleve_id)

    def choisir_motif(self, eleve_id: str):
        eleve = self.a._famille.eleve(self.perimetre, eleve_id)
        motifs = self.a._rdv.motifs()[:OPTIONS_MAX]
        if not motifs:
            self.a._escalader(self.numero, MotifEscalade.AUCUN_CRENEAU, self.maintenant)
            return [self.t("escalade.transmis")], EtatConversation()
        if len(motifs) == 1:
            return self.proposer_creneaux(eleve_id, motifs[0].id)
        lignes = [self.t("agent.choix_motif", prenom=eleve.prenom)]
        for i, motif in enumerate(motifs, start=1):
            libelle = resoudre_libelle(motif.libelle_i18n, self.langue)
            lignes.append(self.t("agent.ligne_option", numero=i, libelle=libelle))
        lignes.append(self.t("agent.retour_menu"))
        etat = EtatConversation(
            etape=Etape.CHOIX_MOTIF, eleve_id=eleve_id, options=[m.id for m in motifs]
        )
        return ["\n".join(lignes)], etat

    def motif_choisi(self, choix: int, etat: EtatConversation):
        motif_id = _option(etat, choix)
        if motif_id is None or etat.eleve_id is None:
            return [self.t("agent.choix_invalide")], etat
        return self.proposer_creneaux(etat.eleve_id, motif_id)

    def proposer_creneaux(self, eleve_id: str, motif_id: str, entete: str | None = None):
        propositions = self.a._rdv.proposer(self.perimetre, eleve_id, motif_id, self.maintenant)
        if not propositions:
            ressource_id = self.a._rdv.ressource_pour(self.perimetre, eleve_id, motif_id)
            self.a._escalader(self.numero, MotifEscalade.AUCUN_CRENEAU, self.maintenant)
            return (
                [self.t("agent.aucun_creneau", ressource=self._libelle_ressource(ressource_id))],
                EtatConversation(),
            )
        lignes = [entete] if entete else []
        lignes.append(self.t("agent.choix_creneau", ressource=propositions[0].ressource_libelle))
        for i, p in enumerate(propositions, start=1):
            lignes.append(
                self.t("agent.ligne_option", numero=i, libelle=self._date(p.creneau.debut))
            )
        lignes.append(self.t("agent.retour_menu"))
        etat = EtatConversation(
            etape=Etape.CHOIX_CRENEAU,
            eleve_id=eleve_id,
            motif_id=motif_id,
            options=[p.creneau.debut.isoformat() for p in propositions],
        )
        return ["\n".join(lignes)], etat

    def creneau_choisi(self, choix: int, etat: EtatConversation):
        debut = _option(etat, choix)
        if debut is None or etat.eleve_id is None or etat.motif_id is None:
            return [self.t("agent.choix_invalide")], etat
        eleve = self.a._famille.eleve(self.perimetre, etat.eleve_id)
        motif = self.conf.motif(etat.motif_id)
        ressource_id = self.a._rdv.ressource_pour(self.perimetre, etat.eleve_id, etat.motif_id)
        texte = self.t(
            "agent.confirmation",
            prenom=eleve.prenom,
            date=self._date(datetime.fromisoformat(debut)),
            ressource=self._libelle_ressource(ressource_id),
            motif=resoudre_libelle(motif.libelle_i18n, self.langue) if motif else "",
        )
        etat.etape = Etape.CONFIRMATION
        etat.selection = debut
        return [texte], etat

    def confirmation(self, choix: int, etat: EtatConversation):
        if etat.eleve_id is None or etat.motif_id is None or etat.selection is None:
            return self.menu()
        if choix == 2:
            return self.proposer_creneaux(etat.eleve_id, etat.motif_id)
        if choix != 1:
            return [self.t("agent.choix_invalide")], etat
        try:
            rdv = self.a._rdv.reserver(
                self.perimetre,
                etat.eleve_id,
                etat.motif_id,
                datetime.fromisoformat(etat.selection),
                self.maintenant,
            )
        except (CreneauIndisponible, HorsOuverture, PeriodeNonScolaire):
            return self.proposer_creneaux(
                etat.eleve_id, etat.motif_id, entete=self.t("agent.creneau_pris")
            )
        eleve = self.a._famille.eleve(self.perimetre, rdv.eleve_id)
        texte = self.t(
            "agent.rdv_confirme",
            prenom=eleve.prenom,
            date=self._date(rdv.debut),
            ressource=self._libelle_ressource(rdv.ressource_id),
        )
        return [texte], EtatConversation()

    # -- consultation et annulation -----------------------------------

    def lister_rendez_vous(self):
        rdvs = self.a._rdv.a_venir(self.perimetre, self.maintenant)[:OPTIONS_MAX]
        if not rdvs:
            return [self.t("agent.aucun_rdv") + "\n" + self.t("agent.retour_menu")], (
                EtatConversation()
            )
        lignes = [self.t("agent.liste_rdv")]
        for i, rdv in enumerate(rdvs, start=1):
            eleve = self.a._famille.eleve(self.perimetre, rdv.eleve_id)
            lignes.append(
                self.t(
                    "agent.ligne_rdv",
                    numero=i,
                    prenom=eleve.prenom,
                    date=self._date(rdv.debut),
                    ressource=self._libelle_ressource(rdv.ressource_id),
                )
            )
        lignes.append(self.t("agent.retour_menu"))
        return ["\n".join(lignes)], EtatConversation(
            etape=Etape.CHOIX_ANNULATION, options=[r.id for r in rdvs]
        )

    def annulation_choisie(self, choix: int, etat: EtatConversation):
        rdv_id = _option(etat, choix)
        if rdv_id is None:
            return [self.t("agent.choix_invalide")], etat
        rdv = self.a._rdv.rendez_vous(self.perimetre, rdv_id)
        eleve = self.a._famille.eleve(self.perimetre, rdv.eleve_id)
        texte = self.t(
            "agent.confirmation_annulation", prenom=eleve.prenom, date=self._date(rdv.debut)
        )
        return [texte], EtatConversation(etape=Etape.CONFIRMATION_ANNULATION, selection=rdv_id)

    def confirmation_annulation(self, choix: int, etat: EtatConversation):
        if etat.selection is None:
            return self.menu()
        if choix == 2:
            return [self.t("agent.rdv_conserve")], EtatConversation()
        if choix != 1:
            return [self.t("agent.choix_invalide")], etat
        rdv = self.a._rdv.annuler(self.perimetre, etat.selection)
        eleve = self.a._famille.eleve(self.perimetre, rdv.eleve_id)
        return (
            [self.t("agent.rdv_annule", prenom=eleve.prenom, date=self._date(rdv.debut))],
            EtatConversation(),
        )

    # -- langue --------------------------------------------------------

    def _langues(self) -> list[Langue]:
        return [lg for lg in Langue if lg in self.conf.etablissement.langues_actives]

    def proposer_langues(self):
        langues = self._langues()
        lignes = [self.t("agent.choix_langue")]
        for i, langue in enumerate(langues, start=1):
            nom = self.a._t("langue.nom", langue)
            lignes.append(self.t("agent.ligne_option", numero=i, libelle=nom))
        return ["\n".join(lignes)], EtatConversation(
            etape=Etape.CHOIX_LANGUE, options=[lg.value for lg in langues]
        )

    def langue_choisie(self, choix: int, etat: EtatConversation):
        code = _option(etat, choix)
        if code is None:
            return [self.t("agent.choix_invalide")], etat
        langue = Langue(code)
        if self.perimetre.contact_id is not None:
            self.a._depot.definir_langue_contact(self.perimetre.contact_id, langue)
        self.langue = langue
        confirme = self.t("agent.langue_changee")
        reponses, nouvel = self.menu()
        return [confirme, *reponses], nouvel

    # -- mise en forme -------------------------------------------------

    def _date(self, instant: datetime) -> str:
        return formater_datetime(instant.astimezone(self.tz), self.langue, self.a._cat)

    def _libelle_ressource(self, ressource_id: str) -> str:
        ressource = self.conf.ressource(ressource_id)
        return ressource.libelle if ressource else ""


def _option(etat: EtatConversation, choix: int) -> str | None:
    if 1 <= choix <= len(etat.options):
        return etat.options[choix - 1]
    return None
