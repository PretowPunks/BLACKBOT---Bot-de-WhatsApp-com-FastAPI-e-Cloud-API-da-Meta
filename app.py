import os
import io
import csv
import logging
import requests

from fastapi import FastAPI, Request, HTTPException, Body, Header
from fastapi.responses import JSONResponse, StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from uuid import uuid4

# Storage (síncrono) — mantém seu estado atual
from storage import (
    init_db, get_conn,
    mark_processed, add_outbox, add_message,
    set_pause_bot, get_pause_bot,
    list_conversations, list_messages
)

# Motor da conversa (FSM)
from engine import next_reply

# R2 helpers
from r2_client import presign_put_url, build_public_url, guess_ext


# =======================================
# BOOT
# =======================================
load_dotenv()
# Inicializa DB (tabelas legadas + o que já existir)
init_db()

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="BlackBot API")

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
GRAPH_VERSION = os.getenv("GRAPH_VERSION", "v22.0")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN")


# =======================================
# STATIC: /static e atalho /admin
# =======================================
# Garante que a pasta exista (útil no Render)
if not os.path.isdir("static"):
    os.makedirs("static/admin", exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def root_redirect():
    # Ajuda a acessar rápido o admin quando abre a raiz
    return RedirectResponse(url="/admin", status_code=307)

@app.get("/admin")
def admin_root():
    # Abre o dashboard do admin
    return RedirectResponse(url="/static/admin/index.html", status_code=307)


# =======================================
# HEALTHCHECK
# =======================================
@app.get("/healthz")
def healthz():
    # Checa conexão e permissão básica
    try:
        with get_conn() as conn:
            c = conn.cursor()
            c.execute("SELECT 1")
            _ = c.fetchone()
        return {"ok": True}
    except Exception as e:
        logging.exception("healthz failed")
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


# =======================================
# ENVIO DE TEXTO
# =======================================
def send_text(to_wa_id: str, text: str):
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_wa_id,
        "type": "text",
        "text": {"body": text},
    }

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=20)
        logging.info(f"[send_text] {r.status_code} {r.text}")
        return r.status_code, r.text
    except Exception as e:
        logging.error(f"[send_text:error] {e}")
        return 500, str(e)


# =======================================
# WEBHOOK VERIFY
# =======================================
@app.get("/webhook")
async def webhook_verify(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN and challenge:
        # o desafio do Meta pode ser retornado como int ou str
        try:
            return int(challenge)
        except Exception:
            return challenge

    raise HTTPException(status_code=403, detail="Verification failed")


# =======================================
# WEBHOOK RECEIVE
# =======================================
@app.post("/webhook")
async def webhook_receive(request: Request):
    data = await request.json()
    logging.info(f"WEBHOOK EVENT: {data}")

    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})

            for msg in value.get("messages", []):
                wa_id = msg.get("from")
                msg_id = msg.get("id")
                msg_type = msg.get("type")

                # Idempotência
                if wa_id and msg_id and not mark_processed(msg_id, wa_id):
                    continue

                # TEXTO
                if msg_type == "text":
                    body = (msg.get("text") or {}).get("body", "").strip()

                    add_message(wa_id, "in", "text", body, wa_message_id=msg_id)

                    # Se pausado, humano responde
                    if get_pause_bot(wa_id):
                        continue

                    # FSM
                    reply = next_reply(wa_id, body)
                    status, resp = send_text(wa_id, reply)

                    add_message(wa_id, "out-bot", "text", reply)

                    if status >= 400:
                        add_outbox(wa_id, reply, reason=resp)

                # NÃO TEXTO
                else:
                    add_message(
                        wa_id, "in", msg_type, "<conteúdo não-texto>", wa_message_id=msg_id
                    )
                    send_text(
                        wa_id,
                        "Recebi seu arquivo/figura/áudio. No momento só entendo texto. 😊"
                    )

    return {"status": "EVENT_RECEIVED"}


# =======================================
# ORDERS CSV
# =======================================
@app.get("/admin/orders.csv")
async def export_orders_csv():
    with get_conn() as conn:
        c = conn.cursor()
        rows = c.execute("""
            SELECT id, wa_id, data, tipo, qtd, status, created_at
            FROM orders
            ORDER BY id DESC
        """).fetchall()

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["id", "wa_id", "data", "tipo", "qtd", "status", "created_at"])
    writer.writerows(rows)
    out.seek(0)

    return StreamingResponse(
        iter([out.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=orders.csv"}
    )


# =======================================
# INBOX (APIs legadas - úteis para auditoria e debug)
# =======================================
@app.get("/inbox/conversations")
async def inbox_conversations(limit: int = 100):
    rows = list_conversations(limit=limit)
    return [
        {
            "wa_id": r[0],
            "last_at": r[1],
            "in_msgs": r[2],
            "out_msgs": r[3],
        }
        for r in rows
    ]


@app.get("/inbox/messages/{wa_id}")
async def inbox_messages(wa_id: str, limit: int = 200):
    try:
        rows = list_messages(wa_id, limit=limit)
        return [
            {
                "direction": r[0],
                "type": r[1],
                "body": r[2],
                "wa_message_id": r[3],
                "created_at": r[4],
            }
            for r in rows
        ]
    except Exception:
        logging.exception("[inbox_messages] erro ao listar mensagens")
        raise HTTPException(status_code=500, detail="inbox_messages_failed")


@app.post("/inbox/send/{wa_id}")
async def inbox_send(wa_id: str, payload: dict = Body(...)):
    text = (payload.get("text") or "").strip()

    if not text:
        raise HTTPException(status_code=400, detail="texto vazio")

    status, resp = send_text(wa_id, text)

    add_message(wa_id, "out-human", "text", text)

    if status >= 400:
        add_outbox(wa_id, text, reason=resp)
        raise HTTPException(status_code=502, detail="falha ao enviar")

    return {"status": "sent"}


@app.post("/inbox/pause/{wa_id}")
async def inbox_pause(wa_id: str):
    set_pause_bot(wa_id, True)
    return {"status": "paused"}


@app.post("/inbox/resume/{wa_id}")
async def inbox_resume(wa_id: str):
    set_pause_bot(wa_id, False)
    return {"status": "resumed"}


# =======================================
# MIDDLEWARE: ADMIN TOKEN (protege apenas /inbox/*)
# =======================================
@app.middleware("http")
async def admin_token_guard(request: Request, call_next):
    # Protege os endpoints do Inbox legado
    if request.url.path.startswith("/inbox/") and ADMIN_TOKEN:
        token = (
            request.headers.get("X-Admin-Token")
            or request.headers.get("Admin-Token")  # header alternativo
        )
        if token != ADMIN_TOKEN:
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
    return await call_next(request)


# =======================================
# UPLOAD: Presign R2
# =======================================
class UploadURLIn(BaseModel):
    filename: str = Field(..., description="Nome original do arquivo")
    content_type: str | None = Field(default=None, description="MIME type (ex.: image/jpeg)")
    expires_in: int = Field(default=600, ge=60, le=3600, description="Validade da URL em segundos")

class UploadURLOut(BaseModel):
    put_url: str
    public_url: str
    key: str
    content_type: str
    expires_in: int

@app.post("/api/t/{slug}/upload-url", response_model=UploadURLOut)
async def create_upload_url(
    slug: str,
    payload: UploadURLIn,
    admin_token: str = Header(..., alias="X-Admin-Token"),
):
    # Enquanto não há tenants, validamos com ADMIN_TOKEN global (do .env)
    if ADMIN_TOKEN and admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Token inválido")

    ct = (payload.content_type or "").strip().lower() or "application/octet-stream"
    # limitar a imagens por ora (menor superfície)
    if not ct.startswith("image/"):
        raise HTTPException(status_code=415, detail="Somente imagens são suportadas")

    ext = guess_ext(payload.filename, ct)
    key = f"{slug}/{uuid4().hex}{ext}"

    put_url = presign_put_url(key=key, content_type=ct, expires_in=payload.expires_in)
    public_url = build_public_url(key)

    # Log leve na outbox (sem quebrar o fluxo)
    try:
        add_outbox(
            wa_id="admin",
            message=f"presign:{slug}:{key}",
            reason=f"ct={ct}|exp={payload.expires_in}",
        )
    except Exception:
        pass

    return UploadURLOut(
        put_url=put_url,
        public_url=public_url,
        key=key,
        content_type=ct,
        expires_in=payload.expires_in,
    )

# =========================
# Products API (MVP) - Router isolado
# =========================
# - Multi-tenant via {slug}
# - Protegido por X-Admin-Token (ADMIN_TOKEN global no .env)
# - Pydantic v2 para validação
# - Paginação: limit (1–200, default 50) e offset (>=0, default 0)
# - Compatível com o front (products.js) do Admin

import os
from typing import Optional, Any, Dict, List

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query

# Pydantic v2
from pydantic import BaseModel, Field

# Import do storage local (funciona se storage.py estiver no mesmo diretório)
try:
    import storage  # type: ignore
except Exception:  # pragma: no cover
    from . import storage  # type: ignore

# Reaproveita app existente; caso o arquivo seja rodado isolado, cria um app
try:  # pragma: no cover
    app  # type: ignore
except NameError:  # pragma: no cover
    from fastapi import FastAPI
    app = FastAPI()

router_products = APIRouter(tags=["products"])

# -------------------------
# Segurança (Admin global)
# -------------------------
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN")

def require_admin_token(x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token")) -> None:
    """
    MVP: proteção simples via header X-Admin-Token comparado ao ADMIN_TOKEN global.
    """
    if not ADMIN_TOKEN:
        raise HTTPException(status_code=500, detail="ADMIN_TOKEN não configurado no servidor")
    if not x_admin_token or x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Não autorizado")

# -------------------------
# Modelos (Pydantic v2)
# -------------------------
# Regex para currency ISO-4217 (3 letras maiúsculas)
CURRENCY_PATTERN = r"^[A-Z]{3}$"

class ProductCreate(BaseModel):
    sku: Optional[str] = None
    name: str = Field(..., min_length=1)
    description: Optional[str] = None
    price_cents: int = Field(..., ge=0)
    currency: str = Field(default="BRL", pattern=CURRENCY_PATTERN)
    image_url: Optional[str] = None

class ProductUpdate(BaseModel):
    # Atualização parcial: todos opcionais, mas validados quando presentes
    sku: Optional[str] = None
    name: Optional[str] = Field(default=None, min_length=1)
    description: Optional[str] = None
    price_cents: Optional[int] = Field(default=None, ge=0)
    currency: Optional[str] = Field(default=None, pattern=CURRENCY_PATTERN)
    image_url: Optional[str] = None

# -------------------------
# Helpers
# -------------------------
def _404_if_none(row: Any, entity: str = "Produto") -> Any:
    """
    Converte resultados vazios em 404.
    storage.* pode retornar None, 0, False ou estrutura vazia quando não há linhas afetadas.
    """
    if row is None:
        raise HTTPException(status_code=404, detail=f"{entity} não encontrado")
    if isinstance(row, (list, tuple, set, dict)) and len(row) == 0:
        raise HTTPException(status_code=404, detail=f"{entity} não encontrado")
    if isinstance(row, int) and row == 0:
        raise HTTPException(status_code=404, detail=f"{entity} não encontrado")
    return row

# -------------------------
# Rotas
# -------------------------
@router_products.get(
    "/api/t/{slug}/products",
)
def list_products_endpoint(
    slug: str = Path(..., description="tenant_slug"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: None = Depends(require_admin_token),
) -> Dict[str, Any]:
    """
    Lista produtos de um tenant com paginação.
    Retorna: { items, total, limit, offset }
    """
    try:
        items: List[Dict[str, Any]] = storage.list_products(tenant_slug=slug, limit=limit, offset=offset)  # type: ignore
        total: int = storage.count_products(tenant_slug=slug)  # type: ignore
        return {
            "items": items,
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Erro ao listar produtos: {exc}")

@router_products.post(
    "/api/t/{slug}/products",
    status_code=201,
)
def create_product_endpoint(
    slug: str,
    body: ProductCreate,
    _: None = Depends(require_admin_token),
) -> Dict[str, Any]:
    """
    Cria um produto para o tenant especificado.
    """
    try:
        data = body.model_dump(exclude_unset=True)
        created = storage.create_product(tenant_slug=slug, data=data)  # type: ignore
        return _404_if_none(created, "Produto")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Erro ao criar produto: {exc}")

@router_products.put(
    "/api/t/{slug}/products/{product_id}",
)
def update_product_endpoint(
    slug: str,
    product_id: int = Path(..., ge=1),
    body: ProductUpdate = ...,
    _: None = Depends(require_admin_token),
) -> Dict[str, Any]:
    """
    Atualiza parcialmente um produto do tenant (qualquer subset dos campos).
    """
    try:
        changes = body.model_dump(exclude_unset=True)
        if not changes:
            raise HTTPException(status_code=400, detail="Corpo vazio: nenhum campo para atualizar")
        updated = storage.update_product(tenant_slug=slug, product_id=product_id, data=changes)  # type: ignore
        return _404_if_none(updated, "Produto")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Erro ao atualizar produto: {exc}")

@router_products.delete(
    "/api/t/{slug}/products/{product_id}",
)
def delete_product_endpoint(
    slug: str,
    product_id: int = Path(..., ge=1),
    _: None = Depends(require_admin_token),
) -> Dict[str, Any]:
    """
    Remove um produto do tenant.
    Retorna { ok: true } se deletado, 404 caso não exista.
    """
    try:
        result = storage.delete_product(tenant_slug=slug, product_id=product_id)  # type: ignore
        _404_if_none(result, "Produto")
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Erro ao remover produto: {exc}")

# Registra o router no app principal
app.include_router(router_products)