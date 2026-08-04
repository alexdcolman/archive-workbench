# Archive Workbench 0.47.0 — actualización y prueba

## Qué cambia

- El rebase puede reutilizar una candidata ya usada: quedan cubiertas las secuencias `A → B → A` y `A → B → A → B`. Antes de reutilizar un objeto OCR, el vínculo de la representación histórica se libera de forma auditada y su procedencia queda conservada en `historical_source_extracted_object_ids`.
- Las menciones se deduplican también entre revisiones textuales. La proyección es conservadora: usa tramos de texto iguales entre revisiones o una única aparición literal; si no hay correspondencia inequívoca, no inventa offsets.
- La búsqueda transversal muestra conflicto cuando el mismo fragmento vigente ya está vinculado a otra entidad, aunque la mención anterior pertenezca a una revisión textual previa. Administración informa `graph_duplicate_mention` para duplicados históricos ya existentes.
- El formulario de edición de menciones dentro de Revisión ya no puede enviarse con `Enter`. La prueba global ahora inspecciona cualquier llamada `.form(...)`, incluidas las creadas desde columnas o contenedores.
- El control de incorporación se llama **Estado que se asignará a las nuevas menciones**, para dejar claro que no filtra coincidencias ni menciones existentes.

No hay migración nueva. La base continúa en `0032_page_quality_assessments`.

La coincidencia semántica observada con puntaje `0.830` queda registrada como caso de calibración; esta versión no modifica umbrales ni modelos sin un conjunto de evaluación suficiente.

## Actualizar desde 0.46.0

Detené Streamlit y ejecutá:

```bash
cd ~/projects/archive_app
source .venv/bin/activate

rm -rf /tmp/archive_workbench_v0.47.0

unzip -q \
  ~/Downloads/archive_workbench_v0.47.0.zip \
  -d /tmp

cp -a /tmp/archive_workbench_v0.47.0/. .

pip install -e ".[dev,extraction,streamlit,semantic,tiff]"
```

Comprobá:

```bash
python -c "import archive_workbench; print(archive_workbench.__version__)"
```

Debe devolver:

```text
0.47.0
```

No ejecutes `db-upgrade`.

## Pruebas automatizadas

Primero, el bloque directamente afectado:

```bash
pytest \
  tests/test_candidate_review.py \
  tests/test_rebase_structural_metadata.py \
  tests/test_relations.py \
  tests/test_search.py \
  tests/test_graph.py \
  tests/test_project_admin.py \
  tests/test_ui_navigation.py \
  tests/test_documentation.py \
  tests/test_packaging.py
```

Después:

```bash
pytest
```

## Prueba en la app

Recreá el proyecto descartable para evitar arrastrar los duplicados producidos durante el diagnóstico de 0.46.0:

```bash
cd ~/projects/archive_app
source .venv/bin/activate

python scripts/create_rebase_validation_project.py --force
archive-workbench review-app project_data_rebase_validation
```

### Rebase repetido

1. En **Procesamiento → Selección canónica**, elegí `demo_surya_candidata` y aplicá el rebase como en la prueba de 0.45.0.
2. Volvé a la corrida `demo_ocr_anterior` y aplicá un segundo rebase.
3. Volvé otra vez a `demo_surya_candidata` y aplicá un tercero.

Los tres deben finalizar sin `IntegrityError`. En el historial deben quedar tres operaciones `rebase`; las representaciones anteriores permanecen retiradas y auditadas.

### Menciones entre revisiones

1. Creá la entidad `Destino comun`, buscá la coincidencia en páginas **Requiere revisión** e incorporala como **Aceptada**.
2. Desde Revisión agregá `Texto agregado. ` al comienzo del primer bloque.
3. Creá `Destino alternativo de prueba` y agregale el alias `Destino comun`.
4. Buscá coincidencias desde la segunda entidad.

Debe aparecer `Conflictos: 1`, no debe poder seleccionarse ni incorporarse y debe indicar que el fragmento ya está vinculado a `Destino comun`.

### Formularios

En **Revisión → Entidades**, cambiá estado, autoridad o nota de una mención y pulsá `Enter`: no debe guardarse. La modificación ocurre únicamente al pulsar **Guardar**.

## Relación con “Pendientes y mejoras”

La versión cierra el bloqueo de rebases repetidos y extiende la integridad de menciones al texto vigente, incluso cuando cambian revisión y offsets. También refuerza la política global de acciones explícitas y agrega diagnóstico para duplicados históricos sin alterar silenciosamente los datos existentes.
