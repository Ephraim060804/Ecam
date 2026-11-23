-- ECAM : migration pour une base DÉJÀ créée avec l'ancien ecam_v2.sql
-- (à exécuter une seule fois dans pgAdmin / psql, connecté à la base "ecam").
-- Elle ne supprime aucune donnée.
BEGIN;

-- 1) Une classe n'a plus besoin d'un niveau ET d'une filière
ALTER TABLE classes ALTER COLUMN niveau_id  DROP NOT NULL;
ALTER TABLE classes ALTER COLUMN filiere_id DROP NOT NULL;

-- 2) On autorise plusieurs classes pour un même niveau/filière (Orange, Banana…)
--    et on rend le NOM de la classe unique à la place
ALTER TABLE classes DROP CONSTRAINT IF EXISTS classes_niveau_id_filiere_id_key;
ALTER TABLE classes DROP CONSTRAINT IF EXISTS classes_nom_key;
ALTER TABLE classes ADD CONSTRAINT classes_nom_key UNIQUE (nom);

-- 3) Les classes de l'école
INSERT INTO classes(nom) VALUES ('Coconut Amphi 200'),('Orange'),('Banana'),('Apple')
ON CONFLICT (nom) DO NOTHING;

COMMIT;
