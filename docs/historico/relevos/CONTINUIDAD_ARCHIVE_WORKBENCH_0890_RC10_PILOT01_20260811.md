# CONTINUIDAD - Archive Workbench 0.89.0 RC10 / PILOT-01

**Fecha de relevo:** 2026-08-11  
**Estado:** candidata `0.89.0 RC10`, no publicada. PILOT-01 continúa sobre el mismo proyecto persistente y acaba de entrar en `Procesar documentos`.

**Actualización de validación:** 2026-08-13. RC10 fue instalada correctamente. `leg_15_a_c_2.tiff` y `leg_15_a_c_6.tiff` completaron `Preparar páginas` sin reproducir `tiff2vips: out of order read`, por lo que `PILOT-01F` queda cerrado. `Extraer texto` terminó sobre los cinco documentos con 5 completados, 0 advertencias y 0 fallos; `effective_backend=surya_cli`, `automatic_fallback=false`, `selection_policy=never`. La inspección visual aprobó `leg_15_a_c_2.tiff` p. 1, `leg_15_a_c_6.tiff` p. 1 y `caso_bolson.pdf` pp. 1, 2 y 4. Se registran para la próxima candidata: (a) dentro de `PILOT-01E`, reducir jerga técnica en `Extraer texto` y reemplazar en el recorrido normal términos como `backend`, `candidata` y `selección canónica` por lenguaje orientado a la tarea; (b) nuevo `PILOT-01G`, inicialización masiva explícita de páginas extraídas por documento y por lote, sin sobrescribir decisiones previas. **Próximo paso vigente:** continuar `Selección canónica` con al menos dos páginas visualmente distintas de `carp_reg.pdf` y una página sencilla más una problemática de `adm_pub_asp_contr.pdf`; después recorrer un caso de OCR regional con un problema localizado y continuar hacia `Revisar documentos`. Los pasos antiguos de reintento TIFF y extracción que aparecen más abajo quedan como historial de la validación ya completada y no deben repetirse.

---

## 0. INSTRUCCIÓN PRINCIPAL PARA LA NUEVA CONVERSACIÓN

Continuamos **Archive Workbench**.

Leé primero este archivo completo y tratá sus reglas y estado como punto de partida. Después leé `.assistant/00_LEER_PRIMERO.md` y seguí **todo** el orden obligatorio de `.assistant`. Leé además los documentos operativos vigentes y la documentación actual de `docs/referencia/`, con `ARQUITECTURA_Y_MODELO_ACTUAL.md` como lectura obligatoria antes de modificar persistencia, procesamiento, catálogo o audiovisual.

No reconstruyas contexto desde intuiciones, memoria conversacional o mensajes sueltos si el paquete contiene documentación vigente. No pidas repetir pruebas, importaciones o validaciones ya cerradas.

El último estado publicado sigue siendo:

- versión: `0.88.2`
- commit publicado: `df118df30e63779d10681618bc2fa9dd173ce7a7`
- tag publicado: `v0.88.2`
- rama publicada: `main`

La candidata actual es:

- versión de código: `0.89.0`
- candidata: **RC10**
- estado: **NO publicada**
- revisión DB: `0046_audiovisual_timeline_annotations`
- migración nueva: **no**
- commit/tag/push de 0.89.0: **todavía no**

El proyecto persistente del piloto es:

```text
/home/alex/projects/archive_app/pilot_data
```

con:

```text
project_id=corpus_archivos_represion
project_name=Corpus de archivos de la represión
```

**Próximo paso inmediato:** instalar RC10 y reintentar únicamente la preparación de `leg_15_a_c_2.tiff` y `leg_15_a_c_6.tiff`. Ambos fallaron en RC9 por un bug localizado de pyvips. Los tres PDF de la muestra ya se prepararon correctamente y no deben repetirse. Si los dos TIFF cierran, continuar con `Extraer texto` sobre los cinco documentos de la muestra.

---

## 1. REGLAS DE TRABAJO QUE NO DEBEN REABRIRSE

1. Dar comandos exactos, ordenados y ejecutables desde la PC local de Alex.
2. En comandos locales usar rutas reales como `~/projects/archive_app`, `~/Downloads/...` o `/home/alex/...`; nunca rutas internas del asistente.
3. Separar el push del resto del cierre:
   - primero actualización, pruebas, revisión, commit y tag;
   - revisar todas las salidas;
   - sólo después autorizar el push.
4. La suite completa local tarda aproximadamente 30 minutos. No repetirla salvo cambio material que invalide resultados previos.
5. No recrear ni reinicializar `pilot_data`.
6. No volver a incorporar los 138 originales APM ya registrados.
7. No volver a repetir la prueba audiovisual completa ya validada.
8. No ejecutar `db-upgrade` por RC10.
9. `project_data` es referencia histórica. No copiar desde allí OCR, extracciones, entidades, relaciones o análisis al piloto.
10. Los originales son inmutables. OCR, transcripciones y análisis son derivados versionados.
11. Ninguna extracción automática pasa a ser versión canónica sin una selección explícita.
12. No inferir estructura archivística por nombres de carpetas o por conveniencia técnica.
13. `.assistant` debe mantenerse actualizada dentro de candidatas y relevos, pero no se versiona en Git/GitHub.
14. `pilot_data/` permanece fuera del versionado local.
15. `/corpus/` está en `.gitignore`; no reescribir el archivo completo para volver a agregarlo.
16. Cuando Alex diga **dejar asentado**, el hallazgo se persiste por documentación del proyecto, no por memoria del asistente:
   - abierto/parcial -> `docs/operativos/PENDIENTES_ACTIVOS.md`;
   - cerrado -> `docs/operativos/IMPLEMENTACIONES_REALIZADAS.md`;
   - regla estable -> `.assistant/`;
   - modelo/arquitectura -> `docs/referencia/`.
17. En la interfaz, ningún texto debe omitir su referente por asumir que el contexto alcanza.
18. No usar `humana`/`humanas` como oposición genérica a resultados automáticos en la redacción de la aplicación.
19. Los campos que piden una carpeta deben ofrecer selector gráfico.
20. No reabrir un cierre funcional sin evidencia material nueva.

---

## 2. QUÉ SE VALIDÓ EN 0.89.0 HASTA RC9

### Primera fase del piloto

Se recorrió desde una experiencia de primer uso real y quedó validado:

- launcher para abrir/crear proyecto;
- identidad de usuario;
- navegación general;
- creación de `pilot_data` desde interfaz;
- catálogo APM Chubut;
- edición de jerarquía y unidades;
- cambio de tipo de unidad;
- eliminación segura de unidades vacías;
- incorporación por lote;
- reglas por carpeta y excepciones;
- incorporación persistente de **138 originales**;
- inventario con **138 documentos** y **0 sin archivo**.

No repetir esta fase.

### Audiovisual

Se validó el recorrido real de `Transcribir audio y video` con material de `rememorARTE`:

- incorporación autorizada desde plataforma;
- reproducción y velocidades;
- transcripción `faster-whisper`;
- `large-v3` en CUDA `float16`;
- idioma español;
- VAD activado;
- `beam_size=5`;
- vocabulario esperado/hotwords;
- edición y persistencia de la transcripción;
- revisión sincronizada;
- conservación de segmento y tiempo al guardar;
- hablantes con alcance puntual o continuo;
- menciones por segmento;
- métricas RAM/GPU con jerarquía equivalente;
- datos técnicos e historial;
- temas nativos de Streamlit y fechas descriptivas históricas.

La corrida histórica de referencia y la corrida controlada del piloto usaron el mismo original y el mismo WAV de transcripción. La primera corrida del piloto sin vocabulario esperado produjo 64 segmentos y una salida peor. La corrida controlada con:

```text
Centro Cultural por la Memoria Trelew, Horacio Bau
```

volvió a **78 segmentos** y reprodujo casi por completo la salida histórica. Esto es evidencia fuerte para este material de la relevancia del vocabulario esperado, pero no debe convertirse en regla universal de faster-whisper.

### Pendientes subsidiarios ya cerrados

Después de la validación acumulada RC7-RC9 pasan a `IMPLEMENTACIONES_REALIZADAS.md`:

- `PILOT-01B`: persistencia de posición/contexto y continuidad audiovisual frente a reruns.
- `PILOT-01C`: configuración, comparación y trazabilidad comprensible de transcripción audiovisual.
- `PILOT-01D`: temas/paletas nativos y fechas históricas.

No devolverlos a `PENDIENTES_ACTIVOS.md` sin una regresión concreta.

---

## 3. ESTADO ACTUAL DE `PILOT-01`

`PILOT-01` sigue **PARCIAL** porque todavía falta recorrer procesamiento documental, OCR, selección canónica, revisión, búsqueda, entidades, relaciones, exportación e integridad final sobre el corpus persistente.

Pendientes subsidiarios abiertos al preparar RC10:

### `PILOT-01A` - modelo descriptivo de colecciones/repositorios/audiovisual

Sigue pendiente revisar de manera archivísticamente sólida la relación entre:

- institución/repositorio de custodia;
- fondo;
- serie;
- colección construida;
- recurso audiovisual;
- publicación/manifestación digital;
- copia local;
- playlist o agrupación de plataforma.

`Archivo > Colección` se usó de manera provisional para continuar el piloto, pero no está aceptado como jerarquía universal.

### `PILOT-01E` - identidad obligatoria y redacción explícita

La identidad obligatoria está implementada. Sigue pendiente una auditoría transversal completa del texto visible de toda la app.

Hallazgos nuevos ya corregidos en RC10:

- la introducción de `Procesar documentos` omitía referentes al decir `Prepará los archivos, generá versiones de texto...`;
- `Las opciones técnicas aparecen solamente cuando corresponden` era un metacomentario innecesario.

RC10 usa una formulación explícita sobre documentos, versiones de texto y páginas y elimina ese segundo texto. `.assistant/05_CRITERIOS_INTERFAZ.md` incorpora además la regla de no explicar la propia lógica de aparición de controles si no ayuda a decidir una acción.

### `PILOT-01F` - preparación TIFF con pyvips - CERRADO

La validación real de 2026-08-13 confirmó la reparación de RC10 en los dos TIFF. El detalle histórico del fallo y del procedimiento de validación se conserva más abajo, pero no debe repetirse.

### `PILOT-01G` - inicialización masiva de páginas extraídas - PENDIENTE

Queda registrada para la próxima candidata una acción explícita que permita inicializar páginas por documento completo y por lote de documentos. Debe mostrar el alcance antes de escribir, conservar la extracción de origen y no sobrescribir páginas ya inicializadas o decisiones previas sin una decisión explícita.

---

## 4. MUESTRA ACTUAL DE `PROCESAR DOCUMENTOS`

La muestra acordada contiene cinco casos:

1. `adm_pub_asp_contr.pdf`
2. `carp_reg.pdf`
3. `caso_bolson.pdf`
4. `leg_15_a_c_2.tiff`
5. `leg_15_a_c_6.tiff`

Primera operación ejecutada en RC9:

```text
Procesar documentos
> Ejecutar
> Preparar páginas

Tratamiento del derivado para OCR: Original
Corrección geométrica: Ninguna
Crear nueva versión equivalente: desmarcado
```

Resultado:

- `adm_pub_asp_contr.pdf`: preparado correctamente.
- `carp_reg.pdf`: preparado correctamente.
- `caso_bolson.pdf`: preparado correctamente.
- `leg_15_a_c_2.tiff`: falló.
- `leg_15_a_c_6.tiff`: falló.

Errores reales observados:

```text
unable to call VipsForeignSaveWebpFile
tiff2vips: out of order read -- at line 2490, but line 0 requested
```

```text
unable to call VipsForeignSaveWebpFile
tiff2vips: out of order read -- at line 2975, but line 0 requested
```

No reintentar los tres PDF.

---

## 5. CAUSA DEL BUG TIFF Y REPARACIÓN RC10

La rama pyvips de `src/archive_workbench/preprocessing.py` abre cada página raster con:

```text
access="sequential"
```

En RC9 hacía:

```text
abrir página TIFF secuencialmente
-> guardar derivado OCR
-> reutilizar la misma imagen ya consumida
-> redimensionar/guardar preview WebP
```

Una lectura secuencial de libvips no puede volver a empezar desde la línea 0 después de haber sido consumida. Por eso el segundo guardado fallaba.

RC10 mantiene el streaming secuencial, pero cambia el flujo a:

```text
abrir página TIFF secuencialmente
-> guardar derivado OCR

abrir nuevamente la misma página TIFF secuencialmente
-> redimensionar si corresponde
-> guardar preview
```

No se cambia globalmente a `access="random"`, porque eso perdería el beneficio de streaming para TIFF grandes y puede aumentar memoria.

Se agregó una regresión que usa un backend pyvips simulado que falla si una lectura secuencial se reutiliza. La prueba exige dos aperturas independientes para una página TIFF.

La arquitectura registra este invariante en `docs/referencia/ARQUITECTURA_Y_MODELO_ACTUAL.md`.

---

## 6. VALIDACIÓN TIFF DE RC10 - COMPLETADA EL 2026-08-13

Después de instalar RC10 y pasar pruebas focalizadas:

Abrir:

```bash
cd ~/projects/archive_app
source .venv/bin/activate
archive-workbench review-app pilot_data
```

Ir a:

```text
Procesar documentos > Ejecutar > Preparar páginas
```

Seleccionar **sólo**:

```text
leg_15_a_c_2.tiff
leg_15_a_c_6.tiff
```

Usar:

```text
Tratamiento del derivado para OCR: Original
Corrección geométrica: Ninguna
Crear una nueva versión aunque exista una equivalente: desmarcado
```

Ejecutar.

Criterio de cierre de `PILOT-01F`:

- ambos TIFF terminan sin `out of order read`;
- ambos crean su corrida de preparación y derivados;
- no se modifica el original;
- Inventario refleja los cinco casos de la muestra ya preparados;
- Historial registra la operación de forma comprensible.

Si cualquiera de los dos vuelve a fallar, detenerse y analizar el error antes de avanzar a OCR.

---

## 7. EXTRACCIÓN OCR DE LA MUESTRA - COMPLETADA EL 2026-08-13

Continuar con:

```text
Procesar documentos > Ejecutar > Extraer texto
```

sobre los **mismos cinco documentos**.

Usar el perfil principal `extraction.yaml`, asociado al recorrido Surya vigente.

Antes de ejecutar comprobar que `Imagen que recibirá el OCR` corresponda al derivado preparado con:

```text
Tratamiento: Original
Corrección geométrica: Ninguna
```

No marcar una nueva versión equivalente.

Si una página falla, no repetir todo el lote por reflejo. Revisar qué falló y usar el mecanismo de reintento de páginas fallidas cuando corresponda.

---

## 8. DESPUÉS DE LA EXTRACCIÓN OCR

### Selección canónica

Recorrer al menos:

- `leg_15_a_c_2.tiff`, página 1;
- `leg_15_a_c_6.tiff`, página 1;
- `caso_bolson.pdf`, páginas 1, 2 y 4;
- `carp_reg.pdf`, al menos dos páginas visualmente distintas;
- `adm_pub_asp_contr.pdf`, una página sencilla y una problemática.

Comparar la candidata con la imagen real atendiendo a:

- texto omitido;
- caracteres erróneos;
- títulos;
- orden de lectura;
- columnas;
- fragmentación;
- sellos;
- anotaciones;
- bloques desordenados.

La evaluación automática de calidad es auxiliar. No seleccionar masivamente páginas por adelantado.

Para una página suficientemente buena, usar `Seleccionar e inicializar esta página` y comprobar que pase al circuito de revisión.

### OCR regional

Usar una página con un problema localizado y recorrer:

```text
OCR regional
> Documento
> Página
> dibujar una zona
> describir la zona
> Intentar OCR
> Agregar esta zona
> Crear extracción candidata
```

La nueva candidata regional debe aparecer después en Selección canónica y no debe seleccionarse automáticamente.

---

## 9. CORPUS APM CHUBUT QUE NO DEBE REINTERPRETARSE

Fuente física original:

```text
/home/alex/projects/archive_app/corpus
```

Inventario:

- 139 archivos totales;
- 10 PDF;
- 128 TIFF;
- 1 DOCX auxiliar;
- 138 originales documentales procesables.

El DOCX auxiliar:

```text
A- índice de documentos_ (en proceso).docx
```

no es un original archivístico a procesar.

El mapeo ya validado y aplicado es:

```text
11 represents
127 is_part_of
```

`represents`:

- 8 PDF de `caja_administracion_publica/` -> sus documentos concretos;
- `caso_bolson.pdf` -> `Caso El Bolsón`;
- `leg_15_a_c_2.tiff` -> documento Diario Jornada;
- `leg_15_a_c_6.tiff` -> `Parte Side n° 01531/183.-`.

`is_part_of`:

- otros 126 TIFF de `leg_17/` -> `15 - Actividades culturales`;
- PDF de `leg_22` -> `22 - Agrupaciones empresarias y profesionales`.

No convertir automáticamente los otros TIFF en documentos individuales.

---

## 10. CATÁLOGO Y AUDIOVISUAL

Durante el piloto se agregó `Colección` para poder continuar con `rememorARTE`, pero `PILOT-01A` mantiene abierta la revisión conceptual. No afirmar que una playlist de YouTube sea por sí misma una colección archivística.

La prueba audiovisual usó `rememorARTE` y permitió completar el recorrido técnico. No volver a ejecutar la transcripción sólo para confirmar lo ya validado.

---

## 11. FUENTES DE VERDAD DOCUMENTAL DEL PAQUETE

Leer en este orden:

1. este relevo;
2. `.assistant/00_LEER_PRIMERO.md`;
3. todos los documentos de `.assistant/` en el orden indicado allí;
4. `docs/operativos/PENDIENTES_ACTIVOS.md`;
5. `docs/operativos/IMPLEMENTACIONES_REALIZADAS.md`;
6. `docs/operativos/ACTUALIZACION_ACTUAL.md`;
7. `docs/operativos/ESTRATEGIA_DE_PRUEBAS.md`;
8. `docs/operativos/GUIA_PRUEBA_PILOTO.md`;
9. `docs/operativos/HOJA_DE_RUTA_PRE_RELEASE.md`;
10. `docs/HISTORIAL_DE_CAMBIOS.md`;
11. `docs/referencia/ARQUITECTURA_Y_MODELO_ACTUAL.md`;
12. los demás documentos de `docs/referencia/` vinculados a la tarea que se vaya a tocar.

`PENDIENTES_ACTIVOS.md` contiene sólo trabajo abierto/parcial. Si un ítem se cierra, debe salir de allí y registrarse en `IMPLEMENTACIONES_REALIZADAS.md`.

---

## 12. PRUEBAS Y POLÍTICA DE VALIDACIÓN

- No repetir la suite completa salvo una razón material.
- Para RC10 ejecutar pruebas focalizadas de preprocessing/processing/documentación/packaging más recopilación completa.
- La regresión pyvips nueva debe formar parte de la tanda focalizada.
- Las pruebas audiovisuales amplias ya fueron aprobadas y no se repiten por esta corrección TIFF.
- Reutilizar resultados previos mientras el subsistema no haya cambiado de forma relevante.

La candidata final RC10 contiene **134 pruebas focalizadas** en cinco archivos y **568 tests recopilados** en 53 archivos. La suite completa no se repitió.

---

## 13. QUÉ NO HACER AL RETOMAR

- No volver a crear `pilot_data`.
- No volver a importar el catálogo APM.
- No volver a incorporar los 138 archivos.
- No restaurar backups por reflejo.
- No ejecutar `db-upgrade`.
- No volver a transcribir el video de `rememorARTE` salvo una pregunta experimental explícita.
- No volver a preparar los tres PDF de la muestra que ya salieron bien.
- No cambiar pyvips globalmente a `random` sin una razón nueva y pruebas de memoria.
- No usar `project_data` como fuente de resultados del piloto.
- No convertir carpetas físicas en jerarquía archivística automática.
- No procesar el DOCX auxiliar como original documental.
- No hacer push junto con commit/tag.
- No modificar memoria del asistente para sustituir documentación del proyecto.

---

## 14. ESTADO DE VERSIONES Y CIERRE

Última publicación real:

```text
v0.88.2
df118df30e63779d10681618bc2fa9dd173ce7a7
```

Candidata actual:

```text
0.89.0 RC10
```

No hay publicación de 0.89.0 todavía.

No preparar commit/tag/push hasta que Alex complete la validación de la candidata y se revisen sus salidas. El push se mantiene en un paso separado posterior.

---

## 15. PRIMERA RESPUESTA RECOMENDADA EN LA NUEVA CONVERSACIÓN

Después de leer este archivo y la documentación interna, la nueva conversación debería continuar directamente, aproximadamente así:

> Entendido. Tomo `0.88.2` como último estado publicado y `0.89.0 RC10` como candidata no publicada, sin migración y con `pilot_data` como proyecto persistente. No voy a repetir catálogo, incorporación, audiovisual ni los tres PDF ya preparados. El bloqueo inmediato de `Procesar documentos` son los dos TIFF reales que fallaron en RC9 por reutilizar una lectura pyvips secuencial. RC10 reabre la página para OCR y preview y agrega una regresión específica. Primero reviso las salidas de instalación/pruebas que me pases y después te guío para reintentar sólo `leg_15_a_c_2.tiff` y `leg_15_a_c_6.tiff`; si cierran, seguimos con `Extraer texto` sobre los cinco documentos.

A partir de ahí, continuar.

---

## 16. RESUMEN ULTRACORTO

**Publicado:** `v0.88.2` - `df118df30e63779d10681618bc2fa9dd173ce7a7`  
**Candidata:** `0.89.0 RC10`, no publicada  
**Proyecto:** `/home/alex/projects/archive_app/pilot_data`  
**DB:** `0046_audiovisual_timeline_annotations`  
**APM:** 138 originales incorporados; mapeo 11 `represents` + 127 `is_part_of`  
**Audiovisual:** recorrido validado; no repetir  
**Procesamiento:** 3 PDF preparados; 2 TIFF fallaron por lectura pyvips secuencial reutilizada  
**RC10:** reabre la página para preview y corrige copy de `Procesar documentos`  
**Pendientes subsidiarios abiertos:** `PILOT-01A`, `PILOT-01E`, `PILOT-01G`  
**Validación RC10:** `PILOT-01F` cerrado; preparación de los 2 TIFF correcta; OCR Surya 5/5 sin advertencias ni fallos  
**Próximo paso:** completar la revisión visual de `carp_reg.pdf` y `adm_pub_asp_contr.pdf`; luego probar OCR regional sobre un problema localizado y continuar hacia `Revisar documentos`.  


---

### Actualización 2026-08-14 - OCR regional

La preparación de ambos TIFF y la extracción Surya de los cinco documentos cerraron correctamente. La revisión visual de la muestra prevista también resultó satisfactoria. Durante el inicio de `OCR regional` se detectó que la sección no se entiende sin guía externa: el propósito, `candidata`, `selección canónica`, `capa editable`, la leyenda de colores, los pasos 5/6 y el uso de plantillas resultan opacos. Queda registrado `PILOT-01H` para replantear integralmente esa sección en la próxima candidata.

Regla reforzada de interacción: antes de indicar una acción manual, comprobar la sección exacta de la candidata contra el código y/o captura real, incluyendo el tipo de control. En RC10, `Intentar OCR` es una opción del selector `Cómo tratarla`, no un botón. El botón real para iniciar la definición visual es `Dibujar una zona`; después de describirla, el botón de escritura es `Agregar esta zona`.

`PILOT-01` evalúa expresamente si una persona puede comprender y ejecutar cada tarea sin una guía externa que supla la interfaz. Toda dependencia de explicación debe registrarse como hallazgo antes de continuar.


### Actualización 2026-08-15 - cierre de OCR regional y avance en Revisar documentos

La prueba regional real creó 1 corrida nueva, 1 página y 1 objeto sin cambiar la selección explícita de la página. En `Selección canónica`, `Texto vigente` conservó la extracción general seleccionada y `Texto candidato` mostró la corrida regional parcial, que contiene sólo la zona procesada. El nombre y cargo atravesados por una firma se recuperaron parcialmente; queda como optimización futura no bloqueante evaluar variantes regionales robustas sin sobreajustar a este caso. Se registra además que la interfaz no explica que ambas corridas quedan separadas ni si el resultado regional debe entenderse como alternativa parcial o como insumo para una futura versión integrada; esta decisión forma parte de `PILOT-01H`.

En `Revisar documentos` se completaron correctamente las acciones básicas de la prueba: comparación imagen/texto, corrección, comentario, etiqueta y estado de revisión. Se registró `PILOT-01J` para corregir antes de la próxima candidata la orientación de la sección: eliminar una frase redundante de `Orden y estructura`, replantear `Formulario` y `Registrar casillero manual`, agregar una síntesis breve a cada pestaña, mover `Datos adicionales` a la penúltima posición y `Historial general` a la última, y eliminar referentes implícitos como `Crea sugerencias pendientes...` sin explicar sugerencias de qué. `PILOT-01E` incorpora cinco pasadas independientes sobre toda la interfaz antes de empaquetar la próxima candidata para detectar referentes implícitos.

**Próximo paso vigente:** continuar el extremo a extremo con `Entidades y menciones` sobre el mismo documento ya revisado; después registrar una relación explícita y avanzar a las búsquedas. No repetir las acciones básicas de revisión ya validadas.
