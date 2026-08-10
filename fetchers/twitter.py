"""Twitter/X sin API de pago: cadena de estrategias con degradación elegante.

Orden configurable en TWITTER_STRATEGY (por defecto "rsshub,nitter"):

  1. rsshub  — RSSHub auto-hospedado. Gratis en infraestructura propia, pero la
               ruta de Twitter necesita cookie/token de una cuenta quemable y se
               rompe cuando X cambia su front-end. Fiabilidad media.
  2. nitter  — espejos públicos. Prácticamente muertos desde que X eliminó las
               guest accounts; algunos forks sobreviven. Fiabilidad baja.
  3. apify   — actor de scraping de pago con créditos gratuitos mensuales.
               Fiabilidad alta, pero el crédito no da para 48 ejecuciones/día:
               úsalo con cadencia baja o sólo en semanas de evento.

Si todas fallan, la función devuelve [] y el sistema sigue con Reddit y webs,
que es donde de todas formas rebota el 90% del contenido de estas cuentas.
"""
from __future__ import annotations

import logging
import os

import feedparser
import requests

from fetchers.base import FetchError, register
from models import Item
from util import USER_AGENT, clean_html, polite_get, to_iso

log = logging.getLogger("democles.fetchers.twitter")


def _strategies() -> list[str]:
    raw = os.getenv("TWITTER_STRATEGY", "rsshub,nitter")
    return [s.strip().lower() for s in raw.split(",") if s.strip()]


def _mk_item(source: dict, handle: str, title: str, url: str, published, summary="") -> Item:
    return Item(
        source=f"@{handle}",
        source_type="twitter",
        title=title,
        url=url,
        published_at=to_iso(published),
        summary=summary,
        author=f"@{handle}",
        priority=int(source.get("prioridad", 2)),
        lang=source.get("idioma", "es"),
        extra={"handle": handle},
    )


# ---------------------------------------------------------------- RSSHub
def _via_rsshub(handle: str, source: dict) -> list[Item]:
    base = os.getenv("RSSHUB_BASE", "").rstrip("/")
    if not base:
        raise FetchError("RSSHUB_BASE no configurado")
    # [verificar ruta] RSSHub cambia rutas entre versiones; comprueba /twitter/user/:id
    url = f"{base}/twitter/user/{handle}"
    key = os.getenv("RSSHUB_ACCESS_KEY", "")
    if key:
        url += f"?key={key}"
    resp = polite_get(url, min_interval=1.5, respect_robots=False, retries=1)
    if resp is None:
        raise FetchError(f"RSSHub no respondió para @{handle}")
    parsed = feedparser.parse(resp.content)
    if not parsed.entries:
        raise FetchError(f"RSSHub devolvió 0 entradas para @{handle}")
    items = []
    for entry in parsed.entries:
        text = clean_html(entry.get("title") or entry.get("summary") or "", 400)
        link = entry.get("link") or ""
        if not text or not link:
            continue
        items.append(
            _mk_item(source, handle, text, link,
                     entry.get("published_parsed") or entry.get("published"),
                     clean_html(entry.get("summary") or "", 600))
        )
    return items


# ---------------------------------------------------------------- Nitter
def _via_nitter(handle: str, source: dict) -> list[Item]:
    mirrors = [m.strip().rstrip("/") for m in os.getenv("NITTER_MIRRORS", "").split(",") if m.strip()]
    if not mirrors:
        raise FetchError("NITTER_MIRRORS no configurado")
    for mirror in mirrors:
        try:
            resp = polite_get(f"{mirror}/{handle}/rss", min_interval=3.0,
                              respect_robots=False, retries=0, timeout=15)
        except Exception as exc:  # noqa: BLE001
            log.debug("Espejo %s falló: %s", mirror, exc)
            continue
        if resp is None:
            continue
        parsed = feedparser.parse(resp.content)
        if not parsed.entries:
            continue
        items = []
        for entry in parsed.entries:
            text = clean_html(entry.get("title") or "", 400)
            link = (entry.get("link") or "").replace(mirror, "https://x.com")
            if not text or not link:
                continue
            items.append(_mk_item(source, handle, text, link, entry.get("published_parsed")))
        if items:
            return items
    raise FetchError(f"ningún espejo Nitter respondió para @{handle}")


# ---------------------------------------------------------------- Apify
def _via_apify(handles: list[str], source: dict) -> list[Item]:
    token = os.getenv("APIFY_TOKEN", "")
    if not token:
        raise FetchError("APIFY_TOKEN no configurado")
    actor = os.getenv("APIFY_ACTOR", "apidojo~tweet-scraper")
    url = f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items?token={token}"
    payload = {
        # Una sola llamada para todas las cuentas: minimiza el consumo de créditos.
        "twitterHandles": handles,
        "maxItems": int(source.get("apify_max_items", 30)),
        "sort": "Latest",
    }
    try:
        resp = requests.post(url, json=payload, timeout=180,
                             headers={"User-Agent": USER_AGENT})
    except requests.RequestException as exc:
        raise FetchError(f"Apify no respondió: {exc}") from exc
    if resp.status_code >= 300:
        raise FetchError(f"Apify HTTP {resp.status_code}: {resp.text[:200]}")

    items = []
    for row in resp.json() or []:
        text = (row.get("text") or row.get("full_text") or "").strip()
        link = row.get("url") or row.get("twitterUrl") or ""
        handle = ((row.get("author") or {}).get("userName")) or row.get("username") or "?"
        if not text or not link:
            continue
        items.append(_mk_item(source, handle, text[:300], link, row.get("createdAt")))
    return items


# --------------------------------------------------------------------------
@register("twitter")
def fetch_twitter(source: dict, ctx: dict) -> list[Item]:
    handles = [h.lstrip("@") for h in source.get("cuentas", [])]
    if not handles:
        raise FetchError("la fuente twitter no tiene 'cuentas'")

    strategies = _strategies()
    if not strategies:
        log.info("Twitter desactivado (TWITTER_STRATEGY vacío)")
        return []

    items: list[Item] = []
    failures: list[str] = []

    for strategy in strategies:
        if strategy == "apify":
            try:
                items.extend(_via_apify(handles, source))
                log.info("Twitter vía apify: %s items", len(items))
                return items
            except FetchError as exc:
                failures.append(f"apify: {exc}")
                continue

        per_handle = {"rsshub": _via_rsshub, "nitter": _via_nitter}.get(strategy)
        if per_handle is None:
            failures.append(f"estrategia desconocida: {strategy}")
            continue

        ok = 0
        for handle in handles:
            try:
                items.extend(per_handle(handle, source))
                ok += 1
            except FetchError as exc:
                log.debug("[%s] @%s: %s", strategy, handle, exc)
        if ok:
            log.info("Twitter vía %s: %s/%s cuentas, %s items",
                     strategy, ok, len(handles), len(items))
            return items
        failures.append(f"{strategy}: 0/{len(handles)} cuentas")

    log.warning("Twitter sin datos. Intentos: %s", " | ".join(failures))
    return []
