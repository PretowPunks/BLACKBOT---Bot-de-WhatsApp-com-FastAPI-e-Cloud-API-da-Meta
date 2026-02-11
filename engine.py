import json
from datetime import datetime, timedelta
from storage import load_session_full, save_session, save_order

TIMEOUT_MINUTES = 90

RESET_WORDS = {
    "novo", "novo pedido", "reiniciar", "recomeçar", "menu", "start", "0"
}
CANCEL_WORDS = {"cancelar", "cancela", "parar", "sair"}
HELP_WORDS = {"ajuda", "help", "?"}


# ============================================================
# UTILITÁRIOS DE TEMPO
# ============================================================

def _now():
    return datetime.utcnow()


# ============================================================
# CARREGAMENTO DE ESTADO
# ============================================================

def _load_state_data(wa_id: str):
    """
    Carrega estado + dados da sessão.
    Se sessão não existir → START.
    Se sesssão estiver expirada → START.
    """
    row = load_session_full(wa_id)  # (state, data_json, updated_at)

    if not row:
        return "START", {}

    state, data_json, updated_at = row

    # Timeout da sessão
    try:
        last = datetime.fromisoformat(updated_at)
        if _now() - last > timedelta(minutes=TIMEOUT_MINUTES):
            return "START", {}
    except Exception:
        pass

    # Carrega JSON dos dados
    try:
        data = json.loads(data_json)
    except Exception:
        data = {}

    return state, data


def _set_state_data(wa_id: str, state: str, data: dict):
    save_session(wa_id, state, json.dumps(data, ensure_ascii=False))


# ============================================================
# MENU PRINCIPAL
# ============================================================

def _menu():
    return (
        "Olá! 😊 Sou o atendimento automático.\n"
        "Como posso ajudar?\n\n"
        "1) Fazer uma encomenda 🎂\n"
        "2) Ver opções/preços 💬\n"
        "3) Falar com a confeiteira 👩‍🍳\n\n"
        "Digite 1, 2 ou 3."
    )


# ============================================================
# FSM PRINCIPAL
# ============================================================

def next_reply(wa_id: str, text: str) -> str:
    t = (text or "").strip()
    t_low = t.lower()

    # ---------------------------------------------------------
    # COMANDOS GLOBAIS
    # ---------------------------------------------------------
    if t_low in HELP_WORDS:
        _set_state_data(wa_id, "START", {})
        return _menu()

    if t_low in CANCEL_WORDS:
        _set_state_data(wa_id, "START", {})
        return "Tudo bem! Pedido cancelado. Se precisar, é só chamar 😊"

    if t_low in RESET_WORDS:
        _set_state_data(wa_id, "START", {})
        return _menu()

    # ---------------------------------------------------------
    # RECUPERA O ESTADO DA SESSÃO
    # ---------------------------------------------------------
    state, data = _load_state_data(wa_id)

    # ---------------------------------------------------------
    # ESTADO: START (menu inicial)
    # ---------------------------------------------------------
    if state == "START":

        if t in ("1", "encomenda", "fazer encomenda", "quero encomendar"):
            _set_state_data(wa_id, "DATA", {})
            return "Perfeito! Para qual data é a encomenda? (ex: 15/02)"

        if t in ("2", "preço", "precos", "preços", "opções", "opcoes"):
            return (
                "Certo! 💬 Hoje trabalhamos com:\n"
                "- Doces para festa (centena)\n"
                "- Caixas presente\n"
                "- Kits personalizados\n\n"
                "Para fazer uma encomenda, digite 1."
            )

        if t in ("3", "humano", "atendente", "confeiteira", "falar"):
            return (
                "Perfeito! 👩‍🍳 Vou avisar a confeiteira.\n"
                "Assim que possível ela te responde por aqui. 😊"
            )

        # Se não reconheceu
        return _menu()

    # ---------------------------------------------------------
    # ESTADO: DATA
    # ---------------------------------------------------------
    if state == "DATA":
        data["data"] = t
        _set_state_data(wa_id, "TIPO", data)
        return "É para Festa 🎉 ou Presente 🎁? (responda: festa/presente)"

    # ---------------------------------------------------------
    # ESTADO: TIPO
    # ---------------------------------------------------------
    if state == "TIPO":
        data["tipo"] = t
        _set_state_data(wa_id, "QTD", data)
        return "Quantas unidades (aprox.)? (ex: 50, 100, 200)"

    # ---------------------------------------------------------
    # ESTADO: QTD
    # ---------------------------------------------------------
    if state == "QTD":
        data["qtd"] = t
        _set_state_data(wa_id, "OBS", data)
        return (
            "Tem alguma observação? (tema, sabores, alergias, entrega/retirada).\n"
            "Se não, digite 'não'."
        )

    # ---------------------------------------------------------
    # ESTADO: OBS
    # ---------------------------------------------------------
    if state == "OBS":
        data["obs"] = t if t_low not in ("nao", "não", "n") else ""
        _set_state_data(wa_id, "RESUMO", data)

        return (
            "Confira se está tudo certo ✅\n"
            f"- Data: {data.get('data')}\n"
            f"- Tipo: {data.get('tipo')}\n"
            f"- Quantidade: {data.get('qtd')}\n"
            f"- Obs: {data.get('obs') or '—'}\n\n"
            "Posso enviar para a confeiteira? (sim/não)\n"
            "Dica: 'não' volta ao menu e você refaz."
        )

    # ---------------------------------------------------------
    # ESTADO: RESUMO
    # ---------------------------------------------------------
    if state == "RESUMO":

        # Confirma o pedido
        if t_low in ("sim", "s", "ok", "pode", "confirmo", "confirmar"):

            save_order(
                wa_id=wa_id,
                data=data.get("data"),
                tipo=data.get("tipo"),
                qtd=data.get("qtd"),
                status="AGUARDANDO_HUMANO"
            )

            # Resetar estado
            _set_state_data(wa_id, "START", {})

            return (
                "Perfeito! ✅ Seu pedido foi registrado e enviado à confeiteira.\n"
                "Assim que possível ela entrará em contato para confirmar e finalizar.\n\n"
                "Se quiser fazer outro pedido, digite 1. 😊"
            )

        # Cancelou no resumo → volta ao menu
        _set_state_data(wa_id, "START", {})
        return "Sem problemas! Vamos voltar ao menu. 😊\n\n" + _menu()

    # ---------------------------------------------------------
    # FALLBACK
    # ---------------------------------------------------------
    _set_state_data(wa_id, "START", {})
    return _menu()