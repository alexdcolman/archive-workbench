# Archive Workbench 0.54.0 — catálogo y procesamiento más legibles, fase 4

Esta versión continúa `UX-01` en las dos primeras secciones del recorrido. Reduce la carga visual inicial y mueve información secundaria a desplegables, sin eliminar campos, filtros, perfiles, operaciones ni historiales. También coloca la búsqueda dentro de palabras junto a las opciones principales de combinación.

## Actualizar desde 0.53.0

Detené Streamlit y ejecutá:

```bash
cd ~/projects/archive_app
source .venv/bin/activate

rm -rf /tmp/archive_workbench_v0.54.0
mkdir -p /tmp/archive_workbench_v0.54.0

unzip -q \
  ~/Downloads/archive_workbench_v0.54.0.zip \
  -d /tmp/archive_workbench_v0.54.0

cp -a /tmp/archive_workbench_v0.54.0/. .

pip install -e ".[dev,extraction,streamlit,semantic,tiff]"
```

Comprobá:

```bash
python -c "import archive_workbench; print(archive_workbench.__version__)"
```

Debe devolver `0.54.0`.

**No ejecutes `db-upgrade`.** La revisión continúa en `0033_export_exchange_lifecycle`.

## Pruebas automatizadas

```bash
pytest -q \
  tests/test_ui_navigation.py \
  tests/test_catalog_management.py \
  tests/test_processing.py \
  tests/test_search.py \
  tests/test_documentation.py \
  tests/test_packaging.py

pytest --collect-only -q
```

El primer bloque debe terminar con `88 passed` y la recopilación completa debe informar `293 tests collected`.

## Validación manual

1. Abrí `project_data_rebase_validation`:

```bash
archive-workbench review-app project_data_rebase_validation
```

2. Entrá en `Buscar texto`. `Buscar también dentro de las palabras` debe aparecer inmediatamente debajo de `Cómo combinar las palabras`, antes de `Filtros opcionales`.
3. Activá y desactivá esa opción sin pulsar `Buscar`. No debe abrir filtros ni ejecutar una búsqueda.
4. Entrá en `Catálogo documental`. Al inicio deben verse `Resumen del catálogo`, `Crear la primera unidad del catálogo`, `Buscar en el catálogo` y `Filtros del catálogo`.
5. Abrí `Filtros del catálogo`: deben seguir disponibles `Nivel documental` y `Estado de descripción`. Cerralo sin cambiar valores.
6. Seleccioná una unidad existente. En la columna izquierda debe aparecer `Datos de la unidad`; al abrirlo deben verse hijas, objetos digitales y revisión interna.
7. Entrá en `Procesar documentos`. Debe aparecer `Resumen de avance` cerrado y conservarse las pestañas `Inventario`, `Ejecutar`, `Selección canónica` e `Historial`.
8. En `Ejecutar`, comprobá `Qué querés hacer`, `Documentos`, `Opciones avanzadas` y `Ejecutar tarea`.
9. Abrí `Opciones avanzadas`: debe seguir disponible `Crear una nueva versión aunque exista una equivalente`.
10. No crees unidades, no ejecutes tareas, no selecciones candidatas y no guardes cambios durante esta validación.

## Relación con los pendientes

La fase 4 simplifica Catálogo y Procesamiento y aplica el ajuste solicitado a la búsqueda dentro de palabras. `UX-01` continúa abierto para Revisión, Entidades y Grafo.
