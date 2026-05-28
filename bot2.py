#!/usr/bin/env python3
"""
AI Местный — Сочи (тест)
Bot: @SochiTestBot
File: /root/bot2.py
Service: sochi-test
"""

import asyncio
import logging
import os
import tempfile
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from openai import OpenAI
import gspread
from google.oauth2.service_account import Credentials

# ──────────────────────────────────────────────────────────────
# КОНФИГ
# ──────────────────────────────────────────────────────────────
BOT_TOKEN      = "8897475918:AAEzrPd1IuCNmy8XUiWsFNlqy13LTscqonM"
OPENAI_KEY     = "sk-mfvVI3QN2uQvXPlhMkAeUUzmbjK5aQzj"   # proxyapi.ru — для Claude и Whisper
OWNER_ID       = 549639607
SPREADSHEET_ID = "1PE7CaFuWOe_eygQqIoMAmUdJBtATbIaNfZR4cvarPCA"
SHEET_NAME     = "Аналитика Сочи"
CREDENTIALS    = "/root/google_credentials.json"
MODEL          = "claude-3-5-sonnet-20241022"   # Claude через proxyapi.ru

# ──────────────────────────────────────────────────────────────
# СИСТЕМНЫЙ ПРОМПТ
# ──────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """Ты — AI Местный, виртуальный друг-сочинец, который живёт в городе 10 лет.

ТВОЯ ЗАДАЧА:
Помогать людям находить интересные места в Сочи — кафе, маршруты, события, активности. Отвечай как живой человек, который хорошо знает город.

ТВОЙ СТИЛЬ:
- Говоришь как живой человек, не как путеводитель. Без канцелярита.
- Тёплый, дружеский тон. Можно на «ты».
- Эмодзи в меру (1-3 на одно место).
- НЕ используй markdown-форматирование (никаких *, _, [], `). Только обычный текст и эмодзи.

ФОРМАТ КАЖДОГО МЕСТА В ПОДБОРКЕ:
📍 Адрес или район
💰 Цена / средний чек (если знаешь)
⏰ Часы работы (если знаешь)
✨ Фишка — почему стоит идти (1-2 предложения)
🔗 Открыть в Яндекс.Картах: https://yandex.ru/maps/?text=Название+места+Сочи

ВАЖНО ПРО ССЫЛКИ:
- Ссылку на Яндекс.Карты ДОБАВЛЯЙ ВСЕГДА для каждого места.
- Формат: https://yandex.ru/maps/?text=Название+места+Сочи (пробелы заменяй на +)
- Пример: https://yandex.ru/maps/?text=Sky+Coffee+Адлер

ЕСЛИ НЕ ЗНАЕШЬ ТОЧНЫХ ДАННЫХ:
Не выдумывай телефоны, цены, адреса. Лучше скажи «уточни на месте» и дай ссылку на Яндекс.Карты.

ФОРМАТ ОТВЕТА:
1. Одна строка вступления — как другу.
2. 3-5 мест нумерованным списком.
3. Короткий практический совет в конце.

ИЗБЕГАЙ:
- Банальщины (Дендрарий, Олимпийский парк, Роза Хутор, Морпорт, Сочи-парк)
- Сетевых ресторанов и ТЦ

ОБРАБОТКА ТЕМАТИЧЕСКИХ КНОПОК:
Когда пользователь жмёт кнопку с эмодзи — сначала задай 3-4 коротких уточняющих вопроса, потом давай подборку.

🍽 Где поесть → спроси: район, бюджет, кухня, с кем
☕ Кофе с видом → спроси: район, бюджет, время суток, атмосфера
🌅 На рассвет → спроси: откуда стартует, машина есть, море или горы, один или с кем
🎉 Что сегодня → спроси: один/пара/компания, формат вечера, бюджет, район
👨‍👩‍👧 С детьми → спроси: возраст ребёнка, бюджет, время, район
💑 Романтика → спроси: бюджет, формат вечера, район, особый случай или нет
🏔 На природу → спроси: сколько времени, активность, машина, с кем
🌃 Вечер → спроси: один/пара/компания, формат, бюджет, район

После каждого уточняющего вопроса добавляй: «Или напиши своими словами 🚀»
Не задавай больше 4 вопросов за раз.

Если человек пишет про другой город — мягко скажи: пока знаешь только Сочи, скоро будут другие города."""

# ──────────────────────────────────────────────────────────────
# КЛАВИАТУРА
# ──────────────────────────────────────────────────────────────
MAIN_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🍽 Где поесть"),   KeyboardButton(text="☕ Кофе с видом")],
        [KeyboardButton(text="🌅 На рассвет"),   KeyboardButton(text="🎉 Что сегодня")],
        [KeyboardButton(text="👨‍👩‍👧 С детьми"),  KeyboardButton(text="💑 Романтика")],
        [KeyboardButton(text="🏔 На природу"),   KeyboardButton(text="🌃 Вечер")],
        [KeyboardButton(text="✏️ Свой вопрос")],
        [KeyboardButton(text="🛠 Поддержка"),    KeyboardButton(text="ℹ️ О проекте")],
    ],
    resize_keyboard=True,
    one_time_keyboard=False,
)

THEME_BUTTONS = {
    "🍽 Где поесть", "☕ Кофе с видом", "🌅 На рассвет", "🎉 Что сегодня",
    "👨‍👩‍👧 С детьми", "💑 Романтика", "🏔 На природу", "🌃 Вечер",
}
SYSTEM_BUTTONS = {"✏️ Свой вопрос", "🛠 Поддержка", "ℹ️ О проекте"}

# ──────────────────────────────────────────────────────────────
# КЛИЕНТ — один для всего (proxyapi.ru)
# ──────────────────────────────────────────────────────────────
bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher()

client = OpenAI(
    api_key=OPENAI_KEY,
    base_url="https://api.proxyapi.ru/openai/v1",
)

# ──────────────────────────────────────────────────────────────
# GOOGLE SHEETS
# ──────────────────────────────────────────────────────────────
def _log_sync(user_id, name, username, msg_type, text, resp_len=0):
    try:
        creds = Credentials.from_service_account_file(
            CREDENTIALS,
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        gc    = gspread.authorize(creds)
        sheet = gc.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
        now   = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        uname = f"@{username}" if username else "(нет username)"
        sheet.append_row([now, str(user_id), name, uname, msg_type, text[:500], str(resp_len)])
    except Exception as e:
        logging.error(f"Sheets error: {e}")

async def log_sheets(user_id, name, username, msg_type, text, resp_len=0):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _log_sync, user_id, name, username, msg_type, text, resp_len)

# ──────────────────────────────────────────────────────────────
# CLAUDE ЧЕРЕЗ PROXYAPI.RU
# ──────────────────────────────────────────────────────────────
def _claude_sync(user_text: str) -> str:
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_text},
        ],
        max_tokens=2000,
    )
    return response.choices[0].message.content.strip()

async def ask_claude(text: str) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _claude_sync, text)

# ──────────────────────────────────────────────────────────────
# ХЕЛПЕР
# ──────────────────────────────────────────────────────────────
def full_name(user) -> str:
    parts = [user.first_name or "", user.last_name or ""]
    return " ".join(p for p in parts if p).strip() or "—"

# ──────────────────────────────────────────────────────────────
# ОБРАБОТЧИКИ
# ──────────────────────────────────────────────────────────────

@dp.message(Command("start"))
async def cmd_start(msg: Message):
    name = msg.from_user.first_name or "друг"
    await msg.answer(
        f"Привет, {name}! 👋\n\n"
        "Я AI Местный — гид по Сочи глазами местного жителя.\n\n"
        "Покажу кафе, маршруты и события — те, о которых не пишут в путеводителях.\n\n"
        "Жми кнопку ниже или спрашивай сразу 👇",
        reply_markup=MAIN_KB,
    )
    asyncio.create_task(log_sheets(
        msg.from_user.id, full_name(msg.from_user),
        msg.from_user.username, "Команда", "/start",
    ))


@dp.message(Command("help"))
async def cmd_help(msg: Message):
    await msg.answer(
        "📖 Как пользоваться AI Местным:\n\n"
        "1️⃣ Жми кнопку с темой внизу — получишь подборку мест.\n\n"
        "2️⃣ Или пиши обычным языком — как другу. Чем больше деталей, тем точнее ответ:\n"
        "   • Бюджет (например, «до 1500 руб»)\n"
        "   • С кем идёшь\n"
        "   • Сколько времени есть\n"
        "   • Настроение\n\n"
        "3️⃣ Нет нужной темы? Жми «✏️ Свой вопрос».\n\n"
        "Команды:\n/start — открыть меню\n/about — о проекте",
        reply_markup=MAIN_KB,
    )


@dp.message(Command("about"))
async def cmd_about_cmd(msg: Message):
    await _send_about(msg)


@dp.message(F.text == "ℹ️ О проекте")
async def cmd_about_btn(msg: Message):
    await _send_about(msg)


async def _send_about(msg: Message):
    await msg.answer(
        "🌊 AI Местный — гид по Сочи\n\n"
        "Туристические сайты пишут одно и то же. А город живёт совсем по-другому.\n\n"
        "Я показываю Сочи глазами местных:\n"
        "• Места, которых нет в Google Maps в топе\n"
        "• События, о которых узнают за день\n"
        "• Кафе, куда ходят местные, а не туристы\n\n"
        "🛠 Замечания и идеи — жми «Поддержка».\n\n"
        "⚠️ Это тестовая версия бота.",
        reply_markup=MAIN_KB,
    )
    asyncio.create_task(log_sheets(
        msg.from_user.id, full_name(msg.from_user),
        msg.from_user.username, "Команда", "О проекте",
    ))


@dp.message(F.text == "🛠 Поддержка")
async def btn_support(msg: Message):
    user  = msg.from_user
    uname = f"@{user.username}" if user.username else "(нет username)"
    await msg.answer(
        "🛠 Напиши свой вопрос или замечание — передам создателю.\n\n"
        "Или пиши напрямую: @demo23rus",
        reply_markup=MAIN_KB,
    )
    try:
        await bot.send_message(
            OWNER_ID,
            f"🛠 Запрос поддержки\n"
            f"Имя: {full_name(user)}\n"
            f"Username: {uname}\n"
            f"ID: {user.id}",
        )
    except Exception as e:
        logging.error(f"Owner notify error: {e}")
    asyncio.create_task(log_sheets(
        user.id, full_name(user), user.username, "Поддержка", "🛠 Поддержка",
    ))


@dp.message(F.text == "✏️ Свой вопрос")
async def btn_own(msg: Message):
    await msg.answer(
        "✏️ Пиши свой вопрос — я отвечу.\n\n"
        "Спрашивай что угодно про Сочи: места, маршруты, события, советы 🚀",
        reply_markup=MAIN_KB,
    )


# ── Голосовые сообщения ───────────────────────────────────────
@dp.message(F.voice)
async def handle_voice(msg: Message):
    await msg.answer(
        "🎤 Слышу тебя! Распознаю голосовое...\n\nЭто займёт секунд 10 😊"
    )
    tmp_path = None
    try:
        file     = await bot.get_file(msg.voice.file_id)
        tmp_file = tempfile.NamedTemporaryFile(suffix=".ogg", delete=False)
        tmp_path = tmp_file.name
        tmp_file.close()
        await bot.download_file(file.file_path, tmp_path)

        with open(tmp_path, "rb") as audio:
            transcript = client.audio.transcriptions.create(
                model    = "whisper-1",
                file     = audio,
                language = "ru",
            )
        text = transcript.text.strip()

        if not text:
            await msg.answer(
                "🤔 Не смог распознать голосовое. Попробуй написать текстом 👇",
                reply_markup=MAIN_KB,
            )
            return

        thinking = await msg.answer(f"🔍 Распознал: «{text}»\n\nИщу для тебя...")
        answer   = await ask_claude(text)

        try:
            await thinking.delete()
        except Exception:
            pass

        await msg.answer(answer, reply_markup=MAIN_KB)

        asyncio.create_task(log_sheets(
            msg.from_user.id, full_name(msg.from_user),
            msg.from_user.username,
            "Голосовое сообщение", f"🎤 {text}", len(answer),
        ))

    except Exception as e:
        logging.error(f"Voice error: {e}")
        await msg.answer(
            "😔 Не смог обработать голосовое. Попробуй написать текстом 👇",
            reply_markup=MAIN_KB,
        )
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


# ── Текстовые сообщения ───────────────────────────────────────
@dp.message(F.text)
async def handle_text(msg: Message):
    text = msg.text.strip()

    if text in SYSTEM_BUTTONS:
        return

    user     = msg.from_user
    msg_type = "Кнопка тематическая" if text in THEME_BUTTONS else "Свободный запрос"

    thinking = await msg.answer("🔍 Ищу для тебя...")

    try:
        answer = await ask_claude(text)
        try:
            await thinking.delete()
        except Exception:
            pass
        await msg.answer(answer, reply_markup=MAIN_KB)

        asyncio.create_task(log_sheets(
            user.id, full_name(user), user.username,
            msg_type, text, len(answer),
        ))

    except Exception as e:
        logging.error(f"Text handler error: {e}")
        try:
            await thinking.delete()
        except Exception:
            pass
        await msg.answer(
            "😔 Что-то пошло не так. Попробуй ещё раз или напиши иначе.",
            reply_markup=MAIN_KB,
        )


# ── Фото, стикеры, документы — заглушка ──────────────────────
@dp.message()
async def fallback(msg: Message):
    await msg.answer(
        "🤔 Я понимаю только текст и голосовые сообщения.\n\n"
        "Фото, стикеры и документы пока не поддерживаются.\n\n"
        "Напиши словами что ищешь, или жми кнопку в меню 👇",
        reply_markup=MAIN_KB,
    )


# ──────────────────────────────────────────────────────────────
# ЗАПУСК
# ──────────────────────────────────────────────────────────────
async def main():
    logging.basicConfig(
        level  = logging.INFO,
        format = "%(asctime)s [%(levelname)s] %(message)s",
    )
    logging.info("SochiTestBot запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
