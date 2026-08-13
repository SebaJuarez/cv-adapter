# cv-adapter — De "CV recortado" a "Base de logros con variantes"
### Documento funcional end-to-end

> Fuente única de verdad del cambio grande de logros con variantes (F1–F7).
> Este archivo es el que el agente debe mantener actualizado a medida que
> las fases avanzan; el estado de avance vive en AGENTS.md.

---

## 0. Objetivo y alcance

Este documento describe el cambio de paradigma central: pasar de un
`master_cv.yaml` donde cada bullet es un string atómico e inmutable, a un
modelo donde cada logro (**achievement**) separa **hechos verificables**
(inmutables) de **variantes de redacción** (múltiples, según a quién le
hablás). Es la base que permite:

- Terminar con los "30 CVs sueltos" donde el mismo logro está reescrito
  a mano N veces.
- Arrancar de cero sin sentir que hay que llenar una planilla vacía y
  hostil.
- Reusar redacciones ya escritas y aprobadas en vez de generar de cero
  cada vez.
- Generar una redacción nueva con IA solo cuando hace falta, bajo
  aprobación explícita, sin romper la garantía de "nunca se inventa un
  hecho" que ya tiene el proyecto.

Cubre: modelo de datos, migración, los cuatro ciclos de vida completos
de un usuario (cero CVs / muchos CVs / aplicar a una oferta / mantener
el master vivo), la máquina de estados de una variante, guía de
interfaz para cada pantalla, arquitectura técnica afectada, plan de
fases y riesgos.

No cubre: implementación línea por línea (eso es el paso siguiente,
como spec técnica separada por feature, en el estilo del roadmap
anterior).

---

## 1. El cambio de paradigma, en una frase

Hoy `merge.py` copia texto **literal** desde `master_cv.yaml` — la
unidad de verdad es el string del bullet. El cambio propone que la
unidad de verdad pase a ser el **hecho** (qué hiciste, con qué
herramientas, con qué resultados medibles), y que el string de bullet
sea una de varias **proyecciones posibles** de ese hecho, cada una
optimizada para un ángulo distinto (liderazgo, profundidad técnica,
impacto en costos, velocidad de entrega, etc.).

La garantía anti-alucinación no cambia de naturaleza, solo de nivel:
en vez de verificar que el LLM no invente algo fuera de "bullet + JD"
(como hoy hace `_verify_match_reason` en `src/llm_node.py`), se
verifica que ninguna variante invente algo fuera de "hechos del
achievement" — mismo principio, aplicado un escalón más abajo en la
jerarquía de datos.

---

## 2. Modelo de datos objetivo

### 2.1 Achievement

```yaml
achievements:
  - id: "ach_a1b2c3"                # estable, no cambia aunque se edite el texto
    entry_ref: {section: "experience", entry_id: "exp_empresa_a"}
    facts:
      action: "Diseñé y desplegué un sistema de facturación"
      tools: ["Java", "Spring Boot", "PostgreSQL", "Docker"]
      scope: "equipo de 4 personas, +50 clientes B2B"
      outcomes:                     # lista, NO un solo número — un logro
        - metric: "tiempo de respuesta de reportes"
          value: "-60%"
        - metric: "incidentes en producción"
          value: "-30%"
      timeframe: {start: "2021-01", end: "2022-06"}
    variants:
      - id: "var_001"
        text: "Diseñé y desplegué un sistema de facturación en Java/Spring Boot, reduciendo el tiempo de respuesta de reportes en 60%."
        angle: "impacto_tecnico"
        source: "manual"            # manual | imported | generated
        status: "approved"          # pending | approved | deprecated
        used_count: 7
        created_at: "2024-01-10"
      - id: "var_002"
        text: "Lideré el diseño de un sistema de facturación con un equipo de 4 personas, reduciendo incidentes en producción un 30%."
        angle: "liderazgo"
        source: "imported"
        status: "approved"
        used_count: 3
        created_at: "2024-03-02"
```

### 2.2 Taxonomía de ángulos (`angle`)

Set chico y fijo para que sea comparable/matcheable contra el JD, no
texto libre:

```
liderazgo | ownership | escala | reduccion_costo | velocidad_entrega
impacto_tecnico | calidad_testing | cross_funcional | vision_producto
```

Una variante puede tener 1-2 ángulos (no más, para que la elección
siga siendo clara). El JD se puntúa contra esta misma taxonomía
(extensión de `extract_keywords`/heurísticas ya existentes, pero sobre
vocabulario de "énfasis" en vez de vocabulario técnico).

### 2.3 Compatibilidad con el esquema actual

Un `highlight: str` de hoy es simplemente un achievement con:

```yaml
facts: {action: null, tools: [], scope: null, outcomes: [], timeframe: null}
variants:
  - {id: "var_legacy_1", text: "<el string original>", angle: null,
     source: "manual", status: "approved", used_count: 0}
```

Es decir: **todo master_cv.yaml existente sigue siendo 100% válido sin
tocar nada**. La extracción de `facts` estructurados a partir de ese
texto legacy es un enriquecimiento *opcional y posterior*, nunca un
requisito para seguir usando la app. Esto es clave para que la
migración no sea un evento de "todo o nada".

---

## 3. Migración

1. **Fase de convivencia**: `merge.py`/`selection.py` aceptan tanto
   `highlights: [str]` (formato viejo) como `achievements: [...]`
   (formato nuevo) en la misma entrada. Un adaptador interno normaliza
   ambos a la misma estructura en memoria antes de indexar — el resto
   del pipeline de IR no necesita saber cuál era el formato original.
2. **Sin migración forzada**: el usuario puede quedarse en formato
   legacy indefinidamente. El nuevo modelo es un *upgrade incremental
   por bullet*, no una migración de todo el archivo de una vez.
3. **Botón "enriquecer este bullet"** en el editor del master: toma un
   highlight string existente y lo abre en el editor de Achievement
   (sección 6.4) con un intento automático de pre-llenar `facts`
   (extracción heurística/LLM asistida, siempre editable antes de
   guardar — nunca se auto-guarda sin que el usuario lo vea).

---

## 4. Ciclos de vida de usuario (end-to-end)

### 4.1 Cold start absoluto — sin ningún CV para cargar

Este es el caso que más fricción tiene hoy: una pantalla de formulario
vacía con conceptos como "achievement", "facts", "outcomes" es
intimidante si nunca escribiste un CV.

**Flujo:**

1. Al detectar que `master_cv.yaml` no existe (mismo chequeo que ya
   hace `api/routers/master_cv.py::get_master_cv` devolviendo
   `_empty_master()`), la app entra en **modo onboarding conversacional**
   en vez de mostrar directamente el formulario estructurado.
2. El onboarding NO pregunta "completá tus achievements". Pregunta en
   lenguaje natural, una cosa a la vez: *"Contame de un trabajo o
   proyecto reciente. ¿Qué hiciste?"* → el usuario escribe en texto
   libre, como le sale. *"¿Con qué herramientas o tecnologías?"* →
   *"¿Hubo algún resultado medible? (tiempo, plata, gente, lo que
   sea — no hace falta que sea perfecto)"*.
3. Esas respuestas en texto libre se estructuran automáticamente en un
   achievement candidato (facts + una primera variante), que se
   muestra para confirmar/editar — nunca se guarda sin que el usuario
   lo vea una vez.
4. Se repite el ciclo pregunta→confirmación tantas veces como el
   usuario quiera, con un contador visible tipo "3 logros cargados —
   con 4-5 ya podés generar tu primer CV". El objetivo es que en
   menos de 10 minutos tenga un master mínimo viable, no un CV
   completo.
5. En cualquier momento puede salir del modo conversacional y pasar al
   editor estructurado tradicional (para quien prefiere completar
   campos directamente).

**Por qué importa:** la barrera de entrada de un modelo de datos más
rico (facts + variants) es más alta que la de un string suelto. Si el
onboarding exige ese formalismo desde el primer momento, el usuario
sin CVs previos abandona antes de cargar nada. La conversación baja
esa barrera a "contame qué hiciste", que es la forma natural en que la
gente ya piensa su propia experiencia.

### 4.2 Cold start con CVs viejos para importar

1. Pantalla de importación: drag&drop de PDFs/DOCX/texto (múltiples a
   la vez — los 30 CVs).
2. Extracción de bullets crudos de cada archivo (reusa
   `pdf-reading`/parseo de docx del lado de herramientas de
   documentos).
3. **Clustering automático** vía similitud de embeddings densos (ya
   calibrados en el proyecto para Max-Sim) entre todos los bullets
   extraídos de todos los archivos: agrupa candidatos que
   probablemente son el mismo logro redactado distinto.
4. **Bandeja de revisión de clusters** (no automática — ver sección
   6.3): el usuario confirma cluster por cluster. Al confirmar un
   cluster como "es el mismo logro", el sistema:
   - Propone un `facts` consolidado (unión de outcomes mencionados en
     cualquiera de las redacciones del cluster).
   - Guarda cada redacción del cluster como una `variant` distinta con
     `source: imported`.
5. Bullets que no clusterizaron con nada (huérfanos, aparecen una sola
   vez en un solo CV) se muestran aparte como "logros sin duplicados"
   — igual se pueden aceptar como achievement de una sola variante.
6. Nada entra al master real hasta que el usuario pasa por esta
   bandeja — es exactamente el mismo principio de "el LLM propone,
   nunca decide" que ya rige el resto del proyecto, aplicado a la
   importación.

### 4.3 Ciclo recurrente: generar CV para una oferta nueva

Este es el flujo que ya existe hoy (`Nueva aplicación`) — se extiende,
no se reemplaza:

1. Pegar el JD (igual que hoy).
2. El motor de selección (`SelectionEngine`) elige qué **achievements**
   entran (mismo mecanismo de retrieval de siempre — BM25/denso/RRF
   corren sobre el texto de la variante `approved` con mayor
   `used_count` o la marcada como default, no cambia esa parte).
3. **Nuevo paso, antes de armar el target**: para cada achievement
   seleccionado, el sistema detecta el ángulo dominante del JD
   (sección 2.2) y busca si existe una variante `approved` con ese
   ángulo:
   - **Si existe** → se usa directamente, sin ninguna interacción
     nueva del usuario (el caso más común una vez que el banco de
     variantes tiene un poco de historia — cero fricción extra).
   - **Si no existe** → el bullet se marca visualmente como
     "redacción genérica, no hay versión para este ángulo" y se
     ofrece un botón inline "Generar versión para [liderazgo]" (ver
     6.6) — pero el CV se puede generar y descargar igual sin tocar
     ese botón, nunca es bloqueante.
4. El resto del flujo (keyword report, pullback, edición manual,
   generar PDF) sigue exactamente igual a hoy.
5. Al aprobar/usar una variante en una corrida, se incrementa su
   `used_count` y se guarda `variant_id` en el registro de historial
   (no solo el índice del achievement como hoy) — esto es lo que
   habilita el loop de la sección 4.4/6.7.

### 4.4 Mantenimiento continuo del master

El momento en que la gente recuerda un logro no suele coincidir con
"estoy armando un CV" — suele ser "acabo de terminar algo bueno en el
trabajo". Un botón flotante persistente **"+ Anotar un logro"**,
accesible desde cualquier vista, abre el mismo mini-flujo
conversacional del onboarding (4.1) pero de un solo achievement, sin
fricción de navegar a la vista de CV maestro. El objetivo es capturar
el logro *en caliente*, cuando el detalle está fresco, no seis meses
después cuando ya se te olvidó la métrica exacta.

---

## 5. Estados y transiciones de una variante

```
                 ┌───────────┐
   generada/     │  pending  │  ← nunca se usa en un target real
   importada  →  └─────┬─────┘
                       │ usuario aprueba
                       ▼
                 ┌───────────┐
                 │ approved  │  ← disponible para selección automática
                 └─────┬─────┘
                       │ usuario la reemplaza o la marca obsoleta
                       ▼
                 ┌────────────┐
                 │ deprecated │  ← no se ofrece más, pero queda en
                 └────────────┘     el historial de corridas viejas
```

Reglas:
- Ninguna variante `pending` puede aparecer en un `target_cv` generado
  — el guardarail de "solo texto verificado se muestra" aplica acá
  igual que aplica hoy a `keywords_detected`/`match_reason`.
- `deprecated` no se borra (preserva la trazabilidad del historial:
  corridas viejas que usaron esa variante siguen siendo legibles), solo
  deja de ofrecerse en nuevas selecciones.
- Una variante `imported` sin revisar cuenta como `pending` — pasar por
  la bandeja de clusters (4.2) es lo que la promueve a `approved`.

---

## 6. Guía de interfaz — cómo minimizar el sufrimiento del usuario

### 6.1 Principios de diseño

1. **Nunca bloquear el camino feliz.** Cualquier feature nueva (generar
   variante, revisar cluster, enriquecer facts) debe ser accesible
   pero salteable — el usuario siempre puede generar y descargar un CV
   con lo que ya tiene, aunque esté "incompleto" según el nuevo modelo.
2. **Progresividad, no formalismo de entrada.** Nadie arranca
   escribiendo `facts.outcomes[].metric`. Se arranca con lenguaje
   natural y el sistema estructura — el formulario rígido es el
   destino, no el punto de partida.
3. **Revisión rápida > formulario largo.** Todo dato que el sistema
   propone (variante generada, cluster de importación, facts
   extraídos) se revisa con un gesto binario simple
   (aceptar/rechazar/editar) — no con un formulario completo cada vez.
4. **La fricción de "aprobar una variante nueva" se paga una sola
   vez.** Después de aprobada, queda disponible para siempre — el
   costo (de tiempo o de tokens de API) es amortizado, no recurrente
   por oferta.
5. **Transparencia sobre qué se usó y por qué**, siempre visible sin
   tener que buscarla (ya es una fortaleza del proyecto hoy con el
   tooltip de JD snippet — extenderla, no perderla).

### 6.2 Onboarding conversacional (cold start sin CVs)

- Reemplaza el editor de secciones vacío como primera pantalla cuando
  no hay `master_cv.yaml`.
- Chat de una sola pregunta a la vez, con opción de "no sé / paso esta
  pregunta" siempre visible — nunca forzar una respuesta.
- Barra de progreso simple: "Logros cargados: 3 · Podés generar tu
  primer CV con 4+".
- Cada achievement candidato se muestra como una tarjeta chica
  editable ANTES de confirmarse — igual patrón visual que ya usan las
  `entry-card` del editor actual, para no introducir un componente
  visual nuevo.
- CTA de salida en cualquier momento: "Terminar por ahora e ir al
  editor completo" — el onboarding no es una jaula.

### 6.3 Bandeja de revisión de clusters (importación de CVs viejos)

- Vista tipo "swipe/aceptar" — un cluster a la vez, con las N
  redacciones candidatas listadas verticalmente y resaltando en negrita
  las palabras/números que difieren entre ellas (para que sea obvio de
  un vistazo si son el mismo logro o dos cosas distintas).
- Tres acciones por cluster: **"Es el mismo logro"** (arma el
  achievement con todas las variantes), **"Son logros distintos"**
  (los separa, cada uno como achievement propio de una variante),
  **"Descartar"** (ninguno entra al master).
- Contador de progreso ("14 de 38 grupos revisados") y posibilidad de
  guardar a medias y volver después — importar 30 CVs no se hace de
  una sentada.
- Los huérfanos (sin cluster) van al final, agrupados, con acción
  masiva "aceptar todos como están" para no obligar a revisar uno por
  uno si el usuario ya está cansado a esa altura.

### 6.4 Editor de Achievement (reemplaza/extiende el editor de highlights)

- Vista de dos columnas dentro de la tarjeta de la entrada:
  - **Izquierda: Hechos** (campos estructurados — acción, herramientas
    como chips editables tipo el tag-input que ya existe para redes
    sociales en `renderHeader`, outcomes como lista de pares
    métrica/valor con botón "+ agregar resultado").
  - **Derecha: Variantes** — lista de tarjetas chicas, cada una con su
    chip de `angle` (select de la taxonomía fija), el texto, y
    `used_count` como badge pequeño ("usada en 7 CVs") para que el
    usuario vea de un vistazo cuáles redacciones le vienen sirviendo.
- Botón "+ Nueva variante" abre un textarea simple — no exige volver a
  tocar los hechos.
- Si el usuario edita un `fact` después de tener variantes ya
  aprobadas, mostrar un aviso no bloqueante: "Este cambio no actualiza
  las redacciones existentes — revisalas si hace falta" (evita que el
  sistema reescriba texto aprobado sin que el usuario lo pida).

### 6.5 Selector de variante durante "Nueva aplicación"

- Dentro de cada bullet del CV generado (misma tarjeta de
  `entry-card`/`highlight-row` de hoy), si el achievement tiene al menos
  una variante `approved`, agregar un ícono chico de "cambiar
  redacción" junto al bullet (no un dropdown gigante — algo discreto,
  en la línea del ícono de mover arriba/abajo que ya existe).
- Al hacer clic, popover corto con las variantes disponibles como
  opciones de un clic (mostrando su `angle` como etiqueta), no un modal
  pesado — el usuario está en medio de revisar el CV, la interacción
  tiene que ser instantánea. (Decisión 2026-08-12: el ícono existe desde
  UNA variante approved — el popover incluye "Generar otra redacción…",
  así ningún bullet queda sin vía de generar redacciones desde el target.)
- El match automático (paso 3 de la sección 4.3) ya eligió la mejor
  por default — este selector es solo para el caso "quiero override
  manual", no el camino principal.

### 6.6 Generación asistida inline (variante nueva bajo aprobación)

- Cuando no hay variante para el ángulo detectado (sección 4.3), el
  botón "Generar versión para [ángulo]" aparece integrado en la misma
  tarjeta del bullet — no navega a otra pantalla.
- **Decisión de API key (2026-08-12):** la generación funciona con el
  proveedor activo — Ollama local o API remota — sin exigir API key ni
  redirigir a Configuración por "falta de key". Si el proveedor activo
  falla (Ollama caído, key inválida, timeout), el toast muestra el error
  con un enlace a Configuración para cambiarlo — nunca un error genérico
  a mitad del flujo.
- El botón aparece SIEMPRE en los bullets del target con logro
  (decisión revisada 2026-08-12 tras QA de corrida real): si la
  selección tiene ángulo preferido para ese slot (`preferred_angles` de
  la fase estratégica — el ángulo que mejor matchea el bullet con la
  oferta) la generación se orienta a ese ángulo; si no lo tiene, se
  genera una versión **genérica** (variante sin ángulo, `angle: ""`) —
  nunca se inventa un ángulo que el match no respalda. El tooltip del
  botón explica esta regla y el ángulo elegido.
- Además, el selector de variantes (6.5) ofrece "Generar otra
  redacción…" con los 9 ángulos a elección, aun cuando el logro ya tenga
  variantes aprobadas.
- Al generar, se muestra el resultado **al lado** de la redacción
  actual (comparación lado a lado, no reemplazo silencioso), con
  cualquier término técnico resaltado si NO está verificado contra los
  `facts` — mismo espíritu visual que ya usan los chips de colores del
  keyword report, aplicado acá.
- Tres acciones: **Usar y guardar como variante nueva** (pasa a
  `approved`, queda para siempre), **Usar solo esta vez** (se usa en
  este target pero queda `pending`, no contamina el banco de variantes
  con algo no revisado del todo), **Descartar**.

### 6.7 Historial: cerrar el loop de qué variante funciona

- En el detalle de una corrida (`openDetailModal`, tab de Análisis),
  agregar qué `variant_id` se usó en cada bullet.
- En la vista de Historial, agregar una sección liviana "Tus variantes
  más usadas" — no hace falta un dashboard de analytics complejo, con
  una lista simple de achievement → variante → cuántas corridas →
  cuántas de esas llegaron a "entrevista" o más (ya existe
  `application.status` por corrida) alcanza para dar la primera señal
  real de qué redacción viene funcionando mejor.

**Implementación (2026-08-13):** la traza se arma en `merge.py` — la
metadata interna por bullet (`_src_variant_map`) suma `angle` y `text`
emitidos, y `extract_bullet_variants(target_cv)` la reconstruye en el
orden efectivo del target. `add_run` la persiste como `bullet_variants`
(solo cuando hay logros con variantes: los runs legacy no ganan la
clave), con el texto guardado para que el historial siga siendo legible
aunque la variante después se marque `deprecated` o se borre del master.
`aggregate_variant_stats` agrupa por variante (clave `ach_id` +
`variant_id`): corridas distintas, cuántas llegaron a
`entrevista`/`oferta` (`SUCCESS_STATUSES`) y última vez usada. UI:
sección "Tus variantes más usadas" en Historial (endpoint
`GET /api/history/stats/variants`) y bloque "Variantes usadas en esta
corrida" en el tab de Análisis del detalle (texto + ángulo + ID).

---

## 7. Arquitectura técnica afectada (resumen, no exhaustivo)

- `src/merge.py` — `_apply_entry_selection` debe resolver achievement→
  variante elegida antes de copiar texto al target (hoy copia
  `highlights` directo).
- `src/selection.py` — el retrieval indexa el texto de la variante
  "representativa" (mayor `used_count`/`approved` marcada default) de
  cada achievement, no un string plano suelto.
- `src/llm_node.py` — nueva función de generación de variante (mismo
  patrón defensivo que `_call_llm`/`_verify_match_reason`, pero
  verificando contra `facts` en vez de contra el bullet completo).
- `src/storage.py` / esquema YAML — soporte del nuevo bloque
  `achievements` conviviendo con `highlights` legacy.
- Nuevo módulo `src/onboarding.py` o similar — lógica del flujo
  conversacional (estructurar respuesta libre → achievement candidato).
- Nuevo módulo de clustering — reusa `DenseIndex`/embeddings ya
  existentes contra un corpus multi-archivo en vez de un master único.
- Frontend: nueva vista de onboarding, nueva vista de bandeja de
  clusters, extensión de `components.js` para el editor de Achievement,
  extensión de `widgets.js` para el selector de variante inline.

---

## 8. Plan de fases (rollout incremental)

1. **Esquema + compatibilidad** — soporte de `achievements` en el YAML
   y en `merge.py`/`selection.py`, sin ninguna UI nueva todavía (se
   sigue usando el editor actual, migración 100% invisible).
2. **Editor de Achievement** (6.4) — el usuario ya puede crear
   achievements con múltiples variantes a mano, sin generación IA ni
   importación todavía.
3. **Selector de variante en "Nueva aplicación"** (6.5) — cierre del
   ciclo manual completo antes de meter automatización.
4. **Onboarding conversacional** (6.2) — resuelve cold start sin CVs.
5. **Importación + bandeja de clusters** (6.3, 4.2) — resuelve cold
   start con muchos CVs (la feature más compleja, va después de que el
   resto del modelo ya esté probado).
6. **Generación asistida + aprobación inline** (6.6) — decidió el tema
   de API key: funciona con el proveedor activo (Ollama local incluido),
   sin exigir key; era la última fase que dependía de una decisión
   externa, por eso quedó para el final.
7. **Loop de feedback en historial** (6.7) — depende de que haya
   volumen real de uso de variantes para decir algo útil. ✅
   (2026-08-13: traza `bullet_variants` por corrida, "variantes más
   usadas" en Historial y `variant_id` por bullet en el detalle.)

Cada fase es usable de forma independiente — no hace falta llegar a la
fase 6 para que el proyecto ya haya resuelto el problema de los "30
CVs sueltos" (eso se resuelve en la fase 3).

---

## 9. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| El modelo de datos más rico ahuyenta a quien solo quiere algo simple | El formato legacy `highlights: [str]` sigue soportado indefinidamente; nada obliga a adoptar achievements. |
| Importación masiva mete basura al master (falsos duplicados agrupados, o hechos mal extraídos) | Bandeja de revisión obligatoria (4.2/6.3) — nada entra sin confirmación explícita, uno por uno o en bloque consciente. |
| Generación de variantes nuevas infla el uso de API sin que el usuario lo note | Aprobación explícita por variante + reuso indefinido una vez aprobada; nunca generación automática en background. |
| El onboarding conversacional se siente igual de tedioso que un formulario largo si tiene muchas preguntas | Límite bajo de preguntas por sesión, opción de salir en cualquier momento, umbral mínimo generoso (4-5 logros) para "ya podés generar tu primer CV". |
| Migración de esquema rompe tests/flujos existentes | Fase 1 (sección 8) es aditiva y invisible — toda la suite actual (`tests/test_merge.py`, `test_selection.py`, etc.) debe seguir pasando sin cambios antes de tocar ninguna UI. |

---

## 10. Métricas de éxito

- Tiempo desde "usuario nuevo sin CV" hasta "primer PDF generado"
  (objetivo: bajarlo respecto al baseline de completar el editor
  estructurado desde cero).
- % de achievements con más de una variante `approved` a los 3 meses
  de uso (mide si el banco de redacciones realmente crece con el uso,
  o si el usuario ignora la feature).
- % de corridas donde el match automático de ángulo encontró variante
  existente vs. requirió generar una nueva (debería subir con el
  tiempo — señal de que el banco de variantes está madurando y el
  costo marginal por oferta baja).
- Correlación entre `variant_id` usado y `application.status` en el
  historial (señal de largo plazo, recién útil con volumen).
