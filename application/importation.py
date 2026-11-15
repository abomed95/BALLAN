"""Import d'une ecole : configuration (JSON) et familles (CSV).

C'est l'outil de mise en service d'une ecole cliente. Le secretariat tient
deja ses listes dans un tableur : on lui demande un export CSV, pas une
saisie de plus.

* ``ecole.json`` — etablissement, annee, periodes, niveaux, enseignants et
  leurs disponibilites, classes, motifs, fermetures (voir
  ``exemples/ecole.exemple.json``) ;
* ``familles.csv`` — une ligne par eleve, jusqu'a deux parents (voir
  ``exemples/familles.exemple.csv``). Separateur ``;`` ou ``,``, UTF-8 avec
  ou sans BOM (export Excel).

**Idempotence.** Chaque identifiant est un uuid5 derive de la cle de
l'ecole et d'une cle metier (identifiant interne de l'eleve, cle de classe,
famille + lien du parent). Re-importer le meme fichier ne change rien ;
re-importer un fichier corrige met a jour.

**Le CSV fait foi pour les liens familiaux.** A chaque import, les liens
parent-eleve des eleves presents sont reconstruits a partir du fichier : un
numero retire du fichier perd l'acces des l'import suivant. C'est le circuit
du secretariat pour changer un numero (§8.2), jamais l'agent.

Les erreurs citent une ligne et une colonne, jamais un nom d'enfant.
"""

from __future__ import annotations

import csv
import io
import json
import unicodedata
import uuid
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

from core.errors import ErreurBallan
from core.models.agenda import Disponibilite, ExceptionAgenda
from core.models.contact import Contact
from core.models.enums import Jour, Langue, TypeException
from core.models.etablissement import Etablissement, FenetreSilence, Ressource
from core.telephone import NumeroInvalide, normaliser
from verticals.school.configuration import ConfigurationEcole, DepotConfigurationMemoire
from verticals.school.depot import DepotEcoleMemoire
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
    TypePeriode,
)

#: Espace de noms des uuid5 BALLAN. Ne jamais le changer : tous les
#: identifiants deja en base en dependent.
ESPACE_BALLAN = uuid.UUID("6b1f6a52-2f0e-4f7e-9a39-6c2a1b0a5a11")

_JOURS = {
    "lundi": Jour.LUNDI, "mardi": Jour.MARDI, "mercredi": Jour.MERCREDI,
    "jeudi": Jour.JEUDI, "vendredi": Jour.VENDREDI, "samedi": Jour.SAMEDI,
    "dimanche": Jour.DIMANCHE,
}
_LIENS = {"pere": LienParente.PERE, "mere": LienParente.MERE, "tuteur": LienParente.TUTEUR,
          "tutrice": LienParente.TUTEUR}
_OUI = {"oui", "o", "yes", "y", "1", "x", "vrai", "true"}


class ErreurImport(ErreurBallan):
    code = "import.invalide"


def identifiant(cle_etab: str, *parties: str) -> str:
    return str(uuid.uuid5(ESPACE_BALLAN, "/".join((cle_etab, *parties))))


def _norm(texte: str) -> str:
    decompose = unicodedata.normalize("NFKD", (texte or "").strip().lower())
    return "".join(c for c in decompose if not unicodedata.combining(c))


@dataclass
class DonneesEcole:
    """Tout ce qu'un import produit, en objets du domaine."""

    cle: str
    configuration: ConfigurationEcole
    niveaux: list[Niveau] = field(default_factory=list)
    enseignants: list[Enseignant] = field(default_factory=list)
    classes: list[Classe] = field(default_factory=list)
    familles: list[Famille] = field(default_factory=list)
    contacts: list[Contact] = field(default_factory=list)
    parents: list[Parent] = field(default_factory=list)
    eleves: list[Eleve] = field(default_factory=list)
    liens: list[LienParentEleve] = field(default_factory=list)

    @property
    def etablissement_id(self) -> str:
        return self.configuration.etablissement.id

    def resume(self) -> dict[str, int]:
        return {
            "enseignants": len(self.enseignants),
            "classes": len(self.classes),
            "motifs": len(self.configuration.motifs),
            "familles": len(self.familles),
            "parents": len(self.parents),
            "eleves": len(self.eleves),
            "liens": len(self.liens),
        }

    def vers_memoire(self) -> tuple[DepotEcoleMemoire, DepotConfigurationMemoire]:
        depot = DepotEcoleMemoire(
            contacts=self.contacts, familles=self.familles, parents=self.parents,
            liens=self.liens, eleves=self.eleves, classes=self.classes, niveaux=self.niveaux,
            enseignants=self.enseignants, annees=[self.configuration.annee],
            periodes=self.configuration.periodes,
        )
        return depot, DepotConfigurationMemoire(self.configuration)


# =====================================================================
# Lecture
# =====================================================================


def charger_fichiers(
    chemin_ecole: Path, chemin_familles: Path | None, maintenant: datetime
) -> DonneesEcole:
    ecole = json.loads(chemin_ecole.read_text(encoding="utf-8"))
    familles = chemin_familles.read_text(encoding="utf-8-sig") if chemin_familles else None
    return construire(ecole, familles, maintenant)


def _date(valeur: Any, contexte: str) -> date:
    try:
        return date.fromisoformat(str(valeur))
    except ValueError as exc:
        raise ErreurImport(f"{contexte} : date attendue au format AAAA-MM-JJ") from exc


def _heure(valeur: Any, contexte: str) -> time:
    try:
        return time.fromisoformat(str(valeur))
    except ValueError as exc:
        raise ErreurImport(f"{contexte} : heure attendue au format HH:MM") from exc


def _langues(valeurs: Any, contexte: str) -> frozenset[Langue]:
    try:
        return frozenset(Langue(v) for v in (valeurs or []))
    except ValueError as exc:
        raise ErreurImport(f"{contexte} : langue inconnue (fr, ar, so, aa)") from exc


def _exiger(d: dict[str, Any], cle: str, contexte: str) -> Any:
    if cle not in d or d[cle] in (None, ""):
        raise ErreurImport(f"{contexte} : champ obligatoire manquant « {cle} »")
    return d[cle]


def construire(
    ecole: dict[str, Any], familles_csv: str | None, maintenant: datetime
) -> DonneesEcole:
    try:
        return _construire(ecole, familles_csv, maintenant)
    except ErreurImport:
        raise
    except ErreurBallan as exc:
        raise ErreurImport(f"donnee incoherente : {exc}") from exc


def _construire(
    ecole: dict[str, Any], familles_csv: str | None, maintenant: datetime
) -> DonneesEcole:
    e = _exiger(ecole, "etablissement", "fichier")
    cle = str(_exiger(e, "cle", "etablissement"))
    etab_id = identifiant(cle, "etablissement")

    def ident(*parties: str) -> str:
        return identifiant(cle, *parties)

    langues = _langues(e.get("langues_actives", ["fr"]), "etablissement.langues_actives")
    jours = e.get("jours_ouvres", ["dimanche", "lundi", "mardi", "mercredi", "jeudi"])
    try:
        jours_ouvres = frozenset(_JOURS[_norm(j)] for j in jours)
    except KeyError as exc:
        raise ErreurImport("etablissement.jours_ouvres : jour inconnu") from exc
    silence = e.get("silence", {})
    etablissement = Etablissement(
        id=etab_id,
        nom=_exiger(e, "nom", "etablissement"),
        fuseau_nom=e.get("fuseau", "Africa/Djibouti"),
        langues_actives=langues,
        langue_defaut=Langue(e.get("langue_defaut", "fr")),
        jours_ouvres=jours_ouvres,
        silence=FenetreSilence(
            _heure(silence.get("debut", "21:00"), "silence.debut"),
            _heure(silence.get("fin", "07:00"), "silence.fin"),
        ),
        devise=e.get("devise", "FDJ"),
        delai_minimal_min=int(e.get("delai_minimal_min", 0)),
    )

    a = _exiger(ecole, "annee", "fichier")
    libelle_annee = str(_exiger(a, "libelle", "annee"))
    annee = AnneeScolaire(
        id=ident("annee", libelle_annee),
        etablissement_id=etab_id,
        libelle=libelle_annee,
        date_debut=_date(_exiger(a, "debut", "annee"), "annee.debut"),
        date_fin=_date(_exiger(a, "fin", "annee"), "annee.fin"),
        active=True,
    )

    periodes = []
    for i, p in enumerate(ecole.get("periodes", []), start=1):
        ctx = f"periodes[{i}]"
        try:
            type_periode = TypePeriode(_exiger(p, "type", ctx))
        except ValueError as exc:
            raise ErreurImport(f"{ctx} : type inconnu") from exc
        periodes.append(Periode(
            id=ident("periode", libelle_annee, str(_exiger(p, "cle", ctx))),
            annee_scolaire_id=annee.id,
            libelle_i18n=_exiger(p, "libelle", ctx),
            type=type_periode,
            date_debut=_date(_exiger(p, "debut", ctx), f"{ctx}.debut"),
            date_fin=_date(_exiger(p, "fin", ctx), f"{ctx}.fin"),
        ))

    niveaux: dict[str, Niveau] = {}
    for i, n in enumerate(ecole.get("niveaux", []), start=1):
        ctx = f"niveaux[{i}]"
        cle_niveau = str(_exiger(n, "cle", ctx))
        niveaux[cle_niveau] = Niveau(
            id=ident("niveau", cle_niveau), etablissement_id=etab_id,
            libelle_i18n=_exiger(n, "libelle", ctx), ordre=int(n.get("ordre", i)),
        )

    ressources: dict[str, Ressource] = {}
    enseignants: dict[str, Enseignant] = {}
    disponibilites: list[Disponibilite] = []

    def lire_dispos(cle_ressource: str, ressource_id: str, liste: list, ctx: str) -> None:
        for j, d in enumerate(liste or [], start=1):
            c = f"{ctx}.disponibilites[{j}]"
            try:
                jour = _JOURS[_norm(_exiger(d, "jour", c))]
            except KeyError as exc:
                raise ErreurImport(f"{c} : jour inconnu") from exc
            disponibilites.append(Disponibilite(
                id=ident("disponibilite", cle_ressource, str(j)),
                etablissement_id=etab_id, ressource_id=ressource_id, jour=jour,
                heure_debut=_heure(_exiger(d, "debut", c), c),
                heure_fin=_heure(_exiger(d, "fin", c), c),
            ))

    for i, en in enumerate(ecole.get("enseignants", []), start=1):
        ctx = f"enseignants[{i}]"
        cle_ens = str(_exiger(en, "cle", ctx))
        ens = Enseignant(
            id=ident("ressource", cle_ens), etablissement_id=etab_id,
            nom=_exiger(en, "nom", ctx), matieres=tuple(en.get("matieres", [])),
            langues=_langues(en.get("langues"), ctx),
            duree_creneau_min=int(en.get("duree_creneau_min", 30)),
            actif=bool(en.get("actif", True)),
        )
        enseignants[cle_ens] = ens
        ressources[cle_ens] = ens.vers_ressource()
        lire_dispos(cle_ens, ens.id, en.get("disponibilites", []), ctx)

    for i, r in enumerate(ecole.get("ressources", []), start=1):
        ctx = f"ressources[{i}]"
        cle_r = str(_exiger(r, "cle", ctx))
        if cle_r in ressources:
            raise ErreurImport(f"{ctx} : cle deja utilisee par un enseignant")
        ressources[cle_r] = Ressource(
            id=ident("ressource", cle_r), etablissement_id=etab_id,
            libelle=_exiger(r, "libelle", ctx),
            duree_creneau_min=int(r.get("duree_creneau_min", 30)),
            langues=_langues(r.get("langues"), ctx), actif=bool(r.get("actif", True)),
        )
        lire_dispos(cle_r, ressources[cle_r].id, r.get("disponibilites", []), ctx)

    classes: dict[str, Classe] = {}
    classes_par_libelle: dict[str, Classe] = {}
    for i, c in enumerate(ecole.get("classes", []), start=1):
        ctx = f"classes[{i}]"
        cle_classe = str(_exiger(c, "cle", ctx))
        niveau = niveaux.get(str(_exiger(c, "niveau", ctx)))
        if niveau is None:
            raise ErreurImport(f"{ctx} : niveau inconnu")
        principal = c.get("enseignant_principal")
        if principal is not None and principal not in enseignants:
            raise ErreurImport(f"{ctx} : enseignant principal inconnu")
        classe = Classe(
            id=ident("classe", libelle_annee, cle_classe), etablissement_id=etab_id,
            niveau_id=niveau.id, annee_scolaire_id=annee.id,
            libelle=_exiger(c, "libelle", ctx),
            enseignant_principal_id=enseignants[principal].id if principal else None,
        )
        classes[cle_classe] = classe
        classes_par_libelle[_norm(classe.libelle)] = classe

    # Les enseignants connaissent leurs classes (table enseignant_classe).
    for cle_ens, ens in list(enseignants.items()):
        rattachees = tuple(
            classes[k].id for k in ecole_classes_de(ecole, cle_ens) if k in classes
        )
        enseignants[cle_ens] = replace(ens, classes=rattachees)

    motifs = []
    for i, m in enumerate(ecole.get("motifs", []), start=1):
        ctx = f"motifs[{i}]"
        try:
            destinataire = DestinataireRendezVous(m.get("destinataire", "enseignant"))
        except ValueError as exc:
            raise ErreurImport(f"{ctx} : destinataire inconnu") from exc
        cle_res = m.get("ressource")
        if cle_res is not None and cle_res not in ressources:
            raise ErreurImport(f"{ctx} : ressource inconnue")
        motifs.append(MotifRendezVous(
            id=ident("motif", str(_exiger(m, "cle", ctx))), etablissement_id=etab_id,
            libelle_i18n=_exiger(m, "libelle", ctx), duree_min=int(m.get("duree_min", 30)),
            destinataire=destinataire,
            ressource_id=ressources[cle_res].id if cle_res else None,
            actif=bool(m.get("actif", True)), ordre=int(m.get("ordre", i)),
        ))

    exceptions = []
    for nom_liste, type_exc in (
        ("fermetures", TypeException.FERMETURE),
        ("horaires_reduits", TypeException.HORAIRE_REDUIT),
        ("ouvertures", TypeException.OUVERTURE),
    ):
        for i, x in enumerate(ecole.get(nom_liste, []), start=1):
            ctx = f"{nom_liste}[{i}]"
            cle_res = x.get("ressource")
            if cle_res is not None and cle_res not in ressources:
                raise ErreurImport(f"{ctx} : ressource inconnue")
            exceptions.append(ExceptionAgenda(
                id=ident("exception", nom_liste, str(i)), etablissement_id=etab_id,
                type=type_exc,
                date_debut=_date(_exiger(x, "debut", ctx), ctx),
                date_fin=_date(x.get("fin", x["debut"]), ctx),
                ressource_id=ressources[cle_res].id if cle_res else None,
                heure_debut=_heure(x["heure_debut"], ctx) if x.get("heure_debut") else None,
                heure_fin=_heure(x["heure_fin"], ctx) if x.get("heure_fin") else None,
                motif=str(x.get("motif", "")),
            ))

    configuration = ConfigurationEcole(
        etablissement=etablissement, annee=annee, periodes=tuple(periodes),
        disponibilites=tuple(disponibilites), exceptions=tuple(exceptions),
        ressources=tuple(ressources.values()), motifs=tuple(motifs),
    )
    donnees = DonneesEcole(
        cle=cle, configuration=configuration, niveaux=list(niveaux.values()),
        enseignants=list(enseignants.values()), classes=list(classes.values()),
    )
    if familles_csv:
        _lire_familles(donnees, familles_csv, classes, classes_par_libelle, maintenant)
    return donnees


def ecole_classes_de(ecole: dict[str, Any], cle_enseignant: str) -> list[str]:
    """Classes d'un enseignant : celles qu'il declare et celles dont il est principal."""
    for en in ecole.get("enseignants", []):
        if str(en.get("cle")) == cle_enseignant:
            declarees = list(en.get("classes", []))
            break
    else:
        declarees = []
    principales = [
        str(c["cle"]) for c in ecole.get("classes", [])
        if c.get("enseignant_principal") == cle_enseignant
    ]
    return list(dict.fromkeys(declarees + principales))


# =====================================================================
# Familles (CSV)
# =====================================================================

COLONNES_OBLIGATOIRES = ("famille", "identifiant", "prenom", "nom", "classe")


def _lire_familles(
    donnees: DonneesEcole,
    texte: str,
    classes: dict[str, Classe],
    classes_par_libelle: dict[str, Classe],
    maintenant: datetime,
) -> None:
    cle = donnees.cle
    etab_id = donnees.etablissement_id
    try:
        dialecte = csv.Sniffer().sniff(texte.splitlines()[0], delimiters=";,\t")
    except (csv.Error, IndexError) as exc:
        raise ErreurImport("familles.csv : separateur introuvable (; ou ,)") from exc
    lecteur = csv.DictReader(io.StringIO(texte), dialect=dialecte)
    lecteur.fieldnames = [_norm(c).replace(" ", "_") for c in (lecteur.fieldnames or [])]
    manquantes = [c for c in COLONNES_OBLIGATOIRES if c not in lecteur.fieldnames]
    if manquantes:
        raise ErreurImport(f"familles.csv : colonnes manquantes {manquantes}")

    familles: dict[str, Famille] = {}
    contacts: dict[str, Contact] = {}
    parents: dict[str, Parent] = {}
    numero_du_parent: dict[str, str | None] = {}
    eleves: dict[str, Eleve] = {}
    liens: dict[tuple[str, str], LienParentEleve] = {}

    for ligne_no, ligne in enumerate(lecteur, start=2):
        ctx = f"familles.csv ligne {ligne_no}"
        valeurs = {k: (v or "").strip() for k, v in ligne.items() if k}
        if not any(valeurs.values()):
            continue
        for colonne in COLONNES_OBLIGATOIRES:
            if not valeurs.get(colonne):
                raise ErreurImport(f"{ctx} : colonne « {colonne} » vide")
        cle_famille = _norm(valeurs["famille"])
        famille = familles.setdefault(cle_famille, Famille(
            id=identifiant(cle, "famille", cle_famille), etablissement_id=etab_id,
            nom_affiche=f"Famille {valeurs['famille']}",
        ))
        classe = classes.get(valeurs["classe"]) or classes_par_libelle.get(_norm(valeurs["classe"]))
        if classe is None:
            raise ErreurImport(f"{ctx} : classe inconnue « {valeurs['classe']} »")
        annee_naissance = valeurs.get("annee_naissance") or ""
        if annee_naissance and not annee_naissance.isdigit():
            raise ErreurImport(f"{ctx} : annee_naissance doit etre une annee seule (ex. 2016)")
        ident_interne = valeurs["identifiant"]
        if ident_interne in eleves:
            raise ErreurImport(f"{ctx} : identifiant d'eleve en double")
        eleve = Eleve(
            id=identifiant(cle, "eleve", ident_interne), etablissement_id=etab_id,
            classe_id=classe.id, prenom=valeurs["prenom"], nom=valeurs["nom"],
            identifiant_interne=ident_interne,
            date_naissance_annee=int(annee_naissance) if annee_naissance else None,
        )
        eleves[ident_interne] = eleve
        consenti = maintenant if _norm(valeurs.get("consentement", "")) in _OUI else None

        for rang in (1, 2):
            telephone = valeurs.get(f"parent{rang}_telephone", "")
            lien_txt = _norm(valeurs.get(f"parent{rang}_lien", ""))
            if not telephone and not lien_txt:
                continue
            c = f"{ctx}, parent{rang}"
            lien = _LIENS.get(lien_txt)
            if lien is None:
                raise ErreurImport(f"{c} : lien attendu pere, mere ou tuteur")
            langue_code = _norm(valeurs.get(f"parent{rang}_langue", ""))
            try:
                langue = Langue(langue_code) if langue_code else None
            except ValueError as exc:
                raise ErreurImport(f"{c} : langue inconnue (fr, ar, so, aa)") from exc
            numero = None
            if telephone:
                try:
                    numero = normaliser(telephone)
                except NumeroInvalide as exc:
                    raise ErreurImport(f"{c} : numero de telephone invalide") from exc
            parent_id = identifiant(cle, "parent", cle_famille, lien.value)
            if parent_id in numero_du_parent and numero_du_parent[parent_id] != numero:
                raise ErreurImport(
                    f"{c} : deux numeros differents pour le meme parent de la famille"
                )
            numero_du_parent[parent_id] = numero
            contact_id = None
            if numero:
                contact_id = identifiant(cle, "contact", numero)
                existant = contacts.get(numero)
                contacts[numero] = Contact(
                    id=contact_id, etablissement_id=etab_id, numero=numero,
                    langue_preferee=(existant.langue_preferee if existant else None) or langue,
                    consenti_at=(existant.consenti_at if existant else None) or consenti,
                )
            parents[parent_id] = Parent(
                id=parent_id, famille_id=famille.id, contact_id=contact_id, lien=lien,
                est_referent=rang == 1
                or (parent_id in parents and parents[parent_id].est_referent),
                langue_preferee=langue,
            )
            liens[(parent_id, eleve.id)] = LienParentEleve(parent_id=parent_id, eleve_id=eleve.id)

    donnees.familles = list(familles.values())
    donnees.contacts = list(contacts.values())
    donnees.parents = list(parents.values())
    donnees.eleves = list(eleves.values())
    donnees.liens = list(liens.values())


# =====================================================================
# Ecriture PostgreSQL
# =====================================================================


def ecrire_postgres(dsn: str, donnees: DonneesEcole, marquer_sortis: bool = True) -> dict[str, int]:
    """Ecrit l'import dans une seule transaction : tout passe, ou rien."""
    import psycopg  # import tardif : la lecture seule ne demande pas de pilote

    conf = donnees.configuration
    e = conf.etablissement
    etab = e.id
    resume = donnees.resume()
    with psycopg.connect(dsn) as conn, conn.transaction():
        x = conn.execute
        x(
            "INSERT INTO etablissement (id, nom, fuseau, langues_actives, langue_defaut, "
            "jours_ouvres, silence_debut, silence_fin, devise, delai_minimal_min) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO UPDATE SET "
            "nom=EXCLUDED.nom, fuseau=EXCLUDED.fuseau, langues_actives=EXCLUDED.langues_actives, "
            "langue_defaut=EXCLUDED.langue_defaut, jours_ouvres=EXCLUDED.jours_ouvres, "
            "silence_debut=EXCLUDED.silence_debut, silence_fin=EXCLUDED.silence_fin, "
            "devise=EXCLUDED.devise, delai_minimal_min=EXCLUDED.delai_minimal_min",
            (etab, e.nom, e.fuseau_nom, sorted(lg.value for lg in e.langues_actives),
             e.langue_defaut.value, sorted(int(j) for j in e.jours_ouvres), e.silence.debut,
             e.silence.fin, e.devise, e.delai_minimal_min),
        )
        a = conf.annee
        x("UPDATE annee_scolaire SET active = false WHERE etablissement_id = %s AND id <> %s",
          (etab, a.id))
        x(
            "INSERT INTO annee_scolaire (id, etablissement_id, libelle, date_debut, date_fin, "
            "active) VALUES (%s,%s,%s,%s,%s,true) ON CONFLICT (id) DO UPDATE SET "
            "libelle=EXCLUDED.libelle, date_debut=EXCLUDED.date_debut, "
            "date_fin=EXCLUDED.date_fin, active=true",
            (a.id, etab, a.libelle, a.date_debut, a.date_fin),
        )
        x("DELETE FROM periode WHERE annee_scolaire_id = %s AND NOT (id = ANY(%s::uuid[]))",
          (a.id, [p.id for p in conf.periodes]))
        for p in conf.periodes:
            x(
                "INSERT INTO periode (id, annee_scolaire_id, libelle_i18n, type, date_debut, "
                "date_fin) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO UPDATE SET "
                "libelle_i18n=EXCLUDED.libelle_i18n, type=EXCLUDED.type, "
                "date_debut=EXCLUDED.date_debut, date_fin=EXCLUDED.date_fin",
                (p.id, a.id, json.dumps(dict(p.libelle_i18n)), p.type.value, p.date_debut,
                 p.date_fin),
            )
        # Ressources : celles absentes du fichier sont desactivees, pas supprimees
        # (des rendez-vous passes y font reference).
        x("UPDATE ressource SET actif = false WHERE etablissement_id = %s "
          "AND NOT (id = ANY(%s::uuid[]))", (etab, [r.id for r in conf.ressources]))
        for r in conf.ressources:
            x(
                "INSERT INTO ressource (id, etablissement_id, libelle, duree_creneau_min, "
                "pas_min, langues, actif) VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) "
                "DO UPDATE SET libelle=EXCLUDED.libelle, "
                "duree_creneau_min=EXCLUDED.duree_creneau_min, pas_min=EXCLUDED.pas_min, "
                "langues=EXCLUDED.langues, actif=EXCLUDED.actif",
                (r.id, etab, r.libelle, r.duree_creneau_min, r.pas_min,
                 sorted(lg.value for lg in r.langues), r.actif),
            )
        x("UPDATE enseignant SET actif = false WHERE etablissement_id = %s "
          "AND NOT (id = ANY(%s::uuid[]))", (etab, [en.id for en in donnees.enseignants]))
        for en in donnees.enseignants:
            x(
                "INSERT INTO enseignant (id, etablissement_id, nom, matieres, langues, "
                "duree_creneau_min, actif) VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) "
                "DO UPDATE SET nom=EXCLUDED.nom, matieres=EXCLUDED.matieres, "
                "langues=EXCLUDED.langues, duree_creneau_min=EXCLUDED.duree_creneau_min, "
                "actif=EXCLUDED.actif",
                (en.id, etab, en.nom, list(en.matieres), sorted(lg.value for lg in en.langues),
                 en.duree_creneau_min, en.actif),
            )
        # Grille et exceptions : configuration pure, remplacee en bloc.
        x("DELETE FROM disponibilite WHERE etablissement_id = %s", (etab,))
        for d in conf.disponibilites:
            x(
                "INSERT INTO disponibilite (id, etablissement_id, ressource_id, jour, "
                "heure_debut, heure_fin, actif) VALUES (%s,%s,%s,%s,%s,%s,true)",
                (d.id, etab, d.ressource_id, int(d.jour), d.heure_debut, d.heure_fin),
            )
        x("DELETE FROM exception_agenda WHERE etablissement_id = %s", (etab,))
        for ex in conf.exceptions:
            x(
                "INSERT INTO exception_agenda (id, etablissement_id, ressource_id, type, "
                "date_debut, date_fin, heure_debut, heure_fin, motif) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (ex.id, etab, ex.ressource_id, ex.type.value, ex.date_debut, ex.date_fin,
                 ex.heure_debut, ex.heure_fin, ex.motif),
            )
        for n in donnees.niveaux:
            x(
                "INSERT INTO niveau (id, etablissement_id, libelle_i18n, ordre) "
                "VALUES (%s,%s,%s,%s) ON CONFLICT (id) DO UPDATE SET "
                "libelle_i18n=EXCLUDED.libelle_i18n, ordre=EXCLUDED.ordre",
                (n.id, etab, json.dumps(dict(n.libelle_i18n)), n.ordre),
            )
        for c in donnees.classes:
            x(
                "INSERT INTO classe (id, etablissement_id, niveau_id, annee_scolaire_id, "
                "libelle, enseignant_principal_id) VALUES (%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (id) DO UPDATE SET niveau_id=EXCLUDED.niveau_id, "
                "libelle=EXCLUDED.libelle, "
                "enseignant_principal_id=EXCLUDED.enseignant_principal_id",
                (c.id, etab, c.niveau_id, a.id, c.libelle, c.enseignant_principal_id),
            )
        x("DELETE FROM enseignant_classe WHERE enseignant_id = ANY(%s::uuid[])",
          ([en.id for en in donnees.enseignants],))
        for en in donnees.enseignants:
            for classe_id in en.classes:
                x("INSERT INTO enseignant_classe (enseignant_id, classe_id) VALUES (%s,%s)",
                  (en.id, classe_id))
        x("UPDATE motif_rendez_vous SET actif = false WHERE etablissement_id = %s "
          "AND NOT (id = ANY(%s::uuid[]))", (etab, [m.id for m in conf.motifs]))
        for m in conf.motifs:
            x(
                "INSERT INTO motif_rendez_vous (id, etablissement_id, libelle_i18n, duree_min, "
                "destinataire, ressource_id, actif, ordre) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (id) DO UPDATE SET libelle_i18n=EXCLUDED.libelle_i18n, "
                "duree_min=EXCLUDED.duree_min, destinataire=EXCLUDED.destinataire, "
                "ressource_id=EXCLUDED.ressource_id, actif=EXCLUDED.actif, ordre=EXCLUDED.ordre",
                (m.id, etab, json.dumps(dict(m.libelle_i18n)), m.duree_min,
                 m.destinataire.value, m.ressource_id, m.actif, m.ordre),
            )

        if donnees.eleves:
            _ecrire_familles(conn, donnees, marquer_sortis, resume)
    return resume


def _ecrire_familles(conn, donnees: DonneesEcole, marquer_sortis: bool, resume: dict) -> None:
    x = conn.execute
    etab = donnees.etablissement_id
    for f in donnees.familles:
        x("INSERT INTO famille (id, etablissement_id, nom_affiche) VALUES (%s,%s,%s) "
          "ON CONFLICT (id) DO UPDATE SET nom_affiche=EXCLUDED.nom_affiche",
          (f.id, etab, f.nom_affiche))
    for c in donnees.contacts:
        # Le STOP d'un parent (stoppe_at) n'est jamais ecrase par un import, et
        # un consentement deja donne n'est pas retire par une case vide.
        x(
            "INSERT INTO contact (id, etablissement_id, numero, langue_preferee, consenti_at) "
            "VALUES (%s,%s,%s,%s,%s) ON CONFLICT (etablissement_id, numero) DO UPDATE SET "
            "langue_preferee=COALESCE(contact.langue_preferee, EXCLUDED.langue_preferee), "
            "consenti_at=COALESCE(contact.consenti_at, EXCLUDED.consenti_at)",
            (c.id, etab, c.numero, c.langue_preferee.value if c.langue_preferee else None,
             c.consenti_at),
        )
    for p in donnees.parents:
        contact_id = None
        if p.contact_id is not None:
            numero = next(c.numero for c in donnees.contacts if c.id == p.contact_id)
            r = x("SELECT id FROM contact WHERE etablissement_id = %s AND numero = %s",
                  (etab, numero)).fetchone()
            contact_id = r[0]
        x(
            "INSERT INTO parent (id, famille_id, contact_id, lien, est_referent, "
            "langue_preferee) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO UPDATE SET "
            "contact_id=EXCLUDED.contact_id, lien=EXCLUDED.lien, "
            "est_referent=EXCLUDED.est_referent, langue_preferee=EXCLUDED.langue_preferee",
            (p.id, p.famille_id, contact_id, p.lien.value, p.est_referent,
             p.langue_preferee.value if p.langue_preferee else None),
        )
    for el in donnees.eleves:
        x(
            "INSERT INTO eleve (id, etablissement_id, classe_id, prenom, nom, "
            "identifiant_interne, date_naissance_annee, statut) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,'inscrit') ON CONFLICT (id) DO UPDATE SET "
            "classe_id=EXCLUDED.classe_id, prenom=EXCLUDED.prenom, nom=EXCLUDED.nom, "
            "date_naissance_annee=EXCLUDED.date_naissance_annee, statut='inscrit'",
            (el.id, etab, el.classe_id, el.prenom, el.nom, el.identifiant_interne,
             el.date_naissance_annee),
        )
    # Le CSV fait foi : liens des eleves importes reconstruits a l'identique.
    ids_eleves = [el.id for el in donnees.eleves]
    gardes = {}
    for r in x("SELECT parent_id, eleve_id, autorise_a_recuperer FROM lien_parent_eleve "
               "WHERE eleve_id = ANY(%s::uuid[])", (ids_eleves,)).fetchall():
        gardes[(str(r[0]), str(r[1]))] = r[2]
    x("DELETE FROM lien_parent_eleve WHERE eleve_id = ANY(%s::uuid[])", (ids_eleves,))
    for lien in donnees.liens:
        # autorise_a_recuperer est gere par l'ecole dans BALLAN : on le conserve.
        autorise = gardes.get((lien.parent_id, lien.eleve_id), lien.autorise_a_recuperer)
        x("INSERT INTO lien_parent_eleve (parent_id, eleve_id, autorise_a_recuperer) "
          "VALUES (%s,%s,%s)", (lien.parent_id, lien.eleve_id, autorise))
    if marquer_sortis:
        r = x("UPDATE eleve SET statut = 'sorti' WHERE etablissement_id = %s "
              "AND statut = 'inscrit' AND NOT (id = ANY(%s::uuid[]))", (etab, ids_eleves))
        resume["eleves_sortis"] = r.rowcount
