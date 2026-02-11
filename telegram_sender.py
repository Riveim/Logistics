# telegram_sender.py
# -*- coding: utf-8 -*-

import os
import time
import sqlite3
import asyncio
from typing import Optional, List, Dict, Any, Literal, Tuple

from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel, Field

from telethon import TelegramClient
from telethon.errors import FloodWaitError, RPCError


# ================== ENV ==================
TG_API_ID = int(os.getenv("TG_API_ID", "37930540"))
TG_API_HASH = os.getenv("TG_API_HASH", "d94a6e7d6ccc9f931e93db1f3097b079")
TG_SESSION_NAME = os.getenv("TG_SESSION_STRING", "tg_session2")

SENDER_HOST = os.getenv("SENDER_HOST", "127.0.0.1")
SENDER_PORT = int(os.getenv("SENDER_PORT", "5000"))

DB_PATH = os.getenv("DB_PATH", "/opt/telegram_sender/sender.db")

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")

GROUP_PERIOD_MINUTES = int(os.getenv("GROUP_PERIOD_MINUTES", "30"))
MAX_MSG_PER_MIN = int(os.getenv("MAX_MSG_PER_MIN", "18"))
MAX_MSG_PER_HOUR = int(os.getenv("MAX_MSG_PER_HOUR", "300"))
MSG_MAX = 3900

# файл, который ты будешь заполнять по SSH/service
TARGETS_TXT = os.getenv("TARGETS_TXT", "/opt/telegram_sender/tg_users.txt")
TARGETS_SYNC_SECONDS = int(os.getenv("TARGETS_SYNC_SECONDS", "30"))  # как часто перечитывать файл

if not TG_API_ID or not TG_API_HASH or not TG_SESSION_NAME:
    raise RuntimeError("Set TG_API_ID, TG_API_HASH, TG_SESSION_STRING in env")


# ================== DB ==================
def _ensure_db_dir():
    parent = os.path.dirname(os.path.abspath(DB_PATH))
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)


def db() -> sqlite3.Connection:
    _ensure_db_dir()
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    return con


def now_ts() -> int:
    return int(time.time())


def init_db():
    con = db()
    cur = con.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS targets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL,          -- 'group' or 'dm'
        name TEXT,
        peer TEXT NOT NULL UNIQUE,   -- '@username' or numeric id (chat_id/user_id)
        created_at INTEGER NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        direction TEXT NOT NULL,
        cargo TEXT NOT NULL,
        tonnage REAL NOT NULL,
        truck TEXT NOT NULL,
        price REAL,
        date TEXT,
        info TEXT,
        created_at INTEGER NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS cursors (
        kind TEXT NOT NULL,
        peer TEXT NOT NULL,
        last_order_id INTEGER NOT NULL DEFAULT 0,
        updated_at INTEGER NOT NULL,
        PRIMARY KEY(kind, peer)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS counters (
        key TEXT PRIMARY KEY,
        value INTEGER NOT NULL
    )
    """)

    con.commit()
    con.close()


def get_counter(con: sqlite3.Connection, key: str) -> int:
    row = con.execute("SELECT value FROM counters WHERE key=?", (key,)).fetchone()
    return int(row[0]) if row else 0


def set_counter(con: sqlite3.Connection, key: str, value: int) -> None:
    con.execute(
        "INSERT INTO counters(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, int(value))
    )
    con.commit()


def get_cursor(con: sqlite3.Connection, kind: str, peer: str) -> int:
    row = con.execute(
        "SELECT last_order_id FROM cursors WHERE kind=? AND peer=?",
        (kind, peer)
    ).fetchone()
    return int(row[0]) if row else 0


def set_cursor(con: sqlite3.Connection, kind: str, peer: str, last_order_id: int) -> None:
    con.execute(
        "INSERT INTO cursors(kind, peer, last_order_id, updated_at) VALUES(?,?,?,?) "
        "ON CONFLICT(kind, peer) DO UPDATE SET last_order_id=excluded.last_order_id, updated_at=excluded.updated_at",
        (kind, peer, int(last_order_id), now_ts())
    )
    con.commit()


# ================== TELEGRAM ==================
client = TelegramClient(TG_SESSION_NAME, TG_API_ID, TG_API_HASH)
rate_lock = asyncio.Lock()


async def ensure_client():
    if not client.is_connected():
        await client.connect()
    if not await client.is_user_authorized():
        # если сессия уже есть — просто авторизуется
        # если нет — попросит номер/код/2FA (но у тебя уже есть .session)
        await client.start()


async def rate_limit_ok():
    async with rate_lock:
        con = db()
        ts = now_ts()
        minute_bucket = ts // 60
        hour_bucket = ts // 3600

        last_min_bucket = get_counter(con, "min_bucket")
        last_hour_bucket = get_counter(con, "hour_bucket")

        if last_min_bucket != minute_bucket:
            set_counter(con, "min_bucket", minute_bucket)
            set_counter(con, "min_count", 0)
        if last_hour_bucket != hour_bucket:
            set_counter(con, "hour_bucket", hour_bucket)
            set_counter(con, "hour_count", 0)

        min_count = get_counter(con, "min_count")
        hour_count = get_counter(con, "hour_count")

        if min_count >= MAX_MSG_PER_MIN:
            con.close()
            await asyncio.sleep((60 - (ts % 60)) + 1)
            return await rate_limit_ok()

        if hour_count >= MAX_MSG_PER_HOUR:
            con.close()
            await asyncio.sleep((3600 - (ts % 3600)) + 5)
            return await rate_limit_ok()

        set_counter(con, "min_count", min_count + 1)
        set_counter(con, "hour_count", hour_count + 1)
        con.close()


def _clean(s: Optional[str]) -> str:
    return (s or "").strip()


# ================== Targets sync from tg_users.txt ==================
def parse_targets_file(path: str) -> List[Tuple[str, str, Optional[str]]]:
    """
    Returns list of (kind, peer, name)
    kind in {'group','dm'}
    """
    items: List[Tuple[str, str, Optional[str]]] = []
    if not os.path.exists(path):
        return items

    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue

            # Split optional name
            name = None
            if "|" in line:
                left, right = line.split("|", 1)
                line = left.strip()
                name = right.strip() or None

            parts = line.split()
            if len(parts) < 2:
                continue

            typ = parts[0].strip().upper()
            peer = parts[1].strip()

            if typ == "GROUP":
                kind = "group"
            elif typ == "DM":
                kind = "dm"
            else:
                continue

            if not peer:
                continue

            # Basic validation: @username or number (including -100...)
            if not (peer.startswith("@") or peer.lstrip("-").isdigit()):
                continue

            items.append((kind, peer, name))

    return items


def upsert_target(con: sqlite3.Connection, kind: str, peer: str, name: Optional[str]):
    # insert if missing
    try:
        con.execute(
            "INSERT INTO targets(kind,name,peer,created_at) VALUES (?,?,?,?)",
            (kind, name, peer, now_ts())
        )
        con.commit()
    except sqlite3.IntegrityError:
        # already exists; maybe update name/kind if changed
        con.execute("UPDATE targets SET kind=?, name=? WHERE peer=?", (kind, name, peer))
        con.commit()


async def targets_sync_loop():
    """
    Every TARGETS_SYNC_SECONDS: read tg_users.txt and sync into DB targets.
    Does NOT delete targets from DB (safe). If you need deletion—say, I'll add.
    """
    last_mtime = 0.0
    while True:
        try:
            if os.path.exists(TARGETS_TXT):
                mtime = os.path.getmtime(TARGETS_TXT)
                if mtime != last_mtime:
                    last_mtime = mtime
                    items = parse_targets_file(TARGETS_TXT)
                    con = db()
                    for kind, peer, name in items:
                        upsert_target(con, kind, peer, name)
                    con.close()
        except Exception:
            pass

        await asyncio.sleep(max(5, TARGETS_SYNC_SECONDS))


# ================== Message formatting ==================
def format_order_block(idx: int, o: Dict[str, Any]) -> str:
    direction = _clean(o.get("direction"))
    cargo = _clean(o.get("cargo"))
    tonnage = o.get("tonnage", 0) or 0
    truck = _clean(o.get("truck"))
    price = o.get("price", None)
    date = _clean(o.get("date"))

    lines = [f"{idx}. {direction}"]
    lines.append(f"{cargo}, {tonnage}т")
    lines.append(f"{truck}")

    if price is not None:
        try:
            p = float(price)
            if p > 0:
                p_txt = str(int(p)) if abs(p - int(p)) < 1e-9 else str(p)
                lines.append(f"{p_txt}$")
        except Exception:
            pass

    if date:
        lines.append(date)

    return "\n".join(lines)


def chunk_messages(blocks: List[str]) -> List[str]:
    out: List[str] = []
    cur = ""
    for b in blocks:
        piece = (b + "\n\n")
        if len(cur) + len(piece) > MSG_MAX:
            if cur.strip():
                out.append(cur.strip())
            cur = piece
        else:
            cur += piece
    if cur.strip():
        out.append(cur.strip())
    return out


def fetch_new_orders(con: sqlite3.Connection, after_id: int, limit: int = 300) -> List[Dict[str, Any]]:
    rows = con.execute(
        "SELECT id, direction, cargo, tonnage, truck, price, date, info, created_at "
        "FROM orders WHERE id>? ORDER BY id ASC LIMIT ?",
        (int(after_id), int(limit))
    ).fetchall()
    return [
        {
            "id": r[0],
            "direction": r[1],
            "cargo": r[2],
            "tonnage": r[3],
            "truck": r[4],
            "price": r[5],
            "date": r[6],
            "info": r[7],
            "created_at": r[8],
        }
        for r in rows
    ]


async def send_to_target(kind: str, peer: str) -> Dict[str, Any]:
    await ensure_client()

    con = db()
    try:
        last_id = get_cursor(con, kind, peer)
        orders = fetch_new_orders(con, last_id)
        if not orders:
            return {"peer": peer, "sent": 0, "last_id": last_id, "status": "no_new"}

        blocks = [format_order_block(i, o) for i, o in enumerate(orders, start=1)]
        messages = chunk_messages(blocks)
        max_sent_id = orders[-1]["id"]

        for m in messages:
            await rate_limit_ok()
            try:
                await client.send_message(peer, m)
            except FloodWaitError as e:
                await asyncio.sleep(e.seconds + 2)
                await rate_limit_ok()
                await client.send_message(peer, m)
            except RPCError as e:
                return {"peer": peer, "sent": 0, "last_id": last_id, "status": "failed", "error": str(e)}
            except Exception as e:
                return {"peer": peer, "sent": 0, "last_id": last_id, "status": "failed", "error": repr(e)}

        set_cursor(con, kind, peer, max_sent_id)
        return {"peer": peer, "sent": len(orders), "last_id": max_sent_id, "status": "ok"}
    finally:
        con.close()


# ================== FASTAPI ==================
app = FastAPI(title="Telegram Sender (groups every 30m + manual DM; targets from tg_users.txt)")

init_db()


class OrderIn(BaseModel):
    direction: str = Field("", description="Откуда - Куда")
    cargo: str = Field("", description="Груз")
    tonnage: float = Field(0, description="Тоннаж")
    truck: str = Field("", description="Тип транспорта")
    price: Optional[float] = Field(None, description="Цена")
    date: Optional[str] = Field(None, description="Дата")
    info: Optional[str] = Field(None, description="Требования/инфо")


def require_token(x_admin_token: Optional[str]) -> None:
    if not ADMIN_TOKEN:
        raise HTTPException(status_code=500, detail="ADMIN_TOKEN is empty. Set it in .env.")
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid admin token")


@app.on_event("startup")
async def startup():
    await ensure_client()
    asyncio.create_task(targets_sync_loop())
    asyncio.create_task(group_scheduler_loop())


@app.get("/health")
async def health():
    return {"ok": True, "host": SENDER_HOST, "port": SENDER_PORT, "db": DB_PATH, "targets_file": TARGETS_TXT}


@app.post("/send_order")
async def send_order(order: OrderIn):
    direction = _clean(order.direction)
    cargo = _clean(order.cargo)
    truck = _clean(order.truck)

    if not direction or not cargo or not truck:
        raise HTTPException(400, detail="direction/cargo/truck required")

    try:
        tonnage = float(order.tonnage or 0)
    except Exception:
        tonnage = 0

    con = db()
    con.execute(
        "INSERT INTO orders(direction,cargo,tonnage,truck,price,date,info,created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (
            direction,
            cargo,
            tonnage,
            truck,
            float(order.price) if order.price is not None else None,
            _clean(order.date) if order.date else None,
            _clean(order.info) if order.info else None,
            now_ts(),
        )
    )
    con.commit()
    con.close()

    return {"status": "ok"}


@app.get("/targets/list")
async def targets_list(x_admin_token: Optional[str] = Header(None)):
    require_token(x_admin_token)
    con = db()
    rows = con.execute("SELECT kind,name,peer,created_at FROM targets ORDER BY id DESC").fetchall()
    con.close()
    return [{"kind": r[0], "name": r[1], "peer": r[2], "created_at": r[3]} for r in rows]


@app.post("/dms/send_now")
async def dms_send_now(x_admin_token: Optional[str] = Header(None)):
    """
    Manual DM send (call via SSH): sends new orders to all dm targets.
    """
    require_token(x_admin_token)

    con = db()
    peers = [r[0] for r in con.execute("SELECT peer FROM targets WHERE kind='dm' ORDER BY id ASC").fetchall()]
    con.close()

    if not peers:
        return {"ok": True, "status": "no_dm_targets"}

    results = [await send_to_target("dm", p) for p in peers]
    return {"ok": True, "results": results}


@app.post("/groups/send_now")
async def groups_send_now(x_admin_token: Optional[str] = Header(None)):
    """
    Manual group send (optional).
    """
    require_token(x_admin_token)

    con = db()
    peers = [r[0] for r in con.execute("SELECT peer FROM targets WHERE kind='group' ORDER BY id ASC").fetchall()]
    con.close()

    if not peers:
        return {"ok": True, "status": "no_group_targets"}

    results = [await send_to_target("group", p) for p in peers]
    return {"ok": True, "results": results}


async def group_scheduler_loop():
    """
    Every GROUP_PERIOD_MINUTES: send new orders to each group target.
    """
    while True:
        try:
            con = db()
            peers = [r[0] for r in con.execute("SELECT peer FROM targets WHERE kind='group' ORDER BY id ASC").fetchall()]
            con.close()

            for p in peers:
                await send_to_target("group", p)
        except Exception:
            pass

        await asyncio.sleep(max(60, GROUP_PERIOD_MINUTES * 60))
