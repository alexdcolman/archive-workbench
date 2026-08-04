# Actualización y prueba — Archive Workbench 0.71.1

Esta versión corrige el fallo de Streamlit ocurrido después de pulsar **Crear grupo manual**. El grupo `Acontecimientos controlados DISC-01C` ya quedó persistido: la transacción se confirmó antes de que fallara la asignación visual. No debe crearse otra vez.

La corrección usa una clave de selección pendiente y aplica el valor en el rerun siguiente, antes de instanciar el selector. No hay migración.

## 1. Actualizar

```bash
cd ~/projects/archive_app
source .venv/bin/activate

rm -rf /tmp/archive_workbench_v0.71.1
mkdir -p /tmp/archive_workbench_v0.71.1

unzip -q \
  ~/Downloads/archive_workbench_v0.71.1.zip \
  -d /tmp/archive_workbench_v0.71.1

cp -a /tmp/archive_workbench_v0.71.1/. .

python -m pip install \
  --no-build-isolation \
  --no-deps \
  -e .

python -c "import archive_workbench; print(archive_workbench.__version__)"
```

Debe devolver `0.71.1`.

## 2. Base de datos

No ejecutar backup, `db-upgrade`, preparación ni agrupamiento automático. La revisión continúa en `0040_discovery_grouping_continuity`.

## 3. Pruebas automatizadas

```bash
pytest -q \
  tests/test_discovery_grouping.py \
  tests/test_ui_navigation.py \
  tests/test_documentation.py \
  tests/test_packaging.py && \
pytest --collect-only -q
```

Esperado: `111 passed` y `413 tests collected`.

## 4. Confirmar que el grupo ya existe

```bash
archive-workbench discovery-groups \
  project_data_open_discovery_validation \
  --include-removed
```

Debe aparecer `Acontecimientos controlados DISC-01C`, con `operativo Horizonte` y `manifestación` como integrantes activos. No crear otro grupo manual y no pulsar **Actualizar grupos propuestos**.

## 5. Continuar la validación

Abrir:

```bash
archive-workbench review-app \
  project_data_open_discovery_validation
```

Entrar en **Entidades y menciones → Descubrimiento abierto → Agrupar candidatos y mantener continuidad → Agrupamiento y duplicados**.

Seleccionar `Acontecimientos controlados DISC-01C`. Separar `manifestación` con el fundamento:

```text
Validación DISC-01C separación manual.
```

Pulsar **Separar candidato** una sola vez. El grupo debe conservar `operativo Horizonte` como activo y mostrar `manifestación` como separado.

Después abrir **Continuidad después de editar texto**, seleccionar el `Cuaderno del Delta` obsoleto indicado por la preparación, elegir **Proyección exacta única** y pulsar **Crear continuidad** una sola vez.

No registrar decisiones, no crear autoridades, menciones ni relaciones y no volver a crear el grupo manual. Detener Streamlit.

## 6. Comprobación final

```bash
archive-workbench discovery-groups \
  project_data_open_discovery_validation \
  --include-removed

archive-workbench discovery-continuities \
  project_data_open_discovery_validation

python scripts/validate_open_discovery_disc01c.py \
  project_data_open_discovery_validation
```

La validación debe incluir al menos tres grupos automáticos, un grupo manual, una continuidad, 17 candidatos, tres corridas, revisión `0040_discovery_grouping_continuity`, integridad `ok` y claves foráneas vacías. Los conteos canónicos deben seguir siendo siete autoridades, doce menciones, tres relaciones, nueve decisiones y cuatro registros propios.
