# Prueba piloto y cierre de Archive Workbench 0.33.1

## Alcance

La prueba piloto se realizó sobre seis documentos locales y 63 páginas editables. Incluyó extracción OCR heterogénea, revisión humana, búsqueda, entidades, relaciones, grafo, exportación, intercambio offline, backup y recuperación.

El objetivo no fue certificar la calidad final del OCR, sino recorrer el circuito operativo completo, detectar fallas de integridad y comprobar que los datos canónicos pudieran revisarse, exportarse, intercambiarse y recuperarse.

## Circuitos comprobados

- Catálogo y verificación de archivos locales.
- Procesamiento, corridas candidatas y selección OCR por página.
- Inicialización, edición, eliminación persistente y aprobación de páginas.
- Búsqueda literal con filtros de revisión y exclusión de objetos eliminados.
- Búsqueda semántica local mediante Multilingual E5 y CUDA.
- Creación de autoridades, detección transversal, aceptación de menciones y relaciones explícitas.
- Grafo con aristas explícitas y derivadas de menciones.
- Exportación JSONL reproducible: dos archivos generados con el mismo perfil produjeron el mismo SHA-256.
- Backup, inspección y recuperación en entorno temporal sin modificar la base activa.
- Intercambio offline limpio: un alias posterior al checkpoint viajó como un único evento, fue evaluado, respaldado y aplicado correctamente en otra copia.
- Estado operativo final de la copia receptora: nueve áreas listas, cero atenciones y cero pendientes.

## Errores bloqueantes encontrados y corregidos

### Migración 0027

La recreación batch de `authority_records` activaba `ON DELETE SET NULL` en menciones y `ON DELETE CASCADE` en relaciones. La migración ahora agrega las columnas temporales sin eliminar la tabla padre y cuenta con una prueba de regresión.

### Integridad de menciones

Las menciones aceptadas o modificadas requieren una autoridad. La incorporación transversal detecta menciones existentes por objeto, revisión y offsets: puede vincular una huérfana, reconocer una ya incorporada o mostrar un conflicto con otra autoridad.

### Relaciones

Los formularios no se envían mediante `Enter`. La interfaz permite cambiar el destino y presenta la baja lógica como una acción explícita que conserva auditoría.

### Backups

La determinación del backup más reciente usa la fecha del manifiesto, no el orden lexicográfico del nombre del ZIP.

### Intercambio offline

El sistema conserva el linaje de bundles aplicados aunque el estado local haya divergido por resoluciones humanas. También normaliza eventos encadenados y rechaza bundles incompletos con objetos OCR sin páginas padre compartidas.

### Índices

El índice semántico se invalida por cambios en su corpus textual, no por alteraciones ajenas como la creación de alias. La reidentificación de copias recrea los directorios operativos necesarios.

## Decisión sobre compatibilidad retrospectiva

Los datos de la prueba piloto fueron considerados descartables. 0.33.1 no incorpora una migración de reparación para reconstruir vínculos perdidos en bases ya afectadas. La prioridad fue impedir que el defecto vuelva a producirse y dejarlo cubierto por pruebas.

## Pendientes posteriores a 0.33.1

Resueltos en 0.34.0:

- previsualización y comparación de corridas OCR candidatas antes de volverlas canónicas, con adopción segura o conservación explícita de ediciones humanas;
- historial cronológico integrado de página y objeto, con estado OCR inicial, operaciones, autoría y cambios de selección.

Continúan pendientes:

- Evaluar calidad automática de imagen, deskew, dewarp, OCR regional, Surya y CUDA sobre un corpus mayor.
- Mejorar fragmentación, orden de lectura, columnas, sellos, firmas, ilustraciones y ruido geométrico.
- Evitar colisiones de textos y aristas paralelas en el grafo.
- Agregar eliminación o archivo de perfiles de exportación y una notificación inequívoca al materializar archivos.
- Limpiar o archivar alertas históricas y referencias huérfanas.
- Calibrar la búsqueda semántica con consultas positivas, negativas y ambiguas.
- Incorporar identificación automática de entidades únicamente como sugerencias revisables.
