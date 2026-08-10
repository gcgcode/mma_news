"""Reddit como agregador. Es la fuente gratuita más fiable del sistema.

Dos adaptadores:
  * reddit      -> API oficial con app "script" (OAuth client_credentials). Gratis,
                   funciona desde IPs de datacenter (GitHub Actions). Recomendado.
  * reddit_rss  -> .rss público, sin credenciales. Respaldo; Reddit devuelve 403
                   con frecuencia desde datacenters y el feed no trae score.
"""
from __future__ import annotations

import logging
import os
import time

import feedparser
import requests

from fetchers.base import FetchError, register
from models import Item
from util import USER_AGENT, clean_html, polite_get, to_iso

log = logging.getLogger("democles.fetchers.reddit")

_TOKEN: dict[str, float | str] = {"value": "", "expires": 0.0}


def _reddit_ua() -> str:
    return os.getenv("REDDIT_USER_AGENT") or "democles-mma-bot/1.0"


def _get_token() -> str:
    """Token de aplicación (client_credentials). Se cachea durante la ejecución."""
    if _TOKEN["value"] and time.time() < float(_TOKEN["expires"]):
        return str(_TOKEN["value"])

    client_id = os.getenv("REDDIT_CLIENT_ID", "")
    secret = os.getenv("REDDIT_CLIENT_SECRET", "")
    if not client_id or not secret:
        raise FetchError("faltan REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET")

    try:
        resp = requests.post(
            "https://www.reddit.com/api/v1/access_token",
            auth=(client_id, secret),
            data={"grant_type": "client_credentials"},
            headers={"User-Agent": _reddit_ua()},
            timeout=20,
        )
    except requests.RequestException as exc:
        raise FetchError(f"no se pudo pedir token a Reddit: {exc}") from exc
    if resp.status_code != 200:
        raise FetchError(f"Reddit token HTTP {resp.status_code}: {resp.text[:150]}")

    payload = resp.json()
    _TOKEN["value"] = payload.get("access_token", "")
    _TOKEN["expires"] = time.time() + int(payload.get("expires_in", 3600)) - 60
    if not _TOKEN["value"]:
        raise FetchError("Reddit devolvió un token vacío")
    return str(_TOKEN["value"])


@register("reddit")
def fetch_reddit(source: dict, ctx: dict) -> list[Item]:
    subreddit = source.get("subreddit")
    if not subreddit:
        raise FetchError("la fuente reddit no tiene 'subreddit'")

    listing = source.get("listing", "new")          # new | hot | rising | top
    limit = int(source.get("max_items", 25))
    min_score = int(source.get("min_score", 0))
    token = _get_token()

    url = f"https://oauth.reddit.com/r/{subreddit}/{listing}"
    try:
        resp = requests.get(
            url,
            params={"limit": limit, "raw_json": 1},
            headers={"Authorization": f"Bearer {token}", "User-Agent": _reddit_ua()},
            timeout=25,
        )
    except requests.RequestException as exc:
        raise FetchError(f"Reddit no respondió: {exc}") from exc
    if resp.status_code != 200:
        raise FetchError(f"Reddit HTTP {resp.status_code}: {resp.text[:150]}")

    items: list[Item] = []
    for child in resp.json().get("data", {}).get("children", []):
        post = child.get("data", {})
        if post.get("stickied") or post.get("over_18"):
            continue
        score = int(post.get("score", 0))
        if score < min_score:
            continue
        title = (post.get("title") or "").strip()
        if not title:
            continue

        # Enlace externo si lo hay (la noticia real); si no, el hilo de Reddit.
        external = post.get("url_overridden_by_dest") or ""
        permalink = "https://www.reddit.com" + post.get("permalink", "")
        target = external if external.startswith("http") and "reddit.com" not in external else permalink

        items.append(
            Item(
                source=f"r/{subreddit}",
                source_type="reddit",
                title=title,
                url=target,
                published_at=to_iso(post.get("created_utc")),
                summary=clean_html(post.get("selftext", ""), 800),
                author=f"u/{post.get('author', '?')}",
                priority=int(source.get("prioridad", 3)),
                lang=source.get("idioma", "en"),
                extra={
                    "score": score,
                    "num_comments": int(post.get("num_comments", 0)),
                    "flair": post.get("link_flair_text") or "",
                    "permalink": permalink,
                },
            )
        )
    return items


@register("reddit_rss")
def fetch_reddit_rss(source: dict, ctx: dict) -> list[Item]:
    subreddit = source.get("subreddit")
    if not subreddit:
        raise FetchError("la fuente reddit_rss no tiene 'subreddit'")
    listing = source.get("listing", "new")
    url = f"https://www.reddit.com/r/{subreddit}/{listing}/.rss"

    # Reddit limita el RSS con dureza y desde IPs de datacenter (GitHub Actions)
    # aún más: medido en producción, 8 s entre subreddits no bastan y el segundo
    # se come cuatro 429 seguidos. Se separa más y se reintenta menos: insistir
    # no ayuda y nos costaba 40 s de ciclo para acabar fallando igual.
    resp = polite_get(url, min_interval=float(source.get("intervalo_min", 20.0)),
                      respect_robots=False, retries=int(source.get("reintentos", 1)),
                      headers={"User-Agent": _reddit_ua() or USER_AGENT})
    if resp is None:
        raise FetchError(
            "Reddit RSS no respondió (429/403; habitual desde IPs de datacenter)"
        )

    parsed = feedparser.parse(resp.content)
    items = []
    for entry in parsed.entries:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        if not title or not link:
            continue
        items.append(
            Item(
                source=f"r/{subreddit}",
                source_type="reddit",
                title=title,
                url=link,
                published_at=to_iso(entry.get("published_parsed") or entry.get("updated_parsed")),
                summary=clean_html(entry.get("summary", ""), 600),
                author=(entry.get("author") or "").strip(),
                priority=int(source.get("prioridad", 3)),
                lang=source.get("idioma", "en"),
                extra={"adaptador": "reddit_rss"},
            )
        )
    return items
