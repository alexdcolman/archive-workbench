# Actualización y prueba — Archive Workbench 0.65.0

## Objetivo

Esta versión implementa `EX-01A`: diagnóstico de evidencia para paquetes de intercambio cuya simulación quedó sin base reconocida (`unmatched`). El diagnóstico es estrictamente de solo lectura: no recupera linaje, no crea una base común, no modifica el corpus y no agrega registros persistentes.

La SQLite vigente y el paquete recibido se verifican siempre. De manera opcional pueden indicarse rutas explícitas a paquetes anteriores, archivos `manifest.json` o backups de proyecto. Cada artefacto queda explicado como evidencia concluyente, de apoyo o rechazada, y el resultado se clasifica como recuperable, ambiguo o insuficiente.

## 1. Actualizar el código

Detené Streamlit con `Ctrl+C` y ejecutá:

```bash
cd ~/projects/archive_app
source .venv/bin/activate

rm -rf /tmp/archive_workbench_v0.65.0
mkdir -p /tmp/archive_workbench_v0.65.0

unzip -q \
  ~/Downloads/archive_workbench_v0.65.0.zip \
  -d /tmp/archive_workbench_v0.65.0

cp -a /tmp/archive_workbench_v0.65.0/. .

pip install -e ".[dev,extraction,streamlit,semantic,tiff]"
```

Comprobá:

```bash
python -c "import archive_workbench; print(archive_workbench.__version__)"
```

Debe devolver:

```text
0.65.0
```

## 2. Base de datos

Esta versión **no contiene una migración**. No ejecutes `db-upgrade`.

La revisión continúa siendo:

```text
0034_automatic_analysis_authorizations
```

No repitas ninguna prueba de `DATA-01` o `DATA-02`.

## 3. Pruebas automatizadas

Ejecutá primero las regresiones nuevas de `EX-01A`:

```bash
pytest -q tests/test_exchange.py \
  -k "lineage_diagnostic or lineage_validation_script or exchange_lineage_diagnose"
```

Esperado:

```text
10 passed, 54 deselected
```

Después ejecutá navegación, documentación y empaquetado:

```bash
pytest -q tests/test_ui_navigation.py
```

Esperado:

```text
43 passed
```

```bash
pytest -q \
  tests/test_documentation.py \
  tests/test_packaging.py
```

Esperado:

```text
39 passed
```

Finalmente:

```bash
pytest --collect-only -q
```

Debe recopilar:

```text
367 tests
```

En construcción también pasaron nueve regresiones críticas del intercambio previo: inspección y alteración de paquetes, clasificación con y sin base, reconocimiento de aplicaciones anteriores, aplicación transaccional, rechazo de simulaciones obsoletas y gestión del ciclo de vida. No ejecuté nuevamente la suite monolítica completa.

También se construyó correctamente:

```text
archive_workbench-0.65.0-py3-none-any.whl
```

## 4. Crear las copias descartables

Con Streamlit cerrado, ejecutá:

```bash
rm -rf \
  project_data_lineage_source_validation \
  project_data_lineage_receiver_validation

python scripts/create_lineage_diagnostic_validation_projects.py \
  --source project_data_rebase_validation \
  --source-destination project_data_lineage_source_validation \
  --receiver-destination project_data_lineage_receiver_validation
```

El script debe informar:

- las dos copias descartables;
- revisión `0034_automatic_analysis_authorizations`;
- un identificador de paquete sin base reconocida;
- una ruta de evidencia concluyente;
- una ruta de manifiesto aislado;
- una ruta `validation.json`.

El proyecto `project_data_rebase_validation` no se modifica.

Prepará las variables para los comandos siguientes:

```bash
VALIDATION_FILE="project_data_lineage_receiver_validation/exchange/lineage_evidence/validation.json"

BUNDLE_ID="$(python -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["target_bundle_id"])' \
  "$VALIDATION_FILE")"

EVIDENCE_BUNDLE="$(python -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["evidence_bundle_path"])' \
  "$VALIDATION_FILE")"

SUPPORT_MANIFEST="$(python -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["support_manifest_path"])' \
  "$VALIDATION_FILE")"

printf 'BUNDLE_ID=%s\nEVIDENCE_BUNDLE=%s\nSUPPORT_MANIFEST=%s\n' \
  "$BUNDLE_ID" "$EVIDENCE_BUNDLE" "$SUPPORT_MANIFEST"
```

## 5. Diagnóstico desde terminal

Primero ejecutá el diagnóstico sin evidencia adicional:

```bash
archive-workbench exchange-lineage-diagnose \
  project_data_lineage_receiver_validation \
  "$BUNDLE_ID"
```

Debe mostrar:

- resultado `insuficiente`;
- cero candidatos concluyentes;
- el paquete recibido como evidencia de apoyo;
- la aclaración de que no se escribió ningún dato.

Comprobá después que un manifiesto aislado sigue siendo solamente evidencia de apoyo:

```bash
archive-workbench exchange-lineage-diagnose \
  project_data_lineage_receiver_validation \
  "$BUNDLE_ID" \
  --evidence "$SUPPORT_MANIFEST"
```

Debe seguir mostrando `insuficiente` e incluir `isolated_manifest`.

Finalmente agregá el paquete anterior íntegro:

```bash
archive-workbench exchange-lineage-diagnose \
  project_data_lineage_receiver_validation \
  "$BUNDLE_ID" \
  --evidence "$EVIDENCE_BUNDLE"
```

Debe mostrar:

- resultado `recuperable`;
- una única cadena concluyente;
- método `verified_bundle_chain`;
- el paquete de evidencia dentro de la cadena;
- cero contradicciones;
- la aclaración de que no se escribió ningún dato.

## 6. Diagnóstico desde la interfaz

Abrí la copia receptora:

```bash
archive-workbench review-app project_data_lineage_receiver_validation
```

Entrá en:

```text
Intercambiar cambios
```

Debe aparecer un paquete recibido con **Base: Sin base reconocida**.

Abrí **Diagnosticar evidencia de linaje**.

### Sin evidencia adicional

Dejá vacío **Rutas de evidencia adicional** y pulsá:

```text
Ejecutar diagnóstico de solo lectura
```

Debe aparecer:

```text
Resultado: Insuficiente
```

No debe aparecer ningún botón para recuperar linaje o establecer una base común.

### Con evidencia concluyente

Pegá exactamente la ruta mostrada antes en `EVIDENCE_BUNDLE` y pulsá nuevamente el botón.

Debe aparecer:

```text
Resultado: Recuperable
```

Además debe mostrar:

- una cadena concluyente;
- método `verified_bundle_chain`;
- el punto local `baseline_ex01a`;
- una evidencia `verified_bundle`;
- cero contradicciones;
- la leyenda que aclara que el resultado no habilita escrituras y que la recuperación corresponde a `EX-01B`.

No resuelvas campos ni apliques el paquete. Detené Streamlit con `Ctrl+C`.

## 7. Verificar ausencia de escrituras de linaje e integridad

Ejecutá:

```bash
python - <<'PY'
from pathlib import Path

from sqlalchemy import inspect, text

from archive_workbench.db import (
    create_sqlite_engine,
    current_revision,
    database_path,
)

root = Path("project_data_lineage_receiver_validation")
engine = create_sqlite_engine(database_path(root))

try:
    with engine.connect() as connection:
        counts = {
            table: connection.execute(
                text(f'SELECT COUNT(*) FROM "{table}"')
            ).scalar_one()
            for table in (
                "exchange_checkpoints",
                "exchange_bundle_applications",
                "exchange_bundle_records",
                "exchange_dry_runs",
            )
        }
        tables = set(inspect(connection).get_table_names())
        integrity = connection.execute(text("PRAGMA integrity_check")).scalar_one()
        foreign_keys = connection.execute(text("PRAGMA foreign_key_check")).all()

    assert counts == {
        "exchange_checkpoints": 1,
        "exchange_bundle_applications": 0,
        "exchange_bundle_records": 1,
        "exchange_dry_runs": 1,
    }
    assert "exchange_lineage_cases" not in tables
    assert "exchange_lineage_evidence" not in tables
    assert "exchange_lineage_decisions" not in tables
    assert current_revision(root) == "0034_automatic_analysis_authorizations"
    assert integrity == "ok"
    assert foreign_keys == []

    print("registros de intercambio:", counts)
    print("tablas de escritura EX-01:", "ausentes")
    print("revisión:", current_revision(root))
    print("integridad:", integrity)
    print("claves foráneas:", foreign_keys)
finally:
    engine.dispose()
PY
```

Debe mostrar:

```text
registros de intercambio: {'exchange_checkpoints': 1, 'exchange_bundle_applications': 0, 'exchange_bundle_records': 1, 'exchange_dry_runs': 1}
tablas de escritura EX-01: ausentes
revisión: 0034_automatic_analysis_authorizations
integridad: ok
claves foráneas: []
```

`EX-01A` permanece activo únicamente hasta confirmar esta validación manual. Después se registra su cierre y comienza `EX-01B`, que agregará la recuperación append-only mediante una migración separada.
