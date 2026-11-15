"""Ligne de commande ``ballan``.

    ballan verifier                       controle la configuration avant mise en service
    ballan migrer                         applique les migrations manquantes
    ballan importer ecole.json [familles.csv] [--essai] [--garder-absents]
    ballan servir [--hote 0.0.0.0] [--port 8000]
    ballan rappels [--boucle SECONDES]    envoie les rappels J-1 (une fois, ou en boucle)
    ballan purger [--jours 30]            efface etats de conversation et anti-doublons anciens
    ballan simuler [--numero +253...]     conversation de demonstration dans le terminal
    ballan secret                         genere un secret pour BALLAN_ADMIN_TOKEN

Toutes les commandes lisent leurs reglages dans l'environnement (voir
``.env.example``).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from application.config import Reglages
from application.journal import configurer_journal
from core.errors import ErreurBallan

journal = logging.getLogger("ballan.cli")


def _reglages() -> Reglages:
    return Reglages.depuis_environnement()


def _dsn() -> str:
    dsn = _environnement().get("BALLAN_DATABASE_URL")
    if not dsn:
        raise ErreurBallan("BALLAN_DATABASE_URL n'est pas defini")
    return dsn


# -- commandes ---------------------------------------------------------


def cmd_migrer(_args) -> int:
    from application.persistance.migrations import appliquer_migrations

    # Les migrations precedent l'import, donc BALLAN_ETABLISSEMENT_ID : seule
    # l'adresse de la base est exigee ici.
    appliquees = appliquer_migrations(_dsn())
    print("migrations appliquees : " + (", ".join(appliquees) if appliquees else "aucune"))
    return 0


def cmd_importer(args) -> int:
    from application.importation import charger_fichiers, ecrire_postgres

    maintenant = datetime.now(UTC)
    donnees = charger_fichiers(
        Path(args.ecole), Path(args.familles) if args.familles else None, maintenant
    )
    print(f"etablissement : {donnees.configuration.etablissement.nom}")
    print(f"identifiant   : {donnees.etablissement_id}  (a mettre dans BALLAN_ETABLISSEMENT_ID)")
    if args.essai:
        print("essai, rien n'est ecrit : " + json.dumps(donnees.resume()))
        return 0
    # L'import n'a besoin que de la base : pas de controle des reglages WhatsApp.
    resume = ecrire_postgres(
        _dsn(),
        donnees,
        marquer_sortis=not args.garder_absents,
    )
    print("importe : " + json.dumps(resume))
    print("pensez a recharger la configuration : POST /admin/configuration/recharger")
    return 0


def _environnement() -> dict[str, str]:
    import os

    return dict(os.environ)


def cmd_servir(args) -> int:
    import uvicorn

    from application.api import creer_app
    from application.conteneur import construire_conteneur

    reglages = _reglages()
    app = creer_app(construire_conteneur(reglages))
    uvicorn.run(app, host=args.hote, port=args.port, log_config=None, proxy_headers=True,
                forwarded_allow_ips="*")
    return 0


def cmd_rappels(args) -> int:
    from application.conteneur import construire_conteneur

    conteneur = construire_conteneur(_reglages())
    try:
        while True:
            bilan = conteneur.rappels.envoyer(datetime.now(UTC))
            print(json.dumps(bilan.__dict__))
            if not args.boucle:
                return 0
            time.sleep(args.boucle)
    finally:
        conteneur.fermer()


def cmd_purger(args) -> int:
    from application.conteneur import construire_conteneur

    conteneur = construire_conteneur(_reglages())
    try:
        if conteneur.purger is None:
            print("rien a purger en mode demonstration")
            return 0
        print(json.dumps(conteneur.purger(datetime.now(UTC) - timedelta(days=args.jours))))
        return 0
    finally:
        conteneur.fermer()


def cmd_verifier(_args) -> int:
    """Liste de controle de mise en service. Sort 1 au premier point bloquant."""
    ok = True

    def point(etat: bool, texte: str, bloquant: bool = True) -> None:
        nonlocal ok
        print(f"[{'ok' if etat else ('KO' if bloquant else '!!')}] {texte}")
        ok = ok and (etat or not bloquant)

    try:
        reglages = _reglages()
    except ErreurBallan as exc:
        point(False, f"reglages : {exc}")
        return 1
    point(True, f"mode {reglages.mode}")
    point(reglages.whatsapp_configure, "WhatsApp configure", bloquant=reglages.est_production)
    point(bool(reglages.wa_template_rappel),
          "modele de rappel WhatsApp (WHATSAPP_TEMPLATE_RAPPEL)", bloquant=False)
    point(bool(reglages.numero_secretariat),
          "numero du secretariat pour les alertes (BALLAN_NUMERO_SECRETARIAT)", bloquant=False)
    if reglages.database_url:
        from application.conteneur import conteneur_production
        from application.persistance.migrations import fichiers_migration

        try:
            conteneur = conteneur_production(reglages)
        except Exception as exc:  # noqa: BLE001 - diagnostic
            point(False, f"base de donnees : {type(exc).__name__}: {exc}")
            return 1
        try:
            import psycopg

            with psycopg.connect(reglages.database_url) as conn:
                faites = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
            manquantes = [f.stem for f in fichiers_migration() if f.stem not in faites]
            point(not manquantes, "migrations a jour" + (f" (manquent {manquantes})"
                                                         if manquantes else ""))
            conf = conteneur.rendez_vous.configuration()
            point(True, f"ecole : {conf.etablissement.nom}, annee {conf.annee.libelle}")
            point(bool(conf.motifs_actifs()), "au moins un motif de rendez-vous actif")
            point(bool(conf.disponibilites), "au moins une disponibilite saisie")
            non_relues = conteneur.verifier_langues()
            point(not non_relues or reglages.autoriser_langues_non_relues,
                  "langues actives relues" + (
                      f" (a relire : {', '.join(lg.value for lg in non_relues)})"
                      if non_relues else ""))
        except Exception as exc:  # noqa: BLE001 - diagnostic
            point(False, f"{type(exc).__name__}: {exc}")
        finally:
            conteneur.fermer()
    else:
        point(not reglages.est_production, "BALLAN_DATABASE_URL (mode demonstration sinon)")
    return 0 if ok else 1


def cmd_simuler(args) -> int:
    """Le produit tel qu'un parent le vit, sans WhatsApp ni base de donnees."""
    from application.conteneur import conteneur_demo

    conteneur = conteneur_demo()
    nom = conteneur.rendez_vous.configuration().etablissement.nom
    print(f"Simulation BALLAN — {nom} (donnees d'exemple, rien n'est enregistre)")
    print(f"Vous ecrivez depuis le {args.numero}. Ctrl-D pour quitter.")
    print("Autres numeros d'exemple : +25377202020 (un enfant), +25377999999 (inconnu)\n")
    while True:
        try:
            texte = input("vous > ")
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        for reponse in conteneur.agent.traiter(args.numero, texte, datetime.now(UTC)):
            print("\nballan >\n" + reponse + "\n")


def cmd_secret(_args) -> int:
    from application.api.securite import nouveau_secret

    print(nouveau_secret())
    return 0


# -- point d'entree ----------------------------------------------------


def analyseur() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ballan", description="BALLAN — AMD Digital")
    s = p.add_subparsers(dest="commande", required=True)
    s.add_parser("verifier", help="controle de mise en service").set_defaults(f=cmd_verifier)
    s.add_parser("migrer", help="applique les migrations").set_defaults(f=cmd_migrer)
    i = s.add_parser("importer", help="importe la configuration et les familles")
    i.add_argument("ecole")
    i.add_argument("familles", nargs="?")
    i.add_argument("--essai", action="store_true", help="valide sans rien ecrire")
    i.add_argument("--garder-absents", action="store_true",
                   help="ne pas passer en 'sorti' les eleves absents du CSV")
    i.set_defaults(f=cmd_importer)
    v = s.add_parser("servir", help="lance l'API")
    v.add_argument("--hote", default="0.0.0.0")
    v.add_argument("--port", type=int, default=8000)
    v.set_defaults(f=cmd_servir)
    r = s.add_parser("rappels", help="envoie les rappels")
    r.add_argument("--boucle", type=int, default=0, help="periode en secondes (0 = une fois)")
    r.set_defaults(f=cmd_rappels)
    u = s.add_parser("purger", help="efface les donnees de conversation anciennes")
    u.add_argument("--jours", type=int, default=30)
    u.set_defaults(f=cmd_purger)
    m = s.add_parser("simuler", help="conversation de demonstration")
    m.add_argument("--numero", default="+25377101010")
    m.set_defaults(f=cmd_simuler)
    s.add_parser("secret", help="genere un secret").set_defaults(f=cmd_secret)
    return p


def main(argv: list[str] | None = None) -> int:
    args = analyseur().parse_args(argv)
    if args.commande != "simuler":
        configurer_journal(_environnement().get("BALLAN_NIVEAU_JOURNAL", "INFO"))
    else:
        logging.basicConfig(level="WARNING")
    try:
        return args.f(args)
    except ErreurBallan as exc:
        print(f"erreur : {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
