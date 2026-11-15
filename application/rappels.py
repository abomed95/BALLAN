"""Rappels de rendez-vous (lot 5).

Lance periodiquement (``ballan rappels --boucle 1800``). Pour chaque
rendez-vous confirme qui commence dans la fenetre [maintenant + 2 h,
maintenant + 26 h[ et n'a pas encore ete rappele :

1. rien ne part pendant la fenetre de silence de l'ecole (21:00 -> 07:00
   par defaut) — le rappel partira au passage suivant ;
2. le contact qui a pris le rendez-vous doit avoir consenti aux envois et ne
   pas avoir repondu STOP (§8.3) ;
3. le lien familial est **reverifie** : un parent retire de la famille
   depuis la reservation ne recoit plus rien sur l'enfant ;
4. hors de la fenetre de 24 h de WhatsApp, seul un modele approuve par Meta
   peut partir : sans ``WHATSAPP_TEMPLATE_RAPPEL``, on tente le texte libre,
   qui ne passera que si le parent a ecrit dans les dernieres 24 h.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from application.whatsapp.client import ErreurEnvoi, Messagerie
from core.i18n.catalogue import Catalogue, catalogue
from core.i18n.dates import formater_datetime
from core.temps import exiger_conscient
from verticals.school.configuration import DepotConfiguration
from verticals.school.depot import DepotEcole
from verticals.school.family import ServiceFamille
from verticals.school.rendez_vous import DepotRendezVous

journal = logging.getLogger("ballan.rappels")

DELAI_MIN = timedelta(hours=2)
DELAI_MAX = timedelta(hours=26)


@dataclass(frozen=True)
class BilanRappels:
    envoyes: int = 0
    sans_consentement: int = 0
    lien_rompu: int = 0
    echecs: int = 0
    silence: bool = False


class ServiceRappels:
    def __init__(
        self,
        etablissement_id: str,
        configuration: DepotConfiguration,
        rendez_vous: DepotRendezVous,
        depot_ecole: DepotEcole,
        famille: ServiceFamille,
        messagerie: Messagerie,
        modele: str | None = None,
        cat: Catalogue | None = None,
    ) -> None:
        self._etab = etablissement_id
        self._configuration = configuration
        self._rdv = rendez_vous
        self._depot = depot_ecole
        self._famille = famille
        self._messagerie = messagerie
        self._modele = modele
        self._cat = cat or catalogue()

    def envoyer(self, maintenant: datetime) -> BilanRappels:
        exiger_conscient(maintenant, "maintenant")
        conf = self._configuration.configuration(self._etab)
        tz = conf.etablissement.tz
        if conf.etablissement.silence.couvre(maintenant.astimezone(tz).time()):
            return BilanRappels(silence=True)

        envoyes = sans_consentement = lien_rompu = echecs = 0
        for rdv in self._rdv.a_rappeler(self._etab, maintenant + DELAI_MIN, maintenant + DELAI_MAX):
            contact = self._depot.contact(rdv.contact_id) if rdv.contact_id else None
            if contact is None or not contact.accepte_envois:
                sans_consentement += 1
                continue
            perimetre = self._famille.perimetre_du_contact(self._etab, contact.id)
            if not perimetre.couvre(rdv.eleve_id):
                lien_rompu += 1
                continue
            eleve = self._famille.eleve(perimetre, rdv.eleve_id)
            langue = conf.etablissement.langue_ou_defaut(
                self._famille.langue_du_perimetre(perimetre, conf.etablissement.langue_defaut)
            )
            ressource = conf.ressource(rdv.ressource_id)
            date = formater_datetime(rdv.debut.astimezone(tz), langue, self._cat)
            libelle = ressource.libelle if ressource else ""
            try:
                if self._modele:
                    self._messagerie.envoyer_modele(
                        contact.numero, self._modele, langue.value, [eleve.prenom, date, libelle]
                    )
                else:
                    self._messagerie.envoyer_texte(
                        contact.numero,
                        self._cat.t("rappel.rendez_vous", langue, prenom=eleve.prenom,
                                    date=date, ressource=libelle),
                    )
            except ErreurEnvoi as exc:
                echecs += 1
                journal.warning("rappel non envoye : %s", exc)
                continue
            self._rdv.marquer_rappel(rdv.id, maintenant)
            envoyes += 1
        bilan = BilanRappels(envoyes, sans_consentement, lien_rompu, echecs)
        journal.info("rappels : %s", bilan)
        return bilan
