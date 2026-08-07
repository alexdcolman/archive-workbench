# Actualización actual — Archive Workbench 0.85.0

**Fecha:** 2026-08-07
**Bloque cerrado:** `AV-02` — incorporación autorizada desde YouTube y otras plataformas
**Próximo bloque:** `AV-03` — evaluación reproducible y optimización de transcripción de video real
**Revisión de base:** `0045_audiovisual_transcription` (sin migración nueva en 0.85.0)

## Qué incorpora

La versión 0.85.0 agrega una extensión opcional basada en `yt-dlp` para descargar un audio o video autorizado y registrarlo inmediatamente mediante el circuito local de AV-01. No crea un sistema paralelo: el archivo incorporado pasa por `DigitalObject`, `FileInstance`, `SourceRegistration` y `AudiovisualMedia`, y desde allí usa la reproducción y la transcripción ya existentes.

`SourceRegistration.source_payload_json` conserva URL solicitada/canónica, plataforma e identificador, canal/uploader, fecha de publicación, formatos seleccionados, versión de `yt-dlp`, ruta y extensión incorporadas, SHA-256, tamaño, fecha de descarga y condiciones de acceso/autorización. La exportación audiovisual añade esos campos de procedencia a cada segmento.

## Interfaz

En **Transcribir audio y video** aparece el panel cerrado **Incorporar desde plataforma**. El recorrido visible pide URL, unidad archivística, tipo de incorporación, condiciones de acceso/autorización y confirmación explícita de que el proyecto puede incorporar el material. La incorporación no inicia una transcripción automáticamente. Los errores de campos obligatorios se muestran con mensajes legibles y no exponen errores internos de Pydantic.

## Dependencias

El extra opcional `platform` instala `yt-dlp[default,deno]>=2026.7.4,<2027`, incluido Deno para el recorrido de YouTube. FFmpeg/FFprobe continúan siendo requisitos de sistema. AV-01, OCR y los demás runtimes no dependen de este extra.

## Base de datos

AV-02 no requiere migración. La revisión continúa en `0045_audiovisual_transcription`, publicada con 0.84.0.

## Validación real

La validación manual se realizó sobre una base descartable fuera del repositorio con el video de YouTube `RememorArte Horacio BAU` (`CwWKigBOfjQ`) del canal `Centro Cultural por la Memoria Trelew` (`UCsZG_7l0cYIEtJNhajrFPYg`). La incorporación produjo un MP4 de 436.221 s y preservó procedencia, condiciones de acceso y SHA-256 `f187eaa71718ed2b016ec3af01e58102d19537d758fdc5c21df46f00378ec7ba`. El diagnóstico final informó `quick_check: ok`, cero violaciones de claves foráneas y `transcription_run_count: 0`; `project_data` permaneció en `0045_audiovisual_transcription` sin contenido audiovisual nuevo.

RC1 mostró un error de presentación cuando faltaba un campo obligatorio: la UI exponía el `ValidationError` de Pydantic. RC2 lo reemplazó por mensajes comprensibles para una persona no técnica y la revalidación fue satisfactoria. `AV-02` queda cerrado. La transcripción del video real, su evaluación y cualquier optimización basada en evidencia corresponden a `AV-03`.
