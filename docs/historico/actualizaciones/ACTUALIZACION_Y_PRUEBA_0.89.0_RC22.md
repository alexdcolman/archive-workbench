# Actualización actual - Archive Workbench 0.89.0 RC22

**Estado:** candidata no publicada para validación manual de `UX-04` y `GRAPH-03`  
**Última publicación real:** `v0.88.2`  
**Versión de código:** `0.89.0`  
**Revisión de base:** `0046_audiovisual_timeline_annotations`  
**Migración nueva:** no. **No ejecutar `db-upgrade`.**

## Alcance de RC22

RC22 parte de RC21 y abre una candidata de diseño para el rodeo `UX-04`. No cambia el modelo de dominio ni la persistencia. Tampoco reabre las validaciones funcionales ya cerradas de `Entidades y menciones`: el objetivo es evaluar si la misma funcionalidad puede presentarse con mucha menos densidad textual y topológica.

En el shell general:

- `Archive Workbench` pasa al sidebar y deja de repetirse como título grande en cada sección;
- desaparecen los botones para ir a la sección anterior o siguiente;
- la navegación sigue concentrada en el selector `Sección` y en `Guía de esta sección`.

En `Entidades y menciones`:

- se elimina la introducción larga y el panel `Qué es una entidad`; `Entidades` y `menciones` ofrecen definición contextual al posar el cursor;
- las cuatro tareas generales dejan de ocupar una barra completa de pestañas y pasan a un selector compacto;
- búsqueda, tipo, estado y período forman una sola barra de refinamiento; no existe ya `Filtros de entidades`;
- el contador de resultados aparece sólo cuando existe búsqueda textual;
- el selector de entidad pierde el encabezado redundante y la entidad elegida recibe una cabecera visual propia con metadata compacta;
- `Resumen de la ficha de entidad seleccionada` y la explicación intermedia desaparecen;
- `Nombres alternativos` se integra en `Ficha`: se agrega junto al nombre principal y los alias existentes se muestran como etiquetas compactas con detalle contextual;
- la ficha conserva una sola barra de navegación contextual: `Ficha`, `Menciones`, `Relaciones`, `Historial`;
- `Menciones` reduce explicación y métricas permanentes;
- `Relaciones` reduce texto, separa `Roles archivísticos` de `Relaciones analíticas`, explica mediante ayuda contextual qué significa crear una relación analítica y elimina la aclaración redundante sobre cuándo se guarda.

RC22 implementa además `GRAPH-03`: en `Explorar relaciones > Elegir qué relaciones mostrar en el mapa > Tipos de relación que querés mostrar`, `Jerarquía archivística` y `Documentos en unidades` quedan desactivadas por defecto. Ambas continúan disponibles para activación explícita.

## Actualización segura desde RC21

Usar el actualizador de candidatas. No copiar el ZIP sobre el repositorio con una operación recursiva y no tocar `pilot_data`.

```bash
cd ~/projects/archive_app
source .venv/bin/activate
TMP_DIR="$(mktemp -d)"
unzip -q ~/Downloads/archive_workbench_v0.89.0_RC22.zip -d "$TMP_DIR"
python "$TMP_DIR/scripts/apply_candidate_update.py" --source "$TMP_DIR" --target ~/projects/archive_app
python -m pip install --no-build-isolation -e ".[dev,extraction,streamlit,semantic,tiff,discovery,audiovisual,platform]"
python -c "import archive_workbench; print(archive_workbench.__version__)"
```

La versión importada debe seguir informando `0.89.0`; `RC22` identifica la candidata. No ejecutar `db-upgrade`.

## Gate automatizado de RC22

Ejecutar desde el repositorio actualizado:

```bash
cd ~/projects/archive_app && source .venv/bin/activate && pytest -q tests/test_ui_navigation.py tests/test_graph.py tests/test_relations.py tests/test_documentation.py tests/test_packaging.py && pytest --collect-only -q
```

## Validación manual pendiente

La primera validación es deliberadamente de comprensión visual. Usar el proyecto persistente `/home/alex/projects/archive_app/pilot_data`; no recrearlo ni repetir fases cerradas.

1. Abrir `Entidades y menciones` y entrar en `Revisar fichas y menciones` sin abrir primero la guía.
2. Mirar la superficie inicial antes de editar: comprobar si se reconoce inmediatamente la entidad activa y si búsqueda/refinamientos se entienden sin panel adicional.
3. Usar una búsqueda textual y un refinamiento, cambiar de entidad y recorrer `Ficha`, `Menciones`, `Relaciones` e `Historial` sin guardar cambios en esta primera pasada.
4. Comprobar que no reaparecen las dos series de pestañas, el resumen eliminado ni las introducciones largas; observar especialmente si `Relaciones` sigue siendo localizable y comprensible con menos texto.
5. Después, abrir `Explorar relaciones > Elegir qué relaciones mostrar en el mapa` y comprobar que `Jerarquía archivística` y `Documentos en unidades` están desmarcadas al entrar, pero siguen disponibles.

Si el prototipo resulta satisfactorio, `UX-04` continuará sección por sección. Si no, se corrige primero esta superficie sin expandir el patrón al resto de la aplicación.

El recorrido principal de `PILOT-01` permanece detenido temporalmente en este rodeo. Después de resolver `UX-04`, vuelve a **Relaciones** y continúa con búsqueda literal, búsqueda semántica, grafo, exportación, asignación/revisión cruzada, checkpoint/bundle y backup/prueba de recuperación.
