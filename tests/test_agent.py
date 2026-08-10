"""Tests del agente y del formato de Telegram. No gastan un solo token."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import agent
import telegram as tg
from models import Item, Verdict

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def noticia() -> Item:
    return Item(
        source="MMA Fighting",
        source_type="web",
        title="Se cancela el combate por el título de peso pluma a cinco días del evento",
        url="https://www.mmafighting.com/2026/8/10/titulo-cancelado?utm_source=twitter",
        published_at="2026-08-10T12:00:00+00:00",
        summary="La UFC confirma la baja del campeón por lesión y busca sustituto.",
        priority=2,
    )


# --------------------------------------------------------------- extract_json
@pytest.mark.parametrize(
    "raw",
    [
        '{"relevancia": 8}',
        '```json\n{"relevancia": 8}\n```',
        'Claro, aquí tienes:\n{"relevancia": 8}\nEspero que sirva.',
        '```\n{"relevancia": 8}\n```',
    ],
)
def test_extract_json_tolera_envoltorios(raw):
    assert agent.extract_json(raw)["relevancia"] == 8


def test_extract_json_falla_sin_objeto():
    with pytest.raises(ValueError):
        agent.extract_json("no hay JSON aquí")


# ----------------------------------------------------------------- pre-filtro
def test_prefiltro_deja_pasar_noticia_mma(noticia):
    assert agent.prefilter(noticia) is None


def test_prefiltro_descarta_sin_senales_mma():
    item = Item(source="X", source_type="web",
                title="El Real Madrid ficha a un nuevo centrocampista este verano",
                url="https://ejemplo.com/a")
    assert agent.prefilter(item) is not None


def test_prefiltro_descarta_promocional():
    item = Item(source="X", source_type="web",
                title="Mejores cuotas y código promocional para apostar en UFC 300",
                url="https://ejemplo.com/b")
    assert "promocional" in agent.prefilter(item)


def test_prefiltro_no_aplica_keywords_a_envio_manual():
    """Un humano ya filtró: no exigimos palabras clave."""
    item = Item(source="Instagram (manual)", source_type="instagram",
                title="Mira esto que acaba de subir", url="https://instagram.com/p/x/")
    assert agent.prefilter(item) is None


# ------------------------------------------------------------------- veredicto
def test_umbral_lo_decide_el_codigo_no_el_modelo():
    """El modelo dice 5 pero marca incluir=true: el código lo corrige."""
    verdict = Verdict.from_dict(
        {"relevancia": 5, "justificacion_relevancia": "x", "incluir_en_telegram": True,
         "briefing": {"formato_instagram": "Reel", "justificacion_formato": "a",
                      "caption_sugerido": "b", "sugerencia_visual": "c",
                      "hashtags": ["#UFC"], "angulo_engagement": "d"}}
    )
    corregido = agent._enforce(verdict, threshold=7)
    assert corregido.incluir_en_telegram is False
    assert corregido.briefing is None


def test_veredicto_alto_conserva_briefing():
    verdict = agent._enforce(Verdict.from_dict(load_fixture("verdict_alto.json")), 7)
    assert verdict.incluir_en_telegram is True
    assert verdict.briefing is not None
    assert 8 <= len(verdict.briefing.hashtags) <= 12


def test_hashtags_se_recortan_a_doce():
    data = load_fixture("verdict_alto.json")
    data["briefing"]["hashtags"] = [f"#tag{i}" for i in range(30)]
    verdict = agent._enforce(Verdict.from_dict(data), 7)
    assert len(verdict.briefing.hashtags) == 12


def test_analyze_usa_una_sola_llamada(monkeypatch, noticia):
    llamadas = []

    def fake_call(system, user):
        llamadas.append((system, user))
        return json.dumps(load_fixture("verdict_alto.json"))

    monkeypatch.setattr(agent, "call_llm", fake_call)
    verdict = agent.analyze(noticia, threshold=7)

    assert len(llamadas) == 1, "clasificación + briefing deben ir en UNA llamada"
    assert verdict.relevancia == 9
    assert noticia.title in llamadas[0][1]


def test_analyze_reintenta_y_luego_falla(monkeypatch, noticia):
    intentos = {"n": 0}

    def fake_call(system, user):
        intentos["n"] += 1
        return "esto no es JSON"

    monkeypatch.setattr(agent, "call_llm", fake_call)
    monkeypatch.setattr(agent.time, "sleep", lambda *_: None)
    with pytest.raises(agent.LLMError):
        agent.analyze(noticia, threshold=7, retries=1)
    assert intentos["n"] == 2


# ------------------------------------------------------- cadena de modelos
def test_cadena_de_modelos_salta_el_agotado(monkeypatch):
    """Un 429 en el primer modelo debe pasar al siguiente, no tumbar el ciclo."""
    intentados = []

    def fake_dispatch(provider, system, user, model, max_tokens):
        intentados.append(model)
        if model == "modelo-a":
            raise agent.LLMError("Gemini HTTP 429: RESOURCE_EXHAUSTED quota")
        return '{"ok": true}'

    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("LLM_MODEL", "modelo-a,modelo-b")
    monkeypatch.setattr(agent, "_dispatch", fake_dispatch)

    assert agent.call_llm("s", "u") == '{"ok": true}'
    assert intentados == ["modelo-a", "modelo-b"]


def test_cadena_de_modelos_salta_el_retirado(monkeypatch):
    """404 'no longer available to new users' también debe degradar."""
    def fake_dispatch(provider, system, user, model, max_tokens):
        if model == "viejo":
            raise agent.LLMError("HTTP 404 NOT_FOUND: no longer available to new users")
        return "{}"

    monkeypatch.setenv("LLM_MODEL", "viejo,nuevo")
    monkeypatch.setattr(agent, "_dispatch", fake_dispatch)
    assert agent.call_llm("s", "u") == "{}"


def test_truncacion_por_max_tokens_da_error_claro(monkeypatch):
    """El fallo real de producción: el JSON se corta y el error era indescifrable."""
    class FakeResp:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {
                "candidates": [{"finishReason": "MAX_TOKENS",
                                "content": {"parts": [{"text": '{"relevancia": 8,'}]}}],
                "usageMetadata": {"thoughtsTokenCount": 1161},
            }

    monkeypatch.setenv("GEMINI_API_KEY", "clave-de-prueba")
    monkeypatch.setattr(agent.requests, "post", lambda *a, **k: FakeResp())

    with pytest.raises(agent.LLMError) as exc:
        agent._call_gemini("s", "u", "gemini-3.6-flash", 1200)
    mensaje = str(exc.value)
    assert "maxOutputTokens" in mensaje and "1161" in mensaje, \
        "el error debe decir qué pasó y cuántos tokens se fueron en razonar"


def test_error_no_recuperable_no_prueba_otros_modelos(monkeypatch):
    """Una clave inválida falla en todos: no tiene sentido reintentar."""
    intentados = []

    def fake_dispatch(provider, system, user, model, max_tokens):
        intentados.append(model)
        raise agent.LLMError("falta GEMINI_API_KEY")

    monkeypatch.setenv("LLM_MODEL", "modelo-a,modelo-b")
    monkeypatch.setattr(agent, "_dispatch", fake_dispatch)
    with pytest.raises(agent.LLMError):
        agent.call_llm("s", "u")
    assert intentados == ["modelo-a"], "no debe malgastar intentos"


# -------------------------------------------------------------------- formato
def test_mensaje_telegram_cabe_y_escapa_html(noticia):
    data = load_fixture("verdict_alto.json")
    data["briefing"]["caption_sugerido"] = 'Un <b>peligro</b> & "comillas"'
    texto = tg.format_briefing(noticia, Verdict.from_dict(data))

    assert "&lt;b&gt;" in texto and "&amp;" in texto      # HTML escapado
    assert "<b>RELEVANCIA: 9/10</b>" in texto
    assert all(chunk and len(chunk) <= tg.SAFE_LEN for chunk in tg._split(texto))


def test_mensaje_incluye_todas_las_secciones(noticia):
    texto = tg.format_briefing(noticia, Verdict.from_dict(load_fixture("verdict_alto.json")))
    for marca in ("RELEVANCIA", "Por qué importa", "FORMATO",
                  "SUGERENCIA VISUAL", "CAPTION SUGERIDO",
                  "ÁNGULO DE ENGAGEMENT", "HASHTAGS"):
        assert marca in texto, f"falta la sección {marca}"


def test_mensaje_muy_largo_se_parte(noticia):
    data = load_fixture("verdict_alto.json")
    data["briefing"]["caption_sugerido"] = "línea muy larga de relleno\n" * 400
    chunks = tg._split(tg.format_briefing(noticia, Verdict.from_dict(data)))
    assert len(chunks) > 1
    assert all(len(c) <= tg.SAFE_LEN for c in chunks)


def test_callback_data_cabe_en_telegram(noticia):
    """Telegram limita callback_data a 64 bytes."""
    assert len(f"pub:{noticia.short_key}".encode()) <= 64
