# Archive Workbench

**Archive Workbench** es una aplicación local para organizar, procesar, revisar, anotar, buscar y exportar documentación archivística digitalizada.

Está pensada especialmente para equipos de archivos, bibliotecas, ciencias sociales, historia, antropología, análisis del discurso y humanidades digitales que trabajan con PDF, TIFF e imágenes escaneadas.

Los documentos y la base de datos permanecen en la computadora del equipo: la aplicación no necesita subir el corpus a un servicio externo.

**Versión actual:** 0.33.1 — primera versión pública funcional.

## Qué permite hacer

Archive Workbench reúne en una misma interfaz:

- catálogo y descripción archivística jerárquica;
- registro de archivos originales sin modificarlos;
- preparación de derivados para procesamiento;
- extracción de texto y OCR versionados;
- selección humana de la mejor extracción por página;
- revisión del texto junto con la imagen y sus regiones;
- edición, anotaciones e historial;
- búsqueda literal y búsqueda semántica opcional;
- entidades, alias, menciones y relaciones;
- grafo documental;
- exportaciones reproducibles en CSV y JSONL;
- asignación de tareas entre integrantes del equipo;
- intercambio offline de cambios entre distintas copias;
- backups y pruebas de recuperación.

La extracción automática siempre produce candidatos revisables. La aplicación no reemplaza la lectura ni las decisiones del equipo de investigación.

## Estado del proyecto

Esta es la primera versión pública y funcional. El circuito completo fue probado con un corpus piloto, pero el proyecto todavía se encuentra en etapa de estabilización.

La instalación actual requiere ejecutar algunos comandos en una terminal. Está prevista una **imagen Docker** para una próxima versión, con el objetivo de simplificar la instalación en equipos sin experiencia técnica.

La calidad del OCR depende mucho del estado y la disposición gráfica de cada documento. La búsqueda semántica es experimental y sus resultados deben evaluarse críticamente.

## Requisitos actuales

Las instrucciones siguientes están pensadas para **Ubuntu o una distribución Linux reciente**.

Se necesita:

- Python 3.11 o posterior;
- conexión a internet durante la instalación;
- Tesseract OCR y el idioma español;
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
  tesseract-ocr-spa
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

La primera instalación puede demorar varios minutos. Algunas funciones pueden descargar modelos la primera vez que se utilizan.

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

Prepará la base local:

```bash
archive-workbench db-upgrade mi_proyecto
```

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
2. **Procesamiento:** prepará derivados, ejecutá extracciones y seleccioná candidatos.
3. **Revisión:** contrastá imagen y texto, corregí objetos y aprobá páginas.
4. **Búsqueda y Entidades:** explorá el corpus revisado y vinculá menciones.
5. **Exportar:** generá corpus reproducibles en CSV o JSONL.
6. **Administración:** revisá el estado operativo y creá backups.

Los originales se conservan sin modificaciones. Las extracciones, correcciones y decisiones quedan separadas y versionadas.

## Documentación

La carpeta [`docs/`](docs/) contiene:

- [Diseño y plan de implementación](docs/DISEÑO_Y_PLAN_DE_IMPLEMENTACION.md)
- [Guía de la prueba piloto](docs/GUIA_PRUEBA_PILOTO_ARCHIVE_WORKBENCH.md)
- [Cierre funcional de la versión 0.33.1](docs/PRUEBA_PILOTO_Y_CIERRE_0.33.1.md)
- [Pendientes y mejoras](docs/PENDIENTES_Y_MEJORAS_ARCHIVE_WORKBENCH_PILOTO_FINAL_20260727_203735.md)
- [Registro completo de la prueba piloto](docs/REGISTRO_PRUEBA_PILOTO_ARCHIVE_WORKBENCH_CIERRE_FINAL_20260727_203735.md)

Los cambios entre versiones se registran en [`CHANGELOG.md`](CHANGELOG.md).

## Desarrollo y pruebas

Para instalar también las herramientas de desarrollo:

```bash
pip install -e ".[dev,extraction,streamlit,semantic,tiff]"
pytest
```

La versión 0.33.1 cuenta con 171 pruebas automatizadas.

## Licencia y cita

Archive Workbench es software libre distribuido bajo la **GNU Affero General Public License v3.0 o posterior (`AGPL-3.0-or-later`)**. Puede utilizarse, estudiarse, modificarse y redistribuirse conforme a los términos de esa licencia.

Las versiones modificadas que se distribuyan o se ofrezcan como servicio a través de una red deben mantener la misma licencia, publicar su código fuente correspondiente y conservar los avisos de autoría y licencia.

El desarrollo fue realizado por **Alex Colman** en el marco del **Grupo de Investigación en Archivos de la Represión (GIAR)**.

Cuando Archive Workbench sea utilizado en una investigación, publicación, informe, actividad docente o desarrollo derivado, solicitamos citar:

> Colman, Alex, y Grupo de Investigación en Archivos de la Represión (GIAR). 2026. *Archive Workbench* (versión 0.33.1) [software]. https://github.com/alexdcolman/archive-workbench

El archivo [`CITATION.cff`](CITATION.cff) contiene los metadatos de cita reconocidos por GitHub y por distintos gestores bibliográficos.
