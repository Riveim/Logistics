# server.py
# -*- coding: utf-8 -*-
import os
import time
import hmac
import secrets
import hashlib
import sqlite3
import threading
import smtplib
from email.message import EmailMessage
import re
import io
from typing import Optional, Dict, Any, Tuple

from flask import Flask, request, jsonify, send_file, abort, send_from_directory

# server.py
# Принимает заявки от manager_app и ПЕРЕСЫЛАЕТ их в telegram_app
# pip install fastapi uvicorn requests

from fastapi import FastAPI, HTTPException, Header
import requests
import uvicorn

app = FastAPI()

# === НАСТРОЙКИ ===
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 5000

TELEGRAM_APP_URL = "http://127.0.0.1:5000/send_order"  # <-- ИЗМЕНИ если нужно
VALID_TOKEN = "SECRET_TOKEN"


@app.post("/login")
def login(data: dict):
    if data.get("username") == "admin" and data.get("password") == "admin":
        return {"token": VALID_TOKEN}
    raise HTTPException(status_code=401, detail="bad credentials")


@app.post("/orders/create")
def create_order(order: dict, authorization: str = Header(None)):
    if authorization != f"Bearer {VALID_TOKEN}":
        raise HTTPException(status_code=401, detail="bad/expired token")

    # пересылаем заявку в telegram_app
    # after order_id is created and committed
    try:
        requests.post(
            "http://127.0.0.1:5001/send_order",
            json={
                "order_id": int(order_id),
                "direction": direction,
                "cargo": cargo,
                "tonnage": float(tonnage),
                "truck": truck,
                "date": date,
                "price": float(price),
                "info": info_text,
                "from_company": "",  # если хочешь
            },
            headers={"X-Telegram-Token": os.getenv("TELEGRAM_FORWARD_TOKEN", "CHANGE_ME_TG_TOKEN")},
            timeout=5,
        )
    except Exception as e:
        print("[SERVER] telegram_app send error:", e)

    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT)


# ================== CONFIG ==================
# ===== EMAIL CONFIG =====
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER)
SMTP_TLS = os.getenv("SMTP_TLS", "1") == "1"

# ================== MUSIC CONFIG ==================
MUSIC_DIR = r"music"
MUSIC_DEFAULT_FILE = ""

DB_PATH = os.getenv("DB_PATH", "mvp_server.db")
ADMIN_SETUP_KEY = os.getenv("ADMIN_SETUP_KEY", "CHANGE_ME_SETUP_KEY")
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "5000"))

REQUIRE_DEVICE_ID = os.getenv("REQUIRE_DEVICE_ID", "1") == "1"
REQUIRE_APP_IN_LOGIN = os.getenv("REQUIRE_APP_IN_LOGIN", "1") == "1"
TOKEN_TTL_SECONDS = int(os.getenv("TOKEN_TTL_SECONDS", "86400"))
SINGLE_SESSION_PER_USER = os.getenv("SINGLE_SESSION_PER_USER", "1") == "1"

TELEGRAM_ENABLED = os.getenv("TELEGRAM_ENABLED", "0") == "1"

ALLOWED_ROLES = {"manager", "transport", "admin"}
ALLOWED_APPS = {"manager", "transport"}

# ================== APP ==================
app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOADS_DIR = os.path.join(BASE_DIR, "downloads")


@app.get("/downloads/<path:filename>")
def downloads(filename):
    return send_from_directory(DOWNLOADS_DIR, filename, as_attachment=True)


ALLOWED_AUDIO_EXT = (".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac")


def pick_music_file() -> str:
    if MUSIC_DEFAULT_FILE and os.path.isfile(MUSIC_DEFAULT_FILE):
        return MUSIC_DEFAULT_FILE
    if not MUSIC_DIR or not os.path.isdir(MUSIC_DIR):
        return ""
    files = []
    for name in os.listdir(MUSIC_DIR):
        p = os.path.join(MUSIC_DIR, name)
        if os.path.isfile(p) and name.lower().endswith(ALLOWED_AUDIO_EXT):
            files.append(p)
    files.sort()
    return files[0] if files else ""


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def send_email(to_email: str, subject: str, body: str) -> Tuple[bool, str]:
    to_email = (to_email or "").strip()
    if not EMAIL_RE.match(to_email):
        return False, "bad_email"

    if not SMTP_HOST or not SMTP_USER or not SMTP_PASS or not SMTP_FROM:
        return False, "smtp_not_configured"

    try:
        msg = EmailMessage()
        msg["From"] = SMTP_FROM
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.set_content(body)

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as s:
            if SMTP_TLS:
                s.starttls()
            s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)

        return True, "ok"
    except Exception as e:
        return False, f"smtp_error: {e}"


@app.get("/music/stream")
def music_stream():
    path = pick_music_file()
    if not path or not os.path.isfile(path):
        abort(404, description="Music file not found. Check MUSIC_DIR / MUSIC_DEFAULT_FILE.")
    return send_file(path, conditional=True, as_attachment=False)


data_lock = threading.Lock()
TOKENS: Dict[str, Dict[str, Any]] = {}


# ================== DB HELPERS ==================
def db_connect():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def now_ts() -> int:
    return int(time.time())


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789@#$%&"


def generate_invite_code(length: int = 10) -> str:
    length = max(8, min(12, int(length)))
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(length))


def validate_and_consume_invite_code(conn: sqlite3.Connection, code: str, role: str) -> Tuple[bool, str]:
    code = (code or "").strip().upper()
    role = (role or "").strip().lower()

    if not code:
        return False, "invite_code_required"
    if len(code) < 8 or len(code) > 12:
        return False, "invite_code_bad_length"

    cur = conn.cursor()
    cur.execute("SELECT * FROM invite_codes WHERE code=?", (code,))
    row = cur.fetchone()
    if not row:
        return False, "invite_code_not_found"

    if int(row["active"]) != 1:
        return False, "invite_code_inactive"

    expires_at = row["expires_at"]
    if expires_at is not None and now_ts() > int(expires_at):
        return False, "invite_code_expired"

    code_role = (row["role"] or "").strip().lower()
    if code_role != role:
        return False, "invite_code_role_mismatch"

    used = int(row["used_count"])
    max_uses = int(row["max_uses"])
    if used >= max_uses:
        return False, "invite_code_already_used"

    cur.execute("UPDATE invite_codes SET used_count = used_count + 1 WHERE code=?", (code,))
    return True, "ok"


# ================== LICENSE (PRODUCT KEYS) ==================
# Лицензионный ключ: хранится на сервере, активируется на конкретное устройство (device_id).
# Можно менять лимит устройств и срок действия через админ-эндпоинты или CLI (см. main).

LICENSE_KEY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
LICENSE_KEY_GROUP = 4

def normalize_license_key(k: str) -> str:
    k = (k or "").strip().upper().replace(" ", "").replace("-", "")
    return k

def format_license_key(k: str) -> str:
    k = normalize_license_key(k)
    if not k:
        return ""
    groups = [k[i:i+LICENSE_KEY_GROUP] for i in range(0, len(k), LICENSE_KEY_GROUP)]
    return "-".join(groups)

def generate_license_key(length: int = 20) -> str:
    length = int(length)
    if length < 12:
        length = 12
    if length > 32:
        length = 32
    raw = "".join(secrets.choice(LICENSE_KEY_ALPHABET) for _ in range(length))
    return format_license_key(raw)

def license_is_expired(expires_at: Optional[int]) -> bool:
    return expires_at is not None and int(expires_at) > 0 and now_ts() > int(expires_at)

def ensure_license_tables():
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS license_keys (
      license_key TEXT PRIMARY KEY,
      app TEXT NOT NULL,                 -- manager/transport/any
      max_devices INTEGER NOT NULL DEFAULT 1,
      expires_at INTEGER DEFAULT NULL,   -- unix ts, NULL = бессрочно
      active INTEGER NOT NULL DEFAULT 1,
      company TEXT DEFAULT '',
      note TEXT DEFAULT '',
      created_at INTEGER NOT NULL
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS license_activations (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      license_key TEXT NOT NULL,
      app TEXT NOT NULL,
      device_id TEXT NOT NULL,
      activated_at INTEGER NOT NULL,
      last_seen INTEGER NOT NULL,
      UNIQUE(license_key, app, device_id)
    )
    """)

    # ---- migration: add company column if DB is old ----
    try:
        cur.execute("PRAGMA table_info(license_keys)")
        cols = {row["name"] for row in cur.fetchall()}
        if "company" not in cols:
            cur.execute("ALTER TABLE license_keys ADD COLUMN company TEXT DEFAULT ''")
    except Exception:
        pass

    conn.commit()
    conn.close()

ensure_license_tables()

def validate_license_and_touch(conn: sqlite3.Connection, license_key: str, app_name: str, device_id: str) -> Tuple[bool, str, Dict[str, Any]]:
    license_key_norm = normalize_license_key(license_key)
    license_key_fmt = format_license_key(license_key_norm)
    app_name = (app_name or "").strip().lower()
    device_id = (device_id or "").strip()

    if not license_key_norm:
        return False, "license_key_required", {}
    if not app_name or app_name not in ("manager", "transport"):
        return False, "bad_app", {"allowed": ["manager", "transport"]}
    if not device_id:
        return False, "device_id_required", {}

    cur = conn.cursor()
    cur.execute("SELECT * FROM license_keys WHERE license_key=?", (license_key_fmt,))
    row = cur.fetchone()
    if not row:
        return False, "license_not_found", {}
    if int(row["active"]) != 1:
        return False, "license_inactive", {}
    key_app = (row["app"] or "").strip().lower()
    if key_app not in ("any", app_name):
        return False, "license_app_mismatch", {"need_app": key_app}

    expires_at = row["expires_at"]
    if license_is_expired(expires_at):
        return False, "license_expired", {"expires_at": int(expires_at)}

    max_devices = int(row["max_devices"] or 1)

    # считаем активированные устройства
    cur.execute("SELECT COUNT(DISTINCT device_id) AS c FROM license_activations WHERE license_key=? AND app=?", (license_key_fmt, app_name))
    c = int(cur.fetchone()["c"] or 0)

    cur.execute("SELECT 1 FROM license_activations WHERE license_key=? AND app=? AND device_id=?", (license_key_fmt, app_name, device_id))
    already = cur.fetchone() is not None

    if not already and c >= max_devices:
        return False, "device_limit_reached", {"max_devices": max_devices, "used_devices": c}

    ts = now_ts()
    if already:
        cur.execute("UPDATE license_activations SET last_seen=? WHERE license_key=? AND app=? AND device_id=?", (ts, license_key_fmt, app_name, device_id))
    else:
        cur.execute(
            "INSERT INTO license_activations (license_key, app, device_id, activated_at, last_seen) VALUES (?, ?, ?, ?, ?)",
            (license_key_fmt, app_name, device_id, ts, ts),
        )
    return True, "ok", {"license_key": license_key_fmt, "expires_at": expires_at, "max_devices": max_devices}


def verify_password(password: str, password_hash: str) -> bool:
    return hmac.compare_digest(sha256(password), password_hash)


def normalize_username(u: Optional[str]) -> str:
    u = (u or "").strip()
    if u.startswith("@"):
        u = u[1:]
    return u.lower()


def db_init():
    conn = db_connect()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
      username TEXT PRIMARY KEY,
      password_hash TEXT NOT NULL,
      role TEXT NOT NULL DEFAULT 'manager',
      email TEXT DEFAULT '',
      phone TEXT DEFAULT '',
      company_name TEXT DEFAULT '',
      contact TEXT DEFAULT '',
      device_id TEXT DEFAULT NULL,
      license_key_used TEXT DEFAULT NULL,
      created_at INTEGER NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS orders (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      username TEXT NOT NULL,
      direction TEXT,
      cargo TEXT,
      tonnage REAL,
      truck TEXT,
      date TEXT,
      price REAL,
      info TEXT,
      status TEXT DEFAULT 'pending',
      created_at INTEGER NOT NULL,
      closed_at INTEGER DEFAULT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS market_orders (
      order_id INTEGER PRIMARY KEY,
      status TEXT NOT NULL DEFAULT 'open',
      created_at INTEGER NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS market_offers (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      order_id INTEGER NOT NULL,
      transport_username TEXT NOT NULL,
      price INTEGER NOT NULL,
      comment TEXT DEFAULT '',
      contact TEXT DEFAULT '',
      company TEXT DEFAULT '',
      created_at INTEGER NOT NULL,
      UNIQUE(order_id, transport_username)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS invite_codes (
      code TEXT PRIMARY KEY,
      role TEXT NOT NULL,
      max_uses INTEGER NOT NULL DEFAULT 1,
      used_count INTEGER NOT NULL DEFAULT 0,
      active INTEGER NOT NULL DEFAULT 1,
      created_at INTEGER NOT NULL,
      expires_at INTEGER DEFAULT NULL
    )
    """)

    conn.commit()
    conn.close()


def db_migrate_users():
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(users)")
    cols = {row[1] for row in cur.fetchall()}

    if "role" not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'manager'")
    if "email" not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN email TEXT DEFAULT ''")
    if "phone" not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN phone TEXT DEFAULT ''")
    if "company_name" not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN company_name TEXT DEFAULT ''")
    if "contact" not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN contact TEXT DEFAULT ''")
    if "device_id" not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN device_id TEXT DEFAULT NULL")
    if "license_key_used" not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN license_key_used TEXT DEFAULT NULL")

    conn.commit()
    conn.close()


def db_migrate_invite_codes():
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(invite_codes)")
    _ = cur.fetchall()
    conn.commit()
    conn.close()


db_init()
db_migrate_users()
db_migrate_invite_codes()

# ================== OPTIONAL TELEGRAM ENGINE ==================
telegram_engine = None
if TELEGRAM_ENABLED:
    try:
        from telegram_engine import TelegramEngine  # type: ignore
        telegram_engine = TelegramEngine()
        print("[TELEGRAM] enabled")
    except Exception as e:
        telegram_engine = None
        print("[TELEGRAM] failed to init:", e)


# ================== AUTH HELPERS ==================
def get_bearer_token() -> Optional[str]:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    return auth.split(" ", 1)[1].strip()


def revoke_all_tokens_for(username: str):
    with data_lock:
        to_del = [t for t, v in TOKENS.items() if v.get("username") == username]
        for t in to_del:
            TOKENS.pop(t, None)


def issue_token(username: str, role: str, app_name: str) -> str:
    token = secrets.token_urlsafe(24)
    with data_lock:
        TOKENS[token] = {
            "username": username,
            "role": role,
            "app": app_name,
            "issued_at": now_ts(),
            "last_seen": now_ts(),
        }
    return token


def validate_token(token: str) -> Optional[Dict[str, Any]]:
    with data_lock:
        meta = TOKENS.get(token)
        if not meta:
            return None
        if now_ts() - int(meta.get("issued_at", 0)) > TOKEN_TTL_SECONDS:
            TOKENS.pop(token, None)
            return None
        meta["last_seen"] = now_ts()
        return meta



def require_auth():
    token = get_bearer_token()
    if not token:
        return None, jsonify({"error": "missing token"}), 401
    meta = validate_token(token)
    if not meta:
        return None, jsonify({"error": "bad/expired token"}), 401

    # License validity is checked only during /login and /register.
    # We do NOT enforce license status on every API call here, so an already logged-in session
    # won't be interrupted mid-work.

    return meta, None, None



def require_role(required_role: str):
    def decorator(fn):
        def wrapper(*args, **kwargs):
            meta, err, code = require_auth()
            if err:
                return err, code
            role = meta.get("role")
            if role != required_role:
                return jsonify({"error": "forbidden", "need": required_role}), 403
            return fn(*args, **kwargs)

        wrapper.__name__ = fn.__name__
        return wrapper

    return decorator


# ================== LICENSE API ==================
@app.post("/license/activate")
def license_activate():
    data = request.get_json(force=True)
    license_key = (data.get("license_key") or "").strip()
    device_id = (data.get("device_id") or "").strip()
    app_name = (data.get("app") or "").strip().lower()

    conn = db_connect()
    try:
        ok, reason, meta = validate_license_and_touch(conn, license_key, app_name, device_id)
        if not ok:
            conn.rollback()
            return jsonify({"error": reason, **meta}), 403
        conn.commit()
        return jsonify({"status": "ok", **meta}), 200
    finally:
        conn.close()


@app.post("/license/status")
def license_status():
    data = request.get_json(force=True)
    license_key = (data.get("license_key") or "").strip()
    device_id = (data.get("device_id") or "").strip()
    app_name = (data.get("app") or "").strip().lower()

    conn = db_connect()
    try:
        ok, reason, meta = validate_license_and_touch(conn, license_key, app_name, device_id)
        if not ok:
            conn.rollback()
            return jsonify({"error": reason, **meta}), 403
        conn.rollback()  # status не должен менять БД (кроме last_seen); но last_seen полезен
        return jsonify({"status": "ok", **meta}), 200
    finally:
        conn.close()


@app.post("/admin/license/create")
@require_role("admin")
def admin_license_create():
    data = request.get_json(force=True)
    app_name = (data.get("app") or "any").strip().lower()
    max_devices = int(data.get("max_devices") or 1)
    days = data.get("days")
    length = int(data.get("length") or 20)
    note = str(data.get("note") or "")

    if app_name not in ("any", "manager", "transport"):
        return jsonify({"error": "bad_app", "allowed": ["any", "manager", "transport"]}), 400
    if max_devices < 1:
        return jsonify({"error": "bad_max_devices"}), 400

    expires_at = None
    if days is not None and str(days).strip() != "":
        try:
            days_i = int(days)
            if days_i > 0:
                expires_at = now_ts() + days_i * 86400
        except Exception:
            return jsonify({"error": "bad_days"}), 400

    key = generate_license_key(length)

    conn = db_connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO license_keys (license_key, app, max_devices, expires_at, active, note, created_at) VALUES (?, ?, ?, ?, 1, ?, ?)",
            (key, app_name, max_devices, expires_at, note, now_ts()),
        )
        conn.commit()
        return jsonify({"status": "ok", "license_key": key, "app": app_name, "max_devices": max_devices, "expires_at": expires_at}), 201
    finally:
        conn.close()


@app.post("/admin/license/update/<path:license_key>")
@require_role("admin")
def admin_license_update(license_key: str):
    license_key = format_license_key(license_key)
    data = request.get_json(force=True)

    fields = {}
    if "max_devices" in data:
        try:
            fields["max_devices"] = int(data.get("max_devices"))
        except Exception:
            return jsonify({"error": "bad_max_devices"}), 400
        if fields["max_devices"] < 1:
            return jsonify({"error": "bad_max_devices"}), 400

    if "expires_at" in data:
        exp = data.get("expires_at")
        if exp in (None, "", 0, "0"):
            fields["expires_at"] = None
        else:
            try:
                fields["expires_at"] = int(exp)
            except Exception:
                return jsonify({"error": "bad_expires_at"}), 400

    if "active" in data:
        fields["active"] = 1 if str(data.get("active")).strip() in ("1", "true", "True", "yes") else 0

    if "note" in data:
        fields["note"] = str(data.get("note") or "")

    if not fields:
        return jsonify({"error": "nothing_to_update"}), 400

    sets = ", ".join([f"{k}=?" for k in fields.keys()])
    values = list(fields.values()) + [license_key]

    conn = db_connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM license_keys WHERE license_key=?", (license_key,))
        if not cur.fetchone():
            return jsonify({"error": "not_found"}), 404

        cur.execute(f"UPDATE license_keys SET {sets} WHERE license_key=?", values)
        conn.commit()
        return jsonify({"status": "ok", "license_key": license_key, "updated": list(fields.keys())}), 200
    finally:
        conn.close()


@app.get("/admin/license/list")
@require_role("admin")
def admin_license_list():
    conn = db_connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT license_key, app, max_devices, expires_at, active, note, created_at FROM license_keys ORDER BY created_at DESC LIMIT 500")
        rows = [dict(r) for r in cur.fetchall()]
        return jsonify({"status": "ok", "items": rows}), 200
    finally:
        conn.close()


@app.post("/register")
def register():
    data = request.get_json(force=True)
    username = normalize_username(data.get("username"))
    password = (data.get("password") or "").strip()
    role = (data.get("role") or "").strip().lower()

    email = (data.get("email") or "").strip()
    phone = (data.get("phone") or "").strip()

    company_name = (data.get("company_name") or "").strip()
    contact = (data.get("contact") or "").strip()
    device_id = (data.get("device_id") or "").strip()
    invite_code = (data.get("invite_code") or "").strip()
    license_key = (data.get("license_key") or "").strip()

    if role not in ("manager", "transport"):
        return jsonify({"error": "bad_role", "allowed": ["manager", "transport"]}), 400
    if not username or not password:
        return jsonify({"error": "username/password required"}), 400
    if not email or not phone:
        return jsonify({"error": "email/phone required"}), 400

    conn = db_connect()
    cur = conn.cursor()
    try:
        cur.execute("SELECT username FROM users WHERE username=?", (username,))
        if cur.fetchone():
            return jsonify({"error": "username_taken"}), 409

        # Оплата отключена. Теперь регистрация может подтверждаться:
        # 1) старым invite_code (если он есть), или
        # 2) license_key (продуктовый ключ).
        meta = {}
        if invite_code:
            ok, reason = validate_and_consume_invite_code(conn, invite_code, role)
            if not ok:
                conn.rollback()
                return jsonify({"error": reason}), 403
        else:
            if REQUIRE_DEVICE_ID and not device_id:
                conn.rollback()
                return jsonify({"error": "device_id_required"}), 400
            ok2, reason2, meta = validate_license_and_touch(conn, license_key, role, device_id or "0")
            if not ok2:
                conn.rollback()
                return jsonify({"error": reason2, "license_valid": False, **meta}), 403


        cur.execute(
            "INSERT INTO users (username, password_hash, role, email, phone, company_name, contact, device_id, license_key_used, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (username, sha256(password), role, email, phone, company_name, contact, (device_id or None), (meta.get("license_key") if not invite_code else None), now_ts()),
        )
        conn.commit()
        return jsonify({"status": "ok", "license_valid": True}), 201
    finally:
        conn.close()


@app.post("/login")
def login():
    data = request.get_json(force=True)
    username = normalize_username(data.get("username"))
    password = (data.get("password") or "").strip()
    device_id = (data.get("device_id") or "").strip()
    app_name = (data.get("app") or "").strip().lower()

    if not username or not password:
        return jsonify({"error": "username/password required"}), 400

    if REQUIRE_APP_IN_LOGIN:
        if app_name not in ALLOWED_APPS:
            return jsonify({"error": "bad_app", "allowed": sorted(list(ALLOWED_APPS))}), 400
    else:
        if not app_name:
            app_name = "manager"

    conn = db_connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE username=?", (username,))
        user = cur.fetchone()
        if not user:
            return jsonify({"error": "bad_credentials"}), 403

        if not verify_password(password, user["password_hash"]):
            return jsonify({"error": "bad_credentials"}), 403

        role = (user["role"] or "").strip().lower()
        if role not in ALLOWED_ROLES:
            role = "manager"

        if REQUIRE_DEVICE_ID:
            if not device_id:
                return jsonify({"error": "device_id_required"}), 400
            # bind device on first login (or enforce same)
            saved = user["device_id"]
            if saved and saved != device_id:
                return jsonify({"error": "device_mismatch"}), 403
            if not saved:
                cur.execute("UPDATE users SET device_id=? WHERE username=?", (device_id, username))
                conn.commit()

        # If the user was registered via a product/license key, then the key must remain active.
        # Otherwise the login itself must fail (not only subsequent actions).
        lk = (user["license_key_used"] or "").strip()
        if lk:
            dev_for_license = device_id or (user["device_id"] or "") or "0"
            ok_lk, reason_lk, meta_lk = validate_license_and_touch(conn, lk, app_name or "manager", dev_for_license)
            if not ok_lk:
                conn.rollback()
                revoke_all_tokens_for(username)
                return jsonify({"error": reason_lk, "license_valid": False, **meta_lk}), 403
            conn.commit()

        if SINGLE_SESSION_PER_USER:
            revoke_all_tokens_for(username)

        token = issue_token(username, role, app_name)
        return jsonify({"token": token, "role": role, "license_valid": True}), 200
    finally:
        conn.close()


@app.get("/me")
def me():
    meta, err, code = require_auth()
    if err:
        return err, code

    # enrich token meta with user profile fields (email/phone/company/contact)
    meta_out = dict(meta)
    conn = db_connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT email, phone, company_name, contact FROM users WHERE username=?", (meta.get("username"),))
        row = cur.fetchone()
        if row:
            meta_out.update({
                "email": row["email"],
                "phone": row["phone"],
                "company_name": row["company_name"],
                "contact": row["contact"],
            })
    finally:
        conn.close()

    return jsonify(meta_out), 200

@app.post("/orders/create")
def create_order():
    meta, err, code = require_auth()
    if err:
        return err, code

    data = request.get_json(force=True)
    direction = (data.get("direction") or "").strip()
    cargo = (data.get("cargo") or "").strip()
    tonnage = data.get("tonnage") or 0
    truck = (data.get("truck") or "").strip()
    date = (data.get("date") or "").strip()
    price = data.get("price") or 0
    info_text = (data.get("info") or "").strip()

    username = meta["username"]

    conn = db_connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO orders (username, direction, cargo, tonnage, truck, date, price, info, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
            (username, direction, cargo, float(tonnage), truck, date, float(price), info_text, now_ts()),
        )
        order_id = cur.lastrowid

        # publish to market for transport users
        cur.execute("INSERT OR IGNORE INTO market_orders (order_id, status, created_at) VALUES (?, 'open', ?)", (order_id, now_ts()))
        conn.commit()
        return jsonify({"status": "ok", "order_id": order_id}), 201
    finally:
        conn.close()


@app.get("/orders/my")
def list_my_orders():
    meta, err, code = require_auth()
    if err:
        return err, code

    username = meta["username"]
    conn = db_connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM orders WHERE username=? ORDER BY id DESC LIMIT 300", (username,))
        rows = [dict(r) for r in cur.fetchall()]
        return jsonify({"items": rows}), 200
    finally:
        conn.close()


@app.post("/orders/close")
def close_orders():
    meta, err, code = require_auth()
    if err:
        return err, code

    data = request.get_json(force=True)
    ids = data.get("ids") or []
    if not isinstance(ids, list) or not ids:
        return jsonify({"error": "ids required"}), 400

    username = meta["username"]
    conn = db_connect()
    try:
        cur = conn.cursor()
        for oid in ids:
            try:
                oid_i = int(oid)
            except Exception:
                continue
            cur.execute(
                "UPDATE orders SET status='closed', closed_at=? WHERE id=? AND username=?",
                (now_ts(), oid_i, username),
            )
            cur.execute("UPDATE market_orders SET status='closed' WHERE order_id=?", (oid_i,))
        conn.commit()
        return jsonify({"status": "ok"}), 200
    finally:
        conn.close()


@app.get("/market/orders")
def market_orders():
    meta, err, code = require_auth()
    if err:
        return err, code

    role = meta.get("role")
    if role != "transport":
        return jsonify({"error": "forbidden"}), 403

    conn = db_connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT o.* FROM orders o "
            "JOIN market_orders m ON m.order_id = o.id "
            "WHERE m.status='open' "
            "ORDER BY o.id DESC LIMIT 300"
        )
        rows = [dict(r) for r in cur.fetchall()]
        return jsonify({"items": rows}), 200
    finally:
        conn.close()


@app.post("/market/offer")
def market_offer():
    meta, err, code = require_auth()
    if err:
        return err, code

    if meta.get("role") != "transport":
        return jsonify({"error": "forbidden"}), 403

    data = request.get_json(force=True)
    order_id = data.get("order_id")
    price = data.get("price")
    comment = (data.get("comment") or "").strip()
    contact = (data.get("contact") or "").strip()
    company = (data.get("company") or "").strip()

    try:
        order_id_i = int(order_id)
        price_i = int(price)
    except Exception:
        return jsonify({"error": "bad order_id/price"}), 400

    username = meta["username"]
    conn = db_connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM market_orders WHERE order_id=? AND status='open'", (order_id_i,))
        if not cur.fetchone():
            return jsonify({"error": "order_not_open"}), 409

        cur.execute(
            "INSERT OR REPLACE INTO market_offers (order_id, transport_username, price, comment, contact, company, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (order_id_i, username, price_i, comment, contact, company, now_ts()),
        )
        conn.commit()

        # optional notify via telegram engine
        if telegram_engine:
            try:
                telegram_engine.notify_new_offer(order_id_i, username, price_i, comment, contact, company)  # type: ignore
            except Exception:
                pass

        return jsonify({"status": "ok"}), 201
    finally:
        conn.close()


@app.get("/market/offers/<int:order_id>")
def market_offers(order_id: int):
    meta, err, code = require_auth()
    if err:
        return err, code

    conn = db_connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM market_offers WHERE order_id=? ORDER BY created_at DESC LIMIT 200",
            (order_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        return jsonify({"items": rows}), 200
    finally:
        conn.close()


@app.get("/health")
def health():
    return jsonify({
        "status": "ok",
        "time": now_ts(),
        "require_device_id": REQUIRE_DEVICE_ID,
        "require_app_in_login": REQUIRE_APP_IN_LOGIN
    }), 200


# ================== MAIN ==================
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MVP server + local console tools (users/roles/license keys)")
    parser.add_argument("--run", action="store_true", help="Run HTTP server (default if no other action)")

    # ===== License keys =====
    parser.add_argument("--keygen", action="store_true", help="Generate and store a new license key in DB, then exit")
    parser.add_argument("--app", default="any", choices=["any", "manager", "transport"], help="License app scope")
    parser.add_argument("--max-devices", type=int, default=1, help="Max devices for generated key")
    parser.add_argument("--days", type=int, default=0, help="Days until expiration (0 = бессрочно)")
    parser.add_argument("--length", type=int, default=20, help="Key length (12..32)")
    parser.add_argument("--company", default="", help="Bind key to company (optional)")
    parser.add_argument("--note", default="", help="Optional note")

    parser.add_argument("--list-keys", action="store_true", help="List last keys from DB (any status) and exit")
    parser.add_argument("--list-active-keys", action="store_true", help="List only ACTIVE keys (active=1) and exit")
    parser.add_argument("--disable-key", default="", help="Disable license key (active=0). Example: --disable-key ABCD-....")
    parser.add_argument("--enable-key", default="", help="Enable license key (active=1). Example: --enable-key ABCD-....")
    parser.add_argument("--set-key-company", nargs=2, metavar=("KEY", "COMPANY"),
                        help="Bind an existing key to a company. Example: --set-key-company KEY \"My LLC\"")

    # ===== Activations =====
    parser.add_argument("--list-activations", action="store_true",
                        help="List recent license activations (all keys). Use --key to filter.")
    parser.add_argument("--key", default="", help="Filter for --list-activations by license key")
    parser.add_argument("--activations-limit", type=int, default=200, help="Limit for --list-activations (default 200)")

    # ===== Users / roles (read-only) =====
    parser.add_argument("--users-count", action="store_true", help="Print total users + per-role counts and exit")
    parser.add_argument("--list-users", action="store_true", help="List last N users with roles and exit")
    parser.add_argument("--users-limit", type=int, default=200, help="Limit for --list-users (default 200)")

    args = parser.parse_args()

    print(f"[SERVER] DB: {DB_PATH}")

    # ------------------ helpers ------------------
    def _print_users_count():
        conn = db_connect()
        try:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) AS c FROM users")
            total = int(cur.fetchone()["c"] or 0)
            cur.execute("SELECT role, COUNT(*) AS c FROM users GROUP BY role ORDER BY c DESC")
            per_role = {str(r["role"]): int(r["c"] or 0) for r in cur.fetchall()}
        finally:
            conn.close()

        print("TOTAL_USERS:", total)
        print("USERS_BY_ROLE:", per_role)

    def _print_users_list(limit: int):
        limit = int(max(1, min(2000, limit)))
        conn = db_connect()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT username, role, email, phone, company_name, device_id, created_at "
                "FROM users ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
            rows = cur.fetchall()
        finally:
            conn.close()

        for r in rows:
            print(dict(r))

    def _set_license_active(key_raw: str, active: int):
        key = format_license_key(normalize_license_key(key_raw))
        if not key:
            print("ERROR: empty key")
            raise SystemExit(2)

        conn = db_connect()
        try:
            cur = conn.cursor()
            cur.execute("SELECT license_key FROM license_keys WHERE license_key=?", (key,))
            row = cur.fetchone()
            if not row:
                print("ERROR: license_not_found:", key)
                raise SystemExit(2)

            cur.execute("UPDATE license_keys SET active=? WHERE license_key=?", (1 if active else 0, key))
            conn.commit()

            # If key is being disabled, immediately revoke sessions and activations
            if not active:
                try:
                    cur.execute("DELETE FROM license_activations WHERE license_key=?", (key,))
                    conn.commit()
                except Exception:
                    pass
                try:
                    cur.execute("SELECT username FROM users WHERE license_key_used=?", (key,))
                    rows_u = cur.fetchall() or []
                    for r in rows_u:
                        uname = r["username"] if isinstance(r, sqlite3.Row) else r[0]
                        if uname:
                            revoke_all_tokens_for(str(uname))
                except Exception:
                    pass

            cur.execute("SELECT license_key, active, app, max_devices, expires_at, company, note, created_at FROM license_keys WHERE license_key=?", (key,))
            updated = cur.fetchone()
        finally:
            conn.close()

        print("UPDATED_LICENSE:", dict(updated))


    def _set_key_company(key_raw: str, company: str):
        key = format_license_key(normalize_license_key(key_raw))
        if not key:
            print("ERROR: empty key")
            raise SystemExit(2)

        conn = db_connect()
        try:
            cur = conn.cursor()
            cur.execute("SELECT license_key FROM license_keys WHERE license_key=?", (key,))
            row = cur.fetchone()
            if not row:
                print("ERROR: license_not_found:", key)
                raise SystemExit(2)

            cur.execute("UPDATE license_keys SET company=? WHERE license_key=?", ((company or "").strip(), key))
            conn.commit()

            cur.execute("SELECT license_key, active, app, max_devices, expires_at, company, note, created_at FROM license_keys WHERE license_key=?", (key,))
            updated = cur.fetchone()
        finally:
            conn.close()

        print("UPDATED_LICENSE:", dict(updated))

    def _list_keys(active_only: bool = False, limit: int = 200):
        limit = int(max(1, min(2000, limit)))
        conn = db_connect()
        try:
            cur = conn.cursor()
            if active_only:
                cur.execute(
                    "SELECT license_key, app, max_devices, expires_at, active, company, note, created_at "
                    "FROM license_keys WHERE active=1 ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                )
            else:
                cur.execute(
                    "SELECT license_key, app, max_devices, expires_at, active, company, note, created_at "
                    "FROM license_keys ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                )
            rows = cur.fetchall()
        finally:
            conn.close()

        for r in rows:
            print(dict(r))

    def _list_activations(key_raw: str = "", limit: int = 200):
        limit = int(max(1, min(5000, limit)))
        key = format_license_key(normalize_license_key(key_raw)) if key_raw else ""
        conn = db_connect()
        try:
            cur = conn.cursor()
            if key:
                cur.execute(
                    "SELECT a.license_key, k.company, a.app, a.device_id, a.activated_at, a.last_seen, k.active "
                    "FROM license_activations a JOIN license_keys k ON k.license_key=a.license_key "
                    "WHERE a.license_key=? "
                    "ORDER BY a.last_seen DESC LIMIT ?",
                    (key, limit),
                )
            else:
                cur.execute(
                    "SELECT a.license_key, k.company, a.app, a.device_id, a.activated_at, a.last_seen, k.active "
                    "FROM license_activations a JOIN license_keys k ON k.license_key=a.license_key "
                    "ORDER BY a.last_seen DESC LIMIT ?",
                    (limit,),
                )
            rows = cur.fetchall()
        finally:
            conn.close()

        for r in rows:
            print(dict(r))

    # ------------------ actions ------------------
    if args.users_count:
        _print_users_count()
        raise SystemExit(0)

    if args.list_users:
        _print_users_list(args.users_limit)
        raise SystemExit(0)

    if args.disable_key:
        _set_license_active(args.disable_key, 0)
        raise SystemExit(0)

    if args.enable_key:
        _set_license_active(args.enable_key, 1)
        raise SystemExit(0)

    if args.set_key_company:
        _set_key_company(args.set_key_company[0], args.set_key_company[1])
        raise SystemExit(0)

    if args.keygen:
        expires_at = None
        if args.days and args.days > 0:
            expires_at = now_ts() + int(args.days) * 86400
        key = generate_license_key(args.length)

        conn = db_connect()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO license_keys (license_key, app, max_devices, expires_at, active, company, note, created_at) "
                "VALUES (?, ?, ?, ?, 1, ?, ?, ?)",
                (
                    key,
                    args.app,
                    int(max(1, args.max_devices)),
                    expires_at,
                    (args.company or "").strip(),
                    (args.note or "").strip(),
                    now_ts(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

        print("LICENSE_KEY:", key)
        print("APP:", args.app)
        print("MAX_DEVICES:", int(max(1, args.max_devices)))
        print("ACTIVE:", 1)
        print("COMPANY:", (args.company or "").strip())
        print("NOTE:", (args.note or "").strip())
        print("EXPIRES_AT:", expires_at)
        raise SystemExit(0)

    if args.list_keys:
        _list_keys(active_only=False, limit=200)
        raise SystemExit(0)

    if args.list_active_keys:
        _list_keys(active_only=True, limit=200)
        raise SystemExit(0)

    if args.list_activations:
        _list_activations(args.key, args.activations_limit)
        raise SystemExit(0)

    # default: run server
    if args.run or (not args.keygen and not args.list_keys and not args.list_active_keys and not args.list_users and not args.users_count
                    and not args.disable_key and not args.enable_key and not args.set_key_company and not args.list_activations):
        print(f"[SERVER] TELEGRAM_ENABLED env: {TELEGRAM_ENABLED}")
        app.run(host=HOST, port=PORT, debug=False)
