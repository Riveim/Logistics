# telegram_app.py

import os
import re
import json
import asyncio
import time
from typing import Dict, Any, Optional, Tuple, List

import requests
from fastapi import FastAPI, HTTPException, Request
from telethon import TelegramClient, events
import uvicorn

# ================== TELEGRAM CONFIG ==================
# Эти 3 поля обязательны. Их берёшь на https://my.telegram.org
API_ID = int(os.getenv("TG_API_ID", "37930540"))
API_HASH = os.getenv("TG_API_HASH", "d94a6e7d6ccc9f931e93db1f3097b079")
PHONE = os.getenv("TG_PHONE", "+998777988735")
SESSION = os.getenv("TG_SESSION", "tg_session")

HOST = os.getenv("TG_HOST", "0.0.0.0")
PORT = int(os.getenv("TG_PORT", "5000"))

# ================== SECURITY / SERVER BRIDGE ==================
# Токен проверяется:
# 1) на входе: server.py -> telegram_app.py (/send_order)
# 2) на выходе: telegram_app.py -> server.py (/telegram/offer)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_FORWARD_TOKEN", "CHANGE_ME_TG_TOKEN")
SERVER_API_URL = os.getenv("SERVER_API_URL", "http://127.0.0.1:5000")  # server.py (Flask)

# ================== DELIVERY ==================
SEND_POLL_INTERVAL = float(os.getenv("TG_SEND_POLL_INTERVAL", "1.0"))
SEND_THROTTLE_SEC = float(os.getenv("TG_SEND_THROTTLE_SEC", "0.4"))

# ================== RECIPIENTS ==================
_users_env = (os.getenv("TG_USERS", "") or "").strip()
if _users_env:
    USERS = {int(x.strip()) for x in _users_env.split(",") if x.strip().isdigit()}
else:
    # fallback: можно оставить пустым и передать через env
    USERS: set[int] = set()

# ================== STORAGE ==================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MAP_PATH = os.path.join(BASE_DIR, "tg_order_msg_map.json")

# (uid, msg_id) -> order_id
order_msg_map: Dict[str, int] = {}
map_lock = asyncio.Lock()

# очередь заявок на рассылку
orders_queue: List[Dict[str, Any]] = []
queue_lock = asyncio.Lock()

# ================== PARSING ==================
PRICE_RE = re.compile(r"(?<!\d)(\d{2,7})(?!\d)")


def _map_key(uid: int, msg_id: int) -> str:
    return f"{uid}:{msg_id}"


def load_map() -> None:
    global order_msg_map
    try:
        if os.path.isfile(MAP_PATH):
            with open(MAP_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                # keep only int values
                cleaned = {}
                for k, v in data.items():
                    try:
                        cleaned[str(k)] = int(v)
                    except Exception:
                        pass
                order_msg_map = cleaned
    except Exception:
        order_msg_map = {}


def save_map() -> None:
    try:
        with open(MAP_PATH, "w", encoding="utf-8") as f:
            json.dump(order_msg_map, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def format_order_text(order: Dict[str, Any]) -> str:
    """Текст одного сообщения (одна заявка -> одно сообщение)."""
    oid = order.get("order_id")
    direction = str(order.get("direction") or "")
    cargo = str(order.get("cargo") or "")
    tonnage = order.get("tonnage")
    truck = str(order.get("truck") or "")
    date = str(order.get("date") or "")
    price = order.get("price")
    info = str(order.get("info") or "")
    from_company = str(order.get("from_company") or "")

    lines = [f"📦 Заявка #{oid}"]
    if from_company:
        lines.append(f"Компания: {from_company}")
    if direction:
        lines.append(direction)
    cargo_line = cargo
    try:
        t = float(tonnage)
        if t:
            cargo_line = (cargo_line + f" {t}т").strip()
    except Exception:
        pass
    if cargo_line:
        lines.append(cargo_line)
    if truck:
        lines.append(f"Транспорт: {truck}")
    if date:
        lines.append(f"Дата: {date}")
    if price:
        lines.append(f"Бюджет: {price}$")
    if info:
        lines.append(f"Требования: {info}")

    lines.append("")
    lines.append("💬 Чтобы откликнуться, ОТВЕТЬТЕ на это сообщение (Reply) и напишите цену и контакт.")
    lines.append("Пример: 1200 +998901234567 (или @username) Комментарий...")
    return "\n".join(lines).strip()


def parse_price(text: str) -> Optional[int]:
    if not text:
        return None
    m = PRICE_RE.search(text)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def extract_sender_meta(event) -> Tuple[str, str]:
    """(telegram_username, telegram_name)"""
    username = ""
    name = ""
    try:
        sender = event.sender
        if sender:
            username = getattr(sender, "username", "") or ""
            first = getattr(sender, "first_name", "") or ""
            last = getattr(sender, "last_name", "") or ""
            name = (first + " " + last).strip()
            if not name:
                name = username
    except Exception:
        pass
    return username, name


app = FastAPI()
client = TelegramClient(SESSION, API_ID, API_HASH)


@app.post("/send_order")
async def send_order(order: Dict[str, Any], request: Request):
    token = request.headers.get("X-Telegram-Token", "")
    if not token or token != TELEGRAM_TOKEN:
        raise HTTPException(status_code=403, detail="forbidden")

    # Требуем order_id, чтобы позже правильно связать reply -> заявка
    if "order_id" not in order:
        raise HTTPException(status_code=400, detail="order_id required")

    async with queue_lock:
        orders_queue.append(order)
    return {"status": "queued"}


async def deliver_one_order(order: Dict[str, Any]) -> None:
    if not USERS:
        return

    msg_text = format_order_text(order)
    oid = int(order.get("order_id"))

    for uid in USERS:
        try:
            m = await client.send_message(uid, msg_text)
            # сохраняем связь (uid, msg_id) -> order_id
            async with map_lock:
                order_msg_map[_map_key(uid, int(m.id))] = oid
                save_map()
            await asyncio.sleep(SEND_THROTTLE_SEC)
        except Exception as e:
            print("[TG] send error:", e)


async def sender_loop() -> None:
    while True:
        await asyncio.sleep(SEND_POLL_INTERVAL)
        async with queue_lock:
            if not orders_queue:
                continue
            batch = orders_queue.copy()
            orders_queue.clear()

        # отправляем по одной заявке = 1 сообщение (важно для Reply->order_id)
        for o in batch:
            try:
                await deliver_one_order(o)
            except Exception as e:
                print("[TG] deliver batch error:", e)


async def push_offer_to_server(payload: Dict[str, Any]) -> None:
    try:
        requests.post(
            f"{SERVER_API_URL.rstrip('/')}/telegram/offer",
            json=payload,
            headers={"X-Telegram-Token": TELEGRAM_TOKEN},
            timeout=8,
        )
    except Exception as e:
        print("[TG] push_offer_to_server error:", e)


@client.on(events.NewMessage(incoming=True))
async def on_new_message(event):
    # Только личка
    if not event.is_private:
        return

    text = (event.raw_text or "").strip()
    if not text:
        return

    # нас интересуют только ответы (reply) на наши сообщения с заявками
    if not event.is_reply:
        return

    try:
        reply = await event.get_reply_message()
        if not reply:
            return
        replied_msg_id = int(reply.id)
    except Exception:
        return

    sender_id = int(event.sender_id or 0)
    if not sender_id:
        return

    # найдём order_id по (uid, replied_msg_id)
    async with map_lock:
        oid = order_msg_map.get(_map_key(sender_id, replied_msg_id))

    if not oid:
        return

    price = parse_price(text)
    if price is None:
        # игнорируем ответы без цены
        return

    tg_username, tg_name = extract_sender_meta(event)

    payload = {
        "order_id": int(oid),
        "price": int(price),
        "comment": text,
        "telegram_id": str(sender_id),
        "telegram_username": tg_username,
        "telegram_name": tg_name,
    }

    await push_offer_to_server(payload)


@app.on_event("startup")
async def startup():
    load_map()
    await client.start(phone=PHONE)
    asyncio.create_task(sender_loop())
    print("[TG] READY")


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)





