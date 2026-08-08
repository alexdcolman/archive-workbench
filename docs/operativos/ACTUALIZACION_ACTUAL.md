# Actualización actual — Archive Workbench 0.88.0

**Estado:** versión final · `EXP-01` cerrado · **fecha:** 2026-08-08

## Alcance

La versión 0.88.0 agrega a **Exportar corpus > Crear archivo** la opción **Exportar texto e imágenes (ZIP)**. El perfil conserva los registros textuales principales y el ZIP puede incluir páginas completas, recortes regionales y figuras. Cada recurso visual mantiene su relación con el documento, la página, la extracción que originó la capa editable, el estado de revisión y los registros textuales asociados.

La imagen de página se toma del derivado exacto registrado por `EditablePage.source_extraction_page_id`. Las figuras se recortan desde esa misma imagen con la geometría editable vigente y los recortes regionales reutilizan el `crop_path` registrado. Tamaños y SHA-256 se verifican antes de exportar; un recurso requerido ausente o modificado hace fallar la ejecución de forma explícita.

El paquete contiene además contexto textual estructurado en `context/objects.jsonl`, `context/pages.jsonl` y `context/documents.jsonl`. Los objetos que sirven sólo como contexto se mantienen separados del contenido principal y conservan identidad, revisión y relación documental. Una futura etapa `vision_describe` podrá decidir cuánto contexto utilizar sin volver a consultar la base.

Las opciones secundarias de imágenes permanecen ocultas hasta activar **Elegir qué imágenes incluir**. Sin abrirlas se incluyen páginas completas, recortes regionales y figuras.

## Persistencia y migración

EXP-01 reutiliza `CorpusExportRun.profile_snapshot_json` para registrar las opciones de la ejecución visual. No agrega tablas ni columnas. La revisión de base continúa en `0046_audiovisual_timeline_annotations`.

**0.88.0 no requiere `db-upgrade`. No ejecutar `db-upgrade` por esta versión.**

## Validación cerrada

La validación manual sobre el proyecto descartable confirmó:

- 1 registro textual principal;
- 1 página completa;
- 1 recorte regional;
- 1 figura;
- 2 objetos textuales de contexto;
- separación correcta entre contenido principal y contexto;
- `quick_check: ok` y cero violaciones de claves foráneas;
- SHA-256 del original y de la página fuente idénticos: `25d1d8b6b483ec915e547648708be185e6f9a193ef88615aff71b3a8f663f41c`;
- huellas internas del ZIP válidas y fuentes sin modificaciones.

`project_data` no participó de la validación y permaneció en `0046_audiovisual_timeline_annotations`. `EXP-01` queda cerrado en 0.88.0.
