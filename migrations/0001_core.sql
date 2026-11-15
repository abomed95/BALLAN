-- ===================================================================
-- Lot 0 — Noyau commun MAWID / BALLAN
--
-- Ne contient aucune notion metier de verticale : ni eleve, ni famille,
-- ni patient. Une ressource est ce qui se reserve ; un contact est un
-- numero connu de l'etablissement. Le reste est dans 0002_school.sql.
--
-- Les tables conversation, message, rappel et journal_escalade sont
-- egalement des tables de noyau (BALLAN.md §4) ; elles arrivent avec les
-- lots 2 et 5, en meme temps que le code qui les remplit. On ne cree pas
-- de table sans code qui l'utilise.
-- ===================================================================

-- Necessaire a la contrainte d'exclusion : permet de combiner un
-- operateur d'egalite btree (ressource_id) et un operateur gist (&&)
-- dans une meme contrainte EXCLUDE.
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- -------------------------------------------------------------------
-- Types
-- -------------------------------------------------------------------

CREATE TYPE type_exception AS ENUM ('fermeture', 'ouverture', 'horaire_reduit');

CREATE TYPE statut_rendez_vous AS ENUM (
    'propose', 'confirme', 'annule', 'honore', 'absent'
);

CREATE TYPE acteur AS ENUM ('agent', 'secretariat', 'direction');

-- -------------------------------------------------------------------
-- Etablissement
-- -------------------------------------------------------------------

CREATE TABLE etablissement (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    nom                text NOT NULL,
    fuseau             text NOT NULL DEFAULT 'Africa/Djibouti',
    langues_actives    text[] NOT NULL DEFAULT ARRAY['fr'],
    langue_defaut      text NOT NULL DEFAULT 'fr',
    -- Convention Python : lundi = 0 ... dimanche = 6. Volontairement
    -- differente de extract(dow) (dimanche = 0) : le moteur de creneaux
    -- est en Python, c'est lui qui fait autorite. Toute requete SQL qui
    -- lit cette colonne doit convertir, jamais l'inverse.
    jours_ouvres       smallint[] NOT NULL DEFAULT ARRAY[6, 0, 1, 2, 3],
    silence_debut      time NOT NULL DEFAULT '21:00',
    silence_fin        time NOT NULL DEFAULT '07:00',
    devise             text NOT NULL DEFAULT 'FDJ',
    delai_minimal_min  integer NOT NULL DEFAULT 0,
    cree_at            timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT etablissement_langues_non_vides
        CHECK (array_length(langues_actives, 1) >= 1),
    CONSTRAINT etablissement_langue_defaut_active
        CHECK (langue_defaut = ANY (langues_actives)),
    CONSTRAINT etablissement_jours_ouvres_non_vides
        CHECK (array_length(jours_ouvres, 1) >= 1),
    CONSTRAINT etablissement_jours_ouvres_valides
        CHECK (jours_ouvres <@ ARRAY[0, 1, 2, 3, 4, 5, 6]::smallint[]),
    CONSTRAINT etablissement_delai_positif
        CHECK (delai_minimal_min >= 0)
);

COMMENT ON COLUMN etablissement.jours_ouvres IS
    'Jours ouvres, convention Python (lundi=0, dimanche=6). Defaut Djibouti : dimanche -> jeudi.';

-- -------------------------------------------------------------------
-- Ressource : ce qui se reserve
-- -------------------------------------------------------------------

CREATE TABLE ressource (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    etablissement_id   uuid NOT NULL REFERENCES etablissement (id) ON DELETE CASCADE,
    libelle            text NOT NULL,
    duree_creneau_min  integer NOT NULL DEFAULT 30,
    pas_min            integer,
    langues            text[] NOT NULL DEFAULT '{}',
    actif              boolean NOT NULL DEFAULT true,

    CONSTRAINT ressource_duree_positive CHECK (duree_creneau_min > 0),
    CONSTRAINT ressource_pas_positif CHECK (pas_min IS NULL OR pas_min > 0)
);

CREATE INDEX ressource_par_etablissement ON ressource (etablissement_id) WHERE actif;

COMMENT ON TABLE ressource IS
    'Un praticien dans MAWID, un enseignant dans BALLAN. La verticale specialise cette table.';

-- -------------------------------------------------------------------
-- Disponibilites et exceptions
-- -------------------------------------------------------------------

CREATE TABLE disponibilite (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    etablissement_id  uuid NOT NULL REFERENCES etablissement (id) ON DELETE CASCADE,
    ressource_id      uuid NOT NULL REFERENCES ressource (id) ON DELETE CASCADE,
    jour              smallint NOT NULL,
    heure_debut       time NOT NULL,
    heure_fin         time NOT NULL,
    actif             boolean NOT NULL DEFAULT true,

    CONSTRAINT disponibilite_jour_valide CHECK (jour BETWEEN 0 AND 6),
    CONSTRAINT disponibilite_bornes CHECK (heure_fin > heure_debut)
);

CREATE INDEX disponibilite_par_ressource
    ON disponibilite (ressource_id, jour) WHERE actif;

CREATE TABLE exception_agenda (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    etablissement_id  uuid NOT NULL REFERENCES etablissement (id) ON DELETE CASCADE,
    -- NULL = toute l'ecole (vacances, jour ferie).
    ressource_id      uuid REFERENCES ressource (id) ON DELETE CASCADE,
    type              type_exception NOT NULL,
    date_debut        date NOT NULL,
    date_fin          date NOT NULL,
    heure_debut       time,
    heure_fin         time,
    motif             text NOT NULL DEFAULT '',

    CONSTRAINT exception_bornes_dates CHECK (date_fin >= date_debut),
    CONSTRAINT exception_bornes_heures_completes
        CHECK ((heure_debut IS NULL) = (heure_fin IS NULL)),
    CONSTRAINT exception_bornes_heures_ordonnees
        CHECK (heure_fin IS NULL OR heure_fin > heure_debut),
    -- Une ouverture ou un horaire reduit sans tranche horaire n'a pas de sens.
    CONSTRAINT exception_tranche_obligatoire
        CHECK (type = 'fermeture' OR heure_debut IS NOT NULL)
);

CREATE INDEX exception_agenda_par_periode
    ON exception_agenda (etablissement_id, date_debut, date_fin);

COMMENT ON TABLE exception_agenda IS
    'Vacances, feries, absences, horaires de Ramadan (horaire_reduit), ouvertures exceptionnelles.';

-- -------------------------------------------------------------------
-- Contact : un numero connu
-- -------------------------------------------------------------------

CREATE TABLE contact (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    etablissement_id  uuid NOT NULL REFERENCES etablissement (id) ON DELETE CASCADE,
    -- Forme canonique imposee : +<indicatif><national>, cf. core/telephone.py.
    numero            text NOT NULL,
    langue_preferee   text,
    -- Consentement horodate aux rappels et annonces (§8.3). Sans lui,
    -- aucun envoi sortant non sollicite.
    consenti_at       timestamptz,
    -- Positionne par un STOP, dans n'importe laquelle des quatre langues.
    stoppe_at         timestamptz,
    cree_at           timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT contact_numero_canonique CHECK (numero ~ '^\+[0-9]{8,15}$'),
    CONSTRAINT contact_numero_unique_par_etablissement
        UNIQUE (etablissement_id, numero)
);

-- -------------------------------------------------------------------
-- Rendez-vous : le noyau. La verticale ajoute ses colonnes.
-- -------------------------------------------------------------------

CREATE TABLE rendez_vous (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    etablissement_id  uuid NOT NULL REFERENCES etablissement (id) ON DELETE CASCADE,
    ressource_id      uuid NOT NULL REFERENCES ressource (id) ON DELETE CASCADE,
    contact_id        uuid REFERENCES contact (id) ON DELETE SET NULL,
    debut_at          timestamptz NOT NULL,
    fin_at            timestamptz NOT NULL,
    statut            statut_rendez_vous NOT NULL DEFAULT 'propose',
    cree_par          acteur NOT NULL DEFAULT 'agent',
    cree_at           timestamptz NOT NULL DEFAULT now(),
    maj_at            timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT rendez_vous_bornes CHECK (fin_at > debut_at),

    -- LE garde-fou du produit : deux parents ne peuvent pas reserver le
    -- meme creneau d'un enseignant, quelle que soit la concurrence entre
    -- les instances de l'API. core/scheduling/conflits.py en est le
    -- miroir applicatif ; c'est cette contrainte qui tranche.
    CONSTRAINT rendez_vous_sans_chevauchement
        EXCLUDE USING gist (
            ressource_id WITH =,
            tstzrange(debut_at, fin_at) WITH &&
        ) WHERE (statut = 'confirme')
);

CREATE INDEX rendez_vous_par_ressource_et_date
    ON rendez_vous (ressource_id, debut_at);

CREATE INDEX rendez_vous_par_contact
    ON rendez_vous (contact_id, debut_at);

COMMENT ON CONSTRAINT rendez_vous_sans_chevauchement ON rendez_vous IS
    'Intervalles semi-ouverts : deux creneaux jointifs (10:00-10:30, 10:30-11:00) coexistent.';
