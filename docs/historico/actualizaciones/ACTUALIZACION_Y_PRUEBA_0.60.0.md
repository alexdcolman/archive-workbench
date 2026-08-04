# Archive Workbench 0.60.0 — resolución manual de ubicaciones de menciones

Esta versión continúa `DATA-01`. Las menciones históricas que no pueden proyectarse automáticamente sobre una ubicación única admiten ahora una decisión humana explícita y auditable.

La persona revisora puede elegir un fragmento literal y una aparición concreta del texto vigente, o registrar que el fragmento histórico ya no está presente. Ninguna ruta borra el registro ni modifica revisiones anteriores.

## Actualizar desde 0.59.0

Detené Streamlit y ejecutá:

```bash
cd ~/projects/archive_app
source .venv/bin/activate

rm -rf /tmp/archive_workbench_v0.60.0
mkdir -p /tmp/archive_workbench_v0.60.0

unzip -q \
  ~/Downloads/archive_workbench_v0.60.0.zip \
  -d /tmp/archive_workbench_v0.60.0

cp -a /tmp/archive_workbench_v0.60.0/. .

pip install -e ".[dev,extraction,streamlit,semantic,tiff]"
```

Comprobá:

```bash
python -c "import archive_workbench; print(archive_workbench.__version__)"
```

Debe devolver `0.60.0`.

**No ejecutes `db-upgrade`.** La revisión continúa en `0033_export_exchange_lifecycle`.

## Pruebas automatizadas

Ejecutá primero las pruebas funcionales:

```bash
pytest -q \
  tests/test_mention_repairs.py \
  tests/test_graph.py \
  tests/test_relations.py
```

Deben terminar con `37 passed`.

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

Deben terminar con `30 passed`. Son `108` pruebas afectadas en total.

Finalmente ejecutá:

```bash
pytest --collect-only -q
```

La recopilación completa debe informar `328 tests collected`.

Las advertencias deprecadas del adaptador de fechas de SQLite en Python 3.12 no representan fallos. Una línea `Permission denied` sobre un archivo de pruebas indica que Bash intentó ejecutarlo como programa por faltar una barra invertida en el comando anterior; los comandos de esta guía ya están completos.

## Crear el proyecto descartable de validación

Cerrá Streamlit antes de continuar. Ejecutá:

```bash
cd ~/projects/archive_app
source .venv/bin/activate

rm -rf project_data_unresolved_mention_validation

python scripts/create_unresolved_mention_validation_project.py \
  --source project_data_rebase_validation \
  --destination project_data_unresolved_mention_validation
```

El resultado debe incluir:

```text
Proyecto descartable creado:
Mención ambigua:
Mención ausente:
Alertas esperadas: 2 × unresolved_relocation
Elegí la segunda aparición para la mención ambigua.
```

**No modifiques el proyecto de origen** `project_data_rebase_validation`. El script trabaja únicamente sobre la copia descartable.

## Validación manual

1. Abrí la copia:

```bash
archive-workbench review-app project_data_unresolved_mention_validation
```

2. Entrá en `Explorar relaciones` y luego en `Revisar alertas`.

3. En `Menciones que requieren revisión` deben aparecer dos tarjetas tituladas `Ubicación no resuelta`:

```text
MENCION AMBIGUA REPETIDA
FRAGMENTO RETIRADO DEL TEXTO VIGENTE
```

### Caso ambiguo

4. En la tarjeta `MENCION AMBIGUA REPETIDA`, comprobá que aparezca `Resolver la ubicación manualmente`.

5. Abrí `Ver texto vigente completo`. El texto debe contener dos apariciones de:

```text
Mencion ambigua repetida
```

6. Conservá la decisión:

```text
Reubicar la mención en un fragmento del texto vigente
```

7. Conservá como fragmento exacto:

```text
MENCION AMBIGUA REPETIDA
```

La búsqueda ignora mayúsculas y debe ofrecer dos apariciones.

8. En `Aparición que corresponde a la mención`, elegí:

```text
Aparición 2
```

La vista previa debe incluir `Segunda aparición elegida`.

9. Conservá el fundamento predeterminado y marcá:

```text
Confirmo que revisé el texto vigente y deseo reubicar esta mención en la aparición seleccionada
```

10. Pulsá una sola vez:

```text
Reubicar mención manualmente
```

11. Debe aparecer una confirmación persistente. La tarjeta ambigua debe desaparecer y la tarjeta del fragmento ausente debe continuar visible.

### Fragmento ausente

12. En la tarjeta `FRAGMENTO RETIRADO DEL TEXTO VIGENTE`, abrí `Ver texto vigente completo` y comprobá que ese fragmento no aparezca.

13. En `Qué querés registrar`, seleccioná:

```text
Registrar que el fragmento ya no está presente
```

14. Debe aparecer una explicación que indique que la mención dejará de estar activa, pero conservará el registro y sus revisiones.

15. Conservá el fundamento predeterminado y marcá:

```text
Confirmo que revisé el texto vigente y que el fragmento ya no está presente
```

16. Pulsá una sola vez:

```text
Retirar mención ausente
```

17. Debe aparecer una confirmación persistente y la tarjeta debe desaparecer.

18. Detené Streamlit con `Ctrl+C`.

## Verificación final de la base y el historial

Ejecutá exactamente:

```bash
python - <<'PY'
from pathlib import Path

from sqlalchemy import select, text

from archive_workbench.authorities import (
    exact_mention_occurrences,
    mention_repair_cases,
)
from archive_workbench.db import create_sqlite_engine, database_path, session_scope
from archive_workbench.db.models import (
    AuthorityRecord,
    EditableObject,
    EntityMention,
    EntityMentionRevision,
)

root = Path("project_data_unresolved_mention_validation")
engine = create_sqlite_engine(database_path(root))

try:
    with session_scope(engine) as session:
        ambiguous_authority = session.scalar(
            select(AuthorityRecord).where(
                AuthorityRecord.preferred_name == "Entidad de ubicación ambigua"
            )
        )
        absent_authority = session.scalar(
            select(AuthorityRecord).where(
                AuthorityRecord.preferred_name == "Entidad de fragmento ausente"
            )
        )
        assert ambiguous_authority is not None
        assert absent_authority is not None

        ambiguous = session.scalar(
            select(EntityMention).where(
                EntityMention.authority_id == ambiguous_authority.id
            )
        )
        absent = session.scalar(
            select(EntityMention).where(
                EntityMention.authority_id == absent_authority.id
            )
        )
        assert ambiguous is not None and absent is not None

        editable = session.get(EditableObject, ambiguous.editable_object_id)
        assert editable is not None

        def operations(mention_id: str) -> list[str]:
            return list(
                session.scalars(
                    select(EntityMentionRevision.operation)
                    .where(EntityMentionRevision.mention_id == mention_id)
                    .order_by(EntityMentionRevision.revision_number)
                )
            )

        ambiguous_ops = operations(ambiguous.id)
        absent_ops = operations(absent.id)
        occurrences = exact_mention_occurrences(
            editable.current_text,
            "MENCION AMBIGUA REPETIDA",
        )

        affected_ids = {ambiguous.id, absent.id}
        remaining = [
            case
            for case in mention_repair_cases(
                session,
                project_id=ambiguous_authority.project_id,
            )
            if case.mention_id in affected_ids
        ]

        integrity = session.execute(text("PRAGMA integrity_check")).scalar_one()
        foreign_keys = session.execute(text("PRAGMA foreign_key_check")).all()

        assert len(occurrences) == 2
        assert ambiguous.status == "accepted"
        assert ambiguous.object_revision_number == editable.revision_number
        assert (ambiguous.start_offset, ambiguous.end_offset) == occurrences[1]
        assert ambiguous_ops == ["create", "repair_manual_relocation"]

        assert absent.status == "rejected"
        assert absent_ops == ["create", "repair_mark_absent"]

        assert remaining == []
        assert integrity == "ok"
        assert foreign_keys == []

        print("ambigua estado:", ambiguous.status)
        print("ambigua operaciones:", ambiguous_ops)
        print("ambigua aparición elegida:", occurrences.index((ambiguous.start_offset, ambiguous.end_offset)) + 1)
        print("ausente estado:", absent.status)
        print("ausente operaciones:", absent_ops)
        print("alertas restantes:", len(remaining))
        print("integridad:", integrity)
        print("claves foráneas:", foreign_keys)
finally:
    engine.dispose()
PY
```

Debe finalizar sin errores y mostrar:

```text
ambigua estado: accepted
ambigua operaciones: ['create', 'repair_manual_relocation']
ambigua aparición elegida: 2
ausente estado: rejected
ausente operaciones: ['create', 'repair_mark_absent']
alertas restantes: 0
integridad: ok
claves foráneas: []
```

No repitas las pruebas manuales de reubicación segura, entidad faltante ni duplicados.
