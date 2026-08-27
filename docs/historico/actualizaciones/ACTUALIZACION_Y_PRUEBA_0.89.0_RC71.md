# Actualización actual - Archive Workbench 0.89.0 RC71

## Alcance de RC71

La recorrida manual posterior a RC70 deja verde la revisión transversal de complejidad y cierra `UX-02`. RC71 inicia `WEB-01`, la documentación pública previa a v1.0.

La candidata agrega un sitio HTML multipágina bajo `docs/`, preparado para GitHub Pages, con navegación estable y páginas de inicio, instalación, tutorial, catálogo, procesamiento, revisión, entidades, búsquedas, relaciones, audio y video, exportación, intercambio, resguardo, conceptos, referencia técnica y problemas frecuentes. Los diagramas SVG expresan el flujo de trabajo, la trazabilidad del texto, la arquitectura local y el intercambio entre copias. No son decorativos ni sustituyen capturas.

El README se reorganiza como puerta de entrada: presentación, diagrama del recorrido, instalación rápida, principios de trabajo, mapa de capacidades, límites, documentación y cita. La política documental se reconcilia para permitir archivos públicos de GitHub Pages en la raíz de `docs/` sin permitir documentos Markdown internos paralelos.

No se modifica la aplicación, SQLite ni `pilot_data`. Continúa `0047_authority_relation_profiles`. No hay migración.

`WEB-01` permanece **PARCIAL** hasta incorporar capturas reales y revisar la publicación final en GitHub Pages. Alex autorizó usar el corpus real ya existente como ejemplo para producir esas capturas.

## Actualización desde RC70

```bash
cd ~/projects/archive_app
source .venv/bin/activate
TMP_DIR="$(mktemp -d)"
unzip -q ~/Downloads/archive_workbench_v0.89.0_RC71.zip -d "$TMP_DIR"
python "$TMP_DIR/scripts/apply_candidate_update.py" --source "$TMP_DIR" --target ~/projects/archive_app
python -m pip install --no-build-isolation -e ".[dev,extraction,streamlit,semantic,tiff,discovery,audiovisual,platform]"
python -c "import archive_workbench; print(archive_workbench.__version__)"
archive-workbench db-status ~/projects/archive_app/pilot_data
```

Resultado esperado: versión de código `0.89.0` y revisión `0047_authority_relation_profiles`.

**No hay migración nueva entre RC70 y RC71. No ejecutar `db-upgrade`.**

## Gate automatizado focal

La suite completa corresponde exclusivamente a Alex. Para RC71 corresponde ejecutar en un solo bloque:

```bash
cd ~/projects/archive_app && source .venv/bin/activate && \
pytest -q \
  tests/test_documentation.py \
  tests/test_packaging.py && \
pytest --collect-only -q
```

## Guía de producción de capturas para WEB-01

Usar el mismo corpus y la misma versión de Archive Workbench durante toda la sesión. Antes de capturar, elegir un documento o unidad que pueda mostrarse públicamente y revisar que la pantalla no exponga datos personales innecesarios, rutas locales completas, tokens, identificadores de Drive ni materiales restringidos fuera del ejemplo autorizado.

Las capturas deben hacerse con una ventana de navegador suficientemente ancha para que la interfaz conserve su diseño normal. Evitar recortes tan cerrados que oculten el título de la sección o el documento activo. No agregar flechas o texto durante la captura: las anotaciones editoriales, si hacen falta, se incorporan después de conservar una copia original de la imagen.

### Captura 1 - Inicio

- Ruta: **Inicio**.
- Estado: proyecto ya abierto, sin diálogos ni tareas en ejecución.
- Mostrar: título de Inicio, identidad del proyecto y las orientaciones principales de estado/recorrido.
- Evitar: rutas locales completas o avisos excepcionales que no representen el uso normal.
- Ruta final prevista: `docs/assets/screenshots/01-inicio.png`.
- Uso: `index.html` y README.

### Captura 2 - Catálogo

- Ruta: **Catálogo > Unidades del catálogo**.
- Estado: seleccionar una unidad representativa de Colección, Fondo o Serie que tenga alguna descripción y vínculos visibles.
- Mostrar: árbol de catálogo, ficha de la unidad y su tipo semántico. Si el panel de productores/gestión contiene datos publicables, puede quedar visible; si no, dejarlo cerrado.
- Ruta final prevista: `docs/assets/screenshots/02-catalogo.png`.
- Uso: `catalogo.html` y tutorial.

### Captura 3 - Procesar documentos

- Ruta: **Procesar documentos > Elegir texto para revisar**.
- Estado: documento con al menos dos fuentes/extracciones comparables ya existentes. No ejecutar OCR nuevo.
- Mostrar: documento y página, opciones de texto disponibles y la decisión de selección, sin abrir paneles técnicos.
- Ruta final prevista: `docs/assets/screenshots/03-procesamiento.png`.
- Uso: `procesamiento.html` y tutorial.

### Captura 4 - Revisar documentos

- Ruta: **Revisar documentos > Corregir o agregar texto**.
- Estado: página con imagen y varios bloques ya extraídos.
- Mostrar: imagen con recuadros, bloque activo y editor de texto. Elegir un bloque cuyo contenido pueda publicarse.
- Ruta final prevista: `docs/assets/screenshots/04-revision.png`.
- Uso: `revision.html`, tutorial y README.

### Captura 5 - Búsqueda textual

- Ruta: **Búsqueda textual > Documentos revisados**.
- Estado: consulta breve que produzca varios resultados claros.
- Mostrar: consulta, cantidad de resultados y algunas tarjetas o concordancias. No hace falta abrir filtros secundarios si no aportan a la explicación.
- Ruta final prevista: `docs/assets/screenshots/05-busqueda-textual.png`.
- Uso: `busquedas.html`.

### Captura 6 - Entidades y menciones

- Ruta: **Entidades y menciones**.
- Estado: abrir una entidad representativa con al menos una mención vinculada y, si es publicable, alguna relación.
- Mostrar: identidad de la entidad y evidencia de una mención. Evitar una ficha sobrecargada sólo para mostrar cantidad de campos.
- Ruta final prevista: `docs/assets/screenshots/06-entidad.png`.
- Uso: `entidades.html` y tutorial.

### Captura 7 - Buscar nuevas entidades

- Ruta: **Entidades y menciones > Buscar nuevas entidades**.
- Estado: corrida nueva con reglas vigentes y referencias ya producidas.
- Mostrar: versión de reglas, conteos de referencias y una muestra de candidatos que resulte comprensible. Mantener el límite visible en 500 o menos.
- Ruta final prevista: `docs/assets/screenshots/07-descubrimiento.png`.
- Uso: `entidades.html`.

### Captura 8 - Explorar relaciones

- Ruta: **Explorar relaciones**.
- Estado: vista general con capas estructurales ocultas si eso produce un mapa más legible.
- Mostrar: un conjunto pequeño de nodos y aristas con etiquetas legibles; no hace falta abrir Configurar mapa.
- Ruta final prevista: `docs/assets/screenshots/08-grafo.png`.
- Uso: `relaciones.html` y README.

### Captura 9 - Audio y video

- Ruta: **Audio y video > Transcribir y revisar**.
- Estado: medio ya incorporado y transcripción existente.
- Mostrar: reproductor, tramo de transcripción y sincronización temporal. Elegir un fragmento autorizado para publicación.
- Ruta final prevista: `docs/assets/screenshots/09-audiovisual.png`.
- Uso: `audiovisual.html`.

### Captura 10 - Exportar corpus

- Ruta: **Exportar corpus**.
- Estado: configuración ya existente o una vista previa que no requiera crear una exportación nueva.
- Mostrar: etapas de configuración/revisión y una muestra breve del alcance. Evitar historiales largos o rutas locales.
- Ruta final prevista: `docs/assets/screenshots/10-exportacion.png`.
- Uso: `exportacion.html`.

### Captura 11 - Intercambiar cambios

- Ruta: **Intercambiar cambios**.
- Estado: pantalla normal sin conflicto activo.
- Mostrar: tareas principales para preparar una copia, enviar o recibir cambios. No mostrar nombres de archivos privados, rutas de Drive ni identificadores de contraparte innecesarios.
- Ruta final prevista: `docs/assets/screenshots/11-intercambio.png`.
- Uso: `intercambio.html`.

### Captura 12 - Administrar y recuperar

- Ruta: **Administrar y recuperar > Integridad**.
- Estado: proyecto en estado normal.
- Mostrar: resumen comprensible de integridad y accesos hacia backups/recuperación, sin abrir detalles técnicos extensos.
- Ruta final prevista: `docs/assets/screenshots/12-resguardo.png`.
- Uso: `resguardo.html`.

### Nombres, formato y control final

Guardar las imágenes como PNG con los nombres indicados. No redimensionarlas antes de conservar el original de captura. Después de reunirlas, revisar en conjunto que:

1. todas correspondan a RC71 o a la misma versión de interfaz que finalmente se publique;
2. el corpus y los estados sean coherentes entre capturas;
3. no haya datos sensibles o rutas personales innecesarias;
4. cada captura conserve suficiente contexto para identificar la sección;
5. las imágenes no dependan sólo del color para entender la acción principal.

La siguiente candidata incorporará estas capturas, agregará sus textos alternativos y pies de figura, y realizará la revisión final de enlaces/metadatos antes de cerrar `WEB-01`.
