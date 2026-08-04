# Actualización y prueba — Archive Workbench 0.68.1

Esta versión registra el cierre manual de `EX-01`, retira el bloque de los pendientes activos y fija el plan completo de `DISC-01`. No cambia la lógica de la aplicación ni el esquema de base.

La próxima fase funcional será `DISC-01A`: perfiles, corridas y candidatos trazables para descubrimiento abierto, con un proveedor local determinista y sin creación automática de autoridades, menciones o relaciones.

## 1. Actualizar el código

Detené Streamlit con `Ctrl+C` y ejecutá:

```bash
cd ~/projects/archive_app
source .venv/bin/activate

rm -rf /tmp/archive_workbench_v0.68.1
mkdir -p /tmp/archive_workbench_v0.68.1

unzip -q \
  ~/Downloads/archive_workbench_v0.68.1.zip \
  -d /tmp/archive_workbench_v0.68.1

cp -a /tmp/archive_workbench_v0.68.1/. .

pip install -e ".[dev,extraction,streamlit,semantic,tiff]"
```

Comprobá:

```bash
python -c "import archive_workbench; print(archive_workbench.__version__)"
```

Debe devolver:

```text
0.68.1
```

## 2. Base de datos

Esta versión **no contiene migración**. No ejecutes `db-upgrade`.

La revisión continúa siendo:

```text
0037_exchange_state_adoptions
```

`project_data` ya fue respaldada, migrada y comprobada en 0.68.0. No repitas esa migración ni las pruebas de `EX-01`.

## 3. Pruebas automatizadas

Ejecutá:

```bash
pytest -q \
  tests/test_documentation.py \
  tests/test_packaging.py
```

Esperado:

```text
42 passed
```

Después:

```bash
pytest --collect-only -q
```

Debe recopilar:

```text
386 tests
```

En construcción pasaron esas pruebas y se construyó correctamente el wheel `archive_workbench-0.68.1-py3-none-any.whl`. No se ejecutó nuevamente la suite monolítica completa.

## 4. Validación manual

No hay prueba manual de interfaz ni de base en esta versión. Comprobados los dos bloques anteriores, corresponde implementar `DISC-01A` sin repetir ninguna fase de `EX-01`.
