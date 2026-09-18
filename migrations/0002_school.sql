-- ===================================================================
-- Lot 1 — Structure scolaire
--
-- Annee, periodes, niveaux, classes, enseignants, eleves, familles,
-- liens parent-eleve.
--
-- Deux garanties du §8 sont ecrites ici comme contraintes de schema,
-- pas comme conventions :
--
--   * date_naissance_annee est un entier, pas une date. Il devient
--     impossible de stocker une date de naissance complete, meme par
--     erreur, meme depuis un import de tableur mal ecrit.
--   * lien_parent_eleve est la seule table qui autorise l'acces aux
--     donnees d'un eleve. Sa cle primaire (parent_id, eleve_id) la rend
--     sans ambiguite.
--
-- Ce qui n'est PAS ici, et ne doit jamais y entrer (§3, §8.1) : notes,
-- moyennes, bulletins, appreciations, comportement, sanctions, photos,
-- donnees de sante, adresse. BALLAN communique et prend des rendez-vous ;
-- il n'est pas un logiciel de gestion scolaire.
--
-- Les tables session_reunion, signalement_absence, echeance_scolarite et
-- annonce arrivent avec les lots 4 et 5, en meme temps que leur code.
-- ===================================================================

CREATE TYPE type_periode AS ENUM ('trimestre', 'semestre', 'vacances', 'examens');
CREATE TYPE lien_parente AS ENUM ('pere', 'mere', 'tuteur');
CREATE TYPE statut_eleve AS ENUM ('inscrit', 'sorti');
CREATE TYPE destinataire_rendez_vous AS ENUM ('enseignant', 'direction', 'vie_scolaire');

-- -------------------------------------------------------------------
-- Calendrier scolaire
-- -------------------------------------------------------------------

CREATE TABLE annee_scolaire (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    etablissement_id  uuid NOT NULL REFERENCES etablissement (id) ON DELETE CASCADE,
    libelle           text NOT NULL,
    date_debut        date NOT NULL,
    date_fin          date NOT NULL,
    active            boolean NOT NULL DEFAULT false,

    CONSTRAINT annee_scolaire_bornes CHECK (date_fin > date_debut)
);

-- Une seule annee active a la fois par etablissement : c'est elle qui
-- sert de reference partout ailleurs.
CREATE UNIQUE INDEX annee_scolaire_une_seule_active
    ON annee_scolaire (etablissement_id) WHERE active;

CREATE TABLE periode (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    annee_scolaire_id  uuid NOT NULL REFERENCES annee_scolaire (id) ON DELETE CASCADE,
    -- Libelle officiel par langue, saisi par l'ecole. Jamais traduit par
    -- le modele de langue (§7).
    libelle_i18n       jsonb NOT NULL,
    type               type_periode NOT NULL,
    date_debut         date NOT NULL,
    date_fin           date NOT NULL,

    CONSTRAINT periode_bornes CHECK (date_fin >= date_debut),
    CONSTRAINT periode_libelle_non_vide CHECK (jsonb_typeof(libelle_i18n) = 'object'
        AND libelle_i18n <> '{}'::jsonb)
);

CREATE INDEX periode_par_annee ON periode (annee_scolaire_id, date_debut, date_fin);

-- -------------------------------------------------------------------
-- Structure pedagogique
-- -------------------------------------------------------------------

CREATE TABLE niveau (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    etablissement_id  uuid NOT NULL REFERENCES etablissement (id) ON DELETE CASCADE,
    libelle_i18n      jsonb NOT NULL,
    ordre             integer NOT NULL,

    CONSTRAINT niveau_libelle_non_vide CHECK (jsonb_typeof(libelle_i18n) = 'object'
        AND libelle_i18n <> '{}'::jsonb),
    CONSTRAINT niveau_ordre_unique UNIQUE (etablissement_id, ordre)
);

COMMENT ON TABLE niveau IS
    'Niveaux propres a chaque ecole. Jamais en dur dans le code (BALLAN.md §2).';

-- L'enseignant EST la ressource du noyau : il herite de son identifiant,
-- donc disponibilite et rendez_vous pointent naturellement vers lui.
CREATE TABLE enseignant (
    id                 uuid PRIMARY KEY REFERENCES ressource (id) ON DELETE CASCADE,
    etablissement_id   uuid NOT NULL REFERENCES etablissement (id) ON DELETE CASCADE,
    nom                text NOT NULL,
    matieres           text[] NOT NULL DEFAULT '{}',
    langues            text[] NOT NULL DEFAULT '{}',
    duree_creneau_min  integer NOT NULL DEFAULT 30,
    actif              boolean NOT NULL DEFAULT true,

    CONSTRAINT enseignant_duree_positive CHECK (duree_creneau_min > 0)
);

CREATE TABLE classe (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    etablissement_id         uuid NOT NULL REFERENCES etablissement (id) ON DELETE CASCADE,
    niveau_id                uuid NOT NULL REFERENCES niveau (id) ON DELETE RESTRICT,
    annee_scolaire_id        uuid NOT NULL REFERENCES annee_scolaire (id) ON DELETE CASCADE,
    libelle                  text NOT NULL,
    enseignant_principal_id  uuid REFERENCES enseignant (id) ON DELETE SET NULL,
    effectif                 integer NOT NULL DEFAULT 0,

    CONSTRAINT classe_effectif_positif CHECK (effectif >= 0),
    CONSTRAINT classe_libelle_unique UNIQUE (annee_scolaire_id, libelle)
);

CREATE INDEX classe_par_niveau ON classe (niveau_id, annee_scolaire_id);

-- Rattachement d'un enseignant aux classes ou il intervient. Table de
-- liaison plutot qu'un tableau : une ecole change d'enseignant en cours
-- d'annee, et on veut pouvoir le faire sans reecrire une colonne.
CREATE TABLE enseignant_classe (
    enseignant_id  uuid NOT NULL REFERENCES enseignant (id) ON DELETE CASCADE,
    classe_id      uuid NOT NULL REFERENCES classe (id) ON DELETE CASCADE,

    PRIMARY KEY (enseignant_id, classe_id)
);

-- -------------------------------------------------------------------
-- Eleves : donnees de mineurs, reduites au minimum (§8.1)
-- -------------------------------------------------------------------

CREATE TABLE eleve (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    etablissement_id      uuid NOT NULL REFERENCES etablissement (id) ON DELETE CASCADE,
    classe_id             uuid NOT NULL REFERENCES classe (id) ON DELETE RESTRICT,
    prenom                text NOT NULL,
    nom                   text NOT NULL,
    identifiant_interne   text NOT NULL,
    -- ANNEE SEULE. Le type entier rend la date complete impossible a
    -- stocker, y compris depuis un import de tableur (§8.1).
    date_naissance_annee  integer,
    statut                statut_eleve NOT NULL DEFAULT 'inscrit',
    cree_at               timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT eleve_annee_naissance_plausible
        CHECK (date_naissance_annee IS NULL
               OR date_naissance_annee BETWEEN 1990 AND 2100),
    CONSTRAINT eleve_identifiant_unique UNIQUE (etablissement_id, identifiant_interne)
);

CREATE INDEX eleve_par_classe ON eleve (classe_id) WHERE statut = 'inscrit';

COMMENT ON COLUMN eleve.date_naissance_annee IS
    'Annee de naissance seule. Jamais une date complete (BALLAN.md §8.1).';

COMMENT ON TABLE eleve IS
    'Donnees de mineurs : prenom, nom, classe, identifiant interne. Aucune note, '
    'appreciation, photo, donnee de sante ou element de comportement (BALLAN.md §3, §8.1).';

-- -------------------------------------------------------------------
-- Familles : la table qui autorise tout
-- -------------------------------------------------------------------

CREATE TABLE famille (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    etablissement_id  uuid NOT NULL REFERENCES etablissement (id) ON DELETE CASCADE,
    nom_affiche       text NOT NULL
);

CREATE TABLE parent (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    famille_id       uuid NOT NULL REFERENCES famille (id) ON DELETE CASCADE,
    -- Une ecole connait parfois un parent sans avoir son numero.
    contact_id       uuid REFERENCES contact (id) ON DELETE SET NULL,
    lien             lien_parente NOT NULL DEFAULT 'tuteur',
    est_referent     boolean NOT NULL DEFAULT false,
    langue_preferee  text
);

CREATE INDEX parent_par_contact ON parent (contact_id) WHERE contact_id IS NOT NULL;
CREATE INDEX parent_par_famille ON parent (famille_id);

CREATE TABLE lien_parent_eleve (
    parent_id              uuid NOT NULL REFERENCES parent (id) ON DELETE CASCADE,
    eleve_id               uuid NOT NULL REFERENCES eleve (id) ON DELETE CASCADE,
    -- Gere par l'ecole, jamais par l'agent : touche a des situations de
    -- garde. Toute question sur ce sujet est escaladee sans etre traitee.
    autorise_a_recuperer   boolean NOT NULL DEFAULT true,
    cree_at                timestamptz NOT NULL DEFAULT now(),

    PRIMARY KEY (parent_id, eleve_id)
);

CREATE INDEX lien_parent_eleve_par_eleve ON lien_parent_eleve (eleve_id);

COMMENT ON TABLE lien_parent_eleve IS
    'La table la plus sensible du produit. Un parent ne voit que les eleves auxquels '
    'elle le rattache, verification refaite cote serveur a chaque requete (BALLAN.md §8.2).';

-- -------------------------------------------------------------------
-- Catalogue administratif des motifs
-- -------------------------------------------------------------------

CREATE TABLE motif_rendez_vous (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    etablissement_id  uuid NOT NULL REFERENCES etablissement (id) ON DELETE CASCADE,
    libelle_i18n      jsonb NOT NULL,
    duree_min         integer NOT NULL DEFAULT 30,
    destinataire      destinataire_rendez_vous NOT NULL DEFAULT 'enseignant',
    actif             boolean NOT NULL DEFAULT true,

    CONSTRAINT motif_duree_positive CHECK (duree_min > 0),
    CONSTRAINT motif_libelle_non_vide CHECK (jsonb_typeof(libelle_i18n) = 'object'
        AND libelle_i18n <> '{}'::jsonb)
);

COMMENT ON TABLE motif_rendez_vous IS
    'Catalogue defini par l''ecole. L''agent choisit dedans, il n''invente jamais un motif.';

-- -------------------------------------------------------------------
-- Specialisation scolaire du rendez-vous du noyau
-- -------------------------------------------------------------------

ALTER TABLE rendez_vous
    ADD COLUMN eleve_id  uuid REFERENCES eleve (id) ON DELETE CASCADE,
    ADD COLUMN parent_id uuid REFERENCES parent (id) ON DELETE SET NULL,
    ADD COLUMN motif_id  uuid REFERENCES motif_rendez_vous (id) ON DELETE SET NULL;

CREATE INDEX rendez_vous_par_eleve ON rendez_vous (eleve_id, debut_at);

COMMENT ON COLUMN rendez_vous.ressource_id IS
    'L''enseignant, la direction ou la vie scolaire : la ressource qui recoit.';
