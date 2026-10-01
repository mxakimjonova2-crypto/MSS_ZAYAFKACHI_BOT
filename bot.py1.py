import asyncio
import os
import tempfile

import yt_dlp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    FSInputFile,
)

API_TOKEN = "8656378230:AAEK7Htv-jAIOn3ItzcLJ4lGUHoT8n07_BI"
ADMIN_ID = 8756103290

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

asosiy_menyu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Zayafka qoldirish")],
        [KeyboardButton(text="Narxlar bilan tanishish")],
        [KeyboardButton(text="🎵 Musiqa qidirish")],
    ],
    resize_keyboard=True,
)

nomlar = list(PLATFORMALAR.keys())

platforma_menyu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=nomlar[0]), KeyboardButton(text=nomlar[1])],
        [KeyboardButton(text=nomlar[2]), KeyboardButton(text=nomlar[3])],
        [KeyboardButton(text="Bekor qilish")],
    ],
    resize_keyboard=True,
)

bekor_menyu = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Bekor qilish")]],
    resize_keyboard=True,
)


class Zayafka(StatesGroup):
    platforma = State()
    ism = State()
    telefon = State()


class Musiqa(StatesGroup):
    nom = State()


# ---------- MUSIQA FUNKSIYALARI ----------

def qidir(soz):
    opts = {
        "quiet": True,
        "extract_flat": True,
        "skip_download": True,
    }

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(
            f"ytsearch5:{soz}",
            download=False
        )

    natijalar = []

    for e in info.get("entries", []):
        if e and e.get("id"):
            natijalar.append(
                (e["id"], e.get("title", "Nomsiz"))
            )

    return natijalar


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
            f"https://www.youtube.com/watch?v={video_id}",
            download=True
        )

        fayl = ydl.prepare_filename(info)

        if not os.path.exists(fayl):
            video_id = info.get("id")

            for nom in os.listdir(papka):
                if nom.startswith(video_id + "."):
                    fayl = os.path.join(papka, nom)
                    break

        return fayl, info.get("title", "Nomsiz")


# ---------- START ----------

@dp.message(Command("start"))
async def start(message: types.Message, state: FSMContext):
    await state.clear()

    await message.answer(
        "👋 Assalomu alaykum!\n\n"
        "Botimizga xush kelibsiz.\n"
        "Kerakli bo'limni tanlang:",
        reply_markup=asosiy_menyu
    )


# ---------- NARXLAR ----------

@dp.message(F.text == "Narxlar bilan tanishish")
async def narxlar(message: types.Message):
    await message.answer(
        NARXLAR,
        reply_markup=asosiy_menyu
    )


# ---------- ZAYAFKA ----------

@dp.message(F.text == "Zayafka qoldirish")
async def zayafka_boshlash(
    message: types.Message,
    state: FSMContext
):
    await state.set_state(Zayafka.platforma)

    await message.answer(
        "📱 Qaysi platforma uchun xizmat kerak?",
        reply_markup=platforma_menyu
    )


@dp.message(Zayafka.platforma, F.text == "Bekor qilish")
async def zayafka_bekor(
    message: types.Message,
    state: FSMContext
):
    await state.clear()

    await message.answer(
        "❌ Zayafka bekor qilindi.",
        reply_markup=asosiy_menyu
    )


@dp.message(Zayafka.platforma)
async def platforma_tanlash(
    message: types.Message,
    state: FSMContext
):
    platforma = message.text

    if platforma not in PLATFORMALAR:
        await message.answer(
            "Iltimos, menyudagi platformalardan birini tanlang."
        )
        return

    await state.update_data(platforma=platforma)
    await state.set_state(Zayafka.ism)

    await message.answer(
        "👤 Ismingizni kiriting:",
        reply_markup=bekor_menyu
    )


@dp.message(Zayafka.ism, F.text == "Bekor qilish")
async def ism_bekor(
    message: types.Message,
    state: FSMContext
):
    await state.clear()

    await message.answer(
        "❌ Zayafka bekor qilindi.",
        reply_markup=asosiy_menyu
    )


@dp.message(Zayafka.ism)
async def ism_qabul(
    message: types.Message,
    state: FSMContext
):
    ism = message.text.strip()

    if len(ism) < 2:
        await message.answer(
            "Iltimos, ismingizni to'g'ri kiriting."
        )
        return

    await state.update_data(ism=ism)
    await state.set_state(Zayafka.telefon)

    await message.answer(
        "📞 Telefon raqamingizni kiriting:\n"
        "Masalan: +998901234567",
        reply_markup=bekor_menyu
    )


@dp.message(Zayafka.telefon, F.text == "Bekor qilish")
async def telefon_bekor(
    message: types.Message,
    state: FSMContext
):
    await state.clear()

    await message.answer(
        "❌ Zayafka bekor qilindi.",
        reply_markup=asosiy_menyu
    )


@dp.message(Zayafka.telefon)
async def telefon_qabul(
    message: types.Message,
    state: FSMContext
):
    telefon = message.text.strip()

    if len(telefon) < 7:
        await message.answer(
            "Telefon raqamini to'g'ri kiriting.\n"
            "Masalan: +998901234567"
        )
        return

    data = await state.get_data()

    platforma = data["platforma"]
    ism = data["ism"]

    admin_xabar = (
        "🔔 Yangi zayafka!\n\n"
        f"👤 Ism: {ism}\n"
        f"📞 Telefon: {telefon}\n"
        f"📱 Platforma: {platforma}\n"
        f"💰 Narx: {PLATFORMALAR[platforma]}"
    )

    try:
        await bot.send_message(
            ADMIN_ID,
            admin_xabar
        )

        await message.answer(
            "✅ Zayavkangiz qabul qilindi!\n\n"
            "Tez orada siz bilan bog'lanamiz.",
            reply_markup=asosiy_menyu
        )

    except Exception:
        await message.answer(
            "⚠️ Zayavkani yuborishda xatolik yuz berdi. "
            "Keyinroq urinib ko'ring.",
            reply_markup=asosiy_menyu
        )

    finally:
        await state.clear()


# ---------- MUSIQA QIDIRISH ----------

@dp.message(F.text == "🎵 Musiqa qidirish")
async def musiqa_boshlash(
    message: types.Message,
    state: FSMContext
):
    await state.set_state(Musiqa.nom)

    await message.answer(
        "🎵 Qo'shiq yoki ijrochi nomini yozing:",
        reply_markup=bekor_menyu
    )


@dp.message(Musiqa.nom, F.text == "Bekor qilish")
async def musiqa_bekor(
    message: types.Message,
    state: FSMContext
):
    await state.clear()

    await message.answer(
        "❌ Qidiruv bekor qilindi.",
        reply_markup=asosiy_menyu
    )


@dp.message(Musiqa.nom)
async def musiqa_qidirish(
    message: types.Message,
    state: FSMContext
):
    soz = message.text.strip()

    if not soz:
        await message.answer(
            "Qo'shiq nomini yozing."
        )
        return

    await message.answer(
        "🔎 Qidiryapman, biroz kuting..."
    )

    try:
        natijalar = await asyncio.to_thread(
            qidir,
            soz
        )

    except Exception:
        await message.answer(
            "❌ Qidirishda xatolik yuz berdi.\n"
            "Keyinroq qayta urinib ko'ring."
        )
        return

    if not natijalar:
        await message.answer(
            "😔 Hech qanday natija topilmadi.",
            reply_markup=asosiy_menyu
        )

        await state.clear()
        return

    keyboard = []

    for video_id, title in natijalar:
        keyboard.append([
            InlineKeyboardButton(
                text=f"🎵 {title[:45]}",
                callback_data=f"music:{video_id}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            text="❌ Bekor qilish",
            callback_data="music_cancel"
        )
    ])

    await message.answer(
        "🎶 Natijalardan birini tanlang:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=keyboard
        )
    )


# ---------- MUSIQANI YUKLASH ----------

@dp.callback_query(F.data.startswith("music:"))
async def musiqa_yuklash(
    callback: types.CallbackQuery
):
    video_id = callback.data.split(":", 1)[1]

    await callback.answer(
        "Yuklanmoqda..."
    )

    await callback.message.edit_text(
        "⏳ Musiqa yuklanmoqda. Biroz kuting..."
    )

    papka = tempfile.mkdtemp(
        prefix="music_"
    )

    try:
        fayl, title = await asyncio.to_thread(
            yukla,
            video_id,
            papka
        )

        if not os.path.exists(fayl):
            raise FileNotFoundError(
                "Audio fayl topilmadi."
            )

        await callback.message.answer_audio(
            audio=FSInputFile(fayl),
            title=title[:64],
            caption=f"🎵 {title}"
        )

    except Exception:
        await callback.message.answer(
            "❌ Musiqani yuklashda xatolik yuz berdi.\n"
            "Boshqa natijani tanlab ko'ring."
        )

    finally:
        try:
            for nom in os.listdir(papka):
                yol = os.path.join(
                    papka,
                    nom
                )

                if os.path.isfile(yol):
                    os.remove(yol)

            os.rmdir(papka)

        except Exception:
            pass


@dp.callback_query(F.data == "music_cancel")
async def musiqa_callback_bekor(
    callback: types.CallbackQuery
):
    await callback.answer(
        "Bekor qilindi."
    )

    await callback.message.edit_text(
        "❌ Musiqa qidirish bekor qilindi."
    )


# ---------- BOTNI ISHGA TUSHIRISH ----------

async def main():
    print("Bot ishga tushdi...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
