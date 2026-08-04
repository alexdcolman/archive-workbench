# Actualización y prueba — Archive Workbench 0.75.0

Esta versión implementa `CAT-01`: plantillas XLSX distribuibles para exportar, completar, simular e importar catálogos jerárquicos. Incluye una primera plantilla pública de prueba del fondo DIPPBA y un control negativo de jerarquía. No modifica el esquema de la base.

## 1. Actualizar sin mover ni eliminar archivos locales

```bash
cd ~/projects/archive_app
source .venv/bin/activate

TMP_DIR="$(mktemp -d)"
unzip -q \
  ~/Downloads/archive_workbench_v0.75.0.zip \
  -d "$TMP_DIR"

cp -a "$TMP_DIR"/. .

python -m pip install \
  --no-build-isolation \
  -e .

python -c "import archive_workbench; print(archive_workbench.__version__)"
git status --short
```

Debe devolver `0.75.0`. La copia no mueve ni elimina archivos locales: `project_data`, `.dev`, `.assistant` y los demás contenidos existentes permanecen en su lugar. La carpeta temporal debe conservarse hasta terminar la validación; cualquier limpieza posterior requiere indicar su ruta exacta.

## 2. Base de datos

**No hay migración.** La revisión requerida continúa en `0040_discovery_grouping_continuity`. No ejecutar `db-upgrade` para esta actualización.

## 3. Pruebas relevantes y colección completa

```bash
pytest -q \
  tests/test_catalog_templates.py \
  tests/test_catalog_management.py \
  tests/test_ui_navigation.py \
  tests/test_documentation.py \
  tests/test_packaging.py && \
pytest --collect-only -q
```

No repetir `UX-03`, `DISC-01A`, `DISC-01B`, `DISC-01C`, `DISC-01D`, `SEM-01` ni `GRAPH-01`: esos bloques ya están validados.

## 4. Validación controlada de CAT-01

La preparación crea una base descartable nueva en `~/Downloads`. No lee ni modifica `project_data`. No uses `--force`: si la ruta ya existe, el bloque se detiene sin reemplazarla.

```bash
cd ~/projects/archive_app
source .venv/bin/activate

VALIDATION_ROOT="$HOME/Downloads/archive_workbench_catalog_template_validation_0750"

test ! -e "$VALIDATION_ROOT" && \
python scripts/create_catalog_template_validation_project.py \
  --destination "$VALIDATION_ROOT" && \
archive-workbench catalog-template-validate \
  "$VALIDATION_ROOT" \
  "$VALIDATION_ROOT/validation/plantilla_catalogo_dippba.xlsx" \
  --output "$VALIDATION_ROOT/validation/dippba_validation.json"
```

Resultado esperado en terminal:

- revisión `0040_discovery_grouping_continuity`;
- plantilla DIPPBA con 155 filas;
- simulación válida con 155 unidades para crear y cero errores;
- informe `dippba_validation.json`;
- confirmación explícita de que `project_data` no fue leído ni modificado.

La plantilla de prueba conserva la estructura y las denominaciones recuperables del cuadro público de la Comisión Provincial por la Memoria. Las ramas mostradas con elipsis o sin nivel archivístico rotulado llevan una advertencia y no se completan por inferencia.

## 5. Revisión manual limitada a CAT-01

Abrí la base descartable:

```bash
cd ~/projects/archive_app
source .venv/bin/activate

VALIDATION_ROOT="$HOME/Downloads/archive_workbench_catalog_template_validation_0750"
archive-workbench review-app "$VALIDATION_ROOT"
```

En **Catálogo documental → Importar o exportar una plantilla XLSX**:

1. Descargá una plantilla vacía y comprobá que contenga `INSTRUCCIONES`, `ESTRUCTURA`, `CATALOGO` y `LISTAS`.
2. Cargá `validation/plantilla_invalida_documento_bajo_fondo.xlsx`: debe informar que un `documento` no puede depender directamente de un `fondo` y no debe habilitar la aplicación.
3. Cargá `validation/plantilla_catalogo_dippba.xlsx`: debe mostrar 155 filas para crear y cero errores.
4. Escribí `IMPORTAR`, aplicá la plantilla y confirmá que el catálogo conserve la jerarquía Archivo → Fondo DIPPBA → secciones, subsecciones, series y subseries.
5. Exportá el catálogo actual, volvé a cargar ese XLSX y aplicalo: el resultado debe indicar 155 unidades sin cambios, sin crear revisiones nuevas por una reimportación idéntica.

Detené Streamlit con `Ctrl+C` al terminar. La base descartable no se elimina automáticamente; cualquier limpieza posterior requiere indicar y autorizar su ruta exacta.
