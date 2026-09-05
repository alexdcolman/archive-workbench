# Pendientes activos — Archive Workbench

**Estado actualizado:** 2026-09-04 · **versión:** 0.89.0 RC84

Este archivo es la única fuente de verdad para trabajo abierto. Las capacidades cerradas se registran en `IMPLEMENTACIONES_REALIZADAS.md` y no deben reabrirse sin una regresión concreta o una ampliación explícita del alcance.

## Orden acordado

`CAT-02` y `GRAPH-02` quedaron implementados, validados y cerrados en 0.77.0. La secuencia principal y las líneas paralelas se mantienen en [`HOJA_DE_RUTA_PRE_RELEASE.md`](HOJA_DE_RUTA_PRE_RELEASE.md).

`AV-01` quedó implementado, validado y cerrado en 0.84.0, `AV-02` en 0.85.0, `AV-03` en 0.86.0, `INT-01` en 0.87.0 y `EXP-01` en 0.88.0. El rodeo pre-release `UX-04` quedó validado y cerrado en RC29. La validación manual de RC34 cerró el árbol tipo explorador, la eliminación explícita de vínculos productores/gestores cargados por error y los límites amplios de calendarios. La validación manual de RC40 cerró `PILOT-01T`: el bbox vuelve a seleccionar inmediatamente el bloque correspondiente sin reconstruir documento ni página. Las validaciones posteriores cerraron `PILOT-01U/V/W`, Búsqueda textual (`PILOT-01X`) y Búsqueda semántica (`PILOT-01Y`). La pasada funcional de **Explorar relaciones** también quedó verde; RC47-RC49 completaron las mejoras visuales del grafo y `PILOT-01Z` quedó validado. La exportación documental JSONL de 138 documentos y el ZIP de texto + imágenes también quedaron verdes. La validación real de RC50 cerró `PILOT-01AA` con JSONL documental y audiovisual correctos; la pasada posterior de asignación y revisión cruzada también quedó verde. El piloto llegó a **Intercambiar cambios** y abrió `PILOT-01AB` al detectar que la base común se explicaba con lenguaje demasiado interno y que el paquete incremental normal no podía crearse desde la interfaz. RC51 hizo visible la creación del paquete, pero la revisión conceptual mostró que el recorrido normal seguía sobrecargado por acuerdos bilaterales e identidades de contraparte. RC52 lo simplifica a preparar una copia de trabajo compartible, enviar cambios y recibir cambios; el mismo ZIP inicial puede distribuirse a varias personas y cada copia se reidentifica automáticamente al abrirse por primera vez. La validación real detectó además que Google Drive podía preseleccionar cualquier ZIP de `exchange/outgoing/` y que un archivo no ZIP propagaba `BadZipFile` hasta Streamlit. RC53 restringió la preselección a paquetes incrementales válidos y contuvo los errores de formato. La siguiente pasada mostró tres necesidades del flujo normal: poder reducir el tamaño de la copia inicial, elegir ZIP mediante selector y transportar también la copia inicial por Google Drive. RC54 agregó perfiles de contenido con estimación de tamaño y omisiones explícitas, selectores de ZIP y transporte reanudable por Drive para copias iniciales y paquetes incrementales. La validación real completó después el intercambio incremental extremo a extremo, incluida subida a Drive, descarga, revisión y aplicación. RC55 redujo banners y relegó detalles técnicos, pero la revisión visual posterior detectó que **Recibir cambios** seguía exponiendo acciones ocasionales y que **Más opciones** separaba Google Drive como una tarea paralela aunque sólo sea una modalidad de Enviar/Recibir. RC56 elimina esa categoría, integra el transporte en las tareas normales y aplica divulgación progresiva al archivo, eliminación, incorporación de nuevos ZIP, diferencias y recuperación. La validación manual posterior dejó todo ese recorrido verde y cerró `PILOT-01AB`. El piloto pasó a **Administrar y recuperar > Integridad** y abrió `PILOT-01AC`: los diagnósticos deben conducir a su sección de resolución, algunos avisos no bloqueantes deben poder descartarse sin borrar evidencia, la revisión técnica de base debe quedar subordinada y **Autorizaciones de análisis** necesita filtros. RC57 implementó esa depuración sin migración y la validación manual posterior cerró `PILOT-01AC`; la creación de backup y la prueba no destructiva de recuperación también quedaron verdes. Después se validó `PILOT-01P` mediante exportación e importación real de fichas. RC58 quedó validado manualmente: desaparecieron los parpadeos de Procesar documentos y los documentos homónimos conservaron identidad independiente. La prueba posterior en lote cerró también `PILOT-01I`: `VLLM::EngineCore` se mantuvo entre documentos y desapareció al finalizar, liberando la VRAM automáticamente. RC59 cierra `PILOT-01L` fijando el contrato público en PDF, TIFF, PNG, JPEG y WebP; BMP queda explícitamente fuera del procesamiento documental. La validación manual posterior confirmó ese contrato y cierra `PILOT-01L`. RC60 realizó la auditoría transversal final de `PILOT-01E` en cinco pasadas. La recorrida manual posterior encontró un último problema de arquitectura de información en audiovisual: la incorporación local y desde plataformas aparecía separada aunque ambas alimentan el mismo circuito, y la sección mezclaba incorporación con transcripción/revisión. RC61 reorganizó esa superficie como **Audio y video** y RC62 agregó la aclaración final de formatos locales. La validación manual de RC62 cerró `PILOT-01E`. La auditoría transversal posterior abrió `PILOT-01AE`; RC63 introdujo regresiones y RC64 las reparó. La validación manual posterior de RC64 dejó la aplicación verde y cierra `PILOT-01AE`. La validación manual de RC65 cierra `PILOT-01A` y con ella el recorrido pre-release de `PILOT-01`; `PILOT-01N` queda post-release. RC66 inicia `DISC-03` con `local_rules_v2` y un corpus heterogéneo reproducible. RC67 audita v2 sobre las exportaciones reales de 138 documentos y 78 segmentos audiovisuales y agrega `local_rules_v3`. La revisión humana de esa corrida detectó falsos positivos de citas, límites truncados/contaminados y un límite silencioso de 500 filas; RC68 agregó `local_rules_v4`, pero la validación mostró que una configuración persistida podía seguir ejecutando v3 sin que la interfaz lo hiciera evidente. RC69 agrega `local_rules_v5`, identifica y bloquea el uso inadvertido de reglas históricas en búsquedas nuevas, conserva corridas anteriores y fija 500 referencias visibles por defecto. La validación manual posterior cierra `DISC-03`. RC70 inició `UX-02` y la recorrida manual posterior lo cerró. RC71 inició `WEB-01`, pero la revisión editorial posterior determinó que el sitio todavía presupone demasiado conocimiento previo y que la instalación pública no puede depender de Linux ni de una terminal. `WEB-01` se retoma tras el cierre pre-release de `OPS-01`. RC72 priorizó `OPS-01` con una distribución CPU basada en contenedor para Windows, macOS y Linux. RC73 separa dos imágenes publicables: CPU multi-arquitectura y NVIDIA GPU, con lanzadores diferenciados y sin construcción local en el equipo del usuario. El primer build material CPU detectó que `llama-server` no resolvía `libllama-server-impl.so` después de copiar el runtime a `/opt/llama`; RC74 corrige la ruta del cargador dinámico y su preflight CPU material queda verde. RC75 mueve la elección de proyectos existentes al sistema anfitrión para abrir carpetas locales sin copiarlas a `ArchiveWorkbenchData`. La utilidad analítica profunda del grafo se evaluará en investigaciones concretas y no bloquea este recorrido. Con `OPS-01` cerrado para el pre-release, se retoma `WEB-01` bajo las reglas de redacción para lectores sin conocimiento previo y continúan `QA-01`/`OPS-02` y `OPS-03`. `OCR-01` quedó cerrado en 0.83.0.

`GIAR-01` comienza como proyecto paralelo vinculado a `PILOT-01` y no bloquea por sí solo la v1.0. `AI-01` y `AI-02` quedan para después del release inicial.

## Índice

| ID | Prioridad | Estado | Tarea |
|---|---|---|---|
| PILOT-01N | Post-release | Pendiente | Evaluar mejoras robustas de OCR localizado sobre texto parcialmente cubierto por firmas o manuscritos |
| GIAR-01 | Paralela | Planificado | Base de conocimiento y sitio del Grupo de Investigación en Archivos de la Represión |
| WEB-01 | Alta | Parcial pre-release, en curso | Reescritura completa del sitio para lectores sin conocimiento previo, capturas reales y publicación final |
| QA-01 | Media | Pendiente | Ruff y mypy como control estático pre-release |
| OPS-02 | Media | Pendiente | Clasificación formal de la suite de pruebas |

| OPS-03 | Media | Parcial | Instalación limpia, rutas CPU/GPU y candidata a v1.0 |
| AI-01 | Post-release | Pendiente | Pipeline CLI opcional de análisis con LLM |
| AI-02 | Post-release | Pendiente | Sistema RAG trazable sobre corpus sistematizados |

## Cierre pre-release

### PILOT-01N - Mejora futura de OCR localizado sobre texto parcialmente cubierto - PENDIENTE POST-RELEASE

La prueba real de lectura localizada sobre `carp_reg.pdf` mostró un caso en que texto impreso queda atravesado u ocultado parcialmente por firmas o anotaciones manuscritas. El reconocimiento localizado recuperó parte del nombre y cargo, pero no todo el contenido visible. Este comportamiento no bloquea el piloto ni invalida la extracción general.

La mejora futura debe evaluarse de manera robusta sobre documentos diversos: comparar tratamientos de imagen acotados y, si la evidencia lo justifica, más de un motor o estrategia de reconocimiento. No debe optimizarse para una sola página ni prometer reconstruir caracteres que estén físicamente ocultos por trazos manuscritos.

**Criterio de cierre:** reunir una muestra variada de regiones con texto impreso parcialmente cubierto, comparar alternativas con verdad terreno cuando sea posible y adoptar una mejora sólo si aumenta de forma estable la recuperación sin degradar casos normales ni introducir reconstrucciones especulativas.




### WEB-01 — Sitio público y documentación de release — PARCIAL PRE-RELEASE, EN CURSO

`WEB-01` se retoma después del cierre pre-release de `OPS-01`.

RC71 construyó una primera versión del sitio público. La revisión editorial posterior detectó un problema transversal: numerosas frases dependen de términos internos o referentes implícitos y resultan difíciles de entender para una persona que llega al software por primera vez. También se decidió no cerrar la página de instalación mientras el uso sencillo siga dependiendo de Linux o de instrucciones de terminal.

`WEB-01` vuelve a ser el bloque activo. La reescritura debe aplicar obligatoriamente `.assistant/LINEAMIENTOS_DE_DISENO_Y_ESCRITURA.md`, en especial la sección **2.5 Regla obligatoria para lectores sin conocimiento previo**. Esa revisión incluye, como reglas de cierre:

- usar una presentación simple del software, sin eslóganes ni formulaciones de venta;
- nombrar siempre el referente completo de palabras como originales, relaciones, evidencia, resultados, copias, extracciones o propuestas;
- definir en lenguaje cotidiano cualquier término archivístico o técnico antes de usarlo para explicar otra función;
- no usar `candidato` como sustantivo autónomo en páginas de entrada o tutoriales;
- no repetir el nombre del software en párrafos donde ya está identificado;
- no repetir en prosa lo que un diagrama contiguo ya comunica;
- explicar concretamente qué varía cuando se hable de documentos, imágenes, audio, video o estructuras diferentes;
- revisar las figuras a tamaño de publicación para impedir texto cortado por los bordes;
- excluir de la publicación cualquier nota interna sobre capturas pendientes, candidatas de desarrollo o tareas editoriales.

Las 16 observaciones editoriales que originaron estas reglas no se resuelven mediante retoques puntuales del HTML actual: la próxima pasada debe revisar **todo el sitio y el README frase por frase** como si la persona lectora no conociera previamente Archive Workbench ni su vocabulario interno.

**Criterio de cierre:** distribución pública ya estabilizada; sitio y README reescritos con referentes explícitos y definiciones suficientes; capturas reales incorporadas; enlaces, metadatos, accesibilidad y publicación de GitHub Pages revisados.


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

Cada salida debe registrar archivo o fragmento de origen, modelo, versión, parámetros, prompt o plantilla, contexto aportado, fecha y hash. No debe escribir sobre el corpus ni convertir resultados automáticos en anotaciones revisadas sin una importación revisada.

### AI-02 — Sistema RAG trazable sobre corpus sistematizados — PENDIENTE POST-RELEASE

Diseñar una capa opcional de recuperación y generación sobre trabajos del equipo u otros corpus sistematizados. Debe:

- construirse desde exportaciones versionadas;
- citar documentos, páginas, objetos o segmentos exactos;
- respetar filtros de calidad y permisos;
- registrar modelo de embeddings, índice y fecha;
- permitir reconstrucción y comparación de índices;
- mantener las respuestas fuera de la fuente de verdad hasta una revisión explícita.

Puede alimentar análisis automático, pero no reemplaza el descubrimiento estructurado ni el diccionario de autoridades.
