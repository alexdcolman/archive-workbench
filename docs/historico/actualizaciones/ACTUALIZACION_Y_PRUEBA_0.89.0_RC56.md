# Actualización actual - Archive Workbench 0.89.0 RC56

## Alcance de RC56

La validación visual posterior a RC55 confirmó que el intercambio incremental ya funciona de extremo a extremo, pero todavía quedaban dos fuentes de sobrecarga: **Recibir cambios** mostraba acciones ocasionales antes de que fueran necesarias y **Más opciones** agrupaba funciones heterogéneas sin explicar de qué tarea eran alternativas. Google Drive, además, aparecía como una superficie paralela aunque en el uso normal sólo es una forma de enviar o recibir un ZIP.

RC56 mantiene la misma persistencia y los mismos contratos de intercambio. Reorganiza únicamente la arquitectura de la interfaz:

- El selector principal de **Intercambiar cambios** queda reducido a **Enviar cambios**, **Recibir cambios** y **Preparar una copia para trabajar en equipo**.
- Google Drive deja de ser una tarea independiente. En **Enviar cambios** y **Preparar una copia** aparece como destino opcional del ZIP recién creado; en **Recibir cambios** se elige **Desde este equipo** o **Desde Google Drive** sólo cuando se abre otro ZIP recibido.
- **Recibir cambios** prioriza el paquete ya seleccionado. Si existen paquetes pendientes, la incorporación de otro ZIP permanece cerrada detrás de **Abrir otro ZIP recibido**.
- **Archivar paquete** es una acción secundaria y reversible: la nota opcional y los botones de archivo aparecen recién después de solicitarla. Restaurar un paquete archivado es directo; eliminar definitivamente conserva confirmación explícita.
- Cuando una comparación requiere decisiones, se muestra una sola diferencia a la vez. La resolución masiva permanece oculta hasta pedir **Resolver todas las diferencias de la misma manera**.
- Las herramientas excepcionales de recuperación, reconstrucción de historial y reemplazo de estado salen del selector principal y se abren mediante **Resolver un problema entre copias**. Ese recorrido reemplaza temporalmente la superficie normal y ofrece **Volver a Recibir cambios**.
- Los metadatos técnicos, diagnósticos y vistas previas desactualizadas siguen disponibles bajo detalles informativos cerrados, sin competir con la decisión actual.

No hay migración nueva. Continúa `0047_authority_relation_profiles`.

## Actualización desde RC55

```bash
cd ~/projects/archive_app
source .venv/bin/activate
TMP_DIR="$(mktemp -d)"
unzip -q ~/Downloads/archive_workbench_v0.89.0_RC56.zip -d "$TMP_DIR"
python "$TMP_DIR/scripts/apply_candidate_update.py" --source "$TMP_DIR" --target ~/projects/archive_app
python -m pip install --no-build-isolation -e ".[dev,extraction,streamlit,semantic,tiff,discovery,audiovisual,platform]"
python -c "import archive_workbench; print(archive_workbench.__version__)"
archive-workbench db-status ~/projects/archive_app/pilot_data
```

Resultado esperado: versión de código `0.89.0` y revisión `0047_authority_relation_profiles`.

**No hay migración nueva entre RC55 y RC56. No ejecutar `db-upgrade`.**

## Gate automatizado focal

No repetir recorridos ya validados ni ejecutar la suite completa. Para RC56 corresponde el gate focal de navegación de intercambio, recepción, ciclo de vida de paquetes, Google Drive, formularios, documentación y empaquetado; al final del mismo bloque se ejecuta `pytest --collect-only -q`. La suite completa corresponde exclusivamente a Alex.

## Validación manual específica de RC56

Usar el mismo `pilot_data`. No recrear el proyecto y no volver a aplicar el paquete que ya fue incorporado durante la validación funcional.

1. Abrir **Intercambiar cambios**. El selector principal debe mostrar únicamente **Enviar cambios**, **Recibir cambios** y **Preparar una copia para trabajar en equipo**. No debe existir **Más opciones** ni un selector llamado **Opción secundaria**.
2. En **Recibir cambios**, con un paquete ya registrado, comprobar que la pantalla prioriza su estado y sus acciones. **Abrir otro ZIP recibido** debe revelar recién entonces la elección **Desde este equipo / Desde Google Drive**, y **Cerrar** debe volver a ocultarla.
3. Pulsar **Archivar paquete** y comprobar que la nota opcional aparece sólo en ese momento junto con **Archivar** y **Cancelar**. Usar **Cancelar** si no se desea cambiar el historial del piloto.
4. Si el paquete contiene diferencias pendientes, comprobar que se presenta una sola diferencia por vez y que la resolución masiva no aparece hasta solicitarla explícitamente. No hace falta repetir una aplicación ya validada.
5. Abrir **Resolver un problema entre copias**. Debe quedar claro que es un recorrido excepcional, debe reemplazar la superficie normal mientras está activo y debe ofrecer **Volver a Recibir cambios**. No ejecutar ninguna recuperación durante esta comprobación visual.
6. Revisar **Enviar cambios** y **Preparar una copia para trabajar en equipo**. Google Drive debe aparecer únicamente como destino contextual del ZIP creado, no como cuarta tarea paralela.

Si esta organización queda clara y sin sobrecarga, cerrar `PILOT-01AB` y continuar con backup/prueba no destructiva de recuperación.
