# Implementaciones realizadas — Archive Workbench

**Estado preparado:** 2026-08-07 · **versión:** 0.82.0

Este documento registra capacidades ya implementadas y, cuando corresponde, validadas. No deben volver a aparecer en `PENDIENTES_ACTIVOS.md` salvo evidencia de regresión o ampliación explícita del alcance.

## Índice de capacidades implementadas

| Área | Estado actual |
|---|---|
| Catálogo, originales y estructura archivística | Implementado |
| Extracciones versionadas y selección canónica | Implementado y validado |
| Revisión, historial y rebase | Implementado y validado |
| Calidad de página y derivados OCR | Implementación parcial; OCR-01A/B/C/D/E cerradas, queda el benchmark ampliado |
| Búsqueda literal y semántica | Implementado; calibración reproducible cerrada en 0.74.0 |
| Autoridades, menciones y relaciones | Núcleo implementado y validado |
| Exportaciones reproducibles | Implementado y validado |
| Backups y restauración | Implementado y validado |
| Intercambio offline | Implementado y validado; EX-01 cerrado en 0.68.1 |
| Política de formularios explícitos | Implementada y validada |
| Simplificación general de interfaz y léxico | Implementada y validada en 0.56.0 |
| Reparación auditable de menciones históricas | Implementada y validada en 0.62.1 |
| Política auditable de análisis automáticos | Implementada y validada en 0.64.1 |
| Organización documental | Implementada en 0.50.0 |
| Descubrimiento abierto DISC-01A–D | Implementado y validado en 0.73.0 |
| Reformulación UX-03 de Entidades y descubrimiento | Implementada y validada en 0.72.0 |
| Calibración semántica SEM-01 | Implementada y validada en 0.74.0 |
| Grafo sin colisiones GRAPH-01 | Implementado y validado en 0.74.0 |
| Duplicados OCR-02 | Cerrado por decisión de alcance en 0.74.0 |
| Plantillas distribuibles CAT-01 | Implementadas y validadas en 0.75.1 |
| Diccionarios de autoridades DISC-02 | Implementados y validados en 0.76.0 |
| Productores y gestores CAT-02 | Implementados y validados en 0.77.0 |
| Capas archivísticas GRAPH-02 | Implementadas y validadas en 0.77.0 |

## Preprocesamiento geométrico para OCR

### OCR-01E — Dewarp conservador — 0.82.0

El nuevo modo `conservative_dewarp` extiende la preparación geométrica con una estimación de curvatura vertical suave. Divide la página en franjas, compara perfiles de tinta, ajusta una curva cuadrática y aplica una malla reproducible únicamente al derivado OCR. La decisión exige soporte suficiente, desplazamiento acotado, ajuste estable y confianza superior al umbral.

Cada página conserva `dewarp_detected`, `dewarp_applied`, confianza, desplazamiento máximo, franjas con soporte, calidad de ajuste, coeficientes y motivo. Se genera un activo `dewarp_diagnostic` separado de la máscara de líneas. La previsualización y el original permanecen intactos. No requiere migración.

**Estado:** implementada, validada y cerrada en 0.82.0. La validación específica de navegación confirmó que documentos y opciones permanecen seleccionados al abrir y recorrer el diagnóstico geométrico.

### OCR-01D — OCR regional visual y zonas documentales — 0.81.0

La extracción regional versionada ya disponible por CLI se integra en **Procesar documentos > OCR regional** mediante un recorrido lineal de seis pasos. La persona elige documento y página, ve la página preparada, carga una plantilla o dibuja zonas, las describe con una clasificación controlada y decide si cada una se procesa por OCR o queda como región manual. Las opciones técnicas de Tesseract permanecen bajo un panel avanzado.

Cada corrida conserva cajas normalizadas, orden, modo, tipo de objeto, clasificación semántica, recortes, resultados crudos, `regions.jsonl` y manifiesto. Se ejecuta con `selection_policy=never`: no cambia la selección canónica ni la capa editable. Una región manual conserva imagen y geometría para revisión posterior y no inventa una transcripción. No agrega migraciones; continúa sobre `0044_layout_structure_review`.

**Validada manualmente en 0.81.0.** La prueba confirmó una corrida terminada con seis zonas, tres regiones OCR y tres manuales, seis recortes, al menos un objeto por zona, clasificación semántica correcta, selección canónica vacía, contrato regional 1.1 e integridad del PDF original. `OCR-01D` queda cerrada.

### OCR-01C — columnas y orden de lectura revisables — 0.80.0

La capa editable calcula una propuesta no canónica de columnas a partir de geometrías normalizadas, muestra el orden sugerido sobre la página y conserva sin cambios el orden vigente hasta una confirmación explícita. La confirmación crea columnas estables, aplica el orden mediante revisiones de objeto y permite reasignación manual, creación, renombrado y archivo de columnas.

El mismo diagnóstico señala secuencias posiblemente fragmentadas y objetos posiblemente duplicados. Ninguna candidata se corrige sola: combinar o archivar exige una acción humana y participa en historial, deshacer/rehacer e intercambio. La migración `0044_layout_structure_review` agrega `layout_structure_json` a páginas y revisiones; la exportación incorpora `layout_structures.jsonl` y manifiesto 1.4.

**Validada manualmente en 0.80.0.** La base controlada confirmó tres columnas activas —`Columna 1`, `Columna 2` y `Margen derecho`—, cinco objetos editables activos, cero fragmentaciones o duplicaciones pendientes, orden vigente coincidente con la propuesta, historial específico con confirmación, renombrado, combinación, archivo, deshacer y rehacer, y exportación `layout_structures.jsonl` con manifiesto 1.4. El PDF conservó su SHA-256 y los siete objetos OCR de origen permanecieron intactos. Durante la validación se corrigieron la ausencia de imagen cuando no había preview, un acceso inválido a `ReviewPageView.page_number`, la ambigüedad entre **Historial general** y el historial específico de layout, y el guiado de las acciones nuevas. `OCR-01C` queda cerrada; la revisión integral de densidad y comprensión de **Orden y estructura** permanece registrada en `UX-02`.


### OCR-01B — formularios y casilleros revisables — 0.79.0

Los indicadores automáticos de casilleros siguen siendo candidatos no canónicos. La capa editable permite confirmarlos de forma explícita, asignar los estados controlados `marked`, `unmarked` o `indeterminate`, corregir rótulos, vincular la marca y el texto a objetos editables y registrar evidencia. Un casillero visible que no fue representado por OCR puede darse de alta manualmente sin inventar un objeto extraído ni modificar la imagen.

Los controles pueden agruparse mediante identificadores persistentes dentro de cada página. Crear, renombrar o archivar un grupo y confirmar, corregir o archivar un control conserva snapshots append-only en las revisiones de página. Archivar un grupo no elimina sus controles: los desvincula y conserva tanto la agrupación histórica como las confirmaciones. Las acciones participan en deshacer/rehacer, intercambio offline y adopción de estado. La exportación editable incorpora `form_structures.jsonl` y el manifiesto 1.3.

La migración aditiva `0043_form_structure_review` agrega `form_structure_json` a `editable_pages` y `editable_page_revisions`. La estructura se valida como una unidad coherente, con IDs únicos y referencias de grupo válidas; las páginas anteriores reciben objetos vacíos. `create_form_structure_validation_project.py` genera una ficha controlada con candidatos marcados y no marcados, un vínculo por proximidad y un casillero visible para alta manual.

**Validada manualmente en 0.79.0.** Se confirmaron grupos, controles, historial, deshacer/rehacer, exportación, SHA-256 del original y ausencia de acceso a `project_data`. Durante la prueba se detectó que acciones renderizadas antes del bloque de pestañas podían hacer volver la interfaz a **Editar texto**; la RC2 agregó una copia durable de la pestaña activa y la validación posterior confirmó que deshacer, rehacer, exportar y las demás acciones conservan la subsección activa. `OCR-01B` queda cerrada; `OCR-01` continúa parcial por los alcances restantes. La simplificación integral de **Formulario** y una referencia visual persistente de la página quedan programadas en `UX-02`.

### OCR-01A — orientación, deskew y líneas controladas — 0.78.0

La preparación de páginas incorpora un modo geométrico conservador que detecta orientaciones de `0°`, `90°`, `180°` y `270°`, aplica deskew dentro de un rango acotado y elimina únicamente líneas o marcos largos que superan los controles de longitud, espesor e intersección con texto. Una confianza insuficiente no modifica la página: la omisión queda registrada como advertencia y transformación no aplicada.

El original y la previsualización permanecen intactos. El tratamiento produce un derivado OCR separado, una máscara diagnóstica de los píxeles eliminados y metadatos estructurados por página con orientación, confianzas, rotación, ángulo de deskew, líneas detectadas, líneas eliminadas y transformaciones aplicadas u omitidas. La interfaz compara en paralelo la previsualización sin cambios, el derivado OCR y la máscara.

La migración aditiva `0042_preprocessing_geometry_trace` agrega `analysis_json` y `transformations_json` a `derivative_assets`. No reconstruye la tabla ni altera derivados anteriores; los registros existentes reciben objetos vacíos. El script `create_preprocessing_geometry_validation_project.py` crea fuera del repositorio cinco casos controlados: orientación a 90°, inclinación de 3°, marco y líneas largas, línea que cruza texto y página de baja confianza.

**Validada manualmente en 0.78.0.** Se confirmaron la rotación controlada de `90°`, el deskew de `-3°`, la eliminación exclusiva de cuatro líneas de marco, la conservación de una línea que cruza texto, la omisión por baja confianza y la presencia de candidato, confianza, umbral y motivo en cada transformación. Los cinco originales conservaron sus SHA-256, ninguna extracción fue adoptada automáticamente como canónica y `project_data` no fue leído ni modificado durante la prueba. `OCR-01A` queda cerrada; `OCR-01` continúa parcial por los alcances restantes.

## Productores, gestores y estructura documental en el grafo

### CAT-02 + GRAPH-02 — implementación conjunta — 0.77.0

Las entidades productoras y gestoras se registran como relaciones controladas `producer` y `manager` entre una autoridad canónica existente y una unidad archivística. Cada vínculo conserva período, evidencia, procedencia, revisión humana, ciclo de vida e historial append-only. Las etiquetas visibles `produjo` y `gestionó` se generan desde el tipo controlado y no se admiten como nombres libres canónicos. Una misma autoridad puede ocupar roles distintos en unidades o períodos diferentes; un cambio de gestión crea otro vínculo y no reescribe el anterior.

La migración `0041_catalog_authority_roles_graph_layers` agrega `relation_kind` y `provenance_note` de manera aditiva. Las relaciones anteriores quedan clasificadas como `analytical`. Los triggers de SQLite impiden roles sin unidad archivística, evidencia, procedencia o etiqueta canónica, y el intercambio offline conserva todos los campos nuevos.

El grafo distingue nodos de autoridad, unidad archivística, objeto digital y parte documental. Sus capas separan jerarquía, pertenencia de documentos, partes internas, menciones, relaciones analíticas, productores, gestores y la capa derivada de entidades compartidas ya existente. La vista permite filtrar niveles, elegir cualquiera de los cuatro tipos de nodo como foco, limitar profundidad y cantidad de nodos, y mostrar la procedencia explicable de cada arista. Las aristas dirigidas terminan en una flecha visible, mientras que la capa simétrica de entidades compartidas permanece sin flecha. La distancia queda siempre disponible y solo se aplica cuando hay un foco. Las relaciones entre objeto digital y unidad siguen la dirección del contrato catalográfico y usan etiquetas legibles en español. JSON, CSV y GraphML conservan el tipo de vínculo, la explicación y la procedencia; las fechas se serializan en ISO.

La validación automatizada creó una base descartable fuera del repositorio en revisión `0041_catalog_authority_roles_graph_layers`, produjo las siete capas requeridas, los cuatro tipos de nodo y cero errores de consistencia. **Validado manualmente en 0.77.0.** Se confirmaron los roles y períodos históricos, el historial append-only, las siete capas, el foco y la distancia, las flechas dirigidas, la pertenencia documental `objeto digital → unidad archivística` y las exportaciones JSON, CSV y GraphML. El JSON final registró nueve nodos, doce aristas, cero inconsistencias y ningún truncamiento. `CAT-02` y `GRAPH-02` quedan cerrados.

## Plantillas distribuibles de catálogo

### CAT-01 — exportación, simulación e importación XLSX — 0.75.0

**Corrección 0.75.1.** El formulario ya no deshabilita el botón según un campo escrito dentro del mismo `st.form`: el botón se envía habilitado y luego comprueba la confirmación exacta `IMPORTAR`. La hoja `LISTAS` continúa oculta porque funciona como soporte de los desplegables y no requiere edición ordinaria. El proyecto descartable usa ahora la identidad neutral `Proyecto de validación CAT-01`.

Se incorporó un formato XLSX versionado con cuatro hojas: `INSTRUCCIONES` documenta el contrato y cada campo; `ESTRUCTURA` declara niveles y padres permitidos; `CATALOGO` contiene las unidades y sus valores descriptivos; y `LISTAS` alimenta controles de valores válidos. La plantilla puede exportarse vacía o con el catálogo vigente desde la interfaz y mediante `catalog-template-export`.

La estructura transportada puede restringir los padres admitidos por el proyecto, pero nunca ampliarlos. La simulación mediante `catalog-template-validate` comprueba el esquema, IDs locales y persistentes, padres inexistentes, ciclos, niveles desconocidos, transiciones jerárquicas, campos aplicables, tipos, estados y confirmaciones de completitud. Los errores conservan hoja, fila, columna y código.

La aplicación requiere `--apply --confirm IMPORTAR` en la CLI o la misma confirmación explícita en la interfaz. Primero valida el libro completo y después crea, actualiza, mueve u omite unidades dentro de una sola transacción. Las escrituras usan las operaciones canónicas del catálogo, conservan historial de revisiones y no generan una actualización nueva cuando una exportación se reimporta sin cambios. La URL y la nota de procedencia de cada fila quedan incorporadas a la revisión y, cuando corresponde, a la procedencia del campo descriptivo.

Se incluye `examples/plantilla_catalogo_dippba.xlsx`, generada desde `config/catalog_templates/dippba_public_seed.json`. Contiene 155 filas trazables obtenidas de información pública de la Comisión Provincial por la Memoria. Las elipsis y los agrupamientos sin nivel rotulado se señalan expresamente como parciales o provisionales; la plantilla no inventa denominaciones ausentes ni debe tratarse como descripción archivística definitiva.

**Validada manualmente en 0.75.1.** Se confirmó el rechazo de un documento directamente bajo un fondo, la importación de las 155 filas DIPPBA, la jerarquía completa, la exportación del catálogo y la reimportación idéntica sin revisiones nuevas. `CAT-01` queda cerrado. No hay migración: continúa `0040_discovery_grouping_continuity`.

## Diccionarios distribuibles de autoridades

### DISC-02 — esquema, simulación e importación transaccional — 0.76.0

Se incorporó un formato JSON `1.0` con esquema y ejemplo versionados. Cada diccionario registra identidad, fuente y proyecto de destino; describe autoridades, alias, temporalidad, características y relaciones; y conserva una huella SHA-256 reproducible en el informe de simulación.

La detección de duplicados compara nombres preferidos y alias normalizados. El modo `auto` crea registros nuevos solo cuando no hay coincidencias y reutiliza únicamente una coincidencia exacta de nombre y tipo. Los casos ambiguos exigen `use_existing`, `create_new` o `skip`. Una autoridad existente nunca es sobrescrita: puede recibir alias nuevos, mientras las diferencias de descripción, características o temporalidad se muestran como advertencias.

Las relaciones pueden dirigirse a otra autoridad, una unidad archivística o una parte documental. Cada una requiere evidencia en el propio JSON. Las relaciones idénticas se omiten en reimportaciones; una relación paralela con evidencia o temporalidad distinta exige `create_parallel` o `skip`.

La CLI ofrece `authority-dictionary-schema`, `authority-dictionary-validate` y `authority-dictionary-import`; la interfaz agrega **Importar diccionario** dentro de **Entidades y menciones**. La aplicación requiere la confirmación `IMPORTAR` y ejecuta autoridades, alias y relaciones dentro de una sola transacción. La guía canónica está en `docs/referencia/IMPORTACION_DICCIONARIOS_DISC_02.md`.

**Validado manualmente en 0.76.0.** Se confirmó que una coincidencia nominal ambigua exige resolución explícita, que una relación sin evidencia es rechazada y que el diccionario controlado crea dos autoridades, reutiliza una ficha sin sobrescribirla, agrega dos alias y crea dos relaciones. La reimportación idéntica produjo cero autoridades, cero alias y cero relaciones nuevas y omitió las dos relaciones duplicadas. `project_data` no fue leído ni modificado. `DISC-02` queda cerrado. No hay migración: continúa `0040_discovery_grouping_continuity`.

## Descubrimiento abierto

### Primera ejecución con menciones existentes — 0.69.1

Se reemplazó el acceso inválido a `EntityMention.lifecycle_status` por el contrato real de `EntityMention.status`. Solo las menciones no rechazadas y con offsets completos bloquean un tramo ya registrado. El panel se movió al final de la vista y queda colapsado por defecto. La corrección quedó incluida en la validación final de `DISC-01A`.

### DISC-01A — detección reproducible validada — 0.69.2

La validación manual de la corrida existente quedó cerrada con 17 objetos aprobados recorridos, 13 candidatos totales y siete candidatos controlados correctos. Se comprobaron las seis familias previstas, offsets, revisión textual, ausencia de escrituras canónicas durante la detección, revisión `0038_open_discovery`, integridad `ok` y claves foráneas vacías. La cantidad mayor de objetos y candidatos corresponde a otros documentos aprobados presentes en la copia y no es una anomalía.

### Verificación de descubrimiento sobre corpus no vacío — 0.69.2

La validación de `DISC-01A` identifica el objeto controlado por su ID y comprueba sus siete candidatos sin asumir que la corrida excluye otros documentos aprobados. El total de candidatos y objetos puede ser mayor.

### DISC-01B — revisión persistente implementada — 0.70.0

La migración `0039_discovery_decisions` agrega `discovery_decisions` y `discovery_context_records`. Cada candidato puede aceptar, rechazar, modificar o aplazar mediante una decisión append-only. Actores, espacios, acontecimientos y obras pueden vincularse a una autoridad existente o iniciar explícitamente una autoridad `unreviewed`; tiempos, acontecimientos y acciones o procesos conservan datos propios. Las decisiones obsoletas se bloquean por revisión textual, toda escritura conserva responsable y origen, y ninguna aceptación crea relaciones automáticamente.

### DISC-01B — revisión persistente validada — 0.70.2

La validación manual confirmó ocho decisiones controladas y una decisión adicional append-only sobre `manifestación`, cuatro registros propios, dos menciones controladas y ninguna relación creada automáticamente. Los conteos finales conservados son siete autoridades, doce menciones, tres relaciones, nueve decisiones y cuatro registros propios. Los paneles interactivos permanecieron abiertos al cambiar decisiones y destinos.

### DISC-01C — agrupamiento y continuidad implementados — 0.71.0

La migración `0040_discovery_grouping_continuity` agrega grupos, pertenencias, acciones append-only y vínculos de continuidad entre candidatos. El agrupamiento automático propone coincidencias exactas o normalizadas entre corridas; el agrupamiento manual permite reunir y separar candidatos sin fusionar sus filas ni borrar procedencias. Una separación conserva la pertenencia histórica con estado retirado y no es revertida por una reconstrucción automática posterior.

Cuando una revisión textual vuelve obsoleto un candidato, la continuidad crea una corrida y un candidato nuevos mediante proyección exacta única o nueva detección local. El candidato anterior continúa visible, el nuevo snapshot conserva offsets y revisión vigentes y las pertenencias activas de grupo se trasladan como procedencia, nunca como decisión humana. La interfaz ubica la función en un panel secundario cerrado por defecto y usa paneles persistentes para que los reruns no interrumpan el recorrido. La validación manual quedó cerrada en 0.72.0.

### Selección segura después de crear un grupo manual — 0.71.1

La creación del grupo se confirma y persiste antes del rerun. La interfaz ya no intenta modificar la clave de un `selectbox` después de instanciarlo: guarda una selección pendiente en una clave separada, ejecuta el rerun y aplica esa selección antes de crear el widget. Esto evita `StreamlitAPIException`, conserva abierto el recorrido y no duplica el grupo ya escrito.

### Validación de continuidad desde snapshots equivalentes — 0.71.2

La continuidad de `Cuaderno del Delta` puede iniciarse desde cualquiera de los dos candidatos obsoletos controlados que representan el mismo texto, objeto y revisión y ya pertenecen al mismo grupo. El validador dejó de exigir arbitrariamente el identificador `work_original` y comprueba en cambio que el origen sea uno de los snapshots controlados equivalentes, que esté obsoleto, que el destino sea vigente y que ambos permanezcan en el grupo. La regresión de extremo a extremo usa ahora el candidato duplicado, que fue el seleccionado durante la prueba manual.

### DISC-01C — agrupamiento y continuidad validados — 0.72.0

El validador final confirmó cuatro grupos —tres automáticos y uno manual—, nueve pertenencias conservadas, catorce acciones append-only y una continuidad desde un snapshot equivalente. También conservó exactamente siete autoridades, doce menciones, tres relaciones, nueve decisiones y cuatro registros propios. La revisión es `0040_discovery_grouping_continuity`, la integridad es correcta y no hay claves foráneas inválidas. La prueba no debe repetirse.

### DISC-01D — evaluación reproducible y proveedor opcional — 0.73.0

Se agregó un corpus JSONL inicial con cobertura explícita de las siete familias, texto exacto, offsets, subtipo y procedencia. El evaluador calcula precisión, recuperación y F1 micro, macro y por familia; conserva predicciones, falsos positivos, falsos negativos, discrepancias de familia o subtipo, parámetros y huellas SHA-256. Los informes del mismo corpus pueden compararse por proveedor, versión y configuración.

El proveedor `local_deterministic@local_rules_v1` continúa disponible sin declararse empíricamente superior. El adaptador opcional `spacy_ner` usa el mismo contrato auditable y exige fijar `modelo@versión`; la dependencia y el modelo se cargan únicamente al ejecutar ese perfil. El corpus inicial es un control sintético de contrato, no un benchmark representativo: muestra seis aciertos de siete y documenta que la familia `other` no es cubierta por las reglas locales. `DISC-01` queda cerrado sin migración nueva.

### UX-03 — recorridos separados para entidades y descubrimiento — 0.72.0

La vista **Entidades y menciones** separa ahora tres tareas principales persistentes: revisar entidades, crear una entidad y abrir Descubrimiento abierto. La creación dejó de competir visualmente con la búsqueda y el descubrimiento ya no aparece como un panel agregado al final de una ficha.

Dentro de Descubrimiento abierto se distinguen **Revisar candidatos**, **Nueva corrida** y **Agrupamiento y continuidad**. La revisión cotidiana queda primero; la configuración de perfiles y la ejecución se aíslan en su propia tarea; agrupamiento y continuidad se dividen en recorridos persistentes. Los historiales, resúmenes y datos técnicos permanecen cerrados por defecto. Se conservaron autoridades, menciones, relaciones, perfiles, corridas, decisiones, grupos, continuidades y contratos de datos sin migración nueva.

La validación manual confirmó los recorridos separados, la conservación de la pestaña activa y el cierre inicial de resúmenes, historiales, filtros y detalles técnicos.

## Correcciones validadas

### Ciclo de vida visual de perfiles de exportación — 0.50.3

**Resuelto y validado manualmente.** Archivar, restaurar y eliminar perfiles reconstruye un único selector, un único bloque de pestañas y un único formulario. La secuencia previa al render evita duplicaciones visuales sin modificar archivos ni historial.

## Núcleo documental

### Catálogo y originales

- Catálogo archivístico jerárquico y campos configurables.
- Registro de objetos digitales y ubicaciones locales.
- Originales inmutables y verificación de presencia, tamaño y checksum.
- Partes internas y asociación de páginas con documentos.
- Migraciones explícitas mediante `db-upgrade`.

### Procesamiento y extracción

- Preparación reproducible de derivados para OCR.
- Corridas versionadas por página y perfil.
- Tesseract, Docling y Surya como backends revisables.
- Runtime Surya aislado y servidor persistente con fallback.
- Comparación de corridas no canónicas mediante texto, imagen y cajas.
- Selección canónica independiente de la evaluación de calidad.
- Diagnóstico de brillo, contraste, desenfoque probable, ruido, fragmentación, objetos mínimos y solapamientos.
- Control conservador de ordinales y candidatos de casilleros sin corrección silenciosa.

La evaluación empírica inicial de Surya y las decisiones técnicas se conservan en `docs/historico/decisiones_tecnicas/`.

### Decisión de alcance sobre duplicados y copias — OCR-02, 0.74.0

- Los archivos binariamente idénticos ya se reconocen por SHA-256 dentro de cada proyecto: `DigitalObject` conserva unicidad por `project_id + sha256` y una nueva ubicación se registra como otra instancia del mismo objeto digital.
- Dos copias, ejemplares o digitalizaciones catalográficamente distintas pueden contener el mismo texto y seguir siendo documentos diferentes por procedencia, soporte o contexto.
- Cada objeto documental distinto conserva su propio OCR y sus derivados; Archive Workbench no sustituye automáticamente una representación por otra ni elige una copia “más legible” para reemplazar la fuente.
- La identificación intelectual de duplicados documentales corresponde al proceso de catalogación. No se implementa una deduplicación OCR adicional que pueda mezclar procedencias.

`OCR-02` queda cerrado como decisión de alcance, sin migración ni cambios de datos.

## Revisión e historial

### Editor y auditoría

- Edición de texto y tipo de objeto.
- Alta, baja lógica, restauración, división, unión y reordenamiento.
- Comentarios, etiquetas, partes documentales y estados de revisión.
- Deshacer y rehacer transaccional.
- Historial integrado de página y por objeto, incluido el estado OCR inicial.

### Rebase de edición sobre otra extracción

Implementado entre 0.40.0 y 0.48.0:

- rebase conservador de tres estados;
- relocalización de comentarios, etiquetas y menciones;
- resolución manual de conflictos de menciones;
- resolución de conflictos textuales;
- conservación del snapshot estructural activo;
- decisiones de parte documental, estado y tipo;
- proyección manual de objetos ambiguos;
- resolución de atributos especializados;
- ciclos `A → B → A → B` sin violar unicidad histórica;
- conservación de procedencia e historial;
- entradas manuales con botón explícito y sin envío por `Enter` o `Ctrl+Enter`.

La validación manual confirmó tres rebases sucesivos, conservación de atributos, dos comentarios, dos etiquetas y ausencia del remanente visual oscuro.

## Búsqueda, autoridades y grafo

### Búsqueda

- Índice literal FTS5 y búsqueda por trigramas.
- Búsqueda semántica opcional con perfiles e índices reconstruibles.
- Navegación desde resultados hacia documento, página y objeto.
- Filtros por estado de página en búsqueda literal y semántica.

### Calibración reproducible de búsqueda semántica — SEM-01, 0.74.0

- `semantic-evaluate` ejecuta consultas verificadas contra un perfil y un índice vigentes sin modificar la base, el corpus ni los vectores.
- El corpus JSONL distingue consultas `positive`, `negative` y `ambiguous`, fija el tipo de fragmento y permite evaluar por `chunk_id`, `record_id`, `source_key` u `object_id`.
- Cada informe conserva corpus, perfil, modelo, revisión, corrida de índice, parámetros, resultados ordenados, falsos positivos, falsos negativos y métricas por umbral y tipo de consulta.
- El umbral recomendado maximiza F1 dentro del conjunto evaluado y queda acompañado por una advertencia explícita: no es universal y solo vale para ese corpus, perfil, modelo, revisión de índice y grilla de umbrales.
- `semantic-evaluation-compare` compara informes del mismo corpus y tipo de fragmento sin declarar un modelo superior fuera de esa evidencia.
- `config/semantic_evaluation_corpus.example.jsonl` documenta los tres tipos de consulta y exige reemplazar las claves de ejemplo por referencias verificadas del proyecto.

No hay migración: los informes son archivos JSON reproducibles y la ejecución solo lee el índice y la base existentes.

**Validada en 0.74.0.** El proyecto descartable conservó la revisión `0040_discovery_grouping_continuity`, recomendó el umbral controlado `0.7` con F1 `0.8`, produjo un informe alternativo comparable y confirmó que `project_data` no fue leído ni modificado. El resultado valida el contrato y la comparación reproducible; no fija un umbral universal.

### Autoridades y menciones

- Autoridades con nombre preferido, alias, tipo, estados y temporalidad.
- Rastreo transversal de nombres y alias ya registrados.
- Incorporación de menciones con offsets y revisión textual.
- Invariante que impide menciones aceptadas o modificadas sin autoridad.
- Historial append-only de creación, desvinculación y revinculación.
- Deduplicación transrevisionaria y conflicto cuando un fragmento ya está vinculado a otra autoridad.
- Diagnósticos para menciones huérfanas, antiguas y duplicadas.

El descubrimiento de elementos desconocidos es una función separada y quedó cerrado como `DISC-01` en 0.73.0.

### Relaciones

**Resuelto y validado en 0.46.0:** creación con confirmación explícita, edición de tipo, evidencia, temporalidad y estado, cambio de destino, baja lógica y conservación de todas las revisiones. La baja lógica se refleja correctamente en el grafo.

### Grafo

- Relaciones explícitas, entidades compartidas y capas derivadas.
- Filtros de entidades o relaciones inactivas.
- Advertencias de consistencia y procedencia de aristas.

### Grafo sin colisiones — GRAPH-01, 0.74.0

- Las aristas paralelas, incluidas las de sentido inverso, reciben carriles deterministas y separados.
- El canvas usa rutas cuadráticas o bucles propios en lugar de líneas superpuestas, y recalcula la geometría al arrastrar nodos.
- Las etiquetas de aristas se desplazan automáticamente cuando colisionan con nodos u otras etiquetas.
- Las etiquetas de nodos se envuelven en dos líneas y eligen automáticamente el lado menos ocupado.
- Los tooltips de nodos y aristas muestran tipo, contexto, explicación del origen, evidencia, estado, período y fuente cuando esos datos existen.
- El layout aplica una separación mínima determinista entre centros de nodos y conserva el mismo resultado ante la misma vista.
- La identidad del componente incorpora todos los filtros visibles para que el estado corresponda exactamente a la vista solicitada.

Los filtros y la explicación detallada ya existentes se conservan; no se agrega un panel nuevo a la pantalla principal.

**Validado manualmente en 0.74.0.** Se comprobaron tres relaciones curvas separadas entre los nodos controlados, incluida una relación en sentido inverso; los tooltips conservaron tipo, dirección, procedencia y evidencia; al arrastrar nodos se recalcularon curvas y etiquetas; y los filtros coincidieron con el resumen, la tabla y el canvas.


## Reparación auditable de menciones

### Reubicación segura sobre el texto vigente — fase 1, 0.57.0

- Las menciones activas se separan de las menciones rechazadas, que permanecen como evidencia histórica.
- Cada alerta se clasifica como reubicación segura, ubicación no resuelta, colisión con otra mención, vínculo faltante o divergencia de snapshot.
- La reubicación automática solo se habilita cuando existe una proyección única, no hay otra mención activa en el mismo fragmento y la fila coincide con su último snapshot.
- La operación exige confirmación explícita, actor y nota; actualiza offsets y revisión textual, incrementa la revisión de la mención y agrega un snapshot `repair_relocation`.
- Los snapshots anteriores no se modifican y la revisión rechazada o ambigua nunca se repara automáticamente.
- `scripts/create_mention_repair_validation_project.py` genera una copia descartable para validar el recorrido sin alterar proyectos reales.

### Resolución de menciones sin entidad — fase 2, 0.58.0

- Una mención histórica con estado `accepted` o `modified` y sin entidad vinculada puede asociarse a una entidad activa existente del mismo proyecto.
- Como alternativa, puede volver a estado `pending` para exigir una revisión humana posterior.
- Las dos rutas requieren confirmación explícita, actor y nota.
- La vinculación agrega una revisión `repair_link_authority`; el retorno a pendiente agrega `repair_return_pending`.
- Las revisiones y snapshots anteriores permanecen intactos.
- Si la fila vigente diverge de su último snapshot, ninguna de las dos decisiones se habilita.
- `scripts/create_missing_authority_validation_project.py` crea dos casos descartables, con frases completas, para validar ambas rutas sin alterar proyectos reales.

**Validada manualmente en 0.58.0.** Las dos rutas produjeron `repair_link_authority` y `repair_return_pending`, eliminaron las alertas activas correspondientes y conservaron integridad y claves foráneas válidas.

### Resolución de menciones duplicadas — fase 3, 0.59.0

- La comparación se habilita cuando una mención histórica converge con exactamente una mención activa sobre el fragmento vigente.
- La persona revisora puede conservar la mención vigente y retirar la histórica, o conservar la histórica, retirar la vigente y reubicar la elegida.
- La mención retirada agrega `repair_duplicate_rejected`; la histórica conservada y reubicada agrega `repair_duplicate_relocated`.
- No se fusionan entidades, notas ni snapshots, y ninguna mención se elimina físicamente.
- Las dos filas deben coincidir con sus últimos snapshots y con las revisiones mostradas por el formulario.
- Los conjuntos con más de una contraparte se mantienen bloqueados para evitar decisiones parciales.
- `scripts/create_duplicate_mention_validation_project.py` crea dos pares descartables para validar ambas rutas sin alterar proyectos reales.

**Validada manualmente en 0.59.0.** Las dos decisiones conservaron la mención elegida, retiraron la contraparte mediante revisiones nuevas y dejaron la base íntegra y sin claves foráneas inválidas.

### Resolución manual de ubicaciones — fase 4, 0.60.0

- Los casos `unresolved_relocation` permiten indicar un fragmento literal del texto vigente y elegir una aparición concreta.
- La reubicación manual verifica revisión textual, revisión de mención, contenido exacto, offsets y ausencia de otra mención activa antes de registrar `repair_manual_relocation`.
- Cuando el fragmento histórico ya no aparece, puede retirarse la mención mediante `repair_mark_absent`; no se borra el registro ni se alteran revisiones anteriores.
- No se permite declarar ausencia cuando el fragmento todavía aparece en el texto vigente.
- Las dos decisiones exigen confirmación explícita, actor y fundamento, y generan eventos de intercambio `update`.
- `scripts/create_unresolved_mention_validation_project.py` crea una aparición ambigua y un fragmento ausente dentro de una copia descartable.

**Validada manualmente en 0.60.0.** La prueba confirmó la reubicación en la segunda aparición, el retiro del fragmento ausente, las operaciones `repair_manual_relocation` y `repair_mark_absent`, cero alertas restantes, integridad `ok` y ausencia de claves foráneas inválidas.

### Reconciliación entre fila e historial — fase 5, 0.61.0

- Los casos `snapshot_divergence` comparan en pantalla cada campo distinto entre la fila vigente y el último snapshot registrado.
- La persona revisora puede conservar la fila vigente mediante `repair_adopt_current_row` o restaurar el último estado registrado.
- Antes de restaurar, `repair_capture_divergent_row` incorpora la fila divergente al historial para que ningún valor observado desaparezca.
- La restauración agrega después `repair_restore_snapshot`; no reescribe ni elimina snapshots anteriores.
- El formulario queda obsoleto si cambia la fila, la revisión de la mención o el contenido del último snapshot.
- Se validan objeto, entidad, estado, procedencia, offsets y pertenencia al proyecto antes de restaurar.
- `scripts/create_snapshot_divergence_validation_project.py` crea dos casos descartables para validar ambas decisiones.

**Validada manualmente en 0.61.0.** Las dos rutas produjeron `repair_adopt_current_row`, `repair_capture_divergent_row` y `repair_restore_snapshot`, conservaron la fila divergente antes de restaurar el historial y dejaron cero alertas, integridad `ok` y claves foráneas válidas.

### Conjuntos coincidentes y reubicaciones agrupadas — fase 6, 0.62.0

- Los conjuntos de tres o más menciones sobre la misma ubicación se presentan una sola vez como `duplicate_group`.
- La interfaz muestra todas las menciones y exige elegir una única ganadora; no permite decisiones binarias parciales.
- Las perdedoras agregan `repair_group_duplicate_rejected`; la ganadora agrega `repair_group_duplicate_relocated` si era histórica o `repair_group_duplicate_kept` si ya estaba vigente.
- Las reubicaciones seguras del mismo objeto pueden aplicarse juntas mediante `repair_group_relocation`.
- Antes de escribir, ambas operaciones vuelven a verificar revisiones, snapshots, revisión textual, offsets y composición exacta del conjunto; cualquier cambio cancela la transacción completa.
- `scripts/create_grouped_mention_validation_project.py` crea un conjunto de tres menciones y tres reubicaciones seguras agrupables en una copia descartable.

**Validada manualmente en 0.62.1.** La prueba confirmó las tres reubicaciones seguras agrupadas, la elección de una única mención ganadora, el rechazo auditable de las otras dos, cero alertas restantes, integridad `ok` y ausencia de claves foráneas inválidas. DATA-01 queda cerrado: todas las reparaciones conservan snapshots y agregan revisiones nuevas sin reescritura silenciosa.

## Calidad y análisis

- Estados de calidad de página y evaluación de corridas.
- Exportación, búsqueda literal, búsqueda semántica y sugerencias por diccionario respetan filtros de calidad.
- Índices se marcan como pendientes de reconstrucción cuando cambia el corpus.

### Política común de alcance automático — fase 1, 0.63.0

- `analysis_quality.py` concentra estados válidos, alcance predeterminado y mensajes de calidad.
- El alcance seguro para análisis automático es únicamente `approved`.
- Los perfiles nuevos de exportación y búsqueda semántica comienzan con páginas aprobadas.
- Un perfil ampliado debe confirmarse explícitamente al guardar; el botón permanece disponible y la validación ocurre al enviar para evitar bloqueos circulares de `st.form`.
- La búsqueda automática de menciones muestra el alcance, advierte cuando se amplía y exige confirmación antes de comenzar.
- Los estados seleccionados permanecen registrados en perfiles y snapshots reproducibles.

La obligatoriedad programática, la auditoría persistente y el contrato para análisis futuros se completan en la fase 2 de 0.64.0.

### Política común, obligatoria y auditable — fase 2, 0.64.0

- El alcance seguro deja de ser solamente una convención de interfaz: `ExportProfileValues` y `SemanticProfileValues` usan `approved` como valor programático predeterminado.
- Ya no existe la ruta de compatibilidad que permitía un alcance ampliado sin autorización; otros estados o todos exigen confirmación explícita y un fundamento no vacío.
- Cada guardado de perfil de exportación, perfil semántico o búsqueda automática de menciones agrega una fila append-only en `automatic_analysis_authorizations`.
- La previsualización y ejecución de exportaciones y las operaciones semánticas verifican una autorización que coincida con la huella de los parámetros funcionales actuales; una autorización vieja no habilita silenciosamente una configuración modificada.
- Los perfiles existentes antes de la migración deben guardarse nuevamente para registrar su primer alcance autorizado; no se fabrican consentimientos retrospectivos.
- La autorización registra política, tipo de análisis, estados de página, responsable, fundamento, origen, destino y hash canónico de parámetros.
- La migración `0034_automatic_analysis_authorizations` crea el registro sin modificar perfiles, índices, menciones ni autorizaciones históricas inexistentes.
- La interfaz incorpora **Administrar y recuperar → Auditoría de análisis** y la terminal agrega `analysis-quality-audit`.
- El registro común declara contratos para exportación, índice semántico, sugerencias, resúmenes, estadísticas, descubrimiento abierto, importaciones asistidas, herramientas LLM, RAG e integraciones. Una implementación futura debe usar un tipo registrado o falla de manera explícita.
- `.assistant/06_RELEVO_NUEVA_CONVERSACION.md` prepara la continuidad sin reconstruir decisiones desde conversaciones antiguas.

La implementación funcional de `DATA-02` quedó completa en 0.64.0 y la corrección del botón se incorporó en 0.64.1.

**Validada manualmente en 0.64.1.** La interfaz registró las autorizaciones ampliadas de exportación, índice semántico y sugerencias de menciones con origen `ui`, responsable `alex`, estados `reviewed,approved`, fundamentos y huellas SHA-256. `analysis-quality-audit` mostró los tres tipos esperados; la comprobación directa devolvió tres autorizaciones ampliadas, revisión `0034_automatic_analysis_authorizations`, integridad `ok` y ninguna clave foránea inválida. `DATA-02` queda cerrado y retirado de los pendientes activos.

## Exportación

**Implementado y validado en 0.49.1:**

- perfiles con agrupación, texto, formatos y filtros;
- vista previa con registros y caracteres;
- CSV y JSONL reproducibles;
- historial con ruta, tamaño, estado y SHA-256;
- prevención de sobrescritura implícita;
- confirmación persistente y descarga directa;
- archivar, restaurar y eliminar perfiles sin borrar archivos ni historial.

## Backups y recuperación

**Resuelto y validado en 0.48.0:**

- creación y listado cronológico por fecha real del manifiesto;
- verificación de estructura, checksums y SQLite;
- prueba de recuperación no destructiva;
- restauración real con backup automático previo;
- indicación explícita de `db-upgrade` posterior;
- integridad y claves foráneas verificadas;
- recuperación del estado esperado sin conservar cambios posteriores al backup.

## Intercambio offline

- copias reidentificadas y puntos de control;
- exportación incremental de paquetes;
- inspección, simulación y reportes;
- reconocimiento de ascendencia aunque existan cambios locales posteriores;
- aplicación transaccional con backup;
- registro de dos paquetes aplicados y coexistencia de cambios remotos y locales;
- bloqueo de simulaciones obsoletas antes de crear backups;
- archivo, restauración y limpieza de entradas no aplicadas;
- presentación segura de paquetes sin base común, con tres eventos y 21 campos;
- aceptación masiva recibida deshabilitada para creaciones sin base verificable.

### Diagnóstico de evidencia de linaje — EX-01A, 0.65.0

**Implementado y validado manualmente.**

- trabaja únicamente sobre paquetes activos cuya simulación quedó `unmatched`;
- lee la SQLite vigente y el paquete recibido sin crear casos, decisiones, puntos de control ni reportes persistentes;
- inspecciona solamente paquetes, manifiestos y backups adicionales indicados explícitamente;
- reconoce punto exacto, aplicación anterior, backup íntegro de la misma copia y cadenas continuas de paquetes;
- clasifica como recuperable, ambiguo o insuficiente y explica cada evidencia concluyente, de apoyo o rechazada;
- rechaza checksums inválidos, proyecto diferente, copia de origen incompatible, ciclos y bifurcaciones;
- expone `exchange-lineage-diagnose` y un panel de solo lectura en Intercambiar cambios.

La validación manual confirmó por terminal e interfaz que el caso sin evidencia quedaba insuficiente, que un manifiesto aislado seguía siendo solo apoyo y que la cadena íntegra producía un único candidato `verified_bundle_chain`. La comprobación directa confirmó ausencia de tablas o filas de escritura de `EX-01`, revisión `0034_automatic_analysis_authorizations`, integridad `ok` y claves foráneas válidas.

### Recuperación append-only de linaje — EX-01B, 0.66.0

**Implementada y validada manualmente.**

- agrega la migración `0035_exchange_lineage_recovery` con casos, evidencias y decisiones append-only separadas de los eventos de contenido;
- persiste el método con el que cada simulación reconoce su base mediante `base_match_method`;
- solo permite recuperar un paquete `unmatched` cuando el diagnóstico produce una cadena concluyente, única y sin contradicciones;
- exige responsable, fundamento, confirmación explícita y conserva un SHA-256 de los parámetros funcionales;
- registra todas las evidencias examinadas y marca cuáles sustentan la decisión;
- impide una segunda recuperación sobre el mismo paquete;
- vuelve obsoleta la simulación anterior y obliga a repetirla;
- permite que la nueva simulación reconozca la base mediante `recovered_lineage`;
- no modifica páginas, objetos, autoridades, menciones, relaciones ni eventos de contenido;
- expone `exchange-lineage-recover`, `exchange-lineage-recoveries` y un formulario Streamlit con `enter_to_submit=False` y validaciones posteriores al envío.

La validación manual confirmó una única recuperación `verified_bundle_chain` sobre `baseline_ex01a`, con responsable y fundamento persistidos. La simulación anterior quedó obsoleta y la reevaluación reconoció la base mediante `recovered_lineage`, produjo el conflicto esperado y no aplicó ningún cambio al estado editable.

### Acuerdo bilateral de base común con estado idéntico — EX-01C, 0.67.0

**Implementada y validada manualmente.**

- agrega la migración `0036_exchange_common_base_agreements` con un registro append-only local del mismo acuerdo bilateral en cada copia;
- divide el recorrido en propuesta, aceptación por la contraparte y finalización por la copia iniciadora;
- transporta propuesta y acuerdo en ZIP verificables con manifiestos JSON 1.0 y checksums SHA-256;
- exige proyecto común, identidades de copia distintas y el mismo SHA-256 del estado editable;
- bloquea la aceptación si la contraparte, el proyecto o el estado no coinciden y bloquea la finalización si la iniciadora cambió desde la propuesta;
- registra en ambos lados el mismo `agreement_id`, la misma huella del manifiesto y puntos de control locales con la etiqueta `common_base_<id>`;
- vuelve obsoletas las simulaciones anteriores y permite reconocer paquetes posteriores mediante `common_base_agreement`;
- no modifica páginas, objetos, autoridades, menciones, relaciones ni texto editable;
- expone los comandos `exchange-common-base-propose`, `exchange-common-base-accept`, `exchange-common-base-finalize` y `exchange-common-base-agreements`;
- incorpora formularios Streamlit con `enter_to_submit=False`, botones siempre habilitados y validación posterior al envío;
- incorpora `create_common_base_validation_projects.py` para crear dos copias descartables con identidades distintas y estado idéntico.

La validación manual confirmó que ambas copias registraron el mismo identificador de acuerdo, manifiesto, SHA-256 editable y punto `common_base_…`, con roles `initiator` y `counterpart`. Un paquete posterior sin eventos fue reconocido mediante `common_base_agreement`, quedó `empty` y no modificó el estado editable.

### Adopción explícita de estado divergente — EX-01D, 0.68.0

**Implementada y validada manualmente.**

- agrega la migración `0037_exchange_state_adoptions` con adopciones y rollbacks append-only;
- crea un ZIP verificable del estado editable completo, dirigido a una contraparte concreta y vinculado a la base documental compartida;
- presenta una vista previa de solo lectura con altas, bajas y cambios por sección;
- exige responsable, fundamento y confirmación explícita tanto para crear el paquete como para adoptarlo;
- crea un backup verificable antes de escribir y reemplaza transaccionalmente el estado editable;
- verifica SHA-256 final, integridad SQLite y claves foráneas antes de confirmar la operación;
- invalida simulaciones anteriores y no activa por sí sola una base común;
- permite restaurar el backup previo mediante un rollback explícito, que crea además un backup de seguridad del estado posterior;
- bloquea el rollback si el estado cambió desde la adopción, si ya fue revertida o si un acuerdo bilateral ya utiliza ese estado;
- expone `exchange-state-package-create`, `exchange-state-adoption-preview`, `exchange-state-adopt`, `exchange-state-adoptions` y `exchange-state-adoption-rollback`;
- incorpora el panel **Reconciliar estados divergentes** y `create_state_adoption_validation_projects.py`.

La validación manual confirmó la vista previa sin escritura, la primera adopción con backup, la igualdad de hashes, el rollback, una segunda adopción definitiva, el acuerdo bilateral posterior y el reconocimiento de un paquete final mediante `common_base_agreement`. Ambas bases conservaron revisión `0037_exchange_state_adoptions`, integridad `ok` y claves foráneas válidas. `project_data` fue respaldada y migrada a la misma revisión; la aplicación abrió y las pruebas OCR continuaron visibles.

**EX-01 queda cerrado en 0.68.1.** El diagnóstico, la recuperación, el acuerdo bilateral y la adopción reversible quedaron validados sin convertir resoluciones de contenido en parentesco implícito.

## Integridad y migraciones

### Migración 0027

**Resuelta y validada en 0.49.1.** La regresión parte de `0026_team_workflow` y conserva:

- UUID de autoridades;
- alias;
- snapshots append-only;
- una mención aceptada vinculada;
- una relación entre autoridades;
- claves foráneas hasta `0033_export_exchange_lifecycle`.

También pasaron las rutas desde 0031 y 0032 y el archivo completo `tests/test_database.py`. No debe reabrirse como bloqueante sin una regresión concreta.

### Integridad posterior

Las bases descartables de rebase, intercambio receptor y paquete sin base común devolvieron:

```text
integrity_check: ok
foreign_key_check: []
```

## Interfaz y formularios

### Principio permanente para toda modificación — 0.70.1–0.70.2

Toda nueva versión debe releer y aplicar esta sección y `.assistant/05_CRITERIOS_INTERFAZ.md` antes de agregar o modificar capacidades. La interfaz no debe volver a complejizarse por acumulación: el recorrido principal permanece visible y breve; configuraciones, historiales, parámetros y datos técnicos se muestran mediante divulgación progresiva; los paneles secundarios nuevos quedan cerrados por defecto; y no se duplican controles ni explicaciones.

Los paneles que contienen controles reactivos deben conservar su apertura durante los reruns de Streamlit. Los `st.expander` quedan reservados para contenido informativo, historiales o detalles técnicos; un flujo interactivo usa un estado persistente con clave estable o un recorrido explícito por pasos. Cambiar una decisión, un destino o un filtro no debe cerrar el panel activo ni hacer perder el contexto.

Esta obligación rige desde el diseño de cada cambio y se verifica en sus pruebas de navegación. `UX-02` realizará una revisión integral al final de los bloques funcionales activos y antes de la candidata a v1.0, sin postergar la corrección de regresiones concretas.

### Orientación y lenguaje claro — fase 1, 0.51.0

- La barra lateral presenta secciones como tareas y explica brevemente para qué sirve cada una.
- Inicio muestra el recorrido recomendado con los mismos nombres visibles.
- Intercambio usa “paquete de intercambio”, “simulación”, “punto de control” y “copia de seguridad” en las acciones principales.
- Los estados técnicos permanecen disponibles en un desplegable separado, sin dominar la pantalla principal.

Esta fue la primera de seis fases; la revisión general quedó completada y validada en 0.56.0.

### Recorrido guiado y lenguaje claro — fase 2, 0.52.0

- El circuito completo se organiza en cinco etapas y once pasos, sin retirar ninguna sección.
- La barra lateral permite ir a la sección anterior o siguiente.
- La orientación contextual es opcional y explica objetivo, requisitos y paso habitual siguiente.
- Administración usa “copia de seguridad” en todo el recorrido principal y oculta el comando técnico de restauración hasta abrir su desplegable.
- Exportar explica `JSONL` como un registro por línea y `CSV` como tabla.

Esta fue la segunda de seis fases; la revisión general quedó completada y validada en 0.56.0.

### Búsquedas comprensibles — fase 3, 0.53.0

- Buscar texto muestra primero la consulta y la forma de combinar palabras.
- Todos los filtros anteriores se conservan dentro de `Filtros opcionales`.
- La reconstrucción y la generación del índice literal quedan en desplegables técnicos.
- Buscar por significado separa consulta, opciones, estado técnico, contenido incluido y configuración del índice.
- CPU y CUDA se presentan como procesador y placa NVIDIA, sin cambiar los valores internos.

Esta fue la tercera de seis fases; la revisión general quedó completada y validada en 0.56.0.

### Catálogo y procesamiento más legibles — fase 4, 0.54.0

- Buscar dentro de las palabras pasa a ser una opción principal junto con la combinación de términos.
- Catálogo deja visible la búsqueda general y agrupa resumen, filtros y datos internos de la unidad.
- Procesamiento presenta las acciones como tareas, agrupa el resumen de avance y relega la repetición forzada a opciones avanzadas.
- Se conservan todos los campos, filtros, operaciones, perfiles, candidatos e historiales existentes.

**Implementada y validada manualmente en 0.54.0.**

### Revisión, entidades y relaciones más legibles — fase 5, 0.55.0

- Revisión conserva documento, página y objeto como recorrido principal, y agrupa visualización, resumen, exportación, estado de página, deshacer/rehacer y datos del objeto.
- Las tareas del objeto se nombran como editar texto, ordenar y estructurar, anotar, revisar datos adicionales y gestionar menciones.
- Entidades deja visible la búsqueda general y separa filtros, resumen, explicación conceptual y opciones de búsqueda de menciones.
- El grafo se presenta como mapa de relaciones, usa “elementos” y “vínculos” en la interfaz principal y mantiene identificadores y pesos dentro de detalles técnicos.
- No cambia la persistencia, la lógica de revisión, las relaciones ni la construcción del grafo.

**Implementada y validada manualmente en 0.55.0.** La revisión final de densidad, legibilidad y recorridos de trabajo se completó en 0.56.0.

### Legibilidad final de datos, trabajo y exportación — fase 6, 0.56.0

- Los datos del objeto seleccionado usan tarjetas de texto que permiten envolver valores largos; “Sin revisar” y los demás estados ya no quedan recortados con puntos suspensivos.
- Los estados de ciclo de vida del objeto se presentan como “Activo” y “Eliminado”.
- Organización del trabajo separa el resumen principal de la carga por responsable, el avance documental y los filtros de asignaciones.
- Exportar organiza el recorrido como configurar perfil, revisar contenido y crear archivo; identificadores y huellas verificables quedan disponibles en detalles técnicos.
- No cambia estados, asignaciones, perfiles, archivos ni reglas de exportación.

**Implementada y validada manualmente en 0.56.0.** No se detectaron recortes ni pérdida de controles; `UX-01` queda cerrado con sus seis fases validadas.

- Navegación persistente por vista y pestaña.
- Fragmentos autocontenidos y separación entre rerun local y navegación completa.
- Ausencia validada del remanente visual oscuro después del rebase.
- Formularios con `enter_to_submit=False`.
- Botones que validan sus propias casillas al enviar, sin bloqueo circular.
- Mensajes `Press Enter…` y `Press Ctrl+Enter…` ocultos.
- Pruebas AST para impedir regresiones de formularios y confirmaciones.

**UX-01 queda cerrado:** el recorrido completo mantiene todas las funciones y presenta navegación, orientación, léxico y detalles técnicos con jerarquía progresiva. Las mejoras futuras de pantallas concretas se registrarán como tareas nuevas y acotadas, no como reapertura de este bloque general.

## Organización documental

**Implementada en 0.50.0:**

- una única lista de pendientes activos;
- un único registro de implementaciones realizadas;
- guía de actualización vigente con nombre estable;
- documentación histórica separada por tipo;
- arquitectura actual separada del diseño histórico;
- carpeta oculta `.assistant/` con instrucciones de continuidad;
- pruebas que impiden volver a ensuciar la raíz de `docs/` o duplicar documentos operativos.
