# Archive Workbench 0.55.0 — revisión, entidades y relaciones más legibles, fase 5

Esta versión continúa `UX-01` en las tres pantallas centrales de análisis manual. Reduce la carga visual inicial y reemplaza etiquetas técnicas en el recorrido principal, sin eliminar controles ni cambiar datos, revisiones, menciones, relaciones o algoritmos.

## Actualizar desde 0.54.0

Detené Streamlit y ejecutá:

```bash
cd ~/projects/archive_app
source .venv/bin/activate

rm -rf /tmp/archive_workbench_v0.55.0
mkdir -p /tmp/archive_workbench_v0.55.0

unzip -q \
  ~/Downloads/archive_workbench_v0.55.0.zip \
  -d /tmp/archive_workbench_v0.55.0

cp -a /tmp/archive_workbench_v0.55.0/. .

pip install -e ".[dev,extraction,streamlit,semantic,tiff]"
```

Comprobá:

```bash
python -c "import archive_workbench; print(archive_workbench.__version__)"
```

Debe devolver `0.55.0`.

**No ejecutes `db-upgrade`.** La revisión continúa en `0033_export_exchange_lifecycle`.

## Pruebas automatizadas

```bash
pytest -q \
  tests/test_ui_navigation.py \
  tests/test_review.py \
  tests/test_relations.py \
  tests/test_graph.py \
  tests/test_documentation.py \
  tests/test_packaging.py

pytest --collect-only -q
```

El primer bloque debe terminar con `84 passed`. La recopilación completa debe informar `296 tests collected`.

## Validación manual

1. Abrí el proyecto descartable:

```bash
archive-workbench review-app project_data_rebase_validation
```

2. Entrá en `Revisar documentos`. En la barra lateral deben mantenerse visibles `Documento`, los botones de página y `Página física`.
3. Comprobá que estén cerrados inicialmente `Opciones de visualización`, `Resumen del documento`, `Herramientas de la capa editable` y `Estado de revisión de la página`.
4. Abrí cada desplegable y verificá que conserve, respectivamente, las cajas OCR y objetos eliminados; los contadores del documento; la exportación editable; y el estado y nota de página. Cerralo sin modificar ni exportar nada.
5. En el área principal, comprobá que aparezca `Deshacer o rehacer cambios` cerrado y que el panel derecho se titule `Revisar objetos de la página`.
6. Seleccioná un objeto y abrí `Datos del objeto seleccionado`. Deben aparecer orden, revisión, estado, revisión humana y parte interna.
7. Comprobá que sigan disponibles las pestañas `Editar texto`, `Orden y estructura`, `Anotaciones`, `Datos adicionales`, `Menciones`, `Historial` y `Agregar objeto`. No guardes cambios.
8. Entrá en `Entidades y menciones`. Deben aparecer `Qué es una entidad`, la búsqueda general y `Filtros de entidades` cerrado.
9. Abrí los filtros y verificá `Tipos de entidad`, `Incluir entidades dadas de baja` y el filtro temporal. Cerralo sin modificar valores.
10. Seleccioná una entidad. Deben aparecer `Resumen de la entidad` y las pestañas `Datos de la entidad`, `Nombres alternativos`, `Menciones en documentos`, `Relaciones` e `Historial`.
11. En `Menciones en documentos`, verificá `Encontrar nuevas menciones en el corpus`, `Opciones de búsqueda` y `Menciones ya vinculadas`. No busques ni incorpores menciones.
12. Entrá en `Explorar relaciones`. La pantalla debe titularse `Mapa de relaciones` y mostrar cerrados `Cómo se construye este mapa`, `Filtros del mapa` y `Resumen del mapa`.
13. Abrí `Filtros del mapa` y verificá que continúen todos los filtros, incluido `Tipos de vínculo`. No pulses `Aplicar filtros`.
14. Comprobá las pestañas `Explorar`, `Revisar alertas` y `Exportar datos`.
15. En `Explorar`, abrí `Cómo leer los elementos y vínculos`. Al seleccionar un elemento o vínculo, los identificadores y el peso deben aparecer solo dentro de `Detalles técnicos`.
16. No edites texto, estados, menciones, relaciones, filtros ni exportaciones durante esta validación.

## Relación con los pendientes

La fase 5 simplifica Revisión, Entidades y el mapa de relaciones y deja los datos técnicos disponibles bajo demanda. `UX-01` continúa abierto para revisar mensajes, densidad interna y recorridos de las pantallas restantes antes de su cierre general.
