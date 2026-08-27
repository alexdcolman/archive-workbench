# Actualización actual - Archive Workbench 0.89.0 RC61

## Alcance de RC61

La recorrida manual posterior a RC60 encontró un último problema de arquitectura de información dentro de `PILOT-01E`: **Transcribir audio y video** mezclaba en una sola superficie la incorporación desde plataformas, la selección de materiales ya registrados y el trabajo de transcripción, mientras que incorporar un archivo audiovisual local seguía dependiendo de Catálogo. El resultado era un modelo mental inconsistente: dos métodos para la misma tarea de incorporación aparecían en lugares distintos.

RC61 reorganiza esa superficie sin crear un segundo circuito de registro ni reabrir `AV-01`, `AV-02` o `AV-03`:

- la sección pasa a llamarse **Audio y video**;
- quedan dos tareas principales: **Incorporar audio o video** y **Transcribir y revisar**;
- **Incorporar audio o video** ofrece una única elección de método: **Desde esta computadora** o **Desde una plataforma web**, mostrando sólo el recorrido elegido;
- la incorporación local usa selector gráfico del sistema y puede elegir varios archivos;
- los archivos locales se registran mediante `catalog_management.register_external_file()`, el mismo servicio canónico usado por Catálogo: si están fuera del proyecto se copian a `corpus/importados`; si ya pertenecen al proyecto se registran sin crear otra copia;
- ese mismo registro crea o reutiliza `DigitalObject`, `FileInstance`, `SourceRegistration` y `AudiovisualMedia`; no existe una identidad audiovisual paralela;
- la incorporación desde plataforma conserva el contrato ya validado de `AV-02`, incluida autorización explícita, procedencia y elección entre video o sólo audio; incorporar no inicia una transcripción automáticamente;
- después de una incorporación correcta puede abrirse el material directamente en **Transcribir y revisar**;
- la tarea de transcripción conserva reproducción, editor continuo, revisión sincronizada, versiones, hablantes/anotaciones y evaluación ya validadas;
- las acciones secundarias de descarte/restauración de versiones dejan de usar `st.expander` interactivos y pasan a controles persistentes, de acuerdo con el invariante Streamlit;
- cambiar entre las dos tareas principales usa `tracked_tabs(..., rerun_on_change=False)`: la navegación visual no fuerza un rerun completo.

RC61 también conserva los límites amplios de fecha audiovisual mediante `DATE_INPUT_MIN`/`DATE_INPUT_MAX` y agrega regresiones para el selector múltiple local, el circuito canónico de registro y la separación de las dos tareas. La auditoría semántica obligatoria en cinco pasadas sobre la superficie modificada dejó además el campo descriptivo como **Fecha de registro, producción o publicación**, evitando el rótulo aislado `Fecha`; no se detectaron otros residuos que justificaran ampliar el alcance.

No se modifica el esquema de base ni se requiere migración. `PILOT-01E` permanece **PARCIAL** hasta validar manualmente esta reorganización; la auditoría anterior no se considera suficiente una vez que la recorrida real encontró este caso.

## Actualización desde RC60

```bash
cd ~/projects/archive_app
source .venv/bin/activate
TMP_DIR="$(mktemp -d)"
unzip -q ~/Downloads/archive_workbench_v0.89.0_RC61.zip -d "$TMP_DIR"
python "$TMP_DIR/scripts/apply_candidate_update.py" --source "$TMP_DIR" --target ~/projects/archive_app
python -m pip install --no-build-isolation -e ".[dev,extraction,streamlit,semantic,tiff,discovery,audiovisual,platform]"
python -c "import archive_workbench; print(archive_workbench.__version__)"
archive-workbench db-status ~/projects/archive_app/pilot_data
```

Resultado esperado: versión de código `0.89.0` y revisión `0047_authority_relation_profiles`.

**No hay migración nueva entre RC60 y RC61. No ejecutar `db-upgrade`.**

## Gate automatizado focal

No repetir transcripciones, evaluación AV-03, incorporación desde plataforma real, OCR, Surya ni otros recorridos ya cerrados. Para RC61 corresponde ejecutar las regresiones audiovisuales, incorporación desde plataforma/local, navegación/interfaz, documentación/empaquetado y `pytest --collect-only -q`. La suite completa corresponde exclusivamente a Alex.

## Validación manual específica de RC61

Usar el mismo `pilot_data`. No volver a descargar el material de plataforma ya validado y no iniciar una transcripción nueva sólo para esta prueba.

1. Abrir **Audio y video** y comprobar si las dos tareas principales, **Incorporar audio o video** y **Transcribir y revisar**, se entienden sin explicación externa.
2. En **Incorporar audio o video**, alternar entre **Desde esta computadora** y **Desde una plataforma web**. Debe mostrarse solamente el método elegido y la tarea principal no debe perderse ni parpadear por un rerun forzado de pestaña.
3. Para validar la incorporación local, elegir un archivo audiovisual que sea seguro incorporar y vincularlo con una unidad del catálogo. Si se seleccionan varios archivos, cada uno debe conservar identidad propia. No hace falta repetir una descarga de plataforma.
4. Después de incorporar, usar **Abrir este audio o video para transcribirlo**. Debe abrir **Transcribir y revisar** con ese medio seleccionado.
5. Recorrer brevemente el material seleccionado sin iniciar una inferencia nueva. Confirmar que el trabajo de transcripción/revisión permanece separado de la incorporación y que las herramientas secundarias no compiten con el editor principal.
6. Cambiar varias veces entre las dos tareas principales. La navegación no debe perder la selección de trabajo por un cambio meramente visual.

Si esta recorrida queda clara, `PILOT-01E` puede volver a evaluarse para cierre. El siguiente bloque sustantivo dentro de `PILOT-01` continúa siendo `PILOT-01A`, dedicado al modelo descriptivo de custodia, repositorios, colecciones y agrupaciones audiovisuales/plataformas.
