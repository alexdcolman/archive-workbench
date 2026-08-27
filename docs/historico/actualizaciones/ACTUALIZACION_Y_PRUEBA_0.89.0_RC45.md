# Actualización actual - Archive Workbench 0.89.0 RC45

## Alcance de RC45

RC45 cierra la validación manual de las ampliaciones de **Búsqueda textual** de RC44 y avanza el piloto a **Búsqueda semántica**. Búsqueda textual conserva concordancias, distribución y recorrido anterior/siguiente, y ahora ese recorrido puede cerrarse explícitamente dentro de `Revisar documentos`.

Búsqueda semántica conserva su consulta principal y agrega herramientas secundarias de exploración: `Distribución de los resultados` cerrada por defecto; similitud coseno visible en cada resultado; `Umbral mínimo de similitud coseno` dentro de `Más opciones de búsqueda semántica`; recorrido anterior/siguiente, retorno y cierre dentro de `Revisar documentos`; y `Buscar pasajes similares a este resultado`, que usa el texto completo del fragmento como nueva consulta y excluye el mismo fragmento de los resultados. La consulta y los parámetros enviados se conservan al entrar y volver de `Revisar documentos`.

No se agrega KWIC a la búsqueda semántica porque no existe necesariamente una coincidencia léxica central que pueda alinearse como concordancia.

No se modifica `pilot_data`, el esquema de base ni el índice semántico persistente. Continúa `0047_authority_relation_profiles`.

## Actualización desde RC44

```bash
cd ~/projects/archive_app
source .venv/bin/activate
TMP_DIR="$(mktemp -d)"
unzip -q ~/Downloads/archive_workbench_v0.89.0_RC45.zip -d "$TMP_DIR"
python "$TMP_DIR/scripts/apply_candidate_update.py" --source "$TMP_DIR" --target ~/projects/archive_app
python -m pip install --no-build-isolation -e ".[dev,extraction,streamlit,semantic,tiff,discovery,audiovisual,platform]"
python -c "import archive_workbench; print(archive_workbench.__version__)"
archive-workbench db-status /home/alex/projects/archive_app/pilot_data
```

Resultado esperado: versión de código `0.89.0` y revisión `0047_authority_relation_profiles`.

**No hay migración nueva entre RC44 y RC45. No ejecutar `db-upgrade`.**

## Gate automatizado focal

No repetir tandas grandes. Para RC45 alcanza con:

```bash
cd ~/projects/archive_app
source .venv/bin/activate
pytest -q \
  tests/test_semantic_search.py::test_semantic_index_build_search_and_staleness \
  tests/test_semantic_search.py::test_semantic_search_can_post_filter_by_entity_period \
  tests/test_ui_navigation.py::test_semantic_search_separates_plain_language_from_technical_configuration \
  tests/test_ui_navigation.py::test_semantic_search_supports_distribution_traversal_closure_and_similar_passages \
  tests/test_ui_navigation.py::test_literal_search_supports_kwic_distribution_and_result_traversal \
  tests/test_documentation.py::test_current_update_guide_describes_0890_rc45_pilot_changes_and_resume \
  tests/test_documentation.py::test_history_map_is_concise_and_references_historical_detail \
  tests/test_packaging.py::test_candidate_update_reconciles_only_known_relocations && \
pytest --collect-only -q
```

La suite completa corresponde exclusivamente a Alex.

## Validación manual específica de RC45

No repetir Búsqueda textual completa. Sólo comprobar allí que, al abrir un resultado en `Revisar documentos`, `Cerrar el recorrido de resultados de Búsqueda textual` retire la navegación sin alterar el documento o bloque abierto.

Después abrir **Búsqueda semántica > Buscar en los textos** y usar una consulta real que produzca varios resultados.

1. Abrir `Distribución de los resultados` y comprobar que las cantidades por documento y, cuando exista, parte interna correspondan con el conjunto mostrado.
2. Observar la `similitud coseno` de resultados pertinentes y de alguno claramente débil. Abrir `Más opciones de búsqueda semántica`, elevar `Umbral mínimo de similitud coseno` y repetir la consulta. El umbral debe retirar únicamente resultados por debajo del valor elegido.
3. Abrir un resultado intermedio en `Revisar documentos`. Debe aparecer `Resultado N de M` con anterior/siguiente, `Volver a los resultados de Búsqueda semántica` y `Cerrar el recorrido de resultados de Búsqueda semántica`.
4. Recorrer un resultado anterior y uno siguiente. Volver a Búsqueda semántica y comprobar que consulta, umbral y demás opciones enviadas se conservan.
5. Desde una tarjeta semántica o desde el recorrido en `Revisar documentos`, usar `Buscar pasajes similares a este resultado`. Debe ejecutarse una nueva consulta con el pasaje como punto de partida y el pasaje original debe quedar excluido del conjunto devuelto.
6. Abrir nuevamente un resultado y usar `Cerrar el recorrido de resultados de Búsqueda semántica`. La navegación debe desaparecer y `Revisar documentos` debe continuar sobre el mismo documento/página/bloque.

Si estos puntos quedan verdes, `PILOT-01Y` puede cerrarse y el piloto continúa con **Explorar relaciones**.
