# Actualización actual - Archive Workbench 0.89.0 RC12

**Estado actualizado:** 2026-08-16  
**Bloque:** `PILOT-01` - reescritura transversal de la interfaz después de que la validación manual de RC11 detectara referentes todavía implícitos.

## Estado de partida

El último estado publicado sigue siendo `v0.88.2`. `0.89.0 RC12` es una candidata no publicada. No agrega migración: la revisión de base continúa en `0046_audiovisual_timeline_annotations`.

PILOT-01 continúa sobre `/home/alex/projects/archive_app/pilot_data`. No recrear el proyecto, no volver a incorporar los 138 originales, no repetir la prueba audiovisual, no volver a preparar la muestra documental y no repetir por rutina la extracción Surya 5/5 ya validada.

RC11 quedó instalado y pasó la tanda indicada por la prueba local. La validación manual posterior mostró que su auditoría de referentes era metodológicamente insuficiente: podía evitar rótulos genéricos aislados y, sin embargo, conservar frases como `Cada tarjeta resume una parte del trabajo` o `qué significa cada columna`, que sólo se entienden reconstruyendo el referente desde el contexto.

## Qué cambia RC12

### 1. Prueba semántica de referente

Toda cadena visible se revisa con una regla más fuerte: leída aisladamente debe permitir reconocer el objeto del que habla, la acción disponible y el efecto relevante. Un título, una tarjeta o la frase anterior no completan un referente omitido.

La auditoría se amplía a los componentes auxiliares que renderizan interfaz, no sólo a `*_app.py`: `region_canvas.py`, `review_canvas.py`, `audiovisual_review_component.py`, `graph_canvas.py` y `local_picker.py` forman parte del alcance.

### 2. Inicio y Catálogo

Inicio deja de hablar de `una parte del trabajo`: cada tarjeta nombra la etapa concreta del trabajo con el corpus y su botón nombra la sección que abre.

La pestaña de planilla del Catálogo explica que el XLSX crea o actualiza unidades archivísticas, qué datos del catálogo corresponden a sus columnas y qué cambios se mostrarán antes de guardar. También se revisan rótulos de unidades, archivos, movimientos, eliminación y vínculos para que nombren explícitamente su objeto.

### 3. Procesar documentos y Revisar documentos

Se conserva la funcionalidad de RC11: `Trabajar una zona`, reemplazo localizado del texto de un bloque con OCR regional, preparación masiva para revisión y liberación automática de recursos de Surya. RC12 vuelve a revisar sus textos visibles con la prueba semántica.

`Revisar documentos` mantiene el orden acordado de pestañas, las síntesis breves y el replanteo de casilleros/formularios, pero revisa nuevamente botones, estados, historial, datos adicionales y acciones de orden/estructura para evitar objetos implícitos.

### 4. Resto de la aplicación

La misma lectura semántica se aplica a búsqueda textual, búsqueda por significado, entidades y menciones, explorar relaciones, exportación, intercambio entre copias, administración y recuperación, transcripción audiovisual y organización de trabajo. La jerga técnica necesaria queda secundaria y explicada cuando aporta diagnóstico o reproducibilidad.

### 5. Auditoría de cinco pasadas

El informe vigente es `docs/operativos/AUDITORIA_INTERFAZ_RC12_5_PASADAS.txt`. Las pasadas separan: títulos/navegación; controles; ayudas/avisos; estados/resultados/historiales; y opciones técnicas/avanzadas. Las pruebas estáticas se usan sólo como guardas de regresión y no como prueba suficiente de claridad.

## Base de datos

**No hay migración. No ejecutar `db-upgrade`.** La revisión continúa en `0046_audiovisual_timeline_annotations`.

## Actualización local

```bash
cd ~/projects/archive_app
source .venv/bin/activate

TMP_DIR="$(mktemp -d)"
unzip -q ~/Downloads/archive_workbench_v0.89.0_RC12.zip -d "$TMP_DIR"
cp -a "$TMP_DIR"/. .

python -m pip install --no-build-isolation -e ".[dev,extraction,streamlit,semantic,tiff,discovery,audiovisual,platform]"
python -c "import archive_workbench; print(archive_workbench.__version__)"
```

La versión de código seguirá mostrando `0.89.0`; `RC12` identifica la candidata y no cambia el número semántico publicado.

## Pruebas automatizadas de RC12

RC12 modifica principalmente texto visible, documentación y guardas de interfaz. En la construcción de la candidata pasaron **129 pruebas focalizadas** de interfaz, documentación, empaquetado y estado operativo. `compileall` de `src` y `tests` terminó correctamente. La recopilación completa encuentra **575 tests en 53 archivos**. No se repitió la suite completa costosa porque RC11 ya había pasado su tanda funcional y RC12 no cambia el modelo de datos ni la lógica de procesamiento.

```bash
pytest -q \
  tests/test_ui_navigation.py \
  tests/test_documentation.py \
  tests/test_packaging.py \
  tests/test_operational.py && \
pytest --collect-only -q
```

## Validación manual de RC12

Después de pasar la tanda focalizada, abrir el proyecto persistente con:

```bash
archive-workbench review-app pilot_data
```

Reanudar `PILOT-01` únicamente sobre las pantallas modificadas. No repetir tareas documentales ya cerradas. Primero recorrer Inicio, Catálogo, `Procesar documentos` y `Revisar documentos` sin guía externa y registrar cualquier frase o control cuyo objeto, propósito o efecto todavía tenga que inferirse. Después continuar el recorrido extremo a extremo desde el punto alcanzado antes de RC12.

`PILOT-01E` y `PILOT-01J` permanecen parciales hasta esa validación manual. Las funcionalidades de `PILOT-01G`, `PILOT-01H` y `PILOT-01I` conservan su estado de RC11 y no se consideran validadas sólo por esta reescritura.
