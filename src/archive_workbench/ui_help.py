from __future__ import annotations

# Texto de orientación mostrado mediante el icono de información contextual.
# Esta tabla concentra la redacción de ayuda de secciones, pestañas y tareas
# principales para evitar que una simplificación futura elimine la orientación
# o vuelva a esconder su disparador visual.

SECTION_HELP = {
    "Abrir o crear un proyecto": (
        "Permite elegir un proyecto existente de Archive Workbench o crear uno nuevo. "
        "Un proyecto reúne en una misma carpeta el catálogo, los archivos vinculados, "
        "los textos y transcripciones, las revisiones, la configuración y las copias de seguridad."
    ),
    "Inicio": (
        "Muestra el estado general del proyecto y señala qué etapas están listas, cuáles requieren "
        "atención y cuáles todavía están pendientes. Cada estado permite abrir directamente la sección "
        "correspondiente cuando hace falta continuar o resolver un problema."
    ),
    "Catálogo": (
        "Permite organizar el contexto de custodia y la estructura documental del proyecto y vincular los archivos digitales con "
        "las unidades del catálogo a las que corresponden. Desde esta sección se describen las unidades, su relación con niveles superiores, "
        "sus productores y responsables de gestión, y los archivos asociados."
    ),
    "Audio y video": (
        "Permite incorporar archivos de audio o video al proyecto y trabajar con sus transcripciones. "
        "Los materiales locales y los incorporados desde plataformas usan el mismo registro canónico vinculado con el catálogo; "
        "la revisión conserva versiones, correcciones, hablantes, anotaciones temporales y evaluación del reconocimiento."
    ),
    "Procesar documentos": (
        "Permite preparar las imágenes de los documentos, extraer su texto y decidir qué extracción completa "
        "se usará como base para la revisión. También permite volver a leer zonas concretas de una página cuando "
        "la extracción general no alcanza."
    ),
    "Organizar trabajo": (
        "Permite distribuir tareas de procesamiento y revisión entre las personas que trabajan en el proyecto y "
        "registrar el estado de cada asignación. También permite organizar una segunda revisión independiente del trabajo ya realizado."
    ),
    "Revisar documentos": (
        "Permite comparar la imagen de cada página con el texto editable, corregir el contenido y registrar decisiones "
        "sobre orden, estructura, formularios, anotaciones y menciones de entidades. Los cambios crean revisiones nuevas y conservan el historial anterior."
    ),
    "Búsqueda textual": (
        "Permite encontrar palabras, frases o partes de palabras dentro de los documentos revisados y de las "
        "transcripciones de audio y video. En documentos, los resultados pueden compararse como concordancias, "
        "resumirse por distribución y recorrerse en su contexto sin perder la consulta ni sus filtros."
    ),
    "Búsqueda semántica": (
        "Permite encontrar fragmentos relacionados por significado aunque no contengan exactamente las mismas palabras. "
        "La búsqueda utiliza un índice local construido a partir del contenido elegido y cada resultado debe revisarse en su contexto documental."
    ),
    "Entidades y menciones": (
        "Permite registrar referentes del corpus, como personas, organizaciones, lugares, acontecimientos u obras, y "
        "vincular con esas entidades las referencias concretas que aparecen en los textos. Las fichas de entidades se reutilizan en todo el proyecto."
    ),
    "Explorar relaciones": (
        "Permite visualizar en un mapa las conexiones registradas entre entidades, unidades archivísticas, documentos y "
        "partes internas de documentos. El mapa puede mostrar por separado relaciones estructurales, roles archivísticos, menciones y relaciones analíticas."
    ),
    "Exportar corpus": (
        "Permite preparar archivos con los textos y datos revisados del proyecto para analizarlos o utilizarlos fuera de "
        "Archive Workbench. Las exportaciones quedan registradas para poder reconstruir qué contenido y qué configuración produjo cada archivo."
    ),
    "Intercambiar cambios": (
        "Permite compartir trabajo entre distintas copias del mismo proyecto sin mantener una base de datos abierta en común. "
        "Archive Workbench compara los estados de las copias, permite revisar diferencias antes de incorporarlas y conserva registros de cada intercambio."
    ),
    "Administrar y recuperar": (
        "Permite comprobar el estado técnico del proyecto, crear y verificar copias de seguridad y comprobar que esas copias "
        "puedan recuperarse. También conserva el registro de las autorizaciones utilizadas por análisis automáticos."
    ),
}

TAB_HELP = {
    "launcher_tabs": {
        "Abrir un proyecto existente": (
            "Permite abrir una carpeta que ya contiene un proyecto de Archive Workbench. La aplicación comprueba que la carpeta tenga "
            "la configuración y la base de datos necesarias antes de abrirla."
        ),
        "Crear un proyecto nuevo": (
            "Permite crear la carpeta y la estructura inicial de un proyecto nuevo. Archive Workbench registra el nombre del proyecto, "
            "su identificador y la configuración inicial necesaria para comenzar a trabajar."
        ),
    },
    "catalog_detail_tabs": {
        "Descripción de la unidad": (
            "Permite revisar y modificar el título, el código de referencia y los demás datos descriptivos de la unidad archivística seleccionada."
        ),
        "Productores y responsables": (
            "Permite registrar qué personas u organizaciones produjeron la unidad archivística o tuvieron responsabilidad sobre su gestión. "
            "Cada rol puede conservar información sobre período, evidencia y procedencia."
        ),
        "Archivos vinculados": (
            "Muestra los archivos digitales relacionados con la unidad archivística seleccionada. Permite comprobar si las copias locales siguen "
            "disponibles, agregar nuevos vínculos y retirar vínculos incorrectos."
        ),
        "Ubicación y tipo": (
            "Permite revisar el tipo de unidad y su relación con el nivel superior del catálogo. Esa relación puede expresar contexto de custodia, "
            "jerarquía documental o ubicación física; un cambio mueve también la rama dependiente y queda registrado en el historial."
        ),
        "Historial de la unidad": (
            "Muestra las revisiones registradas para la unidad archivística seleccionada, incluidas modificaciones de descripción, cambios de tipo y movimientos dentro del catálogo."
        ),
    },
    "audiovisual_tabs": {
        "Incorporar audio o video": (
            "Permite agregar audio o video desde esta computadora o desde una plataforma web y vincular el material con una unidad del catálogo. "
            "Cuando proviene de una plataforma, se conserva la publicación remota y su agrupación externa separadas de la copia local; la incorporación no inicia una transcripción automáticamente."
        ),
        "Transcribir y revisar": (
            "Permite elegir un audio o video ya incorporado, reproducirlo, crear o seleccionar una versión de transcripción, corregir el texto y revisar hablantes, anotaciones y resultados del reconocimiento."
        ),
    },
    "processing_tabs": {
        "Estado": (
            "Muestra en qué punto del procesamiento se encuentra cada documento: disponibilidad del archivo, preparación de imágenes, extracción de texto, "
            "elección de una extracción y envío a revisión. La tabla puede buscarse por documento, ruta archivística o archivo."
        ),
        "Preparar / extraer": (
            "Permite ejecutar las dos etapas generales previas a la revisión: preparar las imágenes de las páginas y extraer texto de esas imágenes. "
            "Primero se elige la operación y después Archive Workbench muestra solamente las opciones necesarias para esa operación."
        ),
        "Leer una zona": (
            "Permite volver a reconocer una parte concreta de una página cuando el texto general no recuperó bien esa zona. Se eligen el documento y la página, "
            "se marca la zona sobre la imagen y Archive Workbench guarda la nueva lectura parcial sin reemplazar automáticamente el texto revisado."
        ),
        "Elegir texto": (
            "Permite comparar las extracciones completas disponibles para una página y elegir cuál se usará como base en Revisar documentos. La elección afecta "
            "la extracción completa de la página; las lecturas parciales realizadas en Leer una zona se administran por separado."
        ),
        "Corregir o agregar": (
            "Permite usar una lectura obtenida en Leer una zona dentro de una página que ya está en Revisar documentos. El texto recuperado puede reemplazar "
            "el contenido de un bloque existente o agregarse como un nuevo bloque cuando falta texto."
        ),
        "Enviar a revisión": (
            "Permite enviar a Revisar documentos las páginas que ya tienen una extracción completa elegida. Se puede trabajar con un documento o con varios documentos, "
            "y Archive Workbench incorpora las páginas al espacio editable sin modificar los archivos originales."
        ),
        "Historial": (
            "Muestra los trabajos ejecutados desde Procesar documentos y el resultado de cada uno. Permite revisar qué documentos y páginas fueron procesados, "
            "qué operación se ejecutó y, cuando hace falta, consultar los detalles técnicos."
        ),
    },
    "work_tabs": {
        "Estado de las tareas": (
            "Resume las asignaciones activas, vencidas, enviadas a revisión y destinadas a una segunda revisión. También permite consultar la carga de trabajo por persona y el avance de cada documento."
        ),
        "Crear y administrar asignaciones": (
            "Permite asignar un documento o un rango de páginas a una persona, indicar la tarea, prioridad y fecha límite, y después modificar el estado o la persona responsable de la asignación."
        ),
        "Tareas de la persona actual": (
            "Muestra las asignaciones que corresponden a la persona identificada actualmente en Archive Workbench. Desde cada tarea se puede abrir el documento y actualizar rápidamente el estado del trabajo."
        ),
        "Asignar una segunda revisión": (
            "Permite crear una revisión independiente sobre una revisión primaria que ya fue enviada o completada. La segunda revisión conserva su propia persona responsable, estado, conclusión y observaciones."
        ),
    },
    "review_object_tabs": {
        "Editar texto": (
            "Permite corregir el contenido del bloque de texto seleccionado y cambiar su clase cuando corresponde. Cada guardado crea una nueva revisión y conserva el texto anterior y el OCR original."
        ),
        "Orden y estructura": (
            "Permite revisar cómo se organizan y se leen los bloques de texto de la página. Desde esta pestaña se puede revisar el orden propuesto, trabajar con columnas y partes internas del documento, "
            "mover, combinar o dividir textos, resolver fragmentaciones o duplicados y consultar el historial estructural."
        ),
        "Casilleros y campos": (
            "Permite describir la estructura de páginas que funcionan como formularios. Se pueden confirmar casilleros detectados, agregar casilleros que no fueron detectados y agrupar opciones que pertenecen a una misma pregunta o campo."
        ),
        "Estado y anotaciones": (
            "Permite registrar el estado de revisión del bloque de texto seleccionado y agregar etiquetas o comentarios de revisión. Estas anotaciones quedan vinculadas con el bloque y se conservan en su historial."
        ),
        "Menciones de entidades": (
            "Permite vincular una parte del bloque de texto seleccionado con una entidad registrada en el proyecto. También permite revisar nombres detectados automáticamente y decidir si corresponden o no a una entidad."
        ),
        "Datos adicionales": (
            "Muestra información adicional asociada con el bloque de texto seleccionado, incluida información de procedencia, clasificación u otros datos conservados durante la extracción y el procesamiento."
        ),
        "Historial general": (
            "Muestra los cambios registrados para la página y sus bloques de texto, con la persona responsable y la fecha de cada modificación. Cuando existe una revisión anterior recuperable, también permite restaurar su contenido sin borrar el historial posterior."
        ),
    },
    "semantic_tabs": {
        "Buscar en los textos": (
            "Permite escribir una consulta y recuperar los fragmentos cuyo significado se parece más a esa consulta. Los resultados muestran su grado de similitud y permiten abrir el texto dentro del documento de origen."
        ),
        "Configurar el índice de búsqueda": (
            "Permite decidir qué contenido formará parte del índice semántico, cómo se agruparán los textos y qué modelo se utilizará para representarlos. Después de modificar la configuración es necesario reconstruir el índice antes de volver a buscar."
        ),
    },
    "authority_tabs": {
        "Ficha": (
            "Permite revisar y modificar los datos estables de la entidad seleccionada: tipo, nombre principal, nombres alternativos, descripción, período y estados de revisión y vigencia."
        ),
        "Menciones": (
            "Muestra primero las menciones que ya están vinculadas con la entidad seleccionada. También permite buscar nuevas apariciones del nombre principal o de sus nombres alternativos y decidir cuáles deben vincularse con la entidad."
        ),
        "Relaciones": (
            "Muestra las relaciones de la entidad seleccionada. Distingue los roles archivísticos de productor o responsable de gestión, que provienen de Catálogo, de las relaciones analíticas creadas para registrar vínculos interpretativos sustentados por el corpus."
        ),
        "Historial": (
            "Muestra las revisiones anteriores de la ficha de la entidad seleccionada y permite conocer qué datos cambiaron, quién realizó cada modificación y cuándo se hizo."
        ),
    },
    "open_discovery_grouping_tasks": {
        "Revisar posibles referencias repetidas": (
            "Agrupa referencias que podrían corresponder al mismo referente para que una persona decida si deben tratarse juntas. La agrupación no fusiona referencias ni copia decisiones entre ellas."
        ),
        "Actualizar referencias después de corregir el texto": (
            "Permite volver a ubicar una referencia cuando una corrección posterior modificó el texto en el que había sido encontrada. La ubicación anterior se conserva en el historial."
        ),
    },
    "open_discovery_review_modes": {
        "Revisar una por una": (
            "Muestra cada referencia pendiente con su contexto documental y permite tomar una decisión individual sobre esa referencia."
        ),
        "Trabajar con varias referencias": (
            "Permite seleccionar varias referencias y aplicar una misma clase de decisión al conjunto. Archive Workbench conserva una decisión y, cuando corresponde, una entidad independiente para cada referencia seleccionada."
        ),
        "Referencias descartadas": (
            "Muestra las referencias descartadas en revisiones anteriores. Permite restaurar una referencia mediante una nueva decisión sin borrar el descarte histórico."
        ),
    },
    "graph_tabs": {
        "Explorar las relaciones": (
            "Muestra el mapa interactivo construido con los filtros actuales. Al seleccionar un elemento o una relación se puede consultar qué representa, de qué registro proviene y abrir el documento, la unidad archivística o la entidad relacionada."
        ),
        "Revisar problemas detectados": (
            "Muestra menciones y relaciones que presentan problemas de consistencia, como ubicaciones desactualizadas, duplicados o entidades faltantes. Cada reparación requiere una decisión explícita y queda registrada como una nueva revisión."
        ),
        "Exportar estas relaciones": (
            "Permite guardar las relaciones que están visibles con los filtros actuales en formatos destinados al análisis externo. La exportación puede generar JSON, CSV y GraphML sin modificar los registros del proyecto."
        ),
    },
    "export_tabs": {
        "Configurar qué exportar": (
            "Permite definir qué textos y datos se incluirán, cómo se agruparán y qué formato se usará. Guardar la configuración no crea todavía el archivo de exportación."
        ),
        "Revisar textos que se exportarán": (
            "Muestra una vista previa de los textos incluidos por la configuración seleccionada para comprobar el contenido antes de crear el archivo."
        ),
        "Crear archivo de exportación": (
            "Crea el archivo utilizando la configuración seleccionada. Archive Workbench registra el archivo generado, su tamaño y su huella de verificación para poder identificar exactamente el resultado."
        ),
        "Historial de exportaciones": (
            "Muestra los archivos de exportación creados anteriormente y la configuración utilizada para producir cada uno."
        ),
    },
    "admin_tabs": {
        "Integridad": (
            "Comprueba la base de datos, los archivos y otros componentes necesarios para trabajar con el proyecto. Cuando existe una tarea concreta para revisar un hallazgo, el resultado permite abrirla directamente; los detalles técnicos permanecen disponibles sin ocupar la vista principal."
        ),
        "Copias de seguridad": (
            "Permite crear una copia de seguridad verificable del proyecto y revisar las copias ya existentes. Cada copia conserva información sobre su creación y una huella SHA-256 para comprobar su integridad."
        ),
        "Probar recuperación": (
            "Comprueba una copia de seguridad en un entorno temporal sin reemplazar el proyecto actual. La prueba verifica que la copia pueda abrirse y, cuando corresponde, actualizarse hasta la revisión vigente de la base."
        ),
        "Restaurar": (
            "Permite preparar la restauración de una copia de seguridad sobre el proyecto actual. La restauración reemplaza la base de datos activa, por lo que se realiza con Archive Workbench cerrado y conserva las confirmaciones de seguridad correspondientes."
        ),
        "Autorizaciones de análisis": (
            "Muestra las autorizaciones registradas cuando una búsqueda, exportación u otro análisis automático utilizó un alcance de páginas determinado. Puede filtrarse por análisis, responsable, origen y alcance sin modificar el historial registrado."
        ),
    },
}

TASK_HELP = {
    "catalog_main_task": {
        "Estado del catálogo": "Resume cuántas unidades y archivos están registrados y señala descripciones incompletas o archivos que no están disponibles localmente.",
        "Unidades del catálogo": "Permite buscar y seleccionar una unidad del catálogo para revisar o modificar su descripción, sus responsables, los archivos vinculados, su relación con el nivel superior y su historial.",
        "Planilla del catálogo": "Permite descargar el catálogo como planilla XLSX o importar una planilla para crear y actualizar unidades. Archive Workbench muestra primero qué cambios produciría la planilla y sólo los guarda después de una confirmación explícita.",
        "Crear una unidad": "Permite crear manualmente una nueva unidad según las relaciones de custodia, jerarquía documental o ubicación física permitidas por el proyecto.",
        "Incorporar archivos": "Permite registrar archivos digitales y vincularlos con las unidades del catálogo que representan o de las que forman parte.",
    },
    "audiovisual_import_method": {
        "Desde esta computadora": (
            "Permite elegir uno o varios archivos locales de audio o video. Si están fuera de la carpeta del proyecto, Archive Workbench copia los archivos dentro del proyecto antes de registrarlos; si ya pertenecen al proyecto, reutiliza esas rutas."
        ),
        "Desde una plataforma web": (
            "Permite incorporar una copia autorizada de un audio o video publicado en una plataforma. Archive Workbench conserva por separado la publicación remota, la agrupación de plataforma si existe y la copia local incorporada; una playlist no se convierte automáticamente en una unidad del catálogo."
        ),
    },
    "review_search_surface": {
        "Documentos revisados": "Busca palabras o frases dentro de los textos y datos revisados de los documentos. La búsqueda puede limitarse por documento, parte interna, tipo de bloque, estado de revisión, etiquetas, entidades y período.",
        "Transcripciones de audio y video": "Busca palabras o frases dentro de los segmentos de las transcripciones registradas. Cada coincidencia permite volver directamente al segmento correspondiente en Audio y video.",
    },
    "review_search_result_view": {
        "Tarjetas": "Muestra cada bloque encontrado con su contexto, estado y procedencia, y permite abrirlo directamente en Revisar documentos.",
        "Concordancias": "Alinea cada aparición encontrada con un contexto breve a izquierda y derecha para comparar rápidamente cómo se usa una palabra o frase en distintos documentos.",
    },
    "authority_main_task": {
        "Revisar fichas y menciones": "Permite buscar una entidad registrada y revisar su ficha, las menciones vinculadas, sus relaciones y su historial.",
        "Crear una ficha": "Permite registrar manualmente una entidad nueva con su nombre, tipo, descripción, período y estado de revisión.",
        "Importar o exportar fichas": "Permite descargar las fichas actuales de entidades y relaciones como una plantilla JSON editable o importar una plantilla preparada fuera de Archive Workbench. Antes de guardar cambios, la aplicación muestra qué registros se crearían, actualizarían o reutilizarían.",
        "Buscar nuevas entidades": "Permite buscar automáticamente posibles referencias a entidades en los textos y revisar cada resultado antes de crear una ficha o vincularlo con una entidad existente.",
    },
    "open_discovery_task": {
        "Revisar referencias encontradas": "Permite revisar las posibles referencias a entidades encontradas en una búsqueda automática y decidir si cada referencia crea una entidad nueva, se vincula con una entidad existente o se descarta.",
        "Ejecutar búsqueda de entidades": "Permite elegir o configurar cómo se buscarán nuevas referencias a entidades dentro de los textos y ejecutar una nueva búsqueda. Los resultados quedan pendientes hasta que una persona los revise.",
        "Duplicados y cambios de texto": "Permite resolver dos problemas que pueden aparecer después de una búsqueda: referencias que podrían corresponder al mismo referente y referencias cuya ubicación quedó desactualizada porque el texto del documento cambió.",
    },
    "export_surface": {
        "Documentos revisados": "Permite seleccionar, revisar y exportar textos de los documentos según sus tipos, estados de revisión, agrupación y otros criterios.",
        "Segmentos de audio y video": "Permite configurar, revisar y crear archivos JSONL o CSV con segmentos de transcripción; las exportaciones quedan registradas dentro del proyecto.",
    },
    "exchange_main_task": {
        "Enviar cambios": "Crea un ZIP con los cambios nuevos de esta copia desde el último punto compartido. El ZIP puede descargarse o subirse a Google Drive desde el mismo recorrido.",
        "Recibir cambios": "Permite abrir un ZIP recibido desde este equipo o desde Google Drive, ver qué modificaría en esta copia y resolver únicamente las diferencias necesarias antes de incorporar nada.",
        "Preparar una copia para trabajar en equipo": "Crea una copia transportable del proyecto para iniciar trabajo distribuido. Permite elegir si viajan originales y otros grupos de archivos; la base y la configuración siempre se conservan. El mismo ZIP puede enviarse a varias personas y cada copia recibida obtiene automáticamente una identidad propia al abrirse por primera vez.",
    },
    "exchange_receive_source": {
        "Desde este equipo": "Permite elegir un ZIP guardado en este equipo para identificar si contiene una copia inicial o cambios de otra copia del mismo proyecto.",
        "Desde Google Drive": "Permite elegir y descargar un ZIP desde Google Drive. Archive Workbench verifica el archivo antes de mostrar la acción que corresponde.",
    },
    "exchange_advanced_task": {
        "Reemplazar el trabajo editable completo": "Herramienta excepcional para sustituir todo el trabajo editable de una copia por el estado completo de otra, con vista previa y copia de seguridad previa.",
        "Reconectar dos copias con el mismo trabajo editable": "Herramienta excepcional para dos copias ya existentes que contienen el mismo trabajo editable pero dejaron de reconocer su punto de partida común. El recorrido normal de trabajo en equipo no requiere usarla.",
    },
    "exchange_adoption_step": {
        "Crear el ZIP con todo el trabajo editable": "Crea un paquete que contiene el estado editable completo de esta copia para enviarlo a otra copia del mismo proyecto.",
        "Revisar un ZIP completo y reemplazar el trabajo editable de esta copia": "Compara un paquete de estado completo con la copia actual y muestra qué elementos se agregarían, quitarían o cambiarían antes de permitir el reemplazo.",
    },
    "exchange_common_base_step": {
        "1. Iniciar desde esta copia": "Crea un ZIP de propuesta que se lleva a la otra copia para que confirme que ambas contienen el mismo trabajo editable.",
        "2. Confirmar en la otra copia": "Comprueba la propuesta recibida y, si el trabajo editable coincide, crea el acuerdo que debe volver a la copia inicial.",
        "3. Completar en la copia inicial": "Registra en la copia que inició el recorrido el mismo punto común ya confirmado por la otra copia.",
    },
    "review_form_task": {
        "Revisar casilleros detectados": (
            "Muestra los posibles casilleros detectados automáticamente en la página actual. Cada propuesta sigue pendiente hasta que una persona confirma su estado, rótulo y grupo."
        ),
        "Agregar un casillero manualmente": (
            "Permite registrar un casillero real que no fue detectado automáticamente, vinculando su rótulo y, cuando existe, la marca con bloques de texto de la página actual."
        ),
        "Revisar casilleros confirmados": (
            "Permite editar el estado, rótulo, grupo o nota de un casillero ya confirmado en la página actual, o archivarlo si dejó de corresponder."
        ),
        "Administrar grupos de casilleros": (
            "Permite crear, renombrar o archivar grupos que organizan casilleros relacionados dentro de la página actual."
        ),
        "Historial de casilleros y grupos": (
            "Muestra las revisiones registradas de la estructura de casilleros y grupos de la página actual, sin mezclar este historial con los demás cambios del bloque de texto."
        ),
    },
    "review_structure_task": {
        "Revisar orden y columnas": "Analiza la posición de los bloques de texto y propone un orden de lectura y, cuando corresponde, una organización en columnas. La propuesta no modifica la página hasta que la persona la confirma.",
        "Ajustar columnas": "Permite crear columnas manualmente, asignar el bloque de texto seleccionado a una columna, moverlo entre columnas y renombrar o archivar columnas ya confirmadas.",
        "Asignar parte del documento": "Permite indicar a qué parte interna del documento pertenece el bloque de texto seleccionado o toda la página. La parte debe estar previamente registrada para ese documento.",
        "Mover texto": "Permite cambiar una posición el bloque de texto seleccionado dentro del orden de lectura de la página.",
        "Combinar textos": "Permite unir el bloque de texto seleccionado con el bloque anterior o siguiente. La persona elige cómo se separarán ambos contenidos en el texto resultante.",
        "Dividir texto": "Permite separar un bloque de texto en dos bloques distintos indicando el punto exacto donde debe producirse la división.",
        "Resolver fragmentaciones o duplicados": "Muestra posibles fragmentaciones y duplicados detectados en la página. Ninguna sugerencia modifica el texto por sí sola: la persona decide qué fragmentos combinar o qué duplicado archivar.",
        "Historial de orden y estructura": "Muestra solamente los cambios relacionados con orden de lectura, columnas, fragmentaciones y duplicados. Las demás modificaciones de la página siguen disponibles en Historial general.",
    },
}
