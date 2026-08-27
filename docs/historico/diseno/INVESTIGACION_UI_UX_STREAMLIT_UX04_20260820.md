# Investigación UI/UX para UX-04 y aplicación en Streamlit

**Fecha:** 2026-08-20  
**Estado:** insumo de diseño para `UX-04`; no es política canónica todavía.  
**Candidata estudiada:** Archive Workbench 0.89.0 RC21, no publicada.  
**Primer prototipo previsto:** `Entidades y menciones`.

## 1. Problema observado en PILOT-01

La prueba manual de RC21 identifica una dificultad transversal: la interfaz acumula demasiadas unidades visibles de texto, títulos, ayudas, paneles y capas de navegación. La función puede existir y ser correcta, pero el esfuerzo para reconocer el objeto activo y decidir el próximo paso sigue siendo alto. En `Entidades y menciones` el problema se vuelve especialmente visible: la entidad seleccionada no domina la jerarquía, hay dos series de pestañas, las explicaciones compiten con los controles y tareas secundarias ocupan el mismo plano visual que la tarea principal.

Este diagnóstico encaja con la regla de escalamiento ya vigente en `.assistant/05_CRITERIOS_INTERFAZ.md`: una pantalla que se percibe como laberinto requiere reformular arquitectura de información y recorrido, no sumar retoques cosméticos.

## 2. Síntesis de investigación general de UX/UI

### 2.1 Menos información visible, pero sin esconder lo necesario

La heurística de diseño estético y minimalista de Nielsen Norman Group sostiene que cada unidad de información irrelevante o rara compite con las unidades relevantes y disminuye su visibilidad. Para Archive Workbench esto respalda retirar del plano principal explicaciones repetitivas, diagnósticos y contexto que no intervienen en la decisión inmediata.

La reducción no debe convertirse en ocultamiento indiscriminado. Nielsen Norman Group advierte que los modos de interfaz que esconden herramientas necesarias pueden aumentar costo de interacción, carga cognitiva y cambios de atención. La regla útil para UX-04 es por lo tanto: **retirar ruido, no retirar instrumentos de trabajo**. Una función frecuente debe ser directa; una explicación o variante secundaria puede quedar disponible bajo demanda.

Fuentes:

- Nielsen Norman Group, *Heuristic Evaluation Workbook*, heurística 8: https://media.nngroup.com/media/articles/attachments/Heuristic_Evaluation_Workbook_-_Nielsen_Norman_Group.pdf
- Nielsen Norman Group, *Why Zen Mode Isn’t the Answer to Everything*: https://www.nngroup.com/articles/zen-mode/

### 2.2 Jerarquía visual como reducción de carga cognitiva

La escala, el contraste y la jerarquía visual permiten indicar qué elemento debe mirarse primero. Nielsen Norman Group recomienda usar el tamaño relativo para señalar importancia y mantener pocas escalas tipográficas. Para una ficha de entidad, el nombre de la entidad debe convertirse en el primer ancla de lectura; los atributos secundarios deben ocupar un nivel menor y estable.

El mismo principio aparece en las guías de listados: cada entrada necesita una mini-arquitectura de información que priorice pocos atributos y refleje esa prioridad mediante posición, tamaño, peso y espacio. Una entidad puede tratarse como un objeto reconocible con nombre dominante, tipo y estado secundarios, en lugar de diluirse dentro de una larga secuencia de controles.

Fuentes:

- Nielsen Norman Group, *5 Visual-design Principles in UX*: https://media.nngroup.com/media/articles/attachments/Principles_Visual_Design-Letter.pdf
- Nielsen Norman Group, *The Anatomy of a List Entry*: https://www.nngroup.com/articles/list-entries/

### 2.3 Reconocimiento antes que recuerdo

La heurística de reconocimiento en lugar de recuerdo recomienda mantener visibles o fácilmente recuperables los elementos necesarios para usar la interfaz. UX-04 no debe exigir recordar qué entidad está activa al desplazarse por una pantalla larga. El objeto activo necesita una identidad visual persistente dentro del recorrido y las ayudas conceptuales deben estar disponibles en contexto, en lugar de obligar a consultar explicaciones largas antes de trabajar.

Fuente:

- Nielsen Norman Group, *Recognition Rather Than Recall*: https://media.nngroup.com/media/articles/attachments/Heuristic_6_A4_compressed.pdf

### 2.4 Escritura escaneable

La investigación clásica de lectura en pantalla muestra que las personas tienden a escanear y a economizar fijaciones. Cuando la página no ofrece señales visuales claras, la lectura adopta recorridos de mínimo esfuerzo y el texto adicional puede convertirse en ruido. Para Archive Workbench, las instrucciones del cuerpo deben reservarse para información que cambia una decisión. El contexto extenso puede vivir en la guía de la sección y las definiciones breves junto al término que las necesita.

Fuentes:

- Nielsen Norman Group, *Be Succinct! (Writing for the Web)*: https://www.nngroup.com/articles/be-succinct-writing-for-the-web/
- Nielsen Norman Group, *F-Shaped Pattern of Reading on the Web*: https://www.nngroup.com/articles/f-shaped-pattern-reading-web-content/

### 2.5 Arquitectura de información: una capa de navegación contextual a la vez

Una pantalla con dos barras de pestañas obliga a mantener simultáneamente dos jerarquías: tarea general y subárea de la ficha. El problema no se resuelve cambiando colores de las pestañas. Debe aplanarse la arquitectura de información para que en el cuerpo exista una sola capa contextual de navegación visible.

La referencia de GOV.UK para formularios complejos parte del mismo objetivo: reducir la cantidad de decisiones simultáneas y evitar repetición cuando el contexto ya nombra la tarea. Archive Workbench no necesita adoptar literalmente el patrón de una pregunta por página, pero sí su principio de foco y no duplicación.

Fuente:

- GOV.UK Design System, *Making labels and legends headings*: https://design-system.service.gov.uk/get-started/labels-legends-headings/

## 3. Investigación específica sobre Streamlit

RC21 declara `streamlit>=1.55,<2`. Las capacidades nativas actuales permiten resolver buena parte del rediseño sin introducir componentes paralelos ni una arquitectura alternativa de reruns.

### 3.1 Sidebar para navegación persistente

La documentación oficial describe el sidebar como espacio para organizar widgets y mantener el foco en el contenido principal. Esto respalda llevar `Archive Workbench` y la navegación global a esa superficie, reservando el cuerpo para el título y la tarea de la sección activa.

Fuente: https://docs.streamlit.io/develop/api-reference/layout/st.sidebar

### 3.2 Contenedores horizontales para economizar topología

`st.container(horizontal=True)` permite disponer elementos en una fila y adaptarlos al contenido; la documentación de Streamlit lo recomienda frente a columnas rígidas cuando los elementos tienen anchos variables. Es útil para identidad de entidad, acciones breves, alias y controles de refinamiento que no justifican una fila completa cada uno.

Fuentes:

- https://docs.streamlit.io/develop/api-reference/layout/st.container
- https://docs.streamlit.io/develop/concepts/design/layouts-and-containers

### 3.3 Búsqueda compacta sin perder nombre accesible

`st.text_input` admite `placeholder` y `label_visibility="collapsed"`, pero su documentación exige mantener un `label` no vacío por accesibilidad. W3C también advierte que el placeholder no sustituye semánticamente una etiqueta. Para cumplir el pedido de economía visual, el prototipo puede conservar `Buscar nombre, nombre alternativo o descripción` como etiqueta programática y mostrar esa misma indicación dentro del campo, sin renderizar una línea de etiqueta separada.

Esto reduce altura sin convertir el control en un input sin nombre accesible.

Fuentes:

- Streamlit, `st.text_input`: https://docs.streamlit.io/develop/api-reference/widgets/st.text_input
- W3C WAI, *Labeling Controls*: https://www.w3.org/WAI/tutorials/forms/labels/
- W3C WAI, *Form Instructions*: https://www.w3.org/WAI/tutorials/forms/instructions/

### 3.4 Ayuda contextual y tooltips

Streamlit admite `help` en encabezados, Markdown, badges y widgets. Esto permite reemplazar desplegables puramente definicionales por ayuda breve disponible junto al término. Esa ayuda no debe contener información crítica que sea necesaria para completar una acción, porque la persona puede no abrirla y porque un tooltip no reemplaza el estado visible de una tarea.

Fuentes:

- https://docs.streamlit.io/develop/api-reference/text/st.header
- https://docs.streamlit.io/develop/api-reference/text/st.markdown
- https://docs.streamlit.io/develop/api-reference/text/st.badge

### 3.5 Pills, controles segmentados y badges

`st.pills` y `st.segmented_control` ofrecen selecciones compactas; `st.badge` permite información breve no interactiva con color y ayuda contextual. Son herramientas posibles para estados, tipos o pequeños conjuntos de opciones. No constituyen una obligación de diseño: si su acumulación vuelve a producir una segunda barra de navegación o una nube de controles, deben descartarse.

Fuentes:

- https://docs.streamlit.io/develop/api-reference/widgets/st.pills
- https://docs.streamlit.io/develop/api-reference/widgets/st.segmented_control
- https://docs.streamlit.io/develop/api-reference/text/st.badge

### 3.6 Popovers y divulgación progresiva

`st.popover` puede alojar controles secundarios y, con el comportamiento normal, abrirse sin un rerun; las interacciones internas mantienen el popover abierto. Es útil para tareas auxiliares pequeñas, como agregar un alias. No debe usarse como respuesta automática a toda densidad y no es la propuesta elegida para `Filtros de entidades`, porque en este caso la validación manual pidió explícitamente evitar otro botón/panel de filtros.

Fuente: https://docs.streamlit.io/develop/api-reference/layout/st.popover

### 3.7 Compatibilidad con el invariante local

La documentación externa de Streamlit también ofrece fragmentos y otros mecanismos de rerun, pero `UX-04` no debe introducirlos como estrategia local. Para Archive Workbench prevalece `docs/referencia/ARQUITECTURA_Y_MODELO_ACTUAL.md#streamlit-interaction-invariant`: estado estable en `session_state`, acciones semánticas discretas, componentes locales sin eventos espurios y conservación de scroll mediante el mecanismo canónico ya existente.

## 4. Método provisional de revisión UI/UX para Archive Workbench

Este método funciona como una skill de trabajo para `UX-04`. No se incorpora todavía a `.assistant`; primero debe probarse y corregirse sobre una candidata real.

1. **Nombrar el objeto y la acción principal.** Antes de tocar widgets, responder qué objeto está activo y qué tarea principal se completa en la superficie.
2. **Inventariar lo visible.** Contar títulos, párrafos, pestañas, paneles, controles y estados que aparecen antes de la primera acción útil.
3. **Clasificar cada unidad.** Marcarla como identidad del objeto, decisión necesaria, estado necesario, ayuda secundaria, auditoría/historial o redundancia.
4. **Eliminar duplicación visual.** Una explicación que repite el título, el botón o el contexto se retira del cuerpo. Si conserva valor pedagógico, se mueve a `Guía de esta sección` o a ayuda contextual.
5. **Construir jerarquía.** El objeto activo y la acción principal reciben mayor escala o contraste; la metadata secundaria se agrupa de forma compacta y consistente.
6. **Aplanar navegación.** No mostrar simultáneamente dos niveles de pestañas. Las tareas auxiliares se reubican como acciones contextuales o dentro de una única navegación.
7. **Economizar topología.** Usar una fila para elementos breves relacionados, evitar que cada control consuma una línea completa y preferir contenedores horizontales adaptativos cuando la semántica lo permita.
8. **Preservar accesibilidad.** Una etiqueta puede ocultarse visualmente sólo cuando el contexto la hace redundante; el nombre accesible permanece. El color nunca es el único indicador de estado.
9. **Respetar contratos de interacción.** No cambiar el modelo de reruns, scroll o persistencia para obtener una apariencia más compacta.
10. **Validar sin explicación previa.** La prueba final pregunta si una persona entiende dónde está, sobre qué objeto trabaja y qué puede hacer sin que la guía externa repare el diseño.

## 5. Propuesta de arquitectura para `Entidades y menciones`

### 5.1 Shell global afectado por el prototipo

- `Archive Workbench` pasa al encabezado del sidebar.
- El cuerpo principal deja de repetir el nombre de la aplicación; el título grande es `Entidades y menciones`.
- La descripción general de la sección se integra en `Guía de esta sección`.
- Se eliminan los botones de sección anterior/siguiente del sidebar. La navegación de secciones queda en el selector global existente.

Estos cambios son globales por naturaleza, pero la reducción de textos internos de cada sección se implementa primero sólo en `Entidades y menciones` y se generaliza después de la validación del prototipo.

### 5.2 Una sola navegación contextual

El prototipo debe eliminar la combinación actual de dos barras de pestañas. Propuesta:

- mantener una única navegación principal de la sección para las tareas de alto nivel;
- convertir la revisión de una entidad en una **superficie de ficha**, no en una segunda aplicación dentro de la pestaña;
- integrar `Datos` y `Nombres alternativos` en la misma ficha;
- presentar `Menciones`, `Relaciones` e `Historial` como acciones contextuales de la ficha mediante un único selector de vista compacto, o trasladar la navegación de tareas generales fuera del cuerpo. La decisión concreta se tomará de manera que el resultado final muestre una sola serie de navegación en la superficie principal.

Antes de implementar se debe verificar cuál de las dos variantes produce menos desplazamiento y menos pérdida de contexto en Streamlit sin violar el invariante canónico.

### 5.3 Identidad visual de la ficha

Después del buscador/selector, la pantalla debe mostrar una cabecera de ficha claramente distinguible:

- nombre principal como elemento tipográfico dominante;
- tipo de entidad y estado como metadata breve;
- cantidad de menciones sólo si ayuda a reconocer el estado;
- alias como etiquetas compactas cuando existan;
- acciones ligadas a la ficha en el mismo bloque visual, sin crear otra tarjeta para cada dato.

La finalidad no es decorar la sección. Es que, incluso con visión periférica o después de desplazarse, resulte evidente qué entidad está activa. Este patrón funciona como primer experimento de identidad mnemotécnica de `UX-04`.

### 5.4 Búsqueda

El campo mantiene como nombre accesible `Buscar nombre, nombre alternativo o descripción`, pero la etiqueta visible se colapsa y el texto se presenta como placeholder. El contador de resultados permanece oculto cuando la consulta está vacía. Cuando hay consulta, aparece como información compacta destacada junto a los resultados, no como una línea permanente.

### 5.5 Filtros: decisión aprobada para el prototipo RC22

La alternativa recomendada para evaluar es una **barra de refinamiento integrada**, no un panel:

- el buscador ocupa la mayor parte de la fila;
- a su derecha aparecen controles directos, breves y siempre visibles para `Tipo`, `Estado` y `Período`;
- no existe título `Filtros de entidades`, expander, botón `Filtros`, popover ni paso previo para abrir opciones;
- `Tipo` parte sin restricción;
- `Estado` parte en activas y permite incluir dadas de baja;
- `Período` parte vacío y sólo filtra cuando la persona ingresa un rango; la opción de incluir entidades sin fecha se integra en el propio criterio temporal cuando éste está activo;
- si no hay filtros activos, la fila se lee visualmente como un buscador con refinamientos secundarios, no como un formulario separado.

Ventaja principal: preserva todas las funciones con **cero acción adicional para revelar filtros** y sin agregar una nueva superficie. El costo es que siempre quedan visibles tres refinamientos breves. La alternativa de moverlos al sidebar despeja más el cuerpo, pero separa controles que afectan inmediatamente el listado de entidades y obliga a mover la mirada entre dos regiones. La alternativa de ocultarlos en un popover ahorra espacio, pero contradice el pedido específico de no crear otro panel/botón y agrega una acción para acceder a opciones frecuentes.

Por eso la barra integrada fue la recomendación provisional. Alex aprobó explícitamente esta alternativa el 2026-08-20 y RC22 la implementa como parte del primer prototipo de `UX-04`. La aprobación corresponde a esta candidata de evaluación y no convierte todavía el patrón en una política transversal definitiva.

### 5.6 Datos y nombres alternativos

`Nombres alternativos` deja de ser una pestaña. Junto a la línea de `Nombre principal` aparece una acción compacta `Agregar nombre alternativo`. Al activarla se muestran únicamente los campos necesarios para ese alias. Los alias ya registrados se leen como etiquetas compactas; su tipo y nota quedan en ayuda contextual y no ocupan líneas permanentes. La eliminación sigue siendo una acción explícita y trazable.

### 5.7 Menciones

Se retira del cuerpo la explicación larga del mecanismo de búsqueda de coincidencias. La vista presenta directamente la acción y sus resultados. La explicación detallada pasa a la guía de la sección. Las métricas se reducen a las necesarias para decidir si hay algo por revisar y no se muestran como tablero cuando no aportan una acción.

### 5.8 Relaciones

La vista distingue visual y terminológicamente dos grupos:

- roles archivísticos procedentes de Catálogo, sólo lectura en esta sección;
- relaciones analíticas creadas desde la ficha.

`Crear una relación analítica` recibe una definición breve disponible en contexto. Se elimina la frase que explica que completar los campos no guarda nada. La interfaz conserva un único botón explícito de escritura y la evidencia documental sigue siendo parte obligatoria del recorrido cuando corresponda.

## 6. Qué no debe hacer el prototipo

- No eliminar funcionalidades para obtener una pantalla más limpia.
- No sustituir claridad por iconos sin texto o códigos internos.
- No convertir cada grupo en una tarjeta decorativa.
- No introducir una paleta nueva como solución a un problema de jerarquía.
- No usar color como único indicador.
- No introducir fragmentos, reruns adicionales, hacks de scroll ni componentes paralelos para sostener el rediseño.
- No expandir el patrón al resto de la aplicación hasta validar manualmente la primera candidata.

## 7. Criterios de validación del prototipo

La candidata de `Entidades y menciones` se considera útil sólo si la prueba manual confirma, como mínimo:

- que la entidad activa se reconoce inmediatamente;
- que la primera pantalla tiene sensiblemente menos texto y menos altura antes de la acción principal;
- que existe una sola jerarquía de navegación contextual visible;
- que búsqueda y refinamiento se entienden sin una explicación externa;
- que alias, menciones y relaciones siguen siendo localizables sin recordar rutas ocultas;
- que ninguna funcionalidad vigente desapareció;
- que los guardados, cambios de selección y controles reactivos conservan el contexto según el invariante canónico de Streamlit;
- que el diseño sigue siendo legible en las paletas existentes y no depende sólo del color.

## Validación posterior y promoción de criterios

La validación manual de RC22-RC23 confirmó que el prototipo aplicado a `Entidades y menciones` redujo materialmente la sobrecarga visual sin perder funciones. La segunda ronda validó también la reorganización de `Menciones` y `Relaciones`; el selector doble de `Buscar nuevas entidades` se aceptó como solución funcional, pero no se adopta como patrón obligatorio para otras secciones.

A partir de esa aprobación, los criterios generalizables dejan de ser sólo una metodología provisional y se incorporan a `.assistant/05_CRITERIOS_INTERFAZ.md`. RC24 aplica esos criterios transversalmente. Este documento permanece como evidencia histórica de la investigación y de las decisiones que originaron la política canónica.

## Seguimiento RC28 - descubribilidad de la ayuda contextual

La revisión posterior de RC27 mostró que una explicación correcta puede seguir siendo ineficaz si su disparador no es visible. El hover sobre un título común obligaba a descubrir la ayuda por accidente. Antes de RC28 se contrastó ese problema con documentación de sistemas de diseño y accesibilidad:

- U.S. Web Design System, `Tooltip`: recomienda que el elemento que dispara un tooltip sea reconocible como interactivo y advierte contra tooltips sin un disparador visual claro: https://designsystem.digital.gov/components/tooltip/
- WAI-ARIA Authoring Practices, `Tooltip Pattern`: define el tooltip como contenido asociado al elemento que recibe hover o foco y exige una relación accesible con el disparador: https://www.w3.org/WAI/ARIA/apg/patterns/tooltip/
- WCAG 2.1, `Content on Hover or Focus`: exige que la información adicional activada por hover también pueda manejarse mediante foco y permanezca disponible el tiempo necesario: https://www.w3.org/WAI/WCAG21/Understanding/content-on-hover-or-focus.html
- Streamlit documenta `help` como patrón nativo para títulos y widgets, confirmando que la ayuda contextual junto al rótulo es un patrón previsto por la biblioteca. `st.tabs` no ofrece un parámetro `help`, por lo que Archive Workbench mantiene la resolución centralizada en `tracked_tabs`: https://docs.streamlit.io/develop/api-reference/text/st.header y https://docs.streamlit.io/develop/api-reference/layout/st.tabs

Decisión de RC28: conservar las explicaciones completas ya aprobadas, pero asociarlas a un icono de información pequeño, consistente y visible. El icono reemplaza tanto al signo `?` rechazado en RC26 como al disparador invisible de RC27. La ayuda sigue fuera del cuerpo principal y aparece por hover y foco de teclado. Esta nota conserva la evidencia de la decisión; la política vigente está únicamente en `.assistant/05_CRITERIOS_INTERFAZ.md`.
## Seguimiento RC55 - jerarquía del feedback en Intercambiar cambios

La validación real posterior a RC54 confirmó que el intercambio incremental podía completarse, pero mostró una regresión de arquitectura visual: el resultado de aplicar un paquete, el estado persistente de conexión con Google Drive y la verificación local de un ZIP aparecían como mensajes destacados en zonas diferentes de la misma página. El problema no era falta de feedback, sino competencia entre feedback de distinta naturaleza.

Se contrastó el hallazgo con:

- Nielsen Norman Group, **Visibility of System Status**: el sistema debe informar con rapidez el resultado y el estado necesario para que la persona pueda decidir el paso siguiente. https://www.nngroup.com/articles/visibility-system-status/
- Nielsen Norman Group, **Progressive Disclosure**: las opciones avanzadas o poco frecuentes deben diferirse para concentrar la atención en las opciones primarias. https://www.nngroup.com/articles/progressive-disclosure/
- GOV.UK Design System, **Notification banner**: recomienda usar banners con moderación, evitar más de uno en la misma página y combinar mensajes cuando corresponden al mismo contexto. https://design-system.service.gov.uk/components/notification-banner/

Decisión de RC55: conservar feedback inmediato, pero diferenciarlo por función. Los resultados de una acción pueden usar un único mensaje destacado; estados persistentes como la conexión con Drive pasan a una línea compacta; hashes, rutas, IDs y tablas de compatibilidad quedan en detalles cerrados; las tareas alternativas de Drive se muestran de una en una; y `Más opciones` deja de competir simultáneamente con el flujo principal de enviar o recibir. La política canónica resultante está en `.assistant/05_CRITERIOS_INTERFAZ.md`.


## Seguimiento RC56 - arquitectura completa de Intercambiar cambios

La revisión manual posterior a RC55 mostró que reducir banners no alcanzaba si la navegación seguía trasladando distinciones internas al modelo mental de la persona usuaria. Dos casos eran especialmente visibles: `Más opciones` no nombraba un objeto ni un problema concreto y Google Drive duplicaba las tareas de enviar/recibir aunque sólo modificara el medio de transporte. En `Recibir cambios`, además, acciones reversibles u ocasionales ocupaban espacio antes de ser solicitadas.

RC56 aplica los criterios ya establecidos por UX-04 y RC55 a toda la sección:

- el selector principal expresa únicamente objetivos de trabajo: **Enviar cambios**, **Recibir cambios** y **Preparar una copia para trabajar en equipo**;
- Google Drive se trata como modalidad contextual: destino de un ZIP creado o fuente de un ZIP recibido;
- si ya existe un paquete recibido, la revisión de ese paquete es el objeto activo y abrir otro ZIP queda detrás de una acción explícita;
- archivar, eliminar definitivamente, reconstruir historial y resolver todas las diferencias de la misma manera revelan sus controles sólo después de solicitar la acción;
- las diferencias se recorren de una en una para evitar una pila de formularios reactivos;
- las funciones excepcionales de sustitución completa o reconexión manual entre copias se agrupan bajo **Resolver un problema entre copias**, fuera del selector cotidiano, y sustituyen temporalmente el recorrido normal mientras están activas;
- los `st.expander` que permanecen en esta sección contienen sólo información, historial o datos técnicos. Ningún flujo reactivo de archivo, conflicto o recuperación depende de que un expander conserve su apertura.

La auditoría funcional de RC56 comprobó que esta reorganización conserva los servicios ya validados para crear paquetes, preparar copias configurables, transportar por Drive, identificar ZIP, simular, resolver diferencias, aplicar con backup, archivar/restaurar/eliminar entradas y usar las rutas excepcionales de recuperación. No se modifica el contrato de dominio ni la persistencia; la intervención es de arquitectura de información y estado de interfaz.
