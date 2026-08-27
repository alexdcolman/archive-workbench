# Actualización actual - Archive Workbench 0.89.0 RC46

## Alcance de RC46

La validación manual de RC45 confirmó el funcionamiento de distribución, similitud coseno visible, umbral mínimo, recorrido anterior/siguiente, retorno conservando consulta/parámetros y búsqueda de pasajes similares. RC46 no reabre esas comprobaciones.

RC46 corrige tres ajustes finales de `PILOT-01Y`:

- el recorrido de resultados de Búsqueda textual y Búsqueda semántica se muestra debajo del visor y de la ayuda de selección, dentro de la región local de revisión, con una presentación más compacta;
- cerrarlo usa una `✕` y elimina únicamente el contexto del recorrido dentro del fragmento local, sin solicitar un rerun global ni cambiar documento, página o bloque activo;
- cualquier bloque seleccionado en `Revisar documentos` puede iniciar `Buscar fragmentos similares a este bloque`. Se usa el texto revisado actual como consulta semántica y los fragmentos indexados que contienen ese mismo bloque quedan excluidos de los resultados.

No se modifica `pilot_data`, el esquema de base ni el índice semántico persistente. Continúa `0047_authority_relation_profiles`.

## Actualización desde RC45

```bash
cd ~/projects/archive_app
source .venv/bin/activate
TMP_DIR="$(mktemp -d)"
unzip -q ~/Downloads/archive_workbench_v0.89.0_RC46.zip -d "$TMP_DIR"
python "$TMP_DIR/scripts/apply_candidate_update.py" --source "$TMP_DIR" --target ~/projects/archive_app
python -m pip install --no-build-isolation -e ".[dev,extraction,streamlit,semantic,tiff,discovery,audiovisual,platform]"
python -c "import archive_workbench; print(archive_workbench.__version__)"
archive-workbench db-status /home/alex/projects/archive_app/pilot_data
```

Resultado esperado: versión de código `0.89.0` y revisión `0047_authority_relation_profiles`.

**No hay migración nueva entre RC45 y RC46. No ejecutar `db-upgrade`.**

## Gate automatizado focal

No repetir las pruebas de Búsqueda semántica que ya quedaron validadas manualmente. Para RC46 alcanza con:

```bash
cd ~/projects/archive_app
source .venv/bin/activate
pytest -q \
  tests/test_semantic_search.py::test_semantic_index_build_search_and_staleness \
  tests/test_ui_navigation.py::test_semantic_search_supports_distribution_traversal_closure_and_similar_passages \
  tests/test_ui_navigation.py::test_review_search_navigation_is_compact_fragment_local_and_supports_selected_block_similarity \
  tests/test_ui_navigation.py::test_literal_search_supports_kwic_distribution_and_result_traversal \
  tests/test_ui_navigation.py::test_rc40_review_bbox_selection_updates_object_inside_local_fragment \
  tests/test_documentation.py::test_current_update_guide_describes_0890_rc46_pilot_changes_and_resume \
  tests/test_documentation.py::test_history_map_is_concise_and_references_historical_detail \
  tests/test_packaging.py::test_candidate_update_reconciles_only_known_relocations && \
pytest --collect-only -q
```

La suite completa corresponde exclusivamente a Alex.

## Validación manual específica de RC46

No repetir distribución, similitud, umbral, anterior/siguiente, retorno ni búsqueda de pasajes similares desde tarjetas: ya quedaron verdes en RC45.

1. Abrir un resultado de Búsqueda textual en `Revisar documentos`. El recorrido debe aparecer debajo del visor, después de la ayuda de selección, en formato compacto. Pulsar `✕`: debe desaparecer y conservar exactamente documento, página y bloque activo.
2. Repetir lo mismo desde un resultado de Búsqueda semántica. Pulsar `✕` no debe cambiar documento, página ni bloque ni provocar una navegación global visible.
3. En `Revisar documentos`, seleccionar cualquier bloque con texto y usar `Buscar fragmentos similares a este bloque`. Debe abrir Búsqueda semántica con el texto del bloque como punto de partida y el bloque semilla no debe reaparecer entre los resultados.

Si estos tres puntos quedan verdes, `PILOT-01Y` puede cerrarse y el piloto continúa con **Explorar relaciones**.
