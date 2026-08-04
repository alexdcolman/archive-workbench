# Archive Workbench 0.51.0 — orientación y lenguaje claro, fase 1

Esta versión inicia `UX-01` sin eliminar funciones ni cambiar la lógica de dominio. La navegación lateral se expresa como tareas, cada sección explica su propósito y la pantalla de intercambio reemplaza los principales anglicismos visibles por términos comprensibles en español.

También registra como resuelto y validado el problema de duplicación visual al archivar perfiles de exportación.

## Actualizar desde 0.50.3

Detené Streamlit y ejecutá:

```bash
cd ~/projects/archive_app
source .venv/bin/activate

rm -rf /tmp/archive_workbench_v0.51.0
mkdir -p /tmp/archive_workbench_v0.51.0

unzip -q \
  ~/Downloads/archive_workbench_v0.51.0.zip \
  -d /tmp/archive_workbench_v0.51.0

cp -a /tmp/archive_workbench_v0.51.0/. .

pip install -e ".[dev,extraction,streamlit,semantic,tiff]"
```

Comprobá:

```bash
python -c "import archive_workbench; print(archive_workbench.__version__)"
```

Debe devolver `0.51.0`.

**No ejecutes `db-upgrade`.** La revisión continúa en `0033_export_exchange_lifecycle`.

## Pruebas automatizadas

```bash
pytest -q \
  tests/test_operational.py \
  tests/test_ui_navigation.py \
  tests/test_documentation.py \
  tests/test_packaging.py

# Resultado esperado: 57 passed

pytest --collect-only -q
# Resultado esperado: 287 tests collected
```

## Validación manual limitada a la interfaz nueva

1. Abrí cualquier proyecto descartable con `archive-workbench review-app <proyecto>`.
2. En la barra lateral, verificá que el control se llame `Sección`, que las opciones estén formuladas como tareas y que debajo aparezca una explicación breve de la sección elegida.
3. Entrá en `Intercambiar cambios`.
4. Sin cargar ni aplicar ningún archivo, verificá que las acciones principales digan `Paquete de intercambio`, `Simular evaluación`, `Paquete recibido`, `Aplicar paquete` y `Archivar paquete`.
5. Comprobá que los estados se lean en español y que los códigos internos aparezcan solamente dentro de `Detalles técnicos`.

No repitas pruebas de perfiles de exportación: la corrección visual ya fue validada en 0.50.3.

## Relación con los pendientes

La versión cierra el bug visual de perfiles e inicia `UX-01` con orientación contextual y léxico comprensible. La simplificación general de recorridos y opciones avanzadas continúa abierta.
