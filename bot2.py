#!/usr/bin/env python3
"""
AI Местный — мультигород v4
Bot: @mestniy_guide_bot
File: /root/bot2.py
Service: sochi-test
"""

import asyncio
import logging
import os
import sqlite3
import tempfile
import random
from datetime import datetime, timedelta
import pytz

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from openai import OpenAI
import gspread
from google.oauth2.service_account import Credentials

# ──────────────────────────────────────────────────────────────
# КОНФИГ
# ──────────────────────────────────────────────────────────────
BOT_TOKEN      = "8987086395:AAHN0YjaZTQoP28WPImnQguZrx5FPiXV8kw"
OPENAI_KEY     = "sk-mfvVI3QN2uQvXPlhMkAeUUzmbjK5aQzj"
OWNER_ID       = 549639607
SPREADSHEET_ID = "1PE7CaFuWOe_eygQqIoMAmUdJBtATbIaNfZR4cvarPCA"
SHEET_NAME     = "Аналитика Сочи"
REVIEW_SHEET   = "Отзывы AI местный"
CREDENTIALS    = "/root/google_credentials.json"
DB_PATH        = "/root/bot2.db"
MODEL          = "gpt-4o"
MOSCOW_TZ      = pytz.timezone("Europe/Moscow")

# ──────────────────────────────────────────────────────────────
# ГОРОДА
# ──────────────────────────────────────────────────────────────
CITIES = {
    "🌊 Сочи":            {"name": "Сочи"},
    "🏙 Москва":          {"name": "Москва"},
    "🏛 Санкт-Петербург": {"name": "Санкт-Петербург"},
    "🕌 Казань":          {"name": "Казань"},
    "🌿 Краснодар":       {"name": "Краснодар"},
    "🌅 Калининград":     {"name": "Калининград"},
    "💎 Екатеринбург":    {"name": "Екатеринбург"},
    "🏯 Нижний Новгород": {"name": "Нижний Новгород"},
}

CITY_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🌊 Сочи"),            KeyboardButton(text="🏙 Москва")],
        [KeyboardButton(text="🏛 Санкт-Петербург"), KeyboardButton(text="🕌 Казань")],
        [KeyboardButton(text="🌿 Краснодар"),       KeyboardButton(text="🌅 Калининград")],
        [KeyboardButton(text="💎 Екатеринбург"),    KeyboardButton(text="🏯 Нижний Новгород")],
    ],
    resize_keyboard=True,
)

# ──────────────────────────────────────────────────────────────
# ЗОДИАК
# ──────────────────────────────────────────────────────────────
ZODIAC_SIGNS = [
    "♈ Овен", "♉ Телец", "♊ Близнецы", "♋ Рак",
    "♌ Лев", "♍ Дева", "♎ Весы", "♏ Скорпион",
    "♐ Стрелец", "♑ Козерог", "♒ Водолей", "♓ Рыбы",
]

ZODIAC_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="♈ Овен"),      KeyboardButton(text="♉ Телец")],
        [KeyboardButton(text="♊ Близнецы"),  KeyboardButton(text="♋ Рак")],
        [KeyboardButton(text="♌ Лев"),       KeyboardButton(text="♍ Дева")],
        [KeyboardButton(text="♎ Весы"),      KeyboardButton(text="♏ Скорпион")],
        [KeyboardButton(text="♐ Стрелец"),   KeyboardButton(text="♑ Козерог")],
        [KeyboardButton(text="♒ Водолей"),   KeyboardButton(text="♓ Рыбы")],
        [KeyboardButton(text="⏭ Пропустить")],
    ],
    resize_keyboard=True,
)

# ──────────────────────────────────────────────────────────────
# ГЛАВНОЕ МЕНЮ
# ──────────────────────────────────────────────────────────────
MAIN_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="✏️ Свой вопрос"),      KeyboardButton(text="🏙 Сменить город")],
        [KeyboardButton(text="🍽 Где поесть"),        KeyboardButton(text="☕ Кофе с видом")],
        [KeyboardButton(text="🌅 На рассвет"),        KeyboardButton(text="🎭 Куда сходить")],
        [KeyboardButton(text="👨‍👩‍👧 С детьми"),       KeyboardButton(text="💑 Романтика")],
        [KeyboardButton(text="🏔 На природу"),        KeyboardButton(text="🌃 Вечер")],
        [KeyboardButton(text="🗺 Маршрут на день"),   KeyboardButton(text="💬 Местный советует")],
        [KeyboardButton(text="🛠 Поддержка"),         KeyboardButton(text="ℹ️ О проекте")],
        [KeyboardButton(text="💬 Оставить отзыв"),    KeyboardButton(text="🏠 Главное меню")],
    ],
    resize_keyboard=True,
    one_time_keyboard=False,
)

THEME_BUTTONS = {
    "🍽 Где поесть", "☕ Кофе с видом", "🌅 На рассвет", "🎭 Куда сходить",
    "👨‍👩‍👧 С детьми", "💑 Романтика", "🏔 На природу", "🌃 Вечер",
    "🗺 Маршрут на день", "💬 Местный советует",
}
SYSTEM_BUTTONS = {
    "✏️ Свой вопрос", "🛠 Поддержка", "ℹ️ О проекте",
    "🏙 Сменить город", "💬 Оставить отзыв", "🏠 Главное меню",
}

BACK_TEXT = "\n\nЧто ещё найти? Жми кнопку или пиши 👇"

# ──────────────────────────────────────────────────────────────
# FSM
# ──────────────────────────────────────────────────────────────
class UserState(StatesGroup):
    choosing_city   = State()
    choosing_zodiac = State()
    writing_review  = State()

# ──────────────────────────────────────────────────────────────
# КЛИЕНТЫ
# ──────────────────────────────────────────────────────────────
bot    = Bot(token=BOT_TOKEN)
dp     = Dispatcher(storage=MemoryStorage())
client = OpenAI(api_key=OPENAI_KEY, base_url="https://api.proxyapi.ru/openai/v1")

# ──────────────────────────────────────────────────────────────
# БАЗА ДАННЫХ
# ──────────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id        INTEGER PRIMARY KEY,
            name           TEXT,
            username       TEXT,
            city           TEXT DEFAULT 'Сочи',
            city_emoji     TEXT DEFAULT '🌊 Сочи',
            zodiac         TEXT DEFAULT NULL,
            registered_at  TEXT,
            last_active    TEXT,
            total_requests INTEGER DEFAULT 0,
            is_premium     INTEGER DEFAULT 1,
            morning_notify INTEGER DEFAULT 1
        )
    """)
    # Добавить zodiac если старая база
    try:
        c.execute("ALTER TABLE users ADD COLUMN zodiac TEXT DEFAULT NULL")
    except Exception:
        pass
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row

def save_user(user_id, name, username, city="Сочи", city_emoji="🌊 Сочи"):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    c.execute("""
        INSERT INTO users (user_id, name, username, city, city_emoji, registered_at, last_active)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            name=excluded.name, username=excluded.username, last_active=excluded.last_active
    """, (user_id, name, username or "", city, city_emoji, now, now))
    conn.commit()
    conn.close()

def update_city(user_id, city, city_emoji):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET city=?, city_emoji=? WHERE user_id=?", (city, city_emoji, user_id))
    conn.commit()
    conn.close()

def update_zodiac(user_id, zodiac):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET zodiac=? WHERE user_id=?", (zodiac, user_id))
    conn.commit()
    conn.close()

def increment_requests(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    c.execute("UPDATE users SET total_requests=total_requests+1, last_active=? WHERE user_id=?", (now, user_id))
    conn.commit()
    conn.close()

def get_all_users_for_morning():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, city, zodiac FROM users WHERE morning_notify=1")
    rows = c.fetchall()
    conn.close()
    return rows

def get_user_city(user_id):
    row = get_user(user_id)
    if row:
        return row[3], row[4]
    return "Сочи", "🌊 Сочи"

def get_user_zodiac(user_id):
    row = get_user(user_id)
    if row and len(row) > 5:
        return row[5]
    return None

def has_zodiac_set(user_id):
    """Возвращает True если зодиак уже спрашивали (даже если пропустили)"""
    row = get_user(user_id)
    if not row:
        return False
    zodiac = row[5] if len(row) > 5 else None
    return zodiac is not None

# ──────────────────────────────────────────────────────────────
# GPT
# ──────────────────────────────────────────────────────────────
def get_system_prompt(city):
    return f"""Ты — AI Местный, виртуальный друг который отлично знает город {city}. Живёшь там много лет.

ТВОЯ ЗАДАЧА: помогать людям находить интересные места и активности в городе {city}.

СТИЛЬ ОБЩЕНИЯ:
- Говори как живой человек, тепло и дружелюбно. Без канцелярита.
- Можно на ты.
- СТРОГО ЗАПРЕЩЕНО использовать markdown: никаких **, __, ##, [], ``. Совсем.
- Эмодзи умеренно — 1-2 на место, не больше.

ФОРМАТ КАЖДОГО МЕСТА:
1. Название места
📍 Район или улица
💚 Доступные цены / 💛 Средние цены / 💰 Цены выше среднего (выбери одно)
✨ Фишка — почему стоит идти (1-2 предложения)
🗺 Яндекс.Карты: https://yandex.ru/maps/?text=Название+места+{city.replace(' ', '+')}
🗺 2ГИС: https://2gis.ru/search/Название+места+{city.replace(' ', '+')}
⚠️ Актуальные цены и часы уточняйте по телефону или по ссылкам выше

ПРАВИЛА:
- Никогда не пиши конкретные цены в рублях.
- Никогда не выдумывай телефоны.
- Давай 5-7 мест в ответе.
- Если человек нажал кнопку — СРАЗУ давай подборку БЕЗ ВОПРОСОВ.
- Никогда не спрашивай про бюджет или компанию — человек сам уточнит.
- Только если город большой (Москва, СПб) — можно спросить район одним вопросом.

КНОПКА "КУДА СХОДИТЬ":
Дай ссылки на афишу:
- https://kudago.com/{city.lower().replace(' ', '-')}
- https://afisha.yandex.ru/{city.lower().replace(' ', '-')}

КНОПКА "МАРШРУТ НА ДЕНЬ":
Составь план утро → день → вечер с маршрутом между точками.

КНОПКА "МЕСТНЫЙ СОВЕТУЕТ":
Один инсайд про {city} — лайфхак, секрет, традиция. Без конкретных заведений. 3-5 предложений.

Если пишут про другой город — предложи сменить город кнопкой 🏙 Сменить город."""

def _ask_sync(user_text, city):
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": get_system_prompt(city)},
            {"role": "user",   "content": user_text},
        ],
        max_tokens=2000,
    )
    return response.choices[0].message.content.strip()

async def ask_ai(text, city):
    return await asyncio.get_event_loop().run_in_executor(None, _ask_sync, text, city)

def _morning_sync(city, zodiac):
    zodiac_part = ""
    if zodiac and zodiac != "skip":
        zodiac_part = f"\n2. Персональный гороскоп для знака {zodiac} на сегодня (2-3 предложения, позитивный и вдохновляющий, конкретный совет на день)"

    prompt = f"""Напиши короткое утреннее сообщение на русском языке.

Структура:
1. Один интересный и неожиданный факт о городе {city} который мало кто знает (2-3 предложения){zodiac_part}

Формат ответа (строго):
🏛 Факт о {city}:
[факт]
{"" if not zodiac or zodiac == "skip" else f"\n{zodiac} сегодня:\n[гороскоп]"}

Стиль: тёплый, дружеский, живой язык. Никакого markdown форматирования."""

    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=350,
    )
    return response.choices[0].message.content.strip()

async def get_morning_msg(city, zodiac):
    return await asyncio.get_event_loop().run_in_executor(None, _morning_sync, city, zodiac)

# ──────────────────────────────────────────────────────────────
# GOOGLE SHEETS
# ──────────────────────────────────────────────────────────────
def _log_sync(user_id, name, username, msg_type, text, resp_len=0):
    try:
        creds = Credentials.from_service_account_file(
            CREDENTIALS, scopes=["https://www.googleapis.com/auth/spreadsheets"])
        sheet = gspread.authorize(creds).open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
        now   = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        uname = f"@{username}" if username else "(нет username)"
        sheet.append_row([now, str(user_id), name, uname, msg_type, text[:500], str(resp_len)])
    except Exception as e:
        logging.error(f"Sheets error: {e}")

async def log_sheets(user_id, name, username, msg_type, text, resp_len=0):
    await asyncio.get_event_loop().run_in_executor(None, _log_sync, user_id, name, username, msg_type, text, resp_len)

def _log_review_sync(user_id, name, username, city, review_text):
    try:
        creds = Credentials.from_service_account_file(
            CREDENTIALS, scopes=["https://www.googleapis.com/auth/spreadsheets"])
        sheet = gspread.authorize(creds).open_by_key(SPREADSHEET_ID).worksheet(REVIEW_SHEET)
        now   = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        uname = f"@{username}" if username else "(нет username)"
        sheet.append_row([now, str(user_id), name, uname, "Отзыв", city, review_text])
    except Exception as e:
        logging.error(f"Review sheets error: {e}")

async def log_review(user_id, name, username, city, review_text):
    await asyncio.get_event_loop().run_in_executor(None, _log_review_sync, user_id, name, username, city, review_text)

# ──────────────────────────────────────────────────────────────
# УТРЕННЯЯ РАССЫЛКА
# ──────────────────────────────────────────────────────────────
async def send_morning_messages():
    users = get_all_users_for_morning()
    for user_id, city, zodiac in users:
        try:
            msg_text = await get_morning_msg(city, zodiac)
            full_text = f"Доброе утро! ☀️\n\n{msg_text}\n\nЧем могу помочь сегодня? 👇"
            await bot.send_message(user_id, full_text, reply_markup=MAIN_KB, disable_web_page_preview=True)
            await asyncio.sleep(0.1)
        except Exception as e:
            logging.error(f"Morning error {user_id}: {e}")

async def morning_scheduler():
    while True:
        now    = datetime.now(MOSCOW_TZ)
        target = now.replace(hour=9, minute=0, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())
        await send_morning_messages()

# ──────────────────────────────────────────────────────────────
# ХЕЛПЕРЫ
# ──────────────────────────────────────────────────────────────
def full_name(user):
    return " ".join(p for p in [user.first_name or "", user.last_name or ""] if p).strip() or "—"

# ──────────────────────────────────────────────────────────────
# ОБРАБОТЧИКИ
# ──────────────────────────────────────────────────────────────

@dp.message(Command("start"))
async def cmd_start(msg: Message, state: FSMContext):
    user     = msg.from_user
    name     = full_name(user)
    existing = get_user(user.id)

    if existing and existing[3]:
        city     = existing[3]
        city_key = existing[4]
        await msg.answer(
            f"Привет, {user.first_name or 'друг'}! 👋\n\n"
            f"Твой город: {city_key}\n\n"
            f"Жми кнопку или спрашивай — найду лучшее 👇",
            reply_markup=MAIN_KB,
            disable_web_page_preview=True,
        )
        save_user(user.id, name, user.username, city, city_key)
    else:
        save_user(user.id, name, user.username)
        await msg.answer(
            f"Привет, {user.first_name or 'друг'}! 👋\n\n"
            "Я AI Местный — гид по городам России глазами местных жителей.\n\n"
            "Покажу кафе, маршруты и события — те о которых не пишут в путеводителях.\n\n"
            "Выбери свой город 👇",
            reply_markup=CITY_KEYBOARD,
        )
        await state.set_state(UserState.choosing_city)

    asyncio.create_task(log_sheets(user.id, name, user.username, "Команда", "/start"))


@dp.message(UserState.choosing_city)
async def handle_city_choice(msg: Message, state: FSMContext):
    text = msg.text.strip()
    if text not in CITIES:
        await msg.answer("Выбери город из списка 👇", reply_markup=CITY_KEYBOARD)
        return

    city = CITIES[text]["name"]
    update_city(msg.from_user.id, city, text)
    await state.clear()

    # Спрашиваем знак зодиака только если ещё не спрашивали
    if not has_zodiac_set(msg.from_user.id):
        await msg.answer(
            f"Отлично, {city}! 🎉\n\n"
            f"Последний штрих ✨\n\n"
            f"Укажи свой знак зодиака — каждое утро буду присылать персональный гороскоп на день 🔮\n\n"
            f"Если не хочешь — нажми Пропустить.",
            reply_markup=ZODIAC_KEYBOARD,
        )
        await state.set_state(UserState.choosing_zodiac)
    else:
        await msg.answer(
            f"Город изменён на {text} 🎉\n\nЖми кнопку или спрашивай 👇",
            reply_markup=MAIN_KB,
            disable_web_page_preview=True,
        )


@dp.message(UserState.choosing_zodiac)
async def handle_zodiac_choice(msg: Message, state: FSMContext):
    text = msg.text.strip()

    if text == "⏭ Пропустить":
        update_zodiac(msg.from_user.id, "skip")
        await state.clear()
        city, city_key = get_user_city(msg.from_user.id)
        await msg.answer(
            f"Хорошо! Буду присылать интересные факты о {city} каждое утро ☀️\n\n"
            f"Жми кнопку или спрашивай 👇",
            reply_markup=MAIN_KB,
            disable_web_page_preview=True,
        )
        return

    if text in ZODIAC_SIGNS:
        update_zodiac(msg.from_user.id, text)
        await state.clear()
        city, city_key = get_user_city(msg.from_user.id)
        await msg.answer(
            f"{text} — отличный выбор! 🔮\n\n"
            f"Каждое утро в 9:00 тебя будет ждать факт о {city} и персональный гороскоп.\n\n"
            f"Жми кнопку или спрашивай 👇",
            reply_markup=MAIN_KB,
            disable_web_page_preview=True,
        )
        return

    await msg.answer("Выбери знак зодиака из списка или нажми Пропустить 👇", reply_markup=ZODIAC_KEYBOARD)


@dp.message(Command("zodiac"))
async def cmd_zodiac(msg: Message, state: FSMContext):
    await msg.answer(
        "🔮 Выбери свой знак зодиака — обновлю гороскоп в утренних сообщениях:",
        reply_markup=ZODIAC_KEYBOARD,
    )
    await state.set_state(UserState.choosing_zodiac)


@dp.message(F.text == "🏠 Главное меню")
async def btn_main_menu(msg: Message, state: FSMContext):
    await state.clear()
    user = msg.from_user
    city, city_key = get_user_city(user.id)
    await msg.answer(
        f"Главное меню 🏠\n\nТвой город: {city_key}\n\nЧем могу помочь? 👇",
        reply_markup=MAIN_KB,
        disable_web_page_preview=True,
    )


@dp.message(F.text == "🏙 Сменить город")
async def change_city(msg: Message, state: FSMContext):
    await msg.answer("Выбери новый город 👇", reply_markup=CITY_KEYBOARD)
    await state.set_state(UserState.choosing_city)


@dp.message(Command("help"))
async def cmd_help(msg: Message):
    await msg.answer(
        "Как пользоваться AI Местным:\n\n"
        "1. Жми кнопку с темой — получишь подборку мест.\n\n"
        "2. Или пиши обычным языком — чем больше деталей тем точнее ответ.\n\n"
        "3. Смени город кнопкой 🏙 Сменить город.\n\n"
        "4. Каждое утро в 9:00 — факт о городе и гороскоп.\n\n"
        "/zodiac — сменить знак зодиака\n"
        "/start — главное меню\n"
        "/about — о проекте",
        reply_markup=MAIN_KB,
    )


@dp.message(Command("about"))
async def cmd_about(msg: Message):
    await _send_about(msg)


@dp.message(F.text == "ℹ️ О проекте")
async def btn_about(msg: Message):
    await _send_about(msg)


async def _send_about(msg: Message):
    await msg.answer(
        "AI Местный — гид по городам России\n\n"
        "Показываю города глазами тех кто там живёт:\n"
        "Места которых нет в топе Google Maps\n"
        "Кафе куда ходят местные а не туристы\n"
        "События о которых узнают за день\n"
        "Маршруты без толпы\n\n"
        "Города: Сочи, Москва, Санкт-Петербург, Казань, Краснодар, Калининград, Екатеринбург, Нижний Новгород.\n\n"
        "Замечания и идеи — жми Поддержка.\n\n"
        f"Тестовая версия.{BACK_TEXT}",
        reply_markup=MAIN_KB,
        disable_web_page_preview=True,
    )


@dp.message(F.text == "🛠 Поддержка")
async def btn_support(msg: Message):
    user  = msg.from_user
    uname = f"@{user.username}" if user.username else "(нет username)"
    city, _ = get_user_city(user.id)
    await msg.answer(
        f"Напиши замечание или идею — передам создателю.\n\nИли пиши напрямую: @demo23rus{BACK_TEXT}",
        reply_markup=MAIN_KB,
    )
    try:
        zodiac = get_user_zodiac(user.id)
        await bot.send_message(
            OWNER_ID,
            f"Поддержка\nИмя: {full_name(user)}\nUsername: {uname}\nID: {user.id}\nГород: {city}\nЗодиак: {zodiac or 'не указан'}",
        )
    except Exception as e:
        logging.error(f"Owner notify: {e}")


@dp.message(F.text == "✏️ Свой вопрос")
async def btn_own(msg: Message):
    city, _ = get_user_city(msg.from_user.id)
    await msg.answer(
        f"Пиши любой вопрос про {city} — отвечу 🚀",
        reply_markup=MAIN_KB,
    )


@dp.message(F.text == "💬 Оставить отзыв")
async def btn_review(msg: Message, state: FSMContext):
    await msg.answer(
        "💬 Напиши свой отзыв или пожелание — читаю всё и учитываю при развитии бота.\n\n"
        "Что понравилось? Что можно улучшить? Чего не хватает?",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="❌ Отмена")]],
            resize_keyboard=True,
        ),
    )
    await state.set_state(UserState.writing_review)


@dp.message(UserState.writing_review)
async def handle_review(msg: Message, state: FSMContext):
    text = msg.text.strip()
    if text == "❌ Отмена":
        await state.clear()
        await msg.answer("Хорошо, в другой раз 👌", reply_markup=MAIN_KB)
        return
    user    = msg.from_user
    city, _ = get_user_city(user.id)
    await state.clear()
    await msg.answer(
        "Спасибо за отзыв! 🙏 Это очень помогает делать бота лучше." + BACK_TEXT,
        reply_markup=MAIN_KB,
    )
    asyncio.create_task(log_review(user.id, full_name(user), user.username, city, text))


# ── Голосовые ─────────────────────────────────────────────────
@dp.message(F.voice)
async def handle_voice(msg: Message):
    await msg.answer("🎤 Распознаю голосовое... подожди немного 😊")
    tmp_path = None
    try:
        file     = await bot.get_file(msg.voice.file_id)
        tmp_file = tempfile.NamedTemporaryFile(suffix=".ogg", delete=False)
        tmp_path = tmp_file.name
        tmp_file.close()
        await bot.download_file(file.file_path, tmp_path)
        with open(tmp_path, "rb") as audio:
            transcript = client.audio.transcriptions.create(
                model="whisper-1", file=audio, language="ru")
        text = transcript.text.strip()
        if not text:
            await msg.answer(f"Не смог распознать. Попробуй написать текстом 👇{BACK_TEXT}", reply_markup=MAIN_KB)
            return
        city, _ = get_user_city(msg.from_user.id)
        thinking = await msg.answer(f"Распознал: {text}\n\nИщу в {city}...")
        answer   = await ask_ai(text, city)
        try:
            await thinking.delete()
        except Exception:
            pass
        await msg.answer(answer + BACK_TEXT, reply_markup=MAIN_KB, disable_web_page_preview=True)
        increment_requests(msg.from_user.id)
        asyncio.create_task(log_sheets(
            msg.from_user.id, full_name(msg.from_user),
            msg.from_user.username, "Голосовое", f"🎤 {text}", len(answer)))
    except Exception as e:
        logging.error(f"Voice error: {e}")
        await msg.answer(f"Не смог обработать голосовое. Попробуй написать текстом 👇{BACK_TEXT}", reply_markup=MAIN_KB)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


# ── Текстовые сообщения ───────────────────────────────────────
@dp.message(F.text)
async def handle_text(msg: Message, state: FSMContext):
    text = msg.text.strip()
    if text in SYSTEM_BUTTONS or text in CITIES or text in ZODIAC_SIGNS or text == "⏭ Пропустить":
        return
    user     = msg.from_user
    city, _  = get_user_city(user.id)
    msg_type = "Кнопка тематическая" if text in THEME_BUTTONS else "Свободный запрос"
    thinking = await msg.answer(f"Ищу в {city}...")
    try:
        answer = await ask_ai(text, city)
        try:
            await thinking.delete()
        except Exception:
            pass
        await msg.answer(answer + BACK_TEXT, reply_markup=MAIN_KB, disable_web_page_preview=True)
        increment_requests(user.id)
        asyncio.create_task(log_sheets(
            user.id, full_name(user), user.username, msg_type, text, len(answer)))
    except Exception as e:
        logging.error(f"Text error: {e}")
        try:
            await thinking.delete()
        except Exception:
            pass
        await msg.answer(f"Что-то пошло не так. Попробуй ещё раз.{BACK_TEXT}", reply_markup=MAIN_KB)


# ── Фото, стикеры и прочее ────────────────────────────────────
@dp.message()
async def fallback(msg: Message):
    await msg.answer(
        f"Я понимаю только текст и голосовые сообщения.\n\nФото, стикеры и документы пока не поддерживаются.\n\nНапиши что ищешь или жми кнопку 👇",
        reply_markup=MAIN_KB,
    )


# ──────────────────────────────────────────────────────────────
# ЗАПУСК
# ──────────────────────────────────────────────────────────────
async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    init_db()
    logging.info("AI Местный v4 запущен")
    asyncio.create_task(morning_scheduler())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
