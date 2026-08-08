# Actualización actual — Archive Workbench 0.88.1

**Estado:** corrección validada para cierre local · **fecha:** 2026-08-08

## Alcance

La primera importación real de `PILOT-01` detectó una inconsistencia en el recorrido de proyecto nuevo. `init-project` crea la estructura de carpetas y `db-upgrade` crea o actualiza el esquema, pero una base recién creada todavía puede tener `projects: 0`. La simulación de una plantilla XLSX era válida, mientras que la aplicación fallaba al crear la primera unidad archivística por la clave foránea `archival_units.project_id -> projects.id`.

0.88.1 corrige ese recorrido en `apply_catalog_template()`: después de completar una validación válida y antes de crear o actualizar unidades, registra o actualiza el proyecto mediante la configuración `decisions.yaml` dentro de la misma transacción. La simulación (`catalog-template-validate`) continúa sin escribir en la base.

La regresión agregada reproduce explícitamente una base recién creada sin fila `Project`, comprueba que la validación no la modifica y verifica que la aplicación válida crea el proyecto y la jerarquía esperada.

## Persistencia y migración

No hay cambios de esquema. La revisión continúa en `0046_audiovisual_timeline_annotations`.

**0.88.1 no requiere `db-upgrade`. No ejecutar `db-upgrade` por esta versión.**

La importación fallida observada en `pilot_data` fue transaccional: después del error permanecieron `projects: 0`, `archival_units: 0` y `archival_unit_revisions: 0`. No es necesario restaurar el backup baseline antes de reintentar con la corrección.

## Estado de PILOT-01

`PILOT-01` continúa abierto. El catálogo APM Chubut preparado para el piloto contiene 9 unidades nuevas. La simulación previa informó 9 creaciones, 0 actualizaciones, 0 omisiones, 0 errores y 0 advertencias. Después de instalar 0.88.1, la aplicación real creó correctamente las 9 unidades: `projects: 1`, `archival_units: 9`, `digital_objects: 0`, sin migración y con UUID nuevos.

`project_data` no participó de esta corrección ni de su validación manual.

## Validación cerrada

La candidata 0.88.1 pasó las regresiones acotadas de catálogo, documentación, empaquetado y módulos afectados por versionado. `pytest --collect-only -q` recopiló 537 tests. La validación manual reintentó exactamente la importación que había fallado sobre `pilot_data`: la simulación volvió a informar 9 creaciones y 0 errores, y la aplicación terminó con 9 creadas, 0 actualizadas, 0 movidas, 0 sin cambios y 0 omitidas. El árbol resultante contiene las 9 unidades APM Chubut y ningún objeto digital. No se repitió la suite completa ya cerrada de 0.88.0.
