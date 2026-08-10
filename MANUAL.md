# MANUAL DE USUARIO — DEMOCLES

Sistema de vigilancia de noticias de MMA que te manda a Telegram, cada 20 minutos,
sólo lo que merece la pena publicar, ya convertido en un briefing listo para
Instagram.

**Tiempo total de instalación: 30-40 minutos.** No hace falta saber programar.

---

## Índice

1. [Qué vas a montar](#1-qué-vas-a-montar)
2. [Antes de empezar](#2-antes-de-empezar)
3. [Instalación local](#3-instalación-local)
4. [Conseguir las credenciales](#4-conseguir-las-credenciales)
5. [Rellenar el archivo .env](#5-rellenar-el-archivo-env)
6. [Verificar que todo funciona](#6-verificar-que-todo-funciona)
7. [Primeras pruebas](#7-primeras-pruebas)
8. [Despliegue en GitHub Actions](#8-despliegue-en-github-actions)
9. [Uso diario](#9-uso-diario)
10. [Ajustar el comportamiento](#10-ajustar-el-comportamiento)
11. [Problemas frecuentes](#11-problemas-frecuentes)
12. [Mantenimiento](#12-mantenimiento)
13. [Pausar o desinstalar](#13-pausar-o-desinstalar)

---

## 1. Qué vas a montar

```
Cada 20 min, en un servidor gratuito de GitHub:

  1. Lee ~19 fuentes de MMA (Reddit, medios, Google News, Twitter/X)
  2. Elimina las noticias repetidas entre fuentes
  3. Descarta el ruido con un filtro de palabras (gratis)
  4. Pide a una IA que puntúe cada noticia de 1 a 10
  5. Si puntúa 7 o más, la IA escribe el briefing completo
  6. Te llega a Telegram: formato, caption, visual, hashtags, gancho
  7. Tú decides en 20 segundos si lo publicas
```

**Lo que NO hace:** publicar en Instagram por ti. Eso es deliberado — publicar
automáticamente es lo que hace que una cuenta parezca un bot.

**Coste:** 0 €/mes.

---

## 2. Antes de empezar

Necesitas cuatro cosas. Las tres primeras son obligatorias:

| # | Qué | Dónde | Coste | Tiempo |
|---|---|---|---|---|
| 1 | **Bot de Telegram** | app de Telegram, chat con `@BotFather` | 0 € | 3 min |
| 2 | **Clave de IA** (Gemini) | [aistudio.google.com](https://aistudio.google.com) | 0 € | 3 min |
| 3 | **Cuenta de GitHub** | [github.com](https://github.com) | 0 € | 5 min |

Sin la nº 3 el sistema funciona igual, pero tendrás que lanzarlo tú a mano desde
tu ordenador. Con ella se ejecuta solo, aunque tengas el ordenador apagado.

**Reddit no necesita credenciales**: se lee por su RSS público. Ver sección 4.3.

También necesitas **Python 3.10 o superior** instalado. Compruébalo abriendo
PowerShell y escribiendo:

```powershell
python --version
```

Si dice `Python 3.10.x` o superior, perfecto. Si no lo reconoce, instálalo desde
[python.org/downloads](https://www.python.org/downloads/) y marca la casilla
**"Add Python to PATH"** durante la instalación.

---

## 3. Instalación local

Abre **PowerShell** y ejecuta estos comandos uno a uno.

**Paso 3.1 — Ir a la carpeta del proyecto**

```powershell
cd C:\Users\Usuario\Desktop\DEMOCLES
```

**Paso 3.2 — Crear un entorno aislado** (recomendado: evita que las librerías de
este proyecto choquen con otros que tengas)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

> Si sale un error de *"la ejecución de scripts está deshabilitada"*, ejecuta
> primero:
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
> ```
> y responde `S`. Es un permiso de PowerShell, no del proyecto.

Cuando el entorno está activo, verás `(.venv)` al principio de la línea.
**Tendrás que activarlo cada vez que abras una PowerShell nueva.**

**Paso 3.3 — Instalar las librerías**

```powershell
pip install -r requirements.txt
```

Tarda 1-2 minutos. Al final debe decir `Successfully installed ...`.

**Paso 3.4 — Crear tu archivo de configuración**

```powershell
Copy-Item .env.example .env
```

Ese `.env` es donde van tus claves. **Nunca se sube a internet** — está protegido
por `.gitignore`.

---

## 4. Conseguir las credenciales

### 4.1 · Bot de Telegram (obligatorio)

**Crear el bot:**

1. Abre Telegram y busca `@BotFather` (el que tiene la marca de verificación azul).
2. Pulsa **Start** y escribe `/newbot`.
3. Te pide un **nombre** (lo que se ve): por ejemplo `Democles MMA`.
4. Te pide un **usuario**, que debe terminar en `bot`: por ejemplo `democles_mma_bot`.
   Si está cogido, prueba otro.
5. BotFather te responde con un mensaje que contiene una línea así:

   ```
   Use this token to access the HTTP API:
   7812345678:AAH9xK2mQpL7vN3sR8tYuI4oP1aS6dF0gH2
   ```

   **Ese es tu `TELEGRAM_BOT_TOKEN`.** Cópialo entero, incluidos los dos puntos.

**Conseguir tu ID de chat** — pon el token en `.env` y deja que el proyecto lo
averigüe por ti:

```powershell
python chat_id.py
```

El script comprueba el token, detecta si hay un webhook estorbando y luego se
queda esperando. Abre Telegram, escríbele cualquier cosa a tu bot y te imprimirá
las dos líneas listas para pegar en `.env`:

```
TELEGRAM_CHAT_ID=1379532921
TELEGRAM_ALLOWED_USERS=1379532921
```

<details>
<summary>Método manual, si prefieres hacerlo desde el navegador</summary>

1. Busca tu bot por su usuario, ábrelo y pulsa **Start**. Escríbele algo.
   **Obligatorio**: un bot no puede escribirte hasta que tú le hables primero.
2. Abre `https://api.telegram.org/bot<TOKEN>/getUpdates` sustituyendo `<TOKEN>`.
3. Busca `"chat":{"id":1379532921` — ese número es el que necesitas.

</details>

> **Si te devuelve `{"ok":true,"result":[]}`**, es una de estas tres, en orden de
> frecuencia:
>
> 1. **No le has escrito al bot todavía**, o consultaste la URL antes de escribir.
> 2. **Hay un webhook configurado**: mientras exista, `getUpdates` devuelve vacío
>    siempre. Bórralo abriendo `https://api.telegram.org/bot<TOKEN>/deleteWebhook`.
> 3. **Los mensajes ya se consumieron**: Telegram los borra al leerlos con un
>    offset mayor, y los descarta pasadas 24 h. Escribe otro mensaje.
>
> `python chat_id.py` distingue los tres casos y te dice cuál es.

> ⚠️ **Error clásico:** dejar el `123456789` de ejemplo en el `.env`. Telegram
> responde `Bad Request: chat not found` y parece un problema del token cuando en
> realidad es el chat. `python doctor.py --enviar` lo detecta al instante.

---

### 4.2 · Clave de Gemini (obligatorio)

1. Entra en [aistudio.google.com](https://aistudio.google.com) con tu cuenta de
   Google.
2. Arriba a la izquierda pulsa **Get API key** (o *Obtener clave de API*).
3. Pulsa **Create API key** → elige un proyecto o crea uno nuevo.
4. Copia la clave. Empieza por `AIza...`.

   **Esa es tu `GEMINI_API_KEY`.**

> **Sobre el plan gratuito:** Gemini tiene un nivel gratuito con límite de
> peticiones al día. Con ~150 noticias diarias vas sobrado, pero los límites los
> cambia Google sin avisar. Si algún día se agota, cambias una línea del `.env`
> y pasas a Groq (también gratis). Está explicado en la sección 10.

> ⚠️ **Cuidado con el nombre del modelo.** Google retira modelos y las claves
> nuevas dejan de poder usarlos: `gemini-2.5-flash` y anteriores responden
> `404 — no longer available to new users`. Por eso `LLM_MODEL` acepta una
> **lista separada por comas**: si el primero falla por cuota (429) o por estar
> retirado (404), el sistema pasa solo al siguiente sin perder el ciclo.
>
> Cadena verificada y funcionando:
> `gemini-3.6-flash,gemini-3.5-flash,gemini-3.5-flash-lite`
>
> Para ver qué modelos admite **tu** clave en cualquier momento:
> `https://generativelanguage.googleapis.com/v1beta/models?key=TU_CLAVE`

---

### 4.3 · Reddit — no hay que configurar nada

Reddit ha endurecido su política: usar la API oficial exige **solicitar permiso**
y esperar aprobación. Como no queremos bloquear el despliegue por eso, el sistema
lee r/MMA y r/ufc por su **RSS público**, que sigue abierto y no pide credenciales.

**No tienes que hacer nada.** Ya está configurado así en `config.yaml`.

> **Lo que cuesta esta decisión, dicho claramente:**
>
> - El RSS no expone el número de votos, así que no se puede filtrar por
>   popularidad mínima. Se compensa leyendo `hot` en lugar de `new`: lo que sube
>   ahí ya lo ha filtrado la comunidad.
> - Desde GitHub Actions (IPs de datacenter) Reddit devuelve `403` o `429` con
>   más frecuencia que desde tu casa. Si pasa, la fuente registra un aviso y el
>   ciclo continúa con las 18 fuentes restantes. No se rompe nada.
>
> **El día que Reddit te apruebe el acceso a la API**, tendrás una fuente más
> fiable y con filtro por votos. Entonces:
>
> 1. Crea la app en [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps),
>    tipo **script**, con `redirect uri: http://localhost:8080`
> 2. Copia el ID (bajo `personal use script`) y el `secret` al `.env`
> 3. En `config.yaml`: pon `activo: true` en *"r/MMA (API oficial)"* y
>    `activo: false` en las dos entradas `reddit_rss`

---

### 4.4 · Twitter/X (opcional, y probablemente puedas saltártelo)

Twitter/X no tiene forma gratuita y fiable de leerse. El sistema está diseñado
para funcionar sin él. **Mi recomendación: déjalo desactivado al principio.**
Reddit reposta los tuits importantes en minutos.

Si más adelante quieres intentarlo, necesitarías desplegar tu propio
[RSSHub](https://docs.rsshub.app/) en un hosting gratuito y poner su dirección en
`RSSHUB_BASE`. Es un proyecto aparte y se rompe cada pocas semanas.

Para desactivarlo del todo, deja esta línea vacía en el `.env`:

```
TWITTER_STRATEGY=
```

---

## 5. Rellenar el archivo .env

Abre `C:\Users\Usuario\Desktop\DEMOCLES\.env` con el Bloc de notas (clic derecho →
*Abrir con* → *Bloc de notas*) y sustituye los valores de ejemplo por los tuyos.

Debe quedar algo así:

```ini
# ---------- Telegram ----------
TELEGRAM_BOT_TOKEN=7812345678:AAH9xK2mQpL7vN3sR8tYuI4oP1aS6dF0gH2
TELEGRAM_CHAT_ID=123456789
TELEGRAM_ALLOWED_USERS=123456789

# ---------- LLM ----------
LLM_PROVIDER=gemini
LLM_MODEL=gemini-3.6-flash,gemini-3.5-flash,gemini-3.5-flash-lite
GEMINI_API_KEY=tu-clave-real-aqui

RELEVANCE_THRESHOLD=7
MAX_LLM_CALLS=25

# ---------- Reddit (sin credenciales: se usa el RSS público) ----------
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
# Este sí conviene rellenarlo: Reddit trata mucho mejor a los clientes que se
# identifican. Pon tu usuario real de Reddit (o cualquiera si no tienes).
REDDIT_USER_AGENT=democles-mma-bot/1.0 by u/tu_usuario_reddit

# ---------- Twitter (desactivado) ----------
TWITTER_STRATEGY=

# ---------- Varios ----------
STATE_FILE=state/state.json
LOG_LEVEL=INFO
```

**Reglas al editar:**

- ❌ **Sin comillas:** `TELEGRAM_CHAT_ID=123456789`, no `="123456789"`
- ❌ **Sin espacios alrededor del `=`**
- ✅ Las líneas que empiezan por `#` son comentarios, se ignoran
- ✅ Las claves que no uses puedes dejarlas vacías o borrarlas
- 💾 Guarda con `Ctrl+S` y **asegúrate de que se llama `.env`**, no `.env.txt`
  (el Bloc de notas a veces añade `.txt`; si pasa, renómbralo desde el explorador
  con las extensiones visibles activadas)

---

## 6. Verificar que todo funciona

Este es el paso que te ahorra media hora de frustración. El proyecto trae un
verificador que comprueba cada credencial por separado:

```powershell
python doctor.py
```

Te dirá, línea por línea, qué funciona y qué no:

```
🔧 DEMOCLES — verificación de instalación

── Entorno ───────────────────────────────────────────
✅ Python 3.10.11
✅ Dependencias instaladas

── Archivos del proyecto ─────────────────────────────
✅ Archivo .env encontrado
✅ config.yaml válido — 19 fuentes activas
⚠️  5 fuentes con RSS sin confirmar

── Telegram ──────────────────────────────────────────
✅ Bot conectado: @democles_mma_bot
✅ TELEGRAM_CHAT_ID definido (123456789)

── Modelo de lenguaje ────────────────────────────────
✅ Proveedor: gemini · modelo: gemini-2.5-flash
✅ Llamada de prueba correcta

── Reddit ────────────────────────────────────────────
✅ Reddit vía RSS público — 25 items

── Resumen ───────────────────────────────────────────
   ✅ correctos: 9
   ⚠️ avisos:    3   (no impiden funcionar)
   ❌ fallos:    0

🎉 Todo listo.
```

**Interpretación de los símbolos:**

| Símbolo | Significado |
|---|---|
| ✅ | Funciona |
| ⚠️ | Opcional sin configurar. **No impide funcionar** |
| ❌ | Hay que arreglarlo antes de seguir |

**Prueba de fuego de Telegram** — envía un mensaje real a tu chat:

```powershell
python doctor.py --enviar
```

Si te llega *"🔧 DEMOCLES — mensaje de prueba"*, Telegram está perfecto.

**Prueba de las fuentes** — descarga de verdad de cada medio (tarda ~1 minuto):

```powershell
python doctor.py --fuentes
```

Aquí verás cuáles de los RSS marcados `[verificar]` funcionan de verdad y cuáles
hay que desactivar.

---

## 7. Primeras pruebas

Hazlas en este orden. Cada una gasta un poco más que la anterior.

**7.1 — Sin gastar absolutamente nada**

```powershell
python main.py --dry-run
```

Recoge noticias reales, las deduplica y te dice cuántas llamadas *habría* hecho a
la IA. No llama a la IA ni envía nada. Coste: 0 €.

Salida esperada:

```
Recogidos 30 items en bruto
Dedup: 30 entran -> 25 únicos (0 ya vistos, 5 duplicados del lote)
Candidatos al agente: 23
  [p2] r/MMA    Islam Makhachev vs. Ian Machado Garry oficial para UFC 330
  ...
DRY-RUN: se habrían hecho 23 llamadas al LLM. Coste: 0 €.
```

**7.2 — Con IA, pero sin enviar a Telegram**

```powershell
python main.py --no-send --limit 3
```

Analiza 3 noticias de verdad e imprime los briefings en la pantalla. Así ves la
calidad del resultado antes de llenarte el chat. Coste: céntimos de céntimo.

**7.3 — Ciclo completo real**

```powershell
python main.py --limit 5
```

Ahora sí: analiza 5 noticias y te manda a Telegram las que puntúen 7 o más.

**7.4 — Sin límite (lo que hará el sistema en producción)**

```powershell
python main.py
```

> **Aviso sobre la primera ejecución:** el histórico está vacío, así que todas las
> noticias son "nuevas" y puede que te lleguen 8-10 mensajes de golpe. Es normal y
> pasa **una sola vez**. A partir de ahí sólo llega lo nuevo. Si quieres evitarlo,
> haz la primera ejecución con `--limit 3`.

---

## 8. Despliegue en GitHub Actions

Esto es lo que hace que el sistema funcione solo, cada 20 minutos, con tu
ordenador apagado. Es gratis.

> Se usa la cuenta de GitHub que ya tienes configurada en el equipo
> (`gcgcode`). No hace falta tocar la configuración de git: la identidad global
> ya está puesta y las credenciales guardadas en Windows sirven tal cual.

### 8.1 · Crear el repositorio

1. Entra en [github.com](https://github.com) con tu cuenta.
2. Arriba a la derecha: **+** → **New repository**.
3. Rellena:
   - **Repository name:** `democles`
   - **Description:** `Briefings de MMA para Instagram`
   - **Public** ✅ ← **elige público**
   - **NO marques** *Add a README file*, ni `.gitignore`, ni licencia
4. **Create repository**.

> **¿Por qué público?** GitHub Actions da **minutos ilimitados** en repositorios
> públicos. En privados tienes 2.000 minutos al mes; un ciclo cada 20 minutos son
> 2.160 ejecuciones, así que irías muy justo.
>
> **¿Es seguro?** Sí, siempre que **nunca subas el `.env`**. Está protegido por
> `.gitignore` y lo verificaremos antes de subir. Las claves van en los *Secrets*
> de GitHub, que están cifrados y no se ven ni siendo el repo público.

### 8.2 · Inicializar el repositorio

En PowerShell, dentro de `C:\Users\Usuario\Desktop\DEMOCLES`:

```powershell
cd C:\Users\Usuario\Desktop\DEMOCLES
git init
git branch -M main
```

Comprueba con qué identidad vas a firmar los commits:

```powershell
git config user.name ; git config user.email
```

Debe devolver tu usuario y email de GitHub. Si sale vacío, configúralos:

```powershell
git config --global user.name  "gcgcode"
git config --global user.email "tu-email@ejemplo.com"
```

### 8.3 · Comprobación de seguridad antes de subir

**Haz esto siempre.** Verifica que el `.env` con tus claves no va a subirse:

```powershell
git add .
git status --short
```

En la lista **NO debe aparecer `.env`** (sí debe aparecer `.env.example`, que sólo
tiene valores falsos). Si aparece `.env`, para y avísame antes de continuar.

Comprobación automática equivalente:

```powershell
git check-ignore -v .env
```

Debe responder `.gitignore:1:.env	.env`. Si no responde nada, el `.env` **no**
está protegido: no subas nada.

### 8.4 · Primer envío

Sustituye `TU_USUARIO` por tu usuario de GitHub:

```powershell
git commit -m "DEMOCLES: sistema de briefings de MMA"
git remote add origin https://github.com/TU_USUARIO/democles.git
git push -u origin main
```

Lo más probable es que suba directamente, porque Windows ya tiene guardadas tus
credenciales de GitHub.

**Si te pide usuario y contraseña**, GitHub ya no acepta la contraseña normal:
necesitas un *token de acceso*.

1. [github.com/settings/tokens](https://github.com/settings/tokens) →
   **Generate new token (classic)**
2. **Note:** `democles` · **Expiration:** 90 días o *No expiration*
3. **Scopes:** marca **únicamente `repo`** ⬅️ *nada más*
4. **Generate token** y cópialo (`ghp_...`)
5. Repite el `push`: usuario = el tuyo, contraseña = **el token**

> El token **sólo se muestra una vez**. Trátalo como una contraseña.

### 8.5 · Cargar las claves en GitHub

En tu repositorio: **Settings** → **Secrets and variables** → **Actions**.

**Pestaña *Secrets*** → botón **New repository secret**, uno por uno:

| Name | Secret |
|---|---|
| `TELEGRAM_BOT_TOKEN` | tu token de BotFather |
| `TELEGRAM_CHAT_ID` | tu número de chat |
| `TELEGRAM_ALLOWED_USERS` | el mismo número |
| `GEMINI_API_KEY` | tu clave de Gemini |

> Reddit no necesita *Secrets*: se usa su RSS público, sin credenciales.

**Pestaña *Variables*** → botón **New repository variable**:

| Name | Value |
|---|---|
| `LLM_PROVIDER` | `gemini` |
| `LLM_MODEL` | `gemini-3.6-flash,gemini-3.5-flash,gemini-3.5-flash-lite` |
| `TWITTER_STRATEGY` | *(déjalo vacío)* |
| `RELEVANCE_THRESHOLD` | `7` |
| `MAX_LLM_CALLS` | `25` |
| `REDDIT_USER_AGENT` | `democles-mma-bot/1.0 by u/tu_usuario_reddit` |

> **Secrets vs Variables:** los *Secrets* se cifran y nadie puede leerlos, ni tú
> después de guardarlos. Las *Variables* se ven en claro — por eso ahí sólo van
> ajustes, nunca claves.

### 8.6 · Dar permiso de escritura al robot

Sin esto el sistema no puede recordar qué noticias ya te envió y te llegarán
repetidas cada 20 minutos.

**Settings** → **Actions** → **General** → baja hasta *Workflow permissions* →
marca **Read and write permissions** → **Save**.

### 8.7 · Primera ejecución en la nube

1. Pestaña **Actions** del repositorio.
2. Si sale un aviso *"Workflows aren't being run on this forked repository"* o
   similar, pulsa el botón verde para habilitarlos.
3. En la barra lateral izquierda: **DEMOCLES — ciclo de noticias MMA**.
4. Botón **Run workflow** (derecha) → **Run workflow**.
5. Espera ~40 segundos y refresca. Debe salir un ✅ verde.

**Cómo leer el resultado:** pulsa sobre la ejecución → **ciclo** → despliega
*Ejecutar ciclo*. Verás el mismo registro que en tu ordenador:

```
Fuente 'r/MMA': 25 items (se toman 25)
Recogidos 118 items en bruto
Dedup: 118 entran -> 74 únicos (0 ya vistos, 44 duplicados del lote)
Candidatos al agente: 25
ENVIADO [9/10] Makhachev vs Machado Garry oficial para UFC 330
Ciclo terminado — enviados: 4 | descartados: 21 | fallos: 0
```

Y en el paso *Persistir estado* debe aparecer un `git commit` — esa es la memoria
del sistema.

**A partir de aquí funciona solo cada 20 minutos.** Ya puedes apagar el ordenador.

> **Sobre la puntualidad:** GitHub retrasa los cron de los repos gratuitos entre 5
> y 15 minutos cuando tiene carga. Para MMA es aceptable. Las noches de evento, si
> quieres inmediatez, pulsa **Run workflow** a mano.

---

## 9. Uso diario

### 9.1 · Leer un briefing

Cuando llegue un mensaje, léelo en este orden y decide:

```
🚨 RELEVANCIA: 9/10        ← ¿merece mi tiempo? Si es 7, quizá no
📰 [titular]               ← ¿de qué va?
📍 fuente · abrir noticia  ← ¿de quién viene? ¿me fío?
💬 Por qué importa: ...    ← el argumento de la IA
🎠 FORMATO: Carrusel       ← qué tipo de post
🖼️ SUGERENCIA VISUAL       ← qué imagen buscar
📝 CAPTION SUGERIDO        ← mantén pulsado para copiar
🎯 ÁNGULO DE ENGAGEMENT    ← la pregunta para comentarios
🏷️ HASHTAGS                ← mantén pulsado para copiar
```

Los botones **👍 Publicar / ✏️ Editar / ❌ Descartar** son para tu propio control:
te confirman la pulsación, pero no publican nada. La publicación siempre la haces
tú en Instagram.

**Truco:** mantén pulsado el caption o los hashtags y Telegram te ofrece *Copiar*.
Están en formato monoespaciado precisamente para eso.

### 9.2 · Enviar un post de Instagram al sistema

Cuando veas algo bueno en tu feed de Instagram:

1. En Instagram: **⋯** (o el icono de compartir) → **Copiar enlace**
2. En tu chat con el bot de Telegram:

```
/add https://www.instagram.com/p/Cxyz123/ Topuria confirma subida a peso ligero
```

La nota del final es opcional pero **mejora mucho el resultado**: la IA no puede
ver la imagen, así que tu frase es todo el contexto que tiene.

También vale pegar el enlace a secas, sin `/add`.

El briefing te llega en el siguiente ciclo (máximo 20 minutos).

### 9.3 · Otros comandos

| Comando | Qué hace |
|---|---|
| `/status` | Cuántas noticias procesadas, enviadas y en cola |
| `/help` | Recordatorio de comandos |

---

## 10. Ajustar el comportamiento

### 10.1 · Recibo demasiadas noticias / muy pocas

El umbral de relevancia decide qué se envía. Cámbialo en GitHub:
**Settings → Secrets and variables → Actions → Variables → `RELEVANCE_THRESHOLD`**

| Valor | Efecto |
|---|---|
| `6` | Muy permisivo: ~10-15 mensajes al día |
| `7` | **Por defecto:** ~4-8 al día. Equilibrado |
| `8` | Sólo lo importante: ~2-4 al día |
| `9` | Sólo bombazos: 0-2 al día |

Cambia **de uno en uno** y deja pasar un día antes de volver a tocarlo.

### 10.2 · Añadir o quitar una fuente

Edita `config.yaml`. Para desactivar una fuente sin borrarla, cambia su línea:

```yaml
    activo: false
```

Para añadir un medio nuevo, copia este bloque al final de `fuentes:` y cambia las
dos primeras líneas:

```yaml
  - name: "Nombre del medio"
    adaptador: gnews
    query: "site:dominiodelmedio.com (UFC OR MMA) when:2d"
    hl: es-419
    gl: MX
    prioridad: 3
    activo: true
    max_items: 10
```

Luego sube el cambio:

```powershell
git add config.yaml
git commit -m "Añadir fuente X"
git push
```

El siguiente ciclo ya la usa. **No hace falta tocar código.**

### 10.3 · Cambiar de proveedor de IA

Si Gemini se queda sin cuota, en **Variables** de GitHub cambia:

| Variable | Nuevo valor |
|---|---|
| `LLM_PROVIDER` | `groq` |
| `LLM_MODEL` | `llama-3.3-70b-versatile` |

Y añade el *Secret* `GROQ_API_KEY` con una clave de
[console.groq.com](https://console.groq.com) (gratis).

### 10.4 · Cambiar la frecuencia

Edita `.github/workflows/run.yml`, línea del `cron`:

```yaml
    - cron: "*/20 * * * *"     # cada 20 minutos (por defecto)
    - cron: "*/30 * * * *"     # cada 30 minutos (más barato)
    - cron: "0 * * * *"        # cada hora
```

---

## 11. Problemas frecuentes

### No me llega nada a Telegram

| Comprobación | Comando / acción |
|---|---|
| ¿El bot funciona? | `python doctor.py --enviar` |
| ¿Le hablaste al bot? | Un bot no puede escribirte hasta que tú le escribas |
| ¿El umbral es muy alto? | Baja `RELEVANCE_THRESHOLD` a 6 temporalmente |
| ¿Hay noticias nuevas? | `python main.py --dry-run` — si dice 0 candidatos, es que no hay novedades |
| ¿Falla el ciclo en GitHub? | Pestaña *Actions* → ¿hay ❌ rojos? |

### Me llegan noticias repetidas

Casi siempre es que **falta el permiso de escritura** (paso 8.6): sin él, GitHub no
guarda la memoria y cada ciclo empieza de cero. Compruébalo en el registro de
Actions: el paso *Persistir estado* debe hacer un `commit`, no un warning.

Si el permiso está bien y aun así se cuelan parecidas, baja `umbral_similitud` de
`88` a `84` en `config.yaml`.

### El ciclo falla en GitHub con ❌

Abre la ejecución fallida y busca la línea roja:

| Mensaje | Solución |
|---|---|
| `falta TELEGRAM_BOT_TOKEN` | El *Secret* no está creado o está mal escrito (respeta mayúsculas) |
| `Gemini HTTP 404 … no longer available to new users` | El modelo está retirado. Usa la cadena de la sección 4.2 |
| `Gemini HTTP 429` en **todos** los modelos de la cadena | Cuota diaria agotada. Espera 24 h o cambia a Groq (10.3) |
| `Gemini HTTP 400` | La clave es inválida. Regenérala en aistudio.google.com |
| `respuesta cortada por maxOutputTokens` | Sube la Variable `LLM_MAX_TOKENS` a `6000`. Los modelos que razonan gastan del mismo presupuesto que la respuesta |
| `Reddit RSS no responde` / `403` / `429` | Reddit bloquea IPs de datacenter a ratos. Es esperable y el ciclo continúa. Si es permanente, pon `activo: false` a r/MMA y r/ufc |
| `Permission denied` en *Persistir estado* | Falta el permiso del paso 8.6 |

### `python` no se reconoce

Python no está en el PATH. Reinstálalo desde python.org marcando
**"Add Python to PATH"**, o usa `py` en vez de `python`.

### `pip install` falla

Actualiza pip primero:

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Un medio devuelve 0 items

Es lo normal con los RSS marcados `[verificar RSS]` — sus direcciones no estaban
confirmadas. Ejecuta `python doctor.py --fuentes` para ver cuáles fallan, y en
`config.yaml` ponles `activo: false`. Su contenido lo sigue capturando la entrada
equivalente de Google News.

### Los tests fallan con `collections.Callable`

Es un problema de tu Python, no del proyecto (un `pyreadline` antiguo). Usa:

```powershell
python -m pytest tests -q -p no:capture
```

---

## 12. Mantenimiento

### Rutina mensual (5 minutos)

```powershell
cd C:\Users\Usuario\Desktop\DEMOCLES
.venv\Scripts\Activate.ps1
python doctor.py --fuentes
```

Y revisa:

1. ¿Alguna fuente da 0 items varias veces? → desactívala en `config.yaml`.
2. En GitHub → *Actions*, ¿hay ❌ rojos repetidos? → mira el registro.
3. ¿Estás recibiendo demasiado o demasiado poco? → ajusta el umbral (10.1).

### Vigila el tamaño del histórico

`state/state.json` se limpia solo cada 14 días. Si en GitHub ves que pesa más de
1 MB, baja `dias_historico` a `7` en `config.yaml`.

### Qué se rompe con el tiempo, por orden de probabilidad

1. **Los RSS de los medios** — cambian de dirección cada varios meses. Google News
   lo cubre mientras tanto.
2. **Los límites gratuitos de la IA** — Google los cambia sin avisar. Plan B: Groq.
3. **Twitter/X** — si algún día lo activas, se romperá. Es esperable.
4. **Reddit por RSS** — puede bloquear las IPs de GitHub Actions. Si te falla a
   diario, la solución de fondo es pedirles acceso a la API (sección 4.3).

---

## 13. Pausar o desinstalar

**Pausar sin borrar nada:**

En GitHub → **Actions** → barra lateral → **DEMOCLES...** → menú **⋯** (arriba a
la derecha) → **Disable workflow**. Se reactiva desde el mismo sitio.

**Dejar de recibir sin apagar el sistema:**

Sube `RELEVANCE_THRESHOLD` a `10` en *Variables*. Sólo te llegarán bombazos.

**Desinstalar del todo:**

1. GitHub → *Settings* → abajo del todo → **Delete this repository**
2. Telegram → `@BotFather` → `/deletebot`
3. Borra la carpeta `C:\Users\Usuario\Desktop\DEMOCLES`
4. Revoca la clave en aistudio.google.com y la app en reddit.com/prefs/apps

---

## Referencia rápida de comandos

```powershell
cd C:\Users\Usuario\Desktop\DEMOCLES
.venv\Scripts\Activate.ps1          # activar el entorno (cada vez que abras PowerShell)

python doctor.py                     # ¿está todo bien configurado?
python doctor.py --enviar            # + mensaje de prueba a Telegram
python doctor.py --fuentes           # + probar la descarga de cada fuente

python main.py --dry-run             # ensayo sin gastar nada
python main.py --no-send --limit 3   # ver 3 briefings en pantalla
python main.py --limit 5             # ciclo real, máximo 5 noticias
python main.py                       # ciclo completo

python -m pytest tests -q -p no:capture   # ejecutar los 29 tests

git add . ; git commit -m "cambios" ; git push    # subir cambios a GitHub
```
