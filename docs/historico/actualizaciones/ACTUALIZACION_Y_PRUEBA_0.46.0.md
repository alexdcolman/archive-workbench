# Archive Workbench 0.46.0 — actualización y prueba

## Qué cambia

- La vista activa crea su contenedor dentro del propio fragmento. Esto elimina la frontera problemática entre un rerun local y la navegación completa que podía dejar oscurecida la vista anterior después de un rebase.
- Todos los formularios de la aplicación usan `enter_to_submit=False`: pulsar `Enter` no crea, guarda, aplica, elimina ni confirma nada.
- Revisión incorpora una pestaña **Atributos** que muestra el `current_attributes_json` completo del objeto seleccionado.
- Las sugerencias automáticas de entidades y menciones usan por defecto solamente páginas **Aprobadas**. En Entidades puede ampliarse explícitamente el filtro a otros estados.

No hay migración nueva. La base continúa en `0032_page_quality_assessments`.

## Actualizar desde 0.45.0

Detené Streamlit y ejecutá:

```bash
cd ~/projects/archive_app
source .venv/bin/activate

rm -rf /tmp/archive_workbench_v0.46.0

unzip -q \
  ~/Downloads/archive_workbench_v0.46.0.zip \
  -d /tmp

cp -a /tmp/archive_workbench_v0.46.0/. .

pip install -e ".[dev,extraction,streamlit,semantic,tiff]"
```

Comprobá:

```bash
python -c "import archive_workbench; print(archive_workbench.__version__)"
```

Debe devolver:

```text
0.46.0
```

No ejecutes `db-upgrade`.

## Pruebas automatizadas

Primero, el bloque afectado:

```bash
pytest \
  tests/test_ui_navigation.py \
  tests/test_relations.py \
  tests/test_search.py \
  tests/test_review.py \
  tests/test_documentation.py \
  tests/test_packaging.py
```

Después:

```bash
pytest
```

## Prueba en la app

Abrí el proyecto descartable:

```bash
archive-workbench review-app project_data_rebase_validation
```

1. En **Revisión → Atributos**, el primer objeto debe mostrar `classification`, `demo_attribute`, `shared_review`, `layout_role`, `source_*` y `rebased_from_object_ids`.
2. En **Entidades → Crear entidad**, escribí un nombre y pulsá `Enter`: no debe crearse nada. La creación ocurre únicamente con el botón.
3. Con la página en **Requiere revisión**, buscá coincidencias de `Destino comun` desde la entidad. Con el filtro predeterminado **Aprobado** debe devolver 0; al seleccionar explícitamente **Requiere revisión**, debe devolver 1.
4. Repetí la transición que producía el remanente: aplicar un rebase, permanecer en Procesamiento y abrir la página en Revisión. La vista anterior no debe quedar oscurecida.
