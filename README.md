# cv-adapter — Adaptador de CV local ($0, 100% offline)

Pipeline que adapta tu `master_cv.yaml` a una oferta laboral usando un LLM
local (Ollama) o una API remota, con revisión humana antes de compilar el PDF
con RenderCV. Todo desde una interfaz web local — no hace falta tocar YAML a
mano ni usar la línea de comandos.

## Por qué es seguro contra alucinaciones

El LLM **nunca redacta el YAML final**. Solo devuelve un JSON con **índices**
que apuntan a experiencia/skills/bullets que ya existen en `master_cv.yaml`
(ver `src/prompts.py`). El armado real del `target_cv.yaml` lo hace código
Python determinístico (`src/merge.py`), que copia texto literal del maestro.
Si el LLM devuelve un índice inválido, se ignora — nunca se inventa contenido
de reemplazo. A esto se suma la revisión humana en la web antes de compilar
el PDF.

## Presupuesto de una página (forzado por código, no por prompt)

Un modelo de 8B local no es confiable para "portarse bien" solo con
instrucciones — así que los límites de longitud se aplican con código en
`src/merge.py`, leyendo valores desde `config.json` (editable desde la
pestaña **Configuración** de la web, o a mano), sin importar cuánto
contenido pida devolver el LLM:

- Máx. N experiencias laborales, máx. N proyectos.
- Máx. N bullets por experiencia/proyecto (los que el LLM haya marcado como
  más relevantes, según `highlight_order`).
- Máx. N categorías de skills.
- Educación: el título principal siempre se incluye; hasta N
  certificaciones adicionales si aplican.

## Optimización ATS

El LLM identifica palabras clave de la oferta (`job_description`) que
también existen literalmente en tu `master_cv.yaml`, y esas palabras se:

1. Priorizan al elegir qué bullets mostrar (los que matchean van primero).
2. Agregan como una línea "Palabras clave: ..." al principio del CV, para
   mejorar el parseo por sistemas ATS.

Cualquier keyword que el LLM "invente" (que no exista literalmente en tu
master_cv) se descarta automáticamente en `merge.py` — nunca se muestra una
palabra clave sin respaldo real en tu experiencia.

## 1. Instalación

```bash
# 1. Instalar Ollama (una sola vez): https://ollama.com/download
ollama pull llama3:8b        # o llama3.1:8b si preferís esa versión
ollama serve                 # dejalo corriendo en otra terminal

# 2. Entorno Python
python3 -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

> **¿Sin Ollama? Usá una API remota compatible con OpenAI** (OpenAI,
> OpenRouter, Groq, LM Studio…). No hace falta instalar nada local: configurá
> en la pestaña Configuración (o en `config.json`):
>
> ```json
> {
>   "llm_provider": "openai",
>   "openai_api_key": "sk-...",
>   "openai_model": "gpt-4o-mini",
>   "openai_base_url": ""
> }
> ```
>
> - `openai_base_url` es opcional: vacío usa el endpoint oficial de OpenAI;
>   para OpenRouter/Groq poné su URL base (`https://openrouter.ai/api/v1`,
>   `https://api.groq.com/openai/v1`).
> - La API key se guarda en `config.json` **en texto plano** (está
>   gitignored, pero no la compartas). Cualquier API compatible con OpenAI
>   sirve, siempre que devuelva JSON estructurado.
> - Si la llamada remota falla, el pipeline degrada con gracia y usa solo la
>   selección IR local (el CV igual se genera, sin razones de match).

> **Nota sobre Structured Outputs:** el nodo LLM usa el parámetro `format`
> del cliente `ollama` con un JSON Schema (no el modo básico `format="json"`).
> Esto requiere **Ollama >= 0.5**. Verificá con `ollama --version`; si tenés
> una versión vieja, actualizala o el nodo puede fallar/degradar la calidad
> del JSON.

> **Nota sobre RenderCV:** la versión probada es **RenderCV v2.8**, que usa
> Typst como motor de render (no necesitás instalar LaTeX aparte). Instalá
> con el extra `[full]` (`pip install "rendercv[full]"`) — si instalás solo
> `rendercv`, el propio CLI te va a pedir que reinstales así. La primera vez
> que renderiza, Typst descarga paquetes (fuentes, íconos) de
> `packages.typst.org`, así que necesitás conexión a internet **la primera
> vez** (después queda cacheado localmente; el resto del pipeline sigue
> siendo 100% local/offline).

## 2. Uso

```bash
uvicorn app:app --reload
```

Abrí `http://127.0.0.1:8000` en el navegador. Cuatro pestañas:

- **CV maestro** — editá tu CV completo con un formulario (no YAML a mano):
  agregar/sacar secciones enteras, entradas y bullets; reordenar con ↑/↓.
- **Nueva aplicación** — pegá la oferta, tocá "Generar CV para esta oferta".
  El resultado es editable: cada experiencia/proyecto muestra por qué se
  eligió, y tenés un desplegable "traer bullet del master" para recuperar
  contenido que el modelo dejó afuera pero vos querés incluir igual.
  "Generar PDF" compila y te deja descargarlo.
- **Historial** — cada corrida queda registrada automáticamente con su
  análisis ATS, el PDF asociado y el seguimiento de la aplicación
  (estado, fecha, notas, link a la oferta). Además agrupa las keywords que
  las ofertas piden y no están en tu CV maestro, para ver cuáles se repiten
  en general y decidir agregarlas manualmente (nunca se toca el master solo).
  El historial vive en `data/run_history.json` (gitignored).
- **Configuración** — los límites de una página, el proveedor del LLM
  (Ollama local o API remota) y su modelo, ya no hardcodeados: se guardan en
  `config.json`.

## 3. Estructura del proyecto

```
cv-adapter/
├── README.md
├── requirements.txt
├── config.json               # límites configurables (se crea al guardar desde la web)
├── app.py                    # entry point de uvicorn (re-exporta api.main:app)
├── api/                      # backend web (FastAPI)
│   ├── main.py               # arma la app (routers + mount del frontend)
│   ├── schemas.py            # modelos pydantic de request/response
│   ├── deps.py               # rutas del filesystem compartidas
│   └── routers/              # un router por recurso (master_cv, config, generate, render, history, system)
├── frontend/
│   ├── index.html
│   ├── style.css
│   ├── package.json          # declara ESM ("type": "module"), sin build step
│   └── js/                   # ES modules nativos (sin bundler)
│       ├── main.js           # bootstrap: tabs, init
│       ├── dom.js / api.js / state.js / labels.js / notify.js / modals.js
│       ├── widgets.js        # keyword report, oportunidades, excluidos
│       ├── components.js     # renderers compartidos master/target (ctx)
│       └── views/            # master.js, apply.js, history.js, settings.js
├── data/
│   ├── master_cv.yaml        # tu CV completo (reemplazar por el real)
│   ├── job_description_example.txt   # ejemplo de oferta laboral
│   └── run_history.json      # historial de corridas y seguimiento (se crea solo)
├── src/
│   ├── config.py             # carga/guarda config.json
│   ├── storage.py            # persistencia YAML (master/target)
│   ├── prompts.py            # system prompt + JSON Schema, dinámicos según config
│   ├── llm_node.py           # llamada al LLM: Ollama local o API remota (función pelada)
│   ├── merge.py              # fusión determinística + presupuesto de una página
│   ├── history.py            # historial de corridas + agregación de keywords faltantes
│   ├── render_node.py        # guardar YAML + render PDF (funciones peladas)
│   └── services/
│       └── generation.py     # orquestación del pipeline (web)
├── target_cv.yaml            # generado en cada corrida (revisar antes de aprobar)
└── output/                   # PDFs finales generados por RenderCV
```

## 4. Troubleshooting rápido

- **"Error llamando a Ollama"** → confirmá que `ollama serve` está corriendo
  y que el modelo (pestaña Configuración, o `ollama_model` en `config.json`)
  fue descargado con `ollama pull`.
- **"No hay API key configurada"** → tenés `llm_provider: "openai"` pero la
  `openai_api_key` está vacía. Completala en Configuración, o volvé a
  `llm_provider: "ollama"`.
- **Error de la API remota (401/403/404)** → verificá la key, el modelo y la
  `openai_base_url` (para OpenRouter/Groq, esa URL es obligatoria).
- **"El LLM no devolvió JSON válido"** → normalmente pasa con modelos muy
  chicos sin soporte real de structured outputs. Probá con `llama3.1:8b`.
- **"RenderCV falló al compilar el YAML"** → revisá `target_cv.yaml` a mano;
  el error de `stderr` de RenderCV suele apuntar directo a la línea rota. La
  causa más común es un bullet sin comillas con ": " en el medio del texto.