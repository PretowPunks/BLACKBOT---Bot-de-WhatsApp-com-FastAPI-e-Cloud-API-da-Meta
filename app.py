import os
import requests
from fastapi import FastAPI, Request, HTTPException, Body
from dotenv import load_dotenv

from storage import (
    init_db, get_conn,
    mark_processed, add_outbox,
    add_message, set_pause_bot, get_pause_bot,
    list_conversations, list_messages
)

from engine import next_reply

import io
import csv
from fastapi.responses import StreamingResponse

# Carrega variáveis de ambiente
load_dotenv()

# Inicializa banco
init_db()

app = FastAPI()

# Credenciais / Configurações
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
GRAPH_VERSION = os.getenv("GRAPH_VERSION", "v22.0")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN")


# ============================================================
# ENVIO DE MENSAGEM
# ============================================================

def send_text(to_wa_id: str, text: str):
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_wa_id,
        "type": "text",
        "text": {"body": text}
    }

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=20)
        print("SEND:", r.status_code, r.text)
        return r.status_code, r.text

    except Exception as e:
        print("ERROR SENDING:", str(e))
        return 500, str(e)


# ============================================================
# VERIFICAÇÃO DO WEBHOOK
# ============================================================

@app.get("/webhook")
async def webhook_verify(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN and challenge:
        return int(challenge)

    raise HTTPException(status_code=403, detail="Verification failed")


# ============================================================
# RECEBIMENTO DE MENSAGENS
# ============================================================

@app.post("/webhook")
async def webhook_receive(request: Request):
    data = await request.json()
    print("WEBHOOK EVENT:", data)

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

                # -------------------------------------------------------
                # MENSAGENS DE TEXTO
                # -------------------------------------------------------
                if msg_type == "text":
                    body = (msg.get("text") or {}).get("body", "").strip()

                    # Registrar entrada
                    add_message(wa_id, "in", "text", body, wa_message_id=msg_id)

                    # Se estiver pausado → NÃO responder com bot
                    if get_pause_bot(wa_id):
                        continue

                    # Bot gera resposta
                    reply = next_reply(wa_id, body)
                    print("REPLY_GENERATED:", reply)

                    status, resp = send_text(wa_id, reply)

                    # Registrar saída do bot
                    add_message(wa_id, "out-bot", "text", reply)

                    # Se falhou, salva na outbox
                    if status >= 400:
                        add_outbox(wa_id, reply, reason=resp)

                # -------------------------------------------------------
                # MENSAGENS NÃO-TEXTO
                # -------------------------------------------------------
                else:
                    add_message(
                        wa_id,
                        "in",
                        msg_type or "unknown",
                        "<conteúdo não-texto>",
                        wa_message_id=msg_id
                    )

                    send_text(
                        wa_id,
                        "Recebi seu arquivo/figura/áudio. No momento só entendo texto. 😊"
                    )

    return {"status": "EVENT_RECEIVED"}


# ============================================================
# ADMIN: EXPORTAR PEDIDOS
# ============================================================

@app.get("/admin/orders.csv")
async def export_orders_csv():
    with get_conn() as conn:
        c = conn.cursor()
        rows = c.execute("""
            SELECT id, wa_id, data, tipo, qtd, status, created_at
            FROM orders
            ORDER BY id DESC
        """).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "wa_id", "data", "tipo", "qtd", "status", "created_at"])
    writer.writerows(rows)

    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=orders_export.csv"}
    )


# ============================================================
# INBOX — Listar conversas, mensagens, enviar como humano
# ============================================================

@app.get("/inbox/conversations")
async def inbox_conversations(limit: int = 100):
    rows = list_conversations(limit=limit)
    return [
        {
            "wa_id": r[0],
            "last_at": r[1],
            "in_msgs": r[2],
            "out_msgs": r[3]
        }
        for r in rows
    ]


@app.get("/inbox/messages/{wa_id}")
async def inbox_messages(wa_id: str, limit: int = 200):
    rows = list_messages(wa_id, limit=limit)
    return [
        {
            "direction": r[0],
            "type": r[1],
            "body": r[2],
            "wa_message_id": r[3],
            "created_at": r[4]
        }
        for r in rows
    ]


@app.post("/inbox/send/{wa_id}")
async def inbox_send(wa_id: str, payload: dict = Body(...)):
    text = (payload.get("text") or "").strip()

    if not text:
        raise HTTPException(status_code=400, detail="Texto vazio")

    status, resp = send_text(wa_id, text)

    # Registrar como saída humana
    add_message(wa_id, "out-human", "text", text)

    if status >= 400:
        add_outbox(wa_id, text, reason=resp)
        raise HTTPException(status_code=502, detail=f"Falha ao enviar: {resp}")

    return {"status": "SENT"}


@app.post("/inbox/pause/{wa_id}")
async def inbox_pause(wa_id: str):
    set_pause_bot(wa_id, True)
    return {"status": "BOT_PAUSED"}


@app.post("/inbox/resume/{wa_id}")
async def inbox_resume(wa_id: str):
    set_pause_bot(wa_id, False)
    return {"status": "BOT_RESUMED"}

@app.middleware("http")
async def admin_token_guard(request: Request, call_next):
    if request.url.path.startswith("/inbox/"):
        if ADMIN_TOKEN:
            header_token = request.headers.get("X-Admin-Token")
            if header_token != ADMIN_TOKEN:
                raise HTTPException(status_code=401, detail="Unauthorized")
    return await call_next(request)