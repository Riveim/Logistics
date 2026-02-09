# telegram_app.py
# Рассылает заявки в личку водителям из списка USERS и принимает их ответы.
# Полученные ответы (офферы) отправляет на server.py, где они объединяются с откликами из transport_app.
#
# pip install telethon fastapi uvicorn requests

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
API_ID = int(os.getenv("TG_API_ID", "123456"))
API_HASH = os.getenv("TG_API_HASH", "API_HASH")
PHONE = os.getenv("TG_PHONE", "+998901234567")
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
# Кому рассылать (Telegram user IDs)
# Можно передать через env: TG_USERS="123,456,789"
TG_USERS="5112013904,
    7966902342,
    118359043,
    1817780335,
    8499702845,
    8569965030,
    7136405185,
    322165610,
    1891557736,
    7180077267,
    1225082497,
    1324703148,
    874400895,
    8076124659,
    6441723365,
    6060878530,
    5671041404,
    2095190037,
    7727863705,
    763534886,
    585322397,
    8089375604,
    66141011,
    556544226,
    1767507279,
    187018262,
    180161621,
    8498195583,
    1900139161,
    7365607516,
    5567213850,
    398130201,
    48030217,
    6791215087,
    547783261,
    142892404,
    6220099746,
    5364891345,
    2009381830,
    772702942,
    8263639461,
    612096838,
    7778827944,
    8455420676,
    888931941,
    8220689775,
    690404507,
    250866369,
    31616628,
    3227044,
    8218850547,
    140110009,
    1792860231,
    779250657,
    5876910453,
    289947777,
    8382865232,
    793284429,
    6255811114,
    592629854,
    399938925,
    1684842885,
    8167068289,
    545085308,
    6116903450,
    937029722,
    593623982,
    767700277,
    6456413340,
    6582617846,
    471068875,
    8596885137,
    5939051564,
    7718372646,
    6202001514,
    565594213,
    8112826135,
    8238145906,
    500049324,
    1280480656,
    210077465,
    5528887544,
    7140825445,
    7735250971,
    98341672,
    6733766295,
    7976064788,
    642005144,
    5231465598,
    820503694,
    5017164510,
    136202459,
    7316035553,
    494131222,
    6444258305,
    1236162618,
    539057200,
    954935331,
    127896780,
    962832260,
    8332792854,
    586054132,
    8018398253,
    6718376757,
    8337978335,
    5273583462,
    1138204717,
    8533062324,
    817283187,
    7545366614,
    7652989943,
    8192819147,
    551432281,
    421275584,
    8083435727,
    216258433,
    517138324,
    1774696128,
    639177004,
    1042955311,
    394192707,
    7043930081,
    8585013071,
    1652550559,
    1057248475,
    168238168,
    60629002,
    6151119375,
    1301192523,
    7863557008,
    7693081606,
    883494446,
    6834828833,
    7990061182,
    6889750661,
    7362284935,
    5226488881,
    1746605710,
    1058418490,
    5446472005,
    7186774518,
    280929048,
    8137343751,
    1064838111,
    8456735173,
    8326830902,
    6210256063,
    1607802549,
    5474193853,
    1246621915,
    1128993239,
    932878011,
    788087519,
    1392715252,
    860846699,
    8510998530,
    7655437503,
    41732346,
    495525146,
    321996832,
    2100800169,
    384140630,
    7452549631,
    110964129,
    631812762,
    6694558650,
    7670099625,
    8569179833,
    6037157781,
    5745942864,
    1972998885,
    7253389314,
    266283488,
    5140067352,
    794414582,
    178727724,
    6523521732,
    2020469743,
    266012703,
    7283767853,
    184119642,
    1608572382,
    5956066366,
    7543954935,
    119566306,
    1913537818,
    130460792,
    671393077,
    300536459,
    877909994,
    1672325433,
    6849097209,
    7865538386,
    533932513,
    5585563178,
    6097257475,
    2016029664,
    7307305771,
    498021594,
    1814821786,
    6529916834,
    1253461418,
    839501742,
    1791197340,
    8482580787,
    5374858682,
    5409348307,
    1909049933,
    6779222661,
    906830571,
    8261504518,
    101276887,
    6142877722,
    344047900,
    584026291,
    6534176233,
    246100104,
    5999854962,
    2045690947,
    187457662,
    391784818,
    2635453,
    595347740,
    6325612922,
    6238726865,
    46528408,
    1723952666,
    6773398553,
    370564246,
    6325939203,
    7738886130,
    673503465,
    1046978286,
    8581635255,
    6305238370,
    1557125230,
    150307664,
    5200644868,
    612386599,
    1063996618,
    295821519,
    2021905572,
    311926504,
    7703632065,
    5559026493,
    6675377543,
    7561343177,
    1167622099,
    6010601246,
    6030942113,
    7024693387,
    1814619117,
    392712701,
    1023345294,
    872988630,
    816676174,
    7888943402,
    7722962607,
    8332996684,
    1647835811,
    5155060001,
    5898949070,
    8046532344,
    137358139,
    6559930083,
    1366101045,
    847718303,
    6289662266,
    1136800987,
    6253562933,
    7917201252,
    206025967,
    70894029,
    7243668783,
    5961937265,
    887511891,
    632800247,
    5514533426,
    6036212630,
    7878033366,
    8372491816,
    2787220,
    512234656,
    1347594563,
    1005444483,
    5196084162,
    6105598002,
    8406196484,
    368002166,
    7161254284,
    1901244952,
    2021239874,
    544732280,
    6787989028,
    5174920325,
    1760155215,
    418323081,
    8416161780,
    8134797319,
    1690766846,
    7623719293,
    1078167993,
    5046577824,
    7027235917,
    1255381492,
    7261514333,
    1340862615,
    7359477742,
    6518205883,
    6404419756,
    92459865,
    136922402,
    615656383,
    5259120872,
    624406490,
    415174942,
    922733081,
    773270267,
    1234475948,
    7187411078,
    406463783,
    7488225627,
    693955207,
    7892409563,
    7878414672,
    336110608,
    7460269174,
    720748072,
    808357990,
    348257631,
    6959801931,
    120222594,
    7626579736,
    624911601,
    7341657928,
    952712899,
    8463410505,
    2145648615,
    1391471997,
    7242899512,
    1346595646,
    8120339562,
    262129074,
    809986558,
    1996214345,
    84728454,
    6474078472,
    548547086,
    7920349194,
    894843481,
    5028528486,
    1403896641,
    359170175,
    7088789449,
    6812283061,
    5080103025,
    821475389,
    8385942069,
    7079217462,
    7853482244,
    309723870,
    7181495503,
    829137895,
    708344926,
    1013035433,
    292645759,
    71413408,
    1105979906,
    1785735,
    6636058100,
    265819953,
    5766062658,
    167060608,
    390856555,
    1882752125,
    292118338,
    358970238,
    1284791085,
    5159813514,
    6888419225,
    322755443,
    6931954803,
    6900906076,
    5245422491,
    1276013201,
    6344821027,
    65593901,
    1918087,
    5084497635,
    1748671827,
    166142774,
    168964666,
    5240515511,
    7601155305,
    6410728421,
    550983233,
    5650606548,
    519490351,
    7789185739,
    216566520,
    1375402,
    108542684,
    1626305221,
    309744240,
    8328288440,
    455325521,
    7308877563,
    1689192182,
    339004392,
    1037656091,
    1257642087,
    134948403,
    779437281,
    7610576310,
    7770172730,
    8147810067,
    5922401345,
    5366267412,
    1437311847,
    5904131884,
    5567483299,
    7965725666,
    6485132044,
    1313779606,
    5455363596,
    494474281,
    865393205,
    534057574,
    304453322,
    5167103554,
    243756044,
    446093795,
    431513112,
    7258550317,
    344278436,
    247927386,
    7079325509,
    42037793,
    181789989,
    7984323606,
    7393004416,
    1768980651,
    5897989945,
    6287265158,
    6183004796,
    1751971196,
    199826313,
    1318978771,
    7716783270,
    7334739960,
    363751187,
    6118877502,
    5759708328,
    289911383,
    35480098,
    382421488,
    6224350678,
    1545257296,
    7082571133,
    446122305,
    1889133370,
    7929423932,
    6934952955,
    7606637951,
    1893206711,
    1618715993,
    8434398634,
    831579483,
    413022362,
    8265092807,
    978030498,
    414097587,
    902751352,
    233367460,
    600232160,
    183647744,
    1509278317,
    127090858,
    1474355293,
    5711212526,
    1898061570,
    1184905968,
    5742356333,
    233302149,
    7200117580,
    6397537165,
    193690763,
    7694327145,
    1695720321,
    136771024,
    738947344,
    8038325906,
    8207630607,
    495957274,
    677239763,
    8375870941,
    6770735921,
    7257130655,
    1648179660,
    5827021964,
    639520336,
    502837591,
    43415142,
    660111534,
    417322731,
    1813746144,
    480475616,
    87373188,
    8402169047,
    876672802,
    714402507,
    1760175510,
    8311001932,
    578864865,
    204185111,
    662044,
    72020022,
    343283488,
    1794477901,
    6465989179,
    357169978,
    1732438785,
    2046939091,
    687877302,
    835014842,
    653900832,
    6635859246,
    7763246150,
    437775414,
    411834030,
    1785653771,
    5941554741,
    7663561436,
    8285970391,
    1118754817,
    346877009,
    6700999360,
    53609029,
    89235298,
    133096106,
    7364335821,
    904295149,
    2062584398,
    51007767,
    110802953,
    533349140,
    725734465,
    5032119127,
    271758157,
    6983766836,
    7038539742,
    993555007,
    389215944,
    8311984972,
    5644147889,
    259885314,
    874745237,
    7997574184,
    861647520,
    272405396,
    1502453487,
    8038605373,
    735762858,
    5277267668,
    874722354,
    877053747,
    686976923,
    136821790,
    7445781915,
    246137703,
    6759392014,
    202413259,
    16766564,
    168975532,
    755875228,
    363137730,
    255774641,
    1778855576,
    1695771,
    7468070735,
    8044426770,
    226272004,
    7784902972,
    7692624396,
    304525996,
    679100786,
    1799175967,
    5164706689,
    7613106408"
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

