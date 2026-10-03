import asyncio
import hashlib
import json
import logging
import math
import os
import re
import secrets
import shutil
import sqlite3
import tempfile
import time
from contextlib import suppress

import urllib.parse
import urllib.request

import yt_dlp
from aiohttp import web
from aiogram import BaseMiddleware, Bot, Dispatcher, F, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

logging.basicConfig(level=logging.INFO)

API_TOKEN = "8656378230:AAH5VKXBUKhCWwR3Bzb6I2O5BA5dTa2ZtWE"  # tokenni kodga yozmang
ADMIN_ID = int(os.getenv("ADMIN_ID", "8756103290"))
DATA_DIR = os.getenv("DATA_DIR", ".")  # Railway Volume ulangan bo'lsa, masalan /data
KARTA_FAYL = os.path.join(DATA_DIR, "karta.json")
MIN_MIQDOR, MAX_MIQDOR = 100, 100000

bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Xizmatlar katalogi: platforma -> {xizmat: 1000 ta uchun narx (so'm)}
# Yangi platforma yoki xizmat qo'shish uchun shu ro'yxatga qator qo'shing.
KATALOG = {
    "Telegram": {"👤 Obunachilar": 10000, "👁 Ko'rishlar": 500, "🔥 Reaksiyalar": 1500, "📊 Ovozlar": 3000},
    "Instagram": {"👤 Obunachilar": 15000, "👁 Ko'rishlar": 250, "❤️ Layklar": 2000},
    "TikTok": {"👤 Obunachilar": 20000, "👁 Ko'rishlar": 300, "❤️ Layklar": 2500},
    "YouTube": {"👤 Obunachilar": 50000, "👁 Ko'rishlar": 8000, "👍 Layklar": 5000},
}


def pul(n):
    return f"{n:,}".replace(",", " ") + " so'm"


PLATFORMALAR = {p: f"1000 ta obunachi: {pul(x['👤 Obunachilar'])}" for p, x in KATALOG.items()}
NARXLAR = "💰 Xizmatlarimiz narxi:\n\n" + "\n".join(f"• {p}: {n}" for p, n in PLATFORMALAR.items())
nomlar = list(KATALOG)

# ---------- BAZA ----------

db = sqlite3.connect(os.path.join(DATA_DIR, "bot.db"))
db.executescript("""
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, balans INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS orders(
    id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, platforma TEXT, xizmat TEXT,
    havola TEXT, miqdor INTEGER, narx INTEGER, holat TEXT DEFAULT 'Jarayonda');
CREATE TABLE IF NOT EXISTS topups(
    id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, summa INTEGER, holat TEXT DEFAULT 'kutilmoqda');
""")
with suppress(sqlite3.OperationalError):
    db.execute("ALTER TABLE orders ADD COLUMN smm_id INTEGER")  # panel buyurtma raqami


def balans(uid):
    db.execute("INSERT OR IGNORE INTO users(id) VALUES(?)", (uid,))
    return db.execute("SELECT balans FROM users WHERE id=?", (uid,)).fetchone()[0]


def balans_ozgar(uid, d):
    balans(uid)
    db.execute("UPDATE users SET balans=balans+? WHERE id=?", (d, uid))
    db.commit()


def karta_oqi():
    try:
        with open(KARTA_FAYL, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


# ---------- TUGMALAR ----------

def kb(*rows):
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t) for t in r] for r in rows], resize_keyboard=True
    )


def ik(*rows):
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=d) for t, d in r] for r in rows]
    )


def menyu(uid):
    rows = [
        ["🗂 Xizmatlarga buyurtma berish", "🎵 Musiqa qidirish"],
        ["💵 Hisob to'ldirish", "💰 Mening hisobim"],
        ["🔎 Buyurtmalarim", "👥 Pul ishlash"],
        ["⭐ Stars hizmati", "💎 Premium olish"],
        ["Zayafka qoldirish", "☎️ Qo'llab-quvvatlash"],
    ]
    if uid == ADMIN_ID:
        rows.append(["💳 Karta qo'shish"])
    return kb(*rows)


platforma_menyu = kb(nomlar[:2], nomlar[2:], ["Bekor qilish"])
bekor_menyu = kb(["Bekor qilish"])


def platforma_kb():
    return ik(*[[(p, f"p:{p}") for p in nomlar[i:i + 2]] for i in range(0, len(nomlar), 2)])


class Zayafka(StatesGroup):
    platforma = State()
    ism = State()
    telefon = State()


class Musiqa(StatesGroup):
    nom = State()


class Karta(StatesGroup):
    raqam = State()
    egasi = State()


class Buyurtma(StatesGroup):
    havola = State()
    miqdor = State()


class Tolov(StatesGroup):
    summa = State()
    chek = State()


# ---------- MUSIQA FUNKSIYALARI ----------

# YouTube botni "bot" deb aniqlab so'rovni rad etganda cookie fayl yordam beradi.
# Cookie faylini olish: brauzerda YouTube'ga kiring, "Cookie-Editor" kengaytmasi
# orqali cookies.txt (Netscape format) ni eksport qiling va YOUTUBE_COOKIES
# environment o'zgaruvchisida fayl yo'lini ko'rsating.
COOKIES_FAYL = os.getenv("YOUTUBE_COOKIES") or None

# Railway Variables ichidagi YT_COOKIES (cookies.txt matni) ni faylga yozamiz
_yt_cookies = os.getenv("YT_COOKIES")
if _yt_cookies:
    COOKIES_FAYL = os.path.join(tempfile.gettempdir(), "cookies.txt")
    with open(COOKIES_FAYL, "w", encoding="utf-8") as _f:
        _f.write(_yt_cookies.strip() + "\n")
    logging.info("YouTube cookies yuklandi: %s", COOKIES_FAYL)

# YouTube server IP ni bloklaganda ishlatiladigan zaxira (Piped) serverlari
PIPED_SERVERLAR = [
    "https://pipedapi.kavin.rocks",
    "https://api.piped.private.coffee",
    "https://pipedapi.adminforge.de",
    "https://pipedapi.reallyaweso.me",
]

# YouTube "Sign in to confirm you're not a bot" xatosini aylanib o'tish uchun
# turli player clientlar ketma-ket sinab ko'riladi
# None = yt-dlp ning standart clientlari (cookies bilan eng yaxshi ishlaydi)
PLAYER_CLIENTLAR = [None, "android_vr", "tv_embedded", "web_creator", "web"]


def _client_args(client):
    if not client:
        return {}
    return {"extractor_args": {"youtube": {"player_client": [client]}}}


def _ydl_opts(**qoshimcha):
    opts = {
        "quiet": True,
        "noplaylist": True,
        "nocheckcertificate": True,
        "max_filesize": 48 * 1024 * 1024,
        "http_headers": {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
        "js_runtimes": {"deno": {}},  # YouTube uchun JS runtime (Dockerfile'da o'rnatiladi)
    }
    if COOKIES_FAYL and os.path.exists(COOKIES_FAYL):
        opts["cookiefile"] = COOKIES_FAYL
    opts.update(qoshimcha)
    return opts


def qidir(soz):
    # 1) YouTube'da turli player clientlar bilan qidirish
    oxirgi_xato = None
    for client in PLAYER_CLIENTLAR:
        try:
            opts = _ydl_opts(
                extract_flat=True,
                skip_download=True,
                **_client_args(client),
            )
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f"ytsearch5:{soz}", download=False)
            natijalar = [
                (e["id"], e.get("title") or "Nomsiz")
                for e in (info.get("entries") or [])
                if e and e.get("id")
            ]
            if natijalar:
                return natijalar
        except Exception as e:
            oxirgi_xato = e
            logging.warning("Qidiruv (%s) xato: %s", client, e)

    # 2) Zaxira: Piped orqali qidirish
    natijalar = qidir_piped(soz)
    if natijalar:
        return natijalar

    if oxirgi_xato:
        raise oxirgi_xato
    raise RuntimeError("Hech qanday natija topilmadi")


def qidir_piped(soz):
    for server in PIPED_SERVERLAR:
        try:
            url = f"{server}/search?q={urllib.parse.quote(soz)}&filter=videos"
            sorov = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(sorov, timeout=12) as javob:
                data = json.load(javob)
            natijalar = []
            for e in data.get("items", [])[:5]:
                vid = (e.get("url") or "").split("watch?v=")[-1].split("&")[0]
                if vid and e.get("title"):
                    natijalar.append((vid, e["title"]))
            if natijalar:
                logging.info("Piped (%s) orqali qidirildi", server)
                return natijalar
        except Exception:
            continue
    return []


def yukla(video_id, papka):
    # 1) yt-dlp bilan turli player clientlarni sinash
    oxirgi_xato = None
    for client in PLAYER_CLIENTLAR:
        try:
            opts = _ydl_opts(
                format="bestaudio[ext=m4a]/bestaudio/best",
                outtmpl=os.path.join(papka, "%(id)s.%(ext)s"),
                **_client_args(client),
            )
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=True)
            fayllar = os.listdir(papka)
            if not fayllar:
                raise FileNotFoundError("Audio fayl topilmadi.")
            return os.path.join(papka, fayllar[0]), info.get("title") or "Nomsiz"
        except Exception as e:
            oxirgi_xato = e
            logging.warning("Yuklash (%s) xato: %s", client, e)

    # 2) Zaxira: Piped orqali to'g'ridan-to'g'ri audio oqimini yuklash
    try:
        return yukla_piped(video_id, papka)
    except Exception as e:
        logging.warning("Piped yuklash xato: %s", e)

    raise oxirgi_xato or RuntimeError("Yuklab bo'lmadi")


def yukla_piped(video_id, papka):
    for server in PIPED_SERVERLAR:
        try:
            sorov = urllib.request.Request(
                f"{server}/streams/{video_id}", headers={"User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(sorov, timeout=15) as javob:
                data = json.load(javob)
            oqimlar = [s for s in data.get("audioStreams", []) if s.get("url")]
            if not oqimlar:
                continue
            eng_yaxshi = max(oqimlar, key=lambda s: s.get("bitrate") or 0)
            kengaytma = (eng_yaxshi.get("format") or "m4a").lower()
            fayl = os.path.join(papka, f"{video_id}.{kengaytma}")
            sorov = urllib.request.Request(eng_yaxshi["url"], headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(sorov, timeout=120) as javob, open(fayl, "wb") as f:
                shutil.copyfileobj(javob, f)
            logging.info("Piped (%s) orqali yuklandi", server)
            return fayl, data.get("title") or "Nomsiz"
        except Exception:
            continue
    raise RuntimeError("Piped serverlarida audio topilmadi")


# ---------- SMM PANEL (avtomatik buyurtma) ----------

# Railway Variables: SMM_API_URL (masalan https://panel.smmflw.com/api/v2) va SMM_API_KEY.
# Ikkalasi ham bo'lmasa, bot avvalgidek qo'lda ishlaydi (admin tugma bosadi).
SMM_API_URL = os.getenv("SMM_API_URL")
SMM_API_KEY = os.getenv("SMM_API_KEY")

# Bizning xizmat -> panelning "Services" sahifasidagi xizmat ID raqami.
# None qoldirilgan xizmat qo'lda (admin orqali) bajariladi.
SMM_XIZMAT = {
    ("Telegram", "👤 Obunachilar"): None,
    ("Telegram", "👁 Ko'rishlar"): None,
    ("Telegram", "🔥 Reaksiyalar"): None,
    ("Telegram", "📊 Ovozlar"): None,
    ("Instagram", "👤 Obunachilar"): None,
    ("Instagram", "👁 Ko'rishlar"): None,
    ("Instagram", "❤️ Layklar"): None,
    ("TikTok", "👤 Obunachilar"): None,
    ("TikTok", "👁 Ko'rishlar"): None,
    ("TikTok", "❤️ Layklar"): None,
    ("YouTube", "👤 Obunachilar"): None,
    ("YouTube", "👁 Ko'rishlar"): None,
    ("YouTube", "👍 Layklar"): None,
}


def smm_sorov(**params):
    data = urllib.parse.urlencode({"key": SMM_API_KEY, **params}).encode()
    sorov = urllib.request.Request(SMM_API_URL, data=data, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(sorov, timeout=30) as javob:
        return json.load(javob)


def smm_havola(h):
    h = h.strip()
    if h.startswith("@"):
        return "https://t.me/" + h[1:]
    if h.startswith("t.me/"):
        return "https://" + h
    return h


async def smm_yubor(sid, havola, miqdor):
    """('qolda', None) | ('ok', panel_id) | ('xato', matn) | ('noaniq', matn)"""
    if not (SMM_API_URL and SMM_API_KEY and sid):
        return "qolda", None
    try:
        j = await asyncio.to_thread(
            smm_sorov, action="add", service=sid, link=smm_havola(havola), quantity=miqdor
        )
    except Exception as e:
        # Tarmoq xatosi: buyurtma panelga yetib borgan-bormaganini bilmaymiz
        logging.exception("SMM add xatosi")
        return "noaniq", str(e)
    if j.get("order"):
        return "ok", int(j["order"])
    return "xato", str(j.get("error") or j)


def buyurtma_yop(oid, yangi, qaytar=0):
    """Buyurtmani faqat 'Jarayonda' bo'lsa yopadi. Foydalanuvchi ID sini qaytaradi."""
    c = db.execute("UPDATE orders SET holat=? WHERE id=? AND holat='Jarayonda'", (yangi, oid))
    if c.rowcount == 0:
        return None
    uid = db.execute("SELECT uid FROM orders WHERE id=?", (oid,)).fetchone()[0]
    db.commit()
    if qaytar > 0:
        balans_ozgar(uid, qaytar)
    return uid


async def smm_kuzat():
    """Har daqiqada panel buyurtmalari holatini tekshiradi."""
    while True:
        await asyncio.sleep(60)
        try:
            qatorlar = db.execute(
                "SELECT id, smm_id, narx, miqdor FROM orders WHERE holat='Jarayonda' AND smm_id IS NOT NULL"
            ).fetchall()
            for oid, sid, narx, miqdor in qatorlar:
                try:
                    j = await asyncio.to_thread(smm_sorov, action="status", order=sid)
                except Exception:
                    continue
                st = str(j.get("status", "")).strip().lower()
                if st == "completed":
                    uid = buyurtma_yop(oid, "Bajarildi")
                    matn = f"✅ #{oid}-buyurtmangiz bajarildi!"
                elif st in ("canceled", "cancelled", "refunded", "failed"):
                    uid = buyurtma_yop(oid, "Bekor qilindi", narx)
                    matn = f"🚫 #{oid}-buyurtmangiz bekor qilindi. {pul(narx)} hisobingizga qaytarildi."
                elif st == "partial":
                    try:
                        qolgan = int(float(j.get("remains") or 0))
                    except ValueError:
                        qolgan = 0
                    qaytar = min(narx, round(narx * qolgan / miqdor)) if miqdor else 0
                    uid = buyurtma_yop(oid, "Qisman bajarildi", qaytar)
                    matn = (
                        f"⚠️ #{oid}-buyurtma qisman bajarildi. "
                        f"Bajarilmagan qismi uchun {pul(qaytar)} hisobingizga qaytarildi."
                    )
                else:
                    continue
                if uid:
                    with suppress(Exception):
                        await bot.send_message(uid, matn)
                    with suppress(Exception):
                        await bot.send_message(ADMIN_ID, f"ℹ️ Buyurtma #{oid}: {st} (panel #{sid})")
        except Exception:
            logging.exception("SMM kuzatuvchi xatosi")


def env_son(nom, default):
    """Railway o'zgaruvchisidan raqam oladi. "11760 SO'M" kabi yozilsa ham raqamni ajratib oladi."""
    qiymat = os.getenv(nom, "")
    m = re.search(r"\d+(?:[.,]\d+)?", qiymat.replace(" ", ""))
    if not m:
        return default
    return float(m.group().replace(",", "."))


# ---------- PANEL KATALOGI (xizmatlar paneldan avtomatik olinadi) ----------

USD_KURS = env_son("USD_KURS", 12500)  # 1 dollar necha so'm (Railway Variables'da o'zgartiring)
USTAMA = env_son("USTAMA", 30)  # panel narxiga foiz ustama (sizning foydangiz)
PLAT_TARTIB = ["Telegram", "Instagram", "TikTok", "YouTube", "Boshqa"]
KESH = {"xizmat": {}, "plat": {}, "plat_list": [], "cat_list": {}, "vaqt": 0}


def platforma_aniq(cat, nom):
    t = f"{cat} {nom}".lower()
    for p in PLAT_TARTIB[:-1]:
        if p.lower() in t:
            return p
    return "Boshqa"


def katalog_yukla():
    j = smm_sorov(action="services")
    if not isinstance(j, list):
        raise ValueError(f"Xizmatlar ro'yxati kelmadi: {j}")
    xiz, plat = {}, {}
    for s in j:
        try:
            if str(s.get("type", "default")).lower() != "default":
                continue  # faqat oddiy (link + miqdor) xizmatlar
            sid = int(s["service"])
            rate = float(s["rate"])
            mn, mx = int(float(s["min"])), int(float(s["max"]))
        except (KeyError, ValueError, TypeError):
            continue
        cat = str(s.get("category") or "Boshqa").strip()
        nom = str(s.get("name") or sid).strip()
        p = platforma_aniq(cat, nom)
        narx = max(1, round(rate * USD_KURS * (1 + USTAMA / 100)))
        xiz[sid] = {"name": nom, "cat": cat, "plat": p, "mn": mn, "mx": mx, "narx": narx, "rate": rate}
        plat.setdefault(p, {}).setdefault(cat, []).append(sid)
    for p in plat:
        for c in plat[p]:
            plat[p][c].sort(key=lambda i: xiz[i]["narx"])
    KESH.update(
        xizmat=xiz,
        plat=plat,
        plat_list=[p for p in PLAT_TARTIB if p in plat],
        cat_list={p: sorted(plat[p]) for p in plat},
        vaqt=time.time(),
    )
    return len(xiz)


async def katalog_yangila():
    """Ishga tushganda va har 30 daqiqada paneldan xizmatlarni yangilaydi."""
    while True:
        try:
            n = await asyncio.to_thread(katalog_yukla)
            logging.info("Panel katalogi yangilandi: %s ta xizmat", n)
        except Exception:
            logging.exception("Panel katalogini yuklab bo'lmadi")
        await asyncio.sleep(1800)


def sahifa(royxat, pg, olcham=8):
    jami = max(1, -(-len(royxat) // olcham))
    pg = min(max(pg, 0), jami - 1)
    return royxat[pg * olcham:(pg + 1) * olcham], pg, jami


def nav(pg, jami, prefiks):
    qator = []
    if pg > 0:
        qator.append(("◀️", f"{prefiks}:{pg - 1}"))
    qator.append((f"{pg + 1}/{jami}", "noop"))
    if pg < jami - 1:
        qator.append(("▶️", f"{prefiks}:{pg + 1}"))
    return qator


def smm_platformalar_kb():
    pl = KESH["plat_list"]
    tugmalar = [
        (f"{p} ({sum(len(v) for v in KESH['plat'][p].values())})", f"sk:{i}:0") for i, p in enumerate(pl)
    ]
    return ik(*[tugmalar[i:i + 2] for i in range(0, len(tugmalar), 2)])


@dp.callback_query(F.data == "noop")
async def noop(callback: types.CallbackQuery):
    await callback.answer()


@dp.callback_query(F.data == "sp")
async def smm_platformalar(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "👇 Quyidagi ijtimoiy tarmoqlardan birini tanlang.", reply_markup=smm_platformalar_kb()
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("sk:"))
async def smm_kategoriyalar(callback: types.CallbackQuery):
    _, pi, pg = callback.data.split(":")
    try:
        p = KESH["plat_list"][int(pi)]
    except (IndexError, ValueError):
        return await callback.answer("Ro'yxat yangilandi, qaytadan oching.", show_alert=True)
    qism, pg, jami = sahifa(KESH["cat_list"][p], int(pg))
    base = int(pg) * 8
    tugmalar = [[(c[:48], f"ss:{pi}:{base + i}:0")] for i, c in enumerate(qism)]
    if jami > 1:
        tugmalar.append(nav(pg, jami, f"sk:{pi}"))
    tugmalar.append([("⬅️ Ortga", "sp")])
    await callback.message.edit_text(f"📱 {p}: bo'limni tanlang", reply_markup=ik(*tugmalar))
    await callback.answer()


@dp.callback_query(F.data.startswith("ss:"))
async def smm_xizmatlar(callback: types.CallbackQuery):
    _, pi, ci, pg = callback.data.split(":")
    try:
        p = KESH["plat_list"][int(pi)]
        cat = KESH["cat_list"][p][int(ci)]
    except (IndexError, ValueError):
        return await callback.answer("Ro'yxat yangilandi, qaytadan oching.", show_alert=True)
    qism, pg, jami = sahifa(KESH["plat"][p][cat], int(pg))
    tugmalar = [
        [(f"{KESH['xizmat'][i]['name'][:34]} — {pul(KESH['xizmat'][i]['narx'])}", f"sx:{i}")] for i in qism
    ]
    if jami > 1:
        tugmalar.append(nav(pg, jami, f"ss:{pi}:{ci}"))
    tugmalar.append([("⬅️ Ortga", f"sk:{pi}:0")])
    await callback.message.edit_text(
        f"📂 {cat[:60]}\n💰 Narxlar 1000 ta uchun:", reply_markup=ik(*tugmalar)
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("sx:"))
async def smm_xizmat_tanlandi(callback: types.CallbackQuery, state: FSMContext):
    s = KESH["xizmat"].get(int(callback.data[3:]))
    if not s:
        return await callback.answer("Xizmat topilmadi, ro'yxatni qaytadan oching.", show_alert=True)
    await state.clear()
    await state.set_state(Buyurtma.havola)
    await state.update_data(
        p=s["plat"], x=s["name"][:60], sid=int(callback.data[3:]),
        narx1000=s["narx"], mn=s["mn"], mx=s["mx"],
    )
    await callback.message.answer(
        f"📌 {s['name']}\n💰 Narxi: {pul(s['narx'])} / 1000 ta\n"
        f"➕ Miqdor: {s['mn']} – {s['mx']}\n\n📎 Havolani (link) yuboring:",
        reply_markup=bekor_menyu,
    )
    await callback.answer()


# ---------- MAJBURIY OBUNA ----------

# Railway Variables: MAJBURIY_KANALLAR=@kanal1,@kanal2  (bot shu kanallarda ADMIN bo'lishi shart)
KANALLAR = [k.strip() for k in os.getenv("MAJBURIY_KANALLAR", "").split(",") if k.strip().startswith("@")]
OBUNA_KESH = {}  # uid -> oxirgi muvaffaqiyatli tekshiruv vaqti
KUTILAYOTGAN_REF = {}  # obuna bo'lmagan foydalanuvchining referal havolasi


async def obuna_yoq(uid):
    if time.time() - OBUNA_KESH.get(uid, 0) < 300:
        return []
    yoq = []
    for k in KANALLAR:
        try:
            m = await bot.get_chat_member(k, uid)
            if m.status in ("left", "kicked"):
                yoq.append(k)
        except Exception:
            logging.warning("Obunani tekshirib bo'lmadi (%s). Bot kanalda admin ekanini tekshiring.", k)
    if not yoq:
        OBUNA_KESH[uid] = time.time()
    return yoq


def obuna_kb(yoq):
    qatorlar = [[InlineKeyboardButton(text=f"📢 {k}", url=f"https://t.me/{k[1:]}")] for k in yoq]
    qatorlar.append([InlineKeyboardButton(text="✅ Tekshirish", callback_data="obuna_tekshir")])
    return InlineKeyboardMarkup(inline_keyboard=qatorlar)


class ObunaMW(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if not KANALLAR or not user or user.id == ADMIN_ID:
            return await handler(event, data)
        if isinstance(event, types.CallbackQuery):
            if event.data == "obuna_tekshir":
                return await handler(event, data)
            xabar = event.message
        else:
            xabar = event
            if xabar.chat.type != "private":
                return await handler(event, data)
        yoq = await obuna_yoq(user.id)
        if not yoq:
            return await handler(event, data)
        if isinstance(event, types.Message) and (event.text or "").startswith("/start "):
            KUTILAYOTGAN_REF[user.id] = event.text.split(" ", 1)[1].strip()
        await xabar.answer(
            "Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling.", reply_markup=obuna_kb(yoq)
        )
        if isinstance(event, types.CallbackQuery):
            await event.answer()


@dp.callback_query(F.data == "obuna_tekshir")
async def obuna_tekshir(callback: types.CallbackQuery):
    uid = callback.from_user.id
    OBUNA_KESH.pop(uid, None)
    yoq = await obuna_yoq(uid)
    if yoq:
        return await callback.answer("Siz hali hamma kanalga obuna bo'lmagansiz.", show_alert=True)
    await callback.message.edit_text("✅ Obuna tasdiqlandi!")
    await ref_qayd(uid, KUTILAYOTGAN_REF.pop(uid, ""))
    balans(uid)
    await callback.message.answer("Kerakli bo'limni tanlang:", reply_markup=menyu(uid))
    await callback.answer()


# ---------- REFERAL (Pul ishlash) ----------

REFERAL_BONUS = int(env_son("REFERAL_BONUS", 500))  # taklif qilgan odamga so'mda
with suppress(sqlite3.OperationalError):
    db.execute("ALTER TABLE users ADD COLUMN ref INTEGER")


async def ref_qayd(uid, ref):
    """Yangi foydalanuvchi referal havola orqali kelsa, taklif qilgan odamga bonus beradi."""
    if not ref.isdigit() or int(ref) == uid:
        return
    rid = int(ref)
    if db.execute("SELECT 1 FROM users WHERE id=?", (uid,)).fetchone():
        return  # yangi emas
    if not db.execute("SELECT 1 FROM users WHERE id=?", (rid,)).fetchone():
        return
    db.execute("INSERT INTO users(id, ref) VALUES(?, ?)", (uid, rid))
    db.commit()
    if REFERAL_BONUS > 0:
        balans_ozgar(rid, REFERAL_BONUS)
        with suppress(Exception):
            await bot.send_message(
                rid, f"🎉 Sizning havolangiz orqali yangi foydalanuvchi qo'shildi!\n💰 +{pul(REFERAL_BONUS)}"
            )


@dp.message(F.text == "👥 Pul ishlash")
async def pul_ishlash(message: types.Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    me = await bot.get_me()
    n = db.execute("SELECT COUNT(*) FROM users WHERE ref=?", (uid,)).fetchone()[0]
    await message.answer(
        "👥 Do'stlaringizni taklif qiling va pul ishlang!\n\n"
        f"Har bir yangi foydalanuvchi uchun: {pul(REFERAL_BONUS)}\n"
        f"🔗 Sizning havolangiz:\nhttps://t.me/{me.username}?start={uid}\n\n"
        f"👤 Taklif qilganlaringiz: {n} ta",
        reply_markup=menyu(uid),
    )


# ---------- QO'LLAB-QUVVATLASH va ADMIN ----------

SUPPORT = os.getenv("SUPPORT_USERNAME", "").lstrip("@")  # masalan: mening_username


@dp.message(F.text == "☎️ Qo'llab-quvvatlash")
async def yordam(message: types.Message, state: FSMContext):
    await state.clear()
    havola = f"https://t.me/{SUPPORT}" if SUPPORT else f"tg://user?id={ADMIN_ID}"
    await message.answer(
        "☎️ Savol va takliflar uchun admin bilan bog'laning:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="👨‍💻 Adminga yozish", url=havola)]]
        ),
    )


@dp.message(Command("panel"), F.from_user.id == ADMIN_ID)
async def panel_holat(message: types.Message):
    if not (SMM_API_URL and SMM_API_KEY):
        return await message.answer("SMM_API_URL va SMM_API_KEY o'rnatilmagan.")
    try:
        b = await asyncio.to_thread(smm_sorov, action="balance")
        n = await asyncio.to_thread(katalog_yukla)
    except Exception as e:
        return await message.answer(f"❌ Panelga ulanib bo'lmadi: {e}")
    await message.answer(
        f"💳 Panel balansi: {b.get('balance')} {b.get('currency', '')}\n"
        f"📦 Katalogda {n} ta xizmat yangilandi.\n💱 Kurs: {USD_KURS:g} so'm · Ustama: {USTAMA:g}%"
    )


# ---------- API HAMKORLIK (hamkorlar uchun veb-server) ----------

# Hamkorlarga narx = panel narxi + shu foiz (Railway Variables: HAMKOR_USTAMA)
HAMKOR_USTAMA = env_son("HAMKOR_USTAMA", 40)
MU = 1_000_000  # balans "mikro-dollar" ko'rinishida saqlanadi (suzuvchi nuqta xatosi bo'lmasligi uchun)

db.executescript("""
CREATE TABLE IF NOT EXISTS partners(
    id INTEGER PRIMARY KEY AUTOINCREMENT, nom TEXT, kalit_hash TEXT UNIQUE,
    balans_mu INTEGER DEFAULT 0, faol INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS partner_orders(
    id INTEGER PRIMARY KEY AUTOINCREMENT, pid INTEGER, sid INTEGER, havola TEXT, miqdor INTEGER,
    narx_mu INTEGER, qaytarildi_mu INTEGER DEFAULT 0, smm_id INTEGER,
    holat TEXT DEFAULT 'Pending', qolgan INTEGER DEFAULT 0, boshlash INTEGER DEFAULT 0);
""")

API_SOROVLAR = {}  # ip -> so'rov vaqtlari (tezlikni cheklash uchun)


def tezlik_oshdi(ip, limit=120):
    hozir = time.time()
    royxat = [t for t in API_SOROVLAR.get(ip, []) if hozir - t < 60]
    royxat.append(hozir)
    API_SOROVLAR[ip] = royxat
    if len(API_SOROVLAR) > 5000:  # xotira to'lib ketmasligi uchun
        API_SOROVLAR.clear()
    return len(royxat) > limit


def kalit_hash(kalit):
    return hashlib.sha256(kalit.encode()).hexdigest()


def hamkor_topish(kalit):
    if not kalit or len(kalit) > 100:
        return None
    return db.execute(
        "SELECT id, nom, balans_mu FROM partners WHERE kalit_hash=? AND faol=1", (kalit_hash(kalit),)
    ).fetchone()


def hamkor_narx(rate):
    return rate * (1 + HAMKOR_USTAMA / 100)


def holat_norm(st):
    st = str(st).strip().lower()
    if st == "completed":
        return "Completed"
    if st == "partial":
        return "Partial"
    if st in ("canceled", "cancelled", "refunded", "failed"):
        return "Canceled"
    if st == "pending":
        return "Pending"
    return "In progress"


async def admin_xabar(matn):
    with suppress(Exception):
        await bot.send_message(ADMIN_ID, matn)


def hamkor_qaytar(pid, oid, mu):
    if mu <= 0:
        return
    db.execute("UPDATE partners SET balans_mu=balans_mu+? WHERE id=?", (mu, pid))
    db.execute("UPDATE partner_orders SET qaytarildi_mu=qaytarildi_mu+? WHERE id=?", (mu, oid))
    db.commit()


async def api_v2(request):
    ip = (request.headers.get("X-Forwarded-For") or str(request.remote or "")).split(",")[0].strip()
    if tezlik_oshdi(ip):
        return web.json_response({"error": "Too many requests"}, status=429)
    data = {k: str(v) for k, v in request.query.items()}
    if request.method == "POST":
        try:
            data.update({k: str(v) for k, v in (await request.post()).items()})
        except Exception:
            return web.json_response({"error": "Bad request"}, status=400)
    h = hamkor_topish(data.get("key", ""))
    if not h:
        return web.json_response({"error": "Incorrect API key"})
    pid, _, balans_mu = h
    action = data.get("action", "")

    if action == "balance":
        return web.json_response({"balance": f"{balans_mu / MU:.5f}", "currency": "USD"})

    if action == "services":
        return web.json_response([
            {
                "service": sid, "name": s["name"], "type": "Default", "category": s["cat"],
                "rate": f"{hamkor_narx(s['rate']):.4f}", "min": str(s["mn"]), "max": str(s["mx"]),
                "refill": False, "cancel": False,
            }
            for sid, s in KESH["xizmat"].items()
        ])

    if action == "status":
        if not data.get("order", "").isdigit():
            return web.json_response({"error": "Incorrect order ID"})
        r = db.execute(
            "SELECT holat, narx_mu, qaytarildi_mu, qolgan, boshlash FROM partner_orders WHERE id=? AND pid=?",
            (int(data["order"]), pid),
        ).fetchone()
        if not r:
            return web.json_response({"error": "Incorrect order ID"})
        holat = r[0] if r[0] in ("Pending", "In progress", "Completed", "Partial", "Canceled") else "Pending"
        return web.json_response({
            "charge": f"{(r[1] - r[2]) / MU:.5f}", "start_count": str(r[4]), "status": holat,
            "remains": str(r[3]), "currency": "USD",
        })

    if action == "add":
        try:
            sid, qty = int(data.get("service", "")), int(data.get("quantity", ""))
        except ValueError:
            return web.json_response({"error": "Incorrect service ID or quantity"})
        s = KESH["xizmat"].get(sid)
        if not s:
            return web.json_response({"error": "Incorrect service ID"})
        link = data.get("link", "").strip()
        if len(link) > 300 or not re.match(r"(https?://|t\.me/|@)\S+$", link):
            return web.json_response({"error": "Incorrect link"})
        if not s["mn"] <= qty <= s["mx"]:
            return web.json_response({"error": "Incorrect quantity"})
        narx_mu = math.ceil(hamkor_narx(s["rate"]) * qty / 1000 * MU - 1e-9)
        if balans_mu < narx_mu:
            return web.json_response({"error": "Not enough funds on balance"})
        # Pulni yechish va buyurtmani yozish (orasida await yo'q, shuning uchun xavfsiz)
        db.execute("UPDATE partners SET balans_mu=balans_mu-? WHERE id=?", (narx_mu, pid))
        oid = db.execute(
            "INSERT INTO partner_orders(pid, sid, havola, miqdor, narx_mu) VALUES (?,?,?,?,?)",
            (pid, sid, link, qty, narx_mu),
        ).lastrowid
        db.commit()
        try:
            j = await asyncio.to_thread(
                smm_sorov, action="add", service=sid, link=smm_havola(link), quantity=qty
            )
        except Exception as e:
            logging.exception("Hamkor buyurtmasi: panelga ulanish xatosi")
            db.execute("UPDATE partner_orders SET holat='Tekshirish kerak' WHERE id=?", (oid,))
            db.commit()
            await admin_xabar(
                f"⚠️ Hamkor #{pid} buyurtmasi #{oid}: panelga ulanishda xato ({e}).\n"
                "Panelda buyurtma bor-yo'qligini tekshiring. Pul avtomatik qaytarilmadi."
            )
            return web.json_response({"error": f"Temporary error. Contact support, order {oid}"})
        if j.get("order"):
            db.execute("UPDATE partner_orders SET smm_id=? WHERE id=?", (int(j["order"]), oid))
            db.commit()
            return web.json_response({"order": oid})
        db.execute("UPDATE partner_orders SET holat='Canceled' WHERE id=?", (oid,))
        hamkor_qaytar(pid, oid, narx_mu)
        await admin_xabar(f"⚠️ Hamkor #{pid} buyurtmasini panel rad etdi: {j.get('error') or j}\nPul hamkorga qaytarildi.")
        return web.json_response({"error": "Service is temporarily unavailable"})

    return web.json_response({"error": "Incorrect action"})


async def partner_kuzat():
    """Hamkor buyurtmalari holatini panel bilan sinxronlaydi."""
    while True:
        await asyncio.sleep(60)
        try:
            qatorlar = db.execute(
                "SELECT id, pid, smm_id, narx_mu, miqdor, holat FROM partner_orders "
                "WHERE smm_id IS NOT NULL AND holat IN ('Pending','In progress')"
            ).fetchall()
            for oid, pid, sid, narx_mu, miqdor, eski in qatorlar:
                try:
                    j = await asyncio.to_thread(smm_sorov, action="status", order=sid)
                except Exception:
                    continue
                yangi = holat_norm(j.get("status", ""))
                try:
                    qolgan = int(float(j.get("remains") or 0))
                    boshlash = int(float(j.get("start_count") or 0))
                except ValueError:
                    qolgan, boshlash = 0, 0
                c = db.execute(
                    "UPDATE partner_orders SET holat=?, qolgan=?, boshlash=? "
                    "WHERE id=? AND holat IN ('Pending','In progress')",
                    (yangi, qolgan, boshlash, oid),
                )
                if c.rowcount == 0:
                    continue
                db.commit()
                if yangi == "Canceled":
                    hamkor_qaytar(pid, oid, narx_mu)
                elif yangi == "Partial" and miqdor:
                    hamkor_qaytar(pid, oid, min(narx_mu, round(narx_mu * qolgan / miqdor)))
        except Exception:
            logging.exception("Hamkor kuzatuvchisi xatosi")


async def api_ishga_tushir():
    port = int(os.getenv("PORT", "8080"))
    app = web.Application(client_max_size=65536)
    app.router.add_route("*", "/api/v2", api_v2)
    app.router.add_get("/", lambda r: web.Response(text="ok"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()
    logging.info("API server %s-portda ishga tushdi", port)


# Admin buyruqlari

def api_url():
    d = os.getenv("RAILWAY_PUBLIC_DOMAIN")
    return f"https://{d}/api/v2" if d else "(Railway → Settings → Networking → Generate Domain)"


@dp.message(Command("hamkor_qosh"), F.from_user.id == ADMIN_ID)
async def hamkor_qosh(message: types.Message):
    nom = (message.text or "").split(maxsplit=1)
    if len(nom) < 2:
        return await message.answer("Foydalanish: /hamkor_qosh Hamkor_nomi")
    kalit = secrets.token_urlsafe(24)
    pid = db.execute(
        "INSERT INTO partners(nom, kalit_hash) VALUES (?, ?)", (nom[1][:60], kalit_hash(kalit))
    ).lastrowid
    db.commit()
    await message.answer(
        f"✅ Hamkor #{pid} ({nom[1][:60]}) yaratildi.\n\n🔗 API URL:\n{api_url()}\n"
        f"🔑 API kalit (faqat hozir ko'rsatiladi, saqlab oling):\n{kalit}\n\n"
        f"Balans qo'shish: /hamkor_balans {pid} 10"
    )


@dp.message(Command("hamkor_balans"), F.from_user.id == ADMIN_ID)
async def hamkor_balans_qosh(message: types.Message):
    q = (message.text or "").split()
    try:
        pid, summa = int(q[1]), float(q[2].replace(",", "."))
    except (IndexError, ValueError):
        return await message.answer("Foydalanish: /hamkor_balans HAMKOR_ID DOLLAR\nMasalan: /hamkor_balans 1 10")
    if not db.execute("SELECT 1 FROM partners WHERE id=?", (pid,)).fetchone():
        return await message.answer("Bunday hamkor yo'q.")
    db.execute("UPDATE partners SET balans_mu=balans_mu+? WHERE id=?", (round(summa * MU), pid))
    db.commit()
    b = db.execute("SELECT balans_mu FROM partners WHERE id=?", (pid,)).fetchone()[0]
    await message.answer(f"✅ Hamkor #{pid} balansi: ${b / MU:.4f}")


@dp.message(Command("hamkorlar"), F.from_user.id == ADMIN_ID)
async def hamkorlar_royxati(message: types.Message):
    qatorlar = db.execute("SELECT id, nom, balans_mu, faol FROM partners ORDER BY id").fetchall()
    matn = "\n".join(
        f"#{i} {n} · ${b / MU:.4f} · {'faol' if f else 'o‘chirilgan'}" for i, n, b, f in qatorlar
    ) or "Hamkorlar yo'q."
    await message.answer(f"👥 Hamkorlar (ustama {HAMKOR_USTAMA:g}%):\n{matn}\n\n🔗 {api_url()}")


@dp.message(Command("hamkor_ochir"), F.from_user.id == ADMIN_ID)
async def hamkor_ochir(message: types.Message):
    q = (message.text or "").split()
    if len(q) < 2 or not q[1].isdigit():
        return await message.answer("Foydalanish: /hamkor_ochir HAMKOR_ID")
    db.execute("UPDATE partners SET faol=0 WHERE id=?", (int(q[1]),))
    db.commit()
    await message.answer(f"🚫 Hamkor #{q[1]} o'chirildi (kalit endi ishlamaydi).")


@dp.message(Command("hamkor_kalit"), F.from_user.id == ADMIN_ID)
async def hamkor_kalit(message: types.Message):
    q = (message.text or "").split()
    if len(q) < 2 or not q[1].isdigit():
        return await message.answer("Foydalanish: /hamkor_kalit HAMKOR_ID (yangi kalit yaratadi, eskisi bekor bo'ladi)")
    kalit = secrets.token_urlsafe(24)
    c = db.execute(
        "UPDATE partners SET kalit_hash=?, faol=1 WHERE id=?", (kalit_hash(kalit), int(q[1]))
    )
    db.commit()
    if c.rowcount == 0:
        return await message.answer("Bunday hamkor yo'q.")
    await message.answer(f"🔑 Hamkor #{q[1]} uchun yangi kalit:\n{kalit}")


# ---------- TELEGRAM STARS va PREMIUM (admin qo'lda yetkazadi) ----------

STAR_NARXI = env_son("STAR_NARXI", 300)  # 1 ta Stars narxi, so'mda (Railway Variables'da o'zgartiring)
STARS_MIN, STARS_MAX = 50, 10000
STARS_PAKET = [50, 100, 250, 500, 1000, 2500]
# Premium: oy -> narx (so'm). NAMUNA narxlar, o'zingiznikiga almashtiring!
PREMIUM_PAKET = {1: 60000, 3: 170000, 6: 230000, 12: 410000}


class Sotib(StatesGroup):
    miqdor = State()
    username = State()


def stars_narx(n):
    return round(n * STAR_NARXI)


@dp.message(F.text == "⭐ Stars hizmati")
async def stars_menyu(message: types.Message, state: FSMContext):
    await state.clear()
    tugmalar = [[(f"⭐ {n} — {pul(stars_narx(n))}", f"st:{n}")] for n in STARS_PAKET]
    tugmalar.append([("✍️ Boshqa miqdor", "st:custom")])
    await message.answer(
        f"⭐ Telegram Stars\n💰 1 ta Stars: {pul(STAR_NARXI)}\n\nPaketni tanlang:", reply_markup=ik(*tugmalar)
    )


@dp.message(F.text == "💎 Premium olish")
async def premium_menyu(message: types.Message, state: FSMContext):
    await state.clear()
    tugmalar = [[(f"💎 {oy} oy — {pul(narx)}", f"pr:{oy}")] for oy, narx in PREMIUM_PAKET.items()]
    await message.answer("💎 Telegram Premium\n\nMuddatni tanlang:", reply_markup=ik(*tugmalar))


async def username_sora(xabar, state, tur, nom, miqdor, narx):
    await state.set_state(Sotib.username)
    await state.update_data(tur=tur, nom=nom, miqdor=miqdor, narx=narx)
    await xabar.answer(
        f"{nom}\n💰 Narxi: {pul(narx)}\n\n"
        "👤 Qaysi akkauntga yuboramiz? Telegram username'ni yozing (masalan: @username):",
        reply_markup=bekor_menyu,
    )


@dp.callback_query(F.data.startswith("st:"))
async def stars_tanlandi(callback: types.CallbackQuery, state: FSMContext):
    qiymat = callback.data[3:]
    await state.clear()
    if qiymat == "custom":
        await state.set_state(Sotib.miqdor)
        await callback.message.answer(
            f"✍️ Nechta Stars kerak? ({STARS_MIN} – {STARS_MAX}):", reply_markup=bekor_menyu
        )
    else:
        n = int(qiymat)
        if n not in STARS_PAKET:
            return await callback.answer()
        await username_sora(callback.message, state, "Telegram Stars", f"⭐ {n} ta Stars", n, stars_narx(n))
    await callback.answer()


@dp.message(Sotib.miqdor, F.text)
async def stars_miqdor(message: types.Message, state: FSMContext):
    soni = message.text.replace(" ", "")
    if not soni.isdigit() or not STARS_MIN <= int(soni) <= STARS_MAX:
        return await message.answer(f"Miqdor {STARS_MIN} dan {STARS_MAX} gacha bo'lishi kerak.")
    n = int(soni)
    await username_sora(message, state, "Telegram Stars", f"⭐ {n} ta Stars", n, stars_narx(n))


@dp.callback_query(F.data.startswith("pr:"))
async def premium_tanlandi(callback: types.CallbackQuery, state: FSMContext):
    try:
        oy = int(callback.data[3:])
        narx = PREMIUM_PAKET[oy]
    except (ValueError, KeyError):
        return await callback.answer()
    await state.clear()
    await username_sora(callback.message, state, "Telegram Premium", f"💎 Premium {oy} oy", oy, narx)
    await callback.answer()


@dp.message(Sotib.username, F.text)
async def sotib_username(message: types.Message, state: FSMContext):
    u = message.text.strip()
    if not re.fullmatch(r"@?[A-Za-z0-9_]{5,32}", u):
        return await message.answer("Username noto'g'ri. Masalan: @username")
    u = "@" + u.lstrip("@")
    await state.update_data(uname=u)
    d = await state.get_data()
    await message.answer(
        f"🧾 Buyurtma:\n{d['nom']}\n👤 Qabul qiluvchi: {u}\n💰 Narxi: {pul(d['narx'])}\n"
        f"💳 Joriy hisob: {pul(balans(message.from_user.id))}",
        reply_markup=ik([("✅ Tasdiqlash", "sotib_tasdiq"), ("❌ Bekor qilish", "b_bekor")]),
    )


@dp.callback_query(F.data == "sotib_tasdiq")
async def sotib_tasdiq(callback: types.CallbackQuery, state: FSMContext):
    d = await state.get_data()
    uid = callback.from_user.id
    if "uname" not in d:
        return await callback.answer("Buyurtma eskirgan. Qaytadan boshlang.", show_alert=True)
    await state.clear()
    if balans(uid) < d["narx"]:
        await callback.message.edit_text(
            f"❌ Hisobingizda mablag' yetarli emas.\n💰 Narxi: {pul(d['narx'])}\n"
            f"💳 Joriy hisob: {pul(balans(uid))}\n\n«💵 Hisob to'ldirish» orqali hisobni to'ldiring."
        )
        return await callback.answer()
    balans_ozgar(uid, -d["narx"])
    oid = db.execute(
        "INSERT INTO orders(uid, platforma, xizmat, havola, miqdor, narx) VALUES (?,?,?,?,?,?)",
        (uid, d["tur"], d["nom"], d["uname"], d["miqdor"], d["narx"]),
    ).lastrowid
    db.commit()
    await callback.message.edit_text(
        "✅ Muvaffaqiyatli ro'yxatga olindi.\nBuyurtma bajarilganda sizga xabar yuboriladi.\n\n"
        f"🆔 Buyurtma raqami: {oid}\n{d['nom']}\n👤 Qabul qiluvchi: {d['uname']}\n"
        f"💰 Narxi: {pul(d['narx'])}\n💳 Joriy hisob: {pul(balans(uid))}"
    )
    await admin_xabar_tugmali(
        f"🛒 Yangi buyurtma #{oid}\n👤 {callback.from_user.full_name} (ID: {uid})\n"
        f"{d['nom']}\n👤 Qabul qiluvchi: {d['uname']}\n💰 {pul(d['narx'])}",
        ik([("✅ Bajarildi", f"ord:ok:{oid}"), ("🚫 Bekor qilish", f"ord:no:{oid}")]),
    )
    await callback.answer()


async def admin_xabar_tugmali(matn, markup):
    with suppress(Exception):
        await bot.send_message(ADMIN_ID, matn, reply_markup=markup)


# ---------- START / BEKOR ----------

@dp.message(Command("start"))
async def start(message: types.Message, state: FSMContext):
    await state.clear()
    qismlar = (message.text or "").split(maxsplit=1)
    if len(qismlar) > 1:
        await ref_qayd(message.from_user.id, qismlar[1].strip())
    balans(message.from_user.id)
    await message.answer(
        "👋 Assalomu alaykum!\n\nBotimizga xush kelibsiz.\nKerakli bo'limni tanlang:",
        reply_markup=menyu(message.from_user.id),
    )


@dp.message(StateFilter("*"), F.text == "Bekor qilish")
async def bekor(message: types.Message, state: FSMContext):
    holat = ((await state.get_state()) or "").split(":")[0]
    nomi = {
        "Zayafka": "Zayafka", "Musiqa": "Qidiruv", "Karta": "Karta qo'shish",
        "Buyurtma": "Buyurtma", "Sotib": "Buyurtma", "Tolov": "To'lov",
    }.get(holat, "Amal")
    await state.clear()
    await message.answer(f"❌ {nomi} bekor qilindi.", reply_markup=menyu(message.from_user.id))


# ---------- ASOSIY MENYU TUGMALARI (har biri avvalgi holatni tozalaydi) ----------

@dp.message(F.text == "Narxlar bilan tanishish")
async def narxlar(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(NARXLAR, reply_markup=menyu(message.from_user.id))


@dp.message(F.text == "💰 Mening hisobim")
async def hisobim(message: types.Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    n = db.execute("SELECT COUNT(*) FROM orders WHERE uid=?", (uid,)).fetchone()[0]
    await message.answer(
        f"👤 ID: {uid}\n💰 Joriy hisob: {pul(balans(uid))}\n🧾 Buyurtmalar soni: {n}\n"
        f"👥 Takliflar: {db.execute('SELECT COUNT(*) FROM users WHERE ref=?', (uid,)).fetchone()[0]} ta",
        reply_markup=menyu(uid),
    )


@dp.message(F.text == "🔎 Buyurtmalarim")
async def buyurtmalarim(message: types.Message, state: FSMContext):
    await state.clear()
    qatorlar = db.execute(
        "SELECT id, platforma, xizmat, miqdor, narx, holat FROM orders WHERE uid=? ORDER BY id DESC LIMIT 10",
        (message.from_user.id,),
    ).fetchall()
    matn = "\n\n".join(
        f"🆔 #{i}\n{p} — {x}\n➕ {m} ta · 💰 {pul(n)}\n📌 {h}" for i, p, x, m, n, h in qatorlar
    ) or "Sizda hali buyurtmalar yo'q."
    await message.answer(matn, reply_markup=menyu(message.from_user.id))


@dp.message(F.text == "🗂 Xizmatlarga buyurtma berish")
async def xizmatlar(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "✅ Bizning xizmatlarimizni tanlaganingizdan xursandmiz!\n"
        "👇 Quyidagi ijtimoiy tarmoqlardan birini tanlang.",
        reply_markup=smm_platformalar_kb() if KESH["plat_list"] else platforma_kb(),
    )


@dp.message(F.text == "💵 Hisob to'ldirish")
async def tolov_boshlash(message: types.Message, state: FSMContext):
    await state.clear()
    karta = karta_oqi()
    if not karta:
        return await message.answer("⚠️ To'lov kartasi hali kiritilmagan. Admin bilan bog'laning.")
    await state.set_state(Tolov.summa)
    await message.answer(
        f"💳 To'lov kartasi:\n{karta['raqam']}\n{karta['egasi']}\n\n"
        "💵 Qancha so'm o'tkazmoqchisiz? Summani yozing (kamida 1 000):",
        reply_markup=bekor_menyu,
    )


@dp.message(F.text == "Zayafka qoldirish")
async def zayafka_boshlash(message: types.Message, state: FSMContext):
    await state.clear()
    await state.set_state(Zayafka.platforma)
    await message.answer("📱 Qaysi platforma uchun xizmat kerak?", reply_markup=platforma_menyu)


@dp.message(F.text == "💳 Karta qo'shish", F.from_user.id == ADMIN_ID)
async def karta_boshlash(message: types.Message, state: FSMContext):
    await state.clear()
    await state.set_state(Karta.raqam)
    await message.answer("💳 Karta raqamini kiriting (16 ta raqam):", reply_markup=bekor_menyu)


@dp.message(F.text == "🎵 Musiqa qidirish")
async def musiqa_boshlash(message: types.Message, state: FSMContext):
    await state.clear()
    await state.set_state(Musiqa.nom)
    await message.answer("🎵 Qo'shiq yoki ijrochi nomini yozing:", reply_markup=bekor_menyu)


# ---------- BUYURTMA (inline tanlov) ----------

@dp.callback_query(F.data.startswith("p:"))
async def platforma_tanlandi(callback: types.CallbackQuery):
    p = callback.data[2:]
    if p not in KATALOG:
        return await callback.answer()
    tugmalar = [
        [(f"{x} — {pul(n)}/1000", f"x:{p}:{i}")] for i, (x, n) in enumerate(KATALOG[p].items())
    ]
    tugmalar.append([("⬅️ Ortga", "ortga")])
    await callback.message.edit_text(f"📱 {p} xizmatlari:", reply_markup=ik(*tugmalar))
    await callback.answer()


@dp.callback_query(F.data == "ortga")
async def ortga(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "👇 Quyidagi ijtimoiy tarmoqlardan birini tanlang.", reply_markup=platforma_kb()
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("x:"))
async def xizmat_tanlandi(callback: types.CallbackQuery, state: FSMContext):
    _, p, i = callback.data.split(":")
    x = list(KATALOG[p])[int(i)]
    await state.clear()
    await state.set_state(Buyurtma.havola)
    await state.update_data(
        p=p, x=x, sid=SMM_XIZMAT.get((p, x)), narx1000=KATALOG[p][x], mn=MIN_MIQDOR, mx=MAX_MIQDOR
    )
    await callback.message.answer(
        f"{p} — {x}\n💰 Narxi: {pul(KATALOG[p][x])} / 1000 ta\n\n📎 Havolani (link) yuboring:",
        reply_markup=bekor_menyu,
    )
    await callback.answer()


@dp.message(Buyurtma.havola, F.text)
async def havola_qabul(message: types.Message, state: FSMContext):
    havola = message.text.strip()
    if not re.match(r"(https?://|t\.me/|@)\S+$", havola):
        return await message.answer("Iltimos, to'g'ri havola yuboring (masalan: https://t.me/kanal).")
    await state.update_data(havola=havola)
    d = await state.get_data()
    await state.set_state(Buyurtma.miqdor)
    await message.answer(
        f"➕ Miqdorni kiriting ({d.get('mn', MIN_MIQDOR)} – {d.get('mx', MAX_MIQDOR)}):", reply_markup=bekor_menyu
    )


@dp.message(Buyurtma.miqdor, F.text)
async def miqdor_qabul(message: types.Message, state: FSMContext):
    d = await state.get_data()
    mn, mx = d.get("mn", MIN_MIQDOR), d.get("mx", MAX_MIQDOR)
    soni = message.text.replace(" ", "")
    if not soni.isdigit() or not mn <= int(soni) <= mx:
        return await message.answer(f"Miqdor {mn} dan {mx} gacha bo'lishi kerak.")
    n = int(soni)
    narx = max(1, round(n * d["narx1000"] / 1000))
    await state.update_data(miqdor=n, narx=narx)
    await message.answer(
        f"🧾 Buyurtma:\n📱 {d['p']} — {d['x']}\n📎 {d['havola']}\n➕ Miqdor: {n} ta\n"
        f"💰 Narxi: {pul(narx)}\n💳 Joriy hisob: {pul(balans(message.from_user.id))}",
        reply_markup=ik([("✅ Tasdiqlash", "tasdiq"), ("❌ Bekor qilish", "b_bekor")]),
    )


@dp.callback_query(F.data == "b_bekor")
async def buyurtma_bekor(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Buyurtma bekor qilindi.")
    await callback.message.answer("Bosh menyu:", reply_markup=menyu(callback.from_user.id))
    await callback.answer()


@dp.callback_query(F.data == "tasdiq")
async def buyurtma_tasdiq(callback: types.CallbackQuery, state: FSMContext):
    d = await state.get_data()
    uid = callback.from_user.id
    if "narx" not in d:
        await callback.answer("Buyurtma eskirgan. Qaytadan boshlang.", show_alert=True)
        return
    await state.clear()

    if balans(uid) < d["narx"]:
        await callback.message.edit_text(
            f"❌ Hisobingizda mablag' yetarli emas.\n💰 Narxi: {pul(d['narx'])}\n"
            f"💳 Joriy hisob: {pul(balans(uid))}\n\n«💵 Hisob to'ldirish» orqali hisobni to'ldiring."
        )
        return await callback.answer()

    balans_ozgar(uid, -d["narx"])
    oid = db.execute(
        "INSERT INTO orders(uid, platforma, xizmat, havola, miqdor, narx) VALUES (?,?,?,?,?,?)",
        (uid, d["p"], d["x"], d["havola"], d["miqdor"], d["narx"]),
    ).lastrowid
    db.commit()

    await callback.message.edit_text(
        "✅ Muvaffaqiyatli ro'yxatga olindi.\nBuyurtma bajarilganda sizga xabar yuboriladi.\n\n"
        f"🆔 Buyurtma raqami: {oid}\n📱 {d['p']} — {d['x']}\n📎 Havola: {d['havola']}\n"
        f"➕ Miqdor: {d['miqdor']} ta\n💰 Narxi: {pul(d['narx'])}\n💳 Joriy hisob: {pul(balans(uid))}"
    )
    holat, info = await smm_yubor(d.get("sid"), d["havola"], d["miqdor"])
    tafsilot = (
        f"🛒 Yangi buyurtma #{oid}\n👤 {callback.from_user.full_name} (ID: {uid})\n"
        f"📱 {d['p']} — {d['x']}\n📎 {d['havola']}\n➕ {d['miqdor']} ta\n💰 {pul(d['narx'])}"
    )
    tugmalar = ik([("✅ Bajarildi", f"ord:ok:{oid}"), ("🚫 Bekor qilish", f"ord:no:{oid}")])
    if holat == "ok":
        db.execute("UPDATE orders SET smm_id=? WHERE id=?", (info, oid))
        db.commit()
        with suppress(Exception):
            await bot.send_message(ADMIN_ID, f"{tafsilot}\n\n🤖 Panelga yuborildi (panel #{info})")
    elif holat == "xato":
        buyurtma_yop(oid, "Bekor qilindi", d["narx"])
        with suppress(Exception):
            await bot.send_message(
                uid, f"🚫 #{oid}-buyurtma bajarilmadi. {pul(d['narx'])} hisobingizga qaytarildi."
            )
        with suppress(Exception):
            await bot.send_message(ADMIN_ID, f"{tafsilot}\n\n⚠️ Panel xatosi: {info}\nPul qaytarildi.")
    elif holat == "noaniq":
        with suppress(Exception):
            await bot.send_message(
                ADMIN_ID,
                f"{tafsilot}\n\n⚠️ Panelga ulanishda xato: {info}\n"
                "Panelda buyurtma bor-yo'qligini tekshiring, so'ng tugmani bosing.",
                reply_markup=tugmalar,
            )
    else:
        with suppress(Exception):
            await bot.send_message(ADMIN_ID, tafsilot, reply_markup=tugmalar)
    await callback.answer()


@dp.callback_query(F.data.startswith("ord:"), F.from_user.id == ADMIN_ID)
async def buyurtma_holat(callback: types.CallbackQuery):
    _, amal, oid = callback.data.split(":")
    qator = db.execute("SELECT uid, narx, holat FROM orders WHERE id=?", (oid,)).fetchone()
    if not qator or qator[2] != "Jarayonda":
        return await callback.answer("Bu buyurtma allaqachon ko'rib chiqilgan.", show_alert=True)
    uid, narx, _ = qator
    if amal == "ok":
        yangi, matn = "Bajarildi", f"✅ #{oid}-buyurtmangiz bajarildi!"
    else:
        yangi = "Bekor qilindi"
        matn = f"🚫 #{oid}-buyurtmangiz bekor qilindi. {pul(narx)} hisobingizga qaytarildi."
        balans_ozgar(uid, narx)
    db.execute("UPDATE orders SET holat=? WHERE id=?", (yangi, oid))
    db.commit()
    await callback.message.edit_text(f"{callback.message.text}\n\n📌 Holat: {yangi}")
    with suppress(Exception):
        await bot.send_message(uid, matn)
    await callback.answer()


# ---------- HISOB TO'LDIRISH ----------

@dp.message(Tolov.summa, F.text)
async def tolov_summa(message: types.Message, state: FSMContext):
    soni = message.text.replace(" ", "")
    if not soni.isdigit() or int(soni) < 1000:
        return await message.answer("Summa kamida 1 000 so'm bo'lishi kerak. Faqat raqam yozing.")
    await state.update_data(summa=int(soni))
    await state.set_state(Tolov.chek)
    await message.answer(
        "📸 Pulni karta raqamiga o'tkazing va to'lov chekini (skrinshot) rasm qilib yuboring.",
        reply_markup=bekor_menyu,
    )


@dp.message(Tolov.chek, F.photo)
async def tolov_chek(message: types.Message, state: FSMContext):
    d = await state.get_data()
    await state.clear()
    uid = message.from_user.id
    tid = db.execute("INSERT INTO topups(uid, summa) VALUES (?,?)", (uid, d["summa"])).lastrowid
    db.commit()
    await bot.send_photo(
        ADMIN_ID,
        message.photo[-1].file_id,
        caption=f"💵 Yangi to'lov #{tid}\n👤 {message.from_user.full_name} (ID: {uid})\n💰 {pul(d['summa'])}",
        reply_markup=ik([("✅ Tasdiqlash", f"tp:ok:{tid}"), ("❌ Rad etish", f"tp:no:{tid}")]),
    )
    await message.answer(
        "✅ Chek yuborildi. Admin tasdiqlagach hisobingiz to'ldiriladi.", reply_markup=menyu(uid)
    )


@dp.message(Tolov.chek)
async def tolov_chek_xato(message: types.Message):
    await message.answer("Iltimos, chekni rasm (skrinshot) sifatida yuboring.")


@dp.callback_query(F.data.startswith("tp:"), F.from_user.id == ADMIN_ID)
async def tolov_holat(callback: types.CallbackQuery):
    _, amal, tid = callback.data.split(":")
    qator = db.execute("SELECT uid, summa, holat FROM topups WHERE id=?", (tid,)).fetchone()
    if not qator or qator[2] != "kutilmoqda":
        return await callback.answer("Bu to'lov allaqachon ko'rib chiqilgan.", show_alert=True)
    uid, summa, _ = qator
    if amal == "ok":
        balans_ozgar(uid, summa)
        yangi = "tasdiqlandi"
        matn = f"✅ Hisobingiz {pul(summa)} ga to'ldirildi.\n💰 Joriy hisob: {pul(balans(uid))}"
    else:
        yangi = "rad etildi"
        matn = "❌ To'lovingiz tasdiqlanmadi. Savol bo'lsa admin bilan bog'laning."
    db.execute("UPDATE topups SET holat=? WHERE id=?", (yangi, tid))
    db.commit()
    await callback.message.edit_caption(caption=f"{callback.message.caption}\n\n📌 {yangi}")
    with suppress(Exception):
        await bot.send_message(uid, matn)
    await callback.answer()


# ---------- ZAYAFKA ----------

@dp.message(Zayafka.platforma, F.text)
async def platforma_tanlash(message: types.Message, state: FSMContext):
    if message.text not in PLATFORMALAR:
        return await message.answer("Iltimos, menyudagi platformalardan birini tanlang.")
    await state.update_data(platforma=message.text)
    await state.set_state(Zayafka.ism)
    await message.answer("👤 Ismingizni kiriting:", reply_markup=bekor_menyu)


@dp.message(Zayafka.ism, F.text)
async def ism_qabul(message: types.Message, state: FSMContext):
    ism = message.text.strip()
    if len(ism) < 2:
        return await message.answer("Iltimos, ismingizni to'g'ri kiriting.")
    await state.update_data(ism=ism)
    await state.set_state(Zayafka.telefon)
    await message.answer(
        "📞 Telefon raqamingizni kiriting:\nMasalan: +998901234567", reply_markup=bekor_menyu
    )


@dp.message(Zayafka.telefon, F.text)
async def telefon_qabul(message: types.Message, state: FSMContext):
    telefon = message.text.strip()
    if not re.fullmatch(r"\+?\d{9,15}", re.sub(r"[\s\-()]", "", telefon)):
        return await message.answer("Telefon raqamini to'g'ri kiriting.\nMasalan: +998901234567")

    data = await state.get_data()
    await state.clear()
    platforma = data["platforma"]

    try:
        await bot.send_message(
            ADMIN_ID,
            "🔔 Yangi zayafka!\n\n"
            f"👤 Ism: {data['ism']}\n📞 Telefon: {telefon}\n"
            f"📱 Platforma: {platforma}\n💰 Narx: {PLATFORMALAR[platforma]}",
        )
        matn = "✅ Zayavkangiz qabul qilindi!\n\nTez orada siz bilan bog'lanamiz."
        karta = karta_oqi()
        if karta:
            matn += f"\n\n💳 To'lov kartasi:\n{karta['raqam']}\n{karta['egasi']}"
    except Exception:
        matn = "⚠️ Zayavkani yuborishda xatolik yuz berdi. Keyinroq urinib ko'ring."

    await message.answer(matn, reply_markup=menyu(message.from_user.id))


# ---------- KARTA QO'SHISH (faqat admin) ----------

@dp.message(Karta.raqam, F.text)
async def karta_raqam(message: types.Message, state: FSMContext):
    raqam = re.sub(r"\D", "", message.text)
    if len(raqam) != 16:
        return await message.answer("Karta raqami 16 ta raqamdan iborat bo'lishi kerak.")
    await state.update_data(raqam=" ".join(raqam[i:i + 4] for i in range(0, 16, 4)))
    await state.set_state(Karta.egasi)
    await message.answer("👤 Karta egasining ism-familiyasini kiriting:", reply_markup=bekor_menyu)


@dp.message(Karta.egasi, F.text)
async def karta_egasi(message: types.Message, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    with open(KARTA_FAYL, "w", encoding="utf-8") as f:
        json.dump({"raqam": data["raqam"], "egasi": message.text.strip()}, f, ensure_ascii=False)
    await message.answer(
        f"✅ Karta saqlandi:\n{data['raqam']}\n{message.text.strip()}",
        reply_markup=menyu(message.from_user.id),
    )


# ---------- MUSIQA ----------

@dp.message(Musiqa.nom, F.text)
async def musiqa_qidirish(message: types.Message, state: FSMContext):
    soz = message.text.strip()
    if not soz:
        return await message.answer("Qo'shiq nomini yozing.")

    await message.answer("🔎 Qidiryapman, biroz kuting...")
    try:
        natijalar = await asyncio.to_thread(qidir, soz)
    except Exception:
        logging.exception("Qidiruv xatosi")
        return await message.answer("❌ Qidirishda xatolik yuz berdi.\nKeyinroq qayta urinib ko'ring.")

    await state.clear()
    if not natijalar:
        return await message.answer(
            "😔 Hech qanday natija topilmadi.", reply_markup=menyu(message.from_user.id)
        )

    tugmalar = [[(f"🎵 {t[:45]}", f"music:{vid}")] for vid, t in natijalar]
    tugmalar.append([("❌ Bekor qilish", "music_cancel")])
    await message.answer("🎶 Natijalardan birini tanlang:", reply_markup=ik(*tugmalar))


@dp.callback_query(F.data.startswith("music:"))
async def musiqa_yuklash(callback: types.CallbackQuery):
    await callback.answer("Yuklanmoqda...")
    await callback.message.edit_text("⏳ Musiqa yuklanmoqda. Biroz kuting...")

    papka = tempfile.mkdtemp(prefix="music_")
    try:
        fayl, title = await asyncio.to_thread(yukla, callback.data.split(":", 1)[1], papka)
        await callback.message.answer_audio(
            audio=FSInputFile(fayl), title=title[:64], caption=f"🎵 {title}"
        )
        with suppress(Exception):
            await callback.message.delete()
    except Exception:
        logging.exception("Yuklash xatosi")
        await callback.message.answer(
            "❌ Musiqani yuklab bo'lmadi. YouTube server IP sini bloklagan bo'lishi mumkin.\n"
            "Boshqa natijani sinab ko'ring yoki birozdan keyin urinib ko'ring."
        )
    finally:
        shutil.rmtree(papka, ignore_errors=True)


@dp.callback_query(F.data == "music_cancel")
async def musiqa_callback_bekor(callback: types.CallbackQuery):
    await callback.answer("Bekor qilindi.")
    await callback.message.edit_text("❌ Musiqa qidirish bekor qilindi.")


# ---------- ISHGA TUSHIRISH ----------

async def main():
    print("Bot ishga tushdi...")
    dp.message.outer_middleware(ObunaMW())
    dp.callback_query.outer_middleware(ObunaMW())
    if SMM_API_URL and SMM_API_KEY:
        asyncio.create_task(smm_kuzat())
        asyncio.create_task(katalog_yangila())
        asyncio.create_task(partner_kuzat())
        if os.getenv("PORT"):
            await api_ishga_tushir()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
