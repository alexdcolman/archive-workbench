# Archive Workbench 0.53.0 — búsquedas más simples, fase 3

Esta versión continúa `UX-01` en las pantallas de búsqueda. La consulta principal queda visible y los filtros, el mantenimiento del índice y la configuración técnica pasan a desplegables. No se elimina ni cambia ningún filtro, perfil o parámetro.

## Actualizar desde 0.52.0

Detené Streamlit y ejecutá:

```bash
cd ~/projects/archive_app
source .venv/bin/activate

rm -rf /tmp/archive_workbench_v0.53.0
mkdir -p /tmp/archive_workbench_v0.53.0

unzip -q \
  ~/Downloads/archive_workbench_v0.53.0.zip \
  -d /tmp/archive_workbench_v0.53.0

cp -a /tmp/archive_workbench_v0.53.0/. .

pip install -e ".[dev,extraction,streamlit,semantic,tiff]"
```

Comprobá:

```bash
python -c "import archive_workbench; print(archive_workbench.__version__)"
```

Debe devolver `0.53.0`.

**No ejecutes `db-upgrade`.** La revisión continúa en `0033_export_exchange_lifecycle`.

## Pruebas automatizadas

```bash
pytest -q \
  tests/test_ui_navigation.py \
  tests/test_search.py \
  tests/test_semantic_search.py \
  tests/test_documentation.py \
  tests/test_packaging.py

pytest --collect-only -q
```

El primer bloque debe terminar sin fallos y la recopilación completa debe informar `292 tests collected`.

## Validación manual limitada a las búsquedas

1. Abrí `project_data_rebase_validation` o cualquier proyecto descartable.
2. Entrá en `Buscar texto`: deben quedar visibles `Qué querés encontrar`, `Cómo combinar las palabras` y el botón `Buscar`.
3. Abrí `Filtros opcionales`: deben seguir presentes campos, documentos, tipos, estados, etiquetas, fechas, objetos dados de baja, búsqueda parcial y límite.
4. Cerrá los filtros y comprobá que la pantalla principal vuelva a quedar breve.
5. Abrí `Mantenimiento del índice de texto`: no reconstruyas el índice; verificá que la acción técnica esté allí.
6. Entrá en `Buscar por significado`: el estado técnico debe estar cerrado y la pestaña debe llamarse `Preparar búsqueda`.
7. Abrí `Opciones de búsqueda`: verificá similitud mínima, máximo de resultados, procesador/placa NVIDIA y fechas.
8. En `Preparar búsqueda`, abrí `Contenido incluido` y `Configuración técnica del índice`; no guardes ni reconstruyas.

No cambies perfiles, índices ni datos durante esta validación.

## Relación con los pendientes

La fase 3 reduce la carga visual de las búsquedas y conserva todas sus capacidades. `UX-01` continúa abierto para revisar catálogo, procesamiento, revisión, entidades y grafo.
