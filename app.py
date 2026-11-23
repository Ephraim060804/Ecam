import os, re, secrets
from datetime import date, time
from functools import wraps

import click
import psycopg2, psycopg2.errors, psycopg2.extras
from dotenv import load_dotenv
from flask import (Flask, abort, flash, g, jsonify, redirect, render_template,
                   request, send_from_directory, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

load_dotenv()
app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ["SECRET_KEY"],          # obligatoire (voir .env.example)
    MAX_CONTENT_LENGTH=20 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)
UPLOAD_DIR = os.path.join(app.root_path, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


# ---------- Base de données ----------
def db():
    if "db" not in g:
        g.db = psycopg2.connect(os.environ["DATABASE_URL"],
                                cursor_factory=psycopg2.extras.RealDictCursor)
    return g.db


@app.teardown_appcontext
def fermer_db(_):
    c = g.pop("db", None)
    if c:
        c.close()                                  # sans commit() => annulation automatique


def q(sql, args=(), one=False):
    with db().cursor() as cur:
        cur.execute(sql, args)
        if cur.description is None:
            return None
        return cur.fetchone() if one else cur.fetchall()


def commit():
    db().commit()


# ---------- Sécurité : CSRF, session, rôles ----------
@app.before_request
def csrf():
    session.setdefault("csrf", secrets.token_hex(16))
    if request.method == "POST":
        recu = request.form.get("csrf") or request.headers.get("X-CSRF") or ""
        if not secrets.compare_digest(recu, session["csrf"]):
            abort(400)


def utilisateur():
    if "uid" not in session:
        return None
    if "u" not in g:
        g.u = q("""SELECT u.id, u.nom, u.prenom, r.nom_role AS role FROM users u
                   JOIN roles r ON r.id = u.role_id WHERE u.id = %s""", (session["uid"],), one=True)
    return g.u


def connecte(*roles):
    def deco(f):
        @wraps(f)
        def w(*a, **k):
            u = utilisateur()
            if not u:
                if request.path.startswith("/api/"):
                    return jsonify(erreur="Connectez-vous pour continuer."), 401
                return redirect(url_for("connexion"))
            if roles and u["role"] not in roles:
                abort(403)
            return f(*a, **k)
        return w
    return deco


@app.context_processor
def globals_templates():
    u = utilisateur()
    non_lues = 0
    if u:
        non_lues = q("SELECT COUNT(*) AS n FROM notification WHERE user_id=%s AND NOT lu", (u["id"],), one=True)["n"]
    return dict(user=u, csrf_token=session.get("csrf", ""), non_lues=non_lues)


def annee_active():
    return q("SELECT id, libelle FROM annees WHERE active", one=True)


def etudiant_courant():
    return q("""SELECT e.id, e.matricule, e.classe_id, c.nom AS classe FROM etudiants e
                JOIN classes c ON c.id = e.classe_id WHERE e.user_id = %s""", (session["uid"],), one=True)


# ---------- Pages publiques ----------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/accueil")
def accueil():
    return render_template("accueil.html")


@app.route("/formations")
def formations():
    return render_template("formations.html")


# ---------- Portail : inscription / connexion ----------
TEL_SQL = r"regexp_replace(telephone, '\D', '', 'g')"      # le numéro réduit à ses chiffres


def normaliser_tel(t):
    """'+242 06 123-45.67' -> '242061234567' : seuls les chiffres comptent, donc espaces, tirets,
    points, parenthèses et « + » n'ont aucune importance (même forme à l'inscription et à la connexion)."""
    return re.sub(r"\D", "", t or "")


def page_portail(form=None, code=200):
    # les classes « de groupe » (Coconut Amphi 200, Orange, Banana, Apple) passent en premier
    classes = q("""SELECT id, nom, (niveau_id IS NULL) AS groupe FROM classes
                   ORDER BY (niveau_id IS NULL) DESC, nom""")
    return render_template("portail.html", classes=classes, form=form or {}), code


@app.get("/portail")
def portail():
    return page_portail()


@app.post("/inscription")
def inscription():
    f = request.form
    role = f.get("role")
    nom, prenom = (f.get(k, "").strip() for k in ("nom", "prenom"))
    tel = normaliser_tel(f.get("telephone"))
    mdp = f.get("mot_de_passe", "")
    classe_id = f.get("classe_id", type=int)

    erreur = None
    if role not in ("etudiant", "enseignant"):
        erreur = "Choisissez votre profil : étudiant ou professeur."
    elif not (nom and prenom):
        erreur = "Renseignez votre nom et votre prénom."
    elif not re.fullmatch(r"\d{6,15}", tel):
        erreur = "Numéro de téléphone invalide (6 à 15 chiffres)."
    elif len(mdp) < 8:
        erreur = "Le mot de passe doit faire 8 caractères au minimum."
    elif role == "etudiant" and not (classe_id and q("SELECT 1 FROM classes WHERE id=%s", (classe_id,), one=True)):
        erreur = "Choisissez votre classe dans la liste."
    if erreur:
        flash(erreur, "erreur")
        return page_portail(f, 400)             # on garde ce que la personne a déjà saisi

    if q(f"SELECT 1 FROM users WHERE {TEL_SQL}=%s", (tel,), one=True):
        flash("Ce numéro est déjà inscrit. Connectez-vous.", "erreur")
        return redirect(url_for("connexion"))
    try:
        u = q("""INSERT INTO users(nom, prenom, telephone, mot_de_passe, role_id)
                 VALUES (%s,%s,%s,%s,(SELECT id FROM roles WHERE nom_role=%s)) RETURNING id""",
              (nom, prenom, tel, generate_password_hash(mdp), role), one=True)
        if role == "etudiant":
            q("INSERT INTO etudiants(user_id, matricule, classe_id) VALUES (%s,%s,%s)",
              (u["id"], f"ECAM{date.today():%y}{u['id']:05d}", classe_id))
        else:
            q("INSERT INTO enseignants(user_id) VALUES (%s)", (u["id"],))
        commit()
    except psycopg2.errors.UniqueViolation:     # deux inscriptions simultanées avec le même numéro
        db().rollback()
        flash("Ce numéro est déjà inscrit. Connectez-vous.", "erreur")
        return redirect(url_for("connexion"))
    session.clear()
    session["uid"] = u["id"]
    flash("Compte créé : bienvenue à l’ECAM !", "ok")
    return redirect(url_for("dashboard"))


@app.route("/connexion", methods=["GET", "POST"])
def connexion():
    if request.method == "POST":
        tel = normaliser_tel(request.form.get("telephone"))
        row = q(f"SELECT id, mot_de_passe FROM users WHERE {TEL_SQL}=%s", (tel,), one=True)
        if row and check_password_hash(row["mot_de_passe"], request.form.get("mot_de_passe", "")):
            session.clear()
            session["uid"] = row["id"]
            return redirect(url_for("dashboard"))
        flash("Téléphone ou mot de passe incorrect. Vérifiez le numéro, ou inscrivez-vous si vous n’avez pas encore de compte.", "erreur")
    return render_template("connexion.html")


@app.post("/deconnexion")
def deconnexion():
    session.clear()
    return redirect(url_for("accueil"))


# ---------- Espace étudiant ----------
@app.get("/tableau-de-bord")
@connecte()
def dashboard():
    role = utilisateur()["role"]
    if role == "enseignant":
        return redirect(url_for("espace_enseignant"))
    if role != "etudiant":
        return redirect(url_for("espace_direction"))
    et, an = etudiant_courant(), annee_active()
    a = an["id"] if an else None
    acces = q("SELECT autorise FROM acces_resultat WHERE etudiant_id=%s", (et["id"],), one=True)
    autorise = bool(acces and acces["autorise"])
    moyenne = q("""SELECT ROUND(SUM(valeur*coefficient)/NULLIF(SUM(coefficient),0),2) AS m
                   FROM notes WHERE etudiant_id=%s AND annee_id=%s""", (et["id"], a), one=True)["m"]
    presence = q("""SELECT ROUND(100.0*COUNT(*) FILTER (WHERE present)/NULLIF(COUNT(*),0)) AS t
                    FROM presences WHERE etudiant_id=%s""", (et["id"],), one=True)["t"]
    total = q("SELECT COALESCE(SUM(montant),0) AS t FROM types_paiements WHERE obligatoire", one=True)["t"]
    paye = q("""SELECT COALESCE(SUM(montant),0) AS t FROM paiements
                WHERE etudiant_id=%s AND annee_id=%s AND statut='valide'""", (et["id"], a), one=True)["t"]
    credits = q("""SELECT COALESCE(SUM(m.credits) FILTER (WHERE moy.moyenne >= 10),0) AS valides,
                          COALESCE(SUM(m.credits),0) AS total
                   FROM matieres m LEFT JOIN (
                     SELECT matiere_id, SUM(valeur*coefficient)/NULLIF(SUM(coefficient),0) AS moyenne
                     FROM notes WHERE etudiant_id=%s AND annee_id=%s GROUP BY matiere_id) moy
                     ON moy.matiere_id = m.id WHERE m.classe_id=%s""", (et["id"], a, et["classe_id"]), one=True)
    resultats = q("""SELECT m.nom, n.valeur,
                       (SELECT ROUND(AVG(x.valeur),2) FROM notes x WHERE x.matiere_id=n.matiere_id
                          AND x.annee_id=n.annee_id AND x.type_note=n.type_note) AS moy_classe
                     FROM notes n JOIN matieres m ON m.id=n.matiere_id
                     WHERE n.etudiant_id=%s AND n.annee_id=%s ORDER BY n.id DESC LIMIT 5""",
                  (et["id"], a)) if autorise else []
    cours_jour = q("""SELECT m.nom AS cours, u.nom AS prof, s.nom AS salle, e.heure_debut, e.heure_fin
                      FROM emplois_temps e JOIN matieres m ON m.id=e.matiere_id
                      LEFT JOIN enseignants en ON en.id=e.enseignant_id LEFT JOIN users u ON u.id=en.user_id
                      LEFT JOIN salles s ON s.id=e.salle_id
                      WHERE m.classe_id=%s AND e.annee_id=%s AND e.jour=%s ORDER BY e.heure_debut""",
                   (et["classe_id"], a, date.today().isoweekday()))
    mois = {r["mois"] for r in q("""SELECT DISTINCT EXTRACT(MONTH FROM date_paie)::int AS mois FROM paiements
                                    WHERE etudiant_id=%s AND annee_id=%s AND statut='valide'""", (et["id"], a))}
    return render_template("dashboard.html", et=et, an=an, autorise=autorise, moyenne=moyenne, presence=presence,
                           reste=max(total - paye, 0), credits=credits, resultats=resultats,
                           cours_jour=cours_jour, mois=mois)


@app.get("/emploi-du-temps")
@connecte("etudiant", "directeur_etudes", "admin")
def emploi_du_temps():
    classes = q("SELECT id, nom FROM classes ORDER BY nom")
    if utilisateur()["role"] == "etudiant":
        classe_id = etudiant_courant()["classe_id"]
    else:
        classe_id = request.args.get("classe_id", type=int)
    grille, creneaux = {}, set()
    an = annee_active()
    if classe_id and an:
        for r in q("""SELECT m.nom AS cours, u.nom AS prof, s.nom AS salle, e.jour, e.heure_debut, e.heure_fin
                      FROM emplois_temps e JOIN matieres m ON m.id=e.matiere_id
                      LEFT JOIN enseignants en ON en.id=e.enseignant_id LEFT JOIN users u ON u.id=en.user_id
                      LEFT JOIN salles s ON s.id=e.salle_id
                      WHERE m.classe_id=%s AND e.annee_id=%s ORDER BY e.heure_debut""", (classe_id, an["id"])):
            c = (r["heure_debut"], r["heure_fin"])
            creneaux.add(c)
            grille.setdefault((c, r["jour"]), []).append(r)
    return render_template("emploi_du_temps.html", classes=classes, classe_id=classe_id,
                           creneaux=sorted(creneaux), grille=grille)


# ---------- Bibliothèque ----------
@app.get("/bibliotheque")
@connecte()
def bibliotheque():
    t = request.args.get("q", "").strip()
    livres = q("""SELECT l.id, l.titre, l.matiere, f.code AS filiere, l.annee FROM livres l
                  LEFT JOIN filieres f ON f.id=l.filiere_id
                  WHERE l.statut='valide' AND (%s='' OR l.titre ILIKE %s OR l.matiere ILIKE %s)
                  ORDER BY l.date_depot DESC LIMIT 100""", (t, f"%{t}%", f"%{t}%"))
    attente = q("""SELECT id, titre, matiere FROM livres WHERE statut='en_attente' ORDER BY date_depot""") \
        if utilisateur()["role"] in ("directeur_etudes", "admin") else []
    return render_template("bibliotheque.html", livres=livres, attente=attente, t=t)


@app.route("/bibliotheque/ajout", methods=["GET", "POST"])
@connecte()
def ajout():
    filieres = q("SELECT id, code FROM filieres ORDER BY code")
    if request.method == "POST":
        fic, titre = request.files.get("fichier"), request.form.get("titre", "").strip()
        if not (fic and titre) or not fic.filename.lower().endswith(".pdf") or fic.stream.read(4) != b"%PDF":
            flash("Indiquez un titre et choisissez un fichier PDF.", "erreur")
            return redirect(url_for("ajout"))
        fic.stream.seek(0)
        nom = f"{secrets.token_hex(8)}_{secure_filename(fic.filename)}"
        fic.save(os.path.join(UPLOAD_DIR, nom))
        statut = "valide" if utilisateur()["role"] in ("enseignant", "directeur_etudes", "admin") else "en_attente"
        q("""INSERT INTO livres(titre, matiere, filiere_id, annee, fichier, depose_par, statut)
             VALUES (%s,%s,%s,%s,%s,%s,%s)""",
          (titre, request.form.get("matiere", "").strip() or None, request.form.get("filiere_id", type=int),
           request.form.get("annee", type=int), nom, session["uid"], statut))
        commit()
        flash("Document publié." if statut == "valide" else "Document reçu : il sera visible après validation.", "ok")
        return redirect(url_for("bibliotheque"))
    return render_template("ajout.html", filieres=filieres, annee_courante=date.today().year)


@app.post("/bibliotheque/valider/<int:livre_id>")
@connecte("directeur_etudes", "admin")
def valider_livre(livre_id):
    statut = "valide" if request.form.get("decision") == "valide" else "refuse"
    q("UPDATE livres SET statut=%s WHERE id=%s", (statut, livre_id))
    commit()
    return redirect(url_for("bibliotheque"))


@app.get("/fichier/<int:livre_id>")
@connecte()
def fichier(livre_id):
    r = q("SELECT fichier FROM livres WHERE id=%s AND statut='valide'", (livre_id,), one=True)
    if not r:
        abort(404)
    return send_from_directory(UPLOAD_DIR, r["fichier"])


# ---------- Outils d’écriture ----------
def nombre(champ):
    try:
        v = float(request.form.get(champ, "").replace(",", "."))
        return v if v == v and abs(v) != float("inf") else None
    except ValueError:
        return None


def tenter(fn, ok):
    """Exécute des écritures en base : tout est annulé si une erreur survient."""
    try:
        if fn() is False:
            db().rollback()
            flash("Élément introuvable : vérifiez la saisie.", "erreur")
            return
        commit()
        flash(ok, "ok")
    except psycopg2.Error:
        db().rollback()
        flash("Enregistrement impossible : vérifiez les valeurs saisies.", "erreur")


# ---------- Espace enseignant ----------
def charger_matiere(mid):
    an = annee_active()
    ens = q("SELECT id FROM enseignants WHERE user_id=%s", (session["uid"],), one=True)
    m = q("""SELECT m.id, m.nom, m.classe_id, c.nom AS classe FROM affectations a
             JOIN matieres m ON m.id=a.matiere_id JOIN classes c ON c.id=m.classe_id
             WHERE a.enseignant_id=%s AND a.matiere_id=%s AND a.annee_id=%s""",
          (ens["id"] if ens else None, mid, an["id"] if an else None), one=True)
    if not m:
        abort(404)
    return m, ens["id"], an


@app.get("/enseignant")
@connecte("enseignant")
def espace_enseignant():
    an = annee_active()
    mats = q("""SELECT m.id, m.nom, c.nom AS classe, s.nom AS semestre FROM affectations a
                JOIN enseignants en ON en.id=a.enseignant_id JOIN matieres m ON m.id=a.matiere_id
                JOIN classes c ON c.id=m.classe_id JOIN semestres s ON s.id=m.semestre_id
                WHERE en.user_id=%s AND a.annee_id=%s ORDER BY c.nom, m.nom""",
             (session["uid"], an["id"] if an else None))
    return render_template("enseignant.html", mats=mats)


@app.get("/enseignant/matiere/<int:mid>")
@connecte("enseignant")
def saisie(mid):
    m, _, _ = charger_matiere(mid)
    etus = q("""SELECT e.id, e.matricule, u.nom, u.prenom FROM etudiants e JOIN users u ON u.id=e.user_id
                WHERE e.classe_id=%s ORDER BY u.nom, u.prenom""", (m["classe_id"],))
    return render_template("saisie.html", m=m, etus=etus, aujourdhui=date.today().isoformat())


@app.post("/enseignant/matiere/<int:mid>/notes")
@connecte("enseignant")
def saisir_notes(mid):
    m, ens, an = charger_matiere(mid)
    type_note, coef = request.form.get("type_note"), nombre("coefficient")
    if type_note not in ("devoir", "tp", "examen") or not coef or coef <= 0:
        flash("Choisissez un type de note et un coefficient valide.", "erreur")
        return redirect(url_for("saisie", mid=mid))
    lignes = []
    for e in q("SELECT id FROM etudiants WHERE classe_id=%s", (m["classe_id"],)):
        brut = request.form.get(f"note_{e['id']}", "").strip().replace(",", ".")
        if not brut:
            continue
        try:
            v = float(brut)
        except ValueError:
            v = -1
        if not 0 <= v <= 20:
            flash(f"Note invalide « {brut} » : saisie annulée, les notes doivent être entre 0 et 20.", "erreur")
            return redirect(url_for("saisie", mid=mid))
        lignes.append((e["id"], mid, ens, an["id"], type_note, v, coef))

    def go():
        for l in lignes:
            q("""INSERT INTO notes(etudiant_id, matiere_id, enseignant_id, annee_id, type_note, valeur, coefficient)
                 VALUES (%s,%s,%s,%s,%s,%s,%s)""", l)
    tenter(go, f"{len(lignes)} note(s) enregistrée(s).")
    return redirect(url_for("saisie", mid=mid))


@app.post("/enseignant/matiere/<int:mid>/presences")
@connecte("enseignant")
def saisir_presences(mid):
    m, _, _ = charger_matiere(mid)
    try:
        jour = date.fromisoformat(request.form.get("date", ""))
    except ValueError:
        flash("Date invalide.", "erreur")
        return redirect(url_for("saisie", mid=mid))

    def go():
        for e in q("SELECT id FROM etudiants WHERE classe_id=%s", (m["classe_id"],)):
            q("""INSERT INTO presences(etudiant_id, matiere_id, date_p, present) VALUES (%s,%s,%s,%s)
                 ON CONFLICT (etudiant_id, matiere_id, date_p) DO UPDATE SET present = EXCLUDED.present""",
              (e["id"], mid, jour, f"present_{e['id']}" in request.form))
    tenter(go, "Présences enregistrées.")
    return redirect(url_for("saisie", mid=mid))


# ---------- Espace direction ----------
@app.get("/direction")
@connecte("directeur_etudes", "admin")
def espace_direction():
    stats = q("""SELECT (SELECT COUNT(*) FROM etudiants) AS etudiants,
                        (SELECT COUNT(*) FROM enseignants) AS enseignants,
                        (SELECT COUNT(*) FROM livres WHERE statut='en_attente') AS docs""", one=True)
    return render_template(
        "direction.html", stats=stats,
        classes=q("SELECT id, nom FROM classes ORDER BY nom"),
        semestres=q("SELECT id, nom FROM semestres ORDER BY id"),
        matieres=q("SELECT m.id, m.nom || ' — ' || c.nom AS nom FROM matieres m JOIN classes c ON c.id=m.classe_id ORDER BY c.nom, m.nom"),
        enseignants=q("SELECT en.id, u.nom || ' ' || u.prenom AS nom FROM enseignants en JOIN users u ON u.id=en.user_id ORDER BY u.nom"),
        types=q("SELECT id, nom FROM types_paiements ORDER BY nom"))


@app.post("/direction/matiere")
@connecte("directeur_etudes", "admin")
def dir_matiere():
    f, an = request.form, annee_active()
    nom, coef, cred = f.get("nom", "").strip(), nombre("coefficient"), f.get("credits", type=int)
    cl, se, ens = f.get("classe_id", type=int), f.get("semestre_id", type=int), f.get("enseignant_id", type=int)
    if not (nom and coef and coef > 0 and cred is not None and cred >= 0 and cl and se):
        flash("Renseignez le nom, le coefficient, les crédits, la classe et le semestre.", "erreur")
        return redirect(url_for("espace_direction"))

    def go():
        m = q("""INSERT INTO matieres(nom, coefficient, credits, classe_id, semestre_id) VALUES (%s,%s,%s,%s,%s)
                 ON CONFLICT (nom, classe_id, semestre_id) DO UPDATE
                 SET coefficient=EXCLUDED.coefficient, credits=EXCLUDED.credits RETURNING id""",
              (nom, coef, cred, cl, se), one=True)
        if ens and an:
            q("INSERT INTO affectations(enseignant_id, matiere_id, annee_id) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
              (ens, m["id"], an["id"]))
    tenter(go, "Matière enregistrée.")
    return redirect(url_for("espace_direction"))


@app.post("/direction/emploi")
@connecte("directeur_etudes", "admin")
def dir_emploi():
    f, an = request.form, annee_active()
    mid, jour = f.get("matiere_id", type=int), f.get("jour", type=int)
    try:
        d, e = time.fromisoformat(f.get("debut", "")), time.fromisoformat(f.get("fin", ""))
    except ValueError:
        d = e = None
    if not (an and mid and jour in range(1, 8) and d and e and e > d):
        flash("Choisissez la matière, le jour et des horaires valides (fin après début).", "erreur")
        return redirect(url_for("espace_direction"))

    def go():
        salle, sid = f.get("salle", "").strip(), None
        if salle:
            sid = q("INSERT INTO salles(nom) VALUES (%s) ON CONFLICT (nom) DO UPDATE SET nom=EXCLUDED.nom RETURNING id",
                    (salle,), one=True)["id"]
        ens = q("SELECT enseignant_id FROM affectations WHERE matiere_id=%s AND annee_id=%s LIMIT 1",
                (mid, an["id"]), one=True)
        q("""INSERT INTO emplois_temps(matiere_id, enseignant_id, salle_id, annee_id, jour, heure_debut, heure_fin)
             VALUES (%s,%s,%s,%s,%s,%s,%s)""",
          (mid, ens["enseignant_id"] if ens else None, sid, an["id"], jour, d, e))
    tenter(go, "Cours ajouté à l’emploi du temps.")
    return redirect(url_for("espace_direction"))


@app.post("/direction/resultats")
@connecte("directeur_etudes", "admin")
def dir_resultats():
    cid, autorise = request.form.get("classe_id", type=int), request.form.get("autorise") == "1"
    if not cid:
        flash("Choisissez une classe.", "erreur")
        return redirect(url_for("espace_direction"))
    tenter(lambda: q("""INSERT INTO acces_resultat(etudiant_id, autorise)
                        SELECT id, %s FROM etudiants WHERE classe_id=%s
                        ON CONFLICT (etudiant_id) DO UPDATE SET autorise = EXCLUDED.autorise""", (autorise, cid)),
           "Accès aux résultats mis à jour pour la classe.")
    return redirect(url_for("espace_direction"))


@app.post("/direction/type-paiement")
@connecte("directeur_etudes", "admin")
def dir_type_paiement():
    nom, montant = request.form.get("nom", "").strip(), nombre("montant")
    if not nom or montant is None or montant < 0:
        flash("Indiquez un nom et un montant valide.", "erreur")
        return redirect(url_for("espace_direction"))
    tenter(lambda: q("""INSERT INTO types_paiements(nom, montant, obligatoire) VALUES (%s,%s,%s)
                        ON CONFLICT (nom) DO UPDATE SET montant=EXCLUDED.montant, obligatoire=EXCLUDED.obligatoire""",
                     (nom, montant, request.form.get("obligatoire") == "1")),
           "Type de paiement enregistré.")
    return redirect(url_for("espace_direction"))


@app.post("/direction/paiement")
@connecte("directeur_etudes", "admin")
def dir_paiement():
    f, an, montant = request.form, annee_active(), nombre("montant")
    if not (an and montant and montant > 0 and f.get("type_paiement_id", type=int)
            and f.get("mode_paie") in ("especes", "mobile_money", "virement", "cheque")):
        flash("Renseignez le matricule, le type, un montant positif et le mode de paiement.", "erreur")
        return redirect(url_for("espace_direction"))
    tenter(lambda: bool(q("""INSERT INTO paiements(etudiant_id, type_paiement_id, annee_id, montant, mode_paie)
                             SELECT id, %s, %s, %s, %s FROM etudiants WHERE matricule=%s RETURNING id""",
                          (f.get("type_paiement_id", type=int), an["id"], montant, f["mode_paie"],
                           f.get("matricule", "").strip()))),
           "Paiement enregistré.")
    return redirect(url_for("espace_direction"))


@app.post("/direction/message")
@connecte("directeur_etudes", "admin")
def dir_message():
    f, u = request.form, utilisateur()
    texte, sujet = f.get("message", "").strip()[:1000], f.get("sujet", "").strip()[:80] or "Message"
    ids = [r["user_id"] for r in q("SELECT user_id FROM etudiants WHERE matricule=%s", (f.get("matricule", "").strip(),))]
    if not texte or not ids:
        flash("Matricule introuvable ou message vide.", "erreur")
        return redirect(url_for("espace_direction"))

    def go():
        for i in ids:
            q("INSERT INTO notification(user_id, expediteur_id, titre, message) VALUES (%s,%s,%s,%s)",
              (i, u["id"], f"{sujet} (de {u['prenom']} {u['nom']})", texte))
    tenter(go, "Message envoyé à l’étudiant.")
    return redirect(url_for("espace_direction"))


# ---------- Messages ----------
@app.get("/messages")
@connecte()
def notifications():
    msgs = q("""SELECT n.id, n.titre, n.message, n.lu, n.date_envoi FROM notification n
                WHERE n.user_id=%s ORDER BY n.date_envoi DESC LIMIT 50""", (session["uid"],))
    resp = render_template("messages.html", msgs=msgs)
    q("UPDATE notification SET lu=true WHERE user_id=%s AND NOT lu", (session["uid"],))
    commit()
    return resp


@app.post("/api/transmettre")
@connecte()
def api_transmettre():
    d = request.get_json(silent=True) or {}
    texte = (d.get("message") or "").strip()[:1000]
    sujet = (d.get("sujet") or "Message").strip()[:80]
    if not texte:
        return jsonify(erreur="Le message est vide."), 400
    u = utilisateur()
    if d.get("destinataire") == "directeur_etudes":
        ids = [r["id"] for r in q("""SELECT u.id FROM users u JOIN roles r ON r.id=u.role_id
                                     WHERE r.nom_role='directeur_etudes'""")]
    elif u["role"] in ("enseignant", "directeur_etudes", "admin"):     # message à un étudiant, par matricule
        ids = [r["user_id"] for r in q("SELECT user_id FROM etudiants WHERE matricule=%s", (str(d.get("destinataire")),))]
    else:
        return jsonify(erreur="Destinataire non autorisé."), 403
    if not ids:
        return jsonify(erreur="Aucun destinataire trouvé."), 404
    for i in ids:
        q("INSERT INTO notification(user_id, expediteur_id, titre, message) VALUES (%s,%s,%s,%s)",
          (i, u["id"], f"{sujet} (de {u['prenom']} {u['nom']})", texte))
    commit()
    return jsonify(ok=True)


# ---------- Assistant (agent Mistral) ----------
SUJETS = {
    "inscription": ("Pour vous inscrire, choisissez votre profil (étudiant ou professeur) sur le portail.",
                    [("Ouvrir le portail", "portail")]),
    "formations": ("Licences professionnelles, masters délocalisés et cursus d’ingénieur : tout est détaillé ici.",
                   [("Voir les formations", "formations")]),
    "emploi": ("Votre emploi du temps se consulte dans votre espace.", [("Emploi du temps", "emploi_du_temps")]),
    "resultats": ("Vos notes et votre moyenne s’affichent sur votre tableau de bord, une fois autorisées par l’administration.",
                  [("Tableau de bord", "dashboard")]),
    "paiements": ("Le solde restant et les mois réglés figurent sur votre tableau de bord.",
                  [("Tableau de bord", "dashboard")]),
    "bibliotheque": ("Cherchez un document ou déposez le vôtre pour enrichir la bibliothèque.",
                     [("Bibliothèque", "bibliotheque"), ("Ajouter un document", "ajout")]),
}
_client = None


def demander_agent(historique):
    global _client
    if _client is None:
        from mistralai.client import Mistral
        _client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
    r = _client.beta.conversations.start(
        agent_id=os.environ.get("MISTRAL_AGENT_ID", "ag_019f3e51c86575dbaee9834c3686c1cc"),
        agent_version=0, inputs=historique)
    for o in r.outputs or []:
        if o.type == "message.output":
            c = o.content
            return c if isinstance(c, str) else "".join(getattr(p, "text", "") for p in c)
    return None


@app.post("/api/chat")
def api_chat():
    d = request.get_json(silent=True) or {}
    if d.get("topic") in SUJETS:
        rep, liens = SUJETS[d["topic"]]
        return jsonify(reponse=rep, liens=[{"label": l, "url": url_for(e)} for l, e in liens])
    texte = (d.get("message") or "").strip()[:500]
    if not texte:
        return jsonify(erreur="Écrivez un message."), 400
    sid = session.setdefault("chat", secrets.token_hex(16))
    if q("""SELECT COUNT(*) AS n FROM chat_messages WHERE session_id=%s AND role='user'
            AND date_msg > now() - interval '1 hour'""", (sid,), one=True)["n"] >= 20:
        return jsonify(erreur="Limite atteinte : réessayez dans une heure."), 429
    u = utilisateur()
    histo = list(reversed(q("SELECT role, contenu FROM chat_messages WHERE session_id=%s ORDER BY id DESC LIMIT 8", (sid,))))
    contexte = f"[Profil : {u['role']}] " if u else "[Visiteur non connecté] "
    entree = [{"role": h["role"], "content": h["contenu"]} for h in histo] + [{"role": "user", "content": contexte + texte}]
    try:
        reponse = demander_agent(entree)
    except Exception:
        app.logger.exception("Erreur agent Mistral")
        reponse = None
    if not reponse:
        return jsonify(erreur="L’assistant est indisponible pour le moment. Choisissez un sujet ci-dessus."), 502
    uid = u["id"] if u else None
    q("INSERT INTO chat_messages(session_id,user_id,role,contenu) VALUES (%s,%s,'user',%s),(%s,%s,'assistant',%s)",
      (sid, uid, texte, sid, uid, reponse))
    commit()
    return jsonify(reponse=reponse)


# ---------- Création d’un compte direction (commande) ----------
@app.cli.command("creer-direction")
@click.option("--nom", prompt=True)
@click.option("--prenom", prompt=True)
@click.option("--telephone", prompt=True)
@click.password_option()
def creer_direction(nom, prenom, telephone, password):
    """Crée un compte directeur d’études : flask --app app creer-direction"""
    q("""INSERT INTO users(nom, prenom, telephone, mot_de_passe, role_id)
         VALUES (%s,%s,%s,%s,(SELECT id FROM roles WHERE nom_role='directeur_etudes'))""",
      (nom, prenom, normaliser_tel(telephone), generate_password_hash(password)))
    commit()
    click.echo("Compte créé.")


if __name__ == "__main__":
    app.run(debug=True)
