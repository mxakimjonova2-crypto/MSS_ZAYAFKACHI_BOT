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
API_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

if not API_TOKEN:
    raise ValueError("BOT_TOKEN topilmadi! .env faylini tekshiring.")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(name)

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
    ism = State
