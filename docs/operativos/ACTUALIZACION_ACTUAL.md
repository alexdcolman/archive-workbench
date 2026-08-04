# Actualización y prueba — Archive Workbench 0.71.2

Esta versión corrige únicamente el validador final de `DISC-01C`. La continuidad ya creada es válida: se originó en el candidato duplicado controlado de `Cuaderno del Delta`, que representa el mismo texto, objeto y revisión que el candidato original y pertenece al mismo grupo. El validador anterior exigía de manera innecesaria un identificador específico.

También registra `UX-03` como pendiente crítico: la interfaz de **Entidades y menciones** y **Descubrimiento abierto** debe reformularse completamente, conservando todas las funciones y contratos de datos. No se iniciará `DISC-01D` antes de resolver esa reformulación.

No hay migración ni acciones manuales que repetir.

## 1. Actualizar

```bash
cd ~/projects/archive_app
source .venv/bin/activate

rm -rf /tmp/archive_workbench_v0.71.2
mkdir -p /tmp/archive_workbench_v0.71.2

unzip -q \
  ~/Downloads/archive_workbench_v0.71.2.zip \
  -d /tmp/archive_workbench_v0.71.2

cp -a /tmp/archive_workbench_v0.71.2/. .

python -m pip install \
  --no-build-isolation \
  --no-deps \
  -e .

python -c "import archive_workbench; print(archive_workbench.__version__)"
```

Debe devolver `0.71.2`.

## 2. Base de datos

No ejecutar backup, `db-upgrade`, preparación, agrupamiento, separación ni continuidad. La revisión continúa en `0040_discovery_grouping_continuity` y el estado que ya existe es el que debe validarse.

## 3. Todas las pruebas relevantes y `collect-only`

```bash
pytest -q \
  tests/test_discovery_grouping.py \
  tests/test_documentation.py \
  tests/test_packaging.py && \
pytest --collect-only -q
```

Esperado: `50 passed` y `413 tests collected`.

## 4. Repetir solamente el validador final

```bash
python scripts/validate_open_discovery_disc01c.py \
  project_data_open_discovery_validation
```

Debe aceptar como origen controlado de la continuidad `duplicate_equivalent` y mostrar, como mínimo:

```text
grupos automáticos: 3
grupos manuales: 1
familia del grupo manual: actor
continuidades: 1
origen controlado de continuidad: duplicate_equivalent
candidatos totales: 17
corridas totales: 3
conteos canónicos: {'authority_records': 7, 'entity_mentions': 12, 'entity_relations': 3, 'discovery_decisions': 9, 'discovery_context_records': 4}
revisión: 0040_discovery_grouping_continuity
integridad: ok
claves foráneas: []
```

El número de grupos automáticos puede ser mayor que tres. En tu copia, `familia del grupo manual: actor` se conserva como evidencia de la confusión de interfaz registrada en `UX-03`; no modifica autoridades, menciones, relaciones, decisiones ni registros propios. No volver a abrir Streamlit ni repetir ninguna acción de `DISC-01C`. Con esta salida se cierra la fase y el próximo bloque es `UX-03`, no `DISC-01D`.
