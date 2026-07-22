# cv-adapter — Adaptador de CV local ($0, 100% offline)

Pipeline LangGraph que adapta tu `master_cv.yaml` a una oferta laboral usando
un LLM local (Ollama), con una pausa humana obligatoria antes de compilar
el PDF con RenderCV.

## Por qué es seguro contra alucinaciones

El LLM **nunca redacta el YAML final**. Solo devuelve un JSON con **índices**
que apuntan a experiencia/skills/bullets que ya existen en `master_cv.yaml`
(ver `src/prompts.py`). El armado real del `target_cv.yaml` lo hace código
Python determinístico (`src/merge.py`), que copia texto literal del maestro.
Si el LLM devuelve un índice inválido, se ignora — nunca se inventa contenido
de reemplazo. A esto se suma la pausa humana antes de compilar el PDF.

## Presupuesto de una página (forzado por código, no por prompt)

Un modelo de 8B local no es confiable para "portarse bien" solo con
instrucciones — así que los límites de longitud se aplican con código en
`src/merge.py` (constantes `MAX_*` al principio del archivo), sin importar
cuánto contenido pida devolver el LLM:

- Máx. 2 experiencias laborales, máx. 3 proyectos.
- Máx. 4 bullets por experiencia/proyecto (los que el LLM haya marcado como
  más relevantes, según `highlight_order`).
- Máx. 6 categorías de skills.
- Educación: el título principal siempre se incluye; como máximo 1
  certificación adicional si aplica.

Si necesitás un presupuesto distinto (por ejemplo, CVs de dos páginas para
perfiles senior), ajustá esas constantes en `src/merge.py`.

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

1. Reemplazá `data/master_cv.yaml` con tu CV real (mantené el schema de
   RenderCV: `cv.sections.experience`, `cv.sections.skills`, etc.).
2. Pegá la oferta laboral en `data/job_description.txt`.
3. Corré:

```bash
python main.py --master data/master_cv.yaml --job data/job_description.txt
```

4. El script va a:
   - Llamar a Ollama local y generar `target_cv.yaml`.
   - **Pausar** y pedirte: `¿Deseás generar el PDF con RenderCV? (y/n)`
   - Revisá `target_cv.yaml` a mano en ese momento (fechas, empresas, puestos).
   - Si respondés `y`, compila el PDF final en `output/`.
   - Si respondés `n`, corta ahí sin generar nada.

## 3. Estructura del proyecto

```
cv-adapter/
├── README.md
├── requirements.txt
├── main.py                  # arma y corre el grafo LangGraph
├── data/
│   ├── master_cv.yaml       # tu CV completo (reemplazar por el real)
│   └── job_description.txt  # oferta laboral (reemplazar por la real)
├── src/
│   ├── state.py             # TypedDict del estado del grafo
│   ├── prompts.py           # system prompt + JSON Schema (Structured Outputs)
│   ├── llm_node.py          # llamada a Ollama
│   ├── merge.py             # fusión determinística master + selección LLM
│   └── render_node.py       # guardar YAML, pausa humana, render PDF
├── target_cv.yaml           # generado en cada corrida (revisar antes de aprobar)
└── output/                  # PDFs finales generados por RenderCV
```

## 4. Troubleshooting rápido

- **"Error llamando a Ollama"** → confirmá que `ollama serve` está corriendo
  y que el modelo (`OLLAMA_MODEL` en `src/llm_node.py`) fue descargado con
  `ollama pull`.
- **"El LLM no devolvió JSON válido"** → normalmente pasa con modelos muy
  chicos sin soporte real de structured outputs. Probá con `llama3.1:8b` o
  subí `num_ctx` si tu master_cv es muy largo.
- **"RenderCV falló al compilar el YAML"** → revisá `target_cv.yaml` a mano;
  el error de `stderr` de RenderCV suele apuntar directo a la línea rota.