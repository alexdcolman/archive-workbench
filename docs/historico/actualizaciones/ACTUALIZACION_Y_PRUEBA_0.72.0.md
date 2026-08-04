# Actualización y prueba — Archive Workbench 0.72.0

Esta versión cierra `DISC-01C`, resuelve `UX-03` y ordena los dos registros documentales que habían quedado mezclados. No cambia contratos de datos ni agrega migraciones.

## 1. Actualizar sin mover ni eliminar archivos locales

```bash
cd ~/projects/archive_app
source .venv/bin/activate

TMP_DIR="$(mktemp -d)"
unzip -q \
  ~/Downloads/archive_workbench_v0.72.0.zip \
  -d "$TMP_DIR"

cp -a "$TMP_DIR"/. .

python -m pip install \
  --no-build-isolation \
  --no-deps \
  -e .

python -c "import archive_workbench; print(archive_workbench.__version__)"
```

Debe devolver `0.72.0`. La copia no se mueve ni se elimina: `project_data`, `.dev`, `.assistant` y los demás archivos locales existentes permanecen en su lugar.

## 2. Base de datos

**No hay migración.** La revisión requerida continúa en `0040_discovery_grouping_continuity`. No ejecutar `db-upgrade` para esta actualización.

## 3. Pruebas relevantes y colección completa

```bash
pytest -q \
  tests/test_ui_navigation.py \
  tests/test_open_discovery.py \
  tests/test_documentation.py \
  tests/test_packaging.py && \
pytest --collect-only -q
```

## 4. Validación manual breve de UX-03

Usar la copia conservada `project_data_open_discovery_validation`, ubicada fuera de la raíz del repositorio. No crear grupos, decisiones ni corridas nuevas.

```bash
VALIDATION_ROOT="$(find "$HOME/projects" -maxdepth 3 -type d -name 'project_data_open_discovery_validation' -print -quit)"
archive-workbench review-app "$VALIDATION_ROOT"
```

En **Entidades y menciones** comprobar únicamente:

1. Arriba aparecen tres tareas separadas: **Revisar entidades**, **Crear entidad** y **Descubrimiento abierto**.
2. La búsqueda y las menciones existentes están dentro de **Revisar entidades**; el formulario de alta está únicamente en **Crear entidad**.
3. **Descubrimiento abierto** abre primero **Revisar candidatos** y separa **Nueva corrida** de **Agrupamiento y continuidad**.
4. Dentro de **Agrupamiento y continuidad** aparecen recorridos separados para **Revisar grupos** y **Continuidad textual**.
5. Los resúmenes, historiales, filtros y datos técnicos permanecen cerrados por defecto y ninguna pestaña pierde su selección al cambiar un control.

No hace falta repetir el validador de `DISC-01C`: quedó cerrado con cuatro grupos, nueve pertenencias, catorce acciones append-only, una continuidad, revisión `0040`, integridad correcta y claves foráneas vacías.
