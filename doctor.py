"""Verificador de instalación. Comprueba credencial por credencial qué funciona.

    python doctor.py            comprueba todo sin enviar nada
    python doctor.py --enviar   además manda un mensaje de prueba a tu Telegram
    python doctor.py --fuentes  además prueba una descarga real de cada fuente activa

Salida: ✅ funciona · ⚠️ opcional sin configurar · ❌ hay que arreglarlo.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

OK, WARN, FAIL = "✅", "⚠️ ", "❌"
_resultados: list[tuple[str, str, str]] = []   # (estado, título, detalle)


def check(estado: str, titulo: str, detalle: str = "") -> None:
    _resultados.append((estado, titulo, detalle))
    linea = f"{estado} {titulo}"
    if detalle:
        linea += f"\n     └─ {detalle}"
    print(linea)


def seccion(titulo: str) -> None:
    print(f"\n\033[1m── {titulo} {'─' * max(0, 58 - len(titulo))}\033[0m")


# ---------------------------------------------------------------------------
def check_python() -> None:
    seccion("Entorno")
    v = sys.version_info
    if v >= (3, 10):
        check(OK, f"Python {v.major}.{v.minor}.{v.micro}")
    else:
        check(FAIL, f"Python {v.major}.{v.minor}", "Se necesita 3.10 o superior")

    faltan = []
    for mod, paquete in [
        ("requests", "requests"), ("feedparser", "feedparser"), ("yaml", "PyYAML"),
        ("bs4", "beautifulsoup4"), ("rapidfuzz", "rapidfuzz"),
        ("dateutil", "python-dateutil"), ("dotenv", "python-dotenv"),
    ]:
        try:
            __import__(mod)
        except ImportError:
            faltan.append(paquete)
    if faltan:
        check(FAIL, "Dependencias", f"Faltan: {', '.join(faltan)} → pip install -r requirements.txt")
    else:
        check(OK, "Dependencias instaladas")


def check_archivos() -> None:
    seccion("Archivos del proyecto")
    if (ROOT / ".env").exists():
        check(OK, "Archivo .env encontrado")
    else:
        check(FAIL, "Falta el archivo .env",
              "Ejecuta: copy .env.example .env    y rellena las claves")

    try:
        import yaml
        data = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
        activas = [f for f in data.get("fuentes", []) if f.get("activo", True)]
        sin_verificar = [f["name"] for f in activas if f.get("verificar")]
        check(OK, f"config.yaml válido — {len(activas)} fuentes activas")
        if sin_verificar:
            check(WARN, f"{len(sin_verificar)} fuentes con RSS sin confirmar",
                  ", ".join(sin_verificar[:4]) + (" …" if len(sin_verificar) > 4 else ""))
    except Exception as exc:  # noqa: BLE001
        check(FAIL, "config.yaml ilegible", str(exc)[:120])

    estado = ROOT / "state" / "state.json"
    if estado.exists():
        import json
        try:
            d = json.loads(estado.read_text(encoding="utf-8-sig"))  # tolera BOM
            check(OK, "Estado accesible",
                  f"{len(d.get('seen', []))} noticias en histórico, "
                  f"{len(d.get('manual_queue', []))} en cola manual")
        except Exception:  # noqa: BLE001
            check(FAIL, "state/state.json corrupto", "Bórralo y se regenerará vacío")
    else:
        check(WARN, "Sin estado previo", "Se creará en la primera ejecución")


def check_telegram(enviar: bool) -> None:
    seccion("Telegram")
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat = os.getenv("TELEGRAM_CHAT_ID", "")

    if not token:
        check(FAIL, "TELEGRAM_BOT_TOKEN vacío", "Créalo con @BotFather → /newbot")
        return
    if ":" not in token:
        check(FAIL, "TELEGRAM_BOT_TOKEN con formato raro",
              "Debe ser 123456789:AA... (copiado entero de BotFather)")
        return

    import telegram as tg
    try:
        me = tg.call("getMe", {}, retries=0)
        check(OK, f"Bot conectado: @{me.get('username')}")
    except Exception as exc:  # noqa: BLE001
        check(FAIL, "El token no funciona", str(exc)[:160])
        return

    if not chat:
        check(FAIL, "TELEGRAM_CHAT_ID vacío",
              f"Escribe algo a tu bot y abre: "
              f"https://api.telegram.org/bot{token[:10]}.../getUpdates → message.chat.id")
        return

    if enviar:
        try:
            tg.send_text("🔧 <b>DEMOCLES</b> — mensaje de prueba.\n"
                         "Si lees esto, Telegram está bien configurado.")
            check(OK, f"Mensaje de prueba enviado al chat {chat}")
        except Exception as exc:  # noqa: BLE001
            check(FAIL, "No se pudo enviar al chat", str(exc)[:160])
    else:
        check(OK, f"TELEGRAM_CHAT_ID definido ({chat})", "Usa --enviar para probarlo de verdad")

    permitidos = os.getenv("TELEGRAM_ALLOWED_USERS", "")
    if permitidos:
        check(OK, f"Usuarios autorizados para /add: {permitidos}")
    else:
        check(WARN, "TELEGRAM_ALLOWED_USERS vacío",
              "Se usará TELEGRAM_CHAT_ID como único autorizado")


def check_llm() -> None:
    seccion("Modelo de lenguaje")
    proveedor = os.getenv("LLM_PROVIDER", "gemini").lower()
    modelo = os.getenv("LLM_MODEL", "(por defecto)")
    clave = {
        "gemini": "GEMINI_API_KEY", "groq": "GROQ_API_KEY",
        "openai": "OPENAI_API_KEY", "together": "TOGETHER_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
    }.get(proveedor)

    if clave is None:
        check(FAIL, f"LLM_PROVIDER desconocido: {proveedor}",
              "Valores válidos: gemini, groq, openai, together, anthropic")
        return
    if not os.getenv(clave):
        check(FAIL, f"Falta {clave}", f"El proveedor elegido es '{proveedor}'")
        return

    check(OK, f"Proveedor: {proveedor} · modelo: {modelo}")
    try:
        import agent
        respuesta = agent.call_llm(
            'Responde solo con este JSON exacto: {"ok": true}',
            "Comprobación de conexión.",
        )
        agent.extract_json(respuesta)
        check(OK, "Llamada de prueba correcta", "La clave funciona (coste: ~0,00001 €)")
    except Exception as exc:  # noqa: BLE001
        check(FAIL, "La llamada al modelo falló", str(exc)[:200])


def check_reddit() -> None:
    seccion("Reddit")
    if os.getenv("REDDIT_CLIENT_ID") and os.getenv("REDDIT_CLIENT_SECRET"):
        try:
            from fetchers.reddit import _get_token
            _get_token()
            check(OK, "Credenciales de Reddit válidas (API oficial)")
        except Exception as exc:  # noqa: BLE001
            check(FAIL, "Reddit rechazó las credenciales", str(exc)[:180])
        return

    # Sin credenciales usamos el RSS público, que es lo que hace config.yaml.
    # La API oficial exige solicitar permiso desde el cambio de políticas.
    try:
        from fetchers.base import FetchError
        from fetchers.reddit import fetch_reddit_rss
        items = fetch_reddit_rss(
            {"name": "r/MMA", "subreddit": "MMA", "listing": "hot"}, {}
        )
        if items:
            check(OK, f"Reddit vía RSS público — {len(items)} items",
                  "Sin credenciales. Puede dar 403/429 desde GitHub Actions")
        else:
            check(WARN, "Reddit RSS devolvió 0 items", "El ciclo continúa sin Reddit")
    except Exception as exc:  # noqa: BLE001
        check(WARN, "Reddit RSS no responde", f"{str(exc)[:120]} — el ciclo continúa")


def check_twitter() -> None:
    seccion("Twitter/X (opcional)")
    estrategias = [s.strip() for s in os.getenv("TWITTER_STRATEGY", "").split(",") if s.strip()]
    if not estrategias:
        check(WARN, "Twitter desactivado",
              "Es normal y aceptable: Reddit y las webs cubren el 90% del contenido")
        return
    check(OK, f"Estrategias configuradas: {', '.join(estrategias)}")
    if "rsshub" in estrategias and not os.getenv("RSSHUB_BASE"):
        check(WARN, "rsshub activo pero RSSHUB_BASE vacío", "Esa estrategia se saltará")
    if "nitter" in estrategias and not os.getenv("NITTER_MIRRORS"):
        check(WARN, "nitter activo pero NITTER_MIRRORS vacío", "Esa estrategia se saltará")
    if "apify" in estrategias and not os.getenv("APIFY_TOKEN"):
        check(WARN, "apify activo pero APIFY_TOKEN vacío", "Esa estrategia se saltará")


def check_fuentes() -> None:
    seccion("Prueba real de fuentes (descarga)")
    import yaml
    from fetchers.base import run_source
    from state import State

    data = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    ctx = {"state": State(ROOT / "state" / "state.json"), "config": data}

    for fuente in data.get("fuentes", []):
        if not fuente.get("activo", True) or fuente["adaptador"] == "instagram_manual":
            continue
        nombre = fuente.get("name", "?")
        try:
            items = run_source(fuente, ctx)
        except Exception as exc:  # noqa: BLE001
            check(FAIL, nombre, str(exc)[:120]); continue
        if items:
            check(OK, f"{nombre} — {len(items)} items", items[0].title[:80])
        else:
            check(WARN, f"{nombre} — 0 items",
                  "Revisa la URL en config.yaml, o desactívala y usa gnews")


# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="Verificador de DEMOCLES")
    parser.add_argument("--enviar", action="store_true",
                        help="envía un mensaje de prueba a Telegram")
    parser.add_argument("--fuentes", action="store_true",
                        help="descarga de verdad de cada fuente activa (tarda ~1 min)")
    args = parser.parse_args()

    print("\n\033[1m🔧 DEMOCLES — verificación de instalación\033[0m")

    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass

    check_python()
    check_archivos()
    check_telegram(args.enviar)
    check_llm()
    check_reddit()
    check_twitter()
    if args.fuentes:
        check_fuentes()

    fallos = [r for r in _resultados if r[0] == FAIL]
    avisos = [r for r in _resultados if r[0] == WARN]

    seccion("Resumen")
    print(f"   {OK} correctos: {len(_resultados) - len(fallos) - len(avisos)}")
    print(f"   {WARN}avisos:    {len(avisos)}   (no impiden funcionar)")
    print(f"   {FAIL} fallos:    {len(fallos)}")

    if fallos:
        print("\n\033[1mHay que arreglar esto antes de desplegar:\033[0m")
        for _, titulo, detalle in fallos:
            print(f"   • {titulo}" + (f" → {detalle}" if detalle else ""))
        return 1

    print("\n\033[1m🎉 Todo listo. Siguiente paso:\033[0m")
    print("   python main.py --dry-run     (prueba sin gastar nada)")
    print("   python main.py               (ciclo real)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
