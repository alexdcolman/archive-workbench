# Relevo vigente - Archive Workbench 0.89.0 RC64 / PILOT-01

**Candidata actual:** `0.89.0 RC64`, no publicada  
**Última publicación real:** `v0.88.2`  
**Proyecto piloto persistente:** `/home/alex/projects/archive_app/pilot_data`  
**Revisión de base vigente:** `0047_authority_relation_profiles`

Antes de modificar código, leer `.assistant/00_LEER_PRIMERO.md`, seguir todo el orden obligatorio y ejecutar la verificación de `.assistant/00_CHECKLIST_CAMBIOS.md`. Toda interacción Streamlit nueva debe respetar `#streamlit-interaction-invariant` en `docs/referencia/ARQUITECTURA_Y_MODELO_ACTUAL.md`.

## Estado del piloto

- No recrear `pilot_data`, no ejecutar `db-upgrade` y no repetir tramos ya validados.
- El recorrido funcional extremo a extremo, audiovisual, procesamiento, revisión, búsquedas, entidades, grafo, exportación, organización del trabajo, intercambio, administración, backup y recuperación están verdes.
- `PILOT-01E` quedó cerrado por validación manual de RC62.
- Después de ese cierre se auditó toda la app contra las políticas Streamlit y se abrió `PILOT-01AE`. RC63 intentó corregir pestañas con rerun visual, 23 expanders interactivos, un formulario circular de Catálogo, escritura audiovisual con Enter y una mutación tardía de key en Descubrimiento.
- La primera validación de RC63 encontró tracebacks y otros estados condicionales en Grafo, Exportar corpus, Revisar documentos, Búsqueda textual y Búsqueda semántica. RC64 repara esas regresiones sin reabrir contratos de dominio.
- `PILOT-01AE` permanece parcial únicamente hasta la validación manual sección por sección de RC64. No repetir funciones de dominio ya cerradas.
- Si RC64 queda verde, cerrar `PILOT-01AE` y continuar con `PILOT-01A` (modelo descriptivo de custodia, repositorios, colecciones y agrupaciones audiovisuales/plataformas).
- `PILOT-01N` es post-release y no bloquea.

RC64 no requiere `db-upgrade` si el proyecto ya está en `0047_authority_relation_profiles`. La suite completa corresponde exclusivamente a Alex; el asistente sólo ejecuta gates focales y `pytest --collect-only -q`.
