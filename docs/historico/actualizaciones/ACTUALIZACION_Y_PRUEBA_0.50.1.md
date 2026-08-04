# Archive Workbench 0.50.1 — sincronización visual de perfiles de exportación

Esta versión corrige la duplicación y desincronización visual que podía aparecer después de guardar, archivar, restaurar o eliminar un perfil de exportación. No modifica la base ni el contenido de los perfiles o exportaciones.

## Actualizar desde 0.50.0

Detené Streamlit y ejecutá:

```bash
cd ~/projects/archive_app
source .venv/bin/activate

rm -rf /tmp/archive_workbench_v0.50.1

unzip -q \
  ~/Downloads/archive_workbench_v0.50.1.zip \
  -d /tmp

cp -a /tmp/archive_workbench_v0.50.1/. .

pip install -e ".[dev,extraction,streamlit,semantic,tiff]"
```

Comprobá:

```bash
python -c "import archive_workbench; print(archive_workbench.__version__)"
```

Debe devolver:

```text
0.50.1
```

**No ejecutes `db-upgrade`.** La revisión continúa en `0033_export_exchange_lifecycle`.

## Pruebas necesarias

```bash
pytest -q \
  tests/test_ui_navigation.py \
  tests/test_corpus_export.py \
  tests/test_documentation.py \
  tests/test_packaging.py
```

Después:

```bash
pytest --collect-only -q
```

## Validación manual

Usá únicamente un proyecto descartable que ya tenga al menos un perfil de exportación.

1. Abrí `Exportar` y seleccioná un perfil existente.
2. Archivá el perfil con su confirmación explícita.
3. Activá `Mostrar perfiles archivados`, seleccioná el perfil y restauralo.
4. Archivá el perfil nuevamente y eliminalo definitivamente.
5. Después de cada acción, verificá en ese mismo momento que exista un solo selector y un solo formulario, y que ambos correspondan a la misma selección.
6. Al eliminarlo, el selector debe quedar en `Crear un perfil nuevo` y solo debe mostrarse ese formulario.
7. El historial y los archivos exportados deben conservarse.

No hace falta repetir la creación de exportaciones, la comprobación de hashes ni otras pruebas ya validadas.

## Relación con los pendientes

Esta versión cierra `BUG-01`: fuerza una reconstrucción completa y una identidad nueva del selector después de cada acción de ciclo de vida. La simplificación general de la interfaz continúa como `UX-01`.
