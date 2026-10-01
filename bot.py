import asyncio
import os
import re
import tempfile
import logging

import yt_dlp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile,
)
from dotenv import load_dotenv

load_dotenv()

# ---------- Sozlamalar ----------
API_TOKEN = 8656378230:AAEK7Htv-jAIOn3ItzcLJ4lGUHoT8n07_BI
ADMIN_ID = 8756103290

if not API_TOKEN:
    raise ValueError("BOT_TOKEN topilmadi! .env faylini tekshiring.")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

PLATFORMALAR = {
    "Instagram": "1000 ta obunachi: 15 000 so'm",
    "YouTube": "1000 ta obunachi: 50 000 so'm",
    "TikTok": "1000 ta obunachi: 20 000 so'm",
    "Telegram": "1000 ta obunachi: 10 000 so'm",
}

NARXLAR = "Xizmatlarimiz narxi:\n\n" + "\n".join(
    f"• {nom}: {narx}" for nom, narx in PLATFORMALAR.items()
)

# ---------- Klaviaturalar ----------
asosiy_menyu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📝 Zayafka qoldirish")],
        [KeyboardButton(text="💰 Narxlar bilan tanishish")],
        [KeyboardButton(text="🎵 Musiqa qidirish")],
    ],
    resize_keyboard=True,
)

nomlar = list(PLATFORMALAR.keys())
platforma_menyu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=nomlar[0]), KeyboardButton(text=nomlar[1])],
        [KeyboardButton(text=nomlar[2]), KeyboardButton(text=nomlar[3])],
        [KeyboardButton(text="❌ Bekor qilish")],
    ],
    resize_keyboard=True,
)

bekor_menyu = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="❌ Bekor qilish")]],
    resize_keyboard=True,
)


# ---------- States ----------
class Zayafka(StatesGroup):
    platforma = State()
    ism = State()
    telefon = State()


class Musiqa(StatesGroup):
    nom = State()


# ---------- Musiqa funksiyalari ----------
def qidir(soz: str):
    opts = {
        "quiet": True,
        "extract_flat": True,
        "skip_download": True,
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch5:{soz}", download=False)
    return [(e["id"], e.get("title", "Nomsiz")) for e in info.get("entries", []) if e]


def yukla(video_id: str, papka: str):
    opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(papka, "%(id)s.%(ext)s"),
        "quiet": True,
        "noplaylist": True,
        "max_filesize": 48 * 1024 * 1024,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(
            f"https://www.youtube.com/watch?v={video_id}", download=True
        )
        fayl = ydl.prepare_filename(info)
        mp3_fayl = os.path.splitext(fayl)[0] + ".mp3"
        return mp3_fayl if os.path.exists(mp3_fayl) else fayl, info.get("title", "Musiqa")


# ---------- Umumiy handlerlar ----------
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Assalomu alaykum! Xush kelibsiz 👋\nQuyidagilardan birini tanlang:",
        reply_markup=asosiy_menyu,
    )


@dp.message(F.text.in_(["❌ Bekor qilish", "Bekor qilish"]))
async def bekor(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Bekor qilindi ✅", reply_markup=asosiy_menyu)


@dp.message(F.text.in_(["💰 Narxlar bilan tanishish", "Narxlar bilan tanishish"]))
async def show_prices(message: types.Message):
    await message.answer(NARXLAR)


# ---------- Musiqa ----------
@dp.message(F.text.in_(["🎵 Musiqa qidirish", "Musiqa qidirish"]))
async def musiqa_boshla(message: types.Message, state: FSMContext):
    await message.answer(
        "Qo‘shiq yoki ijrochi nomini yozing:",
        reply_markup=bekor_menyu,
    )
    await state.set_state(Musiqa.nom)


@dp.message(Musiqa.nom)
async def musiqa_qidir(message: types.Message, state: FSMContext):
    kutish = await message.answer("🔍 Qidirilmoqda...")
    try:
        natija = await asyncio.to_thread(qidir, message.text.strip())
    except Exception as e:
        logger.error(f"Qidiruv xatosi: {e}")
        await kutish.edit_text("Xatolik chiqdi. Keyinroq urinib ko‘ring.")
        await state.clear()
        return

    if not natija:
        await kutish.edit_text("Hech narsa topilmadi 😔")
        await state.clear()
        return

    tugmalar = [
        [InlineKeyboardButton(text=f"{i}. {nom[:55]}", callback_data=f"m:{vid}")]
        for i, (vid, nom) in enumerate(natija, 1)
    ]
    await kutish.edit_text(
        "Natijalar, birini tanlang:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=tugmalar),
    )
    await state.clear()
    await message.answer("Menyuga qaytdingiz.", reply_markup=asosiy_menyu)


@dp.callback_query(F.data.startswith("m:"))
async def musiqa_yukla(call: types.CallbackQuery):
    vid = call.data[2:]
    await call.answer("Yuklanmoqda...")
    kutish = await call.message.answer("⏳ Yuklanmoqda, biroz kuting...")

    with tempfile.TemporaryDirectory() as papka:
        try:
            fayl, nom = await asyncio.to_thread(yukla, vid, papka)
            await call.message.answer_audio(
                FSInputFile(fayl),
                title=nom,
                caption=f"🎵 {nom}"
            )
        except Exception as e:
            logger.error(f"Yuklash xatosi: {e}")
            await call.message.answer("Yuklab bo‘lmadi. Boshqasini tanlang yoki keyinroq urinib ko‘ring.")
        finally:
            await kutish.delete()


# ---------- Zayafka ----------
@dp.message(F.text.in_(["📝 Zayafka qoldirish", "Zayafka qoldirish"]))
async def start_zayafka(message: types.Message, state: FSMContext):
    await message.answer("Qaysi platforma uchun?", reply_markup=platforma_menyu)
    await state.set_state(Zayafka.platforma)


@dp.message(Zayafka.platforma, F.text.in_(PLATFORMALAR.keys()))
async def get_platform(message: types.Message, state: FSMContext):
    await state.update_data(platforma=message.text)
    await message.answer(
        f"<b>{message.text}</b>\n{PLATFORMALAR[message.text]}\n\nIsmingizni kiriting:",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="HTML"
    )
    await state.set_state(Zayafka.ism)


@dp.message(Zayafka.platforma)
async def wrong_platform(message: types.Message):
    await message.answer("Iltimos, tugmalardan birini tanlang 👇")


@dp.message(Zayafka.ism)
async def get_name(message: types.Message, state: FSMContext):
    ism = message.text.strip()
    if len(ism) < 2:
        await message.answer("Ism juda qisqa. Qaytadan kiriting:")
        return
    await state.update_data(ism=ism)
    await message.answer("Telefon raqamingizni kiriting (masalan: +998901234567):")
    await state.set_state(Zayafka.telefon)


@dp.message(Zayafka.telefon)
async def get_phone(message: types.Message, state: FSMContext):
    telefon = message.text.strip()
    if not re.match(r"^[\d\+\-\s\(\)]{9,20}$", telefon):
        await message.answer("Telefon raqami noto‘g‘ri ko‘rinadi. Qaytadan kiriting:")
        return

    data = await state.get_data()
    text = (
        "🆕 <b>Yangi zayafka</b>\n\n"
        f"📱 Platforma: <b>{data['platforma']}</b>\n"
        f"👤 Ism: {data['ism']}\n"
        f"📞 Telefon: <code>{telefon}</code>\n"
        f"🆔 User ID: <code>{message.from_user.id}</code>"
    )
    await message.answer(
        "Rahmat! Zayafkangiz qabul qilindi ✅\nTez orada bog‘lanamiz.",
        reply_markup=asosiy_menyu,
    )
    try:
        await bot.send_message(chat_id=ADMIN_ID, text=text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Adminga yuborishda xato: {e}")
    await state.clear()


# ---------- Ishga tushirish ----------
async def main():
    logger.info("Bot ishga tushmoqda...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
