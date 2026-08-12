# QA F6 — Hallazgos (12-ago-2026, corrida real con OpenRouter nemotron)

**CERRADO**: QA completo aprobado por el usuario. Estado final restaurado (rollback
completo: master original + config Gemini, backups eliminados).

Contexto: QA end-to-end de la generación asistida inline (F6) con el master real del
usuario + JD Softtek "Desarrollador JAVA Trainee". Proveedor: OpenRouter (nemotron).
master_cv.yaml temporal con variante var_qa_f6 en ach_447d6d905eb4.

## Resultado del QA manual (confirmado por el usuario)

- [x] Modal F6: muestra el lado a lado y genera redacciones coherentes ("anda
      perfecto" tras el fix de timeout).
- [x] "Usar y guardar" / "Usar solo esta vez": funcionan.
- [x] Popover F3 (⇄): lista variantes y aplica la redacción elegida.
- [x] PDF final: renderiza correctamente.
- [x] Botón ✏ solo en bullets con ángulo preferido sin variante de ese ángulo
      (regla verificada en corrida real; explicada al usuario).

## Verificado OK

- Botón ✏ aparece cuando el bullet del target tiene ángulo preferido sin variante
  aprobada de ese ángulo (bullet 1 = ach_447d6d905eb4, ángulo "Calidad y testing" —
  el LLM de esta corrida eligió ese, no "velocidad_entrega" como la corrida API previa;
  la fase estratégica produce preferred_angles per-bullet consistentes).
- Botones ⇄/✏ solo en bullets con variantes/ángulo; bullets sin variantes (2º, 3º del
  target) no los muestran.
- Clic en ✏ abre el modal F6 y el ✏ queda `disabled` durante la generación,
  re-habilitándose al terminar (~25s con OpenRouter) → la llamada al backend
  `/api/variants/generate` se dispara y completa sin colgarse.
- Generación completa: 44/45 líneas, ATS 21/40 keywords, faltantes críticas listadas,
  botones "traer del master" por keyword faltante.

## Fallas / no convincente (para la próxima iteración)

1. **Popover F3 y modal F6 invisibles para el árbol de accesibilidad (Browser MCP)**:
   su contenido (variantes, botones del modal) no se serializa en el snapshot — solo
   aparece un `document` vacío al final del DOM. Imposible operarlos/verificarlos con
   el MCP. Sospecha: portales renderizados con `aria-hidden`/rol no expuesto → revisar
   roles ARIA del popover y el modal (también afecta a lectores de pantalla si el
   contenido no está expuesto).
2. **timeouts intermitentes del Browser MCP**: `click` y `type` a veces cuelgan
   30s+ (WebSocket response timeout). Reintentar el click suele funcionar; `type`
   quedó inutilizable. `Ctrl+V` por teclado no insertó texto en el textbox de la
   oferta (o el foco no estaba ahí — no verificable sin imagen).
3. **MCP no soporta verificación visual**: el modelo no lee screenshots → el foco del
   teclado es ciego; los pasos por Tab requieren conteos frágiles.
4. **Pendiente de corrida anterior, aún vigente**: si la fase estratégica no produce
   `preferred_angles` (p.ej. Ollama 8B), el botón ✏ queda oculto — comportamiento por
   diseño, pero sin feedback al usuario de por qué no aparece.
5. **timeout de 30s en `generate_variant_text` → RESUELTO (30→90s)**: la llamada del
   modal dio "El proveedor tardó demasiado..." con OpenRouter sano: nemotron free
   varió entre 20.7s (smoke previo) y 30.9s (verificado después del fix) — la cola
   del free tier excede el límite viejo. Cambio: default `timeout=90.0` en
   `llm_node.py:407` + mensaje de error distingue "probá de nuevo" de "cambiá de
   proveedor". Verificado de punta a punta vía `POST /api/variants/generate`
   (200 OK en 30.9s, texto coherente, `unverified_terms: []`). El server con
   `--reload` tomó el cambio sin reiniciar.

## Hallazgos menores (no bloqueantes)

- El error "ángulo desconocido" responde **502** en vez de 422 (el validador de
  ángulos vive en el RuntimeError del proveedor, no en el router).
- El `uvicorn --reload` aparece como dos procesos python (supervisor + worker);
  no es un puerto duplicado, es el patrón normal en Windows.

## Mejoras candidatas (UX, detectadas con el usuario en la corrida real)

- **Hueco: bullet con 1 variante y sin ángulo preferido no tenía vía de generar
  redacciones desde el target** — **RESUELTO (iteración post-QA, 2026-08-12)**:
  decisión del usuario: ✏ y ⇄ aparecen SIEMPRE en bullets del target con logro;
  sin ángulo preferido el ✏ genera una versión "genérica" (`angle: ""`), el ⇄
  existe desde 1 variante approved incluyendo "Generar otra redacción…". El
  ángulo para redactar sale del match del bullet con la oferta (preferred_angles).
  Spec: `docs/specs/iteracion_post_qa_f6.md`.
- **Explicar al usuario por qué aparece el ✏** — **RESUELTO**: tooltip del botón
  explica la regla y el ángulo elegido (o "genérica").
- **Confirmado por el usuario**: el modal F6 "anda perfecto" tras el fix de timeout
  (30→90s). "Usar y guardar"/"Usar solo esta vez" funcionan.

## Resueltos en la iteración post-QA (2026-08-12)

- [x] 422 para ángulo desconocido no vacío (antes 502); ángulo vacío = "genérica"
      válido en el router y en `generate_variant_text` (prompt sin ángulo).
- [x] Feature: proveedor OpenRouter en la UI de Configuración (preset que
      configura `openai` + base_url de OpenRouter), campos condicionales por
      proveedor (`ollama_model` solo con local) y sugerencias de modelos
      OpenRouter vía datalist (texto libre).

## Otros hallazgos del entorno (QA previos, útiles para iteraciones futuras)

- `load_config()` degrada a `DEFAULTS` silenciosamente si `config.json` no parsea
  (p.ej. BOM de PowerShell 5.1) → config rota sin aviso; pedir mejor un log/error.
- No volver a escribir `config.json` con PowerShell `Set-Content -Encoding UTF8`
  (escribe BOM y rompe el parseo de Python).
- uvicorn relanzado con el código nuevo es requisito para que exista
  `/api/variants/generate` (el proceso viejo daba 405).

## Estado de datos al cierre del QA

- Rollback completo ejecutado: `data/master_cv.yaml` restaurado al original (sin
  var_qa_f6 ni variantes del QA) y `config.json` restaurado a Gemini
  (gemini-3.6-flash). Backups eliminados.
- OpenRouter queda documentado para uso a gusto: `llm_provider: openai` +
  `openai_base_url: https://openrouter.ai/api/v1` + `openai_model: <modelo>` +
  `openai_api_key` (compatible sin cambios de código).
