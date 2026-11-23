-- ECAM : schéma PostgreSQL corrigé (v2)
-- 1) CREATE DATABASE ecam ENCODING 'UTF8';   2) se connecter à ecam   3) exécuter ce fichier
BEGIN;

-- ---------- Utilisateurs ----------
CREATE TABLE roles(
  id SERIAL PRIMARY KEY,
  nom_role VARCHAR(30) NOT NULL UNIQUE);
INSERT INTO roles(nom_role) VALUES ('etudiant'),('enseignant'),('directeur_etudes'),('admin');

CREATE TABLE users(
  id SERIAL PRIMARY KEY,
  nom VARCHAR(50) NOT NULL,
  prenom VARCHAR(50) NOT NULL,
  email VARCHAR(100) UNIQUE,
  telephone VARCHAR(20) NOT NULL UNIQUE,          -- sert d’identifiant de connexion
  mot_de_passe VARCHAR(255) NOT NULL,             -- hash (werkzeug), jamais en clair
  photo VARCHAR(255),
  role_id INTEGER NOT NULL REFERENCES roles(id),
  date_creation TIMESTAMP NOT NULL DEFAULT now());

-- ---------- Académique ----------
CREATE TABLE departements(id SERIAL PRIMARY KEY, nom VARCHAR(100) NOT NULL UNIQUE);
CREATE TABLE filieres(
  id SERIAL PRIMARY KEY,
  code VARCHAR(10) NOT NULL UNIQUE,
  nom VARCHAR(120) NOT NULL UNIQUE,
  departement_id INTEGER REFERENCES departements(id));
CREATE TABLE niveaux(id SERIAL PRIMARY KEY, nom VARCHAR(30) NOT NULL UNIQUE);
CREATE TABLE annees(
  id SERIAL PRIMARY KEY,
  libelle VARCHAR(9) NOT NULL UNIQUE,             -- ex. 2026-2027
  active BOOLEAN NOT NULL DEFAULT false);
CREATE UNIQUE INDEX une_seule_annee_active ON annees(active) WHERE active;
CREATE TABLE semestres(id SERIAL PRIMARY KEY, nom VARCHAR(30) NOT NULL UNIQUE);
CREATE TABLE classes(
  id SERIAL PRIMARY KEY,
  niveau_id INTEGER REFERENCES niveaux(id),        -- facultatifs : une classe comme « Orange » n'a pas
  filiere_id INTEGER REFERENCES filieres(id),      -- forcément un niveau ou une filière précis
  nom VARCHAR(60) NOT NULL UNIQUE);

CREATE TABLE etudiants(
  id SERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
  matricule VARCHAR(20) NOT NULL UNIQUE,
  date_naissance DATE,
  sexe CHAR(1) CHECK (sexe IN ('M','F')),
  adresse VARCHAR(150),
  telephone_parent VARCHAR(20),
  date_inscription DATE NOT NULL DEFAULT CURRENT_DATE,
  classe_id INTEGER NOT NULL REFERENCES classes(id));   -- le niveau se déduit de la classe

CREATE TABLE enseignants(
  id SERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
  grade VARCHAR(50), specialite VARCHAR(100), date_embauche DATE);

CREATE TABLE matieres(
  id SERIAL PRIMARY KEY,
  nom VARCHAR(100) NOT NULL,
  coefficient NUMERIC(4,2) NOT NULL DEFAULT 1 CHECK (coefficient > 0),
  credits SMALLINT NOT NULL DEFAULT 0 CHECK (credits >= 0),
  classe_id INTEGER NOT NULL REFERENCES classes(id),
  semestre_id INTEGER NOT NULL REFERENCES semestres(id),
  UNIQUE(nom, classe_id, semestre_id));

CREATE TABLE affectations(                         -- ex-« eseignant_matiere »
  id SERIAL PRIMARY KEY,
  enseignant_id INTEGER NOT NULL REFERENCES enseignants(id),
  matiere_id INTEGER NOT NULL REFERENCES matieres(id),
  annee_id INTEGER NOT NULL REFERENCES annees(id),
  UNIQUE(enseignant_id, matiere_id, annee_id));

CREATE TABLE salles(id SERIAL PRIMARY KEY, nom VARCHAR(30) NOT NULL UNIQUE, capacite INTEGER CHECK (capacite > 0));

CREATE TABLE emplois_temps(
  id SERIAL PRIMARY KEY,
  matiere_id INTEGER NOT NULL REFERENCES matieres(id),
  enseignant_id INTEGER REFERENCES enseignants(id),
  salle_id INTEGER REFERENCES salles(id),
  annee_id INTEGER NOT NULL REFERENCES annees(id),
  jour SMALLINT NOT NULL CHECK (jour BETWEEN 1 AND 7),   -- 1 = lundi
  heure_debut TIME NOT NULL,
  heure_fin TIME NOT NULL,
  CHECK (heure_fin > heure_debut));

CREATE TABLE presences(
  id SERIAL PRIMARY KEY,
  etudiant_id INTEGER NOT NULL REFERENCES etudiants(id) ON DELETE CASCADE,
  matiere_id INTEGER NOT NULL REFERENCES matieres(id),
  date_p DATE NOT NULL,
  present BOOLEAN NOT NULL,
  UNIQUE(etudiant_id, matiere_id, date_p));

CREATE TABLE notes(
  id SERIAL PRIMARY KEY,
  etudiant_id INTEGER NOT NULL REFERENCES etudiants(id) ON DELETE CASCADE,
  matiere_id INTEGER NOT NULL REFERENCES matieres(id),
  enseignant_id INTEGER REFERENCES enseignants(id),
  annee_id INTEGER NOT NULL REFERENCES annees(id),
  type_note VARCHAR(20) NOT NULL CHECK (type_note IN ('devoir','tp','examen')),
  valeur NUMERIC(4,2) NOT NULL CHECK (valeur BETWEEN 0 AND 20),   -- ex-« note char(2) » : 14.5 n’y tenait pas
  coefficient NUMERIC(3,1) NOT NULL DEFAULT 1 CHECK (coefficient > 0));

CREATE TABLE resultats(
  id SERIAL PRIMARY KEY,
  etudiant_id INTEGER NOT NULL REFERENCES etudiants(id) ON DELETE CASCADE,
  semestre_id INTEGER NOT NULL REFERENCES semestres(id),
  annee_id INTEGER NOT NULL REFERENCES annees(id),
  moyenne NUMERIC(4,2) NOT NULL CHECK (moyenne BETWEEN 0 AND 20),
  decision VARCHAR(20) NOT NULL CHECK (decision IN ('admis','ajourne','rattrapage')),
  rang SMALLINT,
  UNIQUE(etudiant_id, semestre_id, annee_id));

CREATE TABLE acces_resultat(                       -- l’administration autorise l’affichage des notes
  id SERIAL PRIMARY KEY,
  etudiant_id INTEGER NOT NULL UNIQUE REFERENCES etudiants(id) ON DELETE CASCADE,
  autorise BOOLEAN NOT NULL DEFAULT false);

-- ---------- Paiements ----------
CREATE TABLE types_paiements(
  id SERIAL PRIMARY KEY,
  nom VARCHAR(40) NOT NULL UNIQUE,
  montant NUMERIC(10,0) NOT NULL CHECK (montant >= 0),
  obligatoire BOOLEAN NOT NULL DEFAULT true);
CREATE TABLE tranches(
  id SERIAL PRIMARY KEY,
  type_paiement_id INTEGER NOT NULL REFERENCES types_paiements(id),
  nom VARCHAR(30) NOT NULL,
  date_limite DATE NOT NULL,
  montant NUMERIC(10,0) NOT NULL CHECK (montant > 0));
CREATE TABLE paiements(                            -- ex-« paiement »
  id SERIAL PRIMARY KEY,
  etudiant_id INTEGER NOT NULL REFERENCES etudiants(id),
  type_paiement_id INTEGER NOT NULL REFERENCES types_paiements(id),
  tranche_id INTEGER REFERENCES tranches(id),
  annee_id INTEGER NOT NULL REFERENCES annees(id),
  montant NUMERIC(10,0) NOT NULL CHECK (montant > 0),
  mode_paie VARCHAR(20) NOT NULL CHECK (mode_paie IN ('especes','mobile_money','virement','cheque')),
  date_paie DATE NOT NULL DEFAULT CURRENT_DATE,
  statut VARCHAR(10) NOT NULL DEFAULT 'valide' CHECK (statut IN ('en_attente','valide','refuse')));

-- ---------- Bibliothèque et cours ----------
CREATE TABLE livres(                               -- fusion de « livres » et « ajout_livre »
  id SERIAL PRIMARY KEY,
  titre VARCHAR(150) NOT NULL,
  matiere VARCHAR(100),
  filiere_id INTEGER REFERENCES filieres(id),
  annee SMALLINT CHECK (annee BETWEEN 1990 AND 2100),
  fichier VARCHAR(255) NOT NULL,                   -- nom du PDF dans le dossier uploads/, plus de BYTEA en base
  depose_par INTEGER REFERENCES users(id),
  statut VARCHAR(12) NOT NULL DEFAULT 'en_attente' CHECK (statut IN ('en_attente','valide','refuse')),
  date_depot TIMESTAMP NOT NULL DEFAULT now());
CREATE TABLE cours(
  id SERIAL PRIMARY KEY,
  matiere_id INTEGER NOT NULL REFERENCES matieres(id),
  enseignant_id INTEGER NOT NULL REFERENCES enseignants(id),
  titre VARCHAR(150) NOT NULL,
  description TEXT,
  fichier VARCHAR(255),
  date_pub DATE NOT NULL DEFAULT CURRENT_DATE);

-- ---------- Messages et assistant ----------
CREATE TABLE notification(
  id SERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,        -- destinataire
  expediteur_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  titre VARCHAR(150) NOT NULL,
  message TEXT,
  lu BOOLEAN NOT NULL DEFAULT false,
  date_envoi TIMESTAMP NOT NULL DEFAULT now());
CREATE TABLE chat_messages(
  id SERIAL PRIMARY KEY,
  session_id VARCHAR(40) NOT NULL,
  user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  role VARCHAR(10) NOT NULL CHECK (role IN ('user','assistant')),
  contenu TEXT NOT NULL,
  date_msg TIMESTAMP NOT NULL DEFAULT now());

CREATE INDEX ON notes(etudiant_id, annee_id);
CREATE INDEX ON presences(etudiant_id);
CREATE INDEX ON paiements(etudiant_id, annee_id);
CREATE INDEX ON notification(user_id, lu);
CREATE INDEX ON chat_messages(session_id, id);
CREATE INDEX ON emplois_temps(annee_id, jour);

-- ---------- Données de départ (d’après le site) ----------
INSERT INTO departements(nom) VALUES ('Sciences de l’Ingénieur & Technologie'),('Gestion & Commerce');
INSERT INTO filieres(code,nom,departement_id) VALUES
 ('GIIA','Génie Informatique & Intelligence Artificielle',1),
 ('GIMSP','Génie Industriel & Maintenance des Systèmes Pluritechniques',1),
 ('GEII','Génie Électrique & Informatique Industrielle',1),
 ('CCA','Comptabilité, Contrôle & Audit',2),
 ('TL','Transport & Logistique',2),
 ('GRH','Gestion des Ressources Humaines',2),
 ('GCM','Gestion Commerciale & Marketing',2),
 ('FDA','Fiscalité & Droit des Affaires',2);
INSERT INTO niveaux(nom) VALUES ('L1'),('L2'),('L3');
INSERT INTO semestres(nom) VALUES ('S1'),('S2'),('S3'),('S4'),('S5'),('S6');
INSERT INTO annees(libelle, active) VALUES ('2026-2027', true);
INSERT INTO classes(niveau_id, filiere_id, nom)
  SELECT n.id, f.id, n.nom || ' ' || f.code FROM niveaux n CROSS JOIN filieres f;
-- Classes de l'école (nom de groupe, sans niveau ni filière imposés)
INSERT INTO classes(nom) VALUES ('Coconut Amphi 200'),('Orange'),('Banana'),('Apple');
COMMIT;
