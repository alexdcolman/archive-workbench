# Evaluación empírica de Surya OCR 2 y propuesta de adopción preferida

**Fecha de prueba:** 30 de julio de 2026  
**Archive Workbench:** 0.37.1  
**Surya:** `surya-ocr==0.22.1`  
**Equipo:** NVIDIA GeForce RTX 3090, 24 GB de VRAM  
**Configuración efectiva:** VLM de Surya mediante vLLM y Docker en GPU; modelos auxiliares Torch en CPU.

## 1. Objetivo

La prueba buscó responder cuatro preguntas operativas:

1. si Surya mejora de manera consistente la extracción producida por los perfiles vigentes;
2. si conserva layout, bounding boxes y orden de lectura en páginas difíciles;
3. si puede ejecutarse realmente en la RTX 3090 del equipo objetivo;
4. si su costo de arranque y de memoria permite convertirlo en el backend preferido de Archive Workbench.

No es un benchmark estadístico ni una medición de CER/WER: no se preparó una transcripción de verdad terreno carácter por carácter. La evaluación combina comparación visual de las imágenes, diff contra la selección vigente, inspección de bounding boxes y logs de ejecución.

## 2. Corpus de prueba

Se probaron seis páginas con problemas distintos:

| Documento | Página | Dificultad principal |
|---|---:|---|
| `leg_17_caso_bolson` | 4 | Texto impreso, ilustración y dedicatoria manuscrita parcialmente tapada |
| `leg_17_caso_bolson` | 1 | Copia mecanografiada deteriorada, manchas y caracteres débiles |
| `leg_17_caso_bolson` | 2 | Deterioro fuerte, bloques largos y encabezados parcialmente perdidos |
| `caja_administracion_publica_carp_reg` | 8 | Muy mala orientación, ruido y texto legal mecanografiado |
| `caja_administracion_publica_carp_reg` | 16 | Telegrama degradado, abreviaturas y encabezado poco legible |
| `leg_17_leg_15_a_c_6` | 1 | Ficha/formulario con casilleros, sellos, campos y texto preimpreso |

## 3. Resultado operativo

### 3.1. Primera página

La primera corrida sobre `leg_17_caso_bolson`, página 4, produjo:

- 1 página;
- 8 objetos;
- 534 caracteres;
- 0 fallos.

El VLM utilizó inequívocamente la GPU. El monitoreo registró un pico de 100% de utilización y aproximadamente 22,9 GB de VRAM. vLLM informó 211,8 tokens/s de entrada y 22,4 tokens/s de generación para la solicitud efectiva.

### 3.2. Lotes adicionales

| Lote | Páginas | Objetos | Caracteres | Duración total |
|---|---:|---:|---:|---:|
| `leg_17_caso_bolson`, páginas 1–2 | 2 | 23 | 3043 | 234 s |
| `caja_administracion_publica_carp_reg`, páginas 8 y 16 | 2 | 27 | 2308 | 235 s |
| `leg_17_leg_15_a_c_6`, página única | 1 | 13 | 958 | 226 s |

Las tres corridas tardaron casi lo mismo pese a procesar cantidades distintas de páginas. La conclusión operativa es clara: el costo dominante no es la inferencia por página, sino iniciar el contenedor, cargar el modelo, compilar y calentar vLLM. Reiniciar el servidor en cada corrida vuelve ineficiente el uso interactivo.

## 4. Evaluación cualitativa por página

### 4.1. `leg_17_caso_bolson`, página 4

Surya reconstruyó correctamente el cuerpo impreso, el título `Aziz`, el orden de lectura, la ilustración y la dedicatoria manuscrita. La selección vigente contenía abundante ruido y fragmentación.

El único error claro fue:

```text
Cara Karina con inmenso cariño
```

La imagen dice `Para Karina con inmenso cariño`, pero la parte decisiva de la `P` está tapada por otra hoja. El error es menor y explicable por la evidencia visual.

**Evaluación:** mejora extraordinaria; no se observó invención extensa.

### 4.2. `caja_administracion_publica_carp_reg`, página 8

Surya recompuso párrafos completos y el orden lógico de una página mal orientada. La selección vigente estaba fragmentada en más de cien líneas con ruido, sílabas partidas y secuencias sin sentido.

Apareció un error sistemático relevante en los ordinales de los artículos. El glifo `º` se incorporó como cifra o se confundió con otro número:

```text
Artículo 4º  → Artículo 49
Artículo 5º  → Artículo 50
Artículo 6º  → Artículo 62
Artículo 7º  → Artículo 72
Artículo 8º  → Artículo 82
Artículo 9º  → Artículo 92
```

El cuerpo de cada artículo quedó, en cambio, muy bien recuperado.

**Evaluación:** superior para texto y layout; requiere una alerta o corrección revisable para ordinales legales.

### 4.3. `caja_administracion_publica_carp_reg`, página 16

Surya recuperó el telegrama como bloques coherentes y preservó las líneas principales:

- origen y destino;
- número;
- carácter reservado/urgente;
- cuerpo del mensaje;
- códigos finales.

Los errores se concentraron en zonas muy degradadas del encabezado y en abreviaturas (`RAWSON`, `GHO`, `TTIO:AC`, etc.). El cuerpo principal fue reconocido con mucha mayor continuidad que la selección vigente.

**Evaluación:** mejora fuerte; los errores residuales son localizados y revisables.

### 4.4. `leg_17_caso_bolson`, página 1

Surya reconstruyó párrafos enteros, nombres propios, firma y cargo. Persistieron sustituciones locales como:

```text
averliquaciones
anarcipto
comfirmar
Na todo cuanto...
```

También resolvió correctamente numerosos términos que la selección vigente había destruido o separado.

**Evaluación:** mejora muy importante; necesita corrección humana fina, no reconstrucción manual completa.

### 4.5. `leg_17_caso_bolson`, página 2

La mejora fue especialmente grande. Surya recompuso el encabezado, el objeto del informe y cinco bloques narrativos largos. Persisten errores puntuales (`hallido`, `veriguaciones`, `esistencia`) y algunas lecturas dudosas de nombres o siglas.

No se observó una expansión inventada sin anclaje en la página. Los errores siguen el patrón esperable de sustitución de caracteres en una copia deteriorada.

**Evaluación:** mejora decisiva para continuidad textual y orden de lectura.

### 4.6. `leg_17_leg_15_a_c_6`, ficha compleja

Surya identificó correctamente la estructura general del formulario:

- encabezado;
- lugar, fecha y número de mensaje;
- destinatario y remitente;
- asunto;
- cuerpo;
- campos de circulación;
- nota final;
- sellos y zonas separadas mediante bounding boxes.

La limitación principal no está en detectar el layout, sino en representar el estado semántico de los casilleros. El texto plano enumera etiquetas, pero no expresa de forma confiable qué opciones están marcadas y cuáles no. Por ejemplo, reconocer `Secreto`, `Confidencial`, `Reservado`, `Público`, `Urgente` o `Simple` no equivale a registrar `marcado/no marcado`.

**Evaluación:** muy buen layout; falta una capa específica para formularios y casillas.

## 5. Conclusiones

1. Surya fue claramente superior a la selección vigente en las seis páginas examinadas.
2. La mejora no se limita al OCR: también recompone bloques, continuidad de párrafos, orden de lectura y geometría.
3. La RTX 3090 puede ejecutar el VLM de Surya 2, aunque el perfil observado consume casi toda la VRAM disponible.
4. La configuración estable para este equipo es híbrida:
   - VLM de OCR/layout en GPU mediante vLLM y Docker;
   - detector y modelos auxiliares Torch en CPU;
   - entorno de Surya separado de la `.venv` principal.
5. El costo principal es el arranque de vLLM. Mantener el servidor vivo entre corridas es obligatorio para que Surya sea cómodo en uso real.
6. Surya no debe modificar automáticamente la selección canónica. Su salida continúa siendo una candidata que debe compararse y adoptarse explícitamente.
7. Docling/Tesseract siguen siendo necesarios como fallback para equipos sin runtime Surya, falta de GPU, errores del servidor o tareas específicas.

## 6. Decisión de diseño

A partir de esta prueba se adopta la siguiente política:

```text
Surya disponible y operativo
→ backend preferido

Surya no instalado, backend no disponible o corrida fallida
→ fallback automático Docling/Tesseract

Resultado de cualquier backend
→ candidata no canónica
→ comparación humana
→ adopción explícita
```

Esta política no declara que Surya sea infalible. Declara que, en el corpus real probado, ofrece una base de revisión mucho mejor y reduce de forma drástica el trabajo de reconstrucción manual.

## 7. Propuesta implementada en 0.38.0

La versión 0.38.0 implementa:

1. **Perfil preferido por defecto.** `config/extraction.yaml` pasa a usar Surya.
2. **Fallback explícito.** El perfil preferido referencia `config/extraction_docling_es.yaml`; si el entorno de Surya no está listo, Archive Workbench usa ese perfil y lo informa.
3. **Fallback de ejecución.** Si una corrida Surya falla para un documento, se conserva el intento fallido y se ejecuta el fallback para ese documento. La recuperación queda registrada como advertencia, no se oculta.
4. **Servidor persistente.** Surya se ejecuta con `--keep_server`, para reutilizar vLLM entre corridas y evitar repetir la carga y el warmup.
5. **Gestión explícita del servidor.** Se agregan comandos para consultar y detener los contenedores persistentes:

```bash
archive-workbench surya-server-status
archive-workbench surya-server-stop
```

6. **Configuración híbrida reproducible.** El perfil fija `TORCH_DEVICE=cpu` para los modelos auxiliares y limpia `LD_LIBRARY_PATH` en el subproceso de Surya. El VLM continúa usando vLLM/NVIDIA.
7. **Diagnóstico corregido.** `extraction-doctor` separa la disponibilidad del backend VLM de la ejecución de los modelos auxiliares y deja de interpretar un fallo local de cuDNN como caída de toda la ruta GPU.
8. **Interfaz explícita.** La app informa que el servidor quedará vivo, que puede reservar VRAM y cuál es el fallback configurado.
9. **Actualización explícita de proyectos existentes.** La versión no sobrescribe perfiles locales: cada proyecto adopta esta política al copiar deliberadamente los tres perfiles estándar, con respaldo previo de sus archivos.

## 8. Pendientes derivados de la prueba

- representar casilleros como campos con estado `marcado/no marcado/indeterminado`;
- detectar y proponer correcciones de ordinales legales sin aplicarlas silenciosamente;
- medir tiempo por página con el servidor ya caliente;
- construir una muestra pequeña con verdad terreno para calcular CER/WER;
- evaluar lotes mayores y presión de VRAM;
- estudiar orientación y deskew conservadores antes del OCR;
- comprobar si distintas variantes del derivado mejoran páginas particulares sin degradar las demás.


## 10. Addendum de implementación 0.38.1

La validación posterior detectó que un perfil Surya configurado con `device: cpu` y `surya_torch_device: auto` podía intentar la comprobación auxiliar sobre CUDA si Torch la encontraba disponible en el host. La versión 0.38.1 corrige la resolución para que el dispositivo auxiliar siga al backend explícito cuando no existe una anulación específica, sin modificar la configuración híbrida usada en las pruebas de este informe.
