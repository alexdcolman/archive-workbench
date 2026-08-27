# Actualización actual - Archive Workbench 0.89.0 RC74

## Alcance de RC74

RC74 corrige el primer fallo material encontrado al construir la imagen CPU de `OPS-01`.

La construcción de RC73 llegó a copiar `llama-server`, pero falló al ejecutar `llama-server --version` porque el cargador dinámico no encontraba `libllama-server-impl.so`. El stage upstream de `llama.cpp` coloca el servidor y sus bibliotecas compartidas en `/app`; Archive Workbench copia ese directorio completo a `/opt/llama`. RC74 agrega `/opt/llama` a la ruta de bibliotecas de ambas imágenes y verifica durante el build que `libllama-server-impl.so` esté presente antes de ejecutar el servidor.

Los tags cambian para distinguir esta corrección de RC73:

- CPU: `ghcr.io/alexdcolman/archive-workbench:0.89.0-rc74-cpu`;
- NVIDIA GPU: `ghcr.io/alexdcolman/archive-workbench:0.89.0-rc74-gpu`.

En CPU, `LD_LIBRARY_PATH` es `/opt/llama`. En GPU es `/opt/llama:/usr/local/cuda/lib64`, de modo que se añade la carpeta de `llama.cpp` sin retirar la ruta CUDA definida por la imagen base de NVIDIA.

No cambia la aplicación, SQLite, el modelo de proyecto ni `ArchiveWorkbenchData`. No hay migración y continúa `0047_authority_relation_profiles`.
`WEB-01` permanece parcial y queda pausado hasta completar la distribución multiplataforma y retomar la reescritura integral del sitio.
No se incorporan capturas hasta realizar esa reescritura.
La revisión futura se hará completa para lectores sin conocimiento previo del software.

## Estado de validación material

El build CPU de RC73 falló y no produjo una imagen. RC74 debe repetir primero el build CPU en el equipo de Alex. Si termina correctamente, la misma tanda comprobará la versión de Archive Workbench, `llama-server`, PyTorch CPU de Surya y la existencia de una imagen local utilizable. Después se inicia la aplicación con Compose y se hace una extracción Surya real sobre un documento pequeño.

La imagen GPU no se construye hasta que CPU quede verde. Luego se repetirá el gate básico y se agregarán comprobación NVIDIA, extracción Surya CUDA y una transcripción audiovisual corta.

## Gate automatizado focal

La suite completa corresponde exclusivamente a Alex. El gate focal de RC74 es:

```bash
pytest -q tests/test_container_distribution.py tests/test_surya_extraction.py tests/test_documentation.py tests/test_packaging.py
pytest --collect-only -q
```

## Actualización desde RC73

Usar `scripts/apply_candidate_update.py` incluido en el paquete. No ejecutar `db-upgrade`.
