# Actualización actual - Archive Workbench 0.89.0 RC64

## Alcance de RC64

RC63 intentó aplicar la auditoría transversal de comportamiento Streamlit abierta como `PILOT-01AE`, pero la primera validación manual encontró regresiones de ejecución antes de poder completar ese recorrido. RC64 conserva los cambios de conformidad que no mostraron regresiones y repara las superficies afectadas, contrastadas nuevamente con `.assistant/00_CHECKLIST_CAMBIOS.md`, `.assistant/05_FORMULARIOS_STREAMLIT.md` y `docs/referencia/ARQUITECTURA_Y_MODELO_ACTUAL.md#streamlit-interaction-invariant`.

Los fallos reparados son:

- **Explorar relaciones:** los filtros aplicados al mapa dejan de depender de variables creadas sólo mientras `Configurar mapa` está abierto. El mismo estado aplicado alimenta `build_graph()` y la identidad del canvas, por lo que cerrar el panel no deja nombres sin inicializar ni pierde el mapa configurado.
- **Revisar documentos:** las claves de los paneles de página usan la página realmente seleccionada y las opciones de visualización conservan valores válidos aunque el panel esté cerrado.
- **Búsqueda textual:** `Más filtros` vuelve a ser un control reactivo exterior al formulario. Al buscar con el panel cerrado se conservan los filtros guardados en lugar de depender de variables no renderizadas.
- **Búsqueda semántica:** las opciones técnicas del perfil quedan fuera del `st.form` que controlan y sus valores existentes se conservan si el panel está cerrado. La construcción del índice conserva además dispositivo y tamaño de lote fuera del panel técnico.
- **Exportar corpus:** los paneles de período y separadores dejan de depender reactivamente de toggles situados dentro del mismo formulario; guardar con esos paneles cerrados conserva la configuración existente. Se agrega además el import faltante de `Path`, un bug latente anterior a RC63 que la validación real dejó expuesto.

Se agrega un guardrail estructural para detectar el patrón concreto prohibido por la política: un `st.toggle` ubicado dentro de un `st.form` no puede controlar contenido reactivo de ese mismo formulario. No se prohíben de forma general los toggles que funcionen sólo como datos enviados por un formulario.

No se modifican contratos de dominio, persistencia, esquema de base, OCR, transcripciones ni `pilot_data`.

## Actualización desde RC63

```bash
cd ~/projects/archive_app
source .venv/bin/activate
TMP_DIR="$(mktemp -d)"
unzip -q ~/Downloads/archive_workbench_v0.89.0_RC64.zip -d "$TMP_DIR"
python "$TMP_DIR/scripts/apply_candidate_update.py" --source "$TMP_DIR" --target ~/projects/archive_app
python -m pip install --no-build-isolation -e ".[dev,extraction,streamlit,semantic,tiff,discovery,audiovisual,platform]"
python -c "import archive_workbench; print(archive_workbench.__version__)"
archive-workbench db-status ~/projects/archive_app/pilot_data
```

Resultado esperado: versión de código `0.89.0` y revisión `0047_authority_relation_profiles`.

**No hay migración nueva entre RC63 y RC64. No ejecutar `db-upgrade`.**

## Gate automatizado focal

La suite completa corresponde exclusivamente a Alex y no debe ejecutarse como parte de esta candidata. Para RC64 corresponde comprobar navegación Streamlit y las regresiones directamente relacionadas con grafo, exportación, revisión y búsqueda semántica, además de documentación/empaquetado y colección:

```bash
cd ~/projects/archive_app && \
source .venv/bin/activate && \
pytest -q tests/test_ui_navigation.py && \
pytest -q \
  tests/test_graph.py \
  tests/test_corpus_export.py::test_export_profile_groups_document_and_uses_corrected_text \
  tests/test_corpus_export.py::test_page_export_inserts_marker_and_separators \
  tests/test_corpus_export.py::test_export_filters_by_entity_period_and_includes_temporal_metadata \
  tests/test_corpus_export.py::test_export_profile_archive_restore_and_delete_preserve_run_history \
  tests/test_review.py::test_review_canvas_component_callback_syncs_selected_object_before_rerun \
  tests/test_review.py::test_run_action_queues_selection_without_mutating_widget_key \
  tests/test_semantic_search.py::test_profile_change_invalidates_index_without_deleting_files \
  tests/test_semantic_search.py::test_semantic_search_can_post_filter_by_entity_period && \
pytest -q tests/test_documentation.py tests/test_packaging.py && \
pytest --collect-only -q
```

## Validación manual de PILOT-01AE sobre RC64

Usar el mismo `pilot_data`. No repetir OCR, transcripciones, exportaciones reales, intercambios ni otros recorridos funcionales ya cerrados. Esta pasada comprueba únicamente continuidad de interfaz, ausencia de tracebacks y ausencia de escrituras accidentales.

### 1. Inicio / selector de proyecto

Alternar entre las tareas disponibles para abrir o crear un proyecto. Cambiar una pestaña puramente visual no debe provocar una reconstrucción global. No crear otro proyecto.

### 2. Catálogo

En los paneles que existan para el material real, abrir las acciones secundarias incorporadas por RC63 y cambiar controles sin guardar. En **Quitar asociación**, enviar sin marcar la confirmación debe advertir y no escribir. No crear errores artificiales de planilla ni repetir incorporaciones.

### 3. Audio y video

En la caja para agregar una anotación temporal, escribir texto y pulsar Enter. No debe registrarse la anotación. Borrar el texto y no pulsar el botón de registro.

### 4. Revisar documentos

Abrir un documento existente y recorrer **Opciones de visualización**, **Herramientas de edición de las páginas** y **Estado de revisión de la página**. Los paneles deben abrir sin traceback y conservarse al cambiar controles. Cerrar y volver a abrir **Opciones de visualización** debe conservar las opciones elegidas para esa página. No guardar ni restaurar revisiones.

### 5. Búsqueda textual

Abrir **Más filtros**, cambiar un filtro y comprobar que el panel permanece abierto. Cerrar el panel y ejecutar una búsqueda ya conocida: no debe aparecer un traceback ni perderse el conjunto de filtros previamente guardado.

### 6. Entidades y menciones

Alternar las pestañas principales y abrir una relación existente sin guardar cambios. La ficha debe conservar el contexto. No repetir las validaciones funcionales de relaciones ya cerradas.

### 7. Buscar nuevas entidades

Alternar las pestañas y modos de revisión. Si durante el uso normal se guarda un perfil, el perfil recién guardado debe seguir seleccionado después del rerun. No crear un perfil sólo para esta prueba.

### 8. Búsqueda semántica

Abrir y cerrar las opciones técnicas del perfil sin guardar. Luego abrir las opciones técnicas de construcción, cambiar dispositivo o tamaño de lote sin construir el índice, cerrar y volver a abrir: el panel y sus valores deben conservarse. No reconstruir el índice para esta validación.

### 9. Explorar relaciones

La vista debe abrir sin traceback con **Configurar mapa** cerrado. Abrir el panel, cambiar filtros y pulsar **Actualizar el mapa con estos filtros**. Cerrar después el panel: el mapa debe conservar los filtros aplicados y seguir interactivo sin `UnboundLocalError`.

### 10. Exportar corpus

La superficie debe abrir sin `NameError`. En una configuración existente, abrir y cerrar **Filtro temporal de entidades y relaciones** y **Cómo separar páginas y bloques de texto en el archivo exportado**. No hace falta crear una exportación real. Si se guarda una configuración, cerrar esos paneles no debe borrar sus valores existentes.

### 11. Organizar trabajo

Alternar pestañas y abrir una asignación existente sin guardar. La ficha debe permanecer abierta al cambiar controles secundarios.

### 12. Administrar y recuperar

Alternar pestañas y, si hay una copia existente, usar únicamente la comprobación no destructiva ya prevista por RC63. No crear ni restaurar backups nuevos para esta pasada.

`Procesar documentos` e `Intercambiar cambios` no fueron modificados por RC63 ni RC64 para este bloque y conservan sus validaciones cerradas.

Si estas superficies quedan verdes, `PILOT-01AE` puede cerrarse y el piloto continúa con `PILOT-01A`.
