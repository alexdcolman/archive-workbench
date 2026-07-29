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
