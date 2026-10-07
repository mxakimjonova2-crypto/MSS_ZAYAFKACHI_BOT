import os, json, base64, asyncio, logging, sqlite3
import yt_dlp
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (Message, CallbackQuery, KeyboardButton, WebAppInfo,
                           InlineKeyboardButton, InlineKeyboardMarkup, FSInputFile)
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder

logging.basicConfig(level=logging.INFO)

# ---------- YouTube cookies (Railway Variables: YT_COOKIES_B64) ----------
_b = os.getenv("YT_COOKIES_B64")
if _b:
    with open("cookies.txt", "wb") as f:
        f.write(base64.b64decode(_b))
    print("cookies.txt yozildi")
else:
    print("YT_COOKIES_B64 topilmadi")

# ---------- Sozlamalar (Railway Variables) ----------
BOT_TOKEN = "8656378230:AAEI_XN4L4i3ALsXoVIHtAoWuXPhVbeJVVM"
ADMIN_ID = 8756103290
ADMIN_USERNAME = "MCHE_9804"
SITE_URL = os.getenv("SITE_URL", "https://mxakimjonova2-crypto.github.io/MSS_ZAYAFKACHI_BOT/")
DB_PATH = os.getenv("DB_PATH", "bot.db")
REF_BONUS = 500

# 1000 ta uchun narx (so'm). index.html dagi PR bilan bir xil bo'lsin
PRICES = {
    "Instagram": {"Obunachi": 18000, "Layk": 6000, "Ko'rish": 2000},
    "YouTube": {"Ko'rish": 15000, "Layk": 12000, "Obunachi": 90000},
    "TikTok": {"Ko'rish": 2000, "Layk": 6000, "Obunachi": 20000},
    "Telegram": {"Obunachi": 9000, "Ko'rish": 1500},
}

bot = Bot(BOT_TOKEN)
router = Router()
os.makedirs("downloads", exist_ok=True)

# ---------- Baza ----------
db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.executescript("""
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT, balance REAL DEFAULT 0, ref INTEGER);
CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, text TEXT, price REAL,
  status TEXT DEFAULT 'yangi', ts DATETIME DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);
""")
db.commit()


def get_bal(uid):
    r = db.execute("SELECT balance FROM users WHERE id=?", (uid,)).fetchone()
    return r[0] if r else 0


def add_bal(uid, amount):
    db.execute("UPDATE users SET balance=balance+? WHERE id=?", (amount, uid))
    db.commit()


def get_set(k, default=""):
    r = db.execute("SELECT v FROM settings WHERE k=?", (k,)).fetchone()
    return r[0] if r else default


def set_set(k, v):
    db.execute("INSERT OR REPLACE INTO settings(k,v) VALUES(?,?)", (k, v))
    db.commit()


def fmt(n):
    return f"{int(n):,}".replace(",", " ") + " so'm"


def card_text():
    return get_set("card", os.getenv("CARD", "Karta hali kiritilmagan"))


# ---------- Menyu ----------
def menu(uid):
    kb = ReplyKeyboardBuilder()
    kb.row(KeyboardButton(text="🌐 Sayt", web_app=WebAppInfo(url=f"{SITE_URL}?bal={int(get_bal(uid))}")))
    kb.row(KeyboardButton(text="📁 Xizmatlarga buyurtma berish"), KeyboardButton(text="🎵 Musiqa qidirish"))
    kb.row(KeyboardButton(text="💵 Hisob to'ldirish"), KeyboardButton(text="💰 Mening hisobim"))
    kb.row(KeyboardButton(text="🔎 Buyurtmalarim"), KeyboardButton(text="👥 Pul ishlash"))
    kb.row(KeyboardButton(text="⭐ Stars hizmati"), KeyboardButton(text="💎 Premium olish"))
    kb.row(KeyboardButton(text="Zayafka qoldirish"), KeyboardButton(text="☎️ Qo'llab-quvvatlash"))
    kb.row(KeyboardButton(text="💳 Karta qo'shish"))
    return kb.as_markup(resize_keyboard=True)


class Order(StatesGroup):
    link = State()
    qty = State()


class Topup(StatesGroup):
    amount = State()
    check = State()


class Zay(StatesGroup):
    name = State()
    phone = State()
    price = State()


class Music(StatesGroup):
    query = State()


class CardS(StatesGroup):
    number = State()


# ---------- Yuklash (yt-dlp) ----------
def ydl_download(target, audio):
    opts = {"outtmpl": "downloads/%(id)s.%(ext)s", "noplaylist": True, "quiet": True,
            "max_filesize": 49 * 1024 * 1024}
    if os.path.exists("cookies.txt"):
        opts["cookiefile"] = "cookies.txt"
    if audio:
        opts["format"] = "bestaudio/best"
        opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3",
                                   "preferredquality": "192"}]
    else:
        opts["format"] = "best[ext=mp4]/best"
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(target, download=True)
        if "entries" in info:
            info = info["entries"][0]
        path = ydl.prepare_filename(info)
        if audio:
            path = os.path.splitext(path)[0] + ".mp3"
        return path, info.get("title", "")


def fetch(query_or_url, audio, search):
    targets = [f"ytsearch1:{query_or_url}", f"scsearch1:{query_or_url}"] if search else [query_or_url]
    for t in targets:
        try:
            path, title = ydl_download(t, audio)
            if os.path.exists(path):
                return path, title
        except Exception as e:
            logging.warning("yt-dlp xato (%s): %s", t[:20], e)
    return None, None


async def deliver(m: Message, query, audio, search):
    wait = await m.answer("⏳ Yuklanmoqda, biroz kuting...")
    path, title = await asyncio.to_thread(fetch, query, audio, search)
    if not path:
        await wait.edit_text("❌ Yuklab bo'lmadi. Havolani tekshiring yoki birozdan keyin urinib ko'ring.")
        return
    try:
        if audio:
            await m.answer_audio(FSInputFile(path), title=title)
        else:
            await m.answer_video(FSInputFile(path), caption=title[:200])
        await wait.delete()
    except Exception as e:
        logging.warning("yuborishda xato: %s", e)
        await wait.edit_text("❌ Fayl juda katta yoki yuborib bo'lmadi (limit 50 MB).")
    finally:
        if os.path.exists(path):
            os.remove(path)


# ---------- Buyurtma yaratish ----------
async def make_order(m: Message, uid, platform, service, link, qty):
    price = PRICES[platform][service] * qty / 1000
    if get_bal(uid) < price:
        await m.answer(f"❌ Balans yetarli emas. Kerak: {fmt(price)}, sizda: {fmt(get_bal(uid))}.\n"
                       "«💵 Hisob to'ldirish» orqali to'ldiring.", reply_markup=menu(uid))
        return
    add_bal(uid, -price)
    text = f"{platform} {service} x{qty} | {link}"
    cur = db.execute("INSERT INTO orders(uid,text,price) VALUES(?,?,?)", (uid, text, price))
    db.commit()
    await m.answer(f"✅ Buyurtma #{cur.lastrowid} qabul qilindi.\n{text}\nNarx: {fmt(price)}",
                   reply_markup=menu(uid))
    if ADMIN_ID:
        await bot.send_message(ADMIN_ID, f"🆕 Buyurtma #{cur.lastrowid}\nFoydalanuvchi: {uid}\n{text}\nNarx: {fmt(price)}")


# ---------- /start ----------
@router.message(CommandStart())
async def start(m: Message, command: CommandObject, state: FSMContext):
    await state.clear()
    uid = m.from_user.id
    if not db.execute("SELECT 1 FROM users WHERE id=?", (uid,)).fetchone():
        ref = int(command.args) if command.args and command.args.isdigit() and int(command.args) != uid else None
        db.execute("INSERT INTO users(id,name,ref) VALUES(?,?,?)", (uid, m.from_user.full_name, ref))
        db.commit()
        if ref and db.execute("SELECT 1 FROM users WHERE id=?", (ref,)).fetchone():
            add_bal(ref, REF_BONUS)
            await bot.send_message(ref, f"🎉 Yangi do'stingiz qo'shildi! +{fmt(REF_BONUS)}")
    await m.answer("Xush kelibsiz! 👋\nPastdagi menyudan tanlang. «🌐 Sayt» tugmasi chiroyli ilovani ochadi.",
                   reply_markup=menu(uid))


# ---------- Menyu tugmalari (state'lardan oldin) ----------
@router.message(F.text.contains("Mening hisobim"))
async def my_account(m: Message, state: FSMContext):
    await state.clear()
    await m.answer(f"💰 Balansingiz: {fmt(get_bal(m.from_user.id))}\n🆔 ID: {m.from_user.id}",
                   reply_markup=menu(m.from_user.id))


@router.message(F.text.contains("Buyurtmalarim"))
async def my_orders(m: Message, state: FSMContext):
    await state.clear()
    rows = db.execute("SELECT id,text,price,status FROM orders WHERE uid=? ORDER BY id DESC LIMIT 10",
                      (m.from_user.id,)).fetchall()
    if not rows:
        return await m.answer("Hali buyurtmalar yo'q.")
    await m.answer("\n\n".join(f"#{r[0]} | {r[3]}\n{r[1]}\n{fmt(r[2])}" for r in rows))


@router.message(F.text.contains("Pul ishlash"))
async def earn(m: Message, state: FSMContext):
    await state.clear()
    me = await bot.me()
    await m.answer(f"👥 Do'stlaringizni taklif qiling, har biri uchun {fmt(REF_BONUS)} olasiz.\n\n"
                   f"Sizning havolangiz:\nhttps://t.me/{me.username}?start={m.from_user.id}")


@router.message(F.text.contains("Qo'llab-quvvatlash"))
async def support(m: Message, state: FSMContext):
    await state.clear()
    await m.answer(f"☎️ Savol bo'lsa adminga yozing: {ADMIN_USERNAME}")


def req_kb(name):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📩 So'rov yuborish", callback_data=f"req:{name}")]])


@router.message(F.text.contains("Stars hizmati"))
async def stars(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("⭐ Telegram Stars xizmati. Narxni bilish va buyurtma berish uchun so'rov yuboring.",
                   reply_markup=req_kb("Stars"))


@router.message(F.text.contains("Premium olish"))
async def premium(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("💎 Telegram Premium xizmati. Narxni bilish va buyurtma berish uchun so'rov yuboring.",
                   reply_markup=req_kb("Premium"))


@router.callback_query(F.data.startswith("req:"))
async def req(c: CallbackQuery):
    name = c.data.split(":")[1]
    if ADMIN_ID:
        await bot.send_message(ADMIN_ID, f"📩 {name} so'rovi\nFoydalanuvchi: {c.from_user.full_name} "
                                         f"(@{c.from_user.username}) ID {c.from_user.id}")
    await c.message.answer("✅ So'rovingiz adminga yuborildi. Tez orada bog'lanamiz.")
    await c.answer()


@router.message(F.text.contains("Karta qo'shish"))
async def card_add(m: Message, state: FSMContext):
    await state.clear()
    if m.from_user.id != ADMIN_ID:
        return await m.answer(f"💳 To'lov kartasi:\n{card_text()}")
    await state.set_state(CardS.number)
    await m.answer("Yangi karta raqami va egasini yozing (masalan: 8600 1234 5678 9012 | ISM FAMILIYA):")


@router.message(CardS.number)
async def card_save(m: Message, state: FSMContext):
    set_set("card", m.text.strip())
    await state.clear()
    await m.answer("✅ Karta saqlandi.", reply_markup=menu(m.from_user.id))


# ---------- Xizmatlarga buyurtma ----------
@router.message(F.text.contains("Xizmatlarga buyurtma"))
async def order_start(m: Message, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardBuilder()
    for p in PRICES:
        kb.button(text=p, callback_data=f"p:{p}")
    kb.adjust(2)
    await m.answer("Quyidagi ijtimoiy tarmoqlardan birini tanlang:", reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("p:"))
async def pick_platform(c: CallbackQuery):
    p = c.data.split(":")[1]
    kb = InlineKeyboardBuilder()
    for s, pr in PRICES[p].items():
        kb.button(text=f"{s} ({fmt(pr)}/1000)", callback_data=f"s:{p}:{s}")
    kb.adjust(1)
    await c.message.edit_text(f"{p}: xizmatni tanlang:", reply_markup=kb.as_markup())
    await c.answer()


@router.callback_query(F.data.startswith("s:"))
async def pick_service(c: CallbackQuery, state: FSMContext):
    _, p, s = c.data.split(":")
    await state.update_data(platform=p, service=s)
    await state.set_state(Order.link)
    await c.message.answer("🔗 Havolani yuboring (https://... yoki @nom):")
    await c.answer()


@router.message(Order.link)
async def order_link(m: Message, state: FSMContext):
    link = (m.text or "").strip()
    if not (link.startswith("http") or link.startswith("@")):
        return await m.answer("Havola noto'g'ri. https://... yoki @nom ko'rinishida yuboring.")
    await state.update_data(link=link)
    await state.set_state(Order.qty)
    await m.answer("🔢 Miqdorni yozing (kamida 100):")


@router.message(Order.qty)
async def order_qty(m: Message, state: FSMContext):
    if not (m.text or "").strip().isdigit() or int(m.text) < 100:
        return await m.answer("Miqdor kamida 100 bo'lgan son bo'lsin.")
    d = await state.get_data()
    await state.clear()
    await make_order(m, m.from_user.id, d["platform"], d["service"], d["link"], int(m.text))


# ---------- Hisob to'ldirish ----------
@router.message(F.text.contains("Hisob to'ldirish"))
async def topup_start(m: Message, state: FSMContext):
    await state.clear()
    await state.set_state(Topup.amount)
    await m.answer(f"💳 To'lov kartasi:\n{card_text()}\n\nQancha to'ldirmoqchisiz? Summani yozing (so'm):")


@router.message(Topup.amount)
async def topup_amount(m: Message, state: FSMContext):
    t = (m.text or "").replace(" ", "")
    if not t.isdigit() or int(t) < 1000:
        return await m.answer("Summa kamida 1000 so'm bo'lgan son bo'lsin.")
    await state.update_data(amount=int(t))
    await state.set_state(Topup.check)
    await m.answer(f"{fmt(int(t))} to'lang va to'lov chekining 📸 rasmini yuboring.")


@router.message(Topup.check, F.photo)
async def topup_check(m: Message, state: FSMContext):
    amount = (await state.get_data())["amount"]
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"ap:{m.from_user.id}:{amount}"),
        InlineKeyboardButton(text="❌ Rad etish", callback_data=f"rj:{m.from_user.id}")]])
    if ADMIN_ID:
        await bot.send_photo(ADMIN_ID, m.photo[-1].file_id,
                             caption=f"💵 To'ldirish so'rovi\nFoydalanuvchi: {m.from_user.full_name} ({m.from_user.id})\n"
                                     f"Summa: {fmt(amount)}", reply_markup=kb)
    await m.answer("✅ Chek adminga yuborildi. Tasdiqlangach balansingiz to'ldiriladi.", reply_markup=menu(m.from_user.id))


@router.message(Topup.check)
async def topup_check_wrong(m: Message):
    await m.answer("Iltimos, to'lov chekining rasmini yuboring 📸")


@router.callback_query(F.data.startswith("ap:"))
async def approve(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID:
        return await c.answer("Faqat admin", show_alert=True)
    _, uid, amount = c.data.split(":")
    add_bal(int(uid), int(amount))
    await bot.send_message(int(uid), f"✅ Balansingiz {fmt(int(amount))} ga to'ldirildi.", reply_markup=menu(int(uid)))
    await c.message.edit_caption(caption=(c.message.caption or "") + "\n\n✅ Tasdiqlandi")
    await c.answer()


@router.callback_query(F.data.startswith("rj:"))
async def reject(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID:
        return await c.answer("Faqat admin", show_alert=True)
    await bot.send_message(int(c.data.split(":")[1]), "❌ To'lovingiz rad etildi. Savol bo'lsa adminga yozing.")
    await c.message.edit_caption(caption=(c.message.caption or "") + "\n\n❌ Rad etildi")
    await c.answer()


# ---------- Zayafka ----------
@router.message(F.text.contains("Zayafka qoldirish"))
async def zay_start(m: Message, state: FSMContext):
    await state.clear()
    await state.set_state(Zay.name)
    await m.answer("Ismingizni yozing:")


@router.message(Zay.name)
async def zay_name(m: Message, state: FSMContext):
    await state.update_data(name=m.text)
    await state.set_state(Zay.phone)
    await m.answer("Telefon raqamingizni yozing:")


@router.message(Zay.phone)
async def zay_phone(m: Message, state: FSMContext):
    await state.update_data(phone=m.text)
    await state.set_state(Zay.price)
    await m.answer("Narxni yozing (so'm):")


@router.message(Zay.price)
async def zay_price(m: Message, state: FSMContext):
    d = await state.get_data()
    await state.clear()
    if ADMIN_ID:
        await bot.send_message(ADMIN_ID, f"📝 Yangi zayafka\nIsm: {d['name']}\nTelefon: {d['phone']}\nNarx: {m.text}\n"
                                         f"Telegram: @{m.from_user.username} ({m.from_user.id})")
    await m.answer("✅ Zayafkangiz qabul qilindi.", reply_markup=menu(m.from_user.id))


# ---------- Musiqa ----------
@router.message(F.text.contains("Musiqa qidirish"))
async def music_start(m: Message, state: FSMContext):
    await state.clear()
    await state.set_state(Music.query)
    await m.answer("🎵 Qo'shiq yoki ijrochi nomini yozing:")


@router.message(Music.query)
async def music_query(m: Message, state: FSMContext):
    await state.clear()
    await deliver(m, m.text.strip(), audio=True, search=True)


# ---------- SAYT (Mini App) dan kelgan ma'lumotlar ----------
@router.message(F.web_app_data)
async def from_site(m: Message, state: FSMContext):
    try:
        d = json.loads(m.web_app_data.data)
    except Exception:
        return await m.answer("Ma'lumot o'qilmadi.")
    a, uid = d.get("action"), m.from_user.id
    if a == "order":
        p, s = d.get("platform"), d.get("service")
        qty = int(d.get("qty", 0))
        if p in PRICES and s in PRICES[p] and qty >= 100:
            await make_order(m, uid, p, s, str(d.get("link", ""))[:300], qty)
        else:
            await m.answer("Buyurtma ma'lumoti noto'g'ri.")
    elif a == "download":
        q, kind = str(d.get("query", "")).strip(), d.get("kind")
        if not q:
            return await m.answer("Havola yoki nom bo'sh.")
        await deliver(m, q, audio=kind in ("mp3", "search"), search=kind == "search")
    elif a == "topup":
        amount = int(d.get("amount", 0))
        if amount < 1000:
            return await m.answer("Summa kamida 1000 so'm.")
        await state.update_data(amount=amount)
        await state.set_state(Topup.check)
        await m.answer(f"💳 To'lov kartasi:\n{card_text()}\n\n{fmt(amount)} to'lang va chekning 📸 rasmini yuboring.")


# ---------- Havola yuborilsa video yuklash ----------
@router.message(F.text.regexp(r"https?://"))
async def link_download(m: Message, state: FSMContext):
    if await state.get_state():
        return
    await deliver(m, m.text.strip(), audio=False, search=False)


async def main():
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
