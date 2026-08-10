"""El orden en que se gasta el presupuesto de llamadas al LLM.

Con `MAX_LLM_CALLS` bajo y cola acumulada, este orden decide qué noticias
llegan hoy y cuáles esperan al siguiente ciclo.
"""
from __future__ import annotations

from models import Item


def ordenar(items: list[Item]) -> list[Item]:
    """Réplica exacta del criterio de main.py (dos sorts estables encadenados)."""
    items = list(items)
    items.sort(key=lambda i: i.published_at or "", reverse=True)
    items.sort(key=lambda i: int(i.priority))
    return items


def mk(titulo: str, prioridad: int, fecha: str | None) -> Item:
    return Item(source="X", source_type="web", title=titulo,
                url=f"https://e.com/{titulo}", priority=prioridad, published_at=fecha)


def test_lo_mas_reciente_primero_dentro_de_la_misma_prioridad():
    items = [
        mk("vieja", 2, "2026-08-01T10:00:00+00:00"),
        mk("nueva", 2, "2026-08-10T10:00:00+00:00"),
        mk("media", 2, "2026-08-05T10:00:00+00:00"),
    ]
    assert [i.title for i in ordenar(items)] == ["nueva", "media", "vieja"]


def test_la_prioridad_manda_sobre_la_fecha():
    """Un envío manual (prioridad 1) entra antes que una noticia más reciente."""
    items = [
        mk("gnews-reciente", 4, "2026-08-10T23:00:00+00:00"),
        mk("envio-manual", 1, "2026-08-09T08:00:00+00:00"),
    ]
    assert [i.title for i in ordenar(items)][0] == "envio-manual"


def test_sin_fecha_va_al_final_de_su_prioridad():
    items = [
        mk("sin-fecha", 2, None),
        mk("con-fecha", 2, "2026-08-01T10:00:00+00:00"),
    ]
    assert [i.title for i in ordenar(items)] == ["con-fecha", "sin-fecha"]


def test_el_recorte_por_tope_se_queda_lo_mejor():
    """Lo que sobrevive al tope debe ser lo prioritario y reciente, no lo viejo."""
    items = [mk(f"vieja-{n}", 3, f"2026-07-{n:02d}T10:00:00+00:00") for n in range(1, 20)]
    items.append(mk("BREAKING", 2, "2026-08-10T23:00:00+00:00"))
    assert [i.title for i in ordenar(items)[:1]] == ["BREAKING"]
