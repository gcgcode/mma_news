"""Agente LLM: una llamada por noticia -> relevancia + briefing.

Proveedores intercambiables por variable de entorno. El sistema no depende de
ninguno: si el free tier de uno se agota, cambias LLM_PROVIDER y sigues.

  gemini     Google AI Studio. Free tier real. Recomendado por defecto.
  groq       Free tier generoso (llama-3.3-70b). Muy rápido.
  openai     gpt-4o-mini u o4-mini. De pago, muy barato.
  together   Modelos abiertos alojados. De pago, muy barato.
  anthropic  claude-haiku-4-5 ($1/MTok entrada, $5/MTok salida). El más caro de
             la lista y también el que mejor sigue instrucciones de formato.

Antes del LLM hay un pre-filtro determinista (palabras clave y longitud) que
descarta ruido gratis. Es la diferencia entre 300 y 120 llamadas al día.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Optional

import requests

from models import Item, Verdict
from prompts import OUTPUT_SCHEMA, SYSTEM_PROMPT, build_user_prompt
from util import USER_AGENT

log = logging.getLogger("democles.agent")

# ---------------------------------------------------------------- pre-filtro
MMA_KEYWORDS = re.compile(
    r"\b(ufc|mma|bellator|pfl|one championship|octag|octog|peleador|fighter|"
    r"knockout|nocaut|ko\b|tko|submission|sumisi|title|t[ií]tulo|campe[oó]n|"
    r"champion|main event|estelar|cartelera|card\b|weigh|pesaje|dana white|"
    r"grappling|jiu[- ]?jitsu|muay thai|welterweight|lightweight|middleweight|"
    r"heavyweight|flyweight|bantamweight|featherweight|peso\s+\w+|fight night|"
    r"pay[- ]?per[- ]?view|ppv|noche ufc)\b",
    re.IGNORECASE,
)
BLOCKLIST = re.compile(
    r"\b(apuesta|betting odds|promo code|c[oó]digo promocional|casino|"
    r"suscr[ií]bete|patrocinado|sponsored|advertisement)\b",
    re.IGNORECASE,
)
# Google News cuela fichas de producto de Amazon y similares: contienen "MMA"
# y "Muay Thai" pero no son noticias. Se filtran gratis, antes del LLM.
COMMERCE = re.compile(
    r"\b(comprar|oferta[s]?\b|descuento|mejor precio|amazon|aliexpress|"
    r"guantes de|manoplas|saco de boxeo|espinilleras|rese[ñn]a de producto|"
    r"best deals|buy now|shop\b)\b",
    re.IGNORECASE,
)


def prefilter(item: Item) -> Optional[str]:
    """Devuelve el motivo del descarte, o None si el item merece una llamada al LLM."""
    haystack = f"{item.title} {item.summary}"
    if len(item.title.strip()) < 15:
        return "titular demasiado corto"
    if BLOCKLIST.search(haystack):
        return "contenido promocional / apuestas"
    if COMMERCE.search(haystack):
        return "ficha de producto / e-commerce"
    # Los envíos manuales ya han pasado un filtro humano: no se les aplica keyword gate.
    if item.source_type in ("instagram", "manual"):
        return None
    if not MMA_KEYWORDS.search(haystack):
        return "sin señales de MMA en titular ni resumen"
    return None


# ---------------------------------------------------------------- utilidades
def extract_json(text: str) -> dict:
    """Tolera ```json ... ```, prosa alrededor y un SEGUNDO objeto pegado detrás."""
    if not text:
        raise ValueError("respuesta vacía del LLM")
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.S)
    if fence:
        cleaned = fence.group(1).strip()
    start = cleaned.find("{")
    if start == -1:
        raise ValueError(f"no se encontró un objeto JSON en: {text[:200]!r}")

    # raw_decode se para al cerrar el PRIMER objeto completo. Con rfind('}')
    # abarcábamos hasta la última llave del texto, así que una respuesta con dos
    # objetos seguidos reventaba con 'Extra data: line 7 column 1'.
    try:
        objeto, _ = json.JSONDecoder().raw_decode(cleaned[start:])
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"JSON inválido o incompleto ({exc}) en: {text[:200]!r}"
        ) from exc
    if not isinstance(objeto, dict):
        raise ValueError(f"se esperaba un objeto JSON, llegó {type(objeto).__name__}")
    return objeto


class LLMError(RuntimeError):
    """Fallo de la llamada al modelo (red, cuota, respuesta ilegible)."""


# ---------------------------------------------------------------- proveedores
def _call_gemini(system: str, user: str, model: str, max_tokens: int) -> str:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise LLMError("falta GEMINI_API_KEY")
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        f"?key={key}"
    )
    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {
            "temperature": 0.4,
            "maxOutputTokens": max_tokens,
            "response_mime_type": "application/json",
        },
    }
    resp = requests.post(url, json=payload, timeout=90,
                         headers={"User-Agent": USER_AGENT})
    if resp.status_code != 200:
        raise LLMError(f"Gemini HTTP {resp.status_code}: {resp.text[:250]}")

    data = resp.json()
    candidatos = data.get("candidates") or []
    if not candidatos:
        raise LLMError(f"Gemini no devolvió candidatos: {str(data)[:250]}")

    candidato = candidatos[0]
    fin = candidato.get("finishReason")
    if fin == "MAX_TOKENS":
        # Los modelos Gemini 3.x razonan antes de responder y esos tokens salen
        # del MISMO presupuesto que la respuesta. Con maxOutputTokens bajo, el
        # JSON se corta a media frase y el error resultante es indescifrable.
        pensados = (data.get("usageMetadata") or {}).get("thoughtsTokenCount")
        raise LLMError(
            f"respuesta cortada por maxOutputTokens={max_tokens} "
            f"(el modelo gastó {pensados} tokens razonando). Sube LLM_MAX_TOKENS."
        )

    for parte in (candidato.get("content") or {}).get("parts") or []:
        if "text" in parte:
            return parte["text"]
    raise LLMError(f"Gemini no devolvió texto (finishReason={fin}): {str(data)[:250]}")


def _call_openai_compatible(
    system: str, user: str, model: str, max_tokens: int, base_url: str, api_key: str
) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.4,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    resp = requests.post(
        f"{base_url}/chat/completions",
        json=payload,
        timeout=90,
        headers={"Authorization": f"Bearer {api_key}", "User-Agent": USER_AGENT},
    )
    if resp.status_code != 200:
        raise LLMError(f"{base_url} HTTP {resp.status_code}: {resp.text[:250]}")
    try:
        return resp.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise LLMError(f"respuesta inesperada: {resp.text[:250]}") from exc


def _call_anthropic(system: str, user: str, model: str, max_tokens: int) -> str:
    try:
        import anthropic
    except ImportError as exc:
        raise LLMError("instala el SDK: pip install anthropic") from exc

    client = anthropic.Anthropic()  # lee ANTHROPIC_API_KEY del entorno
    kwargs = {
        "model": model,
        # max_tokens deliberadamente bajo: es una tarea de clasificación con tope
        # de coste, no generación larga. Un briefing completo cabe en ~600 tokens.
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    try:
        # Salida estructurada: garantiza JSON válido en Haiku 4.5.
        message = client.messages.create(
            **kwargs,
            output_config={"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
        )
    except Exception as exc:  # noqa: BLE001 - modelos antiguos sin structured outputs
        log.debug("Salida estructurada no disponible (%s); se usa texto plano", exc)
        message = client.messages.create(**kwargs)

    if getattr(message, "stop_reason", None) == "refusal":
        raise LLMError("el modelo rechazó la petición (stop_reason=refusal)")
    if getattr(message, "stop_reason", None) == "max_tokens":
        raise LLMError(f"respuesta cortada por max_tokens={max_tokens}; súbelo")
    for block in message.content:
        if block.type == "text":
            return block.text
    raise LLMError("Anthropic no devolvió ningún bloque de texto")


def _dispatch(provider: str, system: str, user: str, model: str, max_tokens: int) -> str:
    if provider == "gemini":
        return _call_gemini(system, user, model, max_tokens)
    if provider == "groq":
        return _call_openai_compatible(
            system, user, model, max_tokens,
            "https://api.groq.com/openai/v1", _require("GROQ_API_KEY"))
    if provider == "openai":
        return _call_openai_compatible(
            system, user, model, max_tokens,
            "https://api.openai.com/v1", _require("OPENAI_API_KEY"))
    if provider == "together":
        return _call_openai_compatible(
            system, user, model, max_tokens,
            "https://api.together.xyz/v1", _require("TOGETHER_API_KEY"))
    if provider == "anthropic":
        return _call_anthropic(system, user, model, max_tokens)
    raise LLMError(f"proveedor desconocido: {provider}")


# Errores que justifican probar el siguiente modelo en lugar de abortar:
# cuota agotada (429) o modelo retirado para claves nuevas (404).
_MODELO_AGOTADO = re.compile(
    r"\b(429|404)\b|RESOURCE_EXHAUSTED|NOT_FOUND|quota|no longer available",
    re.IGNORECASE,
)


def call_llm(system: str, user: str) -> str:
    """Llama al modelo. LLM_MODEL admite una LISTA separada por comas.

    Los proveedores retiran modelos y agotan cuotas sin avisar. Con una cadena
    de respaldo, un 429 en el primero pasa al siguiente en vez de tumbar el ciclo.
    """
    provider = os.getenv("LLM_PROVIDER", "gemini").lower()
    crudo = os.getenv("LLM_MODEL") or _default_model(provider)
    modelos = [m.strip() for m in crudo.split(",") if m.strip()]
    # 4000 y no 1200: un briefing ocupa ~450 tokens, pero los modelos con
    # razonamiento (Gemini 3.x) consumen 700-1200 más del mismo presupuesto.
    # Medido: pensamiento 720-1161 tok. Con 1200 fallaba ~1 de cada 3 noticias.
    max_tokens = int(os.getenv("LLM_MAX_TOKENS", "4000"))

    ultimo: Optional[LLMError] = None
    for indice, modelo in enumerate(modelos):
        try:
            return _dispatch(provider, system, user, modelo, max_tokens)
        except LLMError as exc:
            ultimo = exc
            queda_alternativa = indice < len(modelos) - 1
            if queda_alternativa and _MODELO_AGOTADO.search(str(exc)):
                log.warning("Modelo '%s' no disponible (%s); probando '%s'",
                            modelo, str(exc)[:80], modelos[indice + 1])
                continue
            raise
    raise ultimo or LLMError("LLM_MODEL está vacío")


def _require(var: str) -> str:
    value = os.getenv(var)
    if not value:
        raise LLMError(f"falta la variable {var}")
    return value


def _default_model(provider: str) -> str:
    """Cadenas por defecto. Verificadas contra la API el 2026-08-10.

    Aviso: los modelos gemini-2.x devuelven 404 'no longer available to new users'
    para claves creadas a partir de 2026. No los pongas como primera opción.
    """
    # gemini-3.6-flash va el ÚLTIMO a propósito: en producción devuelve 429 en
    # todas las llamadas (cuota gratuita mínima), y tenerlo primero desperdiciaba
    # una petición fallida por cada noticia antes de degradar.
    return {
        "gemini": "gemini-3.5-flash,gemini-3.5-flash-lite,gemini-3.6-flash",
        "groq": "llama-3.3-70b-versatile",
        "openai": "gpt-4o-mini",
        "together": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "anthropic": "claude-haiku-4-5",
    }.get(provider, "gemini-3.6-flash,gemini-3.5-flash-lite")


# ---------------------------------------------------------------- API pública
def analyze(item: Item, *, threshold: int = 7, retries: int = 1) -> Verdict:
    """Clasifica y (si procede) genera el briefing. Una única llamada al modelo."""
    user_prompt = build_user_prompt(item)
    last_error: Optional[Exception] = None

    for attempt in range(retries + 1):
        try:
            raw = call_llm(SYSTEM_PROMPT, user_prompt)
            verdict = Verdict.from_dict(extract_json(raw))
            return _enforce(verdict, threshold)
        except (LLMError, ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            log.warning("Agente falló (%s/%s) en '%s': %s",
                        attempt + 1, retries + 1, item.title[:60], exc)
            if attempt < retries:
                time.sleep(2 + 3 * attempt)

    raise LLMError(f"el agente no produjo un veredicto válido: {last_error}")


def _enforce(verdict: Verdict, threshold: int) -> Verdict:
    """El umbral lo decide el código, no el modelo. El modelo sólo puntúa."""
    should_send = verdict.relevancia >= threshold
    if verdict.incluir_en_telegram != should_send:
        log.debug("Corregido incluir_en_telegram: %s -> %s (relevancia %s, umbral %s)",
                  verdict.incluir_en_telegram, should_send, verdict.relevancia, threshold)
        verdict.incluir_en_telegram = should_send
    if not should_send:
        verdict.briefing = None
    elif verdict.briefing is None:
        # Aprobado sin briefing: se envía igual, marcado, en vez de perder la noticia.
        log.warning("Relevancia %s sin briefing; se envía en modo reducido", verdict.relevancia)
    else:
        verdict.briefing.hashtags = verdict.briefing.hashtags[:12]
    return verdict
