# Actualización y prueba — Archive Workbench 0.64.1

## Objetivo

Esta versión corrige únicamente el bloqueo de **Buscar coincidencias** durante la validación de `DATA-02`. El botón ya no depende de la confirmación ni del fundamento para habilitarse: permanece disponible y, al pulsarlo, la política común valida esos datos antes de registrar la autorización. Un envío incompleto muestra un error y no escribe en la base.

La validación ya realizada de exportación y búsqueda semántica se conserva. No debe repetirse. La revisión de base continúa en `0034_automatic_analysis_authorizations`.

## 1. Actualizar el código

Detené Streamlit con `Ctrl+C` y ejecutá:

```bash
cd ~/projects/archive_app
source .venv/bin/activate

rm -rf /tmp/archive_workbench_v0.64.1
mkdir -p /tmp/archive_workbench_v0.64.1

unzip -q \
  ~/Downloads/archive_workbench_v0.64.1.zip \
  -d /tmp/archive_workbench_v0.64.1

cp -a /tmp/archive_workbench_v0.64.1/. .

pip install -e ".[dev,extraction,streamlit,semantic,tiff]"
```

Comprobá:

```bash
python -c "import archive_workbench; print(archive_workbench.__version__)"
```

Debe devolver:

```text
0.64.1
```

## 2. Pruebas automatizadas

Ejecutá:

```bash
pytest -q tests/test_analysis_quality.py
```

Resultado esperado: `7 passed`.

Después:

```bash
pytest -q tests/test_ui_navigation.py
```

Resultado esperado: `42 passed`.

Y finalmente:

```bash
pytest -q \
  tests/test_documentation.py \
  tests/test_packaging.py
```

Resultado esperado: `38 passed`.

Comprobá la colección completa:

```bash
pytest --collect-only -q
```

Debe recopilar `355 tests`.

Las advertencias del adaptador de fechas de SQLite bajo Python 3.12 no representan fallos.

## 3. Base de datos

Esta versión **no contiene una migración**. No ejecutes `db-upgrade` sobre `project_data_analysis_quality_audit_validation`: debe continuar en:

```text
0034_automatic_analysis_authorizations
```

Tampoco vuelvas a crear la copia descartable. Conservá los dos registros ya obtenidos para exportación y búsqueda semántica.

## 4. Completar la autorización de sugerencias

Abrí la misma copia descartable:

```bash
archive-workbench review-app project_data_analysis_quality_audit_validation
```

Entrá en:

```text
Entidades y menciones
→ seleccionar una entidad existente
→ Menciones en documentos
→ Opciones de búsqueda
```

Usá exactamente:

```text
Estados de página: Revisada + Aprobada
Fundamento: Validación DATA-02 sugerencias.
```

Marcá:

```text
Confirmo que deseo buscar menciones en páginas no aprobadas
```

El botón **Buscar coincidencias** debe permanecer habilitado. Pulsalo una sola vez.

Resultado esperado:

- la búsqueda se ejecuta;
- no aparece un error de confirmación ni de fundamento;
- no incorpores ninguna mención.

No repitas los pasos de exportación ni de búsqueda semántica.

## 5. Revisar la auditoría

Entrá en:

```text
Administrar y recuperar
→ Auditoría de análisis
```

Ahora deben aparecer los tres tipos:

```text
Exportación de corpus
Índice y búsqueda semántica
Sugerencias automáticas de menciones
```

El registro nuevo debe mostrar:

```text
alcance ampliado
origen: Interfaz
fundamento: Validación DATA-02 sugerencias.
```

En **Detalles técnicos** deben verse el identificador, el tipo, los estados incluidos y el SHA-256 de parámetros.

No edites ni elimines esos registros. Detené Streamlit con `Ctrl+C`.

## 6. Comprobar desde terminal

Ejecutá:

```bash
archive-workbench analysis-quality-audit \
  project_data_analysis_quality_audit_validation \
  --limit 20
```

La salida debe contener:

```text
corpus_export
semantic_index
mention_suggestions
fundamento: Validación DATA-02 exportación.
fundamento: Validación DATA-02 índice semántico.
fundamento: Validación DATA-02 sugerencias.
```

## 7. Verificar base e integridad

Ejecutá exactamente:

```bash
python - <<'PY'
from pathlib import Path

from sqlalchemy import select, text

from archive_workbench.db import (
    create_sqlite_engine,
    current_revision,
    database_path,
    session_scope,
)
from archive_workbench.db.models import AutomaticAnalysisAuthorization

root = Path("project_data_analysis_quality_audit_validation")
engine = create_sqlite_engine(database_path(root))

try:
    with session_scope(engine) as session:
        rows = list(
            session.scalars(
                select(AutomaticAnalysisAuthorization).where(
                    AutomaticAnalysisAuthorization.confirmation_reason.in_(
                        [
                            "Validación DATA-02 exportación.",
                            "Validación DATA-02 índice semántico.",
                            "Validación DATA-02 sugerencias.",
                        ]
                    )
                )
            )
        )

        by_kind = {row.analysis_kind: row for row in rows}
        integrity = session.execute(text("PRAGMA integrity_check")).scalar_one()
        foreign_keys = session.execute(text("PRAGMA foreign_key_check")).all()

        assert set(by_kind) == {
            "corpus_export",
            "semantic_index",
            "mention_suggestions",
        }

        for row in rows:
            assert row.scope_key == "broader"
            assert row.page_review_statuses_json == ["reviewed", "approved"]
            assert row.broader_scope_confirmed is True
            assert row.source == "ui"
            assert row.parameters_sha256 is not None
            assert len(row.parameters_sha256) == 64

        assert current_revision(root) == "0034_automatic_analysis_authorizations"
        assert integrity == "ok"
        assert foreign_keys == []

        print("tipos auditados:", sorted(by_kind))
        print("autorizaciones ampliadas:", len(rows))
        print("revisión:", current_revision(root))
        print("integridad:", integrity)
        print("claves foráneas:", foreign_keys)
finally:
    engine.dispose()
PY
```

Debe mostrar:

```text
tipos auditados: ['corpus_export', 'mention_suggestions', 'semantic_index']
autorizaciones ampliadas: 3
revisión: 0034_automatic_analysis_authorizations
integridad: ok
claves foráneas: []
```

No repitas ninguna prueba de `DATA-01`.

Relación con “Pendientes y mejoras”: `DATA-02` sigue activo solamente hasta confirmar esta prueba final. Una vez validada, se hará el cierre documental mínimo y se continuará con `EX-01` desde los documentos de `.assistant`.
