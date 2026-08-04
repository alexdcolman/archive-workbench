# Archive Workbench 0.59.0 — resolución auditable de menciones duplicadas

Esta versión continúa `DATA-01`. Cuando una mención histórica se proyecta al texto vigente y coincide con exactamente una mención activa ya ubicada allí, la aplicación permite comparar ambas y decidir explícitamente cuál conservar.

La decisión nunca fusiona registros ni elimina historia. La mención descartada pasa a `rejected` mediante una revisión nueva; si se conserva la histórica, también se la reubica sobre el texto actual mediante otra revisión auditable.

## Actualizar desde 0.58.0

Detené Streamlit y ejecutá:

```bash
cd ~/projects/archive_app
source .venv/bin/activate

rm -rf /tmp/archive_workbench_v0.59.0
mkdir -p /tmp/archive_workbench_v0.59.0

unzip -q \
  ~/Downloads/archive_workbench_v0.59.0.zip \
  -d /tmp/archive_workbench_v0.59.0

cp -a /tmp/archive_workbench_v0.59.0/. .

pip install -e ".[dev,extraction,streamlit,semantic,tiff]"
```

Comprobá:

```bash
python -c "import archive_workbench; print(archive_workbench.__version__)"
```

Debe devolver `0.59.0`.

**No ejecutes `db-upgrade`.** La revisión continúa en `0033_export_exchange_lifecycle`.

## Pruebas automatizadas

Ejecutá primero las pruebas funcionales:

```bash
pytest -q \
  tests/test_mention_repairs.py \
  tests/test_relations.py \
  tests/test_graph.py
```

Deben terminar con `32 passed`.

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

Deben terminar con `28 passed`. En total son `101` pruebas afectadas.

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

rm -rf project_data_duplicate_mention_validation

python scripts/create_duplicate_mention_validation_project.py \
  --source project_data_rebase_validation \
  --destination project_data_duplicate_mention_validation
```

El resultado debe incluir:

```text
Proyecto descartable creado:
Alfa histórica:
Alfa vigente:
Beta histórica:
Beta vigente:
Alertas esperadas: 2 × duplicate_relocation
```

**No modifiques el proyecto de origen** `project_data_rebase_validation`. El script trabaja únicamente sobre la copia descartable.

## Validación manual

1. Abrí la copia:

```bash
archive-workbench review-app project_data_duplicate_mention_validation
```

2. Entrá en `Explorar relaciones` y luego en `Revisar alertas`.

3. En `Menciones que requieren revisión` deben aparecer dos tarjetas con el título `Coincidencia con otra mención activa` y estos fragmentos completos:

```text
Mencion duplicada alfa para conservar la vigente
Mencion duplicada beta para conservar la historica
```

4. En la tarjeta alfa, comprobá que la comparación muestre:

```text
Mención histórica: Entidad histórica alfa
Mención ya ubicada en el texto vigente: Entidad vigente alfa
```

5. En `Qué mención querés conservar`, dejá seleccionada:

```text
Conservar la mención ya ubicada en el texto vigente
```

6. Conservá el fundamento predeterminado y marcá:

```text
Confirmo que deseo conservar la mención vigente y retirar la mención histórica duplicada
```

7. Pulsá una sola vez:

```text
Registrar decisión sobre el duplicado
```

8. Debe aparecer una confirmación persistente. La tarjeta alfa debe desaparecer y la beta debe seguir visible.

9. En la tarjeta beta, comprobá que la comparación muestre:

```text
Mención histórica: Entidad histórica beta
Mención ya ubicada en el texto vigente: Entidad vigente beta
```

10. Seleccioná:

```text
Conservar la mención histórica y reubicarla
```

11. Conservá el fundamento predeterminado y marcá:

```text
Confirmo que deseo conservar y reubicar la mención histórica, y retirar la mención vigente duplicada
```

12. Pulsá una sola vez:

```text
Registrar decisión sobre el duplicado
```

13. Debe aparecer una confirmación persistente y la tarjeta beta debe desaparecer.

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

root = Path("project_data_duplicate_mention_validation")
engine = create_sqlite_engine(database_path(root))
try:
    with session_scope(engine) as session:
        mentions = {}
        project_id = None
        for authority_name in (
            "Entidad histórica alfa",
            "Entidad vigente alfa",
            "Entidad histórica beta",
            "Entidad vigente beta",
        ):
            authority = session.scalar(
                select(AuthorityRecord).where(
                    AuthorityRecord.preferred_name == authority_name
                )
            )
            assert authority is not None
            project_id = authority.project_id
            mention = session.scalar(
                select(EntityMention).where(
                    EntityMention.authority_id == authority.id
                )
            )
            assert mention is not None
            mentions[authority_name] = mention

        def operations(mention_id: str) -> list[str]:
            return list(
                session.scalars(
                    select(EntityMentionRevision.operation)
                    .where(EntityMentionRevision.mention_id == mention_id)
                    .order_by(EntityMentionRevision.revision_number)
                )
            )

        alpha_historical = mentions["Entidad histórica alfa"]
        alpha_current = mentions["Entidad vigente alfa"]
        beta_historical = mentions["Entidad histórica beta"]
        beta_current = mentions["Entidad vigente beta"]

        alpha_historical_ops = operations(alpha_historical.id)
        alpha_current_ops = operations(alpha_current.id)
        beta_historical_ops = operations(beta_historical.id)
        beta_current_ops = operations(beta_current.id)

        affected_ids = {
            alpha_historical.id,
            alpha_current.id,
            beta_historical.id,
            beta_current.id,
        }
        remaining = [
            case
            for case in mention_repair_cases(
                session,
                project_id=project_id,
            )
            if case.mention_id in affected_ids
        ]

        integrity = session.execute(text("PRAGMA integrity_check")).scalar_one()
        foreign_keys = session.execute(text("PRAGMA foreign_key_check")).all()

        assert project_id is not None
        assert alpha_historical.status == "rejected"
        assert alpha_historical_ops == ["create", "repair_duplicate_rejected"]
        assert alpha_current.status == "accepted"
        assert alpha_current_ops == ["create"]

        assert beta_historical.status == "accepted"
        assert beta_historical.object_revision_number == beta_current.object_revision_number
        assert beta_historical_ops == ["create", "repair_duplicate_relocated"]
        assert beta_current.status == "rejected"
        assert beta_current_ops == ["create", "repair_duplicate_rejected"]

        assert remaining == []
        assert integrity == "ok"
        assert foreign_keys == []

        print("alfa histórica:", alpha_historical.status, alpha_historical_ops)
        print("alfa vigente:", alpha_current.status, alpha_current_ops)
        print("beta histórica:", beta_historical.status, beta_historical_ops)
        print("beta vigente:", beta_current.status, beta_current_ops)
        print("alertas restantes:", len(remaining))
        print("integridad:", integrity)
        print("claves foráneas:", foreign_keys)
finally:
    engine.dispose()
PY
```

Debe finalizar sin errores y mostrar:

```text
alfa histórica: rejected ['create', 'repair_duplicate_rejected']
alfa vigente: accepted ['create']
beta histórica: accepted ['create', 'repair_duplicate_relocated']
beta vigente: rejected ['create', 'repair_duplicate_rejected']
alertas restantes: 0
integridad: ok
claves foráneas: []
```

La copia `project_data_duplicate_mention_validation` puede eliminarse después de esta comprobación.

Relación con “Pendientes y mejoras”: `DATA-01` completa la decisión binaria sobre un duplicado histórico y una única contraparte vigente. Continúan pendientes los conjuntos múltiples, las ubicaciones ambiguas, las divergencias entre fila y snapshot y las operaciones agrupadas verificables.
