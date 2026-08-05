# Actualización y prueba — Archive Workbench 0.77.0

Esta versión implementa conjuntamente `CAT-02` y `GRAPH-02`: incorpora entidades productoras y gestoras como relaciones controladas con autoridades, conserva período, evidencia, procedencia e historial, y separa en el grafo la jerarquía archivística, documentos, partes, menciones, relaciones analíticas y roles archivísticos.

El candidato corregido agrega flechas a los vínculos dirigidos, mantiene sin flecha la capa simétrica de entidades compartidas, corrige la dirección y el rótulo de la pertenencia documental y evita que **Distancia desde el centro** quede deshabilitada después de aplicar filtros.

La versión agrega la migración aditiva `0041_catalog_authority_roles_graph_layers`. `project_data` no debe migrarse durante la primera prueba: antes se crea y valida una base descartable fuera del repositorio.

## 1. Comprobar el ZIP y el estado local

```bash
cd ~/Downloads
sha256sum -c archive_workbench_v0.77.0.zip.sha256

cd ~/projects/archive_app
source .venv/bin/activate

git status --short
python -c "import archive_workbench; print(archive_workbench.__version__)"
```

El checksum debe indicar `OK`, el estado de Git debe estar vacío y la versión previa debe ser `0.76.0`.

## 2. Respaldar la base principal antes de copiar la versión

Este bloque usa la API de backup de SQLite y no modifica la base de origen.

```bash
cd ~/projects/archive_app
source .venv/bin/activate

BACKUP_DIR="$HOME/Downloads/archive_workbench_backups"
STAMP="$(date +%Y%m%d_%H%M%S)"
DB_PATH="$HOME/projects/archive_app/project_data/data/archive_workbench.sqlite3"
BACKUP_PATH="$BACKUP_DIR/project_data_pre_0770_${STAMP}.sqlite3"

mkdir -p "$BACKUP_DIR"

test -f "$DB_PATH" && \
python - "$DB_PATH" "$BACKUP_PATH" <<'PY'
from pathlib import Path
import sqlite3
import sys

source_path = Path(sys.argv[1]).resolve()
backup_path = Path(sys.argv[2]).resolve()
source = sqlite3.connect(source_path)
backup = sqlite3.connect(backup_path)
try:
    check = source.execute("PRAGMA quick_check").fetchone()[0]
    if check != "ok":
        raise SystemExit(f"La base de origen no pasó PRAGMA quick_check: {check}")
    source.backup(backup)
    backup_check = backup.execute("PRAGMA quick_check").fetchone()[0]
    if backup_check != "ok":
        raise SystemExit(f"El backup no pasó PRAGMA quick_check: {backup_check}")
finally:
    backup.close()
    source.close()
print(backup_path)
PY

sha256sum "$BACKUP_PATH" | tee "$BACKUP_PATH.sha256"
```

Conservá el archivo `.sqlite3` y su `.sha256`. Este paso no ejecuta ninguna migración.

## 3. Actualizar el código sin mover ni eliminar archivos locales

```bash
cd ~/projects/archive_app
source .venv/bin/activate

TMP_DIR="$(mktemp -d "$HOME/Downloads/archive_workbench_0770_XXXXXX")"
unzip -q \
  "$HOME/Downloads/archive_workbench_v0.77.0.zip" \
  -d "$TMP_DIR"

cp -a "$TMP_DIR"/. .

python -m pip install \
  --no-build-isolation \
  -e .

python -c "import archive_workbench; print(archive_workbench.__version__)"
```

Debe devolver `0.77.0`. La copia no mueve ni elimina `project_data`, `.git`, `.venv`, `.dev`, `.assistant` ni otros contenidos locales. Conservá la carpeta temporal.

## 4. Crear la base descartable de validación

Este bloque crea una ruta nueva en `~/Downloads`. El script se detiene si la ruta ya existe y nunca elimina ni reemplaza un proyecto.

```bash
cd ~/projects/archive_app
source .venv/bin/activate

VALIDATION_ROOT="$HOME/Downloads/archive_workbench_catalog_graph_validation_0770"

test ! -e "$VALIDATION_ROOT" && \
python scripts/create_catalog_graph_validation_project.py \
  --destination "$VALIDATION_ROOT"
```

Resultado esperado:

- versión `0.77.0`;
- revisión `0041_catalog_authority_roles_graph_layers`;
- proyecto `Proyecto de validación CAT-02 y GRAPH-02`;
- nodos de autoridad, unidad archivística, documento y parte;
- capas `hierarchy`, `document`, `part`, `mention`, `analytical`, `producer` y `manager`;
- cero errores de consistencia;
- confirmación `project_data_touched: false`.

## 5. Pruebas relevantes y recopilación completa

```bash
cd ~/projects/archive_app
source .venv/bin/activate

pytest -q \
  tests/test_relations.py \
  tests/test_graph.py \
  tests/test_catalog_management.py \
  tests/test_catalog_templates.py \
  tests/test_authority_dictionary.py \
  tests/test_ui_navigation.py \
  tests/test_database.py::test_migration_and_registration_are_idempotent \
  tests/test_database.py::test_catalog_authority_roles_migration_preserves_relations_and_enforces_contract \
  tests/test_exchange.py::test_explicit_entity_relations_travel_in_bundle \
  tests/test_exchange.py::test_catalog_authority_role_travels_with_kind_provenance_and_period \
  tests/test_search.py::test_explicit_relations_are_searchable_from_entity_mentions \
  tests/test_documentation.py \
  tests/test_packaging.py && \
pytest --collect-only -q
```

No repetir las pruebas manuales de `UX-03`, `DISC-01A/B/C/D`, `SEM-01`, `GRAPH-01`, `OCR-02`, `CAT-01` ni `DISC-02`.

## 6. Revisión manual limitada a CAT-02 y GRAPH-02

```bash
cd ~/projects/archive_app
source .venv/bin/activate

VALIDATION_ROOT="$HOME/Downloads/archive_workbench_catalog_graph_validation_0770"
archive-workbench review-app "$VALIDATION_ROOT"
```

En **Catálogo documental**:

1. Seleccioná `Informe controlado de dos páginas`.
2. Abrí **Productores y gestión**.
3. Deben aparecer una entidad productora y dos etapas de gestión, con período, evidencia y procedencia.
4. `Dirección de Inteligencia` debe figurar como productora entre 1974 y 1976 y como gestora entre 1977 y 1983. El nombre no debe repetirse como texto libre canónico.
5. Abrí el historial de un vínculo: debe conservar la revisión inicial y su snapshot.
6. En la copia descartable, editá únicamente la nota de procedencia de la gestión 1977–1983. Después del guardado, el historial debe mostrar una revisión nueva sin borrar la anterior.

En **Mapa de relaciones**:

1. Activá y desactivá por separado jerarquía, documentos, partes, menciones, relaciones analíticas, productores y gestores.
2. Filtrá los niveles `archivo`, `fondo`, `serie` y `documento`.
3. Usá como foco, uno por vez, el documento, `Informe principal`, `Dirección de Inteligencia` y la unidad catalográfica.
4. Elegí un foco, seleccioná distancia 1 y aplicá. Confirmá que el selector siga habilitado; cambialo a 2, aplicá otra vez y verificá que continúe habilitado. Sin foco, el valor puede modificarse pero no restringe el mapa.
5. Confirmá que las aristas dirigidas tengan una flecha visible junto al destino. La capa derivada **Entidades compartidas** es simétrica y no debe mostrar flecha.
6. En la arista documental, `informe_controlado.pdf` debe apuntar hacia `Informe controlado de dos páginas` con la etiqueta `representa`.
7. Seleccioná una arista de pertenencia, una analítica y una de productor o gestor. Cada una debe mostrar un origen diferente y explicable; las pertenencias no deben aparecer como relaciones analíticas.
8. Probá los límites de 60 y 120 elementos.
9. En **Exportar datos**, generá JSON, CSV y GraphML. El JSON debe conservar las fechas de los vínculos sin error de serialización y la arista documental debe usar `source = digital_object`, `target = archival_unit` y `label = representa`.

Detené Streamlit con `Ctrl+C`. La base descartable y el temporal de instalación no se eliminan automáticamente.

## 7. Migración autorizada de project_data

La revisión manual fue aprobada. Con el backup ya verificado, corresponde migrar la base principal:

```bash
cd ~/projects/archive_app
source .venv/bin/activate

archive-workbench db-upgrade \
  "$HOME/projects/archive_app/project_data"

archive-workbench db-status \
  "$HOME/projects/archive_app/project_data"
```

El resultado debe indicar `0041_catalog_authority_roles_graph_layers`. La migración es aditiva y conserva las relaciones anteriores como `analytical`.

## 8. Comprobaciones de Git posteriores

Después de la migración:

```bash
cd ~/projects/archive_app

git status --short
git diff --summary
git diff --check
```

La lista exacta de `git add`, el commit, el tag y el push se conserva en las instrucciones de publicación entregadas junto con el artefacto.

## 9. Validación previa del artefacto

Antes de distribuir el ZIP se comprobó en una copia aislada:

- migración aditiva desde `0040_discovery_grouping_continuity` hasta `0041_catalog_authority_roles_graph_layers`;
- conservación de relaciones anteriores como `analytical`;
- rechazo de roles sin unidad, evidencia, procedencia o etiqueta canónica;
- historial append-only de productores y gestores;
- intercambio de roles con período, evidencia y procedencia;
- siete capas nuevas o ampliadas y cuatro tipos de nodo;
- foco, profundidad, límite de nodos y filtro de niveles;
- selector de distancia disponible después de aplicar filtros;
- flechas visibles en todas las aristas dirigidas y ausencia de flecha en la capa simétrica;
- dirección objeto digital → unidad archivística y etiquetas documentales en español;
- exportación JSON, CSV y GraphML con fechas serializadas;
- proyecto descartable fuera del repositorio y `project_data` sin acceso ni modificación.

La validación manual local quedó aprobada el 2026-08-05. Se confirmaron nueve nodos, doce aristas, cero inconsistencias y ningún truncamiento; `CAT-02` y `GRAPH-02` quedan cerrados en 0.77.0.
