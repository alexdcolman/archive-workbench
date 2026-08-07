# Actualización actual — Archive Workbench 0.84.0

**Fecha:** 2026-08-07
**Bloque:** `AV-01` — registro local de audio y video y transcripción segmentada
**Revisión de base:** `0045_audiovisual_transcription`
**Estado:** implementada, validada y cerrada.

## Qué incorpora

Archive Workbench registra archivos locales de audio y video mediante el mismo catálogo e identidad digital ya existentes, conservando original, ruta, SHA-256 y relación archivística. FFprobe registra formato, códecs, canales, frecuencia, resolución y duración. FFmpeg crea solamente derivados técnicos para transcripción o reproducción cuando son necesarios; el original no se modifica.

La transcripción usa corridas trazables y segmentos temporales con `start_time`, `end_time`, texto original, texto corregido, estado de revisión e historial append-only. La vista **Transcribir audio y video** mantiene como núcleo el reproductor, el segmento vigente y **Texto corregido**. **Velocidad de reproducción** e **Ir al inicio del segmento** están visibles; **Editar datos descriptivos**, **Opciones técnicas** y **Anotar entidades en este segmento** permanecen cerrados por defecto.

El backend es intercambiable. El recorrido local inicial usa `faster-whisper`; CPU usa `compute_type=int8` por defecto. La dependencia Python se instala con el extra `audiovisual`; FFmpeg y FFprobe son requisitos de sistema para AV-01. El runtime OCR existente no depende de `faster-whisper`.

Los segmentos participan en búsqueda literal, exportación CSV/JSONL y menciones vinculables a autoridades existentes. Los paquetes de adopción de estado usan contrato 1.1 cuando existe contenido audiovisual y conservan corridas, segmentos, revisiones y menciones; un proyecto sin AV mantiene la huella histórica anterior.

## Migración

`0045_audiovisual_transcription` agrega las tablas `audiovisual_media`, `audiovisual_derivative_assets`, `transcription_runs`, `transcript_segments`, `transcript_segment_revisions` y `segment_entity_mentions`. No transforma las tablas OCR ni convierte tiempos en páginas.

La migración fue probada primero sobre una base descartable `0044 → 0045`, conservando conteos previos, con `PRAGMA quick_check: ok`, cero violaciones de claves foráneas y las seis tablas audiovisuales presentes. La migración de `project_data` se realiza solamente durante el cierre local de 0.84.0, después de crear y verificar un backup SQLite y antes del commit/tag.

## Validación real

La validación descartable confirmó reproducción de audio y video, velocidades configurables, salto al inicio temporal del segmento, corrección persistente, mención de entidad, búsqueda con navegación directa al segmento, exportación JSONL y una corrida real `faster-whisper` `tiny` en CPU con `int8` sobre video.

RC1 reveló dos regresiones de interfaz: el botón **Ir al inicio del segmento** no movía efectivamente el reproductor y **Abrir** desde búsqueda no aplicaba el destino audiovisual. RC2 corrigió ambos problemas y la revalidación manual fue satisfactoria.

El diagnóstico final informó `quick_check: ok`, cero violaciones de claves foráneas, SHA-256 intactos de `testimonio_controlado.wav` y `testimonio_controlado.mp4`, una corrección esperada, la mención `Memoria`, cinco segmentos exportables y una corrida CPU completada con dos segmentos de video. `AV-01` queda cerrado en 0.84.0.

`OCR-01` continúa cerrado en 0.83.0 y no se reabrió durante esta validación.

## Continuidad inmediata

El siguiente bloque es `AV-02`, incorporación autorizada desde YouTube y otras plataformas al circuito local de AV-01. La prueba inicial prevista usará, si el video concreto resulta accesible y autorizado, material del canal `https://www.youtube.com/channel/UCsZG_7l0cYIEtJNhajrFPYg`.

Después se ejecutará `AV-03`: evaluación reproducible de transcripción de video real para observar calidad, segmentación, tiempos y correcciones humanas y decidir optimizaciones sólo a partir de esa evidencia.
