# Pendientes activos — Archive Workbench

**Estado verificado:** 2026-08-04 · **versión:** 0.74.0

Este archivo es la única fuente de verdad para trabajo abierto. Las capacidades cerradas se registran en `IMPLEMENTACIONES_REALIZADAS.md` y no deben reabrirse sin una regresión concreta o una ampliación explícita del alcance.

## Orden acordado

`SEM-01` y `GRAPH-01` quedaron validados en 0.74.0 y ya no forman parte del trabajo abierto. El orden previsto antes de la candidata a v1.0 es:

1. `CAT-01`, incluida la primera plantilla de prueba del fondo DIPPBA;
2. `DISC-02`;
3. `CAT-02` junto con `GRAPH-02`;
4. `OCR-01`;
5. `AV-01`;
6. `AV-02`;
7. `INT-01`;
8. `PILOT-01`;
9. `UX-02`;
10. `QA-01` junto con `OPS-02`;
11. `OPS-01`;
12. `OPS-03` y candidata a v1.0.

`AI-01` y `AI-02` quedan expresamente para después del release inicial.

## Índice

| ID | Prioridad | Estado | Tarea |
|---|---|---|---|
| CAT-01 | Media | Pendiente | Plantillas distribuibles de catálogo y estructura archivística |
| DISC-02 | Media | Pendiente | Importación de diccionarios de autoridades y relaciones |
| CAT-02 | Media | Pendiente | Entidades productoras y gestoras del catálogo |
| GRAPH-02 | Media | Pendiente | Estructura archivística, documentos y partes en el grafo |
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

### CAT-01 — Plantillas distribuibles de catálogo y estructura archivística — PENDIENTE

Permitir que una persona sin conocimientos técnicos pueda exportar, completar e importar una plantilla tabular del catálogo. El formato principal será XLSX y deberá incluir, como mínimo:

- una hoja `INSTRUCCIONES` con la descripción de cada campo vigente;
- una hoja `ESTRUCTURA` con niveles archivísticos, padres permitidos y reglas configurables;
- una hoja `CATALOGO` con identificadores locales, padre local, nivel, código de referencia, título y los demás campos descriptivos habilitados;
- una hoja `LISTAS` para vocabularios controlados y desplegables.

La estructura debe impedir combinaciones no autorizadas —por ejemplo, que un documento tenga como padre directo un archivo o un fondo cuando el perfil exige legajo, caja, carpeta u otro nivel intermedio— sin imponer una jerarquía universal a todos los proyectos.

La importación deberá ejecutar primero una simulación completa, informar errores por hoja, fila y celda, detectar identificadores repetidos, padres inexistentes, ciclos y transiciones de nivel inválidas, y aplicar los cambios únicamente después de una confirmación explícita y dentro de una sola transacción. También deberá permitir exportar una plantilla vacía o un catálogo existente sin perder jerarquía ni campos configurados.

La primera validación utilizará una plantilla del fondo DIPPBA construida a partir de su cuadro público de clasificación. Debe conservar denominaciones, códigos, jerarquía, descripciones, URL de procedencia y fecha de recuperación; los datos ausentes permanecerán vacíos y no se completarán por inferencia.

### DISC-02 — Importación de diccionarios de autoridades y relaciones — PENDIENTE

Permitir importar un diccionario externo creado por un equipo o por una herramienta asistida, con:

- autoridades y nombres preferidos;
- alias;
- tipos y características configurables;
- temporalidad;
- relaciones entre autoridades;
- evidencia y procedencia;
- investigadores, publicaciones u otros objetos de conocimiento cuando el modelo lo permita sin confundir clases.

La importación debe incluir formato documentado, validación, vista previa, simulación, detección de duplicados, resolución de conflictos y aplicación transaccional. No debe sobrescribir registros existentes ni aceptar relaciones sin evidencia de manera silenciosa.

La implementación deberá publicar una guía única de formato —JSON/JSONL o equivalente— con ejemplos, esquema versionado y reglas para identificadores, alias, temporalidad y relaciones.

### CAT-02 — Entidades productoras y gestoras del catálogo — PENDIENTE

Agregar a las unidades archivísticas los roles de entidad productora y entidad gestora mediante relaciones controladas con autoridades existentes, no como texto libre canónico. La interfaz del catálogo debe presentarlas como campos propios y permitir registrar, cuando corresponda, período, evidencia, procedencia y cambios de gestión.

La implementación debe evitar duplicar nombres ya normalizados, conservar historial y permitir que una misma autoridad desempeñe roles distintos en unidades o períodos diferentes.

### GRAPH-02 — Estructura archivística, documentos y partes en el grafo — PENDIENTE

Incorporar como capas filtrables del mapa:

- la jerarquía entre archivo, fondo, sección, serie, subserie, unidad y demás niveles configurados;
- la pertenencia de documentos y partes internas a sus unidades archivísticas;
- las menciones de autoridades en documentos o partes;
- las relaciones analíticas entre autoridades;
- las entidades productoras y gestoras incorporadas por `CAT-02`.

La vista debe permitir activar o desactivar cada capa, filtrar niveles, limitar profundidad y cantidad de nodos, y partir de una unidad, documento, parte o autoridad focal. La procedencia de cada arista debe seguir siendo explicable y no debe confundirse una relación archivística de pertenencia con una relación analítica entre entidades.

### OCR-01 — Preprocesamiento, layout y clasificación documental — PARCIAL

Completar y evaluar:

- deskew, dewarp y orientación;
- eliminación controlada de líneas y marcos;
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
