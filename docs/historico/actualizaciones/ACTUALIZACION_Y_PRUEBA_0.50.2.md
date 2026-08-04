# Archive Workbench 0.50.2 — archivado de perfiles sin duplicación visual

Esta versión corrige únicamente la regresión que permanecía al archivar un perfil de exportación. Restaurar y eliminar ya habían quedado validados; no se repiten esas pruebas.

## Actualizar desde 0.50.1

Detené Streamlit y ejecutá:

```bash
cd ~/projects/archive_app
source .venv/bin/activate

rm -rf /tmp/archive_workbench_v0.50.2

unzip -q \
  ~/Downloads/archive_workbench_v0.50.2.zip \
  -d /tmp

cp -a /tmp/archive_workbench_v0.50.2/. .

pip install -e ".[dev,extraction,streamlit,semantic,tiff]"
```

Comprobá:

```bash
python -c "import archive_workbench; print(archive_workbench.__version__)"
```

Debe devolver `0.50.2`.

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
7. No hace falta restaurar, eliminar ni revisar otra vez el historial: esas operaciones ya pasaron.

## Relación con los pendientes

`BUG-01` permanece en `PENDIENTES_ACTIVOS.md` hasta completar esta validación manual. La corrección cambia el rerun completo por un rerun del fragmento de Exportar, que limpia su árbol anterior antes de montar la nueva selección.
