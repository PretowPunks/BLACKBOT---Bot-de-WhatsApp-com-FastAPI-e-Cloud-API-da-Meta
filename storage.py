import os
import sqlite3
from datetime import datetime

# Permite persistência futura no Render (Disk) sem quebrar local
DB_PATH = os.getenv("DB_PATH", "bot.db")


def get_conn():
    # check_same_thread=False para uso em FastAPI/Uvicorn (threads diferentes)
    return sqlite3.connect(DB_PATH, check_same_thread=False)


# ============================================================
# INIT DB
# ============================================================
def init_db():
    with get_conn() as conn:
        c = conn.cursor()

        c.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                wa_id TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                data_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                pause_bot INTEGER DEFAULT 0
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wa_id TEXT NOT NULL,
                data TEXT,
                tipo TEXT,
                qtd TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wa_id TEXT NOT NULL,
                message TEXT NOT NULL,
                reason TEXT,
                created_at TEXT NOT NULL
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS processed_messages (
                message_id TEXT PRIMARY KEY,
                wa_id TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wa_id TEXT NOT NULL,
                direction TEXT NOT NULL,     -- 'in' | 'out-bot' | 'out-human'
                msg_type TEXT NOT NULL,      -- 'text', 'image', etc.
                body TEXT,
                wa_message_id TEXT,
                created_at TEXT NOT NULL
            )
        """)

        conn.commit()


# ============================================================
# IDEMPOTÊNCIA
# ============================================================
def mark_processed(message_id: str, wa_id: str) -> bool:
    """
    Retorna True se for novo (inseriu), False se já existia (não processar de novo).
    """
    with get_conn() as conn:
        c = conn.cursor()
        try:
            c.execute(
                "INSERT INTO processed_messages(message_id, wa_id, created_at) VALUES (?,?,?)",
                (message_id, wa_id, datetime.utcnow().isoformat())
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False


# ============================================================
# SESSÕES (FSM)
# ============================================================
def load_session_full(wa_id: str):
    """
    Retorna (state, data_json, updated_at) da sessão; None se não existir.
    """
    with get_conn() as conn:
        c = conn.cursor()
        return c.execute(
            "SELECT state, data_json, updated_at FROM sessions WHERE wa_id=?",
            (wa_id,)
        ).fetchone()


def save_session(wa_id: str, state: str, data_json: str):
    """
    Upsert da sessão (state, data_json, updated_at).
    """
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO sessions(wa_id, state, data_json, updated_at)
            VALUES(?,?,?,?)
            ON CONFLICT(wa_id) DO UPDATE SET
              state=excluded.state,
              data_json=excluded.data_json,
              updated_at=excluded.updated_at
        """, (wa_id, state, data_json, datetime.utcnow().isoformat()))
        conn.commit()


def set_pause_bot(wa_id: str, pause: bool):
    """
    Define pause_bot=1 (pausado) ou 0 (ativo). Cria sessão mínima se não existir.
    """
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("UPDATE sessions SET pause_bot=? WHERE wa_id=?", (1 if pause else 0, wa_id))
        if c.rowcount == 0:
            c.execute("""
                INSERT INTO sessions(wa_id, state, data_json, updated_at, pause_bot)
                VALUES(?,?,?,?,?)
            """, (wa_id, "START", "{}", datetime.utcnow().isoformat(), 1 if pause else 0))
        conn.commit()


def get_pause_bot(wa_id: str) -> bool:
    with get_conn() as conn:
        c = conn.cursor()
        row = c.execute("SELECT pause_bot FROM sessions WHERE wa_id=?", (wa_id,)).fetchone()
        return bool(row[0]) if row else False


# ============================================================
# ORDERS
# ============================================================
def save_order(wa_id: str, data: str, tipo: str, qtd: str, status: str = "NOVO"):
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO orders(wa_id, data, tipo, qtd, status, created_at)
            VALUES(?,?,?,?,?,?)
        """, (wa_id, data, tipo, qtd, status, datetime.utcnow().isoformat()))
        conn.commit()


# ============================================================
# OUTBOX (falhas de envio)
# ============================================================
def add_outbox(wa_id: str, message: str, reason: str = None):
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO outbox(wa_id, message, reason, created_at)
            VALUES(?,?,?,?)
        """, (wa_id, message, reason, datetime.utcnow().isoformat()))
        conn.commit()


# ============================================================
# INBOX — histórico
# ============================================================
def add_message(wa_id: str, direction: str, msg_type: str, body: str, wa_message_id: str = None):
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO messages(wa_id, direction, msg_type, body, wa_message_id, created_at)
            VALUES(?,?,?,?,?,?)
        """, (wa_id, direction, msg_type, body, wa_message_id, datetime.utcnow().isoformat()))
        conn.commit()


def list_conversations(limit: int = 100):
    """
    Conversas agregadas por contato.
    Retorna [(wa_id, last_at, in_msgs, out_msgs), ...]
    """
    with get_conn() as conn:
        c = conn.cursor()
        rows = c.execute("""
            SELECT m.wa_id,
                   MAX(m.created_at) AS last_at,
                   SUM(CASE WHEN m.direction='in' THEN 1 ELSE 0 END) AS in_msgs,
                   SUM(CASE WHEN m.direction!='in' THEN 1 ELSE 0 END) AS out_msgs
            FROM messages m
            GROUP BY m.wa_id
            ORDER BY last_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return rows


def list_messages(wa_id: str, limit: int = 200):
    """
    Mensagens por usuário (ordem cronológica crescente).
    Retorna [(direction, msg_type, body, wa_message_id, created_at), ...]
    """
    with get_conn() as conn:
        c = conn.cursor()
        rows = c.execute("""
            SELECT direction, msg_type, body, wa_message_id, created_at
            FROM messages
            WHERE wa_id=?
            ORDER BY id ASC
            LIMIT ?
        """, (wa_id, limit)).fetchall()
        return rows