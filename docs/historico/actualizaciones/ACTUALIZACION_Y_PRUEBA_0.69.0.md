# Actualización y prueba — Archive Workbench 0.69.0

Esta versión implementa `DISC-01A`: perfiles, corridas y candidatos persistentes para descubrimiento abierto, con un proveedor local determinista y trazabilidad hasta el texto exacto. No crea autoridades, menciones ni relaciones.

La versión agrega la migración:

```text
0038_open_discovery
```

## 1. Actualizar el código

Detené Streamlit con `Ctrl+C` y ejecutá:

```bash
cd ~/projects/archive_app
source .venv/bin/activate

rm -rf /tmp/archive_workbench_v0.69.0
mkdir -p /tmp/archive_workbench_v0.69.0

unzip -q \
  ~/Downloads/archive_workbench_v0.69.0.zip \
  -d /tmp/archive_workbench_v0.69.0

cp -a /tmp/archive_workbench_v0.69.0/. .

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
0.69.0
```

## 2. Pruebas automatizadas

Ejecutá en este orden:

```bash
pytest -q tests/test_open_discovery.py
```

Esperado:

```text
7 passed
```

```bash
pytest -q tests/test_database.py
```

Esperado:

```text
15 passed
```

Las advertencias del adaptador de fechas de SQLite bajo Python 3.12 no representan fallos.

```bash
pytest -q \
  tests/test_analysis_quality.py \
  tests/test_ui_navigation.py
```

Esperado:

```text
52 passed
```

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
394 tests
```

No se ejecutó nuevamente la suite monolítica completa.

## 3. Respaldar y migrar `project_data`

`project_data` es la base principal local y debe quedar utilizable en la versión vigente. No ejecutes descubrimiento abierto sobre ella durante esta validación.

Primero creá un backup:

```bash
archive-workbench project-backup-create \
  project_data \
  --created-by alex \
  --note "Antes de migrar project_data a Archive Workbench 0.69.0"
```

Debe mostrar `OK`, la revisión anterior y los SHA-256 del backup.

Después migrá:

```bash
archive-workbench db-upgrade project_data
```

Debe finalizar con:

```text
Revisión: 0038_open_discovery
```

Comprobá:

```bash
archive-workbench db-status project_data
```

Abrí la aplicación solamente para verificar continuidad:

```bash
archive-workbench review-app project_data
```

Confirmá que abre y que las pruebas OCR siguen visibles. No guardes perfiles ni ejecutes descubrimiento en `project_data`. Detené Streamlit con `Ctrl+C`.

## 4. Crear la copia descartable

Ejecutá:

```bash
rm -rf project_data_open_discovery_validation

python scripts/create_open_discovery_validation_project.py \
  --source project_data \
  --destination project_data_open_discovery_validation
```

Debe informar:

```text
Revisión de base: 0038_open_discovery
Familias esperadas: actor, space, time, event, action_process, work
Candidatos esperados: 7
No se crearon perfiles, corridas, candidatos ni registros canónicos.
El proyecto fuente no fue modificado.
```

## 5. Crear el perfil y ejecutar desde la interfaz

Abrí:

```bash
archive-workbench review-app project_data_open_discovery_validation
```

Entrá en:

```text
Entidades y menciones
→ Descubrimiento abierto
→ Configurar perfil
```

Creá un perfil con:

```text
Nombre: Validación DISC-01A local
Descripción: Validación del proveedor local determinista.
Familias: Actor, Espacio, Tiempo, Acontecimiento, Acción o proceso y Obra
Tipos de objeto incluidos: vacío
Estados de revisión de objeto: vacío
Estados de página incluidos: Aprobada
Confianza mínima: 0.75
```

Pulsá **Guardar perfil de descubrimiento**. Debe aparecer:

```text
Perfil guardado y autorización registrada.
```

Después pulsá **Ejecutar descubrimiento abierto** una sola vez.

Debe indicar:

```text
Corrida completada: 7 candidatos en 1 objetos.
```

La corrida debe mostrar estos siete textos:

```text
24 de marzo de 1976
Dra. Valentina Orbe
ciudad de Puerto Niebla
Ministerio de Archivos Imaginarios
operativo Horizonte
investigación documental
Cuaderno del Delta
```

Deben estar representadas seis familias: dos candidatos `actor` y uno de cada una de `space`, `time`, `event`, `action_process` y `work`.

Cada tarjeta debe mostrar fuente, página, objeto, offsets, revisión textual, confianza, proveedor, versión, método y explicación. No debe aparecer ninguna acción para aceptar, crear, vincular o fusionar registros en esta fase.

Detené Streamlit con `Ctrl+C`.

## 6. Comprobar desde terminal

Ejecutá:

```bash
archive-workbench discovery-profiles \
  project_data_open_discovery_validation
```

Debe mostrar un perfil y páginas `approved`.

Después:

```bash
archive-workbench discovery-runs \
  project_data_open_discovery_validation \
  --limit 10
```

Debe mostrar una corrida `completed`, `objetos=1`, `candidatos=7` y las cantidades por familia.

Obtené el identificador de la corrida:

```bash
RUN_ID="$(python - <<'PY'
from pathlib import Path
from sqlalchemy import select
from archive_workbench.db import create_sqlite_engine, database_path, session_scope
from archive_workbench.db.models import DiscoveryRun

root = Path("project_data_open_discovery_validation")
engine = create_sqlite_engine(database_path(root))
try:
    with session_scope(engine) as session:
        row = session.scalar(
            select(DiscoveryRun).order_by(DiscoveryRun.started_at.desc(), DiscoveryRun.id.desc())
        )
        assert row is not None
        print(row.id)
finally:
    engine.dispose()
PY
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
  --output project_data_open_discovery_validation/validation/disc01a_audit.json
```

Debe indicar que escribió el JSON de auditoría.

## 7. Verificar persistencia, offsets y ausencia de escrituras canónicas

Ejecutá exactamente:

```bash
python - <<'PY'
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
validation = json.loads((root / "validation" / "disc01a.json").read_text())
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
                    AutomaticAnalysisAuthorization.analysis_kind == "open_discovery"
                )
            )
        )
        editable = session.get(EditableObject, validation["editable_object_id"])
        assert editable is not None

        canonical_counts = {
            "authority_records": int(
                session.scalar(select(func.count()).select_from(AuthorityRecord)) or 0
            ),
            "entity_mentions": int(
                session.scalar(select(func.count()).select_from(EntityMention)) or 0
            ),
            "entity_relations": int(
                session.scalar(select(func.count()).select_from(EntityRelation)) or 0
            ),
        }
        integrity = session.execute(text("PRAGMA integrity_check")).scalar_one()
        foreign_keys = session.execute(text("PRAGMA foreign_key_check")).all()

        assert len(profiles) == 1
        assert len(runs) == 1
        assert runs[0].status == "completed"
        assert runs[0].object_count == 1
        assert runs[0].candidate_count == 7
        assert len(candidates) == 7
        assert {row.exact_text for row in candidates} == set(validation["expected_texts"])
        assert Counter(row.semantic_family for row in candidates) == Counter(
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
            assert editable.current_text[row.start_offset:row.end_offset] == row.exact_text
            assert row.object_revision_number == editable.revision_number
            assert len(row.parameters_sha256) == 64

        assert canonical_counts == validation["canonical_counts_before"]
        assert len(authorizations) == 1
        assert authorizations[0].source == "ui"
        assert authorizations[0].target_type == "discovery_profile"
        assert authorizations[0].page_review_statuses_json == ["approved"]
        assert current_revision(root) == "0038_open_discovery"
        assert integrity == "ok"
        assert foreign_keys == []

        print("perfiles:", len(profiles))
        print("corridas:", len(runs))
        print("candidatos:", len(candidates))
        print("familias:", dict(sorted(Counter(row.semantic_family for row in candidates).items())))
        print("registros canónicos:", canonical_counts)
        print("revisión:", current_revision(root))
        print("integridad:", integrity)
        print("claves foráneas:", foreign_keys)
finally:
    engine.dispose()
PY
```

Debe mostrar una corrida, siete candidatos, seis familias, los mismos conteos canónicos registrados antes de ejecutar, revisión `0038_open_discovery`, integridad `ok` y claves foráneas vacías.

No repitas pruebas de `DATA-01`, `DATA-02` o `EX-01`. `DISC-01A` queda pendiente únicamente de esta validación manual; después corresponde `DISC-01B`.
