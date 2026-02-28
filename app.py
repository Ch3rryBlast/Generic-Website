from flask import Flask, session, redirect, render_template, request, jsonify, url_for
from werkzeug.security import generate_password_hash, check_password_hash
import json
from authlib.integrations.flask_client import OAuth
import sqlite3
import os
import math
import uuid
from datetime import datetime
from flask_session import Session
import re
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)

# --- Session config ---
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-change-in-prod")
app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_PERMANENT"] = False
Session(app)

# OAuth setup (Google)
oauth = OAuth(app)
if os.getenv('GOOGLE_CLIENT_ID') and os.getenv('GOOGLE_CLIENT_SECRET'):
    oauth.register(
        name='google',
        client_id=os.getenv('GOOGLE_CLIENT_ID'),
        client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={'scope': 'openid email profile'},
    )

# ---------- Static item hints ----------
ITEMS = {
    "plastic bottle": {
        "bin": "Recycle",
        "prep": ["Empty and rinse", "Put cap back on if accepted locally"],
        "notes": "Most curbside programs accept #1 PET bottles.",
        "link": "https://search.earth911.com/",
        "material": "Plastic",
    },
    "aluminum can": {
        "bin": "Recycle",
        "prep": ["Empty and rinse"],
        "notes": "Aluminum is highly recyclable and saves lots of energy.",
        "link": "https://search.earth911.com/",
        "material": "Metal",
    },
    "glass bottle/jar": {
        "bin": "Recycle",
        "prep": ["Empty and rinse", "Remove lid (rules vary by city)"],
        "notes": "Glass is recyclable, but local acceptance varies.",
        "link": "https://search.earth911.com/",
        "material": "Glass",
    },
    "cardboard box": {
        "bin": "Recycle",
        "prep": ["Flatten the box", "Keep it dry and clean"],
        "notes": "Wet/greasy cardboard is often not recyclable.",
        "link": "https://search.earth911.com/",
        "material": "Paper",
    },
    "paper (clean)": {
        "bin": "Recycle",
        "prep": ["Keep clean and dry"],
        "notes": "Avoid recycling paper with food/grease contamination.",
        "link": "https://search.earth911.com/",
        "material": "Paper",
    },
    "pizza box": {
        "bin": "Depends",
        "prep": ["If clean: recycle", "If greasy: compost (if available) or trash"],
        "notes": "Grease contaminates paper recycling streams.",
        "link": "https://search.earth911.com/",
        "material": "Paper",
    },
    "styrofoam": {
        "bin": "Special Drop-off",
        "prep": ["Do not put in curbside bins unless program accepts it"],
        "notes": "Many cities don't accept foam curbside; check drop-off options.",
        "link": "https://search.earth911.com/",
        "material": "Plastic",
    },
    "plastic bag": {
        "bin": "Special Drop-off",
        "prep": ["Clean and dry", "Return to store drop-off (often)"],
        "notes": "Plastic bags tangle recycling machinery—avoid curbside bins.",
        "link": "https://search.earth911.com/",
        "material": "Plastic",
    },
    "battery": {
        "bin": "Special Drop-off",
        "prep": ["Do NOT put in curbside bins", "Take to a battery/e-waste drop-off"],
        "notes": "Batteries can cause fires in recycling facilities.",
        "link": "https://search.earth911.com/",
        "material": "Hazardous",
    },
    "electronics": {
        "bin": "Special Drop-off",
        "prep": ["Take to an e-waste recycler/drop-off"],
        "notes": "E-waste contains hazardous materials and valuable metals.",
        "link": "https://search.earth911.com/",
        "material": "Electronics",
    },
    "banana peel": {
        "bin": "Compost",
        "prep": ["Compost if available (home or municipal)"],
        "notes": "Food waste is great for composting when available.",
        "link": "https://search.earth911.com/",
        "material": "Organic",
    },
    "used napkin/paper towel": {
        "bin": "Compost",
        "prep": ["Compost if allowed; otherwise landfill"],
        "notes": "Soiled paper usually can't be recycled.",
        "link": "https://search.earth911.com/",
        "material": "Organic",
    },
    "clothes/textiles": {
        "bin": "Special Drop-off",
        "prep": ["Donate if usable", "Use textile recycling drop-off if damaged"],
        "notes": "Textiles are rarely accepted curbside; donation is best first step.",
        "link": "https://search.earth911.com/",
        "material": "Textiles",
    },
}

DB_PATH = os.path.join(os.path.dirname(__file__), "recycling.db")


# ---------------- DB helpers ----------------
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def now_ts():
    return datetime.utcnow().isoformat()


def init_db():
    conn = get_db_connection()

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item TEXT NOT NULL,
            amount REAL NOT NULL,
            date TEXT NOT NULL,
            ts TEXT NOT NULL
        )
        """
    )
    conn.commit()

    cur = conn.execute("PRAGMA table_info(entries)")
    cols = [r[1] for r in cur.fetchall()]
    if "material" not in cols:
        conn.execute("ALTER TABLE entries ADD COLUMN material TEXT DEFAULT ''")
    if "points" not in cols:
        conn.execute("ALTER TABLE entries ADD COLUMN points REAL DEFAULT 0")
    if "bin" not in cols:
        conn.execute("ALTER TABLE entries ADD COLUMN bin TEXT DEFAULT ''")
    if "prep" not in cols:
        conn.execute("ALTER TABLE entries ADD COLUMN prep TEXT DEFAULT ''")
    if "notes" not in cols:
        conn.execute("ALTER TABLE entries ADD COLUMN notes TEXT DEFAULT ''")
    if "link" not in cols:
        conn.execute("ALTER TABLE entries ADD COLUMN link TEXT DEFAULT ''")
    if "user_id" not in cols:
        conn.execute("ALTER TABLE entries ADD COLUMN user_id TEXT")
    conn.commit()

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            material TEXT,
            bin TEXT,
            prep TEXT,
            notes TEXT,
            link TEXT
        )
        """
    )
    conn.commit()

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
          id TEXT PRIMARY KEY,
          display_name TEXT,
          email TEXT,
          zip TEXT,
          lat REAL,
          lon REAL,
          created_ts TEXT NOT NULL
        )
        """
    )

    # Add email column to users if it doesn't exist yet
    cur = conn.execute("PRAGMA table_info(users)")
    user_cols = [r[1] for r in cur.fetchall()]
    if "email" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN email TEXT")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS auth_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            display_name TEXT,
            created_ts TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS listings (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          owner_user_id TEXT NOT NULL,
          listing_type TEXT NOT NULL,
          intent TEXT NOT NULL,
          category TEXT NOT NULL,
          query_text TEXT NOT NULL,
          condition TEXT DEFAULT '',
          price REAL DEFAULT NULL,
          zip TEXT DEFAULT '',
          lat REAL DEFAULT NULL,
          lon REAL DEFAULT NULL,
          active INTEGER NOT NULL DEFAULT 1,
          created_ts TEXT NOT NULL,
          FOREIGN KEY(owner_user_id) REFERENCES users(id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS swipes (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          swiper_user_id TEXT NOT NULL,
          listing_id INTEGER NOT NULL,
          decision TEXT NOT NULL,
          created_ts TEXT NOT NULL,
          UNIQUE(swiper_user_id, listing_id),
          FOREIGN KEY(swiper_user_id) REFERENCES users(id),
          FOREIGN KEY(listing_id) REFERENCES listings(id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS matches (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          listing_a_id INTEGER NOT NULL,
          listing_b_id INTEGER NOT NULL,
          created_ts TEXT NOT NULL,
          UNIQUE(listing_a_id, listing_b_id)
        )
        """
    )
    conn.commit()
    conn.close()


def seed_items_if_empty():
    conn = get_db_connection()
    cur = conn.execute("SELECT COUNT(1) as c FROM items")
    if cur.fetchone()[0] == 0:
        seed = [
            ("Plastic bottle", "Plastic", "Recycle", "Empty and rinse", "#1 PET bottles usually accepted", "https://search.earth911.com/"),
            ("Aluminum can", "Metal", "Recycle", "Empty and rinse", "Aluminum is highly recyclable", "https://search.earth911.com/"),
            ("Glass bottle", "Glass", "Recycle", "Empty and rinse", "Glass rules vary by city", "https://search.earth911.com/"),
            ("Cardboard box", "Paper", "Recycle", "Flatten the box", "Keep dry and clean", "https://search.earth911.com/"),
            ("Banana peel", "Organic", "Compost", "Compost if available", "Food waste for composting", "https://search.earth911.com/"),
            ("Electronics", "Electronics", "Special Drop-off", "Drop off at e-waste", "Contains hazardous materials", "https://search.earth911.com/"),
            ("Clothes", "Textiles", "Special Drop-off", "Donate if usable", "Textiles often need special drop-off", "https://search.earth911.com/"),
            ("Battery", "Hazardous", "Special Drop-off", "Do not put in curbside bins", "Take to battery drop-off", "https://search.earth911.com/"),
        ]
        conn.executemany(
            "INSERT OR IGNORE INTO items (name,material,bin,prep,notes,link) VALUES (?, ?, ?, ?, ?, ?)",
            seed,
        )
        conn.commit()
    conn.close()


# ---------------- Session helpers ----------------
def ensure_session():
    if "counts" not in session:
        session["counts"] = {
            "Recycle": 0,
            "Compost": 0,
            "Landfill": 0,
            "Special Drop-off": 0,
            "Depends": 0,
        }
    if "history" not in session:
        session["history"] = []


def ensure_user():
    if "user_id" not in session:
        session["user_id"] = str(uuid.uuid4())

    user_id = session["user_id"]

    conn = get_db_connection()
    conn.execute(
        "INSERT OR IGNORE INTO users (id, created_ts) VALUES (?, ?)",
        (user_id, now_ts()),
    )
    conn.commit()
    conn.close()

    return user_id


def haversine_km(lat1, lon1, lat2, lon2):
    if None in (lat1, lon1, lat2, lon2):
        return None
    R = 6371.0
    p = math.pi / 180.0
    dlat = (lat2 - lat1) * p
    dlon = (lon2 - lon1) * p
    a = (math.sin(dlat / 2) ** 2) + math.cos(lat1 * p) * math.cos(lat2 * p) * (math.sin(dlon / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(a))


# ---------------- Lookup logic ----------------
def normalize(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def heuristic_classify(q: str):
    qn = normalize(q)
    hazardous = ["battery", "lithium", "paint", "chemical", "motor oil", "oil", "propane", "aerosol", "bleach"]
    ewaste = ["laptop", "computer", "phone", "tablet", "tv", "monitor", "electronics", "printer", "router"]
    compost = ["banana", "apple", "food", "peel", "coffee", "tea", "egg", "compost", "leftover"]
    recycle = ["bottle", "can", "cardboard", "paper", "glass", "aluminum", "tin", "steel"]

    def contains_any(words):
        return any(w in qn for w in words)

    if contains_any(hazardous):
        return {"bin": "Special Drop-off", "prep": ["Keep sealed", "Do NOT place in curbside bin"],
                "notes": "Hazardous items can cause fires/contamination. Use a drop-off site.",
                "link": "https://search.earth911.com/", "material": "Hazardous", "name": q}
    if contains_any(ewaste):
        return {"bin": "Special Drop-off", "prep": ["Bring to e-waste recycler", "Remove personal data when possible"],
                "notes": "E-waste contains hazardous materials and valuable metals.",
                "link": "https://search.earth911.com/", "material": "Electronics", "name": q}
    if contains_any(compost):
        return {"bin": "Compost", "prep": ["Compost if available (home/municipal)"],
                "notes": "Food scraps are typically compostable (rules vary).",
                "link": "https://search.earth911.com/", "material": "Organic", "name": q}
    if contains_any(recycle):
        return {"bin": "Recycle", "prep": ["Empty and rinse", "Keep clean and dry"],
                "notes": "Common recyclables vary by city; check local rules.",
                "link": "https://search.earth911.com/", "material": "Mixed", "name": q}
    return {"bin": "Depends",
            "prep": ["Check local rules", "If contaminated/unknown, landfill is safer than contaminating recycling"],
            "notes": "Not sure. Many items require special programs.",
            "link": "https://search.earth911.com/", "material": "Unknown", "name": q}


def lookup_item_info(query: str):
    q = (query or "").strip()
    if not q:
        return None
    qn = normalize(q)

    if qn in ITEMS:
        info = ITEMS[qn].copy()
        info["name"] = q
        info["material"] = info.get("material", "Unknown")
        return info

    conn = get_db_connection()
    row = conn.execute(
        "SELECT name, material, bin, prep, notes, link FROM items WHERE lower(name)=lower(?) LIMIT 1", (q,)
    ).fetchone()
    if not row:
        row = conn.execute(
            "SELECT name, material, bin, prep, notes, link FROM items WHERE lower(name) LIKE lower(?) ORDER BY name LIMIT 1",
            (f"%{q}%",)
        ).fetchone()
    conn.close()

    if row:
        return {"name": row["name"], "bin": row["bin"] or "Recycle",
                "prep": [row["prep"]] if row["prep"] else [],
                "notes": row["notes"] or "", "link": row["link"] or "https://search.earth911.com/",
                "material": row["material"] or "Unknown"}

    return heuristic_classify(q)


# ---------------- Init DB ----------------
init_db()
seed_items_if_empty()


# =========================
# ROUTES (PAGES)
# =========================
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/home")
def home():
    return redirect(url_for("index"))


@app.route("/matching")
def matching():
    ensure_user()
    return render_template("matching.html")


@app.route("/settings")
def settings():
    return render_template("settings.html")


@app.route("/recycling/item", methods=["GET", "POST"])
def recycling():
    ensure_session()

    if request.method == "GET":
        return render_template(
            "recycling.html",
            items=sorted(ITEMS.keys()),
            counts=session["counts"],
            response="",
        )

    item_raw = (request.form.get("item") or "").strip()
    try:
        amount = float(request.form.get("amount", 1))
    except Exception:
        amount = 1.0

    if not item_raw:
        return jsonify(error="Please enter an item."), 400

    info = lookup_item_info(item_raw) or {}
    bin_name = info.get("bin", "Recycle")
    material = info.get("material", "Unknown")
    prep_list = info.get("prep") or []
    notes = info.get("notes") or ""
    link = info.get("link") or "https://search.earth911.com/"
    prep_text = ", ".join(prep_list) if isinstance(prep_list, list) else str(prep_list)

    counts = session["counts"]
    counts[bin_name] = counts.get(bin_name, 0) + 1
    session["counts"] = counts

    history = session["history"]
    history.append({"item": item_raw, "bin": bin_name})
    session["history"] = history[-50:]

    multiplier = 1.5 if (material or "").lower() in ("plastic", "electronics", "hazardous") else 1.0
    points = float(amount) * multiplier

    date_str = datetime.utcnow().date().isoformat()
    ts = now_ts()
    user_id = ensure_user()

    conn = get_db_connection()
    conn.execute(
        """
        INSERT INTO entries (item, amount, date, ts, material, points, bin, prep, notes, link, user_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (item_raw, amount, date_str, ts, material, points, bin_name, prep_text, notes, link, user_id),
    )
    conn.commit()
    conn.close()

    return jsonify(success=True, counts=session["counts"], history=session["history"], item_info=info)


# =========================
# Recycling APIs
# =========================
@app.route("/api/stats")
def api_stats():
    ensure_session()
    return jsonify({"counts": session["counts"], "history": session["history"], "known_items": sorted(ITEMS.keys())})


@app.route("/api/entries")
def api_entries():
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT id, item, amount, date, ts, material, points, bin, prep, notes, link FROM entries ORDER BY id ASC"
    ).fetchall()
    conn.close()
    return jsonify(entries=[dict(r) for r in rows])


@app.route("/api/clear_entries", methods=["POST"])
def api_clear_entries():
    conn = get_db_connection()
    conn.execute("DELETE FROM entries")
    conn.commit()
    conn.close()
    return jsonify(success=True)


@app.route("/api/autocomplete")
def api_autocomplete():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify(suggestions=[])

    conn = get_db_connection()
    rows = conn.execute(
        "SELECT name, material, bin FROM items WHERE lower(name) LIKE lower(?) ORDER BY name LIMIT 15",
        (f"%{q}%",),
    ).fetchall()
    conn.close()

    qn = normalize(q)
    extra = []
    for k in ITEMS.keys():
        if qn in normalize(k):
            extra.append({"name": k, "material": ITEMS[k].get("material", ""), "bin": ITEMS[k].get("bin", "")})
        if len(extra) >= 8:
            break

    suggestions = [dict(r) for r in rows] + extra
    seen = set()
    out = []
    for s in suggestions:
        name = (s.get("name") or "").lower()
        if name and name not in seen:
            seen.add(name)
            out.append(s)
    return jsonify(suggestions=out[:20])


@app.route("/api/lookup")
def api_lookup():
    q = (request.args.get("q") or "").strip()
    info = lookup_item_info(q)
    if not info:
        return jsonify(found=False, item=None)
    return jsonify(found=True, item=info)


@app.route("/api/item")
def api_item():
    name = (request.args.get("name") or "").strip()
    if not name:
        return jsonify(item=None)
    conn = get_db_connection()
    row = conn.execute(
        "SELECT name, material, bin, prep, notes, link FROM items WHERE lower(name)=lower(?) LIMIT 1", (name,)
    ).fetchone()
    if not row:
        row = conn.execute(
            "SELECT name, material, bin, prep, notes, link FROM items WHERE lower(name) LIKE lower(?) ORDER BY name LIMIT 1",
            (f"%{name}%",)
        ).fetchone()
    conn.close()
    return jsonify(item=dict(row) if row else None)


# =========================
# Auth API
# =========================
@app.route("/api/auth/me")
def api_auth_me():
    """Returns current logged-in Google user info for the frontend."""
    if session.get("auth_email"):
        return jsonify(
            logged_in=True,
            email=session.get("auth_email"),
            display_name=session.get("display_name", ""),
            user_id=session.get("user_id", ""),
        )
    return jsonify(logged_in=False)


@app.route("/api/auth/logout", methods=["POST"])
def api_auth_logout():
    session.clear()
    return jsonify(success=True)


# =========================
# MATCHING APIs
# =========================
@app.route("/api/me", methods=["GET", "POST"])
def api_me():
    user_id = ensure_user()
    conn = get_db_connection()

    if request.method == "POST":
        data = request.get_json(force=True)
        display_name = (data.get("display_name") or "").strip()
        zip_code = (data.get("zip") or "").strip()
        lat = data.get("lat", None)
        lon = data.get("lon", None)
        conn.execute(
            """
            INSERT INTO users (id, display_name, zip, lat, lon, created_ts)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              display_name=excluded.display_name,
              zip=excluded.zip,
              lat=excluded.lat,
              lon=excluded.lon
            """,
            (user_id, display_name, zip_code, lat, lon, now_ts()),
        )
        conn.commit()

    row = conn.execute("SELECT id, display_name, zip, lat, lon FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()
    return jsonify(me=dict(row) if row else {"id": user_id})


@app.route("/api/listings", methods=["POST"])
def api_create_listing():
    user_id = ensure_user()
    data = request.get_json(force=True)

    listing_type = (data.get("listing_type") or "").strip().lower()
    intent = (data.get("intent") or "").strip().lower()
    category = (data.get("category") or "").strip()
    query_text = (data.get("query_text") or "").strip()
    condition = (data.get("condition") or "").strip()
    price = data.get("price", None)
    zip_code = (data.get("zip") or "").strip()
    lat = data.get("lat", None)
    lon = data.get("lon", None)

    if listing_type not in ("waste", "part"):
        return jsonify(error="listing_type must be 'waste' or 'part'"), 400
    if intent not in ("offer", "need"):
        return jsonify(error="intent must be 'offer' or 'need'"), 400
    if not category or not query_text:
        return jsonify(error="category and query_text are required"), 400

    conn = get_db_connection()
    conn.execute(
        """
        INSERT INTO listings (owner_user_id, listing_type, intent, category, query_text, condition, price, zip, lat, lon, created_ts)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, listing_type, intent, category, query_text, condition, price, zip_code, lat, lon, now_ts()),
    )
    conn.commit()
    conn.close()
    return jsonify(success=True)


@app.route("/api/listings/others")
def api_listings_others():
    user_id = ensure_user()
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT * FROM listings WHERE active=1 AND owner_user_id != ? ORDER BY created_ts DESC",
        (user_id,)
    ).fetchall()
    conn.close()
    return jsonify(listings=[dict(r) for r in rows])


@app.route("/api/match/next")
def api_match_next():
    user_id = ensure_user()
    q = (request.args.get("q") or "").strip().lower()
    category = (request.args.get("category") or "").strip()
    listing_type = (request.args.get("listing_type") or "waste").strip().lower()
    my_intent = (request.args.get("intent") or "need").strip().lower()

    try:
        max_km = float(request.args.get("max_km")) if request.args.get("max_km", "").strip() else None
    except Exception:
        max_km = None

    if listing_type not in ("waste", "part"):
        return jsonify(error="listing_type must be waste|part"), 400
    if my_intent not in ("offer", "need"):
        return jsonify(error="intent must be offer|need"), 400

    conn = get_db_connection()
    me = conn.execute("SELECT lat, lon, zip FROM users WHERE id=?", (user_id,)).fetchone()
    my_lat = me["lat"] if me else None
    my_lon = me["lon"] if me else None
    my_zip = me["zip"] if me else ""

    params = [user_id, listing_type, user_id]
    where = """
      l.active=1
      AND l.owner_user_id != ?
      AND l.listing_type = ?
      AND l.id NOT IN (SELECT listing_id FROM swipes WHERE swiper_user_id = ?)
    """
    if category:
        where += " AND l.category = ?"
        params.append(category)
    if q:
        where += " AND lower(l.query_text) LIKE ?"
        params.append(f"%{q}%")

    rows = conn.execute(
        f"SELECT l.* FROM listings l WHERE {where} ORDER BY l.created_ts DESC LIMIT 80",
        params,
    ).fetchall()

    candidate = None
    candidate_distance = None
    for r in rows:
        if my_lat and my_lon and r["lat"] and r["lon"]:
            d = haversine_km(my_lat, my_lon, r["lat"], r["lon"])
            if max_km is not None and d is not None and d > max_km:
                continue
            candidate = dict(r)
            candidate_distance = d
            break
        else:
            if my_zip and r["zip"] and my_zip != r["zip"]:
                continue
            candidate = dict(r)
            break

    conn.close()
    if not candidate:
        return jsonify(card=None)
    candidate["distance_km"] = candidate_distance
    return jsonify(card=candidate)


@app.route("/api/match/swipe", methods=["POST"])
def api_match_swipe():
    user_id = ensure_user()
    data = request.get_json(force=True)
    listing_id = data.get("listing_id")
    decision = (data.get("decision") or "").strip().lower()

    if decision not in ("yes", "no"):
        return jsonify(error="decision must be yes or no"), 400
    if not listing_id:
        return jsonify(error="listing_id required"), 400

    conn = get_db_connection()
    conn.execute(
        """
        INSERT INTO swipes (swiper_user_id, listing_id, decision, created_ts)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(swiper_user_id, listing_id) DO UPDATE SET
          decision=excluded.decision, created_ts=excluded.created_ts
        """,
        (user_id, listing_id, decision, now_ts()),
    )
    conn.commit()

    matched = False
    match_id = None

    if decision == "yes":
        reciprocal = conn.execute(
            """
            SELECT s.listing_id FROM swipes s
            JOIN listings l ON l.id = s.listing_id
            WHERE s.swiper_user_id = (SELECT owner_user_id FROM listings WHERE id = ?)
            AND l.owner_user_id = ?
            AND s.decision = 'yes'
            """,
            (listing_id, user_id),
        ).fetchone()

        if reciprocal:
            other_listing = reciprocal["listing_id"]
            a, b = sorted([int(listing_id), int(other_listing)])
            conn.execute(
                "INSERT OR IGNORE INTO matches (listing_a_id, listing_b_id, created_ts) VALUES (?, ?, ?)",
                (a, b, now_ts()),
            )
            conn.commit()
            row = conn.execute(
                "SELECT id FROM matches WHERE listing_a_id=? AND listing_b_id=?", (a, b)
            ).fetchone()
            match_id = row["id"] if row else None
            matched = True

    conn.close()
    return jsonify(success=True, matched=matched, match_id=match_id)


@app.route("/api/matches")
def api_matches():
    user_id = ensure_user()
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT m.id as match_id, m.created_ts,
               la.id as a_id, la.query_text as a_text, la.intent as a_intent, la.listing_type as a_type, la.owner_user_id as a_owner,
               lb.id as b_id, lb.query_text as b_text, lb.intent as b_intent, lb.listing_type as b_type, lb.owner_user_id as b_owner
        FROM matches m
        JOIN listings la ON la.id = m.listing_a_id
        JOIN listings lb ON lb.id = m.listing_b_id
        WHERE la.owner_user_id=? OR lb.owner_user_id=?
        ORDER BY m.created_ts DESC LIMIT 50
        """,
        (user_id, user_id),
    ).fetchall()
    conn.close()
    return jsonify(matches=[dict(r) for r in rows])


@app.route("/api/leaderboard")
def api_leaderboard():
    user_id = ensure_user()
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT
            u.id,
            COALESCE(u.display_name, 'Guest') as name,
            COALESCE(SUM(e.points), 0) as total_points
        FROM users u
        LEFT JOIN entries e ON e.user_id = u.id
        GROUP BY u.id
        ORDER BY total_points DESC
        """
    ).fetchall()
    conn.close()
    return jsonify(leaderboard=[dict(r) for r in rows], current_user=user_id)


# =========================
# OAuth Routes
# =========================
@app.route('/oauth/login/google')
def oauth_login_google():
    client = oauth.create_client('google')
    if not client:
        return jsonify(error='Google OAuth not configured. Add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET to your .env file'), 500
    redirect_uri = url_for('oauth_callback_google', _external=True)
    return client.authorize_redirect(redirect_uri)


@app.route('/oauth/callback/google')
def oauth_callback_google():
    client = oauth.create_client('google')
    if not client:
        return jsonify(error='Google OAuth not configured'), 500

    try:
        token = client.authorize_access_token()
    except Exception as e:
        return jsonify(error=f'OAuth token error: {str(e)}'), 400

    # Modern authlib puts userinfo in the token directly
    userinfo = token.get('userinfo')
    if not userinfo:
        try:
            userinfo = client.userinfo()
        except Exception:
            userinfo = {}

    email = (userinfo.get('email') or '').strip().lower()
    name = userinfo.get('name') or email
    google_id = str(userinfo.get('sub') or email)  # Google's stable unique user ID

    if not email:
        return jsonify(error='Google did not return an email'), 400

    conn = get_db_connection()

    # Save to auth_users table
    conn.execute(
        "INSERT OR IGNORE INTO auth_users (email, password_hash, display_name, created_ts) VALUES (?, ?, ?, ?)",
        (email, '', name, now_ts()),
    )
    conn.commit()

    # Upsert into users table using Google's stable ID
    # This means all recycling data persists across logins
    conn.execute(
        """
        INSERT INTO users (id, display_name, email, created_ts)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          display_name=excluded.display_name,
          email=excluded.email
        """,
        (google_id, name, email, now_ts()),
    )
    conn.commit()

    row = conn.execute(
        "SELECT id, email FROM auth_users WHERE lower(email)=lower(?)", (email,)
    ).fetchone()
    conn.close()

    # Set session — user_id is now Google's stable ID so all data ties to their account
    session['auth_email'] = email
    session['auth_user_id'] = row['id'] if row else None
    session['display_name'] = name
    session['user_id'] = google_id  # ← key line: ties all recycling/leaderboard data to Google account

    return redirect(url_for('index'))


if __name__ == "__main__":
    app.run(debug=True, port=5001)