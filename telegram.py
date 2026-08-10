"""Dispatcher de Telegram: formato del briefing + envío + comandos entrantes.

Objetivo del formato: que el humano decida en 20 segundos si publica o no.
Jerarquía visual fija -> el ojo aprende dónde mirar y deja de leer todo.
"""
from __future__ import annotations

import html
import logging
import os
import time
from typing import Any, Optional

import requests

from models import Item, Verdict
from util import USER_AGENT

log = logging.getLogger("democles.telegram")

API = "https://api.telegram.org/bot{token}/{method}"
MAX_LEN = 4096          # límite duro de Telegram
SAFE_LEN = 3900         # margen para el sufijo de continuación

SEP = "━━━━━━━━━━━━━━━━━━━━"


class TelegramError(RuntimeError):
    pass


# --------------------------------------------------------------------- envío
def _token() -> str:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise TelegramError("falta TELEGRAM_BOT_TOKEN")
    return token


def _chat_ids() -> list[str]:
    """Destinos del briefing. TELEGRAM_CHAT_ID admite varios separados por comas.

    Sirve tanto para chats privados (id positivo) como para un grupo (id
    negativo, tipo -1001234567890) al que hayas añadido el bot.
    """
    crudo = os.getenv("TELEGRAM_CHAT_ID", "")
    destinos = [c.strip() for c in crudo.split(",") if c.strip()]
    if not destinos:
        raise TelegramError("falta TELEGRAM_CHAT_ID")
    return destinos


def call(method: str, payload: dict[str, Any], *, retries: int = 2) -> dict:
    url = API.format(token=_token(), method=method)
    for attempt in range(retries + 1):
        try:
            resp = requests.post(url, json=payload, timeout=30,
                                 headers={"User-Agent": USER_AGENT})
        except requests.RequestException as exc:
            log.warning("Telegram %s falló (%s/%s): %s", method, attempt + 1, retries + 1, exc)
            time.sleep(2 ** attempt)
            continue

        data = resp.json() if resp.content else {}
        if resp.status_code == 200 and data.get("ok"):
            return data.get("result", {})

        # 429: Telegram indica cuántos segundos esperar.
        if resp.status_code == 429:
            wait = int(data.get("parameters", {}).get("retry_after", 5))
            log.warning("Telegram rate limit; espero %ss", wait)
            time.sleep(wait + 1)
            continue
        raise TelegramError(f"{method} -> HTTP {resp.status_code}: {str(data)[:250]}")
    raise TelegramError(f"{method}: agotados los reintentos")


def _split(text: str, limit: int = SAFE_LEN) -> list[str]:
    """Corta por líneas para no romper etiquetas HTML a mitad."""
    if len(text) <= limit:
        return [text]
    chunks, current = [], ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > limit:
            chunks.append(current.rstrip())
            current = ""
        current += line + "\n"
    if current.strip():
        chunks.append(current.rstrip())
    return chunks


def send_briefing(item: Item, verdict: Verdict, *, dry_run: bool = False) -> Optional[int]:
    """Envía el briefing formateado. Devuelve el message_id o None en dry-run."""
    text = format_briefing(item, verdict)
    if dry_run:
        print("\n" + "=" * 70)
        print(text)
        print("=" * 70 + "\n")
        return None

    chunks = _split(text)
    keyboard = {
        "inline_keyboard": [[
            {"text": "👍 Publicar", "callback_data": f"pub:{item.short_key}"},
            {"text": "✏️ Editar", "callback_data": f"edt:{item.short_key}"},
            {"text": "❌ Descartar", "callback_data": f"del:{item.short_key}"},
        ]]
    }

    destinos = _chat_ids()
    message_id = None
    entregados = 0
    fallos: list[str] = []

    for destino in destinos:
        try:
            for index, chunk in enumerate(chunks):
                payload: dict[str, Any] = {
                    "chat_id": destino,
                    "text": chunk,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": index > 0,  # preview sólo en el primero
                }
                if index == len(chunks) - 1:
                    payload["reply_markup"] = keyboard
                result = call("sendMessage", payload)
                message_id = message_id or result.get("message_id")
                if len(chunks) > 1:
                    time.sleep(0.6)
            entregados += 1
        except TelegramError as exc:
            # Un destinatario que bloqueó al bot no puede tumbar el envío a los
            # demás, ni marcar la noticia como fallida y reintentarla eternamente.
            fallos.append(f"{destino}: {exc}")
            log.error("No se pudo entregar a %s: %s", destino, exc)

    if not entregados:
        raise TelegramError("ningún destino recibió el briefing — " + " | ".join(fallos))
    if fallos:
        log.warning("Entregado a %s/%s destinos", entregados, len(destinos))
    return message_id


def send_text(text: str, *, chat_id: Optional[str] = None) -> None:
    """Sin `chat_id` se emite a todos los destinos configurados."""
    destinos = [chat_id] if chat_id else _chat_ids()
    for destino in destinos:
        try:
            for chunk in _split(text):
                call("sendMessage", {
                    "chat_id": destino,
                    "text": chunk,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                })
        except TelegramError as exc:
            log.error("No se pudo escribir a %s: %s", destino, exc)


# ------------------------------------------------------------------- formato
def _fire(score: int) -> str:
    if score >= 10:
        return "🚨🚨"
    if score >= 9:
        return "🚨"
    if score >= 8:
        return "🔥"
    return "⚡"


def _format_icon(formato: str) -> str:
    # "Post único" no puede llevar 🖼️: ese emoji ya identifica la sugerencia
    # visual más abajo y el mensaje pierde su jerarquía de un vistazo.
    return {
        "reel": "🎬", "carrusel": "🎠", "story": "⏱️", "post único": "📷",
    }.get((formato or "").strip().lower(), "📱")


def format_briefing(item: Item, verdict: Verdict) -> str:
    """Mensaje HTML. Orden fijo: qué / por qué / cómo / con qué / gancho."""
    esc = html.escape
    title = esc(item.title.strip())
    source = esc(item.source)
    url = esc(item.url, quote=True)

    # Google News no expone la URL real del medio; sí su nombre. Mostrarlo evita
    # que el humano tenga que abrir el enlace para saber quién lo publica.
    medio = (item.extra or {}).get("medio")
    origen = f"{source} · vía {esc(medio)}" if medio else source

    lines = [
        f"{_fire(verdict.relevancia)} <b>RELEVANCIA: {verdict.relevancia}/10</b>",
        "",
        f"📰 <b>{title}</b>",
        f'📍 {origen} · <a href="{url}">abrir noticia</a>',
    ]
    if verdict.justificacion_relevancia:
        lines += ["", f"💬 <b>Por qué importa:</b> {esc(verdict.justificacion_relevancia)}"]

    briefing = verdict.briefing
    if briefing is None:
        lines += [
            "", SEP, "",
            "⚠️ <i>El agente aprobó la noticia pero no generó briefing. "
            "Revisa la fuente y decide a mano.</i>",
        ]
        return "\n".join(lines)

    lines += [
        "", SEP, "",
        f"{_format_icon(briefing.formato_instagram)} <b>FORMATO: "
        f"{esc(briefing.formato_instagram)}</b>",
        f"<i>{esc(briefing.justificacion_formato)}</i>",
        "",
        "🖼️ <b>SUGERENCIA VISUAL</b>",
        esc(briefing.sugerencia_visual),
        "",
        "📝 <b>CAPTION SUGERIDO</b>",
        # <code> = pulsación larga -> copiar, sin tocar el texto.
        f"<code>{esc(briefing.caption_sugerido)}</code>",
        "",
        "🎯 <b>ÁNGULO DE ENGAGEMENT</b>",
        esc(briefing.angulo_engagement),
    ]

    if briefing.hashtags:
        tags = " ".join(
            esc(h if h.startswith("#") else f"#{h}") for h in briefing.hashtags
        )
        lines += ["", "🏷️ <b>HASHTAGS</b>", f"<code>{tags}</code>"]

    lines += ["", SEP, "⬇️ 👍 publicar · ✏️ editar · ❌ descartar"]
    return "\n".join(lines)


# ------------------------------------------------------------------ comandos
def get_updates(offset: int, *, timeout: int = 0) -> list[dict]:
    """Long-poll corto. `timeout=0` para uso en cron (no bloquea el job)."""
    result = call("getUpdates", {
        "offset": offset,
        "timeout": timeout,
        "allowed_updates": ["message", "callback_query"],
    })
    return result if isinstance(result, list) else []


def answer_callback(callback_id: str, text: str) -> None:
    try:
        call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text},
             retries=0)
    except TelegramError as exc:
        log.debug("answerCallbackQuery falló: %s", exc)
