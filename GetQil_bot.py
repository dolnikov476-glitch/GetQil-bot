"""
Qil — AI Telegram бот
Полная память для всех режимов + кнопки старта
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
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8745686881:AAGXFVZ0s2GWPqPCb_pjDQgmZXMucDD1CE0")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "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")
FREE_REQUESTS_LIMIT = 20
REFERRAL_BONUS = 10
SUBSCRIPTION_PRICE = "100 руб/месяц"
PAYMENT_INFO = "Для оплаты напишите @livix95"
MAX_MEMORY = 30
# ============================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

client = Groq(api_key=GROQ_API_KEY)
USERS_FILE = "users_data.json"

IMAGE_WORDS = ["нарисуй", "сгенерируй картинку", "создай изображение", "нарисуй мне", "сделай фото", "сделай картинку", "нарисуй картинку"]
VOICE_WORDS = ["озвучь", "прочитай вслух", "голосом", "озвучить", "сделай аудио", "прочитай текст"]
STOP_WORDS = ["стоп", "назад", "меню", "хватит", "stop", "back", "сброс"]


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
            "history": [],
            "referrals": 0,
            "referred_by": None,
            "last_image_prompt": None,
            "last_voice_text": None,
        }
        save_users(users)
    return users[uid]


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


def save_last_image(user_id: int, prompt: str):
    users = load_users()
    uid = str(user_id)
    if uid in users:
        users[uid]["last_image_prompt"] = prompt
        save_users(users)


def save_last_voice(user_id: int, text: str):
    users = load_users()
    uid = str(user_id)
    if uid in users:
        users[uid]["last_voice_text"] = text
        save_users(users)


def clear_history(user_id: int):
    users = load_users()
    uid = str(user_id)
    if uid in users:
        users[uid]["history"] = []
        users[uid]["last_image_prompt"] = None
        users[uid]["last_voice_text"] = None
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
    return True  # Лимит временно отключён


def get_remaining(user_id: int) -> int:
    d = get_user(user_id)
    return max(0, FREE_REQUESTS_LIMIT - d["requests"]) + d.get("bonus_requests", 0)


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

def smart_response(user_id: int, user_prompt: str) -> dict:
    """
    Умный ответ с памятью — анализирует контекст и решает:
    - нужно ли сгенерировать картинку
    - нужно ли озвучить
    - или ответить текстом
    Возвращает {"type": "text"|"image"|"voice", "content": "..."}
    """
    history = get_history(user_id)
    user_data = get_user(user_id)
    last_image = user_data.get("last_image_prompt")
    last_voice = user_data.get("last_voice_text")

    system = (
        "Ты профессиональный AI ассистент и копирайтер на русском языке. "
        "Ты помнишь весь контекст разговора. "
        "Если пользователь просит изменить предыдущую картинку — улучши промпт и верни JSON: {\"type\": \"image\", \"content\": \"новый промпт на английском\"}\n"
        "Если пользователь просит переозвучить или изменить текст для озвучки — верни JSON: {\"type\": \"voice\", \"content\": \"новый текст\"}\n"
        "Если пользователь явно просит нарисовать картинку — верни JSON: {\"type\": \"image\", \"content\": \"промпт на английском\"}\n"
        "Если пользователь явно просит озвучить текст — верни JSON: {\"type\": \"voice\", \"content\": \"текст для озвучки\"}\n"
        "Во всех остальных случаях верни JSON: {\"type\": \"text\", \"content\": \"твой ответ\"}\n"
        "ВАЖНО: возвращай ТОЛЬКО валидный JSON без markdown и без лишнего текста.\n"
        f"Последний промпт для картинки: {last_image or 'нет'}\n"
        f"Последний текст для озвучки: {last_voice or 'нет'}"
    )

    messages = [{"role": "system", "content": system}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_prompt})

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=messages,
        max_tokens=1024
    )
    raw = response.choices[0].message.content.strip()

    try:
        # Чистим от markdown если есть
        clean = raw.replace("```json", "").replace("```", "").strip()
        result = json.loads(clean)
        if result.get("type") not in ["text", "image", "voice"]:
            result = {"type": "text", "content": raw}
    except:
        result = {"type": "text", "content": raw}

    return result


def analyze_photo_ai(user_id: int, image_bytes: bytes, caption: str = "") -> str:
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
    result = response.choices[0].message.content

    # Сохраняем в память
    user_msg = f"[Отправил фото{'с подписью: ' + caption if caption else ''}]"
    add_to_history(user_id, "user", user_msg)
    add_to_history(user_id, "assistant", f"[Описание фото]: {result}")

    return result


def generate_image(prompt: str) -> bytes:
    enhanced = f"{prompt}, high quality, detailed, professional, 4k, sharp focus, beautiful lighting, masterpiece"
    url = f"https://image.pollinations.ai/prompt/{requests.utils.quote(enhanced)}?width=768&height=768&nologo=true&enhance=true&model=flux"
    resp = requests.get(url, timeout=90)
    return resp.content


def generate_voice(text: str) -> io.BytesIO:
    tts = gTTS(text=text, lang="ru")
    audio = io.BytesIO()
    tts.write_to_fp(audio)
    audio.seek(0)
    return audio


def get_reaction(request_type: str, user_prompt: str) -> str:
    """Генерирует живой комментарий к запросу пользователя"""
    try:
        prompt = (
            f"Ты весёлый и живой AI ассистент по имени Qil. "
            f"Пользователь только что попросил тебя: '{user_prompt}'\n"
            f"Тип запроса: {request_type}\n\n"
            f"Напиши короткую живую реакцию (1-2 предложения максимум) — "
            f"как будто ты реально заинтересован и рад помочь. "
            f"Можешь добавить эмодзи. Будь естественным, не занудным. "
            f"Не повторяй запрос дословно — просто отреагируй по-человечески. "
            f"Примеры: 'О, интересная тема! Сейчас сделаю 🔥', "
            f"'Ха, люблю такие задачи 😄 Погнали!', "
            f"'Хм, надо подумать... но уже есть идеи! ✍️'"
        )
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=80
        )
        return response.choices[0].message.content.strip()
    except:
        return ""


def footer_text(user_id: int, is_paid: bool) -> str:
    return ""  # Лимит временно отключён


def start_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💡 Что я умею?", callback_data="what_can_i_do"),
            InlineKeyboardButton("👥 Реферальная ссылка", callback_data="referral"),
        ]
    ])


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
        "Просто напиши мне что нужно — я сам пойму!\n\n"
        f"У тебя {FREE_REQUESTS_LIMIT} бесплатных запросов"
    )
    await update.message.reply_text(text, reply_markup=start_keyboard())


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    d = get_user(update.effective_user.id)
    is_paid = d["is_paid"]
    history_len = len(d.get("history", [])) // 2
    referrals = d.get("referrals", 0)
    bonus = d.get("bonus_requests", 0)

    if is_paid:
        text = f"Премиум — безлимит!\nПамять: {history_len} сообщений\nРефералов: {referrals}"
    else:
        remaining = get_remaining(update.effective_user.id)
        text = (
            f"Осталось запросов: {remaining}\n"
            f"Из них бонусных: {bonus}\n"
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
    is_paid = get_user(user_id)["is_paid"]
    text_input = update.message.text
    text_lower = text_input.lower().strip()

    # Стоп
    if text_lower in STOP_WORDS:
        clear_history(user_id)
        await update.message.reply_text("Память сброшена! Начинаем заново.", reply_markup=start_keyboard())
        return

    # Реферал
    if any(w in text_lower for w in ["реферал", "пригласить", "реферальная ссылка"]):
        bot_info = await context.bot.get_me()
        ref_link = f"https://t.me/{bot_info.username}?start=ref_{user_id}"
        d = get_user(user_id)
        await update.message.reply_text(
            f"👥 Реферальная программа\n\n"
            f"За каждого друга +{REFERRAL_BONUS} бонусных запросов!\n\n"
            f"Твоя ссылка:\n{ref_link}\n\n"
            f"Приглашено: {d.get('referrals', 0)}\n"
            f"Бонусных запросов: {d.get('bonus_requests', 0)}"
        )
        return

    if not check_limit(user_id):
        await update.message.reply_text(
            f"Лимит исчерпан!\n\nПодписка — {SUBSCRIPTION_PRICE}, безлимит!\n{PAYMENT_INFO}"
        )
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        result = smart_response(user_id, text_input)

        if result["type"] == "image":
            prompt = result["content"]
            reaction = get_reaction("картинка", text_input)
            if reaction:
                await update.message.reply_text(reaction)
            await update.message.reply_text("Рисую, подожди 15-30 секунд...")
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="upload_photo")
            image_bytes = generate_image(prompt)
            increment_requests(user_id)
            save_last_image(user_id, prompt)
            add_to_history(user_id, "user", f"[Запрос на картинку]: {text_input}")
            add_to_history(user_id, "assistant", f"[Нарисовал картинку по промпту]: {prompt}")
            caption = footer_text(user_id, is_paid).strip()
            await update.message.reply_photo(photo=image_bytes, caption=caption)

        elif result["type"] == "voice":
            voice_text = result["content"]
            if not voice_text.strip():
                await update.message.reply_text("Напиши текст для озвучки, например:\nОзвучь: Привет!")
                return
            reaction = get_reaction("озвучка", text_input)
            if reaction:
                await update.message.reply_text(reaction)
            audio = generate_voice(voice_text)
            increment_requests(user_id)
            save_last_voice(user_id, voice_text)
            add_to_history(user_id, "user", f"[Запрос на озвучку]: {text_input}")
            add_to_history(user_id, "assistant", f"[Озвучил текст]: {voice_text}")
            await update.message.reply_voice(voice=audio)
            ft = footer_text(user_id, is_paid)
            if ft:
                await update.message.reply_text(ft.strip())

        else:
            reaction = get_reaction("текст", text_input)
            if reaction:
                await update.message.reply_text(reaction)
            text_result = result["content"]
            increment_requests(user_id)
            add_to_history(user_id, "user", text_input)
            add_to_history(user_id, "assistant", text_result)
            ft = footer_text(user_id, is_paid)
            await update.message.reply_text(text_result + ft)

    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await update.message.reply_text("Что-то пошло не так, попробуй ещё раз.")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_paid = get_user(user_id)["is_paid"]

    if not check_limit(user_id):
        await update.message.reply_text(f"Лимит исчерпан!\nПодписка: {SUBSCRIPTION_PRICE}\n{PAYMENT_INFO}")
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        image_bytes = await file.download_as_bytearray()
        caption = update.message.caption or ""
        result = analyze_photo_ai(user_id, bytes(image_bytes), caption)
        increment_requests(user_id)
        ft = footer_text(user_id, is_paid)
        await update.message.reply_text(result + ft)
    except Exception as e:
        logger.error(f"Ошибка анализа фото: {e}")
        await update.message.reply_text("Не удалось проанализировать фото, попробуй ещё раз.")


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "what_can_i_do":
        text = (
            "Вот что я умею:\n\n"
            "✍️ Генерация текстов\n"
            "Напиши пост про кофейный магазин\n"
            "Составь резюме для маркетолога с 3 годами опыта\n"
            "Придумай рекламный текст для доставки еды\n\n"
            "🎨 Генерация картинок\n"
            "Нарисуй кота в космосе\n"
            "Нарисуй горный закат в стиле акварель\n"
            "Сделай картинку минималистичнее — и я изменю предыдущую!\n\n"
            "🔊 Озвучка текста\n"
            "Озвучь: Привет, это мой текст\n"
            "Сделай голос медленнее — изменю предыдущую озвучку!\n\n"
            "📸 Анализ фото\n"
            "Просто отправь фото — опишу что на нём\n"
            "Добавь подпись с вопросом: что здесь за здание?\n\n"
            "🧠 Полная память\n"
            "Я помню весь разговор!\n"
            "После картинки: сделай её темнее\n"
            "После текста: сделай короче\n"
            "После фото: а что на заднем плане?\n\n"
            "👥 Рефералы\n"
            "Напиши: реферальная ссылка\n"
            "За каждого друга +10 запросов!\n\n"
            "Напиши СТОП чтобы сбросить память"
        )
        await query.message.reply_text(text)

    elif query.data == "referral":
        bot_info = await context.bot.get_me()
        ref_link = f"https://t.me/{bot_info.username}?start=ref_{user_id}"
        d = get_user(user_id)
        await query.message.reply_text(
            f"👥 Реферальная программа\n\n"
            f"За каждого друга +{REFERRAL_BONUS} бонусных запросов!\n\n"
            f"Твоя ссылка:\n{ref_link}\n\n"
            f"Приглашено: {d.get('referrals', 0)}\n"
            f"Бонусных запросов: {d.get('bonus_requests', 0)}"
        )


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("clear", clear_command))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Qil bot запущен!")
    app.run_polling()


if __name__ == "__main__":
    main()