#!/usr/bin/env python3
"""
AI Местный — гид по городам России v6.0
Bot: @mestniy_guide_bot
File: /root/bot2.py
Service: sochi-test

Что нового в v6.0:
- Свободный ввод любого города России текстом
- GPT отвечает JSON → Python строит ссылки программно
- Контекст диалога (последние 4 сообщения на пользователя)
- Одноимённые города — уточнение региона
- Регионы и курорты (Красная Поляна, Домбай и т.д.)
- Inline-реакции 👍/👎 с причинами → SQLite + Google Sheets
- Разбивка длинных сообщений
- «Другой маршрут» исключает предыдущие места
- Честные формулировки в «О проекте»
"""

import asyncio
import json
import logging
import os
import sys
import fcntl
import sqlite3
import tempfile
import time
import base64
import uuid
import html
import urllib.parse
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery,
)
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
CREDENTIALS    = "/root/google_credentials.json"
DB_PATH        = "/root/bot2.db"
MODEL          = "gpt-4o"
FLOOD_SECONDS  = 4
MAX_MSG_LEN    = 4000   # лимит Telegram 4096, берём с запасом
CONTEXT_TURNS  = 4      # сколько пар сообщений хранить в контексте

# ──────────────────────────────────────────────────────────────
# АФИШИ (для популярных городов)
# ──────────────────────────────────────────────────────────────
CITY_EVENTS = {
    "Сочи":            ("https://kudago.com/sochi/",        "https://afisha.yandex.ru/sochi"),
    "Москва":          ("https://kudago.com/msk/",          "https://afisha.yandex.ru/moscow"),
    "Санкт-Петербург": ("https://kudago.com/spb/",          "https://afisha.yandex.ru/saint-petersburg"),
    "Казань":          ("https://kudago.com/kzn/",          "https://afisha.yandex.ru/kazan"),
    "Краснодар":       ("https://kudago.com/krd/",          "https://afisha.yandex.ru/krasnodar"),
    "Калининград":     ("https://kudago.com/klg/",          "https://afisha.yandex.ru/kaliningrad"),
    "Екатеринбург":    ("https://kudago.com/ekb/",          "https://afisha.yandex.ru/yekaterinburg"),
    "Нижний Новгород": ("https://kudago.com/nnv/",          "https://afisha.yandex.ru/nizhny-novgorod"),
    "Новосибирск":     ("https://kudago.com/nsk/",          "https://afisha.yandex.ru/novosibirsk"),
    "Самара":          ("https://kudago.com/sam/",          "https://afisha.yandex.ru/samara"),
    "Уфа":             ("https://kudago.com/ufa/",          "https://afisha.yandex.ru/ufa"),
    "Ростов-на-Дону":  ("https://kudago.com/rostov/",       "https://afisha.yandex.ru/rostov-on-don"),
    "Воронеж":         ("https://kudago.com/vrn/",          "https://afisha.yandex.ru/voronezh"),
    "Пермь":           ("https://kudago.com/perm/",         "https://afisha.yandex.ru/perm"),
    "Красноярск":      ("https://kudago.com/krsk/",         "https://afisha.yandex.ru/krasnoyarsk"),
    "Владивосток":     ("https://kudago.com/vladivostok/",  "https://afisha.yandex.ru/vladivostok"),
    "Геленджик":       ("https://kudago.com/",              "https://afisha.yandex.ru/gelendgik"),
    "Ялта":            ("https://kudago.com/",              "https://afisha.yandex.ru/yalta"),
    "Севастополь":     ("https://kudago.com/",              "https://afisha.yandex.ru/sevastopol"),
    "Симферополь":     ("https://kudago.com/",              "https://afisha.yandex.ru/simferopol"),
    "Евпатория":       ("https://kudago.com/",              "https://afisha.yandex.ru/evpatoria"),
    "Керчь":           ("https://kudago.com/",              "https://afisha.yandex.ru/kerch"),
    "Анапа":           ("https://kudago.com/",              "https://afisha.yandex.ru/anapa"),
    "Новороссийск":    ("https://kudago.com/",              "https://afisha.yandex.ru/novorossiysk"),
}

# ──────────────────────────────────────────────────────────────
# КОРОТКИЕ ФРАЗЫ — без GPT
# ──────────────────────────────────────────────────────────────
SHORT_REPLIES = {
    "привет":    "Привет! 👋 Жми кнопку или пиши что ищешь 😊",
    "хай":       "Привет! 👋 Жми кнопку или пиши что ищешь 😊",
    "hello":     "Привет! 👋 Жми кнопку или пиши что ищешь 😊",
    "спасибо":   "Пожалуйста! 🙏 Если нужно ещё что-то — пиши 😊",
    "спс":       "Пожалуйста! 🙏 Если нужно ещё что-то — пиши 😊",
    "благодарю": "Пожалуйста! 🙏 Если нужно ещё что-то — пиши 😊",
    "ок":        "Отлично! 👌 Пиши если что-то нужно 😊",
    "окей":      "Отлично! 👌 Пиши если что-то нужно 😊",
    "ok":        "Отлично! 👌 Пиши если что-то нужно 😊",
    "👍":        "😊 Всегда рад помочь!",
    "👌":        "😊 Всегда рад помочь!",
    "отлично":   "Рад помочь! 😊",
    "класс":     "Рад помочь! 😊",
    "супер":     "Рад помочь! 😊",
    "хорошо":    "Отлично! 👌 Пиши если что-то нужно 😊",
    "понял":     "Отлично! 👌 Пиши если что-то нужно 😊",
}

# ──────────────────────────────────────────────────────────────
# КЛАВИАТУРЫ
# ──────────────────────────────────────────────────────────────
MAIN_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🗺 Маршрут на день"),  KeyboardButton(text="✏️ Свой вопрос")],
        [KeyboardButton(text="🍽 Где поесть"),        KeyboardButton(text="🏨 Где остановиться")],
        [KeyboardButton(text="🎭 Куда сходить"),      KeyboardButton(text="➕ Ещё")],
        [KeyboardButton(text="🏙 Сменить город")],
    ],
    resize_keyboard=True,
)

MORE_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="☕ Кофе с видом"),       KeyboardButton(text="🌅 На рассвет")],
        [KeyboardButton(text="👨‍👩‍👧 С детьми"),        KeyboardButton(text="❤️ Для двоих")],
        [KeyboardButton(text="🏔 На природу"),          KeyboardButton(text="🌃 Вечером")],
        [KeyboardButton(text="💎 Неочевидное место"),  KeyboardButton(text="💬 Оставить отзыв")],
        [KeyboardButton(text="ℹ️ О проекте"),           KeyboardButton(text="🛠 Поддержка")],
        [KeyboardButton(text="🏠 Главное меню")],
    ],
    resize_keyboard=True,
)

ROUTE_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🔄 Другой маршрут")],
        [KeyboardButton(text="🏠 Главное меню")],
    ],
    resize_keyboard=True,
)

CITY_INPUT_KB = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="❌ Отмена")]],
    resize_keyboard=True,
)

CITY_CONFIRM_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="✅ Да"), KeyboardButton(text="❌ Нет, другой город")],
    ],
    resize_keyboard=True,
)

PHOTO_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🔍 Определить место"), KeyboardButton(text="✏️ Напишу сам")],
    ],
    resize_keyboard=True,
)

HOTEL_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="💰 Бюджетно"),      KeyboardButton(text="✨ Комфорт")],
        [KeyboardButton(text="👑 Премиум"),        KeyboardButton(text="👨‍👩‍👧 Для семьи")],
        [KeyboardButton(text="❤️ Для пары"),       KeyboardButton(text="📍 В центре")],
        [KeyboardButton(text="🏠 Главное меню")],
    ],
    resize_keyboard=True,
)

# ──────────────────────────────────────────────────────────────
# НАБОРЫ КНОПОК
# ──────────────────────────────────────────────────────────────
THEME_BUTTONS = {
    "🍽 Где поесть", "☕ Кофе с видом", "🌅 На рассвет", "🎭 Куда сходить",
    "👨‍👩‍👧 С детьми", "❤️ Для двоих", "🏔 На природу", "🌃 Вечером",
    "🗺 Маршрут на день", "💎 Неочевидное место",
}

HOTEL_FORMATS = {
    "💰 Бюджетно", "✨ Комфорт", "👑 Премиум",
    "👨‍👩‍👧 Для семьи", "❤️ Для пары", "📍 В центре",
}

SYSTEM_BUTTONS = {
    "✏️ Свой вопрос", "🛠 Поддержка", "ℹ️ О проекте", "🏙 Сменить город",
    "💬 Оставить отзыв", "🏠 Главное меню", "➕ Ещё", "🏨 Где остановиться",
    "🔍 Определить место", "✏️ Напишу сам", "🔄 Другой маршрут",
    "✅ Да", "❌ Нет, другой город", "❌ Отмена",
} | HOTEL_FORMATS

BACK_TEXT = "\n\n✨ Что ещё найдём? Жми или пиши 👇"

# ──────────────────────────────────────────────────────────────
# FSM
# ──────────────────────────────────────────────────────────────
class UserState(StatesGroup):
    entering_city        = State()
    confirming_city      = State()
    confirming_ambiguous = State()
    writing_review       = State()
    waiting_photo_action = State()
    choosing_hotel       = State()

# ──────────────────────────────────────────────────────────────
# КЛИЕНТЫ
# ──────────────────────────────────────────────────────────────
bot    = Bot(token=BOT_TOKEN)
dp     = Dispatcher(storage=MemoryStorage())
client = OpenAI(api_key=OPENAI_KEY, base_url="https://api.proxyapi.ru/openai/v1")

# Антифлуд: user_id → timestamp
last_request_time: dict[int, float] = {}

# Блокировка параллельных запросов: не даём отправить второй пока первый ещё идёт
active_requests: set[int] = set()

# Контекст диалога: user_id → список {"role": ..., "content": ...}
dialog_context: dict[int, list] = {}

# История мест маршрутов: user_id → list названий (накапливается, макс 20)
route_history: dict[int, list] = {}

# ──────────────────────────────────────────────────────────────
# БАЗА ДАННЫХ
# ──────────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Основная таблица пользователей
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id        INTEGER PRIMARY KEY,
            name           TEXT,
            username       TEXT,
            city           TEXT DEFAULT NULL,
            registered_at  TEXT,
            last_active    TEXT,
            total_requests INTEGER DEFAULT 0,
            is_premium     INTEGER DEFAULT 1,
            ref_by         INTEGER DEFAULT NULL
        )
    """)
    # Таблица реакций на подборки
    c.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            response_id     TEXT,
            user_id         INTEGER,
            username        TEXT,
            city            TEXT,
            category        TEXT,
            rating          TEXT,
            negative_reason TEXT DEFAULT NULL,
            created_at      TEXT,
            UNIQUE(response_id, user_id)
        )
    """)
    # Таблица метаданных ответов — для связи реакции с категорией
    c.execute("""
        CREATE TABLE IF NOT EXISTS responses (
            response_id TEXT PRIMARY KEY,
            user_id     INTEGER,
            city        TEXT,
            category    TEXT,
            created_at  TEXT
        )
    """)
    # Миграция: убираем дубли и создаём уникальный индекс для feedback
    # (на новой базе UNIQUE уже в CREATE TABLE, для старой базы нужен индекс)
    c.execute("""
        DELETE FROM feedback
        WHERE id NOT IN (
            SELECT MAX(id)
            FROM feedback
            GROUP BY response_id, user_id
        )
    """)
    c.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_feedback_response_user
        ON feedback(response_id, user_id)
    """)
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row

def save_user(user_id, name, username, city=None, ref_by=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    c.execute("""
        INSERT INTO users (user_id, name, username, city, registered_at, last_active, ref_by)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            name=excluded.name,
            username=excluded.username,
            last_active=excluded.last_active
    """, (user_id, name, username or "", city, now, now, ref_by))
    conn.commit()
    conn.close()

def update_city(user_id, city):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET city=? WHERE user_id=?", (city, user_id))
    conn.commit()
    conn.close()

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

def save_response_meta(response_id: str, user_id: int, city: str, category: str):
    """Сохраняет метаданные ответа для последующей привязки реакции к категории."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    c.execute("""
        INSERT OR IGNORE INTO responses (response_id, user_id, city, category, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (response_id, user_id, city or "", category, now))
    conn.commit()
    conn.close()

def get_response_meta(response_id: str) -> dict:
    """Возвращает метаданные ответа по response_id."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM responses WHERE response_id=?", (response_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"city": row["city"], "category": row["category"], "user_id": row["user_id"]}
    return {}

def save_feedback(response_id, user_id, username, city, category, rating, negative_reason=None):
    """Сохраняет реакцию. UPSERT — повторная реакция обновляет запись."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    c.execute("""
        INSERT INTO feedback (response_id, user_id, username, city, category, rating, negative_reason, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(response_id, user_id) DO UPDATE SET
            rating=excluded.rating,
            negative_reason=excluded.negative_reason,
            created_at=excluded.created_at
    """, (response_id, user_id, username or "", city or "", category, rating, negative_reason, now))
    conn.commit()
    conn.close()

def get_user_city(user_id):
    row = get_user(user_id)
    return row["city"] if row else None

def get_stats():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    total = c.fetchone()[0]
    c.execute("SELECT city, COUNT(*) cnt FROM users WHERE city IS NOT NULL GROUP BY city ORDER BY cnt DESC LIMIT 7")
    top_cities = c.fetchall()
    today = datetime.now().strftime("%d.%m.%Y")
    c.execute("SELECT COUNT(*) FROM users WHERE last_active LIKE ?", (f"{today}%",))
    active_today = c.fetchone()[0]
    c.execute("SELECT SUM(total_requests) FROM users")
    total_req = c.fetchone()[0] or 0
    c.execute("SELECT COUNT(*) FROM users WHERE city IS NULL")
    no_city = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM feedback WHERE rating='positive'")
    pos = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM feedback WHERE rating='negative'")
    neg = c.fetchone()[0]
    conn.close()
    return total, top_cities, active_today, total_req, no_city, pos, neg

# ──────────────────────────────────────────────────────────────
# АНТИФЛУД
# ──────────────────────────────────────────────────────────────
def is_flood(user_id: int) -> bool:
    now = time.time()
    last = last_request_time.get(user_id, 0)
    if now - last < FLOOD_SECONDS:
        return True
    last_request_time[user_id] = now
    if len(last_request_time) > 1000:
        cutoff = now - 3600
        for uid in [u for u, t in last_request_time.items() if t < cutoff]:
            last_request_time.pop(uid, None)
    return False

# ──────────────────────────────────────────────────────────────
# КОНТЕКСТ ДИАЛОГА
# ──────────────────────────────────────────────────────────────
def get_context(user_id: int) -> list:
    """Возвращает историю диалога пользователя."""
    return dialog_context.get(user_id, [])

def add_to_context(user_id: int, role: str, content: str):
    """Добавляет сообщение в контекст, обрезает до CONTEXT_TURNS пар."""
    ctx = dialog_context.setdefault(user_id, [])
    ctx.append({"role": role, "content": content})
    # Храним только последние CONTEXT_TURNS*2 сообщений (пары user+assistant)
    if len(ctx) > CONTEXT_TURNS * 2:
        ctx[:] = ctx[-(CONTEXT_TURNS * 2):]

def clear_context(user_id: int):
    """Очищает контекст и историю маршрутов (при смене города)."""
    dialog_context.pop(user_id, None)
    route_history.pop(user_id, None)

# ──────────────────────────────────────────────────────────────
# ССЫЛКИ НА КАРТЫ — программное построение
# ──────────────────────────────────────────────────────────────
def make_map_links(place_name: str, city: str) -> str:
    """Формирует компактные HTML-ссылки на Яндекс.Карты и 2ГИС."""
    query  = urllib.parse.quote(f"{place_name} {city}")
    yandex = f"https://yandex.ru/maps/?text={query}"
    gis    = f"https://2gis.ru/search/{query}"
    return f'🗺 <a href="{yandex}">Яндекс.Карты</a>  ·  <a href="{gis}">2ГИС</a>'

# ──────────────────────────────────────────────────────────────
# РАЗБИВКА ДЛИННЫХ СООБЩЕНИЙ
# ──────────────────────────────────────────────────────────────
async def send_long(msg: Message, text: str, **kwargs):
    """Отправляет текст с parse_mode=HTML, разбивая на части если превышает лимит."""
    # Всегда используем HTML — ссылки на карты оформлены как <a href>
    kwargs.setdefault("parse_mode", "HTML")
    kwargs.setdefault("disable_web_page_preview", True)
    if len(text) <= MAX_MSG_LEN:
        await msg.answer(text, **kwargs)
        return

    def split_text(t: str, limit: int) -> list[str]:
        """Рекурсивно делит текст на части не длиннее limit."""
        if len(t) <= limit:
            return [t]
        parts = []
        # Сначала по двойному переносу
        for sep in ("\n\n", "\n"):
            chunks = t.split(sep)
            current = ""
            for chunk in chunks:
                candidate = (current + sep + chunk).strip() if current else chunk
                if len(candidate) <= limit:
                    current = candidate
                else:
                    if current:
                        parts.append(current.strip())
                    # Если сам chunk > limit — режем по символам
                    if len(chunk) > limit:
                        for i in range(0, len(chunk), limit):
                            parts.append(chunk[i:i+limit])
                        current = ""
                    else:
                        current = chunk
            if current:
                parts.append(current.strip())
            if parts:
                return [p for p in parts if p]
        # Последний уровень — по символам
        return [t[i:i+limit] for i in range(0, len(t), limit)]

    parts = split_text(text, MAX_MSG_LEN)
    for i, part in enumerate(parts):
        kw = kwargs.copy()
        if i < len(parts) - 1:
            kw.pop("reply_markup", None)
        await msg.answer(part, **kw)
        if i < len(parts) - 1:
            await asyncio.sleep(0.3)

# ──────────────────────────────────────────────────────────────
# INLINE РЕАКЦИИ
# ──────────────────────────────────────────────────────────────
def feedback_kb(response_id: str) -> InlineKeyboardMarkup:
    """Кнопки реакции под подборкой."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="👍 Полезно",    callback_data=f"fb_pos:{response_id}"),
        InlineKeyboardButton(text="👎 Не подошло", callback_data=f"fb_neg:{response_id}"),
    ]])

def feedback_reasons_kb(response_id: str) -> InlineKeyboardMarkup:
    """Причины негативной реакции."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Слишком дорого",         callback_data=f"fb_why:{response_id}:expensive")],
        [InlineKeyboardButton(text="📍 Слишком далеко",         callback_data=f"fb_why:{response_id}:far")],
        [InlineKeyboardButton(text="🎯 Не мой формат",          callback_data=f"fb_why:{response_id}:format")],
        [InlineKeyboardButton(text="❌ Место неверное/закрыто", callback_data=f"fb_why:{response_id}:wrong")],
        [InlineKeyboardButton(text="🔄 Хочу другие варианты",   callback_data=f"fb_why:{response_id}:other")],
    ])

def new_response_id() -> str:
    """Уникальный ID для каждого ответа."""
    return uuid.uuid4().hex[:12]

# ──────────────────────────────────────────────────────────────
# GOOGLE SHEETS
# ──────────────────────────────────────────────────────────────
def _get_sheet(sheet_name):
    creds = Credentials.from_service_account_file(
        CREDENTIALS,
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    gc = gspread.authorize(creds)
    return gc.open_by_key(SPREADSHEET_ID).worksheet(sheet_name)

# ──────────────────────────────────────────────────────────────
# Единая схема строк в листе «Аналитика Сочи»:
# user_id | @username | дата | тип | город | текст/категория | доп.поле
#
# Типы строк:
#   Запрос         — обычный запрос пользователя
#   Отзыв          — текстовый отзыв через кнопку
#   Реакция 👍     — положительная реакция на подборку
#   Реакция 👎     — отрицательная реакция, доп.поле = причина
# ──────────────────────────────────────────────────────────────

def _append_row(row: list):
    """Добавляет строку в основной лист аналитики."""
    try:
        ws  = _get_sheet(SHEET_NAME)
        ws.append_row(row)
    except Exception as e:
        logging.warning(f"Sheets append error: {e}")

def _log_sync(user_id, name, username, msg_type, text, resp_len=0):
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    _append_row([str(user_id), name, f"@{username}" if username else "", now,
                 "Запрос", msg_type, text, resp_len])

async def log_sheets(user_id, name, username, msg_type, text, resp_len=0):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _log_sync, user_id, name, username, msg_type, text, resp_len)

def _log_review_sync(user_id, name, username, city, review_text):
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    _append_row([str(user_id), name, f"@{username}" if username else "", now,
                 "Отзыв", city or "—", review_text, ""])

async def log_review(user_id, name, username, city, review_text):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _log_review_sync, user_id, name, username, city, review_text)

def _log_feedback_sync(response_id, user_id, username, city, category, rating, reason=None):
    now  = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    icon = "👍" if rating == "positive" else "👎"
    _append_row([str(user_id), f"@{username}" if username else "", "", now,
                 f"Реакция {icon}", city or "—", category, reason or ""])

async def log_feedback_sheets(response_id, user_id, username, city, category, rating, reason=None):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None, _log_feedback_sync, response_id, user_id, username, city, category, rating, reason
    )

# ──────────────────────────────────────────────────────────────
# GPT — ОПРЕДЕЛЕНИЕ ГОРОДА
# ──────────────────────────────────────────────────────────────
def _detect_city_sync(user_input: str) -> dict:
    """
    Статусы:
    - ok: чёткий российский город/курорт
    - suggest: опечатка или падежная форма → suggestion
    - ambiguous: одноимённые города → variants (список строк с регионом)
    - destination: конкретный курорт, посёлок (Красная Поляна, Домбай, Шерегеш)
    - region: большой регион без конкретного места (Алтай, Карелия, Дагестан, Байкал)
    - not_city: не населённый пункт вообще
    - foreign: иностранный город
    """
    prompt = f"""Пользователь ввёл: "{user_input}"

Определи что это.

Ответь ТОЛЬКО в формате JSON (без markdown, без пояснений):
{{
  "status": "ok"|"suggest"|"ambiguous"|"destination"|"region"|"not_city"|"foreign",
  "city": "нормализованное название" или null,
  "suggestion": "исправленный вариант" или null,
  "variants": ["Вариант 1 (регион)", "Вариант 2 (регион)"] или null
}}

Правила:
- "ok": явный российский город (Сочи, Казань, Владивосток) — нормализуй
- "suggest": опечатка или падеж (Сачи→Сочи, питер→Санкт-Петербург, екб→Екатеринбург)
- "ambiguous": одноимённые города в разных регионах — дай variants с уточнением региона
  Примеры: Киров, Советск, Красноармейск, Заречный, Александровск
- "destination": конкретный курорт, посёлок или туристическое место (не крупный город):
  Красная Поляна, Домбай, Архыз, Шерегеш, Роза Хутор, Лазаревское, Сириус, Адлер, Дивеево
- "region": большой регион, республика, природный объект без конкретной точки:
  Алтай, Карелия, Дагестан, Байкал, Камчатка, Кавказ, Крым (без города), Урал
- "not_city": не населённый пункт (хочу на море, покажи красивые места, хочу в горы)
- "foreign": иностранный город

Примеры:
"Сочи" → {{"status":"ok","city":"Сочи","suggestion":null,"variants":null}}
"Сачи" → {{"status":"suggest","city":null,"suggestion":"Сочи","variants":null}}
"питер" → {{"status":"suggest","city":null,"suggestion":"Санкт-Петербург","variants":null}}
"Советск" → {{"status":"ambiguous","city":null,"suggestion":null,"variants":["Советск (Калининградская область)","Советск (Кировская область)"]}}
"Красная Поляна" → {{"status":"destination","city":"Красная Поляна","suggestion":null,"variants":null}}
"Алтай" → {{"status":"region","city":"Алтай","suggestion":null,"variants":null}}
"хочу на море" → {{"status":"not_city","city":null,"suggestion":null,"variants":null}}
"Барселона" → {{"status":"foreign","city":null,"suggestion":null,"variants":null}}"""

    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=150,
        temperature=0,
    )
    raw = resp.choices[0].message.content.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)

async def detect_city(user_input: str) -> dict:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _detect_city_sync, user_input)

# ──────────────────────────────────────────────────────────────
# GPT — ВИЗИТКА ГОРОДА
# ──────────────────────────────────────────────────────────────
def _city_intro_sync(city: str) -> str:
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": (
            f"Напиши короткую живую визитку для туриста про {city} — 2-3 предложения. "
            f"Тон дружелюбный, без канцелярита. Никакого markdown. "
            f"Скажи что особенного в этом месте."
        )}],
        max_tokens=150,
        temperature=0.8,
    )
    return resp.choices[0].message.content.strip()

async def get_city_intro(city: str) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _city_intro_sync, city)

# ──────────────────────────────────────────────────────────────
# GPT — СИСТЕМНЫЙ ПРОМПТ
# ──────────────────────────────────────────────────────────────
def get_system_prompt(city: str) -> str:
    events = CITY_EVENTS.get(city)
    if events:
        kudago_url, afisha_url = events
        events_block = (
            f"КНОПКА 'КУДА СХОДИТЬ':\n"
            f"Дай ссылки на афишу:\n- {kudago_url}\n- {afisha_url}\n"
            f"И кратко расскажи что обычно проходит в {city}."
        )
    else:
        events_block = (
            f"КНОПКА 'КУДА СХОДИТЬ':\n"
            f"Для {city} крупных афиш нет. Расскажи про краеведческий музей, "
            f"дом культуры, парки. Посоветуй искать афишу в группе города ВКонтакте. "
            f"Не выдумывай конкретные даты мероприятий."
        )

    return f"""Ты — AI Местный, гид по городам и направлениям России.

ГОРОД/НАПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯ: {city}

СТИЛЬ: дружелюбно, как живой человек. Без канцелярита. Можно на «ты».
ЗАПРЕЩЕНО: markdown (**, __, ##, [], ``), конкретные цены в рублях, телефоны.

ФОРМАТ ОТВЕТА — СТРОГО JSON:
Для подборок мест (Где поесть, Кофе с видом, С детьми и т.д.):
{{
  "type": "places",
  "intro": "Вводная фраза (1 предложение, опционально)",
  "places": [
    {{
      "name": "Название места",
      "area": "Район или улица",
      "price": "Доступные" | "Средние" | "Выше среднего",
      "description": "Почему стоит идти — 1-2 предложения"
    }}
  ],
  "outro": "Закрывающая фраза (опционально)"
}}

Для маршрута на день:
{{
  "type": "route",
  "title": "Маршрут на день по {city}",
  "slots": [
    {{
      "time": "09:00",
      "name": "Название места",
      "area": "Район/адрес",
      "price": "Доступные" | "Средние" | "Выше среднего",
      "description": "Что здесь делать и почему — 2-3 предложения"
    }}
  ],
  "warning": "Часы работы и доступность — уточняйте заранее"
}}

Для одиночного места (Неочевидное место):
{{
  "type": "single",
  "name": "Название",
  "area": "Район",
  "price": "Доступные" | "Средние" | "Выше среднего",
  "description": "Полное описание — 3-5 предложений",
  "tip": "Когда лучше приехать и что учесть"
}}

Для свободного текстового ответа (Куда сходить, вопросы без мест):
{{
  "type": "text",
  "text": "Обычный текст ответа"
}}

ПРАВИЛА:
- Всегда отвечай ТОЛЬКО валидным JSON без markdown-обёрток
- Давай 5-7 мест для подборок (для маленьких городов — сколько знаешь достоверно, лучше 3 честных чем 7 выдуманных)
- Если нажали кнопку — СРАЗУ давай подборку без вопросов
- Для Москвы и СПб — можно спросить район одним вопросом
- Маршрут: логичная география (не гоняй по всему городу), слоты 09:00→11:30→14:00→16:30→19:00
- Не повторяй места из разных слотов маршрута

{events_block}"""

# ──────────────────────────────────────────────────────────────
# GPT — ОСНОВНОЙ ЗАПРОС (с контекстом)
# ──────────────────────────────────────────────────────────────
def _ask_sync(user_text: str, city: str, context: list) -> str:
    messages = [{"role": "system", "content": get_system_prompt(city)}]
    messages.extend(context)
    messages.append({"role": "user", "content": user_text})
    resp = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        max_tokens=2000,
        temperature=0.7,
    )
    return resp.choices[0].message.content.strip()

async def ask_ai(text: str, city: str, context: list) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _ask_sync, text, city, context)

# ──────────────────────────────────────────────────────────────
# ПАРСИНГ JSON-ОТВЕТА GPT → ТЕКСТ + ССЫЛКИ
# ──────────────────────────────────────────────────────────────
def parse_gpt_response(raw: str, city: str) -> tuple[str, list, str]:
    """
    Парсит JSON-ответ GPT, строит текст с программными ссылками.
    Возвращает (text, place_names, resp_type).
    resp_type: "places" | "route" | "single" | "text" | "error"
    """
    raw = raw.strip()
    if raw.startswith("```"):
        raw = "\n".join(raw.split("\n")[1:])
        raw = raw.rsplit("```", 1)[0].strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logging.warning(f"GPT вернул не JSON: {raw[:200]}")
        # Не показываем сырой JSON пользователю
        return "Не удалось корректно собрать подборку. Попробуй запросить ещё раз 👇", [], "error"

    resp_type = data.get("type", "text")
    place_names = []

    if resp_type == "places":
        places = data.get("places", [])
        if not places:
            logging.warning("GPT вернул пустой список places")
            return "Не нашёл конкретных мест по этому запросу. Попробуй уточнить или задай вопрос иначе 👇", [], "error"

        parts = []
        if data.get("intro"):
            parts.append(html.escape(str(data["intro"])))
            parts.append("")
        for i, p in enumerate(places, 1):
            name = html.escape(str(p.get("name", "")).strip())
            if not name:
                continue
            place_names.append(p.get("name", "").strip())
            area  = html.escape(str(p.get("area", "")))
            price_raw = str(p.get("price", ""))
            price = html.escape(price_raw)
            desc  = html.escape(str(p.get("description", "")))
            price_emoji = {"Доступные": "💚", "Средние": "💛", "Выше среднего": "💰"}.get(price_raw, "💛")
            block = (
                f"{i}. {name}\n"
                f"📍 {area}\n"
                f"{price_emoji} {price}\n"
                f"✨ {desc}\n"
                f"{make_map_links(p.get('name', '').strip(), city)}\n"
                f"⚠️ Цены и часы — уточняйте перед визитом"
            )
            parts.append(block)
        if data.get("outro"):
            parts.append("")
            parts.append(html.escape(str(data["outro"])))
        if not place_names:
            return "Не удалось получить конкретные места. Попробуй уточнить запрос 👇", [], "error"
        return "\n\n".join(parts), place_names, resp_type

    elif resp_type == "route":
        slots = data.get("slots", [])
        if not slots:
            logging.warning("GPT вернул пустой маршрут")
            return "Не удалось составить маршрут. Попробуй ещё раз 👇", [], "error"

        title = html.escape(str(data.get("title", "Маршрут на день")))
        parts = [f"🗺 {title}"]
        for slot in slots:
            name = html.escape(str(slot.get("name", "")).strip())
            if not name:
                continue
            place_names.append(slot.get("name", "").strip())
            area     = html.escape(str(slot.get("area", "")))
            price_raw = str(slot.get("price", ""))
            price    = html.escape(price_raw)
            desc     = html.escape(str(slot.get("description", "")))
            time_str = html.escape(str(slot.get("time", "")))
            price_emoji = {"Доступные": "💚", "Средние": "💛", "Выше среднего": "💰"}.get(price_raw, "💛")
            block = (
                f"━━━━━━━━━━━━━━━\n"
                f"🕐 {time_str} — {name}\n"
                f"📍 {area}\n"
                f"{price_emoji} {price}\n"
                f"{desc}\n"
                f"{make_map_links(slot.get('name', '').strip(), city)}"
            )
            parts.append(block)
        parts.append("━━━━━━━━━━━━━━━")
        if data.get("warning"):
            parts.append(f"⚠️ {html.escape(str(data['warning']))}")
        if not place_names:
            return "Не удалось составить маршрут — места оказались пустыми. Попробуй ещё раз 👇", [], "error"
        return "\n\n".join(parts), place_names, resp_type

    elif resp_type == "single":
        name = html.escape(str(data.get("name", "")).strip())
        if not name:
            return "Не удалось найти место. Попробуй уточнить запрос 👇", [], "error"
        place_names.append(data.get("name", "").strip())
        area      = html.escape(str(data.get("area", "")))
        price_raw = str(data.get("price", ""))
        price     = html.escape(price_raw)
        desc      = html.escape(str(data.get("description", "")))
        tip       = html.escape(str(data.get("tip", "")))
        price_emoji = {"Доступные": "💚", "Средние": "💛", "Выше среднего": "💰"}.get(price_raw, "💛")
        text = (
            f"💎 {name}\n\n"
            f"📍 {area}\n"
            f"{price_emoji} {price}\n\n"
            f"{desc}\n\n"
            f"💡 {tip}\n\n"
            f"{make_map_links(data.get('name', '').strip(), city)}\n"
            f"⚠️ Цены и часы — уточняйте перед визитом"
        )
        return text, place_names, resp_type

    else:  # text
        text_content = data.get("text", "")
        if not text_content:
            return "Не получил ответ. Попробуй переформулировать вопрос 👇", [], "error"
        return html.escape(str(text_content)), [], "text"

# ──────────────────────────────────────────────────────────────
# GPT — ОТЕЛИ (JSON)
# ──────────────────────────────────────────────────────────────
def _ask_hotels_sync(city: str, hotel_format: str) -> str:
    format_map = {
        "💰 Бюджетно":    "бюджетные (хостелы, недорогие гостиницы, апартаменты)",
        "✨ Комфорт":     "комфортные 3-4 звезды или хорошие апартаменты",
        "👑 Премиум":     "премиум 4-5 звезд",
        "👨‍👩‍👧 Для семьи": "для семьи с детьми",
        "❤️ Для пары":    "романтические для пары",
        "📍 В центре":    "в самом центре города",
    }
    desc = format_map.get(hotel_format, "комфортные")
    prompt = f"""Подбери варианты размещения в {city} — {desc}.

Ответь СТРОГО в JSON (без markdown):
{{
  "type": "places",
  "intro": "Вводная фраза про категорию",
  "places": [
    {{
      "name": "Название",
      "area": "Район/адрес",
      "price": "Доступные"|"Средние"|"Выше среднего",
      "description": "Главное преимущество — 1-2 предложения"
    }}
  ],
  "outro": "⚠️ Цены и наличие мест меняются — проверяйте на Ostrovok, Яндекс Путешествия, Суточно.ру"
}}

Правила:
- 5 вариантов (если не знаешь 5 достоверно — дай меньше, не выдумывай)
- Не пиши конкретные цены в рублях, только категорию
- Не выдумывай адреса если не уверен — пиши только район"""

    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1200,
        temperature=0.5,
    )
    return resp.choices[0].message.content.strip()

async def ask_hotels(city: str, hotel_format: str) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _ask_hotels_sync, city, hotel_format)

# ──────────────────────────────────────────────────────────────
# GPT — ОПРЕДЕЛЕНИЕ МЕСТА ПО ФОТО
# ──────────────────────────────────────────────────────────────
def _identify_place_sync(image_base64: str, city: str) -> str:
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": [
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{image_base64}", "detail": "low"}
            },
            {
                "type": "text",
                "text": (
                    f"Посмотри на фото и определи что это за место. "
                    f"Пользователь интересуется {city}. "
                    f"Если узнаёшь — назови, опиши, расскажи что интересного. "
                    f"Если не узнаёшь — честно скажи и предложи написать самому. "
                    f"Без markdown. Кратко."
                )
            }
        ]}],
        max_tokens=400,
    )
    return resp.choices[0].message.content.strip()

async def identify_place(image_base64: str, city: str) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _identify_place_sync, image_base64, city)

# ──────────────────────────────────────────────────────────────
# ВСПОМОГАТЕЛЬНЫЕ
# ──────────────────────────────────────────────────────────────
def full_name(user) -> str:
    parts = [user.first_name or "", user.last_name or ""]
    return " ".join(p for p in parts if p).strip() or user.username or str(user.id)

def _send_main_menu_text(city: str) -> str:
    return (
        f"━━━━━━━━━━━━━━━\n"
        f"🏙 Сейчас: {city}\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"Жми кнопку или пиши что ищешь 👇"
    )

# ──────────────────────────────────────────────────────────────
# ЗАЩИТА ОТ ВТОРОГО ЭКЗЕМПЛЯРА
# ──────────────────────────────────────────────────────────────
_lock_handle = None

def acquire_single_instance_lock():
    global _lock_handle
    _lock_handle = open("/tmp/mestniy_bot.lock", "w")
    try:
        fcntl.flock(_lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (IOError, OSError):
        logging.error("Бот уже запущен в другом процессе. Завершаюсь.")
        sys.exit(1)
    _lock_handle.write(str(os.getpid()))
    _lock_handle.flush()

# ──────────────────────────────────────────────────────────────
# ОБРАБОТЧИК: /start
# ──────────────────────────────────────────────────────────────
@dp.message(CommandStart())
async def cmd_start(msg: Message, state: FSMContext):
    await state.clear()
    user = msg.from_user
    name = full_name(user)

    ref_by = None
    args = msg.text.split() if msg.text else []
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            ref_by = int(args[1].replace("ref_", ""))
            if ref_by == user.id:
                ref_by = None
        except ValueError:
            ref_by = None

    existing = get_user(user.id)
    save_user(user.id, name, user.username, ref_by=ref_by)

    if existing and existing["city"]:
        city = existing["city"]
        await msg.answer(
            f"👋 С возвращением, {user.first_name or 'друг'}!\n\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🏙 Твой город: {city}\n"
            f"━━━━━━━━━━━━━━━\n\n"
            f"Жми кнопку или пиши что ищешь 👇",
            reply_markup=MAIN_KB,
            disable_web_page_preview=True,
        )
        return

    # Новый — без кнопки Отмена (отменять нечего)
    await msg.answer(
        f"Привет, {user.first_name or 'друг'}! 👋\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🗺 Я AI Местный — помогу найти\n"
        f"идеи для прогулок, еды и отдыха\n"
        f"в любом городе России 🇷🇺\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"Напиши название города или курорта 🏙",
        reply_markup=ReplyKeyboardRemove(),
    )
    await state.set_state(UserState.entering_city)

# ──────────────────────────────────────────────────────────────
# ОБРАБОТЧИКИ: ввод и смена города
# ──────────────────────────────────────────────────────────────
@dp.message(F.text == "🏙 Сменить город")
async def change_city(msg: Message, state: FSMContext):
    await state.clear()
    await msg.answer(
        "🏙 Смена города\n\n"
        "━━━━━━━━━━━━━━━\n"
        "Напиши название города или курорта 👇",
        reply_markup=CITY_INPUT_KB,
    )
    await state.set_state(UserState.entering_city)


@dp.message(UserState.entering_city)
async def handle_city_input(msg: Message, state: FSMContext):
    text = msg.text.strip() if msg.text else ""

    if text == "❌ Отмена":
        await state.clear()
        city = get_user_city(msg.from_user.id)
        if city:
            await msg.answer(_send_main_menu_text(city), reply_markup=MAIN_KB)
        else:
            await msg.answer("Напиши название города 🏙")
        return

    thinking = await msg.answer("🔍 Проверяю...")
    try:
        result = await detect_city(text)
    except Exception as e:
        logging.error(f"detect_city error: {e}")
        try:
            await thinking.delete()
        except Exception:
            pass
        await msg.answer("Что-то пошло не так. Попробуй ещё раз 👇", reply_markup=CITY_INPUT_KB)
        return

    try:
        await thinking.delete()
    except Exception:
        pass

    status = result.get("status")

    if status == "ok":
        await _finalize_city(msg, state, result["city"])

    elif status == "destination":
        await _finalize_city(msg, state, result["city"])

    elif status == "region":
        region = result["city"] or text
        await msg.answer(
            f"🗺 {region} — это большой регион.\n\n"
            f"Напиши конкретный город, курорт или район,\n"
            f"в котором планируешь побывать 👇",
            reply_markup=CITY_INPUT_KB,
        )

    elif status == "suggest":
        suggestion = result["suggestion"]
        await state.update_data(suggested_city=suggestion)
        await state.set_state(UserState.confirming_city)
        await msg.answer(
            f"🤔 Вы имеете в виду {suggestion}?\n\nПодтвердите или напишите другой 👇",
            reply_markup=CITY_CONFIRM_KB,
        )

    elif status == "ambiguous":
        variants = result.get("variants") or []
        # Сохраняем полный список вариантов в FSM
        await state.update_data(ambiguous_variants=variants)
        await state.set_state(UserState.confirming_ambiguous)
        # Передаём ИНДЕКС, а не имя — чтобы не потерять регион
        buttons = [
            [InlineKeyboardButton(text=v, callback_data=f"city_pick:{i}")]
            for i, v in enumerate(variants)
        ]
        buttons.append([InlineKeyboardButton(text="✏️ Другой город", callback_data="city_pick:other")])
        await msg.answer(
            "🤔 Нашёл несколько городов с таким названием. Уточни какой именно:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )

    elif status == "foreign":
        await msg.answer(
            "🇷🇺 Пока работаю только по городам и курортам России.\n\n"
            "Напиши российский город, например: Сочи, Казань или Владивосток 👇",
            reply_markup=CITY_INPUT_KB,
        )

    else:  # not_city
        await msg.answer(
            "🤔 Не понял — напиши название конкретного города или курорта.\n\n"
            "Например: Сочи, Казань, Красная Поляна 👇",
            reply_markup=CITY_INPUT_KB,
        )


@dp.message(UserState.confirming_city)
async def handle_city_confirm(msg: Message, state: FSMContext):
    text = msg.text.strip() if msg.text else ""
    if text == "✅ Да":
        data = await state.get_data()
        await _finalize_city(msg, state, data.get("suggested_city", ""))
    elif text in ("❌ Нет, другой город", "❌ Отмена"):
        await state.set_state(UserState.entering_city)
        await msg.answer("Напиши название города ещё раз 👇", reply_markup=CITY_INPUT_KB)
    else:
        await state.set_state(UserState.entering_city)
        await handle_city_input(msg, state)


@dp.callback_query(F.data.startswith("city_pick:"))
async def handle_city_pick(cq: CallbackQuery, state: FSMContext):
    raw = cq.data.split("city_pick:", 1)[1]
    try:
        await cq.message.delete()
    except Exception:
        pass

    if raw == "other":
        await state.set_state(UserState.entering_city)
        await cq.message.answer("Напиши название города 👇", reply_markup=CITY_INPUT_KB)
    else:
        # Получаем полный вариант с регионом по индексу
        try:
            idx = int(raw)
            data = await state.get_data()
            variants = data.get("ambiguous_variants", [])
            city = variants[idx] if idx < len(variants) else raw
        except (ValueError, IndexError):
            city = raw
        await state.clear()
        await _finalize_city(cq.message, state, city, user=cq.from_user)
    await cq.answer()


async def _finalize_city(msg: Message, state: FSMContext, city: str, user=None):
    if user is None:
        user = msg.from_user
    update_city(user.id, city)
    clear_context(user.id)
    await state.clear()

    thinking = await msg.answer(f"🏙 Загружаю {city}...")
    try:
        intro = await get_city_intro(city)
    except Exception:
        intro = f"Отличный выбор — {city}!"
    try:
        await thinking.delete()
    except Exception:
        pass

    await msg.answer(
        f"🏙 {city}\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"{intro}\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"Жми кнопку или пиши что ищешь 👇",
        reply_markup=MAIN_KB,
        disable_web_page_preview=True,
    )

# ──────────────────────────────────────────────────────────────
# CALLBACK: реакции 👍/👎
# ──────────────────────────────────────────────────────────────
@dp.callback_query(F.data.startswith("fb_pos:"))
async def cb_feedback_positive(cq: CallbackQuery):
    response_id = cq.data.split("fb_pos:", 1)[1]
    user = cq.from_user
    meta = get_response_meta(response_id)

    # Защита: только владелец подборки может её оценить
    if meta and meta.get("user_id") and meta["user_id"] != user.id:
        await cq.answer("Эта подборка была создана для другого пользователя.", show_alert=True)
        return

    city     = meta.get("city") or get_user_city(user.id) or ""
    category = meta.get("category", "")
    save_feedback(response_id, user.id, user.username, city, category, "positive")
    try:
        await cq.message.edit_text("👍 Спасибо! Рад, что пригодилось 😊")
    except Exception:
        pass
    await cq.answer("Спасибо!")
    asyncio.create_task(log_feedback_sheets(response_id, user.id, user.username, city, category, "positive"))


@dp.callback_query(F.data.startswith("fb_neg:"))
async def cb_feedback_negative(cq: CallbackQuery):
    response_id = cq.data.split("fb_neg:", 1)[1]
    user = cq.from_user
    meta = get_response_meta(response_id)

    # Защита: только владелец подборки
    if meta and meta.get("user_id") and meta["user_id"] != user.id:
        await cq.answer("Эта подборка была создана для другого пользователя.", show_alert=True)
        return

    try:
        await cq.message.edit_reply_markup(reply_markup=feedback_reasons_kb(response_id))
    except Exception:
        pass
    await cq.answer("Скажи подробнее — что не подошло?")


@dp.callback_query(F.data.startswith("fb_why:"))
async def cb_feedback_reason(cq: CallbackQuery):
    _, response_id, reason = cq.data.split(":", 2)
    user = cq.from_user
    meta = get_response_meta(response_id)

    # Защита: только владелец подборки
    if meta and meta.get("user_id") and meta["user_id"] != user.id:
        await cq.answer("Эта подборка была создана для другого пользователя.", show_alert=True)
        return

    city     = meta.get("city") or get_user_city(user.id) or ""
    category = meta.get("category", "")

    reason_labels = {
        "expensive": "Слишком дорого",
        "far":       "Слишком далеко",
        "format":    "Не мой формат",
        "wrong":     "Место неверное/закрыто",
        "other":     "Хотел другие варианты",
    }
    reason_text = reason_labels.get(reason, reason)

    save_feedback(response_id, user.id, user.username, city, category, "negative", reason_text)
    try:
        await cq.message.edit_text("✅ Отзыв учтён — спасибо, это помогает стать лучше!")
    except Exception:
        pass
    await cq.answer("Учтено!")
    asyncio.create_task(log_feedback_sheets(response_id, user.id, user.username, city, category, "negative", reason_text))

# ──────────────────────────────────────────────────────────────
# ОБЩАЯ ФУНКЦИЯ ОТПРАВКИ РЕЗУЛЬТАТА С РЕАКЦИЯМИ
# ──────────────────────────────────────────────────────────────
async def send_result(msg: Message, raw_answer: str, city: str, category: str,
                      kb=None, with_feedback: bool = True):
    """Парсит JSON, строит текст с ссылками, отправляет с кнопками реакции."""
    text, place_names, resp_type = parse_gpt_response(raw_answer, city)
    full_text = text + BACK_TEXT

    response_id = new_response_id()

    # Реакции показываем только для содержательных подборок
    show_feedback = with_feedback and resp_type in ("places", "route", "single")

    # Сохраняем метаданные для привязки реакции к категории
    if show_feedback:
        save_response_meta(response_id, msg.from_user.id, city, category)

    await send_long(msg, full_text, reply_markup=kb or MAIN_KB, disable_web_page_preview=True)
    if show_feedback:
        await msg.answer("Помогло?", reply_markup=feedback_kb(response_id))

    return place_names

# ──────────────────────────────────────────────────────────────
# ОБРАБОТЧИК: Маршрут на день + Другой маршрут
# ──────────────────────────────────────────────────────────────
async def _generate_route(msg: Message):
    city = get_user_city(msg.from_user.id)
    if not city:
        await msg.answer("Сначала выбери город 🏙", reply_markup=CITY_INPUT_KB)
        return
    if is_flood(msg.from_user.id):
        await msg.answer("⏳ Подожди секунду 😊", reply_markup=MAIN_KB)
        return

    if msg.from_user.id in active_requests:
        await msg.answer("⏳ Уже обрабатываю предыдущий запрос 😊", reply_markup=MAIN_KB)
        return

    # Накопленная история всех предыдущих маршрутов (макс 20 мест)
    prev_places = route_history.get(msg.from_user.id, [])
    exclude_note = ""
    if prev_places:
        exclude_note = (
            f"\n\nУже показывал эти места — постарайся их не включать:\n{', '.join(prev_places)}\n"
            f"Если в городе мало мест и без повторов не обойтись — можно повторить максимум 1-2 "
            f"действительно важных места, но измени остальные точки и логику маршрута."
        )

    thinking = await msg.answer(f"🗺 Составляю маршрут по {city}...")
    active_requests.add(msg.from_user.id)
    try:
        ctx = get_context(msg.from_user.id)
        raw = await ask_ai("🗺 Маршрут на день" + exclude_note, city, ctx)
        try:
            await thinking.delete()
        except Exception:
            pass

        # Сохраняем полный raw в контекст
        _, place_names, _ = parse_gpt_response(raw, city)
        add_to_context(msg.from_user.id, "user", "🗺 Маршрут на день")
        add_to_context(msg.from_user.id, "assistant", raw)

        # Накапливаем историю мест — список, последние 20 уникальных
        history = route_history.setdefault(msg.from_user.id, [])
        for place in place_names:
            if place and place not in history:
                history.append(place)
        route_history[msg.from_user.id] = history[-20:]

        await send_result(msg, raw, city, "Маршрут на день", kb=ROUTE_KB)
        increment_requests(msg.from_user.id)
        asyncio.create_task(log_sheets(
            msg.from_user.id, full_name(msg.from_user),
            msg.from_user.username, "Маршрут на день", f"🗺 {city}", len(raw)))
    except Exception as e:
        logging.error(f"Route error: {e}")
        try:
            await thinking.delete()
        except Exception:
            pass
        await msg.answer("Что-то пошло не так. Попробуй ещё раз." + BACK_TEXT, reply_markup=MAIN_KB)
    finally:
        active_requests.discard(msg.from_user.id)


@dp.message(F.text == "🗺 Маршрут на день")
async def btn_route(msg: Message):
    await _generate_route(msg)

@dp.message(F.text == "🔄 Другой маршрут")
async def btn_another_route(msg: Message):
    await _generate_route(msg)

# ──────────────────────────────────────────────────────────────
# ОБРАБОТЧИК: Где остановиться
# ──────────────────────────────────────────────────────────────
@dp.message(F.text == "🏨 Где остановиться")
async def btn_hotels(msg: Message, state: FSMContext):
    city = get_user_city(msg.from_user.id)
    if not city:
        await msg.answer("Сначала выбери город 🏙", reply_markup=CITY_INPUT_KB)
        await state.set_state(UserState.entering_city)
        return
    await msg.answer(
        f"🏨 Где остановиться в {city}\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"Выбери формат — подберу варианты 👇",
        reply_markup=HOTEL_KB,
    )
    await state.set_state(UserState.choosing_hotel)


@dp.message(UserState.choosing_hotel)
async def handle_hotel_format(msg: Message, state: FSMContext):
    text = msg.text.strip() if msg.text else ""
    if text == "🏠 Главное меню":
        await state.clear()
        city = get_user_city(msg.from_user.id)
        await msg.answer(_send_main_menu_text(city or "—"), reply_markup=MAIN_KB)
        return
    if text not in HOTEL_FORMATS:
        await msg.answer("Выбери формат из кнопок 👇", reply_markup=HOTEL_KB)
        return

    city = get_user_city(msg.from_user.id)
    await state.clear()
    if is_flood(msg.from_user.id):
        await msg.answer("⏳ Подожди секунду 😊", reply_markup=MAIN_KB)
        return

    if msg.from_user.id in active_requests:
        await msg.answer("⏳ Уже обрабатываю предыдущий запрос 😊", reply_markup=MAIN_KB)
        return

    thinking = await msg.answer(f"🏨 Ищу варианты в {city}...")
    active_requests.add(msg.from_user.id)
    try:
        raw = await ask_hotels(city, text)
        try:
            await thinking.delete()
        except Exception:
            pass
        hotel_category = f"Отели: {text}"
        parsed, _, resp_type = parse_gpt_response(raw, city)
        full_text = f"🏨 Где остановиться в {city} — {text}\n\n━━━━━━━━━━━━━━━\n\n" + parsed + BACK_TEXT

        await send_long(msg, full_text, reply_markup=MAIN_KB, disable_web_page_preview=True)

        # Реакция только если парсинг успешен (не error)
        if resp_type in ("places", "single"):
            rid = new_response_id()
            save_response_meta(rid, msg.from_user.id, city, hotel_category)
            await msg.answer("Помогло?", reply_markup=feedback_kb(rid))

        increment_requests(msg.from_user.id)
        asyncio.create_task(log_sheets(
            msg.from_user.id, full_name(msg.from_user),
            msg.from_user.username, hotel_category, f"🏨 {text} в {city}", len(raw)))
    except Exception as e:
        logging.error(f"Hotels error: {e}")
        try:
            await thinking.delete()
        except Exception:
            pass
        await msg.answer("Что-то пошло не так. Попробуй ещё раз." + BACK_TEXT, reply_markup=MAIN_KB)
    finally:
        active_requests.discard(msg.from_user.id)

# ──────────────────────────────────────────────────────────────
# СИСТЕМНЫЕ КНОПКИ
# ──────────────────────────────────────────────────────────────
@dp.message(F.text == "🏠 Главное меню")
async def btn_main_menu(msg: Message, state: FSMContext):
    await state.clear()
    city = get_user_city(msg.from_user.id)
    if not city:
        await msg.answer("Напиши название города 🏙", reply_markup=CITY_INPUT_KB)
        await state.set_state(UserState.entering_city)
        return
    await msg.answer(_send_main_menu_text(city), reply_markup=MAIN_KB)


@dp.message(F.text == "➕ Ещё")
async def btn_more(msg: Message):
    city = get_user_city(msg.from_user.id)
    header = f"🏙 Сейчас: {city}\n" if city else ""
    await msg.answer(f"{header}━━━━━━━━━━━━━━━\nВсе категории 👇", reply_markup=MORE_KB)


@dp.message(F.text == "✏️ Свой вопрос")
async def btn_own(msg: Message):
    city = get_user_city(msg.from_user.id)
    if not city:
        await msg.answer("Сначала выбери город 🏙", reply_markup=CITY_INPUT_KB)
        return
    await msg.answer(
        f"✏️ Свой вопрос\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"Пиши любой вопрос про {city}!\n\n"
        f"Например:\n"
        f"— Где недорого поесть возле вокзала?\n"
        f"— Куда пойти вечером вдвоём?\n"
        f"— Что посмотреть за 4 часа?",
        reply_markup=MAIN_KB,
    )


@dp.message(F.text == "🛠 Поддержка")
async def btn_support(msg: Message):
    await msg.answer(
        "🛠 Поддержка\n\n"
        "━━━━━━━━━━━━━━━\n"
        "💬 Напиши замечание или идею — читаю всё!\n\n"
        "📩 Пиши напрямую: @demo23rus\n"
        "━━━━━━━━━━━━━━━\n\n"
        "✨ Что ещё найдём? Жми или пиши 👇",
        reply_markup=MAIN_KB,
    )


@dp.message(F.text == "ℹ️ О проекте")
async def btn_about(msg: Message):
    await msg.answer(
        "🗺 AI Местный — гид по городам России\n\n"
        "━━━━━━━━━━━━━━━\n"
        "Помогаю находить идеи для поездок:\n\n"
        "🍽 Где поесть и выпить кофе\n"
        "🗺 Маршруты на день\n"
        "🏨 Варианты жилья под твой формат\n"
        "🎭 Куда сходить и что посмотреть\n"
        "💎 Места куда редко доходят туристы\n"
        "📸 Определяю места по фото\n"
        "━━━━━━━━━━━━━━━\n\n"
        "🇷🇺 Работаю по всем городам и курортам России\n\n"
        "━━━━━━━━━━━━━━━\n"
        "💡 Идеи и замечания — жми Поддержка 👇",
        reply_markup=MAIN_KB,
        disable_web_page_preview=True,
    )


@dp.message(F.text == "💬 Оставить отзыв")
async def btn_review(msg: Message, state: FSMContext):
    await msg.answer(
        "💬 Оставить отзыв\n\n"
        "━━━━━━━━━━━━━━━\n"
        "🙏 Напиши свой отзыв или пожелание!\n\n"
        "💡 Что понравилось?\n"
        "🔧 Что можно улучшить?\n"
        "✨ Чего не хватает?\n"
        "━━━━━━━━━━━━━━━",
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
        await msg.answer("👌 В другой раз!\n\n✨ Что ещё найдём? Жми или пиши 👇", reply_markup=MAIN_KB)
        return
    user = msg.from_user
    city = get_user_city(user.id)
    await state.clear()
    await msg.answer(
        "🙏 Спасибо за отзыв!\n\n"
        "━━━━━━━━━━━━━━━\n"
        "💪 Это помогает делать бота лучше!\n"
        "━━━━━━━━━━━━━━━\n\n"
        "✨ Что ещё найдём? Жми или пиши 👇",
        reply_markup=MAIN_KB,
    )
    asyncio.create_task(log_review(user.id, full_name(user), user.username, city or "—", text))

# ──────────────────────────────────────────────────────────────
# КОМАНДЫ
# ──────────────────────────────────────────────────────────────
@dp.message(Command("stats"))
async def cmd_stats(msg: Message):
    if msg.from_user.id != OWNER_ID:
        return
    total, top_cities, active_today, total_req, no_city, pos, neg = get_stats()
    cities_text = "\n".join([f"  {c}: {n} чел." for c, n in top_cities])
    await msg.answer(
        f"📊 Статистика AI Местный v6\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"👥 Пользователей: {total}\n"
        f"🏙 Без города: {no_city}\n"
        f"🟢 Активны сегодня: {active_today}\n"
        f"💬 Всего запросов: {total_req}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"👍 Положительных: {pos}\n"
        f"👎 Отрицательных: {neg}\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"🏙 Топ городов:\n{cities_text}",
    )


@dp.message(Command("help"))
async def cmd_help(msg: Message):
    await msg.answer(
        "🗺 Как пользоваться AI Местным\n\n"
        "━━━━━━━━━━━━━━━\n"
        "🏙 Напиши любой город или курорт России\n"
        "🔘 Жми кнопку — получишь подборку мест\n"
        "✏️ Пиши свободным текстом\n"
        "📸 Скинь фото — определю место\n"
        "🎤 Говори голосом\n"
        "━━━━━━━━━━━━━━━\n\n"
        "Команды: /start /help /about",
        reply_markup=MAIN_KB,
    )


@dp.message(Command("about"))
async def cmd_about(msg: Message):
    await btn_about(msg)

# ──────────────────────────────────────────────────────────────
# ОБРАБОТЧИК: фото
# ──────────────────────────────────────────────────────────────
@dp.message(F.photo)
async def handle_photo(msg: Message, state: FSMContext):
    await state.update_data(photo_file_id=msg.photo[-1].file_id)
    await state.set_state(UserState.waiting_photo_action)
    await msg.answer(
        "📸 Вижу фото!\n\n"
        "━━━━━━━━━━━━━━━\n"
        "🔍 Хочешь узнать что это за место?\n"
        "Или расскажи сам что ищешь 👇",
        reply_markup=PHOTO_KB,
    )


@dp.message(UserState.waiting_photo_action, F.text == "🔍 Определить место")
async def handle_identify_place(msg: Message, state: FSMContext):
    data = await state.get_data()
    file_id = data.get("photo_file_id")
    await state.clear()
    city = get_user_city(msg.from_user.id) or "Россия"
    thinking = await msg.answer("🔍 Анализирую фото...", reply_markup=MAIN_KB)
    tmp_path = None
    try:
        file     = await bot.get_file(file_id)
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
            f"📍 Вот что удалось найти:\n\n"
            f"━━━━━━━━━━━━━━━\n"
            f"{result}\n"
            f"━━━━━━━━━━━━━━━\n\n"
            f"⚠️ Это предположение по фото — проверь по картам.\n\n"
            f"✨ Что ещё найдём? Жми или пиши 👇",
            reply_markup=MAIN_KB,
            disable_web_page_preview=True,
        )
        increment_requests(msg.from_user.id)
    except Exception as e:
        logging.error(f"Photo identify error: {e}")
        try:
            await thinking.delete()
        except Exception:
            pass
        await msg.answer("😔 Не смог обработать фото. Напиши название места текстом 👇", reply_markup=MAIN_KB)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


@dp.message(UserState.waiting_photo_action, F.text == "✏️ Напишу сам")
async def handle_photo_write_self(msg: Message, state: FSMContext):
    await state.clear()
    city = get_user_city(msg.from_user.id)
    await msg.answer(
        f"✏️ Пиши что ищешь{' в ' + city if city else ''} 🚀",
        reply_markup=MAIN_KB,
    )

@dp.message(UserState.waiting_photo_action)
async def handle_photo_other(msg: Message, state: FSMContext):
    await msg.answer("Выбери действие 👇", reply_markup=PHOTO_KB)

# ──────────────────────────────────────────────────────────────
# МЕДИА
# ──────────────────────────────────────────────────────────────
@dp.message(F.video | F.video_note)
async def handle_video(msg: Message):
    city = get_user_city(msg.from_user.id)
    await msg.answer(
        f"🎥 Видео пока не поддерживаю!\n\n"
        f"✏️ Напиши что ищешь{' в ' + city if city else ''} 🗺",
        reply_markup=MAIN_KB,
    )

@dp.message(F.sticker)
async def handle_sticker(msg: Message):
    await msg.answer(
        "😄 Классный стикер!\n\n"
        "📝 Понимаю текст, голосовые и фото.\n"
        "Напиши что ищешь или жми кнопку 👇",
        reply_markup=MAIN_KB,
    )

@dp.message(F.document)
async def handle_document(msg: Message):
    await msg.answer(
        "📄 Документы пока не поддерживаю!\n\n"
        "✏️ Напиши что ищешь или жми кнопку 👇",
        reply_markup=MAIN_KB,
    )

# ──────────────────────────────────────────────────────────────
# ГОЛОСОВЫЕ (Whisper) — антифлуд ПЕРВЫМ
# ──────────────────────────────────────────────────────────────
@dp.message(F.voice)
async def handle_voice(msg: Message):
    if is_flood(msg.from_user.id):
        await msg.answer("⏳ Подожди секунду 😊", reply_markup=MAIN_KB)
        return

    if msg.from_user.id in active_requests:
        await msg.answer("⏳ Уже обрабатываю предыдущий запрос 😊", reply_markup=MAIN_KB)
        return

    await msg.answer("🎤 Распознаю голосовое...")
    active_requests.add(msg.from_user.id)
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
            await msg.answer("Не смог распознать. Напиши текстом 👇" + BACK_TEXT, reply_markup=MAIN_KB)
            return
        city = get_user_city(msg.from_user.id)
        if not city:
            await msg.answer(
                f"Распознал: «{text}»\n\nСначала напиши название города 🏙",
                reply_markup=CITY_INPUT_KB,
            )
            return
        thinking = await msg.answer(f"Распознал: «{text}»\n\nИщу в {city}...")
        ctx = get_context(msg.from_user.id)
        raw = await ask_ai(text, city, ctx)
        try:
            await thinking.delete()
        except Exception:
            pass
        # Сохраняем полный raw в контекст
        add_to_context(msg.from_user.id, "user", text)
        add_to_context(msg.from_user.id, "assistant", raw)
        await send_result(msg, raw, city, "Голосовое")
        increment_requests(msg.from_user.id)
        asyncio.create_task(log_sheets(
            msg.from_user.id, full_name(msg.from_user),
            msg.from_user.username, "Голосовое", f"🎤 {text}", len(raw)))
    except Exception as e:
        logging.error(f"Voice error: {e}")
        await msg.answer("Не смог обработать голосовое. Напиши текстом 👇" + BACK_TEXT, reply_markup=MAIN_KB)
    finally:
        active_requests.discard(msg.from_user.id)
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)

# ──────────────────────────────────────────────────────────────
# ТЕКСТОВЫЕ СООБЩЕНИЯ — основной обработчик
# ──────────────────────────────────────────────────────────────
@dp.message(F.text)
async def handle_text(msg: Message, state: FSMContext):
    text = msg.text.strip() if msg.text else ""

    if text in SYSTEM_BUTTONS:
        return

    user = msg.from_user

    short_reply = SHORT_REPLIES.get(text.lower())
    if short_reply:
        await msg.answer(short_reply, reply_markup=MAIN_KB)
        return

    city = get_user_city(user.id)
    if not city:
        await msg.answer(
            "Сначала напиши название города 🏙",
            reply_markup=CITY_INPUT_KB,
        )
        await state.set_state(UserState.entering_city)
        return

    if is_flood(user.id):
        await msg.answer("⏳ Подожди секунду 😊", reply_markup=MAIN_KB)
        return

    if user.id in active_requests:
        await msg.answer("⏳ Уже обрабатываю твой предыдущий запрос — подожди немного 😊", reply_markup=MAIN_KB)
        return

    is_theme  = text in THEME_BUTTONS
    category  = text if is_theme else "Свободный запрос"
    thinking  = await msg.answer(f"Ищу в {city}...")
    active_requests.add(user.id)
    try:
        ctx = get_context(user.id)
        raw = await ask_ai(text, city, ctx)
        try:
            await thinking.delete()
        except Exception:
            pass

        # Сохраняем полный raw в контекст — модель видит правильный JSON-формат
        add_to_context(user.id, "user", text)
        add_to_context(user.id, "assistant", raw)

        await send_result(msg, raw, city, category, with_feedback=True)
        increment_requests(user.id)
        asyncio.create_task(log_sheets(
            user.id, full_name(user), user.username, category, text, len(raw)))
    except Exception as e:
        logging.error(f"Text error: {e}")
        try:
            await thinking.delete()
        except Exception:
            pass
        await msg.answer("Что-то пошло не так. Попробуй ещё раз." + BACK_TEXT, reply_markup=MAIN_KB)
    finally:
        active_requests.discard(user.id)

# ──────────────────────────────────────────────────────────────
# FALLBACK
# ──────────────────────────────────────────────────────────────
@dp.message()
async def fallback(msg: Message):
    await msg.answer(
        "🤔 Не совсем понял!\n\n"
        "📝 Понимаю текст, голосовые и фото.\n"
        "Напиши что ищешь или жми кнопку 👇",
        reply_markup=MAIN_KB,
    )

# ──────────────────────────────────────────────────────────────
# ЗАПУСК
# ──────────────────────────────────────────────────────────────
async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    acquire_single_instance_lock()
    init_db()
    logging.info("AI Местный v6.0 запущен")
    await dp.start_polling(bot, drop_pending_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
