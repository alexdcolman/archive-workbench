# Formato de importación de diccionarios de autoridades y relaciones

**Versión del esquema:** `1.0` · **Implementación:** Archive Workbench `0.76.0`

Este documento define el único formato admitido por `DISC-02`. El diccionario es un archivo JSON versionado que puede describir autoridades, alias y relaciones explícitas. La simulación es obligatoria antes de aplicar y nunca sobrescribe campos de una autoridad existente.

## Archivos de referencia

- Esquema JSON: `config/authority_dictionaries/authority_dictionary.schema.json`.
- Ejemplo editable: `examples/diccionario_autoridades_ejemplo.json`.
- Comandos: `authority-dictionary-schema`, `authority-dictionary-validate` y `authority-dictionary-import`.

## Estructura general

```json
{
  "schema_version": "1.0",
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
- `use_existing`: requiere `authority_id`, coincidencia nominal y el mismo tipo;
- `create_new`: crea una autoridad nueva pese a coincidencias y emite advertencia;
- `skip`: omite la entrada.

Al reutilizar una autoridad, la importación puede agregar alias nuevos, pero no cambia su nombre preferido, tipo, descripción, características ni temporalidad. Las diferencias aparecen como advertencia.

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

### Evidencia obligatoria

`evidence` debe contener al menos uno de `note`, `source_url` o `source_reference`. Una relación sin evidencia ni siquiera cumple el esquema. La evidencia queda almacenada en la relación, no solo en el informe de importación.

Desde 0.77.0, las relaciones creadas por este formato quedan clasificadas explícitamente como `analytical`. La procedencia del diccionario y del elemento importado se conserva en `provenance_note`; los roles archivísticos `producer` y `manager` se administran desde la unidad de catálogo y no se infieren a partir de etiquetas libres del diccionario.

### Relaciones existentes

Una relación idéntica —mismo origen, etiqueta, destino, temporalidad y evidencia— se omite en una reimportación. Si ya existe la misma relación básica con evidencia o temporalidad distintas, `resolution.action` debe ser:

- `create_parallel`, para crear otra relación con advertencia explícita;
- `skip`, para omitirla.

`auto` bloquea el conflicto para evitar reemplazos silenciosos.

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

La reimportación idéntica reutiliza autoridades, omite alias ya presentes y no recrea relaciones idénticas.
