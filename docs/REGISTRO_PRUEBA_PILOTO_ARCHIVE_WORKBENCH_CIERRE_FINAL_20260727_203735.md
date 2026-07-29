# Registro de prueba piloto — Archive Workbench

## Estado general inicial

- Versión evaluada: `0.33.0`
- Revisión de base: `0028_operational_readiness`
- Corpus piloto: 5 documentos
- Documentos con extracción: 4
- Documento pendiente de extracción: `caja_administracion_publica_carp_reg`
- Prueba de recuperación: completada correctamente
- Backup probado: `project_20260724T144034Z.zip`
- Migración temporal comprobada: `0023_reproducible_corpus_exports` → `0028_operational_readiness`
- Proyecto activo sin modificaciones durante la prueba: sí

---

## Caso 1 — Recorte periodístico multicolumna

### Identificación

- `source_key`: `leg_17_leg_15_a_c_2`
- Título: *Diario Jornada, 10 de agosto de 1973, “LA PALANGANA DE PONCIO PREPARA UN ESPECTÁCULO”*
- Soporte: TIFF
- Páginas: 1
- Perfil: `tesseract_press_columns_es_v1`
- Resultado automático: 11 objetos, 1376 caracteres
- Puntaje heurístico: 0.945
- Estado inicial: `needs_review`

### Evaluación humana

- **Cobertura textual:** completa.
- **Orden de lectura:** correcto.
- **Separación de bloques:** correcta.
- **Texto crítico:** “LA PALANGANA DE PONCIO” reconocido correctamente.
- **Encabezado descriptivo:** dividido en dos objetos por geometría; resultado aceptable.
- **Título del recorte:** separado correctamente, pero clasificado como `paragraph`.
- **Ruido:** falso positivo final no textual: `nn AMARA MAA |`.
- **Duplicaciones:** no se observaron.
- **Palabras cortadas por salto de línea:** permanecen con guion, por ejemplo `avan-\nzada`.

### Veredicto

**Extracción aceptable para uso y revisión humana.**

No se perdió contenido sustantivo y el orden de lectura es correcto. Los problemas encontrados no bloquean el uso del resultado.

### Mejoras pendientes

1. Mejorar la clasificación de títulos en recortes periodísticos.
2. Filtrar regiones visuales sin contenido textual, evitando falsos positivos.
3. Diseñar una política conservadora de unión de palabras cortadas por guion al final de línea.
4. Mantener separada la evaluación de cobertura textual de la clasificación de tipos de objeto.

### Criterio para la unión de guiones

No aplicar todavía una unión automática general. Antes debe probarse una regla conservadora sobre corpus real y registrar falsos positivos, especialmente en:

- palabras realmente compuestas;
- códigos y siglas;
- nombres propios;
- guiones discursivos;
- enumeraciones;
- cambios de columna o de objeto.

---

## Próximo caso

`leg_17_leg_15_a_c_6` — Parte SIDE n.º 01531/183.

Aspectos a evaluar:

- cobertura de campos mecanografiados y manuscritos;
- orden de lectura entre regiones;
- fragmentación excesiva;
- sellos, líneas de formulario y marcas reconocidas como texto;
- duplicaciones;
- pérdida de contenido;
- utilidad de los objetos producidos para la revisión.


---

## Caso 2 — Ficha o parte SIDE

### Identificación

- `source_key`: `leg_17_leg_15_a_c_6`
- Título: *Parte SIDE n.º 01531/183*
- Soporte: TIFF
- Páginas: 1
- Perfil: `tesseract_side_form_regions_es_v1`
- Resultado automático: 77 objetos, 926 caracteres
- Puntaje heurístico: 0.754
- Estado inicial: `unreviewed`
- Estado de corrida: `completed_with_warnings`

### Evaluación humana

- **Cobertura textual:** prácticamente completa.
- **Errores OCR:** mínimos.
- **Orden de lectura:** correcto.
- **Campos del formulario:** casi todos reconocidos y separados.
- **Pérdidas:** uno o dos elementos pequeños sobre un total de 77.
- **Fragmentación:** alta, pero en general funcional para este tipo documental.
- **Fragmentación principal no deseada:** el cuerpo mecanografiado queda dividido entre los objetos 51 y 52.
- **Duplicaciones:** no se observaron.
- **Manuscritos y notas marginales:** identificados adecuadamente; algunos aparecen antes en el orden de objetos, sin impedir la lectura.
- **Sellos:** algunos se identifican correctamente como regiones; otros producen OCR espurio.
- **Ruido visual:** líneas del formulario reconocidas como `A A A A` o `A A`.
- **Sello con OCR defectuoso:** `8 DRBOVINCIA Del aunar |`, correspondiente a “PROVINCIA DEL CHUBUT”.
- **Texto crítico:** el pedido de informar sobre espectáculos de contenido ideológico fue recuperado.

### Veredicto

**Extracción aceptable para uso y revisión humana, con advertencias no bloqueantes.**

La cobertura, el orden y la separación general de campos son suficientes. El ruido se concentra en líneas y sellos, y no desplazó ni duplicó el contenido principal.

### Mejoras pendientes

1. Evaluar que los campos impresos y repetitivos de fichas o formularios puedan quedar ocultos por defecto, sin eliminarlos.
2. Mejorar la clasificación de regiones de sello para evitar que se incorporen al cuerpo textual.
3. Filtrar secuencias producidas por líneas y casilleros, como `A A A A`, usando reglas conservadoras.
4. Revisar la unión de bloques textuales separados por geometría cuando forman una misma oración.
5. Mantener visibles y recuperables los manuscritos, sellos y campos ocultos aunque no formen parte del texto exportado por defecto.
6. No reducir la cantidad de objetos únicamente por su número: en formularios complejos la fragmentación puede preservar mejor la estructura.

### Criterio provisional para formularios

Los campos preimpresos no deben borrarse. Puede resultar conveniente marcarlos con tipos específicos y permitir:

- ocultarlos por defecto en la lectura continua;
- mostrarlos en la revisión estructural;
- incluirlos o excluirlos desde los perfiles de exportación;
- conservar siempre bbox, texto original y procedencia.


---

## Caso 3 — PDF de 34 páginas: muestra de evaluación

### Identificación

- `source_key`: `caja_administracion_publica_adm_pub_asp_contr`
- Título: *Ejemplar 0619. Síntesis de conferencias*
- Soporte: PDF
- Páginas: 34
- Perfil: `docling_tesseract_es_v1`
- Estado de corrida: `completed_with_warnings`
- Selección canónica: 34/34 páginas
- Estado inicial de calidad: `unreviewed`

### Muestra elegida

Se seleccionaron cinco páginas representativas:

| Página | Objetos | Caracteres | Motivo |
|---|---:|---:|---|
| 1 | 7 | 110 | Inicio del documento y baja densidad |
| 18 | 13 | 806 | Página interior de densidad media |
| 26 | 7 | 1291 | Mayor densidad textual |
| 33 | 3 | 81 | Página casi vacía o de cierre |
| 34 | 18 | 660 | Última página y alta fragmentación relativa |

### Criterio de evaluación

En cada página se revisará:

- cobertura del texto sustantivo;
- orden de lectura;
- segmentación en objetos;
- títulos, encabezados y pies;
- duplicaciones;
- ruido visual convertido en texto;
- palabras cortadas por guion;
- continuidad entre bloques;
- regiones omitidas;
- utilidad para revisión humana.

La revisión se realizará página por página antes de emitir un veredicto general sobre la extracción.


#### Página 1 — Portada

- **Cobertura textual:** casi completa.
- **Omisiones:** un sello no fue detectado ni clasificado.
- **Orden de lectura:** correcto.
- **Objetos detectados:** 4 encabezados internos y 3 párrafos.
- **Tipo real de página:** portada.
- **Segmentación:** un título quedó dividido en dos objetos por su geometría; resultado aceptable.
- **Ruido:** mínimo; un rectángulo fue interpretado como `(` y `|`.
- **Cantidad de caracteres:** 110, razonable para la página.

**Veredicto de página:** aceptable para uso y revisión humana.

**Mejoras pendientes:**

1. Detectar páginas de portada como una categoría estructural.
2. Mejorar la identificación de sellos ausentes.
3. Filtrar signos aislados producidos por marcos, rectángulos o líneas.
4. No fusionar automáticamente títulos separados por geometría sin comprobar continuidad.

#### Página 18 — Página interior típica

- **Cobertura textual:** completa.
- **Omisiones:** no se observaron.
- **Orden de lectura:** correcto.
- **Tipos detectados:** encabezado de página, párrafo, ítem de lista y encabezado interno.
- **Clasificación general:** adecuada.
- **Observación:** uno de los objetos clasificados como encabezado de página corresponde en realidad a un número de página.

**Veredicto de página:** aceptable para uso y revisión humana.

**Mejora pendiente:**

1. Incorporar una heurística conservadora para distinguir números de página de encabezados, considerando posición, longitud, patrón numérico y repetición entre páginas, sin reclasificar automáticamente otros encabezados breves.

#### Página 26 — Página de mayor densidad

- **Cobertura textual:** completa.
- **Omisiones:** no se observaron.
- **Orden de lectura:** correcto.
- **Palabras cortadas por guion:** recuperadas y unificadas correctamente.
- **Observaciones de clasificación:** un encabezado de página no fue identificado; el número de página volvió a quedar clasificado como encabezado.

**Veredicto de página:** aceptable para uso y revisión humana.

#### Página 33 — Página de baja densidad

- **Cobertura textual:** completa.
- **Orden de lectura:** correcto.
- **Cantidad de texto:** razonable para la página.
- **Observación repetida:** el número de página quedó clasificado como encabezado.
- **Clasificación ambigua:** una frase final resaltada fue clasificada como encabezado interno. La clasificación es plausible y no requiere corrección prioritaria.

**Veredicto de página:** aceptable para uso y revisión humana.

#### Página 34 — Última página

- **Cobertura textual:** completa.
- **Omisiones:** no se observaron.
- **Orden de lectura:** correcto.
- **Fragmentación:** funcional; los 18 objetos responden a la estructura de la página.
- **Observación de clasificación:** el encabezado de página fue identificado como encabezado interno.
- **Observación repetida:** el número de página quedó clasificado como encabezado.

**Veredicto de página:** aceptable para uso y revisión humana.

### Veredicto general del caso 3

**Extracción aceptada sobre una muestra estratificada de cinco páginas.**

La muestra cubrió inicio, página interior, máxima densidad, baja densidad y cierre. No se observaron pérdidas sustantivas, errores de orden de lectura, duplicaciones ni fragmentación que impida la revisión. La unión de palabras cortadas por guion funcionó correctamente en la página más densa.

### Mejoras pendientes del caso 3

1. Distinguir números de página de encabezados mediante una heurística conservadora.
2. Mejorar la detección y clasificación de encabezados repetidos.
3. Reconocer portadas como estructura de página cuando corresponda.
4. Mejorar la detección de sellos omitidos.
5. Filtrar signos aislados producidos por marcos o rectángulos.
6. Mantener las clasificaciones ambiguas cuando no afecten cobertura, orden ni exportación.


---

## Caso 4 — Caso Bolsón: evaluación por perfiles combinados

### Identificación

- `source_key`: `leg_17_caso_bolson`
- Título: *Caso Bolsón: cuento infantil*
- Soporte: PDF
- Páginas: 9
- Selección canónica: 9/9 páginas
- Particularidad: la selección combina tres perfiles de extracción.

### Distribución de perfiles

| Páginas | Perfil | Observación inicial |
|---|---|---|
| 1, 2, 3 y 8 | `tesseract_official_degraded_es_v1` | Documento degradado; revisar ruido, segmentación y pérdida de texto |
| 4 y 5 | `tesseract_book_text_es_v1` | Texto de lectura continua; revisar párrafos, títulos e hifenación |
| 6, 7 y 9 | `tesseract_sparse_page_es_v1` | Páginas de baja densidad; revisar fusiones y elementos visuales |

### Señales cuantitativas que requieren observación

- Página 2: 29 objetos y 2355 caracteres. Comprobar si la fragmentación responde a la estructura real.
- Página 6: 1 objeto y 1171 caracteres. Comprobar si existe una fusión excesiva.
- Página 7: 8 objetos y 402 caracteres. Comprobar si son bloques reales o fragmentación de elementos breves.
- Página 9: 3 objetos y 130 caracteres. Comprobar si la baja densidad es correcta y si no se omitieron elementos.

### Evaluación solicitada

#### Perfil `tesseract_official_degraded_es_v1` — páginas 1, 2, 3 y 8

- cobertura textual;
- orden de lectura;
- errores OCR;
- ruido producido por degradación, sellos o fondo;
- fragmentación de la página 2;
- continuidad entre objetos;
- tipos de objeto;
- elementos omitidos.

#### Perfil `tesseract_book_text_es_v1` — páginas 4 y 5

- continuidad de párrafos;
- títulos o encabezados;
- unión de palabras cortadas por guion;
- números de página;
- fusiones o divisiones incorrectas;
- texto omitido o duplicado.

#### Perfil `tesseract_sparse_page_es_v1` — páginas 6, 7 y 9

- correspondencia entre baja densidad visual y cantidad de objetos;
- posible fusión excesiva en la página 6;
- posible fragmentación excesiva en la página 7;
- cobertura de la página 9;
- ruido visual;
- orden de lectura;
- tipos de objeto.

No se emitirá un veredicto general hasta revisar los tres grupos.


### Benchmark OCR selectivo

- Benchmark: `61c4397e-e8c3-421c-97c8-90978edc9b46`
- Páginas evaluadas: 1, 4 y 8
- Candidatos: 36
- Variantes: `original`, `grayscale_autocontrast` y `otsu`
- PSM comparados: 3, 4, 6 y 11

#### Página 4

El ranking heurístico ubicó primero `p0004_otsu_psm3`, pero la lectura humana confirmó que mantiene la falsa separación en columnas: las mitades de las líneas aparecen en bloques sucesivos y no en el orden textual real.

Los candidatos PSM 4 reconstruyen correctamente las líneas continuas. El mejor candidato humano es:

```text
p0004_original_psm4
```

Motivos:

- conserva el texto en orden lineal;
- recupera las palabras completas;
- evita la falsa alternancia entre mitades de línea;
- introduce solo ruido breve en la zona superior;
- requiere menos corrección que el candidato con mayor puntaje heurístico.

Conclusión: para esta página, el puntaje heurístico no identifica el mejor layout. Debe priorizarse PSM 4 y evaluación humana.

#### Página 1

El candidato mejor ubicado para la página 1 es esencialmente equivalente al perfil vigente (`grayscale_autocontrast`, PSM 3). Ninguna combinación produce una mejora suficiente.

Los PSM 11 y 6 agregan fragmentación o ruido sin resolver las sustituciones graves. Otsu cambia algunos caracteres, pero no recupera de manera confiable nombres, palabras ni frases críticas.

Conclusión: el problema no se resuelve ajustando solamente PSM o estas tres variantes de imagen. Requiere otro preprocesamiento o backend OCR.

#### Página 8

Los candidatos PSM 4 obtienen mejor puntaje heurístico, pero fragmentan el documento y alteran el orden de lectura.

PSM 3 y PSM 6 conservan mejor la continuidad. PSM 6 produce un cuerpo más lineal, pero mantiene errores OCR importantes y ruido de sellos y firmas.

Conclusión: puede conservarse PSM 6 como candidato comparativo, pero ninguna variante alcanza calidad suficiente para reemplazar la selección canónica.

### Resultado metodológico del benchmark

1. El puntaje heurístico sirve para ordenar candidatos, no para elegir automáticamente.
2. La calidad OCR y la calidad del layout deben evaluarse por separado.
3. La página 4 puede mejorar dentro de Tesseract mediante PSM 4.
4. Las páginas 1 y 8 alcanzaron el límite práctico de la grilla actual.
5. La página 6 requiere detección de tipo de página y OCR regional, no otra corrida de OCR completo.
6. Estos cuatro casos quedan como benchmark mínimo para comparar Surya u otro backend:
   - página 1: documento oficial muy degradado;
   - página 4: texto sobre fondo ilustrado con falsa segmentación;
   - página 6: ilustración con título breve;
   - página 8: documento oficial de bajo contraste.


### Comparación de la nueva corrida de la página 4

- Corrida: `0aefc644-5d0b-487f-9a46-9b722c8ff35a`
- Objetos: 7
- Caracteres: 552
- Variante: original
- PSM: 4

#### Resultado

La nueva corrida corrige la falla bloqueante de la extracción canónica anterior.

El cuerpo principal aparece ahora en orden lineal:

```text
Aziz es hijo de un pastor. Lo mismo en verano que en
invierno, vive en las altas montañas, en los pastizales, que
allí llaman Dzhay lau. Todo el día el padre de Aziz
apacienta las grandes ovejas —valuj, mientras la madre
está en la yurta, hace la comida y cose la ropa, y al atardecer
ayuda a recoger las ovejas en el aprisco.
```

El segundo párrafo queda dividido en dos objetos consecutivos, pero conserva el orden:

```text
Ya han recogido hasta la última oveja. El padre entra en la
yurta, toma en sus brazos al pequeño Aziz y empieza a jugar con
él, echándolo a lo alto.
```

Persisten problemas no bloqueantes:

- cuatro objetos de ruido o texto deficiente en la zona superior;
- `[` espurio antes de “ayuda”;
- puntuación duplicada al final;
- ilustración y manuscrito sin clasificación adecuada;
- división del segundo párrafo en dos objetos.

#### Veredicto

**La nueva corrida es claramente superior para la página 4 y debe conservarse como candidata preferida.**

No se cambia todavía la selección canónica debido a una limitación operativa de la versión 0.33.0.

### Limitación detectada en Procesamiento

La pestaña `Selección canónica` permite elegir una corrida, pero no ofrece una vista previa de:

- texto candidato;
- imagen;
- bounding boxes;
- comparación con la selección vigente.

El botón `Abrir en Revisión` abre la capa editable existente, basada en la selección canónica anterior. No abre la corrida candidata elegida.

Además, si se cambia la selección canónica después de inicializar una página, la capa editable queda marcada como `stale`, pero la versión 0.33.0 no ofrece una acción explícita para:

- adoptar la nueva extracción cuando la página todavía no fue corregida;
- comparar ambas versiones;
- rebasar manualmente una edición existente sobre el nuevo OCR.

### Mejora requerida

Incorporar en una versión posterior:

1. vista previa de corridas candidatas sin modificar la selección;
2. comparación lado a lado con la selección vigente;
3. visualización de bboxes candidatos;
4. acción segura “adoptar nueva extracción”;
5. reemplazo directo solo cuando la página no tiene correcciones humanas;
6. rebase o resolución manual cuando ya existen correcciones;
7. conservación completa del linaje y de la extracción anterior.


---

## Caso 5 — Carpeta con reglamentos: benchmark inicial

### Identificación

- `source_key`: `caja_administracion_publica_carp_reg`
- Título: *Carpeta con reglamentos*
- Soporte: PDF
- Páginas: 18
- Extracción previa: ninguna
- Benchmark: `9160fe0e-9fcd-4ac8-826b-42a61200e9a7`
- Páginas evaluadas: 1, 9 y 18
- Candidatos: 36

### Evaluación de candidatos

#### Página 1 — portada o inventario

El ranking heurístico coloca primero `p0001_grayscale_autocontrast_psm11`, pero ese candidato fragmenta expresiones estructurales como:

```text
ESTA CARPETA
CONTIENE
```

y separa los indicadores de ítem del contenido.

La variante más equilibrada es:

```text
p0001_original_psm4
```

Conserva mejor:

- la estructura de portada;
- la línea “ESTA CARPETA CONTIENE”;
- los tres ítems;
- la continuidad visual del listado.

Persisten errores menores en marcas y numeración.

#### Página 9 — reglamento denso

Los candidatos PSM 11 obtienen mayor puntaje heurístico, pero fragmentan casi todas las líneas en piezas pequeñas y destruyen la lectura continua.

La mejor base humana es:

```text
p0009_original_psm3
```

No es perfecta, pero conserva bloques y líneas más largos, y permite reconstruir el orden textual con menos intervención que PSM 11.

PSM 6 produce más caracteres, pero también más ruido y no mejora claramente el reconocimiento.

#### Página 18 — radiograma o comunicación breve

La mejor combinación es:

```text
p0018_original_psm3
```

Es además el candidato mejor puntuado para esa página. Recupera el cuerpo principal en orden y deja el ruido concentrado en firmas, sellos y zonas inferiores.

### Decisión provisional

No hay una única combinación óptima para las tres páginas:

- página 1: `original + PSM 4`;
- página 9: `original + PSM 3`;
- página 18: `original + PSM 3`.

Para producir una primera corrida completa se utilizará:

```text
original + PSM 3
```

Motivos:

1. es la mejor opción para las páginas 9 y 18;
2. mantiene un resultado aceptable en la página 1;
3. evita la fragmentación severa de PSM 11;
4. permite obtener una línea de base uniforme para las 18 páginas;
5. las páginas problemáticas podrán reextraerse después sin sobrescribir la corrida base.

La página 1 podrá recibir posteriormente una corrida selectiva con PSM 4.


### Corrida base completa

- Corrida: `c83c83b9-d057-4ecd-93f9-521b87963db7`
- Perfil: `tesseract_tsv_es_psm3_original_v1`
- Páginas procesadas: 18/18
- Objetos extraídos: 784
- Caracteres: 20.019
- Estado: `completed`
- Calidad inicial: `unreviewed`
- Puntaje heurístico: 0.737
- Política de selección: `never`

### Interpretación inicial

La corrida constituye una línea de base completa, pero todavía no debe seleccionarse como canónica.

La cantidad de 784 objetos es alta para 18 páginas y requiere comprobar:

- si responde a enumeraciones, líneas, campos y estructuras reales;
- si hay fragmentación excesiva;
- si sellos, firmas, marcos o manchas produjeron objetos espurios;
- si las páginas densas mantienen el orden de lectura;
- si las páginas breves conservan todo el contenido.

Las páginas 1, 9 y 18 ya fueron inspeccionadas durante el benchmark con la misma combinación `original + PSM 3`. Se seleccionarán páginas adicionales a partir de los extremos cuantitativos de la corrida completa.


### Muestra adicional para evaluación

Se eligieron tres páginas extremas de la corrida completa:

| Página | Objetos | Caracteres | Motivo |
|---|---:|---:|---|
| 4 | 54 | 2226 | Mayor densidad textual |
| 5 | 120 | 1619 | Mayor cantidad de objetos |
| 14 | 14 | 223 | Menor densidad y pocos objetos |

Estas páginas complementan las páginas 1, 9 y 18 ya revisadas durante el benchmark.

### Criterio de cierre del documento

La corrida podrá considerarse aceptable si:

- las páginas densas conservan orden y contenido;
- la página 5 no muestra fragmentación inútil o ruido masivo;
- la página 14 no omite contenido breve;
- no aparecen pérdidas sistemáticas;
- los errores se concentran en clasificación, sellos, firmas o ruido no bloqueante.

Si alguna de estas páginas presenta fallas de layout, pérdida de texto o OCR inutilizable, se definirá una estrategia de reextracción selectiva.


### Evaluación humana completa de las 18 páginas

#### Nota operativa sobre la selección canónica

La corrida fue seleccionada como canónica para poder inicializar las páginas y abrirlas en Revisión.

Esta selección **no constituye una aprobación de calidad**. Fue necesaria porque la versión 0.33.0 no permite:

- abrir una corrida no canónica directamente en Revisión;
- inicializar una capa editable provisoria desde una candidata;
- previsualizar texto y bounding boxes antes de seleccionar;
- comparar una candidata con la selección vigente dentro del flujo normal.

Debe incorporarse una alternativa explícita para revisar corridas candidatas sin convertirlas primero en canónicas.

#### Página 1

- Resultado general utilizable.
- Solo se observaron pequeños errores OCR.
- No presenta fallas bloqueantes.

#### Página 2

- Fragmentación excesiva: líneas de un mismo párrafo aparecen como objetos separados.
- Sellos identificados incorrectamente como texto.

#### Página 3

- Mismo problema principal que la página 2:
  - excesiva fragmentación;
  - líneas de un mismo párrafo separadas en múltiples objetos.

#### Página 4

- Orden de lectura correcto.
- Continuidad lógica entre párrafos correcta.
- Fragmentación muy alta: prácticamente cada línea fue detectada como un objeto independiente.
- Todos los objetos se clasificaron como párrafos, aunque existen:
  - un encabezado;
  - un pie de página.
- Hay ruido OCR producido por líneas y artefactos, aunque no es abundante.
- Un sello muy desgastado no fue identificado.
- Una firma no fue identificada.
- Resultado parcialmente utilizable, pero estructuralmente deficiente.

#### Página 5

- Repite los problemas de la página 4:
  - fragmentación muy alta;
  - clasificación pobre de tipos;
  - errores OCR.
- Presenta además una falla de orden:
  - algunos bounding boxes se desplazan hacia arriba;
  - se altera el orden de lectura.
- Existe duplicación parcial de un objeto.
- Es una de las páginas más problemáticas de la corrida.

#### Página 6

- Página muy deteriorada y parcialmente ilegible.
- Fragmentación extrema.
- Bounding boxes de tamaños y posiciones muy dispares.
- El deterioro del original explica parte importante del problema.
- Requiere evaluación automática de calidad de imagen y preprocesamiento previo.

#### Página 7

- Página deteriorada.
- Los errores OCR son moderados, no tan graves como en la página 6.
- Persisten:
  - fragmentación;
  - yuxtaposición de bounding boxes.

#### Página 8

- Identificación muy deficiente.
- El escaneo presenta numerosas líneas en diagonal.
- La orientación y deformación dificultan la detección de objetos.
- Requiere un método específico para deskew, dewarp o corrección geométrica previa.

#### Página 9

- Una parte importante de la página no fue detectada.
- Existen numerosas líneas en diagonal.
- Fragmentación alta.
- Yuxtaposición de bounding boxes.
- Resultado no aceptable.

#### Página 10

- Mejor resultado que las páginas anteriores.
- Persisten bastantes errores OCR.
- Hay algunos problemas de orden de lectura.
- Parcialmente utilizable.

#### Página 11

- El texto principal se recupera mejor.
- Aproximadamente la mitad de los objetos son artefactos OCR sin correlato visual válido.
- Requiere filtrado de ruido.

#### Página 12

- Fue interpretada como documento multicolumna.
- Gran parte de la primera “columna” corresponde en realidad a letras utilizadas como bullets.
- La detección de columnas produce una estructura falsa.
- Requiere distinguir enumeraciones marginales de columnas reales.

#### Página 13

- Resultado similar a las páginas 1 y 2.
- Contenido parcialmente utilizable.
- Persisten errores OCR y fragmentación.

#### Página 14

- La página contiene solamente sellos y firmas.
- Esos elementos fueron identificados incorrectamente como texto.
- Los 223 caracteres no representan contenido textual válido.
- Debe clasificarse como página sin texto mecanografiado o como página de marcas visuales.

#### Página 15

- Página muy deteriorada.
- Numerosos errores OCR.
- Presencia de:
  - sellos;
  - encabezados;
  - artefactos;
  - escaneo diagonal.
- Resultado no aceptable.

#### Página 16

- Es la misma página 15 mejor escaneada, o posiblemente otra foja/copia del mismo contenido.
- Mejora el OCR respecto de la página 15.
- Continúa el problema general de fragmentación.
- Es candidata para detección de duplicados o versiones del mismo documento.

#### Página 17

- Contiene numerosos elementos de ficha o formulario.
- El escaneo inclinado dificulta la detección.
- Sellos identificados como texto.
- El texto principal se reconstruye parcialmente.
- Fragmentación alta.
- Resultado incompleto.

#### Página 18

- Fragmentación persistente.
- Mejor orientación que otras páginas.
- Texto mecanografiado con errores de tipeo y correcciones originales, lo que aumenta los errores OCR.
- Sellos identificados como texto.
- Firmas identificadas como texto.
- Texto manuscrito identificado como texto.
- El cuerpo principal es parcialmente recuperable.

### Veredicto general del Caso 5

**La corrida completa no aprueba como extracción canónica de calidad.**

La selección canónica actual debe interpretarse solo como una decisión operativa para habilitar la revisión.

Problemas sistémicos:

1. fragmentación línea por línea;
2. clasificación insuficiente de encabezados, pies, sellos, firmas y manuscritos;
3. falsos positivos producidos por líneas, manchas y artefactos;
4. fallas de orden por bounding boxes yuxtapuestos;
5. detección incorrecta de columnas;
6. falta de corrección geométrica para páginas inclinadas o deformadas;
7. ausencia de evaluación automática de calidad previa al OCR;
8. falta de un flujo seguro para revisar candidatas no canónicas.

### Requisitos derivados para el pipeline

#### Evaluación automática de calidad de página

Incorporar métricas previas al OCR para estimar:

- inclinación;
- deformación;
- contraste;
- desenfoque;
- ruido de fondo;
- densidad textual;
- presencia de líneas;
- proporción de regiones no textuales;
- confianza OCR;
- tasa de objetos de uno o pocos caracteres;
- fragmentación media;
- superposición o yuxtaposición de bounding boxes.

Estas métricas deben sugerir un perfil de preprocesamiento, no modificar automáticamente el original.

#### Preprocesamiento conservador

Evaluar variantes reproducibles y no destructivas:

- rotación y deskew;
- dewarp;
- autocontraste;
- binarización;
- reducción de ruido;
- eliminación controlada de líneas;
- recorte;
- detección de orientación;
- OCR regional.

No utilizar restauración generativa que invente trazos o contenido documental.

#### Control de calidad para análisis posteriores

Las páginas marcadas como:

- `rejected`;
- `needs_review`;
- `unreviewed`;
- o con extracción `stale`;

deben poder excluirse, por configuración, de:

- identificación automática de entidades;
- extracción de relaciones;
- embeddings;
- índices semánticos;
- resúmenes automáticos;
- estadísticas de corpus;
- entrenamiento o construcción de ground truth.

La opción más segura por defecto es procesar automáticamente solo páginas `accepted` o `approved`, permitiendo ampliar el conjunto de manera explícita.

Debe conservarse, de todos modos, la búsqueda literal sobre texto no aprobado cuando el usuario la habilite, mostrando claramente su estado de calidad.

#### Detección de duplicados y versiones

Las páginas 15 y 16 sugieren incorporar:

- similitud visual;
- similitud textual;
- detección de copias o versiones;
- vínculo entre una foja degradada y otra copia más legible;
- posibilidad de usar la copia mejor conservada como ayuda de lectura sin sustituir el original.

### Estado final del Caso 5

- Extracción base completa: realizada.
- Selección canónica: realizada por necesidad operativa.
- Revisión humana: completada.
- Calidad general: no aceptada.
- Próximo uso recomendado: benchmark de preprocesamiento, layout y backend OCR.


---

## Prueba funcional de Revisión: edición, eliminación e historial

### Caso probado

Documento:

```text
leg_17_leg_15_a_c_2
```

Acción realizada:

- eliminación del objeto falso positivo final `nn AMARA MAA |`;
- guardado de la edición;
- aprobación de la página;
- cierre y reapertura de la página;
- verificación de persistencia;
- activación de `Mostrar objetos eliminados`;
- inspección del objeto eliminado;
- apertura de la pestaña `Historial` del objeto.

### Resultado

La eliminación persistió correctamente y el objeto aparece con estado `deleted`.

En la pestaña `Historial` del objeto se muestra únicamente:

```text
Revisión 10 · delete · alex · 2026-07-27T17:45
```

No aparece una entrada previa que represente explícitamente:

- el estado OCR inicial;
- la creación o inicialización del objeto editable;
- el texto anterior a la eliminación.

### Interpretación

La interfaz actual ofrece un historial de acciones o revisiones registradas sobre cada objeto, pero no expone necesariamente una secuencia completa desde el estado inicial.

En este caso concreto, desde la interfaz no puede reconstruirse visualmente la secuencia:

```text
objeto OCR inicial → objeto editable → eliminación
```

Solo se observa la acción de eliminación.

Esto puede responder a una de estas situaciones, que deberán verificarse en la implementación:

1. el estado inicial no se guarda como revisión;
2. se guarda, pero la interfaz no lo muestra;
3. el historial registra solamente mutaciones posteriores a la inicialización;
4. la eliminación conserva una referencia interna al estado anterior, pero no la presenta al usuario.

### Requisito: historial integral de página

Debe incorporarse una vista de `Historial de la página`, pero evitando sumar otra funcionalidad aislada o dispersa.

La solución debe ser limpia, integrada y coherente con el resto de Revisión.

#### Criterios de diseño

La vista debería centralizar, en un único lugar:

- creación o inicialización de la capa editable;
- edición de texto;
- cambio de tipo de objeto;
- movimiento o redimensionamiento;
- división;
- combinación;
- reordenamiento;
- creación;
- eliminación;
- restauración;
- anotaciones;
- cambios de estado de la página;
- aprobación o rechazo;
- acciones de deshacer y rehacer;
- autor y fecha;
- relación con la extracción canónica utilizada.

No debería incorporarse como una pestaña adicional desconectada de:

- el historial por objeto;
- el estado de la página;
- deshacer y rehacer;
- la selección canónica;
- las revisiones o versiones.

#### Organización recomendada

Una única vista de historial de página con:

- línea temporal cronológica;
- filtros por tipo de acción;
- filtro por objeto;
- enlaces desde cada evento al objeto afectado;
- posibilidad de ver el estado anterior y posterior;
- agrupación de acciones realizadas en una misma operación;
- distinción clara entre:
  - extracción inicial;
  - edición humana;
  - cambio de selección canónica;
  - cambio de estado de calidad.

El historial por objeto debería funcionar como una vista filtrada de ese mismo sistema, no como un mecanismo independiente.

### Veredicto de la prueba

- Persistencia de la eliminación: aprobada.
- Estado `deleted`: aprobado.
- Historial por objeto: parcial.
- Reconstrucción completa del estado inicial y sus cambios: no disponible desde la interfaz.
- Historial integral de página: ausente.
- Riesgo de fragmentación funcional: debe considerarse explícitamente en el próximo diseño.


---

## Estado operativo después de la primera aprobación

Salida de `project-readiness`:

- Catálogo: 6 documentos procesables y 6 archivos verificados.
- Procesamiento y revisión: 63 páginas editables y 1 aprobada.
- Trabajos coordinados: 5.
- Trabajo colectivo: 1 asignación activa.
- Búsqueda literal: índice desactualizado, generación 32/1187.
- Búsqueda semántica: perfil `Multilingüe E5 — objetos` pendiente de reconstrucción.
- Entidades y relaciones: 4 entidades, 3 menciones y 1 relación activa.
- Exportación: 1 perfil y 1 exportación materializada.
- Intercambio offline: 6 checkpoints.
- Recuperación: backup más reciente verificado.
- Estado general: `attention`, con 7 componentes listos y 2 que requieren atención.

### Interpretación

El aumento de 45 a 63 páginas editables corresponde a las 18 páginas inicializadas del documento `caja_administracion_publica_carp_reg`.

La página corregida de `leg_17_leg_15_a_c_2` figura como la única aprobada.

Los índices literal y semántico quedaron desactualizados como consecuencia normal de:

- la incorporación de nuevas páginas editables;
- la eliminación de un objeto;
- el cambio de estado de una página a `approved`.

### Próxima prueba: búsqueda literal filtrada por estado de página

Objetivos:

1. comprobar que el índice se reconstruye con la capa editable actual;
2. verificar que el objeto eliminado no aparece;
3. verificar que el filtro `Estado de la página = Aprobado` limita los resultados a la única página aprobada;
4. comprobar que los resultados abren el objeto y la página correctos.

La interfaz exacta se encuentra en:

```text
Barra lateral → Navegación → Vista → Búsqueda literal
```

Dentro del formulario, el filtro está en la columna derecha:

```text
Estado de la página
```

La opción que debe seleccionarse es:

```text
Aprobado
```


### Resultado de la prueba de búsqueda literal

Las tres pruebas fueron superadas:

1. La búsqueda exacta `LA PALANGANA DE PONCIO`, filtrada por página aprobada, devolvió la página correcta.
2. La búsqueda `nn AMARA MAA`, con objetos eliminados excluidos, no devolvió resultados.
3. La búsqueda `UN CORDERITO CON CUERNOS`, limitada a páginas aprobadas, no devolvió resultados.

**Veredicto: búsqueda literal aprobada.**

Se verificó:

- reconstrucción correcta del índice;
- respeto del estado de aprobación de página;
- exclusión de objetos eliminados;
- navegación desde el resultado hacia la página correspondiente.

---

## Próxima prueba: índice y búsqueda semántica con corpus aprobado

### Objetivo

Construir un perfil semántico que indexe únicamente páginas aprobadas, para comprobar que las páginas no revisadas o rechazadas no contaminan los embeddings.

### Configuración requerida

Vista:

```text
Barra lateral → Navegación → Vista → Búsqueda semántica
```

Perfil:

```text
Multilingüe E5 — objetos
```

Pestaña:

```text
Configurar e indexar
```

Valores:

- Unidad indexada: `Objeto textual`
- Tipos de objeto incluidos: vacío
- Estados del objeto: vacío
- Estados de página: únicamente `Aprobado`
- Tamaño máximo del fragmento: conservar valor actual
- Superposición: conservar valor actual
- Modelo y revisión: conservar valores actuales

Dejar `Estados del objeto` vacío es intencional: la página está aprobada, pero sus objetos individuales pueden conservar estados distintos. El filtro decisivo de esta prueba es el estado de página.

### Construcción

- Dispositivo para indexar: `cuda`
- Lote: `32`
- Acción: `Construir o reconstruir`

### Resultado esperado

El índice debe contener únicamente objetos activos de la única página aprobada.

El objeto eliminado `nn AMARA MAA |` no debe incorporarse.

### Consulta de prueba

En la pestaña `Buscar`:

- Consulta: `preparación de un espectáculo teatral`
- Máximo de resultados: `20`
- Puntaje mínimo: `0.20`
- Dispositivo: `cuda`
- Filtro temporal: desactivado

Debe aparecer como resultado el documento periodístico `leg_17_leg_15_a_c_2`.

La acción `Abrir` debe navegar al objeto y página correspondientes.


### Resultado de la prueba de búsqueda semántica

La prueba fue superada.

- Perfil: `Multilingüe E5 — objetos`.
- Corpus indexado: únicamente páginas aprobadas.
- Fragmentos generados: 4.
- La cantidad es correcta porque los párrafos de la página habían sido unificados previamente.
- Consulta: `preparación de un espectáculo teatral`.
- Primer resultado: documento `leg_17_leg_15_a_c_2`, página 1.
- Similitud: `0.853`.
- El fragmento recuperado corresponde efectivamente al anuncio de preparación y estreno del espectáculo de La Palangana de Poncio.
- La navegación al resultado funcionó correctamente.
- No se incorporaron páginas no aprobadas al perfil.

**Veredicto: índice y búsqueda semántica aprobados.**

### Mejora pendiente: calibración del umbral

El puntaje mínimo `0.20` se utilizó únicamente para evitar excluir resultados durante la prueba funcional. No debe considerarse un umbral recomendado.

La calibración posterior deberá utilizar:

- consultas con resultado esperado;
- consultas difíciles o indirectas;
- consultas sin resultado pertinente;
- distribución de puntajes por perfil y modelo;
- precisión en los primeros resultados;
- análisis de falsos positivos y falsos negativos.

El umbral debe configurarse por perfil y modelo. El puntaje es relativo al espacio vectorial utilizado y no representa por sí mismo una relación analítica ni una probabilidad.

---

## Próxima prueba: entidades, menciones y relaciones

Antes de modificar registros existentes, se listarán las cuatro entidades actuales, sus alias, estado de revisión y cantidad de menciones. Esto permitirá elegir un caso de prueba real sin crear duplicados.

Comando:

```bash
archive-workbench entity-list project_data
```


### Inventario inicial de entidades

El comando `entity-list` devolvió cuatro entidades activas:

| Entidad | Tipo | Estado | Revisión | Alias | Menciones |
|---|---|---|---:|---:|---:|
| Dirección de Inteligencia de la Policía de la Provincia de Buenos Aires | organization | unreviewed | 2 | 0 | 0 |
| Poder Ejecutivo Nacional | organization | approved | 1 | 0 | 0 |
| Secretaría de Inteligencia de Estado | organization | approved | 2 | 0 | 0 |
| Servicio de Informaciones del Chubut | organization | approved | 2 | 0 | 0 |

### Interpretación

- Todas las entidades existentes son organizaciones.
- Tres están aprobadas y una permanece sin revisar.
- Ninguna tiene alias.
- Ninguna tiene menciones vinculadas.
- No se modificarán estos cuatro registros durante la primera prueba.

### Caso de prueba elegido

Se creará una entidad nueva a partir de la página aprobada del documento:

```text
leg_17_leg_15_a_c_2
```

Entidad:

```text
La Palangana de Poncio
```

Tipo:

```text
Organismo / institución
```

Justificación: el texto presenta a `La Palangana de Poncio` como un grupo teatral y contiene una mención explícita verificable.


### Resultado de creación de entidad

La entidad `La Palangana de Poncio` fue creada correctamente.

Valores verificados:

- Tipo: `Organismo / institución`.
- Revisión: `1`.
- Alias: `0`.
- Menciones: `0`.
- Estado de revisión: `approved`.

**Veredicto: creación de entidad aprobada.**

---

## Próxima prueba: búsqueda transversal e incorporación de una mención

### Objetivo

Comprobar que la vista Entidades:

1. busca el nombre preferido sobre los textos editables;
2. presenta contexto, documento, página y objeto;
3. no escribe menciones antes de una decisión explícita;
4. permite incorporar una coincidencia como `pending`;
5. evita duplicarla en búsquedas posteriores.

### Caso elegido

Se utilizará la aparición contextual:

```text
a cargo de los componentes del grupo “La Palangana de Poncio”
```

La mención se incorporará inicialmente como `pending` para probar después su revisión desde el objeto.


### Resultado de incorporación de mención

La búsqueda transversal detectó una sola coincidencia:

```text
LA PALANGANA DE PONCIO · página 1 · objeto 3 · pending
```

Documento:

```text
Diario Jornada, 10 de Agosto de 1973,
'LA PALANGANA DE PONCIO PREPARA UN ESPECTACULO'
```

Contadores:

- Coincidencias: 1
- Nuevas: 0
- Ya incorporadas: 1

### Veredicto

- detección del nombre preferido: aprobada;
- incorporación explícita: aprobada;
- estado inicial `pending`: aprobado;
- prevención de duplicados: aprobada;
- vínculo con documento, página y objeto: aprobado.

### Próxima prueba

Aceptar la mención desde la pestaña `Entidades` del objeto correspondiente y comprobar que el cambio se refleje en la vista global de Entidades.


### Resultado de aceptación de la mención

La mención de `La Palangana de Poncio` quedó en estado `accepted`.

**Veredicto: revisión y aceptación de menciones aprobadas.**

Se verificó el circuito completo:

```text
búsqueda transversal → incorporación pending → revisión en el objeto → accepted
```

---

## Próxima prueba combinada: relación explícita y grafo documental

Se probarán en una sola secuencia:

1. creación de una relación explícita entre la entidad y la unidad archivística;
2. coexistencia de esa relación con la arista derivada de la mención aceptada;
3. visualización de ambas en el grafo;
4. diferenciación entre relación afirmada y evidencia derivada.


### Resultado de relación explícita y grafo

La relación explícita fue creada y verificada correctamente en el grafo.

Métricas observadas:

- Nodos: 2
- Aristas: 2
- Relaciones explícitas: 1
- Menciones: 1
- Compartidas: 0
- Alertas: 4

Se comprobó la coexistencia de:

- una relación explícita `aparece en`;
- una arista derivada de mención `mencionada en`.

### Problemas detectados

#### Gestión de relaciones

La interfaz permite crear una relación al confirmar con `Enter`, sin una advertencia suficientemente clara ni una confirmación explícita previa.

Una vez creada, no existe una forma visible de:

- eliminar la relación;
- editarla;
- cambiar el destino;
- corregir el tipo de relación;
- modificar la evidencia.

Esto constituye un problema grave de UX y de control sobre datos canónicos.

#### Alertas históricas

El grafo muestra cuatro alertas que parecen corresponder a relaciones o referencias antiguas desaparecidas durante migraciones anteriores.

Se requiere:

- distinguir alertas activas de alertas históricas;
- detectar referencias huérfanas;
- ofrecer una acción de reparación o limpieza;
- no conservar indefinidamente alertas ya resueltas;
- registrar la limpieza en auditoría.

#### Yuxtaposición de etiquetas

Las etiquetas `aparece en` y `mencionada en` se superponen en el grafo.

La visualización debe garantizar que los textos de nodos y aristas nunca se yuxtapongan de forma ilegible.

La solución debe ser robusta e incluir, según el caso:

- separación automática de aristas paralelas;
- curvatura diferenciada;
- desplazamiento de etiquetas;
- detección de colisiones;
- truncamiento con tooltip;
- zoom o expansión contextual;
- agrupación visual de aristas múltiples.


---

## Prueba funcional de exportación reproducible

### Perfil

- Nombre: `Piloto — páginas aprobadas`
- Agregación: una fila por página
- Texto: corregido con respaldo OCR
- Formato: JSONL
- Estado de página: `approved`
- Marcas de página: activadas

### Vista previa

- Registros: 1
- Caracteres: 1393
- Objetos activos: 4
- Documento: `leg_17_leg_15_a_c_2`
- Página: 1

### Exportaciones comparadas

```text
project_data/exports/piloto_aprobadas_a.jsonl
project_data/exports/piloto_aprobadas_b.jsonl
```

SHA-256 de ambos archivos:

```text
c41daf28cbcd4f8cd59f3136fd25a46d6502a4e19a9f219525b583225fc33469
```

Resultados:

- los hashes son idénticos;
- `diff -u` no produjo diferencias;
- el objeto eliminado `nn AMARA MAA` no aparece;
- `LA PALANGANA DE PONCIO` aparece en el registro;
- la entidad aceptada fue incorporada al campo `entities`;
- el registro conserva jerarquía, estados de revisión, objetos fuente y texto corregido.

**Veredicto: exportación reproducible aprobada.**

### Problemas de UX detectados

1. No existe una opción visible para eliminar un perfil de exportación.
2. La creación del archivo no muestra una notificación suficientemente visible de éxito.

La exportación debería producir un mensaje persistente o `toast` con:

- estado exitoso;
- ruta del archivo;
- formato;
- cantidad de registros;
- cantidad de caracteres;
- acceso directo para abrir la carpeta o descargar el archivo.

La eliminación de perfiles debe requerir confirmación y no debe eliminar exportaciones históricas ya materializadas.


---

## Prueba de intercambio offline: detección de base común

### Bundle exportado

- Bundle: `1de17fcb-fb17-4f8e-a82d-e27d19c505f4`
- Origen: `alex-pc`
- Base declarada: `bundle_2c74c4d6`, secuencia 3
- Secuencias incluidas: 4–1142
- Eventos: 1139
- SHA-256: `47c0db9849a4d6006426aab303213992892ecd1aa13546ceea443d779e44050d`

La inspección estructural y los checksums fueron correctos.

### Dry-run receptor

Resultado:

- base común: no encontrada;
- estado: `needs_review`;
- aplicables: 0;
- duplicados: 0;
- revisables: 1139;
- conflictos: 0.

No se aplicó ningún cambio, comportamiento seguro y correcto.

### Problema detectado

La copia receptora había aplicado previamente el bundle `2c74c4d6`, pero su checkpoint posterior tiene un hash de estado distinto del checkpoint de origen porque hubo resolución local durante la aplicación.

La versión 0.33.0 reconoce parentesco únicamente por igualdad exacta de `state_sha256`. Por eso no reconoce como base común un bundle que consta como aplicado y clasifica todos los eventos posteriores como revisables.

### Mejora requerida

El intercambio debe conservar dos dimensiones independientes:

1. **Ascendencia de eventos**
   - copia de origen;
   - bundle aplicado;
   - secuencia remota alcanzada;
   - IDs de eventos importados.

2. **Estado editable resultante**
   - hash local;
   - resoluciones y divergencias;
   - cambios posteriores propios.

Una divergencia local debe producir conflictos solo en los campos o entidades que se superponen. No debe hacer que todos los eventos futuros pierdan una base verificable.

El sistema debería poder reconocer:

```text
esta copia incorporó el origen X hasta la secuencia N,
aunque su estado editable posterior no sea idéntico
```

### Veredicto parcial

- exportación del bundle: aprobada;
- inspección y checksum: aprobados;
- bloqueo seguro ante base no verificable: aprobado;
- reconocimiento de ascendencia después de una resolución divergente: deficiente;
- escalabilidad de la revisión resultante: no aceptable.


### Confirmación del motivo de revisión

El reporte JSON fue inspeccionado directamente:

```text
counts: apply 0, conflict 0, duplicate 0, review 1139
overall_status: needs_review
base_match_status: unmatched
assessments: 1139
```

Los 1139 eventos comparten exactamente el mismo motivo:

```text
No existe una base común verificable para comparar el evento.
```

No existen conflictos de contenido detectados ni motivos heterogéneos.

### Decisión de la prueba

No se resolverán ni aplicarán masivamente los 1139 eventos.

La versión 0.33.0 establece además que las creaciones conflictivas no pueden aceptarse en bloque como `incoming`; requieren conservar la versión local o descartar el evento. Por lo tanto, una resolución global a favor de la copia principal no constituye un procedimiento válido ni seguro.

### Veredicto de intercambio offline

- creación e inspección del bundle: aprobadas;
- checksum: aprobado;
- copia al directorio receptor: aprobada;
- dry-run sin modificar datos: aprobado;
- bloqueo ante base no verificable: aprobado;
- reconocimiento de ascendencia después de una divergencia local: no aprobado;
- resolución operativa de un bundle grande sin base reconocida: no escalable;
- aplicación del bundle actual: deliberadamente no realizada.

La prueba demuestra que el sistema falla de forma segura, pero necesita mejorar su modelo de ascendencia antes de usar este flujo en producción.


---

## Control global y backup de cierre

### Control global

Resultado:

- 3 errores: menciones `accepted` o `modified` sin entidad vinculada.
- 1 advertencia: relación `dependió de` sin evidencia.
- 2 informaciones: relaciones no revisadas (`aparece en` y `dependió de`).
- Índice literal pendiente.
- Índice semántico pendiente por cambios posteriores.

Las tres menciones huérfanas son:

```text
f8771957-a156-4b14-b1e1-78577a62e51a
da188a01-b0a6-4449-a0b5-ad45dde0514e
ff71cfcd-63e0-4f93-9272-e9a00c0f543c
```

### Backup final

Archivo:

```text
backups/project/pilot_closure_20260727T194340Z.zip
```

Resultados:

- creación: aprobada;
- inspección: aprobada;
- restauración temporal: completada;
- revisión origen y destino: `0028_operational_readiness`;
- tablas: 62;
- archivos de configuración: 11;
- base activa sin modificar: confirmado.

SHA-256 del backup:

```text
02232bb9e7c9c503e49edad8d5fc5f3acc5d8cca8bedf0b073ff3d395cd972dc
```

### Inconsistencia en `project-readiness`

Aunque el backup de cierre fue probado exitosamente, `project-readiness` informó:

```text
El backup más reciente todavía no fue probado.
```

La causa está en la implementación de la versión 0.33.0: los backups se ordenan por nombre de archivo, no por fecha real de creación.

Como `project_...` ordena lexicográficamente después de `pilot_closure_...`, la app considera “más reciente” un backup anterior.

### Mejora requerida

- ordenar backups por `created_at` del manifiesto o por fecha de modificación;
- no usar el nombre del archivo como criterio cronológico;
- mostrar el nombre y hash del backup que se considera más reciente;
- vincular la prueba de recuperación al backup exacto.


---

## Diagnóstico de incidencias finales

### Menciones aceptadas sin autoridad

Se identificaron tres menciones válidas creadas por diccionario y aceptadas sin vínculo canónico:

- `SIDE` → `Secretaría de Inteligencia de Estado`
- `Side` → `Secretaría de Inteligencia de Estado`
- `SI. CHUBUT` → `Servicio de Informaciones del Chubut`

Esto confirma que la interfaz permite alcanzar un estado inconsistente:

```text
status = accepted
authority_id = NULL
```

La aceptación debería exigir una autoridad o, en su defecto, mantener la mención como pendiente/no vinculada.

### Relaciones activas

- `La Palangana de Poncio → 17`: relación accidental, no revisada; debe desactivarse.
- `La Palangana de Poncio → Diario Jornada...`: relación correcta y aprobada.
- `Servicio de Informaciones del Chubut → Secretaría de Inteligencia de Estado`: relación plausible pero sin evidencia; debe permanecer sin revisar hasta documentarla.

### Precisión sobre la gestión de relaciones

La versión 0.33.0 sí permite modificar:

- tipo de relación;
- evidencia;
- período y nota temporal;
- estado de revisión;
- ciclo de vida activo/inactivo.

No permite desde la interfaz:

- cambiar el destino;
- eliminar definitivamente la relación;
- confirmar de forma clara antes de la creación accidental con Enter.

Por lo tanto, `inactiva` funciona como baja lógica, pero no reemplaza una acción explícita y comprensible de eliminar/archivar.


---

## Duplicación de menciones vinculadas y no vinculadas

Las capturas de Revisión muestran dos menciones sobre los mismos offsets:

1. una mención vinculada a la autoridad, con nota `Coincidencia transversal...`;
2. una mención anterior `sin autoridad canónica`, con nota `Coincidencia con nombre preferido...`.

### Causa confirmada en el código

La incorporación desde la vista `Entidades` pasa correctamente el `authority_id` al crear una mención.

Sin embargo, al buscar coincidencias ya incorporadas, `authority_mention_candidates()` construye su mapa de existentes usando solamente:

```text
EntityMention.authority_id == autoridad seleccionada
```

Por lo tanto, una mención existente con:

```text
mismo objeto + misma revisión + mismos offsets
authority_id = NULL
```

no es considerada una coincidencia ya incorporada. La aplicación la presenta como nueva y crea otra mención vinculada sobre el mismo fragmento.

### Consecuencia

Puede coexistir:

```text
SIDE · accepted · sin autoridad
SIDE · pending/accepted · Secretaría de Inteligencia de Estado
```

Esto genera tarjetas duplicadas, errores de integridad y una revisión confusa.

### Corrección requerida

Al buscar o incorporar menciones desde una entidad:

1. detectar cualquier mención existente en el mismo objeto, revisión y rango de offsets;
2. si está sin autoridad, ofrecer `Vincular mención existente` en vez de crear otra;
3. si está vinculada a otra autoridad, mostrar conflicto explícito;
4. si está rechazada, ofrecer reabrirla o crear una nueva con advertencia;
5. impedir dos menciones activas idénticas sobre los mismos offsets;
6. impedir `accepted` o `modified` sin autoridad;
7. ofrecer una herramienta para fusionar o limpiar duplicados existentes.

### Estado del control final

Después de vincular o rechazar las menciones huérfanas:

```text
errores: 0
advertencias: 1
información: 3
```

Persisten solamente:

- relación `dependió de` sin evidencia y sin revisar;
- índice literal pendiente;
- índice semántico pendiente.


---

## Pérdida no auditada de vínculos de menciones

El historial de revisiones demuestra que las tres menciones problemáticas fueron creadas y aceptadas con autoridad canónica:

- `SIDE` y `Side` → `Secretaría de Inteligencia de Estado`
- `SI. CHUBUT` → `Servicio de Informaciones del Chubut`

Secuencia registrada:

```text
create  | pending  | authority_id presente
update  | accepted | authority_id presente
```

Antes de la intervención manual del piloto, el estado actual de esas filas era:

```text
accepted | authority_id NULL
```

Sin embargo, no existe una revisión intermedia que registre la eliminación del vínculo.

La revisión 3 corresponde únicamente al rechazo manual realizado durante la prueba:

```text
update | rejected | authority_id NULL
```

### Conclusión

Las menciones no nacieron desvinculadas ni perdieron la autoridad al ser aceptadas desde la interfaz.

El vínculo canónico desapareció posteriormente mediante una operación que no generó una entrada en `entity_mention_revisions`.

Esto indica una falla de integridad y auditoría posiblemente asociada a:

- una migración;
- una aplicación de bundle;
- una actualización directa de la tabla;
- otro flujo que no usa el servicio normal de revisión.

La búsqueda transversal posterior no reconoció esas menciones huérfanas como ya incorporadas y creó duplicados vinculados.

### Requisitos

- toda modificación de `authority_id` debe producir una revisión;
- migraciones e intercambio deben preservar el vínculo;
- un control de integridad debe comparar el estado actual con el último snapshot;
- cualquier divergencia debe generar alerta reparable;
- la deduplicación debe detectar coincidencias por objeto, revisión y offsets, incluso cuando falte la autoridad.


---

## Causa raíz confirmada: migración 0027

Se reprodujo el problema en una base temporal limpia:

1. base en revisión `0026_team_workflow`;
2. autoridad existente;
3. mención `accepted` vinculada a esa autoridad;
4. relación activa cuyo origen era esa autoridad;
5. actualización a `0027_temporal_authorities_relations`.

Resultado después de migrar:

```text
mención: authority_id = NULL, status = accepted
relación: eliminada
autoridad: conservada
```

### Mecanismo exacto

La migración `0027_temporal_authorities_relations` ejecuta:

```python
with op.batch_alter_table("authority_records") as batch:
    ...
```

En SQLite, el modo batch recrea la tabla:

```text
crear tabla temporal → copiar filas → eliminar tabla original → renombrar
```

Las claves foráneas dependientes estaban definidas así:

```text
entity_mentions.authority_id
    ON DELETE SET NULL

entity_relations.source_authority_id
entity_relations.target_authority_id
    ON DELETE CASCADE
```

Al eliminar la tabla original `authority_records`, SQLite ejecutó esas acciones:

- puso en `NULL` los vínculos de menciones;
- eliminó las relaciones;
- luego recreó las autoridades con los mismos UUID;
- pero no restauró las referencias perdidas.

Como la alteración ocurrió por acción de la clave foránea y no mediante los servicios de dominio, no se generaron revisiones ni eventos de intercambio.

### Evidencia del proyecto

Los eventos 12–18 muestran:

```text
create  → authority_id presente
update  → accepted, authority_id presente
```

No existe ningún evento posterior que quite la autoridad antes de la intervención manual.

Los eventos 1145–1147 corresponden al rechazo manual realizado durante el piloto.

### Corrección requerida

La migración 0027 debe ser reemplazada o corregida para no recrear `authority_records` con claves foráneas activas.

Para agregar esas columnas en SQLite puede usarse `ALTER TABLE ADD COLUMN` directamente, evitando el modo batch.

También se requiere una migración de reparación para instalaciones ya afectadas:

- detectar menciones `accepted`/`modified` con `authority_id=NULL`;
- recuperar el vínculo desde revisiones o eventos cuando sea inequívoco;
- detectar relaciones eliminadas durante la migración;
- reconstruirlas desde eventos, backups o registros históricos;
- registrar toda reparación en auditoría.

### Severidad

**Bloqueante de integridad para actualización de versiones.**

La migración puede modificar silenciosamente datos canónicos y borrar relaciones válidas.


---

## Decisión sobre compatibilidad y reparación de datos

La información generada durante esta prueba piloto es descartable. No se desarrollará una migración destinada a reparar esta base ni otras bases anteriores afectadas.

Se conservarán únicamente como activos valiosos:

- catálogo;
- archivos originales;
- derivados;
- procesamiento;
- corridas y resultados de extracción;
- selección canónica y revisión de páginas, cuando corresponda.

Las capas de entidades, menciones, relaciones, índices, perfiles, exportaciones e intercambio pueden limpiarse o regenerarse.

### Alcance obligatorio de la corrección

1. corregir la migración o el esquema actual para impedir la pérdida de vínculos;
2. agregar una prueba de regresión con autoridades, menciones y relaciones preexistentes;
3. comprobar que futuras migraciones preserven UUID, claves foráneas y estados;
4. no invertir tiempo en recuperar datos piloto anteriores.


---

# Cierre final de la prueba piloto

## Índices

### Búsqueda literal

```text
objetos: 1273
generación de datos: 1217
generación del índice: 1217
estado: actualizado
```

### Búsqueda semántica

```text
perfil: Multilingüe E5 — objetos
fragmentos: 4
dimensiones: 384
estado: actualizado
```

La reconstrucción mediante CUDA finalizó correctamente.

El aviso sobre solicitudes no autenticadas a Hugging Face no afectó la ejecución. Solo indica que no se configuró un `HF_TOKEN` para mejorar límites de descarga.

## Control final

```text
errores: 0
advertencias: 1
información: 1
```

La única advertencia corresponde a la relación:

```text
Servicio de Informaciones del Chubut
    dependió de
Secretaría de Inteligencia de Estado
```

La relación permanece sin revisar y sin evidencia. No constituye un error de integridad.

## Readiness final

```text
READY     Catálogo
READY     Procesamiento y revisión
READY     Trabajo colectivo
READY     Búsqueda literal
READY     Búsqueda semántica
READY     Entidades y relaciones
READY     Exportación
READY     Intercambio offline
ATTENTION Recuperación
```

Estado general:

```text
listos: 8
atención: 1
pendientes: 0
DB: 0028_operational_readiness
```

La única atención de Recuperación es un falso positivo ya diagnosticado: los backups se ordenan por nombre en vez de por fecha real.

## Veredicto general

Archive Workbench 0.33.0 completa el circuito funcional de:

- catálogo y archivos locales;
- procesamiento y extracción;
- revisión y aprobación;
- búsqueda literal y semántica;
- autoridades, menciones y relaciones;
- grafo documental;
- exportación reproducible;
- intercambio offline con bloqueo seguro;
- backup, inspección y recuperación.

La versión todavía no debe considerarse lista para producción por los pendientes de integridad, migraciones, UX, OCR y visualización detectados durante el piloto.

## Orden recomendado para la próxima iteración

1. corregir la migración 0027 y agregar pruebas de regresión;
2. impedir menciones aceptadas sin autoridad y duplicadas por offsets;
3. mejorar creación, edición, baja y confirmación de relaciones;
4. corregir el orden cronológico de backups;
5. corregir ascendencia del intercambio offline;
6. mejorar historial integrado de página y objetos;
7. incorporar previsualización y comparación de corridas candidatas;
8. abordar OCR, layout, calidad automática y Surya/CUDA;
9. corregir colisiones de etiquetas en el grafo;
10. recién después avanzar con identificación automática de entidades.
