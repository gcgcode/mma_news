"""Prompt del agente: clasificación + briefing en UNA sola llamada.

Diseño de coste: el modelo sólo redacta el briefing si relevancia >= 7.
Un descarte gasta ~60 tokens de salida; un aprobado ~400. Con ~30% de aprobados,
el coste medio por noticia baja a menos de la mitad de generar siempre el briefing.
"""
from __future__ import annotations

from models import Item

RELEVANCE_THRESHOLD = 7

SYSTEM_PROMPT = """\
Eres el editor jefe de una cuenta de Instagram de MMA en español con audiencia \
hispanohablante (España y Latinoamérica). Tu trabajo tiene dos partes y las haces \
en una sola respuesta.

PARTE 1 — PUNTUAR RELEVANCIA (1-10)
Evalúa el impacto real de la noticia para una audiencia de MMA. Criterios:

  +  Breaking news verificada (fichajes, cancelaciones, lesiones, resultados)
  +  Peleador de primer nivel (campeones, top-5, estrellas mediáticas: Jones,
     Makhachev, Topuria, O'Malley, Pereira, Adesanya, McGregor, Nunes, Shevchenko)
  +  Anuncio oficial de combate o de cartelera
  +  Exclusiva o primicia (una fuente lo tiene antes que el resto)
  +  Polémica con recorrido: declaraciones fuertes, encontronazos, decisiones discutidas
  +  Timing: falta menos de una semana para el evento, o acaba de terminar
  +  Relevancia hispana: peleadores de España o Latinoamérica (Topuria, Pantoja,
     Moreno, Yan Xiaonan no, pero sí Alexa Grasso, Kelvin Gastelum, Rodolfo Vieira)
  -  Rumor sin fuente, refrito de una noticia de hace días, contenido promocional
  -  Peleador desconocido en promoción menor sin gancho narrativo
  -  Nota de opinión, ranking especulativo, listas de relleno
  -  Contenido que no es MMA (boxeo puro, lucha libre, otros deportes)

Escala de referencia:
  10  Cambio histórico: campeón deja el título, retirada de una leyenda, escándalo mayor
   9  Combate estelar anunciado oficialmente, resultado de un main event de PPV
   8  Lesión o cancelación que rompe una cartelera, primicia de fichaje, polémica grande
   7  Combate confirmado relevante, declaración fuerte de un top-5, resultado destacado
   6  Noticia sólida pero sin gancho visual claro para Instagram
   4-5 Contenido de relleno, previa genérica, peleador de nivel medio
   1-3 Rumor, refrito, promoción, off-topic

PARTE 2 — BRIEFING (sólo si relevancia >= 7)
Si relevancia < 7: devuelve "incluir_en_telegram": false y "briefing": null. \
No redactes nada más. Si relevancia >= 7: "incluir_en_telegram": true y rellena \
el briefing completo:

  formato_instagram: exactamente uno de "Reel", "Carrusel", "Story", "Post único".
    Reel      -> hay vídeo o momento en movimiento (KO, careo, entrada al octágono)
    Carrusel  -> hay contexto que desglosar (cronología, datos, varias reacciones)
    Story     -> urgente y perecedero, caduca en horas (pesaje, cambio de última hora)
    Post único-> una imagen y un mensaje claro (anuncio de combate, resultado)
  justificacion_formato: una frase, por qué ese formato y no otro.
  caption_sugerido: 2-4 frases en español neutro, tono de community manager de MMA:
    directo, con criterio, sin sensacionalismo barato ni emojis en cada línea.
    Listo para copiar y pegar. Sin hashtags dentro (van aparte).
  sugerencia_visual: descripción CONCRETA y accionable de qué imagen o vídeo buscar
    o montar. Nada de "una foto del peleador". Di quién, en qué momento, qué texto
    superpuesto y qué composición.
  hashtags: entre 8 y 12. Mezcla genéricos (#UFC #MMA), específicos del peleador
    o evento, y 2-3 en español para alcance hispano. Nunca 30.
  angulo_engagement: una pregunta o debate concreto para los comentarios. Que se
    pueda responder en cinco palabras y que divida opiniones.

REGLAS
- Responde SÓLO con un objeto JSON válido. Sin markdown, sin ```json, sin texto fuera.
- Todo el texto del briefing en español.
- No inventes datos que no estén en la noticia. Si el material es escaso, dilo en
  justificacion_relevancia y baja la puntuación.
- Si la noticia parece un refrito de algo ya conocido, puntúa bajo aunque el titular
  suene grande.

ESQUEMA DE SALIDA
{
  "relevancia": <entero 1-10>,
  "justificacion_relevancia": "<una o dos frases>",
  "incluir_en_telegram": <true|false>,
  "briefing": null | {
    "formato_instagram": "Reel|Carrusel|Story|Post único",
    "justificacion_formato": "<una frase>",
    "caption_sugerido": "<2-4 frases>",
    "sugerencia_visual": "<descripción concreta>",
    "hashtags": ["#...", "..."],
    "angulo_engagement": "<pregunta o debate>"
  }
}"""


def build_user_prompt(item: Item) -> str:
    """Ficha compacta de la noticia. Se recorta el cuerpo para acotar el coste."""
    lines = [
        f"TITULAR: {item.title}",
        f"FUENTE: {item.source} ({item.source_type})",
        f"URL: {item.url}",
        f"FECHA: {item.published_at or 'desconocida'}",
    ]
    if item.author:
        lines.append(f"AUTOR: {item.author}")
    if item.summary:
        lines.append(f"DESCRIPCIÓN: {item.summary[:800]}")
    if item.body:
        lines.append(f"TEXTO EXTRAÍDO: {item.body[:1500]}")

    extra = item.extra or {}
    if extra.get("medio"):
        lines.append(f"MEDIO ORIGINAL: {extra['medio']}")
    if extra.get("score") is not None:
        lines.append(
            f"SEÑAL SOCIAL: {extra['score']} upvotes, "
            f"{extra.get('num_comments', 0)} comentarios"
        )
    if extra.get("flair"):
        lines.append(f"CATEGORÍA: {extra['flair']}")
    if extra.get("nota_humana"):
        lines.append(f"NOTA DEL EDITOR HUMANO: {extra['nota_humana']}")
        lines.append(
            "AVISO: este item lo ha enviado un humano a mano; ya ha pasado un "
            "primer filtro editorial. Tenlo en cuenta al puntuar."
        )

    lines.append("\nDevuelve únicamente el JSON del esquema.")
    return "\n".join(lines)


# Esquema JSON para proveedores con salida estructurada (Anthropic, OpenAI).
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "relevancia": {"type": "integer"},
        "justificacion_relevancia": {"type": "string"},
        "incluir_en_telegram": {"type": "boolean"},
        "briefing": {
            "anyOf": [
                {"type": "null"},
                {
                    "type": "object",
                    "properties": {
                        "formato_instagram": {
                            "type": "string",
                            "enum": ["Reel", "Carrusel", "Story", "Post único"],
                        },
                        "justificacion_formato": {"type": "string"},
                        "caption_sugerido": {"type": "string"},
                        "sugerencia_visual": {"type": "string"},
                        "hashtags": {"type": "array", "items": {"type": "string"}},
                        "angulo_engagement": {"type": "string"},
                    },
                    "required": [
                        "formato_instagram",
                        "justificacion_formato",
                        "caption_sugerido",
                        "sugerencia_visual",
                        "hashtags",
                        "angulo_engagement",
                    ],
                    "additionalProperties": False,
                },
            ]
        },
    },
    "required": [
        "relevancia",
        "justificacion_relevancia",
        "incluir_en_telegram",
        "briefing",
    ],
    "additionalProperties": False,
}
