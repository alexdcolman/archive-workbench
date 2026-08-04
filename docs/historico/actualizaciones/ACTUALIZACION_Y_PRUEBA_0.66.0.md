# Actualización y prueba — Archive Workbench 0.66.0

## Objetivo

Esta versión implementa `EX-01B`: recuperación append-only de linaje para un paquete cuya simulación quedó sin base reconocida y cuyo diagnóstico de `EX-01A` demuestra una única cadena concluyente.

La recuperación registra un caso, sus evidencias y una decisión auditable. No modifica el corpus ni aplica eventos recibidos. La simulación anterior queda obsoleta y debe repetirse; la nueva simulación reconoce la base mediante `recovered_lineage`.

## 1. Actualizar el código

Detené Streamlit con `Ctrl+C` y ejecutá:

```bash
cd ~/projects/archive_app
source .venv/bin/activate

rm -rf /tmp/archive_workbench_v0.66.0
mkdir -p /tmp/archive_workbench_v0.66.0

unzip -q \
  ~/Downloads/archive_workbench_v0.66.0.zip \
  -d /tmp/archive_workbench_v0.66.0

cp -a /tmp/archive_workbench_v0.66.0/. .

pip install -e ".[dev,extraction,streamlit,semantic,tiff]"
```

Comprobá:

```bash
python -c "import archive_workbench; print(archive_workbench.__version__)"
```

Debe devolver:

```text
0.66.0
```

No repitas ninguna prueba de `DATA-01`, `DATA-02` o `EX-01A`.

## 2. Pruebas automatizadas

Ejecutá primero las regresiones nuevas de recuperación:

```bash
pytest -q tests/test_exchange.py \
  -k "lineage_recovery or exchange_lineage_recover"
```

Esperado:

```text
3 passed, 64 deselected
```

Después comprobá la migración:

```bash
pytest -q tests/test_database.py \
  -k "lineage_recovery_migration"
```

Esperado:

```text
1 passed, 11 deselected
```

Ejecutá navegación:

```bash
pytest -q tests/test_ui_navigation.py
```

Esperado:

```text
43 passed
```

Después:

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
371 tests
```

En construcción también se ejecutaron regresiones críticas del intercambio previo: inspección y alteración de paquetes, reconocimiento por punto exacto o aplicación anterior, simulación con y sin base, aplicación transaccional, rechazo de simulaciones obsoletas y ciclo de vida de paquetes. No se ejecutó nuevamente la suite monolítica completa.

## 3. Respaldar y migrar la copia descartable

Esta versión **sí contiene una migración**. No migres ahora `project_data_rebase_validation`, la copia fuente descartable ni otros proyectos que no vayas a utilizar.

Respaldá únicamente la copia receptora de `EX-01A`:

```bash
archive-workbench project-backup-create \
  project_data_lineage_receiver_validation \
  --created-by alex \
  --note "Antes de migrar a Archive Workbench 0.66.0"
```

Debe mostrar `OK`, la revisión anterior y un SHA-256.

Migrá:

```bash
archive-workbench db-upgrade \
  project_data_lineage_receiver_validation
```

Debe finalizar con:

```text
Revisión: 0035_exchange_lineage_recovery
```

Comprobá:

```bash
archive-workbench db-status \
  project_data_lineage_receiver_validation
```

Debe indicar la misma revisión.

No recrees las copias descartables. Se reutilizan exactamente las que validaste con `EX-01A`.

## 4. Preparar las variables

Ejecutá:

```bash
VALIDATION_FILE="project_data_lineage_receiver_validation/exchange/lineage_evidence/validation.json"

BUNDLE_ID="$(python -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["target_bundle_id"])' \
  "$VALIDATION_FILE")"

BUNDLE_PATH="$(python -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["target_bundle_path"])' \
  "$VALIDATION_FILE")"

EVIDENCE_BUNDLE="$(python -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["evidence_bundle_path"])' \
  "$VALIDATION_FILE")"

printf 'BUNDLE_ID=%s\nBUNDLE_PATH=%s\nEVIDENCE_BUNDLE=%s\n' \
  "$BUNDLE_ID" "$BUNDLE_PATH" "$EVIDENCE_BUNDLE"
```

## 5. Recuperar el linaje desde la interfaz

Abrí:

```bash
archive-workbench review-app \
  project_data_lineage_receiver_validation
```

Entrá en:

```text
Intercambiar cambios
```

Abrí el paquete que muestra:

```text
Base: Sin base reconocida
```

Dentro de **Diagnosticar evidencia de linaje**, pegá exactamente el valor de `EVIDENCE_BUNDLE` en **Rutas de evidencia adicional** y pulsá:

```text
Ejecutar diagnóstico de solo lectura
```

Debe mostrar:

```text
Resultado: Recuperable
Método: verified_bundle_chain
Punto local: baseline_ex01a
```

Ahora completá el formulario de recuperación:

```text
Responsable: alex
Fundamento: Validación EX-01B recuperación.
```

Marcá la confirmación explícita y pulsá **Recuperar linaje** una sola vez.

Debe informar que:

- el linaje fue recuperado;
- se registraron un caso y una decisión;
- la simulación anterior quedó obsoleta;
- el corpus no fue modificado;
- es obligatorio repetir la simulación.

No resuelvas campos ni apliques el paquete. Detené Streamlit con `Ctrl+C`.

## 6. Revisar la decisión append-only

Ejecutá:

```bash
archive-workbench exchange-lineage-recoveries \
  project_data_lineage_receiver_validation
```

Debe mostrar una sola recuperación con:

```text
verified_bundle_chain
punto=baseline_ex01a
fundamento: Validación EX-01B recuperación.
Total: 1 recuperaciones
```

## 7. Repetir la simulación

Ejecutá:

```bash
archive-workbench exchange-dry-run \
  project_data_lineage_receiver_validation \
  "$BUNDLE_PATH" \
  --assessed-by alex
```

Debe mostrar:

```text
Base común: baseline_ex01a | matched | método recovered_lineage | estado conflicts
Eventos: aplicables 0 | duplicados 0 | revisables 0 | conflictos 1
```

El conflicto es esperado: la recuperación demuestra la ascendencia, pero no incorpora el cambio remoto previo que faltaba. No resuelvas ni apliques el paquete en esta fase.

## 8. Verificar base, auditoría e integridad

Ejecutá exactamente:

```bash
python - <<'PY'
from pathlib import Path

from sqlalchemy import func, select, text

from archive_workbench.db import (
    create_sqlite_engine,
    current_revision,
    database_path,
    session_scope,
)
from archive_workbench.db.models import (
    ExchangeBundleApplication,
    ExchangeChangeEvent,
    ExchangeCheckpoint,
    ExchangeDryRun,
    ExchangeLineageCase,
    ExchangeLineageDecision,
    ExchangeLineageEvidence,
)

root = Path("project_data_lineage_receiver_validation")
validation = __import__("json").loads(
    (root / "exchange/lineage_evidence/validation.json").read_text(
        encoding="utf-8"
    )
)
bundle_id = validation["target_bundle_id"]
engine = create_sqlite_engine(database_path(root))

try:
    with session_scope(engine) as session:
        case = session.scalar(
            select(ExchangeLineageCase).where(
                ExchangeLineageCase.bundle_id == bundle_id
            )
        )
        decision = session.scalar(
            select(ExchangeLineageDecision).where(
                ExchangeLineageDecision.target_bundle_id == bundle_id
            )
        )
        evidence = list(
            session.scalars(
                select(ExchangeLineageEvidence).where(
                    ExchangeLineageEvidence.case_id == case.id
                )
            )
        )
        dry = session.scalar(
            select(ExchangeDryRun).where(
                ExchangeDryRun.bundle_id == bundle_id
            )
        )

        counts = {
            "cases": session.scalar(
                select(func.count(ExchangeLineageCase.id))
            ),
            "evidence": session.scalar(
                select(func.count(ExchangeLineageEvidence.id))
            ),
            "decisions": session.scalar(
                select(func.count(ExchangeLineageDecision.id))
            ),
            "applications": session.scalar(
                select(func.count(ExchangeBundleApplication.id))
            ),
            "checkpoints": session.scalar(
                select(func.count(ExchangeCheckpoint.id))
            ),
            "change_events": session.scalar(
                select(func.count(ExchangeChangeEvent.id))
            ),
        }
        integrity = session.execute(
            text("PRAGMA integrity_check")
        ).scalar_one()
        foreign_keys = session.execute(
            text("PRAGMA foreign_key_check")
        ).all()

        assert case is not None
        assert decision is not None
        assert len(evidence) == 2
        assert counts == {
            "cases": 1,
            "evidence": 2,
            "decisions": 1,
            "applications": 0,
            "checkpoints": 1,
            "change_events": 0,
        }
        assert decision.operation == "recover_lineage"
        assert decision.source == "ui"
        assert decision.recovery_confirmed is True
        assert decision.confirmed_by == "alex"
        assert (
            decision.confirmation_reason
            == "Validación EX-01B recuperación."
        )
        assert decision.recovery_method == "verified_bundle_chain"
        assert decision.local_checkpoint_label == "baseline_ex01a"
        assert decision.evidence_ids_json
        assert len(decision.parameters_sha256) == 64
        assert dry is not None
        assert dry.base_match_status == "matched"
        assert dry.base_match_method == "recovered_lineage"
        assert dry.common_checkpoint_label == "baseline_ex01a"
        assert dry.overall_status == "conflicts"
        assert dry.counts_json == {
            "apply": 0,
            "duplicate": 0,
            "review": 0,
            "conflict": 1,
        }
        assert current_revision(root) == "0035_exchange_lineage_recovery"
        assert integrity == "ok"
        assert foreign_keys == []

        print("registros EX-01B:", {
            "cases": counts["cases"],
            "evidence": counts["evidence"],
            "decisions": counts["decisions"],
        })
        print("contenido aplicado:", {
            "applications": counts["applications"],
            "change_events": counts["change_events"],
        })
        print("método de base:", dry.base_match_method)
        print("estado de simulación:", dry.overall_status)
        print("revisión:", current_revision(root))
        print("integridad:", integrity)
        print("claves foráneas:", foreign_keys)
finally:
    engine.dispose()
PY
```

Debe mostrar:

```text
registros EX-01B: {'cases': 1, 'evidence': 2, 'decisions': 1}
contenido aplicado: {'applications': 0, 'change_events': 0}
método de base: recovered_lineage
estado de simulación: conflicts
revisión: 0035_exchange_lineage_recovery
integridad: ok
claves foráneas: []
```

`EX-01B` queda pendiente únicamente de esta validación manual. Después corresponde registrar su cierre e implementar `EX-01C`, sin repetir `EX-01A`.
