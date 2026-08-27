# Guía de prueba piloto y cierre de Archive Workbench v1.0

## Estado de partida

La v0.33.0 es una **beta operativa de extremo a extremo**. La aplicación ya permite:

- registrar y describir documentos;
- vincular archivos locales sin confundir registro y disponibilidad;
- preparar páginas y ejecutar extracciones versionadas;
- seleccionar manualmente la extracción canónica por página;
- revisar y corregir objetos textuales con historial;
- organizar trabajo y revisión cruzada;
- buscar literal y semánticamente;
- registrar entidades, menciones, relaciones y temporalidad;
- construir grafos derivados;
- exportar corpus reproducibles;
- intercambiar cambios entre copias;
- crear, verificar y probar backups.

La finalidad del piloto no es demostrar que todas las funciones existen. Es comprobar que el recorrido completo funciona con documentos reales, detectar errores y producir evidencia para decidir perfiles de extracción y requisitos de la v1.0.

Desde RC12, esta comprobación incluye una prueba de referente explícito: no dar por comprensible una frase sólo porque su título, tarjeta o pestaña permitan adivinar a qué se refiere. Cada texto operativo debe nombrar el objeto o tarea concreta que describe. Las guardas automáticas ayudan a impedir regresiones, pero no reemplazan la lectura manual ni la experiencia de uso sin explicación externa.

Una parte central de esa validación es la **comprensión sin guía externa**. El piloto debe observar si una persona que llega a cada sección desde la navegación puede reconocer qué tarea ofrece, para qué sirve, qué control debe usar y qué resultado producirá. Si hace falta que el asistente traduzca la interfaz o explique un paso que la pantalla no permite inferir, registrar esa dependencia como problema de usabilidad antes de continuar la prueba. La guía puede destrabar el recorrido después del registro, pero no convierte por sí sola una pantalla confusa en una pantalla validada.

## Alcance pendiente

Las capacidades todavía abiertas no se mantienen en esta guía para evitar listas divergentes. El inventario único y vigente está en [`PENDIENTES_ACTIVOS.md`](PENDIENTES_ACTIVOS.md).

Esta guía se limita al piloto, la evaluación de documentos reales y los criterios de cierre de la v1.0.


La secuencia general se consulta en [`HOJA_DE_RUTA_PRE_RELEASE.md`](HOJA_DE_RUTA_PRE_RELEASE.md). El proyecto paralelo del GIAR se documenta en [`PROYECTO_PARALELO_GIAR.md`](../referencia/PROYECTO_PARALELO_GIAR.md) y utilizará una base física separada.

## Reglas de preservación del piloto

- No reinicializar, reemplazar ni eliminar el proyecto real para repetir una prueba.
- Crear y verificar un backup antes de cada migración.
- Mantener corridas rechazadas o superadas como historial comparativo.
- Registrar responsables, notas y procedencia en las operaciones manuales.
- Separar pruebas sintéticas descartables de materiales y resultados reales.
- No publicar originales, capturas, transcripciones o metadatos sin revisar permisos y condiciones de acceso.

## Proyecto real y persistente del piloto

`PILOT-01` se realizará sobre un proyecto nuevo cuya ruta se acordará antes de incorporar materiales. Ese proyecto quedará para el equipo de investigación y no se tratará como una base descartable. Cada actualización deberá conservar resultados, crear backup antes de migrar y registrar cualquier operación que cambie selecciones o revisiones.

El corpus real incluirá:

| procedencia | materiales | uso previsto |
|---|---|---|
| Archivo de la DIPPBA | legajos y documentos asociados | reutilizar la base de catálogo ya construida, validar OCR, estructura, autoridades, relaciones y referencias archivísticas |
| APM-Chubut | legajos e imágenes | ampliar tipos documentales, procedencias y condiciones materiales |
| testimonios audiovisuales | audios y videos autorizados, incluidos materiales de una página de YouTube | validar registro local, incorporación opcional, reproducción a distintas velocidades, transcripción segmentada, corrección, búsqueda y exportación |

Las rutas, permisos, restricciones de difusión y responsables se registrarán antes de cada lote. Los originales, hashes, catálogos, corridas, selecciones, revisiones y exportaciones deben preservarse de una versión a otra.

## Corpus técnico preliminar

El archivo `project_data/config/test_corpus.yaml` conserva cinco casos útiles para regresiones técnicas:

| test_id | Función | Dificultad principal |
|---|---|---|
| `caja_administracion_publica_adm_pub_asp_contr` | documento relativamente controlable | inclinación y páginas apaisadas |
| `caja_administracion_publica_carp_reg` | caso deliberadamente difícil | degradación, orientaciones, manuscritos, sellos y formularios |
| `leg_17_caso_bolson` | legajo heterogéneo | documentos internos, imágenes, manuscritos y sellos |
| `leg_17_leg_15_a_c_2` | recorte periodístico | multicolumna |
| `leg_17_leg_15_a_c_6` | ficha administrativa | formato irregular, manuscritos, sellos y campos |

Estos documentos no reemplazan el piloto real. No es necesario reextraer los cuatro ya procesados antes de evaluarlos.

---

# Fase 1 — Inventario inicial

## Objetivo

Comprobar qué archivos están presentes, qué extracciones existen, qué páginas fueron seleccionadas y qué partes del circuito ya están listas.

## Comandos

Desde la raíz del repositorio:

```bash
cd ~/projects/archive_app
source .venv/bin/activate

archive-workbench validate-test-corpus \
  project_data/config/test_corpus.yaml

archive-workbench inspect-test-corpus \
  project_data/config/test_corpus.yaml \
  --root project_data

archive-workbench extraction-status project_data
archive-workbench selected-extraction-status project_data
archive-workbench project-readiness project_data
```

## Resultado que se debe conservar

Guardar la salida completa con fecha. Registrar:

- documentos presentes y ausentes;
- cantidad de páginas por documento;
- perfil y estado de cada extracción;
- páginas procesadas;
- páginas con un texto elegido para revisar;
- páginas sin selección;
- corridas marcadas `accepted`, `rejected`, `needs_review` o `unreviewed`;
- advertencias operativas de Inicio.

No modificar perfiles durante esta fase.

---

# Fase 2 — Evaluación visual de las extracciones existentes

## Objetivo

Determinar si cada extracción es utilizable y localizar problemas por página.

## Procedimiento por documento

1. Abrir **Procesar documentos → Elegir texto** y revisar los resultados de extracción disponibles.
2. Abrir el documento en **Revisión**.
3. Comparar imagen y texto página por página.
4. No corregir todavía todos los errores. Primero clasificar su naturaleza.
5. Elegir entre `accepted`, `needs_review` y `rejected` para cada corrida evaluada.

## Clasificación mínima de problemas

- texto omitido;
- caracteres o palabras incorrectas;
- orden de lectura incorrecto;
- columnas mezcladas;
- títulos tratados como párrafos;
- párrafos fragmentados indebidamente;
- objetos distintos fusionados;
- sellos no preservados;
- manuscritos no preservados como región;
- tablas o formularios sin estructura;
- orientación incorrecta;
- página vacía o fallida;
- ruido incorporado como texto.

## Registro recomendado

| Campo | Contenido |
|---|---|
| Documento | `source_key` |
| Página | número físico |
| Corrida | `run_id` y perfil |
| Severidad | crítica / alta / media / baja |
| Tipo de problema | categoría de la lista anterior |
| Resultado esperado | descripción concreta |
| Resultado obtenido | descripción concreta |
| Texto crítico | fragmento que no debe perderse |
| Acción posterior | benchmark / nuevo perfil / corrección manual / sin acción |

## Criterios provisionales

### Accepted

- el texto principal es legible;
- no se pierde información crítica;
- el orden de lectura es correcto o corregible fácilmente;
- los problemas restantes pueden resolverse en Revisión.

### Needs review

- la corrida es parcialmente utilizable;
- hay páginas o regiones que requieren comparación;
- todavía no puede elegirse como referencia sin inspección adicional.

### Rejected

- el texto es ininteligible;
- mezcla columnas o páginas de manera grave;
- pierde información crítica;
- aplica una orientación incorrecta;
- el costo de corregirla manualmente supera el de reextraer.

## Comandos opcionales

```bash
archive-workbench extraction-history \
  project_data \
  --source-key DOCUMENTO

archive-workbench review-extraction \
  project_data \
  --source-key DOCUMENTO \
  --verdict needs_review \
  --reviewed-by alex \
  --note "Descripción breve"
```

No seleccionar como canónica una corrida solo porque tenga mayor puntaje automático.

---

# Fase 3 — Ground truth mínimo

## Objetivo

Crear una referencia revisada pequeña que permita comparar motores y perfiles.

No hace falta transcribir documentos enteros. Seleccionar páginas representativas.

## Selección recomendada

Por cada documento:

- una página relativamente fácil;
- una página difícil;
- una página con la característica distintiva del caso.

Puede reducirse a una o dos páginas si el documento es de una sola página.

## Qué registrar

Para cada página seleccionada:

- objetos esperados y su orden;
- texto crítico exacto;
- títulos y subtítulos;
- cambios de columna;
- tablas, formularios o listas;
- sellos;
- regiones manuscritas;
- imágenes o captions;
- elementos que pueden ocultarse, pero no perderse.

## Regla

La verdad terreno debe describir lo que la extracción debería conservar, no imitar el resultado de un motor concreto.

---

# Fase 4 — Benchmark de extracción

## Objetivo

Comparar variantes solamente en páginas donde exista un problema observado.

## Diagnóstico previo

```bash
archive-workbench ocr-benchmark-truth-doctor \
  project_data
```

## Benchmark con verdad terreno

Crear primero `ground_truth/ocr/DOCUMENTO/page_NNNN.txt` y ejecutar:

```bash
archive-workbench ocr-benchmark-truth \
  project_data \
  --source-key DOCUMENTO \
  --page NUMERO
```

La corrida compara Tesseract, Docling y Surya sobre el mismo derivado, calcula CER/WER y conserva perfiles, versiones, tiempos, texto y salida cruda. La salida queda bajo `ocr_benchmarks/<digital_object_id>/truth_<benchmark_id>/`.

## Evaluación

Leer el resumen y los candidatos. Elegir por:

1. conservación del texto crítico;
2. orden de lectura;
3. separación de columnas;
4. ausencia de ruido grave;
5. facilidad de corrección.

El puntaje heurístico no reemplaza la revisión manual.

## Nueva extracción experimental

```bash
archive-workbench extract \
  project_data \
  --source-key DOCUMENTO \
  --page NUMERO \
  --profile project_data/config/extraction_tesseract.yaml \
  --psm 3 \
  --image-variant grayscale_autocontrast \
  --selection-policy never \
  --created-by alex \
  --force
```

Toda corrida comparativa debe usar `--selection-policy never`.

Después se evalúa y, solo si corresponde, se selecciona manualmente:

```bash
archive-workbench select-extraction \
  project_data \
  --source-key DOCUMENTO \
  --run-id ID_DE_LA_CORRIDA \
  --page NUMERO \
  --selected-by alex \
  --note "Motivo de la selección"
```

---

# Fase 5 — Piloto funcional de extremo a extremo

## Punto actual del PILOT-01 - 2026-08-24

El recorrido funcional extremo a extremo ya está verde y no debe repetirse salvo regresión concreta. La validación manual de RC64 cerró `PILOT-01AE`, incluida la reparación transversal de comportamiento Streamlit.

RC65 retoma únicamente `PILOT-01A`. La validación nueva se limita al modelo descriptivo: comprobar en el `pilot_data` existente que `Archivo` se entiende como contexto de custodia cuando corresponda, que `Colección` se presenta como conjunto documental construido distinto de Fondo y que el audiovisual real incorporado desde plataforma distingue publicación remota de copia local. No reimportar materiales, no repetir transcripciones, OCR, búsquedas, exportaciones, intercambio ni backup. La revisión vigente sigue siendo `0047_authority_relation_profiles` y RC65 no agrega migración.

## Objetivo

Completar al menos un documento a través de todo el sistema.

## Recorrido

```text
Catálogo
→ Procesamiento
→ selección canónica
→ inicialización editable
→ Revisión
→ comentarios y etiquetas
→ entidades y relaciones
→ búsqueda literal
→ búsqueda semántica exploratoria
→ grafo
→ exportación
→ asignación y revisión cruzada
→ preparar copia / enviar y recibir cambios
→ backup y prueba de recuperación
```

## Acciones mínimas en un documento

- corregir al menos una página completa;
- dividir o unir un objeto, si el material lo requiere;
- aprobar objetos o página según el flujo vigente;
- agregar un comentario;
- aplicar una etiqueta;
- crear o vincular una entidad;
- crear una relación explícita;
- registrar temporalidad si existe evidencia;
- encontrar el texto mediante búsqueda literal;
- ejecutar una consulta semántica y abrir el original;
- exportar el documento mediante un perfil;
- crear y completar una asignación;
- preparar una copia compartible, intercambiar un paquete incremental e inspeccionarlo en la copia receptora;
- crear un backup y ejecutar la prueba no destructiva de recuperación.


## Regla de avance durante el extremo a extremo

Después de validar las acciones básicas de `Revisar documentos`, continuar sobre el mismo documento con entidades y menciones, luego relaciones, búsqueda literal, búsqueda semántica, grafo y exportación. No repetir las acciones de revisión ya cerradas salvo que una modificación posterior afecte ese subsistema. En cada sección, intentar primero comprender la tarea desde la propia interfaz; si la persona necesita una explicación externa para saber qué hace un control o qué resultado produce, registrar el problema antes de destrabar el recorrido.

En `Entidades y menciones`, la prueba debe distinguir la ficha canónica de una entidad, sus menciones en documentos, sus relaciones analíticas y los roles archivísticos que provienen de Catálogo. Los roles de productor o responsable de gestión pueden consultarse desde la entidad, pero su edición se valida únicamente en Catálogo. Para las referencias encontradas automáticamente, comprobar aceptar con corrección opcional, descartar y restaurar, y una acción masiva acotada; no es necesario procesar todas las sugerencias para validar el recorrido.

## Criterio de cierre

El documento debe poder cerrarse y reabrirse sin perder:

- selección OCR;
- correcciones;
- estructura;
- anotaciones;
- entidades y relaciones;
- historial;
- estado de trabajo;
- capacidad de búsqueda y exportación.

---

# Fase 6 — Validación técnica

Se ejecuta después de observar el corpus real.

## Extracción

- comparar Docling y Tesseract;
- incorporar Surya como candidato aislado;
- medir cobertura, CER/WER donde exista transcripción verdadera y errores de orden;
- definir perfiles por tipo documental;
- conservar siempre las corridas históricas.

## CUDA

Registrar en cada prueba:

- sistema operativo;
- GPU;
- driver NVIDIA;
- CUDA visible;
- versión de Python;
- PyTorch;
- backend;
- versiones de Docling, Surya o Faster Whisper;
- resultado de importación;
- resultado de carga del modelo;
- inferencia mínima;
- VRAM utilizada;
- error completo, si falla.

Detectar una GPU no equivale a demostrar que un backend funciona.

---

# Fase 7 — Candidata a v1.0

Antes de publicar la v1.0 deben cumplirse estas condiciones:

- cinco casos piloto evaluados;
- al menos un recorrido completo de extremo a extremo;
- uno o más perfiles de extracción validados y documentados;
- errores críticos de pérdida de datos resueltos;
- instalación CPU comprobada;
- perfil GPU documentado si funciona;
- migración desde una base anterior real;
- bundle probado entre dos copias;
- backup creado, probado y restaurado en una copia controlada;
- contratos y `schema_version` congelados;
- documentación utilizable por otra persona;
- limitaciones OCR y semánticas explícitas;
- sugerencias automáticas incapaces de sobrescribir decisiones explícitas.

---

# Plantilla de incidencia

```markdown
## Incidencia PILOT-000

- Fecha:
- Versión:
- Proyecto:
- Documento / source_key:
- Página:
- Sección de la aplicación:
- Perfil o corrida:
- Acción realizada:
- Resultado esperado:
- Resultado obtenido:
- Severidad: crítica / alta / media / baja
- ¿Hay riesgo de pérdida de datos?: sí / no
- ¿Es reproducible?: sí / no / no comprobado
- Mensaje de error completo:
- Evidencia adjunta:
- Solución temporal, si existe:
```

# Plantilla de evaluación por documento

```markdown
# Evaluación piloto — DOCUMENTO

## Identificación

- source_key:
- título:
- archivo:
- páginas:
- característica principal:

## Corridas evaluadas

| run_id | perfil | páginas | estado técnico | veredicto de revisión | nota |
|---|---|---:|---|---|---|

## Páginas de ground truth

| página | motivo de selección | texto crítico | objetos esperados |
|---:|---|---|---|

## Problemas encontrados

| página | severidad | categoría | descripción | acción posterior |
|---:|---|---|---|---|

## Texto elegido para revisar

| página | run_id elegido | motivo |
|---:|---|---|

## Resultado

- utilizable:
- requiere nuevo perfil:
- requiere benchmark:
- requiere corrección manual:
- observaciones:
```
