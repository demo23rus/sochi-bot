#!/usr/bin/env python3
"""
Канал «История Сочи каждый день» (@staryi_sochi)
File: /root/sochi_channel.py
Service: sochi-channel.timer (systemd)
Запуск: каждый день в 10:00 МСК
"""

import asyncio
import logging
import os
import random
import json
from datetime import datetime
from pathlib import Path

import pytz
from aiogram import Bot
from openai import OpenAI

# ──────────────────────────────────────────────────────────────
# КОНФИГ
# ──────────────────────────────────────────────────────────────
BOT_TOKEN   = "8987086395:AAHN0YjaZTQoP28WPImnQguZrx5FPiXV8kw"
OPENAI_KEY  = "sk-mfvVI3QN2uQvXPlhMkAeUUzmbjK5aQzj"
CHANNEL_ID  = "@staryi_sochi"
HISTORY_FILE = "/root/sochi_posts_history.json"
MOSCOW_TZ   = pytz.timezone("Europe/Moscow")
MODEL       = "gpt-4o"

# ──────────────────────────────────────────────────────────────
# ФОТО СОЧИ (Unsplash — прямые ссылки, без API)
# ──────────────────────────────────────────────────────────────
SOCHI_PHOTOS = [
    "https://images.unsplash.com/photo-1596484552834-6a58f850e0a1?w=1200",
    "https://images.unsplash.com/photo-1605493725784-37e84f80f8e8?w=1200",
    "https://images.unsplash.com/photo-1548013146-72479768bada?w=1200",
    "https://images.unsplash.com/photo-1504701954957-2010ec3bcec1?w=1200",
    "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?w=1200",
    "https://images.unsplash.com/photo-1519046904884-53103b34b206?w=1200",
    "https://images.unsplash.com/photo-1506929562872-bb421503ef21?w=1200",
    "https://images.unsplash.com/photo-1500375592092-40eb2168fd21?w=1200",
    "https://images.unsplash.com/photo-1473186578172-c141e6798cf4?w=1200",
    "https://images.unsplash.com/photo-1540202404-1b927e27fa8b?w=1200",
    "https://images.unsplash.com/photo-1510414842594-a61c69b5ae57?w=1200",
    "https://images.unsplash.com/photo-1544551763-46a013bb70d5?w=1200",
    "https://images.unsplash.com/photo-1519451241324-20b4ea2c4220?w=1200",
    "https://images.unsplash.com/photo-1501594907352-04cda38ebc29?w=1200",
    "https://images.unsplash.com/photo-1476514525535-07fb3b4ae5f1?w=1200",
    "https://images.unsplash.com/photo-1455156218388-5e61b526818b?w=1200",
    "https://images.unsplash.com/photo-1533587851505-d119e13fa0d7?w=1200",
    "https://images.unsplash.com/photo-1528543606781-2f6e8759f642?w=1200",
    "https://images.unsplash.com/photo-1520454974749-a7a40a900c50?w=1200",
    "https://images.unsplash.com/photo-1518623489648-a173ef7824f3?w=1200",
    "https://images.unsplash.com/photo-1516483638261-f4dbaf036963?w=1200",
    "https://images.unsplash.com/photo-1514565131-fce0801e6785?w=1200",
    "https://images.unsplash.com/photo-1509233725247-49e657c54213?w=1200",
    "https://images.unsplash.com/photo-1500534314209-a25ddb2bd429?w=1200",
    "https://images.unsplash.com/photo-1493246507139-91e8fad9978e?w=1200",
    "https://images.unsplash.com/photo-1491555103944-7c647fd857e6?w=1200",
    "https://images.unsplash.com/photo-1488085061387-422e29b40080?w=1200",
    "https://images.unsplash.com/photo-1486325212027-8081e485255e?w=1200",
    "https://images.unsplash.com/photo-1485470733090-0aae1788d5af?w=1200",
    "https://images.unsplash.com/photo-1483683804023-6ccdb62f86ef?w=1200",
]

# ──────────────────────────────────────────────────────────────
# ИСТОРИЯ ПОСТОВ
# ──────────────────────────────────────────────────────────────
def load_history() -> list:
    """Загружает историю использованных тем"""
    if not Path(HISTORY_FILE).exists():
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_history(history: list, new_topic: str):
    """Сохраняет новую тему в историю (хранит последние 200)"""
    history.append({
        "date": datetime.now(MOSCOW_TZ).strftime("%d.%m.%Y"),
        "topic": new_topic,
    })
    # Храним только последние 200 записей
    history = history[-200:]
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Ошибка сохранения истории: {e}")
    return history


def format_history_for_prompt(history: list) -> str:
    """Форматирует историю для передачи в промпт"""
    if not history:
        return "Ранее опубликованных постов нет."
    last = history[-50:]  # последние 50 тем
    lines = [f"- {h['date']}: {h['topic']}" for h in last]
    return "Уже опубликованные темы (НЕ ПОВТОРЯЙ):\n" + "\n".join(lines)


# ──────────────────────────────────────────────────────────────
# ГЕНЕРАЦИЯ ПОСТА
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

ЗАПОМНИ: пост должен быть таким, чтобы местный житель Сочи (не турист) прочитал и сказал "ого, я этого не знал". Не туристическая открытка, а живой, тёплый рассказ о городе с конкретикой и деталями."""


def generate_post(format_num: int, history_text: str) -> str:
    """Генерирует пост через Claude"""
    client = OpenAI(
        api_key=OPENAI_KEY,
        base_url="https://api.proxyapi.ru/openai/v1"
    )
    today = datetime.now(MOSCOW_TZ).strftime("%d.%m.%Y")
    user_message = (
        f"Сегодня: {today}\n\n"
        f"{history_text}\n\n"
        f"Используй ФОРМАТ {format_num} из системного промпта. "
        f"Сгенерируй пост на НОВУЮ тему о Сочи которой ещё не было в истории выше."
    )
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_message},
        ],
        max_tokens=1000,
    )
    return response.choices[0].message.content.strip()


def extract_topic(post_text: str) -> str:
    """Извлекает краткую тему из поста для сохранения в историю"""
    client = OpenAI(
        api_key=OPENAI_KEY,
        base_url="https://api.proxyapi.ru/openai/v1"
    )
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{
            "role": "user",
            "content": (
                f"Извлеки главную тему этого поста одной короткой фразой (5-8 слов). "
                f"Только фраза, без точки:\n\n{post_text[:500]}"
            )
        }],
        max_tokens=30,
    )
    return response.choices[0].message.content.strip()


# ──────────────────────────────────────────────────────────────
# ОСНОВНАЯ ЛОГИКА
# ──────────────────────────────────────────────────────────────
async def post_to_channel():
    """Генерирует и публикует пост в канал"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

    now = datetime.now(MOSCOW_TZ)
    logging.info(f"Запуск постинга в канал. Дата: {now.strftime('%d.%m.%Y %H:%M')}")

    # Определяем формат по дню года (1, 2 или 3)
    day_of_year = now.timetuple().tm_yday
    format_num  = (day_of_year % 3) + 1
    logging.info(f"Формат поста: {format_num}")

    # Загружаем историю
    history      = load_history()
    history_text = format_history_for_prompt(history)
    logging.info(f"Загружено тем в истории: {len(history)}")

    # Генерируем пост
    logging.info("Генерирую пост через GPT-4o...")
    try:
        post_text = generate_post(format_num, history_text)
        logging.info(f"Пост сгенерирован. Длина: {len(post_text)} символов")
    except Exception as e:
        logging.error(f"Ошибка генерации поста: {e}")
        return

    # Выбираем случайное фото
    photo_url = random.choice(SOCHI_PHOTOS)
    logging.info(f"Фото: {photo_url}")

    # Отправляем в канал
    bot = Bot(token=BOT_TOKEN)
    try:
        await bot.send_photo(
            chat_id=CHANNEL_ID,
            photo=photo_url,
            caption=post_text,
            disable_notification=False,
        )
        logging.info("✅ Пост успешно опубликован в канале!")
    except Exception as e:
        logging.error(f"Ошибка отправки в Telegram: {e}")
        await bot.session.close()
        return
    finally:
        await bot.session.close()

    # Сохраняем тему в историю
    try:
        topic   = extract_topic(post_text)
        history = save_history(history, topic)
        logging.info(f"Тема сохранена в историю: {topic}")
    except Exception as e:
        logging.error(f"Ошибка сохранения истории: {e}")


if __name__ == "__main__":
    asyncio.run(post_to_channel())
