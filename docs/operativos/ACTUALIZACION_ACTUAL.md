# Actualización actual - Archive Workbench 0.89.0 RC79

## Alcance de RC79

RC79 continúa `OPS-01` después de la validación material de la transcripción audiovisual GPU en la imagen RC77. No cambia el backend `faster-whisper`, la segmentación ni la interfaz. Corrige la medición de VRAM máxima cuando Archive Workbench se ejecuta dentro de Docker.

La corrida real `large-v3` + CUDA `float16`, VAD activado y `beam_size=5` completó el medio autorizado `RememorArte Horacio BAU` con `faster-whisper 1.2.1`, produjo 64 segmentos y persistió como `completed`. La primera ejecución dentro del espacio administrado incluyó la descarga inicial del modelo `Systran/faster-whisper-large-v3` al caché persistente de `ArchiveWorkbenchData/Settings`; por eso el tiempo total de esa primera corrida no se interpreta como benchmark puro de inferencia.

El defecto observado fue sólo de instrumentación: `nvidia-smi --query-compute-apps` informa PIDs del anfitrión, mientras `os.getpid()` dentro del contenedor pertenece al espacio de nombres de PID del contenedor. El monitor anterior comparaba ambos valores y registraba `peak_gpu_memory_mib=null` aunque CTranslate2 estuviera ejecutando CUDA. RC79 mantiene la coincidencia directa de PID para instalaciones nativas y, en runtime administrado, usa como fallback el único proceso de cómputo cuyo nombre ejecutable coincide con el proceso Python actual. Si hay más de un candidato, deja la métrica sin medir antes que atribuir VRAM ajena.

La validación material anterior de Surya CPU/GPU, el cierre automático de `llama-server` y la corrección de `extraction-doctor` de RC78 no cambian.

## Tags de esta candidata

- CPU: `ghcr.io/alexdcolman/archive-workbench:0.89.0-rc79-cpu`;
- NVIDIA GPU: `ghcr.io/alexdcolman/archive-workbench:0.89.0-rc79-gpu`.

## Persistencia y base

No cambia SQLite ni el modelo de proyecto. Continúa `0047_authority_relation_profiles` y no hay migración. **No ejecutar `db-upgrade`.**

`WEB-01` permanece parcial y queda pausado hasta terminar la distribución multiplataforma; RC79 no modifica el sitio público. No se incorporan capturas hasta realizar esa reescritura para lectores sin conocimiento previo.

## Gate automatizado focal

La suite completa corresponde exclusivamente a Alex. Para RC79 el gate se limita a la medición audiovisual modificada, distribución, documentación, empaquetado y recopilación completa sin ejecución:

```bash
pytest -q \
  tests/test_transcription_evaluation.py \
  tests/test_container_distribution.py \
  tests/test_documentation.py \
  tests/test_packaging.py \
&& pytest --collect-only -q
```

## Validación manual específica

No repetir la transcripción audiovisual completa de `RememorArte Horacio BAU`, ni las extracciones Surya CPU/GPU, ni la prueba de pestañas: esos recorridos ya quedaron materialmente verdes y RC79 no modifica sus backends. La corrección de `peak_gpu_memory_mib` puede confirmarse en una corrida GPU corta futura, incluida una prueba multiplataforma pendiente, sin volver a procesar ahora el material completo.

El siguiente gate material de `OPS-01` es comprobar persistencia al detener y volver a abrir la distribución y luego continuar con los hosts Windows/macOS previstos. También siguen pendientes la publicación real de imágenes y las comprobaciones limpias de las carpetas de importación/creación administrada.
