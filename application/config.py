"""Reglages du service, lus depuis l'environnement (fichier ``.env`` en Docker).

Aucun secret dans le depot : ``.env.example`` liste les variables, le vrai
``.env`` reste sur le serveur de l'ecole. En mode ``production``, un reglage
obligatoire manquant empeche le demarrage plutot que de produire un service
a moitie fonctionnel.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from core.errors import ErreurConfiguration

MODES = ("production", "demo")

#: Longueur minimale des secrets generes par l'ecole (jeton d'administration,
#: jeton de verification du webhook).
LONGUEUR_SECRET_MIN = 24


def _bool(valeur: str | None) -> bool:
    return (valeur or "").strip().lower() in {"1", "true", "oui", "yes", "on"}


@dataclass(frozen=True)
class Reglages:
    mode: str = "demo"
    database_url: str | None = None
    etablissement_id: str | None = None

    # WhatsApp Cloud API (Meta)
    wa_token: str | None = field(default=None, repr=False)
    wa_phone_number_id: str | None = None
    wa_app_secret: str | None = field(default=None, repr=False)
    wa_verify_token: str | None = field(default=None, repr=False)
    wa_api_version: str = "v23.0"
    #: Modele (template) approuve par Meta pour les rappels : obligatoire pour
    #: ecrire a un parent hors de la fenetre de 24 h.
    wa_template_rappel: str | None = None

    #: Mot de passe du tableau de bord secretariat et jeton de l'API admin.
    admin_token: str | None = field(default=None, repr=False)
    #: Numero WhatsApp du secretariat, prevenu a chaque escalade (facultatif).
    numero_secretariat: str | None = None

    autoriser_langues_non_relues: bool = False
    niveau_journal: str = "INFO"
    docs_api: bool = False
    taille_pool: int = 10

    @classmethod
    def depuis_environnement(cls, env: Mapping[str, str] | None = None) -> Reglages:
        env = os.environ if env is None else env
        reglages = cls(
            mode=env.get("BALLAN_MODE", "demo").strip().lower(),
            database_url=env.get("BALLAN_DATABASE_URL") or None,
            etablissement_id=env.get("BALLAN_ETABLISSEMENT_ID") or None,
            wa_token=env.get("WHATSAPP_TOKEN") or None,
            wa_phone_number_id=env.get("WHATSAPP_PHONE_NUMBER_ID") or None,
            wa_app_secret=env.get("WHATSAPP_APP_SECRET") or None,
            wa_verify_token=env.get("WHATSAPP_VERIFY_TOKEN") or None,
            wa_api_version=env.get("WHATSAPP_API_VERSION", "v23.0"),
            wa_template_rappel=env.get("WHATSAPP_TEMPLATE_RAPPEL") or None,
            admin_token=env.get("BALLAN_ADMIN_TOKEN") or None,
            numero_secretariat=env.get("BALLAN_NUMERO_SECRETARIAT") or None,
            autoriser_langues_non_relues=_bool(env.get("BALLAN_AUTORISER_LANGUES_NON_RELUES")),
            niveau_journal=env.get("BALLAN_NIVEAU_JOURNAL", "INFO").upper(),
            docs_api=_bool(env.get("BALLAN_DOCS_API")),
            taille_pool=int(env.get("BALLAN_TAILLE_POOL", "10")),
        )
        reglages.verifier()
        return reglages

    @property
    def est_production(self) -> bool:
        return self.mode == "production"

    @property
    def whatsapp_configure(self) -> bool:
        return bool(self.wa_token and self.wa_phone_number_id and self.wa_app_secret)

    def manquants(self) -> list[str]:
        """Reglages obligatoires absents en production."""
        if not self.est_production:
            return []
        obligatoires = {
            "BALLAN_DATABASE_URL": self.database_url,
            "BALLAN_ETABLISSEMENT_ID": self.etablissement_id,
            "BALLAN_ADMIN_TOKEN": self.admin_token,
            "WHATSAPP_TOKEN": self.wa_token,
            "WHATSAPP_PHONE_NUMBER_ID": self.wa_phone_number_id,
            "WHATSAPP_APP_SECRET": self.wa_app_secret,
            "WHATSAPP_VERIFY_TOKEN": self.wa_verify_token,
        }
        return [nom for nom, valeur in obligatoires.items() if not valeur]

    def verifier(self) -> None:
        if self.mode not in MODES:
            raise ErreurConfiguration(f"BALLAN_MODE doit valoir {' ou '.join(MODES)}")
        manquants = self.manquants()
        if manquants:
            raise ErreurConfiguration(f"reglages obligatoires manquants : {', '.join(manquants)}")
        if self.est_production:
            for nom, valeur in (
                ("BALLAN_ADMIN_TOKEN", self.admin_token),
                ("WHATSAPP_VERIFY_TOKEN", self.wa_verify_token),
            ):
                if valeur and len(valeur) < LONGUEUR_SECRET_MIN:
                    raise ErreurConfiguration(
                        f"{nom} trop court (minimum {LONGUEUR_SECRET_MIN} caracteres)"
                    )
