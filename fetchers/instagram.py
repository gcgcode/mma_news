"""Instagram: entrada MANUAL vía Telegram. Decisión deliberada, no una carencia.

Por qué no hay scraping automático de Instagram en este proyecto:

  * Instagram exige sesión iniciada para casi todo el contenido público desde 2021;
    el truco `?__a=1` está muerto.
  * Bloquea IPs de datacenter de forma agresiva. GitHub Actions, Oracle Free Tier
    y cualquier VPS caen en ese rango: verás checkpoints y bans en horas, no días.
  * Mantener una "cuenta quemable" con cookies rotando es trabajo semanal y viola
    los Términos de Uso de la plataforma.
  * RSSHub tiene rutas de Instagram, pero necesitan esa misma cookie de sesión:
    trasladan el problema, no lo resuelven.
  * Y lo decisivo: las 14 cuentas de la lista publican en Instagram lo mismo que
    en X, casi siempre después. La cobertura real que pierdes es marginal.

Solución adoptada: el humano envía `/add <url>` al bot cuando ve algo en su feed.
El post entra en el mismo pipeline (dedup -> agente -> briefing) que el resto.
Coste: 0 €. Fiabilidad: 100%. Fricción: un mensaje de Telegram.
"""
from __future__ import annotations

import logging
import re

from fetchers.base import register
from models import Item
from util import now_iso

log = logging.getLogger("democles.fetchers.instagram")

INSTAGRAM_URL = re.compile(
    r"https?://(?:www\.)?instagram\.com/(?:p|reel|reels|tv)/[A-Za-z0-9_\-]+", re.IGNORECASE
)


def is_instagram_url(text: str) -> bool:
    return bool(INSTAGRAM_URL.search(text or ""))


@register("instagram_manual")
def fetch_instagram_manual(source: dict, ctx: dict) -> list[Item]:
    """Vacía la cola alimentada por el comando /add del bot de Telegram."""
    state = ctx.get("state")
    if state is None:
        return []

    queue = list(state.manual_queue)
    if not queue:
        return []
    state.data["manual_queue"] = []   # se consume: si falla el ciclo, se re-encolará al reintentar

    items: list[Item] = []
    for entry in queue:
        url = (entry.get("url") or "").strip()
        if not url:
            continue
        note = (entry.get("note") or "").strip()
        is_ig = is_instagram_url(url)
        items.append(
            Item(
                source="Instagram (manual)" if is_ig else "Enlace manual",
                source_type="instagram" if is_ig else "manual",
                # Sin nota, el titular es la propia URL: el agente lee la nota
                # y la URL, y ya avisa si no hay contexto suficiente.
                title=note or f"Post enviado manualmente: {url}",
                url=url,
                published_at=entry.get("ts") or now_iso(),
                summary=note,
                author=str(entry.get("user_id", "")),
                priority=1,          # lo ha filtrado un humano: máxima prioridad
                lang="es",
                extra={"manual": True, "nota_humana": note},
            )
        )
    log.info("Cola manual: %s items recogidos", len(items))
    return items
