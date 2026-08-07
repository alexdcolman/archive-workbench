## 0.84.0 — 2026-08-07

- Implementa `AV-01` para registro local de audio y video sobre `DigitalObject`/`FileInstance`, con SHA-256 y original inmutable.
- Agrega inspección FFprobe, derivados FFmpeg trazables y la migración aditiva `0045_audiovisual_transcription`.
- Incorpora corridas de transcripción con backend intercambiable, recorrido `faster-whisper` CPU, segmentos temporales y revisiones append-only.
- Agrega la vista **Transcribir audio y video**, reproducción integrada, **Velocidad de reproducción**, salto al segmento, corrección humana y opciones técnicas cerradas por defecto.
- Integra segmentos en búsqueda literal, menciones de entidades, exportación CSV/JSONL y adopción de estado audiovisual 1.1 sin alterar la huella histórica de proyectos que no contienen AV.
- Excluye explícitamente audio y video del inventario OCR.
- Incluye audio/video controlados, creador de base descartable y verificador de validación.
- La validación manual real confirmó audio y video integrados, velocidad variable, salto temporal, corrección persistente, mención de entidad, navegación desde búsqueda, exportación JSONL y una corrida `faster-whisper` `tiny` en CPU con `int8` completada sobre video.
- RC1 reveló dos regresiones de interfaz: **Ir al inicio del segmento** no movía efectivamente el reproductor y **Abrir** desde búsqueda descartaba el destino audiovisual. RC2 corrigió ambas y la revalidación manual las confirmó.
- El verificador final sobre la base descartable informó `quick_check: ok`, cero violaciones de claves foráneas, SHA-256 intactos de los dos originales, cinco segmentos exportables y dos segmentos generados por la corrida CPU de video. `AV-01` queda cerrado en 0.84.0.
- El gate de suite completa previo a migrar `project_data` detectó compatibilidad incompleta de la huella de intercambio con bases anteriores a `0045`; se corrigió para consultar el estado audiovisual solo cuando existe su esquema y se repararon fixtures/verificadores históricos que habían quedado atados a revisiones/versiones antiguas.

## 0.83.0 — 2026-08-07

- Implementa `OCR-01F` con benchmark reproducible Tesseract/Docling/Surya sobre verdad terreno por página.
- Agrega cálculo explícito de CER y WER mediante distancia de Levenshtein, normalización Unicode configurable y recuentos de referencia/candidato.
- Conserva por motor perfiles, versión, tiempo, texto normalizado para comparación, salida cruda y logs; cada corrida copia la verdad terreno usada y registra su SHA-256.
- Incorpora `ocr-benchmark-truth-doctor` y `ocr-benchmark-truth`, junto con `config/ocr_benchmark_truth.yaml`.
- El benchmark exige el motor solicitado y no aplica fallback entre Tesseract, Docling y Surya; no cambia selección canónica ni capa editable.
- Agrega scripts de proyecto y verificación controlados para validar los tres motores sobre el mismo derivado.
- La validación real controlada ejecutó Tesseract 5.3.4, Docling 2.114.0 y Surya 0.22.1 sobre la misma página: los tres obtuvieron CER 0.0000 y WER 0.0000; se conservaron tiempos, perfiles, versiones, textos, salidas crudas y la copia verificable de la verdad terreno.
- El TIFF original permaneció intacto, la selección canónica siguió vacía y `project_data` no fue modificado durante la validación. `OCR-01F` y el bloque completo `OCR-01` quedan cerrados.
- No agrega migraciones; la revisión continúa en `0044_layout_structure_review`.

## 0.82.0 — 2026-08-07

- Agrega `OCR-01E` con el modo geométrico `conservative_dewarp` para corregir curvatura vertical suave únicamente sobre derivados OCR.
- Estima desplazamientos por franjas verticales, ajusta una curva cuadrática reproducible y aplica una malla solo cuando soporte, amplitud, calidad de ajuste y confianza superan los umbrales conservadores.
- Registra por página detección, aplicación, confianza, desplazamiento máximo, franjas con soporte, coeficientes y motivo de aplicación u omisión.
- Conserva un activo `dewarp_diagnostic` separado de la máscara de líneas, el derivado OCR y la previsualización sin cambios.
- Amplía **Procesar documentos** con el modo de corrección y un diagnóstico visual que compara previsualización, derivado, máscara y mapa de curvatura.
- Agrega `create_dewarp_validation_project.py`, `verify_dewarp_validation_project.py` y pruebas unitarias e integrales sobre una página curva y una página plana controladas.
- La validación manual confirmó corrección de la página curva, omisión de la plana, cuatro derivados trazables por documento e integridad de los originales.
- La RC2 conserva operación, documentos, tratamiento OCR y modo geométrico al activar el diagnóstico, incluso si Streamlit elimina temporalmente las claves nativas de los widgets durante el rerun.
- No agrega migraciones; la revisión continúa en `0044_layout_structure_review`.

## 0.81.0 — 2026-08-06

- Implementa `OCR-01D` con una pestaña visual **Procesar documentos > OCR regional** organizada en seis pasos lineales.
- Permite cargar plantillas YAML existentes o dibujar zonas sobre una página visible, clasificarlas y decidir si se intenta OCR o se conservan para transcripción manual.
- Agrega clasificaciones controladas para texto principal, portada, encabezado, pie, número de página, sello, firma, manuscrito, ilustración y elemento preimpreso.
- Conserva geometría, modo, clasificación semántica, recortes, archivos crudos, `regions.jsonl` y manifiesto completo dentro de una corrida inmutable.
- Toda ejecución visual usa `selection_policy=never`: crea una candidata sin cambiar selección canónica ni capa editable. Las zonas manuales no inventan texto.
- Agrega `create_regional_ocr_validation_project.py`, `verify_regional_ocr_validation_project.py` y reglas privadas idempotentes mediante `update_assistant_guidance_0810.py`.
- La RC2 asigna a cada zona manual el primer orden libre de la página y normaliza borradores externos con posiciones repetidas; evita el error de validación observado al ocupar dos veces `reading_order=60`.
- Agrega `EXP-01`, `WEB-01`, el piloto real persistente DIPPBA/APM-Chubut/audiovisual, la planificación de `AI-01` y el proyecto paralelo `GIAR-01`, junto con la hoja de ruta y las políticas privadas del futuro sitio público.
- No agrega migraciones; la revisión continúa en `0044_layout_structure_review`. La validación manual confirmó seis regiones, tres zonas OCR, tres zonas manuales, seis recortes, al menos un objeto por zona, selección canónica vacía, manifiesto regional 1.1 e integridad del PDF original; `OCR-01D` queda cerrada.
- Amplía la planificación de `AV-01` y `AV-02`: incorporación local de audio y video en formatos habituales, transcripción segmentada, reproducción integrada con control de velocidad y una pantalla de corrección deliberadamente simple y poco cargada.

## 0.80.0 — 2026-08-06

- Implementa `OCR-01C` con propuestas no canónicas de columnas y orden de lectura calculadas sobre la geometría de la capa editable.
- La confirmación explícita crea columnas estables por página y aplica el orden mediante revisiones de los objetos; permite reasignar objetos, crear, renombrar o archivar columnas y usar deshacer/rehacer.
- Agrega una superposición diagnóstica numerada y señala fragmentaciones y duplicaciones sin corregirlas automáticamente; cada resolución requiere una acción humana y conserva linaje.
- Integra la estructura de layout en intercambio offline, adopción de estado y exportación reproducible mediante `layout_structures.jsonl` y manifiesto 1.4.
- Añade la migración aditiva `0044_layout_structure_review`, que incorpora snapshots JSON de layout a páginas editables y sus revisiones sin alterar textos, imágenes ni objetos existentes.
- Incluye `create_layout_structure_validation_project.py` con dos columnas, una fragmentación y un duplicado controlados. La validación manual confirmó propuesta no canónica, columnas estables, reasignación, renombrado, combinación, archivo de duplicados, deshacer/rehacer, exportación e integridad de los originales.
- La RC2 reorganiza **Orden y estructura** como un recorrido numerado, mantiene visible el objeto seleccionado y reúne la creación de una columna manual con la asignación del objeto en una sola acción.
- Muestra el historial con frases humanas, genera una referencia visual cacheada desde el original cuando falta el derivado de previsualización y agrega `verify_layout_structure_validation_project.py` con diagnósticos explícitos en lugar de aserciones anónimas.
- Agrega `update_assistant_guidance_0800.py` para incorporar de forma idempotente las reglas de guiado y UX en la documentación privada `.assistant` sin versionarla.
- La RC3 corrige el acceso a `ReviewPageView.page_number` por el atributo contractual `page`, evitando que **Orden y estructura** se interrumpa después del primer bloque; agrega una prueba de regresión específica.
- La RC4 diferencia **Historial general** del historial específico de **Orden y estructura**, muestra la columna vigente del objeto seleccionado, mejora el diagnóstico de estado pendiente y refuerza las reglas privadas de guiado para no pedir comprobaciones en pantallas equivocadas. La verificación final cerró `OCR-01C` con tres columnas activas, cinco objetos editables, cero fragmentaciones o duplicaciones pendientes, historial específico completo, exportación 1.4 y conservación del PDF y de los siete objetos OCR de origen.

## 0.79.0 — 2026-08-05

- Implementa `OCR-01B` con candidatos de casillero no canónicos que requieren confirmación humana antes de incorporarse a la estructura revisada.
- Agrega grupos estables por página y casilleros con estados controlados `marked`, `unmarked` e `indeterminate`, anclados a objetos editables y con evidencia, procedencia de detección y ciclo de vida.
- Permite confirmar candidatos, registrar casilleros visibles que no fueron OCRizados, corregir estados y rótulos, crear o archivar grupos y conservar revisiones append-only.
- Integra la estructura de formularios en deshacer/rehacer, intercambio offline, adopción de estado y exportación reproducible mediante `form_structures.jsonl`.
- Añade la migración aditiva `0043_form_structure_review`, que incorpora snapshots JSON coherentes a páginas editables y sus revisiones sin alterar objetos OCR existentes.
- Incluye `create_form_structure_validation_project.py` con tres candidatos controlados y un casillero visible de alta manual. La validación manual confirmó grupos, controles, historial, deshacer/rehacer, exportación e integridad del original.
- Corrige la navegación persistente de pestañas para que deshacer, rehacer, exportar y otras acciones con rerun no devuelvan la interfaz a **Editar texto**; `OCR-01B` queda cerrada.

## 0.78.0 — 2026-08-05

- Incorpora el modo de preprocesamiento geométrico conservador `OCR-01A` para orientación en cuartos de giro, deskew acotado y eliminación controlada de líneas y marcos.
- Mantiene inmutables los originales y las previsualizaciones; las transformaciones se aplican solo al derivado OCR.
- Agrega máscaras diagnósticas y metadatos estructurados por página con detecciones, confianzas, acciones aplicadas y omisiones.
- Añade la migración aditiva `0042_preprocessing_geometry_trace`, con `analysis_json` y `transformations_json` en `derivative_assets`.
- Agrega `create_preprocessing_geometry_validation_project.py` con cinco casos controlados y comprobación de hashes de originales.
- Completa la validación manual local con cinco casos controlados: rotación de 90°, deskew de -3°, cuatro líneas de marco eliminadas, línea que cruza texto conservada y transformación omitida por baja confianza. Los originales permanecen intactos, no hay adopción canónica automática y `OCR-01A` queda cerrada.

## 0.77.0 — 2026-08-05

- Implementa `CAT-02` con relaciones controladas `producer` y `manager` entre autoridades canónicas y unidades archivísticas.
- Conserva período, evidencia, procedencia, estados y revisiones append-only; las etiquetas `produjo` y `gestionó` se generan desde el tipo de rol y no desde texto libre.
- Agrega la migración `0041_catalog_authority_roles_graph_layers` con columnas aditivas, índice por proyecto/rol/unidad y triggers de contrato; las relaciones previas quedan como `analytical`.
- Integra los campos nuevos en intercambio offline, adopción de estado, búsqueda y diccionarios de autoridades.
- Implementa `GRAPH-02` con nodos de autoridad, unidad archivística, objeto digital y parte documental, y capas separadas para jerarquía, documentos, partes, menciones, relaciones analíticas, productores y gestores.
- Agrega filtros por nivel archivístico, foco sobre cualquiera de los cuatro tipos de nodo, profundidad, límite de nodos y procedencia explicable de cada arista.
- Amplía el canvas, los detalles y las exportaciones JSON, CSV y GraphML; corrige la serialización ISO de fechas temporales en JSON.
- Agrega flechas a todas las aristas dirigidas, mantiene sin flecha la capa simétrica de entidades compartidas y recorta los extremos para que las puntas queden visibles junto al nodo de destino.
- Corrige el filtro **Distancia desde el centro** para que permanezca disponible después de aplicar filtros y se ignore, sin deshabilitarse, cuando no existe un foco.
- Corrige la dirección y la etiqueta de las aristas entre objetos digitales y unidades archivísticas: el objeto apunta a la unidad y muestra `representa`, `contiene`, `es parte de` o `es representación alternativa de`.
- Incluye `scripts/create_catalog_graph_validation_project.py`, que crea una base descartable fuera del repositorio y verifica las siete capas requeridas con cero errores de consistencia.
- Completa la validación manual local: confirma roles e historial, siete capas, cuatro tipos de nodo, flechas dirigidas, distancia persistente, pertenencia documental correcta y exportaciones sin truncamiento ni inconsistencias; `CAT-02` y `GRAPH-02` quedan cerrados.

## 0.76.0 — 2026-08-04

- Implementa `DISC-02` con un diccionario JSON versionado para autoridades, alias y relaciones, acompañado por JSON Schema y ejemplo editable.
- Agrega simulación con huella SHA-256, detección de duplicados por nombres y alias, candidatos visibles y resolución explícita mediante `auto`, `use_existing`, `create_new` o `skip`.
- Las autoridades existentes nunca se sobrescriben: solo pueden reutilizarse y recibir alias nuevos; diferencias de descripción, características o temporalidad quedan como advertencias.
- Exige evidencia en cada relación, detecta duplicados y conflictos con relaciones paralelas y aplica autoridades, alias y relaciones en una única transacción.
- Incorpora los comandos `authority-dictionary-schema`, `authority-dictionary-validate` y `authority-dictionary-import`, además del panel equivalente en **Entidades y menciones**.
- Completa la validación manual de `DISC-02`: confirma conflictos nominales explícitos, evidencia obligatoria, importación controlada, conservación de fichas existentes y reimportación idéntica sin nuevas escrituras.
- No agrega migraciones; la revisión continúa en `0040_discovery_grouping_continuity`.

## 0.75.1 — 2026-08-04

- Corrige el botón **Aplicar plantilla**: la confirmación `IMPORTAR` se valida después del envío y ya no depende de un botón circularmente deshabilitado dentro del formulario.
- Aclara en la interfaz y en el XLSX que `LISTAS` es una hoja auxiliar oculta utilizada por los desplegables.
- Neutraliza la identidad del proyecto descartable de validación de `CAT-01` para que no herede el nombre del Archivo Provincial de la Memoria de Chubut.
- No agrega migraciones; la revisión continúa en `0040_discovery_grouping_continuity`.

## 0.75.0 — 2026-08-04

- Implementa `CAT-01` con plantillas XLSX de cuatro hojas (`INSTRUCCIONES`, `ESTRUCTURA`, `CATALOGO`, `LISTAS`), campos descriptivos configurables, listas controladas y exportación vacía o del catálogo vigente.
- Agrega simulación completa con errores por hoja, fila y columna; detecta IDs repetidos, padres inexistentes, ciclos, niveles desconocidos, transiciones jerárquicas inválidas, estados incompatibles y valores descriptivos no aplicables.
- La aplicación requiere confirmación explícita y se ejecuta en una única transacción, con creación, actualización, movimiento, omisión y preservación del historial de revisiones.
- Incorpora los comandos `catalog-template-export`, `catalog-template-validate` y `catalog-template-import`, además del panel equivalente en la interfaz de Catálogo.
- Incluye una primera plantilla de prueba del fondo DIPPBA con 155 filas trazables, estructura más restrictiva para documentos y advertencias explícitas donde la fuente pública recuperada presenta elipsis o niveles no rotulados.
- No agrega migraciones; la revisión continúa en `0040_discovery_grouping_continuity`.

## 0.74.0 — 2026-08-04

- Implementa y valida `SEM-01` con corpus JSONL de consultas positivas, negativas y ambiguas, barrido de umbrales, métricas por tipo de consulta, falsos positivos y negativos, huellas reproducibles y comparación de informes.
- Implementa y valida `GRAPH-01` con aristas curvas y separadas para relaciones paralelas o inversas, etiquetas desplazadas, separación mínima de nodos y tooltips de procedencia y evidencia.
- Cierra `OCR-02` por decisión de alcance: los binarios idénticos ya se deduplican mediante SHA-256, mientras que copias catalográficamente distintas conservan su OCR propio.
- Programa `CAT-01`, `CAT-02` y `GRAPH-02` para plantillas distribuibles, roles archivísticos y estructura documental filtrable; mantiene `QA-01` junto con `OPS-02` en el cierre pre-release. No agrega migraciones; la revisión continúa en `0040_discovery_grouping_continuity`.

## 0.73.0 — 2026-08-03

- Cierra `DISC-01D` y el bloque `DISC-01` con un corpus JSONL que conserva texto exacto, offsets, familia, subtipo y procedencia.
- Agrega métricas micro, macro y por familia, registro de errores, huellas SHA-256 y comparación reproducible de informes.
- Incorpora `spacy_ner` como adaptador opcional con `modelo@versión` y el mismo contrato auditable del proveedor local.
- Registra la validación manual de `UX-03`. No agrega migraciones; la revisión continúa en `0040_discovery_grouping_continuity`.

## 0.72.0 — 2026-08-03

- Cierra `DISC-01C` con el validador final sobre cuatro grupos, nueve pertenencias, catorce acciones append-only y una continuidad desde un snapshot equivalente.
- Resuelve `UX-03`: separa revisar entidades, crear una entidad y Descubrimiento abierto; dentro de descubrimiento separa revisión, nueva corrida y agrupamiento o continuidad.
- Ordena `docs/HISTORIAL_DE_CAMBIOS.md` y `docs/operativos/IMPLEMENTACIONES_REALIZADAS.md`.
- No agrega migraciones; continúa `0040_discovery_grouping_continuity`.

## 0.71.2 — 2026-08-03

- Corrige el validador de `DISC-01C` para aceptar como origen de continuidad cualquiera de los dos snapshots controlados equivalentes de `Cuaderno del Delta`.
- La regresión de extremo a extremo usa el candidato duplicado, reproduciendo la selección real de la interfaz.
- Registra `UX-03` como pendiente crítico para reformular completamente la interfaz de Entidades y menciones y Descubrimiento abierto sin retirar funcionalidades.
- Bloquea `DISC-01D` hasta resolver `UX-03`.
- No agrega migraciones; la revisión continúa en `0040_discovery_grouping_continuity`.

## 0.71.1 — 2026-08-03

- Corrige la creación de grupos manuales en Streamlit: la selección del grupo nuevo se difiere al rerun siguiente, antes de instanciar el selector.
- Evita `StreamlitAPIException` por modificar `open_discovery_group_selected` después de crear su widget.
- Conserva el grupo que ya fue escrito antes del error y permite continuar la validación sin repetir migraciones, preparación ni agrupamiento automático.
- Agrega una regresión estática que impide volver a asignar directamente la clave del selector después de una escritura.
- No agrega migraciones; la revisión continúa en `0040_discovery_grouping_continuity`.

## 0.71.0 — 2026-08-03

- Registra como validada `DISC-01B` con nueve decisiones append-only, cuatro registros propios y conteos canónicos conservados.
- Implementa `DISC-01C` mediante la migración `0040_discovery_grouping_continuity`.
- Agrega grupos de candidatos, pertenencias y acciones append-only sin fusionar procedencias.
- Propone grupos por coincidencia exacta o normalizada entre corridas y permite agrupamiento y separación manuales.
- Agrega continuidad textual por proyección exacta única o nueva detección local, manteniendo visible el candidato obsoleto.
- Incorpora interfaz secundaria persistente, comandos de terminal y preparación y validación controladas sobre la copia existente.
- Conserva autoridades, menciones, relaciones, decisiones y registros propios sin escrituras canónicas nuevas durante agrupamiento o continuidad.

## 0.70.2 — 2026-08-03

- Agrega `.assistant/05_CRITERIOS_INTERFAZ.md` con jerarquía, divulgación progresiva, estabilidad durante reruns y lista de control obligatoria por versión.
- Reemplaza los expansores interactivos de descubrimiento abierto, configuración de perfil y revisión de candidatos por paneles persistentes con claves estables.
- Evita que cambiar la decisión, el destino de aceptación u otros controles cierre el panel activo.
- Ajusta `validate_open_discovery_disc01b.py` para validar estrictamente las ocho decisiones controladas y conservar decisiones adicionales append-only.
- La copia manual conserva una aceptación adicional de `manifestación`: nueve decisiones totales y cuatro registros propios, sin relaciones nuevas.
- No agrega migraciones; la revisión continúa en `0039_discovery_decisions`.

## 0.70.1 — 2026-08-03

- Registra como regla obligatoria que toda modificación relea y respete los principios de **Interfaz y formularios**.
- Agrega `UX-02` como revisión integral de complejidad acumulada después de los bloques funcionales activos y antes de v1.0.
- Establece que las guías entreguen todas las pruebas relevantes y `pytest --collect-only -q` en un único bloque encadenado.
- No cambia la lógica de `DISC-01B` ni el esquema; la revisión continúa en `0039_discovery_decisions`.

## 0.70.0 — 2026-08-03

- Registra como validada `DISC-01A`: 17 objetos recorridos, 13 candidatos totales y siete candidatos controlados correctos.
- Implementa `DISC-01B`, revisión humana y decisiones persistentes por familia semántica.
- Agrega la migración `0039_discovery_decisions` con `discovery_decisions` y `discovery_context_records`.
- Permite aceptar, rechazar, modificar o aplazar candidatos mediante historial append-only.
- Permite vincular referencias con autoridades existentes o crear explícitamente autoridades nuevas con estado `unreviewed`.
- Conserva tiempos, acontecimientos y acciones o procesos como registros propios y bloquea candidatos obsoletos.
- Agrega interfaz, comandos `discovery-decide`, `discovery-decisions` y `discovery-context-records`, preparación de la corrida existente y verificación final.
- Ninguna decisión crea relaciones automáticamente.

## 0.69.2 — 2026-08-03

- Corrige la verificación manual de `DISC-01A` para copias que ya contienen otros documentos aprobados.
- Agrega `scripts/validate_open_discovery_disc01a.py`, que valida exactamente el objeto controlado y admite candidatos adicionales legítimos.
- No cambia el detector, la persistencia ni la revisión de base `0038_open_discovery`.

## 0.69.1 — 2026-08-03

- Corrige la ejecución de `DISC-01A` sobre proyectos que ya contienen menciones: `EntityMention` usa `status`, no un campo inexistente `lifecycle_status`.
- Las menciones no rechazadas con offsets válidos impiden duplicar el mismo tramo; las rechazadas y las filas sin offsets no bloquean candidatos ni provocan errores.
- Mueve **Descubrimiento abierto** al final de **Entidades y menciones** y deja el panel cerrado por defecto.
- La corrida fallida se revierte completa y el perfil previamente guardado puede reutilizarse.
- No agrega migraciones; la revisión continúa en `0038_open_discovery`.

## 0.69.0 — 2026-08-03

- Implementa `DISC-01A`, contrato, persistencia y detección reproducible para descubrimiento abierto.
- Agrega la migración `0038_open_discovery` con perfiles, corridas inmutables y candidatos trazables.
- Incorpora el proveedor local determinista `local_deterministic@local_rules_v1` para actores, espacios, tiempos, acontecimientos, acciones o procesos y obras.
- Cada candidato conserva texto exacto, documento, página, objeto, offsets, revisión textual, confianza, método, versión, explicación y SHA-256 de parámetros.
- Reutiliza la autorización común `open_discovery`; por defecto solo recorre páginas aprobadas y bloquea perfiles cuya configuración ya no coincide con la autorización persistida.
- Agrega interfaz en **Entidades y menciones**, comandos de terminal para perfiles, corridas, candidatos y auditoría, y `create_open_discovery_validation_project.py`.
- No crea autoridades, menciones ni relaciones; las decisiones humanas quedan para `DISC-01B`.

## 0.68.1 — 2026-08-03

- Registra como validada `EX-01D` y cierra `EX-01` después de comprobar vista previa, adopción, rollback, segunda adopción, acuerdo bilateral posterior e integridad.
- Registra que `project_data` fue respaldada y migrada a `0037_exchange_state_adoptions` y que las pruebas OCR continúan visibles.
- Retira `EX-01` de pendientes y agrega el plan de referencia de `DISC-01`, dividido en contrato y detección, decisiones, deduplicación y evaluación.
- No agrega migraciones ni cambia la lógica funcional.

## 0.68.0 — 2026-08-03

- Implementa `EX-01D`, adopción explícita, respaldada y reversible de un estado editable divergente.
- Agrega la migración `0037_exchange_state_adoptions` con `exchange_state_adoptions` y `exchange_state_adoption_rollbacks` append-only.
- Incorpora paquetes completos de estado 1.0 dirigidos a una contraparte concreta, con manifiesto, checksums, estado editable y huella de la base documental.
- Agrega vista previa de solo lectura con impacto por sección, adopción transaccional con backup previo, verificación de SHA-256, integridad y claves foráneas.
- Incorpora rollback explícito que restaura el backup anterior, crea un backup de seguridad y conserva la auditoría de adopción y reversión.
- La adopción invalida simulaciones anteriores pero no crea parentesco ni una base común; el acuerdo bilateral continúa siendo una operación separada posterior a la igualdad de hashes.
- Agrega comandos de terminal, el panel **Reconciliar estados divergentes** y `create_state_adoption_validation_projects.py`.
- Registra como validada `EX-01C`: ambas copias conservaron el mismo acuerdo y un paquete posterior fue reconocido mediante `common_base_agreement` sin cambios.

## 0.67.0 — 2026-08-03

- Implementa `EX-01C`, creación bilateral y auditable de una nueva base común entre dos copias con estado editable idéntico.
- Agrega la migración `0036_exchange_common_base_agreements` y el modelo append-only `exchange_common_base_agreements`.
- Incorpora propuesta, aceptación y finalización mediante ZIP verificables con manifiestos JSON 1.0 y checksums SHA-256.
- Registra en ambas copias el mismo identificador, manifiesto y estado, con puntos de control locales propios y simulaciones anteriores obsoletas.
- Agrega reconocimiento posterior mediante `common_base_agreement`, comandos de terminal, formularios Streamlit y un generador de copias descartables.
- Rechaza estados divergentes, identidades incompatibles, cambios posteriores a la propuesta y registros repetidos sin modificar el corpus.
- `EX-01D`, adopción explícita de un estado divergente con backup y rollback, continúa pendiente.

## 0.66.0 — 2026-08-03

- Implementa `EX-01B`, recuperación de linaje separada de la aplicación de cambios y limitada a diagnósticos concluyentes, únicos y sin contradicciones.
- Agrega la migración `0035_exchange_lineage_recovery` con `exchange_lineage_cases`, `exchange_lineage_evidence`, `exchange_lineage_decisions` y `exchange_dry_runs.base_match_method`.
- Cada decisión conserva evidencia seleccionada, cadena de paquetes, punto y secuencia comparables, responsable, fundamento, origen y SHA-256 de parámetros.
- La recuperación vuelve obsoleta la simulación anterior; una reevaluación posterior reconoce la base mediante `recovered_lineage`.
- Agrega `exchange-lineage-recover`, `exchange-lineage-recoveries` y un formulario explícito en Intercambiar cambios.
- No modifica el corpus ni aplica eventos recibidos; `EX-01C` y `EX-01D` continúan pendientes.

## 0.65.0 — 2026-08-03

- Implementa `EX-01A`, diagnóstico de evidencia para paquetes de intercambio cuya base quedó `unmatched`.
- El diagnóstico es de solo lectura: no crea casos, decisiones, puntos de control, reportes persistentes ni cambios de contenido.
- Verifica el paquete recibido, la SQLite vigente y artefactos adicionales seleccionados explícitamente.
- Reconoce puntos de control exactos, aplicaciones anteriores, backups íntegros de la misma copia y cadenas continuas de paquetes.
- Clasifica el resultado como recuperable, ambiguo o insuficiente y explica evidencias concluyentes, de apoyo y rechazadas.
- Rechaza paquetes o backups alterados, proyectos diferentes, copias de origen incompatibles, ciclos y bifurcaciones.
- Agrega el comando `exchange-lineage-diagnose`, un panel de diagnóstico en Intercambio y `scripts/create_lineage_diagnostic_validation_projects.py`.
- No agrega migraciones; la revisión continúa en `0034_automatic_analysis_authorizations`.

## 0.64.2 — 2026-08-03

- Cierra `DATA-02` después de validar interfaz, auditoría por terminal, revisión de base, integridad SQLite y claves foráneas.
- Retira `DATA-02` de los pendientes activos y registra la evidencia final en implementaciones realizadas.
- Agrega la definición completa de `EX-01`: objetivo, contratos actuales, evidencia, persistencia prevista, fases, criterios de no regresión, pruebas mínimas y exclusiones.
- Fija `EX-01A` como primera fase funcional: diagnóstico de solo lectura para paquetes sin base común reconocida.
- No cambia la lógica ni agrega migraciones; la revisión continúa en `0034_automatic_analysis_authorizations`.

## 0.64.1 — 2026-08-03

- Corrige el botón **Buscar coincidencias** de sugerencias automáticas de menciones, que podía permanecer deshabilitado después de confirmar un alcance ampliado y escribir su fundamento.
- El botón queda siempre disponible; al pulsarlo, la validación común exige confirmación y fundamento antes de registrar la autorización o iniciar la búsqueda.
- Un envío incompleto muestra el error correspondiente y no escribe en la base.
- Agrega una regresión estática que impide reintroducir `disabled` en este recorrido.
- No agrega migraciones; la revisión continúa en `0034_automatic_analysis_authorizations`.

## 0.64.0 — 2026-08-03

- Completa la implementación de `DATA-02`, pendiente de validación manual: el alcance programático predeterminado para análisis automáticos es únicamente `approved` y ya no existe una ruta de compatibilidad que permita ampliarlo sin autorización.
- Los alcances ampliados requieren confirmación explícita, responsable y fundamento no vacío.
- Agrega `automatic_analysis_authorizations` mediante la migración `0034_automatic_analysis_authorizations`; cada autorización conserva política, tipo de análisis, estados, origen, destino y hash de parámetros.
- Registra de manera append-only los guardados de perfiles de exportación, perfiles semánticos y búsquedas automáticas de menciones.
- Impide previsualizar o ejecutar exportaciones y construir o consultar índices semánticos cuando la configuración vigente del perfil no coincide con una autorización persistida; los perfiles migrados deben guardarse nuevamente antes de su próximo uso.
- Agrega **Administrar y recuperar → Auditoría de análisis** y el comando `analysis-quality-audit`.
- Declara un contrato común para resúmenes, estadísticas, descubrimiento abierto, importaciones asistidas, herramientas LLM, RAG e integraciones futuras.
- Agrega `.assistant/06_RELEVO_NUEVA_CONVERSACION.md` y un procedimiento explícito de continuidad.

## 0.63.0 — 2026-08-03

- Cierra `DATA-01` después de validar la decisión conjunta de menciones, las reubicaciones agrupadas, la integridad SQLite y las claves foráneas.
- Agrega `analysis_quality.py` como política común para alcances de calidad en análisis automáticos.
- Los perfiles nuevos de exportación y búsqueda semántica usan solo páginas aprobadas; ampliar el alcance exige confirmación visible al guardar.
- La búsqueda automática de menciones muestra y valida el alcance de páginas antes de comenzar.
- Agrega `.assistant/05_FORMULARIOS_STREAMLIT.md` para impedir bloqueos circulares entre widgets y botones dentro de `st.form`.
- No modifica el esquema de base de datos.

## 0.62.1 — 2026-08-03

- Corrige el botón permanentemente deshabilitado en la decisión conjunta de menciones coincidentes.
- Elimina la dependencia circular entre un selector dentro de `st.form` y la propiedad `disabled` del botón, ya que los cambios internos del formulario no provocan rerender.
- Valida al enviar que exista una mención ganadora y muestra un error sin modificar la base cuando falta la selección.
- Registra una regresión automatizada para impedir que reaparezca el bloqueo.
- No cambia las operaciones de dominio ni agrega migraciones; la revisión continúa en `0033_export_exchange_lifecycle`.

## 0.62.0 — 2026-08-02

- Continúa `DATA-01` con revisión conjunta de tres o más menciones activas que convergen sobre el mismo fragmento.
- Obliga a elegir una única mención ganadora y registra `repair_group_duplicate_rejected`, `repair_group_duplicate_relocated` o `repair_group_duplicate_kept` sin resolver pares aislados.
- Agrega reubicaciones seguras agrupadas mediante `repair_group_relocation`, conservando una revisión individual por mención.
- Revalida revisiones, snapshots, texto, offsets y composición exacta antes de escribir; cualquier cambio cancela la transacción completa.
- Agrega `scripts/create_grouped_mention_validation_project.py` con un conjunto de tres menciones y tres reubicaciones seguras agrupables.
- Registra como validada la reconciliación entre fila e historial de 0.61.0.
- No agrega migraciones; la revisión continúa en `0033_export_exchange_lifecycle`.

## 0.61.0 — 2026-08-02

- Continúa `DATA-01` con reconciliación auditable de divergencias entre filas vigentes y snapshots de menciones.
- Muestra una comparación campo por campo y permite conservar la fila vigente mediante `repair_adopt_current_row`.
- Al restaurar el historial, registra primero la fila divergente con `repair_capture_divergent_row` y luego repone el snapshot mediante `repair_restore_snapshot`.
- Bloquea formularios obsoletos y valida objeto, entidad, proyecto, estado, procedencia, offsets y revisión textual antes de restaurar.
- Agrega `scripts/create_snapshot_divergence_validation_project.py` con dos rutas descartables independientes.
- No agrega migraciones; la revisión continúa en `0033_export_exchange_lifecycle`.

## 0.60.0 — 2026-08-02

- Continúa `DATA-01` con resolución manual y auditable de ubicaciones sin proyección única.
- Permite seleccionar un fragmento literal y una aparición concreta mediante `repair_manual_relocation`.
- Permite retirar una mención cuyo fragmento ya no aparece mediante `repair_mark_absent`, sin borrar entidad, texto histórico, offsets ni snapshots.
- Bloquea ausencia falsa, ubicaciones ocupadas, formularios obsoletos y divergencias entre fila y snapshot.
- Agrega `scripts/create_unresolved_mention_validation_project.py` con una ubicación ambigua y un fragmento ausente.
- No agrega migraciones; la revisión continúa en `0033_export_exchange_lifecycle`.

## 0.59.0 — 2026-08-02

- Continúa `DATA-01` con resolución auditable de duplicados entre una mención histórica y una mención ya ubicada en el texto vigente.
- Permite conservar la mención vigente y retirar la histórica, o conservar la histórica, retirar la vigente y reubicar la elegida.
- Registra `repair_duplicate_rejected` y `repair_duplicate_relocated` sin modificar snapshots anteriores.
- Exige revisiones vigentes, snapshots consistentes, una única contraparte activa, confirmación explícita, actor y fundamento.
- Bloquea automáticamente conjuntos con más de una contraparte o cambios posteriores a la evaluación.
- Agrega `scripts/create_duplicate_mention_validation_project.py` con dos rutas descartables independientes.
- No agrega migraciones; la revisión continúa en `0033_export_exchange_lifecycle`.

## 0.58.0 — 2026-08-02

- Continúa `DATA-01` con reparación auditable de menciones aceptadas o modificadas que quedaron sin entidad vinculada.
- Permite vincular una entidad activa existente mediante `repair_link_authority` o devolver la mención a pendiente mediante `repair_return_pending`.
- Exige revisión vigente, snapshot consistente, confirmación explícita, actor y nota; no crea entidades ni reescribe historial.
- Agrega `scripts/create_missing_authority_validation_project.py` con dos rutas descartables independientes.
- Corrige el generador de reubicación segura para seleccionar fragmentos completos en límites de palabra.
- No agrega migraciones; la revisión continúa en `0033_export_exchange_lifecycle`.

## 0.57.0 — 2026-08-02

- Cierra `UX-01` después de validar las seis fases de simplificación y legibilidad.
- Inicia `DATA-01` con una revisión centralizada de menciones activas en el mapa de relaciones.
- Clasifica reubicaciones seguras, ubicaciones ambiguas, duplicados, vínculos faltantes y divergencias de snapshots.
- Reubica una mención solo cuando la proyección es única, no existe otra mención activa en el mismo fragmento y la fila coincide con su último snapshot.
- Registra actor, nota y snapshot nuevo mediante la operación `repair_relocation`, sin reescribir revisiones anteriores.
- Agrega `scripts/create_mention_repair_validation_project.py` y regresiones para casos seguros, ambiguos, duplicados y divergentes.
- No agrega migraciones; la revisión continúa en `0033_export_exchange_lifecycle`.

## 0.56.0 — 2026-08-02

- Continúa `UX-01` con una revisión final de legibilidad y densidad.
- Sustituye las cuatro métricas angostas de los datos del objeto por tarjetas en dos columnas que permiten envolver “Sin revisar” y otros valores largos.
- Traduce los estados de ciclo de vida visibles del objeto a “Activo” y “Eliminado”.
- Organización del trabajo adopta un encabezado orientado a tareas, un resumen en tarjetas, tablas plegables y filtros de asignaciones desplegables.
- Exportar presenta el recorrido como configurar perfil, revisar contenido y crear archivo; mueve identificadores de registros y hashes a detalles técnicos.
- No agrega migraciones; la revisión continúa en `0033_export_exchange_lifecycle`.

## 0.55.0 — 2026-08-02

- Continúa `UX-01` en Revisión, Entidades y Grafo, sin cambiar contratos ni lógica de dominio.
- Revisión agrupa opciones de visualización, resumen documental, herramientas, estado de página, deshacer/rehacer y datos del objeto.
- Renombra las tareas del objeto con etiquetas orientadas a la acción: editar texto, orden y estructura, anotaciones, datos adicionales y menciones.
- Entidades separa búsqueda general, filtros, resumen y opciones de búsqueda de menciones; reemplaza “alias” por “nombres alternativos” en el recorrido principal.
- El grafo se presenta como mapa de relaciones y usa “elementos” y “vínculos”, conservando identificadores y pesos en detalles técnicos.
- Agrega regresiones de interfaz para las tres pantallas.
- No agrega migraciones; la revisión continúa en `0033_export_exchange_lifecycle`.

## 0.54.0 — 2026-08-02

- Continúa `UX-01` en Catálogo y Procesamiento, sin cambiar contratos ni lógica de dominio.
- Catálogo deja visible la búsqueda general y agrupa el resumen, los filtros por nivel/estado y los datos internos de la unidad en desplegables.
- Procesamiento usa lenguaje orientado a tareas, agrupa el resumen de avance y ubica la repetición forzada de versiones dentro de `Opciones avanzadas`.
- Buscar texto muestra `Buscar también dentro de las palabras` junto a `Cómo combinar las palabras`, conservando los parámetros internos `match_mode` y `partial_words`.
- Agrega pruebas de interfaz para la jerarquía progresiva de Catálogo, Procesamiento y búsqueda literal.
- No agrega migraciones; la revisión continúa en `0033_export_exchange_lifecycle`.

## 0.53.0 — 2026-08-02

- Continúa `UX-01` simplificando las dos búsquedas sin retirar filtros ni opciones técnicas.
- La búsqueda literal deja visibles solamente la consulta y la forma de combinar palabras; el resto queda en `Filtros opcionales`.
- El mantenimiento y los datos técnicos del índice literal quedan en desplegables separados.
- La búsqueda semántica se presenta como `Buscar por significado`, con opciones de consulta y estado técnico progresivos.
- La preparación del índice separa contenido incluido de configuración técnica y traduce CPU/CUDA en el recorrido visible.
- No agrega migraciones; la revisión continúa en `0033_export_exchange_lifecycle`.

## 0.52.0 — 2026-08-02

- Continúa `UX-01` con un recorrido de cinco etapas y once pasos.
- Agrega orientación contextual opcional y navegación anterior/siguiente entre secciones.
- Traduce el léxico principal de copias de seguridad en Administración.
- Colapsa el comando técnico de restauración y agrega etiquetas explicativas a JSONL y CSV.
- No agrega migraciones; la revisión continúa en `0033_export_exchange_lifecycle`.

## 0.51.0 — 2026-08-02

- Inicia `UX-01` con etiquetas de navegación orientadas a tareas y ayuda contextual por sección.
- Renombra el recorrido principal de intercambio con términos comprensibles: paquete de intercambio, simulación, punto de control y copia de seguridad.
- Traduce estados operativos de intercambio y separa los códigos internos en un desplegable de detalles técnicos.
- Actualiza Inicio para usar el mismo recorrido visible.
- Marca como resuelto y validado el bug de duplicación visual al archivar perfiles de exportación.
- No agrega migraciones; la revisión continúa en `0033_export_exchange_lifecycle`.

## 0.50.3 — 2026-08-02

- Cambia el ciclo de vida de perfiles de exportación a una secuencia previa al render: el callback del botón encola la acción y el siguiente rerun ordinario la procesa antes de construir la vista.
- Elimina los reruns explícitos a mitad del render para archivar, restaurar y eliminar perfiles.
- Conserva una nueva generación del selector después de cada operación.
- Agrega pruebas unitarias de encolado, confirmación y procesamiento sin rerun anidado.
- No agrega migraciones; la revisión continúa en `0033_export_exchange_lifecycle`.

## 0.50.2 — 2026-08-02

- Intentó limpiar el árbol visual mediante rerun del fragmento al archivar perfiles.
- La validación manual posterior demostró que Streamlit todavía podía conservar el formulario anterior junto con el nuevo.
- No produjo pérdida de datos ni de historial.

## 0.50.1 — 2026-08-02

- Corrige la duplicación y desincronización visual del perfil de exportación después de guardar, archivar, restaurar o eliminar.
- Separa el identificador lógico de selección de la clave del widget y cambia la generación del selector tras cada acción de ciclo de vida.
- Usa un rerun completo para reconstruir de manera atómica selector, pestañas y formulario, evitando restos de un fragmento anterior.
- Agrega regresiones para la selección posterior y el incremento de generación.
- No agrega migraciones; la revisión continúa en `0033_export_exchange_lifecycle`.

## 0.50.0 — 2026-08-02

- Reorganiza `docs/` en documentación operativa, referencia actual e historial clasificado por tipo.
- Deja un único documento en la raíz de `docs/`: `HISTORIAL_DE_CAMBIOS.md`, que funciona como mapa breve.
- Agrega `.assistant/` con instrucciones obligatorias de continuidad, interacción, documentación y pruebas para conversaciones futuras.
- Consolida `PENDIENTES_ACTIVOS.md` como única lista de trabajo abierto e `IMPLEMENTACIONES_REALIZADAS.md` como registro separado de funciones cerradas.
- Recupera pendientes de audiovisual local, transcripción, plugin de YouTube, imagen Docker, Drive, verdad terreno y cierre de v1.0.
- Incorpora como pendientes evaluados la simplificación de interfaz y léxico, importación de diccionarios de autoridades, herramientas CLI con LLM y RAG trazable.
- Agrega pruebas estructurales para impedir documentos sueltos en `docs/`, listas activas duplicadas y guías versionadas fuera del archivo histórico.
- No agrega migraciones ni cambia la lógica funcional; la revisión continúa en `0033_export_exchange_lifecycle`.

## 0.49.2 — 2026-08-02

- Consolida `docs/PENDIENTES_ACTIVOS.md` como lista operativa breve con estados e identificadores estables.
- Marca la migración 0027 y sus regresiones con autoridades, menciones y relaciones como resueltas y validadas en 0.49.1.
- Registra explícitamente la recuperación asistida de linaje y la creación de una base común verificada como pendiente independiente de la resolución de campos.
- Registra la desincronización visual del perfil de exportación después de archivar, restaurar o eliminar, sin confundirla con pérdida de datos.
- Define una estrategia de pruebas por subsistema afectado, transversales, recopilación completa y suite monolítica local, conservando toda la cobertura.
- No agrega migraciones ni cambia el comportamiento de la aplicación; la revisión continúa en `0033_export_exchange_lifecycle`.

## 0.49.1 — 2026-08-01

- Corrige el bloqueo circular de las confirmaciones dentro de formularios para archivar, restaurar o limpiar bundles y para archivar, restaurar o eliminar perfiles de exportación.
- Mantiene desactivadas solamente las acciones que dependen de un estado operativo externo; la confirmación se valida al pulsar el botón y nunca habilita escrituras mediante `Enter`.
- Agrega una prueba AST que impide volver a usar una casilla `confirm_*` para deshabilitar el propio botón de envío del formulario.
- Define explícitamente como pendiente el descubrimiento abierto y revisable de actores, espacios, tiempos y acontecimientos, diferenciándolo del rastreo por diccionario de autoridades ya conocidas.
- Documenta actualización y continuación de la validación en `docs/ACTUALIZACION_Y_PRUEBA_0.49.1.md`.

## 0.49.0 — 2026-08-01

- Corrige la vista de bundles sin base común con varios eventos revisables: inicializa el agrupamiento por evento y presenta todos los eventos y campos sin `NameError`.
- Explica globalmente el linaje no reconocido y deshabilita las decisiones masivas incompatibles con creaciones sin una base común verificable.
- Detalla por qué un dry-run quedó `stale`, incluyendo secuencia evaluada, secuencia vigente y eventos locales posteriores.
- Permite archivar, restaurar y limpiar entradas de bundles no aplicados; las entradas archivadas quedan fuera de la vista operativa normal sin perder auditoría.
- Hace persistente la confirmación de exportación con ruta, formato, registros, caracteres, tamaño, SHA-256 y descarga directa.
- Permite archivar, restaurar y eliminar perfiles de exportación con confirmación explícita, mostrando las exportaciones históricas vinculadas y conservándolas después de eliminar el perfil.
- Agrega la migración `0033_export_exchange_lifecycle` para el ciclo de vida de perfiles y dry-runs de intercambio.
- Documenta actualización y validación en `docs/ACTUALIZACION_Y_PRUEBA_0.49.0.md`.
- 273 pruebas automatizadas recopiladas.

## 0.48.0 — 2026-07-31

- Convierte las tres entradas manuales del rebase —texto conflictivo, fragmento de mención y valor JSON de atributo— en formularios independientes con `enter_to_submit=False` y botón explícito.
- Conserva la decisión manual confirmada en el estado de sesión y recalcula la vista previa únicamente después de pulsar su botón; escribir o presionar Enter no incorpora la resolución.
- Oculta globalmente las instrucciones automáticas `Press Enter…` / `Press Ctrl+Enter…` de Streamlit, que contradecían la política de acciones explícitas.
- Amplía las pruebas de arquitectura para comprobar que las entradas manuales están dentro de formularios no enviables por teclado y que la política visual se monta en toda la aplicación.
- Actualiza “Pendientes y mejoras” distinguiendo con precisión los bloques resueltos, validados, parciales y todavía abiertos.
- Documenta actualización y prueba en `docs/ACTUALIZACION_Y_PRUEBA_0.48.0.md`.
- No agrega migración; la revisión continúa en `0032_page_quality_assessments`.
- 264 pruebas automatizadas recopiladas.

## 0.47.0 — 2026-07-31

- Permite rebases repetidos sobre candidatas ya usadas (`A → B → A → B`) sin violar la unicidad histórica de los objetos OCR.
- Conserva la procedencia de los vínculos liberados en `historical_source_extracted_object_ids` y audita `rebase_source_release` y `source_links_released`.
- Proyecta menciones históricas sobre el texto vigente mediante bloques iguales o una única coincidencia literal, sin inventar correspondencias ambiguas.
- Impide crear o incorporar una segunda mención sobre el mismo fragmento vigente aunque los offsets pertenezcan a otra revisión textual.
- Agrega el diagnóstico `graph_duplicate_mention` para duplicados históricos ya existentes.
- Corrige el formulario anidado de edición de menciones y amplía la prueba global a cualquier llamada `.form(...)`.
- Renombra el control de incorporación como **Estado que se asignará a las nuevas menciones**.
- Documenta actualización y prueba en `docs/ACTUALIZACION_Y_PRUEBA_0.47.0.md`.
- No agrega migración; la revisión continúa en `0032_page_quality_assessments`.
- 261 pruebas automatizadas recopiladas.

## 0.46.0 — 2026-07-31

- Monta el contenedor raíz dentro del propio fragmento y elimina el uso operativo de un `st.empty` externo, evitando restos visuales al navegar después de un rerun local de rebase.
- Exige `enter_to_submit=False` en los 39 formularios de la aplicación y agrega una prueba de arquitectura que impide reintroducir envíos por `Enter`.
- Agrega en Revisión una pestaña **Atributos** que muestra el `current_attributes_json` completo del objeto seleccionado.
- Aplica por defecto el filtro de páginas `approved` a la búsqueda transversal y al escaneo automático de menciones; Entidades permite ampliar explícitamente los estados incluidos.
- Revalida las coincidencias al incorporarlas usando el mismo filtro de calidad con el que fueron buscadas.
- Documenta actualización y prueba en `docs/ACTUALIZACION_Y_PRUEBA_0.46.0.md`.
- No agrega migración; la revisión continúa en `0032_page_quality_assessments`.
- 258 pruebas automatizadas recopiladas.

## 0.45.0 — 2026-07-31

- Corrige el bloqueo circular del botón final de rebase dentro de formularios: la confirmación se valida al enviar y nunca controla su propio botón antes del envío.
- Distingue atributos de procedencia, indicadores estructurales transitorios y atributos especializados humanos.
- Conserva automáticamente valores especializados únicos e iguales; presenta conflictos cuando difieren entre objetos o frente a la candidata.
- Permite conservar un valor existente, no trasladar el atributo o escribir un JSON manual válido y confirmado.
- Audita `manual_attribute_resolution_count`, métodos de resolución y cantidad de atributos especializados.
- Incluye `scripts/create_rebase_validation_project.py` para probar de forma descartable proyección estructural y convergencia de atributos.
- Documenta el flujo en `docs/REBASE_ATRIBUTOS_Y_PRUEBA_GUIADA_0.45.0.md`.
- No agrega migración; la revisión continúa en `0032_page_quality_assessments`.
- 252 pruebas automatizadas recopiladas.

# Changelog

## 0.44.0 — 2026-07-31

- Renderiza la vista activa como fragmento independiente para que las interacciones locales no reconstruyan la barra lateral, el encabezado ni las demás vistas.
- Distingue explícitamente entre rerun local de la vista y rerun completo por navegación entre modos.
- Centraliza ambos ámbitos en `ui_navigation.py` y prohíbe mediante una prueba de arquitectura las llamadas directas a `st.rerun` desde los módulos de interfaz.
- Agrupa en formularios las confirmaciones finales de rebase, conservación de edición, desvinculación archivística y aplicación o resolución masiva de bundles.
- Mantiene abierto el panel de rebase durante las recalculaciones de sus controles.
- Agrega resolución manual de objetos anotados con proyección estructural débil o ambigua, mostrando similitud textual y solapamiento posicional por bloque candidato.
- Revalida el destino elegido contra la candidata vigente y registra `manual_object_projection` en la revisión append-only de página.
- Conserva el aislamiento atómico de vistas incorporado en 0.42.0 y la persistencia de pestañas de 0.36.1/0.40.0.
- Documenta la política en `docs/CONTINUIDAD_INTERACCION_STREAMLIT_0.44.0.md`.
- No incorpora migraciones; la revisión permanece en `0032_page_quality_assessments`.
- 246 pruebas automatizadas.

## 0.43.0 — 2026-07-31

- Usa el snapshot editable activo como fuente de verdad para el rebase y deja de bloquear por la mera existencia de divisiones, uniones, reordenamientos, deshacer o rehacer históricos.
- Conserva íntegramente el historial estructural y registra cuántas acciones fueron absorbidas por el nuevo rebase.
- Agrega resolución asistida de partes documentales, estados de revisión y tipos de objeto incompatibles cuando varios objetos convergen en un bloque candidato.
- Revalida las decisiones de metadatos contra las opciones visibles y las registra en la revisión append-only de página.
- Traslada todos los comentarios y deduplica etiquetas idénticas sin borrar las copias asociadas a los objetos históricos retirados.
- Mantiene bloqueadas las incompatibilidades estructurales reales, los conflictos textuales o de menciones y los cambios concurrentes.
- Documenta el procedimiento en `docs/REBASE_ESTRUCTURA_Y_METADATOS_0.43.0.md`.
- No incorpora migraciones; la revisión permanece en `0032_page_quality_assessments`.
- 240 pruebas automatizadas.

## 0.42.0 — 2026-07-31

- Agrega resolución manual asistida de correcciones humanas que se superponen con cambios distintos de una candidata OCR.
- Permite conservar la candidata, reaplicar la corrección humana o escribir un texto exacto para el tramo conflictivo.
- Revalida cada decisión contra los fragmentos humano y candidato visibles y recalcula después las menciones y offsets.
- Registra cantidad y métodos de resoluciones textuales en la revisión append-only de página.
- Centraliza todas las navegaciones entre vistas mediante `request_app_view`.
- Renderiza cada vista completa dentro de un contenedor raíz atómico identificado por modo, evitando árboles visuales anteriores superpuestos e interactivos.
- Mantiene bloqueadas las acciones estructurales previas y los metadatos incompatibles.
- Documenta el procedimiento en `docs/REBASE_CONFLICTOS_TEXTUALES_Y_NAVEGACION_0.42.0.md`.
- No incorpora migraciones; la revisión permanece en `0032_page_quality_assessments`.
- 237 pruebas automatizadas.

## 0.41.0 — 2026-07-31

- Agrega resolución manual asistida de conflictos de menciones dentro del rebase de edición.
- Busca coincidencias exactas o normalizadas en todos los bloques candidatos antes de declarar perdida una mención.
- Permite elegir una sugerencia, seleccionar un fragmento exacto manualmente o rechazar explícitamente un duplicado.
- Conserva intactas las autoridades canónicas y sus relaciones; el rechazo afecta únicamente a la mención textual y queda auditado.
- Registra `rebase_relocate_manual` y `rebase_reject_conflict`, además de conteos de decisiones manuales en la revisión de página.
- Mantiene bloqueados los conflictos textuales, estructurales y de metadatos que todavía no admiten una resolución segura.
- Documenta el procedimiento en `docs/RESOLUCION_CONFLICTOS_REBASE_0.41.0.md`.
- No incorpora migraciones; la revisión permanece en `0032_page_quality_assessments`.
- 229 pruebas automatizadas.

## 0.40.0 — 2026-07-31

- Agrega un rebase transaccional de tres vías entre la extracción anterior, la edición humana y una nueva candidata OCR.
- Traslada menciones, comentarios, etiquetas, estados de revisión y partes documentales cuando el destino es inequívoco.
- Muestra una vista previa y bloquea toda escritura ante cambios superpuestos, menciones no relocalizables o conflictos estructurales.
- Conserva los objetos anteriores como retirados y registra revisiones append-only de página, objetos y menciones.
- Reconoce `rebase` en el intercambio offline como estrategia `three_way_text_rebase`.
- Corrige globalmente la persistencia de pestañas después de navegaciones programáticas y reruns posteriores.
- Documenta el procedimiento en `docs/REBASE_EDICION_OCR_0.40.0.md`.
- No incorpora migraciones; la revisión permanece en `0032_page_quality_assessments`.
- 226 pruebas automatizadas.

## 0.39.0 — 2026-07-30

- Integra en el control automático una primera revisión estructural de ordinales legales y casilleros de formularios.
- Detecta secuencias compatibles con ordinales de un dígito leídos como números de dos cifras y muestra una lectura posible sin modificar el texto OCR.
- Reconoce controles `checkbox`/`radio` preservados en el HTML de Surya, símbolos explícitos y marcas pequeñas próximas a rótulos como candidatos `marked`, `unmarked` o `indeterminate`, conservando el método de asociación.
- Explica en la interfaz que los estados son candidatos, que requieren revisión visual y que los casilleros vacíos sin objeto OCR no pueden inferirse con seguridad.
- Actualiza el algoritmo append-only de calidad a `page_quality_v2`; las evaluaciones históricas `page_quality_v1` permanecen intactas y pueden recalcularse bajo demanda.
- Documenta evidencia, reglas, límites y próximos pasos en `docs/CONTROL_ESTRUCTURAL_OCR_0.39.0.md`.
- No incorpora migraciones; la revisión permanece en `0032_page_quality_assessments`.
- 221 pruebas automatizadas.

## 0.38.1 — 2026-07-30

- Corrige la resolución del dispositivo auxiliar de Surya para que un perfil CPU no pruebe CUDA/cuDNN del host cuando `surya_torch_device` permanece en `auto`.
- Comparte una única regla entre diagnóstico y ejecución, mantiene la configuración híbrida VLM-GPU/auxiliares-CPU y aísla las pruebas del hardware real.
- No incorpora migraciones; la revisión permanece en `0032_page_quality_assessments`.
- 216 pruebas automatizadas.

## 0.38.0 — 2026-07-30

- Documenta en `docs/EVALUACION_SURYA_OCR_0.38.0.md` la prueba real de Surya sobre seis páginas con deterioro, mala orientación, manuscritos y formularios, incluidos resultados cualitativos, tiempos, uso de GPU, limitaciones y decisión de diseño.
- Convierte a Surya en el backend preferido del perfil `config/extraction.yaml`, siempre como candidata revisable y sin modificar la selección canónica automáticamente.
- Mantiene intactos los perfiles de proyectos existentes: la adopción del nuevo perfil preferido se realiza mediante una copia explícita, con respaldo previo, para no sobrescribir personalizaciones locales.
- Agrega `config/extraction_docling_es.yaml` como fallback general de Docling/Tesseract para instalaciones sin runtime Surya o fallos durante la ejecución.
- Resuelve el perfil efectivo antes de extraer; si Surya no está disponible, usa el fallback e informa el motivo. Si falla durante un documento, conserva el intento fallido y reintenta solo ese documento con el fallback.
- Mantiene vLLM activo entre corridas mediante `surya_keep_server: true`, evitando repetir la carga y el warmup del modelo en cada trabajo.
- Agrega `archive-workbench surya-server-status` y `archive-workbench surya-server-stop` para inspeccionar y liberar explícitamente los contenedores persistentes y su VRAM.
- Automatiza la configuración híbrida validada: VLM en GPU mediante vLLM/Docker, modelos auxiliares Torch en CPU, y limpieza de `LD_LIBRARY_PATH` dentro del subproceso Surya.
- Corrige `extraction-doctor` para diagnosticar por separado el backend VLM y los modelos auxiliares, sin confundir un conflicto local de cuDNN con la disponibilidad real de la ruta GPU.
- Actualiza la interfaz para explicar el servidor persistente, la reserva de VRAM, la configuración híbrida y el fallback configurado.
- Registra como pendientes específicos la semántica de casilleros, las alertas para ordinales legales y un benchmark con verdad terreno/CER/WER.
- No incorpora migraciones; la revisión permanece en `0032_page_quality_assessments`.
- 214 pruebas automatizadas.

## 0.37.1 — 2026-07-30

- Corrige la incompatibilidad de metadatos entre Archive Workbench y `surya-ocr==0.22.1`: el rango base de Pillow admite 10.2–12.x y Surya queda fijado exactamente a la versión integrada.
- Instala Surya por defecto en un entorno separado `.venv-surya`, evitando que Pillow, Torch y Transformers del backend experimental alteren el entorno principal de la aplicación.
- Agrega `scripts/install_surya_runtime.sh` con modo `--dry-run`, instalación real y `pip check`.
- Configura los perfiles Surya para usar `.venv-surya/bin/surya_ocr` y resuelve rutas relativas o con `~` antes de ejecutar el subproceso.
- Mejora el diagnóstico cuando falta el ejecutable y conserva la consulta de versión desde el Python hermano del runtime aislado.
- Agrega una regresión de empaquetado que exige la intersección con Pillow 10.4, el pin exacto de Surya, el script aislado y su exclusión de Git.
- No incorpora migraciones; la revisión permanece en `0032_page_quality_assessments`.
- 210 pruebas automatizadas.

## 0.37.0 — 2026-07-30

- Incorpora `surya_cli` como backend experimental de OCR, layout y orden de lectura, siempre como corrida candidata y sin selección automática.
- Normaliza bloques Surya a tipos configurables, texto visible, HTML crudo, confianza, geometría, etiquetas y orden de lectura.
- Agrega el perfil `config/extraction_surya_es.yaml` y el extra opcional `surya` fijado a la rama 0.22.
- Ejecuta Surya por CLI, permitiendo usar el mismo entorno o un entorno virtual separado mediante una ruta absoluta a `surya_ocr`.
- Mapea `device: cuda` a vLLM con NVIDIA/Docker, `device: cpu` a llama.cpp y `device: auto` a selección automática.
- Agrega un único fallback conservador desde la ruta acelerada a llama.cpp en CPU, con diagnóstico completo en `raw/surya.log`.
- Amplía `extraction-doctor` para verificar el ejecutable, el servidor configurado o los prerrequisitos locales de GPU/CPU sin exigir Tesseract a un perfil Surya.
- La interfaz explica qué backend solicitará y conserva la política de candidatas revisables.
- No incorpora migraciones; la revisión permanece en `0032_page_quality_assessments`.
- 208 pruebas automatizadas.

## 0.36.1 — 2026-07-30

- Hace persistentes todas las pestañas de la aplicación mediante navegación con estado: los reruns de Streamlit ya no devuelven a la primera pestaña después de guardar, cambiar un control o ejecutar una operación.
- Aplica la misma política en Procesamiento, Trabajo, Revisión, Catálogo, Entidades, Grafo, Exportar, Búsqueda semántica y Administración, con una única implementación compartida.
- Mantiene abierta **Ejecutar** y conserva la operación elegida después de preparar páginas, extraer texto o cambiar controles del formulario.
- En **Extraer texto**, muestra por documento el tratamiento del derivado vigente y, por separado, la transformación adicional del perfil OCR.
- Aclara que `image_variant: original` significa que el perfil no agrega una segunda transformación: el OCR usa el derivado vigente tal como fue preparado.
- Eleva el requisito mínimo a Streamlit 1.55 para usar pestañas con estado nativo (`key` y `on_change="rerun"`).
- No incorpora migraciones; la revisión permanece en `0032_page_quality_assessments`.
- 202 pruebas automatizadas.

## 0.36.0 — 2026-07-30

- Corrige la presentación del control automático para que sus puntajes internos no se interpreten como exactitud OCR.
- Distingue en la interfaz el estado asignado por el equipo del diagnóstico heurístico automático.
- Muestra indicadores compactos de imagen y extracción, alertas, sugerencias, versión del algoritmo, fecha y responsable incluso cuando no se detectan alertas.
- Aclara expresamente que la ausencia de alertas no demuestra que el texto reconocido sea correcto.
- Agrega un primer flujo de preprocesamiento conservador en **Procesamiento → Ejecutar → Preparar páginas**.
- Permite generar derivados OCR reproducibles sin cambios, con escala de grises y autocontraste, binarización Otsu o reducción de ruido mediana y autocontraste.
- Mantiene intactos el original y la previsualización; el tratamiento se aplica únicamente al derivado usado por las extracciones posteriores.
- Reactiva una corrida de preprocesamiento equivalente cuando ya existe, en lugar de duplicarla, y muestra el tratamiento vigente en el inventario y en `preprocessing-status`.
- Advierte cuando un perfil de extracción va a encadenar otra variante de imagen sobre un derivado que ya fue tratado.
- Detiene con una explicación los tratamientos que excederían el límite seguro de memoria de Pillow en rasteres grandes; la ruta sin cambios conserva pyvips.
- Reconstruye la documentación técnica en un único archivo `docs/DISENO_Y_PLAN_DE_IMPLEMENTACION.md`, con las secciones 1–32 completas y ordenadas.
- No agrega migración; la revisión permanece en `0032_page_quality_assessments`.
- 197 pruebas automatizadas.

## 0.35.0 — 2026-07-29

- Agrega control automático y explicable de calidad por página de extracción.
- Evalúa brillo, contraste, bordes débiles, ruido, cantidad de texto, fragmentación, objetos mínimos, símbolos sospechosos y solapamiento de bounding boxes.
- Clasifica cada evaluación como `clear`, `attention` o `critical`, con puntaje, indicadores medidos y sugerencias conservadoras; nunca aprueba, selecciona ni adopta una extracción automáticamente.
- Las nuevas extracciones reciben una evaluación inicial; las corridas anteriores pueden evaluarse desde **Procesamiento → Selección canónica** o con `page-quality-assess`.
- Conserva evaluaciones sucesivas y distingue cuál es la vigente mediante `extraction_page_quality_assessments`.
- Incorpora la migración `0032_page_quality_assessments`, que crea la tabla sin modificar extracciones, selecciones, textos ni historiales existentes.
- Elimina las migraciones implícitas de todos los comandos de trabajo, consulta, intercambio y apertura de la interfaz. Solo `db-upgrade` puede cambiar la revisión de la base.
- Los comandos que requieren el esquema actual se detienen con un mensaje explícito; `db-status` y los backups continúan permitiendo inspeccionar o preservar una revisión anterior.
- Agrega regresiones para la política de migración explícita, actualización desde `0031`, evaluación automática al extraer y versionado de controles de calidad.
- Revisión de base `0032_page_quality_assessments`.
- 192 pruebas automatizadas.

## 0.34.5 — 2026-07-29

- Conserva al aplicar bundles las operaciones originales de revisión de objetos (`import`, `edit`, `source_replaced`, `undo`, `redo`, entre otras), en lugar de reemplazarlas por `create` o `exchange_apply`.
- Transporta las acciones de página completas, incluidos snapshots, secuencia, objeto seleccionado, estado y marcas de deshacer/rehacer.
- La migración `0031_page_action_exchange` registra acciones futuras y agrega eventos para acciones históricas que todavía no estaban representadas en el intercambio.
- Las acciones históricas compartidas se reconocen como duplicadas; las acciones nuevas se aplican sin decisiones artificiales.
- Incluye las acciones de página en el hash del estado compartido para que la disponibilidad de deshacer/rehacer forme parte de la consistencia entre copias.
- Corrige cadenas dentro de un mismo bundle como `edit → undo → redo`, que ahora se evalúan y aplican en orden.
- `project-backup-create` deja de migrar silenciosamente la base antes de copiarla: el backup conserva la revisión existente y la informa en su manifiesto.
- Agrega regresiones end-to-end para acciones creadas antes de `0031`, historial exacto de revisiones, undo/redo e inmovilidad de la revisión al crear backups.
- Revisión de base `0031_page_action_exchange`.
- 185 pruebas automatizadas.

## 0.34.4 — 2026-07-29

- Corrige los conflictos falsos producidos al transportar objetos retirados por una adopción OCR cuando su revisión base histórica no estaba registrada.
- La migración `0030_source_replaced_exchange` instala un trigger que representa `source_replaced` exclusivamente como `lifecycle_status: active → deleted`.
- Completa, sin generar eventos de intercambio, las revisiones base que pueden reconstruirse de forma segura: objetos intactos en revisión 1 y objetos cuya primera revisión fue `source_replaced`.
- Normaliza al exportar los eventos defectuosos ya creados con `0.34.0`–`0.34.3`, de modo que no sea necesario repetir las decisiones realizadas antes de actualizar.
- Agrega una regresión completa desde `0029`: evento histórico defectuoso, migración, reexportación, dry-run sin conflictos y aplicación en la copia receptora.
- Revisión de base `0030_source_replaced_exchange`.
- 182 pruebas automatizadas.

## 0.34.3 — 2026-07-29

- Permite transportar mediante bundles los cambios de selección OCR, la adopción segura de candidatas y las resoluciones que conservan la edición humana.
- Exige que la copia receptora ya contenga las corridas, páginas y objetos OCR referenciados; el dry-run deja el bundle en revisión si falta alguna dependencia y explica que primero debe compartirse una copia física completa.
- Simula en orden varias decisiones sucesivas sobre una misma página dentro del mismo bundle, por ejemplo adoptar una candidata, volver a otra selección y conservar las correcciones existentes.
- Conserva en la copia receptora las notas y el tipo de decisión registrados en el historial de selección y de página. Los eventos creados con `0.34.0`–`0.34.2` se enriquecen al exportarlos, sin exigir repetir las acciones.
- Mantiene abierta **Selección canónica** después de cambiar una selección, adoptar una candidata o resolver manualmente una página.
- No incorpora migraciones: la revisión de base continúa siendo `0029_extraction_candidate_history`.
- 180 pruebas automatizadas.

## 0.34.2 — 2026-07-29

- Mantiene abierta la pestaña **Selección canónica** después de cambiar una selección, adoptar una candidata o resolver manualmente una página.
- Evita que el rerun de Streamlit devuelva a la persona usuaria a **Inventario** después de esas acciones.
- No incorpora migraciones ni modifica el esquema de datos de `0.34.1`.

## 0.34.1 — 2026-07-29

- Corrige seis pruebas de migración histórica desde las revisiones `0012` a `0017`.
- Los fixtures ya no intentan consultar con el ORM actual la columna `editable_pages.revision_number` antes de que exista.
- El estado editable histórico se siembra con las columnas reales de cada esquema antiguo y luego se valida su actualización hasta `0029_extraction_candidate_history`.
- No modifica la migración `0029`, el esquema final, los datos de usuario ni el funcionamiento de la interfaz.
- Mantiene 177 pruebas automatizadas: los 44 tests de intercambio pasan, incluidos los seis casos corregidos.

## 0.34.0 — 2026-07-29

- Agrega comparación por página entre la selección OCR vigente y cualquier corrida candidata completada, con texto, imagen, bounding boxes, objetos, caracteres y diferencias línea por línea.
- Mantiene separadas tres decisiones: seleccionar una extracción, adoptarla como base editable y aprobar su calidad.
- Permite adoptar automáticamente una candidata solo cuando la página no contiene correcciones, anotaciones, revisiones ni operaciones humanas.
- Conserva los objetos OCR anteriores como historial en lugar de eliminarlos al adoptar una base nueva.
- Incorpora una resolución manual simple para páginas trabajadas: conserva íntegramente la edición existente, vincula la candidata elegida y registra qué objetos se mantuvieron y cuáles no se importaron.
- Agrega historial append-only para cambios de selección OCR y estado general de la página editable.
- Integra selección, inicialización, ediciones, acciones estructurales, comentarios, etiquetas, entidades, revisión, deshacer y rehacer en una única cronología de página.
- Marca inmediatamente una página como desactualizada cuando cambia su selección, sin reemplazar ni mezclar correcciones.
- Incluye selección y procedencia OCR en el hash de checkpoints.
- Bloquea bundles offline que intenten transportar cambios de base OCR sin las corridas y páginas necesarias; exige una nueva copia física compartida y un checkpoint común.
- Migración `0029_extraction_candidate_history`.
- 177 tests automatizados.

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
