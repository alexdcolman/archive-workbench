# Proyecto paralelo vinculado — Grupo de Investigación en Archivos de la Represión

**ID de planificación:** `GIAR-01`
**Relación con Archive Workbench:** proyecto separado, con una base de proyecto persistente de Archive Workbench como fuente estructurada
**Publicación prevista:** repositorio y GitHub Pages en una cuenta propia del grupo

## 1. Propósito

Construir una base de conocimiento y un sitio público del Grupo de Investigación en Archivos de la Represión a partir de publicaciones, informes de proyectos, materiales archivísticos y resultados producidos por el equipo. Archive Workbench administrará la procedencia, las autoridades, las relaciones, las referencias documentales y los vínculos con archivos, fondos, secciones y unidades estudiadas.

El proyecto no debe mezclarse con bases descartables de validación. Cada lote incorporado debe conservar archivo fuente, checksum, procedencia, fecha de incorporación y decisiones de revisión.

## 2. Corpus y carga inicial

Alex entregará lotes de:

- publicaciones del equipo;
- informes de proyectos financiados;
- materiales complementarios necesarios para verificar o ampliar la información;
- enlaces y metadatos bibliográficos;
- imágenes autorizadas de integrantes cuando se preparen las páginas personales.

La revisión deberá detectar temas, entidades, conceptos, publicaciones y referencias archivísticas faltantes o inconsistentes, sin completar silenciosamente datos ausentes.

## 3. Base relacional de investigación

La primera fase construirá relaciones entre:

- integrantes e investigadores;
- publicaciones e informes;
- proyectos financiados;
- entidades estudiadas con el nivel de especificidad documentado, por ejemplo `DIPPBA Bahía Blanca` cuando el trabajo no se refiere a la DIPPBA en general;
- alias y denominaciones históricas;
- clases revisables de entidad, por ejemplo servicio de inteligencia, grupo musical, organización estudiantil o institución archivística;
- relaciones con evidencia, por ejemplo `DIPPBA investigó a estudiantes secundarios`;
- archivos, fondos, secciones, series, legajos y otras unidades documentales citadas;
- fragmentos o páginas concretas de las publicaciones que sostienen cada afirmación.

Las clases y relaciones se ajustarán durante la revisión del corpus. Una coincidencia nominal no implica identidad y ninguna relación analítica se creará sin evidencia y procedencia.

## 4. Páginas personales

Cada integrante tendrá una página con:

- fotografía autorizada;
- inscripción institucional;
- biografía breve;
- temas investigados;
- archivos, fondos, secciones y unidades estudiadas;
- conclusiones, hallazgos y aportes, vinculados a sus fuentes;
- proyectos en los que participó;
- publicaciones y enlaces provistos o revisados por el equipo.

Las páginas deben distinguir información institucional, síntesis editorial del sitio y afirmaciones derivadas de publicaciones.

## 5. Páginas temáticas

Se construirán páginas para grandes áreas de investigación, entre ellas teatro y artes del espectáculo, movimiento estudiantil y servicios de inteligencia. Cada página integrará trabajos de distintos miembros, explicará coincidencias y diferencias, y enlazará personas, publicaciones, conceptos, entidades y materiales de archivo.

## 6. Glosario conceptual

El glosario incluirá:

- conceptos centrales usados por el equipo;
- definiciones atribuidas a cada autor o publicación;
- variaciones conceptuales relevantes;
- conceptos producidos por las investigaciones del grupo;
- ejemplos y fuentes precisas.

No se unificarán definiciones diferentes si la variación tiene valor analítico.

## 7. Páginas de archivos y unidades documentales

Cada archivo, fondo, sección o unidad relevante tendrá una página que reúna:

- descripción y procedencia;
- estructura archivística conocida;
- tipos de materiales;
- integrantes que la estudiaron;
- publicaciones asociadas;
- temas, entidades y conceptos vinculados;
- enlaces a unidades catalogadas en Archive Workbench cuando existan.

## 8. Sitio público del GIAR

El sitio incluirá:

- presentación del grupo;
- proyectos financiados;
- páginas personales;
- páginas temáticas;
- glosario;
- páginas de archivos, fondos y secciones;
- publicaciones;
- mapa de relaciones construido a partir de la base del proyecto.

El grafo permitirá abrir páginas de personas, entidades, conceptos, publicaciones y unidades archivísticas. Los enlaces deben ser persistentes y no depender del nombre visible como identificador.

Antes de diseñar el sitio se crearán documentos propios de `POLITICA_SITIO_PUBLICO` y `LINEAMIENTOS_DE_DISENO_Y_ESCRITURA` dentro del repositorio del GIAR. Las políticas de Archive Workbench sirven como antecedente, pero no se copiarán sin adaptar el auditorio, la identidad y el contenido del grupo.

## 9. Relación con PILOT-01

La carga estructurada puede comenzar en paralelo con el piloto real. Los legajos y referencias DIPPBA o APM-Chubut incorporados al piloto podrán vincularse con publicaciones y miembros del equipo. La base GIAR será un proyecto separado y persistente para evitar mezclar resultados institucionales con pruebas técnicas descartables.

## 10. Fases previstas

1. Inventario, permisos y normalización bibliográfica.
2. Modelo de investigadores, publicaciones, entidades, relaciones y referencias archivísticas.
3. Carga revisada por lotes con evidencia.
4. Páginas personales, temáticas, conceptuales y archivísticas.
5. Grafo navegable y enlaces persistentes.
6. Diseño, validación editorial y publicación en GitHub Pages.

La implementación debe comenzar con un diseño explícito del esquema y de los contratos de importación. No se forzarán publicaciones, conceptos o perfiles personales dentro de tablas existentes si su semántica requiere entidades propias.
