# Archive Workbench 0.49.0 — actualización y validación

## Qué cambia

- Corrige el error `NameError: by_event is not defined` al abrir bundles sin base común con varios eventos revisables.
- Explica globalmente el linaje no reconocido y evita aceptar masivamente creaciones recibidas sin una base verificable.
- Los bundles `stale` muestran la secuencia evaluada, la secuencia actual y los cambios locales posteriores que volvieron caduco el dry-run.
- Los bundles recibidos pueden archivarse, restaurarse y, si nunca fueron aplicados, limpiarse sin modificar el corpus.
- La confirmación de una exportación permanece visible e incluye ruta, formato, registros, caracteres, tamaño, SHA-256 y descarga directa.
- Los perfiles de exportación pueden archivarse, restaurarse y eliminarse con confirmación; las exportaciones históricas y sus archivos se conservan.

Esta versión agrega la migración `0033_export_exchange_lifecycle`.

## Actualizar desde 0.48.0

Detené Streamlit con `Ctrl+C`. Antes de migrar cada proyecto operativo, creá un backup. Por ejemplo:

```bash
cd ~/projects/archive_app
source .venv/bin/activate

archive-workbench project-backup-create \
  project_data \
  --created-by alex \
  --note "Antes de actualizar a 0.49.0"
```

Después actualizá el código:

```bash
rm -rf /tmp/archive_workbench_v0.49.0

unzip -q \
  ~/Downloads/archive_workbench_v0.49.0.zip \
  -d /tmp

cp -a /tmp/archive_workbench_v0.49.0/. .

pip install -e ".[dev,extraction,streamlit,semantic,tiff]"
```

Comprobá:

```bash
python -c "import archive_workbench; print(archive_workbench.__version__)"
```

Debe devolver:

```text
0.49.0
```

Migrá los proyectos descartables usados en esta validación:

```bash
for project in \
  project_data_rebase_validation \
  project_data_exchange_origin \
  project_data_exchange_receiver \
  project_data_exchange_unmatched
do
  if [ -d "$project" ]; then
    archive-workbench db-upgrade "$project"
  fi
done
```

Cada uno debe quedar en:

```text
0033_export_exchange_lifecycle
```

Aplicá también `archive-workbench db-upgrade <proyecto>` a cada proyecto real después de su backup y antes de volver a abrirlo.

## Pruebas automatizadas

Primero, migración, exportación, interfaz y documentación:

```bash
pytest \
  tests/test_database.py \
  tests/test_corpus_export.py \
  tests/test_ui_navigation.py \
  tests/test_documentation.py \
  tests/test_packaging.py
```

Resultado esperado:

```text
55 passed
```

Después, el bloque de intercambio directamente afectado:

```bash
pytest -q \
  tests/test_exchange.py::test_exchange_migration_upgrades_existing_0012_database \
  tests/test_exchange.py::test_dry_run_migration_upgrades_populated_0013_database \
  tests/test_exchange.py::test_dry_run_classifies_clean_incoming_event_as_applicable \
  tests/test_exchange.py::test_dry_run_recognizes_applied_bundle_lineage_after_local_resolution \
  tests/test_exchange.py::test_dry_run_without_common_checkpoint_requires_review \
  tests/test_exchange.py::test_apply_ready_bundle_is_transactional_and_creates_backup \
  tests/test_exchange.py::test_apply_refuses_conflicted_bundle_before_backup \
  tests/test_exchange.py::test_apply_rejects_stale_dry_run_before_creating_backup \
  tests/test_exchange.py::test_incoming_bundle_diagnostics_and_lifecycle_management \
  tests/test_exchange.py::test_unmatched_bundle_with_multiple_creations_exposes_all_review_fields
```

Resultado esperado:

```text
10 passed
```

Finalmente:

```bash
pytest
```

Resultado objetivo:

```text
273 passed
```

## Validación manual — solo cambios de 0.49.0

Las observaciones están indicadas antes de cada acción. No resuelvas los 21 campos del bundle sin base común.

### 1. Bundle sin base común: corrección de la interfaz

Abrí la copia que ya conserva el bundle de tres eventos:

```bash
archive-workbench review-app project_data_exchange_unmatched
```

Entrá en **Intercambio** y seleccioná el bundle `needs_review` / `unmatched`.

Antes de tocar controles, comprobá:

- no aparece `NameError`;
- se muestran `3` eventos, `21` campos y `21` pendientes;
- aparece una explicación que comienza con **No se encontró un checkpoint que demuestre una base común**;
- la decisión conjunta ofrece solamente **Conservar todos los valores locales**: no ofrece aceptar todo lo recibido;
- aparecen tres paneles de evento, cada uno con siete campos;
- **Todo recibido en este evento** está desactivado para las tres creaciones;
- **Finalizar resoluciones** y **Aplicar bundle** permanecen desactivados.

No marques confirmaciones ni guardes decisiones. Cerrá Streamlit con `Ctrl+C`.

### 2. Bundle `stale`: explicación, archivo y limpieza

Abrí el receptor que conserva `CAMBIO LOCAL POST DRY-RUN`:

```bash
archive-workbench review-app project_data_exchange_receiver
```

Entrá en **Intercambio** y seleccioná el bundle `stale`.

Antes de archivarlo, comprobá:

- muestra la secuencia evaluada y la secuencia actual;
- abre **Cambios locales posteriores al dry-run**;
- el detalle identifica el evento local posterior y muestra `CAMBIO LOCAL POST DRY-RUN`;
- **Aplicar bundle** continúa desactivado.

En **Nota de archivo opcional** escribí:

```text
Dry-run obsoleto validado en 0.49.0
```

Marcá la confirmación y pulsá **Archivar bundle**. Debe desaparecer de la lista normal.

Activá **Mostrar bundles archivados**, seleccioná la entrada archivada y comprobá que muestra autor, fecha y nota. Marcá la confirmación y pulsá **Restaurar entrada**.

Archivala nuevamente. Volvé a mostrar archivados, seleccionala, marcá la confirmación de eliminación y pulsá **Limpiar entrada**.

Esperado:

- informa que eliminó la entrada y sus archivos internos;
- los dos bundles aplicados continúan visibles;
- las tres entidades del receptor continúan presentes;
- no se crea un backup ni se modifica el corpus.

Cerrá Streamlit.

### 3. Confirmación persistente de exportación

Abrí:

```bash
archive-workbench review-app project_data_rebase_validation
```

Entrá en **Exportar** y seleccioná el perfil **Validación exportación v0.48.0**.

En **Configurar**, comprobá primero que aparece la cantidad de **Exportaciones históricas vinculadas a este perfil** y que el panel permite ver sus rutas.

Entrá en **Exportar**, elegí JSONL y usá esta ruta nueva:

```text
exports/validacion_exportacion_v049.jsonl
```

Pulsá **Crear exportación** una sola vez. Debe aparecer y permanecer visible:

```text
Exportación creada correctamente
```

La confirmación debe incluir:

- ruta;
- formato;
- registros y caracteres;
- tamaño;
- SHA-256;
- botón **Descargar archivo**.

Entrá en **Historial** y luego regresá a **Exportar**: la confirmación debe seguir visible hasta pulsar **Cerrar confirmación**. Cerrala después de comprobarlo.

### 4. Archivar, restaurar y eliminar el perfil

Volvé a **Configurar** con el mismo perfil seleccionado.

1. Marcá la confirmación y pulsá **Archivar perfil**.
2. Comprobá que queda oculto con **Mostrar perfiles archivados** desactivado.
3. Activá **Mostrar perfiles archivados** y seleccioná `[Archivado] Validación exportación v0.48.0`.
4. Comprobá que siguen listadas las exportaciones `validacion_exportacion_v048.jsonl` y `validacion_exportacion_v049.jsonl`.
5. Marcá la confirmación y pulsá **Restaurar perfil**.
6. Archivá nuevamente el perfil.
7. Mostrá los archivados, seleccionalo, marcá la confirmación y pulsá **Eliminar perfil definitivamente**.

En **Historial** deben continuar las dos exportaciones, con sus rutas y hashes. En terminal, ambos archivos deben seguir existiendo:

```bash
ls -lh \
  project_data_rebase_validation/exports/validacion_exportacion_v048.jsonl \
  project_data_rebase_validation/exports/validacion_exportacion_v049.jsonl
```

### 5. Integridad final

Cerrá Streamlit y ejecutá:

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

Para cada proyecto debe devolver `integrity_check: ok` y `foreign_key_check: []`.
