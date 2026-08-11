"""Orquestador.

    fetchers -> normalizador -> deduplicador -> pre-filtro -> agente LLM -> Telegram

Uso:
    python main.py                      ciclo completo
    python main.py --dry-run            sin LLM y sin Telegram (gratis)
    python main.py --no-llm             recoge y deduplica; imprime lo que llamaría
    python main.py --no-send            llama al LLM pero imprime en vez de enviar
    python main.py --source "r/MMA"     ejecuta sólo esa fuente
    python main.py --limit 3            tope de noticias analizadas
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

import bot_poll
import telegram as tg
from agent import LLMError, analyze, prefilter
from deduplicator import Deduplicator
from fetchers.base import run_source
from models import Item
from state import State

log = logging.getLogger("democles")


def setup_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)-22s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def load_config(path: str = "config.yaml") -> dict:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "fuentes" not in data:
        raise SystemExit(f"{path} inválido: falta la clave 'fuentes'")
    return data


def collect(config: dict, ctx: dict, only: str | None) -> list[Item]:
    items: list[Item] = []
    for source in config["fuentes"]:
        if only and only.lower() not in str(source.get("name", "")).lower():
            continue
        items.extend(run_source(source, ctx))
    return items


def main() -> int:
    parser = argparse.ArgumentParser(description="DEMOCLES — briefings de MMA")
    parser.add_argument("--dry-run", action="store_true",
                        help="sin LLM y sin Telegram; no gasta nada")
    parser.add_argument("--no-llm", action="store_true", help="no llama al modelo")
    parser.add_argument("--no-send", action="store_true",
                        help="llama al modelo pero imprime en consola")
    parser.add_argument("--source", help="filtra por nombre de fuente")
    parser.add_argument("--limit", type=int, help="máximo de noticias a analizar")
    parser.add_argument("--comandos", action="store_true",
                        help="atiende sólo los comandos de Telegram y sale "
                             "(sin fuentes ni LLM): respuesta inmediata")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    load_dotenv()
    setup_logging()

    no_llm = args.no_llm or args.dry_run
    no_send = args.no_send or args.dry_run

    config = load_config(args.config)
    settings = config.get("ajustes", {})
    threshold = int(os.getenv("RELEVANCE_THRESHOLD", settings.get("umbral_relevancia", 7)))
    max_calls = args.limit or int(
        os.getenv("MAX_LLM_CALLS", settings.get("max_llamadas_llm", 25))
    )

    state = State(os.getenv("STATE_FILE", settings.get("archivo_estado", "state/state.json")))
    state.data["stats"] = {}

    # En la nube los comandos se atienden una vez cada ciclo (hasta 20 min de
    # espera). Para /whoami o /add eso es demasiado: este modo los responde al
    # instante desde tu equipo sin tocar fuentes ni gastar LLM.
    if args.comandos:
        en_cola_antes = len(state.manual_queue)
        atendidos = bot_poll.process_updates(state)
        state.save()
        log.info("Comandos atendidos: %s", atendidos)

        nuevos = len(state.manual_queue) - en_cola_antes
        if nuevos > 0:
            # Telegram entrega cada mensaje UNA vez: si lo consumes aquí, el
            # ciclo de la nube ya no lo verá. El enlace sólo llegará al agente
            # si subes tu estado.
            log.warning(
                "%s enlace(s) de /add han quedado en TU estado local. Súbelos o "
                "se perderán:  git add state/state.json && git commit -m cola && git push",
                nuevos,
            )
        elif not atendidos:
            log.info("Nada pendiente. Escribe al bot y vuelve a lanzarlo.")
        return 0

    # 1) Comandos de Telegram (/add, botones). Antes de recoger, para que la
    #    cola manual entre en este mismo ciclo.
    if not no_send:
        try:
            bot_poll.process_updates(state)
        except Exception as exc:  # noqa: BLE001
            log.warning("No se pudieron procesar comandos de Telegram: %s", exc)

    # 2) Recogida
    ctx = {"state": state, "config": config}
    raw_items = collect(config, ctx, args.source)
    state.bump("recogidos", len(raw_items))
    log.info("Recogidos %s items en bruto", len(raw_items))

    # 3) Deduplicación
    dedup = Deduplicator(
        state,
        window_hours=int(settings.get("ventana_dedup_horas", 72)),
        fuzzy_threshold=int(settings.get("umbral_similitud", 88)),
    )
    unique = dedup.dedupe_batch(raw_items)
    state.bump("unicos", len(unique))

    # 4) Pre-filtro determinista (gratis)
    candidates: list[Item] = []
    for item in unique:
        reason = prefilter(item)
        if reason:
            log.debug("PREFILTRO descarta (%s): %s", reason, item.title[:70])
            dedup.remember(item, score=None, sent=False)
            state.bump("prefiltrados")
            continue
        candidates.append(item)

    # Con tope de llamadas importa QUÉ noticias entran. Dos ordenaciones
    # estables encadenadas: primero por fecha descendente, luego por prioridad.
    # El resultado es "mejor fuente primero y, dentro de cada una, lo más
    # reciente". Ordenar por fecha ascendente, como hacía antes, significaba
    # gastar el presupuesto en lo más viejo de la cola: veneno para un bot de
    # noticias, que es justo donde el retraso se nota.
    candidates.sort(key=lambda i: i.published_at or "", reverse=True)
    candidates.sort(key=lambda i: int(i.priority))
    if len(candidates) > max_calls:
        log.warning("%s candidatos > tope de %s llamadas; el resto se verá en el próximo ciclo",
                    len(candidates), max_calls)
        candidates = candidates[:max_calls]

    log.info("Candidatos al agente: %s", len(candidates))

    if no_llm:
        for item in candidates:
            print(f"  [p{item.priority}] {item.source:<24} {item.title[:90]}")
            print(f"       {item.url}")
        print(f"\nDRY-RUN: se habrían hecho {len(candidates)} llamadas al LLM. Coste: 0 €.")
        return 0

    # 5) Agente + 6) Envío
    sent = discarded = failed = 0
    for item in candidates:
        try:
            verdict = analyze(item, threshold=threshold)
        except LLMError as exc:
            log.error("Agente falló en '%s': %s", item.title[:60], exc)
            failed += 1
            continue   # sin remember(): se reintenta en el próximo ciclo

        state.bump("llamadas_llm")
        if verdict.incluir_en_telegram:
            try:
                tg.send_briefing(item, verdict, dry_run=no_send)
                sent += 1
                log.info("ENVIADO [%s/10] %s", verdict.relevancia, item.title[:70])
            except tg.TelegramError as exc:
                log.error("Telegram falló: %s", exc)
                failed += 1
                continue
        else:
            discarded += 1
            log.info("descartado [%s/10] %s", verdict.relevancia, item.title[:70])

        dedup.remember(item, score=verdict.relevancia, sent=verdict.incluir_en_telegram)

    state.bump("enviados", sent)
    state.bump("descartados", discarded)

    log.info("Ciclo terminado — enviados: %s | descartados: %s | fallos: %s",
             sent, discarded, failed)

    if no_send:
        # Una prueba no debe consumir estado de producción: si guardásemos,
        # estas noticias quedarían marcadas como vistas y nunca llegarían
        # a Telegram en el primer ciclo real.
        log.info("Modo prueba: el estado NO se guarda; las noticias siguen sin ver")
        return 0

    state.prune(days=int(settings.get("dias_historico", 14)))
    state.save()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
