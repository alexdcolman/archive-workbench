# Archive Workbench 0.58.0 — reparación auditable de menciones sin entidad

Esta versión continúa `DATA-01`. Las menciones históricas con estado aceptado o modificado que quedaron sin entidad vinculada pueden resolverse de dos maneras explícitas: vincularlas a una entidad activa existente o devolverlas a estado pendiente. Ambas decisiones agregan una revisión nueva y conservan intacto el historial anterior.

También se corrigió el generador de la validación anterior: los fragmentos descartables ahora terminan en límites de palabra y ya no pueden mostrar una palabra cortada por una longitud fija.

## Actualizar desde 0.57.0

Detené Streamlit y ejecutá:

```bash
cd ~/projects/archive_app
source .venv/bin/activate

rm -rf /tmp/archive_workbench_v0.58.0
mkdir -p /tmp/archive_workbench_v0.58.0

unzip -q \
  ~/Downloads/archive_workbench_v0.58.0.zip \
  -d /tmp/archive_workbench_v0.58.0

cp -a /tmp/archive_workbench_v0.58.0/. .

pip install -e ".[dev,extraction,streamlit,semantic,tiff]"
```

Comprobá:

```bash
python -c "import archive_workbench; print(archive_workbench.__version__)"
```

Debe devolver `0.58.0`.

**No ejecutes `db-upgrade`.** La revisión continúa en `0033_export_exchange_lifecycle`.

## Pruebas automatizadas

Ejecutá primero las pruebas funcionales y de intercambio:

```bash
pytest -q \
  tests/test_mention_repairs.py \
  tests/test_relations.py \
  tests/test_graph.py \
  tests/test_exchange.py::test_missing_authority_repair_travels_as_a_mention_update
```

Deben terminar con `29 passed`.

Después ejecutá las pruebas de interfaz:

```bash
pytest -q tests/test_ui_navigation.py
```

Deben terminar con `41 passed`.

Luego ejecutá documentación y empaquetado:

```bash
pytest -q \
  tests/test_documentation.py \
  tests/test_packaging.py
```

Deben terminar con `26 passed`. En total son `96` pruebas afectadas.

Finalmente ejecutá:

```bash
pytest --collect-only -q
```

La recopilación completa debe informar `315 tests collected`.

## Crear el proyecto descartable de validación

Cerrá Streamlit antes de continuar. Ejecutá:

```bash
cd ~/projects/archive_app
source .venv/bin/activate

rm -rf project_data_missing_authority_validation

python scripts/create_missing_authority_validation_project.py \
  --source project_data_rebase_validation \
  --destination project_data_missing_authority_validation
```

El resultado debe incluir:

```text
Proyecto descartable creado:
Mención para vincular:
Mención para devolver a pendiente:
Entidad de destino:
Alertas esperadas: 2 × missing_authority
```

**No modifiques el proyecto de origen** `project_data_rebase_validation`. El script trabaja únicamente sobre la copia descartable.

## Validación manual

1. Abrí la copia:

```bash
archive-workbench review-app project_data_missing_authority_validation
```

2. Entrá en `Explorar relaciones` y luego en `Revisar alertas`.

3. En `Menciones que requieren revisión` deben aparecer dos tarjetas con el título `Mención aceptada sin entidad` y estos fragmentos completos:

```text
Mencion descartable alfa para vincular
Mencion descartable beta para devolver a pendiente
```

Ninguna palabra debe aparecer cortada.

4. En la tarjeta `Mencion descartable alfa para vincular`, comprobá que aparezca `Resolver entidad faltante`.

5. Conservá la opción `Vincular a una entidad existente`.

6. En `Entidad que corresponde a la mención`, seleccioná:

```text
Entidad de destino para reparación
```

7. Conservá la nota predeterminada, marcá:

```text
Confirmo que deseo vincular esta mención y registrar una nueva revisión
```

8. Pulsá `Vincular mención` una sola vez.

9. Debe aparecer una confirmación persistente y la tarjeta alfa debe desaparecer. La tarjeta beta debe seguir visible.

10. En la tarjeta `Mencion descartable beta para devolver a pendiente`, elegí:

```text
Devolver la mención a pendiente
```

11. Conservá la nota predeterminada, marcá:

```text
Confirmo que deseo devolver esta mención a pendiente y registrar una nueva revisión
```

12. Pulsá `Devolver a pendiente` una sola vez.

13. Debe aparecer una confirmación persistente y la tarjeta beta debe desaparecer. No deben quedar alertas activas de entidad faltante para esos dos casos.

14. Detené Streamlit con `Ctrl+C`.

## Verificación final de base e historial

Ejecutá exactamente:

```bash
python - <<'PY'
from pathlib import Path

from sqlalchemy import select, text

from archive_workbench.authorities import mention_repair_cases
from archive_workbench.db import create_sqlite_engine, database_path, session_scope
from archive_workbench.db.models import (
    AuthorityRecord,
    EntityMention,
    EntityMentionRevision,
)

root = Path("project_data_missing_authority_validation")
engine = create_sqlite_engine(database_path(root))
try:
    with session_scope(engine) as session:
        target = session.scalar(
            select(AuthorityRecord).where(
                AuthorityRecord.preferred_name
                == "Entidad de destino para reparación"
            )
        )
        assert target is not None

        alpha = session.scalar(
            select(EntityMention).where(
                EntityMention.mention_text
                == "Mencion descartable alfa para vincular"
            )
        )
        beta = session.scalar(
            select(EntityMention).where(
                EntityMention.mention_text
                == "Mencion descartable beta para devolver a pendiente"
            )
        )
        assert alpha is not None and beta is not None

        alpha_ops = list(
            session.scalars(
                select(EntityMentionRevision.operation)
                .where(EntityMentionRevision.mention_id == alpha.id)
                .order_by(EntityMentionRevision.revision_number)
            )
        )
        beta_ops = list(
            session.scalars(
                select(EntityMentionRevision.operation)
                .where(EntityMentionRevision.mention_id == beta.id)
                .order_by(EntityMentionRevision.revision_number)
            )
        )

        remaining = {
            case.mention_id
            for case in mention_repair_cases(
                session,
                project_id=target.project_id,
            )
            if case.code == "missing_authority"
        }

        integrity = session.execute(text("PRAGMA integrity_check")).scalar_one()
        foreign_keys = session.execute(text("PRAGMA foreign_key_check")).all()

        assert alpha.authority_id == target.id
        assert alpha.status == "accepted"
        assert alpha_ops == ["create", "repair_link_authority"]
        assert beta.authority_id is None
        assert beta.status == "pending"
        assert beta_ops == ["create", "repair_return_pending"]
        assert alpha.id not in remaining
        assert beta.id not in remaining
        assert integrity == "ok"
        assert foreign_keys == []

        print("alfa estado:", alpha.status)
        print("alfa operaciones:", alpha_ops)
        print("beta estado:", beta.status)
        print("beta operaciones:", beta_ops)
        print("alertas faltantes restantes:", len(remaining))
        print("integridad:", integrity)
        print("claves foráneas:", foreign_keys)
finally:
    engine.dispose()
PY
```

Debe finalizar sin errores y mostrar:

```text
alfa operaciones: ['create', 'repair_link_authority']
beta operaciones: ['create', 'repair_return_pending']
alertas faltantes restantes: 0
integridad: ok
claves foráneas: []
```

La copia `project_data_missing_authority_validation` puede eliminarse después de esta comprobación.

Relación con “Pendientes y mejoras”: `DATA-01` completa la reparación de vínculos faltantes, pero continúa abierto para duplicados, ubicaciones ambiguas, divergencias de snapshots y operaciones agrupadas verificables. No se reabre la reubicación segura ya validada en 0.57.0.
