# Benchmark OCR con verdad terreno

**Bloque:** `OCR-01F`
**Versión candidata:** 0.83.0

## Propósito

El benchmark compara Tesseract, Docling y Surya sobre exactamente los mismos derivados OCR y las mismas páginas transcritas manualmente. No selecciona una corrida canónica, no inicializa la capa editable y no modifica los originales.

La comparación automática mide fidelidad textual mediante CER y WER. La evaluación de layout, orden de lectura, tablas, formularios, sellos, manuscritos e imágenes continúa siendo una revisión manual sobre las salidas conservadas por cada motor.

## Verdad terreno

Las transcripciones se guardan en:

```text
ground_truth/ocr/<source_key>/page_0001.txt
```

Cada benchmark copia dentro de su propia salida la versión exacta de la verdad terreno usada y registra su SHA-256. Los textos deben representar lo que la página dice, no imitar errores ni convenciones particulares de un motor.

Para CER/WER se normalizan Unicode y espacios según `config/ocr_benchmark_truth.yaml`. Por defecto se usa NFC, se consideran equivalentes las secuencias de espacio y se conservan mayúsculas, minúsculas y acentos.

## Motores

El perfil estándar usa los perfiles de extracción ya existentes:

- Tesseract: `config/extraction_tesseract.yaml`;
- Docling: `config/extraction_docling_es.yaml`;
- Surya: `config/extraction_surya_es.yaml`.

El diagnóstico del benchmark exige que los tres motores solicitados estén realmente disponibles. No se aplica fallback entre motores porque eso invalidaría la comparación. Los fallbacks de dispositivo dentro del mismo motor pueden quedar registrados en sus logs.

## Métricas

`CER = distancia de Levenshtein entre caracteres / caracteres de referencia`.

`WER = distancia de Levenshtein entre palabras / palabras de referencia`.

Los valores pueden superar 1 cuando las inserciones son numerosas. Un valor menor indica menos ediciones respecto de la transcripción de referencia. El informe conserva también distancias absolutas, recuentos de caracteres y palabras y tiempo de ejecución.

## Salida

Cada corrida se guarda bajo:

```text
ocr_benchmarks/<digital_object_id>/truth_<benchmark_id>/
```

Incluye:

- `manifest.json`, con perfiles, hashes, versiones y métricas;
- `summary.md`, resumen legible;
- `summary.csv`, tabla reutilizable;
- `summary.json`, representación completa;
- copia de la verdad terreno usada;
- texto comparado, salida cruda y log de cada motor por página.

El orden del resumen sirve para inspección. No declara un motor universalmente mejor ni cambia la selección canónica de ninguna página.
