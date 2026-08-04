# Archive Workbench 0.50.0 — reorganización documental

Esta versión reorganiza la documentación y recupera pendientes faltantes. No cambia el comportamiento de la aplicación ni la revisión de la base.

## Actualizar desde 0.49.2

Detené Streamlit y ejecutá:

```bash
cd ~/projects/archive_app
source .venv/bin/activate

rm -rf /tmp/archive_workbench_v0.50.0

unzip -q \
  ~/Downloads/archive_workbench_v0.50.0.zip \
  -d /tmp

cp -a /tmp/archive_workbench_v0.50.0/. .

pip install -e ".[dev,extraction,streamlit,semantic,tiff]"
```

Comprobá:

```bash
python -c "import archive_workbench; print(archive_workbench.__version__)"
```

Debe devolver:

```text
0.50.0
```

**No ejecutes `db-upgrade`.** La revisión continúa en `0033_export_exchange_lifecycle`.

## Pruebas necesarias

```bash
pytest -q \
  tests/test_documentation.py \
  tests/test_packaging.py
```

Resultado esperado:

```text
22 passed
```

Después:

```bash
pytest --collect-only -q
```

Resultado esperado: `281` pruebas recopiladas.

No hace falta repetir pruebas manuales de rebase, migraciones, exportación, backups o intercambio: esta versión solo modifica documentación, rutas y controles de consistencia documental.

## Verificación de la estructura

```bash
find docs -maxdepth 2 -type f | sort
find .assistant -maxdepth 1 -type f | sort
```

En la raíz de `docs/` debe existir únicamente:

```text
docs/HISTORIAL_DE_CAMBIOS.md
```

Los documentos vigentes deben estar en `docs/operativos/` y `docs/referencia/`; los documentos cerrados, en `docs/historico/`.

## Relación con los pendientes

Esta versión no cierra funciones de la aplicación: corrige el sistema de seguimiento para que ningún pendiente desaparezca ni vuelva a presentarse como nuevo después de haber sido validado. También incorpora de forma explícita las líneas futuras de interfaz, diccionarios, audiovisual, LLM, RAG, Docker y Drive.
