# Archive Workbench 0.62.0 — conjuntos coincidentes y reparaciones agrupadas

Esta versión completa la implementación funcional prevista de `DATA-01`. Los conjuntos de tres o más menciones coincidentes se revisan como una sola unidad y las reubicaciones seguras del mismo objeto pueden aplicarse juntas cuando todas conservan una decisión verificable.

Las operaciones siguen siendo append-only: cada mención recibe su propia revisión y cualquier cambio posterior a la evaluación cancela la transacción completa.

## Actualizar desde 0.61.0

Detené Streamlit y ejecutá:

```bash
cd ~/projects/archive_app
source .venv/bin/activate

rm -rf /tmp/archive_workbench_v0.62.0
mkdir -p /tmp/archive_workbench_v0.62.0

unzip -q \
  ~/Downloads/archive_workbench_v0.62.0.zip \
  -d /tmp/archive_workbench_v0.62.0

cp -a /tmp/archive_workbench_v0.62.0/. .

pip install -e ".[dev,extraction,streamlit,semantic,tiff]"
```

Comprobá:

```bash
python -c "import archive_workbench; print(archive_workbench.__version__)"
```

Debe devolver `0.62.0`.

**No ejecutes `db-upgrade`.** La revisión continúa en `0033_export_exchange_lifecycle`.

## Pruebas automatizadas

Ejecutá primero dominio, grafo y relaciones:

```bash
pytest -q \
  tests/test_mention_repairs.py \
  tests/test_graph.py \
  tests/test_relations.py
```

Deben terminar con `45 passed`.

Después ejecutá interfaz:

```bash
pytest -q tests/test_ui_navigation.py
```

Debe terminar con `41 passed`.

Luego ejecutá documentación y empaquetado:

```bash
pytest -q \
  tests/test_documentation.py \
  tests/test_packaging.py
```

Deben terminar con `34 passed`. Son `120` pruebas afectadas en total.

Finalmente ejecutá:

```bash
pytest --collect-only -q
```

La recopilación completa debe informar `340 tests collected`.

Las advertencias deprecadas del adaptador de fechas de SQLite en Python 3.12 no representan fallos.

## Crear el proyecto descartable

Confirmá que Streamlit esté cerrado y ejecutá:

```bash
cd ~/projects/archive_app
source .venv/bin/activate

rm -rf project_data_grouped_mention_validation

python scripts/create_grouped_mention_validation_project.py \
  --source project_data_rebase_validation \
  --destination project_data_grouped_mention_validation
```

El resultado debe incluir:

```text
Proyecto descartable creado:
Conjunto coincidente: 3 menciones
Entidad elegida: Entidad conjunta histórica beta
Reubicaciones seguras agrupables: 3
Alertas esperadas: 1 × duplicate_group + 3 × safe_relocation
```

**No modifiques el proyecto de origen** `project_data_rebase_validation`. El script trabaja únicamente sobre la copia descartable.

## Validación manual

1. Abrí la copia:

```bash
archive-workbench review-app project_data_grouped_mention_validation
```

2. Entrá en `Explorar relaciones`, después en `Revisar alertas` y ubicá el bloque `Menciones que requieren revisión`.

3. Arriba de las tarjetas debe aparecer `Acciones agrupadas verificables` y un bloque titulado:

```text
Reubicar 3 menciones seguras de una vez
```

Debe listar:

```text
Entidad segura agrupada 1
Entidad segura agrupada 2
Entidad segura agrupada 3
```

4. Conservá el fundamento predeterminado y marcá:

```text
Confirmo que deseo reubicar todas estas menciones seguras en una sola operación registrada
```

5. Pulsá una sola vez:

```text
Reubicar menciones seguras
```

6. Debe aparecer una confirmación persistente indicando que se reubicaron tres menciones. El bloque agrupado y las tres alertas seguras deben desaparecer.

7. Debe continuar visible una tarjeta titulada:

```text
Conjunto de menciones coincidentes · “Mencion conjunta para elegir una entre tres”
```

8. En `Revisar el conjunto completo` deben aparecer exactamente:

```text
Entidad conjunta histórica alfa · Histórica
Entidad conjunta histórica beta · Histórica
Entidad conjunta vigente gamma · Vigente
```

9. En `Resolver el conjunto completo`, abrí `Mención que se conservará` y elegí:

```text
Entidad conjunta histórica beta · histórica · Aceptada
```

10. Conservá el fundamento predeterminado y marcá:

```text
Confirmo que revisé el conjunto completo, que deseo conservar una sola mención y retirar las demás
```

11. Pulsá una sola vez:

```text
Registrar decisión conjunta
```

12. Debe aparecer una confirmación persistente. La tarjeta del conjunto debe desaparecer y no debe quedar ninguna alerta activa para esas seis menciones.

13. Detené Streamlit con `Ctrl+C`.

## Verificación final

Ejecutá exactamente:

```bash
python - <<'PY'
from pathlib import Path

from sqlalchemy import select, text

from archive_workbench.authorities import mention_repair_cases
from archive_workbench.db import create_sqlite_engine, database_path, session_scope
from archive_workbench.db.models import (
    AuthorityRecord,
    EditableObject,
    EntityMention,
    EntityMentionRevision,
)

root = Path("project_data_grouped_mention_validation")
engine = create_sqlite_engine(database_path(root))

try:
    with session_scope(engine) as session:
        names = (
            "Entidad conjunta histórica alfa",
            "Entidad conjunta histórica beta",
            "Entidad conjunta vigente gamma",
            "Entidad segura agrupada 1",
            "Entidad segura agrupada 2",
            "Entidad segura agrupada 3",
        )
        mentions = {}
        project_id = None
        for name in names:
            authority = session.scalar(
                select(AuthorityRecord).where(
                    AuthorityRecord.preferred_name == name
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
            mentions[name] = mention

        def operations(mention_id: str) -> list[str]:
            return list(
                session.scalars(
                    select(EntityMentionRevision.operation)
                    .where(EntityMentionRevision.mention_id == mention_id)
                    .order_by(EntityMentionRevision.revision_number)
                )
            )

        alpha = mentions["Entidad conjunta histórica alfa"]
        beta = mentions["Entidad conjunta histórica beta"]
        gamma = mentions["Entidad conjunta vigente gamma"]
        editable = session.get(EditableObject, beta.editable_object_id)
        assert editable is not None

        alpha_ops = operations(alpha.id)
        beta_ops = operations(beta.id)
        gamma_ops = operations(gamma.id)
        safe_ops = {
            name: operations(mentions[name].id)
            for name in names[3:]
        }

        affected_ids = {mention.id for mention in mentions.values()}
        assert project_id is not None
        remaining = [
            case
            for case in mention_repair_cases(session, project_id=project_id)
            if case.mention_id in affected_ids
            or affected_ids.intersection(case.duplicate_mention_ids)
        ]

        integrity = session.execute(
            text("PRAGMA integrity_check")
        ).scalar_one()
        foreign_keys = session.execute(
            text("PRAGMA foreign_key_check")
        ).all()

        assert alpha.status == "rejected"
        assert alpha_ops == ["create", "repair_group_duplicate_rejected"]

        assert beta.status == "accepted"
        assert beta.object_revision_number == editable.revision_number
        assert beta_ops == ["create", "repair_group_duplicate_relocated"]

        assert gamma.status == "rejected"
        assert gamma_ops == ["create", "repair_group_duplicate_rejected"]

        for name in names[3:]:
            mention = mentions[name]
            assert mention.status == "accepted"
            assert mention.object_revision_number == editable.revision_number
            assert safe_ops[name] == ["create", "repair_group_relocation"]

        assert remaining == []
        assert integrity == "ok"
        assert foreign_keys == []

        print("alfa:", alpha.status, alpha_ops)
        print("beta:", beta.status, beta_ops)
        print("gamma:", gamma.status, gamma_ops)
        print("operaciones seguras:", safe_ops)
        print("alertas restantes:", len(remaining))
        print("integridad:", integrity)
        print("claves foráneas:", foreign_keys)
finally:
    engine.dispose()
PY
```

Debe finalizar sin errores y mostrar:

```text
alfa: rejected ['create', 'repair_group_duplicate_rejected']
beta: accepted ['create', 'repair_group_duplicate_relocated']
gamma: rejected ['create', 'repair_group_duplicate_rejected']
alertas restantes: 0
integridad: ok
claves foráneas: []
```

No repitas las validaciones individuales de las versiones 0.57.0 a 0.61.0.
