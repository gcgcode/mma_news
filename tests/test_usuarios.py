"""Acceso multiusuario: quién recibe los briefings y quién puede usar /add."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import bot_poll
import telegram as tg
from models import Item, Verdict

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def noticia() -> Item:
    return Item(source="MMA Fighting", source_type="web",
                title="Combate por el título confirmado para el próximo evento",
                url="https://www.mmafighting.com/x", priority=2)


@pytest.fixture
def veredicto() -> Verdict:
    return Verdict.from_dict(
        json.loads((FIXTURES / "verdict_alto.json").read_text(encoding="utf-8"))
    )


@pytest.fixture
def espia(monkeypatch):
    """Sustituye tg.call y registra a qué chats se ha escrito."""
    enviados: list[str] = []

    def fake_call(method, payload, **kwargs):
        enviados.append(str(payload.get("chat_id")))
        return {"message_id": 1}

    monkeypatch.setattr(tg, "call", fake_call)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "1:AA")
    return enviados


# --------------------------------------------------------------- destinatarios
def test_un_solo_destino(monkeypatch, espia, noticia, veredicto):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "111")
    tg.send_briefing(noticia, veredicto)
    assert espia == ["111"]


def test_varios_destinos_reciben_el_briefing(monkeypatch, espia, noticia, veredicto):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "111, 222 ,333")
    tg.send_briefing(noticia, veredicto)
    assert espia == ["111", "222", "333"]


def test_grupo_con_id_negativo(monkeypatch, espia, noticia, veredicto):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-1001234567890")
    tg.send_briefing(noticia, veredicto)
    assert espia == ["-1001234567890"]


def test_un_destino_caido_no_impide_los_demas(monkeypatch, noticia, veredicto):
    """Si alguien bloquea al bot, el resto tiene que recibirlo igual."""
    entregados: list[str] = []

    def fake_call(method, payload, **kwargs):
        destino = str(payload.get("chat_id"))
        if destino == "222":
            raise tg.TelegramError("Forbidden: bot was blocked by the user")
        entregados.append(destino)
        return {"message_id": 1}

    monkeypatch.setattr(tg, "call", fake_call)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "1:AA")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "111,222,333")

    tg.send_briefing(noticia, veredicto)          # no debe lanzar
    assert entregados == ["111", "333"]


def test_si_fallan_todos_si_se_avisa(monkeypatch, noticia, veredicto):
    """Fallar en silencio marcaría la noticia como enviada sin estarlo."""
    def fake_call(method, payload, **kwargs):
        raise tg.TelegramError("chat not found")

    monkeypatch.setattr(tg, "call", fake_call)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "1:AA")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "111,222")
    with pytest.raises(tg.TelegramError):
        tg.send_briefing(noticia, veredicto)


def test_sin_chat_id_falla_claro(monkeypatch, espia, noticia, veredicto):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "")
    with pytest.raises(tg.TelegramError, match="TELEGRAM_CHAT_ID"):
        tg.send_briefing(noticia, veredicto)


# ------------------------------------------------------------------- permisos
def test_lista_explicita_de_autorizados(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "111, 222,333")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")
    assert bot_poll._allowed_users() == {111, 222, 333}
    assert bot_poll._authorized(222) is True
    assert bot_poll._authorized(444) is False


def test_sin_lista_valen_los_chats_privados(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "111,222")
    assert bot_poll._allowed_users() == {111, 222}


def test_sin_lista_un_grupo_no_autoriza_a_nadie(monkeypatch):
    """El id de un grupo es negativo: no identifica a ninguna persona.
    Tomarlo como usuario dejaría fuera a todo el mundo sin explicación."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-1001234567890")
    assert bot_poll._allowed_users() == set()


def test_grupo_mas_privado_autoriza_solo_al_privado(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-1001234567890,1379532921")
    assert bot_poll._allowed_users() == {1379532921}
