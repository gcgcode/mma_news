"""Averigua tu TELEGRAM_CHAT_ID sin pelearte con getUpdates.

    python chat_id.py

Diagnostica las tres causas del clásico {"ok":true,"result":[]} y luego se queda
esperando a que escribas al bot para enseñarte el número que necesitas.

Causas de una respuesta vacía, en orden de frecuencia:
  1. No le has escrito al bot todavía. Un bot no puede iniciar conversación:
     tienes que hablarle tú primero.
  2. Hay un webhook configurado. Mientras exista, getUpdates devuelve vacío
     siempre. Este script lo detecta y te ofrece borrarlo.
  3. Los mensajes ya se consumieron. Telegram borra cada update en cuanto se lee
     con un offset mayor, y los descarta pasadas 24 h.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

API = "https://api.telegram.org/bot{token}/{metodo}"
ESPERA_TOTAL = 120          # segundos que aguantamos esperando tu mensaje


def llamar(token: str, metodo: str, **params):
    try:
        resp = requests.get(API.format(token=token, metodo=metodo),
                            params=params, timeout=40)
    except requests.RequestException as exc:
        print(f"  ❌ Error de red hablando con Telegram: {exc}")
        return None
    datos = resp.json() if resp.content else {}
    if not datos.get("ok"):
        print(f"  ❌ {metodo} falló: {str(datos)[:200]}")
        return None
    return datos.get("result")


def describir(update: dict) -> tuple[int, int, str] | None:
    """Extrae (chat_id, user_id, descripción) de cualquier tipo de update."""
    for clave in ("message", "edited_message", "channel_post", "my_chat_member"):
        obj = update.get(clave)
        if not obj:
            continue
        chat = obj.get("chat") or {}
        quien = obj.get("from") or {}
        nombre = chat.get("title") or chat.get("first_name") or "?"
        tipo = chat.get("type", "?")
        texto = (obj.get("text") or "").strip()
        detalle = f"{tipo} «{nombre}»" + (f" — “{texto[:40]}”" if texto else "")
        return chat.get("id"), quien.get("id"), detalle
    return None


def main() -> int:
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token or ":" not in token:
        print("\n❌ No encuentro un TELEGRAM_BOT_TOKEN válido en .env")
        print("   Debe tener la forma 123456789:AAH... tal como te lo dio @BotFather")
        return 1

    print("\n\033[1m🔎 Buscando tu chat ID\033[0m\n")

    # ---- 1. ¿El token es bueno? -----------------------------------------
    yo = llamar(token, "getMe")
    if not yo:
        print("\n   El token no es válido. Pídele otro a @BotFather con /token")
        return 1
    usuario = yo.get("username")
    print(f"  ✅ Bot: @{usuario}")

    # ---- 2. ¿Hay un webhook robándose los mensajes? ----------------------
    webhook = llamar(token, "getWebhookInfo") or {}
    if webhook.get("url"):
        # Sin input(): este script también se ejecuta desde entornos sin consola
        # interactiva, y ahí un prompt reventaría con EOFError.
        print(f"\n  ⚠️  Hay un WEBHOOK configurado: {webhook['url']}")
        print("     Mientras exista, getUpdates SIEMPRE devolverá una lista vacía.")
        print("     Lo borro para poder leer los mensajes...")
        if llamar(token, "deleteWebhook") is None:
            print("     ❌ No se pudo borrar. Hazlo a mano abriendo esta URL:")
            print(f"     https://api.telegram.org/bot<TU_TOKEN>/deleteWebhook")
            return 1
        print("     ✅ Webhook borrado (el bot no lo usa; DEMOCLES lee por getUpdates)")
    else:
        print("  ✅ Sin webhook: getUpdates puede leer mensajes")

    # ---- 3. ¿Hay algo pendiente ya? --------------------------------------
    pendientes = llamar(token, "getUpdates", offset=-1, timeout=0) or []
    if pendientes:
        print(f"  ✅ Hay {len(pendientes)} mensaje(s) en cola")
    else:
        print("  ℹ️  Cola vacía — ahora mismo Telegram no tiene nada guardado")

    # ---- 4. Esperar a que el humano escriba ------------------------------
    print(f"\n\033[1m👉 Abre Telegram, busca @{usuario} y escríbele cualquier cosa.\033[0m")
    print(f"   (por ejemplo: hola).  Esperando hasta {ESPERA_TOTAL}s...\n")

    limite = time.time() + ESPERA_TOTAL
    vistos: set[int] = set()
    encontrados: dict[int, tuple[int, str]] = {}   # chat_id -> (user_id, detalle)

    while time.time() < limite:
        # long-poll de 20 s: no consumimos con offset para no perder nada
        updates = llamar(token, "getUpdates", offset=-1, timeout=20) or []
        for upd in updates:
            if upd["update_id"] in vistos:
                continue
            vistos.add(upd["update_id"])
            info = describir(upd)
            if not info:
                continue
            chat_id, user_id, detalle = info
            if chat_id is not None and chat_id not in encontrados:
                encontrados[chat_id] = (user_id, detalle)
                print(f"  📨 Recibido de {detalle}")
                print(f"      chat_id = {chat_id}   user_id = {user_id}")
        if encontrados:
            break
        time.sleep(1)

    if not encontrados:
        print("\n  ⏱️  No ha llegado ningún mensaje.")
        print("     Comprueba que le escribes al bot correcto (@%s)" % usuario)
        print("     y que pulsaste /start la primera vez.")
        return 1

    # ---- 5. Resultado ----------------------------------------------------
    chat_id, (user_id, _) = next(iter(encontrados.items()))
    print("\n\033[1m✅ Listo. Pega esto en tu archivo .env:\033[0m\n")
    print(f"TELEGRAM_CHAT_ID={chat_id}")
    print(f"TELEGRAM_ALLOWED_USERS={user_id}")
    if len(encontrados) > 1:
        print("\n  (He visto más de un chat; usa el que corresponda:)")
        for cid, (uid, det) in encontrados.items():
            print(f"    {cid}  ←  {det}")
    print("\n  Después comprueba que funciona:  python doctor.py --enviar")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
