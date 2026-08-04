# Actualización y prueba — Archive Workbench 0.69.1

Esta versión corrige la primera ejecución manual de `DISC-01A`. El descubrimiento abierto consultaba un atributo inexistente de las menciones históricas; ahora usa su campo real `status`, ignora las menciones rechazadas y omite de forma segura las filas sin offsets. El panel queda al final de **Entidades y menciones** y cerrado por defecto.

La corrida que falló con `AttributeError` fue revertida por la transacción. El perfil guardado continúa vigente y no quedó una corrida parcial.

## 1. Actualizar el código

Detené Streamlit con `Ctrl+C` y ejecutá:

```bash
cd ~/projects/archive_app
source .venv/bin/activate

rm -rf /tmp/archive_workbench_v0.69.1
mkdir -p /tmp/archive_workbench_v0.69.1

unzip -q \
  ~/Downloads/archive_workbench_v0.69.1.zip \
  -d /tmp/archive_workbench_v0.69.1

cp -a /tmp/archive_workbench_v0.69.1/. .

python -m pip install \
  --no-build-isolation \
  --no-deps \
  -e .
```

Comprobá:

```bash
python -c "import archive_workbench; print(archive_workbench.__version__)"
```

Debe devolver:

```text
0.69.1
```

## 2. Base de datos

Esta versión no contiene migración. No ejecutes `db-upgrade`, no vuelvas a respaldar `project_data` y no recrees `project_data_open_discovery_validation`.

La revisión continúa siendo:

```text
0038_open_discovery
```

## 3. Pruebas automatizadas

Ejecutá:

```bash
pytest -q tests/test_open_discovery.py
```

Esperado:

```text
8 passed
```

Después:

```bash
pytest -q tests/test_ui_navigation.py
```

Esperado:

```text
45 passed
```

Luego:

```bash
pytest -q \
  tests/test_documentation.py \
  tests/test_packaging.py
```

Esperado:

```text
42 passed
```

Finalmente:

```bash
pytest --collect-only -q
```

Debe recopilar:

```text
395 tests
```

No se ejecutó nuevamente la suite monolítica completa.

## 4. Retomar la validación manual

Abrí la misma copia descartable:

```bash
archive-workbench review-app \
  project_data_open_discovery_validation
```

Entrá en **Entidades y menciones**. El panel **Descubrimiento abierto** debe aparecer al final de la pantalla y cerrado por defecto.

Abrilo. El perfil **Validación DISC-01A local** debe seguir disponible. No vuelvas a guardarlo ni cambies sus parámetros.

Pulsá **Ejecutar descubrimiento abierto** una sola vez.

Debe indicar:

```text
Corrida completada: 7 candidatos en 1 objetos.
```

Deben aparecer exactamente:

```text
24 de marzo de 1976
Dra. Valentina Orbe
ciudad de Puerto Niebla
Ministerio de Archivos Imaginarios
operativo Horizonte
investigación documental
Cuaderno del Delta
```

Distribución esperada:

```text
actor: 2
space: 1
time: 1
event: 1
action_process: 1
work: 1
```

No debe aparecer ninguna acción para aceptar, crear, vincular o fusionar registros. Detené Streamlit con `Ctrl+C`.

## 5. Comprobaciones desde terminal

```bash
archive-workbench discovery-runs \
  project_data_open_discovery_validation \
  --limit 10
```

Debe mostrar una única corrida `completed`, un objeto y siete candidatos.

Obtené el identificador:

```bash
RUN_ID="$(python - <<'PY2'
from pathlib import Path
from sqlalchemy import select

from archive_workbench.db import (
    create_sqlite_engine,
    database_path,
    session_scope,
)
from archive_workbench.db.models import DiscoveryRun

root = Path("project_data_open_discovery_validation")
engine = create_sqlite_engine(database_path(root))
try:
    with session_scope(engine) as session:
        rows = list(session.scalars(select(DiscoveryRun)))
        assert len(rows) == 1
        assert rows[0].status == "completed"
        print(rows[0].id)
finally:
    engine.dispose()
PY2
)"

printf 'RUN_ID=%s\n' "$RUN_ID"
```

Listá los candidatos:

```bash
archive-workbench discovery-candidates \
  project_data_open_discovery_validation \
  --run-id "$RUN_ID"
```

Debe finalizar con:

```text
Total: 7 candidatos
```

Generá la auditoría:

```bash
archive-workbench discovery-audit \
  project_data_open_discovery_validation \
  "$RUN_ID" \
  --output \
  project_data_open_discovery_validation/validation/disc01a_audit.json
```

## 6. Verificación final

Ejecutá exactamente:

```bash
python - <<'PY2'
from collections import Counter
import json
from pathlib import Path

from sqlalchemy import func, select, text

from archive_workbench.db import (
    create_sqlite_engine,
    current_revision,
    database_path,
    session_scope,
)
from archive_workbench.db.models import (
    AutomaticAnalysisAuthorization,
    AuthorityRecord,
    DiscoveryCandidate,
    DiscoveryProfile,
    DiscoveryRun,
    EditableObject,
    EntityMention,
    EntityRelation,
)

root = Path("project_data_open_discovery_validation")
validation = json.loads(
    (root / "validation" / "disc01a.json").read_text()
)
engine = create_sqlite_engine(database_path(root))

try:
    with session_scope(engine) as session:
        profiles = list(session.scalars(select(DiscoveryProfile)))
        runs = list(session.scalars(select(DiscoveryRun)))
        candidates = list(
            session.scalars(
                select(DiscoveryCandidate).order_by(
                    DiscoveryCandidate.start_offset,
                    DiscoveryCandidate.end_offset,
                    DiscoveryCandidate.semantic_family,
                )
            )
        )
        authorizations = list(
            session.scalars(
                select(AutomaticAnalysisAuthorization).where(
                    AutomaticAnalysisAuthorization.analysis_kind
                    == "open_discovery"
                )
            )
        )
        editable = session.get(
            EditableObject,
            validation["editable_object_id"],
        )
        assert editable is not None

        canonical_counts = {
            "authority_records": int(
                session.scalar(
                    select(func.count()).select_from(AuthorityRecord)
                )
                or 0
            ),
            "entity_mentions": int(
                session.scalar(
                    select(func.count()).select_from(EntityMention)
                )
                or 0
            ),
            "entity_relations": int(
                session.scalar(
                    select(func.count()).select_from(EntityRelation)
                )
                or 0
            ),
        }
        integrity = session.execute(
            text("PRAGMA integrity_check")
        ).scalar_one()
        foreign_keys = session.execute(
            text("PRAGMA foreign_key_check")
        ).all()

        assert len(profiles) == 1
        assert len(runs) == 1
        assert runs[0].status == "completed"
        assert runs[0].object_count == 1
        assert runs[0].candidate_count == 7
        assert len(candidates) == 7
        assert {
            row.exact_text for row in candidates
        } == set(validation["expected_texts"])
        assert Counter(
            row.semantic_family for row in candidates
        ) == Counter(
            {
                "actor": 2,
                "space": 1,
                "time": 1,
                "event": 1,
                "action_process": 1,
                "work": 1,
            }
        )
        for row in candidates:
            assert (
                editable.current_text[
                    row.start_offset:row.end_offset
                ]
                == row.exact_text
            )
            assert (
                row.object_revision_number
                == editable.revision_number
            )
            assert len(row.parameters_sha256) == 64

        assert (
            canonical_counts
            == validation["canonical_counts_before"]
        )
        assert len(authorizations) == 1
        assert authorizations[0].source == "ui"
        assert (
            authorizations[0].target_type
            == "discovery_profile"
        )
        assert (
            authorizations[0].page_review_statuses_json
            == ["approved"]
        )
        assert (
            current_revision(root)
            == "0038_open_discovery"
        )
        assert integrity == "ok"
        assert foreign_keys == []

        print("perfiles:", len(profiles))
        print("corridas:", len(runs))
        print("candidatos:", len(candidates))
        print(
            "familias:",
            dict(
                sorted(
                    Counter(
                        row.semantic_family
                        for row in candidates
                    ).items()
                )
            ),
        )
        print("registros canónicos:", canonical_counts)
        print("revisión:", current_revision(root))
        print("integridad:", integrity)
        print("claves foráneas:", foreign_keys)
finally:
    engine.dispose()
PY2
```

Debe mostrar una corrida, siete candidatos, seis familias, los mismos conteos canónicos registrados antes de ejecutar, revisión `0038_open_discovery`, integridad `ok` y claves foráneas vacías.

No repitas la migración de `project_data` ni recrees la copia descartable. `DISC-01A` continúa pendiente únicamente de esta validación manual corregida.
