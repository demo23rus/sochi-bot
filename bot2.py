#!/usr/bin/env python3
"""
AI Местный — персональный консьерж по путешествиям v8.1 World Premium UI
Bot: @mestniy_guide_bot
File: /root/bot2.py
Service: sochi-test

Сборка V8.1 World Premium UI:
- Свободный ввод любого города и курорта мира
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
from datetime import datetime, timedelta
from contextlib import contextmanager

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, ErrorEvent,
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
OPENAI_KEY     = os.environ.get("OPENAI_KEY", "")
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
NO_TRIP_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="✈️ Создать поездку"), KeyboardButton(text="📍 Я уже в городе")],
        [KeyboardButton(text="🔎 Быстро найти место"), KeyboardButton(text="💬 Спросить консьержа")],
        [KeyboardButton(text="✈️ Мои поездки"), KeyboardButton(text="➕ Ещё")],
    ],
    resize_keyboard=True,
    input_field_placeholder="Куда отправимся?",
)


ACTIVE_TRIP_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🗓 Моя поездка"), KeyboardButton(text="🗺 План на сегодня")],
        [KeyboardButton(text="🔎 Быстро найти место"), KeyboardButton(text="💬 Спросить консьержа")],
        [KeyboardButton(text="⭐ Сохранённые места"), KeyboardButton(text="➕ Ещё")],
    ],
    resize_keyboard=True,
    input_field_placeholder="Спроси что угодно о поездке…",
)


# Совместимость со старыми обработчиками V6. В новых экранах используется main_kb_for().
MAIN_KB = ACTIVE_TRIP_KB

QUICK_SEARCH_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🍽 Где поесть"), KeyboardButton(text="☕ Кофе с видом")],
        [KeyboardButton(text="🏛 Что посмотреть"), KeyboardButton(text="🌿 На природу")],
        [KeyboardButton(text="🌇 Красивый вид"), KeyboardButton(text="🎭 Куда сходить")],
        [KeyboardButton(text="👨‍👩‍👧 С детьми"), KeyboardButton(text="💎 Неочевидное место")],
        [KeyboardButton(text="🏨 Где остановиться"), KeyboardButton(text="✏️ Свой вопрос")],
        [KeyboardButton(text="🏠 Главное меню")],
    ],
    resize_keyboard=True,
)

REPLAN_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="☔ Пошёл дождь"), KeyboardButton(text="😴 Мы устали")],
        [KeyboardButton(text="💰 Нужно дешевле"), KeyboardButton(text="🚶 Меньше ходить")],
        [KeyboardButton(text="⏰ Осталось мало времени"), KeyboardButton(text="🌙 Уже поздно")],
        [KeyboardButton(text="❌ Место закрыто"), KeyboardButton(text="🍽 Хотим поесть сейчас")],
        [KeyboardButton(text="🏠 Главное меню")],
    ],
    resize_keyboard=True,
)

MORE_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🔄 Изменить планы"), KeyboardButton(text="✈️ Мои поездки")],
        [KeyboardButton(text="☕ Кофе с видом"), KeyboardButton(text="🌅 На рассвет")],
        [KeyboardButton(text="👨‍👩‍👧 С детьми"), KeyboardButton(text="❤️ Для двоих")],
        [KeyboardButton(text="🏔 На природу"), KeyboardButton(text="🌃 Вечером")],
        [KeyboardButton(text="💎 Неочевидное место"), KeyboardButton(text="🏨 Где остановиться")],
        [KeyboardButton(text="➕ Новая поездка"), KeyboardButton(text="💬 Оставить отзыв")],
        [KeyboardButton(text="ℹ️ О проекте"), KeyboardButton(text="🛠 Поддержка")],
        [KeyboardButton(text="🏠 Главное меню")],
    ],
    resize_keyboard=True,
    input_field_placeholder="Выбери раздел…",
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

TRIPS_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="✈️ Мои поездки"), KeyboardButton(text="➕ Новая поездка")],
        [KeyboardButton(text="🏠 Главное меню")],
    ],
    resize_keyboard=True,
)

TRIP_CREATE_KB = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="❌ Отмена")]],
    resize_keyboard=True,
)

TRIP_DATES_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📅 Указать даты"), KeyboardButton(text="🔢 Указать количество дней")],
        [KeyboardButton(text="🤷 Пока не знаю")],
        [KeyboardButton(text="❌ Отмена")],
    ], resize_keyboard=True,
)

TRIP_PARTY_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="👤 Один"), KeyboardButton(text="❤️ Вдвоём")],
        [KeyboardButton(text="👨‍👩‍👧 С семьёй"), KeyboardButton(text="👥 С друзьями")],
        [KeyboardButton(text="👴 Со старшими"), KeyboardButton(text="✍️ Другой вариант")],
        [KeyboardButton(text="❌ Отмена")],
    ], resize_keyboard=True,
)

TRIP_CHILDREN_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Нет детей")],
        [KeyboardButton(text="До 3 лет"), KeyboardButton(text="4–7 лет")],
        [KeyboardButton(text="8–12 лет"), KeyboardButton(text="13–17 лет")],
        [KeyboardButton(text="Несколько возрастов")],
        [KeyboardButton(text="❌ Отмена")],
    ], resize_keyboard=True,
)

TRIP_BUDGET_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="💚 Экономно"), KeyboardButton(text="💛 Комфортно")],
        [KeyboardButton(text="💎 Выше среднего"), KeyboardButton(text="👑 Премиум")],
        [KeyboardButton(text="⚖️ Смешанный")],
        [KeyboardButton(text="❌ Отмена")],
    ], resize_keyboard=True,
)

TRIP_PACE_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🌿 Спокойный"), KeyboardButton(text="🚶 Умеренный")],
        [KeyboardButton(text="⚡ Насыщенный"), KeyboardButton(text="🎛 Разный по дням")],
        [KeyboardButton(text="❌ Отмена")],
    ], resize_keyboard=True,
)

TRIP_TRANSPORT_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🚶 В основном пешком"), KeyboardButton(text="🚇 Общественный транспорт")],
        [KeyboardButton(text="🚕 Такси"), KeyboardButton(text="🚗 Своя машина")],
        [KeyboardButton(text="🚙 Аренда автомобиля"), KeyboardButton(text="🔀 Комбинированно")],
        [KeyboardButton(text="❌ Отмена")],
    ], resize_keyboard=True,
)

TRIP_ACCOMMODATION_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📍 Указать адрес"), KeyboardButton(text="🏨 Указать отель")],
        [KeyboardButton(text="🗺 Указать район"), KeyboardButton(text="🤷 Пока не знаю")],
        [KeyboardButton(text="❌ Отмена")],
    ], resize_keyboard=True,
)

TRIP_SKIP_KB = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Пропустить")], [KeyboardButton(text="❌ Отмена")]],
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
    "✈️ Мои поездки", "➕ Новая поездка",
    "✈️ Создать поездку", "📍 Я уже в городе", "🔎 Быстро найти место",
    "💬 Спросить консьержа", "🗓 Моя поездка", "🗺 План на сегодня",
    "🔄 Изменить планы", "🏛 Что посмотреть", "🌿 На природу", "🌇 Красивый вид",
    "☔ Пошёл дождь", "😴 Мы устали", "💰 Нужно дешевле", "🚶 Меньше ходить",
    "⏰ Осталось мало времени", "🌙 Уже поздно", "❌ Место закрыто", "🍽 Хотим поесть сейчас",
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

    # V7 — онбординг поездки
    trip_entering_city       = State()
    trip_choosing_dates      = State()
    trip_entering_dates      = State()
    trip_entering_days       = State()
    trip_choosing_party      = State()
    trip_entering_party      = State()
    trip_choosing_children   = State()
    trip_entering_children   = State()
    trip_choosing_budget     = State()
    trip_choosing_pace       = State()
    trip_choosing_transport  = State()
    trip_choosing_interests  = State()
    trip_choosing_accommodation = State()
    trip_entering_accommodation = State()
    trip_entering_special    = State()
    trip_confirming          = State()

    # V7 — управление готовой поездкой
    trip_adding_place         = State()

# ──────────────────────────────────────────────────────────────
# КЛИЕНТЫ
# ──────────────────────────────────────────────────────────────
bot    = Bot(token=BOT_TOKEN)
dp     = Dispatcher(storage=MemoryStorage())
client = OpenAI(api_key=OPENAI_KEY)

# Антифлуд: user_id → timestamp
last_request_time: dict[int, float] = {}

# Блокировка параллельных запросов: не даём отправить второй пока первый ещё идёт
active_requests: set[int] = set()

# Контекст диалога: user_id → список {"role": ..., "content": ...}
dialog_context: dict[int, list] = {}

# История мест маршрутов: user_id → list названий (накапливается, макс 20)
route_history: dict[int, list] = {}

# Антиспам уведомлений владельцу: одинаковая ошибка одному пользователю не чаще 1 раза в 10 минут.
owner_alert_cooldown: dict[str, float] = {}
OWNER_ALERT_COOLDOWN_SECONDS = 600

async def notify_owner_error(
    *,
    user=None,
    action: str,
    error=None,
    trip_id: int | None = None,
    details: str | None = None,
    force: bool = False,
):
    """Сообщает владельцу о пользовательских сбоях, не прерывая работу бота."""
    try:
        user_id = getattr(user, "id", None)
        if user_id == OWNER_ID and not force:
            return
        error_name = type(error).__name__ if error is not None else "Warning"
        error_text = str(error or details or "Без описания").strip()[:900]
        fingerprint = f"{user_id}:{action}:{error_name}:{error_text[:160]}"
        now_ts = time.time()
        if not force and now_ts - owner_alert_cooldown.get(fingerprint, 0) < OWNER_ALERT_COOLDOWN_SECONDS:
            return
        owner_alert_cooldown[fingerprint] = now_ts
        if len(owner_alert_cooldown) > 1000:
            cutoff = now_ts - 86400
            for key in [k for k, ts in owner_alert_cooldown.items() if ts < cutoff]:
                owner_alert_cooldown.pop(key, None)

        name = full_name(user) if user is not None else "Неизвестный пользователь"
        username = f"@{user.username}" if user is not None and getattr(user, "username", None) else "без username"
        lines = [
            "🚨 <b>Ошибка в AI Местном</b>",
            "",
            f"Действие: <b>{html.escape(action)}</b>",
            f"Пользователь: {html.escape(name)}",
            f"ID: <code>{user_id or 'неизвестен'}</code>",
            f"Username: {html.escape(username)}",
        ]
        if trip_id is not None:
            lines.append(f"Поездка: <code>{trip_id}</code>")
        lines.extend([
            f"Тип: <code>{html.escape(error_name)}</code>",
            f"Описание: {html.escape(error_text)}",
            f"Время: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}",
        ])
        await bot.send_message(OWNER_ID, "\n".join(lines), parse_mode="HTML")
    except Exception as notify_error:
        logging.error(f"Owner alert failed: {notify_error}")

# ──────────────────────────────────────────────────────────────
# БАЗА ДАННЫХ V7 — МИГРАЦИИ И РЕПОЗИТОРИИ
# ──────────────────────────────────────────────────────────────
SCHEMA_VERSION = 2


@contextmanager
def db_connection():
    """Единое подключение SQLite с безопасными настройками V7."""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def _add_column_if_missing(conn: sqlite3.Connection, table: str, definition: str):
    """Добавляет колонку в существующую таблицу без пересоздания и потери данных."""
    column_name = definition.split()[0]
    if column_name not in _table_columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")


def _migration_applied(conn: sqlite3.Connection, version: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM schema_migrations WHERE version=?",
        (version,),
    ).fetchone()
    return bool(row)


def _mark_migration(conn: sqlite3.Connection, version: int, name: str):
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
        (version, name, datetime.now().strftime("%d.%m.%Y %H:%M:%S")),
    )


def _create_v7_schema(conn: sqlite3.Connection):
    """Создаёт все новые сущности V7. Повторный запуск безопасен."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version     INTEGER PRIMARY KEY,
            name        TEXT NOT NULL,
            applied_at  TEXT NOT NULL
        )
    """)

    # Пользователи V6 сохраняются. Новые поля добавляются миграцией ниже.
    conn.execute("""
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

    conn.execute("""
        CREATE TABLE IF NOT EXISTS traveler_profiles (
            user_id                 INTEGER PRIMARY KEY,
            default_budget          TEXT,
            default_pace            TEXT,
            default_transport_json  TEXT DEFAULT '[]',
            default_party_type      TEXT,
            children_info_json      TEXT DEFAULT '[]',
            likes_json              TEXT DEFAULT '[]',
            dislikes_json           TEXT DEFAULT '[]',
            walking_limit_km        REAL,
            dietary_preferences_json TEXT DEFAULT '[]',
            accessibility_needs_json TEXT DEFAULT '[]',
            auto_memory_enabled     INTEGER DEFAULT 0,
            created_at              TEXT NOT NULL,
            updated_at              TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS trips (
            trip_id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id                 INTEGER NOT NULL,
            title                   TEXT,
            city                    TEXT NOT NULL,
            country                 TEXT DEFAULT 'Россия',
            country_code            TEXT DEFAULT 'RU',
            region                  TEXT,
            destination_type        TEXT DEFAULT 'city',
            currency                TEXT,
            local_timezone          TEXT,
            local_language          TEXT,
            start_date              TEXT,
            end_date                TEXT,
            days_count              INTEGER,
            status                  TEXT NOT NULL DEFAULT 'draft',
            party_type              TEXT,
            adults_count            INTEGER DEFAULT 1,
            children_json           TEXT DEFAULT '[]',
            budget_level            TEXT,
            pace                    TEXT,
            transport_json          TEXT DEFAULT '[]',
            interests_json          TEXT DEFAULT '[]',
            limitations_json        TEXT DEFAULT '[]',
            accommodation_name      TEXT,
            accommodation_address   TEXT,
            accommodation_lat       REAL,
            accommodation_lon       REAL,
            special_requests        TEXT,
            current_day             INTEGER DEFAULT 1,
            plan_generation_status  TEXT DEFAULT 'not_started',
            migrated_from           TEXT,
            created_at              TEXT NOT NULL,
            updated_at              TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trips_user ON trips(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trips_user_status ON trips(user_id, status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trips_dates ON trips(start_date, end_date)")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS trip_days (
            day_id             INTEGER PRIMARY KEY AUTOINCREMENT,
            trip_id            INTEGER NOT NULL,
            day_number         INTEGER NOT NULL,
            date               TEXT,
            title              TEXT,
            theme              TEXT,
            pace               TEXT,
            walking_distance_km REAL,
            estimated_budget   TEXT,
            weather_summary    TEXT,
            status             TEXT DEFAULT 'planned',
            notes              TEXT,
            created_at         TEXT NOT NULL,
            updated_at         TEXT NOT NULL,
            UNIQUE(trip_id, day_number),
            FOREIGN KEY(trip_id) REFERENCES trips(trip_id) ON DELETE CASCADE
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trip_days_trip ON trip_days(trip_id, day_number)")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS places (
            place_id           INTEGER PRIMARY KEY AUTOINCREMENT,
            external_source    TEXT,
            external_id        TEXT,
            name               TEXT NOT NULL,
            category           TEXT,
            city               TEXT,
            region             TEXT,
            address            TEXT,
            latitude           REAL,
            longitude          REAL,
            rating             REAL,
            review_count       INTEGER,
            price_level        TEXT,
            opening_hours_json TEXT DEFAULT '{}',
            phone              TEXT,
            website            TEXT,
            photo_url          TEXT,
            data_updated_at    TEXT,
            created_at         TEXT NOT NULL,
            UNIQUE(external_source, external_id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_places_city_category ON places(city, category)")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS trip_items (
            item_id            INTEGER PRIMARY KEY AUTOINCREMENT,
            trip_id            INTEGER NOT NULL,
            day_id             INTEGER,
            place_id           INTEGER,
            custom_place_name  TEXT,
            start_time         TEXT,
            end_time           TEXT,
            position           INTEGER NOT NULL DEFAULT 0,
            item_type          TEXT DEFAULT 'place',
            status             TEXT DEFAULT 'planned',
            transport_to_next  TEXT,
            travel_minutes     INTEGER,
            estimated_cost     TEXT,
            personal_reason    TEXT,
            ai_tip             TEXT,
            is_backup          INTEGER DEFAULT 0,
            created_at         TEXT NOT NULL,
            updated_at         TEXT NOT NULL,
            FOREIGN KEY(trip_id) REFERENCES trips(trip_id) ON DELETE CASCADE,
            FOREIGN KEY(day_id) REFERENCES trip_days(day_id) ON DELETE CASCADE,
            FOREIGN KEY(place_id) REFERENCES places(place_id) ON DELETE SET NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trip_items_day ON trip_items(day_id, position)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trip_items_trip ON trip_items(trip_id)")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS saved_places (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            trip_id     INTEGER,
            place_id    INTEGER,
            place_name  TEXT,
            category    TEXT,
            status      TEXT DEFAULT 'saved',
            notes       TEXT,
            saved_at    TEXT NOT NULL,
            UNIQUE(user_id, trip_id, place_id),
            FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY(trip_id) REFERENCES trips(trip_id) ON DELETE CASCADE,
            FOREIGN KEY(place_id) REFERENCES places(place_id) ON DELETE CASCADE
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_saved_places_user ON saved_places(user_id, trip_id)")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS ai_context (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            trip_id     INTEGER,
            role        TEXT NOT NULL,
            content     TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY(trip_id) REFERENCES trips(trip_id) ON DELETE CASCADE
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ai_context_user_trip ON ai_context(user_id, trip_id, id)")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS trip_versions (
            version_id     INTEGER PRIMARY KEY AUTOINCREMENT,
            trip_id        INTEGER NOT NULL,
            version_number INTEGER NOT NULL,
            snapshot_json  TEXT NOT NULL,
            change_reason  TEXT,
            created_at     TEXT NOT NULL,
            UNIQUE(trip_id, version_number),
            FOREIGN KEY(trip_id) REFERENCES trips(trip_id) ON DELETE CASCADE
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS analytics_events (
            event_id        INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER,
            trip_id         INTEGER,
            event_name      TEXT NOT NULL,
            event_data_json TEXT DEFAULT '{}',
            created_at      TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE SET NULL,
            FOREIGN KEY(trip_id) REFERENCES trips(trip_id) ON DELETE SET NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_analytics_event_name ON analytics_events(event_name, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_analytics_user_trip ON analytics_events(user_id, trip_id)")

    # Таблицы V6 сохраняются и расширяются миграцией.
    conn.execute("""
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS responses (
            response_id TEXT PRIMARY KEY,
            user_id     INTEGER,
            city        TEXT,
            category    TEXT,
            created_at  TEXT
        )
    """)


def _apply_v7_migration_1(conn: sqlite3.Connection):
    """V6 → V7: расширяет схему без потери пользователей и реакций."""
    if _migration_applied(conn, 1):
        return

    # Новые поля пользователя. active_trip_id — выбранная поездка интерфейса.
    _add_column_if_missing(conn, "users", "active_trip_id INTEGER DEFAULT NULL")
    _add_column_if_missing(conn, "users", "subscription_type TEXT DEFAULT 'free'")
    _add_column_if_missing(conn, "users", "subscription_until TEXT DEFAULT NULL")
    _add_column_if_missing(conn, "users", "language TEXT DEFAULT 'ru'")
    _add_column_if_missing(conn, "users", "timezone TEXT DEFAULT 'Europe/Moscow'")
    _add_column_if_missing(conn, "users", "onboarding_completed INTEGER DEFAULT 0")
    _add_column_if_missing(conn, "users", "updated_at TEXT DEFAULT NULL")

    # Расширенная привязка аналитики V7.
    for definition in (
        "trip_id INTEGER DEFAULT NULL",
        "day_id INTEGER DEFAULT NULL",
        "place_id INTEGER DEFAULT NULL",
        "query_text TEXT DEFAULT NULL",
        "answer_summary TEXT DEFAULT NULL",
    ):
        _add_column_if_missing(conn, "feedback", definition)

    for definition in (
        "trip_id INTEGER DEFAULT NULL",
        "day_id INTEGER DEFAULT NULL",
        "place_id INTEGER DEFAULT NULL",
    ):
        _add_column_if_missing(conn, "responses", definition)

    # Защита старой feedback-таблицы от дублей перед созданием индекса.
    conn.execute("""
        DELETE FROM feedback
        WHERE id NOT IN (
            SELECT MAX(id)
            FROM feedback
            GROUP BY response_id, user_id
        )
    """)
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_feedback_response_user
        ON feedback(response_id, user_id)
    """)

    # Каждый пользователь V6 с выбранным городом получает безопасный черновик поездки.
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    legacy_users = conn.execute("""
        SELECT user_id, city
        FROM users
        WHERE city IS NOT NULL AND TRIM(city) <> ''
    """).fetchall()
    for row in legacy_users:
        existing = conn.execute("""
            SELECT trip_id FROM trips
            WHERE user_id=? AND migrated_from='v6_city'
            LIMIT 1
        """, (row["user_id"],)).fetchone()
        if existing:
            trip_id = existing["trip_id"]
        else:
            cursor = conn.execute("""
                INSERT INTO trips (
                    user_id, title, city, status, migrated_from,
                    created_at, updated_at
                ) VALUES (?, ?, ?, 'draft', 'v6_city', ?, ?)
            """, (
                row["user_id"],
                f"Поездка в {row['city']}",
                row["city"],
                now,
                now,
            ))
            trip_id = cursor.lastrowid
        conn.execute("""
            UPDATE users
            SET active_trip_id=COALESCE(active_trip_id, ?),
                updated_at=COALESCE(updated_at, ?)
            WHERE user_id=?
        """, (trip_id, now, row["user_id"]))

    _mark_migration(conn, 1, "v6_to_v7_core_schema")


def _apply_v8_world_migration_2(conn: sqlite3.Connection):
    """V8 World: международные поля поездки. Безопасно для существующей базы."""
    if _migration_applied(conn, 2):
        return
    for definition in (
        "country TEXT DEFAULT 'Россия'",
        "country_code TEXT DEFAULT 'RU'",
        "currency TEXT DEFAULT NULL",
        "local_timezone TEXT DEFAULT NULL",
        "local_language TEXT DEFAULT NULL",
    ):
        _add_column_if_missing(conn, "trips", definition)
    conn.execute("UPDATE trips SET country=COALESCE(NULLIF(country,''), 'Россия')")
    conn.execute("UPDATE trips SET country_code=COALESCE(NULLIF(country_code,''), 'RU')")
    _mark_migration(conn, 2, "world_destinations_and_batch_generation")


def init_db():
    """Инициализация V8 World: схема и безопасные миграции."""
    with db_connection() as conn:
        _create_v7_schema(conn)
        _apply_v7_migration_1(conn)
        _apply_v8_world_migration_2(conn)


# ── Пользователи ──────────────────────────────────────────────
def get_user(user_id):
    with db_connection() as conn:
        return conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()


def save_user(user_id, name, username, city=None, ref_by=None):
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    with db_connection() as conn:
        conn.execute("""
            INSERT INTO users (
                user_id, name, username, city, registered_at, last_active,
                ref_by, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                name=excluded.name,
                username=excluded.username,
                last_active=excluded.last_active,
                updated_at=excluded.updated_at
        """, (user_id, name, username or "", city, now, now, ref_by, now))


def update_city(user_id, city):
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    with db_connection() as conn:
        conn.execute(
            "UPDATE users SET city=?, updated_at=? WHERE user_id=?",
            (city, now, user_id),
        )


def increment_requests(user_id):
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    with db_connection() as conn:
        conn.execute("""
            UPDATE users
            SET total_requests=total_requests+1,
                last_active=?,
                updated_at=?
            WHERE user_id=?
        """, (now, now, user_id))


def get_user_city(user_id):
    row = get_user(user_id)
    return row["city"] if row else None


# ── Поездки V7 ────────────────────────────────────────────────
def create_trip(user_id: int, city: str, title: str | None = None,
                destination_type: str = "city", set_active: bool = True,
                **fields) -> int:
    """Создаёт черновик поездки. Архитектура сразу поддерживает несколько поездок."""
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    allowed = {
        "country", "country_code", "region", "currency", "local_timezone", "local_language",
        "start_date", "end_date", "days_count", "status",
        "party_type", "adults_count", "children_json", "budget_level",
        "pace", "transport_json", "interests_json", "limitations_json",
        "accommodation_name", "accommodation_address", "accommodation_lat",
        "accommodation_lon", "special_requests", "current_day",
        "plan_generation_status",
    }
    safe_fields = {k: v for k, v in fields.items() if k in allowed}
    columns = ["user_id", "title", "city", "destination_type", "created_at", "updated_at"]
    values = [user_id, title or f"Поездка в {city}", city, destination_type, now, now]
    columns.extend(safe_fields.keys())
    values.extend(safe_fields.values())
    placeholders = ", ".join("?" for _ in values)

    with db_connection() as conn:
        cursor = conn.execute(
            f"INSERT INTO trips ({', '.join(columns)}) VALUES ({placeholders})",
            values,
        )
        trip_id = cursor.lastrowid
        if set_active:
            conn.execute(
                "UPDATE users SET active_trip_id=?, updated_at=? WHERE user_id=?",
                (trip_id, now, user_id),
            )
    return trip_id


def get_trip(trip_id: int, user_id: int | None = None):
    with db_connection() as conn:
        if user_id is None:
            return conn.execute("SELECT * FROM trips WHERE trip_id=?", (trip_id,)).fetchone()
        return conn.execute(
            "SELECT * FROM trips WHERE trip_id=? AND user_id=?",
            (trip_id, user_id),
        ).fetchone()


def list_user_trips(user_id: int, include_archived: bool = True) -> list[sqlite3.Row]:
    with db_connection() as conn:
        if include_archived:
            rows = conn.execute("""
                SELECT * FROM trips
                WHERE user_id=?
                ORDER BY
                    CASE status
                        WHEN 'active' THEN 0
                        WHEN 'ready' THEN 1
                        WHEN 'planning' THEN 2
                        WHEN 'draft' THEN 3
                        WHEN 'completed' THEN 4
                        ELSE 5
                    END,
                    COALESCE(start_date, '9999-12-31'),
                    updated_at DESC
            """, (user_id,)).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM trips
                WHERE user_id=? AND status NOT IN ('archived', 'cancelled')
                ORDER BY COALESCE(start_date, '9999-12-31'), updated_at DESC
            """, (user_id,)).fetchall()
        return rows


def get_active_trip(user_id: int):
    with db_connection() as conn:
        return conn.execute("""
            SELECT t.*
            FROM users u
            LEFT JOIN trips t ON t.trip_id = u.active_trip_id AND t.user_id = u.user_id
            WHERE u.user_id=?
        """, (user_id,)).fetchone()


def set_active_trip(user_id: int, trip_id: int | None) -> bool:
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    with db_connection() as conn:
        if trip_id is not None:
            owns_trip = conn.execute(
                "SELECT 1 FROM trips WHERE trip_id=? AND user_id=?",
                (trip_id, user_id),
            ).fetchone()
            if not owns_trip:
                return False
        conn.execute(
            "UPDATE users SET active_trip_id=?, updated_at=? WHERE user_id=?",
            (trip_id, now, user_id),
        )
        return True


def update_trip(trip_id: int, user_id: int, **fields) -> bool:
    allowed = {
        "title", "city", "country", "country_code", "region", "destination_type",
        "currency", "local_timezone", "local_language", "start_date", "end_date",
        "days_count", "status", "party_type", "adults_count", "children_json",
        "budget_level", "pace", "transport_json", "interests_json",
        "limitations_json", "accommodation_name", "accommodation_address",
        "accommodation_lat", "accommodation_lon", "special_requests",
        "current_day", "plan_generation_status",
    }
    safe_fields = {k: v for k, v in fields.items() if k in allowed}
    if not safe_fields:
        return False
    safe_fields["updated_at"] = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    assignments = ", ".join(f"{column}=?" for column in safe_fields)
    values = list(safe_fields.values()) + [trip_id, user_id]
    with db_connection() as conn:
        cursor = conn.execute(
            f"UPDATE trips SET {assignments} WHERE trip_id=? AND user_id=?",
            values,
        )
        return cursor.rowcount > 0


def archive_trip(trip_id: int, user_id: int) -> bool:
    updated = update_trip(trip_id, user_id, status="archived")
    if not updated:
        return False
    with db_connection() as conn:
        conn.execute("""
            UPDATE users
            SET active_trip_id=NULL
            WHERE user_id=? AND active_trip_id=?
        """, (user_id, trip_id))
    return True


def delete_trip(trip_id: int, user_id: int) -> bool:
    """Удаление каскадно очищает дни, точки, контекст, версии и сохранения поездки."""
    with db_connection() as conn:
        conn.execute("""
            UPDATE users SET active_trip_id=NULL
            WHERE user_id=? AND active_trip_id=?
        """, (user_id, trip_id))
        cursor = conn.execute(
            "DELETE FROM trips WHERE trip_id=? AND user_id=?",
            (trip_id, user_id),
        )
        return cursor.rowcount > 0


def select_active_trip(user_id: int, trip_id: int) -> bool:
    """Выбирает поездку и синхронизирует legacy-поле users.city для функций V6."""
    trip = get_trip(trip_id, user_id)
    if not trip or trip["status"] in ("archived", "cancelled"):
        return False
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    with db_connection() as conn:
        conn.execute(
            "UPDATE users SET active_trip_id=?, city=?, updated_at=? WHERE user_id=?",
            (trip_id, trip["city"], now, user_id),
        )
    clear_context(user_id)
    log_analytics_event("trip_selected", user_id=user_id, trip_id=trip_id)
    return True


def choose_next_trip(user_id: int) -> int | None:
    """После архивации/удаления выбирает ближайшую доступную поездку."""
    trips = list_user_trips(user_id, include_archived=False)
    if not trips:
        set_active_trip(user_id, None)
        return None
    trip_id = trips[0]["trip_id"]
    select_active_trip(user_id, trip_id)
    return trip_id


def trip_status_label(status: str) -> str:
    return {
        "draft": "Черновик",
        "planning": "Планирование",
        "ready": "Готова",
        "active": "Сейчас идёт",
        "completed": "Завершена",
        "archived": "В архиве",
        "cancelled": "Отменена",
    }.get(status or "", status or "—")


def trip_period_text(trip) -> str:
    if trip["start_date"] and trip["end_date"]:
        return f"{trip['start_date']} — {trip['end_date']}"
    if trip["days_count"]:
        return f"{trip['days_count']} дн. · даты не указаны"
    return "Даты пока не указаны"


def trips_inline_kb(trips, active_trip_id: int | None) -> InlineKeyboardMarkup:
    rows = []
    for trip in trips[:20]:
        marker = "✅ " if trip["trip_id"] == active_trip_id else ""
        title = (trip["title"] or f"Поездка в {trip['city']}")[:48]
        rows.append([InlineKeyboardButton(
            text=f"{marker}{title}", callback_data=f"trip_open:{trip['trip_id']}"
        )])
    rows.append([InlineKeyboardButton(text="➕ Создать новую поездку", callback_data="trip_new")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def trip_card_kb(trip_id: int, is_active: bool, status: str = "draft", has_plan: bool = False) -> InlineKeyboardMarkup:
    rows = []
    if not is_active:
        rows.append([InlineKeyboardButton(text="✓ Выбрать эту поездку", callback_data=f"trip_select:{trip_id}")])
    if has_plan:
        rows.append([InlineKeyboardButton(text="🗓 Маршрут по дням", callback_data=f"trip_plan:{trip_id}")])
        rows.append([
            InlineKeyboardButton(text="⭐ Избранное", callback_data=f"trip_saved:{trip_id}"),
            InlineKeyboardButton(text="↶ История", callback_data=f"trip_versions:{trip_id}"),
        ])
    elif status in ("planning", "ready", "active"):
        rows.append([InlineKeyboardButton(text="✦ Создать персональный план", callback_data=f"trip_generate:{trip_id}")])
    else:
        rows.append([InlineKeyboardButton(text="Продолжить заполнение →", callback_data=f"trip_resume:{trip_id}")])
    rows.append([
        InlineKeyboardButton(text="В архив", callback_data=f"trip_archive_confirm:{trip_id}"),
        InlineKeyboardButton(text="Удалить", callback_data=f"trip_delete_confirm:{trip_id}"),
    ])
    rows.append([InlineKeyboardButton(text="← Все поездки", callback_data="trip_list")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ── Профиль путешественника ──────────────────────────────────
def upsert_traveler_profile(user_id: int, **fields):
    allowed = {
        "default_budget", "default_pace", "default_transport_json",
        "default_party_type", "children_info_json", "likes_json",
        "dislikes_json", "walking_limit_km", "dietary_preferences_json",
        "accessibility_needs_json", "auto_memory_enabled",
    }
    values_map = {k: v for k, v in fields.items() if k in allowed}
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    with db_connection() as conn:
        existing = conn.execute(
            "SELECT 1 FROM traveler_profiles WHERE user_id=?",
            (user_id,),
        ).fetchone()
        if existing:
            if values_map:
                values_map["updated_at"] = now
                assignments = ", ".join(f"{k}=?" for k in values_map)
                conn.execute(
                    f"UPDATE traveler_profiles SET {assignments} WHERE user_id=?",
                    list(values_map.values()) + [user_id],
                )
        else:
            columns = ["user_id", "created_at", "updated_at"] + list(values_map.keys())
            values = [user_id, now, now] + list(values_map.values())
            conn.execute(
                f"INSERT INTO traveler_profiles ({', '.join(columns)}) VALUES ({', '.join('?' for _ in values)})",
                values,
            )


def get_traveler_profile(user_id: int):
    with db_connection() as conn:
        return conn.execute(
            "SELECT * FROM traveler_profiles WHERE user_id=?",
            (user_id,),
        ).fetchone()


# ── Постоянный AI-контекст V7 ────────────────────────────────
def save_ai_context(user_id: int, role: str, content: str, trip_id: int | None = None):
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    with db_connection() as conn:
        conn.execute("""
            INSERT INTO ai_context(user_id, trip_id, role, content, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, trip_id, role, content, now))


def load_ai_context(user_id: int, trip_id: int | None = None, limit: int = 8) -> list[dict]:
    with db_connection() as conn:
        rows = conn.execute("""
            SELECT role, content
            FROM ai_context
            WHERE user_id=? AND trip_id IS ?
            ORDER BY id DESC
            LIMIT ?
        """, (user_id, trip_id, max(1, limit))).fetchall()
    return [dict(row) for row in reversed(rows)]


def clear_ai_context(user_id: int, trip_id: int | None = None):
    with db_connection() as conn:
        conn.execute(
            "DELETE FROM ai_context WHERE user_id=? AND trip_id IS ?",
            (user_id, trip_id),
        )


# ── Аналитика событий V7 ─────────────────────────────────────
def log_analytics_event(event_name: str, user_id: int | None = None,
                        trip_id: int | None = None, event_data: dict | None = None):
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    payload = json.dumps(event_data or {}, ensure_ascii=False)
    with db_connection() as conn:
        conn.execute("""
            INSERT INTO analytics_events(user_id, trip_id, event_name, event_data_json, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, trip_id, event_name, payload, now))


# ── Версии поездки ────────────────────────────────────────────
def create_trip_version(trip_id: int, change_reason: str | None = None) -> int:
    """Сохраняет полный снимок поездки перед перестройкой маршрута."""
    with db_connection() as conn:
        trip = conn.execute("SELECT * FROM trips WHERE trip_id=?", (trip_id,)).fetchone()
        if not trip:
            raise ValueError("Поездка не найдена")
        days = conn.execute(
            "SELECT * FROM trip_days WHERE trip_id=? ORDER BY day_number",
            (trip_id,),
        ).fetchall()
        items = conn.execute(
            "SELECT * FROM trip_items WHERE trip_id=? ORDER BY day_id, position",
            (trip_id,),
        ).fetchall()
        snapshot = {
            "trip": dict(trip),
            "days": [dict(row) for row in days],
            "items": [dict(row) for row in items],
        }
        next_version = conn.execute("""
            SELECT COALESCE(MAX(version_number), 0) + 1
            FROM trip_versions WHERE trip_id=?
        """, (trip_id,)).fetchone()[0]
        cursor = conn.execute("""
            INSERT INTO trip_versions(
                trip_id, version_number, snapshot_json, change_reason, created_at
            ) VALUES (?, ?, ?, ?, ?)
        """, (
            trip_id,
            next_version,
            json.dumps(snapshot, ensure_ascii=False),
            change_reason,
            datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
        ))
        return cursor.lastrowid


# ── Реакции V6/V7 ────────────────────────────────────────────
def save_response_meta(response_id: str, user_id: int, city: str, category: str,
                       trip_id: int | None = None, day_id: int | None = None,
                       place_id: int | None = None):
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    with db_connection() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO responses (
                response_id, user_id, city, category, created_at,
                trip_id, day_id, place_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            response_id, user_id, city or "", category, now,
            trip_id, day_id, place_id,
        ))


def get_response_meta(response_id: str) -> dict:
    with db_connection() as conn:
        row = conn.execute(
            "SELECT * FROM responses WHERE response_id=?",
            (response_id,),
        ).fetchone()
    return dict(row) if row else {}


def save_feedback(response_id, user_id, username, city, category, rating,
                  negative_reason=None, trip_id=None, day_id=None, place_id=None,
                  query_text=None, answer_summary=None):
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    with db_connection() as conn:
        conn.execute("""
            INSERT INTO feedback (
                response_id, user_id, username, city, category, rating,
                negative_reason, created_at, trip_id, day_id, place_id,
                query_text, answer_summary
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(response_id, user_id) DO UPDATE SET
                rating=excluded.rating,
                negative_reason=excluded.negative_reason,
                created_at=excluded.created_at,
                trip_id=COALESCE(excluded.trip_id, feedback.trip_id),
                day_id=COALESCE(excluded.day_id, feedback.day_id),
                place_id=COALESCE(excluded.place_id, feedback.place_id),
                query_text=COALESCE(excluded.query_text, feedback.query_text),
                answer_summary=COALESCE(excluded.answer_summary, feedback.answer_summary)
        """, (
            response_id, user_id, username or "", city or "", category,
            rating, negative_reason, now, trip_id, day_id, place_id,
            query_text, answer_summary,
        ))


def get_stats():
    with db_connection() as conn:
        total = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        top_cities = conn.execute("""
            SELECT city, COUNT(*) cnt
            FROM users
            WHERE city IS NOT NULL
            GROUP BY city
            ORDER BY cnt DESC
            LIMIT 7
        """).fetchall()
        today = datetime.now().strftime("%d.%m.%Y")
        active_today = conn.execute(
            "SELECT COUNT(*) FROM users WHERE last_active LIKE ?",
            (f"{today}%",),
        ).fetchone()[0]
        total_req = conn.execute("SELECT SUM(total_requests) FROM users").fetchone()[0] or 0
        no_city = conn.execute("SELECT COUNT(*) FROM users WHERE city IS NULL").fetchone()[0]
        pos = conn.execute("SELECT COUNT(*) FROM feedback WHERE rating='positive'").fetchone()[0]
        neg = conn.execute("SELECT COUNT(*) FROM feedback WHERE rating='negative'").fetchone()[0]
    return total, [(row[0], row[1]) for row in top_cities], active_today, total_req, no_city, pos, neg

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
def make_map_links(place_name: str, city: str, country: str | None = None) -> str:
    """Россия: Яндекс + 2ГИС. Остальной мир: Google Maps + OpenStreetMap."""
    location = " ".join(x for x in (place_name, city, country or "") if x).strip()
    query = urllib.parse.quote(location)
    country_norm = (country or "Россия").strip().casefold()
    if country_norm in {"россия", "russia", "российская федерация"}:
        yandex = f"https://yandex.ru/maps/?text={query}"
        gis = f"https://2gis.ru/search/{query}"
        return f'🗺 <a href="{yandex}">Яндекс.Карты</a>  ·  <a href="{gis}">2ГИС</a>'
    google = f"https://www.google.com/maps/search/?api=1&query={query}"
    osm = f"https://www.openstreetmap.org/search?query={query}"
    return f'🗺 <a href="{google}">Google Maps</a>  ·  <a href="{osm}">OpenStreetMap</a>'

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
    _append_row([str(user_id), "", f"@{username}" if username else "", now,
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
    """Определяет город/курорт мира и возвращает международные метаданные."""
    prompt = f"""Пользователь ввёл направление: {json.dumps(user_input, ensure_ascii=False)}.

Определи конкретный город, курорт, остров или туристическое направление в любой стране мира.
Ответь ТОЛЬКО валидным JSON без markdown:
{{
  "status": "ok"|"suggest"|"ambiguous"|"destination"|"region"|"not_city",
  "city": "нормализованное русское название" или null,
  "country": "страна на русском" или null,
  "country_code": "ISO-2" или null,
  "region": "регион/провинция/штат" или null,
  "currency": "код валюты ISO-4217" или null,
  "timezone": "IANA timezone" или null,
  "local_language": "основной местный язык" или null,
  "suggestion": "исправленное направление" или null,
  "variants": [{{"label":"Город, страна/регион","city":"...","country":"...","country_code":"...","region":"..."}}] или null
}}

Правила:
- Анталия → Турция, TR, TRY, Europe/Istanbul, турецкий.
- Дубай → ОАЭ, AE, AED, Asia/Dubai, арабский.
- Питер → suggest: Санкт-Петербург, Россия.
- Для одноимённых городов верни ambiguous и 2-5 объектов variants.
- Если указан только большой регион/страна без конкретной базы для маршрута, status=region.
- Если это не направление, status=not_city.
- Не отклоняй иностранные города.
"""
    resp = client.chat.completions.create(
        model=MODEL, messages=[{"role": "user", "content": prompt}],
        max_tokens=450, temperature=0,
    )
    raw = resp.choices[0].message.content.strip().replace("```json", "").replace("```", "").strip()
    data = json.loads(raw)
    if data.get("status") in ("ok", "destination"):
        data["country"] = data.get("country") or "Россия"
        data["country_code"] = (data.get("country_code") or ("RU" if data["country"] == "Россия" else "")).upper()
    return data

CITY_FALLBACK_META = {
    "пермь": {"city":"Пермь","country":"Россия","country_code":"RU","region":"Пермский край","currency":"RUB","timezone":"Asia/Yekaterinburg","local_language":"русский"},
    "стамбул": {"city":"Стамбул","country":"Турция","country_code":"TR","region":"Стамбул","currency":"TRY","timezone":"Europe/Istanbul","local_language":"турецкий"},
    "анталия": {"city":"Анталия","country":"Турция","country_code":"TR","region":"Анталия","currency":"TRY","timezone":"Europe/Istanbul","local_language":"турецкий"},
    "дубай": {"city":"Дубай","country":"ОАЭ","country_code":"AE","region":"Дубай","currency":"AED","timezone":"Asia/Dubai","local_language":"арабский"},
    "москва": {"city":"Москва","country":"Россия","country_code":"RU","region":"Москва","currency":"RUB","timezone":"Europe/Moscow","local_language":"русский"},
    "санкт-петербург": {"city":"Санкт-Петербург","country":"Россия","country_code":"RU","region":"Санкт-Петербург","currency":"RUB","timezone":"Europe/Moscow","local_language":"русский"},
    "питер": {"city":"Санкт-Петербург","country":"Россия","country_code":"RU","region":"Санкт-Петербург","currency":"RUB","timezone":"Europe/Moscow","local_language":"русский"},
    "сочи": {"city":"Сочи","country":"Россия","country_code":"RU","region":"Краснодарский край","currency":"RUB","timezone":"Europe/Moscow","local_language":"русский"},
    "казань": {"city":"Казань","country":"Россия","country_code":"RU","region":"Республика Татарстан","currency":"RUB","timezone":"Europe/Moscow","local_language":"русский"},
    "рим": {"city":"Рим","country":"Италия","country_code":"IT","region":"Лацио","currency":"EUR","timezone":"Europe/Rome","local_language":"итальянский"},
    "париж": {"city":"Париж","country":"Франция","country_code":"FR","region":"Иль-де-Франс","currency":"EUR","timezone":"Europe/Paris","local_language":"французский"},
    "бали": {"city":"Бали","country":"Индонезия","country_code":"ID","region":"Бали","currency":"IDR","timezone":"Asia/Makassar","local_language":"индонезийский"},
}

def _fallback_destination(user_input: str) -> dict:
    clean = " ".join((user_input or "").strip().split())
    key = clean.casefold().replace("ё", "е")
    for known, meta in CITY_FALLBACK_META.items():
        if key == known.replace("ё", "е"):
            return {"status":"ok", **meta, "suggestion":None, "variants":None, "_fallback_used":True}
    if 2 <= len(clean) <= 80 and any(ch.isalpha() for ch in clean):
        return {
            "status":"ok", "city":clean.title(), "country":"Не определена",
            "country_code":"", "region":None, "currency":None,
            "timezone":None, "local_language":None, "suggestion":None, "variants":None, "_fallback_used":True,
        }
    return {"status":"not_city", "city":None, "country":None, "country_code":None,
            "region":None, "currency":None, "timezone":None, "local_language":None,
            "suggestion":None, "variants":None}

async def detect_city(user_input: str) -> dict:
    """AI-проверка с повтором и безопасным локальным резервом."""
    loop = asyncio.get_event_loop()
    last_error = None
    for attempt in range(2):
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, _detect_city_sync, user_input),
                timeout=35,
            )
        except Exception as error:
            last_error = error
            logging.warning(f"detect_city attempt {attempt + 1} failed: {type(error).__name__}: {error}")
            if attempt == 0:
                await asyncio.sleep(1.2)
    logging.error(f"detect_city fallback used: {type(last_error).__name__ if last_error else 'unknown'}: {last_error}")
    result = _fallback_destination(user_input)
    result["_fallback_used"] = True
    result["_fallback_error"] = f"{type(last_error).__name__ if last_error else 'unknown'}: {last_error}"[:500]
    return result

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

    return f"""Ты — AI Местный, русскоязычный travel-консьерж по городам и направлениям всего мира.

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
def parse_gpt_response(raw: str, city: str, country: str | None = None) -> tuple[str, list, str]:
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
                f"{make_map_links(p.get('name', '').strip(), city, country)}\n"
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
                f"{make_map_links(slot.get('name', '').strip(), city, country)}"
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
            f"{make_map_links(data.get('name', '').strip(), city, country)}\n"
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


async def send_inline_step(message: Message, text: str, inline_markup: InlineKeyboardMarkup,
                           parse_mode: str | None = None) -> Message:
    """Убирает старую reply-клавиатуру и превращает это же сообщение в inline-экран."""
    sent = await message.answer(
        text,
        parse_mode=parse_mode,
        reply_markup=ReplyKeyboardRemove(),
    )
    try:
        await sent.edit_reply_markup(reply_markup=inline_markup)
    except Exception as error:
        logging.warning(f"Inline keyboard attach failed: {error}")
        await message.answer(text, parse_mode=parse_mode, reply_markup=inline_markup)
    return sent

# ──────────────────────────────────────────────────────────────
# PREMIUM UI — ЕДИНЫЙ ВИЗУАЛЬНЫЙ ЯЗЫК
# ──────────────────────────────────────────────────────────────
UI_DIVIDER = "━━━━━━━━━━━━━━"


def _country_line(trip) -> str:
    city = html.escape(str(trip["city"] or ""))
    country = html.escape(str(trip["country"] or "")) if "country" in trip.keys() else ""
    return f"{city} · {country}" if country and country.casefold() not in city.casefold() else city


def _trip_card_text(trip, days_count: int = 0, is_active: bool = True) -> str:
    status = trip_status_label(trip["status"])
    state_icon = "●" if is_active else "○"
    title = html.escape(trip["title"] or ("Поездка в " + trip["city"]))
    party = html.escape(trip["party_type"] or "состав не указан")
    budget = html.escape(trip["budget_level"] or "бюджет не указан")
    pace = html.escape(trip["pace"] or "темп не указан")
    plan = f"{days_count} дн. в плане" if days_count else "план ещё не создан"
    return (
        f"✦ <b>{title}</b>\n"
        f"<i>{_country_line(trip)}</i>\n\n"
        f"📅 {html.escape(trip_period_text(trip))}\n"
        f"👥 {party}\n"
        f"💳 {budget} · 🚶 {pace}\n\n"
        f"{UI_DIVIDER}\n"
        f"{state_icon} {html.escape(status)} · {html.escape(plan)}"
    )


def _day_overview_text(day, items) -> str:
    title = html.escape(day["title"] or "Маршрут дня")
    lines = [f"✦ <b>ДЕНЬ {day['day_number']} · {title.upper()}</b>"]
    meta = []
    if day["walking_distance_km"] is not None:
        meta.append(f"👟 ~{day['walking_distance_km']:g} км")
    if day["pace"]:
        meta.append(f"🚶 {html.escape(day['pace'])}")
    if day["estimated_budget"]:
        meta.append(f"💳 {html.escape(day['estimated_budget'])}")
    if meta:
        lines.append(" · ".join(meta))
    lines.append("")
    for item in items:
        time_value = html.escape(item["start_time"] or "—")
        name = html.escape(item["custom_place_name"] or "Активность")
        suffix = "  · запасной" if item["is_backup"] else ""
        lines.append(f"<b>{time_value}</b>  {name}{suffix}")
    lines.append("")
    lines.append("Нажми на точку ниже — покажу детали, карту и управление.")
    return "\n".join(lines)

# ──────────────────────────────────────────────────────────────
# V7: ДИНАМИЧЕСКОЕ МЕНЮ И КОНТЕКСТ АКТИВНОЙ ПОЕЗДКИ
# ──────────────────────────────────────────────────────────────
def main_kb_for(user_id: int):
    return ACTIVE_TRIP_KB if get_active_trip(user_id) else NO_TRIP_KB


def active_trip_summary(trip) -> str:
    if not trip:
        return ""
    interests = []
    try:
        interests = json.loads(trip["interests_json"] or "[]")
    except Exception:
        interests = []
    return (
        f"Активная поездка: {trip['city']}, {trip['country'] or 'Россия'}. "
        f"Даты: {trip_period_text(trip)}. "
        f"Состав: {trip['party_type'] or 'не указан'}. "
        f"Бюджет: {trip['budget_level'] or 'не указан'}. "
        f"Темп: {trip['pace'] or 'не указан'}. "
        f"Транспорт: {trip['transport_json'] or 'не указан'}. "
        f"Интересы: {', '.join(interests) if interests else 'не указаны'}. "
        f"Жильё/район: {trip['accommodation_name'] or trip['accommodation_address'] or 'не указано'}. "
        f"Особые пожелания: {trip['special_requests'] or 'нет'}."
    )


async def show_v7_main_menu(msg: Message, user_id: int):
    trip = get_active_trip(user_id)
    if not trip:
        await msg.answer(
            "✦ <b>AI МЕСТНЫЙ</b>\n"
            "<i>Персональный консьерж в любом городе мира</i>\n\n"
            "Соберу поездку по дням, подберу реальные места и помогу менять планы уже в пути.\n\n"
            "Куда отправимся?",
            parse_mode="HTML", reply_markup=NO_TRIP_KB,
        )
        return
    days = get_trip_days(trip["trip_id"], user_id)
    await msg.answer(
        _trip_card_text(trip, len(days), True) + "\n\nЧто открыть?",
        parse_mode="HTML", reply_markup=ACTIVE_TRIP_KB,
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
        await msg.answer(f"👋 С возвращением, {user.first_name or 'друг'}!")
        await show_v7_main_menu(msg, user.id)
        return

    await msg.answer(
        f"✦ <b>Добро пожаловать, {html.escape(user.first_name or 'друг')}</b>\n\n"
        f"AI Местный — персональный travel-консьерж по России и миру.\n\n"
        f"Создам маршрут под твой темп, бюджет и интересы — от одного дня до большого путешествия.",
        parse_mode="HTML",
        reply_markup=NO_TRIP_KB,
    )

# ──────────────────────────────────────────────────────────────
# V7 ЭТАП 2: КАРКАС ПОЕЗДОК
# ──────────────────────────────────────────────────────────────
async def show_trips(msg: Message, user_id: int):
    trips = list_user_trips(user_id, include_archived=True)
    user = get_user(user_id)
    active_trip_id = user["active_trip_id"] if user else None
    if not trips:
        await msg.answer(
            "✈️ У тебя пока нет поездок.\n\nСоздадим первую?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="➕ Создать поездку", callback_data="trip_new")
            ]]),
        )
        return
    await msg.answer(
        "✈️ Мои поездки\n\n✅ — поездка, с которой сейчас работает бот.\nВыбери поездку:",
        reply_markup=trips_inline_kb(trips, active_trip_id),
    )


@dp.message(Command("trips"))
@dp.message(F.text == "✈️ Мои поездки")
async def btn_my_trips(msg: Message, state: FSMContext):
    await state.clear()
    await show_trips(msg, msg.from_user.id)


def interests_inline_kb(selected: list[str] | None = None) -> InlineKeyboardMarkup:
    selected = set(selected or [])
    items = [
        ("food", "🍽 Местная кухня"), ("history", "🏛 История и архитектура"),
        ("nature", "🌿 Природа"), ("views", "🌇 Красивые виды"),
        ("culture", "🎭 Культура и события"), ("hidden", "💎 Неочевидные места"),
        ("shopping", "🛍 Покупки"), ("nightlife", "🌙 Вечерняя жизнь"),
        ("coffee", "☕ Кофейни"), ("relax", "🧘 Спокойный отдых"),
        ("kids", "👨‍👩‍👧 Детские места"), ("photo", "📸 Фотолокации"),
    ]
    rows = []
    for i in range(0, len(items), 2):
        row = []
        for key, label in items[i:i+2]:
            mark = "✅ " if key in selected else ""
            row.append(InlineKeyboardButton(text=mark + label, callback_data=f"trip_interest:{key}"))
        rows.append(row)
    rows.append([InlineKeyboardButton(text="✅ Готово", callback_data="trip_interests_done")])
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="trip_onboarding_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _json_list_basic(value) -> list:
    if not value:
        return []
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def _format_date_ru(value: str | None) -> str:
    if not value:
        return "—"
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%d.%m.%Y")
    except ValueError:
        return value


def _trip_summary(trip) -> str:
    interests_map = {
        "food":"кухня", "history":"история", "nature":"природа", "views":"виды",
        "culture":"культура", "hidden":"неочевидное", "shopping":"покупки",
        "nightlife":"вечер", "coffee":"кофейни", "relax":"отдых",
        "kids":"с детьми", "photo":"фотолокации",
    }
    interests = [interests_map.get(x, x) for x in _json_list_basic(trip["interests_json"])]
    children = _json_list_basic(trip["children_json"])
    party = trip["party_type"] or "—"
    if children:
        party += " · дети: " + ", ".join(children)
    stay = trip["accommodation_address"] or trip["accommodation_name"] or "пока не указано"
    wishes = trip["special_requests"] or "без особых пожеланий"
    return (
        f"✦ <b>ПРОВЕРЬ ПОЕЗДКУ</b>\n"
        f"<i>{_country_line(trip)}</i>\n\n"
        f"📅 {html.escape(trip_period_text(trip))}\n"
        f"👥 {html.escape(party)}\n"
        f"💳 {html.escape(trip['budget_level'] or '—')}\n"
        f"🚶 {html.escape(trip['pace'] or '—')} · {html.escape(', '.join(_json_list_basic(trip['transport_json'])) or '—')}\n"
        f"🎯 {html.escape(' · '.join(interests) or '—')}\n"
        f"🏨 {html.escape(stay)}\n\n"
        f"<i>{html.escape(wishes)}</i>"
    )


async def _cancel_trip_onboarding(msg: Message, state: FSMContext):
    data = await state.get_data()
    trip_id = data.get("onboarding_trip_id")
    await state.clear()
    await msg.answer(
        "Создание приостановлено. Черновик поездки сохранён — продолжить можно через «Мои поездки».",
        reply_markup=TRIPS_KB,
    )
    if trip_id:
        log_analytics_event("trip_onboarding_paused", user_id=msg.from_user.id, trip_id=trip_id)


async def _ask_trip_dates(msg: Message, state: FSMContext, trip_id: int):
    await state.update_data(onboarding_trip_id=trip_id)
    await state.set_state(UserState.trip_choosing_dates)
    await msg.answer(
        "📅 Когда планируешь поездку?\n\nМожно указать точные даты, только количество дней или оставить это на потом.",
        reply_markup=TRIP_DATES_KB,
    )


async def _resume_trip_onboarding(msg: Message, state: FSMContext, trip_id: int):
    trip = get_trip(trip_id, msg.from_user.id)
    if not trip:
        await msg.answer("Поездка не найдена.", reply_markup=TRIPS_KB)
        return
    select_active_trip(msg.from_user.id, trip_id)
    await state.update_data(onboarding_trip_id=trip_id)
    # Продолжаем с первого незаполненного обязательного блока.
    if not trip["start_date"] and not trip["days_count"]:
        await _ask_trip_dates(msg, state, trip_id)
    elif not trip["party_type"]:
        await state.set_state(UserState.trip_choosing_party)
        await msg.answer("👥 Кто путешествует?", reply_markup=TRIP_PARTY_KB)
    elif not trip["budget_level"]:
        await state.set_state(UserState.trip_choosing_budget)
        await msg.answer("💰 Какой формат поездки предпочитаешь?", reply_markup=TRIP_BUDGET_KB)
    elif not trip["pace"]:
        await state.set_state(UserState.trip_choosing_pace)
        await msg.answer("🚶 Какой темп тебе ближе?", reply_markup=TRIP_PACE_KB)
    elif not _json_list_basic(trip["transport_json"]):
        await state.set_state(UserState.trip_choosing_transport)
        await msg.answer("🚕 Как планируешь передвигаться?", reply_markup=TRIP_TRANSPORT_KB)
    elif not _json_list_basic(trip["interests_json"]):
        await state.set_state(UserState.trip_choosing_interests)
        await send_inline_step(
            msg,
            "🎯 Что особенно интересно? Можно выбрать несколько вариантов.",
            interests_inline_kb(),
        )
    elif not trip["accommodation_address"] and not trip["accommodation_name"]:
        await state.set_state(UserState.trip_choosing_accommodation)
        await msg.answer("🏨 Уже знаешь, где остановишься?", reply_markup=TRIP_ACCOMMODATION_KB)
    elif trip["special_requests"] is None:
        await state.set_state(UserState.trip_entering_special)
        await msg.answer("📝 Есть важные пожелания или ограничения?", reply_markup=TRIP_SKIP_KB)
    else:
        await state.set_state(UserState.trip_confirming)
        confirm_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✨ Подтвердить поездку", callback_data=f"trip_confirm:{trip_id}")],
            [InlineKeyboardButton(text="✏️ Заполнить заново", callback_data=f"trip_restart:{trip_id}")],
            [InlineKeyboardButton(text="❌ Остановиться", callback_data="trip_onboarding_cancel")],
        ])
        await send_inline_step(
            msg,
            _trip_summary(trip) + "\n\nВсё верно?",
            confirm_kb,
            parse_mode="HTML",
        )


@dp.message(F.text == "➕ Новая поездка")
async def btn_new_trip(msg: Message, state: FSMContext):
    await state.clear()
    await state.set_state(UserState.trip_entering_city)
    await msg.answer("✈️ Новая поездка\n\nНапиши город, курорт или остров в любой стране мира 👇", reply_markup=TRIP_CREATE_KB)


@dp.callback_query(F.data == "trip_new")
async def cb_trip_new(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(UserState.trip_entering_city)
    await cq.message.answer("✈️ Новая поездка\n\nНапиши город, курорт или остров в любой стране мира 👇", reply_markup=TRIP_CREATE_KB)
    await cq.answer()


@dp.message(UserState.trip_entering_city)
async def handle_trip_city(msg: Message, state: FSMContext):
    text = msg.text.strip() if msg.text else ""
    if text == "❌ Отмена":
        await state.clear(); await msg.answer("Создание поездки отменено.", reply_markup=MAIN_KB); return
    if not text:
        await msg.answer("Напиши название города или курорта 👇", reply_markup=TRIP_CREATE_KB); return
    thinking = await msg.answer("🔍 Проверяю направление...")
    try:
        result = await detect_city(text)
        if result.get("_fallback_used"):
            await notify_owner_error(
                user=msg.from_user, action="Проверка направления — включён резерв",
                details=result.get("_fallback_error") or f"Город принят резервно: {text}",
            )
    except Exception as e:
        logging.error(f"trip detect_city error: {e}")
        await notify_owner_error(user=msg.from_user, action="Проверка направления", error=e)
        try: await thinking.delete()
        except Exception: pass
        await msg.answer("Не удалось проверить направление. Попробуй ещё раз 👇", reply_markup=TRIP_CREATE_KB); return
    try: await thinking.delete()
    except Exception: pass
    status = result.get("status")
    if status in ("ok", "destination"):
        city = result.get("city") or text
        trip_id = create_trip(
            msg.from_user.id, city,
            destination_type=("destination" if status == "destination" else "city"),
            status="draft",
            country=result.get("country") or "Россия",
            country_code=result.get("country_code") or "RU",
            region=result.get("region"),
            currency=result.get("currency"),
            local_timezone=result.get("timezone"),
            local_language=result.get("local_language"),
        )
        update_city(msg.from_user.id, city); clear_context(msg.from_user.id)
        log_analytics_event("trip_draft_created", user_id=msg.from_user.id, trip_id=trip_id, event_data={"city": city, "source": "onboarding"})
        await _ask_trip_dates(msg, state, trip_id); return
    if status == "suggest" and result.get("suggestion"):
        await msg.answer(f"Похоже, ты имеешь в виду {result['suggestion']}. Напиши название ещё раз для подтверждения 👇", reply_markup=TRIP_CREATE_KB); return
    if status == "ambiguous":
        variants = result.get("variants") or []
        labels = [v.get("label") if isinstance(v, dict) else str(v) for v in variants[:5]]
        await msg.answer("Нашёл несколько вариантов:\n" + "\n".join(f"• {v}" for v in labels) + "\n\nНапиши нужный полностью 👇", reply_markup=TRIP_CREATE_KB); return
    if status == "region":
        await msg.answer("Это большой регион. Напиши конкретный город, курорт или район 👇", reply_markup=TRIP_CREATE_KB); return
    await msg.answer("Не распознал направление. Напиши конкретный город или курорт 👇", reply_markup=TRIP_CREATE_KB)


@dp.message(UserState.trip_choosing_dates)
async def handle_trip_dates_choice(msg: Message, state: FSMContext):
    text = msg.text.strip() if msg.text else ""
    if text == "❌ Отмена": await _cancel_trip_onboarding(msg, state); return
    data = await state.get_data(); trip_id = data.get("onboarding_trip_id")
    if text == "📅 Указать даты":
        await state.set_state(UserState.trip_entering_dates)
        await msg.answer("Напиши даты в формате:\n12.08.2026 - 15.08.2026", reply_markup=TRIP_CREATE_KB); return
    if text == "🔢 Указать количество дней":
        await state.set_state(UserState.trip_entering_days)
        await msg.answer("На сколько дней поездка? Напиши число от 1 до 30.", reply_markup=TRIP_CREATE_KB); return
    if text == "🤷 Пока не знаю":
        update_trip(trip_id, msg.from_user.id, start_date=None, end_date=None, days_count=None)
        await state.set_state(UserState.trip_choosing_party)
        await msg.answer("👥 Кто путешествует?", reply_markup=TRIP_PARTY_KB); return
    await msg.answer("Выбери один вариант кнопкой 👇", reply_markup=TRIP_DATES_KB)


@dp.message(UserState.trip_entering_dates)
async def handle_trip_dates_input(msg: Message, state: FSMContext):
    text = msg.text.strip() if msg.text else ""
    if text == "❌ Отмена": await _cancel_trip_onboarding(msg, state); return
    try:
        left, right = [x.strip() for x in text.replace("—", "-").split("-", 1)]
        start = datetime.strptime(left, "%d.%m.%Y")
        end = datetime.strptime(right, "%d.%m.%Y")
        if end < start: raise ValueError
        days = (end.date() - start.date()).days + 1
        if not 1 <= days <= 30: raise ValueError
    except Exception:
        await msg.answer("Не понял даты. Пример: 12.08.2026 - 15.08.2026\nМаксимум 30 дней.", reply_markup=TRIP_CREATE_KB); return
    trip_id=(await state.get_data()).get("onboarding_trip_id")
    update_trip(trip_id, msg.from_user.id, start_date=start.strftime("%Y-%m-%d"), end_date=end.strftime("%Y-%m-%d"), days_count=days)
    await state.set_state(UserState.trip_choosing_party); await msg.answer("👥 Кто путешествует?", reply_markup=TRIP_PARTY_KB)


@dp.message(UserState.trip_entering_days)
async def handle_trip_days_input(msg: Message, state: FSMContext):
    text=msg.text.strip() if msg.text else ""
    if text == "❌ Отмена": await _cancel_trip_onboarding(msg, state); return
    try: days=int(text)
    except ValueError: days=0
    if not 1 <= days <= 30:
        await msg.answer("Напиши число от 1 до 30.", reply_markup=TRIP_CREATE_KB); return
    trip_id=(await state.get_data()).get("onboarding_trip_id")
    update_trip(trip_id, msg.from_user.id, start_date=None, end_date=None, days_count=days)
    await state.set_state(UserState.trip_choosing_party); await msg.answer("👥 Кто путешествует?", reply_markup=TRIP_PARTY_KB)


@dp.message(UserState.trip_choosing_party)
async def handle_trip_party(msg: Message, state: FSMContext):
    text=msg.text.strip() if msg.text else ""
    if text == "❌ Отмена": await _cancel_trip_onboarding(msg, state); return
    allowed={"👤 Один":"Один", "❤️ Вдвоём":"Вдвоём", "👨‍👩‍👧 С семьёй":"С семьёй", "👥 С друзьями":"С друзьями", "👴 Со старшими":"Со старшими"}
    trip_id=(await state.get_data()).get("onboarding_trip_id")
    if text == "✍️ Другой вариант":
        await state.set_state(UserState.trip_entering_party); await msg.answer("Напиши, кто едет.", reply_markup=TRIP_CREATE_KB); return
    if text not in allowed:
        await msg.answer("Выбери вариант кнопкой 👇", reply_markup=TRIP_PARTY_KB); return
    party=allowed[text]; update_trip(trip_id,msg.from_user.id,party_type=party, adults_count=(1 if party=="Один" else 2))
    if party == "С семьёй":
        await state.set_state(UserState.trip_choosing_children); await msg.answer("👶 Есть дети? Укажи возрастную группу.", reply_markup=TRIP_CHILDREN_KB)
    else:
        update_trip(trip_id,msg.from_user.id,children_json="[]")
        await state.set_state(UserState.trip_choosing_budget); await msg.answer("💰 Какой формат поездки предпочитаешь?", reply_markup=TRIP_BUDGET_KB)


@dp.message(UserState.trip_entering_party)
async def handle_trip_party_custom(msg: Message, state: FSMContext):
    text=msg.text.strip() if msg.text else ""
    if text == "❌ Отмена": await _cancel_trip_onboarding(msg,state); return
    if len(text)<2: await msg.answer("Опиши состав поездки чуть подробнее.", reply_markup=TRIP_CREATE_KB); return
    trip_id=(await state.get_data()).get("onboarding_trip_id"); update_trip(trip_id,msg.from_user.id,party_type=text[:100])
    await state.set_state(UserState.trip_choosing_children); await msg.answer("👶 Есть дети?", reply_markup=TRIP_CHILDREN_KB)


@dp.message(UserState.trip_choosing_children)
async def handle_trip_children(msg: Message, state: FSMContext):
    text=msg.text.strip() if msg.text else ""
    if text == "❌ Отмена": await _cancel_trip_onboarding(msg,state); return
    options={"Нет детей":[], "До 3 лет":["до 3 лет"], "4–7 лет":["4–7 лет"], "8–12 лет":["8–12 лет"], "13–17 лет":["13–17 лет"]}
    if text == "Несколько возрастов":
        await state.set_state(UserState.trip_entering_children); await msg.answer("Напиши возраст детей через запятую, например: 3, 8, 14", reply_markup=TRIP_CREATE_KB); return
    if text not in options: await msg.answer("Выбери вариант кнопкой 👇", reply_markup=TRIP_CHILDREN_KB); return
    trip_id=(await state.get_data()).get("onboarding_trip_id"); update_trip(trip_id,msg.from_user.id,children_json=json.dumps(options[text],ensure_ascii=False))
    await state.set_state(UserState.trip_choosing_budget); await msg.answer("💰 Какой формат поездки предпочитаешь?", reply_markup=TRIP_BUDGET_KB)


@dp.message(UserState.trip_entering_children)
async def handle_trip_children_custom(msg: Message, state: FSMContext):
    text=msg.text.strip() if msg.text else ""
    if text == "❌ Отмена": await _cancel_trip_onboarding(msg,state); return
    ages=[x.strip() for x in text.split(",") if x.strip()]
    if not ages: await msg.answer("Напиши возраст детей через запятую.", reply_markup=TRIP_CREATE_KB); return
    trip_id=(await state.get_data()).get("onboarding_trip_id"); update_trip(trip_id,msg.from_user.id,children_json=json.dumps(ages[:10],ensure_ascii=False))
    await state.set_state(UserState.trip_choosing_budget); await msg.answer("💰 Какой формат поездки предпочитаешь?", reply_markup=TRIP_BUDGET_KB)


@dp.message(UserState.trip_choosing_budget)
async def handle_trip_budget(msg: Message, state: FSMContext):
    text=msg.text.strip() if msg.text else ""
    if text == "❌ Отмена": await _cancel_trip_onboarding(msg,state); return
    allowed={"💚 Экономно":"Экономно", "💛 Комфортно":"Комфортно", "💎 Выше среднего":"Выше среднего", "👑 Премиум":"Премиум", "⚖️ Смешанный":"Смешанный"}
    if text not in allowed: await msg.answer("Выбери вариант кнопкой 👇", reply_markup=TRIP_BUDGET_KB); return
    trip_id=(await state.get_data()).get("onboarding_trip_id"); update_trip(trip_id,msg.from_user.id,budget_level=allowed[text])
    await state.set_state(UserState.trip_choosing_pace); await msg.answer("🚶 Какой темп тебе ближе?", reply_markup=TRIP_PACE_KB)


@dp.message(UserState.trip_choosing_pace)
async def handle_trip_pace(msg: Message, state: FSMContext):
    text=msg.text.strip() if msg.text else ""
    if text == "❌ Отмена": await _cancel_trip_onboarding(msg,state); return
    allowed={"🌿 Спокойный":"Спокойный", "🚶 Умеренный":"Умеренный", "⚡ Насыщенный":"Насыщенный", "🎛 Разный по дням":"Разный по дням"}
    if text not in allowed: await msg.answer("Выбери вариант кнопкой 👇", reply_markup=TRIP_PACE_KB); return
    trip_id=(await state.get_data()).get("onboarding_trip_id"); update_trip(trip_id,msg.from_user.id,pace=allowed[text])
    await state.set_state(UserState.trip_choosing_transport); await msg.answer("🚕 Как планируешь передвигаться?", reply_markup=TRIP_TRANSPORT_KB)


@dp.message(UserState.trip_choosing_transport)
async def handle_trip_transport(msg: Message, state: FSMContext):
    text=msg.text.strip() if msg.text else ""
    if text == "❌ Отмена": await _cancel_trip_onboarding(msg,state); return
    allowed={"🚶 В основном пешком":"Пешком", "🚇 Общественный транспорт":"Общественный транспорт", "🚕 Такси":"Такси", "🚗 Своя машина":"Своя машина", "🚙 Аренда автомобиля":"Аренда автомобиля", "🔀 Комбинированно":"Комбинированно"}
    if text not in allowed: await msg.answer("Выбери вариант кнопкой 👇", reply_markup=TRIP_TRANSPORT_KB); return
    trip_id=(await state.get_data()).get("onboarding_trip_id"); update_trip(trip_id,msg.from_user.id,transport_json=json.dumps([allowed[text]],ensure_ascii=False))
    await state.update_data(selected_interests=[]); await state.set_state(UserState.trip_choosing_interests)
    await send_inline_step(
        msg,
        "🎯 Что особенно интересно? Можно выбрать несколько вариантов.",
        interests_inline_kb(),
    )


@dp.callback_query(F.data.startswith("trip_interest:"))
async def cb_trip_interest(cq: CallbackQuery, state: FSMContext):
    if await state.get_state() != UserState.trip_choosing_interests.state:
        await cq.answer("Этот выбор уже завершён."); return
    key=cq.data.split(":",1)[1]; data=await state.get_data(); selected=data.get("selected_interests",[])
    if key in selected: selected.remove(key)
    else: selected.append(key)
    await state.update_data(selected_interests=selected)
    try: await cq.message.edit_reply_markup(reply_markup=interests_inline_kb(selected))
    except Exception: pass
    await cq.answer("Выбор обновлён")


@dp.callback_query(F.data == "trip_interests_done")
async def cb_trip_interests_done(cq: CallbackQuery, state: FSMContext):
    if await state.get_state() != UserState.trip_choosing_interests.state:
        await cq.answer("Этот шаг уже завершён."); return
    data=await state.get_data(); selected=data.get("selected_interests",[]); trip_id=data.get("onboarding_trip_id")
    if not selected: await cq.answer("Выбери хотя бы один интерес", show_alert=True); return
    update_trip(trip_id,cq.from_user.id,interests_json=json.dumps(selected,ensure_ascii=False))
    await state.set_state(UserState.trip_choosing_accommodation)
    await cq.message.answer("🏨 Уже знаешь, где остановишься?", reply_markup=TRIP_ACCOMMODATION_KB)
    await cq.answer()


@dp.callback_query(F.data == "trip_onboarding_cancel")
async def cb_trip_onboarding_cancel(cq: CallbackQuery, state: FSMContext):
    data=await state.get_data(); trip_id=data.get("onboarding_trip_id"); await state.clear()
    await cq.message.answer("Создание приостановлено. Черновик сохранён.", reply_markup=TRIPS_KB)
    if trip_id: log_analytics_event("trip_onboarding_paused", user_id=cq.from_user.id, trip_id=trip_id)
    await cq.answer()


@dp.message(UserState.trip_choosing_accommodation)
async def handle_trip_accommodation_choice(msg: Message, state: FSMContext):
    text=msg.text.strip() if msg.text else ""
    if text == "❌ Отмена": await _cancel_trip_onboarding(msg,state); return
    trip_id=(await state.get_data()).get("onboarding_trip_id")
    if text == "🤷 Пока не знаю":
        update_trip(trip_id,msg.from_user.id,accommodation_name="Не указано",accommodation_address="")
        await state.set_state(UserState.trip_entering_special); await msg.answer("📝 Есть важные пожелания или ограничения?", reply_markup=TRIP_SKIP_KB); return
    labels={"📍 Указать адрес":"адрес", "🏨 Указать отель":"название отеля", "🗺 Указать район":"район"}
    if text not in labels: await msg.answer("Выбери вариант кнопкой 👇", reply_markup=TRIP_ACCOMMODATION_KB); return
    await state.update_data(accommodation_mode=text); await state.set_state(UserState.trip_entering_accommodation)
    await msg.answer(f"Напиши {labels[text]} проживания.", reply_markup=TRIP_CREATE_KB)


@dp.message(UserState.trip_entering_accommodation)
async def handle_trip_accommodation_input(msg: Message, state: FSMContext):
    text=msg.text.strip() if msg.text else ""
    if text == "❌ Отмена": await _cancel_trip_onboarding(msg,state); return
    if len(text)<2: await msg.answer("Напиши чуть подробнее.", reply_markup=TRIP_CREATE_KB); return
    data=await state.get_data(); trip_id=data.get("onboarding_trip_id"); mode=data.get("accommodation_mode")
    if mode == "🏨 Указать отель": update_trip(trip_id,msg.from_user.id,accommodation_name=text[:200])
    else: update_trip(trip_id,msg.from_user.id,accommodation_address=text[:300])
    await state.set_state(UserState.trip_entering_special); await msg.answer("📝 Есть важные пожелания или ограничения?\nНапример: мало ходим, не любим музеи, нужен дневной сон ребёнка.", reply_markup=TRIP_SKIP_KB)


@dp.message(UserState.trip_entering_special)
async def handle_trip_special(msg: Message, state: FSMContext):
    text=msg.text.strip() if msg.text else ""
    if text == "❌ Отмена": await _cancel_trip_onboarding(msg,state); return
    trip_id=(await state.get_data()).get("onboarding_trip_id")
    update_trip(trip_id,msg.from_user.id,special_requests=("" if text=="Пропустить" else text[:1000]))
    trip=get_trip(trip_id,msg.from_user.id); await state.set_state(UserState.trip_confirming)
    confirm_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✨ Подтвердить поездку", callback_data=f"trip_confirm:{trip_id}")],
        [InlineKeyboardButton(text="✏️ Заполнить заново", callback_data=f"trip_restart:{trip_id}")],
        [InlineKeyboardButton(text="❌ Остановиться", callback_data="trip_onboarding_cancel")],
    ])
    await send_inline_step(
        msg,
        _trip_summary(trip)+"\n\nВсё верно?",
        confirm_kb,
        parse_mode="HTML",
    )


@dp.callback_query(F.data.startswith("trip_confirm:"))
async def cb_trip_confirm(cq: CallbackQuery, state: FSMContext):
    trip_id=int(cq.data.split(":",1)[1]); trip=get_trip(trip_id,cq.from_user.id)
    if not trip: await cq.answer("Поездка не найдена", show_alert=True); return
    update_trip(trip_id,cq.from_user.id,status="planning",plan_generation_status="not_started")
    select_active_trip(cq.from_user.id,trip_id); await state.clear()
    log_analytics_event("trip_onboarding_completed",user_id=cq.from_user.id,trip_id=trip_id,event_data={"city":trip["city"],"days":trip["days_count"]})
    # Inline-кнопки не заменяют старую reply-клавиатуру шага «Пожелания».
    # Сразу возвращаем постоянное меню активной поездки.
    await cq.message.answer("Поездка сохранена. Главное управление — в меню ниже.", reply_markup=ACTIVE_TRIP_KB)
    await cq.message.answer(
        f"✦ <b>{html.escape(trip['city'])} · поездка готова к планированию</b>\n\nПараметры сохранены. Соберу маршрут блоками, учту географию, темп и твои интересы.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✦ Создать маршрут", callback_data=f"trip_generate:{trip_id}")],
            [InlineKeyboardButton(text="Открыть поездку", callback_data=f"trip_open:{trip_id}")],
        ]),
    ); await cq.answer("Поездка подтверждена")


@dp.callback_query(F.data.startswith("trip_restart:"))
async def cb_trip_restart(cq: CallbackQuery, state: FSMContext):
    trip_id=int(cq.data.split(":",1)[1]); trip=get_trip(trip_id,cq.from_user.id)
    if not trip: await cq.answer("Поездка не найдена",show_alert=True); return
    update_trip(trip_id,cq.from_user.id,start_date=None,end_date=None,days_count=None,party_type=None,children_json="[]",budget_level=None,pace=None,transport_json="[]",interests_json="[]",accommodation_name=None,accommodation_address=None,special_requests=None,status="draft")
    await _ask_trip_dates(cq.message,state,trip_id); await cq.answer()


@dp.callback_query(F.data == "trip_list")
async def cb_trip_list(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    await show_trips(cq.message, cq.from_user.id)
    await cq.answer()


@dp.callback_query(F.data.startswith("trip_open:"))
async def cb_trip_open(cq: CallbackQuery):
    try:
        trip_id = int(cq.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await cq.answer("Некорректная поездка", show_alert=True)
        return
    trip = get_trip(trip_id, cq.from_user.id)
    if not trip:
        await cq.answer("Поездка не найдена", show_alert=True)
        return
    user = get_user(cq.from_user.id)
    is_active = bool(user and user["active_trip_id"] == trip_id)
    days = get_trip_days(trip_id, cq.from_user.id)
    await cq.message.answer(
        _trip_card_text(trip, len(days), is_active),
        reply_markup=trip_card_kb(trip_id, is_active, trip["status"], bool(days)),
        parse_mode="HTML",
    )
    await cq.answer()


@dp.callback_query(F.data.startswith("trip_select:"))
async def cb_trip_select(cq: CallbackQuery):
    try:
        trip_id = int(cq.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await cq.answer("Некорректная поездка", show_alert=True)
        return
    if not select_active_trip(cq.from_user.id, trip_id):
        await cq.answer("Не удалось выбрать поездку", show_alert=True)
        return
    trip = get_trip(trip_id, cq.from_user.id)
    await cq.message.answer(
        f"✅ Активная поездка изменена: {trip['city']}\n\nТеперь быстрые запросы и маршруты будут относиться к этому направлению.",
        reply_markup=MAIN_KB,
    )
    await cq.answer("Поездка выбрана")


@dp.callback_query(F.data.startswith("trip_resume:"))
async def cb_trip_resume(cq: CallbackQuery, state: FSMContext):
    try:
        trip_id = int(cq.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await cq.answer("Некорректная поездка", show_alert=True)
        return
    trip = get_trip(trip_id, cq.from_user.id)
    if not trip:
        await cq.answer("Поездка не найдена", show_alert=True)
        return
    await _resume_trip_onboarding(cq.message, state, trip_id)
    await cq.answer()


@dp.callback_query(F.data.startswith("trip_archive_confirm:"))
async def cb_trip_archive_confirm(cq: CallbackQuery):
    trip_id = int(cq.data.split(":", 1)[1])
    trip = get_trip(trip_id, cq.from_user.id)
    if not trip:
        await cq.answer("Поездка не найдена", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Да, в архив", callback_data=f"trip_archive:{trip_id}")],
        [InlineKeyboardButton(text="Отмена", callback_data=f"trip_open:{trip_id}")],
    ])
    await cq.message.answer(f"Убрать поездку «{trip['title']}» в архив?", reply_markup=kb)
    await cq.answer()


@dp.callback_query(F.data.startswith("trip_archive:"))
async def cb_trip_archive(cq: CallbackQuery):
    trip_id = int(cq.data.split(":", 1)[1])
    if not archive_trip(trip_id, cq.from_user.id):
        await cq.answer("Не удалось архивировать", show_alert=True)
        return
    choose_next_trip(cq.from_user.id)
    log_analytics_event("trip_archived", user_id=cq.from_user.id, trip_id=trip_id)
    await cq.message.answer("📦 Поездка перемещена в архив.", reply_markup=TRIPS_KB)
    await cq.answer()


@dp.callback_query(F.data.startswith("trip_delete_confirm:"))
async def cb_trip_delete_confirm(cq: CallbackQuery):
    trip_id = int(cq.data.split(":", 1)[1])
    trip = get_trip(trip_id, cq.from_user.id)
    if not trip:
        await cq.answer("Поездка не найдена", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Да, удалить навсегда", callback_data=f"trip_delete:{trip_id}")],
        [InlineKeyboardButton(text="Отмена", callback_data=f"trip_open:{trip_id}")],
    ])
    await cq.message.answer(
        f"Удалить поездку «{trip['title']}» навсегда? Это действие нельзя отменить.", reply_markup=kb
    )
    await cq.answer()


@dp.callback_query(F.data.startswith("trip_delete:"))
async def cb_trip_delete(cq: CallbackQuery):
    trip_id = int(cq.data.split(":", 1)[1])
    if not delete_trip(trip_id, cq.from_user.id):
        await cq.answer("Не удалось удалить", show_alert=True)
        return
    choose_next_trip(cq.from_user.id)
    log_analytics_event("trip_deleted", user_id=cq.from_user.id, event_data={"trip_id": trip_id})
    await cq.message.answer("🗑 Поездка удалена.", reply_markup=TRIPS_KB)
    await cq.answer()


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
        if result.get("_fallback_used"):
            await notify_owner_error(
                user=msg.from_user, action="Смена города — включён резерв",
                details=result.get("_fallback_error") or f"Город принят резервно: {text}",
            )
    except Exception as e:
        logging.error(f"detect_city error: {e}")
        await notify_owner_error(user=msg.from_user, action="Смена города", error=e)
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
                      kb=None, with_feedback: bool = True, country: str | None = None):
    """Парсит JSON, строит текст с ссылками, отправляет с кнопками реакции."""
    text, place_names, resp_type = parse_gpt_response(raw_answer, city, country)
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
# V7 — ГЕНЕРАТОР ПЛАНА ПОЕЗДКИ ПО ДНЯМ
# ──────────────────────────────────────────────────────────────

def _json_list(value, default=None):
    if default is None:
        default = []
    if not value:
        return default
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else default
    except Exception:
        return default


def _trip_plan_prompt(trip, start_day: int, end_day: int, excluded_names: list[str] | None = None) -> str:
    interests = _json_list(trip["interests_json"])
    transport = _json_list(trip["transport_json"])
    children = _json_list(trip["children_json"])
    excluded_names = excluded_names or []
    block_days = end_day - start_day + 1
    return f"""Ты — премиальный русскоязычный travel-консьерж по поездкам по всему миру.
Составь только очередной блок персонального маршрута.

НАПРАВЛЕНИЕ: {trip['city']}, {trip['country'] or 'Россия'}
РЕГИОН: {trip['region'] or 'не указан'}
ВАЛЮТА: {trip['currency'] or 'не определена'}
МЕСТНЫЙ ЯЗЫК: {trip['local_language'] or 'не определён'}
ВСЕГО ДНЕЙ: {int(trip['days_count'] or 1)}
СЕЙЧАС НУЖНЫ ДНИ: {start_day}-{end_day} ({block_days} дн.)
ДАТЫ: {trip['start_date'] or 'не указаны'} — {trip['end_date'] or 'не указаны'}
СОСТАВ: {trip['party_type'] or 'не указан'}
ДЕТИ: {json.dumps(children, ensure_ascii=False)}
БЮДЖЕТ: {trip['budget_level'] or 'не указан'}
ТЕМП: {trip['pace'] or 'умеренный'}
ТРАНСПОРТ: {json.dumps(transport, ensure_ascii=False)}
ИНТЕРЕСЫ: {json.dumps(interests, ensure_ascii=False)}
ЖИЛЬЁ/РАЙОН: {trip['accommodation_name'] or ''} {trip['accommodation_address'] or ''}
ПОЖЕЛАНИЯ: {trip['special_requests'] or 'нет'}
УЖЕ ИСПОЛЬЗОВАННЫЕ МЕСТА — НЕ ПОВТОРЯТЬ: {json.dumps(excluded_names[-80:], ensure_ascii=False)}

Верни ТОЛЬКО JSON:
{{"type":"trip_plan","title":"Короткое название поездки","concept":"Концепция блока","days":[{{
"day_number":{start_day},"title":"Название дня","theme":"Тема","pace":"спокойный|умеренный|насыщенный",
"walking_distance_km":6.5,"estimated_budget":"Доступный|Средний|Выше среднего","notes":"Практическая заметка",
"items":[{{"start_time":"09:00","end_time":"10:00","name":"Точное официальное название или честная активность",
"item_kind":"place|activity","category":"категория","address":"район/ориентир",
"estimated_cost":"Доступно|Средне|Выше среднего|Бесплатно","personal_reason":"почему подходит",
"ai_tip":"практический совет","transport_to_next":"пешком|такси|транспорт|авто|—","travel_minutes":15,"is_backup":false}}]}}]}}

ОБЯЗАТЕЛЬНО:
- Верни ровно {block_days} дней с day_number {start_day}..{end_day}.
- 4-6 основных пунктов на день, максимум 1 запасной.
- Логичная география и время по возрастанию.
- Для place — только конкретное реально существующее место с официальным названием.
- Для activity — честная общая активность без фиктивного адреса.
- Название конкретного места желательно дать также в оригинальном написании в скобках.
- Учитывай местную культуру, климат и реальные расстояния.
- Не указывай непроверенные часы работы, телефоны и точные цены.
- Не повторяй уже использованные места.
"""


def _generate_trip_plan_chunk_sync(trip, start_day: int, end_day: int, excluded_names: list[str]) -> str:
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role":"system","content":"Верни только строгий валидный JSON. Не добавляй пояснений."},
            {"role":"user","content":_trip_plan_prompt(trip, start_day, end_day, excluded_names)},
        ],
        max_tokens=6500, temperature=0.4,
    )
    return response.choices[0].message.content.strip()


def _repair_trip_plan_chunk_sync(raw: str, trip, start_day: int, end_day: int) -> str:
    count = end_day - start_day + 1
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role":"system","content":"Исправь JSON и верни только валидный JSON."},
            {"role":"user","content":f"Нужен блок ровно из {count} дней, номера {start_day}-{end_day}, для {trip['city']}, {trip['country'] or 'Россия'}. Исправь структуру и обязательные поля.\n\n{raw[:24000]}"},
        ],
        max_tokens=6500, temperature=0.1,
    )
    return response.choices[0].message.content.strip()


async def generate_trip_plan_chunk_ai(trip, start_day: int, end_day: int, excluded_names: list[str]) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _generate_trip_plan_chunk_sync, trip, start_day, end_day, excluded_names)


async def repair_trip_plan_chunk_ai(raw: str, trip, start_day: int, end_day: int) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _repair_trip_plan_chunk_sync, raw, trip, start_day, end_day)


def generation_chunks(days_count: int, chunk_size: int = 4) -> list[tuple[int, int]]:
    return [(start, min(days_count, start + chunk_size - 1)) for start in range(1, days_count + 1, chunk_size)]

def _extract_json_object(raw: str) -> dict:
    cleaned = (raw or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.replace("```json", "").replace("```", "").strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("JSON-объект не найден")
        data = json.loads(cleaned[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("Корень ответа должен быть объектом")
    return data


def validate_trip_plan(raw: str, expected_days: int, start_day: int = 1) -> dict:
    data = _extract_json_object(raw)
    if data.get("type") != "trip_plan":
        raise ValueError("Неверный type")
    days = data.get("days")
    if not isinstance(days, list) or len(days) != expected_days:
        raise ValueError(f"Ожидалось дней: {expected_days}")
    seen_names = set()
    for expected_number, day in enumerate(days, start_day):
        if not isinstance(day, dict):
            raise ValueError("День должен быть объектом")
        day["day_number"] = expected_number
        if not str(day.get("title", "")).strip():
            raise ValueError("У дня нет названия")
        items = day.get("items")
        if not isinstance(items, list) or len(items) < 2:
            raise ValueError("В дне недостаточно точек")
        normalized = []
        previous_time = "00:00"
        for item in items[:7]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            start_time = str(item.get("start_time", "")).strip()
            if not name or len(start_time) != 5 or start_time[2] != ":":
                continue
            try:
                hh, mm = map(int, start_time.split(":"))
                if not (0 <= hh <= 23 and 0 <= mm <= 59):
                    continue
            except Exception:
                continue
            if start_time < previous_time:
                continue
            previous_time = start_time
            key = name.casefold()
            if key in seen_names and not item.get("is_backup"):
                continue
            if not item.get("is_backup"):
                seen_names.add(key)
            item["name"] = name[:250]
            item_kind = str(item.get("item_kind") or "").strip().lower()
            if item_kind not in ("place", "activity"):
                generic_markers = (
                    "кафе с", "семейный ресторан", "ресторан с", "музей истории города",
                    "отдых на пляже", "прогулка по", "завтрак", "обед", "ужин",
                    "свободное время", "поездка к", "экскурсия в музей"
                )
                item_kind = "activity" if any(marker in name.casefold() for marker in generic_markers) else "place"
            item["item_kind"] = item_kind
            item["start_time"] = start_time
            item["end_time"] = str(item.get("end_time", ""))[:5]
            item["travel_minutes"] = max(0, min(int(item.get("travel_minutes") or 0), 300))
            item["is_backup"] = bool(item.get("is_backup", False))
            normalized.append(item)
        if len([x for x in normalized if not x.get("is_backup")]) < 2:
            raise ValueError("После валидации в дне недостаточно точек")
        day["items"] = normalized
        try:
            day["walking_distance_km"] = max(0.0, min(float(day.get("walking_distance_km") or 0), 50.0))
        except Exception:
            day["walking_distance_km"] = None
    data["days"] = days
    data["title"] = str(data.get("title") or "План поездки")[:200]
    data["concept"] = str(data.get("concept") or "")[:1200]
    return data


def save_trip_plan(trip_id: int, user_id: int, plan: dict):
    """Атомарно заменяет план поездки после полной валидации."""
    trip = get_trip(trip_id, user_id)
    if not trip:
        raise ValueError("Поездка не найдена")
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    start_date = None
    if trip["start_date"]:
        try:
            start_date = datetime.strptime(trip["start_date"], "%Y-%m-%d").date()
        except Exception:
            start_date = None
    with db_connection() as conn:
        conn.execute("DELETE FROM trip_items WHERE trip_id=?", (trip_id,))
        conn.execute("DELETE FROM trip_days WHERE trip_id=?", (trip_id,))
        for day in plan["days"]:
            day_number = int(day["day_number"])
            day_date = (start_date + timedelta(days=day_number - 1)).isoformat() if start_date else None
            cursor = conn.execute("""
                INSERT INTO trip_days(
                    trip_id, day_number, date, title, theme, pace,
                    walking_distance_km, estimated_budget, status, notes,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'planned', ?, ?, ?)
            """, (
                trip_id, day_number, day_date,
                str(day.get("title", ""))[:250], str(day.get("theme", ""))[:250],
                str(day.get("pace", ""))[:100], day.get("walking_distance_km"),
                str(day.get("estimated_budget", ""))[:100], str(day.get("notes", ""))[:1000],
                now, now,
            ))
            day_id = cursor.lastrowid
            for position, item in enumerate(day["items"], 1):
                conn.execute("""
                    INSERT INTO trip_items(
                        trip_id, day_id, custom_place_name, start_time, end_time,
                        position, item_type, status, transport_to_next,
                        travel_minutes, estimated_cost, personal_reason, ai_tip,
                        is_backup, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'planned', ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    trip_id, day_id, str(item.get("name", ""))[:250],
                    str(item.get("start_time", ""))[:5], str(item.get("end_time", ""))[:5],
                    position, str(item.get("item_kind", "place"))[:80],
                    str(item.get("transport_to_next", ""))[:100], item.get("travel_minutes", 0),
                    str(item.get("estimated_cost", ""))[:100],
                    str(item.get("personal_reason", ""))[:1200], str(item.get("ai_tip", ""))[:1200],
                    1 if item.get("is_backup") else 0, now, now,
                ))
        conn.execute("""
            UPDATE trips
            SET title=?, status='ready', plan_generation_status='completed', updated_at=?
            WHERE trip_id=? AND user_id=?
        """, (plan.get("title") or trip["title"], now, trip_id, user_id))


def save_trip_plan_chunk(trip_id: int, user_id: int, plan: dict, *, clear_days: bool = False):
    """Сохраняет один блок дней. Готовые предыдущие блоки не теряются."""
    trip = get_trip(trip_id, user_id)
    if not trip:
        raise ValueError("Поездка не найдена")
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    start_date = None
    if trip["start_date"]:
        try: start_date = datetime.strptime(trip["start_date"], "%Y-%m-%d").date()
        except Exception: start_date = None
    with db_connection() as conn:
        if clear_days:
            conn.execute("DELETE FROM trip_items WHERE trip_id=?", (trip_id,))
            conn.execute("DELETE FROM trip_days WHERE trip_id=?", (trip_id,))
        for day in plan["days"]:
            number = int(day["day_number"])
            existing = conn.execute("SELECT day_id FROM trip_days WHERE trip_id=? AND day_number=?", (trip_id, number)).fetchone()
            if existing:
                conn.execute("DELETE FROM trip_items WHERE day_id=?", (existing["day_id"],))
                conn.execute("DELETE FROM trip_days WHERE day_id=?", (existing["day_id"],))
            day_date = (start_date + timedelta(days=number-1)).isoformat() if start_date else None
            cur = conn.execute("""INSERT INTO trip_days(trip_id,day_number,date,title,theme,pace,walking_distance_km,estimated_budget,status,notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,'planned',?,?,?)""",
                (trip_id,number,day_date,str(day.get("title", ""))[:250],str(day.get("theme", ""))[:250],str(day.get("pace", ""))[:100],day.get("walking_distance_km"),str(day.get("estimated_budget", ""))[:100],str(day.get("notes", ""))[:1000],now,now))
            day_id=cur.lastrowid
            for pos,item in enumerate(day["items"],1):
                conn.execute("""INSERT INTO trip_items(trip_id,day_id,custom_place_name,start_time,end_time,position,item_type,status,transport_to_next,travel_minutes,estimated_cost,personal_reason,ai_tip,is_backup,created_at,updated_at) VALUES(?,?,?,?,?,?,?,'planned',?,?,?,?,?,?,?,?)""",
                    (trip_id,day_id,str(item.get("name", ""))[:250],str(item.get("start_time", ""))[:5],str(item.get("end_time", ""))[:5],pos,str(item.get("item_kind", "place"))[:80],str(item.get("transport_to_next", ""))[:100],item.get("travel_minutes",0),str(item.get("estimated_cost", ""))[:100],str(item.get("personal_reason", ""))[:1200],str(item.get("ai_tip", ""))[:1200],1 if item.get("is_backup") else 0,now,now))
        conn.execute("UPDATE trips SET title=COALESCE(NULLIF(?,''),title), updated_at=? WHERE trip_id=? AND user_id=?", (plan.get("title") or "",now,trip_id,user_id))


def get_existing_trip_place_names(trip_id: int) -> list[str]:
    with db_connection() as conn:
        return [r[0] for r in conn.execute("SELECT custom_place_name FROM trip_items WHERE trip_id=? AND item_type='place' AND custom_place_name IS NOT NULL", (trip_id,)).fetchall() if r[0]]


def get_trip_days(trip_id: int, user_id: int):
    with db_connection() as conn:
        return conn.execute("""
            SELECT d.* FROM trip_days d
            JOIN trips t ON t.trip_id=d.trip_id
            WHERE d.trip_id=? AND t.user_id=?
            ORDER BY d.day_number
        """, (trip_id, user_id)).fetchall()


def get_trip_day(day_id: int, user_id: int):
    with db_connection() as conn:
        return conn.execute("""
            SELECT d.*, t.city, t.country, t.title AS trip_title
            FROM trip_days d JOIN trips t ON t.trip_id=d.trip_id
            WHERE d.day_id=? AND t.user_id=?
        """, (day_id, user_id)).fetchone()


def get_day_items(day_id: int, user_id: int):
    with db_connection() as conn:
        return conn.execute("""
            SELECT i.* FROM trip_items i
            JOIN trips t ON t.trip_id=i.trip_id
            WHERE i.day_id=? AND t.user_id=?
            ORDER BY i.position
        """, (day_id, user_id)).fetchall()


def get_trip_item(item_id: int, user_id: int):
    with db_connection() as conn:
        return conn.execute("""
            SELECT i.*, d.day_number, d.title AS day_title, t.city, t.country, t.user_id
            FROM trip_items i
            JOIN trips t ON t.trip_id=i.trip_id
            LEFT JOIN trip_days d ON d.day_id=i.day_id
            WHERE i.item_id=? AND t.user_id=?
        """, (item_id, user_id)).fetchone()


def normalize_day_positions(conn: sqlite3.Connection, day_id: int):
    rows = conn.execute(
        "SELECT item_id FROM trip_items WHERE day_id=? ORDER BY position, item_id",
        (day_id,),
    ).fetchall()
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    for pos, row in enumerate(rows, 1):
        conn.execute(
            "UPDATE trip_items SET position=?, updated_at=? WHERE item_id=?",
            (pos, now, row["item_id"]),
        )


def delete_trip_item(item_id: int, user_id: int) -> tuple[bool, int | None, int | None]:
    item = get_trip_item(item_id, user_id)
    if not item:
        return False, None, None
    create_trip_version(item["trip_id"], "delete_item")
    with db_connection() as conn:
        conn.execute("DELETE FROM trip_items WHERE item_id=?", (item_id,))
        if item["day_id"]:
            normalize_day_positions(conn, item["day_id"])
    return True, item["trip_id"], item["day_id"]


def save_item_to_favorites(item_id: int, user_id: int) -> bool:
    item = get_trip_item(item_id, user_id)
    if not item:
        return False
    place_name = (item["custom_place_name"] or "").strip()
    if not place_name:
        return False
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    with db_connection() as conn:
        exists = conn.execute("""
            SELECT id FROM saved_places
            WHERE user_id=? AND trip_id=? AND lower(place_name)=lower(?)
        """, (user_id, item["trip_id"], place_name)).fetchone()
        if exists:
            return True
        conn.execute("""
            INSERT INTO saved_places(
                user_id, trip_id, place_id, place_name, category, status, notes, saved_at
            ) VALUES (?, ?, ?, ?, ?, 'saved', ?, ?)
        """, (
            user_id, item["trip_id"], item["place_id"], place_name,
            item["item_type"] or "place", item["personal_reason"] or "", now,
        ))
    return True


def list_saved_places(user_id: int, trip_id: int | None = None):
    with db_connection() as conn:
        if trip_id is None:
            return conn.execute("""
                SELECT s.*, t.city, t.title AS trip_title
                FROM saved_places s
                LEFT JOIN trips t ON t.trip_id=s.trip_id
                WHERE s.user_id=?
                ORDER BY s.saved_at DESC
            """, (user_id,)).fetchall()
        return conn.execute("""
            SELECT s.*, t.city, t.title AS trip_title
            FROM saved_places s
            LEFT JOIN trips t ON t.trip_id=s.trip_id
            WHERE s.user_id=? AND s.trip_id=?
            ORDER BY s.saved_at DESC
        """, (user_id, trip_id)).fetchall()


def delete_saved_place(saved_id: int, user_id: int) -> bool:
    with db_connection() as conn:
        cur = conn.execute("DELETE FROM saved_places WHERE id=? AND user_id=?", (saved_id, user_id))
        return cur.rowcount > 0


def move_trip_item(item_id: int, target_day_id: int, user_id: int) -> bool:
    item = get_trip_item(item_id, user_id)
    target = get_trip_day(target_day_id, user_id)
    if not item or not target or item["trip_id"] != target["trip_id"]:
        return False
    create_trip_version(item["trip_id"], "move_item")
    old_day_id = item["day_id"]
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    with db_connection() as conn:
        max_pos = conn.execute(
            "SELECT COALESCE(MAX(position), 0) FROM trip_items WHERE day_id=?",
            (target_day_id,),
        ).fetchone()[0]
        conn.execute("""
            UPDATE trip_items
            SET day_id=?, position=?, updated_at=?
            WHERE item_id=?
        """, (target_day_id, max_pos + 1, now, item_id))
        if old_day_id:
            normalize_day_positions(conn, old_day_id)
        normalize_day_positions(conn, target_day_id)
    return True


def add_custom_trip_item(day_id: int, user_id: int, name: str) -> int | None:
    day = get_trip_day(day_id, user_id)
    name = name.strip()
    if not day or not name:
        return None
    create_trip_version(day["trip_id"], "add_custom_item")
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    with db_connection() as conn:
        max_pos = conn.execute(
            "SELECT COALESCE(MAX(position), 0) FROM trip_items WHERE day_id=?",
            (day_id,),
        ).fetchone()[0]
        cur = conn.execute("""
            INSERT INTO trip_items(
                trip_id, day_id, custom_place_name, position, item_type, status,
                personal_reason, ai_tip, is_backup, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'place', 'planned', ?, ?, 0, ?, ?)
        """, (
            day["trip_id"], day_id, name, max_pos + 1,
            "Добавлено пользователем", "Уточни часы работы и маршрут перед визитом.", now, now,
        ))
        return cur.lastrowid


def list_trip_versions(trip_id: int, user_id: int, limit: int = 10):
    trip = get_trip(trip_id, user_id)
    if not trip:
        return []
    with db_connection() as conn:
        return conn.execute("""
            SELECT version_id, version_number, change_reason, created_at
            FROM trip_versions
            WHERE trip_id=?
            ORDER BY version_number DESC
            LIMIT ?
        """, (trip_id, limit)).fetchall()


def restore_trip_version(version_id: int, user_id: int) -> int | None:
    with db_connection() as conn:
        version = conn.execute("""
            SELECT v.*, t.user_id
            FROM trip_versions v JOIN trips t ON t.trip_id=v.trip_id
            WHERE v.version_id=? AND t.user_id=?
        """, (version_id, user_id)).fetchone()
    if not version:
        return None
    snapshot = json.loads(version["snapshot_json"])
    trip_id = version["trip_id"]
    create_trip_version(trip_id, "before_restore")
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    with db_connection() as conn:
        conn.execute("DELETE FROM trip_items WHERE trip_id=?", (trip_id,))
        conn.execute("DELETE FROM trip_days WHERE trip_id=?", (trip_id,))
        day_map = {}
        for day in snapshot.get("days", []):
            old_day_id = day.get("day_id")
            cols = [
                "trip_id", "day_number", "date", "title", "theme", "pace",
                "walking_distance_km", "estimated_budget", "weather_summary",
                "status", "notes", "created_at", "updated_at",
            ]
            vals = [
                trip_id, day.get("day_number"), day.get("date"), day.get("title"),
                day.get("theme"), day.get("pace"), day.get("walking_distance_km"),
                day.get("estimated_budget"), day.get("weather_summary"),
                day.get("status") or "planned", day.get("notes"), now, now,
            ]
            cur = conn.execute(
                f"INSERT INTO trip_days ({', '.join(cols)}) VALUES ({', '.join('?' for _ in vals)})",
                vals,
            )
            day_map[old_day_id] = cur.lastrowid
        for item in snapshot.get("items", []):
            new_day_id = day_map.get(item.get("day_id"))
            conn.execute("""
                INSERT INTO trip_items(
                    trip_id, day_id, place_id, custom_place_name, start_time, end_time,
                    position, item_type, status, transport_to_next, travel_minutes,
                    estimated_cost, personal_reason, ai_tip, is_backup, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trip_id, new_day_id, item.get("place_id"), item.get("custom_place_name"),
                item.get("start_time"), item.get("end_time"), item.get("position") or 0,
                item.get("item_type") or "place", item.get("status") or "planned",
                item.get("transport_to_next"), item.get("travel_minutes"),
                item.get("estimated_cost"), item.get("personal_reason"), item.get("ai_tip"),
                item.get("is_backup") or 0, now, now,
            ))
        conn.execute(
            "UPDATE trips SET plan_generation_status='completed', updated_at=? WHERE trip_id=?",
            (now, trip_id),
        )
    return trip_id


def _replace_item_sync(item: sqlite3.Row, trip: sqlite3.Row, other_names: list[str]) -> dict:
    prompt = f"""Ты заменяешь одну точку в готовом туристическом маршруте по России и миру.
Город: {trip['city']}
Заменяемое место: {item['custom_place_name']}
День: {item['day_number']}
Время: {item['start_time'] or 'не задано'}
Категория: {item['item_type'] or 'place'}
Другие места маршрута, которые нельзя повторять: {', '.join(other_names)}
Бюджет поездки: {trip['budget_level'] or 'не указан'}
Темп: {trip['pace'] or 'не указан'}
Интересы: {trip['interests_json'] or '[]'}

Верни ТОЛЬКО JSON:
{{
  "name": "точное официальное название нового реального места",
  "category": "категория",
  "personal_reason": "почему подходит именно этой поездке",
  "ai_tip": "практический совет",
  "estimated_cost": "Доступные|Средние|Выше среднего",
  "transport_to_next": "пешком|такси|транспорт",
  "travel_minutes": 15
}}
Не выдумывай место, если не уверен. Не повторяй другие точки."""
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=500,
        temperature=0.5,
    )
    raw = resp.choices[0].message.content.strip().replace("```json", "").replace("```", "").strip()
    data = json.loads(raw)
    if not str(data.get("name", "")).strip():
        raise ValueError("AI не вернул название замены")
    if str(data["name"]).strip().lower() in {n.lower() for n in other_names}:
        raise ValueError("AI повторил существующее место")
    return data


async def replace_trip_item_ai(item_id: int, user_id: int) -> bool:
    item = get_trip_item(item_id, user_id)
    if not item:
        return False
    trip = get_trip(item["trip_id"], user_id)
    with db_connection() as conn:
        other_names = [r[0] for r in conn.execute(
            "SELECT custom_place_name FROM trip_items WHERE trip_id=? AND item_id<>?",
            (item["trip_id"], item_id),
        ).fetchall() if r[0]]
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, _replace_item_sync, item, trip, other_names)
    create_trip_version(item["trip_id"], "replace_item")
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    with db_connection() as conn:
        conn.execute("""
            UPDATE trip_items SET
                custom_place_name=?, item_type=?, personal_reason=?, ai_tip=?,
                estimated_cost=?, transport_to_next=?, travel_minutes=?, updated_at=?
            WHERE item_id=?
        """, (
            str(data.get("name", ""))[:250], "place",
            str(data.get("personal_reason", ""))[:1200], str(data.get("ai_tip", ""))[:1200],
            str(data.get("estimated_cost", ""))[:100], str(data.get("transport_to_next", ""))[:100],
            max(0, min(int(data.get("travel_minutes") or 0), 240)), now, item_id,
        ))
    return True


def trip_plan_kb(trip_id: int, days) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(
        text=f"День {day['day_number']}  ·  {str(day['title'])[:34]}",
        callback_data=f"trip_day:{day['day_id']}"
    )] for day in days]
    rows.append([InlineKeyboardButton(text="↻ Пересобрать весь маршрут", callback_data=f"trip_regenerate:{trip_id}")])
    rows.append([InlineKeyboardButton(text="← К поездке", callback_data=f"trip_open:{trip_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _item_is_specific_place(item) -> bool:
    """Не показывает фиктивные карты для общих активностей."""
    if (item["item_type"] or "").lower() == "activity":
        return False
    name = (item["custom_place_name"] or "").strip().casefold()
    generic_markers = (
        "кафе с видом", "семейный ресторан", "ресторан с видом",
        "музей истории города", "отдых на пляже", "свободное время",
        "завтрак рядом", "обед рядом", "ужин рядом", "прогулка по"
    )
    return bool(name) and not any(marker in name for marker in generic_markers)


def _day_manage_kb(day, items) -> InlineKeyboardMarkup:
    rows = []
    for item in items:
        label = str(item["custom_place_name"] or "Точка")[:31]
        clock = str(item["start_time"] or "")[:5]
        rows.append([InlineKeyboardButton(
            text=f"{clock}  ·  {label}", callback_data=f"item_manage:{item['item_id']}"
        )])
    rows.extend([
        [InlineKeyboardButton(text="＋ Добавить точку", callback_data=f"item_add:{day['day_id']}")],
        [InlineKeyboardButton(text="← Все дни", callback_data=f"trip_plan:{day['trip_id']}"),
         InlineKeyboardButton(text="Поездка", callback_data=f"trip_open:{day['trip_id']}")],
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _day_text(day, items) -> str:
    return _day_overview_text(day, items)


async def show_trip_day(message: Message, day_id: int, user_id: int, *, notice: str | None = None) -> bool:
    """Единый показ дня после открытия и любых изменений маршрута."""
    day = get_trip_day(day_id, user_id)
    if not day:
        await message.answer("День не найден.", reply_markup=main_kb_for(user_id))
        return False
    items = get_day_items(day_id, user_id)
    if notice:
        await message.answer(notice, reply_markup=ACTIVE_TRIP_KB)
    await send_long(
        message, _day_text(day, items), parse_mode="HTML",
        reply_markup=_day_manage_kb(day, items),
    )
    return True


async def _run_trip_generation(msg: Message, user_id: int, trip_id: int, regenerate: bool = False):
    trip = get_trip(trip_id, user_id)
    if not trip:
        await msg.answer("Поездка не найдена.")
        return
    days_count = int(trip["days_count"] or 0)
    if days_count < 1:
        await msg.answer("Сначала укажи количество дней поездки.", reply_markup=TRIPS_KB)
        return
    if user_id in active_requests:
        await msg.answer("⏳ План уже создаётся. Дождись завершения текущего блока.")
        return
    active_requests.add(user_id)
    update_trip(trip_id, user_id, plan_generation_status="generating")
    log_analytics_event("trip_generation_started", user_id=user_id, trip_id=trip_id, event_data={"regenerate":regenerate,"days":days_count,"mode":"batch"})
    progress = await msg.answer(f"✦ <b>СОБИРАЮ МАРШРУТ</b>\n<i>{html.escape(trip['city'])} · {days_count} дней</i>\n\nПодбираю районы и связываю дни в логичную поездку…", parse_mode="HTML")
    completed = []
    try:
        if regenerate and get_trip_days(trip_id, user_id):
            create_trip_version(trip_id, "full_regeneration")
            with db_connection() as conn:
                conn.execute("DELETE FROM trip_items WHERE trip_id=?", (trip_id,))
                conn.execute("DELETE FROM trip_days WHERE trip_id=?", (trip_id,))
        existing_numbers = {d["day_number"] for d in get_trip_days(trip_id, user_id)}
        chunks = generation_chunks(days_count, 4)
        for index,(start_day,end_day) in enumerate(chunks,1):
            needed=[n for n in range(start_day,end_day+1) if n not in existing_numbers]
            if not needed:
                completed.append(f"✅ Дни {start_day}–{end_day} уже готовы")
                continue
            # Если блок частично сохранён, пересобираем весь блок для связности.
            excluded=get_existing_trip_place_names(trip_id)
            await progress.edit_text("✦ <b>СОБИРАЮ МАРШРУТ</b>\n\n" + "\n".join(completed + [f"◌ Дни {start_day}–{end_day} · создаю…"]))
            raw=await generate_trip_plan_chunk_ai(trip,start_day,end_day,excluded)
            try:
                plan=validate_trip_plan(raw,end_day-start_day+1,start_day=start_day)
            except Exception as first_error:
                logging.warning(f"Chunk {start_day}-{end_day} validation failed: {first_error}")
                repaired=await repair_trip_plan_chunk_ai(raw,trip,start_day,end_day)
                plan=validate_trip_plan(repaired,end_day-start_day+1,start_day=start_day)
            save_trip_plan_chunk(trip_id,user_id,plan)
            existing_numbers.update(range(start_day,end_day+1))
            completed.append(f"✅ Дни {start_day}–{end_day} готовы")
            await progress.edit_text("✦ <b>СОБИРАЮ МАРШРУТ</b>\n\n" + "\n".join(completed) + (f"\n\nОсталось дней: {days_count-end_day}" if end_day < days_count else ""))
        all_days=get_trip_days(trip_id,user_id)
        if len(all_days) != days_count:
            raise ValueError(f"Сохранено {len(all_days)} из {days_count} дней")
        update_trip(trip_id,user_id,status="ready",plan_generation_status="completed")
        increment_requests(user_id)
        log_analytics_event("trip_generation_success",user_id=user_id,trip_id=trip_id,event_data={"days":days_count,"chunks":len(chunks)})
        try: await progress.delete()
        except Exception: pass
        await msg.answer("Маршрут готов. Всё управление — в меню ниже.", reply_markup=ACTIVE_TRIP_KB)
        await msg.answer(
            f"✦ <b>МАРШРУТ ГОТОВ</b>\n<i>{html.escape(trip['city'])} · {html.escape(trip['country'] or 'Россия')} · {days_count} дней</i>\n\nОткрывай день — сначала увидишь компактный план, затем детали каждой точки.",
            parse_mode="HTML", reply_markup=trip_plan_kb(trip_id,all_days))
    except Exception as e:
        logging.exception(f"Batch generation error: {e}")
        await notify_owner_error(user=msg.from_user, action="Генерация маршрута", error=e, trip_id=trip_id)
        update_trip(trip_id,user_id,plan_generation_status="failed")
        ready=len(get_trip_days(trip_id,user_id))
        log_analytics_event("trip_generation_failed",user_id=user_id,trip_id=trip_id,event_data={"error":str(e)[:500],"ready_days":ready})
        try: await progress.delete()
        except Exception: pass
        await msg.answer(
            f"Не удалось завершить очередной блок. Уже сохранено дней: {ready} из {days_count}.\nПовторный запуск продолжит с недостающего блока.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔄 Продолжить генерацию",callback_data=f"trip_generate:{trip_id}")],[InlineKeyboardButton(text="⬅️ К поездке",callback_data=f"trip_open:{trip_id}")]]))
    finally:
        active_requests.discard(user_id)


@dp.callback_query(F.data.startswith("trip_generate:"))
async def cb_trip_generate(cq: CallbackQuery):
    try: trip_id = int(cq.data.split(":", 1)[1])
    except Exception: await cq.answer("Некорректная поездка", show_alert=True); return
    await cq.answer("Начинаю создавать план")
    await _run_trip_generation(cq.message, cq.from_user.id, trip_id, regenerate=False)


@dp.callback_query(F.data.startswith("trip_regenerate:"))
async def cb_trip_regenerate(cq: CallbackQuery):
    try: trip_id = int(cq.data.split(":", 1)[1])
    except Exception: await cq.answer("Некорректная поездка", show_alert=True); return
    await cq.answer("Пересобираю план")
    await _run_trip_generation(cq.message, cq.from_user.id, trip_id, regenerate=True)


@dp.callback_query(F.data.startswith("trip_plan:"))
async def cb_trip_plan(cq: CallbackQuery):
    try: trip_id = int(cq.data.split(":", 1)[1])
    except Exception: await cq.answer("Некорректная поездка", show_alert=True); return
    trip = get_trip(trip_id, cq.from_user.id)
    if not trip: await cq.answer("Поездка не найдена", show_alert=True); return
    days = get_trip_days(trip_id, cq.from_user.id)
    if not days:
        await cq.answer("План ещё не создан", show_alert=True); return
    await cq.message.answer(
        f"🗓 <b>{html.escape(trip['title'] or ('Поездка в ' + trip['city']))}</b>\n\nВыбери день:",
        parse_mode="HTML", reply_markup=trip_plan_kb(trip_id, days)
    )
    await cq.answer()


@dp.callback_query(F.data.startswith("trip_day:"))
async def cb_trip_day(cq: CallbackQuery):
    try: day_id = int(cq.data.split(":", 1)[1])
    except Exception: await cq.answer("Некорректный день", show_alert=True); return
    day = get_trip_day(day_id, cq.from_user.id)
    if not day: await cq.answer("День не найден", show_alert=True); return
    await show_trip_day(cq.message, day_id, cq.from_user.id)
    log_analytics_event("trip_day_opened", user_id=cq.from_user.id, trip_id=day["trip_id"], event_data={"day": day["day_number"]})
    await cq.answer()


@dp.callback_query(F.data.startswith("trip_saved:"))
async def cb_trip_saved(cq: CallbackQuery):
    try: trip_id = int(cq.data.split(":", 1)[1])
    except Exception: await cq.answer("Некорректная поездка", show_alert=True); return
    rows = list_saved_places(cq.from_user.id, trip_id)
    if not rows:
        await cq.answer("В этой поездке пока нет сохранённых мест", show_alert=True); return
    text = "⭐ <b>Сохранённые места поездки</b>\n\n" + "\n\n".join(
        f"{i}. {html.escape(r['place_name'] or 'Место')}" for i, r in enumerate(rows, 1)
    )
    await cq.message.answer(text, parse_mode="HTML")
    await cq.answer()


# ──────────────────────────────────────────────────────────────
# V7 — УПРАВЛЕНИЕ ГОТОВОЙ ПОЕЗДКОЙ
# ──────────────────────────────────────────────────────────────
@dp.callback_query(F.data.startswith("item_manage:"))
async def cb_item_manage(cq: CallbackQuery):
    try:
        item_id = int(cq.data.split(":", 1)[1])
    except Exception:
        await cq.answer("Некорректное место", show_alert=True)
        return
    item = get_trip_item(item_id, cq.from_user.id)
    if not item:
        await cq.answer("Место не найдено", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↻ Заменить", callback_data=f"item_replace:{item_id}"),
         InlineKeyboardButton(text="☆ Сохранить", callback_data=f"item_save:{item_id}")],
        [InlineKeyboardButton(text="Перенести в другой день", callback_data=f"item_move_choose:{item_id}")],
        [InlineKeyboardButton(text="Удалить из маршрута", callback_data=f"item_delete_confirm:{item_id}")],
        [InlineKeyboardButton(text="← Назад к дню", callback_data=f"trip_day:{item['day_id']}")],
    ])
    name = html.escape(item["custom_place_name"] or "Место")
    details = [
        f"✦ <b>{name}</b>",
        f"<i>День {item['day_number']} · {html.escape(item['start_time'] or 'время не задано')}</i>",
    ]
    if item["estimated_cost"]:
        details.append(f"\n💳 {html.escape(item['estimated_cost'])}")
    if item["personal_reason"]:
        details.append(f"\n{html.escape(item['personal_reason'])}")
    if item["ai_tip"]:
        details.append(f"\n💡 <b>Совет</b>\n{html.escape(item['ai_tip'])}")
    if item["travel_minutes"]:
        details.append(f"\n🚶 До следующей точки: около {item['travel_minutes']} мин.")
    if _item_is_specific_place(item):
        details.append("\n" + make_map_links(item["custom_place_name"] or "", item["city"], item["country"]))
    else:
        details.append("\n📍 Общая активность — выбери удобное место рядом.")
    await cq.message.answer("\n".join(details), parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)
    await cq.answer()


@dp.callback_query(F.data.startswith("item_save:"))
async def cb_item_save(cq: CallbackQuery):
    try: item_id = int(cq.data.split(":", 1)[1])
    except Exception: await cq.answer("Некорректное место", show_alert=True); return
    if save_item_to_favorites(item_id, cq.from_user.id):
        item = get_trip_item(item_id, cq.from_user.id)
        log_analytics_event("place_saved", user_id=cq.from_user.id, trip_id=item["trip_id"] if item else None)
        await cq.answer("Сохранено ⭐", show_alert=True)
    else:
        await cq.answer("Не удалось сохранить", show_alert=True)


@dp.callback_query(F.data.startswith("item_delete_confirm:"))
async def cb_item_delete_confirm(cq: CallbackQuery):
    try: item_id = int(cq.data.split(":", 1)[1])
    except Exception: await cq.answer("Некорректное место", show_alert=True); return
    item = get_trip_item(item_id, cq.from_user.id)
    if not item: await cq.answer("Место не найдено", show_alert=True); return
    await cq.message.answer(
        f"Удалить «{html.escape(item['custom_place_name'] or 'это место')}» из маршрута?",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗑 Да, удалить", callback_data=f"item_delete:{item_id}")],
            [InlineKeyboardButton(text="Отмена", callback_data=f"trip_day:{item['day_id']}")],
        ]),
    )
    await cq.answer()


@dp.callback_query(F.data.startswith("item_delete:"))
async def cb_item_delete(cq: CallbackQuery):
    try: item_id = int(cq.data.split(":", 1)[1])
    except Exception: await cq.answer("Некорректное место", show_alert=True); return
    ok, trip_id, day_id = delete_trip_item(item_id, cq.from_user.id)
    if not ok: await cq.answer("Место не найдено", show_alert=True); return
    log_analytics_event("trip_item_deleted", user_id=cq.from_user.id, trip_id=trip_id)
    await cq.answer("Удалено")
    if day_id:
        await show_trip_day(cq.message, day_id, cq.from_user.id, notice="✅ Маршрут обновлён.")


@dp.callback_query(F.data.startswith("item_replace:"))
async def cb_item_replace(cq: CallbackQuery):
    try: item_id = int(cq.data.split(":", 1)[1])
    except Exception: await cq.answer("Некорректное место", show_alert=True); return
    item = get_trip_item(item_id, cq.from_user.id)
    if not item: await cq.answer("Место не найдено", show_alert=True); return
    if cq.from_user.id in active_requests:
        await cq.answer("Уже выполняю другой запрос", show_alert=True); return
    active_requests.add(cq.from_user.id)
    await cq.answer("Подбираю замену")
    thinking = await cq.message.answer("🔄 Ищу подходящую замену…")
    try:
        await replace_trip_item_ai(item_id, cq.from_user.id)
        updated = get_trip_item(item_id, cq.from_user.id)
        log_analytics_event("trip_item_replaced", user_id=cq.from_user.id, trip_id=updated["trip_id"] if updated else None)
        try: await thinking.delete()
        except Exception: pass
        await show_trip_day(
            cq.message, updated["day_id"], cq.from_user.id,
            notice=f"✅ Заменил на {updated['custom_place_name']}."
        )
    except Exception as e:
        logging.exception(f"Replace item error: {e}")
        await notify_owner_error(user=cq.from_user, action="Замена места в маршруте", error=e, trip_id=item["trip_id"] if item else None)
        try: await thinking.delete()
        except Exception: pass
        await cq.message.answer("Не смог надёжно подобрать замену. Попробуй ещё раз позже.")
    finally:
        active_requests.discard(cq.from_user.id)


@dp.callback_query(F.data.startswith("item_move_choose:"))
async def cb_item_move_choose(cq: CallbackQuery):
    try: item_id = int(cq.data.split(":", 1)[1])
    except Exception: await cq.answer("Некорректное место", show_alert=True); return
    item = get_trip_item(item_id, cq.from_user.id)
    if not item: await cq.answer("Место не найдено", show_alert=True); return
    days = get_trip_days(item["trip_id"], cq.from_user.id)
    rows = [[InlineKeyboardButton(
        text=f"День {d['day_number']} — {str(d['title'] or '')[:35]}",
        callback_data=f"item_move:{item_id}:{d['day_id']}"
    )] for d in days if d["day_id"] != item["day_id"]]
    if not rows:
        await cq.answer("В поездке только один день", show_alert=True); return
    rows.append([InlineKeyboardButton(text="Отмена", callback_data=f"trip_day:{item['day_id']}")])
    await cq.message.answer("В какой день перенести место?", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await cq.answer()


@dp.callback_query(F.data.startswith("item_move:"))
async def cb_item_move(cq: CallbackQuery):
    try:
        _, item_id, day_id = cq.data.split(":", 2)
        item_id, day_id = int(item_id), int(day_id)
    except Exception:
        await cq.answer("Некорректные данные", show_alert=True); return
    if not move_trip_item(item_id, day_id, cq.from_user.id):
        await cq.answer("Не удалось перенести", show_alert=True); return
    item = get_trip_item(item_id, cq.from_user.id)
    log_analytics_event("trip_item_moved", user_id=cq.from_user.id, trip_id=item["trip_id"] if item else None)
    await cq.answer("Перенесено", show_alert=True)
    await show_trip_day(
        cq.message, day_id, cq.from_user.id,
        notice=f"✅ Место перенесено в день {item['day_number']}."
    )


@dp.callback_query(F.data.startswith("item_add:"))
async def cb_item_add(cq: CallbackQuery, state: FSMContext):
    try: day_id = int(cq.data.split(":", 1)[1])
    except Exception: await cq.answer("Некорректный день", show_alert=True); return
    day = get_trip_day(day_id, cq.from_user.id)
    if not day: await cq.answer("День не найден", show_alert=True); return
    await state.set_state(UserState.trip_adding_place)
    await state.update_data(add_place_day_id=day_id)
    await cq.message.answer(
        "Напиши название места, которое хочешь добавить в этот день.",
        reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Отмена")]], resize_keyboard=True),
    )
    await cq.answer()


@dp.message(UserState.trip_adding_place)
async def handle_trip_adding_place(msg: Message, state: FSMContext):
    text = (msg.text or "").strip()
    data = await state.get_data()
    day_id = data.get("add_place_day_id")
    await state.clear()
    if text == "❌ Отмена":
        await msg.answer("Добавление отменено.", reply_markup=MAIN_KB)
        return
    item_id = add_custom_trip_item(day_id, msg.from_user.id, text)
    if not item_id:
        await msg.answer("Не удалось добавить место.", reply_markup=MAIN_KB)
        return
    item = get_trip_item(item_id, msg.from_user.id)
    log_analytics_event("trip_item_added", user_id=msg.from_user.id, trip_id=item["trip_id"] if item else None)
    await show_trip_day(
        msg, day_id, msg.from_user.id,
        notice=f"✅ «{text}» добавлено в маршрут."
    )


@dp.message(F.text == "⭐ Сохранённые места")
async def btn_saved_places(msg: Message):
    trip = get_active_trip(msg.from_user.id)
    rows = list_saved_places(msg.from_user.id, trip["trip_id"] if trip else None)
    if not rows:
        await msg.answer("⭐ Пока нет сохранённых мест. Сохраняй точки из готового плана.", reply_markup=MAIN_KB)
        return
    buttons = []
    blocks = ["⭐ <b>Сохранённые места</b>"]
    for idx, row in enumerate(rows, 1):
        blocks.append(f"{idx}. {html.escape(row['place_name'] or 'Место')}\n📍 {html.escape(row['city'] or '')}")
        buttons.append([InlineKeyboardButton(text=f"🗑 Удалить {idx}", callback_data=f"saved_delete:{row['id']}")])
    await send_long(msg, "\n\n".join(blocks), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@dp.callback_query(F.data.startswith("saved_delete:"))
async def cb_saved_delete(cq: CallbackQuery):
    try: saved_id = int(cq.data.split(":", 1)[1])
    except Exception: await cq.answer("Некорректное место", show_alert=True); return
    if delete_saved_place(saved_id, cq.from_user.id):
        await cq.answer("Удалено")
        try: await cq.message.delete()
        except Exception: pass
    else:
        await cq.answer("Место не найдено", show_alert=True)


@dp.callback_query(F.data.startswith("trip_versions:"))
async def cb_trip_versions(cq: CallbackQuery):
    try: trip_id = int(cq.data.split(":", 1)[1])
    except Exception: await cq.answer("Некорректная поездка", show_alert=True); return
    versions = list_trip_versions(trip_id, cq.from_user.id)
    if not versions:
        await cq.answer("Предыдущих версий пока нет", show_alert=True); return
    reason_names = {
        "full_regeneration": "полная пересборка", "replace_item": "замена места",
        "delete_item": "удаление места", "move_item": "перенос места",
        "add_custom_item": "добавление места", "before_restore": "до восстановления",
    }
    rows = [[InlineKeyboardButton(
        text=f"Версия {v['version_number']} · {reason_names.get(v['change_reason'], v['change_reason'] or 'изменение')}",
        callback_data=f"trip_restore_confirm:{v['version_id']}"
    )] for v in versions]
    rows.append([InlineKeyboardButton(text="⬅️ К поездке", callback_data=f"trip_open:{trip_id}")])
    await cq.message.answer("Выбери версию для восстановления:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await cq.answer()


@dp.callback_query(F.data.startswith("trip_restore_confirm:"))
async def cb_trip_restore_confirm(cq: CallbackQuery):
    try: version_id = int(cq.data.split(":", 1)[1])
    except Exception: await cq.answer("Некорректная версия", show_alert=True); return
    await cq.message.answer(
        "Восстановить эту версию? Текущий план тоже будет сохранён в истории.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Восстановить", callback_data=f"trip_restore:{version_id}")],
            [InlineKeyboardButton(text="Отмена", callback_data="noop")],
        ]),
    )
    await cq.answer()


@dp.callback_query(F.data.startswith("trip_restore:"))
async def cb_trip_restore(cq: CallbackQuery):
    try: version_id = int(cq.data.split(":", 1)[1])
    except Exception: await cq.answer("Некорректная версия", show_alert=True); return
    trip_id = restore_trip_version(version_id, cq.from_user.id)
    if not trip_id: await cq.answer("Версия не найдена", show_alert=True); return
    log_analytics_event("trip_version_restored", user_id=cq.from_user.id, trip_id=trip_id)
    await cq.answer("Версия восстановлена", show_alert=True)
    await cq.message.answer("✅ Предыдущая версия маршрута восстановлена.", reply_markup=ACTIVE_TRIP_KB)
    await cq.message.answer(
        "Открой восстановленный план:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Открыть план", callback_data=f"trip_plan:{trip_id}")]
        ]),
    )


@dp.callback_query(F.data == "noop")
async def cb_noop(cq: CallbackQuery):
    await cq.answer()


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
        active_trip = get_active_trip(msg.from_user.id)
        country = active_trip["country"] if active_trip else None
        _, place_names, _ = parse_gpt_response(raw, city, country)
        add_to_context(msg.from_user.id, "user", "🗺 Маршрут на день")
        add_to_context(msg.from_user.id, "assistant", raw)

        # Накапливаем историю мест — список, последние 20 уникальных
        history = route_history.setdefault(msg.from_user.id, [])
        for place in place_names:
            if place and place not in history:
                history.append(place)
        route_history[msg.from_user.id] = history[-20:]

        await send_result(msg, raw, city, "Маршрут на день", kb=ROUTE_KB, country=country)
        increment_requests(msg.from_user.id)
        asyncio.create_task(log_sheets(
            msg.from_user.id, full_name(msg.from_user),
            msg.from_user.username, "Маршрут на день", f"🗺 {city}", len(raw)))
    except Exception as e:
        logging.error(f"Route error: {e}")
        await notify_owner_error(user=msg.from_user, action="Маршрут на день", error=e, trip_id=(get_active_trip(msg.from_user.id)["trip_id"] if get_active_trip(msg.from_user.id) else None))
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
        active_trip = get_active_trip(msg.from_user.id)
        country = active_trip["country"] if active_trip else None
        parsed, _, resp_type = parse_gpt_response(raw, city, country)
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
        await notify_owner_error(user=msg.from_user, action="Подбор жилья", error=e, trip_id=(get_active_trip(msg.from_user.id)["trip_id"] if get_active_trip(msg.from_user.id) else None))
        try:
            await thinking.delete()
        except Exception:
            pass
        await msg.answer("Что-то пошло не так. Попробуй ещё раз." + BACK_TEXT, reply_markup=MAIN_KB)
    finally:
        active_requests.discard(msg.from_user.id)

async def process_contextual_query(msg: Message, query_text: str, category: str = "Свободный запрос"):
    user_id = msg.from_user.id
    trip = get_active_trip(user_id)
    city = trip["city"] if trip else get_user_city(user_id)
    if not city:
        await msg.answer("Сначала выбери город или создай поездку.", reply_markup=NO_TRIP_KB)
        return
    if is_flood(user_id):
        await msg.answer("⏳ Подожди секунду 😊", reply_markup=main_kb_for(user_id)); return
    if user_id in active_requests:
        await msg.answer("⏳ Уже обрабатываю предыдущий запрос.", reply_markup=main_kb_for(user_id)); return
    active_requests.add(user_id)
    thinking = await msg.answer(f"Ищу лучшее решение для {city}…")
    try:
        trip_id = trip["trip_id"] if trip else None
        context = load_ai_context(user_id, trip_id, limit=8) if trip_id else get_context(user_id)
        enriched = query_text
        if trip:
            enriched = active_trip_summary(trip) + "\n\nЗапрос пользователя: " + query_text
        raw = await ask_ai(enriched, city, context)
        try: await thinking.delete()
        except Exception: pass
        if trip_id:
            save_ai_context(user_id, "user", query_text, trip_id)
            save_ai_context(user_id, "assistant", raw, trip_id)
        else:
            add_to_context(user_id, "user", query_text)
            add_to_context(user_id, "assistant", raw)
        await send_result(msg, raw, city, category, with_feedback=True, country=(trip["country"] if trip else None))
        increment_requests(user_id)
        log_analytics_event("contextual_query_completed", user_id=user_id, trip_id=trip_id, event_data={"category": category})
        asyncio.create_task(log_sheets(user_id, full_name(msg.from_user), msg.from_user.username, category, query_text, len(raw)))
    except Exception as e:
        logging.exception(f"Contextual query error: {e}")
        await notify_owner_error(user=msg.from_user, action=f"Запрос консьержу: {category}", error=e, trip_id=trip_id)
        try: await thinking.delete()
        except Exception: pass
        await msg.answer("Не удалось обработать запрос. Попробуй ещё раз.", reply_markup=main_kb_for(user_id))
    finally:
        active_requests.discard(user_id)


# ──────────────────────────────────────────────────────────────
# СИСТЕМНЫЕ КНОПКИ
# ──────────────────────────────────────────────────────────────
@dp.message(F.text == "🏠 Главное меню")
async def btn_main_menu(msg: Message, state: FSMContext):
    await state.clear()
    await show_v7_main_menu(msg, msg.from_user.id)


@dp.message(F.text.in_({"✈️ Создать поездку", "📍 Я уже в городе"}))
async def btn_start_trip_v7(msg: Message, state: FSMContext):
    # В V7.0 оба сценария используют общий устойчивый онбординг поездки.
    await state.clear()
    mode = "already_here" if msg.text == "📍 Я уже в городе" else "planning"
    await state.update_data(v7_trip_mode=mode)
    await state.set_state(UserState.trip_entering_city)
    prompt = "В каком городе ты сейчас находишься?" if mode == "already_here" else "Куда собираешься?"
    await msg.answer(f"{prompt} Напиши город или курорт мира 👇", reply_markup=TRIP_CREATE_KB)
    log_analytics_event("trip_creation_started", user_id=msg.from_user.id, event_data={"mode": mode})


@dp.message(F.text == "🗓 Моя поездка")
async def btn_active_trip_card(msg: Message):
    trip = get_active_trip(msg.from_user.id)
    if not trip:
        await msg.answer("Активной поездки пока нет.", reply_markup=NO_TRIP_KB)
        return
    days = get_trip_days(trip["trip_id"], msg.from_user.id)
    user = get_user(msg.from_user.id)
    await msg.answer(
        _trip_card_text(trip, len(days), True),
        parse_mode="HTML",
        reply_markup=trip_card_kb(
            trip["trip_id"],
            bool(user and user["active_trip_id"] == trip["trip_id"]),
            trip["status"], bool(days),
        ),
    )
    log_analytics_event("active_trip_opened", user_id=msg.from_user.id, trip_id=trip["trip_id"])


@dp.message(F.text == "🗺 План на сегодня")
async def btn_today_plan(msg: Message):
    trip = get_active_trip(msg.from_user.id)
    if not trip:
        await msg.answer("Сначала создай или выбери поездку.", reply_markup=NO_TRIP_KB)
        return
    days = get_trip_days(trip["trip_id"], msg.from_user.id)
    if not days:
        await msg.answer("План ещё не создан.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✨ Создать план", callback_data=f"trip_generate:{trip['trip_id']}")]]))
        return
    day_number = max(1, min(int(trip["current_day"] or 1), len(days)))
    day = days[day_number - 1]
    items = get_day_items(day["day_id"], msg.from_user.id)
    await send_long(msg, _day_text(day, items), parse_mode="HTML", reply_markup=ACTIVE_TRIP_KB)
    log_analytics_event("today_plan_opened", user_id=msg.from_user.id, trip_id=trip["trip_id"], event_data={"day": day_number})


@dp.message(F.text == "🔎 Быстро найти место")
async def btn_quick_search(msg: Message):
    trip = get_active_trip(msg.from_user.id)
    city = trip["city"] if trip else get_user_city(msg.from_user.id)
    if not city:
        await msg.answer("Сначала выбери город или создай поездку.", reply_markup=NO_TRIP_KB)
        return
    await msg.answer(f"🔎 Что найти в {city}?", reply_markup=QUICK_SEARCH_KB)
    log_analytics_event("quick_search_opened", user_id=msg.from_user.id, trip_id=trip["trip_id"] if trip else None)


@dp.message(F.text == "💬 Спросить консьержа")
async def btn_concierge(msg: Message):
    trip = get_active_trip(msg.from_user.id)
    city = trip["city"] if trip else get_user_city(msg.from_user.id)
    if not city:
        await msg.answer("Сначала выбери город или создай поездку.", reply_markup=NO_TRIP_KB)
        return
    await msg.answer(
        f"💬 Пиши любой вопрос про {city}. Я учту параметры активной поездки: состав, бюджет, темп, интересы и жильё.",
        reply_markup=main_kb_for(msg.from_user.id),
    )


@dp.message(F.text == "🔄 Изменить планы")
async def btn_replan_menu(msg: Message):
    trip = get_active_trip(msg.from_user.id)
    if not trip or not get_trip_days(trip["trip_id"], msg.from_user.id):
        await msg.answer("Сначала создай план поездки.", reply_markup=main_kb_for(msg.from_user.id))
        return
    await msg.answer("Что изменилось? Выбери ситуацию — я предложу, как адаптировать текущий план.", reply_markup=REPLAN_KB)


@dp.message(F.text.in_({"☔ Пошёл дождь", "😴 Мы устали", "💰 Нужно дешевле", "🚶 Меньше ходить", "⏰ Осталось мало времени", "🌙 Уже поздно", "❌ Место закрыто", "🍽 Хотим поесть сейчас"}))
async def btn_replan_reason(msg: Message):
    trip = get_active_trip(msg.from_user.id)
    if not trip:
        await msg.answer("Активная поездка не выбрана.", reply_markup=NO_TRIP_KB)
        return
    # V7.0: причина передаётся в свободный AI-запрос с полным контекстом поездки.
    prompt = f"Нужно адаптировать текущий план поездки. Ситуация: {msg.text}. Предложи практичную замену ближайшей части маршрута, не меняя уже посещённые места."
    await process_contextual_query(msg, prompt, category=f"Перестройка: {msg.text}")

@dp.message(F.text == "➕ Ещё")
async def btn_more(msg: Message):
    city = get_user_city(msg.from_user.id)
    header = f"🏙 Сейчас: {city}\n" if city else ""
    await msg.answer(f"✦ <b>ЕЩЁ ВОЗМОЖНОСТИ</b>\n{html.escape(header)}\nВыбери нужный раздел.", parse_mode="HTML", reply_markup=MORE_KB)


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
        "✦ <b>AI МЕСТНЫЙ</b>\n<i>Твой человек в любом городе</i>\n\n"
        "━━━━━━━━━━━━━━━\n"
        "Помогаю находить идеи для поездок:\n\n"
        "🍽 Где поесть и выпить кофе\n"
        "🗺 Маршруты на день\n"
        "🏨 Варианты жилья под твой формат\n"
        "🎭 Куда сходить и что посмотреть\n"
        "💎 Места куда редко доходят туристы\n"
        "📸 Определяю места по фото\n"
        "━━━━━━━━━━━━━━━\n\n"
        "🌍 Работаю по городам и курортам России и мира\n\n"
        "━━━━━━━━━━━━━━━\n"
        "💡 Идеи и замечания — жми Поддержка 👇",
        reply_markup=MAIN_KB,
        parse_mode="HTML",
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
# АНАЛИТИКА И АДМИН V7
# ──────────────────────────────────────────────────────────────
def _count_table(conn: sqlite3.Connection, table: str, where: str = "", params: tuple = ()) -> int:
    query = f"SELECT COUNT(*) FROM {table}"
    if where:
        query += f" WHERE {where}"
    return int(conn.execute(query, params).fetchone()[0] or 0)


def get_v7_admin_stats() -> dict:
    """Сводная продуктовая статистика V7."""
    today = datetime.now().strftime("%d.%m.%Y")
    with db_connection() as conn:
        total_users = _count_table(conn, "users")
        active_today = _count_table(conn, "users", "last_active LIKE ?", (f"{today}%",))
        new_today = _count_table(conn, "users", "registered_at LIKE ?", (f"{today}%",))
        total_trips = _count_table(conn, "trips")
        draft_trips = _count_table(conn, "trips", "status='draft'")
        planning_trips = _count_table(conn, "trips", "status='planning'")
        ready_trips = _count_table(conn, "trips", "plan_generation_status='completed'")
        active_trips = _count_table(conn, "trips", "status='active'")
        completed_trips = _count_table(conn, "trips", "status='completed'")
        saved_places = _count_table(conn, "saved_places")
        trip_days = _count_table(conn, "trip_days")
        trip_items = _count_table(conn, "trip_items")
        generations_ok = _count_table(conn, "analytics_events", "event_name='trip_generation_success'")
        generations_failed = _count_table(conn, "analytics_events", "event_name='trip_generation_failed'")
        rebuilds = conn.execute("""
            SELECT COUNT(*) FROM analytics_events
            WHERE event_name IN ('trip_item_replaced','trip_item_moved','trip_version_restored')
        """).fetchone()[0] or 0
        opened_days = _count_table(conn, "analytics_events", "event_name='trip_day_opened'")
        contextual_queries = _count_table(conn, "analytics_events", "event_name='contextual_query_completed'")
        positive = _count_table(conn, "feedback", "rating='positive'")
        negative = _count_table(conn, "feedback", "rating='negative'")
        returning_users = conn.execute("""
            SELECT COUNT(*) FROM (
                SELECT user_id
                FROM analytics_events
                WHERE event_name IN ('active_trip_opened','trip_day_opened','today_plan_opened')
                  AND user_id IS NOT NULL
                GROUP BY user_id
                HAVING COUNT(*) >= 2
            )
        """).fetchone()[0] or 0
        top_cities = conn.execute("""
            SELECT city, COUNT(*) AS cnt
            FROM trips
            GROUP BY city
            ORDER BY cnt DESC, city ASC
            LIMIT 7
        """).fetchall()
    return {
        "total_users": total_users,
        "active_today": active_today,
        "new_today": new_today,
        "total_trips": total_trips,
        "draft_trips": draft_trips,
        "planning_trips": planning_trips,
        "ready_trips": ready_trips,
        "active_trips": active_trips,
        "completed_trips": completed_trips,
        "saved_places": saved_places,
        "trip_days": trip_days,
        "trip_items": trip_items,
        "generations_ok": generations_ok,
        "generations_failed": generations_failed,
        "rebuilds": int(rebuilds),
        "opened_days": opened_days,
        "contextual_queries": contextual_queries,
        "positive": positive,
        "negative": negative,
        "returning_users": int(returning_users),
        "top_cities": [(row["city"], row["cnt"]) for row in top_cities],
    }


def get_v7_funnel() -> list[tuple[str, int]]:
    """Уникальные пользователи на ключевых этапах продуктовой воронки."""
    steps = [
        ("Начали создание", "trip_creation_started"),
        ("Создали черновик", "trip_draft_created"),
        ("Завершили анкету", "trip_onboarding_completed"),
        ("Запустили генерацию", "trip_generation_started"),
        ("Получили план", "trip_generation_success"),
        ("Открыли день", "trip_day_opened"),
        ("Сохранили место", "place_saved"),
        ("Вернулись к поездке", "active_trip_opened"),
    ]
    result = []
    with db_connection() as conn:
        for label, event_name in steps:
            count = conn.execute("""
                SELECT COUNT(DISTINCT user_id)
                FROM analytics_events
                WHERE event_name=? AND user_id IS NOT NULL
            """, (event_name,)).fetchone()[0] or 0
            result.append((label, int(count)))
    return result


def get_recent_v7_errors(limit: int = 10) -> list[dict]:
    """Последние неуспешные генерации с краткими данными события."""
    with db_connection() as conn:
        rows = conn.execute("""
            SELECT event_id, user_id, trip_id, event_data_json, created_at
            FROM analytics_events
            WHERE event_name='trip_generation_failed'
            ORDER BY event_id DESC
            LIMIT ?
        """, (max(1, min(limit, 30)),)).fetchall()
    errors = []
    for row in rows:
        try:
            payload = json.loads(row["event_data_json"] or "{}")
        except (json.JSONDecodeError, TypeError):
            payload = {}
        errors.append({
            "event_id": row["event_id"],
            "user_id": row["user_id"],
            "trip_id": row["trip_id"],
            "created_at": row["created_at"],
            "error": str(payload.get("error") or payload.get("reason") or "Без описания")[:240],
        })
    return errors


def _percent(part: int, whole: int) -> str:
    if whole <= 0:
        return "—"
    return f"{part / whole * 100:.1f}%"

# ──────────────────────────────────────────────────────────────
# КОМАНДЫ
# ──────────────────────────────────────────────────────────────
@dp.message(Command("stats"))
async def cmd_stats(msg: Message):
    if msg.from_user.id != OWNER_ID:
        return
    stats = get_v7_admin_stats()
    top = "\n".join(f"  {city}: {count}" for city, count in stats["top_cities"]) or "  Пока нет данных"
    total_feedback = stats["positive"] + stats["negative"]
    generation_total = stats["generations_ok"] + stats["generations_failed"]
    await msg.answer(
        "📊 Статистика AI Местный V7\n\n"
        "━━━━━━━━━━━━━━━\n"
        f"👥 Пользователей: {stats['total_users']}\n"
        f"🆕 Новых сегодня: {stats['new_today']}\n"
        f"🟢 Активны сегодня: {stats['active_today']}\n"
        f"🔁 Вернулись к плану: {stats['returning_users']}\n"
        "━━━━━━━━━━━━━━━\n"
        f"✈️ Всего поездок: {stats['total_trips']}\n"
        f"📝 Черновиков: {stats['draft_trips']}\n"
        f"🧭 В планировании: {stats['planning_trips']}\n"
        f"✅ С готовым планом: {stats['ready_trips']}\n"
        f"🚀 Активных: {stats['active_trips']}\n"
        f"🏁 Завершённых: {stats['completed_trips']}\n"
        "━━━━━━━━━━━━━━━\n"
        f"🗓 Дней в планах: {stats['trip_days']}\n"
        f"📍 Точек маршрута: {stats['trip_items']}\n"
        f"⭐ Сохранённых мест: {stats['saved_places']}\n"
        f"👁 Открытий дней: {stats['opened_days']}\n"
        f"💬 Контекстных запросов: {stats['contextual_queries']}\n"
        f"🔄 Изменений плана: {stats['rebuilds']}\n"
        "━━━━━━━━━━━━━━━\n"
        f"🤖 Генераций успешно: {stats['generations_ok']}\n"
        f"⚠️ Ошибок генерации: {stats['generations_failed']}\n"
        f"📈 Успешность: {_percent(stats['generations_ok'], generation_total)}\n"
        f"👍 Положительных: {stats['positive']}\n"
        f"👎 Отрицательных: {stats['negative']}\n"
        f"💚 Доля полезных: {_percent(stats['positive'], total_feedback)}\n"
        "━━━━━━━━━━━━━━━\n\n"
        f"🏙 Популярные направления:\n{top}"
    )


@dp.message(Command("funnel"))
async def cmd_funnel(msg: Message):
    if msg.from_user.id != OWNER_ID:
        return
    funnel = get_v7_funnel()
    first = funnel[0][1] if funnel else 0
    lines = []
    previous = None
    for label, count in funnel:
        from_start = _percent(count, first)
        from_previous = _percent(count, previous) if previous is not None else "100%" if count else "—"
        lines.append(f"{label}: {count}\n  от старта {from_start} · от шага {from_previous}")
        previous = count
    await msg.answer(
        "📈 Воронка AI Местный V7\n\n"
        "━━━━━━━━━━━━━━━\n" + "\n\n".join(lines) +
        "\n━━━━━━━━━━━━━━━\n\n"
        "Считаются уникальные пользователи по событиям. "
        "На раннем тесте проценты могут меняться резко из-за небольшой выборки."
    )


@dp.message(Command("errors"))
async def cmd_errors(msg: Message):
    if msg.from_user.id != OWNER_ID:
        return
    errors = get_recent_v7_errors(10)
    if not errors:
        await msg.answer("✅ Зафиксированных ошибок генерации пока нет.")
        return
    blocks = []
    for item in errors:
        blocks.append(
            f"⚠️ {item['created_at']}\n"
            f"Пользователь: {item['user_id'] or '—'} · Поездка: {item['trip_id'] or '—'}\n"
            f"{html.escape(item['error'])}"
        )
    await send_long(
        msg,
        "🧯 Последние ошибки генерации\n\n" + "\n\n━━━━━━━━━━━━━━━\n\n".join(blocks),
        reply_markup=None,
    )


@dp.message(Command("help"))
async def cmd_help(msg: Message):
    await msg.answer(
        "🗺 Как пользоваться AI Местным\n\n"
        "━━━━━━━━━━━━━━━\n"
        "🏙 Напиши любой город или курорт мира\n"
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
    user_id = msg.from_user.id
    if user_id in active_requests:
        await msg.answer("⏳ Уже обрабатываю предыдущий запрос 😊", reply_markup=MAIN_KB)
        return
    if is_flood(user_id):
        await msg.answer("⏳ Подожди секунду 😊", reply_markup=MAIN_KB)
        return

    data = await state.get_data()
    file_id = data.get("photo_file_id")
    await state.clear()
    if not file_id:
        await msg.answer("Фото не найдено. Пришли его ещё раз 👇", reply_markup=MAIN_KB)
        return

    city = get_user_city(user_id) or "Россия"
    thinking = await msg.answer("🔍 Анализирую фото...", reply_markup=MAIN_KB)
    active_requests.add(user_id)
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
        active_requests.discard(user_id)
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
        await notify_owner_error(user=msg.from_user, action="Обработка голосового", error=e, trip_id=(get_active_trip(msg.from_user.id)["trip_id"] if get_active_trip(msg.from_user.id) else None))
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
        await msg.answer(short_reply, reply_markup=main_kb_for(user.id))
        return

    city = get_user_city(user.id)
    if not city:
        await msg.answer(
            "Сначала напиши название города 🏙",
            reply_markup=CITY_INPUT_KB,
        )
        await state.set_state(UserState.entering_city)
        return

    is_theme = text in THEME_BUTTONS or text in {"🏛 Что посмотреть", "🌿 На природу", "🌇 Красивый вид"}
    category = text if is_theme else "Свободный запрос"
    await process_contextual_query(msg, text, category=category)

# ──────────────────────────────────────────────────────────────
# ГЛОБАЛЬНЫЙ ПЕРЕХВАТ НЕОБРАБОТАННЫХ ОШИБОК
# ──────────────────────────────────────────────────────────────
@dp.errors()
async def global_error_handler(event: ErrorEvent):
    update = getattr(event, "update", None)
    message = getattr(update, "message", None) if update is not None else None
    callback = getattr(update, "callback_query", None) if update is not None else None
    user = getattr(message, "from_user", None) or getattr(callback, "from_user", None)
    await notify_owner_error(
        user=user,
        action="Необработанная ошибка обработчика",
        error=getattr(event, "exception", None),
        force=(user is None),
    )
    logging.exception("Unhandled aiogram error", exc_info=getattr(event, "exception", None))
    return True

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
    logging.info("AI Местный v8 World Owner Alerts запущен")
    await dp.start_polling(bot, drop_pending_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
