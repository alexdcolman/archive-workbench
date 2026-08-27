# Actualización actual - Archive Workbench 0.89.0 RC76

## Alcance de RC76

RC76 continúa `OPS-01` sobre RC75 y corrige cuatro defectos concretos encontrados durante la primera prueba real de extracción dentro de la imagen CPU.

La evidencia de RC75 mostró que el contenedor estaba ejecutándose con `HOME=/home/ubuntu` y `LD_LIBRARY_PATH=/opt/llama`, pero la corrida más reciente guardada en SQLite correspondía a `docling_tesseract_es_fallback_v1` con motor `docling_cli`. No había una corrida Surya nueva ni un `llamacpp_server.log` nuevo. El motivo principal quedó identificado en el preflight interno: Archive Workbench comprobaba `llama-server` por nombre en `PATH`, aunque la imagen administrada declara el binario incluido mediante `LLAMA_CPP_BINARY=/opt/llama/llama-server`. Al considerar no disponible el backend preferido, el flujo podía pasar a Docling antes de intentar Surya.

RC76 corrige ese recorrido de runtime:

- el diagnóstico de Surya usa el mismo `LLAMA_CPP_BINARY` que usa Surya al iniciar llama.cpp;
- cuando `ARCHIVE_WORKBENCH_SURYA_BACKEND=llamacpp`, el subproceso de Surya conserva `LD_LIBRARY_PATH` aunque el perfil histórico mantenga `surya_clean_library_path: true`;
- las instalaciones nativas que no están en ese modo administrado conservan la limpieza histórica de `LD_LIBRARY_PATH`;
- la interfaz de **Elegir texto** muestra de forma visible si cada extracción fue producida por Surya, Docling o Tesseract, además de conservar el perfil técnico dentro del detalle plegable.

La salida aportada para RC75 no demuestra que `/home/ubuntu` sea inescribible. El control usado daba `False` también cuando `~/.cache` todavía no existía. Por eso RC76 no cambia `HOME`: la próxima corrida material debe comprobar si Surya crea normalmente `~/.cache/datalab/surya` una vez que el flujo llega realmente a llama.cpp.

## Corrección de continuidad entre pestañas

La validación real de **Procesar documentos > Elegir texto** detectó además una regresión respecto de RC58: cambiar de documento provoca el rerun semántico esperable del `selectbox`, pero la vista reaparecía en la pestaña inicial **Estado**.

`tracked_tabs()` continúa usando `on_change="ignore"`: cambiar de pestaña sigue siendo navegación visual y no produce un rerun global. RC76 deja de intentar recordar desde Python un valor que Streamlit no registra en ese modo. La pestaña activa se conserva en `sessionStorage` mediante un componente v2 pasivo, sin `setStateValue`, sin `setTriggerValue` y sin comunicar un cambio de pestaña al backend. `request_tab()` conserva la navegación programática posterior a una acción real y tiene prioridad en el siguiente render.

Esto respeta `docs/referencia/ARQUITECTURA_Y_MODELO_ACTUAL.md#streamlit-interaction-invariant` y no reabre el resto de las validaciones de RC58.

## Tags de esta candidata

- CPU: `ghcr.io/alexdcolman/archive-workbench:0.89.0-rc76-cpu`;
- NVIDIA GPU: `ghcr.io/alexdcolman/archive-workbench:0.89.0-rc76-gpu`.

## Persistencia y base

No cambia SQLite ni el modelo de proyecto. Continúa `0047_authority_relation_profiles` y no hay migración. **No ejecutar `db-upgrade`.**

`WEB-01` permanece parcial y queda pausado hasta terminar la distribución multiplataforma. La reescritura integral del sitio para lectores sin conocimiento previo continúa pendiente. No se incorporan capturas hasta realizar esa reescritura.

## Gate automatizado focal

La suite completa corresponde exclusivamente a Alex. Para RC76 el gate se limita a los subsistemas afectados, las reglas transversales de navegación y distribución, y la recopilación completa sin ejecución:

```bash
cd ~/projects/archive_app && source .venv/bin/activate && \
pytest -q \
  tests/test_surya_extraction.py \
  tests/test_ui_navigation.py \
  tests/test_container_distribution.py \
  tests/test_documentation.py \
  tests/test_packaging.py && \
pytest --collect-only -q
```

## Validación manual específica de RC76

Usar una copia descartable del proyecto, no `pilot_data` como proyecto escribible.

1. Construir `0.89.0-rc76-cpu` y abrir la copia descartable mediante el selector Linux de RC75.
2. En **Procesar documentos > Elegir texto**, pasar a esa pestaña, cambiar de documento y confirmar que el documento cambia pero la pestaña sigue siendo **Elegir texto**.
3. Ejecutar una extracción con el método Surya preferido sobre una sola página. No repetir una corrida si la primera deja evidencia suficiente de un fallo.
4. Confirmar en el resultado y en **Elegir texto** que el motor visible es **Surya**. Si aparece **Docling**, registrar el aviso de fallback y no atribuir esa salida a llama.cpp.
5. Si Surya falla, revisar el `surya.log` de esa corrida y `~/.cache/datalab/surya/llamacpp_server.log`. En una ejecución Surya real el log debe permitir distinguir un fallo de servidor de un fallo posterior de inferencia.
6. Si Surya completa, detener y volver a iniciar RC76 y comprobar que la extracción y el proyecto externo montado siguen disponibles.
7. Sólo después de dejar verde CPU continuar con la imagen NVIDIA GPU.

## Actualización desde RC75

Usar `scripts/apply_candidate_update.py` incluido en el paquete. No ejecutar `db-upgrade`.
