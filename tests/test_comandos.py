"""Lectura de comandos de Telegram: confirmación del offset y control de acceso."""
from __future__ import annotations

import pytest

import bot_poll
import telegram as tg
from state import State


def msg(update_id: int, text: str, *, user=111, chat=111) -> dict:
    return {
        "update_id": update_id,
        "message": {"text": text, "from": {"id": user, "first_name": "Ana"},
                    "chat": {"id": chat, "type": "private"}},
    }


@pytest.fixture
def bot(monkeypatch, tmp_path):
    """Simula la API: sirve lotes y registra qué offsets se han pedido."""
    enviados: list[tuple[str, str]] = []

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "1:AA")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "111")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "111")
    monkeypatch.setattr(
        tg, "send_text",
        lambda texto, chat_id=None: enviados.append((str(chat_id), texto)),
    )
    return {"state": State(tmp_path / "s.json"), "enviados": enviados}


def test_se_pide_un_lote_extra_para_confirmar(monkeypatch, bot):
    """Telegram sólo da por leído un update cuando vuelves a llamar con un
    offset mayor. Sin esa llamada final, la cola no se vacía nunca."""
    offsets: list[int] = []
    lotes = [[msg(10, "/whoami"), msg(11, "/status")], []]

    def fake_get_updates(offset, timeout=0):
        offsets.append(offset)
        return lotes.pop(0) if lotes else []

    monkeypatch.setattr(tg, "get_updates", fake_get_updates)
    bot_poll.process_updates(bot["state"])

    assert offsets == [0, 12], "falta la llamada de confirmación con el offset nuevo"
    assert bot["state"].telegram_offset == 12


def test_varios_lotes_seguidos(monkeypatch, bot):
    """Telegram devuelve 100 updates como máximo por llamada."""
    lotes = [[msg(1, "/whoami")], [msg(2, "/whoami")], []]
    monkeypatch.setattr(tg, "get_updates", lambda offset, timeout=0:
                        lotes.pop(0) if lotes else [])
    assert bot_poll.process_updates(bot["state"]) == 2


def test_tope_de_lotes_evita_bucle_infinito(monkeypatch, bot):
    """Si la API nunca vaciara, no podemos quedarnos girando para siempre."""
    llamadas = {"n": 0}

    def siempre_lleno(offset, timeout=0):
        llamadas["n"] += 1
        return [msg(llamadas["n"], "/whoami")]

    monkeypatch.setattr(tg, "get_updates", siempre_lleno)
    bot_poll.process_updates(bot["state"], max_lotes=3)
    assert llamadas["n"] == 3


# ----------------------------------------------------------------- /whoami
def test_whoami_responde_a_quien_no_tiene_acceso(monkeypatch, bot):
    """Es la única vía para que alguien nuevo consiga su ID y pueda pedir permiso."""
    lotes = [[msg(1, "/whoami", user=999, chat=999)], []]
    monkeypatch.setattr(tg, "get_updates", lambda offset, timeout=0:
                        lotes.pop(0) if lotes else [])

    bot_poll.process_updates(bot["state"])
    destino, texto = bot["enviados"][0]
    assert destino == "999"
    assert "999" in texto and "Aún sin acceso" in texto


def test_whoami_en_grupo_devuelve_el_id_del_grupo(monkeypatch, bot):
    lotes = [[{
        "update_id": 1,
        "message": {"text": "/whoami", "from": {"id": 111, "first_name": "Ana"},
                    "chat": {"id": -5448137483, "type": "group", "title": "Equipo"}},
    }], []]
    monkeypatch.setattr(tg, "get_updates", lambda offset, timeout=0:
                        lotes.pop(0) if lotes else [])

    bot_poll.process_updates(bot["state"])
    destino, texto = bot["enviados"][0]
    assert destino == "-5448137483"
    assert "-5448137483" in texto, "hace falta el id del grupo para configurarlo"


def test_whoami_con_sufijo_del_bot(monkeypatch, bot):
    """En grupos Telegram añade @nombredelbot al comando."""
    lotes = [[msg(1, "/whoami@damocles_mma_bot")], []]
    monkeypatch.setattr(tg, "get_updates", lambda offset, timeout=0:
                        lotes.pop(0) if lotes else [])
    bot_poll.process_updates(bot["state"])
    assert bot["enviados"], "el sufijo @bot no debe impedir reconocer el comando"


def test_usuario_no_autorizado_no_puede_encolar(monkeypatch, bot):
    lotes = [[msg(1, "/add https://instagram.com/p/x/", user=999, chat=999)], []]
    monkeypatch.setattr(tg, "get_updates", lambda offset, timeout=0:
                        lotes.pop(0) if lotes else [])

    bot_poll.process_updates(bot["state"])
    assert bot["state"].manual_queue == []
    assert "No autorizado" in bot["enviados"][0][1]
