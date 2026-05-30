#!/usr/bin/env python3
"""
AI Местный — мультигород v5
Bot: @mestniy_guide_bot
File: /root/bot2.py
Service: sochi-test
"""

import asyncio
import logging
import os
import sqlite3
import tempfile
import time
import base64
from datetime import datetime, timedelta
import pytz

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
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
FLOOD_SECONDS  = 4  # минимум секунд между запросами

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

# Города Крыма как отдельный словарь
CRIMEA_CITIES = {
    "🌺 Ялта":          {"name": "Ялта"},
    "⚓ Севастополь":   {"name": "Севастополь"},
    "🏛 Симферополь":   {"name": "Симферополь"},
    "🏖 Евпатория":     {"name": "Евпатория"},
    "🗼 Керчь":         {"name": "Керчь"},
}

# Все допустимые кнопки городов (основные + крым)
ALL_CITY_BUTTONS = set(CITIES.keys()) | set(CRIMEA_CITIES.keys()) | {"🏖 Крым"}

# Ссылки "Куда сходить" по городам
CITY_EVENTS = {
    "Сочи":            ("https://kudago.com/sochi/", "https://afisha.yandex.ru/sochi"),
    "Москва":          ("https://kudago.com/msk/", "https://afisha.yandex.ru/moscow"),
    "Санкт-Петербург": ("https://kudago.com/spb/", "https://afisha.yandex.ru/saint-petersburg"),
    "Казань":          ("https://kudago.com/kzn/", "https://afisha.yandex.ru/kazan"),
    "Краснодар":       ("https://kudago.com/krd/", "https://afisha.yandex.ru/krasnodar"),
    "Калининград":     ("https://kudago.com/klg/", "https://afisha.yandex.ru/kaliningrad"),
    "Екатеринбург":    ("https://kudago.com/ekb/", "https://afisha.yandex.ru/yekaterinburg"),
    "Нижний Новгород": ("https://kudago.com/nnv/", "https://afisha.yandex.ru/nizhny-novgorod"),
    "Ялта":            ("https://kudago.com/", "https://afisha.yandex.ru/yalta"),
    "Севастополь":     ("https://kudago.com/", "https://afisha.yandex.ru/sevastopol"),
    "Симферополь":     ("https://kudago.com/", "https://afisha.yandex.ru/simferopol"),
    "Евпатория":       ("https://kudago.com/", "https://afisha.yandex.ru/evpatoria"),
    "Керчь":           ("https://kudago.com/", "https://afisha.yandex.ru/kerch"),
}

# Короткие фразы — отвечаем без GPT
SHORT_REPLIES = {
    "привет": "Привет! 👋 Жми кнопку или пиши что ищешь — найду лучшее 😊",
    "хай": "Привет! 👋 Жми кнопку или пиши что ищешь — найду лучшее 😊",
    "hello": "Привет! 👋 Жми кнопку или пиши что ищешь — найду лучшее 😊",
    "спасибо": "Пожалуйста! 🙏 Если нужно ещё что-то — пиши 😊",
    "спс": "Пожалуйста! 🙏 Если нужно ещё что-то — пиши 😊",
    "благодарю": "Пожалуйста! 🙏 Если нужно ещё что-то — пиши 😊",
    "ок": "Отлично! 👌 Пиши если что-то нужно 😊",
    "окей": "Отлично! 👌 Пиши если что-то нужно 😊",
    "ok": "Отлично! 👌 Пиши если что-то нужно 😊",
    "👍": "😊 Всегда рад помочь! Пиши если нужно.",
    "👌": "😊 Всегда рад помочь! Пиши если нужно.",
    "отлично": "Рад помочь! 😊 Что-нибудь ещё найти?",
    "класс": "Рад помочь! 😊 Что-нибудь ещё найти?",
    "супер": "Рад помочь! 😊 Что-нибудь ещё найти?",
    "хорошо": "Отлично! 👌 Пиши если что-то нужно 😊",
    "понял": "Отлично! 👌 Пиши если что-то нужно 😊",
}

# ──────────────────────────────────────────────────────────────
# КЛАВИАТУРЫ
# ──────────────────────────────────────────────────────────────
CITY_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🌊 Сочи"),            KeyboardButton(text="🏙 Москва")],
        [KeyboardButton(text="🏛 Санкт-Петербург"), KeyboardButton(text="🕌 Казань")],
        [KeyboardButton(text="🌿 Краснодар"),       KeyboardButton(text="🌅 Калининград")],
        [KeyboardButton(text="💎 Екатеринбург"),    KeyboardButton(text="🏯 Нижний Новгород")],
        [KeyboardButton(text="🏖 Крым")],
    ],
    resize_keyboard=True,
)

CRIMEA_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🌺 Ялта"),        KeyboardButton(text="⚓ Севастополь")],
        [KeyboardButton(text="🏛 Симферополь"), KeyboardButton(text="🏖 Евпатория")],
        [KeyboardButton(text="🗼 Керчь")],
        [KeyboardButton(text="◀️ Назад к городам")],
    ],
    resize_keyboard=True,
)

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

MAIN_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="✏️ Свой вопрос"),      KeyboardButton(text="🏙 Сменить город")],
        [KeyboardButton(text="🍽 Где поесть"),        KeyboardButton(text="☕ Кофе с видом")],
        [KeyboardButton(text="🌅 На рассвет"),        KeyboardButton(text="🎭 Куда сходить")],
        [KeyboardButton(text="👨‍👩‍👧 С детьми"),       KeyboardButton(text="💑 Романтика")],
        [KeyboardButton(text="🏔 На природу"),        KeyboardButton(text="🌃 Вечер")],
        [KeyboardButton(text="🗺 Маршрут на день"),   KeyboardButton(text="💬 Местный советует")],
        [KeyboardButton(text="🛠 Поддержка"),         KeyboardButton(text="ℹ️ О проекте")],
        [KeyboardButton(text="💬 Оставить отзыв"),    KeyboardButton(text="🔔 Утренние сообщения")],
        [KeyboardButton(text="🏠 Главное меню")],
    ],
    resize_keyboard=True,
    one_time_keyboard=False,
)

PHOTO_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🔍 Определить место"), KeyboardButton(text="✏️ Напишу сам")],
    ],
    resize_keyboard=True,
)

ZODIAC_SIGNS = [
    "♈ Овен", "♉ Телец", "♊ Близнецы", "♋ Рак",
    "♌ Лев", "♍ Дева", "♎ Весы", "♏ Скорпион",
    "♐ Стрелец", "♑ Козерог", "♒ Водолей", "♓ Рыбы",
]

THEME_BUTTONS = {
    "🍽 Где поесть", "☕ Кофе с видом", "🌅 На рассвет", "🎭 Куда сходить",
    "👨‍👩‍👧 С детьми", "💑 Романтика", "🏔 На природу", "🌃 Вечер",
    "🗺 Маршрут на день", "💬 Местный советует",
}
SYSTEM_BUTTONS = {
    "✏️ Свой вопрос", "🛠 Поддержка", "ℹ️ О проекте",
    "🏙 Сменить город", "💬 Оставить отзыв", "🏠 Главное меню",
    "🔔 Утренние сообщения", "🔍 Определить место", "✏️ Напишу сам",
    "◀️ Назад к городам",
}

BACK_TEXT = "\n\nЧто ещё найти? Жми кнопку или пиши 👇"

# ──────────────────────────────────────────────────────────────
# FSM
# ──────────────────────────────────────────────────────────────
class UserState(StatesGroup):
    choosing_city    = State()
    choosing_crimea  = State()
    choosing_zodiac  = State()
    writing_review   = State()
    waiting_photo_action = State()  # ждём что делать с фото

# ──────────────────────────────────────────────────────────────
# КЛИЕНТЫ
# ──────────────────────────────────────────────────────────────
bot    = Bot(token=BOT_TOKEN)
dp     = Dispatcher(storage=MemoryStorage())
client = OpenAI(api_key=OPENAI_KEY, base_url="https://api.proxyapi.ru/openai/v1")

# Антифлуд: user_id -> timestamp последнего запроса
last_request_time: dict[int, float] = {}

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
            morning_notify INTEGER DEFAULT 1,
            ref_by         INTEGER DEFAULT NULL
        )
    """)
    # Миграции для старых баз
    for col, definition in [
        ("zodiac",         "TEXT DEFAULT NULL"),
        ("morning_notify", "INTEGER DEFAULT 1"),
        ("ref_by",         "INTEGER DEFAULT NULL"),
    ]:
        try:
            c.execute(f"ALTER TABLE users ADD COLUMN {col} {definition}")
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

def save_user(user_id, name, username, city="Сочи", city_emoji="🌊 Сочи", ref_by=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    c.execute("""
        INSERT INTO users (user_id, name, username, city, city_emoji, registered_at, last_active, ref_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            name=excluded.name, username=excluded.username, last_active=excluded.last_active
    """, (user_id, name, username or "", city, city_emoji, now, now, ref_by))
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

def toggle_morning(user_id) -> bool:
    """Переключает morning_notify, возвращает новое значение"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT morning_notify FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    new_val = 0 if (row and row[0] == 1) else 1
    c.execute("UPDATE users SET morning_notify=? WHERE user_id=?", (new_val, user_id))
    conn.commit()
    conn.close()
    return bool(new_val)

def increment_requests(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    c.execute(
        "UPDATE users SET total_requests=total_requests+1, last_active=? WHERE user_id=?",
        (now, user_id)
    )
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

def get_morning_status(user_id) -> bool:
    row = get_user(user_id)
    if row and len(row) > 10:
        return bool(row[10])
    return True

def has_zodiac_set(user_id):
    """True если зодиак уже выбирали (включая 'skip')"""
    row = get_user(user_id)
    if not row or len(row) <= 5:
        return False
    zodiac = row[5]
    # Зодиак задан если значение не NULL и не пустая строка
    return zodiac is not None and zodiac != ""

def get_stats():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    total = c.fetchone()[0]
    c.execute("SELECT city, COUNT(*) as cnt FROM users GROUP BY city ORDER BY cnt DESC LIMIT 5")
    top_cities = c.fetchall()
    today = datetime.now().strftime("%d.%m.%Y")
    c.execute("SELECT COUNT(*) FROM users WHERE last_active LIKE ?", (f"{today}%",))
    active_today = c.fetchone()[0]
    c.execute("SELECT SUM(total_requests) FROM users")
    total_req = c.fetchone()[0] or 0
    conn.close()
    return total, top_cities, active_today, total_req

# ──────────────────────────────────────────────────────────────
# АНТИФЛУД
# ──────────────────────────────────────────────────────────────
def is_flood(user_id: int) -> bool:
    now = time.time()
    last = last_request_time.get(user_id, 0)
    if now - last < FLOOD_SECONDS:
        return True
    last_request_time[user_id] = now
    return False

# ──────────────────────────────────────────────────────────────
# GPT
# ──────────────────────────────────────────────────────────────
def get_system_prompt(city):
    events = CITY_EVENTS.get(city, ("https://kudago.com/", "https://afisha.yandex.ru/"))
    kudago_url, afisha_url = events

    crimea_note = ""
    if city in ("Ялта", "Севастополь", "Симферополь", "Евпатория", "Керчь"):
        crimea_note = f"""
ОСОБЕННОСТЬ КРЫМА:
- Учитывай сезонность: летом — пляжи, зимой — горы и история.
- Делай акцент на уникальных крымских местах: набережные, крепости, виноградники, горные маршруты.
- Для {city} учитывай специфику города (Ялта — курорт, Севастополь — история флота и т.д.)
"""

    return f"""Ты — AI Местный, виртуальный друг который отлично знает город {city}. Живёшь там много лет.

ТВОЯ ЗАДАЧА: помогать людям находить интересные места и активности в городе {city}.

СТИЛЬ ОБЩЕНИЯ:
- Говори как живой человек, тепло и дружелюбно. Без канцелярита.
- Можно на ты.
- СТРОГО ЗАПРЕЩЕНО использовать markdown: никаких **, __, ##, [], ``. Совсем.
- Эмодзи умеренно — 1-2 на место, не больше.
{crimea_note}
ФОРМАТ КАЖДОГО МЕСТА:
1. Название места
📍 Район или улица
💚 Доступные цены / 💛 Средние цены / 💰 Цены выше среднего (выбери одно)
✨ Фишка — почему стоит идти (1-2 предложения)
🗺 Яндекс.Карты: https://yandex.ru/maps/?text=[название места]+[район]+{city}
🗺 2ГИС: https://2gis.ru/search/[название места]+{city}
⚠️ Актуальные цены и часы уточняйте по телефону или по ссылкам выше

ВАЖНО для ссылок: замени [название места] на реальное название, [район] на район. Не пиши скобки в ссылке.

ПРАВИЛА:
- Никогда не пиши конкретные цены в рублях.
- Никогда не выдумывай телефоны.
- Давай 5-7 мест в ответе.
- Если человек нажал кнопку — СРАЗУ давай подборку БЕЗ ВОПРОСОВ.
- Никогда не спрашивай про бюджет или компанию — человек сам уточнит.
- Только если город большой (Москва, СПб) — можно спросить район одним вопросом.

КНОПКА "КУДА СХОДИТЬ":
Дай ссылки на афишу:
- {kudago_url}
- {afisha_url}

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
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _ask_sync, text, city)


def _city_intro_sync(city):
    """Короткая визитка города при первом выборе"""
    prompt = (
        f"Напиши короткую живую визитку города {city} — 2-3 предложения. "
        f"Что делает этот город особенным? Без перечислений, без markdown. "
        f"Тёплый дружеский тон."
    )
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=150,
    )
    return response.choices[0].message.content.strip()


async def get_city_intro(city):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _city_intro_sync, city)


def _morning_sync(city, zodiac):
    has_zodiac = zodiac and zodiac != "skip"

    structure = f"1. Один интересный и неожиданный факт о городе {city} который мало кто знает (2-3 предложения)"
    fmt = f"🏛 Факт о {city}:\n[факт]"

    if has_zodiac:
        structure += f"\n2. Персональный гороскоп для знака {zodiac} на сегодня (2-3 предложения, позитивный и вдохновляющий, конкретный совет на день)"
        fmt += f"\n\n{zodiac} сегодня:\n[гороскоп]"

    prompt = (
        "Напиши короткое утреннее сообщение на русском языке.\n\n"
        f"Структура:\n{structure}\n\n"
        f"Формат ответа (строго):\n{fmt}\n\n"
        "Стиль: тёплый, дружеский, живой язык. Никакого markdown форматирования."
    )
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=350,
    )
    return response.choices[0].message.content.strip()


async def get_morning_msg(city, zodiac):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _morning_sync, city, zodiac)


def _identify_place_sync(image_base64: str, city: str) -> str:
    """Определяет место по фото через GPT-4o Vision"""
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_base64}",
                            "detail": "low"
                        }
                    },
                    {
                        "type": "text",
                        "text": (
                            f"Посмотри на фото и определи что это за место. "
                            f"Пользователь находится в городе {city}.\n\n"
                            f"Ответь в таком формате (без markdown):\n"
                            f"Место: [название если знаешь, или описание]\n"
                            f"Город/район: [город и район если можешь определить]\n"
                            f"Адрес: [адрес если знаешь]\n"
                            f"Координаты: [если знаешь]\n"
                            f"Описание: [2-3 предложения что это за место]\n\n"
                            f"Если не можешь точно определить — честно скажи что именно видишь на фото "
                            f"и предложи как это можно найти. Не выдумывай адреса."
                        )
                    }
                ]
            }
        ],
        max_tokens=500,
    )
    return response.choices[0].message.content.strip()


async def identify_place(image_base64: str, city: str) -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _identify_place_sync, image_base64, city)


# ──────────────────────────────────────────────────────────────
# GOOGLE SHEETS
# ──────────────────────────────────────────────────────────────
def _get_sheet(sheet_name):
    creds = Credentials.from_service_account_file(
        CREDENTIALS, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    return gspread.authorize(creds).open_by_key(SPREADSHEET_ID).worksheet(sheet_name)


def _log_sync(user_id, name, username, msg_type, text, resp_len=0):
    try:
        sheet = _get_sheet(SHEET_NAME)
        now   = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        uname = f"@{username}" if username else "(нет username)"
        sheet.append_row([now, str(user_id), name, uname, msg_type, text[:500], str(resp_len)])
    except Exception as e:
        logging.error(f"Sheets error: {e}")


async def log_sheets(user_id, name, username, msg_type, text, resp_len=0):
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _log_sync, user_id, name, username, msg_type, text, resp_len)


def _log_review_sync(user_id, name, username, city, review_text):
    try:
        sheet = _get_sheet(REVIEW_SHEET)
        now   = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        uname = f"@{username}" if username else "(нет username)"
        sheet.append_row([now, str(user_id), name, uname, "Отзыв", city, review_text])
    except Exception as e:
        logging.error(f"Review sheets error: {e}")


async def log_review(user_id, name, username, city, review_text):
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _log_review_sync, user_id, name, username, city, review_text)


# ──────────────────────────────────────────────────────────────
# УТРЕННЯЯ РАССЫЛКА
# ──────────────────────────────────────────────────────────────
async def send_morning_messages():
    users = get_all_users_for_morning()
    logging.info(f"Утренняя рассылка: {len(users)} пользователей")
    for user_id, city, zodiac in users:
        try:
            msg_text  = await get_morning_msg(city, zodiac)
            full_text = f"Доброе утро! ☀️\n\n{msg_text}\n\nЧем могу помочь сегодня? 👇"
            await bot.send_message(user_id, full_text, reply_markup=MAIN_KB, disable_web_page_preview=True)
            await asyncio.sleep(0.1)
        except Exception as e:
            logging.error(f"Morning error {user_id}: {e}")


async def morning_scheduler():
    while True:
        try:
            now    = datetime.now(MOSCOW_TZ)
            target = now.replace(hour=9, minute=0, second=0, microsecond=0)
            if now >= target:
                target += timedelta(days=1)
            wait_seconds = (target - now).total_seconds()
            logging.info(f"Следующая рассылка через {int(wait_seconds/3600)}ч {int((wait_seconds%3600)/60)}м")
            await asyncio.sleep(wait_seconds)
            await send_morning_messages()
        except Exception as e:
            logging.error(f"Scheduler error: {e}")
            await asyncio.sleep(60)  # при ошибке подождать минуту и продолжить


# ──────────────────────────────────────────────────────────────
# ХЕЛПЕРЫ
# ──────────────────────────────────────────────────────────────
def full_name(user):
    return " ".join(p for p in [user.first_name or "", user.last_name or ""] if p).strip() or "—"


# ──────────────────────────────────────────────────────────────
# ОБРАБОТЧИКИ
# ──────────────────────────────────────────────────────────────

@dp.message(CommandStart())
async def cmd_start(msg: Message, state: FSMContext):
    user     = msg.from_user
    name     = full_name(user)
    existing = get_user(user.id)

    # Реферальная система: /start ref_12345678
    ref_by = None
    args = msg.text.split() if msg.text else []
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            ref_by = int(args[1].replace("ref_", ""))
            if ref_by == user.id:
                ref_by = None  # нельзя пригласить себя
        except ValueError:
            ref_by = None

    if existing and existing[3]:
        city     = existing[3]
        city_key = existing[4]
        save_user(user.id, name, user.username, city, city_key)
        await msg.answer(
            f"Привет, {user.first_name or 'друг'}! 👋\n\n"
            f"Твой город: {city_key}\n\n"
            f"Жми кнопку или спрашивай — найду лучшее 👇",
            reply_markup=MAIN_KB,
            disable_web_page_preview=True,
        )
    else:
        save_user(user.id, name, user.username, ref_by=ref_by)
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
    text = msg.text.strip() if msg.text else ""

    # Крым — показываем подменю
    if text == "🏖 Крым":
        await msg.answer(
            "🏖 Крым — выбери город 👇",
            reply_markup=CRIMEA_KEYBOARD,
        )
        await state.set_state(UserState.choosing_crimea)
        return

    if text not in CITIES:
        await msg.answer("Выбери город из списка 👇", reply_markup=CITY_KEYBOARD)
        return

    await _finalize_city_choice(msg, state, text, CITIES[text]["name"], is_new=not has_zodiac_set(msg.from_user.id))


@dp.message(UserState.choosing_crimea)
async def handle_crimea_choice(msg: Message, state: FSMContext):
    text = msg.text.strip() if msg.text else ""

    if text == "◀️ Назад к городам":
        await msg.answer("Выбери город 👇", reply_markup=CITY_KEYBOARD)
        await state.set_state(UserState.choosing_city)
        return

    if text not in CRIMEA_CITIES:
        await msg.answer("Выбери город Крыма из списка 👇", reply_markup=CRIMEA_KEYBOARD)
        return

    await _finalize_city_choice(msg, state, text, CRIMEA_CITIES[text]["name"], is_new=not has_zodiac_set(msg.from_user.id))


async def _finalize_city_choice(msg: Message, state: FSMContext, city_key: str, city: str, is_new: bool):
    """Общая логика после выбора города"""
    update_city(msg.from_user.id, city, city_key)
    await state.clear()

    if is_new:
        # Визитка города + спрашиваем зодиак
        try:
            intro = await get_city_intro(city)
        except Exception:
            intro = f"{city} — отличный выбор!"

        await msg.answer(
            f"Отлично, {city}! 🎉\n\n"
            f"{intro}\n\n"
            f"Последний штрих ✨\n\n"
            f"Укажи свой знак зодиака — каждое утро буду присылать персональный гороскоп 🔮\n\n"
            f"Если не хочешь — нажми Пропустить.",
            reply_markup=ZODIAC_KEYBOARD,
        )
        await state.set_state(UserState.choosing_zodiac)
    else:
        await msg.answer(
            f"Город изменён на {city_key} 🎉\n\nЖми кнопку или спрашивай 👇",
            reply_markup=MAIN_KB,
            disable_web_page_preview=True,
        )


@dp.message(UserState.choosing_zodiac)
async def handle_zodiac_choice(msg: Message, state: FSMContext):
    text = msg.text.strip() if msg.text else ""

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


@dp.message(Command("stats"))
async def cmd_stats(msg: Message):
    if msg.from_user.id != OWNER_ID:
        return
    total, top_cities, active_today, total_req = get_stats()
    cities_text = "\n".join([f"  {city}: {cnt} чел." for city, cnt in top_cities])
    await msg.answer(
        f"📊 Статистика AI Местный\n\n"
        f"👥 Всего пользователей: {total}\n"
        f"🟢 Активны сегодня: {active_today}\n"
        f"💬 Всего запросов: {total_req}\n\n"
        f"🏙 Топ городов:\n{cities_text}",
    )


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


@dp.message(F.text == "🔔 Утренние сообщения")
async def btn_morning_toggle(msg: Message):
    new_status = toggle_morning(msg.from_user.id)
    if new_status:
        await msg.answer(
            "🔔 Утренние сообщения включены!\n\nКаждый день в 9:00 буду присылать факт о городе и гороскоп ☀️",
            reply_markup=MAIN_KB,
        )
    else:
        await msg.answer(
            "🔕 Утренние сообщения отключены.\n\nКогда захочешь вернуть — нажми эту кнопку снова.",
            reply_markup=MAIN_KB,
        )


@dp.message(Command("help"))
async def cmd_help(msg: Message):
    await msg.answer(
        "Как пользоваться AI Местным:\n\n"
        "1. Жми кнопку с темой — получишь подборку мест.\n\n"
        "2. Или пиши обычным языком — чем больше деталей тем точнее ответ.\n\n"
        "3. Смени город кнопкой 🏙 Сменить город.\n\n"
        "4. Каждое утро в 9:00 — факт о городе и гороскоп.\n\n"
        "5. Скинь фото места — попробую определить что это.\n\n"
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
        "Города: Сочи, Москва, Санкт-Петербург, Казань, Краснодар, Калининград, "
        "Екатеринбург, Нижний Новгород, Крым (Ялта, Севастополь, Симферополь, Евпатория, Керчь).\n\n"
        "Замечания и идеи — жми Поддержка.\n\n"
        f"Тестовая версия.{BACK_TEXT}",
        reply_markup=MAIN_KB,
        disable_web_page_preview=True,
    )


@dp.message(F.text == "🛠 Поддержка")
async def btn_support(msg: Message):
    user  = msg.from_user
    city, _ = get_user_city(user.id)
    await msg.answer(
        f"Напиши замечание или идею — передам создателю.\n\nИли пиши напрямую: @demo23rus{BACK_TEXT}",
        reply_markup=MAIN_KB,
    )


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
    text = msg.text.strip() if msg.text else ""
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


# ── Фото ──────────────────────────────────────────────────────
@dp.message(F.photo)
async def handle_photo(msg: Message, state: FSMContext):
    await state.update_data(photo_file_id=msg.photo[-1].file_id)
    await state.set_state(UserState.waiting_photo_action)
    await msg.answer(
        "Вижу фото! 📸 Что хочешь сделать?",
        reply_markup=PHOTO_KB,
    )


@dp.message(UserState.waiting_photo_action, F.text == "🔍 Определить место")
async def handle_identify_place(msg: Message, state: FSMContext):
    data = await state.get_data()
    file_id = data.get("photo_file_id")
    await state.clear()

    city, _ = get_user_city(msg.from_user.id)
    thinking = await msg.answer("🔍 Анализирую фото... подожди немного 🤔", reply_markup=MAIN_KB)

    try:
        # Скачиваем фото
        file = await bot.get_file(file_id)
        tmp_file = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        tmp_path = tmp_file.name
        tmp_file.close()
        await bot.download_file(file.file_path, tmp_path)

        with open(tmp_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")

        result = await identify_place(image_data, city)

        try:
            await thinking.delete()
        except Exception:
            pass

        await msg.answer(
            f"{result}\n\n⚠️ Это предположение на основе фото — проверь по ссылкам на карты.{BACK_TEXT}",
            reply_markup=MAIN_KB,
            disable_web_page_preview=True,
        )
        increment_requests(msg.from_user.id)
        asyncio.create_task(log_sheets(
            msg.from_user.id, full_name(msg.from_user),
            msg.from_user.username, "Фото место", "🔍 Определить место", len(result)))
    except Exception as e:
        logging.error(f"Photo identify error: {e}")
        try:
            await thinking.delete()
        except Exception:
            pass
        await msg.answer(
            f"Не смог обработать фото. Попробуй написать название места текстом 👇{BACK_TEXT}",
            reply_markup=MAIN_KB,
        )
    finally:
        if 'tmp_path' in locals() and os.path.exists(tmp_path):
            os.unlink(tmp_path)


@dp.message(UserState.waiting_photo_action, F.text == "✏️ Напишу сам")
async def handle_photo_write_self(msg: Message, state: FSMContext):
    await state.clear()
    city, _ = get_user_city(msg.from_user.id)
    await msg.answer(
        f"Пиши что ищешь в {city} — найду лучшее 🚀",
        reply_markup=MAIN_KB,
    )


@dp.message(UserState.waiting_photo_action)
async def handle_photo_action_other(msg: Message, state: FSMContext):
    await msg.answer("Выбери действие 👇", reply_markup=PHOTO_KB)


# ── Видео и другие медиа ──────────────────────────────────────
@dp.message(F.video | F.video_note)
async def handle_video(msg: Message):
    city, _ = get_user_city(msg.from_user.id)
    await msg.answer(
        f"Видео пока не поддерживаю 😊\n\nНо если хочешь найти что-то в {city} — просто напиши что ищешь или жми кнопку 👇",
        reply_markup=MAIN_KB,
    )


@dp.message(F.sticker)
async def handle_sticker(msg: Message):
    await msg.answer(
        "Классный стикер! 😄 Но я понимаю только текст, голосовые и фото.\n\nЧто ищешь? Жми кнопку или пиши 👇",
        reply_markup=MAIN_KB,
    )


@dp.message(F.document)
async def handle_document(msg: Message):
    await msg.answer(
        "Документы пока не поддерживаю 😊\n\nЕсли ищешь место — напиши что именно или жми кнопку 👇",
        reply_markup=MAIN_KB,
    )


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

        # Антифлуд для голосовых
        if is_flood(msg.from_user.id):
            await msg.answer(f"Подожди секунду — обрабатываю предыдущий запрос 😊", reply_markup=MAIN_KB)
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
    text = msg.text.strip() if msg.text else ""

    # Игнорируем служебные кнопки и кнопки городов
    if (text in SYSTEM_BUTTONS or text in ALL_CITY_BUTTONS or
            text in ZODIAC_SIGNS or text == "⏭ Пропустить" or
            text == "❌ Отмена"):
        return

    user = msg.from_user

    # Короткие фразы — без GPT
    short_reply = SHORT_REPLIES.get(text.lower())
    if short_reply:
        await msg.answer(short_reply, reply_markup=MAIN_KB)
        return

    # Антифлуд
    if is_flood(user.id):
        await msg.answer(
            "Подожди секунду — обрабатываю предыдущий запрос 😊",
            reply_markup=MAIN_KB,
        )
        return

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


# ── Всё остальное ─────────────────────────────────────────────
@dp.message()
async def fallback(msg: Message):
    await msg.answer(
        "Я понимаю текст, голосовые сообщения и фото.\n\nНапиши что ищешь или жми кнопку 👇",
        reply_markup=MAIN_KB,
    )


# ──────────────────────────────────────────────────────────────
# ЗАПУСК
# ──────────────────────────────────────────────────────────────
async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    init_db()
    logging.info("AI Местный v5 запущен")
    asyncio.create_task(morning_scheduler())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
