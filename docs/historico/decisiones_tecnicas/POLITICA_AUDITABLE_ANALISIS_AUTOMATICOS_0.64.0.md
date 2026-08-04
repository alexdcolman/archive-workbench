# Política auditable para análisis automáticos — 0.64.0

## Problema

Los filtros de calidad existían en exportación, búsqueda semántica y sugerencias de menciones, pero una llamada programática todavía podía ampliar el alcance sin dejar evidencia persistente. Las funciones futuras —descubrimiento, importaciones asistidas, herramientas LLM, RAG o integraciones— también corrían el riesgo de implementar reglas propias e incompatibles.

## Decisión

Todo análisis automático debe declarar un tipo registrado y un alcance de estados de página. El alcance seguro es `approved`. Cualquier otro conjunto, incluido el conjunto vacío que significa todos los estados, requiere simultáneamente:

- confirmación explícita;
- persona responsable;
- fundamento no vacío;
- origen de la ejecución;
- registro persistente de la autorización.

La política se centraliza en `analysis_quality.py`. Los tipos desconocidos se rechazan: una función nueva debe incorporarse primero al registro común.

## Persistencia

La migración `0034_automatic_analysis_authorizations` agrega `automatic_analysis_authorizations`. Cada fila conserva:

- versión de la política;
- tipo de análisis;
- estados incluidos y clave de alcance;
- responsable y fundamento;
- interfaz, terminal, API o script de origen;
- tipo e identificador del destino cuando existen;
- SHA-256 de los parámetros canónicos;
- fecha de creación.

El registro es append-only desde el dominio: guardar nuevamente un perfil agrega otra autorización y no modifica la anterior. La migración no fabrica autorizaciones retrospectivas para operaciones históricas que nunca las registraron.

La autorización de un perfil se vincula con una huella canónica de sus parámetros funcionales, no con una aceptación genérica. Exportar, previsualizar un corpus, construir un índice semántico o consultarlo exige una fila vigente que coincida con tipo, destino, estados y huella. Cambiar la configuración invalida esa capacidad hasta guardar nuevamente el perfil. Archivar y restaurar no alteran los parámetros funcionales y, por sí solos, no invalidan la autorización.

## Aplicación actual

La política es obligatoria para perfiles de exportación, perfiles de búsqueda semántica y sugerencias automáticas de menciones. La interfaz expone la auditoría en Administración; la terminal la expone mediante `analysis-quality-audit`.

Resúmenes, estadísticas, descubrimiento abierto, importaciones asistidas, herramientas LLM, RAG e integraciones quedan registrados como tipos contractualmente preparados. Cuando se implementen, deberán usar el mismo validador y registro; no se considera aceptable una ruta paralela.

## Formularios Streamlit

La confirmación se valida después del envío. Un botón dentro de `st.form` nunca depende de que un widget del mismo formulario provoque un rerender. Para controles fuera de formularios puede usarse habilitación reactiva, siempre que la operación vuelva a validar todas las condiciones al ejecutarse.
