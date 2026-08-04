# Archive Workbench 0.49.2 — actualización documental de pendientes

Esta versión no cambia el comportamiento de la aplicación ni la base de datos. Consolida el estado de pendientes, registra las validaciones ya realizadas y define la estrategia de pruebas para las próximas versiones.

## Actualizar desde 0.49.1

Detené Streamlit y ejecutá:

```bash
cd ~/projects/archive_app
source .venv/bin/activate

rm -rf /tmp/archive_workbench_v0.49.2

unzip -q \
  ~/Downloads/archive_workbench_v0.49.2.zip \
  -d /tmp

cp -a /tmp/archive_workbench_v0.49.2/. .

pip install -e ".[dev,extraction,streamlit,semantic,tiff]"
```

Comprobá:

```bash
python -c "import archive_workbench; print(archive_workbench.__version__)"
```

Debe devolver `0.49.2`.

**No ejecutes `db-upgrade`.** La revisión continúa en `0033_export_exchange_lifecycle`.

## Pruebas necesarias para este parche

```bash
pytest -q \
  tests/test_documentation.py \
  tests/test_packaging.py
```

Resultado esperado: `18 passed`.

Después comprobá que toda la suite recopila sin errores:

```bash
pytest --collect-only -q
```

Resultado esperado: `277 tests collected`.

No hace falta repetir pruebas manuales de migración, exportación, bundles o rebase: esta versión solo cambia documentación y estado de seguimiento.

## Consultar el estado vigente

```bash
sed -n '1,240p' docs/PENDIENTES_ACTIVOS.md
```

La migración 0027 figura como resuelta y validada. La recuperación asistida de linaje, el descubrimiento abierto del corpus y la desincronización visual de perfiles aparecen como pendientes separados y descritos sin ambigüedad.

Relación con “Pendientes y mejoras”: 0.49.2 convierte las validaciones ya realizadas en estado documental verificable y separa con claridad los pendientes todavía activos. No reabre la migración 0027 ni exige repetir pruebas manuales ya superadas.
