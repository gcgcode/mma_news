"""Fetchers: cada módulo convierte una fuente externa en `list[Item]`."""
from __future__ import annotations

from fetchers.base import Fetcher, FetchError, register, get_fetcher, REGISTRY
from fetchers import instagram, reddit, twitter, web  # noqa: F401  (registran adaptadores)

__all__ = ["Fetcher", "FetchError", "register", "get_fetcher", "REGISTRY"]
