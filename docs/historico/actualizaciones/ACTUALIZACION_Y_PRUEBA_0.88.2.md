# Actualización actual — Archive Workbench 0.88.2

**Estado:** candidata validada pendiente de cierre local · **fecha:** 2026-08-08

## Alcance

Durante la ampliación real del catálogo APM Chubut en `PILOT-01`, una plantilla válida de 16 filas (`crear 7`, `actualizar 3`, `omitir 6`) falló al aplicarse con `No se pudo resolver el orden jerárquico de la importación`. La base permaneció sin cambios por rollback transaccional.

La causa estaba en `apply_catalog_template()`: el mapa usado para resolver `parent_local_id` excluía las filas marcadas `omitir`, aun cuando representaban unidades existentes con `unit_id`. La validación sí aceptaba correctamente esas filas como padres existentes, por lo que simulación y aplicación no compartían el mismo contrato.

0.88.2 conserva en el mapa jerárquico toda fila que tenga `unit_id`, incluida una unidad existente marcada `omitir`. Esa fila sirve únicamente como referencia de padre: no se actualiza ni genera una revisión por estar omitida. Las filas omitidas nuevas, sin `unit_id`, continúan sin poder actuar como padres y la validación las rechaza.

Se agrega una regresión que crea Archivo y Fondo existentes, marca el Archivo como `omitir`, actualiza el Fondo mediante `parent_local_id` y comprueba que la plantilla válida se aplica, el padre permanece intacto y solo el Fondo recibe la actualización.

## Persistencia y migración

No hay cambios de esquema. La revisión continúa en `0046_audiovisual_timeline_annotations`.

**0.88.2 no requiere `db-upgrade`. No ejecutar `db-upgrade` por esta versión.**

El intento fallido de ampliación de `pilot_data` fue transaccional: el árbol continuó con 9 unidades, `archival_units: 9` y `digital_objects: 0`. Además existe el backup previo `pilot_data_pre_ampliacion_catalogo_20260808_185514.zip`. No restaurar ni repetir trabajo ya cerrado.
`project_data` no participó de este incidente ni debe usarse para la revalidación.

## Estado de PILOT-01

`pilot_data` ya contiene el catálogo APM Chubut ampliado: `projects: 1`, `archival_units: 16` y `digital_objects: 0`. La plantilla real de 16 filas se aplicó correctamente con 0.88.2: 7 unidades creadas, 3 actualizadas y 6 omitidas. El catálogo quedó con `15 — Actividades culturales`, `Caso El Bolsón`, el título ampliado del Ejemplar 0619, seis documentos adicionales de la caja de Administración Pública y `22 — Agrupaciones empresarias y profesionales`.

Los originales del piloto están en `corpus/`; 0.88.2 agrega `/corpus/` al `.gitignore` existente. No se versionan ni se empaquetan esos materiales.

## Validación de la candidata

La candidata quedó validada con las pruebas acotadas de catálogo, documentación, empaquetado y regresiones de versión afectadas (78 pruebas), `pytest --collect-only -q` con 538 pruebas recopiladas y construcción correcta del wheel. La validación manual real reintentó exactamente la misma plantilla de 16 filas y terminó con 7 creadas, 3 actualizadas, 6 omitidas y 0 errores. No repetir la suite completa de 0.88.0, la primera importación de 9 unidades ni esta ampliación ya cerrada, salvo un cambio posterior que invalide materialmente esa evidencia.
