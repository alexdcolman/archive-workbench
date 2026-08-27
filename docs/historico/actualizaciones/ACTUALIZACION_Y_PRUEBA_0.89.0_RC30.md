# Actualización actual - Archive Workbench 0.89.0 RC30

**Estado:** candidata documental no publicada para cerrar `UX-04` y retomar `PILOT-01` en Relaciones  
**Última publicación real:** `v0.88.2`  
**Versión de código:** `0.89.0`  
**Revisión de base:** `0046_audiovisual_timeline_annotations`  
**Migración nueva:** no. **No ejecutar `db-upgrade`.**

## Alcance de RC30

RC29 fue validada manualmente y cierra el rodeo transversal `UX-04`. La validación confirmó el rediseño de economía visual, la orientación mediante iconos de información y el comportamiento corregido de los tooltips. RC30 no modifica código de aplicación, modelo de dominio, persistencia ni base de datos: actualiza la documentación canónica para reflejar el cierre y devuelve el recorrido activo de `PILOT-01` a **Relaciones**.

`UX-04` sale de `PENDIENTES_ACTIVOS.md` y queda registrado en `IMPLEMENTACIONES_REALIZADAS.md`. `UX-02` permanece pendiente para la revisión integral final de interfaz antes de v1.0. `DISC-03` continúa separado y no debe optimizarse a partir de ejemplos aislados del piloto.

## Actualización segura desde RC29

Usar el actualizador de candidatas. No tocar `pilot_data`.

```bash
cd ~/projects/archive_app
source .venv/bin/activate
TMP_DIR="$(mktemp -d)"
unzip -q ~/Downloads/archive_workbench_v0.89.0_RC30.zip -d "$TMP_DIR"
python "$TMP_DIR/scripts/apply_candidate_update.py" --source "$TMP_DIR" --target ~/projects/archive_app
python -m pip install --no-build-isolation -e ".[dev,extraction,streamlit,semantic,tiff,discovery,audiovisual,platform]"
python -c "import archive_workbench; print(archive_workbench.__version__)"
```

La versión importada debe seguir informando `0.89.0`; `RC30` identifica la candidata. No ejecutar `db-upgrade`.

## Gate automatizado de RC30

Como RC30 es documental, el gate focal es documentación, empaquetado y colección completa de tests:

```bash
cd ~/projects/archive_app && source .venv/bin/activate && \
pytest -q tests/test_documentation.py tests/test_packaging.py && \
pytest --collect-only -q
```

No corresponde afirmar que se ejecutó la suite completa salvo que efectivamente se haya hecho.

## Punto exacto de continuación manual

Usar `/home/alex/projects/archive_app/pilot_data`. No repetir las etapas ya cerradas. El recorrido retoma en:

`Relaciones -> búsqueda literal -> búsqueda semántica -> grafo -> exportación -> asignación/revisión cruzada -> checkpoint/bundle -> backup/prueba de recuperación`

La primera prueba en Relaciones debe crear y comprobar una relación analítica real y sustentada por el corpus, manteniendo separados esos vínculos interpretativos de los roles archivísticos de productor y responsable de gestión que provienen de Catálogo.
