# Actualización actual - Archive Workbench 0.89.0 RC54

## Alcance de RC54

La prueba piloto posterior a RC53 confirmó que el intercambio necesitaba completar la simplificación iniciada en RC52. Una copia para trabajar en equipo podía crecer mucho, las rutas de ZIP todavía obligaban a pegar texto en varios recorridos y Google Drive aceptaba únicamente paquetes incrementales aunque una copia inicial también sea un artefacto transportable.

RC54 mantiene la misma persistencia y cambia únicamente empaquetado, transporte e interfaz:

- **Preparar una copia para trabajar en equipo** ofrece tres perfiles: **Completa**, **Para revisión y catalogación** y **Personalizada**.
- La base SQLite consistente y la configuración del proyecto son siempre obligatorias. El contenido pesado o regenerable se organiza en grupos configurables: documentos originales, derivados de consulta, extracción, transcripciones, índices, exportaciones previas, materiales de evaluación y otros auxiliares.
- Antes de crear el ZIP se muestra un tamaño estimado y el detalle por grupo. El manifiesto registra explícitamente qué grupos fueron incluidos y cuáles se omitieron deliberadamente.
- Una omisión deliberada no se interpreta como pérdida del archivo en la copia de origen. Si faltan originales, la interfaz explica que esa copia no podrá abrirlos o reprocesarlos localmente.
- Los recorridos que reciben ZIP incorporan un **selector de archivo**. Para artefactos grandes ya creados dentro del proyecto se conserva además la elección directa de archivos conocidos, evitando volver a cargarlos mediante el navegador.
- **Recibir cambios** inspecciona primero el ZIP. Un paquete incremental entra en la simulación normal; una copia inicial se identifica como tal y no se aplica sobre el proyecto abierto.
- Google Drive transporta tanto **copias para trabajar en equipo** como **paquetes de cambios**. Cada archivo se inspecciona antes de subir y se etiqueta con tipo, proyecto, identificador y SHA-256.
- La subida a Drive usa sesiones **reanudables** y bloques de 8 MiB, múltiplos de 256 KiB; no carga el ZIP completo en RAM. La descarga también se escribe por bloques a un temporal y sólo después se materializa el archivo verificado.
- Después de crear una copia inicial o un paquete incremental, si Drive está conectado aparece una acción directa **Subir a Google Drive**.

`PILOT-01AB` continúa abierto hasta validar este recorrido sobre el proyecto persistente.

## Actualización desde RC53

```bash
cd ~/projects/archive_app
source .venv/bin/activate
TMP_DIR="$(mktemp -d)"
unzip -q ~/Downloads/archive_workbench_v0.89.0_RC54.zip -d "$TMP_DIR"
python "$TMP_DIR/scripts/apply_candidate_update.py" --source "$TMP_DIR" --target ~/projects/archive_app
python -m pip install --no-build-isolation -e ".[dev,extraction,streamlit,semantic,tiff,discovery,audiovisual,platform]"
python -c "import archive_workbench; print(archive_workbench.__version__)"
archive-workbench db-status ~/projects/archive_app/pilot_data
```

Resultado esperado: versión de código `0.89.0` y revisión `0047_authority_relation_profiles`.

**No hay migración nueva entre RC53 y RC54. No ejecutar `db-upgrade`.**

## Gate automatizado focal

No repetir los recorridos ya validados. Para RC54 alcanza con los tests focales de copia configurable, recepción, transporte de Drive, formularios, documentación y empaquetado, seguidos de `pytest --collect-only -q`. La suite completa corresponde exclusivamente a Alex.

## Validación manual específica de RC54

Usar el mismo `pilot_data`; no recrear el proyecto ni repetir etapas anteriores.

1. Abrir **Intercambiar cambios > Preparar una copia para trabajar en equipo**. Comparar **Completa**, **Para revisión y catalogación** y **Personalizada**. Confirmar que el tamaño estimado y el detalle cambien al incluir u omitir grupos.
2. Crear una muestra con **Para revisión y catalogación** o una configuración personalizada que omita originales. Confirmar que el resultado indique tamaño, SHA-256 y contenido omitido deliberadamente.
3. Si Google Drive ya está conectado, usar **Subir a Google Drive** sobre esa copia. Debe admitirse como **Copia para trabajar en equipo**; ya no debe aparecer el rechazo de RC53.
4. En **Más opciones > Google Drive (opcional)** comprobar que la lista distingue copias iniciales y paquetes de cambios, y que **Elegir otro archivo ZIP…** abre un selector de archivos.
5. En **Recibir cambios**, elegir un ZIP local. Una copia inicial debe identificarse sin intentar aplicarla sobre `pilot_data`; un paquete incremental debe continuar hacia la simulación normal.

No aplicar todavía cambios remotos sobre `pilot_data` salvo que la continuación del piloto lo indique explícitamente.
