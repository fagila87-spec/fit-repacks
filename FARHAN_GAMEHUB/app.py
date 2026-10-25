import os, sqlite3, secrets, hashlib, hmac, re
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse
from flask import Flask, render_template, request, redirect, url_for, session, flash, abort, send_from_directory
from werkzeug.utils import secure_filename

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "gamehub.db"
STORAGE = ROOT / "storage"
STORAGE.mkdir(exist_ok=True)
app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024 * 1024  # 8 GB per upload; tune for your host
ALLOWED_COVERS = {"png", "jpg", "jpeg", "webp"}
ALLOWED_ARCHIVES = {"zip", "7z", "rar", "iso", "tar", "gz", "xz"}

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def hash_password(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    hashed = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return salt.hex() + "$" + hashed.hex()

def verify_password(password, stored):
    try:
        salt_hex, hash_hex = stored.split("$", 1)
        return hmac.compare_digest(hash_password(password, bytes.fromhex(salt_hex)).split("$", 1)[1], hash_hex)
    except (ValueError, TypeError):
        return False

def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS admins(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          username TEXT UNIQUE NOT NULL,
          password_hash TEXT NOT NULL,
          role TEXT NOT NULL DEFAULT 'admin',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS games(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          title TEXT NOT NULL,
          slug TEXT UNIQUE NOT NULL,
          description TEXT NOT NULL DEFAULT '',
          genre TEXT NOT NULL DEFAULT '',
          version TEXT NOT NULL DEFAULT '',
          size TEXT NOT NULL DEFAULT '',
          requirements TEXT NOT NULL DEFAULT '',
          cover TEXT NOT NULL DEFAULT '',
          direct_file TEXT NOT NULL DEFAULT '',
          magnet TEXT NOT NULL DEFAULT '',
          external_url TEXT NOT NULL DEFAULT '',
          featured INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS downloads(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """)
        if not c.execute("SELECT id FROM admins LIMIT 1").fetchone():
            username = os.environ.get("INITIAL_ADMIN_USER", "farhan")
            password = os.environ.get("INITIAL_ADMIN_PASSWORD", "farhan.811281")
            c.execute("INSERT INTO admins(username,password_hash,role) VALUES(?,?,?)",
                      (username, hash_password(password), "owner"))
        if not c.execute("SELECT id FROM games LIMIT 1").fetchone():
            c.execute("""INSERT INTO games(title,slug,description,genre,version,size,requirements,featured)
                         VALUES(?,?,?,?,?,?,?,1)""",
                      ("Your First Game", "your-first-game",
                       "Use the admin panel to replace this sample with a game or project you are authorised to distribute.",
                       "Indie", "1.0", "TBA", "Add system requirements in the admin panel."))

def current_admin():
    if "admin_id" not in session:
        return None
    with db() as c:
        return c.execute("SELECT id,username,role FROM admins WHERE id=?", (session["admin_id"],)).fetchone()

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_admin():
            return redirect(url_for("login", next=request.path))
        return fn(*args, **kwargs)
    return wrapper

def owner_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        admin = current_admin()
        if not admin:
            return redirect(url_for("login"))
        if admin["role"] != "owner":
            abort(403)
        return fn(*args, **kwargs)
    return wrapper

def slugify(s):
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s.strip().lower()).strip("-")
    return s[:80] or secrets.token_hex(4)

def allowed(filename, extensions):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in extensions

@app.context_processor
def inject_globals():
    return {"logged_admin": current_admin()}

@app.route("/")
def index():
    q = request.args.get("q", "").strip()
    genre = request.args.get("genre", "").strip()
    with db() as c:
        genres = [r["genre"] for r in c.execute("SELECT DISTINCT genre FROM games WHERE genre!='' ORDER BY genre")]
        sql = "SELECT * FROM games WHERE 1=1"
        args = []
        if q:
            sql += " AND (title LIKE ? OR description LIKE ? OR genre LIKE ?)"
            args += [f"%{q}%"] * 3
        if genre:
            sql += " AND genre=?"
            args.append(genre)
        sql += " ORDER BY featured DESC, created_at DESC"
        games = c.execute(sql, args).fetchall()
        count = c.execute("SELECT COUNT(*) n FROM games").fetchone()["n"]
    return render_template("index.html", games=games, genres=genres, q=q, genre=genre, count=count)

@app.route("/game/<slug>")
def game_detail(slug):
    with db() as c:
        game = c.execute("SELECT * FROM games WHERE slug=?", (slug,)).fetchone()
    if not game:
        abort(404)
    return render_template("game.html", game=game)

@app.route("/download/<int:game_id>")
def download(game_id):
    with db() as c:
        game = c.execute("SELECT * FROM games WHERE id=?", (game_id,)).fetchone()
        if not game or not game["direct_file"]:
            abort(404)
        c.execute("INSERT INTO downloads(game_id) VALUES(?)", (game_id,))
    return send_from_directory(STORAGE, game["direct_file"], as_attachment=True, download_name=game["direct_file"])

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        with db() as c:
            admin = c.execute("SELECT * FROM admins WHERE username=?", (username,)).fetchone()
        if admin and verify_password(password, admin["password_hash"]):
            session.clear()
            session["admin_id"] = admin["id"]
            flash("Welcome back. Admin session started.", "success")
            return redirect(request.args.get("next") or url_for("dashboard"))
        flash("Invalid username or password.", "error")
    return render_template("login.html")

@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("index"))

@app.route("/admin")
@login_required
def dashboard():
    with db() as c:
        games = c.execute("""SELECT g.*, (SELECT COUNT(*) FROM downloads d WHERE d.game_id=g.id) downloads
                             FROM games g ORDER BY g.created_at DESC""").fetchall()
        admins = c.execute("SELECT id,username,role,created_at FROM admins ORDER BY id").fetchall()
        downloads = c.execute("SELECT COUNT(*) n FROM downloads").fetchone()["n"]
    return render_template("admin.html", games=games, admins=admins, downloads=downloads, admin=current_admin())

@app.route("/admin/game/new", methods=["GET", "POST"])
@app.route("/admin/game/<int:game_id>/edit", methods=["GET", "POST"])
@login_required
def edit_game(game_id=None):
    with db() as c:
        game = c.execute("SELECT * FROM games WHERE id=?", (game_id,)).fetchone() if game_id else None
    if game_id and not game:
        abort(404)
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        if not title:
            flash("A title is required.", "error")
            return redirect(request.url)
        slug = slugify(request.form.get("slug", "") or title)
        with db() as c:
            clash = c.execute("SELECT id FROM games WHERE slug=? AND id!=?", (slug, game_id or -1)).fetchone()
        if clash:
            slug += "-" + secrets.token_hex(2)
        cover_name = game["cover"] if game else ""
        direct_file = game["direct_file"] if game else ""
        cover = request.files.get("cover")
        upload = request.files.get("direct_file")
        if cover and cover.filename:
            if not allowed(cover.filename, ALLOWED_COVERS):
                flash("Cover must be PNG, JPG, JPEG, or WEBP.", "error")
                return redirect(request.url)
            cover_name = secrets.token_hex(8) + "." + secure_filename(cover.filename).rsplit(".",1)[1].lower()
            cover.save(STORAGE / cover_name)
        if upload and upload.filename:
            if not allowed(upload.filename, ALLOWED_ARCHIVES):
                flash("File must be a supported archive/ISO type.", "error")
                return redirect(request.url)
            direct_file = secrets.token_hex(8) + "_" + secure_filename(upload.filename)
            upload.save(STORAGE / direct_file)
        fields = (
            title, slug, request.form.get("description", "").strip(),
            request.form.get("genre", "").strip(), request.form.get("version", "").strip(),
            request.form.get("size", "").strip(), request.form.get("requirements", "").strip(),
            cover_name, direct_file, request.form.get("magnet", "").strip(),
            request.form.get("external_url", "").strip(), 1 if request.form.get("featured") else 0
        )
        if fields[9] and not fields[9].startswith("magnet:?xt="):
            flash("Magnet links must start with magnet:?xt=.", "error")
            return redirect(request.url)
        if fields[10]:
            parsed = urlparse(fields[10])
            if parsed.scheme not in {"https", "http"}:
                flash("External download URL must use HTTP or HTTPS.", "error")
                return redirect(request.url)
        with db() as c:
            if game:
                c.execute("""UPDATE games SET title=?,slug=?,description=?,genre=?,version=?,size=?,requirements=?,
                             cover=?,direct_file=?,magnet=?,external_url=?,featured=? WHERE id=?""", fields + (game_id,))
            else:
                c.execute("""INSERT INTO games(title,slug,description,genre,version,size,requirements,cover,direct_file,
                             magnet,external_url,featured) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", fields)
        flash("Game saved.", "success")
        return redirect(url_for("dashboard"))
    return render_template("edit_game.html", game=game)

@app.route("/admin/game/<int:game_id>/delete", methods=["POST"])
@login_required
def delete_game(game_id):
    with db() as c:
        game = c.execute("SELECT * FROM games WHERE id=?", (game_id,)).fetchone()
        if game:
            for name in (game["cover"], game["direct_file"]):
                if name:
                    try: (STORAGE / name).unlink(missing_ok=True)
                    except OSError: pass
            c.execute("DELETE FROM games WHERE id=?", (game_id,))
    flash("Game deleted.", "success")
    return redirect(url_for("dashboard"))

@app.route("/admin/accounts", methods=["POST"])
@owner_required
def create_admin():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    role = request.form.get("role", "admin")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,32}", username):
        flash("Username must be 3–32 characters: letters, numbers, dot, dash, underscore.", "error")
        return redirect(url_for("dashboard"))
    if len(password) < 12:
        flash("Use a unique password of at least 12 characters for each admin account.", "error")
        return redirect(url_for("dashboard"))
    if role not in {"admin", "owner"}:
        role = "admin"
    try:
        with db() as c:
            c.execute("INSERT INTO admins(username,password_hash,role) VALUES(?,?,?)",
                      (username, hash_password(password), role))
        flash(f"Admin account '{username}' created.", "success")
    except sqlite3.IntegrityError:
        flash("That username already exists.", "error")
    return redirect(url_for("dashboard"))

@app.route("/admin/accounts/<int:admin_id>/delete", methods=["POST"])
@owner_required
def delete_admin(admin_id):
    me = current_admin()
    if admin_id == me["id"]:
        flash("You cannot delete the account you are currently using.", "error")
        return redirect(url_for("dashboard"))
    with db() as c:
        target = c.execute("SELECT id,role FROM admins WHERE id=?", (admin_id,)).fetchone()
        if target:
            if target["role"] == "owner":
                owners = c.execute("SELECT COUNT(*) n FROM admins WHERE role='owner'").fetchone()["n"]
                if owners <= 1:
                    flash("You must keep at least one owner account.", "error")
                    return redirect(url_for("dashboard"))
            c.execute("DELETE FROM admins WHERE id=?", (admin_id,))
    flash("Admin account removed.", "success")
    return redirect(url_for("dashboard"))

@app.errorhandler(403)
def forbidden(e):
    return render_template("error.html", code=403, message="This area is reserved for the site owner."), 403

@app.errorhandler(404)
def missing(e):
    return render_template("error.html", code=404, message="That page could not be found."), 404

init_db()
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)
