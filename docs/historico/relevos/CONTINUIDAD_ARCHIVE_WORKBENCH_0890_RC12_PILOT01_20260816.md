# CONTINUIDAD - Archive Workbench 0.89.0 RC12 / PILOT-01

**Fecha:** 2026-08-16  
**Estado:** candidata `0.89.0 RC12`, no publicada. Última publicación real: `v0.88.2`.

## Estado de trabajo

PILOT-01 usa el proyecto persistente `/home/alex/projects/archive_app/pilot_data`. No recrearlo, no volver a incorporar los 138 originales, no repetir la prueba audiovisual, no volver a preparar los tres PDF ni los dos TIFF ya validados y no ejecutar `db-upgrade`.

RC10 cerró la reparación pyvips de los TIFF y la extracción posterior terminó 5/5 con Surya, sin advertencias ni fallos. La inspección manual de la muestra fue satisfactoria. El OCR regional real sobre `carp_reg.pdf`, página 13, creó un resultado parcial y mostró la necesidad de integrar mejor ese resultado con un bloque textual concreto. RC11 implementó ese reemplazo localizado, la preparación masiva para revisión, la liberación automática de recursos Surya y un primer replanteo de Procesar/Revisar.

## Motivo de RC12

La validación manual de RC11 encontró que la auditoría anterior seguía aceptando frases cuyo referente se deducía por contexto, por ejemplo `Cada tarjeta resume una parte del trabajo` o explicaciones de la planilla que decían `qué significa cada columna` sin decir qué dato del catálogo representaba. RC12 no agrega una función nueva: reescribe transversalmente la interfaz y corrige la metodología de revisión.

La regla vigente es que cada texto operativo, leído aisladamente, debe permitir identificar el objeto al que se refiere, la acción que ofrece y el efecto relevante. La auditoría abarca todas las vistas y también `region_canvas.py`, `review_canvas.py`, `audiovisual_review_component.py`, `graph_canvas.py` y `local_picker.py`. Las cinco pasadas separan títulos/navegación, controles, ayudas/avisos, estados/resultados/historiales y opciones técnicas.

## Validación automática de la candidata

En la construcción de RC12 pasaron 129 pruebas focalizadas (`test_ui_navigation.py`, `test_documentation.py`, `test_packaging.py`, `test_operational.py`), `compileall` de `src` y `tests` fue correcto y la recopilación completa encontró 575 tests en 53 archivos. No se repitió la suite completa, porque RC12 modifica interfaz/documentación y RC11 ya había pasado la tanda funcional indicada por el piloto.

## Próximo paso exacto

1. Instalar RC12 sobre `~/projects/archive_app` sin tocar `pilot_data`.
2. Ejecutar la tanda focalizada indicada en `docs/operativos/ACTUALIZACION_ACTUAL.md`.
3. Si queda verde, reabrir la aplicación y recorrer sin guía externa Inicio, Catálogo, Procesar documentos y Revisar documentos. No repetir operaciones ya cerradas: evaluar la comprensión de las pantallas y continuar desde el estado persistente.
4. Mantener `PILOT-01E` y `PILOT-01J` parciales hasta esa validación manual.

## Fuentes de verdad

Leer primero este relevo, luego `.assistant/00_LEER_PRIMERO.md` y toda `.assistant`, los documentos operativos vigentes, `docs/HISTORIAL_DE_CAMBIOS.md` y `docs/referencia/ARQUITECTURA_Y_MODELO_ACTUAL.md`. Cuando una observación deba quedar asentada, usar la documentación canónica del proyecto, nunca memoria del asistente como sustituto.
