# Actualización actual — Archive Workbench 0.87.0

**Estado:** versión final preparada tras validar `INT-01` · **fecha:** 2026-08-08

## Alcance

La versión 0.87.0 agrega Google Drive como transporte opcional dentro de **Intercambiar cambios**. Drive mueve paquetes ZIP de intercambio ya existentes; no sincroniza la base del proyecto y no aplica cambios por sí solo.

Durante la validación, RC2 corrigió el generador descartable: RC1 creaba las bases y el paquete correctamente, pero omitía `config/decisions.yaml`, de modo que `review-app` rechazaba la copia receptora antes de iniciar. La versión final conserva esa corrección y copia la configuración estándar y reemplaza su identidad por `int01-google-drive-validation`; no cambia el transporte Drive ni el esquema de base.

El panel **Google Drive (opcional)** permanece cerrado por defecto. Permite conectar una cuenta mediante OAuth de escritorio con permiso `drive.file`, subir un paquete validado, elegir un ZIP mediante Google Picker, descargarlo a `exchange/drive_downloads/`, verificar su SHA-256 y comparar el manifiesto con la copia local. Sólo después queda disponible **Simular evaluación del paquete descargado**, que reutiliza el dry-run existente.

Las credenciales y el token OAuth viven fuera del repositorio y fuera del proyecto, bajo `~/.config/archive-workbench/`. No deben copiarse a Git ni a los paquetes de intercambio.

## Persistencia y migración

`INT-01` no agrega tablas ni modifica contratos canónicos. La revisión de base continúa en `0046_audiovisual_timeline_annotations`.

**0.87.0 no requiere `db-upgrade`.** La validación de Google Drive se realizó sobre una copia emisora y una receptora descartables creadas desde cero; `project_data` no participó en esa prueba.

## Validación cerrada

La validación real de RC2 se realizó sobre dos proyectos descartables creados desde cero. Confirmó:

1. conexión OAuth con el permiso `drive.file`;
2. subida de un bundle válido desde la copia emisora;
3. selección del mismo ZIP con Google Picker;
4. descarga atómica y verificación local en la copia receptora;
5. SHA-256 idéntico al bundle emitido (`9386824cb404cbba46b57152040ac1c0bbf74086d4729b7cda682c0957997beb`);
6. mismo proyecto, otra identidad de copia, revisión `0046_audiovisual_timeline_annotations` y base común exacta;
7. dry-run existente con `base_match_status: matched`, método `exact_checkpoint` y resultado `overall_status: empty`;
8. `quick_check: ok`, cero violaciones de claves foráneas y ninguna descarga inválida.

La descarga no aplicó cambios. `project_data` quedó fuera del recorrido y continuó en `0046_audiovisual_timeline_annotations` con sus conteos previos. `INT-01` queda cerrado en 0.87.0.

No hay migración de base para esta versión. **No ejecutar `db-upgrade` por 0.87.0.**
