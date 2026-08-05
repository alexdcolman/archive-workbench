# Actualización y uso — Archive Workbench 0.78.0

La versión 0.78.0 implementa y valida `OCR-01A`: orientación conservadora, deskew acotado y eliminación controlada de líneas o marcos sobre el derivado destinado a OCR. El original y la previsualización permanecen intactos. Cada página conserva el análisis, las transformaciones aplicadas u omitidas y una máscara diagnóstica.

La migración `0042_preprocessing_geometry_trace` es aditiva: agrega `analysis_json` y `transformations_json` a `derivative_assets`. `project_data` solo debe migrarse después de crear y verificar un backup SQLite.

No se repiten pruebas manuales de bloques ya cerrados: `UX-03`, `DISC-01A/B/C/D`, `SEM-01`, `GRAPH-01`, `OCR-02`, `CAT-01`, `DISC-02`, `CAT-02`, `GRAPH-02` y `OCR-01A`.

## 1. Actualizar desde el ZIP

```bash
(
  set -euo pipefail

  cd ~/Downloads
  sha256sum -c archive_workbench_v0.78.0.zip.sha256

  cd ~/projects/archive_app
  source .venv/bin/activate

  TMP_DIR="$(mktemp -d "$HOME/Downloads/archive_workbench_0780_final_XXXXXX")"
  unzip -q "$HOME/Downloads/archive_workbench_v0.78.0.zip" -d "$TMP_DIR"
  cp -a "$TMP_DIR"/. .

  python -m pip install --no-build-isolation -e .
  python -c "import archive_workbench; print(archive_workbench.__version__)"

  printf '\nTemporal conservado: %s\n' "$TMP_DIR"
)
```

Debe informar checksum correcto y versión `0.78.0`. La copia no mueve ni elimina `.git`, `.venv`, `project_data`, bases de validación ni temporales.

## 2. Respaldar y migrar `project_data`

```bash
(
  set -euo pipefail

  cd ~/projects/archive_app
  source .venv/bin/activate

  PROJECT_ROOT="$HOME/projects/archive_app/project_data"
  DB_PATH="$PROJECT_ROOT/data/archive_workbench.sqlite3"
  BACKUP_DIR="$HOME/Downloads/archive_workbench_backups"
  STAMP="$(date +%Y%m%d_%H%M%S)"
  BACKUP_PATH="$BACKUP_DIR/project_data_pre_0780_${STAMP}.sqlite3"

  test -f "$DB_PATH" || {
    echo "ERROR: no existe $DB_PATH"
    exit 1
  }

  mkdir -p "$BACKUP_DIR"

  python - "$DB_PATH" "$BACKUP_PATH" <<'PY'
from pathlib import Path
import sqlite3
import sys

source_path = Path(sys.argv[1]).resolve()
backup_path = Path(sys.argv[2]).resolve()

source = sqlite3.connect(source_path)
backup = sqlite3.connect(backup_path)
try:
    check = source.execute("PRAGMA quick_check").fetchone()[0]
    if check != "ok":
        raise SystemExit(f"La base original no pasó quick_check: {check}")
    source.backup(backup)
    check = backup.execute("PRAGMA quick_check").fetchone()[0]
    if check != "ok":
        raise SystemExit(f"El backup no pasó quick_check: {check}")
finally:
    backup.close()
    source.close()

print(f"Backup verificado: {backup_path}")
PY

  sha256sum "$BACKUP_PATH" | tee "$BACKUP_PATH.sha256"

  archive-workbench db-status "$PROJECT_ROOT"
  archive-workbench db-upgrade "$PROJECT_ROOT"
  archive-workbench db-status "$PROJECT_ROOT"
)
```

La revisión final debe ser `0042_preprocessing_geometry_trace`. El backup y su checksum se conservan en `~/Downloads/archive_workbench_backups`.

## 3. Uso de OCR-01A

En **Procesar documentos → Ejecutar**, elegí la corrección geométrica conservadora al preparar páginas. El panel **Mostrar diagnóstico geométrico vigente** permite comparar:

- **Previsualización sin cambios**;
- **Derivado OCR**;
- **Máscara de líneas eliminadas**.

La tabla resume orientación, confianza, rotación, deskew y líneas. El detalle desplegable conserva `applied`, candidato, confianza, umbral y motivo para cada transformación. Una confianza insuficiente mantiene la geometría original y registra la omisión.

La preparación no selecciona automáticamente una extracción como canónica. Esa decisión continúa siendo explícita y separada.

La validación manual se realizó sobre una base descartable creada con `create_preprocessing_geometry_validation_project.py`. Incluyó **Página rotada 90°**, **Página inclinada 3°**, **Página con marco**, **Línea que cruza texto** y **Página de baja confianza**. El resumen confirmó `originals_unchanged: true` y `project_data_touched: false`.

## 4. Pruebas de la versión

```bash
(
  set -euo pipefail

  cd ~/projects/archive_app
  source .venv/bin/activate

  pytest tests/test_preprocessing.py
  pytest tests/test_processing.py tests/test_contracts.py
  pytest \
    tests/test_database.py::test_migration_and_registration_are_idempotent \
    tests/test_database.py::test_preprocessing_geometry_migration_preserves_existing_derivative_assets
  pytest tests/test_ocr_quality.py
  pytest tests/test_extraction.py
  pytest tests/test_ui_navigation.py tests/test_operational.py
  pytest tests/test_documentation.py tests/test_packaging.py

  pytest --collect-only -q
)
```

La validación de 0.78.0 aprobó 132 pruebas relevantes y recopiló 450 pruebas en 42 archivos. La prueba manual confirmó los cinco casos controlados y dejó `OCR-01A` cerrada.

El push se entregará siempre como un paso separado después de revisar las salidas de actualización, migración, pruebas, commit y tag.
