"""
Qil — AI Telegram бот
Функции: тексты, картинки, озвучка, память, анализ фото
Зависимости: pip install python-telegram-bot groq gtts requests
"""

import logging
import json
import os
import io
import base64
import requests
from pathlib import Path
from groq import Groq
from gtts import gTTS
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, CallbackQueryHandler
)

# ============================================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "ВАШ_ТОКЕН_ОТ_BOTFATHER")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "ВАШ_КЛЮЧ_ОТ_GROQ")
FREE_REQUESTS_LIMIT = 20
SUBSCRIPTION_PRICE = "100 руб/месяц"
PAYMENT_INFO = "Для оплаты напишите @livix95"
MAX_MEMORY = 10
# ============================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

client = Groq(api_key=GROQ_API_KEY)

USERS_FILE = "users_data.json"


def load_users() -> dict:
    if Path(USERS_FILE).exists():
        with open(USERS_FILE, "r") as f:
            return json.load(f)
    return {}


def save_users(users: dict):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)


def get_user(user_id: int) -> dict:
    users = load_users()
    uid = str(user_id)
    if uid not in users:
        users[uid] = {"requests": 0, "is_paid": False, "mode": "text", "history": []}
        save_users(users)
    return users[uid]


def set_mode(user_id: int, mode: str):
    users = load_users()
    uid = str(user_id)
    if uid in users:
        users[uid]["mode"] = mode
        save_users(users)


def add_to_history(user_id: int, role: str, content: str):
    users = load_users()
    uid = str(user_id)
    if uid not in users:
        return
    if "history" not in users[uid]:
        users[uid]["history"] = []
    users[uid]["history"].append({"role": role, "content": content})
    if len(users[uid]["history"]) > MAX_MEMORY * 2:
        users[uid]["history"] = users[uid]["history"][-MAX_MEMORY * 2:]
    save_users(users)


def clear_history(user_id: int):
    users = load_users()
    uid = str(user_id)
    if uid in users:
        users[uid]["history"] = []
        save_users(users)


def get_history(user_id: int) -> list:
    return get_user(user_id).get("history", [])


def increment_requests(user_id: int):
    users = load_users()
    uid = str(user_id)
    users[uid]["requests"] = users[uid].get("requests", 0) + 1
    save_users(users)


def set_paid(user_id: int):
    users = load_users()
    uid = str(user_id)
    if uid in users:
        users[uid]["is_paid"] = True
        save_users(users)


def check_limit(user_id: int) -> bool:
    user_data = get_user(user_id)
    return user_data["is_paid"] or user_data["requests"] < FREE_REQUESTS_LIMIT


def generate_text(user_id: int, user_prompt: str) -> str:
    history = get_history(user_id)
    system = (
        "Ты профессиональный копирайтер и AI ассистент на русском языке. "
        "Пиши грамотно, убедительно и по делу. "
        "Если просят пост — делай его живым и вовлекающим. "
        "Если резюме — структурированным. "
        "Если рекламный текст — цепляющим. "
        "Помни контекст предыдущих сообщений. "
        "Не используй символы * # и другое markdown форматирование в ответе."
    )
    messages = [{"role": "system", "content": system}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_prompt})

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=messages,
        max_tokens=1024
    )
    result = response.choices[0].message.content
    add_to_history(user_id, "user", user_prompt)
    add_to_history(user_id, "assistant", result)
    return result


def analyze_photo(image_bytes: bytes, caption: str = "") -> str:
    image_base64 = base64.b64encode(image_bytes).decode("utf-8")
    prompt = caption if caption else "Опиши подробно что изображено на этом фото. Отвечай на русском языке."

    response = client.chat.completions.create(
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_base64}"
                        }
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }
        ],
        max_tokens=1024
    )
    return response.choices[0].message.content


def generate_image(prompt: str) -> bytes:
    # Улучшаем промпт для лучшего качества
    enhanced_prompt = (
        f"{prompt}, "
        "high quality, detailed, professional, 4k, sharp focus, "
        "beautiful lighting, masterpiece"
    )
    url = f"https://image.pollinations.ai/prompt/{requests.utils.quote(enhanced_prompt)}?width=768&height=768&nologo=true&enhance=true&model=flux"
    response = requests.get(url, timeout=90)
    return response.content


def generate_voice(text: str) -> io.BytesIO:
    tts = gTTS(text=text, lang="ru")
    audio = io.BytesIO()
    tts.write_to_fp(audio)
    audio.seek(0)
    return audio


def limit_exceeded_markup():
    return InlineKeyboardMarkup([[InlineKeyboardButton("Оформить подписку", callback_data="subscribe")]])


def main_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✍️ Текст", callback_data="mode_text"),
            InlineKeyboardButton("🎨 Картинка", callback_data="mode_image"),
            InlineKeyboardButton("🔊 Озвучка", callback_data="mode_voice"),
        ],
        [
            InlineKeyboardButton("📸 Анализ фото", callback_data="mode_photo"),
            InlineKeyboardButton("🧹 Очистить память", callback_data="clear_memory"),
        ],
        [InlineKeyboardButton("💡 Примеры", callback_data="examples")]
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    get_user(user.id)
    text = (
        f"Привет, {user.first_name}!\n\n"
        "Я Qil — твой AI ассистент\n\n"
        "Что умею:\n"
        "✍️ Генерировать тексты и посты\n"
        "🎨 Рисовать изображения по запросу\n"
        "🔊 Озвучивать любой текст\n"
        "📸 Анализировать фотографии\n"
        "🧠 Помню контекст разговора\n\n"
        f"У тебя {FREE_REQUESTS_LIMIT} бесплатных запросов\n\n"
        "Выбери режим и напиши запрос!"
    )
    await update.message.reply_text(text, reply_markup=main_keyboard())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Как пользоваться Qil:\n\n"
        "1. Выбери режим кнопками\n"
        "2. Напиши запрос или отправь фото\n\n"
        "Режимы:\n"
        "✍️ Текст — посты, резюме, рекламные тексты\n"
        "🎨 Картинка — изображение по описанию\n"
        "🔊 Озвучка — текст в аудио\n"
        "📸 Анализ фото — отправь фото и задай вопрос\n\n"
        "Команды:\n"
        "/start — главное меню\n"
        "/status — статистика\n"
        "/clear — очистить память\n\n"
        f"Подписка: {SUBSCRIPTION_PRICE} — безлимит\n"
        f"{PAYMENT_INFO}"
    )
    await update.message.reply_text(text)


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data = get_user(update.effective_user.id)
    requests_used = user_data["requests"]
    is_paid = user_data["is_paid"]
    mode = user_data.get("mode", "text")
    history_len = len(user_data.get("history", [])) // 2
    modes = {"text": "✍️ Текст", "image": "🎨 Картинка", "voice": "🔊 Озвучка", "photo": "📸 Анализ фото"}

    if is_paid:
        text = (
            f"У тебя премиум-доступ — безлимитные запросы!\n"
            f"Текущий режим: {modes.get(mode)}\n"
            f"Сообщений в памяти: {history_len}"
        )
    else:
        remaining = max(0, FREE_REQUESTS_LIMIT - requests_used)
        text = (
            f"Твоя статистика:\n\n"
            f"Использовано запросов: {requests_used}\n"
            f"Осталось бесплатных: {remaining}\n"
            f"Текущий режим: {modes.get(mode)}\n"
            f"Сообщений в памяти: {history_len}\n"
        )
        if remaining == 0:
            text += f"\nЛимит исчерпан!\nПодписка: {SUBSCRIPTION_PRICE}\n{PAYMENT_INFO}"

    await update.message.reply_text(text)


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_history(update.effective_user.id)
    await update.message.reply_text("🧹 Память очищена! Начинаем с чистого листа.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user(user_id)
    mode = user_data.get("mode", "text")
    is_paid = user_data["is_paid"]

    if not check_limit(user_id):
        await update.message.reply_text(
            f"Бесплатный лимит исчерпан!\n\n"
            f"Подписка — всего {SUBSCRIPTION_PRICE}, безлимит!\n{PAYMENT_INFO}",
            reply_markup=limit_exceeded_markup()
        )
        return

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="upload_photo" if mode == "image" else "typing"
    )

    try:
        if mode == "text":
            result = generate_text(user_id, update.message.text)
            increment_requests(user_id)
            updated = get_user(user_id)
            remaining = max(0, FREE_REQUESTS_LIMIT - updated["requests"])
            footer = ""
            if not is_paid:
                footer = f"\n\nОсталось запросов: {remaining}" if remaining > 0 else f"\n\nЛимит исчерпан! Подписка: {SUBSCRIPTION_PRICE}\n{PAYMENT_INFO}"
            await update.message.reply_text(result + footer)

        elif mode == "image":
            await update.message.reply_text("Рисую, подожди 15-30 секунд...")
            image_bytes = generate_image(update.message.text)
            increment_requests(user_id)
            updated = get_user(user_id)
            remaining = max(0, FREE_REQUESTS_LIMIT - updated["requests"])
            caption = f"Осталось запросов: {remaining}" if not is_paid and remaining > 0 else ""
            if not is_paid and remaining == 0:
                caption = f"Лимит исчерпан! Подписка: {SUBSCRIPTION_PRICE}\n{PAYMENT_INFO}"
            await update.message.reply_photo(photo=image_bytes, caption=caption)

        elif mode == "voice":
            audio = generate_voice(update.message.text)
            increment_requests(user_id)
            updated = get_user(user_id)
            remaining = max(0, FREE_REQUESTS_LIMIT - updated["requests"])
            await update.message.reply_voice(voice=audio)
            if not is_paid:
                msg = f"Осталось запросов: {remaining}" if remaining > 0 else f"Лимит исчерпан! Подписка: {SUBSCRIPTION_PRICE}\n{PAYMENT_INFO}"
                await update.message.reply_text(msg)

        elif mode == "photo":
            await update.message.reply_text("Для анализа фото — отправь фотографию!")

    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await update.message.reply_text("Что-то пошло не так, попробуй ещё раз.")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user(user_id)
    is_paid = user_data["is_paid"]

    if not check_limit(user_id):
        await update.message.reply_text(
            f"Бесплатный лимит исчерпан!\n\nПодписка — всего {SUBSCRIPTION_PRICE}, безлимит!\n{PAYMENT_INFO}",
            reply_markup=limit_exceeded_markup()
        )
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        image_bytes = await file.download_as_bytearray()

        caption = update.message.caption or ""
        result = analyze_photo(bytes(image_bytes), caption)
        increment_requests(user_id)

        updated = get_user(user_id)
        remaining = max(0, FREE_REQUESTS_LIMIT - updated["requests"])
        footer = ""
        if not is_paid:
            footer = f"\n\nОсталось запросов: {remaining}" if remaining > 0 else f"\n\nЛимит исчерпан! Подписка: {SUBSCRIPTION_PRICE}\n{PAYMENT_INFO}"

        await update.message.reply_text(result + footer)

    except Exception as e:
        logger.error(f"Ошибка анализа фото: {e}")
        await update.message.reply_text("Не удалось проанализировать фото, попробуй ещё раз.")


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "mode_text":
        set_mode(user_id, "text")
        await query.message.reply_text("✍️ Режим: Текст\n\nНапиши что нужно написать!")
    elif query.data == "mode_image":
        set_mode(user_id, "image")
        await query.message.reply_text("🎨 Режим: Картинка\n\nОпиши что нарисовать!")
    elif query.data == "mode_voice":
        set_mode(user_id, "voice")
        await query.message.reply_text("🔊 Режим: Озвучка\n\nОтправь любой текст — озвучу!")
    elif query.data == "mode_photo":
        set_mode(user_id, "photo")
        await query.message.reply_text("📸 Режим: Анализ фото\n\nОтправь фото — опишу что на нём!\nМожешь добавить подпись с вопросом.")
    elif query.data == "clear_memory":
        clear_history(user_id)
        await query.message.reply_text("🧹 Память очищена!")
    elif query.data == "examples":
        text = (
            "Примеры запросов:\n\n"
            "✍️ Текст:\n"
            "- Напиши пост про кофейный магазин\n"
            "- Сделай его короче\n\n"
            "🎨 Картинка:\n"
            "- Кот в скафандре в космосе\n"
            "- Горный закат, акварель\n\n"
            "📸 Анализ фото:\n"
            "- Отправь фото с подписью: что здесь?\n"
            "- Или: напиши пост по этому фото\n\n"
            "🔊 Озвучка:\n"
            "- Просто вставь любой текст"
        )
        await query.message.reply_text(text)
    elif query.data == "subscribe":
        text = (
            f"Оформление подписки\n\n"
            f"Стоимость: {SUBSCRIPTION_PRICE}\n"
            f"Доступ: безлимитные запросы на все функции\n\n"
            f"{PAYMENT_INFO}\n\n"
            "После оплаты пришли скриншот — активируем в течение часа!"
        )
        await query.message.reply_text(text)


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("clear", clear_command))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Qil bot запущен!")
    app.run_polling()


if __name__ == "__main__":
    main()
