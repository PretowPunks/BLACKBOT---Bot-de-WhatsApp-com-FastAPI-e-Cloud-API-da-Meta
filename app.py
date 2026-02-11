import os
import requests
import logging
from fastapi import FastAPI, Request, HTTPException, Body
from fastapi.responses import JSONResponse, StreamingResponse, HTMLResponse
from dotenv import load_dotenv

from storage import (
    init_db, get_conn,
    mark_processed, add_outbox, add_message,
    set_pause_bot, get_pause_bot,
    list_conversations, list_messages
)

from engine import next_reply

import io
import csv

# =======================================
# BOOT
# =======================================
load_dotenv()
init_db()

app = FastAPI()

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
GRAPH_VERSION = os.getenv("GRAPH_VERSION", "v22.0")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN")


# =======================================
# ENVIO DE TEXTO
# =======================================
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
        logging.info(f"SEND {r.status_code} {r.text}")
        return r.status_code, r.text
    except Exception as e:
        logging.error(f"ERROR SENDING {e}")
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
        return int(challenge)

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
# INBOX
# =======================================
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
    try:
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
    except Exception:
        logging.exception(f"[inbox_messages] erro ao listar mensagens")
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
# MIDDLEWARE: ADMIN TOKEN
# =======================================

@app.middleware("http")
async def admin_token_guard(request: Request, call_next):
    # Protege os endpoints do Inbox
    if request.url.path.startswith("/inbox/") and ADMIN_TOKEN:
        token = (
            request.headers.get("X-Admin-Token")
            or request.headers.get("Admin-Token")  # header alternativo
        )
        if token != ADMIN_TOKEN:
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
    return await call_next(request)



@app.get("/inbox", response_class=HTMLResponse)
def serve_inbox():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    inbox_path = os.path.join(base_dir, "inbox.html")
    if not os.path.exists(inbox_path):
        # Ajuda a diagnosticar no Render caso o arquivo não tenha sido copiado na imagem
        return HTMLResponse(
            "<h3>inbox.html não encontrado no container.</h3>"
            "<p>Verifique se o Dockerfile copia o arquivo para a imagem.</p>",
            status_code=500
        )
    with open(inbox_path, "r", encoding="utf-8") as f:
        return f.read()

