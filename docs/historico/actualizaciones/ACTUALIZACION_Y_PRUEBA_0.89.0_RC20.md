# Actualización actual - Archive Workbench 0.89.0 RC20

**Fecha:** 2026-08-20  
**Estado:** candidata no publicada  
**Última publicación real:** `v0.88.2`  
**Revisión de base:** `0046_audiovisual_timeline_annotations`  
**Migración nueva:** no

RC20 continúa `PILOT-01` sobre el mismo proyecto persistente `/home/alex/projects/archive_app/pilot_data`. No recrear el proyecto, no volver a incorporar los 138 originales, no repetir la prueba audiovisual, el procesamiento documental, la extracción OCR general ni las validaciones de Entidades y menciones que RC19 ya superó.

**No ejecutar `db-upgrade`.**

## Qué cambia en RC20

RC20 corrige únicamente los tres hallazgos que quedaron abiertos al terminar la validación manual de RC19. No reabre el resto de esa candidata.

### 1. Bbox y bloque seleccionado en Revisar documentos

El clic sobre un bbox ya cambiaba correctamente `Bloque de texto de la página que querés revisar`, pero el marco rojo del componente podía quedar mostrando la selección anterior. RC20 sincroniza el trigger del componente en `on_selection_commit_change`, antes de que comience el render principal. Así, el componente visual y el selector reciben el mismo objeto desde el comienzo del rerun. No se agrega un segundo rerun. La regla general continúa definida exclusivamente en `docs/referencia/ARQUITECTURA_Y_MODELO_ACTUAL.md#streamlit-interaction-invariant`.

### 2. Trabajo con varias referencias sin cierre del panel

La selección múltiple de RC19 estaba dentro de un `st.expander` reactivo. Cambiar el `multiselect` provocaba un rerun y el expander se cerraba, en contra de la política permanente de interfaz. RC20 reemplaza ese recorrido por una pestaña estable **Trabajar con varias referencias** y un `st.form`. Dentro del formulario se seleccionan referencias y se marca una confirmación. Dos botones explícitos permiten crear una entidad `Sin revisar` por cada referencia seleccionada o descartar las referencias seleccionadas. La selección y la confirmación no se envían a Python hasta pulsar uno de esos botones.

### 3. Referencias descartadas como pestaña

**Referencias descartadas** deja de aparecer debajo de todas las referencias pendientes y pasa a ser una pestaña propia dentro de `Revisar referencias encontradas`. La restauración sigue siendo append-only: devuelve la referencia a pendientes sin borrar el descarte histórico.

### Regla de interacción con el asistente

`.assistant/01_INTERACCION_Y_GUIADO.md` registra la indicación explícita de Alex: todo mensaje que presente una modificación de código debe confirmar que se completó la checklist obligatoria. La checklist sigue siendo `.assistant/00_CHECKLIST_CAMBIOS.md`; no se crea una segunda fuente de políticas.

## Instalación segura

```bash
cd ~/projects/archive_app
source .venv/bin/activate

TMP_DIR="$(mktemp -d)"
unzip -q ~/Downloads/archive_workbench_v0.89.0_RC20.zip -d "$TMP_DIR"

python "$TMP_DIR/scripts/apply_candidate_update.py" \
  --source "$TMP_DIR" \
  --target ~/projects/archive_app

python -m pip install --no-build-isolation -e ".[dev,extraction,streamlit,semantic,tiff,discovery,audiovisual,platform]"
python -c "import archive_workbench; print(archive_workbench.__version__)"
```

La versión de código continúa informando `0.89.0`; `RC20` identifica la candidata no publicada.

## Gate automatizado de RC20

```bash
cd ~/projects/archive_app
source .venv/bin/activate

pytest -q \
  tests/test_ui_navigation.py \
  tests/test_review.py \
  tests/test_open_discovery.py \
  tests/test_documentation.py \
  tests/test_packaging.py && \
pytest --collect-only -q
```

No repetir la suite completa ni las validaciones manuales ya cerradas. La candidata quedó verde en **161 pruebas focalizadas** de esos cinco archivos; `pytest --collect-only -q` reunió **592 tests en 53 archivos** y `compileall` de `src` y `tests` terminó correctamente.

## Validación manual exacta de RC20

Validar únicamente `PILOT-01O`:

1. **Revisar documentos:** sobre una página ya revisada, hacer clic consecutivamente en varios bboxes. En cada clic deben coincidir el bloque elegido en `Bloque de texto de la página que querés revisar` y el marco rojo de la imagen. Documento, página y posición deben conservarse.
2. **Entidades y menciones > Buscar nuevas entidades en los textos > Revisar referencias encontradas > Trabajar con varias referencias:** seleccionar dos o más referencias dentro del formulario. La selección y la casilla de confirmación no deben cerrar la pestaña ni provocar un rerun antes de pulsar `Crear una entidad Sin revisar por cada referencia seleccionada` o `Descartar las referencias seleccionadas`. Probar una sola escritura real con pocas referencias.
3. **Referencias descartadas:** comprobar que es una pestaña independiente. Si la escritura anterior fue un descarte, restaurar una referencia y verificar que vuelva a pendientes conservando el historial.

Si estos tres puntos quedan verdes, trasladar `PILOT-01O` a `IMPLEMENTACIONES_REALIZADAS.md` y preparar el ZIP de relevo solicitado para una nueva conversación.
