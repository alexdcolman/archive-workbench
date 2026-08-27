# Actualización actual - Archive Workbench 0.89.0 RC15

**Fecha:** 2026-08-19  
**Estado:** candidata no publicada  
**Última publicación:** `v0.88.2`  
**Revisión de base:** `0046_audiovisual_timeline_annotations`  
**Migración nueva:** no

RC15 continúa `PILOT-01` sobre el mismo proyecto persistente:

```text
/home/alex/projects/archive_app/pilot_data
```

No recrear `pilot_data`, no reincorporar los 138 originales, no repetir la prueba audiovisual, no repetir la preparación ya cerrada de la muestra y no volver a ejecutar la extracción masiva de 138 documentos iniciada con RC12. **No ejecutar `db-upgrade`.**

## Evidencia manual que ya queda cerrada o reutilizable

La secuencia `Preparar imágenes y extraer texto` de RC14 fue validada manualmente como comprensible. La extracción masiva iniciada anteriormente con RC12 terminó con 138 documentos incluidos, 5 completados y 133 fallidos. Los cinco completados eran los documentos de la muestra que sí tenían imágenes preparadas. Los otros 133 no tenían una preparación vigente. Esa tarea no se repite.

El envío masivo de páginas de un solo documento a `Revisar documentos` funcionó. La variante sobre varios documentos falló con `StreamlitDuplicateElementKey` porque distintos registros podían producir la misma clave de widget a partir de `source_key`.

La incorporación de texto recuperado al trabajar sobre una parte de una página funcionó al reemplazar texto, pero el rerun de Streamlit desplazó la vista al inicio. La validación manual también mostró que mezclar en una sola pestaña la elección de una extracción completa, la incorporación de texto recuperado de una parte concreta y el envío masivo a revisión hacía el recorrido difícil de comprender.

`Revisar documentos` todavía no fue revalidado en esta ronda y debe retomarse después de validar los cambios de procesamiento de RC15.

## Cambios de RC15

### Procesar documentos

RC15 separa tres tareas que antes estaban mezcladas:

1. `Elegir el texto de una página para revisar`: compara solamente extracciones completas de la página y permite elegir cuál se usará en `Revisar documentos`.
2. `Corregir o agregar texto en una página`: usa el texto reconocido después de marcar una parte concreta de una página. Permite corregir un texto existente o agregar texto que faltaba.
3. `Enviar varias páginas a Revisar documentos`: concentra el envío masivo por un documento o por varios documentos y explica cuántas páginas nuevas se enviarán antes de confirmar.

Las extracciones parciales no aparecen entre las extracciones completas de una página. No hay selección cruzada entre ambas tareas.

Al corregir texto existente, la imagen muestra los textos ya presentes y permite elegirlos haciendo clic sobre sus marcos. Al agregar texto faltante, la persona debe dibujar sobre la página el rectángulo donde quedará el texto nuevo. La geometría del reconocimiento parcial original se conserva como procedencia y la ubicación dibujada se guarda como geometría final del nuevo texto.

La operación masiva sobre varios documentos usa `digital_object_id` como identidad de cada documento y deduplica representaciones equivalentes antes de crear los controles. Esto corrige el choque de claves observado con `source_key`.

### Continuidad después de guardar

La conservación de posición de Streamlit se refuerza de forma transversal. Antes de una interacción se guarda el control lógico cercano y su posición relativa; después del rerun se restaura ese ancla y se usa la posición en píxeles solamente como respaldo. La corrección no depende de un botón concreto.

### Historial de la extracción masiva anterior

Cuando un trabajo antiguo conserva la causa `no tiene una corrida de preprocesamiento vigente`, el historial la presenta como:

```text
No se pudo extraer texto porque el documento todavía no tenía imágenes preparadas.
```

No es necesario repetir la tarea de 138 documentos para obtener esta explicación.

### Formatos de documentos e imágenes

El recorrido público actual admite PDF, TIFF, PNG, JPEG y WebP para la incorporación y el procesamiento documental. La inspección técnica también reconoce BMP, pero la incorporación por catálogo no lo admite todavía. Esa inconsistencia queda abierta como `PILOT-01L`; RC15 no amplía el contrato de formatos de manera implícita.

## Auditoría transversal de interfaz en RC15

Antes de empaquetar RC15 se repitieron las cinco pasadas exigidas por `.assistant/05_CRITERIOS_INTERFAZ.md`: propósito y navegación; rótulos y controles; ayudas y avisos; estados, resultados e historiales; y opciones técnicas o avanzadas. La revisión no se limitó a `Procesar documentos`. También corrigió restos de `texto inicial` y orientaciones antiguas en Inicio/Revisar documentos, un texto truncado en `Orden y estructura` y rótulos genéricos de estado o resultado cuando el referente podía expresarse. Los términos técnicos que siguen visibles se conservan únicamente cuando nombran una estructura que la persona debe manipular o están dentro de detalles técnicos.

Los controles automáticos se usan sólo como guarda de regresión; el cierre de claridad sigue dependiendo de la prueba manual de `PILOT-01` sin guía externa.

## Verificación de la candidata

En el entorno de construcción quedaron verdes los **152 tests focalizados** de `candidate_review`, `processing`, `ui_navigation`, `documentation` y `packaging`. La recopilación completa encuentra **583 tests en 53 archivos**. La suite completa no se ejecutó porque no corresponde repetirla sin un cambio material que invalide los resultados previos.

## Instalación

RC15 debe instalarse con el actualizador seguro incorporado en el paquete. No usar `cp -a` para superponer candidatas.

```bash
cd ~/projects/archive_app
source .venv/bin/activate

TMP_DIR="$(mktemp -d)"
unzip -q ~/Downloads/archive_workbench_v0.89.0_RC15.zip -d "$TMP_DIR"

python "$TMP_DIR/scripts/apply_candidate_update.py" \
  --source "$TMP_DIR" \
  --target ~/projects/archive_app

python -m pip install --no-build-isolation -e ".[dev,extraction,streamlit,semantic,tiff,discovery,audiovisual,platform]"
python -c "import archive_workbench; print(archive_workbench.__version__)"
```

La versión de código continúa informando `0.89.0`; `RC15` identifica la candidata no publicada.

## Pruebas focalizadas

Ejecutar una sola tanda focalizada y luego recopilar la suite completa sin ejecutarla:

```bash
cd ~/projects/archive_app
source .venv/bin/activate

pytest -q \
  tests/test_candidate_review.py \
  tests/test_processing.py \
  tests/test_ui_navigation.py \
  tests/test_documentation.py \
  tests/test_packaging.py && \
pytest --collect-only -q
```

No repetir la suite completa salvo evidencia material que invalide resultados anteriores.

## Validación manual siguiente

Después del gate automático, abrir el mismo `pilot_data` y validar únicamente lo que cambió:

1. `Procesar documentos > Volver a leer una parte de una página`: comprobar que el propósito y el recorrido se entienden sin guía externa. No hace falta volver a ejecutar el ejemplo regional ya cerrado.
2. `Procesar documentos > Elegir el texto de una página para revisar`: comprobar que sólo aparecen extracciones completas.
3. `Procesar documentos > Corregir o agregar texto en una página`: comprobar selección visual del texto a corregir, dibujo de la ubicación de un texto nuevo y conservación de la posición después de guardar. Ejecutar sólo una escritura útil o reversible si hace falta para validar el rerun.
4. `Procesar documentos > Enviar varias páginas a Revisar documentos`: no repetir el envío de un solo documento ya validado. Revalidar solamente la operación sobre varios documentos que falló en RC14.
5. Continuar con la validación pendiente de `Revisar documentos` sobre las páginas ya disponibles.

Si aparece una regresión, detenerse en ese punto y analizarla. No retroceder a importaciones, audiovisual ni procesamiento ya cerrado.
