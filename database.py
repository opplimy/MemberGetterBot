import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "membergetter.db"


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = connect()

    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        diamonds INTEGER NOT NULL DEFAULT 0,
        referrals INTEGER NOT NULL DEFAULT 0,
        referred_by INTEGER,
        daily_reward_date TEXT,
        start_bonus_received INTEGER NOT NULL DEFAULT 0,
        is_banned INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS channels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        channel_id TEXT NOT NULL UNIQUE,
        username TEXT,
        title TEXT,
        description TEXT,
        reward INTEGER NOT NULL DEFAULT 2,
        active INTEGER NOT NULL DEFAULT 1,
        added_by INTEGER,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS channel_tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        channel_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        rewarded INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(channel_id, user_id)
    );

    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        amount INTEGER NOT NULL,
        type TEXT NOT NULL,
        description TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS referrals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        inviter_id INTEGER NOT NULL,
        invited_id INTEGER NOT NULL UNIQUE,
        rewarded INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        channel_id TEXT,
        members INTEGER NOT NULL,
        cost INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        mission_message_id INTEGER,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS mission_tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL,
        channel_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        rewarded INTEGER NOT NULL DEFAULT 0,
        joined_at TEXT,
        retention_completed INTEGER NOT NULL DEFAULT 0,
        penalty_applied INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(order_id, user_id)
    );
    """)


    # Existing database migration
    order_columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(orders)").fetchall()
    }

    if "mission_message_id" not in order_columns:
        conn.execute(
            "ALTER TABLE orders ADD COLUMN mission_message_id INTEGER"
        )

    task_columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(mission_tasks)").fetchall()
    }

    if "joined_at" not in task_columns:
        conn.execute(
            "ALTER TABLE mission_tasks ADD COLUMN joined_at TEXT"
        )

    if "retention_completed" not in task_columns:
        conn.execute(
            "ALTER TABLE mission_tasks "
            "ADD COLUMN retention_completed INTEGER NOT NULL DEFAULT 0"
        )

    if "penalty_applied" not in task_columns:
        conn.execute(
            "ALTER TABLE mission_tasks "
            "ADD COLUMN penalty_applied INTEGER NOT NULL DEFAULT 0"
        )

    conn.commit()

    defaults = {
        "start_bonus": "10",
        "daily_reward": "5",
        "referral_reward": "3",
        "channel_join_reward": "2",
        "price_5": "10",
        "price_10": "20",
        "price_15": "30",
        "price_20": "35",
        "price_60": "80",
        "price_100": "120",
    }

    for key, value in defaults.items():
        conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            (key, value)
        )

    conn.commit()
    conn.close()


def get_setting(key, default=None):
    conn = connect()
    row = conn.execute(
        "SELECT value FROM settings WHERE key = ?",
        (key,)
    ).fetchone()
    conn.close()

    return row["value"] if row else default


def set_setting(key, value):
    conn = connect()
    conn.execute(
        """
        INSERT INTO settings (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, str(value))
    )
    conn.commit()
    conn.close()


def add_diamonds(user_id, amount, transaction_type, description=""):
    conn = connect()

    conn.execute(
        "UPDATE users SET diamonds = diamonds + ? WHERE user_id = ?",
        (amount, user_id)
    )

    conn.execute(
        """
        INSERT INTO transactions
        (user_id, amount, type, description)
        VALUES (?, ?, ?, ?)
        """,
        (user_id, amount, transaction_type, description)
    )

    conn.commit()
    conn.close()


def get_balance(user_id):
    conn = connect()
    row = conn.execute(
        "SELECT diamonds FROM users WHERE user_id = ?",
        (user_id,)
    ).fetchone()
    conn.close()

    return row["diamonds"] if row else 0


if __name__ == "__main__":
    init_db()
    print("✅ Database initialized")
