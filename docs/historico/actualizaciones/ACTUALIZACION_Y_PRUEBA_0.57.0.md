# Archive Workbench 0.57.0 — reparación auditable de menciones desactualizadas, fase 1

Esta versión inicia `DATA-01`. Agrega un centro de revisión para menciones desactualizadas y permite reubicar únicamente los casos que tienen una sola proyección verificable, sin colisiones ni divergencias de historial. La reparación crea una revisión nueva y conserva intactos todos los snapshots anteriores.

No modifica automáticamente menciones ambiguas, duplicadas, desvinculadas de una autoridad o divergentes respecto de su último snapshot. Esos casos quedan explicados y bloqueados para una decisión humana posterior.

## Actualizar desde 0.56.0

Detené Streamlit y ejecutá:

```bash
cd ~/projects/archive_app
source .venv/bin/activate

rm -rf /tmp/archive_workbench_v0.57.0
mkdir -p /tmp/archive_workbench_v0.57.0

unzip -q \
  ~/Downloads/archive_workbench_v0.57.0.zip \
  -d /tmp/archive_workbench_v0.57.0

cp -a /tmp/archive_workbench_v0.57.0/. .

pip install -e ".[dev,extraction,streamlit,semantic,tiff]"
```

Comprobá:

```bash
python -c "import archive_workbench; print(archive_workbench.__version__)"
```

Debe devolver `0.57.0`.

**No ejecutes `db-upgrade`.** La revisión continúa en `0033_export_exchange_lifecycle`.

## Pruebas automatizadas

Ejecutá primero las pruebas funcionales:

```bash
pytest -q \
  tests/test_mention_repairs.py \
  tests/test_graph.py \
  tests/test_search.py \
  tests/test_relations.py \
  tests/test_operational.py
```

Deben terminar con `43 passed`.

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

Deben terminar con `24 passed`. En total, son `108` pruebas afectadas.

Finalmente ejecutá:

```bash
pytest --collect-only -q
```

La recopilación completa debe informar `306 tests collected`.

## Crear el proyecto descartable de validación

Cerrá Streamlit antes de continuar. Ejecutá:

```bash
cd ~/projects/archive_app
source .venv/bin/activate

rm -rf project_data_mention_repair_validation

python scripts/create_mention_repair_validation_project.py \
  --source project_data_rebase_validation \
  --destination project_data_mention_repair_validation
```

El script debe informar que creó un caso `safe_relocation` y mostrar los offsets almacenados y proyectados. **No modifiques el proyecto de origen** `project_data_rebase_validation`: el script trabaja sobre una copia nueva y descartable.

## Validación manual

1. Abrí la copia descartable:

```bash
archive-workbench review-app project_data_mention_repair_validation
```

2. Entrá en `Explorar relaciones` y luego en `Revisar alertas`.
3. En `Menciones que requieren revisión`, comprobá que los indicadores muestren al menos una `Reubicable con seguridad`.
4. Localizá la tarjeta de `Entidad de validación de reparación`. Debe mostrar `Reubicación segura disponible`, el fragmento proyectado y una explicación de por qué puede repararse.
5. Abrí `Detalles técnicos e historial de la alerta`. Debe aparecer la revisión histórica de creación, junto con los offsets almacenados y los proyectados. No debe haberse reescrito ninguna revisión anterior.
6. Comprobá que la tarjeta ofrezca `Abrir texto`, `Abrir entidad` y el formulario `Reubicar mención`.
7. Conservá la nota predeterminada, marcá la confirmación explícita y pulsá `Reubicar mención` una sola vez.
8. Inmediatamente después debe aparecer un mensaje persistente de reparación correcta. La tarjeta controlada debe desaparecer de las alertas activas y no deben modificarse otros casos.
9. Detené Streamlit con `Ctrl+C`.

## Verificación final de base e historial

Ejecutá exactamente:

```bash
python - <<'PY'
from pathlib import Path

from sqlalchemy import select

from archive_workbench.authorities import mention_repair_cases
from archive_workbench.db import create_sqlite_engine, database_path, session_scope
from archive_workbench.db.models import (
    AuthorityRecord,
    EditableObject,
    EntityMention,
    EntityMentionRevision,
)

project_root = Path("project_data_mention_repair_validation")
engine = create_sqlite_engine(database_path(project_root))
try:
    with session_scope(engine) as session:
        authority = session.scalar(
            select(AuthorityRecord).where(
                AuthorityRecord.preferred_name
                == "Entidad de validación de reparación"
            )
        )
        assert authority is not None

        mention = session.scalar(
            select(EntityMention).where(EntityMention.authority_id == authority.id)
        )
        assert mention is not None

        editable = session.get(EditableObject, mention.editable_object_id)
        assert editable is not None

        revisions = list(
            session.scalars(
                select(EntityMentionRevision)
                .where(EntityMentionRevision.mention_id == mention.id)
                .order_by(EntityMentionRevision.revision_number)
            )
        )
        operations = [row.operation for row in revisions]
        remaining = [
            case
            for case in mention_repair_cases(
                session,
                project_id=authority.project_id,
            )
            if case.mention_id == mention.id
        ]

        assert mention.object_revision_number == editable.revision_number
        assert operations == ["create", "repair_relocation"]
        assert len(revisions) == 2
        assert remaining == []

        print("mención:", mention.id)
        print("revisión de objeto:", mention.object_revision_number)
        print("offsets actuales:", mention.start_offset, mention.end_offset)
        print("operaciones:", operations)
        print("alertas activas para la mención:", len(remaining))
finally:
    engine.dispose()
PY
```

Debe finalizar sin errores y mostrar:

```text
operaciones: ['create', 'repair_relocation']
alertas activas para la mención: 0
```

No hace falta conservar `project_data_mention_repair_validation` después de la prueba.

## Relación con los pendientes

`UX-01` queda cerrado y validado en 0.56.0. `DATA-01` avanza con la reparación segura individual, pero sigue abierto para duplicados, autoridades faltantes, ubicaciones ambiguas, divergencias de snapshots y operaciones agrupadas verificables.
