# telegram_sender.py
# -*- coding: utf-8 -*-

import os
import time
import sqlite3
import asyncio
from typing import Optional, List, Dict, Any, Tuple, Literal

from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel, Field

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError, RPCError

# ================== ENV ==================
TG_API_ID = int(os.getenv("TG_API_ID", "0"))
TG_API_HASH = os.getenv("TG_API_HASH", "")
TG_SESSION_STRING = os.getenv("TG_SESSION_STRING", "")

SENDER_HOST = os.getenv("SENDER_HOST", "127.0.0.1")
SENDER_PORT = int(os.getenv("SENDER_PORT", "5000"))

DB_PATH = os.getenv("DB_PATH", "/opt/telegram_sender/sender.db")

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")

GROUP_PERIOD_MINUTES = int(os.getenv("GROUP_PERIOD_MINUTES", "30"))

MAX_MSG_PER_MIN = int(os.getenv("MAX_MSG_PER_MIN", "18"))
MAX_MSG_PER_HOUR = int(os.getenv("MAX_MSG_PER_HOUR", "300"))

# message limit safety (Telegram ~4096 chars)
MSG_MAX = 3900

if not TG_API_ID or not TG_API_HASH or not TG_SESSION_STRING:
    raise RuntimeError("Set TG_API_ID, TG_API_HASH, TG_SESSION_STRING in env")


# ================== DB ==================
def db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    return con


def now_ts() -> int:
    return int(time.time())


def init_db():
    con = db()
    cur = con.cursor()

    # targets: where to send
    cur.execute("""
    CREATE TABLE IF NOT EXISTS targets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL,          -- 'group' or 'dm'
        name TEXT,
        peer TEXT NOT NULL UNIQUE,   -- '@username' or numeric chat_id
        created_at INTEGER NOT NULL
    )
    """)

    # orders: incoming logistics orders
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

    # per-target cursor (so no duplicates per chat)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS cursors (
        kind TEXT NOT NULL,          -- 'group' or 'dm'
        peer TEXT NOT NULL,
        last_order_id INTEGER NOT NULL DEFAULT 0,
        updated_at INTEGER NOT NULL,
        PRIMARY KEY(kind, peer)
    )
    """)

    # simple counters for rate-limit
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


# ================== API MODELS ==================
class OrderIn(BaseModel):
    direction: str = Field("", description="Откуда - Куда")
    cargo: str = Field("", description="Груз")
    tonnage: float = Field(0, description="Тоннаж")
    truck: str = Field("", description="Тип транспорта")
    price: Optional[float] = Field(None, description="Цена")
    date: Optional[str] = Field(None, description="Дата")
    info: Optional[str] = Field(None, description="Требования/инфо")


class TargetIn(BaseModel):
    kind: Literal["group", "dm"]
    peer: str = Field(..., description="@username или chat_id (-100...)")
    name: Optional[str] = None


# ================== AUTH ==================
def require_token(x_admin_token: Optional[str]) -> None:
    if not ADMIN_TOKEN:
        raise RuntimeError("ADMIN_TOKEN is empty. Set it in .env")
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid admin token")


# ================== TELEGRAM ==================
client = TelegramClient(StringSession(TG_SESSION_STRING), TG_API_ID, TG_API_HASH)
rate_lock = asyncio.Lock()


async def ensure_client():
    if not client.is_connected():
        await client.connect()
    if not await client.is_user_authorized():
        raise RuntimeError("Telegram session not authorized. Recreate TG_SESSION_STRING.")


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


def format_order_block(idx: int, o: Dict[str, Any]) -> str:
    """
    Требуемый формат:

    1. Направление
    Груз, тоннаж
    Тип транспорта
    Цена (если есть)
    Дата (если есть)
    """
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
                # без лишних .0
                p_txt = str(int(p)) if abs(p - int(p)) < 1e-9 else str(p)
                lines.append(f"{p_txt}$")
        except Exception:
            pass

    if date:
        lines.append(date)

    return "\n".join(lines)


def chunk_messages(blocks: List[str]) -> List[str]:
    """
    Склеивает блоки в сообщения <= MSG_MAX.
    """
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


def fetch_new_orders(con: sqlite3.Connection, after_id: int, limit: int = 200) -> List[Dict[str, Any]]:
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
    """
    Sends all new orders (after cursor) to this target.
    Updates cursor only if send succeeded.
    """
    await ensure_client()

    con = db()
    try:
        last_id = get_cursor(con, kind, peer)
        orders = fetch_new_orders(con, last_id, limit=300)
        if not orders:
            return {"peer": peer, "sent": 0, "last_id": last_id, "status": "no_new"}

        blocks = []
        for i, o in enumerate(orders, start=1):
            blocks.append(format_order_block(i, o))

        messages = chunk_messages(blocks)
        max_sent_id = orders[-1]["id"]

        # send chunks
        for m in messages:
            await rate_limit_ok()
            try:
                await client.send_message(peer, m)
            except FloodWaitError as e:
                await asyncio.sleep(e.seconds + 2)
                # retry once after wait
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
app = FastAPI(title="Telegram Sender (Groups every 30m + manual DM)")

init_db()


@app.on_event("startup")
async def startup():
    await ensure_client()
    asyncio.create_task(group_scheduler_loop())


@app.get("/health")
async def health():
    return {"ok": True, "host": SENDER_HOST, "port": SENDER_PORT}


@app.post("/send_order")
async def send_order(order: OrderIn):
    """
    Called from your server.py (forwarder) to push a new logistics order.
    """
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


@app.post("/targets/add")
async def targets_add(t: TargetIn, x_admin_token: Optional[str] = Header(None)):
    require_token(x_admin_token)

    peer = (t.peer or "").strip()
    if not peer:
        raise HTTPException(400, detail="peer is empty")
    if not (peer.startswith("@") or peer.lstrip("-").isdigit()):
        raise HTTPException(400, detail="peer must be @username or numeric chat_id")

    con = db()
    try:
        con.execute(
            "INSERT INTO targets(kind,name,peer,created_at) VALUES (?,?,?,?)",
            (t.kind, t.name, peer, now_ts())
        )
        con.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(409, detail="target already exists")
    finally:
        con.close()

    return {"ok": True, "kind": t.kind, "peer": peer}


@app.get("/targets/list")
async def targets_list(x_admin_token: Optional[str] = Header(None)):
    require_token(x_admin_token)
    con = db()
    rows = con.execute("SELECT kind,name,peer,created_at FROM targets ORDER BY id DESC").fetchall()
    con.close()
    return [{"kind": r[0], "name": r[1], "peer": r[2], "created_at": r[3]} for r in rows]


@app.post("/targets/remove")
async def targets_remove(peer: str, x_admin_token: Optional[str] = Header(None)):
    require_token(x_admin_token)
    peer = (peer or "").strip()
    con = db()
    cur = con.execute("DELETE FROM targets WHERE peer=?", (peer,))
    con.commit()
    con.close()
    return {"ok": True, "deleted": cur.rowcount}


@app.post("/dms/send_now")
async def dms_send_now(x_admin_token: Optional[str] = Header(None)):
    """
    Manual DM send (call via SSH). Sends new orders to all dm targets.
    """
    require_token(x_admin_token)

    con = db()
    peers = [r[0] for r in con.execute("SELECT peer FROM targets WHERE kind='dm' ORDER BY id ASC").fetchall()]
    con.close()

    if not peers:
        return {"ok": True, "status": "no_dm_targets"}

    results = []
    for p in peers:
        results.append(await send_to_target("dm", p))

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

    results = []
    for p in peers:
        results.append(await send_to_target("group", p))

    return {"ok": True, "results": results}


async def group_scheduler_loop():
    """
    Every GROUP_PERIOD_MINUTES: send new orders to each group target.
    """
    # align to next period boundary (nice, but optional)
    while True:
        try:
            con = db()
            peers = [r[0] for r in con.execute("SELECT peer FROM targets WHERE kind='group' ORDER BY id ASC").fetchall()]
            con.close()

            if peers:
                for p in peers:
                    await send_to_target("group", p)

        except Exception:
            # do not crash loop
            pass

        await asyncio.sleep(max(60, GROUP_PERIOD_MINUTES * 60))
