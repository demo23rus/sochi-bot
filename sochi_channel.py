#!/usr/bin/env python3
"""
Канал «История Сочи каждый день» (@staryi_sochi)
File: /root/sochi_channel.py
Service: sochi-channel.timer (systemd)
Запуск: каждый день в 10:00 МСК
"""

import asyncio
import logging
import fcntl
import random
import json
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path

import pytz
from aiogram import Bot
from openai import OpenAI

# ──────────────────────────────────────────────────────────────
# КОНФИГ
# ──────────────────────────────────────────────────────────────
BOT_TOKEN    = "8987086395:AAHN0YjaZTQoP28WPImnQguZrx5FPiXV8kw"
OPENAI_KEY   = "sk-mfvVI3QN2uQvXPlhMkAeUUzmbjK5aQzj"
CHANNEL_ID   = "@staryi_sochi"
HISTORY_FILE = "/root/sochi_posts_history.json"
PHOTOS_CACHE = "/root/sochi_photos_cache.json"
MOSCOW_TZ    = pytz.timezone("Europe/Moscow")
MODEL        = "gpt-4o"

# ──────────────────────────────────────────────────────────────
# ФОТО — получаем через Wikimedia Commons API
# ──────────────────────────────────────────────────────────────
# Резервный список на случай если API недоступен
FALLBACK_PHOTOS = [
    "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/Sochi_Black_Sea_coast.jpg/1280px-Sochi_Black_Sea_coast.jpg",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/5/5b/Sochi_city_view.jpg/1280px-Sochi_city_view.jpg",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/b/b4/Sochi_Sky_Park.jpg/1280px-Sochi_Sky_Park.jpg",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/1/18/Sochi_sea_port_2.jpg/1280px-Sochi_sea_port_2.jpg",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/f/f7/Sochi_promenade_night.jpg/1280px-Sochi_promenade_night.jpg",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/4/4c/Sochi_resort.jpg/1280px-Sochi_resort.jpg",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/2/2b/Rosa_Khutor_Sochi.jpg/1280px-Rosa_Khutor_Sochi.jpg",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e3/Sochi_Riviera_park.jpg/1280px-Sochi_Riviera_park.jpg",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/9/9c/Sochi_coast_aerial.jpg/1280px-Sochi_coast_aerial.jpg",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/6/6f/Sochi_beach_2014.jpg/1280px-Sochi_beach_2014.jpg",
]


def fetch_wikimedia_photos() -> list:
    """Получает список фото Сочи через Wikimedia Commons API"""
    try:
        url = (
            "https://commons.wikimedia.org/w/api.php"
            "?action=query&list=categorymembers"
            "&cmtitle=Category:Views_of_Sochi"
            "&cmtype=file&cmlimit=50&cmnamespace=6"
            "&format=json"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "SochiBot/1.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())

        titles = [m["title"].replace("File:", "") for m in data["query"]["categorymembers"]]
        photos = []
        for title in titles[:30]:
            title_encoded = title.replace(" ", "_")
            photo_url = f"https://commons.wikimedia.org/wiki/Special:FilePath/{urllib.parse.quote(title_encoded)}?width=1200"
            photos.append(photo_url)

        if photos:
            # Кешируем
            with open(PHOTOS_CACHE, "w") as f:
                json.dump(photos, f)
            logging.info(f"Wikimedia: получено {len(photos)} фото")
            return photos
    except Exception as e:
        logging.warning(f"Wikimedia API недоступен: {e}")

    # Пробуем загрузить кеш
    if Path(PHOTOS_CACHE).exists():
        try:
            with open(PHOTOS_CACHE) as f:
                photos = json.load(f)
            logging.info(f"Загружен кеш фото: {len(photos)} шт.")
            return photos
        except Exception:
            pass

    logging.warning("Используем резервный список фото")
    return FALLBACK_PHOTOS


# ──────────────────────────────────────────────────────────────
# ИСТОРИЯ ПОСТОВ
# ──────────────────────────────────────────────────────────────
def load_history() -> list:
    if not Path(HISTORY_FILE).exists():
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_history(history: list, new_topic: str):
    history.append({
        "date": datetime.now(MOSCOW_TZ).strftime("%d.%m.%Y"),
        "topic": new_topic,
    })
    history = history[-200:]
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Ошибка сохранения истории: {e}")
    return history


def format_history_for_prompt(history: list) -> str:
    if not history:
        return "Ранее опубликованных постов нет."
    last = history[-50:]
    lines = [f"- {h['date']}: {h['topic']}" for h in last]
    return "Уже опубликованные темы (НЕ ПОВТОРЯЙ):\n" + "\n".join(lines)


# ──────────────────────────────────────────────────────────────
# ПРОМПТ
# ──────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """Ты — главный редактор Telegram-канала «История Сочи каждый день» (@staryi_sochi). Каждый день ты пишешь один пост — интересный факт о городе для местных жителей.

ТВОЙ СТИЛЬ:
— Тон тёплый, как у друга-краеведа: интересно, не сухо, без канцелярита
— Не пишешь "вы знали?" в каждом посте — это банально
— Не используй markdown (звёздочки, подчёркивания, прямые скобки)
— Эмодзи в меру (3-5 на пост)
— Длина поста: 600-900 символов
— Никакой воды — каждое предложение должно быть полезным или интересным

ЖЕЛЕЗНЫЕ ПРАВИЛА:
— Не выдумывай факты, имена, даты. Если не уверен — пиши общее: "в советские годы", "до революции", "в нулевые"
— Не упоминай Розу Хутор, Дендрарий, Олимпийский парк, Морпорт без необходимости
— Каждый пост должен заканчиваться ссылкой на бот: 🤖 + призыв + @mestniy_guide_bot

ФОРМАТЫ ПО ДНЯМ:

═══════════════════════════════════════════
ФОРМАТ 1: «А вы знали»
═══════════════════════════════════════════
Структура:
🌊 А вы знали?

[Интересный исторический факт о Сочи в 2-3 предложениях. Тема — название, происхождение чего-то, первые жители, любопытные детали из прошлого, забытые места, имена.]

[Развитие факта в 2-3 предложениях — что было дальше, к чему это привело, как изменилось.]

📷 Архивные фото города — pastvu.com
🤖 Найти места, куда ходят местные — @mestniy_guide_bot

Примеры тем для формата 1:
— Первое название Сочи (Даховский Посад)
— Кто построил первое здание-курорт (Кавказская Ривьера, 1909)
— Откуда в Сочи появились пальмы (искусственно завезены в XX веке)
— Какой реальный год основания (форт Александрия, 1838)
— Старые названия районов (Кардивач, Хоста)

═══════════════════════════════════════════
ФОРМАТ 2: «Было / стало»
═══════════════════════════════════════════
Структура:
🏛 СОЧИ: [год в прошлом] vs 2026

[Что было в этом месте/в городе тогда. 3-4 предложения с конкретикой — цифры, факты, события эпохи.]

[Что в этом месте сейчас. Контраст, цифры, как изменилось. 2-3 предложения.]

📷 Архив города — pastvu.com
🤖 Что посмотреть в Сочи сегодня — @mestniy_guide_bot

Примеры тем для формата 2:
— Морвокзал (раньше порт, сейчас памятник)
— Курортный проспект (узкая дорога → главная артерия)
— Численность населения (10к в 1900 → 540к сейчас)
— Туризм (60к в 1930-х → 7 млн сейчас)
— Адлерский аэропорт (полевой → международный)

═══════════════════════════════════════════
ФОРМАТ 3: «Скрытые факты»
═══════════════════════════════════════════
Структура:
🤫 То, чего вы не знали о Сочи

[Малоизвестный, удивительный факт о городе. Что-то, что местные тоже могут не знать. 3-4 предложения, с подробностями и деталями.]

[Доказательство или продолжение факта — где это можно увидеть/проверить/услышать самому. 2 предложения.]

📷 Старые карты города — pastvu.com
🤖 Найти необычные места Сочи — @mestniy_guide_bot

Примеры тем для формата 3:
— Подземные реки под Курортным проспектом
— Сталинские бункеры в горах
— Зачем строили санатории в виде корабля
— Откуда взялась улица «Воровского» и кто это
— Что на самом деле означает слово «Мацеста»

═══════════════════════════════════════════

ЗАПОМНИ: пост должен быть таким, чтобы местный житель Сочи (не турист) прочитал и сказал "ого, я этого не знал"."""


# ──────────────────────────────────────────────────────────────
# GPT
# ──────────────────────────────────────────────────────────────
def generate_post(format_num: int, history_text: str) -> str:
    client = OpenAI(api_key=OPENAI_KEY, base_url="https://api.proxyapi.ru/openai/v1")
    today = datetime.now(MOSCOW_TZ).strftime("%d.%m.%Y")
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": (
                f"Сегодня: {today}\n\n"
                f"{history_text}\n\n"
                f"Используй ФОРМАТ {format_num}. "
                f"Сгенерируй пост на НОВУЮ тему которой ещё не было выше."
            )},
        ],
        max_tokens=1000,
    )
    return response.choices[0].message.content.strip()


def extract_topic(post_text: str) -> str:
    client = OpenAI(api_key=OPENAI_KEY, base_url="https://api.proxyapi.ru/openai/v1")
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": (
            f"Извлеки главную тему этого поста одной короткой фразой (5-8 слов). "
            f"Только фраза, без точки:\n\n{post_text[:500]}"
        )}],
        max_tokens=30,
    )
    return response.choices[0].message.content.strip()


# ──────────────────────────────────────────────────────────────
# ОСНОВНАЯ ЛОГИКА
# ──────────────────────────────────────────────────────────────
async def post_to_channel():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    # Защита от двойного запуска на ЭТОМ сервере (если таймер/cron сработают дважды).
    # ВНИМАНИЕ: не спасает от запуска на ДРУГОМ сервере или от Make.com — там источник свой.
    lock_handle = open("/tmp/sochi_channel.lock", "w")
    try:
        fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (IOError, OSError):
        logging.error("Скрипт уже выполняется в другом процессе. Завершаюсь, чтобы не задвоить пост.")
        return

    now = datetime.now(MOSCOW_TZ)
    logging.info(f"Запуск. Дата: {now.strftime('%d.%m.%Y %H:%M')}")

    # Формат по дню года
    format_num = (now.timetuple().tm_yday % 3) + 1
    logging.info(f"Формат: {format_num}")

    # История
    history      = load_history()
    history_text = format_history_for_prompt(history)
    logging.info(f"Тем в истории: {len(history)}")

    # Генерируем пост
    logging.info("Генерирую пост...")
    try:
        post_text = generate_post(format_num, history_text)
        logging.info(f"Пост готов. Длина: {len(post_text)} символов")
    except Exception as e:
        logging.error(f"Ошибка генерации: {e}")
        return

    # Получаем фото
    photos    = fetch_wikimedia_photos()
    photo_url = random.choice(photos)
    logging.info(f"Фото: {photo_url}")

    # Отправляем
    bot = Bot(token=BOT_TOKEN)
    try:
        try:
            await bot.send_photo(chat_id=CHANNEL_ID, photo=photo_url, caption=post_text)
            logging.info("✅ Пост с фото опубликован!")
        except Exception as e:
            logging.warning(f"Фото не прошло ({e}), отправляю текст без фото...")
            await bot.send_message(chat_id=CHANNEL_ID, text=post_text, disable_web_page_preview=True)
            logging.info("✅ Текстовый пост опубликован!")
    except Exception as e:
        logging.error(f"Ошибка отправки: {e}")
        return
    finally:
        await bot.session.close()

    # Сохраняем тему
    try:
        topic   = extract_topic(post_text)
        history = save_history(history, topic)
        logging.info(f"Тема сохранена: {topic}")
    except Exception as e:
        logging.error(f"Ошибка сохранения истории: {e}")


if __name__ == "__main__":
    asyncio.run(post_to_channel())
