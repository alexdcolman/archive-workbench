# Pendientes activos — Archive Workbench

**Estado verificado:** 2026-08-05 · **versión:** 0.78.0

Este archivo es la única fuente de verdad para trabajo abierto. Las capacidades cerradas se registran en `IMPLEMENTACIONES_REALIZADAS.md` y no deben reabrirse sin una regresión concreta o una ampliación explícita del alcance.

## Orden acordado

`CAT-02` y `GRAPH-02` quedaron implementados, validados y cerrados en 0.77.0. El orden previsto antes de la candidata a v1.0 es:

1. `OCR-01`;
2. `AV-01`;
3. `AV-02`;
4. `INT-01`;
5. `PILOT-01`;
6. `UX-02`;
7. `QA-01` junto con `OPS-02`;
8. `OPS-01`;
9. `OPS-03` y candidata a v1.0.

`AI-01` y `AI-02` quedan expresamente para después del release inicial.

## Índice

| ID | Prioridad | Estado | Tarea |
|---|---|---|---|
| OCR-01 | Media | Parcial | Preprocesamiento, layout y clasificación documental |
| AV-01 | Media | Pendiente | Registro audiovisual local y transcripción segmentada |
| AV-02 | Baja | Pendiente | Plugin opcional de descarga desde YouTube y otras plataformas |
| INT-01 | Baja | Pendiente | Integración opcional con Google Drive como transporte |
| PILOT-01 | Alta | Parcial | Corpus de evaluación, verdad terreno y cierre del piloto |
| UX-02 | Alta | Pendiente | Revisión final de complejidad acumulada de la interfaz |
| QA-01 | Media | Pendiente | Ruff y mypy como control estático pre-release |
| OPS-02 | Media | Pendiente | Clasificación formal de la suite de pruebas |
| OPS-01 | Media | Pendiente | Imagen Docker y perfiles de instalación |
| OPS-03 | Media | Parcial | Instalación limpia, rutas CPU/GPU y candidata a v1.0 |
| AI-01 | Post-release | Pendiente | Herramientas CLI opcionales con LLM sobre exportaciones |
| AI-02 | Post-release | Pendiente | Sistema RAG trazable sobre corpus sistematizados |

## Mejora funcional

### OCR-01 — Preprocesamiento, layout y clasificación documental — PARCIAL

La fase `OCR-01A` quedó implementada y validada en 0.78.0: orientación conservadora, deskew acotado, eliminación controlada de líneas y marcos, máscaras diagnósticas y trazabilidad estructurada por página. Los originales y las previsualizaciones permanecieron intactos en los cinco casos controlados.

Queda por completar y evaluar dentro de `OCR-01`:

- dewarp;
- OCR regional;
- párrafos, columnas y orden de lectura;
- reducción de fragmentación línea por línea y duplicaciones;
- portadas, encabezados, pies, números de página, sellos, firmas, manuscritos, ilustraciones y elementos preimpresos;
- casilleros vacíos, marcados e indeterminados y agrupaciones de formulario;
- benchmark ampliado de Tesseract, Docling y Surya con verdad terreno.

Toda transformación debe producir un derivado reproducible y nunca inventar trazos.

### AV-01 — Registro audiovisual local y transcripción segmentada — PENDIENTE

Agregar un módulo opcional para audio y video local:

- original inmutable, archivo local y SHA-256;
- título, productor o canal, procedencia, fecha, duración, derechos y descripción;
- transcripción como derivado versionado;
- segmentos con `start_time`, `end_time` y texto;
- revisión manual, búsqueda, entidades y exportación sobre segmentos;
- backend intercambiable con recorrido CPU funcional;
- identificación de hablantes como ampliación opcional posterior.

Debe instalarse como dependencia opcional y evitar conflictos con el runtime OCR/CUDA.

### AV-02 — Plugin opcional de descarga desde YouTube y otras plataformas — PENDIENTE

Implementar fuera del núcleo un plugin prescindible, probablemente basado en `yt-dlp` y FFmpeg, para descargar materiales autorizados. Debe conservar URL, identificador de plataforma, metadatos, fecha de incorporación, checksum y condiciones de acceso.

No será requisito para usar Archive Workbench ni se mezclará con el módulo de transcripción local.

### INT-01 — Integración opcional con Google Drive como transporte — PENDIENTE

Agregar enlaces, descarga asistida, subida de paquetes de intercambio y comparación de manifiestos. Drive no será una base viva ni permitirá edición simultánea de SQLite; su función es transportar archivos y paquetes entre copias controladas.

## Cierre pre-release

### PILOT-01 — Corpus de evaluación, verdad terreno y cierre del piloto — PARCIAL

Consolidar un corpus de cinco documentos representativos y ampliarlo después a entre veinte y treinta. Para páginas seleccionadas registrar objetos esperados, orden, texto crítico, estructura y regiones que no deben perderse.

Debe permitir:

- comparar corridas y perfiles;
- medir cobertura y CER/WER cuando exista transcripción verdadera;
- evaluar orden de lectura y layout;
- documentar perfiles CPU y GPU;
- decidir mejoras con evidencia y no por una sola página;
- completar al menos un recorrido real de extremo a extremo antes de la candidata a v1.0.

### UX-02 — Revisión final de complejidad acumulada de la interfaz — PENDIENTE

Realizar una revisión integral después de cerrar los bloques funcionales activos y antes de la candidata a v1.0. Debe recorrer todas las vistas con un proyecto representativo y comprobar que la incorporación sucesiva de capacidades no haya vuelto a densificar la interfaz.

La revisión debe:

- conservar todas las funciones, sin resolver complejidad eliminando capacidades;
- mantener una acción principal clara por recorrido;
- agrupar opciones avanzadas, historiales y datos técnicos mediante divulgación progresiva;
- dejar cerrados por defecto los paneles secundarios que no sean necesarios para la tarea inmediata;
- detectar controles, explicaciones, tarjetas o paneles duplicados;
- revisar jerarquía visual, longitud de pantallas, navegación, formularios y comportamiento después de cada rerun;
- validar recorridos representativos de OCR, revisión, entidades, descubrimiento, búsqueda, exportación, administración e intercambio.

`UX-02` se programa al final para evaluar la interfaz completa, pero no habilita a postergar regresiones: toda versión nueva debe aplicar de inmediato el principio permanente de **Interfaz y formularios** registrado en `IMPLEMENTACIONES_REALIZADAS.md`. Si una pantalla concreta se vuelve confusa antes, se corrige en ese mismo bloque funcional.

### QA-01 — Control estático y tipado — PENDIENTE

Formalizar el control estático después de `UX-02` y junto con la clasificación de pruebas:

- ejecutar `ruff check` y `ruff format --check` sobre `src` y `tests`;
- incorporar `mypy` de manera gradual sobre `src/archive_workbench`;
- no activar `strict` global de una sola vez;
- no ocultar errores mediante `ignore_errors` global;
- documentar únicamente excepciones puntuales y justificadas para dependencias dinámicas.

### OPS-02 — Clasificación formal de la suite de pruebas — PENDIENTE

Mantener toda la cobertura existente y marcar pruebas como `fast`, `integration` y `slow`. Definir comandos estables por nivel y dependencias externas, sin eliminar pruebas por su duración.

En cada versión se ejecutan los subsistemas afectados, transversales pertinentes y recopilación completa; la suite monolítica queda como validación final local.

### OPS-01 — Imagen Docker y perfiles de instalación — PENDIENTE

Crear una imagen Docker para simplificar la instalación. Debe separar al menos:

- perfil CPU básico;
- servicios opcionales de búsqueda semántica;
- perfil GPU/Surya documentado y compatible con NVIDIA.

Los proyectos y originales se montan como volúmenes; la imagen no debe encerrar datos del usuario. Debe haber instrucciones de backup, actualización y persistencia.

### OPS-03 — Instalación limpia, rutas CPU/GPU y candidata a v1.0 — PARCIAL

Antes de v1.0 falta:

- instalación limpia en otra computadora;
- ruta CPU sin CUDA;
- perfil GPU elegido y documentado;
- migración de una base antigua real;
- proyecto de ejemplo;
- requisitos mínimos y opcionales;
- contratos y esquema 1.0 congelados;
- candidata pública y documentación utilizable por otra persona;
- cierre de bugs con riesgo de pérdida de datos.

Backups, restauración e intercambio ya fueron probados, pero deben repetirse en la candidata final y en un entorno limpio.

## Post-release

### AI-01 — Herramientas CLI opcionales con LLM sobre exportaciones — PENDIENTE POST-RELEASE

Crear herramientas paralelas, ejecutables desde terminal y separadas del núcleo, que consuman salidas reproducibles de Exportar para:

- descripción y análisis de imágenes;
- resumen o descripción de textos;
- análisis temático;
- análisis por conceptos definidos por el equipo.

Cada salida debe registrar archivo o fragmento de origen, modelo, versión, parámetros, prompt o plantilla, fecha y hash. No debe escribir sobre el corpus ni convertir resultados automáticos en anotaciones humanas sin una importación revisada.

### AI-02 — Sistema RAG trazable sobre corpus sistematizados — PENDIENTE POST-RELEASE

Diseñar una capa opcional de recuperación y generación sobre trabajos del equipo u otros corpus sistematizados. Debe:

- construirse desde exportaciones versionadas;
- citar documentos, páginas, objetos o segmentos exactos;
- respetar filtros de calidad y permisos;
- registrar modelo de embeddings, índice y fecha;
- permitir reconstrucción y comparación de índices;
- mantener las respuestas fuera de la fuente de verdad hasta una revisión explícita.

Puede alimentar análisis automático, pero no reemplaza el descubrimiento estructurado ni el diccionario de autoridades.
