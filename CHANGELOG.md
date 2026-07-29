# Changelog

## 0.33.1 — 2026-07-28

- Corrige la migración `0027_temporal_authorities_relations`: deja de recrear `authority_records` mediante batch en SQLite y conserva claves foráneas de menciones y relaciones.
- Agrega regresión de migración con autoridades, alias, menciones, revisiones y relaciones preexistentes.
- Exige autoridad canónica para menciones `accepted` o `modified`.
- Impide menciones activas duplicadas sobre el mismo objeto, revisión y rango de offsets.
- Reutiliza una mención huérfana existente durante la incorporación transversal y muestra conflictos con otras autoridades.
- Aplica las mismas reglas de integridad a la interfaz de Revisión y al intercambio offline.
- Evita la creación o edición accidental de relaciones con `Enter`; permite cambiar el destino y presenta la baja lógica de forma explícita y auditable.
- Ordena los backups por `created_at` del manifiesto, no por el nombre del archivo.
- Reconoce como base común un bundle aplicado previamente aunque el hash editable local haya divergido por una resolución local.
- Tolera enriquecimientos de esquema y fechas ISO equivalentes dentro de cadenas de eventos; trata actualizaciones vacías como duplicados.
- Bloquea la exportación de bundles que contengan inicializaciones OCR posteriores al checkpoint sin una base materializable para sus páginas padre.
- Reconstituye los directorios operativos al reidentificar una copia mediante `exchange-fork-copy`.
- Calcula la vigencia del índice semántico a partir del corpus comprendido por el perfil y evita invalidarlo por cambios ajenos, como alias de entidades.
- Mantiene la revisión de base de datos `0028_operational_readiness`; no incluye reparación retrospectiva de datos piloto.
- 171 tests automatizados.

## 0.33.0 — 2026-07-24

- Agrega la vista **Inicio** con un estado operativo derivado de catálogo, procesamiento, revisión, trabajo, búsquedas, entidades, exportación, intercambio y recuperación.
- Distingue etapas listas, pendientes, opcionales y que requieren atención, con acceso directo a la vista correspondiente.
- Incorpora pruebas no destructivas de recuperación: verifica el backup, lo extrae en una carpeta temporal, controla claves foráneas, aplica las migraciones actuales y abre la copia.
- Registra cada prueba exitosa o fallida en `project_recovery_checks` sin modificar la base activa.
- Agrega historial de recuperación en Administración y los comandos `project-readiness`, `project-backup-test` y `project-recovery-history`.
- Mantiene la restauración real como operación separada, con Streamlit detenido y backup de seguridad previo.
- Conserva diferidas la comparación OCR/Surya, la optimización de extracción y la estabilización CUDA hasta contar con corpus real suficiente.
- Migración `0028_operational_readiness`.
- 159 tests automatizados.

## 0.32.0 — 2026-07-24

- Agrega períodos de existencia o vigencia a entidades y relaciones analíticas.
- Interpreta fechas exactas, meses, años, décadas, intervalos abiertos, rangos y expresiones aproximadas.
- Conserva la expresión humana original y límites normalizados separados.
- Incorpora filtros por superposición temporal en Entidades, Relaciones, Búsqueda literal, Búsqueda semántica, Grafo y Exportar.
- Permite incluir expresamente registros vinculados sin fecha.
- Agrega metadatos temporales a exportaciones CSV/JSONL y registra el filtro en el perfil reproducible.
- Integra campos temporales con revisiones, checkpoints, dry-run, conflictos y bundles offline.
- Corrige la edición de fecha límite dentro de los formularios de Trabajo.
- Mantiene pendientes OCR/Surya, optimización de extracción y compatibilidad CUDA hasta su evaluación sobre corpus real.
- Migración `0027_temporal_authorities_relations`.
- 156 tests automatizados.

## 0.31.0 — 2026-07-24

- Agrega la vista **Trabajo** para coordinar responsabilidades del equipo.
- Permite asignar documentos completos, páginas o rangos para procesamiento y revisión primaria.
- Incorpora estados, prioridades, fechas límite, notas, responsables y accesos directos a Revisión.
- Agrega un panel de carga por persona y avance documental.
- Incorpora revisión cruzada vinculada a una revisión primaria enviada y exige otra persona responsable.
- Registra resultados `accepted`, `changes_requested` o `not_applicable` sin modificar automáticamente el texto ni sus estados canónicos.
- Conserva historial append-only de cada asignación.
- Integra asignaciones, revisiones y conflictos con checkpoints y bundles offline.
- Agrega `work-assignment-*`, `work-cross-review-create`, `work-assignments` y `work-summary`.
- Registra como pendientes la evaluación comparativa de OCR/Surya, la optimización de extracción y la compatibilidad CUDA/dependencias.
- Migración `0026_team_workflow`.
- 141 tests automatizados.

## 0.30.0 — 2026-07-24

- Agrega la vista **Procesamiento** con inventario integral del corpus.
- Coordina preparación, extracción, reintento e inicialización editable por documento o lote.
- Descubre perfiles `extraction*.yaml` y diagnostica sus dependencias antes de ejecutar.
- Registra trabajos e ítems persistentes con responsable, parámetros, estados, mensajes y detalles.
- Permite reintentar únicamente páginas fallidas o no producidas por la última corrida.
- Fuerza selección canónica manual para todas las extracciones iniciadas desde la interfaz.
- Permite elegir páginas por corrida, inicializarlas y abrirlas directamente en Revisión.
- Agrega `processing-status` y `processing-jobs`.
- Deja asentado que la búsqueda semántica funciona técnicamente pero aún no fue evaluada sobre un corpus suficiente.
- Migración `0025_processing_dashboard`.
- 136 tests automatizados.

## 0.29.0 — 2026-07-24

- Agrega búsqueda semántica opcional y separada de la búsqueda literal FTS5.
- Incorpora perfiles persistentes con modelo, revisión, agrupación, filtros, fragmentación y prefijos.
- Incluye un perfil inicial con `intfloat/multilingual-e5-small` fijado a una revisión concreta.
- Guarda vectores Float32, metadatos JSONL y manifest con checksums fuera de SQLite.
- Invalida el índice ante cambios del corpus, del perfil o de sus archivos derivados.
- Permite indexar por objeto, página, parte interna, documento o unidad archivística.
- Agrega navegación desde resultados semánticos hacia la revisión documental.
- Agrega `semantic-profile-*`, `semantic-index-*` y `semantic-search`.
- La dependencia `sentence-transformers` queda en el extra opcional `semantic`.
- Migración `0024_semantic_search`.
- 132 tests automatizados.

## 0.28.0 — 2026-07-24

- Agrega búsqueda transversal por entidad sobre nombre preferido y alias.
- Previsualiza contexto, documento, página, objeto y tipo de coincidencia antes de crear menciones.
- Permite incorporar coincidencias individuales, seleccionadas o todas las nuevas, con deduplicación.
- Agrega `mention-find-entity` y `mention-include-entity`.
- Incorpora la vista **Administración** con controles globales de SQLite, archivos, menciones, grafo, búsqueda y exportaciones.
- Agrega backups ZIP verificables de SQLite y `config/`, sin copiar originales pesados.
- Verifica estructura, checksums y `PRAGMA quick_check` antes de restaurar.
- La restauración crea un backup automático previo y reemplaza la base de forma atómica.
- Agrega `project-check`, `project-backup-*` y `project-restore-backup`.
- Sin migración nueva; la revisión permanece en `0023_reproducible_corpus_exports`.
- 130 tests automatizados.

## 0.27.0 — 2026-07-24

- Corrige `BidiComponentInvalidIdError` en el grafo: las claves dinámicas se transforman en identificadores SHA-256 compatibles con Streamlit Components v2.
- Agrega perfiles persistentes de exportación con nombre, revisión y configuración reproducible.
- Permite agrupar por objeto, página, parte interna, documento o unidad archivística.
- Permite usar texto corregido, OCR original o fallback al original, y filtrar por tipos y revisión.
- Agrega vista previa sin escritura y exportación CSV/JSONL desde la nueva vista **Exportar**.
- Registra snapshot del perfil, hash del estado, checksum del archivo, ruta, filas y caracteres.
- Agrega `export-profile-list`, `export-profile-save`, `corpus-export-preview`, `corpus-export` y `corpus-export-history`.
- Migración `0023_reproducible_corpus_exports`.
- 127 tests automatizados.

## 0.26.0 — 2026-07-24

- Agrega una vista interactiva de grafo derivada de la base canónica.
- Distingue relaciones explícitas, menciones vinculadas y entidades compartidas.
- Permite filtrar por tipo de nodo, arista, revisión, estado, foco y profundidad.
- Explica la procedencia de cada arista y permite navegar a entidades, catálogo o evidencia textual.
- Agrega controles de consistencia para duplicados, falta de evidencia, extremos inactivos y menciones desactualizadas.
- Exporta la vista filtrada a JSON, CSV y GraphML mediante la UI o `graph-export`.
- Agrega `graph-check` para inspección desde terminal.
- Mantiene el grafo como vista derivada: no altera checkpoints, bundles ni relaciones.
- Sin migración nueva; la revisión permanece en `0022_catalog_usability_entity_relations`.
- 119 tests automatizados.

## 0.25.0 — 2026-07-24

- Reorganiza el catálogo alrededor de la unidad seleccionada y permite crear unidades hijas directamente.
- Aclara el significado de unidad padre, el efecto de mover una rama y agrega deshacer del último movimiento.
- Separa quitar un vínculo archivístico, retirar una instancia local y eliminar físicamente un archivo.
- Agrega una guía de procesamiento posterior a la asociación de un PDF/TIFF.
- Corrige la búsqueda trigram para que fragmentos como `marx` encuentren `marxista`.
- Usa “entidad” en la UI y explica el término profesional “registro de autoridad”.
- Agrega `mention-scan-all` y mensajes específicos cuando se confunde un UUID de entidad con uno de objeto textual.
- Incorpora relaciones explícitas versionadas entre entidades, unidades archivísticas y partes internas.
- Integra relaciones y bajas de vínculos digitales con búsqueda, checkpoints y bundles offline.
- Agrega aliases CLI `entity-*` y comandos `entity-relation-*`.
- Migración `0022_catalog_usability_entity_relations`.
- 115 tests automatizados.

## 0.24.0 — 2026-07-24

- Agrega registros de autoridad versionados para personas, organismos, lugares, acontecimientos, obras y otras entidades.
- Incorpora alias tipificados y normalizados sin reemplazar las grafías documentales.
- Agrega menciones sobre objetos editables con offsets, estado, origen, confianza y vínculo opcional a una autoridad.
- Conserva la revisión textual de origen y marca las menciones como desactualizadas cuando cambia el objeto.
- Agrega sugerencias pendientes por diccionario a partir de nombres preferidos y alias activos.
- Incorpora la vista **Entidades** y una pestaña de menciones dentro de la revisión de cada objeto.
- Integra nombres canónicos, alias y menciones en la búsqueda FTS5 normal y por fragmentos.
- Integra autoridades, alias y menciones al hash de checkpoints y a los bundles offline.
- Valida cadenas internas de eventos que crean una autoridad y luego agregan alias dentro del mismo bundle.
- Agrega `authority-list`, `authority-create`, `authority-add-alias` y `mention-scan-object`.
- Migración `0021_entity_authorities`.
- 106 tests automatizados.

## 0.23.0 — 2026-07-24

- Agrega búsqueda por fragmentos internos de palabras mediante un índice FTS5 con tokenizador `trigram`.
- Mantiene separada la búsqueda normal por palabras completas para no cambiar sus resultados.
- Agrega un selector de archivos en Catálogo y copia los archivos elegidos a una ruta relativa configurable bajo `project_data`.
- Reutiliza el archivo ya copiado cuando coinciden nombre y SHA-256; evita sobrescribir contenidos distintos mediante sufijos.
- Explica en la interfaz las relaciones `represents`, `contains`, `is_part_of` y `alternate_representation`.
- Incorpora al intercambio offline la creación, edición y movimiento de unidades archivísticas.
- Incorpora vínculos entre unidades y objetos digitales, junto con sus metadatos verificables.
- No intercambia bytes ni rutas locales: la copia receptora crea el registro digital sin una instancia física.
- Integra el estado del catálogo al hash de checkpoints y al control de caducidad del dry-run.
- Agrega `--partial-words` a `search-editable`.
- Migración `0020_catalog_exchange_fragment_search`.
- 102 tests automatizados.

## 0.22.0 — 2026-07-24

- Agrega la vista **Catálogo** a la interfaz Streamlit.
- Permite crear unidades archivísticas y moverlas dentro de la jerarquía validada por `decisions.yaml`.
- Incorpora edición de título, código, estado de registro, confirmación manual y campos descriptivos configurables.
- Permite registrar unidades aunque no tengan archivo digital asociado.
- Busca por títulos, rutas jerárquicas, códigos, metadatos y nombres de archivo.
- Registra archivos locales por ruta relativa y deduplica objetos digitales mediante SHA-256.
- Crea o reutiliza una fuente procesable para que los archivos catalogados continúen por preprocesamiento, extracción, revisión y búsqueda.
- Permite reutilizar un objeto digital en varias unidades archivísticas.
- Muestra presencia local y progreso de preprocesamiento, extracción, selección y revisión.
- Agrega historial append-only de snapshots descriptivos.
- Agrega `catalog-tree` y `catalog-register-file`.
- Migración `0019_catalog_management`.
- 98 tests automatizados.

## 0.21.0 — 2026-07-24

- Reduce la resolución humana a los campos cuyo valor local difiere realmente del recibido.
- Reconoce automáticamente campos equivalentes aunque la base histórica sea incompleta o nula.
- Agrega resolución masiva por evento y por bundle mediante `exchange-resolve-event` y `exchange-resolve-all`.
- Hace idempotente `exchange-finalize-resolutions`: repetirlo informa que el bundle ya estaba finalizado.
- Separa en la auditoría los duplicados de las resoluciones que conservan explícitamente la versión local.
- Agrega la vista **Intercambio** a la interfaz Streamlit: carga, dry-run, comparación, resolución, finalización y aplicación con backup.
- Mantiene resolución individual con valores local, recibido o personalizado.
- Migración `0018_exchange_resolution_usability`.
- 92 tests automatizados.

## 0.20.0 — 2026-07-24

- Agrega resolución humana campo por campo para eventos `review` y `conflict`.
- Muestra valores base, local y recibido antes de decidir.
- Permite conservar el valor local, aceptar el recibido o ingresar un valor personalizado.
- Permite descartar explícitamente un evento completo.
- Persiste autor, fecha, nota y valores considerados por cada resolución.
- Invalida resoluciones cuando se repite el dry-run o cambia la copia local.
- Habilita `ready_to_apply_resolved` únicamente cuando todas las decisiones están completas.
- Integra las decisiones con la aplicación transaccional, backup y checkpoint posterior.
- Agrega `exchange-conflicts`, `exchange-resolve-field`, `exchange-skip-event`, `exchange-resolution-status` y `exchange-finalize-resolutions`.
- Migración `0017_exchange_conflict_resolutions`.
- 88 tests automatizados.

## 0.19.1 — 2026-07-23

- Corrige la aplicación de eventos de eliminación y restauración lógica de objetos.
- Los eventos nuevos de `delete` y `restore` registran únicamente el cambio de `lifecycle_status`.
- Normaliza bundles históricos que incluyan pares espurios de texto en esas operaciones.
- El dry-run compara las precondiciones con el estado canónico real antes de clasificar un evento como aplicable.
- Registra el hash y la secuencia local exactos evaluados por cada dry-run.
- Marca como `stale` las evaluaciones anteriores o invalidadas por cambios locales posteriores.
- Rechaza la aplicación de un dry-run caduco antes de crear el backup.
- Verifica que el SHA-256 y la representación semántica del bundle coincidan con la evaluación persistida.
- Migración `0016_exchange_delete_preconditions`.
- 84 tests automatizados.

## 0.19.0 — 2026-07-23

- Aplica bundles recibidos únicamente después de un dry-run `ready_to_apply`.
- Crea un backup SQLite verificable antes de toda aplicación.
- Bloquea eventos revisables o conflictivos y omite duplicados de forma auditada.
- Revalida las precondiciones de cada campo dentro de la transacción.
- Registra aplicaciones, eventos aplicados, duplicados, secuencias locales y checkpoint posterior.
- Genera reportes JSON y Markdown de aplicación.
- Enriquece los eventos futuros de creación de objetos con contexto de página.
- Agrega `exchange-apply-bundle` y `exchange-applications`.
- Migración `0015_exchange_transactional_apply`.
- 78 tests automatizados.

## 0.18.0 — 2026-07-23

- Agrega recepción controlada y dry-run de bundles sin modificar el estado editable.
- Compara la base declarada con checkpoints locales mediante SHA-256.
- Clasifica eventos como aplicables, duplicados, revisables o conflictivos.
- Detecta cambios equivalentes, campos superpuestos y borrado frente a actualización.
- Persiste evaluaciones y genera reportes JSON y Markdown.
- Agrega `exchange-dry-run`, `exchange-incoming` y `exchange-fork-copy`.
- `exchange-fork-copy` reidentifica una carpeta duplicada sin alterar OCR ni revisiones.
- Mantiene deshabilitada la aplicación automática de bundles.
- Migración `0014_exchange_dry_run`.
- 73 tests automatizados.

## 0.17.0 — 2026-07-23

- Inicia la Etapa 4 de intercambio offline.
- Agrega identidad estable por copia local mediante `exchange_workspaces`.
- Registra eventos append-only y secuenciales para revisiones editables, comentarios, etiquetas y estados de revisión.
- Agrega checkpoints con hash SHA-256 del estado editable actual.
- Exporta bundles ZIP con manifest versionado, `changes.jsonl`, checksums y firma lógica del contenido.
- Valida bundles sin aplicarlos y rechaza alteraciones, secuencias inválidas, contratos incorrectos y rutas inseguras.
- Agrega `exchange-init`, `exchange-status`, `exchange-checkpoint`, `exchange-checkpoints`, `exchange-export-bundle` y `exchange-inspect-bundle`.
- Cada exportación exitosa crea el checkpoint que servirá como próxima base incremental.
- La importación y combinación se mantienen deshabilitadas hasta incorporar dry run y reporte de conflictos.
- Migración `0013_offline_exchange_log`.
- 67 tests automatizados.

## 0.16.0 — 2026-07-23

- Agrega búsqueda transversal FTS5 sobre texto revisado, OCR original, comentarios y etiquetas.
- Incorpora modos de todas las palabras, cualquiera de las palabras y frase exacta.
- Permite filtrar por documento, tipo, estado del objeto, estado de la página, parte interna y categoría de etiqueta.
- Los resultados muestran el campo donde apareció la coincidencia y abren directamente el objeto en revisión.
- El índice derivado se invalida automáticamente mediante triggers y se reconstruye antes de buscar cuando existen cambios.
- Agrega `rebuild-search-index`, `search-index-status` y `search-editable`.
- Migración `0012_editable_search_fts`.
- 60 tests automatizados.

## 0.15.0 — 2026-07-23

- Corrige `StreamlitAPIException` al agregar etiquetas o comentarios: la selección se aplica en el rerun siguiente antes de instanciar el widget.
- Agrega categorías de etiquetas: temática, conceptual, flujo de trabajo y sin clasificar.
- Las etiquetas existentes se migran como `unclassified`, sin inferir retrospectivamente su categoría.
- Vincula objetos editables con partes internas de documentos multipágina.
- Permite asignación individual o conjunta por página, con revisión, historial y deshacer/rehacer.
- Las divisiones heredan la parte interna y las combinaciones entre partes diferentes se rechazan.
- Las exportaciones incluyen `document_part_id`, `document_part_key` y `tag_kind`.
- Migración `0011_editor_parts_tag_kinds`.
- 54 tests automatizados.

## 0.14.0 — 2026-07-23

- Conserva la caja seleccionada después de editar, mover, combinar, dividir o agregar objetos.
- Agrega deshacer y rehacer por acción completa de página mediante snapshots versionados.
- Deshacer y rehacer cubre ediciones, estados, reordenamientos, combinaciones, divisiones, altas y restauraciones.
- Mejora el visor: paneo por arrastre, zoom centrado en el cursor con Ctrl+rueda y conservación del punto de vista entre reruns.
- Agrega estados de revisión para páginas y objetos.
- Agrega etiquetas y comentarios append-only por objeto.
- Las exportaciones editables incluyen comentarios, etiquetas y estados de revisión.
- Migración `0010_review_actions_annotations`.
- 52 tests automatizados.

## 0.13.0 — 2026-07-23

- Cajas OCR clicables y sincronizadas con el selector mediante Custom Components v2 de Streamlit.
- Zoom, ajuste y desplazamiento sobre la página sin alterar los derivados.
- Operaciones estructurales versionadas: mover, dividir y combinar objetos adyacentes.
- Linaje explícito para divisiones y combinaciones; ninguna operación modifica el OCR original.
- Una división no inventa una geometría nueva: la segunda parte queda marcada como pendiente de caja.
- Fallback a la vista estática si la instalación de Streamlit no dispone de Components v2.
- 50 tests automatizados.
- No requiere migración; la revisión continúa en `0009_editable_objects`.

## 0.12.0 — 2026-07-23

- Primera interfaz local de revisión mediante Streamlit.
- Navegación por documento y página sobre la capa editable existente.
- Vista del derivado con cajas OCR numeradas y resaltado del objeto seleccionado.
- Edición versionada de texto y tipo, historial, reversión, eliminación lógica, restauración y alta manual.
- Comparación con el OCR original inmutable y advertencia de páginas desactualizadas.
- Exportación JSONL desde la interfaz.
- Nuevo comando `review-app`.
- `edit-object` valida UUID y `--text-file` antes de operar, sin mostrar tracebacks por archivos inexistentes.
- 48 tests automatizados.
- No requiere migración; la revisión continúa en `0009_editable_objects`.

## 0.11.0 — 2026-07-23

- Migración `0009_editable_objects`.
- Capa editable separada del OCR original e inicializada desde la selección por página.
- Historial append-only con control optimista mediante número de revisión.
- Corrección de texto y tipo, alta de objetos faltantes, eliminación lógica, restauración y reversión.
- Detección de páginas editables desactualizadas cuando cambia la selección OCR.
- Exportación del estado editable y todas sus revisiones a JSONL.
- Decisión formal de diferir la optimización OCR y evaluar Surya como backend independiente.
- 43 tests automatizados.

## 0.10.1 — hotfix: retiro de reconstrucción espacial regresiva

- Retira `spatial_rows` del contrato y del motor de extracción.
- Restaura los perfiles estables de documentos oficiales y páginas de libro a sus versiones `v1`.
- Restaura `leg_17_caso_bolson_plan_v2`.
- Conserva las corridas creadas con 0.10.0 como historial, pero no las selecciona automáticamente.
- La recomposición futura de renglones será una capa derivada, manualmente aprobada y nunca canónica por defecto.
- Agrega `restore-profile-pages`, que localiza por página la corrida histórica correcta aunque un perfil haya sido ejecutado en varios lotes.
- Mantiene el plan de evaluación futura de Surya como backend independiente.
- Total de tests: 41.
- No requiere migración; la revisión continúa en `0008_document_part_logical_order`.

## 0.10.0 — retirada por regresión

La reconstrucción espacial incorporada en esta versión mezcló renglones y bloques en páginas reales del corpus. No debe utilizarse como extracción seleccionada.

## 0.9.0 — orden lógico y primer plan multipágina ejecutable

- Agrega la migración `0008_document_part_logical_order`.
- Distingue páginas físicas de secuencia lógica en cada documento interno.
- Incorpora `page_sequence` con validación de cobertura, duplicados y pertenencia.
- Agrega el comando `document-parts`.
- Incluye un plan listo para las nueve páginas de `leg_17_caso_bolson`.
- Agrega perfiles para documentos oficiales degradados, páginas de libro y páginas dispersas/portadas.
- Total de tests: 39.

## 0.8.0 — planes multipágina y documentos internos

- Agrega la migración `0007_document_processing_plans`.
- Incorpora hojas de contacto paginadas desde los derivados de vista.
- Agrega planes YAML con partes documentales y asignaciones por página.
- Incorpora los modos `pending`, `ocr`, `regions`, `manual` y `skip`.
- Agrega `create-document-plan`, `render-contact-sheets`, `validate-document-plan`, `import-document-plan`, `benchmark-plan-sample`, `execute-document-plan` y `document-plan-status`.
- Valida cobertura completa, rangos, solapamientos, perfiles y plantillas regionales.
- Registra partes internas provisionales, versiones del plan y asignaciones en SQLite.
- Produce un manifiesto de ejecución y conserva la selección canónica por página.
- Total de tests: 36.

## 0.7.0 — extracción regional para formularios mixtos

- Agrega la migración `0006_region_extraction`.
- Incorpora plantillas YAML con cajas normalizadas por página.
- Agrega regiones `ocr` y `manual` con tipos de objeto archivístico.
- Incorpora `validate-region-template`, `render-regions`, `extract-regions` y `region-status`.
- Guarda un recorte PNG, salida cruda y procedencia por región.
- Registra `extraction_regions` en SQLite y exporta `regions.jsonl`.
- Permite combinar OCR de campos y texto mecanografiado con objetos manuales para sellos, manuscritos y texto vertical.
- Agrega una plantilla inicial para `leg_17_leg_15_a_c_6`.
- Total de tests: 32.

## 0.6.0 — selección por página y perfil de prensa

- Agrega la migración `0005_page_extraction_selection`.
- Incorpora selección canónica de extracción por página.
- Agrega `extraction-history`, `select-extraction` y `selected-extraction-status`.
- Incorpora `--selection-policy` en `extract`.
- Agrupa líneas de Tesseract en párrafos cuando el perfil lo indica.
- Agrega el perfil `tesseract_press_columns_es_v1`.
- Total de tests: 29.

## 0.5.0 — 2026-07-23

- Migración `0004_extraction_quality`, probada desde una base existente en `0003_extraction_objects`.
- Revisión humana de la extracción vigente: `unreviewed`, `accepted`, `rejected` o `needs_review`.
- Backend `tesseract_tsv` independiente de Docling, con texto por línea, confianza y bboxes.
- OCR directo sin detección automática de orientación para PSM 3/4/6/11.
- Variantes no destructivas: original, escala de grises con autocontraste y binarización Otsu.
- Comando `ocr-benchmark` que compara variantes y PSM sin cambiar la extracción vigente.
- Salidas de benchmark en TXT, TSV, PNG, JSON y Markdown.
- Puntaje heurístico explícitamente separado de una evaluación de exactitud con verdad terreno.
- Selección de perfil mediante `extract --profile`, con overrides `--psm` y `--image-variant`.
- 27 tests automatizados.

## 0.4.1 — 2026-07-23

- Diagnóstico real de CUDA/cuDNN mediante una convolución mínima en `extraction-doctor`.
- `--abort-on-error` en todas las ejecuciones de Docling.
- Fallback automático y único a CPU ante errores CUDA/cuDNN.
- Opción CLI `extract --device auto|cpu|cuda`.
- Conservación del comando, código de salida, stdout y stderr en `raw/docling.log`, incluso en fallos.
- Mensajes de error con el diagnóstico real en lugar de limitarse a “no produjo JSON”.
- 22 tests automatizados.

## 0.4.0 — 2026-07-23

- Migración Alembic `0003_extraction_objects` probada desde una base 0.3.0 existente.
- Perfil reproducible `config/extraction.yaml`.
- Diagnóstico de Docling, Tesseract, idioma OCR y aceleración disponible.
- OCR completo mediante una instancia de Docling por documento y Tesseract en español.
- Preservación del JSON crudo y logs por página.
- Normalización de orden de lectura, tipos de objeto, tablas, jerarquía y geometría.
- Exportación atómica de `objects.jsonl`, `paragraphs.jsonl` e `images.jsonl`.
- Corridas versionadas, parciales por página, reutilizables y marcadas como vigentes.
- Verificación SHA-256 de cada derivado OCR antes de extraer.
- Advertencias para páginas con reconocimiento textual mínimo, sin eliminar contenido.
- 20 tests automatizados.

## 0.3.0 — 2026-07-23

- Migración Alembic `0002_preprocessing_derivatives`.
- Corridas versionadas de preprocesamiento y activos derivados por página.
- PDF: PNG a 300 DPI para OCR y preview a 150 DPI.
- TIFF e imágenes: preservación de píxeles nativos para OCR y preview reducida.
- Backends PyMuPDF, Pillow y pyvips opcional.
- Manifiestos reproducibles con checksums, dimensiones, DPI, backend y advertencias.
- Reutilización de corridas equivalentes sin duplicar archivos.
- Rechazo seguro de originales modificados bajo una identidad SHA-256 anterior.
- Sin rotación automática de páginas apaisadas.
- 18 tests automatizados.

## 0.2.0 — 2026-07-23

- Primera base SQLite canónica.
- Migración Alembic `0001_initial_catalog`.
- Modelos SQLAlchemy para proyecto, unidades archivísticas, objetos digitales, copias locales,
  vínculos, procedencia y extracciones futuras.
- Registro idempotente del corpus de prueba.
- Deduplicación de objetos digitales mediante SHA-256.
- Verificación de copias presentes, faltantes y modificadas.
- Inventario textual inicial desde CLI.
- Las páginas apaisadas dejan de tratarse como posible error de orientación.
- 15 tests automatizados.

## 0.1.1 — 2026-07-23

- Decisiones archivísticas del proyecto incorporadas a `decisions.yaml`.
- Corpus inicial de cinco documentos.
- Estructuras configurables por fondo y estados explícitos de información faltante.

## 0.1.0 — 2026-07-22

- Contratos iniciales.
- Plantillas de decisiones y corpus.
- Identidad y JSONL atómico.
- Inspector preliminar de PDF/TIFF.
- Reglas iniciales de combinación.
- Documento maestro de diseño e implementación.
