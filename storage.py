# storage.py (Neon / Postgres)
import os
from datetime import datetime, timezone
from typing import List, Tuple, Optional
from psycopg_pool import ConnectionPool
from psycopg.rows import dict_row

# -------------------------------------------------------------------
# Configuração do Postgres/Neon
# -------------------------------------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL não definido. Configure a URL do Postgres/Neon.")

# Garanta TLS no Neon (sslmode=require) se não vier na URL
if DATABASE_URL.startswith(("postgres://", "postgresql://")) and "sslmode=" not in DATABASE_URL:
    sep = "&" if "?" in DATABASE_URL else "?"
    DATABASE_URL = f"{DATABASE_URL}{sep}sslmode=require"

pool = ConnectionPool(
    conninfo=DATABASE_URL,
    min_size=1,
    max_size=10,
    kwargs={},  # ex.: {"autocommit": False}
)

def get_conn():
    """
    Mantém compatibilidade com 'with get_conn() as conn:' do seu código.
    Retorna um context manager de conexão do pool.
    """
    return pool.connection()


# -------------------------------------------------------------------
# INIT DB (Cria tabelas se não existirem; compatível com seu código atual)
# -------------------------------------------------------------------
def init_db():
    with get_conn() as conn:
        with conn.cursor() as c:
            # sessions
            c.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    wa_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL,
                    pause_bot INTEGER DEFAULT 0
                )
            """)
            # orders
            c.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    id BIGSERIAL PRIMARY KEY,
                    wa_id TEXT NOT NULL,
                    data TEXT,
                    tipo TEXT,
                    qtd TEXT,
                    status TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                )
            """)
            # outbox
            c.execute("""
                CREATE TABLE IF NOT EXISTS outbox (
                    id BIGSERIAL PRIMARY KEY,
                    wa_id TEXT NOT NULL,
                    message TEXT NOT NULL,
                    reason TEXT,
                    created_at TIMESTAMPTZ NOT NULL
                )
            """)
            # processed_messages
            c.execute("""
                CREATE TABLE IF NOT EXISTS processed_messages (
                    message_id TEXT PRIMARY KEY,
                    wa_id TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                )
            """)
            # messages
            c.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id BIGSERIAL PRIMARY KEY,
                    wa_id TEXT NOT NULL,
                    direction TEXT NOT NULL,   -- 'in' | 'out-bot' | 'out-human'
                    msg_type TEXT NOT NULL,    -- 'text', 'image', etc.
                    body TEXT,
                    wa_message_id TEXT,
                    created_at TIMESTAMPTZ NOT NULL
                )
            """)

            # Índices úteis
            c.execute("CREATE INDEX IF NOT EXISTS idx_messages_wa_id ON messages (wa_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages (created_at)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_orders_wa_id ON orders (wa_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders (created_at)")
        conn.commit()

    # Cria a tabela de produtos (MVP multi-tenant por slug)
    create_products_table()


# -------------------------------------------------------------------
# PRODUCTS — criação da tabela
# -------------------------------------------------------------------
def create_products_table():
    with get_conn() as conn:
        with conn.cursor() as c:
            c.execute("""
                CREATE TABLE IF NOT EXISTS products (
                    id BIGSERIAL PRIMARY KEY,
                    tenant_slug TEXT NOT NULL,
                    sku TEXT,
                    name TEXT NOT NULL,
                    description TEXT,
                    price_cents INT NOT NULL CHECK (price_cents >= 0),
                    currency TEXT NOT NULL DEFAULT 'BRL' CHECK (currency ~ '^[A-Z]{3}$'),
                    image_url TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_products_tenant ON products (tenant_slug)")
        conn.commit()


# -------------------------------------------------------------------
# IDEMPOTÊNCIA
# -------------------------------------------------------------------
def mark_processed(message_id: str, wa_id: str) -> bool:
    """
    Retorna True se for novo (inseriu), False se já existia (não processar de novo).
    Usa ON CONFLICT DO NOTHING para idempotência.
    """
    with get_conn() as conn:
        with conn.cursor() as c:
            c.execute(
                """
                INSERT INTO processed_messages(message_id, wa_id, created_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (message_id) DO NOTHING
                """,
                (message_id, wa_id, datetime.now(timezone.utc)),
            )
            inserted = c.rowcount == 1
        conn.commit()
        return inserted


# -------------------------------------------------------------------
# SESSÕES (FSM)
# -------------------------------------------------------------------
def load_session_full(wa_id: str) -> Optional[Tuple[str, str, str]]:
    """
    Retorna (state, data_json, updated_at_iso) da sessão; None se não existir.
    """
    with get_conn() as conn:
        with conn.cursor() as c:
            c.execute(
                "SELECT state, data_json, to_char(updated_at, 'YYYY-MM-DD\"T\"HH24:MI:SS.MS\"Z\"') "
                "FROM sessions WHERE wa_id=%s",
                (wa_id,),
            )
            row = c.fetchone()
            return row if row else None


def save_session(wa_id: str, state: str, data_json: str):
    """
    Upsert da sessão (state, data_json, updated_at).
    """
    with get_conn() as conn:
        with conn.cursor() as c:
            c.execute(
                """
                INSERT INTO sessions(wa_id, state, data_json, updated_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (wa_id) DO UPDATE SET
                  state = EXCLUDED.state,
                  data_json = EXCLUDED.data_json,
                  updated_at = EXCLUDED.updated_at
                """,
                (wa_id, state, data_json, datetime.now(timezone.utc)),
            )
        conn.commit()


def set_pause_bot(wa_id: str, pause: bool):
    """
    Define pause_bot=1 (pausado) ou 0 (ativo). Cria sessão mínima se não existir.
    """
    with get_conn() as conn:
        with conn.cursor() as c:
            c.execute("UPDATE sessions SET pause_bot=%s WHERE wa_id=%s", (1 if pause else 0, wa_id))
            if c.rowcount == 0:
                c.execute(
                    """
                    INSERT INTO sessions(wa_id, state, data_json, updated_at, pause_bot)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (wa_id, "START", "{}", datetime.now(timezone.utc), 1 if pause else 0),
                )
        conn.commit()


def get_pause_bot(wa_id: str) -> bool:
    with get_conn() as conn:
        with conn.cursor() as c:
            c.execute("SELECT pause_bot FROM sessions WHERE wa_id=%s", (wa_id,))
            row = c.fetchone()
            return bool(row[0]) if row else False


# -------------------------------------------------------------------
# ORDERS
# -------------------------------------------------------------------
def save_order(wa_id: str, data: str, tipo: str, qtd: str, status: str = "NOVO"):
    with get_conn() as conn:
        with conn.cursor() as c:
            c.execute(
                """
                INSERT INTO orders(wa_id, data, tipo, qtd, status, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (wa_id, data, tipo, qtd, status, datetime.now(timezone.utc)),
            )
        conn.commit()


# -------------------------------------------------------------------
# OUTBOX (falhas de envio)
# -------------------------------------------------------------------
def add_outbox(wa_id: str, message: str, reason: str = None):
    with get_conn() as conn:
        with conn.cursor() as c:
            c.execute(
                """
                INSERT INTO outbox(wa_id, message, reason, created_at)
                VALUES (%s, %s, %s, %s)
                """,
                (wa_id, message, reason, datetime.now(timezone.utc)),
            )
        conn.commit()


# -------------------------------------------------------------------
# INBOX — histórico
# -------------------------------------------------------------------
def add_message(wa_id: str, direction: str, msg_type: str, body: str, wa_message_id: str = None):
    with get_conn() as conn:
        with conn.cursor() as c:
            c.execute(
                """
                INSERT INTO messages(wa_id, direction, msg_type, body, wa_message_id, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (wa_id, direction, msg_type, body, wa_message_id, datetime.now(timezone.utc)),
            )
        conn.commit()


def list_conversations(limit: int = 100) -> List[Tuple[str, str, int, int]]:
    """
    Conversas agregadas por contato.
    Retorna [(wa_id, last_at_iso, in_msgs, out_msgs), ...]
    """
    with get_conn() as conn:
        with conn.cursor() as c:
            c.execute(
                """
                SELECT m.wa_id,
                       to_char(MAX(m.created_at), 'YYYY-MM-DD\"T\"HH24:MI:SS.MS\"Z\"') AS last_at,
                       SUM(CASE WHEN m.direction='in' THEN 1 ELSE 0 END) AS in_msgs,
                       SUM(CASE WHEN m.direction!='in' THEN 1 ELSE 0 END) AS out_msgs
                FROM messages m
                GROUP BY m.wa_id
                ORDER BY MAX(m.created_at) DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = c.fetchall()
            return rows


def list_messages(wa_id: str, limit: int = 200) -> List[Tuple[str, str, str, Optional[str], str]]:
    """
    Mensagens por usuário (ordem cronológica crescente).
    Retorna [(direction, msg_type, body, wa_message_id, created_at_iso), ...]
    """
    with get_conn() as conn:
        with conn.cursor() as c:
            c.execute(
                """
                SELECT direction,
                       msg_type,
                       body,
                       wa_message_id,
                       to_char(created_at, 'YYYY-MM-DD\"T\"HH24:MI:SS.MS\"Z\"') AS created_at
                FROM messages
                WHERE wa_id=%s
                ORDER BY id ASC
                LIMIT %s
                """,
                (wa_id, limit),
            )
            rows = c.fetchall()
            return rows


# -------------------------------------------------------------------
# PRODUCTS — CRUD (multi-tenant por tenant_slug)
# -------------------------------------------------------------------
def list_products(tenant_slug: str, limit: int = 50, offset: int = 0):
    sql = """
    SELECT id, tenant_slug, sku, name, description, price_cents, currency, image_url,
           to_char(created_at, 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') AS created_at,
           to_char(updated_at, 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') AS updated_at
    FROM products
    WHERE tenant_slug = %s
    ORDER BY id DESC
    LIMIT %s OFFSET %s
    """
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as c:
            c.execute(sql, (tenant_slug, limit, offset))
            return c.fetchall()

def count_products(tenant_slug: str) -> int:
    with get_conn() as conn:
        with conn.cursor() as c:
            c.execute("SELECT COUNT(*) FROM products WHERE tenant_slug = %s", (tenant_slug,))
            (n,) = c.fetchone()
            return int(n)

def get_product(tenant_slug: str, product_id: int):
    sql = """
    SELECT id, tenant_slug, sku, name, description, price_cents, currency, image_url,
           to_char(created_at, 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') AS created_at,
           to_char(updated_at, 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') AS updated_at
    FROM products
    WHERE tenant_slug = %s AND id = %s
    """
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as c:
            c.execute(sql, (tenant_slug, product_id))
            return c.fetchone()

def create_product(tenant_slug: str, data: dict):
    sql = """
    INSERT INTO products (tenant_slug, sku, name, description, price_cents, currency, image_url)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    RETURNING id, tenant_slug, sku, name, description, price_cents, currency, image_url,
              to_char(created_at, 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') AS created_at,
              to_char(updated_at, 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') AS updated_at
    """
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as c:
            c.execute(sql, (
                tenant_slug,
                data.get("sku"),
                data["name"],
                data.get("description"),
                data["price_cents"],
                data.get("currency", "BRL"),
                data.get("image_url"),
            ))
            row = c.fetchone()
        conn.commit()
        return row

def update_product(tenant_slug: str, product_id: int, data: dict):
    allowed = ["sku", "name", "description", "price_cents", "currency", "image_url"]
    fields = []
    values = []
    for k in allowed:
        if k in data and data[k] is not None:
            fields.append(f"{k} = %s")
            values.append(data[k])

    if not fields:
        return get_product(tenant_slug, product_id)

    set_clause = ", ".join(fields + ["updated_at = NOW()"])
    sql = f"""
    UPDATE products
       SET {set_clause}
     WHERE tenant_slug = %s AND id = %s
     RETURNING id, tenant_slug, sku, name, description, price_cents, currency, image_url,
               to_char(created_at, 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') AS created_at,
               to_char(updated_at, 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') AS updated_at
    """
    values.extend([tenant_slug, product_id])

    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as c:
            c.execute(sql, tuple(values))
            row = c.fetchone()
        conn.commit()
        return row

def delete_product(tenant_slug: str, product_id: int) -> bool:
    with get_conn() as conn:
        with conn.cursor() as c:
            c.execute("DELETE FROM products WHERE tenant_slug = %s AND id = %s", (tenant_slug, product_id))
            deleted = c.rowcount > 0
        conn.commit()
        return deleted