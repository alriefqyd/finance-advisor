import sqlite3
import os
from datetime import datetime

DB_PATH = os.getenv("DB_PATH", "data/finance.db")

def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id  TEXT PRIMARY KEY,
            name         TEXT,
            joined_at    TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS transactions (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id  TEXT,
            amount       REAL,
            type         TEXT,        -- income / expense / investment
            category     TEXT,
            description  TEXT,
            date         TEXT DEFAULT (date('now')),
            created_at   TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS budgets (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id  TEXT,
            category     TEXT,
            limit_amount REAL,
            period       TEXT DEFAULT 'monthly',
            UNIQUE(telegram_id, category)
        );

        CREATE TABLE IF NOT EXISTS bills (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id  TEXT,
            name         TEXT,
            amount       REAL,
            due_day      INTEGER,
            is_active    INTEGER DEFAULT 1
        );
    """)
    conn.commit()
    conn.close()

# ── Users ──────────────────────────────────────────────
def upsert_user(telegram_id: str, name: str):
    conn = get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO users(telegram_id, name) VALUES(?,?)",
        (telegram_id, name)
    )
    conn.commit()
    conn.close()

# ── Transactions ───────────────────────────────────────
def add_transaction(telegram_id, amount, type_, category, description, date=None):
    conn = get_conn()
    conn.execute(
        """INSERT INTO transactions(telegram_id, amount, type, category, description, date)
           VALUES(?,?,?,?,?,?)""",
        (telegram_id, amount, type_, category, description, date or datetime.now().strftime("%Y-%m-%d"))
    )
    conn.commit()
    conn.close()

def get_transactions(telegram_id, month=None, limit=50):
    conn = get_conn()
    if month:
        rows = conn.execute(
            """SELECT * FROM transactions WHERE telegram_id=?
               AND strftime('%Y-%m', date)=?
               ORDER BY date DESC LIMIT ?""",
            (telegram_id, month, limit)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM transactions WHERE telegram_id=? ORDER BY date DESC LIMIT ?",
            (telegram_id, limit)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_summary(telegram_id, month):
    """Returns total income, expense, investment for a given YYYY-MM."""
    conn = get_conn()
    rows = conn.execute(
        """SELECT type, category, SUM(amount) as total
           FROM transactions
           WHERE telegram_id=? AND strftime('%Y-%m', date)=?
           GROUP BY type, category""",
        (telegram_id, month)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ── Budgets ────────────────────────────────────────────
def set_budget(telegram_id, category, limit_amount):
    conn = get_conn()
    conn.execute(
        """INSERT INTO budgets(telegram_id, category, limit_amount)
           VALUES(?,?,?)
           ON CONFLICT(telegram_id, category)
           DO UPDATE SET limit_amount=excluded.limit_amount""",
        (telegram_id, category, limit_amount)
    )
    conn.commit()
    conn.close()

def get_budgets(telegram_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM budgets WHERE telegram_id=?", (telegram_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_budget_usage(telegram_id, month):
    """Compare spending vs budget per category for a given month."""
    conn = get_conn()
    rows = conn.execute(
        """SELECT b.category, b.limit_amount,
                  COALESCE(SUM(t.amount), 0) as spent
           FROM budgets b
           LEFT JOIN transactions t
             ON t.telegram_id = b.telegram_id
             AND t.category   = b.category
             AND t.type       = 'expense'
             AND strftime('%Y-%m', t.date) = ?
           WHERE b.telegram_id = ?
           GROUP BY b.category""",
        (month, telegram_id)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ── Bills ──────────────────────────────────────────────
def add_bill(telegram_id, name, amount, due_day):
    conn = get_conn()
    conn.execute(
        "INSERT INTO bills(telegram_id, name, amount, due_day) VALUES(?,?,?,?)",
        (telegram_id, name, amount, due_day)
    )
    conn.commit()
    conn.close()

def get_bills(telegram_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM bills WHERE telegram_id=? AND is_active=1 ORDER BY due_day",
        (telegram_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
