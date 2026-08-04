from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any


def request_tab(st, *, key: str, label: str) -> None:
    """Solicita abrir una pestaña en el siguiente rerun.

    La clave pendiente evita modificar el estado de un widget después de haberlo
    instanciado en el mismo ciclo de Streamlit.
    """

    st.session_state[f"{key}__pending"] = label


def tracked_tabs(
    st,
    labels: Sequence[str],
    *,
    key: str,
    default: str | None = None,
):
    """Crea pestañas cuyo estado persiste en todos los reruns.

    Requiere Streamlit 1.55 o posterior, donde ``st.tabs`` puede registrar la
    pestaña activa mediante ``key`` y ``on_change='rerun'``.
    """

    options = list(labels)
    if not options:
        raise ValueError("tracked_tabs requiere al menos una pestaña")

    pending_key = f"{key}__pending"
    pending = st.session_state.pop(pending_key, None)
    current = st.session_state.get(key)
    if pending in options:
        # La solicitud programática debe sobrevivir también al rerun siguiente.
        current = pending
    elif current not in options:
        current = default if default in options else options[0]

    if current not in options:
        current = options[0]
    st.session_state[key] = current
    default = current

    return st.tabs(
        options,
        default=default,
        key=key,
        on_change="rerun",
    )


def isolated_view(st, *, mode: str):
    """Devuelve un contenedor identificado para integraciones externas.

    La aplicación principal ya no monta fragmentos dentro de este contenedor. Un
    fragmento que escribe en un contenedor creado fuera de él puede conservar restos
    visuales durante la transición a otra vista. ``fragmented_view`` crea ahora el
    contenedor raíz dentro del propio fragmento.
    """

    normalized = "".join(character if character.isalnum() else "_" for character in mode)
    return st.container(key=f"archive_workbench_view_{normalized}")


def fragmented_view(
    st,
    render: Callable[..., Any],
    /,
    *args,
    mode: str | None = None,
    **kwargs,
) -> Any:
    """Renderiza la vista activa dentro de un fragmento autocontenido.

    Las interacciones ordinarias vuelven a ejecutar únicamente el fragmento. Cuando
    se proporciona ``mode``, el contenedor raíz se crea dentro del fragmento: así sus
    elementos se limpian en cada rerun local y la navegación completa no hereda un
    árbol visual perteneciente a la vista anterior.
    """

    normalized = (
        "".join(character if character.isalnum() else "_" for character in mode)
        if mode is not None
        else None
    )

    def render_fragment() -> Any:
        if normalized is None:
            return render(*args, **kwargs)
        with st.container(key=f"archive_workbench_view_{normalized}"):
            return render(*args, **kwargs)

    fragment = st.fragment(render_fragment)
    return fragment()


def rerun_view(st) -> None:
    """Actualiza únicamente la vista activa después de una acción local.

    La llamada se realiza desde una interacción dentro del fragmento. El fallback
    mantiene compatibilidad defensiva con una ejecución directa del renderer en
    pruebas o integraciones que no hayan montado todavía el fragmento.
    """

    try:
        st.rerun(scope="fragment")
    except TypeError:  # dobles de prueba o adaptadores anteriores sin parámetro scope
        st.rerun()
    except Exception as exc:  # pragma: no cover - depende del contexto interno de Streamlit
        if exc.__class__.__name__ not in {"StreamlitAPIException", "StreamlitFragmentError"}:
            raise
        st.rerun(scope="app")


def rerun_app(st) -> None:
    """Solicita un rerun completo para una navegación entre vistas."""

    try:
        st.rerun(scope="app")
    except TypeError:  # dobles de prueba o adaptadores anteriores sin parámetro scope
        st.rerun()


def request_app_view(
    st,
    *,
    mode: str,
    source_key: str | None = None,
    page: int | None = None,
    object_id: str | None = None,
) -> None:
    """Solicita una navegación de vista completa para el siguiente rerun."""

    st.session_state["review_pending_app_mode"] = mode
    if source_key is not None:
        payload: dict[str, object] = {"source_key": source_key}
        if page is not None:
            payload["page"] = int(page)
        if object_id is not None:
            payload["object_id"] = str(object_id)
        st.session_state["review_pending_navigation"] = payload
