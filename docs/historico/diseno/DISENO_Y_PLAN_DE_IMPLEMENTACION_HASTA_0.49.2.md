# Archive Workbench

## Diseño técnico, decisiones pendientes y plan de implementación por iteraciones

**Estado del documento:** diseño base y hoja de ruta inicial  
**Versión:** 0.1  
**Fecha:** 22 de julio de 2026  
**Nombre del proyecto:** provisional

---

## 1. Propósito

Archive Workbench será una aplicación local para equipos de investigación que trabajan con archivos desclasificados de servicios de inteligencia policial. Debe permitir registrar la estructura archivística, localizar o declarar ausentes los objetos digitales, extraer documentos escaneados, corregir y estructurar el texto, realizar anotaciones analíticas, buscar transversalmente y compartir cambios entre computadoras sin mantener un servidor central.

Los documentos de partida del diseño son:

- `idea_diseño.md`: requisitos funcionales y modalidad de trabajo del equipo.
- `documentacion(1).md`: arquitectura y experiencia obtenida con el pipeline anterior de extracción académica.
- `index(1).html`: prototipo de editor de párrafos e imágenes.

La aplicación no debe depender de que todos los archivos estén presentes en cada computadora. El catálogo, las descripciones, las relaciones y el historial tienen que seguir funcionando aunque falte un PDF, un TIFF, un JSONL de extracción o una imagen derivada.

---

## 2. Decisiones arquitectónicas adoptadas

### 2.1 Fuente de verdad

La fuente de verdad será una base SQLite local por proyecto. Los JSONL serán formatos versionados de:

- importación;
- exportación;
- interoperabilidad;
- resultados de extracción;
- paquetes de intercambio;
- copias legibles para auditoría.

No se utilizarán colecciones de JSONL como base principal porque el sistema necesita transacciones, relaciones, revisiones, integridad referencial, búsquedas, versiones y combinación de cambios.

### 2.2 Una aplicación, varios componentes internos

Para el equipo será una sola aplicación. Internamente tendrá:

1. **Núcleo de dominio y persistencia** en Python.
2. **Interfaz multipágina** en Streamlit.
3. **Editor documental especializado** como componente web TypeScript integrado a Streamlit.
4. **Worker local** para OCR, conversiones, embeddings y otras tareas pesadas.

No se dividirá inicialmente en productos o repositorios independientes. Los límites internos permitirán separar componentes más adelante si aparece una necesidad real.

### 2.3 Separación entre lógica e interfaz

Las páginas Streamlit solo mostrarán información y llamarán servicios. No contendrán reglas de negocio, SQL, OCR ni combinación de cambios. Esta separación conserva uno de los puntos fuertes de la aplicación de extracción anterior.

### 2.4 Originales inmutables

Los PDF, TIFF, imágenes, audios y videos originales no se modificarán. Rotaciones, recortes, separación de páginas y conversiones producirán derivados.

### 2.5 Identidades estables

- Las entidades lógicas usarán UUID.
- La identidad del contenido de un archivo será SHA-256.
- Las rutas y nombres no serán identidades.
- Los objetos textuales conservarán identidad aunque cambie su orden.
- Las divisiones y uniones producirán nuevos objetos y registrarán linaje.

### 2.6 Drive como transporte, no como base viva

Google Drive almacenará originales, derivados y paquetes de cambios. No se pondrá una base SQLite abierta en una carpeta sincronizada para que varias personas la modifiquen. Cada computadora tendrá su copia y aplicará paquetes de intercambio validados.

---

## 3. Alcance funcional

### 3.1 Catálogo archivístico

- Crear proyectos.
- Registrar una jerarquía configurable.
- Describir unidades archivísticas.
- Vincular PDF, TIFF, imágenes u otros objetos digitales.
- Mantener registros aunque falten archivos locales.
- Rastrear carpetas y detectar archivos nuevos, movidos, modificados o duplicados.
- Mostrar un árbol expandible.
- Buscar por cualquier nivel o campo descriptivo.

### 3.2 Extracción

- Inspección previa de PDF, TIFF e imágenes.
- Detección de capa digital, páginas probablemente escaneadas y orientación.
- Opciones de OCR automático, sin OCR y OCR completo.
- Procesamiento documento por documento.
- Detección de estructura, orden de lectura y tablas.
- Conservación de títulos, índices, notas, captions, sellos y regiones manuscritas.
- Derivados de página y bounding boxes.
- Registro de motor, versión, configuración, advertencias y calidad.

### 3.3 Editor

- Original inmodificable y texto corregido.
- Imagen opcional con bounding boxes.
- Navegación por página, objeto y parte interna.
- Cambio de tipo de objeto.
- Ocultar sin borrar.
- Dividir y unir con linaje.
- Comentarios analíticos.
- Etiquetas temáticas y conceptuales.
- Entidades y relaciones.
- Historial y atribución.

### 3.4 Intercambio offline

- Exportar cambios incrementales.
- Importar y validar paquetes.
- Simular la aplicación antes de escribir.
- Combinar automáticamente operaciones compatibles.
- Resolver conflictos campo por campo.
- Realizar backup antes de cada importación.

### 3.5 Búsqueda y análisis

- Búsqueda descriptiva y lexical con SQLite FTS5.
- Búsqueda semántica opcional mediante embeddings.
- Búsqueda desde una selección del editor.
- Grafos derivados de relaciones, etiquetas, entidades y similitud.
- Exportaciones configurables hacia otras herramientas.

### 3.6 Audiovisual

El registro y la transcripción de materiales audiovisuales se incorporarán después del núcleo documental. La descarga desde plataformas externas será un plugin prescindible.

---

## 4. Arquitectura

```text
┌───────────────────────────────────────────────────────────────┐
│                         INTERFAZ                              │
│  Streamlit: catálogo · extracción · búsqueda · administración │
│  Componente TS: editor documental · bboxes · atajos           │
└───────────────────────────┬───────────────────────────────────┘
                            │
┌───────────────────────────▼───────────────────────────────────┐
│                         SERVICIOS                             │
│ catálogo · archivos · extracción · edición · intercambio      │
│ búsqueda · exportación · entidades · grafos                   │
└───────────────────────────┬───────────────────────────────────┘
                            │
        ┌───────────────────┼──────────────────────┐
        │                   │                      │
┌───────▼────────┐ ┌────────▼─────────┐ ┌──────────▼───────────┐
│ SQLite + FTS5  │ │ Archivos locales │ │ Worker local         │
│ fuente lógica  │ │ originales y     │ │ OCR, TIFF, Docling,  │
│ de verdad      │ │ derivados        │ │ embeddings           │
└────────────────┘ └──────────────────┘ └──────────────────────┘
        │
┌───────▼──────────────────────────────────────────────────────┐
│ Paquetes de intercambio + Drive                             │
│ cambios.jsonl · manifest · checksums · adjuntos             │
└──────────────────────────────────────────────────────────────┘
```

---

## 5. Modelo de datos principal

### 5.1 Proyecto

Cada corpus tendrá un directorio de proyecto y una base propia.

```text
project
    id
    name
    schema_version
    created_at
    configuration
```

### 5.2 Unidad archivística

Se utilizará una tabla autorreferenciada, no una tabla por nivel.

```text
archival_unit
    id
    parent_id
    level_key
    reference_code
    title
    date_start
    date_end
    date_expression
    extent
    medium
    scope_content
    archivist_note
    description_date
    extra_metadata
    created_at / created_by
    updated_at / updated_by
    revision
```

Los niveles serán configurables. El conjunto sugerido inicial es:

```text
archivo → fondo → sección → subsección → serie → subserie
        → caja → legajo → tomo → documento
```

Se podrán omitir niveles. Los puntos suspensivos que aparecen en una vista no se almacenarán como unidades reales.

### 5.3 Campos descriptivos configurables

```text
metadata_field
metadata_value
```

Esto permitirá agregar condiciones de acceso, lengua, productor, estado de conservación u otros campos sin cambiar la estructura SQL.

### 5.4 Objeto digital

```text
digital_object
    id
    media_type
    original_filename
    sha256
    byte_size
    page_count
```

Un objeto digital puede representar una unidad, parte de ella o varias unidades.

```text
digital_object_unit
    digital_object_id
    archival_unit_id
    relation_type
    page_start
    page_end
```

### 5.5 Instancia local

```text
file_instance
    id
    digital_object_id
    storage_root
    relative_path
    presence
    last_seen_at
    verified_sha256
```

Estados iniciales:

- `present`
- `missing`
- `moved`
- `modified`
- `unverified`

### 5.6 Ubicación remota

```text
remote_location
    digital_object_id
    provider
    url
    remote_path
    notes
```

### 5.7 Extracción

```text
extraction_run
    id
    digital_object_id
    source_sha256
    engine
    engine_version
    options_hash
    options
    status
    warnings
    created_by
    created_at
    is_current
```

### 5.8 Partes internas

```text
document_part
    id
    digital_object_id
    parent_id
    part_type
    title
    order_index
    page_start
    page_end
    archival_unit_id
    reviewed
```

Esto diferencia la jerarquía archivística de la estructura interna detectada en un PDF o legajo.

### 5.9 Objetos textuales y visuales

```text
text_object
    id
    extraction_run_id
    part_id
    object_type
    original_text
    order_index
    confidence
    hidden_by_default
    attributes
```

La geometría será una colección independiente para permitir objetos que atraviesan páginas o que se forman mediante una unión.

```text
object_geometry
    object_id
    page
    polygon
    coordinate_space
```

### 5.10 Revisiones, anotaciones y relaciones

```text
text_revision
annotation
tag
tag_assignment
entity
entity_mention
relation
object_lineage
```

Los comentarios, etiquetas y entidades no quedarán incrustados en el JSONL de párrafos. Tendrán identidad, autor y fecha propios.

---

## 6. Contratos JSONL

### 6.1 Principios

- Cada línea será un objeto JSON válido.
- Cada archivo declarará `schema_version`.
- Las coordenadas serán normalizadas entre 0 y 1 por defecto.
- Los identificadores serán estables.
- La ausencia de un derivado no invalidará el registro lógico.
- El contenido original y las revisiones se mantendrán separados.

### 6.2 `manifest.json`

```json
{
  "schema_version": "1.0",
  "run_id": "uuid",
  "digital_object_id": "uuid",
  "source_sha256": "...",
  "source_media_type": "pdf",
  "engine": "docling",
  "engine_version": "...",
  "model_versions": {},
  "options": {
    "ocr_mode": "auto",
    "rotation_overrides": {"4": 90}
  },
  "options_hash": "...",
  "created_by": "Alex",
  "created_at": "...",
  "status": "completed_with_warnings",
  "warnings": []
}
```

### 6.3 `objects.jsonl`

Contrato estructural completo.

```json
{
  "schema_version": "1.0",
  "object_id": "uuid",
  "digital_object_id": "uuid",
  "extraction_run_id": "uuid",
  "part_id": null,
  "order_index": 47,
  "object_type": "paragraph",
  "original_text": "La comisión informa...",
  "geometry": [
    {
      "page": 12,
      "polygon": [[0.11, 0.20], [0.88, 0.20], [0.88, 0.34], [0.11, 0.34]],
      "coordinate_space": "normalized"
    }
  ],
  "source_label": "text",
  "confidence": 0.92,
  "hidden_by_default": false,
  "attributes": {}
}
```

### 6.4 `paragraphs.jsonl`

Vista simplificada para compatibilidad y exportación.

```json
{
  "schema_version": "1.0",
  "paragraph_id": "uuid",
  "digital_object_id": "uuid",
  "extraction_run_id": "uuid",
  "page": 12,
  "order_index": 47,
  "object_type": "paragraph",
  "text": "La comisión informa...",
  "bboxes": [[0.11, 0.20, 0.88, 0.34]],
  "origin_object_ids": ["uuid"]
}
```

### 6.5 `images.jsonl`

Formato normal recomendado:

```json
{
  "schema_version": "1.0",
  "page_id": "uuid",
  "digital_object_id": "uuid",
  "extraction_run_id": "uuid",
  "page": 1,
  "sha256": "...",
  "width": 1275,
  "height": 1650,
  "dpi": 150,
  "path": "pages/0001.webp",
  "mime_type": "image/webp"
}
```

La exportación portátil podrá reemplazar `path` por `data_b64`, pero nunca incluir ambos.

---

## 7. Tipos de objetos sugeridos

El conjunto inicial está orientado tanto a documentos académicos como a expedientes policiales deteriorados:

| Clave | Uso |
|---|---|
| `title` | Título principal |
| `section_heading` | Título o acápite interno |
| `paragraph` | Cuerpo de texto |
| `list_item` | Enumeración o lista |
| `table` | Tabla estructurada o aproximada |
| `figure` | Imagen o figura |
| `chart` | Gráfico |
| `caption` | Epígrafe |
| `footnote` | Nota al pie |
| `table_of_contents` | Índice |
| `page_header` | Encabezado repetido |
| `page_footer` | Pie repetido o número |
| `stamp` | Sello o marca institucional |
| `handwritten_region` | Escritura manuscrita |
| `marginalia` | Nota al margen |
| `form_field` | Campo de ficha o formulario |
| `unknown` | Región todavía no clasificada |

Los tipos serán configurables antes de crear la primera base de producción.

---

## 8. Pipeline de extracción reducido

### 8.1 Diagnóstico

Para cada entrada:

- validar el archivo;
- calcular SHA-256;
- contar páginas o frames;
- medir dimensiones;
- detectar orientación;
- estimar existencia de texto digital;
- identificar páginas probablemente escaneadas;
- detectar archivos extremadamente grandes;
- mostrar advertencias y recomendaciones.

### 8.2 Preparación

- Aplicar rotaciones como instrucciones, sin alterar el original.
- Crear derivados de trabajo cuando sea necesario.
- Separar TIFF multipágina para procesamiento.
- Seleccionar páginas si se desea una prueba parcial.

### 8.3 Conversión

Modos:

- `auto`
- `sin_ocr`
- `ocr_completo`

Backend inicial: Docling, detrás de un contrato `ExtractorBackend`.

### 8.4 Normalización

Toda salida externa se transforma al contrato interno. Ninguna sección de la aplicación dependerá directamente del formato particular de Docling.

### 8.5 Control de calidad

Advertencias mínimas:

- páginas sin objetos;
- orden de lectura dudoso;
- OCR con baja confianza;
- orientación probable incorrecta;
- tablas sin estructura;
- regiones sin clasificar;
- objetos solapados;
- escritura manuscrita no transcripta.

Nada se descartará automáticamente. Algunos objetos podrán ocultarse por defecto.

---

## 9. TIFF grandes

### 9.1 Política

- Preservar el TIFF original.
- Calcular hash antes de cualquier conversión.
- No comprimir ni guardar encima del original.
- Registrar si es TIFF clásico o BigTIFF.
- Registrar si contiene una o varias páginas.
- Generar derivados por página.

### 9.2 Derivados

Para OCR:

```text
working/pages/0001.png
```

Para editor:

```text
pages/0001.webp
```

Sugerencias iniciales:

- OCR: 300 DPI, PNG.
- Vista del editor: 150 DPI, WebP.
- Alta resolución puntual: derivado bajo demanda.

### 9.3 Biblioteca

Se utilizará Pillow para inspección liviana y pruebas pequeñas. Para TIFF muy grandes se prevé `libvips` mediante `pyvips`, porque puede trabajar de forma secuencial y con menor uso de memoria que conversiones que cargan el raster completo.

### 9.4 Riesgos

- compresiones TIFF poco comunes;
- archivos truncados;
- páginas de cientos de megapíxeles;
- múltiples subimágenes o pirámides;
- orientación almacenada en metadatos;
- bitonalidad y contraste deficientes.

La primera tarea con el corpus será inspeccionar uno de esos TIFF sin convertirlo y registrar sus propiedades.

---

## 10. Editor documental

### 10.1 Paneles

**Izquierda:** imagen, zoom, bboxes, miniaturas.  
**Centro:** original, corregido, tipo, pertenencia estructural.  
**Derecha:** comentarios, etiquetas, entidades, relaciones, historial.

### 10.2 Edición

Cada cambio produce una revisión, no una sobrescritura del original.

```text
text_revision
    text_object_id
    base_revision
    edited_text
    editor_id
    created_at
```

### 10.3 División y unión

Una división crea nuevos objetos derivados. Una unión crea otro objeto y conserva todos los fragmentos geométricos. Los objetos anteriores quedan supersedidos, no borrados.

### 10.4 Comentarios y etiquetas

Son entidades aditivas. Dos comentarios diferentes sobre el mismo párrafo se conservan. Agregar dos etiquetas diferentes no constituye conflicto.

### 10.5 Imágenes opcionales

El editor debe funcionar solo con texto. Si existen imágenes, se cargan automáticamente. Si no existen, se informa sin impedir la edición.

---

## 11. Intercambio y combinación

### 11.1 Paquete

```text
<proyecto>_changes_<fecha>_<persona>.archivebundle
```

Contenido:

```text
manifest.json
changes.jsonl
attachments/
checksums.json
```

### 11.2 Evento

```json
{
  "event_id": "uuid",
  "project_id": "...",
  "entity_type": "text_object",
  "entity_id": "...",
  "operation": "update",
  "base_revision": 4,
  "new_revision": 5,
  "changed_fields": {"edited_text": "..."},
  "actor": "Alex",
  "timestamp": "..."
}
```

### 11.3 Combinaciones automáticas

- objetos diferentes;
- comentarios diferentes;
- etiquetas diferentes;
- relaciones diferentes;
- cambios en campos distintos desde la misma revisión base.

### 11.4 Conflictos

- mismo campo modificado de modo diferente;
- eliminar frente a modificar;
- dos segmentaciones incompatibles;
- dos extracciones declaradas vigentes;
- dos creaciones con la misma identidad y distinto contenido.

### 11.5 Seguridad operativa

Antes de importar:

1. validar checksums;
2. validar esquema y proyecto;
3. crear backup;
4. simular cambios;
5. pedir resolución de conflictos;
6. aplicar en una transacción;
7. registrar el paquete como importado.

La contraseña compartida funcionará como confirmación administrativa, no como seguridad criptográfica.

---

## 12. Búsqueda

### 12.1 FTS5

Se indexarán:

- títulos y códigos;
- descripción archivística;
- original y texto corregido;
- comentarios;
- etiquetas;
- entidades;
- relaciones descriptivas.

La búsqueda lexical será el mecanismo principal para palabras, frases, siglas y fórmulas.

### 12.2 Embeddings

El índice semántico será derivado y reconstruible. Se guardará fuera de SQLite o en tablas auxiliares, con la versión del modelo y del texto indexado.

### 12.3 Selección del editor

Acciones:

- frase exacta;
- términos;
- proximidad lexical;
- similitud semántica;
- crear etiqueta;
- crear entidad;
- crear relación.

---

## 13. Entidades y grafos

Las entidades automáticas serán sugerencias con estados `pending`, `accepted`, `rejected` o `modified`.

Los grafos serán vistas derivadas, no una segunda fuente de verdad. Deben distinguir:

- relación archivística;
- relación analítica humana;
- coincidencia lexical;
- similitud semántica;
- entidad compartida.

No se introducirá inicialmente una base como Neo4j.

---

## 14. Exportación

Perfiles configurables:

- usar texto corregido y fallback al original;
- incluir o excluir tipos de objeto;
- unir por documento, PDF, tomo o legajo;
- normalizar puntuación entre objetos;
- seleccionar código, título, fecha y fuente;
- vista previa;
- CSV o JSONL.

El perfil de exportación y el checkpoint del corpus quedarán registrados.

---

# 15. Plan de implementación

## Etapa 0 — Definiciones, contratos y corpus de prueba

### Objetivo

Fijar decisiones que condicionan la base, el editor, la extracción y el intercambio. Construir contratos validables antes de producir datos reales.

### Tareas

#### 0.1 Estructura inicial del repositorio — **implementado**

- paquete Python;
- configuración de proyecto;
- contratos Pydantic;
- CLI;
- tests iniciales.

#### 0.2 Plantilla de decisiones — **implementado**

- niveles archivísticos;
- tipos de objetos;
- JSONL;
- identidad;
- combinación;
- TIFF.

#### 0.3 Inspección de entradas — **implementado inicialmente**

- SHA-256;
- PDF;
- TIFF e imágenes;
- geometría vertical o apaisada, sin confundirla con rotación del texto;
- páginas con poco texto digital;
- recomendaciones preliminares.

#### 0.4 Corpus de prueba — **muestra inicial implementada**

Hay cinco casos reales registrados. La ampliación hacia 20–30 casos queda pendiente para etapas posteriores.

#### 0.5 Ground truth mínimo — **estructura implementada; contenido pendiente**

Para una muestra de páginas, registrar manualmente:

- objetos esperados;
- orden;
- texto crítico;
- estructura interna;
- regiones que no deben perderse.

#### 0.6 Contratos definitivos — **versión inicial validada**

Revisar las plantillas completadas y publicar `schema_version: 1.0`.

#### 0.7 Benchmark inicial

Comparar extracción sobre los primeros casos. No optimizar el motor hasta tener resultados observados.

### Criterios de cierre

- decisiones validadas por CLI;
- corpus de prueba identificado;
- cinco documentos con expectativas explícitas;
- contratos congelados como 1.0;
- estrategia confirmada para el primer TIFF pesado.

---

## Etapa 1 — Catálogo, SQLite y archivos

### Iteración 1.1 — Base y migraciones — **implementada en 0.2.0**

- SQLAlchemy;
- Alembic;
- tablas de proyecto, usuarios, unidades y metadata;
- restricciones e índices;
- tests de migración.

**Pedido sugerido:**

> Implementá la iteración 1.1 del documento maestro. Usá las decisiones completadas que adjunto. Creá modelos SQLAlchemy, migración inicial y tests de integridad. No hagas todavía Streamlit.

### Iteración 1.2 — Repositorios y servicios — **núcleo implementado en 0.22.0**

- CRUD de unidades;
- validación de jerarquía;
- movimientos en el árbol;
- revisiones y auditoría.

**Pedido sugerido:**

> Implementá la iteración 1.2: repositorios y servicios para unidades archivísticas, con transacciones y tests. Usá la migración ya creada y no agregues interfaz.

### Iteración 1.3 — Registro de objetos digitales — **núcleo implementado**

- digital objects;
- vínculos con unidades;
- instancias locales;
- ubicaciones remotas;
- hashes y duplicados.

### Iteración 1.4 — Rastreo de carpetas — **presencia e integridad implementadas**

- escaneo incremental;
- archivos nuevos;
- ausentes;
- movidos;
- mismo nombre y distinto hash;
- reporte antes de aplicar.

### Iteración 1.5 — Interfaz básica — **implementada en 0.22.0**

- selección de proyecto;
- índice expandible;
- formulario descriptivo;
- buscador de catálogo;
- estados de disponibilidad.

### Criterios de cierre

- registrar un legajo aunque falte el archivo;
- vincular uno o varios objetos;
- mover el proyecto de ruta sin romper referencias;
- detectar duplicados por contenido;
- árbol y buscador funcionales.

---

## Etapa 2 — Extracción PDF/TIFF

### Iteración 2.1 — Diagnóstico avanzado — **implementación parcial en 0.3.0**

- cobertura de texto por página;
- clasificación digital/escaneado/mixto;
- miniaturas;
- rotaciones;
- TIFF clásico/BigTIFF;
- estimación de memoria y espacio.

### Iteración 2.2 — Normalización TIFF — **núcleo implementado en 0.3.0**

- backend pyvips;
- separación de frames;
- derivados PNG;
- previews WebP;
- checksums;
- cancelación segura;
- recuperación ante fallos.

**Pedido sugerido:**

> Implementá 2.2 usando uno de los TIFF de prueba. Preservá el original, generá derivados por página, registrá checksums y evitá cargar el raster completo en RAM.

### Iteración 2.3 — Contrato de extractores — **implementada en 0.4.0**

- `ExtractorBackend`;
- opciones comunes;
- resultado normalizado;
- backend falso para tests.

### Iteración 2.4 — Docling — **implementación inicial en 0.4.0**

- PDF e imágenes;
- OCR auto/no/completo;
- layout;
- tablas;
- jerarquía de títulos;
- salida original de Docling preservada;
- adaptador a contratos internos.

### Iteración 2.5 — Salidas y registro — **implementada en 0.4.0**

- manifest;
- objects;
- paragraphs;
- imágenes referenciadas;
- carpetas con ID corto y slug;
- estados y reintentos.

### Iteración 2.6 — QA — **controles iniciales en 0.4.0**

- página y bboxes;
- advertencias;
- objetos sin clasificar;
- revisión de páginas;
- métricas contra ground truth.

### Criterios de cierre

- extraer un PDF escaneado y un TIFF;
- reproducir la corrida con el mismo manifest;
- no perder regiones críticas;
- distinguir originales y derivados;
- poder reextraer sin alterar revisiones humanas.

---

## Etapa 3 — Editor

### Iteración 3.1 — Backend de revisiones

- objetos;
- texto original;
- revisiones;
- historial;
- bloqueo optimista por revisión.

### Iteración 3.2 — Componente TypeScript mínimo

- imagen y texto;
- navegación;
- guardado;
- estado local;
- eventos hacia Python.

### Iteración 3.3 — Geometría

- bboxes y polígonos;
- múltiples páginas;
- zoom;
- panel opcional;
- ajuste manual.

### Iteración 3.4 — Operaciones estructurales

- dividir;
- unir;
- cambiar tipo;
- ocultar/restaurar;
- linaje;
- undo/redo transaccional.

### Iteración 3.5 — Partes internas

- documentos dentro del legajo;
- secciones y acápites;
- mover objetos;
- vincular parte a unidad archivística.

### Iteración 3.6 — Anotaciones

- comentarios;
- etiquetas;
- entidades manuales;
- relaciones;
- filtros y progreso.

### Criterios de cierre

- corregir un documento completo;
- cerrar y reabrir sin perder estado;
- recuperar el historial;
- editar sin imágenes;
- conservar geometría después de dividir o unir.

---

## Etapa 4 — Intercambio offline

### Iteración 4.1 — Change log — **implementada en 0.17.0**

- eventos por transacción;
- checkpoints;
- idempotencia;
- atribución.

### Iteración 4.2 — Exportación de bundle — **salida verificable implementada en 0.17.0**

- manifest;
- changes;
- checksums;
- adjuntos;
- firma lógica del contenido.

### Iteración 4.3 — Importación y simulación — **dry-run en 0.18.0 y aplicación transaccional en 0.19.0**

- validación;
- backup;
- dry run;
- reporte de cambios.

### Iteración 4.4 — Motor de combinación — **clasificación en 0.18.0 y aplicación de casos seguros en 0.19.0**

- cambios disjuntos;
- aditivos;
- duplicados;
- conflictos;
- borrado frente a actualización.

### Iteración 4.5 — Resolución visual

- base/local/importado;
- diff;
- selección;
- combinación manual;
- confirmación administrativa.

### Iteración 4.6 — Reservas informativas

- disponible;
- reservado;
- en revisión;
- finalizado;
- sincronización mediante paquetes.

### Criterios de cierre

- dos copias parten del mismo checkpoint;
- editan objetos distintos y se combinan;
- editan el mismo campo y aparece conflicto;
- un paquete no se aplica dos veces;
- una importación fallida no altera la base.

---

## Etapa 5 — Búsqueda y exportación

### Iteración 5.1 — FTS5

- índices;
- triggers o actualización controlada;
- snippets;
- frases;
- prefijos;
- filtros archivísticos.

### Iteración 5.2 — Buscador transversal

- catálogo;
- objetos;
- comentarios;
- etiquetas;
- entidades;
- apertura directa en editor.

### Iteración 5.3 — Selección del editor

- frase exacta;
- términos;
- búsqueda dentro de nivel o fecha.

### Iteración 5.4 — Exportación — **implementación inicial en 0.27.0**

- perfiles;
- vista previa;
- unión por unidad;
- reglas de puntuación;
- CSV y JSONL para EmoParse.

### Criterios de cierre

- buscar una fórmula y encontrar todas las apariciones;
- filtrar por serie y fechas;
- abrir el resultado exacto;
- reproducir una exportación mediante su perfil.

---

## Etapa 6 — Funciones derivadas

### Iteración 6.1 — Embeddings

- benchmark de modelos multilingües;
- índice reconstruible;
- agrupación por objeto/documento/legajo;
- calibración de resultados.

### Iteración 6.2 — Entidades

- sugerencias;
- offsets;
- revisión;
- canonicalización;
- diccionario específico del corpus.

### Iteración 6.3 — Grafos

- relaciones explícitas;
- entidades compartidas;
- lexical;
- semántico;
- filtros y explicación de cada arista.

### Iteración 6.4 — Audiovisual

- registro;
- archivo local;
- transcripción;
- segmentos temporales;
- hablantes opcionales;
- exportación al modelo común.

### Iteración 6.5 — Integración Drive

- enlaces;
- descarga asistida;
- subida de bundles;
- comparación de manifests;
- sin edición simultánea de la base.

---

# 16. Plantillas que debe completar el equipo

## 16.1 Niveles archivísticos

Por cada nivel:

```yaml
- key: legajo
  label: Legajo
  plural_label: Legajos
  display_order: 7
  parent_keys: [serie, subserie, caja]
  required_fields: [title]
  optional: false
```

Preguntas:

1. ¿“Archivo” es una unidad descriptiva real o solo el nombre de la institución custodiante?
2. ¿El fondo debe ser obligatorio?
3. ¿Caja tiene valor descriptivo o solo topográfico?
4. ¿Un documento puede colgar directamente de un legajo sin tomo?
5. ¿Existen carpetas, sobres, fichas u otros niveles que deban registrarse?
6. ¿El orden varía entre fondos?

Sugerencia: conservar una jerarquía flexible y permitir saltos, pero fijar los nombres que aparecerán en la interfaz antes de crear la base.

## 16.2 Tipos de objetos

Por cada tipo:

```yaml
- key: stamp
  label: Sello
  category: visual
  visible_by_default: true
  editable: true
  searchable: true
  export_by_default: false
  can_have_children: false
```

Preguntas:

1. ¿Los sellos deben transcribirse o solo marcarse?
2. ¿La escritura manuscrita se incorpora al contenido exportado?
3. ¿Una ficha debe ser un objeto o un documento interno?
4. ¿Los encabezados policiales repetidos se ocultan por defecto?
5. ¿Los números, códigos y clasificaciones merecen tipos propios?

## 16.3 Esquemas JSONL

Decidir:

- coordenadas normalizadas, píxeles o puntos PDF;
- imágenes referenciadas o embebidas por defecto;
- nombres definitivos de archivos;
- campos obligatorios;
- compatibilidad necesaria con herramientas existentes;
- tipos que `paragraphs.jsonl` incluirá.

Sugerencia: coordenadas normalizadas e imágenes referenciadas.

## 16.4 Reglas de identidad

Completar:

| Objeto | Identidad sugerida |
|---|---|
| Unidad archivística | UUID generado al registrar |
| Archivo físico | SHA-256 del contenido |
| Copia local | UUID + ruta relativa |
| Extracción | UUID + fuente/configuración registrada |
| Objeto textual | UUID estable |
| Comentario | UUID propio |
| Etiqueta aplicada | UUID propio o clave compuesta |
| Paquete de cambios | UUID |

Preguntas:

1. ¿Qué hacer si dos archivos tienen igual contenido pero nombres y descripciones diferentes?
2. ¿Qué hacer si se reemplaza un escaneo por uno de mayor calidad?
3. ¿Un PDF que reúne dos legajos es un objeto o dos?
4. ¿Una reextracción sustituye a la anterior o ambas quedan consultables?

Sugerencia: igual SHA-256 implica mismo contenido digital, pero puede vincularse a más de una unidad. Un nuevo escaneo tiene nuevo hash y relación de versión o representación alternativa.

## 16.5 Reglas de combinación

Clasificar cada campo o entidad como:

- aditivo;
- exclusivo;
- derivado;
- no combinable automáticamente.

Plantilla:

```yaml
entity: text_object
field: edited_text
policy: conflict_on_concurrent_change
reason: "Dos correcciones distintas requieren decisión humana"
```

Sugerencias:

- comentarios: aditivos;
- etiquetas: aditivas;
- relaciones: aditivas;
- título: conflicto si ambos lo cambian;
- texto corregido: conflicto;
- tipo de objeto: conflicto;
- ubicación local: puede coexistir por computadora;
- métricas e índices: derivados, se reconstruyen;
- extracción vigente: conflicto o selección explícita.

## 16.6 Resultado esperado por documento

Para cada caso de prueba:

```yaml
test_id: doc_001
local_path: ...
expected_extraction:
  minimum_page_coverage_percent: 95
  reading_order_should_be_correct: true
  preserve_stamps_as_regions: true
  preserve_handwriting_as_regions: true
  transcribe_handwriting_automatically: false
  expected_object_types: [paragraph, title, stamp]
  critical_text_examples:
    - "texto que no puede perderse"
```

No hace falta transcribir todo el documento. Al principio alcanza con elegir páginas y registrar qué debería ocurrir.

---

# 17. Corpus de prueba recomendado

Mínimo inicial de cinco casos:

1. PDF escaneado mecanografiado relativamente limpio.
2. PDF escaneado degradado o torcido.
3. Legajo con sellos, manuscritos y formulario.
4. PDF con varias orientaciones o varios documentos internos.
5. TIFF pesado o multipágina.

Ampliación a 20–30 casos:

- papel transparente o manchas;
- texto tenue;
- páginas duplicadas;
- hojas en blanco;
- recortes;
- fotos;
- tablas;
- mecanografía con letras rotas;
- sellos sobre texto;
- anotaciones marginales;
- numeración manuscrita;
- mezcla de tamaños y resoluciones.

Cada documento debe tener un responsable y una nota breve sobre por qué fue incluido.

---

# 18. Estrategia de pruebas

### Contratos

- validación de campos;
- versiones;
- compatibilidad hacia atrás;
- JSONL inválido;
- coordenadas.

### Persistencia

- claves foráneas;
- transacciones;
- migraciones desde bases antiguas;
- backup y restauración.

### Archivos

- mismo nombre, mismo hash;
- mismo nombre, distinto hash;
- archivo movido;
- ausente;
- archivo truncado;
- rutas Windows/Linux/Docker.

### Extracción

- fixtures pequeños;
- golden files;
- comparación de objetos;
- cobertura por página;
- memoria y cancelación;
- versiones de modelos.

### Editor

- navegación;
- guardado;
- división/unión;
- historial;
- imágenes ausentes;
- bboxes en varias páginas.

### Intercambio

- idempotencia;
- cambios disjuntos;
- conflictos;
- paquete corrupto;
- esquema incompatible;
- rollback.

---

# 19. Riesgos principales

| Riesgo | Tratamiento |
|---|---|
| OCR deficiente en mecanografiados deteriorados | benchmark, revisión, conservar imagen y confianza |
| Manuscritos no reconocidos | región preservada y transcripción manual |
| TIFF enormes | pyvips, derivados, procesamiento secuencial |
| Conflictos entre personas | reservas informativas + paquetes incrementales |
| Dependencia de un motor | contrato de backend y salida normalizada |
| Rutas rotas | rutas relativas + storage roots |
| Cambios de esquema | Alembic + versión de contratos |
| JSONL gigantes de imágenes | referencias por defecto, Base64 solo exportación |
| Complejidad del editor | componente TS aislado y API de operaciones |
| Crecimiento descontrolado | entregar por etapas con criterios de cierre |

---

# 20. Implementación inicial incluida

El starter adjunto contiene:

- `ProjectDecisions` y validación de ciclos y duplicados.
- Plantilla sugerida de niveles y objetos.
- Contratos de unidades, objetos digitales, extracción e intercambio.
- SHA-256, UUID, slugs y escritura JSONL atómica.
- Inspección preliminar de PDF, TIFF e imágenes.
- Detección de PDF probablemente escaneado por página.
- Detección de páginas horizontales.
- Recomendación de pyvips para páginas extremadamente grandes.
- Clasificador inicial de cambios disjuntos, duplicados y conflictos.
- CLI y tests.

Comandos:

```bash
archive-workbench validate-decisions config/decisions.template.yaml
archive-workbench inspect-input /ruta/documento.pdf
archive-workbench init-project project_data --templates config
pytest
```

---

# 21. Próxima iteración concreta

Mientras se descarga el corpus:

1. Copiar `config/decisions.template.yaml` como `decisions.yaml`.
2. Modificar solo lo que resulte claro; dejar comentarios donde haya dudas.
3. Completar cinco entradas de `test_corpus.template.yaml`.
4. Ejecutar `inspect-input` sobre un PDF y un TIFF.
5. Guardar las salidas JSON para revisarlas.

Con esos materiales, la próxima implementación será la **Iteración 1.1: SQLite, modelos SQLAlchemy y migración inicial**, ajustada a las decisiones reales del equipo.

---

## Referencias técnicas oficiales consultadas

- Docling, formatos admitidos: https://docling-project.github.io/docling/usage/supported_formats/
- Docling, conversor de documentos: https://docling-project.github.io/docling/reference/document_converter/
- Streamlit, componentes personalizados v2: https://docs.streamlit.io/develop/concepts/custom-components/components-v2
- SQLite FTS5: https://www.sqlite.org/fts5.html
- pyvips, introducción y manejo de imágenes grandes: https://libvips.github.io/pyvips/README.html


# 22. Estado de implementación al llegar a 0.30.0

La arquitectura local, versionada y auditable ya incluye catálogo, archivos, preprocesamiento, extracción, selección por página, edición, búsqueda literal y semántica, entidades, relaciones, grafo, exportación, intercambio y administración.

La versión 0.30.0 agrega la capa de coordinación operativa **Procesamiento**. Esta capa no crea una segunda fuente de verdad: deriva el estado desde SQLite, ejecuta los servicios existentes y persiste solamente el historial de los trabajos iniciados desde la interfaz.

El recorrido operativo actual es:

```text
Catálogo
→ Procesamiento: preparación
→ Procesamiento: extracción candidata
→ selección canónica manual por página
→ inicialización editable
→ Revisión
```

Una corrida nueva no reemplaza automáticamente selecciones ni texto aprobado. Los lotes continúan por documento aunque un ítem falle, y cada resultado queda registrado en `processing_jobs` y `processing_job_items`.

La búsqueda semántica está técnicamente operativa, pero su evaluación analítica permanece abierta hasta ampliar el corpus y definir consultas de control.

# 23. Estado de implementación al llegar a 0.31.0

La versión 0.31.0 agrega la capa **Trabajo** para coordinar responsabilidades sin alterar el estado canónico de los documentos.

El recorrido colectivo puede organizarse así:

```text
Procesamiento
→ asignación de revisión primaria
→ Revisión
→ envío de la asignación
→ asignación de revisión cruzada a otra persona
→ resultado de la segunda lectura
→ correcciones y cierre
```

Las asignaciones pueden abarcar documentos, páginas o rangos y conservan responsable, tipo, estado, prioridad, fecha límite, notas e historial. La revisión cruzada depende de una revisión primaria enviada y no puede asignarse a la misma persona.

Esta capa forma parte de checkpoints y bundles offline. No cambia automáticamente OCR, selecciones, texto editable, entidades ni estados de aprobación.

Permanece diferida la optimización de extracción: comparación OCR/Surya sobre corpus ampliado, ajustes de preprocesamiento y revisión de compatibilidad entre CUDA, PyTorch y las dependencias de cada backend.

# 24. Estado de implementación al llegar a 0.32.0

La versión 0.32.0 incorpora una capa temporal transversal para registrar existencia o vigencia de entidades y relaciones sin confundir precisión documental con precisión cronológica. Cada expresión se conserva tal como fue escrita y se acompaña de límites normalizados reconstruibles.

Los filtros temporales quedan disponibles en entidades, relaciones, búsquedas, grafo y exportaciones. El intercambio offline transporta los campos temporales y sus revisiones. También se corrige la edición de fechas límite en Trabajo.

La evaluación OCR/Surya, la optimización de perfiles y la estabilización CUDA continúan deliberadamente diferidas hasta contar con una muestra real suficiente.

# 25. Estado de implementación al llegar a 0.33.0

La versión 0.33.0 agrega el cierre operativo de la primera secuencia funcional. La vista **Inicio** reúne indicadores derivados del estado canónico sin crear una segunda fuente de verdad y permite navegar hacia cada tarea pendiente.

La recuperación deja de limitarse a comprobar checksums. Cada backup puede someterse a una prueba no destructiva que lo extrae, controla sus referencias, migra una copia temporal y verifica que pueda abrirse con la versión actual. Los resultados quedan auditados en `project_recovery_checks`.

La restauración real permanece separada y exige detener la interfaz. Antes de reemplazar SQLite crea una copia automática del estado vigente.

Este cierre es operativo, no una declaración de calidad final. OCR/Surya, perfiles de extracción, CUDA y evaluación semántica continúan pendientes de pruebas sobre corpus ampliado.


# 26. Estado de estabilización al llegar a 0.33.1

La versión 0.33.1 consolida el cierre operativo de 0.33.0 a partir de una prueba piloto integral. No agrega funciones analíticas mayores ni una nueva revisión de esquema: corrige fallas de integridad, auditoría, intercambio y vigencia de índices encontradas al usar el circuito completo sobre documentación real.

Las invariantes reforzadas son:

- una migración no puede perder vínculos de menciones ni eliminar relaciones;
- una mención aceptada o modificada debe tener autoridad canónica;
- un mismo fragmento no puede acumular menciones activas duplicadas;
- las relaciones requieren acciones explícitas y conservan historial al cambiar destino o darse de baja;
- el parentesco entre copias no depende únicamente de que sus hashes editables sean idénticos;
- un bundle incremental no puede transportar objetos OCR hijos sin una base compartida capaz de materializar sus páginas;
- un backup se ordena por su fecha verificable y un índice semántico se invalida solo por cambios dentro de su corpus.

La suite automatizada alcanza 171 tests. La próxima fase vuelve a concentrarse en revisión y extracción: comparación de candidatas, historial integrado, calidad automática, preprocesamiento conservador y evaluación de Surya/CUDA.


# 27. Estado de implementación al llegar a 0.34.0

La versión 0.34.0 integra la comparación y adopción de extracciones candidatas dentro de **Procesamiento** y reúne la auditoría de página dentro de **Revisión**. No crea pantallas ni fuentes de verdad paralelas.

El flujo visible queda reducido a cuatro situaciones comprensibles:

```text
página todavía no inicializada
→ puede seleccionarse e inicializarse

página inicializada sin trabajo humano
→ puede adoptarse otra candidata de forma segura

candidata ya usada por la edición
→ no hace falta ninguna acción

página con correcciones o anotaciones
→ la aplicación conserva la edición y exige una decisión explícita
```

Seleccionar, adoptar y aprobar son operaciones distintas. Cambiar solamente la selección nunca reemplaza texto editable. Cuando existe trabajo humano, la resolución disponible conserva íntegramente textos, orden, geometrías, anotaciones, menciones y estados; vincula la nueva candidata como referencia y deja registrados los objetos editables retenidos y los objetos candidatos no importados.

La migración `0029_extraction_candidate_history` incorpora historial append-only para la selección canónica y para el estado general de cada página editable. La cronología de Revisión compone esas fuentes con revisiones de objetos, comentarios, etiquetas, menciones, acciones estructurales, estados de revisión, deshacer y rehacer.

Los checkpoints incluyen ahora la selección y la procedencia OCR de la capa editable. Como los bundles offline no transportan corridas ni páginas de extracción, cualquier cambio posterior de base OCR bloquea la exportación incremental y exige crear una nueva copia física compartida con un checkpoint común. Esta restricción evita paquetes técnicamente válidos pero imposibles de materializar en la copia receptora.

La interfaz prioriza una única acción principal por situación, explica por qué una operación está bloqueada y mantiene los identificadores técnicos dentro de detalles secundarios. La próxima fase se concentra en calidad automática de imagen, preprocesamiento conservador, evaluación de Surya/CUDA y, posteriormente, sugerencias revisables de entidades.

# 28. Cierre del intercambio de decisiones OCR en 0.34.3

La versión 0.34.3 completa el criterio pendiente de 0.34.0: las decisiones sobre una candidata OCR pueden viajar mediante bundles offline sin convertir el paquete en un contenedor de corridas completas.

El bundle transporta y aplica, en su orden original:

```text
cambio de selección canónica
→ cambios de objetos producidos por una adopción segura
→ cambio de la base editable
→ correcciones, deshacer y rehacer posteriores
→ resolución que conserva la edición humana
```

La copia receptora debe contener previamente las corridas, páginas y objetos OCR referenciados. Esta condición se cumple normalmente cuando ambas copias nacieron de una misma copia física del proyecto. El dry-run verifica cada dependencia antes de habilitar la aplicación. Si falta una extracción, no intenta reconstruirla ni aplicar parcialmente la decisión: deja los eventos en revisión e indica que debe compartirse primero una copia física completa.

Las notas y el tipo de decisión se recuperan del historial append-only al exportar. Por eso también pueden transportarse decisiones ya registradas con 0.34.0, 0.34.1 o 0.34.2; no hace falta repetirlas después de actualizar.

Varias decisiones sucesivas sobre la misma página se simulan de manera encadenada durante el dry-run. La segunda operación se evalúa contra el estado que produciría la primera, no contra el estado inicial de la copia receptora. Esto permite intercambiar en un solo bundle secuencias reales de trabajo sin generar conflictos artificiales.

La revisión de base continúa siendo `0029_extraction_candidate_history`: el cambio pertenece a la lógica de exportación, evaluación y aplicación de bundles, no al esquema SQLite.

# 29. Corrección de intercambio de objetos retirados en 0.34.4

La validación real de 0.34.3 detectó seis conflictos artificiales al adoptar una candidata OCR. Las dos copias compartían el mismo checkpoint y no tenían cambios concurrentes: el problema estaba en los eventos `source_replaced` de objetos históricos sin revisión base.

Esos eventos describían erróneamente todos los campos como cambios desde `NULL`, aunque la operación real solo había retirado el objeto de la base activa. La versión 0.34.4 fija una representación canónica:

```text
lifecycle_status: active → deleted
```

La migración `0030_source_replaced_exchange` realiza dos tareas conservadoras:

1. reinstala el trigger de intercambio para que los nuevos `source_replaced` registren únicamente esa transición;
2. completa revisiones base solo cuando el estado anterior puede reconstruirse sin inventar contenido: objetos intactos en revisión 1 y objetos cuya primera revisión fue precisamente `source_replaced`.

El backfill no modifica el estado editable actual ni genera eventos nuevos. Agrega puntos de partida append-only a historiales incompletos.

Los eventos defectuosos ya registrados con 0.34.0–0.34.3 se normalizan durante la exportación al correlacionarlos con su revisión `source_replaced`. Por eso las acciones ya realizadas pueden reexportarse desde el checkpoint anterior; no es necesario repetir adopciones, correcciones ni resoluciones manuales.

El criterio de cierre se verifica de extremo a extremo: exportación desde el checkpoint común, dry-run con todos los eventos aplicables y cero conflictos, aplicación en la copia receptora y coincidencia de selección, base editable, objetos retirados, objetos nuevos e historial.

# 30. Intercambio completo del historial editable en 0.34.5

La validación de 0.34.4 confirmó que el estado final de una página podía llegar correctamente a otra copia, pero detectó una diferencia histórica: la receptora recreaba revisiones con operaciones genéricas (`create` y `exchange_apply`) y no recibía las filas de `editable_page_actions`. Por eso el texto, la selección y los objetos coincidían, aunque la cronología remota no podía reconstruir con precisión `edit`, `source_replaced`, `undo` y `redo`.

La versión 0.34.5 transporta dos niveles complementarios:

1. **Estado editable:** texto, tipo, orden, geometría, atributos, ciclo de vida y base OCR.
2. **Historia operativa:** operación original, nota, autor, fecha, acción de página, snapshots y marcas de deshacer/rehacer.

La migración `0031_page_action_exchange` instala eventos para la creación y actualización de acciones de página. También representa las acciones anteriores que ya existían al migrar. Si una acción histórica está presente en ambas copias, el dry-run la clasifica como duplicada; si solo existe en el origen, la aplica.

Las revisiones de objetos se enriquecen al exportar con su operación append-only original. La aplicación receptora conserva esa operación y no la sustituye por una etiqueta genérica. Esto permite que la cronología integrada describa la misma secuencia metodológica en ambas copias.

El hash del estado compartido incorpora ahora las acciones de página, porque la disponibilidad de deshacer o rehacer forma parte del estado operativo y no debe quedar fuera de los checkpoints.

La versión también corrige `project-backup-create`: crear un backup ya no ejecuta `upgrade_database()`. Un respaldo captura la revisión que existe en ese momento y la informa explícitamente; la migración se realiza después mediante `db-upgrade`.

El criterio de cierre exige coincidencia de selección, base editable, objetos activos y retirados, texto corregido, operaciones de revisión, acciones de página y cronología de undo/redo.

# 31. Control automático de calidad y migraciones explícitas en 0.35.0

La primera etapa posterior al cierre de candidatas OCR incorpora una evaluación automática por página, separada de cualquier decisión humana. El control mide características observables de la imagen y de la extracción: brillo, contraste, bordes débiles, ruido, volumen textual, fragmentación, objetos mínimos, símbolos sospechosos y solapamiento de bounding boxes.

El resultado se registra en `extraction_page_quality_assessments` con versión del algoritmo, métricas, alertas, sugerencias, autor y fecha. Una nueva evaluación no sobrescribe la anterior: solamente pasa a ser la vigente. Los estados `clear`, `attention` y `critical` ordenan la revisión; no equivalen a aceptación, aprobación ni rechazo.

Las sugerencias se limitan a operaciones conservadoras, como autocontraste, Otsu, comparación de PSM o revisión de layout. La evaluación no modifica imágenes, no ejecuta restauración generativa y no cambia la selección canónica ni la base editable.

La interfaz integra el control en **Procesamiento → Selección canónica** mediante una única acción para las versiones visibles. Las extracciones nuevas reciben una evaluación inicial automáticamente; las corridas históricas se evalúan bajo demanda.

Desde esta versión, la evolución del esquema también queda sometida a una regla global: únicamente `archive-workbench db-upgrade` puede ejecutar migraciones. Los demás comandos verifican la revisión y se detienen con una explicación si la base está desactualizada. `db-status` y la creación de backups siguen pudiendo leer o preservar una revisión anterior sin alterarla.

La migración `0032_page_quality_assessments` crea la nueva tabla vacía y no modifica extracciones, selecciones, objetos editables, revisiones ni eventos de intercambio existentes.

# 32. Transparencia del control y preprocesamiento conservador en 0.36.0

La versión 0.36.0 corrige la presentación del control automático de calidad para evitar que un puntaje heurístico se interprete como exactitud OCR. La interfaz diferencia explícitamente el estado asignado por el equipo del diagnóstico automático, muestra los indicadores que sostienen cada alerta y aclara que la ausencia de alertas no prueba que el texto sea correcto.

El primer flujo de preprocesamiento conservador se integra en **Procesamiento → Ejecutar → Preparar páginas**. La persona puede generar una nueva corrida de derivados para OCR con una de cuatro opciones reproducibles:

```text
sin cambios
autocontraste en escala de grises
binarización Otsu
reducción de ruido mediana y autocontraste
```

Los tratamientos se aplican únicamente al derivado OCR. El original y la previsualización permanecen intactos; no se usa restauración generativa, deskew automático ni transformación que invente trazos. Cada preparación conserva su perfil y hash de opciones, puede reutilizarse y volver a activarse sin duplicar archivos.

La preparación no ejecuta OCR ni cambia una selección canónica. Después debe correrse una extracción sobre el derivado vigente para obtener una candidata que pueda compararse con las anteriores mediante el flujo ya existente.

En rasteres demasiado grandes para Pillow, los tratamientos conservadores se detienen con una explicación antes de cargar la imagen en memoria. La ruta `Sin cambios` mantiene el uso de pyvips cuando está disponible.

La documentación técnica se reconstruye en un único archivo ASCII, `docs/DISENO_Y_PLAN_DE_IMPLEMENTACION.md`, con las secciones 1–32 completas y ordenadas. No hay migración nueva: la revisión de base continúa en `0032_page_quality_assessments`.

# 33. Navegación persistente y procedencia visible del derivado en 0.36.1

La versión 0.36.1 elimina una fuente repetida de confusión operativa: los reruns de Streamlit ya no devuelven a la primera pestaña de una sección. Todas las pestañas visibles quedan asociadas a una clave estable y registran la opción activa; cambiar un control, guardar o ejecutar una operación conserva la ubicación de la persona usuaria.

La política se aplica transversalmente a Procesamiento, Trabajo, Revisión, Catálogo, Entidades, Grafo, Exportar, Búsqueda semántica y Administración. Las aperturas programáticas continúan usando una solicitud pendiente aplicada antes de crear el widget, para no modificar el estado de una pestaña ya instanciada.

En el flujo OCR se explicitan dos capas que antes aparecían confundidas:

```text
tratamiento del derivado vigente
→ transformación realizada al preparar las páginas

image_variant del perfil
→ transformación adicional aplicada durante la extracción
```

Por eso `image_variant: original` no implica volver al archivo fuente ni ignorar la preparación. Significa que el perfil utiliza el derivado vigente sin agregarle una segunda transformación. La pantalla de extracción muestra ambas decisiones por documento antes de ejecutar la corrida.

La revisión de base continúa siendo `0032_page_quality_assessments`; el cambio pertenece a la interfaz y a la política de navegación.

# 34. Backend experimental Surya y verificación explícita de aceleración en 0.37.0

La versión 0.37.0 incorpora `surya_cli` como tercer backend de extracción, junto con `docling_cli` y `tesseract_tsv`. Surya se ejecuta como subproceso para que sus dependencias y su servidor de inferencia puedan mantenerse aislados del entorno principal de Archive Workbench.

El perfil `config/extraction_surya_es.yaml` produce candidatas por página con OCR, clasificación de bloques y orden de lectura. La normalización conserva el HTML crudo, las etiquetas original y canónica, la confianza, los bounding boxes, el orden y los indicadores de bloques omitidos o fallidos. Las etiquetas se traducen a los tipos configurables de Archive Workbench sin crear estados nuevos.

El campo `device` tiene una interpretación explícita para Surya:

```text
auto  → vLLM con NVIDIA/Docker si está disponible; de lo contrario llama.cpp
cuda  → vLLM con NVIDIA/Docker
cpu   → llama.cpp mediante llama-server
```

Si el intento acelerado falla y el perfil habilita fallback, se realiza un único reintento con llama.cpp en CPU. Ambos comandos, variables de entorno, stdout y stderr quedan en `raw/surya.log`; el manifiesto conserva la versión del paquete y todas las opciones reproducibles.

`extraction-doctor` verifica por separado el ejecutable Surya y el backend requerido. Para CUDA comprueba NVIDIA, Docker y el runtime `nvidia`; para CPU comprueba `llama-server`; también puede validar un servidor OpenAI-compatible configurado mediante `surya_inference_url`. La prueba efectiva de uso real no se declara a partir del diagnóstico: se confirma ejecutando una corrida de una página con `--device cuda` o `--device cpu` y revisando su log y sus resultados.

La interfaz integra el perfil en **Procesamiento → Ejecutar → Extraer texto** y explica qué backend se solicitará. Toda corrida sigue la política ya establecida: genera candidatos, no cambia automáticamente la selección canónica ni reemplaza una edición existente.

No hay migración nueva. La revisión continúa en `0032_page_quality_assessments`. La evaluación comparativa de exactitud, layout y rendimiento sobre verdad terreno continúa pendiente y debe realizarse con las mismas páginas y derivados usados por Tesseract.

# 35. Runtime aislado y compatibilidad reproducible de Surya en 0.37.1

La instalación real de 0.37.0 mostró una incompatibilidad de dependencias: Archive Workbench exigía Pillow 11 o posterior, mientras `surya-ocr==0.22.1` exige Pillow 10.2 o posterior y menor que 11. La corrección amplía el rango compatible del paquete principal y fija exactamente la versión de Surya cuya CLI y esquema de salida fueron integrados.

Surya continúa siendo un subproceso externo y se instala por defecto en `.venv-surya`, separado de `.venv`. Esta separación evita que su rama de Pillow, Torch y Transformers reemplace las bibliotecas usadas por Streamlit, Docling, preprocesamiento y búsqueda semántica en el entorno principal.

El instalador `scripts/install_surya_runtime.sh` ofrece dos pasos explícitos:

```text
--dry-run → resolver dependencias sin instalarlas
install   → instalar, ejecutar pip check e informar el ejecutable resultante
```

Los perfiles apuntan a `.venv-surya/bin/surya_ocr`. Las rutas relativas, absolutas y con `~` se normalizan antes del diagnóstico y de la ejecución; la versión se consulta mediante el Python del mismo runtime para no confundir paquetes instalados en entornos diferentes.

No hay migración de base. La corrección pertenece al empaquetado y al aislamiento del backend experimental. La verificación empírica de CUDA, CPU, exactitud, layout y rendimiento continúa pendiente.

# 36. Surya preferido, fallback automático y servidor persistente en 0.38.0

La evaluación empírica documentada en `docs/EVALUACION_SURYA_OCR_0.38.0.md` mostró una mejora consistente de Surya sobre seis páginas reales con deterioro, mala orientación, manuscritos y estructura de formulario. La decisión de diseño deja de tratarlo como una alternativa experimental equivalente a las demás: pasa a ser el backend preferido cuando su runtime está disponible, sin convertirlo en dependencia obligatoria ni permitir que seleccione páginas automáticamente.

El perfil principal `config/extraction.yaml` utiliza `surya_cli` y declara `config/extraction_docling_es.yaml` como fallback. La resolución ocurre antes de la corrida: si el ejecutable, el backend VLM o los modelos auxiliares no están listos, se elige el fallback y se informa el motivo. Si Surya supera el diagnóstico pero falla durante un documento, el intento fallido se conserva y el fallback procesa únicamente los documentos que no pudieron completarse. Esta recuperación no borra el error original y queda registrada como advertencia.

La configuración validada en la RTX 3090 separa dos dispositivos:

```text
VLM de OCR, layout y orden de lectura
→ vLLM en Docker con NVIDIA

modelos auxiliares Torch
→ CPU dentro de .venv-surya
```

El subproceso fija `TORCH_DEVICE=cpu` y elimina el `LD_LIBRARY_PATH` heredado cuando el perfil lo solicita. Esto evita mezclar la cuDNN del runtime de PyTorch con bibliotecas del sistema, sin modificar la instalación CUDA global ni la `.venv` principal.

Para eliminar el costo dominante observado —carga, compilación y warmup de vLLM— el perfil usa `surya_keep_server: true`. El primer comando deja activo el contenedor `surya-vllm-*`; las corridas posteriores se conectan al mismo servidor. La persona usuaria puede inspeccionarlo o liberar la VRAM explícitamente:

```bash
archive-workbench surya-server-status
archive-workbench surya-server-stop
```

`extraction-doctor` informa por separado el ejecutable Surya, el backend VLM y los modelos auxiliares. Cuando los auxiliares están configurados en CPU no realiza una convolución cuDNN irrelevante para decidir si la ruta VLM GPU está disponible.

La interfaz muestra el carácter preferido del perfil, la configuración híbrida, la persistencia del servidor y el fallback. La selección canónica conserva la misma regla de seguridad: todo resultado es una candidata hasta que una persona la compara y la adopta.

Los proyectos existentes no reciben una reescritura silenciosa de sus perfiles. La adopción del perfil preferido requiere una copia explícita de los perfiles estándar, con respaldo previo, para preservar cualquier personalización local.

No hay migración nueva. La revisión de base continúa en `0032_page_quality_assessments`. Quedan pendientes una capa semántica para casilleros, alertas revisables para ordinales legales y un benchmark con verdad terreno.


# 37. Resolución coherente del dispositivo auxiliar de Surya en 0.38.1

El diagnóstico y la ejecución de Surya comparten una única regla para resolver `TORCH_DEVICE`. Cuando `surya_torch_device` permanece en `auto`, un perfil con `device: cpu` fuerza también los modelos auxiliares a CPU, uno con `device: cuda` los dirige a CUDA y uno con `device: auto` conserva la autodetección; una configuración auxiliar explícita sigue teniendo prioridad.

Esto evita que un perfil CPU consulte o utilice accidentalmente CUDA/cuDNN del equipo anfitrión y convierte las pruebas del doctor en pruebas aisladas del hardware real. La política híbrida validada para el perfil preferido no cambia: `device: auto` para el VLM y `surya_torch_device: cpu` para los auxiliares.

# 38. Control estructural revisable para ordinales y casilleros en 0.39.0

La calidad OCR no puede evaluarse solamente con volumen textual, fragmentación o confianza. Las pruebas reales de Surya mostraron dos pérdidas semánticas específicas: ordinales legales convertidos en números de dos cifras y formularios cuyos rótulos se leen correctamente, pero cuyo estado marcado o no marcado no queda representado de forma segura en el texto plano.

La versión 0.39.0 integra esas comprobaciones en el control automático ya existente. `page_quality_v2` conserva métricas de imagen y extracción y agrega detalles estructurales en el JSON de cada evaluación. No se crea una tabla nueva porque las evaluaciones ya admiten métricas, flags y sugerencias versionadas.

La regla de ordinales exige una secuencia suficientemente fuerte antes de alertar. Presenta una lectura posible —por ejemplo `49` como posible `4º`—, pero nunca reescribe el objeto extraído. Una secuencia normal como `49`, `50`, `51` no activa la regla.

La regla de casilleros identifica controles preservados en el HTML crudo de Surya, símbolos explícitos y marcas pequeñas próximas a rótulos. El resultado se conserva como candidato con estado, marca, etiqueta y método de asociación. Los casilleros vacíos que no produzcan un objeto OCR ni un control HTML permanecen indetectables y se señalan como límite de la técnica.

La interfaz muestra ambos grupos dentro de **Ver indicadores del control automático** y aclara que requieren revisión visual. La selección canónica, la adopción de candidatas y la edición continúan siendo decisiones humanas separadas.

No hay migración nueva. La revisión de base continúa en `0032_page_quality_assessments`; las evaluaciones anteriores conservan `page_quality_v1` y pueden recalcularse explícitamente para obtener los indicadores de `page_quality_v2`.

# 39. Rebase seguro de edición y navegación persistente de raíz en 0.40.0

La versión 0.40.0 incorpora el procedimiento que faltaba entre la comparación de candidatas y la sustitución segura de una base editable ya trabajada. El rebase compara la extracción que originó la edición, el estado humano vigente y la nueva candidata. La candidata aporta la estructura, el orden y la geometría; las modificaciones humanas se vuelven a aplicar únicamente cuando el alineamiento permite hacerlo sin ambigüedad.

La vista previa es obligatoria y no escribe en la base. Informa bloques anteriores y nuevos, correcciones trasladadas, menciones, comentarios, etiquetas, estados y partes documentales. La aplicación queda bloqueada ante cambios superpuestos, menciones sin relocalización exacta, metadatos incompatibles o acciones estructurales previas. No existe modo forzado que silencie esos conflictos.

Cuando el plan es seguro, la operación se ejecuta en una única transacción. Los nuevos objetos quedan anclados a la candidata; las menciones cambian de objeto y offsets mediante una revisión append-only; comentarios, etiquetas y partes se trasladan; los objetos anteriores pasan a retirados sin borrarse. La página registra una revisión `rebase` con todos los identificadores y conteos necesarios para auditar la decisión. Las relaciones canónicas entre autoridades permanecen intactas.

El intercambio offline reconoce `rebase` como una operación explícita de cambio de base editable y conserva su estrategia `three_way_text_rebase` junto con las revisiones de objetos y menciones.

La versión también corrige la causa del retorno a la primera pestaña después de una navegación programática. `tracked_tabs` ya no aplica la pestaña solicitada únicamente como `default` de un rerun: la persiste como estado activo antes de construir el widget. El estado sobrevive al rerun siguiente provocado por cualquier selectbox, botón o cambio de documento y la regla se aplica globalmente.

No hay migración nueva. La revisión de base continúa en `0032_page_quality_assessments`.

# 40. Resolución asistida de conflictos de menciones en el rebase 0.41.0

La versión 0.41.0 completa el primer bloque de resolución manual asistida sobre el rebase incorporado en 0.40.0. La aplicación ya no se limita a informar que una mención desapareció o que dos menciones convergen en el mismo fragmento: presenta el contexto anterior, la autoridad vinculada y destinos concretos dentro de la nueva base.

La búsqueda de anclajes se amplía a todos los bloques candidatos. Una coincidencia única exacta o normalizada se traslada automáticamente aunque el alineamiento estructural haya predicho otro bloque. Las coincidencias múltiples o aproximadas permanecen bloqueadas y se muestran como sugerencias revisables.

La persona usuaria puede elegir una sugerencia, seleccionar manualmente un bloque y un fragmento exacto, o rechazar explícitamente una mención duplicada. El rechazo no elimina ni modifica la autoridad canónica ni sus relaciones: conserva la mención con estado `rejected`, su revisión append-only y el objeto anterior retirado.

La vista previa se recalcula con las decisiones tomadas y el botón de aplicación continúa deshabilitado mientras quede cualquier conflicto. Las relocalizaciones manuales y los rechazos se registran como `rebase_relocate_manual` y `rebase_reject_conflict`; la revisión de página conserva los conteos y la estrategia de rebase.

Los conflictos textuales superpuestos, acciones estructurales previas y metadatos incompatibles siguen sin modo forzado. No hay migración nueva y la revisión de base continúa en `0032_page_quality_assessments`.

# 41. Conflictos textuales de rebase y aislamiento atómico de vistas en 0.42.0

La versión 0.42.0 convierte las superposiciones entre correcciones humanas y cambios distintos de la candidata en conflictos estructurados y revisables. Cada caso conserva la base anterior, la corrección humana, la lectura candidata, el contexto y un identificador estable. La persona usuaria puede conservar la candidata, reaplicar la corrección humana o escribir el resultado exacto para ese tramo; ninguna decisión se infiere ni se aplica por defecto.

Las resoluciones se revalidan contra los fragmentos que estaban visibles al decidir. Una vez incorporadas, la vista previa completa se recalcula y las menciones vuelven a proyectarse sobre el texto resultante. La revisión de página registra la cantidad y los métodos de las decisiones textuales. Los conflictos estructurales y de metadatos incompatibles continúan bloqueados.

La versión también corrige en la raíz la permanencia de vistas anteriores oscurecidas e interactivas. Todas las navegaciones entre modos pasan por `request_app_view`, y el contenido principal se monta dentro de un único placeholder estable mediante `isolated_view`. Cada modo tiene una identidad de contenedor propia, por lo que Streamlit desmonta el árbol anterior completo antes de mostrar la nueva vista. La política se aplica a todas las secciones de la aplicación.

No hay migración nueva y la revisión de base continúa en `0032_page_quality_assessments`.


# 42. Rebase del estado estructural activo y resolución de metadatos en 0.43.0

La versión 0.43.0 deja de tratar la mera existencia de acciones de división, unión, reordenamiento, deshacer o rehacer como un conflicto. El rebase toma como fuente de verdad el snapshot editable activo después de esas acciones y conserva el historial completo sin intentar reproducirlo mecánicamente sobre la candidata. Solo bloquea cuando la proyección del estado actual produce una incompatibilidad concreta.

Los objetos activos se alinean con los bloques candidatos después del rebase textual. Las menciones mantienen su relocalización independiente; los comentarios convergentes se trasladan y las etiquetas idénticas se deduplican sin borrar la copia histórica asociada al objeto retirado.

Cuando varios objetos convergen con partes documentales, estados de revisión o tipos de objeto incompatibles, la interfaz presenta una resolución explícita por bloque. La persona usuaria puede elegir una parte existente o ninguna, un estado de revisión resultante y la clasificación humana o candidata. Las decisiones se revalidan contra las opciones visibles y quedan registradas en la revisión append-only de página.

La operación continúa siendo transaccional y no agrega un modo forzado. Las incompatibilidades textuales, de menciones, de proyección estructural o por cambios concurrentes siguen bloqueando toda escritura. No hay migración nueva y la revisión permanece en `0032_page_quality_assessments`.

# 43. Continuidad de interacción y ámbitos de rerun en 0.44.0

La versión 0.44.0 establece una frontera de ejecución entre la vista activa y la aplicación completa. Cada renderer principal se monta como fragmento dentro del contenedor atómico de su modo. Una interacción ordinaria —seleccionar un objeto, cambiar una opción o recalcular una vista previa— vuelve a ejecutar solamente ese fragmento; la barra lateral, el encabezado y los demás modos permanecen montados sin reconstrucción.

Las navegaciones entre modos conservan un rerun completo deliberado. La diferencia queda centralizada mediante `rerun_view` y `rerun_app`, y una prueba de arquitectura impide llamadas directas a `st.rerun` desde los módulos `*_app.py`. Esta regla evita que nuevas pantallas reintroduzcan actualizaciones globales por accidente.

Las confirmaciones finales o destructivas se agrupan en formularios para que marcar una casilla no produzca por sí solo un rerun. La casilla y la acción se envían juntas. El primer alcance comprende el rebase, la conservación íntegra de una edición, la desvinculación archivística y las decisiones masivas o aplicación de bundles. El panel de rebase permanece abierto mientras se resuelven sus conflictos.

La versión también incorpora una resolución explícita para objetos anotados cuya proyección sobre la candidata sea débil o ambigua. La vista previa combina similitud textual y solapamiento posicional, presenta los destinos sugeridos y exige seleccionar un bloque antes de trasladar menciones, comentarios, etiquetas o metadatos. La decisión se invalida si cambia la lista de objetos candidatos y queda registrada como `manual_object_projection`.

La aplicación continúa siendo reactiva: una interacción puede redibujar el fragmento que necesita recalcularse. La garantía de diseño es que no pierda la vista o pestaña activa, no reconstruya secciones ajenas y no cierre una confirmación antes de enviarla. No hay migración nueva y la revisión permanece en `0032_page_quality_assessments`.

# 44. Confirmación enviable y atributos especializados en el rebase 0.45.0

La versión 0.45.0 corrige la semántica de los formularios finales. Un widget incluido en un formulario no comunica su valor hasta el envío; por lo tanto, el propio botón de envío no puede depender del valor todavía no enviado. El rebase mantiene el botón disponible cuando la vista previa es aplicable y valida la confirmación dentro del evento de envío. Una confirmación ausente produce un mensaje y ninguna escritura.

El rebase distingue los atributos de procedencia OCR, los indicadores estructurales transitorios y los atributos especializados humanos. La procedencia se reconstruye desde la candidata; los indicadores de división, unión, geometría pendiente o linaje quedan absorbidos por el historial; los atributos humanos nuevos o modificados se proyectan junto con el objeto editable.

Un valor especializado único se conserva automáticamente. Los valores iguales se deduplican. Cuando difieren dos objetos humanos o cuando un valor humano contradice a la candidata, la interfaz exige elegir una opción existente, eliminar el atributo o escribir un JSON manual válido. Las decisiones se revalidan y quedan auditadas como `manual_attribute_selection` o `manual_attribute_json`.

La versión incorpora un generador de proyecto descartable que produce de forma determinista dos proyecciones estructurales ambiguas y una convergencia de atributos incompatible. Este caso permite validar el flujo completo sin modificar los proyectos operativos. No hay migración nueva y la revisión permanece en `0032_page_quality_assessments`.

# 45. Fragmentos autocontenidos, formularios explícitos y calidad de sugerencias en 0.46.0

La versión 0.46.0 corrige la frontera entre navegación y reruns locales. La vista activa ya no escribe desde un fragmento dentro de un `st.empty` creado por la aplicación completa: el propio fragmento crea y administra su contenedor raíz. Así, cada rerun local limpia solamente su árbol y una navegación completa no conserva elementos oscurecidos de la vista anterior.

La política de confirmación pasa a ser global. Todos los formularios usan `enter_to_submit=False`; pulsar `Enter` puede actualizar el valor local de un widget, pero nunca equivale a crear, guardar, aplicar, dar de baja o confirmar una operación. Una prueba de arquitectura recorre el código de la interfaz y bloquea cualquier formulario nuevo que omita esa opción.

La capa editable deja de ocultar los atributos arbitrarios vigentes: Revisión incorpora una pestaña **Atributos** que presenta el `current_attributes_json` completo del objeto seleccionado, incluidos valores de procedencia, clasificación y metadatos conservados por un rebase.

Las sugerencias automáticas de entidades y menciones aplican control de calidad antes de recorrer el corpus. El valor predeterminado incluye únicamente páginas `approved`; la interfaz de Entidades permite ampliar de forma explícita el conjunto de estados. La misma regla alcanza la búsqueda transversal, la incorporación posterior y el escaneo por diccionario, de modo que cambiar el estado de una página invalida también las coincidencias que ya no pertenecen al corpus autorizado.

No hay migración nueva. La revisión de base continúa en `0032_page_quality_assessments`.

# 46. Rebase repetible e identidad lógica de menciones en 0.47.0

La versión 0.47.0 distingue el objeto OCR inmutable de sus representaciones editables históricas. Cuando una candidata ya utilizada vuelve a convertirse en base de la edición, el vínculo fuerte de la representación retirada se libera antes de crear la nueva representación; el identificador de procedencia se conserva en atributos auditables y las revisiones append-only permanecen intactas. Esto permite ciclos `A → B → A → B` sin relajar la unicidad vigente ni recrear tablas de SQLite.

La deduplicación de menciones deja de depender exclusivamente de la tupla revisión + offsets. Una mención histórica se proyecta sobre el texto actual únicamente cuando su tramo pertenece a un bloque textual igual entre revisiones o cuando existe una sola aparición literal inequívoca. La búsqueda transversal, la creación de dominio y la validación administrativa usan esa identidad lógica para impedir vínculos contradictorios sobre el mismo fragmento vigente.

La política de formularios se aplica también a formularios anidados en columnas y contenedores. El análisis AST ya no reconoce solamente `st.form`, sino cualquier llamada `.form`, por lo que pulsar `Enter` no puede guardar una modificación de mención ni reintroducirse accidentalmente en futuras vistas.

No hay migración nueva y la revisión de base permanece en `0032_page_quality_assessments`. La calibración semántica continúa pendiente: el resultado no pertinente observado con similitud `0.830` se conserva como caso de evaluación, sin convertir una observación aislada en un umbral global.

# 47. Resoluciones manuales explícitas y política visual de teclado en 0.48.0

La versión 0.48.0 completa la política de acciones explícitas en los tres lugares del rebase que todavía dependían de entradas reactivas: el texto exacto de un conflicto textual, el fragmento manual de una mención y el valor JSON de un atributo especializado. Cada entrada vive ahora dentro de un formulario propio con `enter_to_submit=False` y un botón específico. Escribir, salir del campo o pulsar Enter no incorpora la decisión a la vista previa.

La resolución confirmada se conserva en el estado de sesión mediante una clave estable por conflicto. En cada rerun se vuelve a validar contra la candidata y las opciones vigentes antes de recalcular la vista previa. Cambiar a una decisión no manual elimina el valor manual almacenado para evitar que una resolución anterior se reaplique de forma invisible.

Streamlit muestra instrucciones automáticas como `Press Enter to submit form` o `Press Ctrl+Enter to apply` junto a campos de escritura. Como contradicen el contrato de la aplicación, la vista raíz oculta globalmente el elemento `InputInstructions`. Esta capa es únicamente de presentación: la garantía funcional sigue estando en los formularios no enviables por teclado y en los botones explícitos.

Las pruebas de arquitectura inspeccionan todas las llamadas `.form(...)`, comprueban `enter_to_submit=False` y verifican que las tres entradas manuales y sus botones se encuentren dentro de formularios independientes. No hay migración nueva y la revisión de base permanece en `0032_page_quality_assessments`.

# 48. Ciclo de vida operativo para exportaciones y bundles en 0.49.0

La versión 0.49.0 incorpora un ciclo de vida explícito para dos objetos operativos que hasta ahora solo podían acumularse: perfiles de exportación y evaluaciones de bundles recibidos. Ambos pueden archivarse para salir de la vista normal y restaurarse después; la eliminación definitiva queda restringida a perfiles archivados y a bundles no aplicados. Las exportaciones ya materializadas y las aplicaciones de intercambio conservan sus snapshots, hashes y auditoría aunque desaparezca el objeto operativo que las originó.

La confirmación de una exportación deja de depender de un mensaje efímero anterior al rerun. El resultado se conserva en el estado de la vista y presenta ruta, formato, cantidad de registros, caracteres, tamaño, SHA-256 y descarga directa hasta que la persona lo cierre expresamente. Antes de archivar o eliminar un perfil, la interfaz muestra las exportaciones históricas que todavía lo referencian.

Los dry-runs `stale` exponen la secuencia evaluada, la secuencia actual y los eventos locales posteriores que explican la caducidad. Archivar no modifica el corpus ni borra reportes; limpiar una entrada archivada no aplicada elimina únicamente el ZIP recibido, el dry-run, sus decisiones y sus reportes internos. Un bundle ya aplicado no puede limpiarse porque su evaluación forma parte de la cadena de auditoría.

La resolución de bundles sin base común inicializa correctamente el agrupamiento por evento y muestra todos los campos revisables. La pantalla explica que aceptar valores recibidos no reconstruye el parentesco y deshabilita decisiones masivas incompatibles con creaciones sin una base verificada. La recuperación asistida del linaje sigue siendo una operación futura e independiente.

Estos cambios agregan la migración `0033_export_exchange_lifecycle`, que incorpora estado de ciclo de vida y datos de archivo a `corpus_export_profiles` y `exchange_dry_runs` sin reescribir sus registros anteriores.

# 49. Corrección de confirmaciones operativas en 0.49.1

Las casillas de confirmación incluidas dentro de un formulario no pueden controlar la propiedad `disabled` de su propio botón: Streamlit comunica el nuevo valor recién al enviar el formulario, lo que produce un bloqueo circular. La versión 0.49.1 mantiene el botón disponible cuando el estado operativo lo permite y valida la casilla al pulsarlo; sin confirmación muestra un error y no ejecuta ninguna escritura. Una prueba AST impide reintroducir este patrón en cualquier pantalla.

También se precisa el alcance del análisis automático pendiente: no se limita a buscar nombres y alias conocidos, sino que debe recorrer el corpus para proponer actores, espacios, tiempos y acontecimientos nuevos como candidatos revisables y trazables, sin canonización automática.

# 50. Estado operativo de pendientes y estrategia de pruebas en 0.49.2

La versión 0.49.2 separa el registro histórico del listado operativo. `PENDIENTES_ACTIVOS.md` contiene únicamente trabajo abierto o parcial con identificadores estables; el documento consolidado conserva la evidencia de cada resolución y validación. La migración 0027 deja de figurar como bloqueante después de pasar la regresión con autoridades, alias, menciones aceptadas, relaciones, snapshots y claves foráneas desde 0026 hasta 0033.

La recuperación asistida de linaje queda explicitada como una operación futura independiente: resolver campos de un bundle `unmatched` no crea parentesco. También se registra la desincronización visual del formulario de perfiles después de archivar, restaurar o eliminar, sin confundirla con una pérdida de datos.

La política de pruebas distingue desde ahora pruebas afectadas, transversales, recopilación completa y suite monolítica local. Se conserva toda la cobertura; la clasificación futura en `fast`, `integration` y `slow` busca reducir tiempo por versión, no eliminar regresiones históricas. No hay migración ni cambio funcional.
