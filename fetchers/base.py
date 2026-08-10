"""Contrato genérico de fuente + registro de adaptadores.

Añadir una fuente nueva = añadir una entrada en config.yaml.
Añadir un TIPO nuevo de fuente = escribir una función y decorarla con @register("nombre").
"""
from __future__ import annotations

import logging
from typing import Callable, Protocol

from models import Item

log = logging.getLogger("democles.fetchers")


class FetchError(RuntimeError):
    """Fallo recuperable de una fuente: se registra y se sigue con las demás."""


class Fetcher(Protocol):
    def __call__(self, source: dict, ctx: dict) -> list[Item]: ...


REGISTRY: dict[str, Fetcher] = {}


def register(name: str) -> Callable[[Fetcher], Fetcher]:
    def decorator(fn: Fetcher) -> Fetcher:
        if name in REGISTRY:
            raise ValueError(f"Adaptador duplicado: {name}")
        REGISTRY[name] = fn
        return fn

    return decorator


def get_fetcher(adapter: str) -> Fetcher:
    try:
        return REGISTRY[adapter]
    except KeyError as exc:
        raise FetchError(
            f"Adaptador desconocido '{adapter}'. Disponibles: {sorted(REGISTRY)}"
        ) from exc


def run_source(source: dict, ctx: dict) -> list[Item]:
    """Ejecuta una fuente aislando sus errores: una fuente caída no tumba el ciclo."""
    name = source.get("name", "?")
    if not source.get("activo", True):
        log.debug("Fuente desactivada: %s", name)
        return []
    try:
        fetcher = get_fetcher(source["adaptador"])
        items = fetcher(source, ctx) or []
    except FetchError as exc:
        log.warning("Fuente '%s' falló: %s", name, exc)
        return []
    except Exception as exc:  # noqa: BLE001 - aislamiento deliberado por fuente
        log.exception("Fuente '%s' lanzó un error inesperado: %s", name, exc)
        return []

    limit = int(source.get("max_items", 15))
    log.info("Fuente '%s': %s items (se toman %s)", name, len(items), min(len(items), limit))
    return items[:limit]
