"""Modelo de datos normalizado. Todo fetcher devuelve una lista de `Item`."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from util import canonical_url, normalize_title, sha1

SOURCE_TYPES = ("web", "twitter", "reddit", "instagram", "manual")


@dataclass
class Item:
    """Una noticia candidata, ya normalizada e independiente de su origen."""

    source: str                    # nombre legible: "MMA Fighting"
    source_type: str               # web | twitter | reddit | instagram | manual
    title: str
    url: str
    published_at: Optional[str] = None   # ISO-8601 UTC
    summary: str = ""
    body: str = ""                 # texto extraído si lo hay
    author: str = ""
    priority: int = 3              # 1 (máxima) .. 5 — desempata duplicados
    lang: str = "es"
    extra: dict[str, Any] = field(default_factory=dict)

    # ---- claves derivadas -------------------------------------------------
    @property
    def canonical(self) -> str:
        return canonical_url(self.url)

    @property
    def url_key(self) -> str:
        return sha1(self.canonical)

    @property
    def title_norm(self) -> str:
        return normalize_title(self.title)

    @property
    def title_key(self) -> str:
        return sha1(self.title_norm)

    @property
    def short_key(self) -> str:
        """8 caracteres — cabe en el callback_data de Telegram (64 bytes)."""
        return self.url_key[:8]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Item":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class Briefing:
    formato_instagram: str
    justificacion_formato: str
    caption_sugerido: str
    sugerencia_visual: str
    hashtags: list[str]
    angulo_engagement: str


@dataclass
class Verdict:
    """Salida del agente LLM para un `Item`."""

    relevancia: int
    justificacion_relevancia: str
    incluir_en_telegram: bool
    briefing: Optional[Briefing] = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Verdict":
        raw = data.get("briefing")
        briefing = None
        if isinstance(raw, dict):
            hashtags = raw.get("hashtags") or []
            if isinstance(hashtags, str):
                hashtags = [h for h in hashtags.split() if h.startswith("#")]
            briefing = Briefing(
                formato_instagram=str(raw.get("formato_instagram", "")).strip(),
                justificacion_formato=str(raw.get("justificacion_formato", "")).strip(),
                caption_sugerido=str(raw.get("caption_sugerido", "")).strip(),
                sugerencia_visual=str(raw.get("sugerencia_visual", "")).strip(),
                hashtags=[str(h).strip() for h in hashtags if str(h).strip()],
                angulo_engagement=str(raw.get("angulo_engagement", "")).strip(),
            )
        relevancia = int(data.get("relevancia", 0) or 0)
        return cls(
            relevancia=max(1, min(10, relevancia)),
            justificacion_relevancia=str(data.get("justificacion_relevancia", "")).strip(),
            incluir_en_telegram=bool(data.get("incluir_en_telegram", False)),
            briefing=briefing,
        )
