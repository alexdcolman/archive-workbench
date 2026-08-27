# Actualización actual - Archive Workbench 0.89.0 RC42

## Alcance de RC42

La validación manual de RC41 confirmó que el intento de ensanchar `Búsqueda textual > Más filtros` mediante CSS sobre el popover no modificó el ancho real y mostró la misma limitación en `Explorar relaciones > Configurar mapa`.

RC42 corrige únicamente ese problema estructural: ambos controles dejan de usar `st.popover` y pasan a `st.expander` cerrados por defecto, inline y de ancho completo. Se conservan los mismos filtros, formularios y valores; no se agrega estado ni lógica nueva. También se retira el parche CSS específico de RC41.

No se modifica `pilot_data` ni el esquema de base. Continúa `0047_authority_relation_profiles`.

## Actualización desde RC41

```bash
cd ~/projects/archive_app
source .venv/bin/activate
TMP_DIR="$(mktemp -d)"
unzip -q ~/Downloads/archive_workbench_v0.89.0_RC42.zip -d "$TMP_DIR"
python "$TMP_DIR/scripts/apply_candidate_update.py" --source "$TMP_DIR" --target ~/projects/archive_app
python -m pip install --no-build-isolation -e ".[dev,extraction,streamlit,semantic,tiff,discovery,audiovisual,platform]"
python -c "import archive_workbench; print(archive_workbench.__version__)"
archive-workbench db-status /home/alex/projects/archive_app/pilot_data
```

Resultado esperado: versión de código `0.89.0` y revisión `0047_authority_relation_profiles`.

**No hay migración nueva entre RC41 y RC42. No ejecutar `db-upgrade`.**

## Gate automatizado focal

No repetir tandas grandes. Para RC42 alcanza con:

```bash
cd ~/projects/archive_app
source .venv/bin/activate
pytest -q \
  tests/test_ui_navigation.py::test_literal_search_keeps_basic_decisions_visible_and_preserves_all_filters \
  tests/test_ui_navigation.py::test_graph_uses_plain_language_and_progressive_details && \
pytest --collect-only -q
```

La suite completa corresponde exclusivamente a Alex y no forma parte de esta revalidación focal.

## Validación manual específica de RC42

No repetir recorridos ya cerrados.

1. En **Búsqueda textual**, abrir `Más filtros`. Debe desplegarse inline usando el ancho disponible de la sección, con sus dos columnas legibles.
2. En **Explorar relaciones**, abrir `Configurar mapa`. Debe desplegarse inline usando el ancho disponible, sin comprimir las tres columnas en una ventana flotante.
3. Si ambos puntos quedan bien, continuar inmediatamente con la prueba normal de consultas de **Búsqueda textual**. `PILOT-01V` y `PILOT-01W` mantienen sus validaciones propias si todavía no fueron cerradas.
