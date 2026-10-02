import asyncio
import json
import os
import re
import shutil
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

API_TOKEN = os.environ["BOT_TOKEN"]  # tokenni kodga yozmang, muhit o'zgaruvchisidan oling
ADMIN_ID = int(os.getenv("ADMIN_ID", "8756103290"))
KARTA_FAYL = "karta.json"

bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

PLATFORMALAR = {
    "Instagram": "1000 ta obunachi: 15 000 so'm",
    "YouTube": "1000 ta obunachi: 50 000 so'm",
    "TikTok": "1000 ta obunachi: 20 000 so'm",
    "Telegram": "1000 ta obunachi: 10 000 so'm",
}
NARXLAR = "💰 Xizmatlarimiz narxi:\n\n" + "\n".join(
    f"• {nom}: {narx}" for nom, narx in PLATFORMALAR.items()
)
nomlar = list(PLATFORMALAR)


def kb(*rows):
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t) for t in r] for r in rows],
        resize_keyboard=True,
    )


def menyu(uid):
    rows = [["Zayafka qoldirish"], ["Narxlar bilan tanishish"], ["🎵 Musiqa qidirish"]]
    if uid == ADMIN_ID:
        rows.append(["💳 Karta qo'shish"])
    return kb(*rows)


platforma_menyu = kb(nomlar[:2], nomlar[2:], ["Bekor qilish"])
bekor_menyu = kb(["Bekor qilish"])


class Zayafka(StatesGroup):
    platforma = State()
    ism = State()
    telefon = State()


class Musiqa(StatesGroup):
    nom = State()


class Karta(StatesGroup):
    raqam = State()
    egasi = State()


def karta_oqi():
    try:
        with open(KARTA_FAYL, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


# ---------- MUSIQA FUNKSIYALARI ----------

def qidir(soz):
    opts = {"quiet": True, "extract_flat": True, "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch5:{soz}", download=False)
    return [
        (e["id"], e.get("title") or "Nomsiz")
        for e in (info.get("entries") or [])
        if e and e.get("id")
    ]


def yukla(video_id, papka):
    opts = {
        "format": "bestaudio[ext=m4a]/bestaudio",
        "outtmpl": os.path.join(papka, "%(id)s.%(ext)s"),
        "quiet": True,
        "noplaylist": True,
        "max_filesize": 48 * 1024 * 1024,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(
            f"https://www.youtube.com/watch?v={video_id}", download=True
        )
    fayllar = os.listdir(papka)
    if not fayllar:
        raise FileNotFoundError("Audio fayl topilmadi.")
    return os.path.join(papka, fayllar[0]), info.get("title") or "Nomsiz"


# ---------- START / BEKOR / NARXLAR ----------

@dp.message(Command("start"))
async def start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "👋 Assalomu alaykum!\n\nBotimizga xush kelibsiz.\nKerakli bo'limni tanlang:",
        reply_markup=menyu(message.from_user.id),
    )


@dp.message(StateFilter("*"), F.text == "Bekor qilish")
async def bekor(message: types.Message, state: FSMContext):
    holat = ((await state.get_state()) or "").split(":")[0]
    nomi = {"Zayafka": "Zayafka", "Musiqa": "Qidiruv", "Karta": "Karta qo'shish"}.get(holat, "Amal")
    await state.clear()
    await message.answer(f"❌ {nomi} bekor qilindi.", reply_markup=menyu(message.from_user.id))


@dp.message(F.text == "Narxlar bilan tanishish")
async def narxlar(message: types.Message):
    await message.answer(NARXLAR, reply_markup=menyu(message.from_user.id))


# ---------- ZAYAFKA ----------

@dp.message(F.text == "Zayafka qoldirish")
async def zayafka_boshlash(message: types.Message, state: FSMContext):
    await state.set_state(Zayafka.platforma)
    await message.answer("📱 Qaysi platforma uchun xizmat kerak?", reply_markup=platforma_menyu)


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
        "📞 Telefon raqamingizni kiriting:\nMasalan: +998901234567",
        reply_markup=bekor_menyu,
    )


@dp.message(Zayafka.telefon, F.text)
async def telefon_qabul(message: types.Message, state: FSMContext):
    telefon = message.text.strip()
    if not re.fullmatch(r"\+?\d{9,15}", re.sub(r"[\s\-()]", "", telefon)):
        return await message.answer(
            "Telefon raqamini to'g'ri kiriting.\nMasalan: +998901234567"
        )

    data = await state.get_data()
    await state.clear()
    platforma = data["platforma"]

    try:
        await bot.send_message(
            ADMIN_ID,
            "🔔 Yangi zayafka!\n\n"
            f"👤 Ism: {data['ism']}\n"
            f"📞 Telefon: {telefon}\n"
            f"📱 Platforma: {platforma}\n"
            f"💰 Narx: {PLATFORMALAR[platforma]}",
        )
        matn = "✅ Zayavkangiz qabul qilindi!\n\nTez orada siz bilan bog'lanamiz."
        karta = karta_oqi()
        if karta:
            matn += f"\n\n💳 To'lov kartasi:\n{karta['raqam']}\n{karta['egasi']}"
    except Exception:
        matn = "⚠️ Zayavkani yuborishda xatolik yuz berdi. Keyinroq urinib ko'ring."

    await message.answer(matn, reply_markup=menyu(message.from_user.id))


# ---------- KARTA QO'SHISH (faqat admin) ----------

@dp.message(F.text == "💳 Karta qo'shish", F.from_user.id == ADMIN_ID)
async def karta_boshlash(message: types.Message, state: FSMContext):
    await state.set_state(Karta.raqam)
    await message.answer("💳 Karta raqamini kiriting (16 ta raqam):", reply_markup=bekor_menyu)


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


# ---------- MUSIQA QIDIRISH ----------

@dp.message(F.text == "🎵 Musiqa qidirish")
async def musiqa_boshlash(message: types.Message, state: FSMContext):
    await state.set_state(Musiqa.nom)
    await message.answer("🎵 Qo'shiq yoki ijrochi nomini yozing:", reply_markup=bekor_menyu)


@dp.message(Musiqa.nom, F.text)
async def musiqa_qidirish(message: types.Message, state: FSMContext):
    soz = message.text.strip()
    if not soz:
        return await message.answer("Qo'shiq nomini yozing.")

    await message.answer("🔎 Qidiryapman, biroz kuting...")

    try:
        natijalar = await asyncio.to_thread(qidir, soz)
    except Exception:
        return await message.answer("❌ Qidirishda xatolik yuz berdi.\nKeyinroq qayta urinib ko'ring.")

    await state.clear()

    if not natijalar:
        return await message.answer(
            "😔 Hech qanday natija topilmadi.", reply_markup=menyu(message.from_user.id)
        )

    tugmalar = [
        [InlineKeyboardButton(text=f"🎵 {t[:45]}", callback_data=f"music:{vid}")]
        for vid, t in natijalar
    ]
    tugmalar.append([InlineKeyboardButton(text="❌ Bekor qilish", callback_data="music_cancel")])

    await message.answer(
        "🎶 Natijalardan birini tanlang:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=tugmalar),
    )


@dp.callback_query(F.data.startswith("music:"))
async def musiqa_yuklash(callback: types.CallbackQuery):
    await callback.answer("Yuklanmoqda...")
    await callback.message.edit_text("⏳ Musiqa yuklanmoqda. Biroz kuting...")

    papka = tempfile.mkdtemp(prefix="music_")
    try:
        fayl, title = await asyncio.to_thread(
            yukla, callback.data.split(":", 1)[1], papka
        )
        await callback.message.answer_audio(
            audio=FSInputFile(fayl), title=title[:64], caption=f"🎵 {title}"
        )
        with suppress(Exception):
            await callback.message.delete()
    except Exception:
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
