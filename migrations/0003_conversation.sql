-- ===================================================================
-- Lots 2, 3 et 5 — conversation, escalade, rappels, suivi des migrations
--
-- Comme pour les lots precedents, chaque table arrive avec le code qui la
-- remplit : application/persistance/postgres.py.
--
-- Minimisation (§8) : aucune table ne conserve le texte des messages des
-- parents. On garde l'etat du dialogue (des identifiants), l'identifiant
-- technique des messages deja traites (anti-doublon) et les escalades.
-- Ces deux premieres tables se purgent : voir `ballan purger`.
-- ===================================================================

-- -------------------------------------------------------------------
-- Motifs adresses a une ressource precise (direction, vie scolaire)
-- -------------------------------------------------------------------

ALTER TABLE motif_rendez_vous
    ADD COLUMN ressource_id uuid REFERENCES ressource (id) ON DELETE SET NULL,
    ADD COLUMN ordre        integer NOT NULL DEFAULT 0,
    -- Miroir de MotifRendezVous.__post_init__ : seul un motif adresse a
    -- l'enseignant peut se passer de ressource designee.
    ADD CONSTRAINT motif_ressource_si_pas_enseignant
        CHECK (destinataire = 'enseignant' OR ressource_id IS NOT NULL);

-- -------------------------------------------------------------------
-- Rappels (lot 5) : un rappel par rendez-vous, au plus
-- -------------------------------------------------------------------

ALTER TABLE rendez_vous ADD COLUMN rappel_envoye_at timestamptz;

CREATE INDEX rendez_vous_a_rappeler
    ON rendez_vous (etablissement_id, debut_at)
    WHERE statut = 'confirme' AND rappel_envoye_at IS NULL;

-- -------------------------------------------------------------------
-- Etat de conversation : une ligne par numero
-- -------------------------------------------------------------------

CREATE TABLE conversation (
    etablissement_id  uuid NOT NULL REFERENCES etablissement (id) ON DELETE CASCADE,
    numero            text NOT NULL,
    -- Etape et identifiants seulement (application/conversation/etat.py).
    etat              jsonb NOT NULL,
    maj_at            timestamptz NOT NULL DEFAULT now(),

    PRIMARY KEY (etablissement_id, numero),
    CONSTRAINT conversation_numero_canonique CHECK (numero ~ '^\+[0-9]{8,15}$')
);

CREATE INDEX conversation_par_anciennete ON conversation (maj_at);

-- -------------------------------------------------------------------
-- Messages entrants deja traites : WhatsApp re-livre un webhook tant
-- qu'il n'a pas recu de 200, il ne faut repondre qu'une fois.
-- -------------------------------------------------------------------

CREATE TABLE message_entrant (
    id       text PRIMARY KEY,
    recu_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX message_entrant_par_anciennete ON message_entrant (recu_at);

-- -------------------------------------------------------------------
-- Escalades vers le secretariat
-- -------------------------------------------------------------------

CREATE TYPE motif_escalade AS ENUM (
    'numero_inconnu', 'demande_parent', 'sujet_sensible', 'aucun_creneau', 'incident'
);

CREATE TABLE escalade (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    etablissement_id  uuid NOT NULL REFERENCES etablissement (id) ON DELETE CASCADE,
    numero            text NOT NULL,
    motif             motif_escalade NOT NULL,
    cree_at           timestamptz NOT NULL DEFAULT now(),
    traitee_at        timestamptz,
    traitee_par       acteur,

    CONSTRAINT escalade_numero_canonique CHECK (numero ~ '^\+[0-9]{8,15}$'),
    CONSTRAINT escalade_traitee_par_un_humain
        CHECK (traitee_at IS NULL OR traitee_par IN ('secretariat', 'direction'))
);

-- Une seule escalade ouverte par numero et par motif : un parent qui
-- insiste ne noie pas le secretariat.
CREATE UNIQUE INDEX escalade_une_ouverte_par_numero_et_motif
    ON escalade (etablissement_id, numero, motif) WHERE traitee_at IS NULL;

CREATE INDEX escalade_ouvertes ON escalade (etablissement_id, cree_at) WHERE traitee_at IS NULL;
