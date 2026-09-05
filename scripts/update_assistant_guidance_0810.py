#!/usr/bin/env python3
"""Actualiza reglas privadas de OCR-01D y crea políticas del sitio público."""

from __future__ import annotations

from pathlib import Path


OCR_BLOCKS = {
    "01_INTERACCION_Y_GUIADO.md": """

<!-- OCR01D_GUIDED_MANUAL_VALIDATION -->
## Validaciones manuales de OCR regional (0.81.0)

- Indicar siempre la ruta completa dentro de la interfaz: sección, pestaña, bloque y nombre literal del control.
- No agrupar en una sola oración acciones situadas en lugares distintos de la pantalla.
- Antes de pedir una comprobación visual, declarar explícitamente si la imagen se muestra en esa vista y verificarlo sobre la candidata.
- Para OCR regional, describir cada paso en el mismo orden numerado que usa la pantalla; no exigir al usuario conocer plantillas YAML ni contratos internos.
- Si la validación se interrumpe, retomar desde la última acción no persistida. No repetir la carga, el dibujo o las decisiones que ya quedaron guardadas.
""",
    "05_CRITERIOS_INTERFAZ.md": """

<!-- OCR01D_VISUAL_WORKFLOW -->
## OCR regional visual (0.81.0)

- El recorrido común debe ser lineal: documento, página, dibujo, descripción, lista y ejecución.
- La página sobre la que se dibuja debe permanecer visible durante la definición de zonas.
- Las opciones de Tesseract y otros detalles técnicos quedan ocultos bajo opciones avanzadas.
- Una corrida regional siempre nace como candidata y no altera selección canónica ni capa editable.
- Una zona manual conserva geometría y recorte; nunca inventa una transcripción.
- El orden de lectura asignado por la interfaz debe ser único por página y aprovechar huecos existentes antes de crear posiciones nuevas.
""",
}

READ_FIRST_BLOCK = """

<!-- PUBLIC_SITE_POLICIES -->
## Políticas para documentación y sitios públicos

Antes de producir HTML, README, tutoriales, capturas, figuras o contenido público, leer conjuntamente:

- `.assistant/POLITICA_SITIO_PUBLICO.md`;
- `.assistant/LINEAMIENTOS_DE_DISENO_Y_ESCRITURA.md`.

Estas políticas se aplican al sitio público de Archive Workbench. El futuro sitio del GIAR tendrá documentos propios en su repositorio.
"""

PUBLIC_SITE_POLICY = """# Política del sitio público y los tutoriales de Archive Workbench

Los criterios visuales, retóricos y de registro se desarrollan en
`.assistant/LINEAMIENTOS_DE_DISENO_Y_ESCRITURA.md`. Ambos documentos se aplican juntos.

## Auditorio

El sitio público se dirige a archivistas, cientistas sociales, lingüistas, historiadores y personas que consultan, describen o investigan archivos. No se presupone formación en programación, bases de datos, OCR o aprendizaje automático.

La escritura debe:

- partir de una tarea o problema de trabajo con archivos;
- explicar cada término técnico la primera vez que aparece;
- usar ejemplos archivísticos y documentales concretos;
- distinguir propuestas automáticas, cálculos deterministas, decisiones humanas y datos canónicos;
- explicar la procedencia y el historial cuando afecten la interpretación;
- evitar jerga de desarrollo, nombres de fixes, commits, pruebas locales y decisiones transitorias;
- usar afirmaciones directas, sin marketing, cierres aforísticos ni señalización vacía de importancia.

Archive Workbench se presenta como una herramienta de investigación, descripción, revisión y preservación de resultados. La documentación pública debe mostrar qué permite hacer, qué conserva y qué exige revisión humana.

## Alcance de WEB-01

Antes de v1.0 se prepararán:

- un sitio de varias páginas HTML para GitHub Pages;
- un tutorial completo de uso de la aplicación;
- un README ilustrado, explicativo y enlazado con el sitio;
- una referencia técnica pública detallada;
- figuras, esquemas y capturas reales cuando ayuden a comprender el flujo;
- una revisión de accesibilidad, enlaces y metadatos.

El sitio se construye después de `UX-02`, para que las capturas y recorridos correspondan a la interfaz consolidada.

## Organización pública prevista

La estructura puede ajustarse durante WEB-01, pero debe cubrir como mínimo:

- `docs/index.html`: presentación, auditorio y recorrido general;
- páginas de catálogo, procesamiento, revisión, autoridades, relaciones, grafos, búsqueda, exportación, intercambio y resguardo;
- `docs/tutorial.html` o un conjunto `docs/tutorial/`: recorrido reproducible de principio a fin;
- una página de instalación y primeros pasos;
- una página de conceptos y decisiones metodológicas;
- una referencia técnica pública sobre arquitectura, SQLite, revisiones, migraciones, contratos y extensiones;
- solución de problemas frecuentes;
- enlaces al README, CHANGELOG, licencia y repositorio.

El README debe permitir comprender el proyecto sin abrir el código. Incluye presentación, estado, instalación, quickstart, capturas reales, mapa de capacidades, limitaciones vigentes y enlaces a la documentación extensa.

## Retórica y organización

Cada página debe tener:

1. una entrada que formule la tarea o el problema;
2. una progresión clara de conceptos o acciones;
3. definiciones en contexto;
4. ejemplos, figuras o capturas cuando aclaren el procedimiento;
5. enlaces hacia la referencia técnica cuando el detalle exceda al auditorio general;
6. navegación estable entre páginas relacionadas.

La prosa expositiva usa registro impersonal o tercera persona. Las instrucciones directas emplean voseo consistente. No se fuerza oralidad porteña ni se usa español peninsular.

Los registros de validación, versiones candidatas y detalles efímeros no van al HTML público. Un dato de desarrollo se publica únicamente cuando puede formularse como comportamiento estable.

## Tutoriales

Un tutorial debe:

- declarar el material y el estado inicial;
- indicar la ruta exacta dentro de la interfaz;
- usar los nombres visibles de controles y secciones;
- explicar qué se crea o modifica en cada paso;
- señalar cuándo una salida sigue siendo candidata;
- incluir el resultado esperado y cómo comprobarlo;
- separar acciones obligatorias de opciones avanzadas;
- evitar saltos que presupongan conocimiento previo de una función nueva.

Las capturas del tutorial deben corresponder al mismo recorrido, corpus y versión documentada.

## Información técnica

La referencia técnica de release debe explicar:

- arquitectura modular y responsabilidades;
- fuente de verdad SQLite;
- originales inmutables y derivados;
- revisiones append-only, deshacer/rehacer y auditoría;
- catálogo, autoridades, menciones y relaciones;
- preprocesamiento, extracción, selección canónica y capa editable;
- intercambio, adopción de estado, backups y migraciones;
- exportaciones y contratos públicos;
- extensiones opcionales y límites de confianza.

La documentación introductoria enlaza esa referencia sin duplicarla de manera parcial o contradictoria.

## Capturas, figuras y esquemas

Las capturas representan estados reales de la interfaz. No se inventan ni se reemplazan por mockups. La guía de producción registra pantalla, proyecto, documento, estado, filtros, recorte, texto visible y ruta final.

Los SVG y diagramas deben expresar relaciones reales del modelo. No se agregan figuras decorativas. Una captura con datos sensibles, originales restringidos o información personal requiere autorización o una base pública de demostración.

## Accesibilidad y lectura

- Mantener contraste suficiente y jerarquía tipográfica legible.
- No depender solo del color para explicar estados.
- Incluir texto alternativo en imágenes informativas.
- Evitar líneas excesivamente largas y bloques densos sin subtítulos.
- Permitir lectura razonable en pantallas pequeñas.
- Usar tablas únicamente cuando mejoran la comparación.

## Sincronización

Al cerrar una implementación con impacto público se revisa:

- README y páginas de uso si cambia una tarea;
- tutoriales si cambia el recorrido;
- referencia técnica si cambia el modelo, esquema o contrato;
- comandos públicos si cambia el CLI;
- capturas y figuras si la interfaz o los resultados visibles cambiaron.

La fuente de verdad para trabajo abierto sigue siendo `.assistant/project_docs/operativos/PENDIENTES_ACTIVOS.md`. El sitio público no debe presentar como disponible una función pendiente.
"""

DESIGN_WRITING_POLICY = """# Lineamientos de diseño y escritura para Archive Workbench

> Referencia para cualquier LLM o persona que produzca interfaz, HTML, README,
> tutoriales, documentación, figuras o contenido visual para Archive Workbench.

## 0. Propósito

Archive Workbench es un instrumento de investigación y trabajo archivístico. Su diseño debe facilitar lectura, procedencia, revisión y comprensión de operaciones complejas. El estilo genérico de una landing page o un dashboard comercial resulta inadecuado para este proyecto.

Este documento cubre diseño visual y escritura. Se aplica junto con `.assistant/POLITICA_SITIO_PUBLICO.md`.

## 1. Diseño visual: prohibiciones

### 1.1 Patrones que no deben usarse como solución por defecto

- Gradientes violetas o azules usados como identidad automática.
- Hero centrado seguido por tres tarjetas redondeadas de funciones.
- Glassmorphism, blur y transparencias sin función semántica.
- Componentes de bibliotecas visuales sin adaptar jerarquía, densidad y paleta.
- Íconos dentro de cuadrados redondeados repetidos para cada sección.
- Botones azules genéricos sin sistema visual propio.
- Sombras y radios idénticos en todas las superficies.
- Gráficos, líneas o métricas decorativas sin datos reales.
- Emojis como reemplazo de títulos, categorías o navegación.

### 1.2 Orientación visual para Archive Workbench

El sitio y la documentación pueden tomar referencias de instrumentos archivísticos, publicaciones académicas, catálogos, ediciones documentales y visualización científica.

- La jerarquía se construye con tipografía, espacio, numeración y estructura.
- La paleta se usa para distinguir estados, capas o tipos documentales con una justificación estable.
- Las redes y grafos siguen convenciones de análisis de redes y muestran dirección, tipo y procedencia.
- Las figuras deben poder leerse sin conocer la implementación.
- La densidad de información se controla mediante divulgación progresiva, no mediante eliminación de trazabilidad.
- El sitio público prioriza lectura y orientación; la interfaz de trabajo puede mostrar mayor densidad cuando la tarea lo requiere.

### 1.3 Tipografía y composición

- Evitar una única sans-serif de sistema aplicada sin criterio a todo el sitio.
- Elegir familias con buena lectura en español, cifras claras y signos suficientes.
- Usar una combinación tipográfica limitada y coherente.
- Mantener anchos de lectura razonables en prosa extensa.
- Reservar monoespaciada para comandos, rutas, identificadores y contratos.
- No convertir cada párrafo en una tarjeta.

### 1.4 Capturas y visualización de datos

- Las capturas deben ser reales y reproducibles.
- Los recortes deben conservar contexto suficiente para ubicar la acción.
- Los datos personales o restringidos se ocultan mediante un procedimiento documentado o se reemplazan por una base de demostración.
- Las flechas, leyendas, escalas y etiquetas deben ser visibles.
- Los colores no pueden ser el único código para diferenciar categorías.

## 2. Escritura y prosa

### 2.1 Patrones retóricos a eliminar

- Binarios de contraste usados como tic: “no es X, es Y”.
- Cierres aforísticos o frases diseñadas para sonar citables.
- Anuncios vacíos de importancia: “esto es crucial”, “vale la pena destacar”.
- Narración de la estructura en lugar de una estructura clara.
- Simetrías repetidas de cláusulas para producir énfasis artificial.
- Anticipar una objeción que nadie planteó solo para rebatirla.
- Inflar el alcance de una función o presentar cada cambio como transformador.
- Ganchos de suspenso en documentación técnica.
- Guiones largos usados como muletilla para toda aclaración.
- Resúmenes finales obligatorios cuando el texto ya terminó.

### 2.2 Léxico y registro

Evitar lenguaje de producto y marketing: revolucionario, potente, next-gen, seamless, desbloquear, empoderar, solución integral y expresiones equivalentes sin contenido verificable.

Evitar muletillas frecuentes de prosa generada: “cabe destacar”, “en el mundo actual”, “juega un papel fundamental”, “a la hora de”, “en definitiva”, “por otro lado” como apertura automática y “no se trata solo de”.

La prosa pública debe ser directa, concreta y verificable. Cada afirmación describe qué hace el sistema, sobre qué datos opera y qué limitación tiene.

### 2.3 Español rioplatense

- La prosa expositiva usa registro impersonal o tercera persona.
- Las instrucciones puntuales usan voseo: elegí, abrí, revisá, guardá.
- No mezclar voseo, tuteo y usted dentro del mismo documento.
- No forzar lunfardo ni oralidad porteña.
- Usar computadora, archivo, celular y términos habituales en Argentina.
- Evitar vosotros, ordenador, fichero, móvil y otras marcas peninsulares cuando no sean términos citados.

### 2.4 Terminología archivística y técnica

- Usar archivo, fondo, sección, serie, unidad documental, autoridad, productor, gestor, procedencia y evidencia con precisión.
- Explicar las diferencias entre original, derivado, corrida, candidata, selección canónica y capa editable.
- No usar “documento” para cualquier entidad si el modelo distingue página, objeto digital, parte o unidad archivística.
- Atribuir las relaciones analíticas a su evidencia y procedencia.
- No presentar una propuesta automática como decisión humana.

## 3. Diseño de tutoriales y guías

- Indicar sección, pestaña, bloque y control literal.
- Introducir una función nueva antes de pedir una acción.
- Separar pasos que ocurren en lugares distintos.
- Mostrar el resultado esperado con el mismo texto que usa la interfaz.
- Verificar que una imagen o panel exista en la candidata antes de pedir que se observe.
- Usar diagnósticos automáticos para listas extensas o estados internos.
- No pedir al lector que deduzca si una acción quedó guardada.

## 4. Sitio público y README

El sitio debe resultar reconocible como documentación de una herramienta archivística y de investigación. Debe evitar la apariencia de un SaaS genérico.

El README tendrá una entrada accesible, capturas reales, instalación, quickstart, mapa de capacidades, límites, documentación y licencia. Las funciones avanzadas se enlazan a páginas específicas en lugar de acumularse en una lista sin contexto.

La referencia técnica puede ser densa, pero debe mantener definiciones, enlaces internos y ejemplos de contratos. El tutorial usa tareas concretas y reduce la carga técnica visible.

## 5. Checklist antes de entregar

1. ¿La pieza puede pertenecer a cualquier producto genérico? Rediseñar para el dominio archivístico.
2. ¿Hay gradientes, tarjetas o sombras aplicados por costumbre? Retirarlos o justificarlos.
3. ¿Las capturas son reales y reproducibles?
4. ¿La página distingue propuestas, automatismos y decisiones humanas?
5. ¿La terminología corresponde al modelo actual?
6. ¿Hay frases de marketing, cierres aforísticos o anuncios vacíos de importancia?
7. ¿El registro es consistente y usa voseo solo en instrucciones?
8. ¿Cada acción nueva está ubicada mediante su ruta y etiqueta literal?
9. ¿La información técnica tiene una fuente pública única y enlazada?
10. ¿El contenido evita exponer materiales restringidos o datos personales?
"""


def _append_once(path: Path, marker: str, block: str) -> bool:
    text = path.read_text(encoding="utf-8")
    if marker in text:
        return False
    path.write_text(text.rstrip() + block + "\n", encoding="utf-8")
    return True


def _create_once(path: Path, content: str) -> bool:
    if path.exists():
        return False
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    return True


def update(root: Path) -> list[str]:
    assistant = root / ".assistant"
    if not assistant.is_dir():
        raise SystemExit(f"No existe la carpeta privada esperada: {assistant}")

    required = [
        assistant / "00_LEER_PRIMERO.md",
        assistant / "01_INTERACCION_Y_GUIADO.md",
        assistant / "05_CRITERIOS_INTERFAZ.md",
    ]
    missing = [path for path in required if not path.is_file()]
    if missing:
        formatted = "\n".join(f"- {path}" for path in missing)
        raise SystemExit("Faltan documentos privados canónicos:\n" + formatted)

    messages: list[str] = []
    for name, block in OCR_BLOCKS.items():
        path = assistant / name
        marker = block.strip().splitlines()[0]
        changed = _append_once(path, marker, block)
        messages.append(("Actualizado: " if changed else "Sin cambios: ") + str(path))

    first = assistant / "00_LEER_PRIMERO.md"
    changed = _append_once(first, "<!-- PUBLIC_SITE_POLICIES -->", READ_FIRST_BLOCK)
    messages.append(("Actualizado: " if changed else "Sin cambios: ") + str(first))

    for name, content in {
        "POLITICA_SITIO_PUBLICO.md": PUBLIC_SITE_POLICY,
        "LINEAMIENTOS_DE_DISENO_Y_ESCRITURA.md": DESIGN_WRITING_POLICY,
    }.items():
        path = assistant / name
        changed = _create_once(path, content)
        messages.append(("Creado: " if changed else "Sin cambios: ") + str(path))

    return messages


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    for message in update(root):
        print(message)


if __name__ == "__main__":
    main()
