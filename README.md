# DEMOCLES — briefings de MMA para Instagram

Vigila fuentes de MMA cada 20 minutos, deduplica, puntúa la relevancia con un LLM
barato y envía a Telegram **sólo** lo que puntúa 7/10 o más, ya convertido en un
briefing listo para publicar. El humano decide en 20 segundos.

**Coste objetivo: 0 €/mes.** Máximo 3 usuarios.

```
fetchers ─→ normalizador ─→ deduplicador ─→ pre-filtro ─→ agente LLM ─→ Telegram
(RSS, Google News,          3 capas         keywords     1 llamada:      >= 7/10
 Reddit, Twitter,           (URL/título/    (gratis)     nota+briefing
 /add manual)                similitud)
```

---

## Arranque rápido (local)

```bash
git clone <tu-repo> && cd DEMOCLES
python -m venv .venv && .venv\Scripts\activate      # Windows
pip install -r requirements.txt
copy .env.example .env                              # y rellena las claves
python main.py --dry-run                            # sin gastar nada
python main.py                                      # ciclo real
```

### Comprobaciones sin gastar tokens

| Comando | Qué hace |
|---|---|
| `python main.py --dry-run` | Recoge y deduplica. Ni LLM ni Telegram. Coste 0 €. |
| `python main.py --no-llm` | Igual que dry-run, pero sí procesa comandos de Telegram. |
| `python main.py --no-send` | Llama al LLM de verdad e imprime el mensaje en consola. |
| `python main.py --source "r/MMA"` | Sólo esa fuente. |
| `python main.py --limit 3` | Máximo 3 llamadas al modelo. |
| `python -m pytest tests -q` | 29 tests, sin red y sin tokens. |

---

## Configuración

Todo vive en dos sitios:

- **`config.yaml`** — qué fuentes se leen. Añadir una fuente **no requiere tocar
  código**: copia un bloque, cambia `name`/`url`, listo.
- **`.env`** — claves y credenciales. Nunca se sube al repositorio.

### Proveedor de LLM

Se cambia con una variable, sin tocar código:

```bash
LLM_PROVIDER=gemini   LLM_MODEL=gemini-3.6-flash          # free tier — recomendado
LLM_PROVIDER=groq     LLM_MODEL=llama-3.3-70b-versatile   # free tier — respaldo
LLM_PROVIDER=openai   LLM_MODEL=gpt-4o-mini               # de pago, barato
LLM_PROVIDER=anthropic LLM_MODEL=claude-haiku-4-5         # de pago, mejor formato
```

Si el free tier de uno se agota a mitad de mes, cambias la variable y sigues.

`LLM_MODEL` admite una **lista separada por comas**: ante un 429 (cuota agotada) o
un 404 (modelo retirado) se pasa solo al siguiente. Los modelos `gemini-2.x`
devuelven 404 en claves creadas desde 2026 — no los pongas los primeros.

---

## Despliegue en GitHub Actions (0 €)

1. Sube el repositorio. **Hazlo público** si quieres minutos ilimitados de Actions;
   en repositorio privado tienes 2.000 min/mes, suficiente para un ciclo cada 20 min
   si cada ejecución dura menos de un minuto. En repositorio público **no subas
   nunca el `.env`** (ya está en `.gitignore`).
2. *Settings → Secrets and variables → Actions → Secrets*: `TELEGRAM_BOT_TOKEN`,
   `TELEGRAM_CHAT_ID`, `TELEGRAM_ALLOWED_USERS`, `GEMINI_API_KEY`,
   `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`.
3. *Variables* (no son secretas): `LLM_PROVIDER`, `LLM_MODEL`, `TWITTER_STRATEGY`,
   `RSSHUB_BASE`, `RELEVANCE_THRESHOLD`, `MAX_LLM_CALLS`.
4. *Settings → Actions → General → Workflow permissions* → **Read and write**.
5. Pestaña *Actions* → `DEMOCLES` → **Run workflow** para la primera prueba.

**Persistencia del estado.** `state/state.json` se commitea al final de cada
ejecución. Eso resuelve dos cosas a la vez: sobrevive entre ejecuciones (los
runners son efímeros) y mantiene vivo el cron, porque GitHub desactiva los
workflows programados tras 60 días sin actividad en el repositorio.

**Puntualidad.** El cron de GitHub se retrasa entre 5 y 15 minutos cuando hay
carga. Para MMA es aceptable. Si necesitas puntualidad al minuto, mueve el cron a
una Raspberry Pi o a una VM del Oracle Free Tier con el mismo `main.py`.

---

## Entrada manual de Instagram

Instagram **no se scrapea** en este proyecto. El motivo está documentado en
`fetchers/instagram.py`: exige sesión iniciada, bloquea IPs de datacenter y quema
cuentas en horas. En su lugar, desde Telegram:

```
/add https://www.instagram.com/p/Cxyz123/ Topuria confirma subida de peso
/add https://www.instagram.com/reel/Cabc456/
/status
/help
```

El post entra en el mismo pipeline con prioridad máxima (ya lo ha filtrado un
humano) y vuelve como briefing en el siguiente ciclo. Pegar una URL de Instagram
a secas equivale a `/add`.

---

## Mantenimiento

| Síntoma | Causa probable | Solución |
|---|---|---|
| `feed ilegible` en los logs | El medio movió su RSS | Corrige la `url` en `config.yaml`, o pon `activo: false` y deja que lo cubra su entrada `gnews` |
| `Twitter sin datos` | RSSHub/Nitter caídos | Normal. Reddit y las webs cubren el hueco. Revisa `RSSHUB_BASE` cuando puedas |
| `Reddit HTTP 403` | Sin credenciales o UA genérico | Crea la app *script* y rellena `REDDIT_CLIENT_ID`/`SECRET` |
| Llegan duplicados | Umbral de similitud alto | Baja `umbral_similitud` de 88 a 84 en `config.yaml` |
| Llega demasiado | Umbral de relevancia bajo | Sube `RELEVANCE_THRESHOLD` a 8 |
| No llega nada | Umbral alto o prefiltro agresivo | Baja a 6 y mira los logs de `PREFILTRO descarta` |
| Se agota la cuota del LLM | Free tier consumido | Cambia `LLM_PROVIDER` a `groq` |

**Ninguna fuente caída tumba el ciclo**: `run_source()` aísla los errores por
fuente, los registra y continúa con las demás.

---

## Legalidad y buena vecindad

- `robots.txt` se respeta en todas las fuentes web (`util.robots_allows`).
- Rate limiting por dominio, User-Agent identificable con contacto.
- Sólo se almacenan **titular, fragmento y enlace**. Nunca el artículo completo.
  El briefing es texto original generado para tu cuenta, no una copia del medio.
- El scraping de Twitter/X e Instagram vulnera sus Términos de Uso. Por eso
  Instagram es manual y Twitter es la única pata explícitamente frágil y opcional.
