# Formato de importación de diccionarios de autoridades y relaciones

**Versión del esquema:** `1.1` · **Implementación bidireccional:** Archive Workbench `0.89.0 RC33`

Este documento define el formato JSON versionado de `DISC-02`. El esquema 1.1 conserva compatibilidad de lectura con 1.0 y agrega un modo bidireccional para exportar fichas existentes, editarlas y reimportarlas mediante actualización explícita. La simulación sigue siendo obligatoria antes de aplicar; una coincidencia ordinaria nunca se sobrescribe por inferencia.

## Archivos de referencia

- Esquema JSON: `config/authority_dictionaries/authority_dictionary.schema.json`.
- Ejemplo editable: `examples/diccionario_autoridades_ejemplo.json`.
- Comandos: `authority-dictionary-schema`, `authority-dictionary-export`, `authority-dictionary-validate` y `authority-dictionary-import`.

## Estructura general

```json
{
  "schema_version": "1.1",
  "dictionary_id": "identificador_estable",
  "dictionary_name": "Nombre legible",
  "target_project_id": "*",
  "source": {},
  "authorities": [],
  "relations": []
}
```

`dictionary_id` identifica la fuente importada dentro de notas de revisión y debe permanecer estable entre reimportaciones. `target_project_id` puede omitirse, usar `*` o fijar el identificador exacto del proyecto.

## Fuente y procedencia

`source.title` es obligatorio. También pueden registrarse `organization`, `url`, `reference`, `created_by`, `created_at` y `note`. La importación copia esta procedencia a las revisiones creadas. No se usa la URL como prueba automática de veracidad.

## Autoridades

Cada entrada de `authorities` requiere:

- `local_id`: identificador único dentro del JSON;
- `entity_type`: `person`, `organization`, `place`, `event`, `work` u `other`;
- `preferred_name`.

Admite `description`, `characteristics`, `temporal_expression`, `temporal_note`, `review_status`, `aliases`, `source_note` y `resolution`.

`characteristics` conserva pares descriptivos dentro de la descripción de una autoridad nueva, bajo el bloque **Características importadas**. No crea clases nuevas ni campos canónicos paralelos. Una persona investigadora se representa como `person`; una publicación u obra como `work`; una institución como `organization`.

### Alias

Cada alias tiene `value`, `alias_type`, `note` y `allow_ambiguous`. Los tipos admitidos son `variant`, `abbreviation`, `acronym`, `former_name`, `title` y `other`.

Un alias que ya identifica otra autoridad es un error. Solo puede importarse si `allow_ambiguous` vale `true`; esa decisión queda como advertencia visible. Un alias igual al nombre preferido se omite.

### Duplicados y resolución

La simulación compara nombres preferidos y alias normalizados. `resolution.action` admite:

- `auto`: crea si no hay coincidencias; reutiliza una única coincidencia exacta de nombre preferido y tipo; bloquea casos ambiguos;
- `use_existing`: requiere `authority_id`, coincidencia nominal y el mismo tipo; reutiliza sin sobrescribir la ficha;
- `update_existing`: requiere `authority_id` y se reserva para una actualización explícita, normalmente generada por `authority-dictionary-export`; actualiza la ficha identificada después de una simulación válida;
- `create_new`: crea una autoridad nueva pese a coincidencias y emite advertencia;
- `skip`: omite la entrada.

Al reutilizar una autoridad, la importación puede agregar alias nuevos, pero no cambia su nombre preferido, tipo, descripción, características ni temporalidad. Las diferencias aparecen como advertencia. `update_existing` es distinto: la identidad se fija por `authority_id` y los campos del archivo se aplican como una revisión nueva del mismo registro. Quitar un alias de la plantilla no lo elimina; la eliminación de alias sigue siendo una operación explícita de la aplicación.

## Temporalidad

`temporal_expression` usa el mismo contrato del resto de Archive Workbench: fechas exactas, mes y año, año, décadas, rangos o intervalos abiertos, por ejemplo `15/03/1975`, `03/1975`, `1975`, `años setenta`, `desde 1974` o `03/1974 - 03/1976`.

## Relaciones

Cada relación requiere:

- `local_id`;
- `source_local_id`, que referencia una autoridad del mismo diccionario;
- `relation_label`;
- `target_kind`: `authority`, `archival_unit` o `document_part`;
- un destino local o canónico según el tipo;
- `evidence`.

Para `authority` se usa exactamente uno de `target_local_id` o `target_id`. Para unidades archivísticas y partes documentales se usa `target_id` canónico del proyecto.

### Evidencia

Para crear una relación nueva, `evidence` debe contener al menos uno de `note`, `source_url` o `source_reference`. La evidencia queda almacenada en la relación, no solo en el informe de importación. Una relación existente exportada con `update_existing` puede conservar evidencia vacía, porque el objetivo del ida y vuelta es representar fielmente el estado ya registrado y no inventar una fuente.

Desde 0.77.0, las relaciones creadas por este formato quedan clasificadas explícitamente como `analytical`. La procedencia del diccionario y del elemento importado se conserva en `provenance_note`; los roles archivísticos `producer` y `manager` se administran desde la unidad de catálogo y no se infieren a partir de etiquetas libres del diccionario.

### Relaciones existentes

Una relación idéntica —mismo origen, etiqueta, destino, temporalidad y evidencia— se omite en una reimportación. Si ya existe la misma relación básica con evidencia o temporalidad distintas, `resolution.action` debe ser:

- `create_parallel`, para crear otra relación con advertencia explícita;
- `skip`, para omitirla.

`auto` bloquea el conflicto para evitar reemplazos silenciosos.

El esquema 1.1 agrega `update_existing`, que requiere `resolution.relation_id`. Este modo se usa en las plantillas exportadas por Archive Workbench y permite actualizar explícitamente la misma relación analítica -rótulo, origen/destino, temporalidad, evidencia, estado de revisión y perfil descriptivo- después de la simulación. No se aplica por coincidencia aproximada.

## Simulación y aplicación

La validación produce un informe con huella SHA-256, acciones previstas, candidatos de duplicación, errores y advertencias. No escribe en la base.

La aplicación requiere una simulación válida, `--apply` y la confirmación exacta `IMPORTAR`, o el flujo equivalente en la interfaz. Autoridades, alias y relaciones se aplican en una sola transacción: cualquier error revierte el bloque completo.

```bash
archive-workbench authority-dictionary-validate \
  project_data diccionario.json \
  --output informe.json

archive-workbench authority-dictionary-import \
  project_data diccionario.json \
  --apply --confirm IMPORTAR --changed-by Alex \
  --output informe.json
```

Una importación 1.0 idéntica conserva el comportamiento histórico de reutilización/omisión. Una plantilla 1.1 exportada desde el proyecto reimporta sus registros como actualizaciones explícitas del mismo `authority_id`/`relation_id`, sin duplicarlos.
