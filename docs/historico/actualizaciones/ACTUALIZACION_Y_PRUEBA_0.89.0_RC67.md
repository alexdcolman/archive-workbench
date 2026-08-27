# Actualización actual - Archive Workbench 0.89.0 RC67

## Alcance de RC67

RC67 continúa `DISC-03` a partir de la auditoría externa de dos exportaciones reales ya producidas durante `PILOT-01`: un JSONL documental con 138 registros agregados por documento y un JSONL audiovisual con 78 segmentos de una transcripción. Ambos archivos se usaron únicamente como evidencia de lectura en la construcción de esta candidata: **no se incorporan al repositorio, al ZIP ni a los tests**.

La auditoría confirma que `local_rules_v2` mejoró el ruido respecto de v1, pero dejó dos brechas importantes sobre material real: redujo en exceso los títulos de obras/publicaciones y no recuperó nombres o topónimos frecuentes en discurso testimonial sin una clase introductora. También mostró ambigüedades de tiempo: días de la semana usados como nombres propios o dentro de títulos, `mañana` como parte del día y años abreviados en secuencias históricas.

RC67 agrega `local_rules_v3` como versión local vigente para perfiles nuevos y conserva **ejecutables y sin reinterpretación** `local_rules_v1` y `local_rules_v2` para perfiles, corridas y continuidades históricas. v3:

- distingue días de la semana de nombres propios y de títulos entrecomillados mediante contexto temporal;
- diferencia `mañana` relativo de usos como `por la mañana` o `turnos mañana y tarde`;
- recupera secuencias abreviadas de años como `1959-60` o `1962/63/64` sin volver a aceptar identificadores como `1976/4`;
- recupera títulos entrecomillados con señales de obra, publicación, repertorio, estreno, lectura o autoría, usando pares de comillas balanceados;
- evita tratar como obra nombres de grupos, teatros, bibliotecas, escuelas, establecimientos o citas directas por el solo hecho de estar entrecomillados;
- agrega capturas contextuales acotadas de personas y lugares en discurso testimonial o de procedencia, sin reabrir patrones genéricos de mayúsculas OCR;
- restringe `marcha` como acontecimiento a construcciones explícitas como `marcha estudiantil`, evitando `poner en marcha` o `sentido de marcha`;
- detecta acciones flexionadas sólo cuando tienen un objetivo compatible, evitando usos genéricos como `reprimir exageraciones`.

El benchmark de 46 controles de RC66 se mantiene intacto para poder comparar v1/v2 con exactamente la misma evidencia. Sobre las seis familias locales, v1 conserva F1 micro `0.675676`, v2 `0.911765` y v3 resuelve los seis holdouts de ese benchmark. RC67 agrega además `config/discovery_evaluation_corpus_disc03_real_patterns.jsonl`, con 41 controles **sintéticos** que reproducen patrones observados durante la auditoría real; en ese corpus de regresión v2 obtiene F1 `0.545455` y v3 `1.0`. Ese `1.0` no se presenta como estimación de calidad sobre documentos futuros: el corpus fue creado para impedir que reaparezcan errores ya observados.

Como control externo no anotado, sobre los 138 documentos el número total de candidatos de las seis familias pasa de `1002` en v2 a `1139` en v3: tiempo `503→501`, actor `275→276`, espacio `50→55`, obra `17→151`, acontecimiento `90→90` y acción/proceso `67→66`. Sobre los 78 segmentos audiovisuales pasa de `5` candidatos exclusivamente temporales en v2 a `12` en v3: conserva los cinco temporales y agrega cuatro actores y tres espacios. Estos conteos describen comportamiento, **no precisión ni recall**, porque las exportaciones reales no contienen verdad terreno exhaustiva para estas seis familias.

`DISC-03` continúa **PARCIAL**. La siguiente evidencia necesaria es una revisión humana acotada de candidatos v3 sobre material real. Sólo después de esa revisión corresponde decidir si v3 se adopta para cerrar el bloque o si queda otro ajuste justificado por falsos positivos/negativos concretos.

No se modifica `pilot_data`, no se ejecuta descubrimiento sobre el proyecto real durante la construcción, no se crean autoridades/menciones/relaciones y no hay migración de base. Continúa `0047_authority_relation_profiles`.

## Actualización desde RC66

```bash
cd ~/projects/archive_app
source .venv/bin/activate
TMP_DIR="$(mktemp -d)"
unzip -q ~/Downloads/archive_workbench_v0.89.0_RC67.zip -d "$TMP_DIR"
python "$TMP_DIR/scripts/apply_candidate_update.py" --source "$TMP_DIR" --target ~/projects/archive_app
python -m pip install --no-build-isolation -e ".[dev,extraction,streamlit,semantic,tiff,discovery,audiovisual,platform]"
python -c "import archive_workbench; print(archive_workbench.__version__)"
archive-workbench db-status ~/projects/archive_app/pilot_data
```

Resultado esperado: versión de código `0.89.0` y revisión `0047_authority_relation_profiles`.

**No hay migración nueva entre RC66 y RC67. No ejecutar `db-upgrade`.**

## Gate automatizado focal

La suite completa corresponde exclusivamente a Alex. RC67 se valida con proveedor/evaluación, continuidad de candidatos, documentación/empaquetado y recopilación completa sin ejecución:

```bash
cd ~/projects/archive_app && source .venv/bin/activate && pytest -q \
  tests/test_discovery_evaluation.py \
  tests/test_open_discovery.py::test_discovery_persists_reproducible_candidates_without_canonical_writes \
  tests/test_open_discovery.py::test_discovery_rejects_unconfirmed_scope_and_changed_profile_authorization \
  tests/test_discovery_grouping.py::test_local_redetection_uses_original_local_rule_version \
  tests/test_discovery_grouping.py::test_continuity_projects_stale_candidate_and_keeps_old_candidate_visible \
  tests/test_documentation.py \
  tests/test_packaging.py && \
pytest --collect-only -q
```

## Validación manual específica de RC67

No repetir OCR, transcripciones, exportaciones ni recorridos cerrados. Usar el mismo `pilot_data` y crear, en **Entidades y menciones > Buscar nuevas entidades**, una configuración nueva con el proveedor local vigente. Ejecutarla sobre un alcance pequeño y reconocible del corpus, no sobre todo el proyecto.

Revisar una muestra breve que incluya, cuando el material la ofrezca:

1. títulos entrecomillados frente a nombres de grupos, teatros o instituciones;
2. días de la semana frente a nombres propios o títulos;
3. personas y lugares en formulaciones testimoniales o de procedencia;
4. acciones/procesos y acontecimientos que puedan confundirse con expresiones ordinarias.

La corrida sólo debe crear **referencias sugeridas para revisar**. No debe crear automáticamente entidades, menciones aceptadas ni relaciones. Conservar la corrida y las decisiones de revisión: esa evidencia permite cerrar `DISC-03` o justificar un ajuste siguiente sin volver a ejecutar una auditoría masiva.
