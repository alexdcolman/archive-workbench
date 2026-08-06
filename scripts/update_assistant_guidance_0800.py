#!/usr/bin/env python3
"""Actualiza de forma idempotente las reglas privadas de guiado y UX para OCR-01C."""

from __future__ import annotations

from pathlib import Path

_MARKER_GUIDE = "<!-- OCR01C_GUIDED_MANUAL_VALIDATION -->"
_MARKER_UX = "<!-- OCR01C_LAYOUT_UX -->"
_MARKER_TESTS = "<!-- OCR01C_DIAGNOSTIC_COMMANDS -->"
_MARKER_HISTORY_GUIDE = "<!-- OCR01C_HISTORY_DISAMBIGUATION -->"
_MARKER_HISTORY_UX = "<!-- OCR01C_HISTORY_UX_DISAMBIGUATION -->"


_GUIDE = f"""

{_MARKER_GUIDE}
## Validaciones manuales de funciones nuevas

Toda instrucción debe ubicar primero la acción mediante la sección principal, el
documento, la pestaña o panel y la etiqueta literal del control. No se deben
agrupar en una sola oración acciones que obliguen a pasar por lugares distintos.
Cada control nuevo debe explicarse como si la persona todavía no lo conociera.

Cuando se pida revisar un historial, la guía debe enumerar las frases exactas que
aparecen en la columna visible `acción`. Antes de pedir una comparación visual,
la candidata debe comprobar que la imagen aparece realmente en esa pantalla y
en la base descartable utilizada.
"""

_UX = f"""

{_MARKER_UX}
## Orden y estructura: complejidad y referencia visual

La pestaña `Orden y estructura` debe presentar un recorrido numerado, mantener
visible el objeto seleccionado y agrupar en una sola acción las operaciones que
forman una tarea conceptual única. Crear una columna para un objeto no debe
obligar a buscar por separado los controles de creación y asignación.

El historial debe usar frases humanas y no códigos internos. La pantalla debe
conservar una referencia visual de la página incluso cuando todavía no exista
un derivado de previsualización; en ese caso puede usar una copia cacheada del
original sin modificarlo. La implementación funcional de OCR-01C no cierra la
revisión general de UX-02.
"""
_HISTORY_GUIDE = f"""

{_MARKER_HISTORY_GUIDE}
## No confundir historiales ni controles nuevos

Antes de pedir una comprobación, la guía debe distinguir de manera literal entre
una pestaña general y un bloque interno con nombres parecidos. Debe indicar la
ruta completa y el nombre exacto visible, por ejemplo: `Revisar documentos >
Orden y estructura > 4. Historial de Orden y estructura`. Nunca debe pedir que
el usuario busque una frase en una pantalla distinta ni asumir que una acción
previa fue realizada si no apareció explícitamente en la guía vigente.

Las frases visibles que se pidan comprobar deben haber sido verificadas contra
el código o una captura de la misma candidata. Cuando el estado pueda validarse
por comando, la inspección manual de listas extensas no debe trasladarse al
usuario.
"""

_HISTORY_UX = f"""

{_MARKER_HISTORY_UX}
## Historial general e historiales específicos

Los historiales de alcance distinto deben tener nombres inequívocos. La pestaña
de auditoría completa se denomina `Historial general`; los historiales propios
de una tarea deben permanecer dentro de esa tarea y declarar explícitamente su
alcance. Las validaciones no deben exigir recorrer manualmente un historial
general largo para comprobar operaciones de una sola función.
"""


_TESTS = f"""

{_MARKER_TESTS}
## Diagnósticos posteriores a validaciones manuales

Los comandos entregados al usuario deben imprimir primero el estado real y
explicar cada control fallido. No se deben usar `assert` sin mensaje como
interfaz de diagnóstico. Cualquier `exit` de un bloque destinado a una terminal
interactiva debe quedar encapsulado en una subshell.
"""


def _append_once(path: Path, marker: str, block: str) -> bool:
    text = path.read_text(encoding="utf-8")
    if marker in text:
        return False
    path.write_text(text.rstrip() + block + "\n", encoding="utf-8")
    return True


def update(repository_root: Path) -> list[Path]:
    assistant = repository_root / ".assistant"
    required = {
        assistant / "01_INTERACCION_Y_GUIADO.md": [
            (_MARKER_GUIDE, _GUIDE),
            (_MARKER_HISTORY_GUIDE, _HISTORY_GUIDE),
        ],
        assistant / "05_CRITERIOS_INTERFAZ.md": [
            (_MARKER_UX, _UX),
            (_MARKER_HISTORY_UX, _HISTORY_UX),
        ],
        assistant / "03_POLITICA_DE_PRUEBAS.md": [(_MARKER_TESTS, _TESTS)],
    }
    missing = [path for path in required if not path.is_file()]
    if missing:
        formatted = "\n".join(f"- {path}" for path in missing)
        raise SystemExit(
            "No se modificó .assistant porque faltan documentos canónicos:\n" + formatted
        )
    changed: list[Path] = []
    for path, blocks in required.items():
        path_changed = False
        for marker, block in blocks:
            if _append_once(path, marker, block):
                path_changed = True
        if path_changed:
            changed.append(path)
    return changed


def main() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    changed = update(repository_root)
    if changed:
        print("Documentos .assistant actualizados:")
        for path in changed:
            print(f"- {path.relative_to(repository_root)}")
    else:
        print(".assistant ya contenía las reglas OCR-01C; no hubo cambios.")


if __name__ == "__main__":
    main()
