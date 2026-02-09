# telegram_app.py
# pip install telethon fastapi uvicorn

import os
import re
import json
import time
import asyncio
from typing import List, Dict, Tuple, Optional

from fastapi import FastAPI, HTTPException
from telethon import TelegramClient, events
import uvicorn

# ================== CONFIG ==================

API_ID = 37930540
API_HASH = "d94a6e7d6ccc9f931e93db1f3097b079"
PHONE = "+998777988735"
SESSION = "session_Kudratulla"

HOST = "0.0.0.0"
PORT = 5000

# ИНТЕРВАЛ ОТПРАВКИ (20 минут)
SEND_INTERVAL_SECONDS = 20 * 60

# ТОЛЬКО TELEGRAM ID (получатели рассылки заявок)
USERS = {1064838111}

# ================== AUTO REPLY (LEARN FROM YOUR CHATS) ==================
AUTO_REPLY_ENABLED = os.getenv("AUTO_REPLY_ENABLED", "1") == "1"

# сколько сообщений забирать из каждого чата для обучения
LEARN_LIMIT_PER_CHAT = int(os.getenv("LEARN_LIMIT_PER_CHAT", "800"))

# сколько последних реплик давать в контекст
LEARN_CONTEXT_TURNS = int(os.getenv("LEARN_CONTEXT_TURNS", "8"))

# минимальная похожесть (0..1). если ниже — не отвечаем
MIN_SIMILARITY = float(os.getenv("MIN_SIMILARITY", "0.23"))

# задержка перед ответом (сек)
REPLY_DELAY_MIN = float(os.getenv("REPLY_DELAY_MIN", "2.0"))
REPLY_DELAY_MAX = float(os.getenv("REPLY_DELAY_MAX", "6.0"))

# если хочешь отвечать только конкретным людям — перечисли ID через запятую
_allowlist_raw = os.getenv("AUTO_REPLY_ALLOWLIST", "").strip()
AUTO_REPLY_ALLOWLIST = set()
if _allowlist_raw:
    for p in _allowlist_raw.split(","):
        p = p.strip()
        if p.isdigit():
            AUTO_REPLY_ALLOWLIST.add(int(p))

# кэш корпуса на диск
CORPUS_CACHE_PATH = os.getenv("CORPUS_CACHE_PATH", "auto_reply_corpus.jsonl")

# ================== APP ==================

app = FastAPI()
client = TelegramClient(SESSION, API_ID, API_HASH)

# Очередь заявок
orders_queue: List[Dict] = []
queue_lock = asyncio.Lock()

# Корпус для автоответов: (context_text, answer_text, context_tokens_set)
corpus: List[Tuple[str, str, set]] = []
corpus_lock = asyncio.Lock()

# ================== TEXT NORMALIZATION (ADDED) ==================

# унификация апострофов/типичных узбекских вариантов
_APOSTROPHE_MAP = {
    "‘": "'",
    "’": "'",
    "ʻ": "'",
    "ʼ": "'",
    "`": "'",
    "´": "'",
    "o‘": "o'",
    "g‘": "g'",
    "oʻ": "o'",
    "gʻ": "g'",
}

# всё, что НЕ буква/цифра/' — превращаем в пробел (убирает ? ! , . и т.п.)
_CLEAN_RE = re.compile(r"[^a-zа-яё0-9']+", re.IGNORECASE)

def _normalize_text(s: str) -> str:
    """
    Нормализация текста ПЕРЕД обучением/поиском:
    - нижний регистр
    - убрать мусорные символы типа ? ! , . : ; и пр.
    - унифицировать апострофы (для uz)
    - схлопнуть пробелы
    """
    if not s:
        return ""

    s = s.lower()

    # сначала замены для uz-апострофов и вариантов
    for k, v in _APOSTROPHE_MAP.items():
        s = s.replace(k, v)

    # русская нормализация
    s = s.replace("ё", "е")

    # убрать пунктуацию/мусор -> пробел
    s = _CLEAN_RE.sub(" ", s)

    # схлопнуть пробелы
    s = re.sub(r"\s+", " ", s).strip()

    return s

def _tokens(s: str) -> List[str]:
    s = _normalize_text(s)
    return s.split()

def _token_set(s: str) -> set:
    return set(_tokens(s))

def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0

def _build_context_text(turns: List[Dict[str, str]]) -> str:
    parts = []
    for t in turns:
        role = t["role"]
        text = (t["text"] or "").strip()
        # ВАЖНО: нормализацию применяем именно здесь, чтобы и обучение, и поиск были одинаковыми
        text = _normalize_text(text)
        parts.append(f"{role}:{text}")
    return "\n".join(parts).strip()

def _pick_best_answer(query_context: str) -> Tuple[Optional[str], float]:
    qset = _token_set(query_context)
    best_ans = None
    best_score = 0.0

    for ctx, ans, ctxset in corpus:
        score = _jaccard(qset, ctxset)
        if score > best_score:
            best_score = score
            best_ans = ans

    return best_ans, best_score

# ================== LEARN FROM CHATS ==================

async def _load_corpus_from_cache() -> bool:
    if not os.path.exists(CORPUS_CACHE_PATH):
        return False
    try:
        loaded = []
        with open(CORPUS_CACHE_PATH, "r", encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line)
                ctx = rec.get("context", "")
                ans = rec.get("answer", "")
                if ctx and ans:
                    loaded.append((ctx, ans, _token_set(ctx)))
        async with corpus_lock:
            corpus.clear()
            corpus.extend(loaded)
        print(f"[AUTO] corpus loaded from cache: {len(loaded)}")
        return True
    except Exception as e:
        print(f"[AUTO] failed to load cache: {e}")
        return False

async def _save_corpus_to_cache(items: List[Tuple[str, str]]):
    try:
        with open(CORPUS_CACHE_PATH, "w", encoding="utf-8") as f:
            for ctx, ans in items:
                f.write(json.dumps({"context": ctx, "answer": ans}, ensure_ascii=False) + "\n")
        print(f"[AUTO] corpus saved: {len(items)} -> {CORPUS_CACHE_PATH}")
    except Exception as e:
        print(f"[AUTO] failed to save cache: {e}")

async def learn_from_telegram_chats():
    """
    Проходит по личным чатам и строит пары:
      контекст (последние LEARN_CONTEXT_TURNS реплик до ответа) -> твой ответ (msg.out True)
    """
    # Если кэш уже есть — используем. Если ты поменял нормализацию, УДАЛИ auto_reply_corpus.jsonl один раз.
    if await _load_corpus_from_cache():
        return

    learned_pairs: List[Tuple[str, str]] = []

    async for dialog in client.iter_dialogs():
        if dialog.is_group or dialog.is_channel:
            continue
        entity = dialog.entity
        if getattr(entity, "bot", False):
            continue

        msgs = []
        async for msg in client.iter_messages(entity, limit=LEARN_LIMIT_PER_CHAT):
            text = (msg.message or "").strip()
            if not text:
                continue
            msgs.append({"out": bool(getattr(msg, "out", False)), "text": text, "id": int(msg.id)})

        if not msgs:
            continue

        msgs.sort(key=lambda x: x["id"])

        window: List[Dict[str, str]] = []
        for m in msgs:
            role = "logist" if m["out"] else "driver"
            window.append({"role": role, "text": m["text"]})

            if role == "logist":
                ctx_turns = window[:-1][-LEARN_CONTEXT_TURNS:]
                answer = (window[-1]["text"] or "").strip()
                if ctx_turns and answer:
                    ctx_text = _build_context_text(ctx_turns)
                    # ответ НЕ нормализуем (оставляем твой оригинальный стиль), иначе будет “робот”
                    if len(ctx_text) >= 10 and len(answer) >= 1:
                        learned_pairs.append((ctx_text, answer))

            if len(window) > 60:
                window = window[-60:]

    async with corpus_lock:
        corpus.clear()
        for ctx, ans in learned_pairs:
            corpus.append((ctx, ans, _token_set(ctx)))

    print(f"[AUTO] learned pairs: {len(learned_pairs)}")
    await _save_corpus_to_cache(learned_pairs)

# ================== TELEGRAM: INCOMING HANDLER ==================

@client.on(events.NewMessage(incoming=True))
async def on_incoming_message(event):
    if not AUTO_REPLY_ENABLED:
        return

    try:
        if event.is_group or event.is_channel:
            return
    except Exception:
        pass
    try:
        if not event.is_private:
            return
    except Exception:
        pass

    text = (event.raw_text or "").strip()
    if not text:
        return

    sender = await event.get_sender()
    peer_id = getattr(sender, "id", None)
    if not peer_id:
        return

    if AUTO_REPLY_ALLOWLIST and int(peer_id) not in AUTO_REPLY_ALLOWLIST:
        return

    # строим контекст из последних реплик чата (включая новое сообщение)
    context_turns: List[Dict[str, str]] = []
    async for msg in client.iter_messages(event.chat_id, limit=LEARN_CONTEXT_TURNS + 6):
        t = (msg.message or "").strip()
        if not t:
            continue
        role = "logist" if bool(getattr(msg, "out", False)) else "driver"
        context_turns.append({"role": role, "text": t})

    context_turns.reverse()
    context_turns = context_turns[-LEARN_CONTEXT_TURNS:]
    query_context = _build_context_text(context_turns)

    async with corpus_lock:
        ans, score = _pick_best_answer(query_context)

    if not ans or score < MIN_SIMILARITY:
        return

    # задержка перед ответом
    delay = REPLY_DELAY_MIN + (REPLY_DELAY_MAX - REPLY_DELAY_MIN) * (time.time() % 1.0)
    await asyncio.sleep(delay)

    try:
        await event.respond(ans)
    except Exception as e:
        print(f"[AUTO] reply send error to {peer_id}: {e}")

# ================== STARTUP ==================

@app.on_event("startup")
async def startup():
    await client.start(phone=PHONE)
    print("[TG] Telegram connected")

    asyncio.create_task(sender_loop())

    if AUTO_REPLY_ENABLED:
        asyncio.create_task(learn_from_telegram_chats())

# ================== API ==================

@app.post("/send_order")
async def send_order(data: dict):
    """
    REQUIRED:
      direction, cargo, tonnage, truck

    OPTIONAL:
      date, price, requirement
    """
    required = ["direction", "cargo", "tonnage", "truck"]
    for field in required:
        if field not in data or not str(data[field]).strip():
            raise HTTPException(status_code=400, detail=f"Missing field: {field}")

    order = {
        "direction": str(data["direction"]),
        "cargo": str(data["cargo"]),
        "tonnage": str(data["tonnage"]),
        "truck": str(data["truck"]),
        "date": str(data["date"]) if data.get("date") else None,
        "price": str(data["price"]) if data.get("price") else None,
        "requirement": str(data["requirement"]) if data.get("requirement") else None,
    }

    async with queue_lock:
        orders_queue.append(order)

    return {"status": "queued", "queue_size": len(orders_queue)}

# ================== SENDER LOOP ==================

async def sender_loop():
    while True:
        await asyncio.sleep(SEND_INTERVAL_SECONDS)

        async with queue_lock:
            if not orders_queue:
                continue
            batch = orders_queue.copy()
            orders_queue.clear()

        message = build_message(batch)

        for tg_id in USERS:
            try:
                await client.send_message(int(tg_id), message)
                await asyncio.sleep(0.5)
            except Exception as e:
                print(f"[TG] send error to {tg_id}: {e}")

# ================== MESSAGE BUILDER ==================

def build_message(orders: List[Dict]) -> str:
    blocks = []
    for o in orders:
        lines = [
            str(o["direction"]),
            f"{o['cargo']} {o['tonnage']}т",
            str(o["truck"]),
        ]
        if o.get("price"):
            lines.append(f"{o['price']}$")
        if o.get("date"):
            lines.append(str(o["date"]))
        if o.get("requirement"):
            lines.append(str(o["requirement"]))
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)

if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
