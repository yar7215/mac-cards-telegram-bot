import json
import random
import asyncio
import time
import os
import psycopg2
from psycopg2.extras import RealDictCursor

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# ---------- CONFIG ----------
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_CHAT_ID = 853539093

# ---------- DATABASE ----------
conn = psycopg2.connect(DATABASE_URL, sslmode="require")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS customers (
    id SERIAL PRIMARY KEY,
    telegram_id BIGINT UNIQUE,
    username TEXT,
    name TEXT,
    phone TEXT,
    created_at BIGINT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS daily_cards (
    telegram_id BIGINT PRIMARY KEY,
    last_card_time BIGINT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS card_history (
    telegram_id BIGINT,
    card_id TEXT,
    shown_at BIGINT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS bot_users (
    telegram_id BIGINT PRIMARY KEY,
    username TEXT,
    first_seen BIGINT
)
""")

conn.commit()

print("✅ PostgreSQL connected & tables ready")

# ---------- LOAD CARDS ----------
with open("cards.json", "r", encoding="utf-8") as f:
    cards = json.load(f)

user_cards = {}
user_steps = {}

def get_card_keyboard(extra_buttons=None):
    keyboard = [[InlineKeyboardButton("🎴 Отримати карту дня", callback_data="get_card")]]

    if extra_buttons:
        keyboard.insert(0, extra_buttons)

    return InlineKeyboardMarkup(keyboard)

# ---------- START ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    now = int(time.time())

    cursor.execute(
        "SELECT telegram_id FROM bot_users WHERE telegram_id = %s",
        (user.id,)
    )
    exists = cursor.fetchone()

    keyboard = [[InlineKeyboardButton("🎴 Отримати карту дня", callback_data="get_card")]]

    if not exists:
        cursor.execute(
            "INSERT INTO bot_users (telegram_id, username, first_seen) VALUES (%s, %s, %s)",
            (user.id, user.username, now)
        )
        conn.commit()

        text = (
            "🌿 Вітаю тебе у просторі МАК-карт\n\n"
            "Цей бот допоможе тобі щодня отримувати\n"
            "✨ одну карту дня — символ або підказку,\n"
            "яка може відгукнутися саме тобі сьогодні.\n\n"
            "🔮 Як це працює:\n"
            "• щодня ти можеш отримати одну карту\n"
            "• подивитись її значення\n"
            "• за бажанням — записатися на МАК-сесію\n\n"
            "🃏 Просто натисни кнопку нижче\n"
            "і дозволь карті знайти тебе ✨"
        )
    else:
        text = "🌿 Радий(а) тебе знову бачити 💛"

    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
async def show_card_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("🎴 Отримати карту дня", callback_data="get_card")]]

    await update.message.reply_text(
        "🌿 Натисни кнопку нижче, щоб отримати карту дня ✨",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ---------- GET CARD ----------
async def get_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    now = int(time.time())

    cursor.execute(
        "SELECT last_card_time FROM daily_cards WHERE telegram_id = %s",
        (user_id,)
    )
    row = cursor.fetchone()

    if row and now - row[0] < 86400:
        hours_left = int((86400 - (now - row[0])) / 3600)

        keyboard = [[
            InlineKeyboardButton("🎴 Отримати карту дня", callback_data="get_card")
        ]]

        await query.message.reply_text(
            f"🌿 Ти вже отримав(ла) свою сьогоднішню карту.\n"
            f"Повертайся приблизно через {hours_left} год 💛",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    limit_time = now - 30 * 86400
    cursor.execute(
        "SELECT card_id FROM card_history WHERE telegram_id = %s AND shown_at > %s",
        (user_id, limit_time)
    )
    used_cards = {str(r[0]) for r in cursor.fetchall()}
    available_cards = [c for c in cards if str(c["id"]) not in used_cards]

    card = random.choice(available_cards)
    user_cards[user_id] = card

    cursor.execute("""
        INSERT INTO daily_cards (telegram_id, last_card_time)
        VALUES (%s, %s)
        ON CONFLICT (telegram_id)
        DO UPDATE SET last_card_time = EXCLUDED.last_card_time
    """, (user_id, now))

    cursor.execute(
        "INSERT INTO card_history (telegram_id, card_id, shown_at) VALUES (%s, %s, %s)",
        (user_id, card["id"], now)
    )

    conn.commit()

    await query.message.reply_photo(
        photo=open(card["image"], "rb"),
        caption="🃏 *Подумай, що ця карта значить саме для тебе?*",
        parse_mode="Markdown"
    )

    await asyncio.sleep(1)

    keyboard = [[InlineKeyboardButton("📖 Дізнатися опис", callback_data="show_full_card")]]
    await query.message.reply_text(
        "✨ Коли будеш готовий — натисни кнопку",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ---------- FULL CARD ----------
async def show_full_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    card = user_cards.get(query.from_user.id)
    if not card:
        await query.message.reply_text("Спочатку отримай карту 🌿")
        return

    keyboard = get_card_keyboard(
    [InlineKeyboardButton("💫 Хочу на МАК-сесію", callback_data="want_session")]
    )

    await query.message.reply_text(
        f"🔮 *{card['title']}*\n\n{card['text']}",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

# ---------- WANT SESSION ----------
async def want_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = query.from_user

    cursor.execute(
        "SELECT name, phone FROM customers WHERE telegram_id = %s",
        (user.id,)
    )
    row = cursor.fetchone()

    if row:
        user_steps[user.id] = {"step": "confirm", "name": row[0], "phone": row[1]}
        await query.message.reply_text("Хочеш записатися ще раз? Напиши «так» або «ні»")
        return

    user_steps[user.id] = {"step": "name"}
    await query.message.reply_text("💬 Напиши своє імʼя")

# ---------- HANDLE TEXT ----------
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in user_steps:
        await show_card_button(update, context)
        return

    step = user_steps[user_id]["step"]

    if step == "name":
        user_steps[user_id]["name"] = update.message.text
        user_steps[user_id]["step"] = "phone"
        await update.message.reply_text("📞 Введи номер телефону")

    elif step == "confirm":
        if update.message.text.lower() == "так":
            user_steps[user_id]["step"] = "phone"
            await update.message.reply_text("📞 Введи номер телефону")
        else:
            user_steps.pop(user_id)
            await update.message.reply_text("🌿 Добре")

    elif step == "phone":
        name = user_steps[user_id]["name"]
        phone = update.message.text
        user = update.message.from_user

        cursor.execute("""
            INSERT INTO customers (telegram_id, username, name, phone, created_at)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (telegram_id)
            DO UPDATE SET phone = EXCLUDED.phone, created_at = EXCLUDED.created_at
        """, (user.id, user.username, name, phone, int(time.time())))

        conn.commit()
        user_steps.pop(user_id)

        await context.bot.send_message(
            ADMIN_CHAT_ID,
            f"🆕 Нова заявка\n\n👤 {name}\n📞 {phone}\n🆔 {user.id}"
        )

        await update.message.reply_text(
            "✨ Дякую! Ми звʼяжемось з тобою 💛",
            reply_markup=get_card_keyboard()
        )

# ---------- MAIN ----------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(get_card, pattern="get_card"))
    app.add_handler(CallbackQueryHandler(show_full_card, pattern="show_full_card"))
    app.add_handler(CallbackQueryHandler(want_session, pattern="want_session"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("🤖 Бот запущено")
    app.run_polling()

if __name__ == "__main__":
    main()
