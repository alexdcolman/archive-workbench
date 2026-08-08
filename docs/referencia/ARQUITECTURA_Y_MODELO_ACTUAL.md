# Arquitectura y modelo actual — Archive Workbench

Este documento describe el diseño vigente. El desarrollo histórico completo hasta 0.49.2 se conserva en `../historico/diseno/DISENO_Y_PLAN_DE_IMPLEMENTACION_HASTA_0.49.2.md`.

## Propósito

Archive Workbench organiza, procesa, revisa, busca y exporta documentación archivística digitalizada sin convertir resultados automáticos en decisiones humanas definitivas.

## Principios

1. Originales inmutables: los archivos fuente no se alteran.
2. SQLite local es la fuente de verdad de cada proyecto.
3. Derivados, OCR, transcripciones, índices y análisis son versionados o reconstruibles.
4. Las identidades son estables y no dependen del orden visual.
5. Toda escritura importante es explícita, auditable y transaccional.
6. Migraciones solo se ejecutan mediante `db-upgrade`.
7. Los backends automáticos producen candidatos revisables.
8. Las capas derivadas no sustituyen catálogo, texto revisado ni autoridades.
9. El intercambio entre copias requiere simulación, confirmación y backup.
10. Las extensiones opcionales no deben volver obligatorio un backend, nube o GPU.

## Componentes

### Catálogo

Describe fondos, colecciones, series, unidades, documentos, partes internas, objetos digitales, ubicaciones y metadatos configurables. Las entidades productoras y gestoras se vinculan a cada unidad mediante autoridades canónicas existentes y roles controlados, con período, evidencia, procedencia, estado e historial append-only; no se duplican como texto libre canónico. Un cambio de gestión crea otro vínculo temporal y conserva el anterior. Las plantillas XLSX de catálogo transportan instrucciones, una estructura jerárquica restringida, unidades y listas controladas. Pueden ser más estrictas que la configuración del proyecto, pero no ampliar padres permitidos. La importación siempre simula el libro completo, informa errores por ubicación y aplica únicamente con confirmación explícita dentro de una sola transacción.

### Archivos y derivados

Registra originales, checksums, copias locales y derivados de preparación. Cada transformación conserva procedencia, parámetros y archivo de origen.

El preprocesamiento geométrico trabaja únicamente sobre el derivado destinado a OCR. La previsualización de consulta y el original no reciben rotaciones, deskew ni limpieza. Por página se conservan un análisis estructurado, la secuencia exacta de transformaciones y, cuando corresponde, una máscara diagnóstica de los píxeles retirados. La orientación se limita a cuartos de giro; el deskew está acotado; y la eliminación de líneas exige controles conservadores para no borrar trazos que atraviesan texto. Una confianza insuficiente produce una omisión explicable, no una corrección silenciosa.

### Procesamiento

Ejecuta corridas por página mediante perfiles y backends. Las corridas se conservan, se evalúan y pueden seleccionarse por página sin borrar alternativas.

El OCR regional reutiliza la misma identidad de corrida y página. Una plantilla regional contiene cajas normalizadas, orden, modo `ocr` o `manual`, tipo de objeto y clasificación semántica. La interfaz visual puede cargar una plantilla o construirla mediante **Dibujar una zona** sobre la previsualización. La ejecución recorta cada zona y conserva el recorte, archivos crudos, `regions.jsonl` y manifiesto completo. Las zonas OCR pueden producir texto candidato; las zonas manuales crean candidatos visuales sin inventar texto. Toda corrida regional se crea con selección canónica desactivada y solo puede adoptarse posteriormente mediante la comparación normal por página.

### Revisión

Mantiene objetos editables con texto, tipo, orden, geometría, atributos, estado y revisiones append-only. Comentarios, etiquetas, menciones y relaciones se gestionan como capas vinculadas.

La estructura revisada de formularios pertenece a la página editable y no al resultado OCR. Los detectores producen candidatos sin autoridad canónica; una persona debe confirmar cada control, su estado y su rótulo. Los casilleros se anclan al menos a un objeto editable de marca o etiqueta, pueden agruparse mediante IDs estables y conservan evidencia, método candidato, responsable, fechas y ciclo de vida. Los grupos archivados permanecen en el snapshot histórico y sus controles activos quedan sin grupo. Cada cambio genera una revisión de página y participa en deshacer/rehacer, intercambio y adopción de estado.

La estructura revisada de layout también pertenece a la página editable. La detección geométrica propone columnas y un orden de lectura, pero no modifica `current_order_index` hasta una confirmación explícita. Las columnas tienen IDs estables y asignaciones de objetos; el orden canónico continúa en las revisiones de cada objeto. Fragmentaciones y duplicaciones son diagnósticos revisables: combinar o archivar exige una acción humana y conserva linaje, historial y reversibilidad.

### Búsqueda

La búsqueda literal usa índices reconstruibles. La búsqueda semántica utiliza perfiles con modelo, fragmentación, filtros y estado del corpus. Su calibración se ejecuta sin modificar la base: un corpus JSONL de consultas positivas, negativas y ambiguas se compara contra una revisión concreta del índice, se evalúan umbrales y se conservan métricas, falsos positivos, falsos negativos, parámetros y huellas reproducibles. Las comparaciones solo aceptan informes del mismo corpus y tipo de fragmento; cualquier umbral recomendado queda limitado al corpus, perfil, modelo, revisión de índice y grilla evaluada.

### Autoridades y grafo

Separa autoridad canónica, alias y menciones contextuales. Una grafía coincidente no implica identidad automática. Las relaciones se clasifican como analíticas, productoras o gestoras. Los roles archivísticos solo pueden apuntar a unidades y exigen evidencia y procedencia; las relaciones anteriores permanecen como `analytical`.

El grafo distingue autoridades, unidades archivísticas, objetos digitales y partes documentales. Las capas de jerarquía, pertenencia de documentos, partes, menciones, relaciones analíticas, productores y gestores pueden filtrarse de manera independiente. Cada arista explica la tabla o registro del que procede, por lo que una pertenencia archivística nunca se presenta como relación analítica. El foco puede partir de cualquiera de los cuatro tipos de nodo y limitar profundidad, niveles y cantidad de elementos. El canvas sigue siendo una proyección de lectura: separa de forma determinista relaciones paralelas o inversas, recalcula rutas y etiquetas al mover nodos y conserva tooltips de tipo, dirección, procedencia y evidencia. Cambiar el layout visual no escribe relaciones ni altera el modelo canónico.

Los diccionarios externos usan un contrato JSON versionado. La simulación resuelve cada autoridad como creación, reutilización, omisión o conflicto; compara nombres y alias normalizados y nunca actualiza silenciosamente una ficha existente. Las características externas se conservan como descripción estructurada solo al crear una autoridad nueva. Los alias ambiguos requieren autorización expresa. Cada relación importada exige evidencia y puede apuntar a una autoridad, unidad archivística o parte documental existente. Autoridades, alias y relaciones se aplican dentro de una sola transacción. El formato vigente está en [`IMPORTACION_DICCIONARIOS_DISC_02.md`](IMPORTACION_DICCIONARIOS_DISC_02.md).

### Exportación

Los perfiles seleccionan contenido, agrupación, filtros y formato. Cada materialización registra ruta, tamaño, hash y estado del corpus.

### Descubrimiento abierto

Los perfiles autorizados producen corridas inmutables y candidatos con texto exacto, offsets, revisión textual, familia semántica, método y procedencia. Las decisiones humanas se registran por separado y son append-only. Los grupos reúnen candidatos repetidos sin fusionar sus filas: cada pertenencia conserva corrida, documento, offsets y estado. Las acciones de grupo registran creación, incorporación, restauración y separación. Cuando una edición vuelve obsoleto un candidato, la continuidad crea un candidato nuevo sobre la revisión vigente y mantiene visible el snapshot histórico. La evaluación usa corpus JSONL con verdad terreno, métricas por familia e informes con huellas reproducibles. Los proveedores opcionales comparten el mismo contrato y fijan versión, método y modelo sin declararse superiores por defecto.

### Intercambio offline

Los eventos se exportan desde un punto de control. La copia receptora inspecciona y simula antes de aplicar. Los hashes de estado no sustituyen la ascendencia de eventos. Cuando una base no puede reconocerse, el diagnóstico de `EX-01A` permanece de solo lectura; `EX-01B` puede registrar una recuperación append-only únicamente ante evidencia concluyente y única. Esa decisión invalida la simulación anterior, y la siguiente reevaluación identifica el método `recovered_lineage`. Cuando dos copias distintas ya tienen exactamente el mismo estado editable, `EX-01C` permite registrar bilateralmente una nueva base común mediante propuesta, aceptación y finalización verificables; los paquetes posteriores pueden reconocerla mediante `common_base_agreement`. Cuando los estados divergen, `EX-01D` permite crear un paquete completo dirigido, previsualizar su impacto, respaldar la copia destinataria, adoptar el estado transaccionalmente o restaurar el backup previo. La adopción no crea parentesco: el acuerdo bilateral se registra recién después de comprobar hashes idénticos. La planificación completa está en [`RECUPERACION_LINAJE_EX_01.md`](RECUPERACION_LINAJE_EX_01.md).

### Backups

Los backups incluyen manifiesto, base y configuración. La restauración crea primero una copia de seguridad y requiere migración explícita si la versión de esquema lo necesita.

## Modelo de identidad

- Proyecto: identidad estable del corpus.
- Copia de trabajo: identidad propia para intercambio.
- Unidad archivística: identidad estable independiente de ruta o título.
- Objeto digital: archivo intelectual registrado.
- Instancia local: copia física concreta.
- Derivado de preparación: previsualización intacta, imagen OCR tratada o máscara diagnóstica, vinculada a una corrida y página.
- Corrida de extracción: ejecución versionada.
- Página extraída y objeto extraído: candidatos automáticos.
- Página editable y objeto editable: estado humano activo e historial.
- Estructura de formulario: snapshot coherente por página con grupos y casilleros de IDs estables, estados controlados, anclajes editables, evidencia y ciclo de vida.
- Estructura de layout: columnas estables y asignaciones revisadas por página; el orden canónico se conserva en las revisiones de objetos.
- Autoridad: identidad canónica revisada.
- Mención: fragmento contextual con offsets, revisión textual y snapshots append-only.
- Relación: vínculo controlado `analytical`, `producer` o `manager` con destino tipado, evidencia, procedencia, temporalidad, estado e historial.
- Perfil de exportación o búsqueda: configuración versionada.
- Autorización de análisis automático: registro append-only del alcance, responsable, fundamento, origen, destino y hash de parámetros.
- Punto de control y paquete de intercambio: ascendencia y transporte de eventos.
- Caso, evidencia y decisión de recuperación de linaje: auditoría append-only separada del contenido y de las aplicaciones de paquetes.
- Acuerdo bilateral de base común: mismo identificador y manifiesto en ambas copias, con puntos de control locales propios.
- Adopción y rollback de estado: sustitución explícita respaldada y reversible, separada del acuerdo de parentesco.
- Perfil, corrida y candidato de descubrimiento: configuración autorizada, ejecución reproducible y snapshot textual revisable.
- Decisión y registro propio de descubrimiento: juicio humano append-only y datos específicos por familia.
- Grupo, pertenencia y acción de descubrimiento: deduplicación explícita sin fusionar procedencias.
- Continuidad de candidato: vínculo entre un snapshot obsoleto y uno nuevo sobre la revisión vigente.
- Corpus e informe de evaluación de descubrimiento: verdad terreno y comparación reproducible por proveedor, versión y parámetros.
- Corpus e informe de calibración semántica: consultas verificadas, métricas por umbral y comparación reproducible por perfil, modelo, revisión de índice y parámetros.
- Plantilla distribuible de catálogo: contrato XLSX versionado con estructura, unidades, campos, listas y procedencia, sin identidad canónica propia fuera de las unidades importadas.
- Diccionario distribuible de autoridades: contrato JSON versionado con identidad de fuente, autoridades locales, alias, resoluciones y relaciones; no es una autoridad canónica por sí mismo.
- Layout del grafo: proyección visual reconstruible sin identidad ni persistencia propias.

## Reglas de seguridad

- No borrar originales ni corridas históricas.
- Usar baja lógica cuando el historial deba conservarse.
- No aceptar una mención sin autoridad.
- Una mención histórica aceptada o modificada que perdió su autoridad solo puede vincularse a una entidad activa existente o volver a estado pendiente mediante una revisión explícita.
- Una mención desactualizada solo puede reubicarse automáticamente cuando la proyección al texto vigente es única, no colisiona con otra mención activa y la fila coincide con su último snapshot.
- Si una fila diverge de su último snapshot, la persona revisora debe comparar ambos estados y elegir cuál conservar. Restaurar el snapshot exige registrar primero la fila divergente como evidencia.
- Toda reparación de mención agrega una revisión nueva; los snapshots anteriores no se reescriben.
- No fusionar autoridades automáticamente.
- Los candidatos de descubrimiento abierto son sugerencias históricas, no registros canónicos.
- Toda decisión sobre un candidato es append-only y debe comprobar la revisión textual vigente.
- Una autoridad creada desde descubrimiento abierto queda `unreviewed`; ninguna aceptación crea relaciones automáticamente.
- Tiempos, acontecimientos y acciones o procesos conservan registros propios y no se reducen silenciosamente a autoridades.
- Agrupar candidatos no fusiona filas, no copia decisiones y no elimina procedencias.
- Una separación manual conserva el historial y no puede ser revertida por una reconstrucción automática.
- La continuidad textual crea un candidato nuevo; el candidato obsoleto permanece visible y no recibe decisiones nuevas.
- No trasladar anotaciones por similitud ambigua.
- Un candidato de casillero no es una decisión: el estado y la agrupación solo se vuelven revisados mediante confirmación explícita.
- Una propuesta de columnas, orden, fragmentación o duplicación no modifica la capa editable hasta una confirmación explícita.
- Una corrida de OCR regional no modifica la selección canónica ni la capa editable. Una región manual no inventa transcripción: conserva geometría y recorte para revisión humana posterior.
- Dar de alta un casillero visible sin marca OCR exige anclarlo a un objeto editable existente y registrar evidencia; no se inventan trazos ni objetos extraídos.
- No aplicar un paquete con simulación obsoleta.
- Resolver contenido de un paquete sin base común no crea linaje.
- Recuperar linaje exige una cadena concluyente única, responsable, fundamento y confirmación; no aplica eventos de contenido.
- Toda recuperación vuelve obsoleta la simulación anterior y obliga a reevaluar el paquete.
- Adoptar un estado divergente exige paquete íntegro dirigido, backup previo, responsable, fundamento, confirmación e integridad válida.
- Una adopción de estado no activa una base común; ambas copias deben registrar después el acuerdo bilateral.
- El rollback de una adopción se bloquea si el estado cambió después o si un acuerdo bilateral ya depende del estado adoptado.
- Una plantilla de catálogo no puede ampliar la jerarquía autorizada por el proyecto; la aplicación exige simulación válida y confirmación explícita.
- Un diccionario externo no puede sobrescribir autoridades existentes ni crear relaciones sin evidencia; los conflictos exigen resolución explícita y toda aplicación es transaccional.
- No sobrescribir exportaciones salvo confirmación explícita.
- No ejecutar escrituras mediante `Enter`.

## Calidad

Los estados de página controlan qué contenido puede alimentar búsquedas, exportaciones y análisis. El alcance predeterminado para toda automatización es únicamente contenido aprobado. Incluir otros estados exige confirmación explícita, responsable, fundamento y una fila append-only en `automatic_analysis_authorizations`. Los tipos de análisis deben estar registrados en la política común; una integración futura no puede inventar una ruta paralela sin este contrato.

## Extensiones previstas

Las extensiones abiertas se describen únicamente en `../operativos/PENDIENTES_ACTIVOS.md`. El diseño vigente de descubrimiento abierto está en `DESCUBRIMIENTO_ABIERTO_DISC_01.md`; entre las extensiones restantes se encuentran incorporación remota audiovisual, herramientas LLM, RAG, Docker y transporte mediante Drive.

Cada extensión debe respetar los mismos contratos de identidad, procedencia, calidad, revisión y auditoría.

## Dewarp conservador de derivados OCR

`OCR-01E` agrega el modo `conservative_dewarp` al perfil de preparación. La estimación trabaja sobre una copia reducida, divide la página en franjas verticales y compara perfiles horizontales de tinta para estimar desplazamientos relativos. Los puntos con soporte se ajustan mediante una curva cuadrática.

La corrección solo se aplica cuando la curva tiene amplitud suficiente y acotada, soporte textual mayoritario, calidad de ajuste estable y confianza superior al umbral. El remapeo mueve píxeles mediante una malla vertical suave; no reconstruye caracteres, perspectiva, pliegues locales ni contenido faltante. El original y la previsualización permanecen intactos.

La decisión queda en `analysis_json` y `transformations_json`. El activo `dewarp_diagnostic` muestra la curva estimada y se conserva separado de `diagnostic_mask`, que continúa representando las líneas eliminadas. El modelo vigente de `DerivativeAsset` admite ambos tipos sin migración.

## Proyectos y extensiones planificados

`AV-01` está implementado, validado y cerrado en 0.84.0. La versión 0.85.0 agrega y cierra `AV-02` sin migración: una extensión opcional de incorporación desde plataformas descarga el material autorizado, lo registra por el mismo circuito local y conserva su procedencia remota dentro de `SourceRegistration.source_payload_json`. `DigitalObject`, `FileInstance` y `SourceRegistration` siguen siendo la identidad del original; `AudiovisualMedia` agrega metadatos descriptivos y técnicos sin duplicar el archivo. `AudiovisualDerivativeAsset` conserva derivados reproducibles de FFmpeg. `TranscriptionRun` registra backend, versión, modelo, dispositivo y opciones; `TranscriptSegment` conserva tiempo y texto vigente, y `TranscriptSegmentRevision` su historial append-only. `SegmentEntityMention` vincula evidencia textual con las autoridades canónicas existentes. La base audiovisual original se introdujo en `0045_audiovisual_transcription`. `AV-03` agrega en `0046_audiovisual_timeline_annotations` una capa independiente de la corrida: `AudiovisualTimelineAnnotation` registra hablantes o anotaciones con intervalo temporal y autoridad opcional, y `AudiovisualTimelineAnnotationRevision` conserva su historial append-only. La RC6 mantiene ese esquema y cambia únicamente la interacción: un componente Streamlit v2 acompaña el tiempo del reproductor en el navegador, resalta la transcripción vigente y envía al backend sólo acciones discretas de hablante/anotación. Los turnos de hablante se abren desde la posición actual y el turno anterior se cierra automáticamente; las notas toman el tramo textual vigente.

La UI se encuentra en **Transcribir audio y video** y no reutiliza las tablas ni la pantalla page-centric de OCR. Integra audio/video, salto al segmento y reproducción con velocidades configurables; la corrección queda visible y las opciones técnicas permanecen cerradas por defecto. Búsqueda y exportación tratan el segmento como unidad temporal. Cuando existe estado audiovisual, la adopción de estado usa contrato 1.1; sin contenido AV se conserva la huella histórica anterior. `AV-02` es un plugin opcional de incorporación autorizada desde plataformas y entrega sus archivos al mismo circuito local; no define un segundo modelo de transcripción. `AV-03`, cerrado en 0.86.0, evaluó sobre video real ese mismo circuito sin crear un modelo paralelo: preserva una línea de base portable `small` + CPU y registra `large-v3` + CUDA como el perfil cualitativamente superior en la prueba realizada, con mayor coste y revisión humana todavía necesaria.

`EXP-01` quedó implementado, validado y cerrado en 0.88.0. **Exportar texto e imágenes (ZIP)** materializa los registros del perfil, imágenes de página ancladas a `EditablePage.source_extraction_page_id`, recortes regionales y figuras recortadas desde `current_geometry_json`. `manifest.json` conserva huellas, procedencia, revisión y vínculos con registros. El contexto textual adicional se guarda separado por objeto, página y documento, marcando qué objetos pertenecen al contenido principal. La validación final confirmó una exportación con 1 registro principal, 1 página, 1 recorte regional, 1 figura y 2 objetos de contexto, con huellas válidas y originales intactos. La etapa `vision_describe` se diseñará en `AI-01` y consumirá este paquete sin acceder directamente a originales ni a SQLite.

`GIAR-01` usará un proyecto separado y persistente de Archive Workbench como base estructurada para investigadores, publicaciones, entidades, relaciones, conceptos y referencias archivísticas. El alcance se encuentra en [`PROYECTO_PARALELO_GIAR.md`](PROYECTO_PARALELO_GIAR.md). Todavía no forma parte del esquema vigente y cualquier ampliación se diseñará antes de crear tablas nuevas.

## Benchmark OCR con verdad terreno

`OCR-01F` mantiene la evaluación fuera de la selección canónica. La verdad terreno vive por `source_key` y página, cada corrida conserva una copia y su SHA-256, y Tesseract, Docling y Surya reciben el mismo derivado OCR vigente. CER/WER se calculan sobre una normalización declarada en el perfil; los textos, salidas crudas, logs, versiones y tiempos permanecen trazables. El benchmark no aplica fallback entre motores ni declara automáticamente un backend universalmente preferido.


### Transporte opcional por Google Drive — INT-01

La versión 0.87.0 agrega una capa de transporte sobre el intercambio existente. `google_drive_transport.py` no define persistencia canónica nueva ni abre bases remotas: valida un paquete ZIP con `inspect_change_bundle`, lo sube mediante la API de Drive y conserva como propiedades del archivo el SHA-256, `bundle_id` y `project_id`. Para recepción, Google Picker limita la selección a un archivo concreto con el permiso `drive.file`; el ZIP se descarga de forma atómica a `exchange/drive_downloads/`, se verifica localmente y se compara su manifiesto con el proyecto, la identidad de la copia, la revisión de base y la base común conocida.

La comparación previa es informativa y no sustituye `dry_run_change_bundle`. Sólo después de una descarga válida la interfaz habilita la misma simulación persistente usada por el intercambio local. Aplicación, resolución de conflictos, backups y linaje siguen regidos por el subsistema de intercambio existente. Las credenciales OAuth y el token se guardan fuera del proyecto, bajo la configuración local del usuario; esta función no sube ni descarga `project_data` ni ninguna SQLite. INT-01 no agrega migraciones y mantiene la revisión `0046_audiovisual_timeline_annotations`. La validación real de 0.87.0 confirmó OAuth, subida, Picker, descarga con SHA-256 idéntico, comparación de manifiesto y dry-run `empty/matched` entre dos copias descartables, con `project_data` fuera del recorrido. `INT-01` queda cerrado.

### Anotaciones temporales audiovisuales

Las marcas `speaker` y `annotation` pertenecen a `AudiovisualMedia`, no a `TranscriptionRun`. Pueden usar segmentos como referencia de captura, pero persisten `start_time` y `end_time` propios y sobreviven a una nueva transcripción. Los hablantes pueden permanecer provisionales o vincularse a `AuthorityRecord`; las anotaciones libres describen eventos observables sin mezclarse con el texto transcripto. La vista integrada es derivada. La adopción de estado usa esquema 1.2 cuando existen estas secciones y mantiene compatibilidad con paquetes 1.0/1.1 cuando no hay marcas temporales.

### Evaluación audiovisual AV-03

AV-03 reutiliza `TranscriptionRun` y `TranscriptSegment`; la única migración del bloque es `0046_audiovisual_timeline_annotations`. Las métricas de ejecución derivadas se guardan bajo la clave reservada `_runtime_metrics` dentro de `TranscriptionRun.options_json`; el estado audiovisual transportable ya incluye ese JSON. `transcription_evaluation.py` calcula informes derivados de rendimiento, segmentación y carga de corrección humana sin crear una segunda capa canónica. Para evaluar reconocimiento, la hipótesis es siempre `TranscriptSegment.original_text`; `corrected_text` se usa únicamente como referencia humana. CER/WER se calculan sólo cuando las fronteras temporales de la hipótesis coinciden con las ventanas humanas revisadas. Si otra corrida usa fronteras distintas y no existen timestamps por palabra, se conserva y muestra el contexto original de todos los segmentos temporalmente solapados, pero no se fabrica una puntuación recortando el candidato con ayuda del texto humano. Las salidas automáticas completas acompañan siempre la comparación. La interfaz muestra **Corrida** solo cuando existen varias y mantiene **Evaluar transcripción** cerrado por defecto. La validación final de 0.86.0 concluyó cualitativamente que el perfil probado `large-v3` + CUDA `float16` supera a `small` + CPU `int8` en este material, sin convertir esa observación de un único medio en un cambio automático del perfil general.
