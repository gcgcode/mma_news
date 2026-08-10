"""Deduplicación en tres capas.

Una misma noticia llega por r/MMA, MMA Fighting y @arielhelwani en 20 minutos.
Sin esto, el chat de Telegram es inservible.

  Capa 1 — URL canónica: mismo enlace sin params de tracking -> duplicado exacto.
  Capa 2 — Hash de titular normalizado: sin acentos, sin stopwords, sin prefijos
           tipo "BREAKING:". Pilla el mismo titular republicado con otra URL.
  Capa 3 — Similitud difusa (rapidfuzz token_set_ratio) dentro de una ventana
           temporal. Pilla reescrituras: "Jones vacates title" vs
           "Jon Jones vacates heavyweight title".

Dentro de un mismo lote se conserva el item de MAYOR prioridad (config.yaml),
no el primero que llega: si la noticia viene de r/MMA y de MMA Fighting, gana
el medio, que es lo que quieres enlazar.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from rapidfuzz import fuzz

from models import Item
from state import State
from util import now_iso

log = logging.getLogger("democles.dedup")


class Deduplicator:
    def __init__(
        self,
        state: State,
        *,
        window_hours: int = 72,
        fuzzy_threshold: int = 88,
        min_title_tokens: int = 4,
    ) -> None:
        self.state = state
        self.window = timedelta(hours=window_hours)
        self.threshold = fuzzy_threshold
        self.min_title_tokens = min_title_tokens

        cutoff = (datetime.now(timezone.utc) - self.window).isoformat()
        recent = [s for s in state.seen if s.get("ts", "") >= cutoff]
        self._url_keys = {s["key"] for s in state.seen if "key" in s}
        self._title_keys = {s["title_key"] for s in state.seen if s.get("title_key")}
        self._recent_titles = [s.get("title_norm", "") for s in recent if s.get("title_norm")]
        log.debug("Índice de dedup: %s urls, %s titulares recientes",
                  len(self._url_keys), len(self._recent_titles))

    # ------------------------------------------------------------------
    def _fuzzy_hit(self, title_norm: str, corpus: Iterable[str]) -> Optional[str]:
        """Titulares muy cortos no se comparan por similitud: demasiados falsos positivos."""
        if len(title_norm.split()) < self.min_title_tokens:
            return None
        for other in corpus:
            if len(other.split()) < self.min_title_tokens:
                continue
            if fuzz.token_set_ratio(title_norm, other) >= self.threshold:
                return other
        return None

    def duplicate_reason(self, item: Item) -> Optional[str]:
        """Motivo por el que el item ya se ha visto en ejecuciones anteriores, o None."""
        if item.url_key in self._url_keys:
            return "url-repetida"
        if item.title_key in self._title_keys:
            return "titular-identico"
        match = self._fuzzy_hit(item.title_norm, self._recent_titles)
        if match:
            return f"titular-similar ~ '{match[:60]}'"
        return None

    # ------------------------------------------------------------------
    def dedupe_batch(self, items: list[Item]) -> list[Item]:
        """Filtra contra el histórico y colapsa duplicados internos del lote."""
        # Prioridad ascendente (1 = mejor fuente) y, a igualdad, más reciente primero.
        ordered = sorted(
            items,
            key=lambda i: (int(i.priority), i.published_at or ""),
        )

        kept: list[Item] = []
        kept_urls: set[str] = set()
        kept_titles: list[str] = []
        dropped_history = 0
        dropped_batch = 0

        for item in ordered:
            reason = self.duplicate_reason(item)
            if reason:
                log.debug("DESCARTA (histórico, %s): %s", reason, item.title[:70])
                dropped_history += 1
                continue

            if item.url_key in kept_urls:
                dropped_batch += 1
                continue
            if self._fuzzy_hit(item.title_norm, kept_titles):
                log.debug("DESCARTA (lote): %s", item.title[:70])
                dropped_batch += 1
                continue

            kept.append(item)
            kept_urls.add(item.url_key)
            if item.title_norm:
                kept_titles.append(item.title_norm)

        log.info(
            "Dedup: %s entran -> %s únicos (%s ya vistos, %s duplicados del lote)",
            len(items), len(kept), dropped_history, dropped_batch,
        )
        return kept

    # ------------------------------------------------------------------
    def remember(self, item: Item, *, score: Optional[int] = None, sent: bool = False) -> None:
        """Marca el item como procesado. Se llama SIEMPRE, se envíe o no.

        Marcar también los descartados evita reevaluar (y repagar tokens) la
        misma noticia irrelevante en cada ejecución.
        """
        self.state.seen.append(
            {
                "key": item.url_key,
                "title_key": item.title_key,
                "title_norm": item.title_norm,
                "title": item.title[:160],
                "url": item.canonical,
                "source": item.source,
                "ts": now_iso(),
                "score": score,
                "sent": sent,
            }
        )
        self._url_keys.add(item.url_key)
        self._title_keys.add(item.title_key)
        if item.title_norm:
            self._recent_titles.append(item.title_norm)
