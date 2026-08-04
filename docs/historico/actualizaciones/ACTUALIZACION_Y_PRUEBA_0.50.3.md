# Archive Workbench 0.50.3 — archivado procesado antes de reconstruir Exportar

La duplicación visual persistía porque 0.50.1 y 0.50.2 modificaban la base y solicitaban otro rerun mientras el fragmento todavía estaba renderizando el formulario anterior. Esta versión cambia la secuencia: el botón solo encola la operación; el rerun ordinario del formulario la ejecuta al comienzo de la vista siguiente, antes de crear selector, pestañas o formularios.

## Actualizar desde 0.50.2

Detené Streamlit y ejecutá:

```bash
cd ~/projects/archive_app
source .venv/bin/activate

rm -rf /tmp/archive_workbench_v0.50.3

unzip -q \
  ~/Downloads/archive_workbench_v0.50.3.zip \
  -d /tmp

cp -a /tmp/archive_workbench_v0.50.3/. .

pip install -e ".[dev,extraction,streamlit,semantic,tiff]"
```

Comprobá:

```bash
python -c "import archive_workbench; print(archive_workbench.__version__)"
```

Debe devolver `0.50.3`.

**No ejecutes `db-upgrade`.** La revisión continúa en `0033_export_exchange_lifecycle`.

## Pruebas automatizadas

```bash
pytest -q \
  tests/test_ui_navigation.py \
  tests/test_corpus_export.py \
  tests/test_documentation.py \
  tests/test_packaging.py

pytest --collect-only -q
```

## Validación manual única

1. Abrí `project_data_rebase_validation`.
2. Entrá en `Exportar` y activá `Mostrar perfiles archivados`.
3. Seleccioná o creá un perfil activo descartable.
4. Marcá `Confirmo que deseo archivar este perfil`.
5. Pulsá `Archivar perfil`.
6. Inmediatamente después del clic, verificá que haya un solo selector de perfil, un solo bloque de pestañas y un solo formulario.
7. No repitas restaurar, eliminar ni revisar el historial: esas operaciones ya fueron validadas.

## Relación con los pendientes

`BUG-01` permanece activo hasta esta validación. La corrección elimina el rerun anidado a mitad del render y procesa el archivado antes de construir el árbol visual siguiente.
