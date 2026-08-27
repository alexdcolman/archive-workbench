# Actualización actual - Archive Workbench 0.89.0 RC58

## Alcance de RC58

La validación manual de RC57 cerró `PILOT-01AC`: Integridad quedó accionable y depurada, los avisos no bloqueantes pueden descartarse sin borrar evidencia y Autorizaciones de análisis quedó filtrable. La creación de una copia de seguridad y la prueba no destructiva de recuperación también quedaron verdes. Después se validó `PILOT-01P` mediante exportación, modificación e importación real de fichas de entidades y relaciones. En `PILOT-01I`, una extracción individual con Surya demostró además que `VLLM::EngineCore` desaparece al terminar y la VRAM vuelve al nivel basal; queda pendiente únicamente la validación del ciclo de vida durante un lote.

Antes de esa validación en lote, la prueba real detectó dos regresiones en **Procesar documentos**: al cambiar de pestaña se perciben parpadeos y, en **Preparar / extraer**, documentos distintos con el mismo nombre visible pueden comportarse como una única opción al seleccionar o quitar elementos.

RC58 corrige esa superficie sin cambiar OCR, persistencia ni contratos de procesamiento:

- las siete pestañas de **Procesar documentos** conservan su estado pero un cambio puramente visual de pestaña ya no solicita un rerun completo de la aplicación;
- la navegación programática posterior a una acción sigue pudiendo abrir una pestaña concreta mediante un estado pendiente aplicado antes de renderizar los controles;
- los selectores de documentos usan `digital_object_id` como identidad estable y deduplican representaciones equivalentes del mismo objeto digital;
- cuando dos documentos tienen el mismo título o nombre de archivo, el rótulo visible agrega sólo el contexto necesario para distinguirlos: ruta archivística, referencia de origen y, como último recurso, identificador del objeto;
- quitar un documento del multiselector afecta únicamente al objeto elegido, aunque existan otros con el mismo nombre visible;
- el mismo criterio de identidad se aplica a preparación/extracción, OCR regional, elección de texto para revisar e incorporación masiva a revisión;
- el formulario para conservar una edición deja de deshabilitar el envío en función de una casilla del mismo `st.form`: la confirmación se valida después de pulsar el botón, conforme a la política del proyecto;
- los `st.expander` de Procesar documentos continúan limitados a contenido informativo y no contienen recorridos reactivos.

No se modifica `pilot_data`, el esquema ni el ciclo de vida de Surya. RC58 abre `PILOT-01AD` únicamente para validar esta reparación antes de retomar la mitad pendiente de `PILOT-01I`.

## Actualización desde RC57

```bash
cd ~/projects/archive_app
source .venv/bin/activate
TMP_DIR="$(mktemp -d)"
unzip -q ~/Downloads/archive_workbench_v0.89.0_RC58.zip -d "$TMP_DIR"
python "$TMP_DIR/scripts/apply_candidate_update.py" --source "$TMP_DIR" --target ~/projects/archive_app
python -m pip install --no-build-isolation -e ".[dev,extraction,streamlit,semantic,tiff,discovery,audiovisual,platform]"
python -c "import archive_workbench; print(archive_workbench.__version__)"
archive-workbench db-status ~/projects/archive_app/pilot_data
```

Resultado esperado: versión de código `0.89.0` y revisión `0047_authority_relation_profiles`.

**No hay migración nueva entre RC57 y RC58. No ejecutar `db-upgrade`.**

## Gate automatizado focal

No repetir recorridos ya validados ni ejecutar la suite completa. Para RC58 corresponde verificar navegación y estado de widgets de Procesar documentos, identidad de documentos homónimos, formularios afectados y operaciones de procesamiento representativas, seguido de documentación/empaquetado y `pytest --collect-only -q`. La suite completa corresponde exclusivamente a Alex.

## Validación manual específica de RC58

Usar el mismo `pilot_data`. No repetir OCR, backup, intercambio, exportación/importación de fichas ni la extracción individual de Surya.

1. Abrir **Procesar documentos** y cambiar varias veces entre las siete pestañas. El cambio de pestaña debe sentirse local: no debe producir el parpadeo de reconstrucción completa ni saltos de contexto.
2. En **Preparar / extraer**, elegir dos o más documentos que compartan el mismo nombre visible. Cada documento debe permanecer como opción independiente y, cuando haga falta, su rótulo debe incorporar contexto suficiente para distinguirlo.
3. Quitar con la cruz sólo uno de esos documentos. Los demás homónimos deben permanecer seleccionados y disponibles.
4. Alternar entre **Preparar páginas** y **Extraer texto** y volver. La selección no debe fusionar ni eliminar documentos por compartir título o nombre de archivo.
5. Recorrer sin ejecutar operaciones destructivas los selectores de documento de **OCR regional**, **Elegir texto para revisar** y **Enviar páginas a Revisar documentos**. Si aparecen homónimos, deben distinguirse sin depender del nombre como identidad.
6. Cambiar de pestaña después de una interacción normal y comprobar que la pestaña activa y las selecciones relevantes permanecen coherentes.

Si todo queda verde, cerrar `PILOT-01AD` y retomar exactamente la validación pendiente de `PILOT-01I`: un lote pequeño con Surya debe reutilizar el servidor durante el lote y liberar la VRAM automáticamente al finalizar.
