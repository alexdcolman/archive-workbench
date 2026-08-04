# Actualización y prueba — Archive Workbench 0.69.2

Esta versión corrige la validación de `DISC-01A`: la corrida recorre todas las páginas aprobadas, de modo que puede encontrar candidatos adicionales fuera del objeto controlado. La comprobación valida los siete candidatos controlados sin exigir que sean los únicos de la corrida.

## Actualizar

```bash
cd ~/projects/archive_app
source .venv/bin/activate
rm -rf /tmp/archive_workbench_v0.69.2
mkdir -p /tmp/archive_workbench_v0.69.2
unzip -q ~/Downloads/archive_workbench_v0.69.2.zip -d /tmp/archive_workbench_v0.69.2
cp -a /tmp/archive_workbench_v0.69.2/. .
python -m pip install --no-build-isolation --no-deps -e .
python -c "import archive_workbench; print(archive_workbench.__version__)"
```

Debe devolver `0.69.2`.

No contiene migración. No ejecutes `db-upgrade`, no recrees la copia y no repitas la corrida.

## Pruebas

```bash
pytest -q tests/test_documentation.py tests/test_packaging.py
pytest --collect-only -q
```

## Validación corregida

```bash
python scripts/validate_open_discovery_disc01a.py \
  project_data_open_discovery_validation
```

Debe mostrar `candidatos controlados: 7`, la distribución esperada, revisión `0038_open_discovery`, integridad `ok` y claves foráneas vacías. El total puede ser mayor; en la corrida ya realizada debe ser `13`.
