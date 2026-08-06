# Actualización actual — Archive Workbench 0.81.0

**Fecha:** 2026-08-06
**Bloque:** `OCR-01D` — OCR regional y zonas documentales
**Revisión de base:** `0044_layout_structure_review`

La versión 0.81.0 integra **Procesar documentos > OCR regional** como un recorrido visual de seis pasos. Permite elegir documento y página, cargar una plantilla o dibujar zonas, clasificarlas, decidir entre OCR y conservación manual, revisar la lista y crear una extracción candidata.

## Estado de cierre

`OCR-01D` quedó validada y cerrada. La prueba manual confirmó:

- una corrida regional terminada;
- una página y seis zonas;
- encabezado, texto principal y número de página procesados con OCR;
- sello, firma e ilustración conservados como regiones manuales;
- seis recortes y al menos un objeto por zona;
- `manifest.json` y `regions.jsonl` válidos bajo el contrato regional 1.1;
- selección canónica vacía;
- PDF original conservado por SHA-256;
- `project_data` sin acceso ni modificaciones durante la validación.

La RC2 corrigió la colisión de `reading_order` observada al agregar una región manual a una plantilla con huecos. La interfaz asigna el primer múltiplo de diez libre y normaliza borradores externos con órdenes repetidos.

## Invariantes

- El original y la previsualización no se modifican.
- La plantilla completa queda dentro del manifiesto.
- Se conservan recortes, archivos crudos y `regions.jsonl`.
- Toda ejecución visual usa `selection_policy=never`.
- La nueva corrida no cambia la selección canónica ni la capa editable.
- Una región manual no inventa trazos ni transcripción.

## Base de datos

No hay migración. La revisión continúa en `0044_layout_structure_review`, porque `ExtractionRun`, `ExtractionRegion`, los objetos extraídos y los manifiestos ya conservan geometría, modo, clasificación, procedencia y archivos derivados.

## Audiovisual planificado

`AV-01` incorporará archivos locales de audio y video en formatos habituales, reproducción integrada con velocidades configurables y transcripción segmentada revisable en una pantalla simple. `AV-02` agregará la incorporación opcional y autorizada desde YouTube y otras plataformas, pero reutilizará el mismo circuito local de reproducción, transcripción y corrección.

## Uso cotidiano

1. Preparar el documento en **Procesar documentos > Ejecutar**.
2. Abrir **Procesar documentos > OCR regional**.
3. Elegir documento y página.
4. Cargar una plantilla guardada o pulsar **Dibujar una zona** sobre la imagen.
5. Describir la zona y agregarla a la lista.
6. Crear la candidata.
7. Compararla en **Selección canónica**. La creación de la candidata no la selecciona.

## Archivos principales

```text
src/archive_workbench/contracts/regions.py
src/archive_workbench/regional_workflow.py
src/archive_workbench/region_canvas.py
src/archive_workbench/region_extraction.py
src/archive_workbench/processing_app.py
src/archive_workbench/cli.py
scripts/create_regional_ocr_validation_project.py
scripts/prepare_regional_ocr_validation_resume.py
scripts/verify_regional_ocr_validation_project.py
scripts/update_assistant_guidance_0810.py
tests/test_regional_workflow.py
tests/test_region_extraction.py
tests/test_ui_navigation.py
```
