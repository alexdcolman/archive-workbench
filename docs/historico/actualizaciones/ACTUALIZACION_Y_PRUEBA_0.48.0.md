# Archive Workbench 0.48.0 — actualización y prueba

## Qué cambia

- Las tres entradas manuales del rebase —texto conflictivo, fragmento de mención y JSON de atributo— tienen ahora un formulario propio con `enter_to_submit=False` y un botón explícito.
- Escribir, salir del campo o pulsar `Enter`/`Ctrl+Enter` no incorpora la resolución a la vista previa. La decisión queda activa únicamente después de pulsar **Confirmar texto manual**, **Confirmar fragmento manual** o **Confirmar valor JSON**.
- La aplicación oculta globalmente las instrucciones automáticas `Press Enter…` y `Press Ctrl+Enter…` de Streamlit, porque contradicen este flujo.
- “Pendientes y mejoras” distingue ahora los bloques ya resueltos y validados de los parciales o todavía abiertos.

No hay migración nueva. La base continúa en `0032_page_quality_assessments`.

## Actualizar desde 0.47.0

Detené Streamlit con `Ctrl+C` y ejecutá:

```bash
cd ~/projects/archive_app
source .venv/bin/activate

rm -rf /tmp/archive_workbench_v0.48.0

unzip -q \
  ~/Downloads/archive_workbench_v0.48.0.zip \
  -d /tmp

cp -a /tmp/archive_workbench_v0.48.0/. .

pip install -e ".[dev,extraction,streamlit,semantic,tiff]"
```

Comprobá:

```bash
python -c "import archive_workbench; print(archive_workbench.__version__)"
```

Debe devolver:

```text
0.48.0
```

No ejecutes `db-upgrade`.

## Pruebas automatizadas

Primero, el bloque directamente afectado:

```bash
pytest \
  tests/test_ui_navigation.py \
  tests/test_documentation.py \
  tests/test_packaging.py \
  tests/test_processing.py \
  tests/test_rebase_structural_metadata.py \
  tests/test_candidate_review.py
```

Resultado esperado:

```text
56 passed
```

Después:

```bash
pytest
```

Resultado objetivo:

```text
264 passed
```

## Validación manual — secuencia completa

La secuencia siguiente contiene todas las decisiones y observaciones antes de empezar. No agregues decisiones distintas durante la prueba.

### 1. Recrear y abrir el proyecto descartable

Cerrá cualquier app que siga usando el puerto 8501 y recreá el proyecto:

```bash
cd ~/projects/archive_app
source .venv/bin/activate

fuser -k 8501/tcp 2>/dev/null || true
python scripts/create_rebase_validation_project.py --force
archive-workbench review-app project_data_rebase_validation
```

### 2. Preparar el rebase

Entrá en:

```text
Procesamiento
→ Selección canónica
→ rebase_demo
→ página 1
→ demo_surya_candidata
→ Rebasar la edición sobre esta candidata
```

En los dos conflictos **Proyección del objeto editable**, elegí deliberadamente:

```text
Bloque candidato 1
```

Los dos objetos deben converger en el primer bloque candidato.

### 3. Validar la entrada JSON antes de confirmarla

Cuando aparezca **Atributo `classification`**, elegí:

```text
Escribir un valor JSON manual
```

Antes de pulsar ningún botón, verificá:

- no aparece `Press Enter to submit form`, `Press Enter to apply` ni `Press Ctrl+Enter to apply`;
- aparece el botón **Confirmar valor JSON**.

Pegá exactamente:

```json
{
  "origin": "reviewed",
  "value": "AB",
  "confidence": "human-confirmed"
}
```

Marcá **Confirmo este valor JSON**. Con el cursor dentro del área JSON, pulsá `Ctrl+Enter` una vez.

En ese momento **no** debe aparecer:

```text
Valor JSON confirmado para la vista previa.
```

Tampoco debe habilitarse la aplicación final por esa acción de teclado.

Ahora pulsá con el mouse:

```text
Confirmar valor JSON
```

Recién entonces debe aparecer:

```text
Valor JSON confirmado para la vista previa.
```

### 4. Aplicar y observar la navegación

Marcá la confirmación final y pulsá:

```text
Aplicar rebase y adoptar la candidata
```

El rebase debe completarse sin error. Inmediatamente después, pulsá:

```text
Abrir esta página en Revisión
```

Durante esa transición observá si queda la vista de Procesamiento oscurecida detrás de Revisión. **No debe aparecer ningún remanente oscuro.**

### 5. Verificar el resultado del rebase

En **Revisión**, el primer objeto debe conservar:

- 2 comentarios;
- 2 etiquetas;
- `classification` con `origin=reviewed`, `value=AB` y `confidence=human-confirmed`;
- `demo_attribute: true`;
- `shared_review.priority: high`;
- `layout_role: body`.

En **Historial → Toda la página** debe existir una operación `rebase`.

### 6. Validar un formulario común

Entrá en:

```text
Entidades
→ Crear entidad
```

Escribí en **Nombre preferido**:

```text
Prueba Enter 0.48
```

Pulsá `Enter` una vez. No debe crearse la entidad y no debe aparecer ninguna instrucción `Press Enter…`. No pulses **Crear entidad definitivamente**; esta entidad no forma parte de la prueba.

### 7. Integridad final de la base

Cerrá Streamlit y ejecutá:

```bash
python - <<'PY'
import sqlite3

path = "project_data_rebase_validation/data/archive_workbench.sqlite3"
with sqlite3.connect(path) as connection:
    print("integrity_check:", connection.execute("PRAGMA integrity_check").fetchone()[0])
    print("foreign_key_check:", connection.execute("PRAGMA foreign_key_check").fetchall())
PY
```

Debe devolver:

```text
integrity_check: ok
foreign_key_check: []
```

## Relación con “Pendientes y mejoras”

Esta versión completa la política de acciones explícitas en las entradas manuales del rebase y elimina mensajes de teclado que podían inducir envíos accidentales. También deja el registro de pendientes alineado con lo ya resuelto y validado, sin cerrar los bloques parciales que todavía requieren trabajo.
