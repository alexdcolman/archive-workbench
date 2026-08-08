# Archive Workbench

**Archive Workbench** es una aplicación local para organizar, procesar, revisar, anotar, buscar y exportar documentación archivística digitalizada.

Está pensada especialmente para equipos de archivos, bibliotecas, ciencias sociales, historia, antropología, análisis del discurso y humanidades digitales que trabajan con PDF, TIFF e imágenes escaneadas.

Los documentos y la base de datos permanecen en la computadora del equipo: la aplicación no necesita subir el corpus a un servicio externo.

**Versión actual:** 0.88.1 — corrige la primera importación de catálogo en proyectos recién inicializados, manteniendo la simulación no destructiva y la aplicación transaccional. Conserva la exportación **Exportar texto e imágenes (ZIP)** cerrada en 0.88.0.

## Qué permite hacer

Archive Workbench reúne en una misma interfaz:

- catálogo y descripción archivística jerárquica;
- plantillas XLSX distribuibles con estructura configurable, simulación y aplicación transaccional;
- registro de archivos originales sin modificarlos;
- registro local de audio y video con metadatos técnicos, reproducción integrada y transcripción temporal revisable;
- evaluación reproducible de corridas audiovisuales con tiempo, factor tiempo-real, memoria observada y segmentación, junto con un editor continuo y revisión sincronizada: el video/audio acompaña la transcripción, permite saltar por texto y registrar hablantes o anotaciones desde el tiempo actual sin perder los anclajes temporales internos;
- preparación versionada de derivados para OCR, con opciones conservadoras de autocontraste, Otsu, reducción de ruido, orientación, deskew, dewarp y eliminación controlada de líneas;
- extracción de texto y OCR versionados;
- OCR regional visual sobre páginas preparadas, con zonas OCR o manuales y clasificación documental;
- benchmark reproducible Tesseract/Docling/Surya con verdad terreno, CER/WER y salidas trazables;
- Surya como backend OCR/layout preferido cuando está disponible, siempre como candidato revisable;
- fallback automático a Docling/Tesseract si Surya no está instalado o una corrida falla;
- comparación y selección humana de extracciones por página;
- control automático de contraste, desenfoque probable, ruido, fragmentación y solapamiento;
- adopción segura de una nueva candidata mediante rebase de correcciones, conflictos textuales y menciones;
- revisión del texto junto con la imagen y sus regiones;
- confirmación explícita de casilleros, estados y grupos de formulario con historial y exportación;
- propuestas revisables de columnas y orden de lectura, con diagnóstico de fragmentación y duplicaciones;
- edición, anotaciones y cronología integrada por página;
- búsqueda literal y búsqueda semántica opcional;
- entidades, alias, menciones y relaciones, con importación JSON simulable;
- entidades productoras y gestoras vinculadas al catálogo con período, evidencia, procedencia e historial;
- descubrimiento abierto reproducible con candidatos, decisiones humanas append-only y evaluación por familia;
- grafo documental con capas separadas para jerarquía, documentos, partes, menciones, relaciones analíticas, productores y gestores;
- exportaciones reproducibles en CSV y JSONL;
- exportación conjunta de texto e imágenes en ZIP, con páginas, recortes regionales, figuras, contexto textual estructurado y manifiesto verificable;
- asignación de tareas entre integrantes del equipo;
- intercambio offline de cambios entre distintas copias;
- transporte opcional de esos paquetes mediante Google Drive, con selección por archivo, verificación local y simulación antes de cualquier aplicación;
- copias de seguridad y pruebas de recuperación.

La extracción automática siempre produce candidatos revisables. La aplicación no reemplaza la lectura ni las decisiones del equipo de investigación.

Desde 0.87.0, Google Drive puede usarse únicamente para transportar paquetes ZIP de intercambio. Cada copia conserva su propia base SQLite local: Drive no sincroniza `project_data`, no habilita edición simultánea de la base y una descarga nunca aplica cambios automáticamente. La recepción conserva la inspección del manifiesto y el dry-run ya usados por el intercambio local.

## Estado del proyecto

El estado operativo se mantiene en una sola lista: [`docs/operativos/PENDIENTES_ACTIVOS.md`](docs/operativos/PENDIENTES_ACTIVOS.md). Las funciones cerradas se registran por separado en [`IMPLEMENTACIONES_REALIZADAS.md`](docs/operativos/IMPLEMENTACIONES_REALIZADAS.md).

Esta es la primera versión pública y funcional. El circuito completo fue probado con un corpus piloto, pero el proyecto todavía se encuentra en etapa de estabilización.

La instalación actual requiere ejecutar algunos comandos en una terminal. Está prevista una **imagen Docker** para una próxima versión, con el objetivo de simplificar la instalación en equipos sin experiencia técnica.

La calidad del OCR depende mucho del estado y la disposición gráfica de cada documento. La búsqueda semántica es experimental y sus resultados deben evaluarse críticamente.

Los análisis automáticos usan únicamente páginas aprobadas de manera predeterminada. Toda ampliación exige confirmación y fundamento, y queda registrada en una auditoría append-only consultable desde la interfaz o con `analysis-quality-audit`.
Las exportaciones y las operaciones semánticas solo se ejecutan cuando la configuración funcional vigente del perfil coincide con una autorización persistida; los perfiles anteriores a 0.64.0 deben guardarse nuevamente antes de su próximo uso.

## Requisitos actuales

Las instrucciones siguientes están pensadas para **Ubuntu o una distribución Linux reciente**.

Se necesita:

- Python 3.11 o posterior;
- conexión a internet durante la instalación;
- Tesseract OCR y el idioma español;
- FFmpeg/FFprobe para las funciones audiovisuales de AV-01 y AV-02;
- espacio suficiente para los documentos, derivados y modelos opcionales.

Una placa gráfica no es obligatoria. Puede acelerar algunas funciones, pero Archive Workbench también funciona con CPU.

Instalá los requisitos del sistema:

```bash
sudo apt update
sudo apt install -y \
  git \
  python3 \
  python3-venv \
  python3-pip \
  tesseract-ocr \
  tesseract-ocr-spa \
  ffmpeg
```

## Descargar Archive Workbench

### Opción sencilla: descargar el ZIP

En esta página de GitHub:

1. Pulsá el botón verde **Code**.
2. Elegí **Download ZIP**.
3. Descomprimí el archivo.
4. Abrí una terminal dentro de la carpeta descomprimida.

En Ubuntu suele poder hacerse con clic derecho sobre la carpeta y **Abrir en una terminal**.

### Opción con Git

```bash
git clone https://github.com/alexdcolman/archive-workbench.git
cd archive-workbench
```

## Instalación

Dentro de la carpeta de Archive Workbench, ejecutá:

```bash
python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
pip install -e ".[extraction,streamlit,tiff]"
```

La búsqueda semántica es opcional. Para agregarla:

```bash
pip install -e ".[semantic]"
```

La incorporación autorizada desde YouTube y otras plataformas es opcional:

```bash
pip install -e ".[platform]"
```

Este extra instala `yt-dlp` con sus componentes recomendados para YouTube, incluido Deno. Los archivos incorporados entran después al mismo circuito audiovisual local de AV-01.

Surya OCR es el backend preferido desde 0.38.0, pero sigue siendo opcional: si no está disponible, el perfil principal usa automáticamente el fallback Docling/Tesseract. Se instala en un runtime separado para no modificar Pillow, Torch ni Transformers del entorno principal:

```bash
./scripts/install_surya_runtime.sh --dry-run
./scripts/install_surya_runtime.sh
```

El script crea `.venv-surya`, instala `surya-ocr==0.22.1`, ejecuta `pip check` y deja disponible `.venv-surya/bin/surya_ocr`. En equipos NVIDIA, el perfil validado usa el VLM mediante vLLM/Docker y mantiene los modelos auxiliares de Torch en CPU.

El servidor vLLM queda activo entre corridas para evitar repetir la carga y el calentamiento del modelo. Podés consultar su estado y liberar la VRAM al terminar:

```bash
archive-workbench surya-server-status
archive-workbench surya-server-stop
```

Para comparar los tres motores contra una transcripción humana, prepará archivos `ground_truth/ocr/<source_key>/page_NNNN.txt` y usá:

```bash
archive-workbench ocr-benchmark-truth-doctor mi_proyecto
archive-workbench ocr-benchmark-truth mi_proyecto \
  --source-key DOCUMENTO \
  --page 1
```

El benchmark calcula CER/WER y conserva perfiles, versiones, tiempos, textos y salidas crudas. No cambia la selección canónica. La referencia está en [`docs/referencia/BENCHMARK_OCR_VERDAD_TERRENO.md`](docs/referencia/BENCHMARK_OCR_VERDAD_TERRENO.md).

La primera instalación puede demorar varios minutos. Algunas funciones pueden descargar modelos la primera vez que se utilizan.

Los proyectos ya existentes conservan sus perfiles para no sobrescribir personalizaciones. Para adoptar explícitamente la política preferida de 0.38.0, respaldá sus perfiles y copiá `extraction.yaml`, `extraction_surya_es.yaml` y `extraction_docling_es.yaml` desde la carpeta `config/` de la aplicación hacia la carpeta `config/` de cada proyecto.

## Crear el primer proyecto

Cada corpus se guarda en una carpeta de proyecto separada. En este ejemplo se llama `mi_proyecto`:

```bash
archive-workbench init-project mi_proyecto

cp config/decisions.template.yaml \
  mi_proyecto/config/decisions.yaml

cp config/extraction.template.yaml \
  mi_proyecto/config/extraction.yaml
```

Antes de comenzar, abrí este archivo con un editor de texto:

```text
mi_proyecto/config/decisions.yaml
```

Al principio del archivo, reemplazá `project_name` y `project_id` por el nombre y un identificador breve de tu proyecto. No hace falta modificar toda la configuración para realizar una primera exploración.

Prepará la base local. Las migraciones solo se ejecutan mediante este comando explícito:

```bash
archive-workbench db-upgrade mi_proyecto
```

Los demás comandos nunca migran la base de forma implícita. Si la revisión es anterior, la aplicación se detiene y explica que debe ejecutarse `db-upgrade`.

## Abrir la aplicación

Cada vez que vuelvas a trabajar, entrá en la carpeta del programa, activá el entorno y abrí la interfaz:

```bash
source .venv/bin/activate
archive-workbench review-app mi_proyecto
```

La aplicación abrirá una página en el navegador. Si no se abre automáticamente, visitá:

```text
http://127.0.0.1:8501
```

Para detenerla, volvé a la terminal y presioná `Ctrl+C`.

## Primer recorrido recomendado

Dentro de la interfaz:

1. **Catálogo:** definí la estructura archivística y registrá los archivos.
2. **Procesamiento:** prepará derivados, ejecutá extracciones, evaluá su calidad y seleccioná candidatos.
3. **Revisión:** contrastá imagen y texto, corregí objetos y aprobá páginas.
4. **Búsqueda y Entidades:** explorá el corpus revisado y vinculá menciones.
5. **Exportar:** generá corpus reproducibles en CSV o JSONL.
6. **Administrar y recuperar:** revisá el estado operativo y creá copias de seguridad.

Los originales se conservan sin modificaciones. Las extracciones, correcciones y decisiones quedan separadas y versionadas.

### Plantillas distribuibles de catálogo

Desde **Catálogo documental → Importar o exportar una plantilla XLSX** se puede descargar una plantilla vacía o el catálogo actual, simular una importación y aplicarla únicamente después de una confirmación explícita. La estructura configurada en la plantilla puede ser más estricta que el proyecto, pero nunca ampliar relaciones padre–hijo no autorizadas.

También están disponibles los comandos:

```bash
archive-workbench catalog-template-export project_data plantilla.xlsx --empty
archive-workbench catalog-template-validate project_data plantilla.xlsx --output informe.json
archive-workbench catalog-template-import project_data plantilla.xlsx
archive-workbench catalog-template-import project_data plantilla.xlsx --apply --confirm IMPORTAR --changed-by Alex
```

La primera plantilla pública de prueba se incluye en `examples/plantilla_catalogo_dippba.xlsx`. Conserva fuentes y advertencias sobre ramas parciales; no debe tratarse como descripción archivística definitiva.

### Productores, gestores y mapa archivístico

En la ficha de cada unidad, la sección **Productores y gestión** vincula autoridades existentes mediante roles controlados. Un cambio de gestión se registra como otro vínculo temporal y conserva el historial anterior.

El **Mapa de relaciones** distingue autoridades, unidades archivísticas, documentos y partes internas. Las capas de jerarquía, pertenencia, menciones, relaciones analíticas, productores y gestores pueden filtrarse por separado, con foco, profundidad, niveles archivísticos y límite de nodos. Cada arista muestra una procedencia explicable.

Los proyectos anteriores deben actualizar explícitamente su base mediante `archive-workbench db-upgrade` después de crear y comprobar un backup. La revisión vigente es `0041_catalog_authority_roles_graph_layers`.

### Diccionarios de autoridades y relaciones

Desde **Entidades y menciones → Importar diccionario** se puede descargar un ejemplo y el esquema JSON `1.0`, simular un diccionario externo y aplicarlo con confirmación explícita. La importación detecta coincidencias por nombres y alias, no sobrescribe fichas existentes y exige evidencia para cada relación.

```bash
archive-workbench authority-dictionary-schema authority_dictionary.schema.json
archive-workbench authority-dictionary-validate project_data diccionario.json --output informe.json
archive-workbench authority-dictionary-import project_data diccionario.json
archive-workbench authority-dictionary-import project_data diccionario.json --apply --confirm IMPORTAR --changed-by Alex
```

El formato completo está documentado en [`docs/referencia/IMPORTACION_DICCIONARIOS_DISC_02.md`](docs/referencia/IMPORTACION_DICCIONARIOS_DISC_02.md). Se incluyen `config/authority_dictionaries/authority_dictionary.schema.json` y `examples/diccionario_autoridades_ejemplo.json`.

## Documentación

La raíz de [`docs/`](docs/) contiene un único mapa breve: [Historial de cambios y mapa documental](docs/HISTORIAL_DE_CAMBIOS.md).

Documentación vigente:

- [Pendientes activos](docs/operativos/PENDIENTES_ACTIVOS.md)
- [Implementaciones realizadas](docs/operativos/IMPLEMENTACIONES_REALIZADAS.md)
- [Actualización actual](docs/operativos/ACTUALIZACION_ACTUAL.md)
- [Estrategia de pruebas](docs/operativos/ESTRATEGIA_DE_PRUEBAS.md)
- [Guía de prueba piloto](docs/operativos/GUIA_PRUEBA_PILOTO.md)
- [Hoja de ruta pre-release](docs/operativos/HOJA_DE_RUTA_PRE_RELEASE.md)
- [Arquitectura y modelo actual](docs/referencia/ARQUITECTURA_Y_MODELO_ACTUAL.md)
- [Proyecto paralelo GIAR](docs/referencia/PROYECTO_PARALELO_GIAR.md)

La documentación cerrada y las guías de versiones anteriores están separadas en [`docs/historico/`](docs/historico/). Los cambios técnicos exhaustivos se registran en [`CHANGELOG.md`](CHANGELOG.md).

## Desarrollo y pruebas

Para instalar también las herramientas de desarrollo:

```bash
pip install -e ".[dev,extraction,streamlit,semantic,tiff,discovery,audiovisual,platform]"
pytest
```

La versión 0.85.0 mantiene AV-01 y cierra AV-02 para incorporar de forma autorizada audio o video desde plataformas compatibles. La validación real con YouTube confirmó descarga, reproducción y procedencia trazable sin iniciar transcripción automáticamente; los campos obligatorios del formulario fallan con mensajes comprensibles y no exponen errores internos. La versión 0.86.0 cierra AV-03 después de una prueba real sobre `RememorArte Horacio BAU`: reemplaza la edición segmento por segmento por un editor continuo que conserva los anclajes temporales, agrega marcas estructuradas de hablante/anotación mediante `0046_audiovisual_timeline_annotations` y ofrece revisión sincronizada junto al reproductor. La evaluación usa siempre las salidas automáticas originales y sólo publica CER/WER cuando las fronteras temporales son comparables; con otra segmentación muestra el contexto original sin fabricar una puntuación. En la prueba realizada, el perfil `large-v3` + CUDA `float16` produjo una transcripción cualitativamente superior a `small` + CPU `int8`, aunque con mayor coste de ejecución y todavía con errores que requieren revisión humana. Ambas salidas completas permanecen visibles y descargables. AV-01, AV-02, AV-03 y `OCR-01` quedan cerrados.

## Licencia y cita

Archive Workbench es software libre distribuido bajo la **GNU Affero General Public License v3.0 o posterior (`AGPL-3.0-or-later`)**. Puede utilizarse, estudiarse, modificarse y redistribuirse conforme a los términos de esa licencia.

Las versiones modificadas que se distribuyan o se ofrezcan como servicio a través de una red deben mantener la misma licencia, publicar su código fuente correspondiente y conservar los avisos de autoría y licencia.

El desarrollo fue realizado por **Alex Colman** en el marco del **Grupo de Investigación en Archivos de la Represión (GIAR)**.

Cuando Archive Workbench sea utilizado en una investigación, publicación, informe, actividad docente o desarrollo derivado, solicitamos citar:

> Colman, Alex, y Grupo de Investigación en Archivos de la Represión (GIAR). 2026. *Archive Workbench* (versión 0.85.0) [software]. https://github.com/alexdcolman/archive-workbench

El archivo [`CITATION.cff`](CITATION.cff) contiene los metadatos de cita reconocidos por GitHub y por distintos gestores bibliográficos.
