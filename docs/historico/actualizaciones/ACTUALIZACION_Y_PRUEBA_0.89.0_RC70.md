# Actualización actual - Archive Workbench 0.89.0 RC70

## Alcance de RC70

La validación manual de RC69 confirmó una mejora material de la corrida nueva con `local_rules_v5` y cierra `DISC-03`. Las corridas y configuraciones históricas continúan conservando su versión de reglas; no se recalculan ni se reinterpretan.

RC70 inicia `UX-02`, la revisión final de complejidad acumulada antes de v1.0. La auditoría transversal de cinco pasadas se conserva en `docs/historico/actualizaciones/AUDITORIA_UX02_RC70_5_PASADAS.md` y concentra cambios sólo donde encontró remanentes concretos:

- **Revisar documentos > Casilleros y campos** deja de mostrar simultáneamente detecciones, alta manual, edición de confirmados, grupos e historial. Un selector **Tarea con casilleros y campos** muestra una sola de esas superficies por vez y ofrece ayuda contextual específica. La página continúa visible en la columna izquierda, de modo que no se duplica la referencia visual.
- El resumen de **Casilleros y campos** pasa de tres métricas grandes a una línea compacta con casilleros confirmados, grupos y propuestas pendientes.
- En **Orden y estructura > Revisar orden y columnas**, la imagen con la propuesta y la confirmación permanecen en el recorrido principal; la tabla completa del orden se abre sólo mediante **Ver detalle del orden propuesto**.
- **Procesar documentos > Leer una zona** vuelve a mostrar explícitamente seis pasos: elegir documento/página, marcar zona, describirla, agregarla, revisar las zonas marcadas y procesarlas.
- **Cambiar el identificador de esta lectura** reemplaza el rótulo genérico `Más opciones` de OCR regional.
- En **Preparar / extraer**, la única opción que antes estaba debajo de otro `Más opciones` se muestra directamente como **Crear una nueva versión aunque ya exista una equivalente**.

No se eliminan capacidades ni se cambian contratos de OCR, edición, estructura, persistencia o historial. No se modifica `pilot_data` y no hay migración. Continúa `0047_authority_relation_profiles`.

`UX-02` permanece **PARCIAL** hasta una recorrida manual representativa. Las superficies ya cerradas funcionalmente no deben volver a probarse de extremo a extremo: la validación de RC70 es de jerarquía, comprensión y continuidad visual.

## Actualización desde RC69

```bash
cd ~/projects/archive_app
source .venv/bin/activate
TMP_DIR="$(mktemp -d)"
unzip -q ~/Downloads/archive_workbench_v0.89.0_RC70.zip -d "$TMP_DIR"
python "$TMP_DIR/scripts/apply_candidate_update.py" --source "$TMP_DIR" --target ~/projects/archive_app
python -m pip install --no-build-isolation -e ".[dev,extraction,streamlit,semantic,tiff,discovery,audiovisual,platform]"
python -c "import archive_workbench; print(archive_workbench.__version__)"
archive-workbench db-status ~/projects/archive_app/pilot_data
```

Resultado esperado: versión de código `0.89.0` y revisión `0047_authority_relation_profiles`.

**No hay migración nueva entre RC69 y RC70. No ejecutar `db-upgrade`.**

## Gate automatizado focal

La suite completa corresponde exclusivamente a Alex. Para RC70 corresponde ejecutar en un solo bloque:

```bash
cd ~/projects/archive_app && source .venv/bin/activate && \
pytest -q \
  tests/test_ui_navigation.py \
  tests/test_documentation.py \
  tests/test_packaging.py && \
pytest --collect-only -q
```

## Validación manual específica de RC70

Usar el mismo `/home/alex/projects/archive_app/pilot_data`. No ejecutar OCR, no crear nuevas extracciones y no repetir búsquedas, exportaciones, intercambio, backup o recuperación ya validados. La prueba consiste en recorrer estados existentes y, cuando un formulario permita escribir, no guardar cambios salvo que quieras comprobar expresamente una acción.

### 1. Revisar documentos > Casilleros y campos

1. Abrir un documento y una página que ya tengan bloques de texto.
2. Confirmar que la imagen de la página continúa visible a la izquierda mientras se trabaja en **Casilleros y campos**.
3. Comprobar que aparece una sola elección **Tarea con casilleros y campos** y que no están desplegadas a la vez todas las funciones de formulario.
4. Recorrer, sin guardar, **Revisar casilleros detectados**, **Agregar un casillero manualmente**, **Revisar casilleros confirmados**, **Administrar grupos de casilleros** e **Historial de casilleros y grupos**. Cada elección debe reemplazar la superficie anterior y conservar la página y el bloque seleccionados.

### 2. Revisar documentos > Orden y estructura

1. Elegir **Revisar orden y columnas**.
2. Confirmar que la propuesta visual sigue disponible.
3. Confirmar que la tabla larga no ocupa la pantalla hasta abrir **Ver detalle del orden propuesto**.
4. Cambiar entre las tareas del selector de **Orden y estructura** y comprobar que la página y el bloque seleccionados no cambian por esa navegación.

### 3. Procesar documentos > Leer una zona

1. Abrir **Leer una zona** sobre un documento que ya tenga imágenes preparadas. No hace falta procesar una zona nueva.
2. Confirmar que el recorrido muestra de forma comprensible los seis pasos en orden.
3. Comprobar que las opciones del reconocimiento siguen cerradas hasta pedirlas y que **Cambiar el identificador de esta lectura** está cerrado por defecto.
4. En **Preparar / extraer**, confirmar que ya no aparece `Más opciones`: la decisión excepcional se llama **Crear una nueva versión aunque ya exista una equivalente**.

### 4. Pasada transversal libre

Recorrer brevemente Inicio, Catálogo, Audio y video, Procesar documentos, Revisar documentos, búsquedas, Entidades y menciones, Explorar relaciones, Exportar corpus, Organizar trabajo, Intercambiar cambios y Administrar y recuperar usando información ya existente. No hace falta ejecutar acciones. Registrar únicamente si alguna pantalla vuelve a mostrar demasiadas tareas simultáneas, controles duplicados, información técnica dominante o un panel secundario abierto sin haberlo pedido.

Si estos puntos quedan verdes y la pasada transversal no detecta otro remanente material, `UX-02` puede cerrarse y la secuencia pre-release continúa con `WEB-01`.
