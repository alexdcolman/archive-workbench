# Archive Workbench 0.56.0 — legibilidad final de datos, trabajo y exportación, fase 6

Esta versión realiza la revisión final prevista en `UX-01`. Corrige el recorte de “Sin revisar” en los datos del objeto seleccionado y reduce la densidad de Organización del trabajo y Exportar, sin retirar funciones ni modificar datos.

## Actualizar desde 0.55.0

Detené Streamlit y ejecutá:

```bash
cd ~/projects/archive_app
source .venv/bin/activate

rm -rf /tmp/archive_workbench_v0.56.0
mkdir -p /tmp/archive_workbench_v0.56.0

unzip -q \
  ~/Downloads/archive_workbench_v0.56.0.zip \
  -d /tmp/archive_workbench_v0.56.0

cp -a /tmp/archive_workbench_v0.56.0/. .

pip install -e ".[dev,extraction,streamlit,semantic,tiff]"
```

Comprobá:

```bash
python -c "import archive_workbench; print(archive_workbench.__version__)"
```

Debe devolver `0.56.0`.

**No ejecutes `db-upgrade`.** La revisión continúa en `0033_export_exchange_lifecycle`.

## Pruebas automatizadas

```bash
pytest -q \
  tests/test_ui_navigation.py \
  tests/test_review.py \
  tests/test_work.py \
  tests/test_corpus_export.py \
  tests/test_documentation.py \
  tests/test_packaging.py

pytest --collect-only -q
```

El primer bloque debe terminar con `81 passed`. La recopilación completa debe informar `298 tests collected`.

## Validación manual

1. Abrí el proyecto descartable:

```bash
archive-workbench review-app project_data_rebase_validation
```

2. Entrá en `Revisar documentos`, seleccioná un objeto y abrí `Datos del objeto seleccionado`.
3. Comprobá que Orden, Revisión, Estado y Revisión humana aparezcan en dos filas de dos tarjetas.
4. El valor de Revisión humana debe verse completo —por ejemplo, `Sin revisar`—, sin `Sin re…` ni puntos suspensivos. Estado debe mostrarse como `Activo` o `Eliminado`, no como el código interno en inglés.
5. No edites ni guardes el objeto.
6. Entrá en `Organizar trabajo`. Deben aparecer `Cómo se organiza el trabajo` y las pestañas `Resumen`, `Asignar y administrar`, `Mi trabajo` y `Revisión cruzada`.
7. En `Resumen`, los cuatro indicadores deben verse en dos filas y sin textos recortados. Abrí `Carga por responsable` y `Avance de los documentos`; comprobá que las tablas sigan presentes y cerralas.
8. Entrá en `Asignar y administrar`. Abrí `Filtros de asignaciones` y comprobá que continúen Responsable, Estado y Tipo de tarea. No crees asignaciones ni guardes cambios.
9. Entrá en `Preparar corpus`. Deben aparecer `Cómo preparar una exportación`, `Perfil de exportación` y las pestañas `Configurar perfil`, `Revisar contenido`, `Crear archivo` e `Historial`.
10. En `Revisar contenido`, si existe un perfil activo, comprobá que el identificador de cada registro aparezca solo dentro de `Detalles técnicos del registro`.
11. En `Crear archivo`, comprobá la etiqueta `Nombre o ruta del archivo dentro del proyecto`. No crees una exportación.
12. En `Historial`, comprobá que las huellas del archivo y del estado del corpus aparezcan solo dentro de `Detalles técnicos de la exportación`.
13. No crees asignaciones, no guardes cambios y no generes archivos durante esta validación.

## Relación con los pendientes

La fase 6 corrige el recorte informado y completa la revisión de legibilidad prevista en `UX-01`. La tarea podrá cerrarse después de esta validación manual, manteniendo las mejoras futuras de funciones concretas como pendientes independientes.
