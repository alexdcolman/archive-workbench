# Actualización y prueba — Archive Workbench 0.64.2

## Objetivo

Esta versión realiza el cierre documental de `DATA-02` después de su validación completa y fija el plan de implementación de `EX-01`. No cambia la lógica de la aplicación ni el esquema de base.

`DATA-02` deja de figurar entre los pendientes: quedaron confirmados los tres tipos auditados, las tres autorizaciones ampliadas, la revisión `0034_automatic_analysis_authorizations`, la integridad SQLite y las claves foráneas.

El nuevo documento [`RECUPERACION_LINAJE_EX_01.md`](../referencia/RECUPERACION_LINAJE_EX_01.md) define objetivo, alcance, contratos actuales, evidencia aceptable, persistencia prevista, fases, no regresiones, pruebas mínimas y exclusiones. La primera fase de código será `EX-01A`, diagnóstico de solo lectura para paquetes `unmatched`.

## 1. Actualizar el código

Detené Streamlit con `Ctrl+C` y ejecutá:

```bash
cd ~/projects/archive_app
source .venv/bin/activate

rm -rf /tmp/archive_workbench_v0.64.2
mkdir -p /tmp/archive_workbench_v0.64.2

unzip -q \
  ~/Downloads/archive_workbench_v0.64.2.zip \
  -d /tmp/archive_workbench_v0.64.2

cp -a /tmp/archive_workbench_v0.64.2/. .

pip install -e ".[dev,extraction,streamlit,semantic,tiff]"
```

Comprobá:

```bash
python -c "import archive_workbench; print(archive_workbench.__version__)"
```

Debe devolver:

```text
0.64.2
```

## 2. Base de datos

Esta versión **no contiene una migración**. No ejecutes `db-upgrade`.

Los proyectos ya migrados deben continuar en:

```text
0034_automatic_analysis_authorizations
```

No vuelvas a abrir ni modificar la copia descartable de validación de `DATA-02`; esa prueba está cerrada.

## 3. Pruebas automatizadas

Como esta entrega modifica versión y documentación, ejecutá únicamente:

```bash
pytest -q \
  tests/test_documentation.py \
  tests/test_packaging.py
```

Comprobá después la colección completa:

```bash
pytest --collect-only -q
```

Resultado esperado del primer bloque: `39 passed`.

La colección completa debe indicar `356 tests collected`.

## 4. Validación manual

No hay una prueba manual de interfaz para 0.64.2. No repitas exportación, búsqueda semántica, sugerencias de menciones ni controles de integridad de `DATA-02`.

Para revisar el plan de la fase siguiente:

```bash
less docs/referencia/RECUPERACION_LINAJE_EX_01.md
```

La próxima versión funcional comenzará con `EX-01A`: diagnóstico sin escritura de evidencia para paquetes sin base común reconocida.
