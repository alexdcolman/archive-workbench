# Actualización y prueba — Archive Workbench 0.75.1

Esta versión corrige la validación manual de `CAT-01`: elimina el bloqueo circular del botón **Aplicar plantilla**, aclara que `LISTAS` es una hoja auxiliar oculta y asigna una identidad neutral al proyecto descartable de validación. No modifica el esquema de la base.

## 1. Actualizar sin mover ni eliminar archivos locales

```bash
cd ~/projects/archive_app
source .venv/bin/activate

TMP_DIR="$(mktemp -d)"
unzip -q \
  ~/Downloads/archive_workbench_v0.75.1.zip \
  -d "$TMP_DIR"

cp -a "$TMP_DIR"/. .

python -m pip install \
  --no-build-isolation \
  -e .

python -c "import archive_workbench; print(archive_workbench.__version__)"
```

Debe devolver `0.75.1`. La copia no mueve ni elimina archivos locales: `project_data`, `.dev`, `.assistant` y los demás contenidos existentes permanecen en su lugar. La carpeta temporal debe conservarse hasta terminar la validación.

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

## 4. Validación controlada corregida de CAT-01

La preparación crea una base descartable nueva en `~/Downloads`. No lee ni modifica `project_data`. No uses `--force`: si la ruta ya existe, el bloque se detiene sin reemplazarla.

```bash
cd ~/projects/archive_app
source .venv/bin/activate

VALIDATION_ROOT="$HOME/Downloads/archive_workbench_catalog_template_validation_0751"

test ! -e "$VALIDATION_ROOT" && \
python scripts/create_catalog_template_validation_project.py \
  --destination "$VALIDATION_ROOT" && \
archive-workbench catalog-template-validate \
  "$VALIDATION_ROOT" \
  "$VALIDATION_ROOT/validation/plantilla_catalogo_dippba.xlsx" \
  --output "$VALIDATION_ROOT/validation/dippba_validation.json"
```

Resultado esperado:

- revisión `0040_discovery_grouping_continuity`;
- proyecto neutral `Proyecto de validación CAT-01 (cat01_validation)`;
- plantilla DIPPBA con 155 filas;
- simulación válida con 155 unidades para crear y cero errores;
- confirmación explícita de que `project_data` no fue leído ni modificado.

## 5. Revisión manual limitada a la corrección

```bash
cd ~/projects/archive_app
source .venv/bin/activate

VALIDATION_ROOT="$HOME/Downloads/archive_workbench_catalog_template_validation_0751"
archive-workbench review-app "$VALIDATION_ROOT"
```

En **Catálogo documental → Importar o exportar una plantilla XLSX**:

1. Descargá una plantilla vacía. Debe mostrar el proyecto neutral de validación, no el Archivo Provincial de la Memoria de Chubut.
2. Debe haber tres hojas visibles: `INSTRUCCIONES`, `ESTRUCTURA` y `CATALOGO`. `LISTAS` existe como hoja auxiliar oculta para sostener los desplegables; no hace falta editarla.
3. Cargá `validation/plantilla_catalogo_dippba.xlsx`: debe mostrar 155 filas para crear y cero errores.
4. Escribí `IMPORTAR`. El botón **Aplicar plantilla** debe permanecer habilitado; al pulsarlo debe aplicar las 155 filas.
5. Confirmá la jerarquía Archivo → Fondo DIPPBA → secciones, subsecciones, series y subseries.
6. Exportá el catálogo actual, volvé a cargar ese XLSX y aplicalo: debe indicar 155 unidades sin cambios y no crear revisiones nuevas.

Detené Streamlit con `Ctrl+C` al terminar. La base descartable no se elimina automáticamente.

## 6. Resultado de la validación

`CAT-01` quedó validado el 2026-08-04 mediante los proyectos descartables `archive_workbench_catalog_template_validation_0750` y `archive_workbench_catalog_template_validation_0751`:

- revisión `0040_discovery_grouping_continuity`;
- rechazo correcto de un `documento` como hijo directo de un `fondo`;
- proyecto neutral `Proyecto de validación CAT-01 (cat01_validation)`;
- tres hojas visibles (`INSTRUCCIONES`, `ESTRUCTURA` y `CATALOGO`) y `LISTAS` como hoja auxiliar oculta;
- simulación e importación correctas de las 155 filas de la plantilla DIPPBA;
- botón **Aplicar plantilla** operativo después de escribir `IMPORTAR`;
- jerarquía Archivo → Fondo DIPPBA → secciones → subsecciones → series → subseries conservada;
- reexportación y reimportación idéntica con 155 unidades sin cambios y sin revisiones nuevas;
- `project_data` no fue leído ni modificado.

Las bases descartables y los temporales de instalación se conservan hasta recibir autorización expresa para eliminarlos.
