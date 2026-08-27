# Actualización actual - Archive Workbench 0.89.0 RC50

## Alcance de RC50

La validación manual de RC49 cerró `PILOT-01Z`: el grafo quedó funcionalmente verde y la evaluación analítica profunda se pospone al uso en investigaciones concretas. La primera pasada de **Exportar corpus** también quedó verde para 138 documentos en JSONL y para el paquete texto + imágenes. El archivo JSONL real permitió revisar además si la salida resulta comprensible fuera de Archive Workbench.

RC50 normaliza la exportación de **transcripciones de audio y video** con el mismo recorrido general usado para documentos: `Configurar qué exportar` → `Revisar textos que se exportarán` → `Crear archivo de exportación` → `Historial de exportaciones`. La exportación audiovisual deja de depender de una descarga inmediata: crea primero un archivo administrado dentro de `exports/`, registra ruta, cantidad, tamaño, SHA-256, estado del corpus y configuración usada; la descarga queda disponible después como comodidad secundaria sobre ese archivo ya registrado.

La configuración audiovisual permite elegir audios/videos, usar la última transcripción completada de cada medio o todas las corridas completadas, seleccionar texto corregido/original, estados de revisión, marcas temporales y formato JSONL/CSV. Las transcripciones descartadas siguen fuera del uso normal.

RC50 también amplía de forma aditiva el contrato de los registros documentales JSONL/CSV. Conserva todas las claves existentes y agrega `export_schema_version=1.1`, proyecto, configuración exacta de exportación, nombres y SHA-256 de originales, tipos de medio, procedencia, título/nivel archivístico, páginas incluidas, `source_documents` que preserva la correspondencia entre cada original y sus identificadores, y `object_provenance` con documento, fuente, página, orden, tipo, estados y fuente del texto de cada bloque. Cada archivo materializado agrega además `export_run_id`, fecha de exportación y `corpus_state_sha256` para identificar la corrida y el estado exacto del corpus. Esto permite interpretar cada registro con mucha menos dependencia del modelo interno de Archive Workbench. No se modifica la base de datos.

`PILOT-01AA` queda abierto sólo para validar estas dos ampliaciones de exportación. Después el piloto continúa con **asignación y revisión cruzada**.

## Actualización desde RC49

```bash
cd ~/projects/archive_app
source .venv/bin/activate
TMP_DIR="$(mktemp -d)"
unzip -q ~/Downloads/archive_workbench_v0.89.0_RC50.zip -d "$TMP_DIR"
python "$TMP_DIR/scripts/apply_candidate_update.py" --source "$TMP_DIR" --target ~/projects/archive_app
python -m pip install --no-build-isolation -e ".[dev,extraction,streamlit,semantic,tiff,discovery,audiovisual,platform]"
python -c "import archive_workbench; print(archive_workbench.__version__)"
archive-workbench db-status /home/alex/projects/archive_app/pilot_data
```

Resultado esperado: versión de código `0.89.0` y revisión `0047_authority_relation_profiles`.

**No hay migración nueva entre RC49 y RC50. No ejecutar `db-upgrade`.**

## Gate automatizado focal

No repetir búsqueda, grafo ni exportaciones documentales ya validadas. Para RC50 alcanza con:

```bash
cd ~/projects/archive_app
source .venv/bin/activate
pytest -q \
  tests/test_corpus_export.py::test_run_export_writes_jsonl_and_registers_hashes \
  tests/test_corpus_export.py::test_run_export_writes_csv_lists_as_json \
  tests/test_corpus_export.py::test_visual_zip_exports_pages_regions_figures_and_structured_context \
  tests/test_audiovisual.py::test_audio_registration_transcription_review_search_export_and_ocr_exclusion \
  tests/test_audiovisual.py::test_discarded_transcription_is_removed_from_normal_use_and_can_be_restored \
  tests/test_audiovisual.py::test_audiovisual_export_is_materialized_in_project_and_registered_in_history \
  tests/test_audiovisual_timeline.py::test_timeline_marks_survive_retranscription_and_travel_in_state \
  tests/test_ui_navigation.py::test_audiovisual_export_uses_configure_preview_create_history_flow \
  tests/test_documentation.py::test_current_update_guide_describes_0890_rc50_export_normalization_and_resume \
  tests/test_packaging.py::test_candidate_update_reconciles_only_known_relocations && \
pytest --collect-only -q
```

La suite completa corresponde exclusivamente a Alex.

## Validación manual específica de RC50

No repetir la exportación JSONL de 138 documentos ni el ZIP texto + imágenes ya validados.

1. Abrir `Exportar corpus` → `Segmentos de audio y video`.
2. Comprobar que el recorrido use las mismas cuatro etapas que documentos y que permita elegir medios, versiones de transcripción, versión del texto, estados de revisión y marcas temporales.
3. Revisar la muestra y crear un JSONL o CSV con una selección pequeña. El archivo debe quedar dentro de `exports/` y aparecer en `Historial de exportaciones`; la descarga debe aparecer sólo después de crear el archivo.
4. Abrir un JSONL documental nuevo de muestra y comprobar que conserva las claves anteriores y agrega contexto autoexplicativo como `export_configuration`, `source_documents`, `original_filenames`, `original_sha256s`, `hierarchy_path`, `archival_unit_title`, `page_numbers`, `object_provenance`, `export_run_id` y `corpus_state_sha256`.

Si estos puntos quedan verdes, cerrar `PILOT-01AA` y continuar directamente con **asignación y revisión cruzada**.
