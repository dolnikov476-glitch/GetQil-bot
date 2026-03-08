"""
Qil — AI Telegram бот
Без кнопок — умное определение режима по ключевым словам
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
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes
)

# ============================================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8745686881:AAGXFVZ0s2GWPqPCb_pjDQgmZXMucDD1CE0")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "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")
FREE_REQUESTS_LIMIT = 20
REFERRAL_BONUS = 10
SUBSCRIPTION_PRICE = "100 руб/месяц"
PAYMENT_INFO = "Для оплаты напишите @livix95"
MAX_MEMORY = 10
# ============================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

client = Groq(api_key=GROQ_API_KEY)
USERS_FILE = "users_data.json"

# Ключевые слова для режимов
IMAGE_WORDS = ["нарисуй", "сгенерируй картинку", "создай изображение", "нарисуй мне", "сделай фото", "сделай картинку", "картинку", "изображение"]
VOICE_WORDS = ["озвучь", "прочитай вслух", "голосом", "озвучить", "сделай аудио", "прочитай текст"]
PHOTO_WORDS = ["анализ фото", "что на фото", "опиши фото", "анализируй фото", "посмотри фото"]
STOP_WORDS = ["стоп", "назад", "меню", "хватит", "stop", "back", "старт", "в меню"]
REFERRAL_WORDS = ["реферал", "пригласить", "реферальная ссылка", "пригласить друга"]


# ── База данных ──────────────────────────────────────────────

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
        users[uid] = {
            "requests": 0,
            "bonus_requests": 0,
            "is_paid": False,
            "mode": "text",
            "history": [],
            "referrals": 0,
            "referred_by": None
        }
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
    user = users[uid]
    if user.get("bonus_requests", 0) > 0:
        users[uid]["bonus_requests"] -= 1
    else:
        users[uid]["requests"] = user.get("requests", 0) + 1
    save_users(users)


def set_paid(user_id: int):
    users = load_users()
    uid = str(user_id)
    if uid in users:
        users[uid]["is_paid"] = True
        save_users(users)


def check_limit(user_id: int) -> bool:
    user_data = get_user(user_id)
    return user_data["is_paid"] or user_data["requests"] < FREE_REQUESTS_LIMIT or user_data.get("bonus_requests", 0) > 0


def get_remaining(user_id: int) -> int:
    user_data = get_user(user_id)
    base = max(0, FREE_REQUESTS_LIMIT - user_data["requests"])
    bonus = user_data.get("bonus_requests", 0)
    return base + bonus


def register_referral(new_user_id: int, referrer_id: int):
    users = load_users()
    new_uid = str(new_user_id)
    ref_uid = str(referrer_id)
    if new_uid not in users:
        get_user(new_user_id)
        users = load_users()
    if users[new_uid].get("referred_by") is None and new_uid != ref_uid:
        users[new_uid]["referred_by"] = referrer_id
        if ref_uid in users:
            users[ref_uid]["referrals"] = users[ref_uid].get("referrals", 0) + 1
            users[ref_uid]["bonus_requests"] = users[ref_uid].get("bonus_requests", 0) + REFERRAL_BONUS
        save_users(users)
        return True
    return False


# ── AI функции ───────────────────────────────────────────────

def generate_text(user_id: int, user_prompt: str) -> str:
    history = get_history(user_id)
    system = (
        "Ты профессиональный копирайтер и AI ассистент на русском языке. "
        "Пиши грамотно, убедительно и по делу. "
        "Если просят пост — делай его живым и вовлекающим. "
        "Если резюме — структурированным. Если рекламный текст — цепляющим. "
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
        messages=[{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
                {"type": "text", "text": prompt}
            ]
        }],
        max_tokens=1024
    )
    return response.choices[0].message.content


def generate_image(prompt: str) -> bytes:
    enhanced = f"{prompt}, high quality, detailed, professional, 4k, sharp focus, beautiful lighting, masterpiece"
    url = f"https://image.pollinations.ai/prompt/{requests.utils.quote(enhanced)}?width=768&height=768&nologo=true&enhance=true&model=flux"
    response = requests.get(url, timeout=90)
    return response.content


def generate_voice(text: str) -> io.BytesIO:
    tts = gTTS(text=text, lang="ru")
    audio = io.BytesIO()
    tts.write_to_fp(audio)
    audio.seek(0)
    return audio


def footer_text(user_id: int, is_paid: bool) -> str:
    if is_paid:
        return ""
    remaining = get_remaining(user_id)
    if remaining > 0:
        return f"\n\nОсталось запросов: {remaining}"
    return f"\n\nЛимит исчерпан!\nПодписка: {SUBSCRIPTION_PRICE}\n{PAYMENT_INFO}"


# ── Хендлеры ────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    get_user(user.id)

    if context.args and context.args[0].startswith("ref_"):
        try:
            referrer_id = int(context.args[0].replace("ref_", ""))
            if register_referral(user.id, referrer_id):
                try:
                    await context.bot.send_message(
                        chat_id=referrer_id,
                        text=f"🎉 По твоей ссылке зарегистрировался новый пользователь!\nТы получил +{REFERRAL_BONUS} бонусных запросов!"
                    )
                except:
                    pass
        except:
            pass

    text = (
        f"Привет, {user.first_name}!\n\n"
        "Я Qil — твой AI ассистент ✍️\n\n"
        "Просто напиши мне что нужно:\n\n"
        "Нарисуй закат над морем\n"
        "Озвучь: привет, это мой текст\n"
        "Напиши пост про кофейный магазин\n"
        "Отправь фото — опишу что на нём\n\n"
        f"У тебя {FREE_REQUESTS_LIMIT} бесплатных запросов\n\n"
        "Напиши СТОП чтобы сбросить режим"
    )
    await update.message.reply_text(text, reply_markup=ReplyKeyboardRemove())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Как пользоваться Qil:\n\n"
        "Просто пиши что хочешь — я сам пойму!\n\n"
        "Примеры:\n"
        "- Нарисуй кота в космосе\n"
        "- Озвучь: текст для озвучки\n"
        "- Напиши пост для Instagram\n"
        "- Отправь фото с вопросом в подписи\n"
        "- Реферальная ссылка\n\n"
        "Команды:\n"
        "/start — начало\n"
        "/status — статистика\n"
        "/clear — очистить память\n\n"
        f"Подписка: {SUBSCRIPTION_PRICE} — безлимит\n"
        f"{PAYMENT_INFO}"
    )
    await update.message.reply_text(text)


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data = get_user(update.effective_user.id)
    is_paid = user_data["is_paid"]
    mode = user_data.get("mode", "text")
    history_len = len(user_data.get("history", [])) // 2
    referrals = user_data.get("referrals", 0)
    bonus = user_data.get("bonus_requests", 0)
    modes = {
        "text": "✍️ Текст", "image": "🎨 Картинка",
        "voice": "🔊 Озвучка", "photo": "📸 Фото"
    }

    if is_paid:
        text = (
            f"Премиум — безлимит!\n"
            f"Режим: {modes.get(mode, 'Текст')}\n"
            f"Память: {history_len} сообщений\n"
            f"Рефералов: {referrals}"
        )
    else:
        remaining = get_remaining(update.effective_user.id)
        text = (
            f"Осталось запросов: {remaining}\n"
            f"Из них бонусных: {bonus}\n"
            f"Режим: {modes.get(mode, 'Текст')}\n"
            f"Память: {history_len} сообщений\n"
            f"Рефералов: {referrals}\n"
        )
        if remaining == 0:
            text += f"\nЛимит исчерпан!\nПодписка: {SUBSCRIPTION_PRICE}\n{PAYMENT_INFO}"

    await update.message.reply_text(text)


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_history(update.effective_user.id)
    await update.message.reply_text("🧹 Память очищена!")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user(user_id)
    is_paid = user_data["is_paid"]
    text_input = update.message.text
    text_lower = text_input.lower().strip()

    # Стоп — сброс режима
    if text_lower in STOP_WORDS:
        set_mode(user_id, "text")
        await update.message.reply_text(
            "Режим сброшен! Пиши что нужно:\n\n"
            "Нарисуй, Озвучь, Напиши пост..."
        )
        return

    # Реферальная ссылка
    if any(w in text_lower for w in REFERRAL_WORDS):
        bot = await context.bot.get_me()
        ref_link = f"https://t.me/{bot.username}?start=ref_{user_id}"
        user_data2 = get_user(user_id)
        await update.message.reply_text(
            f"👥 Реферальная программа\n\n"
            f"За каждого друга +{REFERRAL_BONUS} бонусных запросов!\n\n"
            f"Твоя ссылка:\n{ref_link}\n\n"
            f"Приглашено: {user_data2.get('referrals', 0)}\n"
            f"Бонусных запросов: {user_data2.get('bonus_requests', 0)}"
        )
        return

    # Определяем режим по ключевым словам
    mode = user_data.get("mode", "text")

    if any(w in text_lower for w in IMAGE_WORDS):
        mode = "image"
        set_mode(user_id, "image")
    elif any(w in text_lower for w in VOICE_WORDS):
        mode = "voice"
        set_mode(user_id, "voice")
    elif any(w in text_lower for w in PHOTO_WORDS):
        mode = "photo"
        set_mode(user_id, "photo")

    # Режим фото — просим прислать фото
    if mode == "photo":
        await update.message.reply_text(
            "📸 Отправь фото!\nМожешь добавить подпись с вопросом.\n\nНапиши СТОП чтобы выйти."
        )
        return

    if not check_limit(user_id):
        await update.message.reply_text(
            f"Лимит исчерпан!\n\nПодписка — {SUBSCRIPTION_PRICE}, безлимит!\n{PAYMENT_INFO}"
        )
        return

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="upload_photo" if mode == "image" else "typing"
    )

    try:
        if mode == "image":
            await update.message.reply_text("Рисую, подожди 15-30 секунд...")
            image_bytes = generate_image(text_input)
            increment_requests(user_id)
            caption = footer_text(user_id, is_paid).strip()
            await update.message.reply_photo(photo=image_bytes, caption=caption)

        elif mode == "voice":
            # Убираем ключевое слово из текста
            clean_text = text_input
            for w in ["озвучь", "озвучить", "прочитай вслух", "голосом", "сделай аудио", "прочитай текст", "прочитай"]:
                clean_text = clean_text.replace(w, "").replace(w.capitalize(), "").strip(" :,-")
            if not clean_text:
                await update.message.reply_text("Напиши текст для озвучки, например:\nОзвучь: Привет, это мой текст!")
                return
            audio = generate_voice(clean_text)
            increment_requests(user_id)
            await update.message.reply_voice(voice=audio)
            ft = footer_text(user_id, is_paid)
            if ft:
                await update.message.reply_text(ft.strip())

        else:  # text режим
            result = generate_text(user_id, text_input)
            increment_requests(user_id)
            ft = footer_text(user_id, is_paid)
            await update.message.reply_text(result + ft)

    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await update.message.reply_text("Что-то пошло не так, попробуй ещё раз.")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_paid = get_user(user_id)["is_paid"]

    if not check_limit(user_id):
        await update.message.reply_text(
            f"Лимит исчерпан!\nПодписка: {SUBSCRIPTION_PRICE}\n{PAYMENT_INFO}"
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
        ft = footer_text(user_id, is_paid)
        await update.message.reply_text(result + ft)
    except Exception as e:
        logger.error(f"Ошибка анализа фото: {e}")
        await update.message.reply_text("Не удалось проанализировать фото, попробуй ещё раз.")


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("clear", clear_command))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Qil bot запущен!")
    app.run_polling()


if __name__ == "__main__":
    main()
