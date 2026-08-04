# Archive Workbench 0.63.0 — alcance de calidad para análisis automáticos

Esta versión cierra `DATA-01` después de la validación completa de las reparaciones agrupadas e inicia `DATA-02` con una política común de calidad. Los perfiles nuevos de exportación y búsqueda semántica usan solamente páginas aprobadas; ampliar el alcance requiere una confirmación explícita y visible.

También se agrega `.assistant/05_FORMULARIOS_STREAMLIT.md`. Desde ahora, ningún botón dentro de `st.form` puede depender reactivamente de otro widget del mismo formulario: el botón permanece disponible y las precondiciones se validan al enviar, o los controles reactivos se ubican fuera del formulario.

No hay cambios de esquema ni migraciones.

## Actualizar desde 0.62.1

Detené Streamlit y ejecutá:

```bash
cd ~/projects/archive_app
source .venv/bin/activate

rm -rf /tmp/archive_workbench_v0.63.0
mkdir -p /tmp/archive_workbench_v0.63.0

unzip -q \
  ~/Downloads/archive_workbench_v0.63.0.zip \
  -d /tmp/archive_workbench_v0.63.0

cp -a /tmp/archive_workbench_v0.63.0/. .

pip install -e ".[dev,extraction,streamlit,semantic,tiff]"
```

Comprobá:

```bash
python -c "import archive_workbench; print(archive_workbench.__version__)"
```

Debe devolver:

```text
0.63.0
```

**No ejecutes `db-upgrade`.** La revisión continúa en `0033_export_exchange_lifecycle`.

## Pruebas automatizadas

Ejecutá el núcleo nuevo y los dos perfiles afectados:

```bash
pytest -q tests/test_analysis_quality.py
pytest -q tests/test_corpus_export.py
pytest -q tests/test_semantic_search.py
```

Resultados esperados, respectivamente:

```text
4 passed
8 passed
4 passed
```

Ejecutá las regresiones de menciones y alcance predeterminado:

```bash
pytest -q \
  tests/test_relations.py::test_authority_ui_defaults_candidate_search_to_approved_pages \
  tests/test_relations.py::test_transversal_entity_candidates_show_alias_and_can_be_included \
  tests/test_relations.py::test_transversal_entity_candidates_default_to_approved_pages \
  tests/test_search.py::test_automatic_mention_suggestions_require_approved_pages_by_default
```

Debe terminar con:

```text
4 passed
```

Ejecutá navegación completa:

```bash
pytest -q tests/test_ui_navigation.py
```

Debe terminar con:

```text
42 passed
```

Después ejecutá documentación y empaquetado:

```bash
pytest -q \
  tests/test_documentation.py \
  tests/test_packaging.py
```

Debe terminar con:

```text
35 passed
```

Finalmente:

```bash
pytest --collect-only -q
```

Debe recopilar:

```text
346 tests
```

## Crear la copia descartable

Confirmá que Streamlit esté cerrado y ejecutá:

```bash
cd ~/projects/archive_app
source .venv/bin/activate

rm -rf project_data_quality_scope_validation

python scripts/create_quality_scope_validation_project.py \
  --source project_data_rebase_validation \
  --destination project_data_quality_scope_validation
```

Debe informar que creó la copia, dejó una página aprobada y reinició los perfiles de exportación y búsqueda semántica. `project_data_rebase_validation` no se modifica.

## Validación manual

Abrí la copia:

```bash
archive-workbench review-app project_data_quality_scope_validation
```

### Exportación

1. Entrá en `Preparar corpus` y luego en `Configurar perfil`.
2. Elegí `Crear un perfil nuevo`.
3. Comprobá que aparezca `Alcance de calidad: solo páginas aprobadas` y que `Estado de revisión de la página` tenga seleccionada solamente `Aprobado`.
4. Escribí como nombre `Validación de alcance ampliado`.
5. En estados de página, seleccioná `Revisado` y `Aprobado`.
6. Sin marcar la confirmación de alcance ampliado, pulsá `Guardar perfil`.
7. El botón debe poder pulsarse. Debe aparecer un error indicando que el alcance ampliado requiere confirmación y no debe guardarse el perfil.
8. Marcá `Confirmo que deseo incluir páginas no aprobadas en este análisis automático`.
9. Pulsá nuevamente `Guardar perfil`.
10. Debe aparecer `Perfil guardado` y el perfil debe conservar los dos estados elegidos.

### Búsqueda semántica

11. Entrá en `Buscar por significado` y luego en `Preparar búsqueda`.
12. El perfil inicial `Multilingüe E5 — objetos` debe mostrar `Alcance de calidad: solo páginas aprobadas` y tener seleccionada solamente la página `Aprobada`.
13. En `Contenido incluido`, elegí `Revisada` y `Aprobada`.
14. Sin marcar la confirmación, pulsá `Guardar perfil`.
15. El botón debe poder pulsarse. Debe aparecer el mismo error de alcance ampliado y el perfil no debe guardarse.
16. Marcá la confirmación de inclusión de páginas no aprobadas y pulsá `Guardar perfil` otra vez.
17. Debe aparecer que el perfil fue guardado y que el índice anterior queda pendiente de reconstrucción. No reconstruyas el índice.

### Menciones automáticas por diccionario

18. Entrá en `Entidades y menciones`, seleccioná una entidad existente y abrí `Menciones en documentos`.
19. En `Opciones de búsqueda`, seleccioná `Revisada` y `Aprobada` como estados de página.
20. Debe aparecer una advertencia de alcance ampliado y la confirmación `Confirmo que deseo buscar menciones en páginas no aprobadas`.
21. Antes de marcarla, `Buscar coincidencias` debe estar deshabilitado.
22. Marcá la confirmación. El botón debe habilitarse inmediatamente, porque estos controles están fuera de `st.form`.
23. No ejecutes la búsqueda ni incorpores menciones.

Detené Streamlit con `Ctrl+C`.

Durante esta validación no generes exportaciones, no reconstruyas índices y no modifiques menciones. La copia `project_data_quality_scope_validation` puede eliminarse al terminar.

Relación con “Pendientes y mejoras”: `DATA-01` queda cerrado y trasladado a implementaciones realizadas. `DATA-02` avanza con la política común, los perfiles seguros y las confirmaciones visibles; continúa abierto para resúmenes, estadísticas, descubrimiento, importaciones, herramientas LLM, RAG y llamadas programáticas futuras.
