# Actualización actual — Archive Workbench 0.82.0

**Fecha:** 2026-08-07
**Bloque:** `OCR-01E` — dewarp conservador sobre derivados OCR
**Revisión de base:** `0044_layout_structure_review`

La versión agrega un modo geométrico que evalúa curvatura vertical suave en páginas escaneadas. El cálculo compara perfiles de tinta en franjas verticales, ajusta una curva cuadrática y aplica una malla de remapeo únicamente cuando existen soporte textual, desplazamiento suficiente, ajuste estable y confianza superior al umbral.

## Estado de la versión

La implementación y las validaciones confirman:

- detección y corrección de una página curva sintética controlada;
- omisión del dewarp en una página plana;
- conservación del original y de la previsualización;
- derivado OCR, máscara de líneas y diagnóstico de curvatura separados;
- registro por página de confianza, desplazamiento máximo, franjas con soporte, coeficientes y motivo de aplicación u omisión;
- reutilización idempotente de una corrida equivalente;
- ausencia de selección canónica automática.

La validación manual confirmó el dewarp de la página curva, la omisión de la página plana, los cuatro derivados trazables y la integridad de los originales. La validación específica de la corrección confirmó además que abrir el diagnóstico geométrico conserva los documentos seleccionados y las opciones de preparación.

`OCR-01E` queda cerrada en 0.82.0. Dentro de `OCR-01` resta el benchmark ampliado de Tesseract, Docling y Surya con verdad terreno.

## Alcance conservador

- Solo se modela un desplazamiento vertical suave que varía a lo ancho de la página.
- No se reconstruyen letras, trazos, perspectiva, pliegues locales ni superficies tridimensionales.
- Un candidato con soporte o confianza insuficientes se registra y se omite.
- El original y la previsualización no se transforman.
- La corrección se aplica únicamente al derivado OCR reproducible.
- El diagnóstico gráfico se conserva como un activo separado.

## Base de datos

No hay migración. `PreprocessingRun`, `DerivativeAsset`, `options_json`, `analysis_json` y `transformations_json` ya conservan el perfil, los derivados y la decisión geométrica. La revisión continúa en `0044_layout_structure_review`.

## Uso

1. Abrir **Procesar documentos > Ejecutar**.
2. Elegir **Preparar páginas**.
3. Seleccionar los documentos.
4. En **Corrección geométrica**, elegir **Orientación, inclinación, curvatura y líneas (conservador)**.
5. Pulsar **Ejecutar tarea**.
6. Activar **Mostrar diagnóstico geométrico vigente**.
7. Comparar **Previsualización sin cambios**, **Derivado OCR**, **Máscara de líneas eliminadas** y **Diagnóstico de curvatura**.

## Archivos principales

```text
src/archive_workbench/preprocessing_dewarp.py
src/archive_workbench/preprocessing_geometry.py
src/archive_workbench/preprocessing.py
src/archive_workbench/processing.py
src/archive_workbench/processing_app.py
scripts/create_dewarp_validation_project.py
scripts/verify_dewarp_validation_project.py
tests/test_dewarp.py
```
