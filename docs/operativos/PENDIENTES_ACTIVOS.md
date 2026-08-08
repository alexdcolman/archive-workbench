# Pendientes activos — Archive Workbench

**Estado preparado:** 2026-08-08 · **versión:** 0.86.0

Este archivo es la única fuente de verdad para trabajo abierto. Las capacidades cerradas se registran en `IMPLEMENTACIONES_REALIZADAS.md` y no deben reabrirse sin una regresión concreta o una ampliación explícita del alcance.

## Orden acordado

`CAT-02` y `GRAPH-02` quedaron implementados, validados y cerrados en 0.77.0. La secuencia principal y las líneas paralelas se mantienen en [`HOJA_DE_RUTA_PRE_RELEASE.md`](HOJA_DE_RUTA_PRE_RELEASE.md).

`AV-01` quedó implementado, validado y cerrado en 0.84.0, `AV-02` en 0.85.0 y `AV-03` en 0.86.0. La secuencia abierta comienza en `INT-01` y después continúa con `EXP-01`, `PILOT-01`, `UX-02`, `WEB-01`, `QA-01` junto con `OPS-02`, `OPS-01` y `OPS-03`. `OCR-01` quedó cerrado en 0.83.0.

`GIAR-01` comienza como proyecto paralelo vinculado a `PILOT-01` y no bloquea por sí solo la v1.0. `AI-01` y `AI-02` quedan para después del release inicial.

## Índice

| ID | Prioridad | Estado | Tarea |
|---|---|---|---|
| INT-01 | Baja | Pendiente | Integración opcional con Google Drive como transporte |
| EXP-01 | Alta | Pendiente pre-release | Exportación trazable de imágenes y recortes para análisis visual |
| PILOT-01 | Alta | Parcial | Corpus real persistente, verdad terreno y cierre del piloto |
| GIAR-01 | Paralela | Planificado | Base de conocimiento y sitio del Grupo de Investigación en Archivos de la Represión |
| UX-02 | Alta | Pendiente | Revisión final de complejidad acumulada de la interfaz |
| WEB-01 | Alta | Pendiente pre-release | Sitio público, tutorial, README ilustrado y referencia técnica |
| QA-01 | Media | Pendiente | Ruff y mypy como control estático pre-release |
| OPS-02 | Media | Pendiente | Clasificación formal de la suite de pruebas |
| OPS-01 | Media | Pendiente | Imagen Docker y perfiles de instalación |
| OPS-03 | Media | Parcial | Instalación limpia, rutas CPU/GPU y candidata a v1.0 |
| AI-01 | Post-release | Pendiente | Pipeline CLI opcional de análisis con LLM |
| AI-02 | Post-release | Pendiente | Sistema RAG trazable sobre corpus sistematizados |

## Mejora funcional

### INT-01 — Integración opcional con Google Drive como transporte — PENDIENTE

Agregar enlaces, descarga asistida, subida de paquetes de intercambio y comparación de manifiestos. Drive no será una base viva ni permitirá edición simultánea de SQLite; su función es transportar archivos y paquetes entre copias controladas.

### EXP-01 — Exportación trazable de imágenes y recortes — PENDIENTE PRE-RELEASE

Extender la exportación para incluir imágenes de página, recortes regionales y figuras seleccionadas junto con un manifiesto que conserve documento, página, región, geometría, checksum, procedencia, estado de revisión y relación con el texto exportado.

La salida debe poder consumirse después desde `AI-01` por una etapa CLI `vision_describe`, sin acceder directamente a originales ni perder el vínculo con la fuente. La exportación no ejecutará modelos ni convertirá descripciones automáticas en datos revisados.

## Cierre pre-release

### PILOT-01 — Corpus real persistente, verdad terreno y cierre del piloto — PARCIAL

El piloto pre-release se ejecutará sobre un proyecto real y persistente destinado después al equipo de investigación. No será una base descartable ni se reinicializará entre pruebas. Antes de comenzar se acordarán su ruta, política de backups, responsables y reglas de acceso.

El corpus incluirá:

- legajos del archivo de la DIPPBA, reutilizando la base de catálogo ya construida;
- legajos del APM-Chubut;
- audios y videos testimoniales, incluidos los materiales autorizados de una página de YouTube, incorporados mediante `AV-01` y, cuando corresponda, `AV-02`.

Las pruebas deben conservar corridas, selecciones, revisiones, transcripciones, entidades, relaciones, referencias archivísticas y exportaciones reales. El corpus técnico anterior puede seguir usándose para regresiones, pero no reemplaza este piloto.

Debe permitir:

- comparar corridas y perfiles;
- medir cobertura y CER/WER cuando exista transcripción verdadera;
- evaluar orden de lectura, layout y regiones documentales;
- evaluar transcripción segmentada de audio y video, reproducción con velocidad variable y corrección humana sincronizada;
- documentar perfiles CPU y GPU;
- decidir mejoras con evidencia acumulada;
- completar recorridos reales de extremo a extremo sin perder resultados entre versiones.

La guía operativa específica se encuentra en [`GUIA_PRUEBA_PILOTO.md`](GUIA_PRUEBA_PILOTO.md). El proyecto paralelo `GIAR-01` puede reutilizar referencias, autoridades y vínculos documentales sin compartir la misma base física.

### UX-02 — Revisión final de complejidad acumulada de la interfaz — PENDIENTE

Realizar una revisión integral después de cerrar los bloques funcionales activos y antes de la candidata a v1.0. Debe recorrer todas las vistas con un proyecto representativo y comprobar que la incorporación sucesiva de capacidades no haya vuelto a densificar la interfaz.

La revisión debe:

- conservar todas las funciones, sin resolver complejidad eliminando capacidades;
- mantener una acción principal clara por recorrido;
- agrupar opciones avanzadas, historiales y datos técnicos mediante divulgación progresiva;
- dejar cerrados por defecto los paneles secundarios que no sean necesarios para la tarea inmediata;
- detectar controles, explicaciones, tarjetas o paneles duplicados;
- revisar jerarquía visual, longitud de pantallas, navegación, formularios y comportamiento después de cada rerun;
- validar recorridos representativos de OCR, revisión, entidades, descubrimiento, búsqueda, exportación, administración e intercambio;
- reorganizar la subsección **Formulario** de revisión, hoy funcional pero difícil de comprender, y evaluar una referencia visual persistente de la página sin saturar el recorrido principal;
- revisar nuevamente **Orden y estructura** después del cierre funcional: aun con el recorrido numerado incorporado en la RC2 de 0.80.0, debe evaluarse su densidad, la relación entre selección de objeto, columnas y diagnósticos, y la comprensión del historial.
- reevaluar **OCR regional** sin perder su recorrido lineal de seis pasos, la página visible ni el ocultamiento de opciones avanzadas.

`UX-02` se programa al final para evaluar la interfaz completa, pero no habilita a postergar regresiones: toda versión nueva debe aplicar de inmediato el principio permanente de **Interfaz y formularios** registrado en `IMPLEMENTACIONES_REALIZADAS.md`. Si una pantalla concreta se vuelve confusa antes, se corrige en ese mismo bloque funcional.

### WEB-01 — Sitio público y documentación de release — PENDIENTE PRE-RELEASE

Preparar un sitio de varias páginas HTML para GitHub Pages dirigido a archivistas, cientistas sociales, lingüistas, historiadores y personas que trabajan con archivos. Debe ser legible sin conocimientos de programación e incluir figuras, esquemas y capturas reales de la interfaz cuando ayuden a explicar una tarea.

El bloque incluye:

- portada y mapa de capacidades;
- explicación del catálogo, procesamiento, revisión, autoridades, grafos, búsqueda, intercambio y resguardo;
- tutorial completo de uso de la aplicación;
- README revisado con capturas, instalación, recorrido inicial y enlaces públicos;
- documento técnico detallado para el release sobre arquitectura, persistencia, contratos, trazabilidad, migraciones y extensiones;
- revisión de accesibilidad, enlaces, metadatos y publicación en GitHub Pages.

Las políticas privadas canónicas serán `.assistant/POLITICA_SITIO_PUBLICO.md` y `.assistant/LINEAMIENTOS_DE_DISENO_Y_ESCRITURA.md`. Las capturas deben mostrar estados reales de la aplicación y documentar cómo se reprodujeron. `WEB-01` se ejecuta después de `UX-02` para evitar publicar recorridos que todavía puedan reorganizarse.

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

## Proyecto paralelo vinculado

### GIAR-01 — Base de conocimiento y sitio del Grupo de Investigación en Archivos de la Represión — PLANIFICADO

Construir, en un proyecto separado y persistente de Archive Workbench, una base que relacione integrantes, publicaciones, informes, proyectos financiados, entidades estudiadas, alias, clases revisables, relaciones con evidencia y referencias a archivos, fondos, secciones y unidades documentales.

A partir de esa base se prepararán páginas personales, páginas temáticas integradas, un glosario con variaciones conceptuales, páginas de archivos y unidades estudiadas, publicaciones y un grafo navegable. El sitio se publicará mediante GitHub Pages en una cuenta propia del grupo.

La carga estructurada puede avanzar en paralelo con `PILOT-01`; la publicación del sitio se realizará cuando el modelo y los contenidos hayan sido revisados. El alcance, las fases y las reglas de separación están en [`PROYECTO_PARALELO_GIAR.md`](../referencia/PROYECTO_PARALELO_GIAR.md). Antes de diseñar ese sitio se crearán políticas propias de sitio, diseño y escritura en su repositorio.

## Post-release

### AI-01 — Pipeline CLI opcional de análisis con LLM — PENDIENTE POST-RELEASE

Diseñar las etapas concretas del pipeline de análisis con LLM, sus contratos de entrada y salida, orden, reintentos, caché, trazabilidad e ingeniería de contexto. Cuando comience este bloque, Alex proporcionará otro repositorio para estudiar qué componentes pueden reutilizarse y cuáles deben implementarse específicamente para Archive Workbench.

El pipeline consumirá exportaciones reproducibles y podrá incluir, entre otras, estas familias de etapas:

- `vision_describe` sobre imágenes y recortes producidos por `EXP-01`;
- descripción o resumen de textos;
- análisis temático;
- análisis por conceptos definidos por el equipo;
- etapas adicionales que se definan después de revisar el repositorio de referencia.

Cada salida debe registrar archivo o fragmento de origen, modelo, versión, parámetros, prompt o plantilla, contexto aportado, fecha y hash. No debe escribir sobre el corpus ni convertir resultados automáticos en anotaciones humanas sin una importación revisada.

### AI-02 — Sistema RAG trazable sobre corpus sistematizados — PENDIENTE POST-RELEASE

Diseñar una capa opcional de recuperación y generación sobre trabajos del equipo u otros corpus sistematizados. Debe:

- construirse desde exportaciones versionadas;
- citar documentos, páginas, objetos o segmentos exactos;
- respetar filtros de calidad y permisos;
- registrar modelo de embeddings, índice y fecha;
- permitir reconstrucción y comparación de índices;
- mantener las respuestas fuera de la fuente de verdad hasta una revisión explícita.

Puede alimentar análisis automático, pero no reemplaza el descubrimiento estructurado ni el diccionario de autoridades.
