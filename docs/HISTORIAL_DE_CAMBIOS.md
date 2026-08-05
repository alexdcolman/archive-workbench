# Historial de cambios y mapa documental
Este es el único documento en la raíz de `docs/`. Resume la evolución del proyecto y señala dónde encontrar el detalle sin duplicarlo.

## Documentación vigente
- [Pendientes activos](operativos/PENDIENTES_ACTIVOS.md): único inventario de tareas abiertas.
- [Implementaciones realizadas](operativos/IMPLEMENTACIONES_REALIZADAS.md): funciones cerradas y validaciones.
- [Actualización actual](operativos/ACTUALIZACION_ACTUAL.md): instalación y pruebas de la versión vigente.
- [Estrategia de pruebas](operativos/ESTRATEGIA_DE_PRUEBAS.md).
- [Guía de prueba piloto](operativos/GUIA_PRUEBA_PILOTO.md).
- [Arquitectura y modelo actual](referencia/ARQUITECTURA_Y_MODELO_ACTUAL.md).
- [Plan de recuperación de linaje EX-01](referencia/RECUPERACION_LINAJE_EX_01.md).
- [Plan de descubrimiento abierto DISC-01](referencia/DESCUBRIMIENTO_ABIERTO_DISC_01.md).
- [Formato de importación DISC-02](referencia/IMPORTACION_DICCIONARIOS_DISC_02.md).

## Versiones recientes — más reciente primero

### 0.78.0 — 2026-08-05
- Implementa `OCR-01A`: orientación conservadora, deskew acotado y eliminación controlada de líneas o marcos sobre derivados OCR.
- Conserva originales y previsualizaciones sin cambios y agrega comparación visual con el derivado OCR y la máscara diagnóstica.
- Registra análisis y transformaciones por página mediante la migración aditiva `0042_preprocessing_geometry_trace`.
- Incorpora y valida manualmente una base descartable con cinco casos geométricos controlados: rotación de 90°, deskew de -3°, marco removible, línea que cruza texto y baja confianza. Los originales permanecen intactos y `OCR-01A` queda cerrada.

### 0.77.0 — 2026-08-05
- Implementa conjuntamente `CAT-02` y `GRAPH-02`: roles productores y gestores controlados, historial, períodos, evidencia, procedencia y capas archivísticas o documentales separadas.
- Agrega foco sobre autoridades, unidades, documentos o partes; filtros de niveles, profundidad y límite de nodos; y exportación explicable en JSON, CSV y GraphML.
- Muestra flechas en los vínculos dirigidos, conserva sin flecha las entidades compartidas, corrige la dirección y etiqueta de la pertenencia documental y mantiene disponible la distancia después de aplicar filtros.
- Incorpora la migración aditiva `0041_catalog_authority_roles_graph_layers`; las relaciones existentes permanecen como `analytical`.
- La validación automatizada y manual queda completa: nueve nodos, doce aristas, cero inconsistencias, flechas y filtros correctos; `CAT-02` y `GRAPH-02` quedan cerrados.

### 0.76.0 — 2026-08-04
- Implementa `DISC-02`: formato JSON versionado, esquema, ejemplo, simulación, resolución de duplicados, evidencia obligatoria y aplicación transaccional de autoridades, alias y relaciones.
- Valida manualmente el conflicto nominal sin resolver, el rechazo de relaciones sin evidencia, la conservación de una ficha reutilizada y la reimportación idéntica sin nuevas escrituras; `DISC-02` queda cerrado.
- Agrega la guía vigente [`IMPORTACION_DICCIONARIOS_DISC_02.md`](referencia/IMPORTACION_DICCIONARIOS_DISC_02.md).
- No agrega migración; continúa `0040_discovery_grouping_continuity`.

### 0.75.1 — 2026-08-04
- Corrige el flujo de confirmación de la importación XLSX para que `IMPORTAR` se compruebe después de pulsar un botón habilitado.
- Documenta que `LISTAS` es una hoja auxiliar oculta y neutraliza el nombre del proyecto descartable de validación.
- No agrega migraciones; continúa `0040_discovery_grouping_continuity` y `CAT-01` permanece abierto solo para repetir los pasos afectados.

### 0.75.0 — 2026-08-04
- Implementa `CAT-01` con plantillas XLSX documentadas, estructura jerárquica distribuible, exportación vacía o del catálogo vigente, simulación detallada e importación transaccional con confirmación explícita.
- Incorpora comandos de terminal, interfaz de Catálogo y una primera plantilla pública DIPPBA de 155 filas con fuentes y advertencias sobre ramas parciales.
- No agrega migraciones; continúa `0040_discovery_grouping_continuity` y el bloque queda abierto únicamente para validación manual.

### 0.74.0 — 2026-08-04
- Implementa y valida la calibración semántica reproducible y la comparación de informes por corpus, perfil, modelo, revisión de índice y umbrales.
- Separa y valida relaciones paralelas e inversas en el grafo, conserva tooltips de procedencia y evita colisiones básicas de nodos y etiquetas.
- Cierra `OCR-02` por alcance, incorpora `CAT-01`, `CAT-02` y `GRAPH-02` al plan y mantiene `QA-01` en el cierre pre-release; sin migración, continúa `0040_discovery_grouping_continuity`.

### 0.73.0 — 2026-08-03
- Cierra `DISC-01D` y `DISC-01` con corpus JSONL por familia, métricas reproducibles, errores auditables y comparación de informes.
- Agrega el adaptador opcional `spacy_ner` con selección exacta de modelo y versión, sin declararlo superior al proveedor local.
- Confirma la validación manual de `UX-03`; sin migración nueva.

### 0.72.0 — 2026-08-03
- Cierra `DISC-01C` con cuatro grupos, nueve pertenencias, catorce acciones append-only, una continuidad desde un snapshot equivalente e integridad correcta.
- Resuelve `UX-03` separando Entidades y menciones en tareas persistentes y dividiendo Descubrimiento abierto en revisión, nueva corrida y agrupamiento o continuidad.
- Ordena `HISTORIAL_DE_CAMBIOS.md` e `IMPLEMENTACIONES_REALIZADAS.md` sin migración nueva.

### 0.71.2 — 2026-08-03
- Corrige el validador de continuidad para snapshots equivalentes y registra `UX-03` como reformulación crítica de la interfaz de descubrimiento; sin migración.

### 0.71.1 — 2026-08-03
- Corrige la selección posterior a crear un grupo manual: Streamlit aplica la selección pendiente en el rerun siguiente y conserva el grupo ya persistido; sin migración.

### 0.71.0 — 2026-08-03
- Valida `DISC-01B` e implementa `DISC-01C` con `0040_discovery_grouping_continuity`, grupos y pertenencias sin fusión, acciones append-only y continuidad textual que conserva candidatos obsoletos.

### 0.70.2 — 2026-08-03
- Agrega criterios permanentes de interfaz, mantiene abiertos los paneles interactivos durante reruns y valida las ocho decisiones controladas sin borrar una decisión adicional append-only; sin migración.

### 0.70.1 — 2026-08-03
- Hace obligatorio revisar los principios de interfaz en cada modificación, agrega `UX-02` como auditoría final de complejidad y unifica pruebas relevantes más `collect-only` en un solo comando; sin migración.

### 0.70.0 — 2026-08-03
- Valida `DISC-01A` e implementa `DISC-01B` con `0039_discovery_decisions`, decisiones append-only, autoridades explícitas, registros propios por familia y bloqueo de candidatos obsoletos, sin relaciones automáticas.

### 0.69.2 — 2026-08-03
- Corrige la verificación de `DISC-01A` sobre corpus con otros documentos aprobados sin cambiar detector ni esquema.

### 0.69.1 — 2026-08-03
- Corrige el filtrado de menciones existentes y mueve el panel de `DISC-01A` al final de la vista, cerrado por defecto; sin migración ni nueva copia de prueba.

### 0.69.0 — 2026-08-03
- Implementa `DISC-01A` con perfiles, corridas y candidatos persistentes de descubrimiento abierto.
- Agrega `0038_open_discovery`, proveedor local determinista, interfaz, comandos de terminal y copia descartable de validación.
- Conserva offsets, revisión textual, parámetros y autorización de calidad sin crear registros canónicos.

### 0.68.1 — 2026-08-03
- Cierra `EX-01` después de validar la adopción reversible, el acuerdo bilateral posterior y la integridad de las copias descartables.
- Registra la migración y apertura correcta de `project_data`, con las pruebas OCR todavía visibles.
- Fija el plan completo de `DISC-01` y deja `DISC-01A` como próximo bloque funcional, sin migración nueva.

### 0.68.0 — 2026-08-03
- Implementa `EX-01D`: paquete completo, vista previa, backup, adopción transaccional y rollback de un estado editable divergente.
- Agrega `0037_exchange_state_adoptions`; la adopción no crea base común y el acuerdo bilateral sigue siendo posterior y separado.
- Registra como validada `EX-01C` mediante un acuerdo coincidente en ambas copias y un paquete vacío reconocido por `common_base_agreement`.

### 0.67.0 — 2026-08-03
- Implementa `EX-01C`: propuesta, aceptación y finalización bilateral de una nueva base común cuando dos copias tienen estado editable idéntico.
- Agrega `0036_exchange_common_base_agreements`, manifiestos verificables, puntos de control vinculados y `common_base_agreement`, sin modificar contenido.

### 0.66.0 — 2026-08-03
- Implementa `EX-01B`: recuperación append-only de linaje cuando `EX-01A` demuestra una cadena concluyente y única.
- Agrega la migración `0035_exchange_lineage_recovery`, casos, evidencias y decisiones auditables, y el método persistido `recovered_lineage`.
- La recuperación no modifica contenido, invalida la simulación anterior y obliga a reevaluar el paquete antes de resolver o aplicar.

### 0.65.0 — 2026-08-03
- Implementa `EX-01A`: diagnóstico de solo lectura para paquetes sin base reconocida.
- Verifica SQLite local, paquetes, manifiestos aislados y backups explícitos; clasifica evidencia recuperable, ambigua o insuficiente.
- Agrega interfaz, comando de terminal y proyecto descartable de validación, sin migración ni acciones de recuperación.

### 0.64.2 — 2026-08-03
- Cierra `DATA-02` tras validar las tres autorizaciones, la auditoría por terminal y la integridad de la base.
- Fija la planificación completa de `EX-01` y deja `EX-01A` como próximo bloque funcional.

### 0.64.1 — 2026-08-03
- Corrige el bloqueo del botón de sugerencias de menciones con alcance ampliado: la acción permanece habilitada y la autorización se valida al pulsarla.
- No modifica el esquema; continúa la revisión `0034_automatic_analysis_authorizations` y la validación parcial de `DATA-02`.

### 0.64.0 — 2026-08-03
- Completa la implementación de `DATA-02`: alcance programático seguro, fundamento obligatorio, registro append-only y bloqueo de perfiles sin autorización vigente; su cierre queda sujeto a validación manual.
- Agrega la migración `0034_automatic_analysis_authorizations`, auditoría en interfaz y terminal, y relevo documental para una conversación nueva.

### 0.63.0 — 2026-08-03
- Cierra `DATA-01` tras validar reparaciones agrupadas e inicia `DATA-02` con páginas aprobadas como alcance automático predeterminado y confirmación para ampliarlo.
- Agrega a `.assistant/` una regla obligatoria contra bloqueos circulares entre widgets y botones dentro de `st.form`.

### 0.62.1 — 2026-08-03
- Corrige el bloqueo circular del botón de decisión conjunta: la selección dentro del formulario ya no necesita habilitar el botón mediante un rerender que Streamlit no realiza.
- Valida la mención ganadora al enviar y conserva intacta la transacción de dominio.

### 0.62.0 — 2026-08-02
- Permite revisar como una unidad conjuntos de tres o más menciones coincidentes y elegir una única ganadora sin decisiones parciales.
- Agrega reubicaciones seguras agrupadas, con una revisión individual por mención y cancelación completa ante cualquier cambio.

### 0.61.0 — 2026-08-02
- Permite comparar la fila vigente de una mención con su último snapshot y elegir explícitamente cuál conservar.
- Registra `repair_adopt_current_row` o, al restaurar, conserva primero la divergencia mediante `repair_capture_divergent_row` y agrega después `repair_restore_snapshot`.

### 0.60.0 — 2026-08-02
- Permite resolver ubicaciones ambiguas seleccionando un fragmento literal y una aparición concreta, con revisión `repair_manual_relocation`.
- Permite retirar de manera auditable una mención cuyo fragmento ya no aparece mediante `repair_mark_absent`, sin borrar registro ni historial.

### 0.59.0 — 2026-08-02
- Permite comparar dos menciones que convergen sobre el mismo fragmento vigente y elegir explícitamente cuál conservar.
- Retira la perdedora mediante `repair_duplicate_rejected`; cuando se conserva la histórica, la reubica mediante `repair_duplicate_relocated`.
- Mantiene bloqueados los conjuntos múltiples, las revisiones obsoletas y las divergencias de historial.

### 0.58.0 — 2026-08-02
- Permite resolver menciones aceptadas o modificadas sin entidad mediante `repair_link_authority` o `repair_return_pending`, sin alterar snapshots anteriores y bloqueando divergencias.
- Agrega una copia descartable con dos rutas de validación y corrige los fragmentos de prueba para que no terminen con palabras cortadas.

### 0.57.0 — 2026-08-02
- Cierra `UX-01` y agrega revisión centralizada para reubicar únicamente menciones con proyección única, sin colisiones y con historial consistente.
- Registra `repair_relocation` sin reescribir snapshots previos e incorpora una copia descartable para validar el recorrido.

### 0.56.0 — 2026-08-02
- Evita el recorte de estados largos y simplifica el resumen, las tablas y los filtros de Organización del trabajo.
- Presenta Exportar como configurar, revisar contenido y crear archivo, con identificadores y huellas en detalles técnicos.

### 0.55.0 — 2026-08-02
- Simplifica Revisión, Entidades y el mapa de relaciones, agrupando opciones secundarias y usando un léxico más directo.
- No modifica datos, revisiones, menciones ni algoritmos del grafo.

### 0.54.0 — 2026-08-02
- Simplifica Catálogo y Procesamiento, mantiene las acciones principales visibles y mueve la búsqueda dentro de palabras al bloque principal.
- No modifica datos, perfiles, extracciones ni la revisión de base.

### 0.53.0 — 2026-08-02
- Simplifica las búsquedas literal y por significado, manteniendo la consulta visible y agrupando filtros y configuración técnica.
- No modifica índices, perfiles, resultados ni reglas de filtrado.

### 0.52.0 — 2026-08-02
- Organiza el recorrido en cinco etapas y once pasos, con navegación y orientación contextual opcional.
- Reemplaza anglicismos operativos y relega comandos técnicos a detalles desplegables.

### 0.51.0 — 2026-08-02
- Inicia la simplificación de interfaz con navegación por tareas, ayuda contextual y léxico principal en español.
- Conserva códigos internos en detalles técnicos y registra la corrección visual de perfiles.

### 0.50.3 — 2026-08-02
- Ejecuta las acciones de ciclo de vida antes del render mediante callbacks encolados, evitando formularios duplicados.
- Agrega regresiones para impedir reruns anidados durante el archivado.

### 0.50.1 — 2026-08-02
- Intentó sincronizar selector y formulario de perfiles tras acciones de ciclo de vida sin modificar datos ni historial.

### 0.50.0 — 2026-08-02
- Reorganiza `docs/` en documentación operativa, referencia actual e historial.
- Agrega `.assistant/` con reglas de continuidad, interacción, documentación y pruebas.
- Consolida una única lista de pendientes y un único registro de implementaciones realizadas.
- Recupera pendientes que habían desaparecido: audiovisual, transcripción, plugin de YouTube, imagen Docker, integración Drive, corpus de evaluación y cierre de v1.0.
- Incorpora como pendientes evaluados la simplificación de interfaz, importación de diccionarios, herramientas LLM y RAG.
- No modifica la base ni la lógica funcional.

## Ciclos anteriores

### 0.49.x — ciclo de vida de exportaciones e intercambio
- Confirmación persistente de exportaciones y administración de perfiles.
- Diagnóstico, archivo y limpieza de paquetes obsoletos.
- Presentación segura de paquetes sin base común.
- Confirmaciones de formularios sin bloqueo circular.
- Consolidación inicial de pendientes y estrategia de pruebas.

Detalle: [actualizaciones 0.49.x](historico/actualizaciones/) y `CHANGELOG.md`.

### 0.46.0–0.48.0 — continuidad, rebase y menciones
- Formularios sin acciones por `Enter`.
- Atributos completos en Revisión.
- Filtros de calidad para búsquedas y sugerencias.
- Rebase repetible y conservación de procedencia.
- Deduplicación de menciones entre revisiones.
- Entradas manuales con botones explícitos.

Detalle: [actualizaciones históricas](historico/actualizaciones/) y [decisiones de rebase](historico/decisiones_tecnicas/).

### 0.40.0–0.45.0 — rebase conservador
- Adopción segura de nuevas extracciones.
- Resolución de menciones, texto, estructura, metadatos y atributos.
- Navegación persistente y fragmentos autocontenidos.

Detalle: [decisiones técnicas](historico/decisiones_tecnicas/).

### 0.35.0–0.39.0 — calidad, preprocesamiento y Surya
- Calidad automática de página.
- Derivados conservadores.
- Runtime Surya aislado, servidor persistente y fallback.
- Evaluación empírica inicial y control estructural revisable.

Detalle: [decisiones técnicas](historico/decisiones_tecnicas/).

### 0.30.0–0.34.5 — circuito operativo completo
- Catálogo, procesamiento, revisión, búsqueda, entidades, relaciones, exportación, intercambio y backups.
- Historial integral y revisión de corridas candidatas.
- Intercambio creciente del historial editable.

Detalle: [diseño histórico](historico/diseno/DISENO_Y_PLAN_DE_IMPLEMENTACION_HASTA_0.49.2.md) y [prueba piloto](historico/prueba_piloto/).

## Versiones anteriores

La evolución completa desde el inicio se conserva en [`CHANGELOG.md`](../CHANGELOG.md). Ese archivo es el registro técnico exhaustivo; este documento funciona como índice breve y no repite cada cambio.

## Regla para versiones futuras

La guía vigente permanece en `operativos/ACTUALIZACION_ACTUAL.md`. Al publicar una nueva versión, la guía reemplazada se mueve a `historico/actualizaciones/` con su número de versión. No se crean archivos nuevos en la raíz de `docs/`.
