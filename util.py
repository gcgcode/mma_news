"""Utilidades compartidas: HTTP educado, robots.txt, normalización de texto."""
from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
import unicodedata
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import requests

log = logging.getLogger("democles.util")

USER_AGENT = (
    "Mozilla/5.0 (compatible; DemoclesMMABot/1.0; uso personal; "
    "contacto: alcorex.tech@gmail.com)"
)

_TRACKING_PREFIXES = ("utm_", "mc_", "pk_", "at_")
_TRACKING_EXACT = {
    "fbclid", "gclid", "igshid", "ref", "ref_src", "ref_url", "s", "t",
    "cmpid", "smid", "sr_share", "guccounter", "guce_referrer", "amp",
}

_last_request: dict[str, float] = {}
_robots_cache: dict[str, Optional[RobotFileParser]] = {}
_lock = threading.Lock()

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "es,en;q=0.8"})


# --------------------------------------------------------------------------
# URLs
# --------------------------------------------------------------------------
def domain_of(url: str) -> str:
    try:
        return urlsplit(url).netloc.lower().removeprefix("www.")
    except ValueError:
        return ""


def canonical_url(url: str) -> str:
    """URL estable para deduplicar: sin fragmento, sin params de tracking."""
    if not url:
        return ""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip()

    netloc = parts.netloc.lower().removeprefix("www.")
    # Espejos de Twitter -> dominio canónico
    if netloc in {"nitter.net", "xcancel.com", "twitter.com"} or netloc.startswith("nitter."):
        netloc = "x.com"

    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=False)
        if not k.lower().startswith(_TRACKING_PREFIXES) and k.lower() not in _TRACKING_EXACT
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme or "https", netloc, path, urlencode(sorted(query)), ""))


def sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", "ignore")).hexdigest()


# --------------------------------------------------------------------------
# Normalización de titulares (para deduplicar entre fuentes)
# --------------------------------------------------------------------------
_STOPWORDS = {
    "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "y", "o",
    "en", "por", "para", "con", "su", "sus", "al", "se", "que", "es", "the", "a",
    "an", "of", "for", "to", "in", "on", "at", "is", "was", "his", "her", "and",
    "with", "from", "as", "by", "it", "he", "she",
}
_LEAD_NOISE = re.compile(
    r"^(breaking|ultima hora|ultimo minuto|oficial|official|report|informe|video|"
    r"watch|exclusiva|exclusive|rumor|confirmado|confirmed)\s*[:\-–]\s*",
    re.IGNORECASE,
)


def strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )


def normalize_title(title: str) -> str:
    """Titular reducido a su esqueleto semántico, comparable entre idiomas/medios."""
    if not title:
        return ""
    t = _LEAD_NOISE.sub("", title.strip())
    t = strip_accents(t).lower()
    t = re.sub(r"[^a-z0-9áéíóúñ\s]", " ", t)
    tokens = [w for w in t.split() if len(w) > 1 and w not in _STOPWORDS]
    return " ".join(tokens)


def clean_html(raw: str, limit: int = 1200) -> str:
    """Quita etiquetas y colapsa espacios. Para resúmenes de RSS."""
    if not raw:
        return ""
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", raw, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = (
        text.replace("&nbsp;", " ").replace("&amp;", "&")
        .replace("&quot;", '"').replace("&#39;", "'")
        .replace("&lt;", "<").replace("&gt;", ">")
    )
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def to_iso(value) -> Optional[str]:
    """Acepta struct_time, datetime, epoch o string ISO. Devuelve ISO UTC o None."""
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc).isoformat(timespec="seconds")
        if isinstance(value, time.struct_time):
            return datetime.fromtimestamp(
                time.mktime(value), tz=timezone.utc
            ).isoformat(timespec="seconds")
        if isinstance(value, datetime):
            dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat(timespec="seconds")
        from dateutil import parser as dateparser  # import perezoso

        dt = dateparser.parse(str(value))
        if dt is None:
            return None
        dt = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat(timespec="seconds")
    except Exception:  # noqa: BLE001 - fechas rotas son habituales en RSS
        return None


# --------------------------------------------------------------------------
# robots.txt + rate limiting
# --------------------------------------------------------------------------
def _robots_for(scheme: str, netloc: str) -> Optional[RobotFileParser]:
    base = f"{scheme}://{netloc}"
    with _lock:
        if base in _robots_cache:
            return _robots_cache[base]
    parser: Optional[RobotFileParser] = None
    try:
        resp = _SESSION.get(f"{base}/robots.txt", timeout=10)
        if resp.status_code == 200 and resp.text:
            parser = RobotFileParser()
            parser.parse(resp.text.splitlines())
    except requests.RequestException as exc:
        log.debug("robots.txt inaccesible en %s: %s", base, exc)
    with _lock:
        _robots_cache[base] = parser
    return parser


def robots_allows(url: str) -> bool:
    """True si robots.txt permite (o no existe / no se pudo leer)."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    parser = _robots_for(parts.scheme or "https", parts.netloc)
    if parser is None:
        return True
    return parser.can_fetch(USER_AGENT, url)


def _throttle(host: str, min_interval: float) -> None:
    with _lock:
        last = _last_request.get(host, 0.0)
        wait = min_interval - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)
        _last_request[host] = time.monotonic()


def polite_get(
    url: str,
    *,
    min_interval: float = 2.0,
    timeout: int = 25,
    retries: int = 2,
    respect_robots: bool = True,
    headers: Optional[dict] = None,
) -> Optional[requests.Response]:
    """GET con User-Agent identificable, robots.txt, rate limit por dominio y reintentos."""
    if respect_robots and not robots_allows(url):
        log.warning("robots.txt prohíbe %s — se omite", url)
        return None

    host = urlsplit(url).netloc
    for attempt in range(retries + 1):
        _throttle(host, min_interval)
        try:
            resp = _SESSION.get(url, timeout=timeout, headers=headers)
        except requests.RequestException as exc:
            log.warning("GET falló (%s/%s) %s: %s", attempt + 1, retries + 1, url, exc)
            time.sleep(2 ** attempt)
            continue
        # Cualquier 2xx: ESPN responde 202 a las peticiones desde datacenter y
        # el cuerpo trae el feed igualmente. Si viniera vacío, quien parsea ya
        # se queja; descartarlo aquí nos costaba la fuente entera.
        if 200 <= resp.status_code < 300:
            return resp
        if resp.status_code in (429, 500, 502, 503, 504):
            espera = 2 ** attempt + 1
            # Si el servidor nos dice cuánto esperar (Reddit lo hace), obedecemos.
            cabecera = resp.headers.get("Retry-After", "")
            if cabecera.strip().isdigit():
                espera = min(max(espera, int(cabecera)), 45)
            log.warning("HTTP %s en %s — reintento en %ss", resp.status_code, url, espera)
            time.sleep(espera)
            continue
        log.warning("HTTP %s en %s — se descarta", resp.status_code, url)
        return None
    return None
