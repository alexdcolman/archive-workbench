# Actualización y prueba — Archive Workbench 0.64.0

## Objetivo

Esta versión completa la implementación de `DATA-02`; el pendiente se cierra después de validar esta guía. El alcance seguro de todo análisis automático actual es programáticamente `approved`; ampliar el alcance exige confirmación, responsable y fundamento, y genera una autorización append-only visible en la interfaz y en terminal.

La previsualización y ejecución de exportaciones, la construcción de índices semánticos y la búsqueda semántica verifican además que la configuración funcional vigente del perfil coincida con una autorización persistida. La migración `0034_automatic_analysis_authorizations` agrega únicamente ese registro: no modifica perfiles, índices, textos, menciones, autoridades, relaciones ni exportaciones existentes, y no fabrica autorizaciones retrospectivas.

## 1. Actualizar el código

Cerrá Streamlit con `Ctrl+C` y ejecutá:

```bash
cd ~/projects/archive_app
source .venv/bin/activate

rm -rf /tmp/archive_workbench_v0.64.0
mkdir -p /tmp/archive_workbench_v0.64.0

unzip -q \
  ~/Downloads/archive_workbench_v0.64.0.zip \
  -d /tmp/archive_workbench_v0.64.0

cp -a /tmp/archive_workbench_v0.64.0/. .

pip install -e ".[dev,extraction,streamlit,semantic,tiff]"
```

Comprobá:

```bash
python -c "import archive_workbench; print(archive_workbench.__version__)"
```

Debe devolver:

```text
0.64.0
```

## 2. Pruebas automatizadas

Ejecutá primero la política común:

```bash
pytest -q tests/test_analysis_quality.py
```

Resultado esperado: `7 passed`.

Después ejecutá perfiles de exportación y búsqueda semántica:

```bash
pytest -q \
  tests/test_corpus_export.py \
  tests/test_semantic_search.py
```

Resultado esperado: `14 passed`.

Ejecutá menciones y búsqueda literal por separado:

```bash
pytest -q tests/test_relations.py
```

Resultado esperado: `10 passed`.

```bash
pytest -q tests/test_search.py
```

Resultado esperado: `15 passed`.

Después ejecutá la migración:

```bash
pytest -q tests/test_database.py
```

Resultado esperado: `11 passed`.

Ejecutá operación e interfaz:

```bash
pytest -q \
  tests/test_operational.py \
  tests/test_ui_navigation.py
```

Resultado esperado: `48 passed`.

Ejecutá las regresiones de intercambio vinculadas con la revisión de base y las menciones:

```bash
pytest -q \
  tests/test_exchange.py::test_exchange_migration_upgrades_existing_0012_database \
  tests/test_exchange.py::test_bundle_export_and_inspection_are_verifiable \
  tests/test_exchange.py::test_missing_authority_repair_travels_as_a_mention_update \
  tests/test_exchange.py::test_incoming_bundle_diagnostics_and_lifecycle_management
```

Resultado esperado:

```text
4 passed
```

Finalmente:

```bash
pytest -q \
  tests/test_documentation.py \
  tests/test_packaging.py
```

Resultado esperado:

```text
38 passed
```

Comprobá la recopilación completa:

```bash
pytest --collect-only -q
```

Debe recopilar:

```text
355 tests
```

Las advertencias del adaptador de fechas de SQLite bajo Python 3.12 no representan fallos.

## 3. Respaldar y migrar el proyecto de referencia

Esta versión sí contiene una migración. Antes de ejecutarla sobre el proyecto de referencia, creá una copia verificable:

```bash
archive-workbench project-backup-create \
  project_data_rebase_validation \
  --created-by alex \
  --note "Antes de migrar a Archive Workbench 0.64.0"
```

Debe mostrar `OK`, el SHA-256 y la revisión anterior.

Migrá después el proyecto:

```bash
archive-workbench db-upgrade project_data_rebase_validation
```

Debe finalizar con:

```text
Revisión: 0034_automatic_analysis_authorizations
```

Comprobá sin modificar nada:

```bash
archive-workbench db-status project_data_rebase_validation
```

Debe indicar la misma revisión. Para cualquier otro proyecto que abras con 0.64.0, repetí primero el backup y luego `db-upgrade`; no hace falta migrar ahora proyectos que no vayas a usar.

Los perfiles de exportación o búsqueda semántica creados antes de 0.64.0 no reciben una autorización inventada durante la migración. La primera vez que vuelvas a usar uno, abrilo en su pantalla de configuración y guardalo nuevamente; hasta entonces, la aplicación bloqueará su vista previa, exportación, construcción de índice o consulta semántica con un mensaje explícito.

## 4. Crear una copia descartable para la validación

Con Streamlit cerrado, ejecutá:

```bash
rm -rf project_data_analysis_quality_audit_validation

python scripts/create_analysis_quality_audit_validation_project.py \
  --source project_data_rebase_validation \
  --destination project_data_analysis_quality_audit_validation
```

Debe informar:

```text
Proyecto descartable creado:
Revisión de base: 0034_automatic_analysis_authorizations
Página aprobada para la prueba:
Perfiles, índices y autorizaciones anteriores reiniciados en la copia.
```

El script modifica únicamente la copia descartable.

## 5. Registrar tres alcances ampliados desde la interfaz

Abrí:

```bash
archive-workbench review-app project_data_analysis_quality_audit_validation
```

### Exportación

Entrá en **Preparar corpus → Configurar perfil → Crear un perfil nuevo**.

Usá:

```text
Nombre: Validación auditoría exportación
Estados de página: Revisada + Aprobada
Fundamento: Validación DATA-02 exportación.
```

Marcá la confirmación de alcance ampliado y pulsá **Guardar perfil**. Debe aparecer `Perfil guardado`.

Entrá inmediatamente en **Revisar contenido**. La vista previa debe cargarse sin advertencias de autorización y mostrar sus métricas; esto verifica que el guardado habilitó exactamente la configuración vigente. No generes el archivo.

### Búsqueda semántica

Entrá en **Buscar por significado → Preparar búsqueda**. En el perfil `Multilingüe E5 — objetos`, seleccioná:

```text
Estados de página: Revisada + Aprobada
Fundamento: Validación DATA-02 índice semántico.
```

Marcá la confirmación y pulsá **Guardar perfil**. Debe indicar que el perfil fue guardado y que el índice requiere reconstrucción. No reconstruyas el índice. Las pruebas automatizadas verifican que una configuración semántica modificada sin nueva autorización queda bloqueada y que vuelve a habilitarse después de guardarla.

### Sugerencias de menciones

Entrá en **Entidades y menciones**, seleccioná una entidad existente y abrí **Menciones en documentos → Opciones de búsqueda**.

Seleccioná:

```text
Estados de página: Revisada + Aprobada
Fundamento: Validación DATA-02 sugerencias.
```

Marcá la confirmación y pulsá **Buscar coincidencias** una sola vez. No incorpores ninguna mención.

## 6. Revisar la auditoría

Entrá en **Administrar y recuperar → Auditoría de análisis**.

Deben aparecer registros para:

```text
Exportación de corpus
Índice y búsqueda semántica
Sugerencias automáticas de menciones
```

Los tres registros ampliados deben mostrar una advertencia de alcance, origen **Interfaz** y el fundamento correspondiente. Al abrir **Detalles técnicos**, deben verse identificador, tipo, alcance, estados y SHA-256 de parámetros.

No edites ni elimines esos registros: la auditoría es append-only.

Detené Streamlit con `Ctrl+C`.

## 7. Comprobar la auditoría desde terminal

Ejecutá:

```bash
archive-workbench analysis-quality-audit \
  project_data_analysis_quality_audit_validation \
  --limit 20
```

La salida debe incluir:

```text
corpus_export
semantic_index
mention_suggestions
fundamento: Validación DATA-02 exportación.
fundamento: Validación DATA-02 índice semántico.
fundamento: Validación DATA-02 sugerencias.
```

## 8. Verificación final de base

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

## 9. Relevo a una conversación nueva

Después de validar esta guía, la conversación siguiente debe comenzar leyendo `.assistant/00_LEER_PRIMERO.md` y `.assistant/06_RELEVO_NUEVA_CONVERSACION.md`. No hay que reconstruir pendientes desde el chat ni repetir validaciones cerradas; el próximo bloque recomendado queda indicado allí y en `PENDIENTES_ACTIVOS.md`.

Relación con “Pendientes y mejoras”: `DATA-02` queda en la lista activa únicamente como validación pendiente de esta versión. Cuando la prueba resulte satisfactoria, se retirará, se preparará el relevo definitivo a una conversación nueva y la siguiente prioridad será `EX-01`.
