import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

# Yangi tokenni shu yerga qo'ying
API_TOKEN = '8656378230:AAFtOSKmhaWlHwhHhRzvkxK8bPuVEKRh9Hg'

# O'zingizning raqamli Telegram ID'ingiz (qo'shtirnoqsiz)
ADMIN_ID = 8756103290

bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Narxlar ro'yxati
NARXLAR = """
💰 Xizmatlarimiz narxi:

1. Oddiy zayafka: 50 000 so'm
2. Premium zayafka: 100 000 so'm
3. VIP xizmat: 200 000 so'm

Zayafka qoldirish uchun /start tugmasini bosing.
"""

# Tugmalar
keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Zayafka qoldirish")],
        [KeyboardButton(text="Narxlar bilan tanishish")]
    ],
    resize_keyboard=True
)

# Holatlar (States)
class Zayafka(StatesGroup):
    ism = State()
    telefon = State()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("Assalomu alaykum! Xush kelibsiz. Quyidagilardan birini tanlang:", reply_markup=keyboard)

@dp.message(F.text == "Narxlar bilan tanishish")
async def show_prices(message: types.Message):
    await message.answer(NARXLAR, parse_mode="Markdown")

@dp.message(F.text == "Zayafka qoldirish")
async def start_zayafka(message: types.Message, state: FSMContext):
    await message.answer("Ismingizni kiriting:")
    await state.set_state(Zayafka.ism)

@dp.message(Zayafka.ism)
async def get_name(message: types.Message, state: FSMContext):
    await state.update_data(ism=message.text)
    await message.answer("Telefon raqamingizni kiriting:")
    await state.set_state(Zayafka.telefon)

@dp.message(Zayafka.telefon)
async def get_phone(message: types.Message, state: FSMContext):
    data = await state.get_data()
    ism = data['ism']
    telefon = message.text

    text = f"Yangi zayafka:\nIsm: {ism}\nTelefon: {telefon}"
    await message.answer("Rahmat! Zayafkangiz qabul qilindi.")

    await bot.send_message(chat_id=ADMIN_ID, text=text)
    await state.clear()

async def main():
    await dp.start_polling(bot)

if _name_ == "_main_":
    asyncio.run(main())
    
