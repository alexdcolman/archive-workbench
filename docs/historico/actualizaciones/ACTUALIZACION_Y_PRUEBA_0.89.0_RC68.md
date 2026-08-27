# Actualización actual - Archive Workbench 0.89.0 RC68

## Alcance de RC68

La revisión humana de una corrida real de `DISC-03` con `local_rules_v3` detectó tres problemas que impiden usar esos candidatos como una cola de revisión confiable:

1. demasiadas citas entrecomilladas se proponían como `Obra`, aunque fueran discurso citado, apodos, etiquetas, géneros o expresiones ordinarias;
2. muchos actores e instituciones quedaban truncados o contaminados por el texto siguiente, por ejemplo una institución terminada en `de la`, una persona cortada en una inicial o un nombre que absorbía `- Esquel`;
3. la interfaz cargaba como máximo 500 candidatos mediante un límite fijo y no explicaba que una corrida podía contener muchos más.

RC68 conserva `local_rules_v1`, `local_rules_v2` y `local_rules_v3` sin reinterpretarlos, y agrega `local_rules_v4` para perfiles nuevos. Las corridas históricas continúan mostrando exactamente los candidatos producidos por su versión de reglas. Para comprobar el nuevo comportamiento hay que ejecutar una búsqueda nueva con v4; abrir una corrida v3 no la recalcula.

`local_rules_v4` cambia dos contratos del proveedor local:

- **Obra / publicación:** las comillas ya no son evidencia suficiente. Un candidato entrecomillado sólo se conserva cuando existe una señal positiva cercana de obra, publicación, repertorio, estreno, representación, lectura, montaje o tipo/autoria compatible. Se excluyen de forma explícita discurso directo, apodos dentro de nombres, etiquetas, géneros, técnicas y denominaciones institucionales. La etiqueta visible de la familia pasa de `Obra` a **Obra / publicación**, en línea con el modelo ya usado en las otras superficies.
- **Límites de actores e instituciones:** los nombres con tratamientos y las denominaciones institucionales conservan partículas internas necesarias como `de la Nación` o `de Mulhall`, aceptan iniciales seguidas de apellido como `W. KLEIN` o `A.KRUGER` y se detienen antes de separadores que introducen procedencia, lugar o identificadores.

La auditoría externa sobre los 138 documentos exportados previamente no se incorpora al repositorio. Como control descriptivo, v3 producía 151 candidatos `work`; v4 produce 89. En actores, los controles estructurales detectaron en v3 28 candidatos terminados en conectores, 21 terminados en una inicial y 15 contaminados por un guion seguido de otro dato; esos tres conteos bajan a cero con v4. Los cuatro ejemplos reportados durante la revisión se reconstruyen completos y con el corte esperado. Estos conteos no son precisión/recall porque el JSONL real no posee anotación exhaustiva.

`config/discovery_evaluation_corpus_disc03_rc68.jsonl` agrega una regresión sintética específica para estas fronteras y para precisión de citas. No contiene datos del piloto. Los dos benchmarks anteriores se mantienen intactos y v1/v2/v3 siguen ejecutables para reproducibilidad.

### Cantidad de referencias visibles

`Entidades y menciones > Buscar nuevas entidades > Revisar referencias encontradas` ya no solicita sólo las primeras 500 filas. La vista recupera la corrida completa y muestra explícitamente:

- cuántas referencias contiene la búsqueda;
- cuántas coinciden con los tipos de referencia seleccionados;
- cuántas están pendientes, aceptadas y descartadas;
- cuántas referencias pendientes o descartadas se están dibujando en cada pestaña.

El selector **Cuántas referencias mostrar** ofrece `Todas`, `100`, `250`, `500` y `1000`; `Todas` es el valor inicial. Limitar la vista no cambia ni elimina candidatos de la corrida.

`DISC-03` continúa **PARCIAL** hasta validar v4 sobre una muestra real. No se modifica `pilot_data`, no se crean autoridades, menciones o relaciones durante la construcción y no hay migración de base. Continúa `0047_authority_relation_profiles`.

## Actualización desde RC67

```bash
cd ~/projects/archive_app
source .venv/bin/activate
TMP_DIR="$(mktemp -d)"
unzip -q ~/Downloads/archive_workbench_v0.89.0_RC68.zip -d "$TMP_DIR"
python "$TMP_DIR/scripts/apply_candidate_update.py" --source "$TMP_DIR" --target ~/projects/archive_app
python -m pip install --no-build-isolation -e ".[dev,extraction,streamlit,semantic,tiff,discovery,audiovisual,platform]"
python -c "import archive_workbench; print(archive_workbench.__version__)"
archive-workbench db-status ~/projects/archive_app/pilot_data
```

Resultado esperado: versión de código `0.89.0` y revisión `0047_authority_relation_profiles`.

**No hay migración nueva entre RC67 y RC68. No ejecutar `db-upgrade`.**

## Gate automatizado focal

La suite completa corresponde exclusivamente a Alex. RC68 se valida con proveedor/evaluación, consulta completa de candidatos, navegación de Descubrimiento, continuidad histórica, documentación/empaquetado y recopilación completa sin ejecución:

```bash
cd ~/projects/archive_app && source .venv/bin/activate && pytest -q \
  tests/test_discovery_evaluation.py \
  tests/test_open_discovery.py::test_discovery_persists_reproducible_candidates_without_canonical_writes \
  tests/test_open_discovery.py::test_discovery_candidate_rows_can_return_more_than_500_when_limit_is_none \
  tests/test_discovery_grouping.py::test_local_redetection_uses_original_local_rule_version \
  tests/test_discovery_grouping.py::test_continuity_projects_stale_candidate_and_keeps_old_candidate_visible \
  tests/test_ui_navigation.py::test_rc20_discovery_review_is_accept_or_discard_with_stable_bulk_and_discarded_tabs \
  tests/test_documentation.py \
  tests/test_packaging.py && \
pytest --collect-only -q
```

## Validación manual específica de RC68

Usar el mismo `/home/alex/projects/archive_app/pilot_data`. No repetir OCR, transcripciones, exportaciones, intercambio ni otros recorridos cerrados.

1. Entrar en **Entidades y menciones > Buscar nuevas entidades > Revisar referencias encontradas** y seleccionar la corrida v3 que produjo más de 500 referencias. Verificar que la pantalla declare el total completo de la búsqueda y cuántas referencias coinciden con los filtros actuales.
2. En **Cuántas referencias mostrar**, comprobar primero `Todas` y después `500`. La pestaña de pendientes debe indicar literalmente cuántas muestra sobre el total de pendientes. Volver a `Todas` debe recuperar la lista completa sin crear ni modificar candidatos.
3. Crear una configuración nueva del proveedor local, que debe usar `local_rules_v4`, y ejecutar una búsqueda sobre un alcance pequeño y conocido. Una corrida histórica v3 no cambia por instalar RC68.
4. En la nueva corrida, revisar varios textos con comillas. Discurso citado, apodos, etiquetas o expresiones ordinarias no deben aparecer como **Obra / publicación** sólo por las comillas. Un título con señal explícita de libro, diario, revista, obra, estreno o repertorio sí puede aparecer.
5. Cuando el material incluya nombres equivalentes a los casos reportados, comprobar que una institución no termine en `de la`, que una inicial conserve el apellido siguiente, que un apellido compuesto conserve partículas necesarias y que un guion de procedencia no se incorpore al nombre.

La corrida nueva debe seguir creando únicamente referencias sugeridas para revisar. Si esta muestra queda usable, `DISC-03` puede cerrarse; si aparece otra clase sistemática de falso positivo, falso negativo o límite incorrecto, conservar el ejemplo y mantener el bloque parcial.
