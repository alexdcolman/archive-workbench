# Actualización actual - Archive Workbench 0.89.0 RC55

## Alcance de RC55

La validación real de RC54 completó el intercambio incremental extremo a extremo: una copia creó un paquete, lo subió a Google Drive y el proyecto original lo descargó, revisó y aplicó correctamente. El hallazgo pendiente fue de UX: mensajes de resultado, estados persistentes y comprobaciones técnicas competían en distintas zonas de la página y volvían desordenada una función que ya era operativamente simple.

RC55 mantiene la misma persistencia y los mismos contratos de intercambio. Reorganiza únicamente la presentación:

- **Más opciones** pasa a ser una tarea del selector principal. Nunca se renderiza a la vez que Enviar cambios, Recibir cambios o Preparar una copia.
- Dentro de Google Drive se elige **Subir un ZIP** o **Recibir un ZIP** y sólo aparece el recorrido elegido.
- Una conexión activa con Drive se muestra como estado compacto, no como banner permanente de éxito. Las credenciales quedan ocultas mientras no se solicite configurar la conexión.
- Los resultados de subida, descarga, revisión y aplicación priorizan una única conclusión comprensible. SHA-256, rutas, IDs, método de base y tablas de compatibilidad permanecen disponibles en detalles cerrados.
- Un ZIP descargado desde Drive que se envía a revisión vuelve automáticamente al recorrido principal **Recibir cambios** y deja seleccionado el paquete evaluado.
- La lista de paquetes recibidos usa copia de origen, fecha/hora y estado visible en lugar de mostrar el fragmento del identificador técnico como dato principal.
- La comparación normal muestra primero cambios listos, diferencias que requieren decisión o conflictos; los conteos completos se desplazan a **Detalles del paquete y la comparación**.

No hay migración nueva. Continúa `0047_authority_relation_profiles`.

## Actualización desde RC54

```bash
cd ~/projects/archive_app
source .venv/bin/activate
TMP_DIR="$(mktemp -d)"
unzip -q ~/Downloads/archive_workbench_v0.89.0_RC55.zip -d "$TMP_DIR"
python "$TMP_DIR/scripts/apply_candidate_update.py" --source "$TMP_DIR" --target ~/projects/archive_app
python -m pip install --no-build-isolation -e ".[dev,extraction,streamlit,semantic,tiff,discovery,audiovisual,platform]"
python -c "import archive_workbench; print(archive_workbench.__version__)"
archive-workbench db-status ~/projects/archive_app/pilot_data
```

Resultado esperado: versión de código `0.89.0` y revisión `0047_authority_relation_profiles`.

**No hay migración nueva entre RC54 y RC55. No ejecutar `db-upgrade`.**

## Gate automatizado focal

No repetir recorridos ya validados ni ejecutar la suite completa. Para RC55 corresponde el gate focal de navegación/intercambio/Google Drive/documentación/empaquetado y, al final del mismo bloque, `pytest --collect-only -q`. La suite completa corresponde exclusivamente a Alex.

## Validación manual específica de RC55

Usar el mismo `pilot_data`. No recrear el proyecto ni volver a aplicar el paquete que ya quedó incorporado durante la validación de RC54.

1. Abrir **Intercambiar cambios** y recorrer el selector principal. Confirmar que **Enviar cambios**, **Recibir cambios**, **Preparar una copia para trabajar en equipo** y **Más opciones** aparecen como tareas alternativas y que sólo se muestra una a la vez.
2. Elegir **Más opciones > Google Drive (opcional)**. Con Drive ya conectado, confirmar que la conexión aparece como una línea compacta y que las credenciales permanecen ocultas hasta activar **Configurar conexión con Google Drive**.
3. Dentro de Drive alternar **Subir un ZIP** y **Recibir un ZIP**. Confirmar que nunca aparecen ambos recorridos completos simultáneamente.
4. En **Recibir un ZIP**, elegir o descargar un paquete ya existente si querés comprobar el estado visual. La tabla de compatibilidad, SHA-256 y ruta deben quedar cerrados en **Detalles de compatibilidad y archivo**. No hace falta aplicar nuevamente el paquete.
5. Volver a **Recibir cambios** y revisar el paquete ya registrado. La superficie principal debe comunicar primero si hay cambios listos, diferencias por decidir o ausencia de cambios nuevos. IDs, método de base y conteos completos deben quedar en **Detalles del paquete y la comparación**.

Si esta organización queda clara y sin sobrecarga, cerrar `PILOT-01AB` y continuar con backup/prueba no destructiva de recuperación.
