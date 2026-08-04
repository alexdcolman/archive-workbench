# Actualización y prueba — Archive Workbench 0.76.0

Esta versión implementa `DISC-02`: importación JSON versionada de autoridades, alias y relaciones con simulación, duplicados, resolución explícita, evidencia obligatoria y aplicación transaccional. No modifica el esquema de la base.

## 1. Actualizar sin mover ni eliminar archivos locales

```bash
cd ~/projects/archive_app
source .venv/bin/activate

TMP_DIR="$(mktemp -d)"
unzip -q \
  ~/Downloads/archive_workbench_v0.76.0.zip \
  -d "$TMP_DIR"

cp -a "$TMP_DIR"/. .

python -m pip install \
  --no-build-isolation \
  -e .

python -c "import archive_workbench; print(archive_workbench.__version__)"
```

Debe devolver `0.76.0`. La copia no mueve ni elimina `project_data`, `.dev`, `.assistant` ni otros contenidos locales. Conservá la carpeta temporal hasta terminar la validación.

## 2. Base de datos

**No hay migración.** La revisión requerida continúa en `0040_discovery_grouping_continuity`. No ejecutar `db-upgrade` para esta actualización.

## 3. Pruebas relevantes y colección completa

```bash
pytest -q \
  tests/test_authority_dictionary.py \
  tests/test_relations.py \
  tests/test_ui_navigation.py \
  tests/test_documentation.py \
  tests/test_packaging.py && \
pytest --collect-only -q
```

No repetir `UX-03`, `DISC-01A/B/C/D`, `SEM-01`, `GRAPH-01` ni `CAT-01`: esos bloques ya están validados.

## 4. Validación controlada de DISC-02

La preparación crea una base descartable nueva en `~/Downloads`. No lee ni modifica `project_data`. No uses `--force`: si la ruta ya existe, el bloque se detiene sin reemplazarla.

```bash
cd ~/projects/archive_app
source .venv/bin/activate

VALIDATION_ROOT="$HOME/Downloads/archive_workbench_authority_dictionary_validation_0760"

test ! -e "$VALIDATION_ROOT" && \
python scripts/create_authority_dictionary_validation_project.py \
  --destination "$VALIDATION_ROOT" && \
archive-workbench authority-dictionary-validate \
  "$VALIDATION_ROOT" \
  "$VALIDATION_ROOT/validation/diccionario_autoridades_valido.json" \
  --output "$VALIDATION_ROOT/validation/dictionary_validation.json"
```

Resultado esperado:

- revisión `0040_discovery_grouping_continuity`;
- proyecto neutral `Proyecto de validación DISC-02 (disc02_validation)`;
- dos autoridades para crear y una para reutilizar;
- dos alias y dos relaciones para crear;
- cero errores;
- una advertencia porque la ficha existente no será sobrescrita;
- confirmación explícita de que `project_data` no fue leído ni modificado.

## 5. Revisión manual limitada a DISC-02

```bash
cd ~/projects/archive_app
source .venv/bin/activate

VALIDATION_ROOT="$HOME/Downloads/archive_workbench_authority_dictionary_validation_0760"
archive-workbench review-app "$VALIDATION_ROOT"
```

En **Entidades y menciones → Importar diccionario**:

1. Descargá el ejemplo y el esquema JSON; ambos deben indicar versión `1.0`.
2. Cargá `validation/diccionario_conflicto_sin_resolver.json`: debe mostrar una coincidencia ambigua y exigir `resolution`.
3. Cargá `validation/diccionario_relacion_sin_evidencia.json`: debe rechazar el archivo porque la relación no tiene evidencia.
4. Cargá `validation/diccionario_autoridades_valido.json`: debe mostrar dos autoridades nuevas, una reutilizada, dos alias y dos relaciones nuevas.
5. Escribí `IMPORTAR` y aplicá. La ficha previa de la Comisión Provincial por la Memoria debe conservar su descripción, recibir el alias nuevo y quedar vinculada a la unidad archivística de control.
6. Volvé a cargar y aplicar el mismo JSON: debe crear cero autoridades, cero alias y cero relaciones; las dos relaciones deben aparecer como duplicados omitidos.

Detené Streamlit con `Ctrl+C` al terminar. La base descartable no se elimina automáticamente.

## 6. Resultado de la validación

`DISC-02` quedó validado el 2026-08-04 mediante el proyecto descartable `archive_workbench_authority_dictionary_validation_0760`:

- revisión `0040_discovery_grouping_continuity` y proyecto neutral `Proyecto de validación DISC-02 (disc02_validation)`;
- ejemplo y JSON Schema correctamente identificados con la versión `1.0`;
- coincidencia nominal ambigua detectada y bloqueada hasta indicar `resolution`;
- relación sin evidencia rechazada;
- simulación e importación correctas de dos autoridades nuevas, una autoridad reutilizada, dos alias y dos relaciones;
- ficha existente de la Comisión Provincial por la Memoria conservada sin sobrescritura, con el alias nuevo y la relación controlada incorporados;
- reimportación idéntica con cero autoridades, cero alias y cero relaciones nuevas y dos relaciones duplicadas omitidas;
- `project_data` no fue leído ni modificado.

La base descartable y el temporal de instalación se conservan hasta recibir autorización expresa para eliminarlos.
