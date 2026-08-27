# Actualización actual - Archive Workbench 0.89.0 RC43

## Alcance de RC43

La validación de interfaz de RC42 señaló que `Opciones de esta transcripción` no respeta la jerarquía visual acordada: agrupa bajo un rótulo genérico una acción excepcional y la hace competir demasiado pronto con el trabajo normal sobre la versión activa.

RC43 no cambia la lógica de descarte/restauración. Retira ese contenedor y reorganiza el recorrido: escucha, corrección, anotación y evaluación aparecen primero; al final quedan cerrados por defecto `Descartar esta versión de la transcripción` y `Transcripciones descartadas (n)`. También incorpora el criterio general a `.assistant/05_CRITERIOS_INTERFAZ.md`.

No se modifica `pilot_data` ni el esquema de base. Continúa `0047_authority_relation_profiles`.

## Actualización desde RC42

```bash
cd ~/projects/archive_app
source .venv/bin/activate
TMP_DIR="$(mktemp -d)"
unzip -q ~/Downloads/archive_workbench_v0.89.0_RC43.zip -d "$TMP_DIR"
python "$TMP_DIR/scripts/apply_candidate_update.py" --source "$TMP_DIR" --target ~/projects/archive_app
python -m pip install --no-build-isolation -e ".[dev,extraction,streamlit,semantic,tiff,discovery,audiovisual,platform]"
python -c "import archive_workbench; print(archive_workbench.__version__)"
archive-workbench db-status /home/alex/projects/archive_app/pilot_data
```

Resultado esperado: versión de código `0.89.0` y revisión `0047_authority_relation_profiles`.

**No hay migración nueva entre RC42 y RC43. No ejecutar `db-upgrade`.**

## Gate automatizado focal

No repetir tandas grandes. Para RC43 alcanza con:

```bash
cd ~/projects/archive_app
source .venv/bin/activate
pytest -q \
  tests/test_audiovisual.py::test_discarded_transcription_is_removed_from_normal_use_and_can_be_restored \
  tests/test_audiovisual.py::test_audiovisual_ui_exposes_simple_review_flow_and_hidden_technical_options && \
pytest --collect-only -q
```

La suite completa corresponde exclusivamente a Alex y no forma parte de esta revalidación focal.

## Validación manual específica de RC43

No repetir recorridos ya cerrados.

1. Entrar en **Transcribir audio y video** y seleccionar una transcripción completada. El recorrido principal de escucha, corrección, anotación y evaluación debe aparecer antes que cualquier acción de descarte.
2. Comprobar que ya no existe `Opciones de esta transcripción`. Hacia el final del recorrido deben aparecer cerrados `Descartar esta versión de la transcripción` y, si existen versiones descartadas, `Transcripciones descartadas (n)`.
3. No hace falta descartar una versión real sólo para probar la interfaz. Si ya existe una versión razonable para la prueba, el ciclo descarte/restauración puede validarse allí; en caso contrario, `PILOT-01V` queda pendiente sin crear datos artificiales.
4. Después continuar con la prueba normal de **Búsqueda textual**.
