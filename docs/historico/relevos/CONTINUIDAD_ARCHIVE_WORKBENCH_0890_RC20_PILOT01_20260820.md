# Relevo vigente - Archive Workbench 0.89.0 RC20 / PILOT-01

**Candidata actual:** `0.89.0 RC20`, no publicada  
**Última publicación real:** `v0.88.2`  
**Revisión DB:** `0046_audiovisual_timeline_annotations`  
**Migración nueva:** no

## Lectura obligatoria

Antes de proponer cambios o guiar pruebas, seguir exactamente el orden de `.assistant/00_LEER_PRIMERO.md`. En particular, completar `.assistant/00_CHECKLIST_CAMBIOS.md` antes de cualquier modificación y leer el invariante canónico de Streamlit en `docs/referencia/ARQUITECTURA_Y_MODELO_ACTUAL.md#streamlit-interaction-invariant` antes de tocar una interacción.

Todo mensaje que presente cambios de código debe confirmar explícitamente que la checklist fue verificada, según `.assistant/01_INTERACCION_Y_GUIADO.md`.

## Estado de PILOT-01

No recrear `pilot_data`, no volver a incorporar los 138 originales, no ejecutar `db-upgrade` y no repetir las fases ya cerradas de audiovisual, procesamiento, OCR regional, envío masivo a revisión ni revisión general de documentos. RC18 validó la arquitectura Streamlit recuperada desde RC7/RC8. RC19 avanzó en Entidades y menciones y la validación manual confirmó el resto de sus cambios.

Queda únicamente `PILOT-01O` para revalidar RC20:

- en `Revisar documentos`, bbox rojo y selector textual deben quedar sincronizados en cada clic;
- `Trabajar con varias referencias` usa un formulario estable: seleccionar, elegir acción y confirmar no deben provocar rerun antes del envío;
- `Referencias descartadas` es una pestaña independiente con restauración append-only.

`DISC-03` sigue pendiente pre-release para afinar la búsqueda de entidades mediante tests y auditorías diversas. No optimizar el detector durante este cierre del piloto.

## Después de RC20

Si `PILOT-01O` queda validado, trasladarlo a `IMPLEMENTACIONES_REALIZADAS.md` y continuar el recorrido de extremo a extremo desde el punto posterior a Entidades y menciones, sin reabrir fases cerradas salvo evidencia material nueva. El próximo relevo solicitado por Alex debe empaquetar la candidata validada y toda la continuidad necesaria para otra conversación.
