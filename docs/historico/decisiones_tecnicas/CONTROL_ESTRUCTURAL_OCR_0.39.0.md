# Control estructural OCR — versión 0.39.0

## 1. Motivo

La evaluación de Surya documentada en `EVALUACION_SURYA_OCR_0.38.0.md` mostró una mejora muy grande en texto corrido, orden de lectura y segmentación. También dejó dos riesgos específicos que no pueden resolverse evaluando solamente cantidad de caracteres, confianza o solapamiento de bounding boxes:

1. los ordinales legales pueden convertirse en números de dos cifras, por ejemplo `4º` → `49`;
2. los formularios pueden conservar los rótulos pero perder la relación entre cada casillero y su estado.

La versión 0.39.0 agrega un primer control estructural conservador. No modifica el OCR, no corrige el texto, no selecciona candidatas y no crea estados canónicos automáticamente.

## 2. Evidencia que originó las reglas

En `caja_administracion_publica_carp_reg`, página 8, Surya reconstruyó correctamente el cuerpo del decreto, pero produjo la secuencia:

```text
Artículo 49
Artículo 50
Artículo 62
Artículo 72
Artículo 82
Artículo 92
```

La imagen mostraba ordinales de un solo dígito. La regla nueva detecta secuencias de encabezados cuyo primer dígito avanza de manera consecutiva mientras los números completos no forman una secuencia ordinaria. La aplicación muestra la lectura posible (`4º`, `5º`, etc.) únicamente como alerta revisable.

En `leg_17_leg_15_a_c_6`, Surya recuperó la estructura general de la ficha, sus rótulos y varias marcas `X`. Sin embargo, el texto plano no expresaba de forma segura qué opciones estaban marcadas. La regla nueva reconoce símbolos explícitos y marcas pequeñas próximas a un rótulo, y las presenta como candidatos de estado.

## 3. Integración

El control se integra en la evaluación de calidad ya existente:

```text
Procesamiento
→ Selección canónica
→ Evaluar calidad de las versiones visibles
→ Ver indicadores del control automático
```

No se crea una pestaña nueva ni un flujo paralelo. Las evaluaciones siguen siendo append-only en `extraction_page_quality_assessments`; la versión del algoritmo pasa a `page_quality_v2`.

## 4. Ordinales legales dudosos

La regla exige al menos tres encabezados de artículo compatibles con el patrón observado. Evita marcar una secuencia legal normal como `49`, `50`, `51`.

Cuando se activa, la interfaz muestra:

- texto OCR detectado;
- lectura ordinal posible;
- motivo de la alerta.

La lectura posible nunca reemplaza el texto original. La corrección, si corresponde, debe hacerse durante la revisión humana.

## 5. Casilleros y marcas

El primer bloque reconoce:

- controles `checkbox` o `radio` conservados en el HTML crudo de Surya, incluso cuando no producen texto visible;
- símbolos combinados con su rótulo, por ejemplo `☒ Secreto`, `☐ Reservado` o `[x] Urgente`;
- marcas pequeñas separadas —por ejemplo una `X`— próximas espacialmente a otro bloque textual;
- asociaciones por orden de lectura cuando no hay geometría suficiente.

Cada resultado conserva:

- estado candidato: `marked` o `unmarked`;
- marca observada;
- rótulo asociado, si pudo inferirse;
- método de asociación.

La interfaz los traduce como “Marcado (candidato)” o “No marcado (candidato)”. No se presenta ninguna inferencia como hecho confirmado.

## 6. Límites deliberados

Este bloque no puede detectar con seguridad un casillero vacío que no produzca ningún objeto OCR ni control en el HTML crudo. Tampoco interpreta tablas completas, líneas del formulario ni agrupaciones semánticas entre opciones mutuamente excluyentes.

La alerta de ordinales trabaja sobre patrones textuales y secuencias de página. Puede producir falsos positivos en documentos legales con numeración realmente discontinua; por eso no aplica correcciones automáticas.

## 7. Decisión de diseño

Archive Workbench tratará ordinales y casilleros como estructuras revisables, no como texto ordinario ni como valores canónicos generados por OCR. La versión 0.39.0 instala la detección y la presentación; una etapa posterior podrá permitir confirmar manualmente estados `marcado`, `no marcado` o `indeterminado` con auditoría.

## 8. Próximos pasos

- confirmar y editar estados de casilleros dentro de la capa editable;
- representar grupos de opciones y campos de formulario;
- vincular cada alerta con un resaltado específico sobre la imagen;
- construir verdad terreno y medir CER/WER por backend;
- evaluar lotes mayores con el servidor Surya persistente.
