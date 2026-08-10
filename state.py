"""Estado persistente entre ejecuciones (un único JSON, versionado en git)."""
from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("democles.state")

SCHEMA_VERSION = 1


class State:
    """JSON pequeño y diffeable. Sustituible por SQLite si crece mucho."""

    def __init__(self, path: str | os.PathLike = "state/state.json") -> None:
        self.path = Path(path)
        self.data: dict[str, Any] = {
            "version": SCHEMA_VERSION,
            "telegram_offset": 0,
            "seen": [],           # [{key,title_norm,url,ts,score,source,sent}]
            "manual_queue": [],   # [{url,note,ts,user_id}]
            "stats": {},
        }
        self.load()

    # ---------------------------------------------------------------- I/O
    def load(self) -> None:
        if not self.path.exists():
            log.info("Sin estado previo en %s — arranque en frío", self.path)
            return
        try:
            # utf-8-sig y no utf-8: los editores de Windows y PowerShell escriben
            # UTF-8 CON BOM, y json.loads lo rechaza. Sin esto, editar el archivo
            # a mano equivale a borrar el histórico y reenviar todas las noticias.
            loaded = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, OSError) as exc:
            log.error("Estado corrupto (%s): se reinicia. %s", self.path, exc)
            return
        if loaded.get("version") != SCHEMA_VERSION:
            log.warning("Versión de estado distinta; se conserva lo compatible")
        for key in self.data:
            if key in loaded:
                self.data[key] = loaded[key]

    def save(self) -> None:
        """Escritura atómica: temp + replace (evita estado a medias si falla el runner)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, ensure_ascii=False, indent=1, sort_keys=True)
            os.replace(tmp, self.path)
        except Exception:
            Path(tmp).unlink(missing_ok=True)
            raise
        log.info("Estado guardado: %s vistos, %s en cola manual",
                 len(self.seen), len(self.manual_queue))

    # ------------------------------------------------------------ accesos
    @property
    def seen(self) -> list[dict[str, Any]]:
        return self.data["seen"]

    @property
    def manual_queue(self) -> list[dict[str, Any]]:
        return self.data["manual_queue"]

    @property
    def telegram_offset(self) -> int:
        return int(self.data.get("telegram_offset", 0))

    @telegram_offset.setter
    def telegram_offset(self, value: int) -> None:
        self.data["telegram_offset"] = int(value)

    # ------------------------------------------------------------ limpieza
    def prune(self, days: int = 14) -> int:
        """Borra registros antiguos para que el JSON no crezca sin límite."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        before = len(self.seen)
        self.data["seen"] = [s for s in self.seen if s.get("ts", "") >= cutoff]
        removed = before - len(self.seen)
        if removed:
            log.info("Purgados %s registros con más de %s días", removed, days)
        return removed

    def bump(self, key: str, amount: int = 1) -> None:
        stats = self.data.setdefault("stats", {})
        stats[key] = int(stats.get(key, 0)) + amount
