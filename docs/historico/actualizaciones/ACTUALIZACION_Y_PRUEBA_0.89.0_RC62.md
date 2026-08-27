# Actualización actual - Archive Workbench 0.89.0 RC62

## Alcance de RC62

La validación manual de RC61 consideró clara la nueva arquitectura de **Audio y video**, incluida la separación entre **Incorporar audio o video** y **Transcribir y revisar**, y dejó un único ajuste textual antes de cerrar esa pasada: la incorporación local no indicaba qué formatos de archivo admite Archive Workbench.

RC62 agrega una aclaración breve únicamente dentro de **Audio y video > Incorporar audio o video > Desde esta computadora**. La lista visible se deriva de `AUDIO_EXTENSIONS` y `VIDEO_EXTENSIONS`, las mismas constantes usadas por el selector y la detección audiovisual, para evitar una segunda lista que pueda quedar desactualizada.

Formatos admitidos:

- **Audio:** AAC, AIF, AIFF, ALAC, FLAC, M4A, MP3, OGG, OPUS, WAV y WMA.
- **Video:** AVI, M2TS, M4V, MKV, MOV, MP4, MPEG, MPG, MTS, TS, WEBM y WMV.

La aclaración no modifica el circuito de registro, FFmpeg, reproducción, transcripción, plataforma ni persistencia. El método **Desde una plataforma web** y el registro local mediante `register_external_file()` permanecen sin cambios. Los formatos que el navegador no reproduce de manera directa siguen usando el derivado de reproducción ya existente. No hay migración.

`PILOT-01E` permanece **PARCIAL** únicamente hasta comprobar manualmente que esta aclaración final se ve en el lugar esperado y que la sección audiovisual sigue resultando clara. No se repiten incorporaciones, transcripciones ni pruebas funcionales ya cerradas.

## Actualización desde RC61

```bash
cd ~/projects/archive_app
source .venv/bin/activate
TMP_DIR="$(mktemp -d)"
unzip -q ~/Downloads/archive_workbench_v0.89.0_RC62.zip -d "$TMP_DIR"
python "$TMP_DIR/scripts/apply_candidate_update.py" --source "$TMP_DIR" --target ~/projects/archive_app
python -m pip install --no-build-isolation -e ".[dev,extraction,streamlit,semantic,tiff,discovery,audiovisual,platform]"
python -c "import archive_workbench; print(archive_workbench.__version__)"
archive-workbench db-status ~/projects/archive_app/pilot_data
```

Resultado esperado: versión de código `0.89.0` y revisión `0047_authority_relation_profiles`.

**No hay migración nueva entre RC61 y RC62. No ejecutar `db-upgrade`.**

## Gate automatizado focal

No repetir transcripciones, incorporación audiovisual real ni recorridos ya cerrados. Para RC62 corresponde ejecutar únicamente la regresión de interfaz/formato audiovisual, documentación/empaquetado y `pytest --collect-only -q`. La suite completa corresponde exclusivamente a Alex.

## Validación manual específica de RC62

Usar el mismo `pilot_data`.

1. Abrir **Audio y video > Incorporar audio o video**.
2. Elegir **Desde esta computadora**.
3. Comprobar que aparece una aclaración breve con los formatos admitidos de audio y video.
4. No hace falta elegir ni incorporar ningún archivo nuevo.

Si la aclaración resulta clara y la sección sigue ordenada, `PILOT-01E` puede cerrarse. El siguiente bloque sustantivo de `PILOT-01` continúa siendo `PILOT-01A`.
