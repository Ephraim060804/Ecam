
CREATE DATABASE ECAM ENCODING 'UTF8';
\c ECAM;


CREATE TABLE IF NOT EXISTS roles (
    id SERIAL PRIMARY KEY,
    nom VARCHAR(50) UNIQUE NOT NULL
);


CREATE TABLE IF NOT EXISTS utilisateurs (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    mot_de_passe_hash VARCHAR(255) NOT NULL,
    nom VARCHAR(100) NOT NULL,
    prenom VARCHAR(100) NOT NULL,
    photo VARCHAR(255), 
    role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE RESTRICT,
    date_creation TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    actif BOOLEAN DEFAULT TRUE
);
CREATE INDEX idx_utilisateurs_email ON utilisateurs(email);
CREATE INDEX idx_utilisateurs_role ON utilisateurs(role_id);


CREATE TABLE IF NOT EXISTS departements (
    id SERIAL PRIMARY KEY,
    nom VARCHAR(100) UNIQUE NOT NULL,
    description TEXT
);


CREATE TABLE IF NOT EXISTS cours (
    id SERIAL PRIMARY KEY,
    code VARCHAR(20) UNIQUE NOT NULL,
    intitule VARCHAR(255) NOT NULL,
    credits INTEGER CHECK (credits > 0),
    semestre INTEGER CHECK (semestre BETWEEN 1 AND 6),
    annee INTEGER CHECK (annee >= 1),
    departement_id INTEGER NOT NULL REFERENCES departements(id) ON DELETE CASCADE
);
CREATE INDEX idx_cours_departement ON cours(departement_id);


CREATE TABLE IF NOT EXISTS affectations_prof (
    id SERIAL PRIMARY KEY,
    professeur_id INTEGER NOT NULL REFERENCES utilisateurs(id) ON DELETE CASCADE,
    cours_id INTEGER NOT NULL REFERENCES cours(id) ON DELETE CASCADE,
    semestre INTEGER CHECK (semestre BETWEEN 1 AND 6),
    annee INTEGER NOT NULL,
    salle VARCHAR(50),
    horaire VARCHAR(100) 
);
CREATE INDEX idx_affectations_prof_cours ON affectations_prof(cours_id);
CREATE INDEX idx_affectations_prof_prof ON affectations_prof(professeur_id);

ALTER TABLE affectations_prof ADD CONSTRAINT unique_affectation UNIQUE (professeur_id, cours_id, semestre, annee);


CREATE TABLE IF NOT EXISTS inscriptions (
    id SERIAL PRIMARY KEY,
    etudiant_id INTEGER NOT NULL REFERENCES utilisateurs(id) ON DELETE CASCADE,
    cours_id INTEGER NOT NULL REFERENCES cours(id) ON DELETE CASCADE,
    note DECIMAL(5,2) CHECK (note >= 0 AND note <= 20), -- peut être NULL tant que non noté
    statut VARCHAR(20) DEFAULT 'en cours' CHECK (statut IN ('en cours', 'validé', 'échec', 'abandon')),
    date_inscription DATE DEFAULT CURRENT_DATE
);
CREATE INDEX idx_inscriptions_etudiant ON inscriptions(etudiant_id);
CREATE INDEX idx_inscriptions_cours ON inscriptions(cours_id);
ALTER TABLE inscriptions ADD CONSTRAINT unique_inscription UNIQUE (etudiant_id, cours_id);


CREATE TABLE IF NOT EXISTS presences (
    id SERIAL PRIMARY KEY,
    inscription_id INTEGER NOT NULL REFERENCES inscriptions(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    present BOOLEAN DEFAULT FALSE
);
CREATE INDEX idx_presences_inscription ON presences(inscription_id);

ALTER TABLE presences ADD CONSTRAINT unique_presence_date UNIQUE (inscription_id, date);


CREATE TABLE IF NOT EXISTS devoirs (
    id SERIAL PRIMARY KEY,
    cours_id INTEGER NOT NULL REFERENCES cours(id) ON DELETE CASCADE,
    titre VARCHAR(255) NOT NULL,
    description TEXT,
    date_limite DATE NOT NULL,
    date_creation TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_devoirs_cours ON devoirs(cours_id);


CREATE TABLE IF NOT EXISTS rendus (
    id SERIAL PRIMARY KEY,
    devoir_id INTEGER NOT NULL REFERENCES devoirs(id) ON DELETE CASCADE,
    etudiant_id INTEGER NOT NULL REFERENCES utilisateurs(id) ON DELETE CASCADE,
    fichier VARCHAR(255) NOT NULL, 
    note DECIMAL(5,2) CHECK (note >= 0 AND note <= 20),
    date_remise TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_rendus_devoir ON rendus(devoir_id);
CREATE INDEX idx_rendus_etudiant ON rendus(etudiant_id);
ALTER TABLE rendus ADD CONSTRAINT unique_rendu UNIQUE (devoir_id, etudiant_id);


CREATE TABLE IF NOT EXISTS paiements (
    id SERIAL PRIMARY KEY,
    etudiant_id INTEGER NOT NULL REFERENCES utilisateurs(id) ON DELETE CASCADE,
    
   
    montant DECIMAL(10,2) NOT NULL CHECK (montant > 0),
    categorie VARCHAR(50) NOT NULL, 
    methode VARCHAR(20) NOT NULL CHECK (methode IN ('Espèces', 'Chèque', 'Carte', 'Virement')),
    date_paiement DATE DEFAULT CURRENT_DATE,
    statut VARCHAR(20) DEFAULT 'effectué' CHECK (statut IN ('effectué', 'en attente', 'annulé')),
    reference_facture VARCHAR(50)
);
CREATE INDEX idx_paiements_etudiant ON paiements(etudiant_id);


CREATE TABLE IF NOT EXISTS documents_archives (
    id SERIAL PRIMARY KEY,
    titre VARCHAR(255) NOT NULL,
    description TEXT,
    fichier VARCHAR(255) NOT NULL,
    matiere VARCHAR(100), 
    annee INTEGER,
    departement_id INTEGER REFERENCES departements(id) ON DELETE SET NULL,
    uploaded_by INTEGER REFERENCES utilisateurs(id) ON DELETE SET NULL,
    date_upload TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    type_document VARCHAR(50) CHECK (type_document IN ('cours', 'examen', 'td', 'tp', 'memoire', 'autre'))
);
CREATE INDEX idx_documents_departement ON documents_archives(departement_id);


CREATE TABLE IF NOT EXISTS annonces (
    id SERIAL PRIMARY KEY,
    titre VARCHAR(255) NOT NULL,
    contenu TEXT NOT NULL,
    date_publication TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    cible_role_id INTEGER REFERENCES roles(id) ON DELETE SET NULL, 
    publie_par INTEGER REFERENCES utilisateurs(id) ON DELETE SET NULL,
    est_active BOOLEAN DEFAULT TRUE
);
CREATE INDEX idx_annonces_role ON annonces(cible_role_id);