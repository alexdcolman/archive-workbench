# Actualización actual — Archive Workbench 0.86.0

**Fecha:** 2026-08-08
**Bloque cerrado:** `AV-03` — evaluación, revisión y anotación temporal de video real
**Revisión de base:** `0046_audiovisual_timeline_annotations`

## Estado acumulado de AV-03

La RC1 midió la línea de base real de `RememorArte Horacio BAU` con `faster_whisper` `small`, CPU `int8`: 202.21 s para 436.22 s (`RTF 0.464`), 2109.6 MiB de RAM máxima, 89 segmentos con mediana de 3.48 s y una muestra humana con CER 0.100 y WER 0.163. La revisión detectó errores de nombres propios —entre ellos Trelew— y mostró que editar segmento por segmento era inviable.

RC2–RC4 reemplazaron ese recorrido por un editor continuo con un solo **Guardar transcripción**, conservaron los segmentos como anclajes temporales internos y corrigieron las regresiones de estado de Streamlit y del reproductor. La validación de RC4 confirmó guardado continuo y navegación temporal sin traceback. Esa evidencia no se repite en RC5.

## RC5–RC12 — anotaciones, revisión sincronizada y comparación de reconocimiento

RC5 agrega una capa editorial estructurada que pertenece al medio audiovisual y no a una corrida concreta. La migración aditiva `0046_audiovisual_timeline_annotations` crea:

- `AudiovisualTimelineAnnotation`: tipo `speaker` o `annotation`, inicio/fin, etiqueta, vínculo opcional a una autoridad, estado y revisión;
- `AudiovisualTimelineAnnotationRevision`: historial append-only de creación y archivo.

Una marca puede nacer tomando como referencia uno o varios segmentos de la corrida vigente, pero guarda tiempos propios del medio. Por eso se conserva si después se genera otra transcripción.

## Interfaz

La transcripción continua sigue siendo la tarea principal. **Anotaciones y hablantes** pasa a resolverse en RC6 mediante una **Revisión sincronizada** junto al reproductor:

- mientras el audio/video avanza, el segmento correspondiente se resalta y acompaña automáticamente el tiempo actual sin reruns continuos de Streamlit;
- al pulsar un segmento en la transcripción sincronizada, el reproductor salta directamente a ese tiempo;
- la marca **Hablante** se controla desde **Hablante actual**: permite elegir una **Autoridad** existente o escribir una etiqueta provisional y usar **Asignar hablante desde aquí**; al cambiar de hablante, se cierra automáticamente el turno anterior y comienza el nuevo en la posición actual;
- la marca **Anotación** se crea con **Agregar anotación aquí**, que toma automáticamente el tiempo del reproductor y asocia la nota al tramo textual vigente;
- ejemplos como `sonríe`, `se ríe` o `muestra una fotografía` permanecen estructurados y no se insertan dentro del texto corregible;
- **Gestionar anotaciones y hablantes** queda como panel secundario para revisar/archivar marcas existentes y consultar la **Transcripción con hablantes y anotaciones** derivada.

Las marcas temporales viajan en adopción de estado 1.2 y se incluyen en la exportación de segmentos cuando se superponen con el intervalo exportado.

## Validación

La validación de RC5–RC6 partió de copias descartables y confirmó que la revisión sincronizada es usable. La exploración libre generó más marcas que el recorrido controlado, por lo que RC7 deja de exigir una secuencia literal de turnos en el verificador y diagnostica cierres automáticos reales.

RC7 inició la comparación sin pedir otra corrección humana y ejecutó `faster_whisper` `large-v3`, GPU CUDA `float16`, sobre el video completo. La corrida terminó en 914.92 s (`RTF 2.097`) con 5394 MiB de VRAM máxima observada. La primera tabla RC7 fue metodológicamente incorrecta: para la línea de base podía leer el texto ya corregido y compararlo contra la misma referencia humana, produciendo CER/WER 0; además proyectaba la corrida candidata mediante el centro temporal de segmentos con fronteras diferentes, inflando el error.

RC12 corrige la evaluación sin repetir inferencia y deja la optimización apoyada en evidencia visible y reproducible. Toda medición de reconocimiento usa exclusivamente `original_text`; la referencia sigue siendo la misma corrección humana. CER/WER sólo se calculan cuando las fronteras temporales de la hipótesis coinciden con las cinco ventanas humanas. Si otra corrida segmenta distinto y no existen timestamps por palabra, la UI muestra el contexto original de todos los segmentos que solapan cada ventana y deja CER/WER sin valor en lugar de recortar el candidato usando la propia referencia. También permite ver y descargar completas las dos transcripciones automáticas originales. El campo **Vocabulario esperado (opcional)** continúa transmitiéndose mediante `hotwords`, pero la detección de un término es informativa y no se interpreta por sí sola como calidad. RC12 no agrega migración; continúa en `0046_audiovisual_timeline_annotations` y `project_data` permanece sin modificar durante la validación.

## Cierre de AV-03

La validación final de RC12 confirmó el recorrido completo, el evaluador conservador y la inspección de ambas transcripciones sin volver a inferir. `small` conserva CER 0.100 / WER 0.163 sobre las cinco ventanas revisadas. `large-v3`, al usar fronteras diferentes y no disponer de timestamps por palabra persistidos, queda correctamente sin CER/WER comparable y se evalúa mediante el contexto temporal original y la salida completa.

La revisión cualitativa de las dos transcripciones completas concluyó que el perfil probado `large-v3` + CUDA `float16` es globalmente superior a `small` + CPU `int8` para este material: recupera mejor frases, nombres propios y relaciones semánticas. También es considerablemente más costoso (914.92 s, `RTF 2.097`, frente a 202.21 s y `RTF 0.464`) y conserva errores que requieren revisión humana. Por tratarse de una evaluación sobre un único medio, 0.86.0 registra el perfil de mayor calidad pero no cambia silenciosamente el default portable `small` + CPU.

`AV-03` queda implementado, validado y cerrado en 0.86.0. `project_data` debe migrarse de `0045_audiovisual_transcription` a `0046_audiovisual_timeline_annotations` únicamente durante el cierre local, después de backup y verificación explícitos.
