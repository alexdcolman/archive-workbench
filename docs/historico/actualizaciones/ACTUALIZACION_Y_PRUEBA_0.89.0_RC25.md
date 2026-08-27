# Actualización actual - Archive Workbench 0.89.0 RC25

**Estado:** candidata no publicada para validación focal de `UX-04` en `Procesar documentos`  
**Última publicación real:** `v0.88.2`  
**Versión de código:** `0.89.0`  
**Revisión de base:** `0046_audiovisual_timeline_annotations`  
**Migración nueva:** no. **No ejecutar `db-upgrade`.**

## Alcance de RC25

La validación manual de RC24 fue favorable en principio para la expansión transversal de `UX-04`, con una excepción concreta: `Procesar documentos` siguió resultando demasiado cargado en sus pestañas. RC25 no reabre el resto de la aplicación. Realiza una segunda pasada focal sobre las siete tareas de procesamiento, aplicando los criterios ya validados de economía visual y arquitectura de información sin cambiar el modelo de dominio, la persistencia ni las operaciones existentes.

Cambios principales:

- las pestañas pasan a rótulos breves: `Estado`, `Preparar / extraer`, `Leer una zona`, `Elegir texto`, `Corregir o agregar`, `Enviar a revisión` e `Historial`;
- `Estado` muestra por defecto sólo las columnas necesarias para orientarse; los datos secundarios aparecen mediante `Ver más datos`, y el contador se muestra únicamente cuando hay búsqueda o filtro activo;
- `Preparar / extraer` hace visible la secuencia real mediante un único selector de `Paso`, alinea los controles principales y relega parámetros secundarios, reintentos y detalles técnicos a controles persistentes cerrados por defecto;
- `Leer una zona` elimina la secuencia de grandes encabezados numerados, conserva la imagen como objeto central y agrupa documento/página, contenido/acción y nombre/nota; plantillas y opciones del reconocimiento aparecen sólo cuando se solicitan;
- `Elegir texto` reduce métricas, altura de textos y explicaciones permanentes; el control automático se resume en un indicador compacto y sus detalles quedan cerrados; cuando existe una edición previa, se elige un único recorrido entre conservarla o trasladarla y sólo se renderiza el recorrido elegido;
- `Corregir o agregar` elimina introducciones repetitivas, agrupa página y lectura, presenta una sola elección entre corregir texto existente o agregar texto faltante y conserva la confirmación explícita porque la operación sí modifica el texto revisable;
- `Enviar a revisión` ya no muestra simultáneamente los recorridos de un documento y varios documentos: se elige el alcance y sólo aparece el flujo correspondiente; se retira una segunda confirmación redundante, porque el envío sigue requiriendo un botón explícito;
- `Historial` reemplaza métricas permanentes por una síntesis compacta por trabajo, muestra el título del documento en lugar del identificador técnico cuando está disponible y concentra parámetros y detalle técnico en información secundaria cerrada;
- la referencia desde `Revisar documentos` se actualiza al nombre vigente `Procesar documentos > Corregir o agregar`;
- `.assistant/05_CRITERIOS_INTERFAZ.md` incorpora como regla general que los recorridos alternativos mutuamente excluyentes no deben renderizarse completos al mismo tiempo.

No se elimina ninguna función. Las confirmaciones vinculadas a escrituras materiales se conservan. No se introduce ninguna estrategia alternativa de reruns, fragmentos o conservación de scroll.

## Actualización segura desde RC24

Usar el actualizador de candidatas. No copiar el ZIP recursivamente sobre el repositorio y no tocar `pilot_data`.

```bash
cd ~/projects/archive_app
source .venv/bin/activate
TMP_DIR="$(mktemp -d)"
unzip -q ~/Downloads/archive_workbench_v0.89.0_RC25.zip -d "$TMP_DIR"
python "$TMP_DIR/scripts/apply_candidate_update.py" --source "$TMP_DIR" --target ~/projects/archive_app
python -m pip install --no-build-isolation -e ".[dev,extraction,streamlit,semantic,tiff,discovery,audiovisual,platform]"
python -c "import archive_workbench; print(archive_workbench.__version__)"
```

La versión importada debe seguir informando `0.89.0`; `RC25` identifica la candidata. No ejecutar `db-upgrade`.

## Gate automatizado de RC25

```bash
cd ~/projects/archive_app && source .venv/bin/activate && \
pytest -q tests/test_ui_navigation.py tests/test_processing.py tests/test_preprocessing.py tests/test_regional_workflow.py tests/test_documentation.py tests/test_packaging.py && \
pytest --collect-only -q
```

## Validación manual pendiente

Usar el proyecto persistente `/home/alex/projects/archive_app/pilot_data`. No repetir la validación transversal de RC24 ni ejecutar nuevamente OCR, OCR regional o envíos ya cerrados. Esta ronda es únicamente una inspección de las siete pestañas de `Procesar documentos`.

Recorrer `Estado`, `Preparar / extraer`, `Leer una zona`, `Elegir texto`, `Corregir o agregar`, `Enviar a revisión` e `Historial` y comprobar que cada superficie deja claro qué decisión corresponde sin acumular recorridos alternativos, explicaciones, métricas o detalles secundarios. Abrir los controles secundarios para verificar que siguen localizables y conservan contexto, pero no hace falta guardar ni ejecutar operaciones.

Si RC25 queda validada, `UX-04` puede cerrarse y `PILOT-01` vuelve exactamente a **Relaciones**. Después siguen búsqueda literal, búsqueda semántica, grafo, exportación, asignación/revisión cruzada, checkpoint/bundle y backup/prueba de recuperación.
