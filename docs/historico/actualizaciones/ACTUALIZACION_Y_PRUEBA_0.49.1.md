# Archive Workbench 0.49.1 — actualización y continuación de la validación

Esta versión corrige el bloqueo circular de las casillas de confirmación dentro de formularios. No agrega migraciones: los proyectos que ya están en `0033_export_exchange_lifecycle` permanecen en esa revisión.

## Actualizar desde 0.49.0

Detené Streamlit y ejecutá:

```bash
cd ~/projects/archive_app
source .venv/bin/activate

rm -rf /tmp/archive_workbench_v0.49.1

unzip -q \
  ~/Downloads/archive_workbench_v0.49.1.zip \
  -d /tmp

cp -a /tmp/archive_workbench_v0.49.1/. .

pip install -e ".[dev,extraction,streamlit,semantic,tiff]"
```

Comprobá:

```bash
python -c "import archive_workbench; print(archive_workbench.__version__)"
```

Debe devolver `0.49.1`. No ejecutes `db-upgrade`: la revisión sigue siendo `0033_export_exchange_lifecycle`.

## Pruebas automatizadas

Bloque directamente afectado:

```bash
pytest -q \
  tests/test_ui_navigation.py \
  tests/test_exchange.py::test_incoming_bundle_diagnostics_and_lifecycle_management \
  tests/test_corpus_export.py \
  tests/test_documentation.py \
  tests/test_packaging.py
```

Resultado esperado:

```text
48 passed
```

Después podés ejecutar la suite completa:

```bash
pytest
```

## Continuación manual desde el punto actual

### 1. Archivar el bundle `stale`

```bash
archive-workbench review-app project_data_exchange_receiver
```

Entrá en **Intercambio**, seleccioná el bundle `stale` y comprobá antes de actuar que todavía identifica `CAMBIO LOCAL POST DRY-RUN`.

En **Nota de archivo opcional** escribí:

```text
Dry-run obsoleto validado en 0.49.1
```

Marcá **Confirmo que deseo archivar esta entrada**. El botón **Archivar bundle** debe poder pulsarse. Pulsalo y comprobá que la entrada desaparece de la lista normal.

### 2. Restaurar, volver a archivar y limpiar

Activá **Mostrar bundles archivados**, seleccioná la entrada y comprobá que muestra autor, fecha y nota.

1. Marcá la confirmación y pulsá **Restaurar entrada**.
2. Archivala nuevamente.
3. Mostrá los archivados, seleccionala, marcá la confirmación y pulsá **Limpiar entrada**.

Esperado:

- la entrada y sus archivos internos se eliminan;
- los dos bundles aplicados continúan visibles;
- `CAMBIO REMOTO 1`, `CAMBIO LOCAL DEL RECEPTOR` y `CAMBIO REMOTO 2` continúan presentes;
- no se crea un backup ni se modifica el corpus.

Cerrá Streamlit.

### 3. Confirmación persistente de exportación

```bash
archive-workbench review-app project_data_rebase_validation
```

En **Exportar**, seleccioná **Validación exportación v0.48.0**. En **Configurar**, comprobá la cantidad de exportaciones históricas vinculadas y sus rutas.

En **Exportar**, elegí JSONL y usá:

```text
exports/validacion_exportacion_v049.jsonl
```

Pulsá **Crear exportación** una vez. La confirmación debe persistir y mostrar ruta, formato, registros, caracteres, tamaño, SHA-256 y **Descargar archivo**. Cambiá a **Historial** y regresá: debe seguir visible hasta pulsar **Cerrar confirmación**.

### 4. Ciclo de vida del perfil

En **Configurar**:

1. Marcá la confirmación y pulsá **Archivar perfil**.
2. Activá **Mostrar perfiles archivados** y seleccioná el perfil archivado.
3. Verificá que las exportaciones históricas siguen listadas.
4. Marcá la confirmación y pulsá **Restaurar perfil**.
5. Archivá otra vez el perfil.
6. Mostrá los archivados, seleccionalo, marcá la confirmación y pulsá **Eliminar perfil definitivamente**.

En **Historial** deben continuar las exportaciones y en terminal deben seguir existiendo:

```bash
ls -lh \
  project_data_rebase_validation/exports/validacion_exportacion_v048.jsonl \
  project_data_rebase_validation/exports/validacion_exportacion_v049.jsonl
```

### 5. Integridad final

```bash
python - <<'PY'
import sqlite3

for project in (
    "project_data_rebase_validation",
    "project_data_exchange_receiver",
    "project_data_exchange_unmatched",
):
    path = f"{project}/data/archive_workbench.sqlite3"
    with sqlite3.connect(path) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
    print(project, "integrity_check:", integrity)
    print(project, "foreign_key_check:", foreign_keys)
PY
```

Cada proyecto debe devolver `integrity_check: ok` y `foreign_key_check: []`.
