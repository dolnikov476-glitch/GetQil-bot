"""
Qil — AI Telegram бот
Функции: генерация текстов, изображений, озвучка, память разговора
Зависимости: pip install python-telegram-bot groq gtts requests
"""

import logging
import json
import os
import io
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
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8745686881:AAGXFVZ0s2GWPqPCb_pjDQgmZXMucDD1CE0")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "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")
FREE_REQUESTS_LIMIT = 20
SUBSCRIPTION_PRICE = "100 руб/месяц"
PAYMENT_INFO = "Для оплаты напишите @livix95"
MAX_MEMORY = 10  # Сколько сообщений помнит бот
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
    # Оставляем только последние MAX_MEMORY сообщений
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
    user_data = get_user(user_id)
    return user_data.get("history", [])


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
        "Ты профессиональный копирайтер и помощник по созданию текстов на русском языке. "
        "Пиши грамотно, убедительно и по делу. "
        "Если просят пост — делай его живым и вовлекающим. "
        "Если резюме — структурированным. "
        "Если рекламный текст — цепляющим. "
        "Помни контекст предыдущих сообщений и учитывай его в ответах. "
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

    # Сохраняем в память
    add_to_history(user_id, "user", user_prompt)
    add_to_history(user_id, "assistant", result)

    return result


def generate_image(prompt: str) -> bytes:
    url = f"https://image.pollinations.ai/prompt/{requests.utils.quote(prompt)}?width=512&height=512&nologo=true"
    response = requests.get(url, timeout=60)
    return response.content


def generate_voice(text: str) -> io.BytesIO:
    tts = gTTS(text=text, lang="ru")
    audio = io.BytesIO()
    tts.write_to_fp(audio)
    audio.seek(0)
    return audio


def limit_exceeded_markup():
    return InlineKeyboardMarkup([[InlineKeyboardButton("Оформить подписку", callback_data="subscribe")]])


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
        "🧠 Помню контекст нашего разговора\n\n"
        f"У тебя {FREE_REQUESTS_LIMIT} бесплатных запросов\n\n"
        "Выбери режим и напиши запрос!"
    )

    keyboard = [
        [
            InlineKeyboardButton("✍️ Текст", callback_data="mode_text"),
            InlineKeyboardButton("🎨 Картинка", callback_data="mode_image"),
            InlineKeyboardButton("🔊 Озвучка", callback_data="mode_voice"),
        ],
        [
            InlineKeyboardButton("🧹 Очистить память", callback_data="clear_memory"),
            InlineKeyboardButton("💡 Примеры", callback_data="examples"),
        ]
    ]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Как пользоваться Qil:\n\n"
        "1. Выбери режим кнопками\n"
        "2. Напиши запрос\n\n"
        "Режимы:\n"
        "✍️ Текст — посты, резюме, рекламные тексты\n"
        "🎨 Картинка — любое изображение по описанию\n"
        "🔊 Озвучка — отправь текст, получи аудио\n\n"
        "Команды:\n"
        "/start — главное меню\n"
        "/status — твоя статистика\n"
        "/clear — очистить память разговора\n\n"
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

    modes = {"text": "✍️ Текст", "image": "🎨 Картинка", "voice": "🔊 Озвучка"}

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
        action="typing" if mode != "image" else "upload_photo"
    )

    try:
        if mode == "text":
            result = generate_text(user_id, update.message.text)
            increment_requests(user_id)

            updated = get_user(user_id)
            remaining = max(0, FREE_REQUESTS_LIMIT - updated["requests"])
            footer = ""
            if not is_paid:
                if remaining > 0:
                    footer = f"\n\nОсталось запросов: {remaining}"
                else:
                    footer = f"\n\nЛимит исчерпан! Подписка: {SUBSCRIPTION_PRICE}\n{PAYMENT_INFO}"

            await update.message.reply_text(result + footer)

        elif mode == "image":
            await update.message.reply_text("Рисую, подожди 10-20 секунд...")
            image_bytes = generate_image(update.message.text)
            increment_requests(user_id)

            updated = get_user(user_id)
            remaining = max(0, FREE_REQUESTS_LIMIT - updated["requests"])
            caption = ""
            if not is_paid and remaining == 0:
                caption = f"Лимит исчерпан! Подписка: {SUBSCRIPTION_PRICE}\n{PAYMENT_INFO}"
            elif not is_paid:
                caption = f"Осталось запросов: {remaining}"

            await update.message.reply_photo(photo=image_bytes, caption=caption)

        elif mode == "voice":
            audio = generate_voice(update.message.text)
            increment_requests(user_id)

            updated = get_user(user_id)
            remaining = max(0, FREE_REQUESTS_LIMIT - updated["requests"])

            await update.message.reply_voice(voice=audio)

            if not is_paid:
                if remaining == 0:
                    await update.message.reply_text(f"Лимит исчерпан! Подписка: {SUBSCRIPTION_PRICE}\n{PAYMENT_INFO}")
                else:
                    await update.message.reply_text(f"Осталось запросов: {remaining}")

    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await update.message.reply_text("Что-то пошло не так, попробуй ещё раз.")


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

    elif query.data == "clear_memory":
        clear_history(user_id)
        await query.message.reply_text("🧹 Память очищена!")

    elif query.data == "examples":
        text = (
            "Примеры запросов:\n\n"
            "✍️ Текст:\n"
            "- Напиши пост про кофейный магазин\n"
            "- Сделай его короче\n"
            "- Добавь призыв к действию\n\n"
            "🎨 Картинка:\n"
            "- Кот в скафандре, цифровое искусство\n\n"
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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Qil bot запущен!")
    app.run_polling()


if __name__ == "__main__":
    main()
