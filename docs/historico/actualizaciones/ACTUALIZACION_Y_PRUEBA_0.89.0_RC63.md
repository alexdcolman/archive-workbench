# Actualización actual - Archive Workbench 0.89.0 RC63

## Alcance de RC63

La validación manual de RC62 cerró `PILOT-01E`: la interfaz audiovisual quedó ordenada y la aclaración de formatos locales resultó suficiente. Después de ese cierre se realizó una auditoría exhaustiva de toda la aplicación contra las políticas canónicas de comportamiento Streamlit. La auditoría detectó residuos históricos que no pertenecen a un único módulo y abre `PILOT-01AE` hasta su validación manual. El informe queda preservado en `docs/historico/actualizaciones/AUDITORIA_EXHAUSTIVA_STREAMLIT_ARCHIVE_WORKBENCH_RC62.md`.

RC63 corrige ese bloque transversal sin modificar contratos de dominio, persistencia ni esquema de base:

- `tracked_tabs()` pasa a ser pasivo por defecto. Cambiar una pestaña que sólo cambia el panel visible no solicita un rerun global. La navegación programática conserva el mecanismo de estado pendiente aplicado antes del siguiente render.
- Los 23 flujos interactivos detectados dentro de `st.expander` pasan a paneles persistentes basados en controles explícitos y `st.container`. Los expanders que permanecen contienen sólo información, historial o detalles técnicos.
- En Catálogo, quitar la asociación entre un documento y una unidad ya no deshabilita el botón a partir de una casilla ubicada dentro del mismo `st.form`; la confirmación se comprueba al enviar y una confirmación ausente no escribe nada.
- En Audio y video, escribir una anotación y pulsar Enter deja de crearla. Registrar la anotación exige el botón explícito correspondiente.
- En Buscar nuevas entidades, el perfil seleccionado después de guardar se aplica mediante estado pendiente antes de reconstruir el selector, en lugar de modificar la key del widget después de haberlo creado.
- Las pruebas de navegación incorporan guardrails transversales para impedir que vuelvan a introducirse pestañas con rerun visual, expanders interactivos, formularios circulares, escritura audiovisual por Enter o mutaciones tardías de keys de widgets sin estado pendiente.

No se modifica `pilot_data`, no se ejecuta OCR, no se inicia ninguna transcripción y no hay migración.

## Actualización desde RC62

```bash
cd ~/projects/archive_app
source .venv/bin/activate
TMP_DIR="$(mktemp -d)"
unzip -q ~/Downloads/archive_workbench_v0.89.0_RC63.zip -d "$TMP_DIR"
python "$TMP_DIR/scripts/apply_candidate_update.py" --source "$TMP_DIR" --target ~/projects/archive_app
python -m pip install --no-build-isolation -e ".[dev,extraction,streamlit,semantic,tiff,discovery,audiovisual,platform]"
python -c "import archive_workbench; print(archive_workbench.__version__)"
archive-workbench db-status ~/projects/archive_app/pilot_data
```

Resultado esperado: versión de código `0.89.0` y revisión `0047_authority_relation_profiles`.

**No hay migración nueva entre RC62 y RC63. No ejecutar `db-upgrade`.**

## Gate automatizado focal

RC63 toca comportamiento de interfaz en varias superficies, por lo que se validan navegación y los módulos directamente afectados en bloques separados, además de documentación/empaquetado y `pytest --collect-only -q`. La suite completa corresponde exclusivamente a Alex y no debe ejecutarse como parte de esta candidata.

## Validación manual específica de RC63

Usar el mismo `pilot_data`. No repetir OCR, transcripciones, exportaciones reales, intercambios ni otros recorridos funcionales ya cerrados. Esta validación comprueba únicamente continuidad de interfaz y ausencia de escrituras accidentales.

### 1. Inicio / selector de proyecto

En el selector inicial, alternar entre las tareas disponibles para abrir o crear un proyecto. Cambiar de pestaña no debe producir un parpadeo o reconstrucción global de la pantalla. No hace falta crear otro proyecto.

### 2. Catálogo

Validar los paneles que aparezcan en el material real:

1. En incorporación por lote, abrir **Asignar la misma unidad del catálogo a varios archivos de una subcarpeta** y **Corregir archivos que no siguen la asignación de su subcarpeta**. Cambiar selectores internos no debe cerrar el panel.
2. En **Unidades del catálogo**, abrir **Agregar una unidad hija a ...** y recorrer sus campos sin guardar.
3. En un contenido digital existente, abrir su panel y comprobar que permanece abierto al interactuar con sus controles secundarios.
4. Abrir **Quitar asociación** entre un documento y una unidad, dejar la confirmación sin marcar y pulsar el botón. Debe advertir que falta confirmar y **no debe quitar la asociación**.
5. Si existe un contenido digital disponible para vincular, abrir **Vincular un contenido digital existente** y cambiar la selección sin confirmar la escritura.
6. **Revisar la estructura permitida del catálogo** sólo aparece cuando una importación de planilla tiene errores estructurales. No crear un error artificial para esta candidata; ese panel queda cubierto por los guardrails automáticos.

### 3. Audio y video

En **Transcribir y revisar**, llegar a la caja para agregar una anotación temporal. Escribir un texto de prueba y pulsar Enter. **No debe crearse ninguna anotación.** Borrar el texto después. No pulsar el botón de registrar la anotación.

### 4. Revisar documentos

En un documento que ya tenga el tipo de información correspondiente, abrir los paneles secundarios disponibles, por ejemplo **Opciones de visualización**, **Herramientas de edición de las páginas**, **Estado de revisión de la página**, controles de casillas detectadas o manuales, administración de grupos y **Restaurar una revisión anterior**. Cambiar selectores o controles no destructivos dentro de un panel debe mantenerlo abierto. No guardar ni restaurar nada para esta validación.

### 5. Búsqueda textual

Abrir **Más filtros** y cambiar uno de los filtros. El panel debe permanecer abierto y la pantalla no debe reconstruirse de manera visible por abrir o cerrar la configuración.

### 6. Entidades y menciones

Alternar entre sus pestañas principales. No debe haber parpadeo por el cambio de pestaña. En **Relaciones**, abrir una relación analítica existente y, si se desea, **Modificar esta relación**. Cambiar un control sin guardar no debe cerrar la ficha de la relación.

### 7. Buscar nuevas entidades

Alternar entre las pestañas de agrupamiento/continuidad y entre los modos de revisión. Los cambios puramente visuales no deben forzar un rerun global. Si durante el trabajo normal se guarda un perfil de descubrimiento, el perfil recién guardado debe continuar seleccionado después del rerun; no hace falta crear un perfil sólo para esta prueba.

### 8. Búsqueda semántica

Alternar entre sus pestañas. Abrir las opciones técnicas para construir o reconstruir el índice y modificar un parámetro sin iniciar la construcción. El panel debe permanecer abierto.

### 9. Explorar relaciones

Alternar entre sus pestañas principales y abrir **Configurar mapa**. Cambiar controles de la configuración debe conservar el panel y no provocar una reconstrucción inesperada de la sección.

### 10. Preparar corpus

Alternar entre las pestañas documentales y, cuando corresponda, audiovisuales. Abrir **Acotar por período de tiempo** y **Cómo separar páginas y bloques de texto en el archivo exportado**. Cambiar opciones sin guardar un perfil ni crear una exportación debe conservar los paneles abiertos.

### 11. Organizar trabajo

Alternar entre sus pestañas. Abrir una asignación existente y cambiar un campo sin pulsar el botón de guardar. La ficha de la asignación debe permanecer abierta.

### 12. Administrar y recuperar

Alternar entre sus pestañas. En **Copias de seguridad disponibles**, abrir una copia existente y pulsar **Volver a comprobar esta copia de seguridad**. La comprobación es de solo lectura y el panel de la copia debe seguir abierto después del rerun.

`Procesar documentos` e `Intercambiar cambios` no fueron modificados por RC63 porque la auditoría confirmó que ya respetan estas políticas; no repetir sus validaciones cerradas.

Si estas superficies quedan verdes, `PILOT-01AE` puede cerrarse y el recorrido vuelve a `PILOT-01A`.
