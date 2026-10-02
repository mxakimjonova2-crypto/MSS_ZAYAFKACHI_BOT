import asyncio
import json
import logging
import os
import re
import shutil
import sqlite3
import tempfile
from contextlib import suppress

import yt_dlp
from aiogram import Bot, Dispatcher, F, types
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

API_TOKEN = "8656378230:AAEleplFidTjbHqYUT6bc2s9BTCK-8gHAqE" # tokenni kodga yozmang
ADMIN_ID =  8756103290
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
        ["🗂 Xizmatlarga buyurtma berish"],
        ["💰 Mening hisobim", "🔎 Buyurtmalarim"],
        ["💵 Hisob to'ldirish", "Narxlar bilan tanishish"],
        ["Zayafka qoldirish", "🎵 Musiqa qidirish"],
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

BASLIQ = {}  # video_id -> nom (YouTube yuklanmasa SoundCloud'dan qidirish uchun)


def qidir(soz):
    opts = {"quiet": True, "extract_flat": True, "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch5:{soz}", download=False)
    natija = [
        (e["id"], e.get("title") or "Nomsiz")
        for e in (info.get("entries") or [])
        if e and e.get("id")
    ]
    BASLIQ.update(natija)
    return natija


def yukla(video_id, papka):
    opts = {
        "format": "bestaudio[ext=m4a]/bestaudio",
        "outtmpl": os.path.join(papka, "%(id)s.%(ext)s"),
        "quiet": True,
        "noplaylist": True,
        "max_filesize": 48 * 1024 * 1024,
    }
    nom = BASLIQ.get(video_id, "")
    manbalar = [f"https://www.youtube.com/watch?v={video_id}"]
    if nom:
        manbalar.append(f"scsearch1:{nom}")  # zaxira: SoundCloud
    for manba in manbalar:
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(manba, download=True)
            info = (info.get("entries") or [info])[0]
            fayllar = os.listdir(papka)
            if fayllar:
                return os.path.join(papka, fayllar[0]), info.get("title") or nom or "Nomsiz"
        except Exception as e:
            logging.warning("Yuklash xatosi (%s): %s", manba, e)
    raise FileNotFoundError("Audio fayl topilmadi.")


# ---------- START / BEKOR ----------

@dp.message(Command("start"))
async def start(message: types.Message, state: FSMContext):
    await state.clear()
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
        "Buyurtma": "Buyurtma", "Tolov": "To'lov",
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
        f"👤 ID: {uid}\n💰 Joriy hisob: {pul(balans(uid))}\n🧾 Buyurtmalar soni: {n}",
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
        reply_markup=platforma_kb(),
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
    await state.update_data(p=p, x=x)
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
    await state.set_state(Buyurtma.miqdor)
    await message.answer(f"➕ Miqdorni kiriting ({MIN_MIQDOR} – {MAX_MIQDOR}):", reply_markup=bekor_menyu)


@dp.message(Buyurtma.miqdor, F.text)
async def miqdor_qabul(message: types.Message, state: FSMContext):
    soni = message.text.replace(" ", "")
    if not soni.isdigit() or not MIN_MIQDOR <= int(soni) <= MAX_MIQDOR:
        return await message.answer(f"Miqdor {MIN_MIQDOR} dan {MAX_MIQDOR} gacha bo'lishi kerak.")
    n = int(soni)
    d = await state.get_data()
    narx = round(n * KATALOG[d["p"]][d["x"]] / 1000)
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
    with suppress(Exception):
        await bot.send_message(
            ADMIN_ID,
            f"🛒 Yangi buyurtma #{oid}\n👤 {callback.from_user.full_name} (ID: {uid})\n"
            f"📱 {d['p']} — {d['x']}\n📎 {d['havola']}\n➕ {d['miqdor']} ta\n💰 {pul(d['narx'])}",
            reply_markup=ik([("✅ Bajarildi", f"ord:ok:{oid}"), ("🚫 Bekor qilish", f"ord:no:{oid}")]),
        )
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
            "❌ Musiqani yuklashda xatolik yuz berdi.\nBoshqa natijani tanlab ko'ring."
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
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
