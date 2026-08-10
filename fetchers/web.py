"""Fuentes web: RSS nativo, Google News RSS y scraping HTML con selectores CSS.

Tres adaptadores:
  * rss   -> feed Atom/RSS declarado en config.yaml
  * gnews -> Google News RSS con `site:` (respaldo universal, no requiere descubrir feeds)
  * html  -> scraping con selectores CSS, sujeto a robots.txt
"""
from __future__ import annotations

import logging
from urllib.parse import quote_plus, urljoin

import feedparser

from fetchers.base import FetchError, register
from models import Item
from util import clean_html, polite_get, to_iso

log = logging.getLogger("democles.fetchers.web")

GNEWS_TEMPLATE = "https://news.google.com/rss/search?q={query}&hl={hl}&gl={gl}&ceid={gl}:{lang}"


def _parse_feed(url: str, *, min_interval: float, respect_robots: bool = True):
    """Descarga con nuestro User-Agent y deja que feedparser sólo parsee."""
    resp = polite_get(url, min_interval=min_interval, respect_robots=respect_robots)
    if resp is None:
        raise FetchError(f"no se pudo descargar el feed {url}")
    parsed = feedparser.parse(resp.content)
    if parsed.bozo and not parsed.entries:
        raise FetchError(f"feed ilegible en {url}: {parsed.get('bozo_exception')}")
    return parsed


def _entry_to_item(entry, source: dict, *, source_type: str = "web") -> Item | None:
    title = (entry.get("title") or "").strip()
    link = (entry.get("link") or "").strip()
    if not title or not link:
        return None
    summary = clean_html(entry.get("summary") or entry.get("description") or "")
    published = to_iso(
        entry.get("published_parsed")
        or entry.get("updated_parsed")
        or entry.get("published")
        or entry.get("updated")
    )
    return Item(
        source=source.get("name", "?"),
        source_type=source_type,
        title=title,
        url=link,
        published_at=published,
        summary=summary,
        author=(entry.get("author") or "").strip(),
        priority=int(source.get("prioridad", 3)),
        lang=source.get("idioma", "es"),
        extra={"adaptador": source["adaptador"]},
    )


# --------------------------------------------------------------------------
@register("rss")
def fetch_rss(source: dict, ctx: dict) -> list[Item]:
    url = source.get("url")
    if not url:
        raise FetchError("la fuente rss no tiene 'url'")
    parsed = _parse_feed(url, min_interval=float(source.get("intervalo_min", 2.0)))
    items = [_entry_to_item(e, source) for e in parsed.entries]
    return [i for i in items if i]


# --------------------------------------------------------------------------
@register("gnews")
def fetch_gnews(source: dict, ctx: dict) -> list[Item]:
    """Respaldo universal: Google News RSS. Endpoint público y estable.

    Útil cuando un medio no publica RSS o cuando su feed cambia de ruta.
    `query` admite operadores de Google News: site:, comillas, OR.
    """
    query = source.get("query")
    if not query:
        raise FetchError("la fuente gnews no tiene 'query'")
    hl = source.get("hl", "es-419")
    gl = source.get("gl", "US")
    lang = source.get("idioma", "es")
    url = GNEWS_TEMPLATE.format(query=quote_plus(query), hl=hl, gl=gl, lang=lang)

    # news.google.com no requiere robots-check por feed público de búsqueda.
    parsed = _parse_feed(url, min_interval=3.0, respect_robots=False)
    items: list[Item] = []
    for entry in parsed.entries:
        item = _entry_to_item(entry, source)
        if not item:
            continue
        # Google News antepone " - Medio" al titular; lo movemos a `source`.
        if " - " in item.title:
            head, _, tail = item.title.rpartition(" - ")
            if head and len(tail) < 40:
                item.title = head.strip()
                item.extra["medio"] = tail.strip()
        items.append(item)
    return items


# --------------------------------------------------------------------------
@register("html")
def fetch_html(source: dict, ctx: dict) -> list[Item]:
    """Scraping con selectores CSS declarados en config.yaml.

    Claves esperadas en la fuente:
        url, selector_lista, selector_titulo, selector_enlace (opcional),
        selector_fecha (opcional), selector_resumen (opcional)
    Sólo fragmentos + enlace: nunca copiamos el artículo completo.
    """
    from bs4 import BeautifulSoup  # import perezoso: sólo si hay fuentes html

    url = source.get("url")
    if not url:
        raise FetchError("la fuente html no tiene 'url'")
    sel_list = source.get("selector_lista")
    sel_title = source.get("selector_titulo")
    if not sel_list or not sel_title:
        raise FetchError("faltan 'selector_lista' o 'selector_titulo'")

    resp = polite_get(url, min_interval=float(source.get("intervalo_min", 4.0)))
    if resp is None:
        raise FetchError(f"no se pudo descargar {url}")

    soup = BeautifulSoup(resp.text, "lxml")
    items: list[Item] = []
    for node in soup.select(sel_list):
        title_node = node.select_one(sel_title)
        if not title_node:
            continue
        title = title_node.get_text(strip=True)

        link_node = node.select_one(source["selector_enlace"]) if source.get("selector_enlace") else title_node
        href = link_node.get("href") if link_node else None
        if not href and link_node is not None:
            anchor = link_node.find("a")
            href = anchor.get("href") if anchor else None
        if not title or not href:
            continue

        summary = ""
        if source.get("selector_resumen"):
            node_sum = node.select_one(source["selector_resumen"])
            summary = node_sum.get_text(" ", strip=True)[:600] if node_sum else ""

        published = None
        if source.get("selector_fecha"):
            node_date = node.select_one(source["selector_fecha"])
            if node_date is not None:
                published = to_iso(node_date.get("datetime") or node_date.get_text(strip=True))

        items.append(
            Item(
                source=source.get("name", "?"),
                source_type="web",
                title=title,
                url=urljoin(url, href),
                published_at=published,
                summary=summary,
                priority=int(source.get("prioridad", 3)),
                lang=source.get("idioma", "es"),
                extra={"adaptador": "html"},
            )
        )
    return items
