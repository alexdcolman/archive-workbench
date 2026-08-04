# Reparación asistida de menciones — Archive Workbench 0.57.0

## Problema

Una mención conserva el fragmento, los offsets y la revisión textual sobre la que fue creada. Cuando el objeto editable cambia, la mención puede seguir siendo interpretable, volverse ambigua, coincidir con otra mención activa o quedar separada de su historial. La aplicación ya detectaba varios de estos casos, pero no ofrecía una reparación segura y auditada.

## Clasificación

La revisión de alertas distingue:

- `safe_relocation`: el fragmento tiene una única proyección verificable sobre el texto vigente;
- `unresolved_relocation`: no existe una ubicación única;
- `duplicate_relocation`: la ubicación proyectada ya está ocupada por otra mención activa;
- `missing_authority`: una mención aceptada o modificada quedó sin autoridad;
- `snapshot_divergence`: la fila vigente no coincide con el último snapshot registrado.

Las menciones rechazadas son evidencia histórica y no se presentan como trabajo activo.

## Condiciones de la reubicación segura

La aplicación solo habilita la operación cuando se cumplen simultáneamente estas condiciones:

1. la mención sigue activa;
2. pertenece a una revisión textual anterior;
3. el último snapshot coincide con la fila vigente;
4. `project_mention_span_to_current` encuentra una única ubicación;
5. el fragmento proyectado coincide con el texto registrado;
6. no existe otra mención activa sobre esa ubicación;
7. la ubicación no cambió desde que se mostró la alerta.

Si falla una condición, la aplicación no modifica datos y explica por qué requiere revisión humana.

## Auditoría

`repair_stale_mention` actualiza el fragmento, los offsets y `object_revision_number`, incrementa la revisión de la mención y agrega una fila en `entity_mention_revisions` con operación `repair_relocation`, actor, fecha, nota y snapshot completo. Las revisiones anteriores permanecen intactas y el evento entra en el mecanismo existente de intercambio offline.

## Interfaz

La operación se encuentra en `Explorar relaciones → Revisar alertas → Menciones que requieren revisión`. Requiere una casilla de confirmación y el botón explícito `Reubicar mención`; `Enter` no ejecuta la escritura. La pantalla permite abrir el texto, la entidad y el historial técnico de la mención.

## Validación descartable

`scripts/create_mention_repair_validation_project.py` copia un proyecto existente, crea una entidad y una mención controladas y desplaza el texto en la copia. El proyecto de origen no se modifica.

## Alcance pendiente

Esta fase no resuelve automáticamente duplicados, vínculos faltantes, ubicaciones ambiguas ni divergencias de snapshots. Esas decisiones continúan en `DATA-01` y deberán producir revisiones explícitas, nunca reescrituras silenciosas.
