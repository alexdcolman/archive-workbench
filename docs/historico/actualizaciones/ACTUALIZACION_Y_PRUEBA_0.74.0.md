# Actualización y prueba — Archive Workbench 0.74.0

Esta versión implementa la calibración reproducible de la búsqueda semántica (`SEM-01`) y mejora el canvas del grafo para separar relaciones paralelas y conservar su procedencia (`GRAPH-01`). También registra el cierre por alcance de `OCR-02`. No modifica el esquema de la base.

## 1. Actualizar sin mover ni eliminar archivos locales

```bash
cd ~/projects/archive_app
source .venv/bin/activate

TMP_DIR="$(mktemp -d)"
unzip -q \
  ~/Downloads/archive_workbench_v0.74.0.zip \
  -d "$TMP_DIR"

cp -a "$TMP_DIR"/. .

python -m pip install \
  --no-build-isolation \
  --no-deps \
  -e .

python -c "import archive_workbench; print(archive_workbench.__version__)"
```

Debe devolver `0.74.0`. La copia no mueve ni elimina archivos locales: `project_data`, `.dev`, `.assistant` y los demás contenidos existentes permanecen en su lugar.

## 2. Base de datos

**No hay migración.** La revisión requerida continúa en `0040_discovery_grouping_continuity`. No ejecutar `db-upgrade` para esta actualización.

## 3. Pruebas relevantes y colección completa

```bash
pytest -q \
  tests/test_semantic_evaluation.py \
  tests/test_semantic_search.py \
  tests/test_graph.py \
  tests/test_ui_navigation.py \
  tests/test_documentation.py \
  tests/test_packaging.py && \
pytest --collect-only -q
```

No repetir `UX-03` ni `DISC-01A`, `DISC-01B`, `DISC-01C` o `DISC-01D`: esos bloques ya están validados.

## 4. Validación controlada de SEM-01 y GRAPH-01

La preparación crea una base descartable nueva en `~/Downloads`. No lee ni modifica `project_data`. No uses `--force`: si la ruta ya existe, el bloque se detiene sin reemplazarla.

```bash
cd ~/projects/archive_app
source .venv/bin/activate

VALIDATION_ROOT="$HOME/Downloads/archive_workbench_sem_graph_validation_0740"

test ! -e "$VALIDATION_ROOT" && \
python scripts/create_semantic_graph_validation_project.py \
  --destination "$VALIDATION_ROOT" && \
archive-workbench semantic-evaluation-compare \
  "$VALIDATION_ROOT/validation/semantic_evaluation.json" \
  "$VALIDATION_ROOT/validation/semantic_evaluation_alt.json" \
  --output "$VALIDATION_ROOT/validation/semantic_comparison.json"
```

Resultado esperado en terminal:

- revisión `0040_discovery_grouping_continuity`;
- perfil `Control SEM-01`;
- umbral recomendado `0.7` y F1 `0.8` en el informe principal;
- tres relaciones paralelas controladas;
- confirmación explícita de que `project_data` no fue leído ni modificado;
- comparación creada porque ambos informes comparten la misma huella del corpus y el mismo tipo de fragmento.

El corpus controlado verifica el contrato y la comparación de umbrales. No establece un umbral universal ni declara un modelo superior fuera de ese corpus, perfil, revisión de índice y conjunto de parámetros.

## 5. Revisión manual limitada al grafo nuevo

Abrí la base descartable:

```bash
cd ~/projects/archive_app
source .venv/bin/activate

VALIDATION_ROOT="$HOME/Downloads/archive_workbench_sem_graph_validation_0740"
archive-workbench review-app "$VALIDATION_ROOT"
```

En **Mapa de relaciones**:

1. Mostrá todos los tipos y estados de revisión.
2. Confirmá que entre **Persona Investigada** y **Dirección de Inteligencia** aparecen tres relaciones curvas separadas, incluida una en sentido inverso.
3. Pasá el cursor sobre nodos, aristas y etiquetas: el tooltip debe conservar tipo, dirección, procedencia y evidencia.
4. Arrastrá uno de los nodos: las curvas y etiquetas deben recalcularse sin superponerse sobre el nodo.
5. Cambiá los filtros de tipo y estado: el canvas debe corresponder exactamente con el resumen y la tabla visibles.

Detené Streamlit con `Ctrl+C` al terminar. La base descartable no se elimina automáticamente; cualquier limpieza posterior requiere indicar y autorizar su ruta exacta.

## 6. Resultado de la validación

`SEM-01` y `GRAPH-01` quedaron validados el 2026-08-04 sobre el proyecto descartable `archive_workbench_sem_graph_validation_0740`:

- revisión `0040_discovery_grouping_continuity`;
- umbral controlado recomendado `0.7` y F1 `0.8` en el informe principal;
- comparación reproducible creada con el informe alternativo;
- tres relaciones curvas separadas, incluida una en sentido inverso;
- tooltips, arrastre de nodos y filtros coherentes con el resumen y la tabla;
- `project_data` no fue leído ni modificado.

La base descartable y el temporal de instalación se conservan hasta recibir autorización expresa para eliminarlos.
