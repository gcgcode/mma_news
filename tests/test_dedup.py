"""Tests del deduplicador y de la normalización de URLs/titulares."""
from __future__ import annotations

import pytest

from deduplicator import Deduplicator
from models import Item
from state import State
from util import canonical_url, normalize_title


def make_item(title: str, url: str, source="Fuente", priority=3, source_type="web") -> Item:
    return Item(source=source, source_type=source_type, title=title, url=url,
                priority=priority, published_at="2026-08-10T10:00:00+00:00")


@pytest.fixture
def dedup(tmp_path) -> Deduplicator:
    return Deduplicator(State(tmp_path / "state.json"))


# ------------------------------------------------------------------- canónico
def test_url_canonica_elimina_tracking():
    a = canonical_url("https://www.mmafighting.com/nota?utm_source=tw&utm_medium=x")
    b = canonical_url("https://mmafighting.com/nota/")
    assert a == b


def test_espejos_de_twitter_se_unifican():
    assert canonical_url("https://nitter.net/ufc/status/1") == \
           canonical_url("https://x.com/ufc/status/1")


def test_normalize_title_quita_prefijos_y_acentos():
    a = normalize_title("BREAKING: Jon Jones deja vacante el título")
    b = normalize_title("Jon Jones deja vacante el titulo")
    assert a == b


# ---------------------------------------------------------------------- capas
def test_capa1_misma_url(dedup):
    items = [
        make_item("Jones deja vacante el título de peso pesado", "https://a.com/x?utm_source=rss"),
        make_item("Otro titular distinto del anterior aquí", "https://a.com/x"),
    ]
    assert len(dedup.dedupe_batch(items)) == 1


def test_capa2_titular_identico_distinta_url(dedup):
    items = [
        make_item("Jon Jones deja vacante el título de peso pesado", "https://a.com/1"),
        make_item("BREAKING: Jon Jones deja vacante el título de peso pesado", "https://b.com/2"),
    ]
    assert len(dedup.dedupe_batch(items)) == 1


def test_capa3_titular_similar_reescrito(dedup):
    items = [
        make_item("Jon Jones vacates the UFC heavyweight title after retirement", "https://a.com/1"),
        make_item("Jon Jones vacates UFC heavyweight title", "https://b.com/2"),
    ]
    assert len(dedup.dedupe_batch(items)) == 1


def test_noticias_distintas_no_se_colapsan(dedup):
    items = [
        make_item("Jon Jones deja vacante el título de peso pesado", "https://a.com/1"),
        make_item("Ilia Topuria firma su combate por el título de peso ligero", "https://b.com/2"),
    ]
    assert len(dedup.dedupe_batch(items)) == 2


def test_gana_la_fuente_de_mayor_prioridad(dedup):
    """Misma noticia por Reddit (p3) y por el medio (p2): debe ganar el medio."""
    items = [
        make_item("Topuria confirma su subida a peso ligero para el próximo evento",
                  "https://reddit.com/r/MMA/x", source="r/MMA", priority=3),
        make_item("Topuria confirma su subida a peso ligero para el proximo evento",
                  "https://mmafighting.com/x", source="MMA Fighting", priority=2),
    ]
    kept = dedup.dedupe_batch(items)
    assert len(kept) == 1
    assert kept[0].source == "MMA Fighting"


def test_titulares_cortos_no_se_comparan_por_similitud(dedup):
    """Evita falsos positivos tipo 'UFC 300' vs 'UFC 301'."""
    items = [make_item("UFC 300 resultados", "https://a.com/1"),
             make_item("UFC 301 resultados", "https://b.com/2")]
    assert len(dedup.dedupe_batch(items)) == 2


# ------------------------------------------------------------------ histórico
def test_remember_bloquea_en_ciclos_siguientes(tmp_path):
    state = State(tmp_path / "state.json")
    item = make_item("Jon Jones deja vacante el título de peso pesado", "https://a.com/1")

    d1 = Deduplicator(state)
    assert len(d1.dedupe_batch([item])) == 1
    d1.remember(item, score=9, sent=True)
    state.save()

    d2 = Deduplicator(State(tmp_path / "state.json"))
    assert d2.dedupe_batch([item]) == []


def test_estado_con_BOM_de_windows_se_lee_bien(tmp_path):
    """PowerShell y los editores de Windows escriben UTF-8 con BOM.
    Si no se tolera, el histórico se pierde y se reenvían todas las noticias."""
    ruta = tmp_path / "state.json"
    ruta.write_text(
        '{"version":1,"seen":[{"key":"abc","ts":"2026-08-10T00:00:00+00:00"}],'
        '"manual_queue":[],"telegram_offset":7,"stats":{}}',
        encoding="utf-8-sig",
    )
    state = State(ruta)
    assert len(state.seen) == 1, "el BOM no debe invalidar el estado"
    assert state.telegram_offset == 7


def test_purga_respeta_el_limite_de_dias(tmp_path):
    state = State(tmp_path / "state.json")
    state.seen.append({"key": "viejo", "ts": "2020-01-01T00:00:00+00:00"})
    state.seen.append({"key": "nuevo", "ts": "2999-01-01T00:00:00+00:00"})
    assert state.prune(days=14) == 1
    assert [s["key"] for s in state.seen] == ["nuevo"]
