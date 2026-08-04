# Archive Workbench 0.52.0 — recorrido guiado y lenguaje claro, fase 2

Esta versión continúa `UX-01` sin ocultar funciones ni modificar la lógica de dominio. Cada sección puede mostrar una orientación breve con su objetivo, requisitos y paso habitual siguiente; la barra lateral permite avanzar o retroceder por el recorrido completo.

También reemplaza el léxico visible de “backup” por “copia de seguridad” en Administración, relega el comando técnico de restauración a un desplegable y explica los formatos de exportación en lenguaje común.

## Actualizar desde 0.51.0

Detené Streamlit y ejecutá:

```bash
cd ~/projects/archive_app
source .venv/bin/activate

rm -rf /tmp/archive_workbench_v0.52.0
mkdir -p /tmp/archive_workbench_v0.52.0

unzip -q \
  ~/Downloads/archive_workbench_v0.52.0.zip \
  -d /tmp/archive_workbench_v0.52.0

cp -a /tmp/archive_workbench_v0.52.0/. .

pip install -e ".[dev,extraction,streamlit,semantic,tiff]"
```

Comprobá:

```bash
python -c "import archive_workbench; print(archive_workbench.__version__)"
```

Debe devolver `0.52.0`.

**No ejecutes `db-upgrade`.** La revisión continúa en `0033_export_exchange_lifecycle`.

## Pruebas automatizadas

```bash
pytest -q \
  tests/test_ui_navigation.py \
  tests/test_operational.py \
  tests/test_corpus_export.py \
  tests/test_documentation.py \
  tests/test_packaging.py

# Resultado esperado: 68 passed

pytest --collect-only -q
# Resultado esperado: 290 tests collected
```

## Validación manual limitada a la interfaz nueva

1. Abrí `project_data_exchange_receiver` o cualquier proyecto descartable.
2. Entrá en una sección distinta de Inicio.
3. Verificá que la barra lateral indique la etapa y el número de paso, y que muestre `Sección anterior` y `Sección siguiente`.
4. Dejá activada `Mostrar orientación de la sección`: arriba de la pantalla debe aparecer un único panel con el objetivo. Abrí `Antes de empezar y qué sigue`.
5. Desactivá la orientación: el panel debe desaparecer y todas las funciones de la sección deben permanecer disponibles.
6. Entrá en `Administrar y recuperar` y verificá que la interfaz diga `copias de seguridad`, no `backups`. En Restaurar, el comando debe aparecer solamente al abrir `Ver comando técnico de restauración`.
7. Entrá en `Preparar corpus`: los formatos deben leerse como `JSONL · un registro por línea` y `CSV · tabla`.

No crees, restaures, elimines ni apliques nada durante esta validación.

## Relación con los pendientes

La fase 2 agrega recorrido contextual, navegación anterior/siguiente y divulgación progresiva de información técnica. `UX-01` continúa abierto para simplificar pantallas internas, revisar mensajes y completar el léxico de toda la aplicación.
