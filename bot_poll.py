"""Comandos entrantes de Telegram, sin servidor ni webhook.

Se ejecuta al inicio de cada ciclo de main.py: vacía la cola de getUpdates,
procesa comandos y pulsaciones de botones, y guarda el offset en el estado.
Latencia máxima de un /add: un ciclo de cron. Coste de infraestructura: 0 €.
"""
from __future__ import annotations

import html
import logging
import os
import re
from typing import Optional

import telegram as tg
from fetchers.instagram import is_instagram_url
from state import State
from util import now_iso

log = logging.getLogger("democles.bot")

URL_RE = re.compile(r"https?://\S+")

HELP = (
    "<b>DEMOCLES — bot de briefings de MMA</b>\n\n"
    "<code>/add &lt;url&gt; [nota]</code>  Envía un post de Instagram (o cualquier "
    "enlace) al agente. La nota es opcional y ayuda a puntuar mejor.\n"
    "<code>/status</code>  Estado del sistema y últimos envíos.\n"
    "<code>/whoami</code>  Tu ID de usuario (para pedir acceso).\n"
    "<code>/help</code>  Esta ayuda.\n\n"
    "Ejemplo:\n"
    "<code>/add https://www.instagram.com/p/Cxyz123/ Topuria confirma peso pluma</code>"
)


def _allowed_users() -> set[int]:
    """Quién puede usar /add. Lista de IDs numéricos separados por comas."""
    raw = os.getenv("TELEGRAM_ALLOWED_USERS", "")
    ids = {int(x) for x in re.findall(r"\d+", raw)}
    if ids:
        return ids

    # Sin lista explícita, valen los chats PRIVADOS de TELEGRAM_CHAT_ID: en un
    # chat privado el id del chat coincide con el del usuario. Los grupos tienen
    # id negativo y no identifican a nadie; incluirlos dejaría fuera a todos.
    for destino in os.getenv("TELEGRAM_CHAT_ID", "").split(","):
        destino = destino.strip()
        if destino.isdigit():
            ids.add(int(destino))
    return ids


def _authorized(user_id: Optional[int]) -> bool:
    allowed = _allowed_users()
    return bool(user_id) and (not allowed or user_id in allowed)


# --------------------------------------------------------------------------
def _handle_add(text: str, user_id: int, chat_id: str, state: State) -> None:
    match = URL_RE.search(text)
    if not match:
        tg.send_text("❌ No veo ninguna URL. Uso: <code>/add &lt;url&gt; [nota]</code>",
                     chat_id=chat_id)
        return

    url = match.group(0).rstrip(".,;)")
    note = (text[: match.start()] + " " + text[match.end():]).replace("/add", "").strip()

    if any(entry.get("url") == url for entry in state.manual_queue):
        tg.send_text("ℹ️ Ese enlace ya está en la cola.", chat_id=chat_id)
        return

    state.manual_queue.append(
        {"url": url, "note": note, "ts": now_iso(), "user_id": user_id}
    )
    kind = "Post de Instagram" if is_instagram_url(url) else "Enlace"
    tg.send_text(
        f"✅ {kind} encolado. El agente lo analizará en el próximo ciclo "
        f"(máx. 20 min).\n<i>{'Nota: ' + note if note else 'Sin nota — añade contexto para afinar la puntuación.'}</i>",
        chat_id=chat_id,
    )
    log.info("Cola manual +1: %s", url)


def _handle_status(chat_id: str, state: State) -> None:
    seen = state.seen
    sent = [s for s in seen if s.get("sent")]
    last = sent[-3:][::-1]
    lines = [
        "<b>📊 Estado</b>",
        f"Noticias procesadas (histórico): <b>{len(seen)}</b>",
        f"Enviadas a este chat: <b>{len(sent)}</b>",
        f"En cola manual: <b>{len(state.manual_queue)}</b>",
    ]
    stats = state.data.get("stats", {})
    if stats:
        lines.append("")
        lines.append("<b>Último ciclo</b>")
        for key in ("recogidos", "unicos", "llamadas_llm", "enviados", "descartados"):
            if key in stats:
                lines.append(f"· {key}: {stats[key]}")
    if last:
        lines += ["", "<b>Últimos enviados</b>"]
        for entry in last:
            lines.append(f"· [{entry.get('score', '?')}/10] {entry.get('title', '')[:70]}")
    tg.send_text("\n".join(lines), chat_id=chat_id)


def _handle_callback(update: dict) -> None:
    query = update["callback_query"]
    action = (query.get("data") or "").split(":", 1)[0]
    reply = {
        "pub": "👍 Marcado para publicar",
        "edt": "✏️ Marcado para editar",
        "del": "❌ Descartado",
    }.get(action, "Recibido")
    tg.answer_callback(query["id"], reply)


# --------------------------------------------------------------------------
def process_updates(state: State, *, max_lotes: int = 5) -> int:
    """Procesa todo lo pendiente. Devuelve el número de updates atendidos.

    Se piden lotes hasta que Telegram devuelve vacío, por dos razones:
    un lote trae como mucho 100 updates, y sobre todo porque Telegram **sólo
    da por leído un update cuando vuelves a llamar con un offset mayor**.
    Guardar el offset en el estado no basta: sin esa llamada final de
    confirmación, la cola seguía creciendo indefinidamente.
    """
    handled = 0
    for _ in range(max_lotes):
        try:
            updates = tg.get_updates(state.telegram_offset)
        except tg.TelegramError as exc:
            log.warning("No se pudieron leer los updates: %s", exc)
            break
        if not updates:
            break          # esta llamada ya ha confirmado el lote anterior
        handled += _procesar_lote(updates, state)

    if handled:
        log.info("Telegram: %s comandos procesados", handled)
    return handled


def _procesar_lote(updates: list[dict], state: State) -> int:
    handled = 0
    for update in updates:
        state.telegram_offset = int(update["update_id"]) + 1
        try:
            if "callback_query" in update:
                _handle_callback(update)
                handled += 1
                continue

            message = update.get("message") or {}
            text = (message.get("text") or "").strip()
            user_id = (message.get("from") or {}).get("id")
            chat_id = str((message.get("chat") or {}).get("id", ""))
            if not text or not chat_id:
                continue

            command = text.split()[0].split("@")[0].lower()

            # /whoami va ANTES del control de acceso a propósito: es como una
            # persona nueva averigua su ID para que tú puedas autorizarla. Sólo
            # revela el ID de quien pregunta, que ya es suyo.
            if command == "/whoami":
                nombre = (message.get("from") or {}).get("first_name", "")
                tg.send_text(
                    f"👤 <b>{html.escape(str(nombre))}</b>\n"
                    f"Tu ID de usuario: <code>{user_id}</code>\n"
                    f"ID de este chat: <code>{chat_id}</code>\n\n"
                    + ("✅ Ya tienes acceso a /add"
                       if _authorized(user_id) else
                       "🔒 Aún sin acceso. Pásale tu ID al administrador para "
                       "que lo añada a <code>TELEGRAM_ALLOWED_USERS</code>."),
                    chat_id=chat_id,
                )
                handled += 1
                continue

            if not _authorized(user_id):
                log.warning("Usuario no autorizado: %s", user_id)
                tg.send_text(
                    "🔒 No autorizado. Envía <code>/whoami</code> y pásale tu ID "
                    "al administrador.",
                    chat_id=chat_id,
                )
                continue

            if command == "/add":
                _handle_add(text, int(user_id), chat_id, state)
            elif command == "/status":
                _handle_status(chat_id, state)
            elif command in ("/help", "/start"):
                tg.send_text(HELP, chat_id=chat_id)
            elif URL_RE.search(text) and is_instagram_url(text):
                # Pegar una URL de Instagram a secas equivale a /add.
                _handle_add(text, int(user_id), chat_id, state)
            else:
                continue
            handled += 1
        except Exception as exc:  # noqa: BLE001 - un update roto no debe parar el ciclo
            log.exception("Error procesando update %s: %s", update.get("update_id"), exc)

    return handled
