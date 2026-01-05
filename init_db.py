import sqlite3

conn = sqlite3.connect("users.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    last_date TEXT,
    card_id INTEGER,
    is_paid INTEGER DEFAULT 0
)
""")

conn.commit()
conn.close()

print("✅ Таблиця users створена")
