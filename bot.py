import json
import random
import asyncio
import sqlite3
import time
import init_db
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_CHAT_ID = 853539093

# ---------- DATABASE ----------
conn = sqlite3.connect("users.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER,
    username TEXT,
    name TEXT,
    phone TEXT,
    created_at INTEGER
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS daily_cards (
    telegram_id INTEGER PRIMARY KEY,
    last_card_time INTEGER
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS card_history (
    telegram_id INTEGER,
    card_id TEXT,
    shown_at INTEGER
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS bot_users (
    telegram_id INTEGER PRIMARY KEY,
    username TEXT,
    first_seen INTEGER
)
""")

conn.commit()

# ---------- LOAD CARDS ----------
with open("cards.json", "r", encoding="utf-8") as f:
    cards = json.load(f)

user_cards = {}
user_steps = {}

# ---------- START / CARD ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    now = int(time.time())

    cursor.execute(
        "SELECT telegram_id FROM bot_users WHERE telegram_id = ?",
        (user.id,)
    )
    exists = cursor.fetchone()

    keyboard = [[InlineKeyboardButton("🎴 Отримати карту дня", callback_data="get_card")]]

    if not exists:
        # Перший вхід
        cursor.execute(
            "INSERT INTO bot_users (telegram_id, username, first_seen) VALUES (?, ?, ?)",
            (user.id, user.username, now)
        )
        conn.commit()

        await update.message.reply_text(
            "🌿 Вітаю тебе у просторі МАК-карт\n\n"
            "Цей бот допоможе тобі щодня отримувати\n"
            "✨ одну карту дня — символ або підказку,\n"
            "яка може відгукнутися саме тобі сьогодні.\n\n"
            "🔮 Як це працює:\n"
            "• щодня ти можеш отримати одну карту\n"
            "• подивитись її значення\n"
            "• за бажанням — записатися на МАК-сесію\n\n"
            "🃏 Просто натисни кнопку нижче\n"
            "і дозволь карті знайти тебе ✨",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        # Повторний вхід
        await update.message.reply_text(
            "🌿 Радий(а) тебе знову бачити\n\n"
            "Натисни кнопку нижче, щоб отримати карту дня ✨",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def get_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    now = int(time.time())

    # --- 24 години ---
    cursor.execute(
        "SELECT last_card_time FROM daily_cards WHERE telegram_id = ?",
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

    # --- карти за 30 днів ---
    limit_time = now - (30 * 86400)
    cursor.execute(
        """
        SELECT card_id FROM card_history
        WHERE telegram_id = ? AND shown_at > ?
        """,
        (user_id, limit_time)
    )
    used_cards = {row[0] for row in cursor.fetchall()}

    available_cards = [c for c in cards if c["id"] not in used_cards]

    if not available_cards:
        available_cards = cards  # fallback

    card = random.choice(available_cards)
    user_cards[user_id] = card

    # --- запис часу ---
    cursor.execute("""
        INSERT INTO daily_cards (telegram_id, last_card_time)
        VALUES (?, ?)
        ON CONFLICT(telegram_id)
        DO UPDATE SET last_card_time = excluded.last_card_time
    """, (user_id, now))

    cursor.execute("""
        INSERT INTO card_history (telegram_id, card_id, shown_at)
        VALUES (?, ?, ?)
    """, (user_id, card["id"], now))

    conn.commit()

    await query.message.reply_photo(
        photo=open(card["image"], "rb"),
        caption="🃏 *Подумай, що ця карта значить саме для тебе?*",
        parse_mode="Markdown"
    )

    await asyncio.sleep(1)

    keyboard = [[
        InlineKeyboardButton("📖 Дізнатися повний опис карти", callback_data="show_full_card")
    ]]

    await query.message.reply_text(
        "✨ Коли будеш готовий(а) — натисни кнопку нижче.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ---------- FULL CARD ----------
async def show_full_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    card = user_cards.get(query.from_user.id)

    if not card:
        await query.message.reply_text("Спочатку отримай карту дня 🌿")
        return

    keyboard = [[InlineKeyboardButton("💫 Хочу на МАК сесію", callback_data="want_session")]]

    await query.message.reply_text(
        f"🔮 *{card['title']}*\n\n{card['text']}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ---------- WANT SESSION ----------
async def want_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = query.from_user

    cursor.execute(
        "SELECT name, phone FROM customers WHERE telegram_id = ?",
        (user.id,)
    )
    row = cursor.fetchone()

    if row:
        user_steps[user.id] = {
            "step": "confirm",
            "name": row[0],
            "phone": row[1]
        }
        await query.message.reply_text(
            "💫 Ти вже залишав(ла) заявку раніше.\n"
            "Хочеш записатися на МАК-сесію ще раз?\n\n"
            "Напиши «так» або «ні»"
        )
        return

    user_steps[user.id] = {"step": "name"}
    await query.message.reply_text("💬 Напиши, будь ласка, своє імʼя")

# ---------- HANDLE TEXT ----------
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    if user_id not in user_steps:
        return

    step = user_steps[user_id]["step"]

    if step == "name":
        user_steps[user_id]["name"] = update.message.text
        user_steps[user_id]["step"] = "phone"
        await update.message.reply_text("📞 Напиши контактний номер телефону")

    elif step == "confirm":
        text = update.message.text.lower().strip()
        if text == "так":
            user_steps[user_id]["step"] = "phone"
            await update.message.reply_text("📞 Напиши контактний номер телефону")
        else:
            user_steps.pop(user_id)
            await update.message.reply_text("🌿 Добре, якщо що — я поруч")

    elif step == "phone":
        name = user_steps[user_id]["name"]
        phone = update.message.text
        user = update.message.from_user

        cursor.execute(
            "SELECT id FROM customers WHERE telegram_id = ?",
            (user.id,)
        )
        exists = cursor.fetchone()

        if exists:
            cursor.execute("""
                UPDATE customers
                SET phone = ?, created_at = ?
                WHERE telegram_id = ?
            """, (phone, int(time.time()), user.id))
        else:
            cursor.execute("""
                INSERT INTO customers (telegram_id, username, name, phone, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (user.id, user.username, name, phone, int(time.time())))

        conn.commit()
        user_steps.pop(user_id)

        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=(
                "🆕 Нова заявка на МАК-сесію\n\n"
                f"👤 Імʼя: {name}\n"
                f"📞 Телефон: {phone}\n"
                f"🆔 Telegram ID: {user.id}\n"
                f"🔗 Username: @{user.username if user.username else 'немає'}"
            )
        )

        await update.message.reply_text(
            "✨ Дякую!\n\nМи отримали твою заявку і звʼяжемось з тобою найближчим часом 💛"
        )

# ---------- ERROR ----------
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print("🔥 ERROR:", context.error)

# ---------- REMINDER ----------
async def check_reminder(context: ContextTypes.DEFAULT_TYPE):
    now = int(time.time())

    cursor.execute("SELECT telegram_id, last_card_time FROM daily_cards")
    rows = cursor.fetchall()

    for user_id, last_time in rows:
        if 90000 <= now - last_time < 91000:
            await context.bot.send_message(
                chat_id=user_id,
                text="🌿 Тобі вже доступна нова карта дня.\n"
                     "Можеш отримати її прямо зараз ✨"
            )

#-------------MAIN------------#
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("card", start))

    app.add_handler(CallbackQueryHandler(get_card, pattern="get_card"))
    app.add_handler(CallbackQueryHandler(show_full_card, pattern="show_full_card"))
    app.add_handler(CallbackQueryHandler(want_session, pattern="want_session"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    app.add_error_handler(error_handler)

    # ⏰ REMINDER JOB > це для встановення нагадування
    #app.job_queue.run_repeating(
    #    check_reminder,
    #    interval=3600,   # раз на годину
    #    first=10         # старт через 10 секунд
    #)

    print("🤖 Бот запущено")
    app.run_polling()


if __name__ == "__main__":
    main()
