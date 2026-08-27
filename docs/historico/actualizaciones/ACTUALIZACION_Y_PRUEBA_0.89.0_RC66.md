# Actualización actual - Archive Workbench 0.89.0 RC66

## Alcance de RC66

La validación manual de RC65 confirma el modelo descriptivo de custodia, conjuntos documentales y procedencia audiovisual y cierra `PILOT-01A`. Con ese cierre, `PILOT-01` queda completado para el pre-release; `PILOT-01N` continúa como trabajo post-release y no bloquea la v1.0.

RC66 inicia `DISC-03` sin reabrir el recorrido funcional del piloto. El proveedor local determinista pasa a tener dos versiones reproducibles:

- `local_rules_v1` queda preservado sin cambios para perfiles, corridas y continuidades históricas;
- `local_rules_v2` es la versión local vigente para perfiles nuevos y refina reglas de actores, espacios, tiempos, acontecimientos, acciones/procesos y obras;
- la continuidad por redetección reutiliza la versión local que originó el candidato, incluso cuando el candidato histórico ya fue proyectado;
- `config/discovery_evaluation_corpus_disc03.jsonl` agrega 46 controles heterogéneos con casos positivos, negativos, límites y una tanda holdout no usada para diseñar el primer ajuste;
- la auditoría sobre las seis familias cubiertas por el proveedor local pasa de F1 micro `0.675676` en v1 a `0.911765` en v2; v2 conserva un falso positivo y cinco falsos negativos en la tanda completa, por lo que el límite sigue explícito;
- los informes de evaluación conservan también la procedencia del registro en cada predicción para que los errores puedan auditarse por caso y género documental.

Los principales errores corregidos son años dentro de identificadores compuestos, `archivo` usado como sustantivo, fórmulas como `manifestación de interés` y `acto administrativo`, citas directas o apodos confundidos con obras, y omisiones de algunos nombres, siglas, topónimos y expresiones temporales en contextos acotados. Los controles holdout mantienen abiertos casos como un año usado como número de modelo, nombres en otra posición sintáctica, topónimos desnudos, obras sin clase introductora, variantes léxicas de acontecimientos y verbos flexionados.

`DISC-03` queda **PARCIAL**: falta contrastar estas reglas con material real del piloto o con una exportación real anotada. El corpus de 46 controles es un benchmark de regresión diverso, no se presenta como representativo de los 138 documentos.

No se modifica `pilot_data`, no se ejecuta descubrimiento sobre el proyecto real y no hay migración de base. Continúa `0047_authority_relation_profiles`.

## Actualización desde RC65

```bash
cd ~/projects/archive_app
source .venv/bin/activate
TMP_DIR="$(mktemp -d)"
unzip -q ~/Downloads/archive_workbench_v0.89.0_RC66.zip -d "$TMP_DIR"
python "$TMP_DIR/scripts/apply_candidate_update.py" --source "$TMP_DIR" --target ~/projects/archive_app
python -m pip install --no-build-isolation -e ".[dev,extraction,streamlit,semantic,tiff,discovery,audiovisual,platform]"
python -c "import archive_workbench; print(archive_workbench.__version__)"
archive-workbench db-status ~/projects/archive_app/pilot_data
```

Resultado esperado: versión de código `0.89.0` y revisión `0047_authority_relation_profiles`.

**No hay migración nueva entre RC65 y RC66. No ejecutar `db-upgrade`.**

## Gate automatizado focal

La suite completa corresponde exclusivamente a Alex. RC66 se valida con evaluación/proveedor, corridas y continuidad de descubrimiento, documentación/empaquetado y recopilación completa sin ejecución:

```bash
cd ~/projects/archive_app && source .venv/bin/activate && pytest -q   tests/test_discovery_evaluation.py   tests/test_open_discovery.py::test_discovery_persists_reproducible_candidates_without_canonical_writes   tests/test_open_discovery.py::test_discovery_rejects_unconfirmed_scope_and_changed_profile_authorization   tests/test_open_discovery.py::test_discovery_uses_approved_pages_and_marks_candidate_stale   tests/test_open_discovery.py::test_discovery_skips_registered_authority_surface   tests/test_open_discovery.py::test_discovery_audit_and_cli_expose_traceability   tests/test_discovery_grouping.py::test_grouping_proposes_duplicates_across_runs_and_preserves_provenance   tests/test_discovery_grouping.py::test_continuity_projects_stale_candidate_and_keeps_old_candidate_visible   tests/test_discovery_grouping.py::test_continuity_rejects_ambiguous_exact_projection   tests/test_discovery_grouping.py::test_local_redetection_uses_original_local_rule_version   tests/test_documentation.py   tests/test_packaging.py && pytest --collect-only -q
```

## Validación y continuidad de DISC-03

No repetir OCR, transcripciones, búsquedas, exportaciones ni recorridos cerrados del piloto. RC66 no necesita una nueva validación funcional de Catálogo o audiovisual.

La próxima evidencia necesaria para `DISC-03` es una auditoría sobre texto real del proyecto. Debe conservar muestras y decisiones de revisión, no modificar automáticamente autoridades, menciones ni relaciones y no reinterpretar corridas históricas v1. Hasta disponer de esa evidencia, `DISC-03` no se cierra y el siguiente bloque de la hoja de ruta no se inicia.
