# Actualización y prueba — Archive Workbench 0.68.0

Esta versión implementa `EX-01D`: una copia puede previsualizar, respaldar, adoptar y revertir explícitamente el estado editable completo de otra copia del mismo proyecto. La adopción no crea parentesco ni activa una base común; el acuerdo bilateral se registra después, cuando ambas copias ya tienen el mismo SHA-256 editable.

También registra como validada `EX-01C` y deja asentado que `project_data` es la base principal de trabajo local, donde se conservan las pruebas OCR. Las bases `project_data_*_validation` son copias descartables.

No repitas ninguna prueba de `DATA-01`, `DATA-02`, `EX-01A`, `EX-01B` o `EX-01C`.

## 1. Actualizar el código

Detené Streamlit con `Ctrl+C` y ejecutá:

```bash
cd ~/projects/archive_app
source .venv/bin/activate

rm -rf /tmp/archive_workbench_v0.68.0
mkdir -p /tmp/archive_workbench_v0.68.0

unzip -q \
  ~/Downloads/archive_workbench_v0.68.0.zip \
  -d /tmp/archive_workbench_v0.68.0

cp -a /tmp/archive_workbench_v0.68.0/. .

pip install -e ".[dev,extraction,streamlit,semantic,tiff]"
```

Comprobá:

```bash
python -c "import archive_workbench; print(archive_workbench.__version__)"
```

Debe devolver:

```text
0.68.0
```

## 2. Pruebas automatizadas

Ejecutá:

```bash
pytest -q tests/test_exchange.py -k "state_adoption"
```

Esperado:

```text
4 passed
```

Después:

```bash
pytest -q tests/test_database.py
```

Esperado:

```text
14 passed
```

Las advertencias del adaptador de fechas de SQLite bajo Python 3.12 no representan fallos.

Luego:

```bash
pytest -q tests/test_ui_navigation.py
```

Esperado:

```text
45 passed
```

Después:

```bash
pytest -q \
  tests/test_documentation.py \
  tests/test_packaging.py
```

Esperado:

```text
41 passed
```

Finalmente:

```bash
pytest --collect-only -q
```

Debe recopilar:

```text
385 tests
```

En construcción también pasaron las regresiones de recuperación de linaje y acuerdos de base común. No se ejecutó nuevamente la suite monolítica completa.

## 3. Respaldar y migrar `project_data`

Esta versión **sí contiene una migración**:

```text
0037_exchange_state_adoptions
```

`project_data` es la base principal de trabajo local y actualmente está en `0033_export_exchange_lifecycle`. No hace falta transferirla: debe respaldarse y migrarse en tu repositorio local.

Con Streamlit cerrado, creá primero el backup:

```bash
archive-workbench project-backup-create \
  project_data \
  --created-by alex \
  --note "Antes de migrar project_data a Archive Workbench 0.68.0"
```

Debe mostrar `OK`, el SHA-256 del backup, el SHA-256 de la base y la revisión anterior:

```text
0033_export_exchange_lifecycle
```

Después migrá:

```bash
archive-workbench db-upgrade project_data
```

Debe finalizar con:

```text
Revisión: 0037_exchange_state_adoptions
```

Comprobá:

```bash
archive-workbench db-status project_data
```

Luego verificá la base y las cantidades principales de OCR:

```bash
python - <<'PY'
from pathlib import Path

from sqlalchemy import inspect, text

from archive_workbench.db import (
    create_sqlite_engine,
    current_revision,
    database_path,
)

root = Path("project_data")
engine = create_sqlite_engine(database_path(root))

try:
    with engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        requested = (
            "digital_objects",
            "extraction_runs",
            "extraction_pages",
            "extracted_objects",
            "editable_pages",
            "editable_objects",
        )
        counts = {
            table: connection.execute(
                text(f'SELECT COUNT(*) FROM "{table}"')
            ).scalar_one()
            for table in requested
            if table in tables
        }
        integrity = connection.execute(
            text("PRAGMA integrity_check")
        ).scalar_one()
        foreign_keys = connection.execute(
            text("PRAGMA foreign_key_check")
        ).all()

    assert current_revision(root) == "0037_exchange_state_adoptions"
    assert integrity == "ok"
    assert foreign_keys == []

    print("registros OCR y editables:", counts)
    print("revisión:", current_revision(root))
    print("integridad:", integrity)
    print("claves foráneas:", foreign_keys)
finally:
    engine.dispose()
PY
```

Debe mostrar la revisión nueva, `integridad: ok` y `claves foráneas: []`. Las cantidades dependen de tus pruebas OCR y no deben aparecer en cero si antes había registros en esas tablas.

Abrí la base principal:

```bash
archive-workbench review-app project_data
```

Comprobá únicamente que la aplicación abre y que las pruebas OCR siguen visibles. No edites nada durante esta comprobación. Detené Streamlit con `Ctrl+C`.

No migres ahora las copias descartables usadas en `EX-01A`, `EX-01B` o `EX-01C`.

## 4. Crear dos copias divergentes para `EX-01D`

Ejecutá:

```bash
rm -rf \
  project_data_state_adoption_source_validation \
  project_data_state_adoption_target_validation

python scripts/create_state_adoption_validation_projects.py \
  --source project_data_rebase_validation \
  --source-destination project_data_state_adoption_source_validation \
  --target-destination project_data_state_adoption_target_validation
```

El script debe informar:

- una copia origen `ex01d-origen`;
- una copia destinataria `ex01d-destino`;
- revisión `0037_exchange_state_adoptions`;
- dos SHA-256 editables diferentes;
- la ruta del paquete inicial;
- la ruta de `validation.json`;
- que el proyecto fuente no fue modificado.

Prepará las variables:

```bash
VALIDATION_FILE="project_data_state_adoption_target_validation/exchange/state_adoption/validation.json"

SOURCE_ROOT="$(python -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["source_root"])' \
  "$VALIDATION_FILE")"

TARGET_ROOT="$(python -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["target_root"])' \
  "$VALIDATION_FILE")"

SOURCE_ID="$(python -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["source_workspace_id"])' \
  "$VALIDATION_FILE")"

SOURCE_NAME="$(python -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["source_workspace_name"])' \
  "$VALIDATION_FILE")"

TARGET_ID="$(python -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["target_workspace_id"])' \
  "$VALIDATION_FILE")"

TARGET_NAME="$(python -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["target_workspace_name"])' \
  "$VALIDATION_FILE")"

INITIAL_PACKAGE="$(python -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["package_path"])' \
  "$VALIDATION_FILE")"

INITIAL_ADOPTION_ID="$(python -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["adoption_id"])' \
  "$VALIDATION_FILE")"

SOURCE_STATE="$(python -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["source_state_sha256"])' \
  "$VALIDATION_FILE")"

TARGET_STATE="$(python -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["target_state_sha256"])' \
  "$VALIDATION_FILE")"

printf 'SOURCE_ROOT=%s\nTARGET_ROOT=%s\nSOURCE_ID=%s\nTARGET_ID=%s\nINITIAL_PACKAGE=%s\nINITIAL_ADOPTION_ID=%s\nSOURCE_STATE=%s\nTARGET_STATE=%s\n' \
  "$SOURCE_ROOT" "$TARGET_ROOT" "$SOURCE_ID" "$TARGET_ID" \
  "$INITIAL_PACKAGE" "$INITIAL_ADOPTION_ID" "$SOURCE_STATE" "$TARGET_STATE"
```

`SOURCE_STATE` y `TARGET_STATE` deben ser diferentes.

## 5. Previsualizar desde terminal sin escribir

Ejecutá:

```bash
archive-workbench exchange-state-adoption-preview \
  "$TARGET_ROOT" \
  "$INITIAL_PACKAGE"
```

Debe mostrar:

- el identificador de adopción;
- estado local y estado recibido diferentes;
- al menos un cambio en `objects`;
- `Vista previa de solo lectura: no se escribió ningún dato.`

Comprobá que todavía no haya adopciones:

```bash
archive-workbench exchange-state-adoptions "$TARGET_ROOT"
```

Esperado:

```text
Total: 0 adopciones
```

## 6. Adoptar el primer paquete desde la interfaz

Abrí la copia destinataria:

```bash
archive-workbench review-app "$TARGET_ROOT"
```

Entrá en:

```text
Intercambiar cambios
→ Reconciliar estados divergentes
→ Previsualizar y adoptar
```

Pegá el valor completo de `INITIAL_PACKAGE` en **Ruta del ZIP completo de estado** y pulsá:

```text
Previsualizar impacto sin escribir
```

Deben aparecer los dos SHA-256 diferentes y una fila de impacto sobre `objects`.

Completá:

```text
Responsable de la adopción: alex
Fundamento de la adopción: Validación EX-01D adopción inicial.
```

Marcá:

```text
Confirmo que deseo crear un backup y reemplazar transaccionalmente el estado editable local
```

Pulsá **Adoptar estado recibido** una sola vez.

Debe aparecer un mensaje con:

- el identificador de adopción;
- la ruta del backup previo;
- la indicación de que después deben comprobarse los hashes y registrar la base común bilateral.

No crees todavía una base común. Detené Streamlit con `Ctrl+C`.

Listá la adopción:

```bash
archive-workbench exchange-state-adoptions "$TARGET_ROOT"
```

Debe mostrar una única adopción `activa`, origen `ex01d-origen`, responsable `alex` y fundamento:

```text
Validación EX-01D adopción inicial.
```

## 7. Comprobar que ambos estados quedaron iguales

```bash
python - <<'PY'
from pathlib import Path

from sqlalchemy import select

from archive_workbench.db import (
    create_sqlite_engine,
    database_path,
    session_scope,
)
from archive_workbench.db.models import Project
from archive_workbench.exchange import current_editable_state_sha256

roots = {
    "origen": Path("project_data_state_adoption_source_validation"),
    "destino": Path("project_data_state_adoption_target_validation"),
}

states = {}
for label, root in roots.items():
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            project_id = session.scalar(select(Project.id))
            assert project_id
            states[label] = current_editable_state_sha256(
                session, project_id
            )
    finally:
        engine.dispose()

assert states["origen"] == states["destino"]
print("estados después de adoptar:", states)
PY
```

Los dos hashes deben coincidir.

## 8. Revertir la primera adopción

Con Streamlit cerrado:

```bash
archive-workbench exchange-state-adoption-rollback \
  "$TARGET_ROOT" \
  "$INITIAL_ADOPTION_ID" \
  --rolled-back-by alex \
  --reason "Validación EX-01D rollback." \
  --confirm-rollback
```

Debe mostrar:

- `OK: adopción revertida`;
- el estado restaurado;
- el backup original restaurado;
- un backup de seguridad del estado posterior;
- su SHA-256.

Listá nuevamente:

```bash
archive-workbench exchange-state-adoptions "$TARGET_ROOT"
```

La adopción debe aparecer como `revertida`, con:

```text
fundamento rollback: Validación EX-01D rollback.
```

Comprobá que volvió el hash destinatario original:

```bash
python - <<'PY'
import json
from pathlib import Path

from sqlalchemy import select

from archive_workbench.db import (
    create_sqlite_engine,
    database_path,
    session_scope,
)
from archive_workbench.db.models import Project
from archive_workbench.exchange import current_editable_state_sha256

validation = json.loads(
    Path(
        "project_data_state_adoption_target_validation/"
        "exchange/state_adoption/validation.json"
    ).read_text(encoding="utf-8")
)
root = Path(validation["target_root"])
engine = create_sqlite_engine(database_path(root))
try:
    with session_scope(engine) as session:
        project_id = session.scalar(select(Project.id))
        assert project_id
        observed = current_editable_state_sha256(session, project_id)
finally:
    engine.dispose()

assert observed == validation["target_state_sha256"]
assert observed != validation["source_state_sha256"]
print("estado restaurado:", observed)
PY
```

## 9. Crear y aplicar una segunda adopción definitiva

Creá un paquete nuevo desde la copia origen:

```bash
FINAL_PACKAGE="$PWD/$SOURCE_ROOT/exchange/state_adoption/ex01d_final_state.zip"

archive-workbench exchange-state-package-create \
  "$SOURCE_ROOT" \
  --target-workspace-id "$TARGET_ID" \
  --target-workspace-name "$TARGET_NAME" \
  --created-by alex \
  --reason "Validación EX-01D paquete definitivo." \
  --confirm-package \
  --destination "$FINAL_PACKAGE"
```

Previsualizalo:

```bash
archive-workbench exchange-state-adoption-preview \
  "$TARGET_ROOT" \
  "$FINAL_PACKAGE"
```

Debe volver a mostrar estados distintos y al menos un cambio en `objects`.

Aplicalo desde terminal:

```bash
archive-workbench exchange-state-adopt \
  "$TARGET_ROOT" \
  "$FINAL_PACKAGE" \
  --applied-by alex \
  --reason "Validación EX-01D adopción definitiva." \
  --confirm-adoption
```

Debe mostrar:

```text
OK: estado divergente adoptado
La aplicación fue transaccional. La base común todavía debe registrarse bilateralmente después de comprobar hashes idénticos.
```

Listá las adopciones:

```bash
archive-workbench exchange-state-adoptions "$TARGET_ROOT"
```

Debe haber dos registros:

- la adopción inicial, `revertida`;
- la adopción definitiva, `activa`.

## 10. Registrar la base común después de la adopción

Primero comprobá nuevamente que los hashes editables coinciden:

```bash
python - <<'PY'
from pathlib import Path
from sqlalchemy import select

from archive_workbench.db import create_sqlite_engine, database_path, session_scope
from archive_workbench.db.models import Project
from archive_workbench.exchange import current_editable_state_sha256

roots = [
    Path("project_data_state_adoption_source_validation"),
    Path("project_data_state_adoption_target_validation"),
]
states = []
for root in roots:
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            project_id = session.scalar(select(Project.id))
            assert project_id
            states.append(current_editable_state_sha256(session, project_id))
    finally:
        engine.dispose()

assert len(set(states)) == 1
print("estado común:", states[0])
PY
```

Creá la propuesta:

```bash
COMMON_PROPOSAL="$PWD/$SOURCE_ROOT/exchange/common_base/ex01d_common_base_proposal.zip"
COMMON_AGREEMENT="$PWD/$TARGET_ROOT/exchange/common_base/ex01d_common_base_agreement.zip"

archive-workbench exchange-common-base-propose \
  "$SOURCE_ROOT" \
  --counterpart-workspace-id "$TARGET_ID" \
  --counterpart-workspace-name "$TARGET_NAME" \
  --proposed-by alex \
  --reason "Validación EX-01D propuesta posterior a adopción." \
  --confirm-proposal \
  --destination "$COMMON_PROPOSAL"
```

Aceptala en la copia destinataria:

```bash
archive-workbench exchange-common-base-accept \
  "$TARGET_ROOT" \
  "$COMMON_PROPOSAL" \
  --accepted-by alex \
  --reason "Validación EX-01D contraparte posterior a adopción." \
  --confirm-agreement \
  --destination "$COMMON_AGREEMENT"
```

Finalizala en la copia origen:

```bash
archive-workbench exchange-common-base-finalize \
  "$SOURCE_ROOT" \
  "$COMMON_AGREEMENT" \
  --proposal "$COMMON_PROPOSAL" \
  --finalized-by alex \
  --reason "Validación EX-01D iniciadora posterior a adopción." \
  --confirm-agreement
```

Listá ambos registros:

```bash
archive-workbench exchange-common-base-agreements "$SOURCE_ROOT"
archive-workbench exchange-common-base-agreements "$TARGET_ROOT"
```

Deben mostrar el mismo identificador, manifiesto, estado y punto `common_base_…`, con roles opuestos.

## 11. Verificar un paquete posterior

Extraé el identificador del acuerdo y prepará el paquete:

```bash
AGREEMENT_ID="$(python -c '
import json, sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as archive:
    print(json.loads(archive.read("agreement.json"))["agreement_id"])
' "$COMMON_AGREEMENT")"

CHECKPOINT_LABEL="common_base_${AGREEMENT_ID:0:8}"
POST_BUNDLE="$PWD/$SOURCE_ROOT/exchange/state_adoption/post_ex01d_validation.zip"
```

Exportá desde la copia origen:

```bash
archive-workbench exchange-export-bundle \
  "$SOURCE_ROOT" \
  --since "$CHECKPOINT_LABEL" \
  --created-by alex \
  --destination "$POST_BUNDLE"
```

Debe indicar `eventos 0` y `sin eventos nuevos`.

Simulalo en la copia destinataria:

```bash
archive-workbench exchange-dry-run \
  "$TARGET_ROOT" \
  "$POST_BUNDLE" \
  --assessed-by alex
```

Esperado:

```text
Base común: common_base_… | matched | método common_base_agreement | estado empty
Eventos: aplicables 0 | duplicados 0 | revisables 0 | conflictos 0
No se aplicó ningún cambio al estado editable.
```

No apliques el paquete.

## 12. Verificación final de `EX-01D`

Ejecutá exactamente:

```bash
python - <<'PY'
from pathlib import Path

from sqlalchemy import func, select, text

from archive_workbench.common_base import common_base_agreement_rows
from archive_workbench.db import (
    create_sqlite_engine,
    current_revision,
    database_path,
    session_scope,
)
from archive_workbench.db.models import (
    ExchangeStateAdoption,
    ExchangeStateAdoptionRollback,
    Project,
)
from archive_workbench.exchange import current_editable_state_sha256
from archive_workbench.state_adoption import state_adoption_rows

roots = {
    "origen": Path("project_data_state_adoption_source_validation"),
    "destino": Path("project_data_state_adoption_target_validation"),
}

states = {}
agreements = {}
adoptions = []
rollback_count = 0

for label, root in roots.items():
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            project_id = session.scalar(select(Project.id))
            assert project_id
            states[label] = current_editable_state_sha256(session, project_id)
            agreements[label] = common_base_agreement_rows(session)
            if label == "destino":
                adoptions = state_adoption_rows(session)
                rollback_count = session.scalar(
                    select(func.count()).select_from(
                        ExchangeStateAdoptionRollback
                    )
                )
                adoption_count = session.scalar(
                    select(func.count()).select_from(
                        ExchangeStateAdoption
                    )
                )
            integrity = session.execute(
                text("PRAGMA integrity_check")
            ).scalar_one()
            foreign_keys = session.execute(
                text("PRAGMA foreign_key_check")
            ).all()
            assert integrity == "ok"
            assert foreign_keys == []
        assert current_revision(root) == "0037_exchange_state_adoptions"
    finally:
        engine.dispose()

assert states["origen"] == states["destino"]
assert adoption_count == 2
assert rollback_count == 1
assert len(adoptions) == 2
assert sum(row.rolled_back for row in adoptions) == 1
assert sum(not row.rolled_back for row in adoptions) == 1
assert len(agreements["origen"]) == 1
assert len(agreements["destino"]) == 1
assert agreements["origen"][0].agreement_id == agreements["destino"][0].agreement_id
assert agreements["origen"][0].manifest_sha256 == agreements["destino"][0].manifest_sha256
assert agreements["origen"][0].state_sha256 == states["origen"]
assert agreements["destino"][0].state_sha256 == states["destino"]

print("estado común:", states["origen"])
print("adopciones:", adoption_count)
print("adopciones revertidas:", sum(row.rolled_back for row in adoptions))
print("rollbacks:", rollback_count)
print("acuerdo común:", agreements["origen"][0].agreement_id)
print("revisión:", "0037_exchange_state_adoptions")
print("integridad:", "ok")
print("claves foráneas:", [])
PY
```

Debe mostrar:

```text
adopciones: 2
adopciones revertidas: 1
rollbacks: 1
revisión: 0037_exchange_state_adoptions
integridad: ok
claves foráneas: []
```

`EX-01D` queda pendiente únicamente de esta validación manual. Cuando se confirme, `EX-01` podrá cerrarse documentalmente sin repetir ninguna fase anterior.
