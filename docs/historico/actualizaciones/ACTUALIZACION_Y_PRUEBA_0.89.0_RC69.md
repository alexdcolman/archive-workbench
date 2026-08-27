# Actualización actual - Archive Workbench 0.89.0 RC69

## Alcance de RC69

La validación manual de RC68 mostró que el arreglo anunciado no estaba llegando necesariamente a la corrida que se revisaba. El problema no era sólo de reglas: las configuraciones de descubrimiento persisten `provider_version`, por lo que una configuración creada con `local_rules_v3` seguía ejecutando v3 después de instalar RC68. La interfaz no mostraba esa versión de forma suficientemente visible y permitía iniciar otra búsqueda con las reglas históricas sin advertirlo con claridad.

RC69 corrige ese contrato y conserva la reproducibilidad histórica:

- `local_rules_v1`, `local_rules_v2`, `local_rules_v3` y `local_rules_v4` permanecen ejecutables para corridas y perfiles históricos;
- `local_rules_v5` pasa a ser la versión local vigente para configuraciones nuevas o actualizadas;
- una configuración local histórica se identifica explícitamente como tal y ofrece **Actualizar esta configuración a reglas v5**;
- desde la interfaz no se inicia una búsqueda nueva con reglas locales históricas hasta que la configuración se actualiza de forma explícita;
- las búsquedas ya registradas siguen mostrando la versión con la que fueron producidas y nunca se recalculan al actualizar una configuración.

### Límites de entidades

v5 mantiene las fronteras nominales corregidas en v4. Sobre los textos reales usados durante DISC-03, las siguientes construcciones se detectan como una sola referencia completa:

- `Secretaría General de la Presidencia de la Nación`;
- `Dr. Guillermo W. KLEIN`;
- `profesora Encarnación Díaz de Mulhall`;
- `Sr. Reberte Equiza- Esquel` se corta como `Sr. Reberte Equiza`.

La diferencia con la corrida problemática se debe a la versión: v3 reproduce deliberadamente los límites históricos defectuosos; v5 usa las reglas corregidas.

Como control externo de sólo lectura sobre los 138 documentos ya exportados, v3 produce 28 actores terminados en conectores, 21 terminados en una inicial y 26 contaminados por un guion seguido de otro dato; esos tres conteos son 0 con v5. No son métricas de precisión/recall porque el corpus real no tiene verdad terreno exhaustiva.

### Obra / publicación

RC69 vuelve más conservadora esta familia. Las comillas son sólo delimitadores y nunca evidencia suficiente. v5 exige una señal léxica inmediata que identifique el fragmento como obra, publicación, repertorio o pieza representada. Se elimina la propagación amplia de contexto de v4, que podía convertir una cita posterior en obra sólo porque antes se había mencionado `obra`, `teatro` o `publicación`.

La regresión nueva cubre, entre otros, casos donde v4 podía proponer falsamente `"El Flaco"` o `"Plan de acción"` por una mención lejana de `obra`; v5 no los propone. El criterio favorece precisión de la cola de revisión aunque pueda perder títulos sin ninguna señal contextual explícita.

En el mismo control externo, la cantidad de candidatos `Obra / publicación` baja de 151 en v3 y 89 en v4 a 75 en v5. Ese conteo sólo describe el efecto del cambio; no se usa como estimación de calidad.

### Cantidad visible

La vista sigue recuperando el conjunto completo para poder informar el total de la corrida y los totales por filtro/estado, pero **Cuántas referencias mostrar** usa ahora `500` como valor inicial. Las opciones son `100`, `250`, `500`, `1000` y `Todas`. La cantidad elegida controla únicamente cuántas tarjetas se dibujan; no borra ni modifica referencias.

`DISC-03` continúa **PARCIAL** hasta validar una corrida nueva con v5. No se modifica `pilot_data`, no hay migración y continúa `0047_authority_relation_profiles`.

## Actualización desde RC68

```bash
cd ~/projects/archive_app
source .venv/bin/activate
TMP_DIR="$(mktemp -d)"
unzip -q ~/Downloads/archive_workbench_v0.89.0_RC69.zip -d "$TMP_DIR"
python "$TMP_DIR/scripts/apply_candidate_update.py" --source "$TMP_DIR" --target ~/projects/archive_app
python -m pip install --no-build-isolation -e ".[dev,extraction,streamlit,semantic,tiff,discovery,audiovisual,platform]"
python -c "import archive_workbench; print(archive_workbench.__version__)"
archive-workbench db-status ~/projects/archive_app/pilot_data
```

Resultado esperado: versión de código `0.89.0` y revisión `0047_authority_relation_profiles`.

**No hay migración nueva entre RC68 y RC69. No ejecutar `db-upgrade`.**

## Gate automatizado focal

La suite completa corresponde exclusivamente a Alex. Para RC69 corresponde:

```bash
cd ~/projects/archive_app && source .venv/bin/activate && pytest -q \
  tests/test_discovery_evaluation.py \
  tests/test_open_discovery.py::test_discovery_persists_reproducible_candidates_without_canonical_writes \
  tests/test_open_discovery.py::test_discovery_profile_can_upgrade_rules_without_rewriting_historical_runs \
  tests/test_open_discovery.py::test_discovery_candidate_rows_can_return_more_than_500_when_limit_is_none \
  tests/test_discovery_grouping.py::test_local_redetection_uses_original_local_rule_version \
  tests/test_ui_navigation.py::test_rc20_discovery_review_is_accept_or_discard_with_stable_bulk_and_discarded_tabs \
  tests/test_documentation.py \
  tests/test_packaging.py && \
pytest --collect-only -q
```

## Validación manual específica de RC69

Usar el mismo `/home/alex/projects/archive_app/pilot_data`. No repetir OCR, transcripciones, exportaciones ni otros recorridos cerrados.

1. Entrar en **Entidades y menciones > Buscar nuevas entidades > Ejecutar búsqueda de entidades** y seleccionar la configuración usada en la corrida problemática. Si usa v3/v4, debe indicarlo como reglas históricas y ofrecer **Actualizar esta configuración a reglas v5**.
2. Actualizar esa configuración. Las búsquedas históricas deben seguir disponibles sin cambiar; la configuración queda preparada para una nueva corrida v5.
3. Ejecutar una búsqueda nueva con esa configuración ya actualizada. En **Revisar referencias encontradas**, la búsqueda debe identificarse como `reglas v5`.
4. Confirmar que **Cuántas referencias mostrar** empieza en `500`; cambiarlo a `100`, `1000` o `Todas` debe modificar sólo la cantidad dibujada y mantener visibles los totales.
5. Revisar los cuatro ejemplos de límites informados y una muestra de **Obra / publicación**. Los nombres no deben quedar truncados/contaminados y las comillas solas no deben producir obras.

La corrida v3/v4 histórica puede seguir mostrando los defectos que produjo en su momento; eso es esperado y forma parte de la reproducibilidad. La validación de RC69 se hace sobre una **corrida nueva v5**.
