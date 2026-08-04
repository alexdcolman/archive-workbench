# Actualización y prueba — Archive Workbench 0.67.0

Esta versión implementa `EX-01C`: un acuerdo bilateral, explícito y append-only para establecer una nueva base común cuando dos copias distintas del mismo proyecto ya tienen exactamente el mismo estado editable.

El recorrido tiene tres pasos: la copia iniciadora crea una propuesta verificable, la contraparte confirma el estado idéntico y completa el acuerdo, y la iniciadora finaliza ese mismo manifiesto. La operación no modifica el corpus.

Los mismos pasos están disponibles por terminal mediante `exchange-common-base-propose`, `exchange-common-base-accept`, `exchange-common-base-finalize` y `exchange-common-base-agreements`.

No repitas ninguna prueba de `DATA-01`, `DATA-02`, `EX-01A` o `EX-01B`.

## 1. Actualizar

Detené Streamlit con `Ctrl+C` y ejecutá:

```bash
cd ~/projects/archive_app
source .venv/bin/activate

rm -rf /tmp/archive_workbench_v0.67.0
mkdir -p /tmp/archive_workbench_v0.67.0

unzip -q \
  ~/Downloads/archive_workbench_v0.67.0.zip \
  -d /tmp/archive_workbench_v0.67.0

cp -a /tmp/archive_workbench_v0.67.0/. .

pip install -e ".[dev,extraction,streamlit,semantic,tiff]"
```

Comprobá:

```bash
python -c "import archive_workbench; print(archive_workbench.__version__)"
```

Debe devolver:

```text
0.67.0
```

## 2. Pruebas automatizadas

Ejecutá:

```bash
pytest -q tests/test_exchange.py -k "common_base"
```

Esperado:

```text
4 passed
```

Después:

```bash
pytest -q tests/test_database.py -k "common_base_migration"
```

Esperado:

```text
1 passed
```

Luego:

```bash
pytest -q tests/test_ui_navigation.py
```

Esperado:

```text
44 passed
```

Después:

```bash
pytest -q \
  tests/test_documentation.py \
  tests/test_packaging.py
```

Esperado:

```text
40 passed
```

Finalmente:

```bash
pytest --collect-only -q
```

Debe recopilar:

```text
378 tests
```

En construcción también pasaron las regresiones críticas de diagnóstico, recuperación de linaje, exportación, simulación, aplicación transaccional y rechazo de simulaciones obsoletas. No se ejecutó nuevamente la suite monolítica completa.

## 3. Migración y copias descartables

Esta versión **sí contiene una migración**:

```text
0036_exchange_common_base_agreements
```

No migres ahora `project_data_rebase_validation` ni las copias utilizadas en `EX-01A` y `EX-01B`. El siguiente script copia el proyecto de referencia y ejecuta `archive-workbench db-upgrade` únicamente sobre las dos copias descartables nuevas.

Con Streamlit cerrado, ejecutá:

```bash
rm -rf \
  project_data_common_base_a_validation \
  project_data_common_base_b_validation

python scripts/create_common_base_validation_projects.py \
  --source project_data_rebase_validation \
  --initiator-destination project_data_common_base_a_validation \
  --counterpart-destination project_data_common_base_b_validation
```

Debe informar:

- una copia iniciadora llamada `ex01c-iniciadora`;
- una contraparte llamada `ex01c-contraparte`;
- identidades de copia distintas;
- revisión `0036_exchange_common_base_agreements`;
- el mismo SHA-256 de estado editable para ambas;
- una ruta `validation.json`;
- que el proyecto fuente no fue modificado.

Comprobá las revisiones:

```bash
archive-workbench db-status project_data_common_base_a_validation
archive-workbench db-status project_data_common_base_b_validation
```

Ambas deben indicar:

```text
0036_exchange_common_base_agreements
```

## 4. Preparar variables

Ejecutá:

```bash
VALIDATION_FILE="project_data_common_base_a_validation/exchange/common_base/validation.json"

INITIATOR_ID="$(python -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["initiator_workspace_id"])' \
  "$VALIDATION_FILE")"

COUNTERPART_ID="$(python -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["counterpart_workspace_id"])' \
  "$VALIDATION_FILE")"

COUNTERPART_NAME="$(python -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["counterpart_workspace_name"])' \
  "$VALIDATION_FILE")"

EXPECTED_STATE="$(python -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["state_sha256"])' \
  "$VALIDATION_FILE")"

PROPOSAL_PATH="$PWD/project_data_common_base_a_validation/exchange/common_base/ex01c_validation_proposal.zip"

printf 'INITIATOR_ID=%s\nCOUNTERPART_ID=%s\nCOUNTERPART_NAME=%s\nEXPECTED_STATE=%s\nPROPOSAL_PATH=%s\n' \
  "$INITIATOR_ID" "$COUNTERPART_ID" "$COUNTERPART_NAME" \
  "$EXPECTED_STATE" "$PROPOSAL_PATH"
```

## 5. Crear la propuesta desde la copia iniciadora

Ejecutá:

```bash
archive-workbench exchange-common-base-propose \
  project_data_common_base_a_validation \
  --counterpart-workspace-id "$COUNTERPART_ID" \
  --counterpart-workspace-name "$COUNTERPART_NAME" \
  --proposed-by alex \
  --reason "Validación EX-01C propuesta." \
  --confirm-proposal \
  --destination "$PROPOSAL_PATH"
```

Debe mostrar:

- `OK: propuesta de base común`;
- las identidades iniciadora y contraparte;
- secuencia `0`;
- el mismo valor de `EXPECTED_STATE`;
- SHA-256 del manifiesto y del ZIP;
- `La propuesta no activó ningún acuerdo ni modificó el corpus.`

En este punto todavía no debe existir ningún acuerdo registrado:

```bash
archive-workbench exchange-common-base-agreements \
  project_data_common_base_a_validation
```

Esperado:

```text
Total: 0 acuerdos
```

## 6. Aceptar la propuesta desde la interfaz de la contraparte

Abrí:

```bash
archive-workbench review-app \
  project_data_common_base_b_validation
```

Entrá en:

```text
Intercambiar cambios
→ Establecer una base común entre copias
→ Aceptar propuesta
```

Completá:

```text
Ruta del ZIP de propuesta recibido: el valor completo de PROPOSAL_PATH
Responsable de la aceptación: alex
Fundamento de la aceptación: Validación EX-01C contraparte.
```

Marcá:

```text
Confirmo que esta copia es la contraparte indicada y que su estado editable es idéntico
```

Pulsá **Aceptar y completar acuerdo** una sola vez.

Debe aparecer un mensaje que indique:

- el identificador del acuerdo;
- que quedó registrado en esta copia;
- la ruta del manifiesto completado;
- que la copia iniciadora todavía debe finalizarlo.

En **Acuerdos registrados en esta copia** debe verse un único registro con rol `counterpart` y un punto `common_base_…`.

Detené Streamlit con `Ctrl+C`.

## 7. Localizar y finalizar el acuerdo en la copia iniciadora

Ejecutá:

```bash
AGREEMENT_PATH="$(find \
  project_data_common_base_b_validation/exchange/common_base/outgoing \
  -type f -name '*_agreement.zip' \
  | sort \
  | tail -n 1)"

printf 'AGREEMENT_PATH=%s\n' "$AGREEMENT_PATH"

test -n "$AGREEMENT_PATH"
test -f "$AGREEMENT_PATH"
```

Después:

```bash
archive-workbench exchange-common-base-finalize \
  project_data_common_base_a_validation \
  "$AGREEMENT_PATH" \
  --proposal "$PROPOSAL_PATH" \
  --finalized-by alex \
  --reason "Validación EX-01C iniciadora." \
  --confirm-agreement
```

Debe mostrar:

- `OK: acuerdo finalizado`;
- un punto local `common_base_…`;
- el valor de `EXPECTED_STATE`;
- SHA-256 del manifiesto compartido;
- `La base común ya quedó registrada en esta copia. No se modificó el corpus.`

## 8. Comparar los registros bilaterales

Ejecutá:

```bash
archive-workbench exchange-common-base-agreements \
  project_data_common_base_a_validation

archive-workbench exchange-common-base-agreements \
  project_data_common_base_b_validation
```

Cada salida debe contener exactamente un acuerdo. Deben coincidir:

- el identificador del acuerdo;
- el SHA-256 del estado;
- el SHA-256 del manifiesto;
- la etiqueta `common_base_…`.

Los roles deben ser diferentes:

```text
rol=initiator
rol=counterpart
```

Los fundamentos deben ser respectivamente:

```text
Validación EX-01C iniciadora.
Validación EX-01C contraparte.
```

## 9. Verificar que un paquete posterior reconoce la nueva base

Extraé el identificador y la etiqueta:

```bash
AGREEMENT_ID="$(python -c '
import json, sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as z:
    print(json.loads(z.read("agreement.json"))["agreement_id"])
' "$AGREEMENT_PATH")"

CHECKPOINT_LABEL="common_base_${AGREEMENT_ID:0:8}"
POST_BUNDLE="$PWD/project_data_common_base_a_validation/exchange/common_base/post_common_base_validation.zip"

printf 'AGREEMENT_ID=%s\nCHECKPOINT_LABEL=%s\nPOST_BUNDLE=%s\n' \
  "$AGREEMENT_ID" "$CHECKPOINT_LABEL" "$POST_BUNDLE"
```

Exportá desde la nueva base común:

```bash
archive-workbench exchange-export-bundle \
  project_data_common_base_a_validation \
  --since "$CHECKPOINT_LABEL" \
  --created-by alex \
  --destination "$POST_BUNDLE"
```

Debe indicar `eventos 0` y `sin eventos nuevos`.

Simulalo en la contraparte:

```bash
archive-workbench exchange-dry-run \
  project_data_common_base_b_validation \
  "$POST_BUNDLE" \
  --assessed-by alex
```

Debe mostrar:

```text
Base común: common_base_… | matched | método common_base_agreement
Eventos: aplicables 0 | duplicados 0 | revisables 0 | conflictos 0
No se aplicó ningún cambio al estado editable.
```

No apliques ese paquete.

## 10. Verificar registros, estado e integridad

Ejecutá exactamente:

```bash
python - <<'PY'
import json
from pathlib import Path

from sqlalchemy import select, text

from archive_workbench.common_base import inspect_common_base_agreement
from archive_workbench.db import (
    create_sqlite_engine,
    current_revision,
    database_path,
    session_scope,
)
from archive_workbench.db.models import (
    ExchangeCheckpoint,
    ExchangeCommonBaseAgreement,
)
from archive_workbench.exchange import current_editable_state_sha256

validation = json.loads(
    Path(
        "project_data_common_base_a_validation/exchange/common_base/validation.json"
    ).read_text(encoding="utf-8")
)
expected_state = validation["state_sha256"]

agreement_paths = sorted(
    Path(
        "project_data_common_base_b_validation/exchange/common_base/outgoing"
    ).glob("*_agreement.zip")
)
assert len(agreement_paths) == 1
manifest, _proposal, manifest_sha256, _zip_sha256, _proposal_bytes = (
    inspect_common_base_agreement(agreement_paths[0])
)

roots = {
    "initiator": Path("project_data_common_base_a_validation"),
    "counterpart": Path("project_data_common_base_b_validation"),
}
observed = {}

for expected_role, root in roots.items():
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            rows = list(session.scalars(select(ExchangeCommonBaseAgreement)))
            assert len(rows) == 1
            row = rows[0]
            checkpoint = session.get(ExchangeCheckpoint, row.local_checkpoint_id)

            assert row.local_role == expected_role
            assert row.agreement_id == manifest.agreement_id
            assert row.manifest_sha256 == manifest_sha256
            assert row.state_sha256 == expected_state
            assert row.local_checkpoint_label == manifest.checkpoint_label
            assert checkpoint is not None
            assert checkpoint.label == manifest.checkpoint_label
            assert checkpoint.state_sha256 == expected_state
            assert current_editable_state_sha256(session, row.project_id) == expected_state

            integrity = session.execute(
                text("PRAGMA integrity_check")
            ).scalar_one()
            foreign_keys = session.execute(
                text("PRAGMA foreign_key_check")
            ).all()

            assert current_revision(root) == "0036_exchange_common_base_agreements"
            assert integrity == "ok"
            assert foreign_keys == []

            observed[expected_role] = {
                "agreement_id": row.agreement_id,
                "checkpoint": row.local_checkpoint_label,
                "state": row.state_sha256,
                "manifest": row.manifest_sha256,
                "integrity": integrity,
                "foreign_keys": foreign_keys,
            }
    finally:
        engine.dispose()

assert observed["initiator"]["agreement_id"] == observed["counterpart"]["agreement_id"]
assert observed["initiator"]["checkpoint"] == observed["counterpart"]["checkpoint"]
assert observed["initiator"]["state"] == observed["counterpart"]["state"]
assert observed["initiator"]["manifest"] == observed["counterpart"]["manifest"]

print("acuerdo compartido:", observed["initiator"]["agreement_id"])
print("punto común:", observed["initiator"]["checkpoint"])
print("estado idéntico:", observed["initiator"]["state"])
print("manifiesto idéntico:", observed["initiator"]["manifest"])
print("roles registrados:", sorted(observed))
print("revisión:", "0036_exchange_common_base_agreements")
print("integridad:", [observed[key]["integrity"] for key in sorted(observed)])
print("claves foráneas:", [observed[key]["foreign_keys"] for key in sorted(observed)])
PY
```

Debe mostrar:

```text
acuerdo compartido: <UUID>
punto común: common_base_<8 caracteres>
estado idéntico: <SHA-256>
manifiesto idéntico: <SHA-256>
roles registrados: ['counterpart', 'initiator']
revisión: 0036_exchange_common_base_agreements
integridad: ['ok', 'ok']
claves foráneas: [[], []]
```

`EX-01C` queda pendiente únicamente de esta validación manual. Después corresponde registrar su cierre e implementar `EX-01D`, sin repetir las fases anteriores.
