"""
Qil — AI Telegram бот
Функции: тексты, картинки, озвучка, анализ фото, перевод, редактирование, шаблоны, реферальная система
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
REFERRAL_BONUS = 10  # Бонусных запросов за реферала
SUBSCRIPTION_PRICE = "100 руб/месяц"
PAYMENT_INFO = "Для оплаты напишите @livix95"
MAX_MEMORY = 10
STOP_WORDS = ["стоп", "назад", "меню", "хватит", "stop", "back", "старт"]
# ============================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

client = Groq(api_key=GROQ_API_KEY)
USERS_FILE = "users_data.json"


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
    # Сначала тратим бонусные
    if user.get("bonus_requests", 0) > 0:
        users[uid]["bonus_requests"] -= 1
    else:
        users[uid]["requests"] = user.get("requests", 0) + 1
    save_users(users)


def add_bonus(user_id: int, amount: int):
    users = load_users()
    uid = str(user_id)
    if uid in users:
        users[uid]["bonus_requests"] = users[uid].get("bonus_requests", 0) + amount
        save_users(users)


def set_paid(user_id: int):
    users = load_users()
    uid = str(user_id)
    if uid in users:
        users[uid]["is_paid"] = True
        save_users(users)


def check_limit(user_id: int) -> bool:
    user_data = get_user(user_id)
    if user_data["is_paid"]:
        return True
    total_free = FREE_REQUESTS_LIMIT + user_data.get("bonus_requests", 0)
    return user_data["requests"] < FREE_REQUESTS_LIMIT or user_data.get("bonus_requests", 0) > 0


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

def ai_request(messages: list) -> str:
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=messages,
        max_tokens=1024
    )
    return response.choices[0].message.content


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
    result = ai_request(messages)
    add_to_history(user_id, "user", user_prompt)
    add_to_history(user_id, "assistant", result)
    return result


def translate_text(text: str, target_lang: str = "английский") -> str:
    messages = [
        {"role": "system", "content": "Ты профессиональный переводчик. Переводи точно и естественно. Возвращай только перевод без пояснений."},
        {"role": "user", "content": f"Переведи на {target_lang}:\n\n{text}"}
    ]
    return ai_request(messages)


def edit_text(text: str, instruction: str) -> str:
    messages = [
        {"role": "system", "content": "Ты профессиональный редактор текстов. Улучшай тексты согласно инструкции. Не используй markdown форматирование."},
        {"role": "user", "content": f"Инструкция: {instruction}\n\nТекст:\n{text}"}
    ]
    return ai_request(messages)


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


# ── Клавиатуры ───────────────────────────────────────────────

def main_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✍️ Текст", callback_data="mode_text"),
            InlineKeyboardButton("🎨 Картинка", callback_data="mode_image"),
            InlineKeyboardButton("🔊 Озвучка", callback_data="mode_voice"),
        ],
        [
            InlineKeyboardButton("📸 Анализ фото", callback_data="mode_photo"),
            InlineKeyboardButton("🌍 Перевод", callback_data="mode_translate"),
            InlineKeyboardButton("📝 Редактор", callback_data="mode_edit"),
        ],
        [
            InlineKeyboardButton("💬 Шаблоны", callback_data="templates"),
            InlineKeyboardButton("👥 Рефералы", callback_data="referral"),
            InlineKeyboardButton("💡 Примеры", callback_data="examples"),
        ]
    ])


def limit_exceeded_markup():
    return InlineKeyboardMarkup([[InlineKeyboardButton("Оформить подписку", callback_data="subscribe")]])


def templates_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 Пост в Instagram", callback_data="tpl_instagram")],
        [InlineKeyboardButton("💼 Пост для бизнеса", callback_data="tpl_business")],
        [InlineKeyboardButton("🛍 Описание товара", callback_data="tpl_product")],
        [InlineKeyboardButton("📣 Рекламный текст", callback_data="tpl_ads")],
        [InlineKeyboardButton("✉️ Деловое письмо", callback_data="tpl_email")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_menu")],
    ])


# ── Хендлеры ────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    get_user(user.id)

    # Реферальная система
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
        "Я Qil — твой AI ассистент\n\n"
        "Что умею:\n"
        "✍️ Генерировать тексты и посты\n"
        "🎨 Рисовать изображения\n"
        "🔊 Озвучивать тексты\n"
        "📸 Анализировать фото\n"
        "🌍 Переводить на любой язык\n"
        "📝 Редактировать твои тексты\n"
        "💬 Готовые шаблоны постов\n\n"
        f"У тебя {FREE_REQUESTS_LIMIT} бесплатных запросов\n\n"
        "Напиши СТОП или НАЗАД чтобы вернуться в меню"
    )
    await update.message.reply_text(text, reply_markup=main_keyboard())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Как пользоваться Qil:\n\n"
        "1. Выбери режим кнопками\n"
        "2. Напиши запрос\n"
        "3. Напиши СТОП чтобы вернуться в меню\n\n"
        "Умные команды:\n"
        "- Напиши нарисуй/сгенерируй → режим картинки\n"
        "- Напиши озвучь/прочитай → режим озвучки\n"
        "- Напиши переведи → режим перевода\n"
        "- Напиши улучши/отредактируй → режим редактора\n\n"
        "Команды:\n"
        "/start — главное меню\n"
        "/status — статистика\n"
        "/referral — реферальная ссылка\n"
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
        "voice": "🔊 Озвучка", "photo": "📸 Анализ фото",
        "translate": "🌍 Перевод", "edit": "📝 Редактор"
    }

    if is_paid:
        text = (
            f"У тебя премиум-доступ — безлимитные запросы!\n"
            f"Текущий режим: {modes.get(mode)}\n"
            f"Сообщений в памяти: {history_len}\n"
            f"Рефералов: {referrals}"
        )
    else:
        remaining = get_remaining(update.effective_user.id)
        text = (
            f"Твоя статистика:\n\n"
            f"Осталось запросов: {remaining}\n"
            f"Из них бонусных: {bonus}\n"
            f"Текущий режим: {modes.get(mode)}\n"
            f"Сообщений в памяти: {history_len}\n"
            f"Рефералов приглашено: {referrals}\n"
        )
        if remaining == 0:
            text += f"\nЛимит исчерпан!\nПодписка: {SUBSCRIPTION_PRICE}\n{PAYMENT_INFO}"

    await update.message.reply_text(text)


async def referral_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user(user_id)
    referrals = user_data.get("referrals", 0)
    bonus = user_data.get("bonus_requests", 0)
    bot = await context.bot.get_me()
    ref_link = f"https://t.me/{bot.username}?start=ref_{user_id}"

    text = (
        f"👥 Твоя реферальная программа\n\n"
        f"За каждого приглашённого друга ты получаешь +{REFERRAL_BONUS} бонусных запросов!\n\n"
        f"Твоя ссылка:\n{ref_link}\n\n"
        f"Приглашено друзей: {referrals}\n"
        f"Бонусных запросов: {bonus}"
    )
    await update.message.reply_text(text)


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_history(update.effective_user.id)
    await update.message.reply_text("🧹 Память очищена!")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user(user_id)
    mode = user_data.get("mode", "text")
    is_paid = user_data["is_paid"]
    text_input = update.message.text
    text_lower = text_input.lower().strip()

    # Стоп-слова
    if text_lower in STOP_WORDS:
        set_mode(user_id, "text")
        await update.message.reply_text("Главное меню:", reply_markup=main_keyboard())
        return

    # Умные ключевые слова для переключения режима
    if any(w in text_lower for w in ["нарисуй", "сгенерируй картинку", "создай изображение", "нарисуй мне"]):
        set_mode(user_id, "image")
        mode = "image"
    elif any(w in text_lower for w in ["озвучь", "прочитай вслух", "голосом"]):
        set_mode(user_id, "voice")
        mode = "voice"
    elif any(w in text_lower for w in ["переведи", "переведи на", "перевод"]):
        set_mode(user_id, "translate")
        mode = "translate"
    elif any(w in text_lower for w in ["улучши", "отредактируй", "исправь текст", "сделай лучше"]):
        set_mode(user_id, "edit")
        mode = "edit"

    if not check_limit(user_id):
        await update.message.reply_text(
            f"Бесплатный лимит исчерпан!\n\nПодписка — {SUBSCRIPTION_PRICE}, безлимит!\n{PAYMENT_INFO}",
            reply_markup=limit_exceeded_markup()
        )
        return

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="upload_photo" if mode == "image" else "typing"
    )

    try:
        result = None

        if mode == "text":
            result = generate_text(user_id, text_input)

        elif mode == "image":
            await update.message.reply_text("Рисую, подожди 15-30 секунд...")
            image_bytes = generate_image(text_input)
            increment_requests(user_id)
            remaining = get_remaining(user_id)
            caption = f"Осталось запросов: {remaining}" if not is_paid else ""
            await update.message.reply_photo(photo=image_bytes, caption=caption)
            return

        elif mode == "voice":
            audio = generate_voice(text_input)
            increment_requests(user_id)
            remaining = get_remaining(user_id)
            await update.message.reply_voice(voice=audio)
            if not is_paid:
                await update.message.reply_text(f"Осталось запросов: {remaining}")
            return

        elif mode == "translate":
            # Определяем язык из запроса
            target = "английский"
            for lang in ["английский", "немецкий", "французский", "испанский", "китайский", "японский", "турецкий", "арабский"]:
                if lang in text_lower:
                    target = lang
                    break
            result = translate_text(text_input, target)

        elif mode == "edit":
            parts = text_input.split("\n", 1)
            if len(parts) == 2:
                result = edit_text(parts[1], parts[0])
            else:
                result = edit_text(text_input, "улучши текст, сделай его грамотнее и интереснее")

        elif mode == "photo":
            await update.message.reply_text("Отправь фото! Можешь добавить подпись с вопросом.")
            return

        if result:
            increment_requests(user_id)
            remaining = get_remaining(user_id)
            footer = ""
            if not is_paid:
                footer = f"\n\nОсталось запросов: {remaining}" if remaining > 0 else f"\n\nЛимит исчерпан!\nПодписка: {SUBSCRIPTION_PRICE}\n{PAYMENT_INFO}"
            await update.message.reply_text(result + footer)

    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await update.message.reply_text("Что-то пошло не так, попробуй ещё раз.")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_paid = get_user(user_id)["is_paid"]

    if not check_limit(user_id):
        await update.message.reply_text(
            f"Лимит исчерпан!\nПодписка: {SUBSCRIPTION_PRICE}\n{PAYMENT_INFO}",
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
        remaining = get_remaining(user_id)
        footer = f"\n\nОсталось запросов: {remaining}" if not is_paid else ""
        await update.message.reply_text(result + footer)
    except Exception as e:
        logger.error(f"Ошибка анализа фото: {e}")
        await update.message.reply_text("Не удалось проанализировать фото, попробуй ещё раз.")


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    # Режимы
    mode_messages = {
        "mode_text": ("text", "✍️ Режим: Текст\n\nНапиши что нужно написать!\nСТОП — вернуться в меню."),
        "mode_image": ("image", "🎨 Режим: Картинка\n\nОпиши что нарисовать!\nСТОП — вернуться в меню."),
        "mode_voice": ("voice", "🔊 Режим: Озвучка\n\nОтправь любой текст — озвучу!\nСТОП — вернуться в меню."),
        "mode_photo": ("photo", "📸 Режим: Анализ фото\n\nОтправь фото с вопросом в подписи!\nСТОП — вернуться в меню."),
        "mode_translate": ("translate", "🌍 Режим: Перевод\n\nНапиши текст — переведу на английский.\nИли укажи язык: переведи на немецкий: [текст]\nСТОП — вернуться в меню."),
        "mode_edit": ("edit", "📝 Режим: Редактор\n\nНапиши инструкцию на первой строке, текст на второй:\n\nСделай короче\nТвой текст здесь...\n\nСТОП — вернуться в меню."),
    }

    if query.data in mode_messages:
        mode, msg = mode_messages[query.data]
        set_mode(user_id, mode)
        await query.message.reply_text(msg)
        return

    if query.data == "back_menu":
        await query.message.reply_text("Главное меню:", reply_markup=main_keyboard())

    elif query.data == "clear_memory":
        clear_history(user_id)
        await query.message.reply_text("🧹 Память очищена!")

    elif query.data == "referral":
        user_data = get_user(user_id)
        bot = await context.bot.get_me()
        ref_link = f"https://t.me/{bot.username}?start=ref_{user_id}"
        text = (
            f"👥 Реферальная программа\n\n"
            f"За каждого друга +{REFERRAL_BONUS} бонусных запросов!\n\n"
            f"Твоя ссылка:\n{ref_link}\n\n"
            f"Приглашено: {user_data.get('referrals', 0)}\n"
            f"Бонусных запросов: {user_data.get('bonus_requests', 0)}"
        )
        await query.message.reply_text(text)

    elif query.data == "templates":
        await query.message.reply_text("💬 Выбери шаблон:", reply_markup=templates_keyboard())

    elif query.data.startswith("tpl_"):
        templates = {
            "tpl_instagram": "Напиши вовлекающий пост для Instagram про [тему]. Добавь эмодзи и призыв к действию.",
            "tpl_business": "Напиши деловой пост для компании про [тему]. Стиль: профессиональный, убедительный.",
            "tpl_product": "Напиши продающее описание товара [название]. Укажи преимущества и выгоды для покупателя.",
            "tpl_ads": "Напиши цепляющий рекламный текст для [продукт/услуга]. Заголовок + текст + призыв к действию.",
            "tpl_email": "Напиши деловое письмо на тему [тема]. Стиль вежливый и профессиональный.",
        }
        template_text = templates.get(query.data, "")
        set_mode(user_id, "text")
        await query.message.reply_text(
            f"Скопируй шаблон и замени [скобки] на своё:\n\n{template_text}\n\nСТОП — вернуться в меню."
        )

    elif query.data == "examples":
        text = (
            "Примеры запросов:\n\n"
            "✍️ Текст:\n"
            "- Напиши пост про кофейный магазин\n\n"
            "🎨 Картинка:\n"
            "- Нарисуй кота в космосе\n\n"
            "🌍 Перевод:\n"
            "- Переведи на английский: Привет мир\n\n"
            "📝 Редактор:\n"
            "- Сделай короче\n"
            "- [твой текст]\n\n"
            "📸 Фото:\n"
            "- Отправь фото с подписью: что здесь?\n\n"
            "Напиши СТОП чтобы вернуться в меню"
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
    app.add_handler(CommandHandler("referral", referral_command))
    app.add_handler(CommandHandler("clear", clear_command))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Qil bot запущен!")
    app.run_polling()


if __name__ == "__main__":
    main()
