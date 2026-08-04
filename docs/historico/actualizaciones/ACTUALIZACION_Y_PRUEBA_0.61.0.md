# Archive Workbench 0.61.0 — reconciliación de divergencias entre fila e historial

Esta versión continúa `DATA-01`. Cuando una fila vigente de mención no coincide con su último snapshot, la aplicación muestra las diferencias campo por campo y exige elegir explícitamente qué estado conservar.

Conservar la fila vigente agrega `repair_adopt_current_row`. Restaurar el historial conserva primero la fila divergente mediante `repair_capture_divergent_row` y agrega después `repair_restore_snapshot`; ningún valor observado ni snapshot anterior se pierde.

## Actualizar desde 0.60.0

Detené Streamlit y ejecutá:

```bash
cd ~/projects/archive_app
source .venv/bin/activate

rm -rf /tmp/archive_workbench_v0.61.0
mkdir -p /tmp/archive_workbench_v0.61.0

unzip -q \
  ~/Downloads/archive_workbench_v0.61.0.zip \
  -d /tmp/archive_workbench_v0.61.0

cp -a /tmp/archive_workbench_v0.61.0/. .

pip install -e ".[dev,extraction,streamlit,semantic,tiff]"
```

Comprobá:

```bash
python -c "import archive_workbench; print(archive_workbench.__version__)"
```

Debe devolver `0.61.0`.

**No ejecutes `db-upgrade`.** La revisión continúa en `0033_export_exchange_lifecycle`.

## Pruebas automatizadas

Ejecutá primero las pruebas específicas de reparación:

```bash
pytest -q tests/test_mention_repairs.py
```

Deben terminar con `24 passed`.

Después ejecutá las pruebas transversales de grafo y relaciones:

```bash
pytest -q \
  tests/test_graph.py \
  tests/test_relations.py
```

Deben terminar con `17 passed`.

Luego ejecutá las pruebas de interfaz:

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

Deben terminar con `32 passed`. Son `114` pruebas afectadas en total.

Finalmente ejecutá:

```bash
pytest --collect-only -q
```

La recopilación completa debe informar `334 tests collected`.

Las advertencias deprecadas del adaptador de fechas de SQLite en Python 3.12 no representan fallos.

## Crear el proyecto descartable de validación

Cerrá Streamlit antes de continuar. Ejecutá:

```bash
cd ~/projects/archive_app
source .venv/bin/activate

rm -rf project_data_snapshot_divergence_validation

python scripts/create_snapshot_divergence_validation_project.py \
  --source project_data_rebase_validation \
  --destination project_data_snapshot_divergence_validation
```

El resultado debe incluir:

```text
Proyecto descartable creado:
Mención para conservar fila vigente:
Mención para restaurar historial:
Alertas esperadas: 2 × snapshot_divergence
En alfa, conservá la fila vigente. En beta, restaurá el último estado registrado.
```

**No modifiques el proyecto de origen** `project_data_rebase_validation`. El script trabaja únicamente sobre la copia descartable.

## Validación manual

1. Abrí la copia:

```bash
archive-workbench review-app project_data_snapshot_divergence_validation
```

2. Entrá en `Explorar relaciones` y luego en `Revisar alertas`.

3. En `Menciones que requieren revisión` deben aparecer dos tarjetas tituladas `Divergencia entre fila e historial`:

```text
Mencion divergente alfa para conservar fila vigente
Mencion divergente beta para restaurar historial
```

### Caso alfa: conservar la fila vigente

4. En la tarjeta alfa, comprobá que aparezca `Comparar la fila vigente con el último estado registrado`.

5. La diferencia visible debe corresponder a `Nota`:

```text
Fila vigente: Nota vigente verificada para conservar.
Último estado registrado: Nota registrada antes de la divergencia alfa.
```

6. En `Qué estado querés conservar`, dejá seleccionada:

```text
Conservar la fila vigente y registrarla en el historial
```

7. Conservá el fundamento predeterminado y marcá:

```text
Confirmo que revisé las diferencias y deseo conservar la fila vigente como una nueva revisión
```

8. Pulsá una sola vez:

```text
Conservar fila vigente
```

9. Debe aparecer una confirmación persistente. La tarjeta alfa debe desaparecer y la tarjeta beta debe continuar visible.

### Caso beta: restaurar el último estado registrado

10. En la tarjeta beta, comprobá las diferencias visibles de `Entidad vinculada`, `Estado` y `Nota`.

La fila vigente debe mostrar:

```text
Sin entidad vinculada
Pendiente
Estado accidental sin respaldo histórico.
```

El último estado registrado debe mostrar:

```text
Entidad divergente beta
Aceptada
Nota registrada antes de la divergencia beta.
```

11. En `Qué estado querés conservar`, seleccioná:

```text
Restaurar el último estado registrado
```

12. Conservá el fundamento predeterminado y marcá:

```text
Confirmo que revisé las diferencias y deseo restaurar el último estado registrado como una nueva revisión
```

13. Pulsá una sola vez:

```text
Restaurar estado registrado
```

14. Debe aparecer una confirmación persistente y la tarjeta beta debe desaparecer.

15. Detené Streamlit con `Ctrl+C`.

## Verificación final de la base y el historial

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

root = Path("project_data_snapshot_divergence_validation")
engine = create_sqlite_engine(database_path(root))

try:
    with session_scope(engine) as session:
        alpha_authority = session.scalar(
            select(AuthorityRecord).where(
                AuthorityRecord.preferred_name == "Entidad divergente alfa"
            )
        )
        beta_authority = session.scalar(
            select(AuthorityRecord).where(
                AuthorityRecord.preferred_name == "Entidad divergente beta"
            )
        )
        assert alpha_authority is not None and beta_authority is not None

        alpha = session.scalar(
            select(EntityMention).where(
                EntityMention.authority_id == alpha_authority.id
            )
        )
        beta = session.scalar(
            select(EntityMention).where(
                EntityMention.authority_id == beta_authority.id
            )
        )
        assert alpha is not None and beta is not None

        def revisions(mention_id: str):
            return list(
                session.scalars(
                    select(EntityMentionRevision)
                    .where(EntityMentionRevision.mention_id == mention_id)
                    .order_by(EntityMentionRevision.revision_number)
                )
            )

        alpha_revisions = revisions(alpha.id)
        beta_revisions = revisions(beta.id)
        alpha_ops = [row.operation for row in alpha_revisions]
        beta_ops = [row.operation for row in beta_revisions]

        affected_ids = {alpha.id, beta.id}
        remaining = [
            case
            for case in mention_repair_cases(
                session,
                project_id=alpha_authority.project_id,
            )
            if case.mention_id in affected_ids
        ]

        integrity = session.execute(text("PRAGMA integrity_check")).scalar_one()
        foreign_keys = session.execute(text("PRAGMA foreign_key_check")).all()

        assert alpha.note == "Nota vigente verificada para conservar."
        assert alpha_ops == ["create", "repair_adopt_current_row"]

        assert beta.status == "accepted"
        assert beta.note == "Nota registrada antes de la divergencia beta."
        assert beta_ops == [
            "create",
            "repair_capture_divergent_row",
            "repair_restore_snapshot",
        ]
        assert beta_revisions[1].snapshot_json["authority_id"] is None
        assert beta_revisions[1].snapshot_json["status"] == "pending"
        assert beta_revisions[1].snapshot_json["note"] == (
            "Estado accidental sin respaldo histórico."
        )
        assert beta_revisions[-1].snapshot_json == beta_revisions[0].snapshot_json

        assert remaining == []
        assert integrity == "ok"
        assert foreign_keys == []

        print("alfa operaciones:", alpha_ops)
        print("beta operaciones:", beta_ops)
        print("beta divergencia conservada:", beta_revisions[1].snapshot_json["note"])
        print("alertas restantes:", len(remaining))
        print("integridad:", integrity)
        print("claves foráneas:", foreign_keys)
finally:
    engine.dispose()
PY
```

Debe mostrar:

```text
alfa operaciones: ['create', 'repair_adopt_current_row']
beta operaciones: ['create', 'repair_capture_divergent_row', 'repair_restore_snapshot']
beta divergencia conservada: Estado accidental sin respaldo histórico.
alertas restantes: 0
integridad: ok
claves foráneas: []
```

No repitas las validaciones de reubicación segura, entidad faltante, duplicados ni ubicaciones manuales.
