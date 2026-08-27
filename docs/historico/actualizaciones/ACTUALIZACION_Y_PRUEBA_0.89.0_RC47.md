# Actualización actual - Archive Workbench 0.89.0 RC47

## Alcance de RC47

La validación manual de RC46 cerró Búsqueda semántica (`PILOT-01Y`) y la pasada funcional de `Explorar relaciones` quedó satisfactoria para foco, filtros, jerarquía archivística, temporalidad y navegación. RC47 no reabre esas comprobaciones.

RC47 agrega únicamente tres mejoras visuales del grafo:

- `Pantalla completa` amplía el componente mediante la API Fullscreen del navegador. Entrar o salir es una interacción local y no provoca rerun de Streamlit;
- `Leyenda` abre/cierra una referencia compacta de tipos de nodo y familias de vínculo dentro del propio componente, también sin rerun;
- los rótulos estructurales repetitivos `contiene` y `contiene parte` quedan ocultos en la vista general para reducir ruido. La arista, la flecha y el tooltip permanecen visibles; el rótulo reaparece al pasar el puntero, seleccionar el vínculo o ampliar el mapa al 145% o más.

La utilidad analítica profunda del grafo se evaluará en investigaciones concretas y no bloquea el piloto. Si estos tres ajustes quedan verdes, el siguiente tramo es **Exportar corpus**.

No se modifica `pilot_data`, el esquema de base ni el modelo del grafo. Continúa `0047_authority_relation_profiles`.

## Actualización desde RC46

```bash
cd ~/projects/archive_app
source .venv/bin/activate
TMP_DIR="$(mktemp -d)"
unzip -q ~/Downloads/archive_workbench_v0.89.0_RC47.zip -d "$TMP_DIR"
python "$TMP_DIR/scripts/apply_candidate_update.py" --source "$TMP_DIR" --target ~/projects/archive_app
python -m pip install --no-build-isolation -e ".[dev,extraction,streamlit,semantic,tiff,discovery,audiovisual,platform]"
python -c "import archive_workbench; print(archive_workbench.__version__)"
archive-workbench db-status /home/alex/projects/archive_app/pilot_data
```

Resultado esperado: versión de código `0.89.0` y revisión `0047_authority_relation_profiles`.

**No hay migración nueva entre RC46 y RC47. No ejecutar `db-upgrade`.**

## Gate automatizado focal

No repetir búsquedas ni filtros del grafo ya validados manualmente. Para RC47 alcanza con:

```bash
cd ~/projects/archive_app
source .venv/bin/activate
pytest -q \
  tests/test_graph.py::test_graph_canvas_supports_local_fullscreen_legend_and_quieter_structural_labels \
  tests/test_graph.py::test_graph_canvas_uses_curved_paths_arrows_and_automatic_label_displacement \
  tests/test_ui_navigation.py::test_graph_uses_plain_language_and_progressive_details \
  tests/test_documentation.py::test_current_update_guide_describes_0890_rc47_graph_refinement_and_resume \
  tests/test_documentation.py::test_history_map_is_concise_and_references_historical_detail \
  tests/test_packaging.py::test_candidate_update_reconciles_only_known_relocations && \
pytest --collect-only -q
```

La suite completa corresponde exclusivamente a Alex.

## Validación manual específica de RC47

No repetir foco, filtros, jerarquía archivística, temporalidad ni navegación del grafo: ya quedaron verdes en la pasada anterior.

1. Abrir `Explorar relaciones > Explorar las relaciones` y pulsar `Pantalla completa` en la barra del grafo. Comprobar que el mapa ocupa la pantalla y conserva zoom, desplazamiento y posiciones de nodos. Salir con `Salir de pantalla completa` o `Esc` y comprobar que se vuelve al mismo grafo.
2. Pulsar `Leyenda`. Debe aparecer una referencia compacta para Entidad, Unidad del catálogo, Documento, Parte del documento y las familias principales de vínculo. Cerrar `Leyenda` y comprobar que no cambia el mapa.
3. En una vista con varias relaciones archivísticas, comprobar que `contiene`/`contiene parte` no saturen la vista general. Pasar el puntero por una de esas aristas o seleccionarla: su rótulo debe reaparecer. También debe reaparecer al ampliar el grafo al 145% o más. Las flechas y tooltips deben permanecer disponibles siempre.

Si estos tres puntos quedan verdes, cerrar `PILOT-01Z` y continuar directamente con **Exportar corpus**.
