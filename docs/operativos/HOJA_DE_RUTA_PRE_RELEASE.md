# Hoja de ruta pre-release y líneas paralelas — Archive Workbench

**Estado preparado:** 2026-08-08
**Versión de referencia:** 0.88.2

Esta hoja ordena el trabajo restante hasta v1.0. El detalle y el estado de cada bloque se mantienen en [`PENDIENTES_ACTIVOS.md`](PENDIENTES_ACTIVOS.md). Las líneas paralelas no bloquean la publicación inicial salvo decisión explícita posterior.

## Secuencia principal hasta v1.0

`OCR-01` quedó implementado, validado y cerrado en 0.83.0. `AV-01` quedó implementado, validado y cerrado en 0.84.0. `AV-02` quedó implementado, validado y cerrado en 0.85.0. `AV-03` quedó implementado, validado y cerrado en 0.86.0. `INT-01` quedó implementado, validado y cerrado en 0.87.0. `EXP-01` quedó implementado, validado y cerrado en 0.88.0.

1. Ejecutar `PILOT-01` sobre un proyecto real y persistente con materiales DIPPBA, APM-Chubut y testimonios audiovisuales.
2. Ejecutar `UX-02` sobre la aplicación completa y el corpus real del piloto.
3. Completar `WEB-01`: sitio público de Archive Workbench en GitHub Pages, tutorial, README ilustrado y referencia técnica pública.
4. Ejecutar `QA-01` junto con `OPS-02`.
5. Preparar `OPS-01` y verificar perfiles de instalación.
6. Cerrar `OPS-03`, congelar contratos públicos y preparar la candidata a v1.0.

## Línea paralela vinculada

`GIAR-01` puede comenzar en paralelo con `PILOT-01`, porque reutiliza materiales, autoridades, unidades archivísticas y resultados de investigación reales. Su base debe vivir en un proyecto separado y persistente de Archive Workbench. La construcción del sitio público del Grupo de Investigación en Archivos de la Represión se realizará cuando el modelo de datos y los contenidos hayan sido revisados; no bloquea por sí sola la v1.0 de Archive Workbench.

El alcance completo se documenta en [`PROYECTO_PARALELO_GIAR.md`](../referencia/PROYECTO_PARALELO_GIAR.md).

## Trabajo posterior al release inicial

`AI-01` diseñará las etapas concretas del pipeline de análisis con LLM, sus contratos, ingeniería de contexto y trazabilidad. En ese momento se revisará el repositorio adicional que provea Alex para decidir qué componentes pueden reutilizarse. `vision_describe` consumirá las imágenes y recortes producidos por `EXP-01`.

`AI-02` agregará recuperación y generación trazables sobre corpus sistematizados, sin convertir respuestas automáticas en fuente de verdad.
