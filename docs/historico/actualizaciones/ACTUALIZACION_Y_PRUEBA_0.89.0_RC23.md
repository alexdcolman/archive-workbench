# Actualización actual - Archive Workbench 0.89.0 RC23

**Estado:** candidata no publicada para segunda validación manual de `UX-04`  
**Última publicación real:** `v0.88.2`  
**Versión de código:** `0.89.0`  
**Revisión de base:** `0046_audiovisual_timeline_annotations`  
**Migración nueva:** no. **No ejecutar `db-upgrade`.**

## Alcance de RC23

RC23 parte de la candidata RC22, cuya reformulación general de `Entidades y menciones` fue validada manualmente como una mejora material. No cambia el modelo de dominio ni la persistencia y no reabre las pruebas funcionales ya cerradas. Esta ronda profundiza `UX-04` únicamente en las superficies que todavía se percibían densas.

En `Menciones`:

- las menciones ya vinculadas aparecen antes que la búsqueda de nuevas coincidencias;
- los estados de página se muestran directamente junto a la acción de búsqueda, sin `Opciones de búsqueda`;
- desaparecen el rótulo redundante de alcance de calidad y la alarma, confirmación y fundamento adicionales cuando se eligen páginas no aprobadas;
- la selección explícita de estados sigue dejando una autorización auditable en el backend, sin una segunda confirmación visible;
- las tarjetas dejan de mostrar el identificador técnico `source_key`, traducen el estado de la mención y acortan la acción de navegación.

En `Relaciones`:

- `Crear una relación analítica` queda cerrado por defecto mediante un toggle persistente;
- abrirlo muestra el mismo formulario y no introduce un `st.expander` reactivo.

En `Buscar nuevas entidades en los textos`:

- las tres tareas generales pasan de una segunda serie de pestañas a un selector compacto;
- la configuración de búsqueda usa un selector de configuración y un panel persistente sólo para editarla;
- tipos de referencia, estados de página, tipos de fragmento y estado de revisión del texto se agrupan con menos topología;
- desaparecen las alarmas y fundamentos redundantes de alcance ampliado, manteniendo la auditoría interna de la selección explícita;
- la revisión de resultados alinea búsqueda y filtro de tipo en una sola fila, elimina el resumen desplegable y reduce métricas permanentes;
- la confianza de cada referencia se presenta de forma compacta;
- los identificadores técnicos dejan los selectores normales y permanecen disponibles en `Trazabilidad técnica`.

La validación de RC22 cerró `GRAPH-03`: `Jerarquía archivística` y `Documentos en unidades` quedan desactivadas por defecto y siguen disponibles para activación manual.

## Actualización segura desde RC22

Usar el actualizador de candidatas. No copiar el ZIP recursivamente sobre el repositorio y no tocar `pilot_data`.

```bash
cd ~/projects/archive_app
source .venv/bin/activate
TMP_DIR="$(mktemp -d)"
unzip -q ~/Downloads/archive_workbench_v0.89.0_RC23.zip -d "$TMP_DIR"
python "$TMP_DIR/scripts/apply_candidate_update.py" --source "$TMP_DIR" --target ~/projects/archive_app
python -m pip install --no-build-isolation -e ".[dev,extraction,streamlit,semantic,tiff,discovery,audiovisual,platform]"
python -c "import archive_workbench; print(archive_workbench.__version__)"
```

La versión importada debe seguir informando `0.89.0`; `RC23` identifica la candidata. No ejecutar `db-upgrade`.

## Gate automatizado de RC23

```bash
cd ~/projects/archive_app && source .venv/bin/activate && pytest -q tests/test_ui_navigation.py tests/test_relations.py tests/test_open_discovery.py tests/test_analysis_quality.py tests/test_documentation.py tests/test_packaging.py tests/test_graph.py && pytest --collect-only -q
```

## Validación manual pendiente

Usar el proyecto persistente `/home/alex/projects/archive_app/pilot_data`. No repetir onboarding, catálogo, OCR, revisión general ni la validación ya aprobada del shell, la cabecera de ficha o el grafo.

1. En `Entidades y menciones > Revisar fichas y menciones`, abrir `Menciones`: comprobar que las menciones vinculadas aparecen primero y que la búsqueda queda debajo con sus opciones visibles en línea, sin panel de opciones ni mensajes adicionales de alcance de calidad.
2. Sin necesidad de incorporar nada, cambiar los estados de página de la búsqueda y verificar que el control sigue siendo comprensible y no aparece una segunda confirmación o fundamento.
3. Abrir `Relaciones`: comprobar que `Crear una relación analítica` está cerrado al entrar. Abrirlo y cambiar el tipo de destino para confirmar que el panel sigue abierto durante el rerun. No hace falta crear una relación para esta validación visual.
4. Cambiar la tarea general a `Buscar nuevas entidades en los textos`. Recorrer `Revisar referencias encontradas`, `Ejecutar una búsqueda` y `Duplicados y cambios de texto` sin ejecutar una nueva detección: comprobar que sólo haya una capa de pestañas visible a la vez, que la configuración y los filtros sean localizables y que la trazabilidad técnica quede secundaria.

Si RC23 resulta satisfactoria, `UX-04` puede pasar de este prototipo a la adaptación sección por sección del resto de la aplicación. El recorrido principal de `PILOT-01` sigue temporalmente detenido en este rodeo y luego vuelve a **Relaciones**.
