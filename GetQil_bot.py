"""
Qil — AI Telegram бот для генерации текстов
Зависимости: pip install python-telegram-bot groq
"""

import logging
import json
from pathlib import Path
from groq import Groq
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, CallbackQueryHandler
)
from telegram.request import HTTPXRequest

# ============================================================
# НАСТРОЙКИ — ЗАПОЛНИ ПЕРЕД ЗАПУСКОМ
# ============================================================
TELEGRAM_TOKEN = "8745686881:AAGXFVZ0s2GWPqPCb_pjDQgmZXMucDD1CE0"   # <- вставь сюда
GROQ_API_KEY = "org_01kk6h8jq3fvw9yw3yzj0q28yg"           # <- вставь сюда
FREE_REQUESTS_LIMIT = 5
SUBSCRIPTION_PRICE = "299 руб/месяц"
PAYMENT_INFO = "Для оплаты напишите @твой_юзернейм"  # <- замени
PROXY_URL = "http://127.0.0.1:7890"
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
        users[uid] = {"requests": 0, "is_paid": False}
        save_users(users)
    return users[uid]


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


def generate_text(user_prompt: str) -> str:
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "system",
                "content": (
                    "Ты профессиональный копирайтер и помощник по созданию текстов на русском языке. "
                    "Пиши грамотно, убедительно и по делу. "
                    "Если просят пост — делай его живым и вовлекающим. "
                    "Если резюме — структурированным. "
                    "Если рекламный текст — цепляющим. "
                    "Не используй символы * # и другое markdown форматирование в ответе."
                )
            },
            {"role": "user", "content": user_prompt}
        ],
        max_tokens=1024
    )
    return response.choices[0].message.content


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    get_user(user.id)

    text = (
        f"Привет, {user.first_name}!\n\n"
        "Я Qil — твой AI копирайтер\n\n"
        "Помогу написать:\n"
        "- Посты для соцсетей\n"
        "- Резюме и сопроводительные письма\n"
        "- Описания товаров\n"
        "- Рекламные тексты\n\n"
        f"У тебя {FREE_REQUESTS_LIMIT} бесплатных запросов\n\n"
        "Просто напиши что нужно — и я сделаю!"
    )

    keyboard = [[InlineKeyboardButton("Примеры запросов", callback_data="examples")]]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Как пользоваться Qil:\n\n"
        "Просто напиши запрос, например:\n\n"
        "- Напиши пост про мой кофейный магазин\n"
        "- Сделай резюме для маркетолога с 3 годами опыта\n"
        "- Придумай рекламный текст для доставки еды\n"
        "- Напиши описание товара: беспроводные наушники\n\n"
        f"Подписка: {SUBSCRIPTION_PRICE} — безлимитные запросы\n"
        f"{PAYMENT_INFO}"
    )
    await update.message.reply_text(text)


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data = get_user(update.effective_user.id)
    requests_used = user_data["requests"]
    is_paid = user_data["is_paid"]

    if is_paid:
        text = "У тебя премиум-доступ — безлимитные запросы!"
    else:
        remaining = max(0, FREE_REQUESTS_LIMIT - requests_used)
        text = (
            f"Твоя статистика:\n\n"
            f"Использовано запросов: {requests_used}\n"
            f"Осталось бесплатных: {remaining}\n"
        )
        if remaining == 0:
            text += f"\nЛимит исчерпан!\nПодписка: {SUBSCRIPTION_PRICE}\n{PAYMENT_INFO}"

    await update.message.reply_text(text)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user(user_id)
    requests_used = user_data["requests"]
    is_paid = user_data["is_paid"]

    if not is_paid and requests_used >= FREE_REQUESTS_LIMIT:
        await update.message.reply_text(
            f"Бесплатный лимит исчерпан!\n\n"
            f"Ты использовал все {FREE_REQUESTS_LIMIT} запросов.\n\n"
            f"Подписка — {SUBSCRIPTION_PRICE}, безлимит!\n{PAYMENT_INFO}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Оформить подписку", callback_data="subscribe")]])
        )
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        result = generate_text(update.message.text)
        increment_requests(user_id)

        updated = get_user(user_id)
        remaining = max(0, FREE_REQUESTS_LIMIT - updated["requests"])

        footer = ""
        if not is_paid:
            if remaining > 0:
                footer = f"\n\nОсталось бесплатных запросов: {remaining}"
            else:
                footer = f"\n\nПоследний бесплатный запрос использован!\nПодписка: {SUBSCRIPTION_PRICE}"

        await update.message.reply_text(result + footer)

    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await update.message.reply_text("Что-то пошло не так, попробуй ещё раз.")


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "examples":
        text = (
            "Примеры запросов:\n\n"
            "- Напиши вовлекающий пост про фитнес для Instagram\n\n"
            "- Составь резюме для Python-разработчика с опытом 2 года\n\n"
            "- Напиши описание товара: умные часы с пульсометром\n\n"
            "- Придумай рекламный текст для онлайн-школы английского\n\n"
            "- Напиши сопроводительное письмо для вакансии менеджера"
        )
        await query.message.reply_text(text)

    elif query.data == "subscribe":
        text = (
            f"Оформление подписки\n\n"
            f"Стоимость: {SUBSCRIPTION_PRICE}\n"
            f"Доступ: безлимитные запросы\n\n"
            f"{PAYMENT_INFO}\n\n"
            "После оплаты пришли скриншот — активируем в течение часа!"
        )
        await query.message.reply_text(text)


def main():
    request = HTTPXRequest(
        proxy=PROXY_URL,
        connection_pool_size=16,
        pool_timeout=60.0,
        connect_timeout=30.0,
        read_timeout=30.0,
        write_timeout=30.0,
    )

    get_updates_request = HTTPXRequest(
        proxy=PROXY_URL,
        connection_pool_size=8,
        pool_timeout=60.0,
        connect_timeout=30.0,
        read_timeout=30.0,
        write_timeout=30.0,
    )

    app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .request(request)
        .get_updates_request(get_updates_request)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Qil bot запущен!")
    app.run_polling()


if __name__ == "__main__":
    main()