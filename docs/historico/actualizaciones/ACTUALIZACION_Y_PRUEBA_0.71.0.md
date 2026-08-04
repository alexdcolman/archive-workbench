# Actualización y prueba — Archive Workbench 0.71.0

Esta versión implementa `DISC-01C`: agrupamiento, deduplicación y continuidad textual de candidatos de descubrimiento abierto. Los grupos no fusionan candidatos ni procedencias. Separar un miembro conserva su historial, y crear continuidad genera un candidato nuevo sobre la revisión vigente sin ocultar el candidato obsoleto.

La migración nueva es:

```text
0040_discovery_grouping_continuity
```

La validación continúa sobre `project_data_open_discovery_validation`. Conserva el estado real ya confirmado: nueve decisiones, cuatro registros propios, doce menciones, siete autoridades y tres relaciones previas. No se repite el descubrimiento ni se corrige la decisión adicional append-only.

## 1. Actualizar el código

Detené Streamlit con `Ctrl+C` y ejecutá:

```bash
cd ~/projects/archive_app
source .venv/bin/activate

rm -rf /tmp/archive_workbench_v0.71.0
mkdir -p /tmp/archive_workbench_v0.71.0

unzip -q \
  ~/Downloads/archive_workbench_v0.71.0.zip \
  -d /tmp/archive_workbench_v0.71.0

cp -a /tmp/archive_workbench_v0.71.0/. .

python -m pip install \
  --no-build-isolation \
  --no-deps \
  -e .

python -c "import archive_workbench; print(archive_workbench.__version__)"
```

Debe devolver:

```text
0.71.0
```

## 2. Todas las pruebas relevantes, en un solo comando

```bash
pytest -q \
  tests/test_open_discovery.py \
  tests/test_discovery_grouping.py \
  tests/test_database.py \
  tests/test_analysis_quality.py \
  tests/test_ui_navigation.py \
  tests/test_relations.py \
  tests/test_search.py \
  tests/test_documentation.py \
  tests/test_packaging.py && \
pytest --collect-only -q
```

Esperado:

```text
159 passed
412 tests recopilados
```

Las advertencias del adaptador de fechas de SQLite bajo Python 3.12 no representan fallos. No se ejecutó nuevamente la suite monolítica completa.

## 3. Respaldar y migrar `project_data`

Esta versión sí contiene migración. Con Streamlit cerrado:

```bash
archive-workbench project-backup-create \
  project_data \
  --created-by alex \
  --note "Antes de migrar project_data a Archive Workbench 0.71.0"

archive-workbench db-upgrade project_data
archive-workbench db-status project_data
```

Debe quedar en:

```text
0040_discovery_grouping_continuity
```

Abrí la base principal y comprobá solamente que los documentos y las pruebas OCR continúan visibles:

```bash
archive-workbench review-app project_data
```

No ejecutes descubrimiento, agrupamiento ni continuidad allí. Detené Streamlit con `Ctrl+C`.

## 4. Respaldar y migrar la copia de validación existente

No recrees la copia y no vuelvas a ejecutar el descubrimiento.

```bash
archive-workbench project-backup-create \
  project_data_open_discovery_validation \
  --created-by alex \
  --note "Antes de migrar la copia de DISC-01B a Archive Workbench 0.71.0"

archive-workbench db-upgrade \
  project_data_open_discovery_validation

archive-workbench db-status \
  project_data_open_discovery_validation
```

También debe quedar en:

```text
0040_discovery_grouping_continuity
```

## 5. Preparar el escenario de `DISC-01C`

```bash
python scripts/prepare_open_discovery_grouping_validation.py \
  project_data_open_discovery_validation
```

Debe informar:

```text
Revisión: 0040_discovery_grouping_continuity
Candidatos totales después de preparar: 16
No se creó ningún grupo, pertenencia, acción de grupo ni continuidad.
```

La preparación:

- conserva las nueve decisiones y los cuatro registros propios existentes;
- agrega una segunda corrida controlada con tres candidatos repetidos;
- crea una variante normalizada de `Dra. Valentina Orbe`;
- agrega un prefacio al objeto controlado para volver obsoletos sus candidatos anteriores;
- no crea grupos ni continuidad todavía.

Prepará identificadores para reconocer los candidatos exactos en la interfaz:

```bash
VALIDATION_FILE="project_data_open_discovery_validation/validation/disc01c.json"

WORK_ORIGINAL_ID="$(python -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["candidate_ids"]["work_original"])' \
  "$VALIDATION_FILE")"

MANUAL_EVENT_ID="$(python -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["candidate_ids"]["manual_event"])' \
  "$VALIDATION_FILE")"

ADDITIONAL_ID="$(python -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["additional_candidate_id"])' \
  "$VALIDATION_FILE")"

printf 'WORK_ORIGINAL_ID=%s\nMANUAL_EVENT_ID=%s\nADDITIONAL_ID=%s\n' \
  "$WORK_ORIGINAL_ID" "$MANUAL_EVENT_ID" "$ADDITIONAL_ID"
```

`ADDITIONAL_ID` debe corresponder al candidato accidental `manifestación`.

## 6. Proponer grupos y comprobar procedencias

Abrí:

```bash
archive-workbench review-app \
  project_data_open_discovery_validation
```

Entrá en:

```text
Entidades y menciones
→ Descubrimiento abierto
→ Agrupar candidatos y mantener continuidad
→ Agrupamiento y duplicados
```

Los tres paneles son secundarios, quedan cerrados inicialmente y deben conservar su apertura durante los reruns.

Pulsá **Actualizar grupos propuestos** una sola vez. La salida debe incluir al menos tres grupos nuevos y seis pertenencias nuevas para el escenario controlado. Si el corpus ya contiene otros textos repetidos, puede proponer grupos automáticos adicionales; eso no invalida la prueba.

Comprobá estos grupos controlados:

- `Ministerio de Archivos Imaginarios`: coincidencia exacta entre dos corridas;
- `Dra. Valentina Orbe` y `Dra Valentina Orbe`: coincidencia normalizada;
- `Cuaderno del Delta`: coincidencia exacta entre dos corridas.

Cada grupo debe conservar los identificadores de candidato, las corridas, archivo, página, revisión y estado vigente u obsoleto. No debe fusionar ni borrar filas históricas.

## 7. Crear y separar un grupo manual

Dentro de **Agrupamiento y duplicados**, abrí **Crear grupo manual**.

Seleccioná exactamente:

- `operativo Horizonte`, cuyo identificador comienza con los primeros ocho caracteres de `MANUAL_EVENT_ID`;
- `manifestación`, cuyo identificador comienza con los primeros ocho caracteres de `ADDITIONAL_ID`.

Usá:

```text
Etiqueta del grupo: Acontecimientos controlados DISC-01C
Familia del grupo: Acontecimiento
Fundamento: Validación DISC-01C agrupamiento manual.
```

Pulsá **Crear grupo manual** una sola vez.

En el selector **Grupo**, elegí `Acontecimientos controlados DISC-01C`. En **Candidato que debe separarse del grupo**, seleccioná `manifestación` y usá:

```text
Fundamento de la separación: Validación DISC-01C separación manual.
```

Pulsá **Separar candidato** una sola vez.

El grupo debe seguir existiendo. `operativo Horizonte` debe quedar activo y `manifestación` debe aparecer como separado. No vuelvas a pulsar **Actualizar grupos propuestos**: una separación manual no debe ser revertida automáticamente.

## 8. Crear continuidad para el candidato obsoleto

Abrí **Continuidad después de editar texto**.

En **Candidato obsoleto**, seleccioná `Cuaderno del Delta` cuyo identificador comienza con los primeros ocho caracteres de `WORK_ORIGINAL_ID`. La opción muestra también el identificador corto de la corrida para distinguir candidatos con el mismo texto.

Usá:

```text
Método: Proyección exacta única
```

Pulsá **Crear continuidad** una sola vez.

Debe indicar una revisión textual nueva y offsets nuevos. El candidato histórico debe continuar visible como obsoleto y debe existir un candidato nuevo vigente dentro del mismo grupo de `Cuaderno del Delta`.

No registres decisiones nuevas, no crees autoridades, menciones o relaciones y no ejecutes nuevamente el descubrimiento. Detené Streamlit con `Ctrl+C`.

## 9. Comprobar desde terminal

```bash
archive-workbench discovery-groups \
  project_data_open_discovery_validation \
  --include-removed

archive-workbench discovery-continuities \
  project_data_open_discovery_validation
```

La salida debe incluir:

- al menos tres grupos automáticos controlados;
- un grupo manual;
- `manifestación` como pertenencia separada;
- una continuidad mediante `exact_projection`;
- candidatos obsoletos todavía visibles;
- `Total: 1 continuidades`.

## 10. Verificación final

```bash
python scripts/validate_open_discovery_disc01c.py \
  project_data_open_discovery_validation
```

Debe mostrar, como mínimo:

```text
grupos automáticos: 3
grupos manuales: 1
continuidades: 1
candidatos totales: 17
corridas totales: 3
conteos canónicos: {'authority_records': 7, 'entity_mentions': 12, 'entity_relations': 3, 'discovery_decisions': 9, 'discovery_context_records': 4}
revisión: 0040_discovery_grouping_continuity
integridad: ok
claves foráneas: []
```

`grupos automáticos` puede ser mayor que tres si existían otras coincidencias legítimas en los documentos aprobados; el validador comprueba de manera estricta los tres grupos controlados y reporta por separado los adicionales. Deben conservarse exactamente los conteos canónicos anteriores a la preparación.

`DISC-01C` queda pendiente únicamente de esta validación manual. Después corresponde registrar su cierre e implementar `DISC-01D`.
