# Reconciliación de divergencias de menciones — Archive Workbench 0.61.0

## Problema

Una fila de `entity_mentions` puede no coincidir con el último registro de `entity_mention_revisions`. Esto puede provenir de una importación antigua, una reparación manual fuera de los contratos actuales o una migración histórica incompleta. Mientras exista esa divergencia, no es seguro aplicar reubicaciones, vínculos o decisiones sobre duplicados porque la aplicación no sabe cuál de los dos estados representa la decisión humana vigente.

## Decisión

La divergencia se presenta como `snapshot_divergence` y exige una comparación campo por campo entre:

- la fila vigente;
- el último snapshot registrado;
- el número de revisión de ambos estados.

La persona revisora puede elegir una de dos rutas explícitas.

### Conservar la fila vigente

`repair_adopt_current_row` mantiene los valores actuales y agrega una revisión nueva que los incorpora al historial. No se modifica el snapshot anterior.

### Restaurar el último estado registrado

La restauración usa dos operaciones dentro de una misma transacción:

1. `repair_capture_divergent_row` registra primero todos los valores de la fila divergente;
2. `repair_restore_snapshot` repone después el último snapshot como una revisión nueva.

Este paso doble es obligatorio para que ningún valor observado desaparezca: restaurar directamente habría borrado la única evidencia de los valores divergentes.

## Controles de concurrencia y seguridad

Antes de escribir, la operación vuelve a comprobar:

- UUID y revisión vigente de la mención;
- número y contenido exacto del último snapshot;
- contenido exacto de la fila que se mostró en pantalla;
- existencia del objeto textual y de la entidad restaurada;
- pertenencia de objeto y entidad al mismo proyecto;
- validez de estado, procedencia, revisión textual y offsets.

Si cualquiera de esos elementos cambió, el formulario se rechaza y debe volver a evaluarse. Ninguna acción se ejecuta mediante `Enter`.

## Alcance

La reconciliación no decide por sí sola si una mención está bien ubicada, vinculada o deduplicada. Después de reconciliar, la mención puede aparecer como otra alerta más específica —por ejemplo, entidad faltante o ubicación desactualizada— que deberá resolverse mediante su flujo correspondiente.

## Validación descartable

`scripts/create_snapshot_divergence_validation_project.py` crea dos menciones:

- una cuya fila vigente debe conservarse;
- otra cuyo último estado registrado debe restaurarse.

La comprobación exige revisar las diferencias, ejecutar ambas decisiones, verificar las operaciones append-only, confirmar que no queden alertas para esas menciones y ejecutar `PRAGMA integrity_check` y `PRAGMA foreign_key_check`.
