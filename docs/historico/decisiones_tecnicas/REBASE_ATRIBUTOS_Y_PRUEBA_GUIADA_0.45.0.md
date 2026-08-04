# Rebase de atributos especializados y prueba guiada en Archive Workbench 0.45.0

## 1. Problema corregido en la confirmación final

En 0.44.0 la casilla de confirmación y el botón de aplicación quedaron agrupados correctamente dentro de un formulario, pero el botón se renderizaba deshabilitado mientras la casilla todavía era falsa. Como los widgets de un formulario no envían su nuevo valor hasta presionar el botón, el botón no podía enterarse de que la casilla había sido marcada: se producía un bloqueo circular.

En 0.45.0 el botón queda habilitado siempre que la vista previa sea aplicable. Al enviarse el formulario, el dominio comprueba también la confirmación recibida. Si no está marcada, no escribe nada y muestra un error; si está marcada, aplica el rebase en una única transacción.

La regla general queda expresada así:

```text
la seguridad del dominio decide si la operación puede enviarse
la confirmación humana se valida al recibir el envío
un valor todavía no enviado nunca controla la habilitación del propio envío
```

## 2. Qué se considera un atributo especializado

`current_attributes_json` puede contener datos de procedencia OCR, estado estructural interno y atributos agregados o modificados durante el trabajo humano. El rebase separa esas categorías:

- Los datos de procedencia (`source_label`, `source_confidence`, `source_language` y atributos sin cambios respecto de la extracción anterior) se reconstruyen desde la candidata.
- Los indicadores estructurales transitorios (`manually_added`, `geometry_pending`, referencias de división o unión y `lineage_events`) quedan absorbidos por el historial de rebase; no se presentan como si siguieran describiendo al bloque nuevo.
- Todo atributo cuyo valor activo no coincide con la extracción anterior se considera especializado y debe conservarse o resolverse explícitamente.

Esto permite trasladar, por ejemplo, clasificaciones analíticas, códigos locales, estados de formulario ya confirmados, atributos de investigación o diccionarios JSON añadidos por una integración externa.

## 3. Reglas de traslado

Cuando un atributo humano llega a un bloque candidato:

1. Si existe un único valor humano y la candidata no tiene ese atributo, se conserva automáticamente.
2. Si varias fuentes humanas aportan exactamente el mismo valor, se deduplican y se conserva una sola copia.
3. Si la candidata y la edición humana tienen el mismo valor, no existe conflicto.
4. Si la candidata y la edición humana difieren, se exige una decisión.
5. Si varios objetos humanos que convergen aportan valores diferentes, se exige una decisión.

Las opciones son:

- conservar el valor de la candidata;
- conservar uno de los valores humanos existentes;
- no trasladar el atributo;
- escribir un valor JSON manual.

La interfaz muestra el nombre del atributo, el bloque resultante y cada valor posible. Un JSON manual debe ser sintácticamente válido y requiere confirmación propia.

## 4. Auditoría

La revisión append-only de página registra:

```text
manual_attribute_resolution_count
attribute_resolution_methods
specialized_attribute_count
```

Los métodos posibles en esta versión son:

```text
manual_attribute_selection
manual_attribute_json
```

Los objetos retirados conservan sus atributos históricos. El bloque nuevo recibe los atributos de la candidata, los atributos humanos no conflictivos y las decisiones confirmadas, además de `rebased_from_object_ids`.

## 5. Proyecto descartable para probar los dos conflictos pendientes

La versión incluye:

```text
scripts/create_rebase_validation_project.py
```

El script crea un proyecto independiente llamado, por defecto, `project_data_rebase_validation`. No modifica `project_data` ni `project_data_receiver`.

Desde la raíz del repositorio:

```bash
source .venv/bin/activate
python scripts/create_rebase_validation_project.py
```

Si el proyecto ya existe y se desea recrearlo:

```bash
python scripts/create_rebase_validation_project.py --force
```

El proyecto contiene:

- una selección canónica anterior con dos bloques editables;
- una candidata Surya simulada con dos bloques muy diferentes;
- dos objetos anteriores con comentarios y etiquetas;
- un atributo compartido no conflictivo;
- tres valores incompatibles para `classification`: candidata, humano A y humano B.

## 6. Prueba guiada

Abrir el proyecto descartable:

```bash
archive-workbench review-app project_data_rebase_validation
```

Ir a:

```text
Procesamiento
→ Selección canónica
→ rebase_demo
→ página 1
→ demo_surya_candidata
→ Rebasar la edición sobre esta candidata
```

### Paso A: proyección estructural

Deben aparecer dos tarjetas `Proyección del objeto editable`. En ambas, elegir deliberadamente el **bloque candidato 1**.

La vista previa se recalcula. Al hacer converger ambos objetos en el mismo destino, sus comentarios, etiquetas y atributos pasan a evaluarse conjuntamente.

### Paso B: atributo especializado

Debe aparecer una tarjeta:

```text
Atributo `classification`
```

Las opciones deben incluir:

- valor de la candidata: `{"origin":"surya","value":"candidate"}`;
- valor humano A;
- valor humano B;
- no trasladar el atributo;
- escribir un JSON manual.

Elegir primero `Escribir un valor JSON manual` y usar:

```json
{
  "origin": "reviewed",
  "value": "AB",
  "confidence": "human-confirmed"
}
```

Confirmar ese JSON. La vista previa debe quedar aplicable.

### Paso C: confirmación final

Marcar:

```text
Confirmo que revisé la vista previa y deseo aplicar el rebase
```

El botón debe permanecer disponible. Al presionarlo, el rebase debe aplicarse una sola vez y conservar comentarios, etiquetas y el atributo manual.

### Paso D: verificación

Abrir la página en Revisión. El nuevo bloque 1 debe mostrar dos comentarios, dos etiquetas y los atributos:

```json
{
  "classification": {
    "origin": "reviewed",
    "value": "AB",
    "confidence": "human-confirmed"
  },
  "shared_review": {
    "priority": "high"
  },
  "demo_attribute": true,
  "layout_role": "body"
}
```

Los atributos exactos de procedencia pueden agregar otras claves. `lineage_events`, `manually_added` o `geometry_pending` no deben aparecer como estado activo del bloque nuevo.

## 7. Eliminación del caso descartable

Cerrar Streamlit y borrar únicamente el proyecto de demostración:

```bash
rm -rf project_data_rebase_validation
```

No hay migración nueva. Los proyectos reales continúan en `0032_page_quality_assessments`.
