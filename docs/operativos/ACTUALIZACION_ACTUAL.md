# Actualización actual — Archive Workbench 0.83.0

**Fecha:** 2026-08-07
**Bloque:** `OCR-01F` — benchmark Tesseract, Docling y Surya con verdad terreno
**Revisión de base:** `0044_layout_structure_review`

La versión 0.83.0 cierra `OCR-01` con un benchmark reproducible que compara Tesseract, Docling y Surya sobre exactamente los mismos derivados OCR y páginas transcritas manualmente. Calcula CER y WER, conserva tiempo de ejecución, versiones, perfiles, salidas crudas y una copia con SHA-256 de la verdad terreno utilizada.

## Estado validado

La validación real confirmó:

- Tesseract 5.3.4, Docling 2.114.0 y Surya 0.22.1 disponibles en el mismo entorno;
- una página controlada evaluada por los tres motores sobre la misma verdad terreno;
- CER 0.0000 y WER 0.0000 para los tres motores en ese caso;
- tiempos registrados de 0.27 s para Tesseract, 23.07 s para Docling y 209.84 s para Surya;
- conservación del texto comparado, salida cruda, versiones, perfiles y métricas;
- copia exacta de la verdad terreno con SHA-256 verificable;
- TIFF original intacto;
- selección canónica vacía y ausencia de escrituras sobre la capa editable;
- `project_data` sin modificaciones durante la validación;
- ausencia de migración de base.

Los tiempos corresponden al caso controlado y no constituyen una comparación general de rendimiento entre motores.

## Verdad terreno

Cada página de referencia se guarda como:

```text
ground_truth/ocr/<source_key>/page_0001.txt
```

El benchmark copia el archivo usado dentro de su salida y registra su SHA-256. La referencia describe el contenido correcto de la página y no reproduce convenciones ni errores de un motor específico.

## Métricas

- `CER`: distancia de Levenshtein entre caracteres dividida por la longitud de la referencia.
- `WER`: distancia de Levenshtein entre palabras dividida por la cantidad de palabras de referencia.
- Tiempo acumulado por motor y por página.

CER/WER evalúan fidelidad textual. Layout, orden de lectura y estructuras visuales siguen requiriendo inspección humana de las salidas.

## Comandos

```text
archive-workbench ocr-benchmark-truth-doctor
archive-workbench ocr-benchmark-truth
```

La referencia técnica está en `docs/referencia/BENCHMARK_OCR_VERDAD_TERRENO.md`.

## Base de datos

No hay migración. El benchmark lee el catálogo y los derivados vigentes y escribe únicamente bajo `ocr_benchmarks/`. La revisión continúa en `0044_layout_structure_review`.
