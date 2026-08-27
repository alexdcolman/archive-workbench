# Actualización actual - Archive Workbench 0.89.0 RC44

## Alcance de RC44

RC44 amplía **Búsqueda textual** después de la recuperación de resultados. No cambia el índice persistente ni sus filtros. Mantiene `Tarjetas` como vista principal y agrega tres herramientas optativas: `Concordancias`, `Distribución de los resultados` y recorrido anterior/siguiente dentro de `Revisar documentos`.

`Concordancias` genera una fila por aparición dentro del campo donde se detectó cada resultado y muestra contexto anterior, coincidencia y contexto posterior. `Distribución de los resultados` queda cerrada por defecto y resume solamente los bloques mostrados, agrupados por documento, lugar de coincidencia y parte interna cuando corresponde. Al abrir una tarjeta, `Revisar documentos` conserva el orden de ese conjunto y permite pasar al resultado anterior o siguiente y volver a Búsqueda textual sin perder la consulta ni los filtros utilizados.

No se modifica `pilot_data` ni el esquema de base. Continúa `0047_authority_relation_profiles`.

## Actualización desde RC43

```bash
cd ~/projects/archive_app
source .venv/bin/activate
TMP_DIR="$(mktemp -d)"
unzip -q ~/Downloads/archive_workbench_v0.89.0_RC44.zip -d "$TMP_DIR"
python "$TMP_DIR/scripts/apply_candidate_update.py" --source "$TMP_DIR" --target ~/projects/archive_app
python -m pip install --no-build-isolation -e ".[dev,extraction,streamlit,semantic,tiff,discovery,audiovisual,platform]"
python -c "import archive_workbench; print(archive_workbench.__version__)"
archive-workbench db-status /home/alex/projects/archive_app/pilot_data
```

Resultado esperado: versión de código `0.89.0` y revisión `0047_authority_relation_profiles`.

**No hay migración nueva entre RC43 y RC44. No ejecutar `db-upgrade`.**

## Gate automatizado focal

No repetir tandas grandes. Para RC44 alcanza con:

```bash
cd ~/projects/archive_app
source .venv/bin/activate
pytest -q \
  tests/test_search.py::test_concordance_occurrences_split_all_marked_hits \
  tests/test_search.py::test_literal_search_exposes_all_hits_for_kwic \
  tests/test_search.py::test_search_navigation_payload_preserves_result_order \
  tests/test_search.py::test_search_finds_current_original_comment_and_tag \
  tests/test_search.py::test_literal_search_respects_gap_in_discontinuous_entity_period \
  tests/test_ui_navigation.py::test_literal_search_supports_kwic_distribution_and_result_traversal \
  tests/test_ui_navigation.py::test_literal_search_keeps_basic_decisions_visible_and_preserves_all_filters \
  tests/test_documentation.py::test_current_update_guide_describes_0890_rc44_pilot_changes_and_resume \
  tests/test_documentation.py::test_history_map_is_concise_and_references_historical_detail \
  tests/test_packaging.py::test_candidate_update_reconciles_only_known_relocations && \
pytest --collect-only -q
```

La suite completa corresponde exclusivamente a Alex.

## Validación manual específica de RC44

No repetir recorridos ya cerrados. Abrir **Búsqueda textual > Documentos revisados** y usar una consulta real que produzca varias coincidencias.

1. Ejecutar la búsqueda con los filtros que tengan sentido para el corpus. Abrir `Distribución de los resultados` y comprobar que las cantidades por documento y lugar de coincidencia correspondan con el conjunto mostrado; si hay partes internas, comprobar también esa agrupación.
2. Cambiar `Cómo querés ver los resultados` de `Tarjetas` a `Concordancias`. Comprobar que cada fila muestre documento, página, contexto anterior, coincidencia y contexto posterior, y que una palabra repetida dentro de un mismo bloque genere más de una concordancia.
3. Volver a `Tarjetas` y abrir un resultado que no sea el primero ni el último mediante `Abrir este resultado en Revisar documentos`. En la parte superior de `Revisar documentos` debe aparecer `Resultado N de M`, con `Resultado anterior de la búsqueda`, `Resultado siguiente de la búsqueda` y `Volver a los resultados de Búsqueda textual`.
4. Recorrer al menos un resultado anterior y uno siguiente. Cada acción debe abrir el documento, la página y el bloque correspondientes sin alterar el orden del conjunto.
5. Pulsar `Volver a los resultados de Búsqueda textual`. Deben reaparecer la misma consulta, los mismos filtros y el mismo conjunto de resultados.

Si estos cinco puntos quedan verdes, `PILOT-01X` puede cerrarse y el piloto continúa con **Búsqueda semántica**.
