# Demo Recorder

Grabación de GIFs de demostración para el README del repo (`docs/media/demo-*.gif`).
Stack: **Puppeteer + ghost-cursor + puppeteer-screen-recorder** (Node, sin build
step), conversión con **ffmpeg + gifsicle** (ffmpeg empaquetado en
`@ffmpeg-installer`; `gifsicle` vive en `tools/gifsicle/`).

## Requisitos

- Node >= 20 (probado con v21.7.1). `npm install` baja Puppeteer + Chrome for
  Testing (nada a nivel sistema).
- App corriendo en `http://127.0.0.1:8000` (`uvicorn app:app`) con datos de
  demo (ver abajo).

## Uso

```bash
npm install
node record-imports.mjs       # videos/imports.mp4 + timeline
node record-apply.mjs         # videos/apply.mp4
node record-variant-gen.mjs   # videos/variant-gen.mp4
node record-achievements.mjs  # videos/achievements.mp4
node record-hero.mjs          # videos/hero.mp4
node record-history.mjs       # videos/history.mp4
node convert.mjs imports      # -> docs/media/demo-imports.gif (+ frames en work/)
node convert.mjs apply
node convert.mjs variant-gen
node convert.mjs achievements
node convert.mjs hero
node convert.mjs history
```

Cada grabación deja `videos/<nombre>.mp4` + `videos/<nombre>.timeline.json`
(marcas de tiempo para el recorte de esperas). `convert.mjs` recorta las
ventanas muertas (progreso del LLM/render) usando las marcas del timeline
(`gen_click`→`gen_result`, `render_click`→`render_done`), aplica 2 pasadas de
paleta (10 fps, 820px el hero / 760px el resto) y optimiza con `gifsicle -O3`.
Si supera 5MB reintenta a 8 fps.

## Orden de grabación (dependencias de datos)

1. `record-imports.mjs` — importa los CVs demo y deja **1 logro confirmado en
   el master** (el cluster de "cacheo distribuido con Redis", que es el que
   usan los demos siguientes). Resetea el master con
   `Copy-Item data\master_cv_example.yaml data\master_cv.yaml -Force` y borra
   `data/import_sessions/*.json` antes de grabar (sesiones viejas se suman a la
   bandeja).
2. `record-apply.mjs` — target con el JD backend (`data/job_description_example.txt`).
3. `record-variant-gen.mjs` — usa `work/jd_variantgen.txt` (JD temático de
   Redis): el logro importado del paso 1 gana un slot del target y por eso
   existe el botón ✏. **No re-grabar imports con otros CVs**: los temas de
   `work/cvs/cv1-3.txt` no deben duplicar los highlights del master de ejemplo
   (si el logro importado es casi un duplicado semántico, la selección MMR lo
   descarta y no hay botón ✏).
4. `record-achievements.mjs` — enriquece un bullet legacy del master (en
   memoria, no toca el master en disco salvo el guardado final).
5. `record-hero.mjs` — JD frontend (`work/jd_frontend.txt`), renderiza PDF.
6. `record-history.mjs` — necesita las corridas de apply/variant-gen/hero en
   `data/run_history.json` (limpiar corridas de debug antes de grabar).

## Qué hace cada demo

- `imports`: subir 3 CVs (texto), agrupar por embeddings, bandeja de clusters
  con el diff resaltado, "Es el mismo logro" → el LLM genera el logro candidato
  (redacciones del grupo como variantes) → confirmar → el logro llega al master.
- `apply`: pegar oferta backend, generar (LLM real, se recorta el tiempo
  muerto), keyword report, scores por bullet con tooltip del JD, pullback
  ("Agregar este bullet"), renderizar PDF.
- `variant-gen`: botón ✏ (aparece siempre en bullets con logro) → modal de
  comparación lado a lado con términos no verificables resaltados → "Usar y
  guardar como variante nueva" → popover ⇄ con la variante nueva.
- `achievements`: editor de logros — hechos vs variantes, ángulos, "usada en N
  CVs", enriquecer un bullet legacy, editar redacción (aparecen
  Previsualizar/Guardar/Descartar) y guardar el master.
- `hero`: flujo panorámico del README — pegar oferta frontend, generar, revisar
  y descargar PDF.
- `history`: variantes más usadas, keywords faltantes, búsqueda por oferta,
  estado de aplicación, chips de filtro, comparar 2 corridas y detalle
  "Análisis".

## Datos de demo (privacidad)

Antes de grabar hay que swap de datos (en `data/`):

- `master_cv.yaml` <- `master_cv_example.yaml` (Juan Pérez)
- `run_history.json` <- respaldo con 3 corridas ficticias (apply backend,
  variant-gen backend, hero frontend)
- `import_sessions/` <- vacío
- `config.json` <- el del usuario real (gitignored; no tocar el proveedor LLM)

Los archivos reales se respaldan en `data/.bak/` y se restauran al terminar.
Las grabaciones mutan: `imports` (master + sesiones), `apply`/`variant-gen`/
`hero` (corridas en `data/run_history.json`, `data/run_cvs/` y `output/`),
`achievements` (master al guardar). Restaurar desde `data/.bak/` al terminar y
borrar artefactos demo (`output/Juan_Pérez_*`, `target_cv.yaml`,
`data/import_sessions/*.json`).

## Gotchas

- **Puppeteer v24**: los uploads van con `elementHandle.uploadFile(...)` (ya no
  existe `page.setInputFiles`/`page.uploadFile`).
- **Selects nativos**: no se escriben con teclado; usar `page.select(sel, value)`
  (el evento `change` real dispara los listeners del frontend).
- El cursor visible es un **overlay SVG de flecha** inyectado en la página (el
  screencast de CDP no captura el cursor nativo); el movimiento es 100%
  ghost-cursor (`visible: false` + overlay propio).
- Clicks por texto: `clickText` usa locators `::-p-text` de Puppeteer; para
  apuntar a un elemento específico (ej. un cluster en particular) se marca con
  un atributo temporal `data-*` y se usa como scope del selector.
- El free tier de OpenRouter tarda 35–130s en generar: los waits son por
  `waitForSelector` del resultado real (sin timeouts fijos) y el recorte se
  hace en post con `select` de ffmpeg.
- Al editar `run_history.json` (limpiar corridas) usar Python o Node, no
  `Set-Content` de PowerShell: el BOM de UTF-8 rompe el `json.load` del backend
  y la app mueve el archivo a `.bak` y arranca con historial vacío.