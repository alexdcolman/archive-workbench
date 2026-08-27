from __future__ import annotations

import base64
import mimetypes
from functools import lru_cache
from pathlib import Path
from typing import Any

from archive_workbench.review import ReviewObjectRow, _normalized_polygons


_COMPONENT_HTML = """
<div class="aw-toolbar" aria-label="Controles para ampliar y recorrer la imagen de la página">
  <button type="button" data-action="zoom-out" title="Alejar">−</button>
  <button type="button" data-action="fit" title="Ajustar">Ajustar</button>
  <button type="button" data-action="zoom-in" title="Acercar">+</button>
  <span class="aw-zoom-label">100%</span>
  <button type="button" data-action="draw">Dibujar dónde irá el texto nuevo</button>
  <span class="aw-help">Usá Ctrl+rueda para ampliar o reducir. Arrastrá el fondo para recorrer la página.</span>
</div>
<div class="aw-selection-bar">
  <span class="aw-selection-summary">Ningún texto seleccionado en la imagen.</span>
  <button type="button" data-action="confirm-selection">Usar el texto seleccionado</button>
  <button type="button" data-action="confirm-drawing">Usar esta ubicación</button>
</div>
<div class="aw-viewport">
  <div class="aw-stage">
    <img class="aw-image" alt="Página documental" draggable="false" />
    <svg class="aw-overlay" viewBox="0 0 1 1" preserveAspectRatio="none" aria-label="Marcos que señalan los textos de la página"></svg>
  </div>
</div>
"""

_COMPONENT_CSS = """
.aw-toolbar, .aw-selection-bar {
  display: flex;
  align-items: center;
  gap: .45rem;
  margin-bottom: .45rem;
  font-family: var(--st-font, sans-serif);
  flex-wrap: wrap;
}
.aw-toolbar button, .aw-selection-bar button {
  border: 1px solid color-mix(in srgb, var(--st-text-color) 28%, transparent);
  border-radius: .35rem;
  background: var(--st-secondary-background-color);
  color: var(--st-text-color);
  padding: .28rem .62rem;
  cursor: pointer;
}
.aw-toolbar button:hover, .aw-selection-bar button:hover { border-color: var(--st-primary-color); }
.aw-toolbar button.active { border-color: var(--st-primary-color); box-shadow: 0 0 0 1px var(--st-primary-color); }
.aw-toolbar button:disabled, .aw-selection-bar button:disabled { opacity:.45; cursor:default; }
.aw-help { opacity: .72; font-size: .82rem; margin-left: .25rem; }
.aw-selection-summary { font-size:.88rem; flex:1 1 24rem; }
.aw-zoom-label { min-width: 3.4rem; text-align: center; font-variant-numeric: tabular-nums; }
.aw-viewport {
  max-height: 76vh;
  overflow: auto;
  border: 1px solid color-mix(in srgb, var(--st-text-color) 18%, transparent);
  border-radius: .45rem;
  background: color-mix(in srgb, var(--st-secondary-background-color) 80%, transparent);
  cursor: grab;
  overscroll-behavior: contain;
  scrollbar-gutter: stable both-edges;
}
.aw-viewport.dragging { cursor: grabbing; user-select: none; }
.aw-stage { position: relative; width: 100%; line-height: 0; transform-origin: top left; }
.aw-image { display: block; width: 100%; height: auto; user-select: none; pointer-events: none; }
.aw-overlay { position: absolute; inset: 0; width: 100%; height: 100%; }
.aw-box { vector-effect: non-scaling-stroke; fill: rgba(20,120,180,.06); stroke: rgb(20,120,180); stroke-width: 2.5; cursor: pointer; }
.aw-box:hover { fill: rgba(255,165,0,.18); stroke: rgb(235,135,0); stroke-width: 4; }
.aw-box.selected { fill: rgba(210,45,45,.12); stroke: rgb(210,45,45); stroke-width: 5; }
.aw-box.deleted { fill: rgba(115,115,115,.07); stroke: rgb(115,115,115); stroke-dasharray: 7 5; }
.aw-draft { vector-effect: non-scaling-stroke; fill: rgba(210,45,45,.08); stroke: rgb(210,45,45); stroke-width: 4; stroke-dasharray: 8 5; pointer-events: none; }
.aw-label-bg { fill: rgba(0,0,0,.78); pointer-events: none; }
.aw-label { fill: white; font-weight: 700; pointer-events: none; dominant-baseline: hanging; }
"""

_COMPONENT_JS = r"""
export default function(component) {
  const { parentElement, data, setTriggerValue } = component;
  const image = parentElement.querySelector('.aw-image');
  const overlay = parentElement.querySelector('.aw-overlay');
  const stage = parentElement.querySelector('.aw-stage');
  const viewport = parentElement.querySelector('.aw-viewport');
  const zoomLabel = parentElement.querySelector('.aw-zoom-label');
  const drawButton = parentElement.querySelector('[data-action="draw"]');
  const confirmSelection = parentElement.querySelector('[data-action="confirm-selection"]');
  const confirmDrawing = parentElement.querySelector('[data-action="confirm-drawing"]');
  const selectionSummary = parentElement.querySelector('.aw-selection-summary');

  const browserStateKey = `archive-workbench-review-canvas:${String(data.browser_state_key || 'default')}`;
  const readStored = () => {
    try { return JSON.parse(window.sessionStorage.getItem(browserStateKey) || 'null'); }
    catch (error) { return null; }
  };
  const stored = readStored() || {};
  const state = parentElement.__awbViewState || {
    zoom: Number(stored.zoom || 1),
    scrollLeft: Number(stored.scrollLeft || 0),
    scrollTop: Number(stored.scrollTop || 0),
    drawing: false,
    drawStart: null,
    drawCurrent: null,
    drawnBox: stored.drawnBox || null,
    selected: stored.selected || null,
    serverSelectedSeen: stored.serverSelectedSeen ?? null,
  };
  parentElement.__awbViewState = state;

  const availableIds = new Set((data.boxes || []).map((box) => String(box.object_id)));
  const incomingSelected = data.selected_object_id ? String(data.selected_object_id) : null;
  if (state.serverSelectedSeen !== incomingSelected) {
    state.serverSelectedSeen = incomingSelected;
    state.selected = incomingSelected;
  }
  if (state.selected && !availableIds.has(String(state.selected))) state.selected = incomingSelected;
  if (data.confirmed_box && !state.drawnBox) state.drawnBox = data.confirmed_box;

  const saveState = () => {
    window.sessionStorage.setItem(browserStateKey, JSON.stringify({
      zoom: state.zoom,
      scrollLeft: state.scrollLeft,
      scrollTop: state.scrollTop,
      drawnBox: state.drawnBox,
      selected: state.selected,
      serverSelectedSeen: state.serverSelectedSeen,
    }));
  };

  const boxById = (objectId) => (data.boxes || []).find((box) => String(box.object_id) === String(objectId));
  const updateControls = () => {
    const selectedBox = boxById(state.selected);
    selectionSummary.textContent = selectedBox
      ? `Texto seleccionado: ${selectedBox.label}. ${selectedBox.text_preview || selectedBox.object_type || ''}`
      : 'Ningún texto seleccionado en la imagen.';
    confirmSelection.hidden = !Boolean(data.allow_selection) || Boolean(data.commit_selection_on_click);
    confirmSelection.disabled = !selectedBox;
    confirmDrawing.hidden = !Boolean(data.allow_draw);
    confirmDrawing.disabled = !state.drawnBox;
    drawButton.hidden = !Boolean(data.allow_draw);
    drawButton.classList.toggle('active', Boolean(state.drawing));
  };

  const applyZoom = (nextZoom, anchorX = viewport.clientWidth / 2, anchorY = viewport.clientHeight / 2) => {
    const oldZoom = state.zoom || 1;
    const contentX = (viewport.scrollLeft + anchorX) / oldZoom;
    const contentY = (viewport.scrollTop + anchorY) / oldZoom;
    state.zoom = Math.max(0.5, Math.min(5, nextZoom));
    stage.style.width = `${state.zoom * 100}%`;
    zoomLabel.textContent = `${Math.round(state.zoom * 100)}%`;
    saveState();
    requestAnimationFrame(() => {
      viewport.scrollLeft = Math.max(0, contentX * state.zoom - anchorX);
      viewport.scrollTop = Math.max(0, contentY * state.zoom - anchorY);
      state.scrollLeft = viewport.scrollLeft;
      state.scrollTop = viewport.scrollTop;
      saveState();
    });
  };

  const normalizedPoint = (event) => {
    const rect = overlay.getBoundingClientRect();
    return {
      x: Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)),
      y: Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)),
    };
  };

  const currentDraft = () => {
    if (state.drawStart && state.drawCurrent) {
      return {
        x0: Math.min(state.drawStart.x, state.drawCurrent.x),
        y0: Math.min(state.drawStart.y, state.drawCurrent.y),
        x1: Math.max(state.drawStart.x, state.drawCurrent.x),
        y1: Math.max(state.drawStart.y, state.drawCurrent.y),
      };
    }
    return state.drawnBox;
  };

  const renderOverlay = () => {
    overlay.replaceChildren();
    for (const box of data.boxes || []) {
      for (const polygon of box.polygons || []) {
        const xs = polygon.map((point) => Number(point[0]));
        const ys = polygon.map((point) => Number(point[1]));
        const x = Math.min(...xs);
        const y = Math.min(...ys);
        const width = Math.max(...xs) - x;
        const height = Math.max(...ys) - y;
        if (!(width > 0 && height > 0)) continue;

        const group = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        group.setAttribute('role', 'button');
        group.setAttribute('tabindex', '0');
        group.setAttribute('aria-label', `Texto ${box.label}: ${box.object_type}`);
        group.onclick = (event) => {
          event.stopPropagation();
          if (state.drawing || moved) return;
          state.selected = String(box.object_id);
          saveState();
          renderOverlay();
          updateControls();
          if (Boolean(data.commit_selection_on_click)) {
            setTriggerValue('selection_commit', state.selected);
          }
        };
        group.onkeydown = (event) => {
          if (!state.drawing && (event.key === 'Enter' || event.key === ' ')) {
            event.preventDefault();
            state.selected = String(box.object_id);
            saveState();
            renderOverlay();
            updateControls();
            if (Boolean(data.commit_selection_on_click)) {
              setTriggerValue('selection_commit', state.selected);
            }
          }
        };

        const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        rect.setAttribute('x', String(x));
        rect.setAttribute('y', String(y));
        rect.setAttribute('width', String(width));
        rect.setAttribute('height', String(height));
        rect.setAttribute('rx', '0.004');
        rect.setAttribute('class', `aw-box${String(box.object_id) === String(state.selected) ? ' selected' : ''}${box.deleted ? ' deleted' : ''}`);
        group.appendChild(rect);

        const labelWidth = Math.max(0.034, 0.014 + String(box.label).length * 0.012);
        const labelHeight = 0.034;
        const labelBg = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        labelBg.setAttribute('x', String(x));
        labelBg.setAttribute('y', String(Math.max(0, y - labelHeight)));
        labelBg.setAttribute('width', String(labelWidth));
        labelBg.setAttribute('height', String(labelHeight));
        labelBg.setAttribute('class', 'aw-label-bg');
        group.appendChild(labelBg);

        const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        text.setAttribute('x', String(x + 0.005));
        text.setAttribute('y', String(Math.max(0, y - labelHeight + 0.004)));
        text.setAttribute('class', 'aw-label');
        text.setAttribute('font-size', '0.024');
        text.textContent = String(box.label);
        group.appendChild(text);
        overlay.appendChild(group);
      }
    }

    const draft = currentDraft();
    if (draft) {
      const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      rect.setAttribute('x', String(draft.x0));
      rect.setAttribute('y', String(draft.y0));
      rect.setAttribute('width', String(draft.x1 - draft.x0));
      rect.setAttribute('height', String(draft.y1 - draft.y0));
      rect.setAttribute('class', 'aw-draft');
      overlay.appendChild(rect);
    }
  };

  applyZoom(state.zoom);
  requestAnimationFrame(() => {
    viewport.scrollLeft = state.scrollLeft || 0;
    viewport.scrollTop = state.scrollTop || 0;
  });

  parentElement.querySelector('[data-action="zoom-in"]').onclick = () => applyZoom(state.zoom + 0.25);
  parentElement.querySelector('[data-action="zoom-out"]').onclick = () => applyZoom(state.zoom - 0.25);
  parentElement.querySelector('[data-action="fit"]').onclick = () => {
    state.scrollLeft = 0;
    state.scrollTop = 0;
    applyZoom(1, 0, 0);
    viewport.scrollTo({top: 0, left: 0, behavior: 'smooth'});
    saveState();
  };

  const allowDraw = Boolean(data.allow_draw);
  if (!allowDraw) {
    state.drawing = false;
    state.drawStart = null;
    state.drawCurrent = null;
    state.drawnBox = null;
  }
  drawButton.onclick = () => {
    if (!allowDraw) return;
    state.drawing = !state.drawing;
    state.drawStart = null;
    state.drawCurrent = null;
    if (state.drawing) state.drawnBox = null;
    saveState();
    renderOverlay();
    updateControls();
  };
  confirmSelection.onclick = () => {
    if (state.selected) setTriggerValue('selection_commit', String(state.selected));
  };
  confirmDrawing.onclick = () => {
    if (state.drawnBox) setTriggerValue('box_commit', state.drawnBox);
  };

  viewport.onscroll = () => {
    state.scrollLeft = viewport.scrollLeft;
    state.scrollTop = viewport.scrollTop;
    saveState();
  };
  viewport.onwheel = (event) => {
    if (!event.ctrlKey && !event.metaKey) return;
    event.preventDefault();
    const rect = viewport.getBoundingClientRect();
    applyZoom(
      state.zoom + (event.deltaY < 0 ? 0.15 : -0.15),
      event.clientX - rect.left,
      event.clientY - rect.top,
    );
  };

  let dragging = false;
  let moved = false;
  let startX = 0;
  let startY = 0;
  let startLeft = 0;
  let startTop = 0;
  viewport.onpointerdown = (event) => {
    if (event.button !== 0) return;
    if (state.drawing && !event.target.closest('.aw-box')) {
      event.preventDefault();
      state.drawStart = normalizedPoint(event);
      state.drawCurrent = state.drawStart;
      viewport.setPointerCapture(event.pointerId);
      renderOverlay();
      return;
    }
    if (event.target.closest('.aw-box')) return;
    dragging = true;
    moved = false;
    startX = event.clientX;
    startY = event.clientY;
    startLeft = viewport.scrollLeft;
    startTop = viewport.scrollTop;
    viewport.classList.add('dragging');
    viewport.setPointerCapture(event.pointerId);
  };
  viewport.onpointermove = (event) => {
    if (state.drawing && state.drawStart) {
      state.drawCurrent = normalizedPoint(event);
      renderOverlay();
      return;
    }
    if (!dragging) return;
    const dx = event.clientX - startX;
    const dy = event.clientY - startY;
    if (Math.abs(dx) + Math.abs(dy) > 3) moved = true;
    viewport.scrollLeft = startLeft - dx;
    viewport.scrollTop = startTop - dy;
  };
  const endDrag = (event) => {
    if (state.drawing && state.drawStart) {
      state.drawCurrent = normalizedPoint(event);
      const x0 = Math.min(state.drawStart.x, state.drawCurrent.x);
      const y0 = Math.min(state.drawStart.y, state.drawCurrent.y);
      const x1 = Math.max(state.drawStart.x, state.drawCurrent.x);
      const y1 = Math.max(state.drawStart.y, state.drawCurrent.y);
      if (x1 - x0 > .005 && y1 - y0 > .005) state.drawnBox = {x0, y0, x1, y1};
      state.drawing = false;
      state.drawStart = null;
      state.drawCurrent = null;
      saveState();
      renderOverlay();
      updateControls();
      if (viewport.hasPointerCapture(event.pointerId)) viewport.releasePointerCapture(event.pointerId);
      return;
    }
    if (!dragging) return;
    dragging = false;
    viewport.classList.remove('dragging');
    if (viewport.hasPointerCapture(event.pointerId)) viewport.releasePointerCapture(event.pointerId);
    state.scrollLeft = viewport.scrollLeft;
    state.scrollTop = viewport.scrollTop;
    saveState();
  };
  viewport.onpointerup = endDrag;
  viewport.onpointercancel = endDrag;

  if (image.src !== data.image_data_url) image.src = data.image_data_url;
  renderOverlay();
  updateControls();
  saveState();
}
"""


def _image_data_url(path: str | Path) -> str:
    image_path = Path(path)
    mime = mimetypes.guess_type(image_path.name)[0] or "image/webp"
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def build_review_canvas_payload(
    image_path: str | Path,
    objects: list[ReviewObjectRow],
    *,
    page: int,
    selected_object_id: str | None,
    show_deleted: bool = False,
) -> dict[str, Any]:
    boxes: list[dict[str, Any]] = []
    for item in objects:
        if item.lifecycle_status == "deleted" and not show_deleted:
            continue
        polygons = _normalized_polygons(item.geometry, page=page)
        if not polygons:
            continue
        preview = " ".join(item.text.split())
        if len(preview) > 90:
            preview = preview[:87].rstrip() + "..."
        boxes.append(
            {
                "object_id": item.object_id,
                "label": item.order_index + 1,
                "object_type": item.object_type,
                "text_preview": preview,
                "selected": item.object_id == selected_object_id,
                "deleted": item.lifecycle_status == "deleted",
                "polygons": [[[x, y] for x, y in polygon] for polygon in polygons],
            }
        )
    return {
        "image_data_url": _image_data_url(image_path),
        "page": page,
        "selected_object_id": selected_object_id,
        "boxes": boxes,
        "allow_selection": True,
        "allow_draw": False,
        "confirmed_box": None,
        "commit_selection_on_click": False,
    }


@lru_cache(maxsize=1)
def _renderer():
    import streamlit as st

    if not hasattr(st.components, "v2"):
        return None
    return st.components.v2.component(
        name="archive_workbench_review_canvas",
        html=_COMPONENT_HTML,
        css=_COMPONENT_CSS,
        js=_COMPONENT_JS,
    )


def _component_result_value(result: Any, name: str) -> Any:
    if result is None:
        return None
    if isinstance(result, dict):
        return result.get(name)
    return getattr(result, name, None)


def _sync_component_selection(
    st,
    *,
    component_key: str,
    selection_state_key: str,
    valid_object_ids: set[str],
) -> None:
    """Sincroniza el widget de Streamlit antes de que empiece el rerun principal."""
    result = st.session_state.get(component_key)
    selected = _component_result_value(result, "selection_commit")
    if selected is None:
        return
    selected_id = str(selected)
    if selected_id in valid_object_ids:
        st.session_state[selection_state_key] = selected_id


def clickable_review_canvas(
    image_path: str | Path,
    objects: list[ReviewObjectRow],
    *,
    page: int,
    selected_object_id: str | None,
    show_deleted: bool,
    key: str,
    commit_on_click: bool = False,
    selection_state_key: str | None = None,
) -> str | None:
    """Sincroniza la selección semántica del bloque; el alcance del rerun lo define la vista."""
    renderer = _renderer()
    if renderer is None:
        return None
    payload = build_review_canvas_payload(
        image_path,
        objects,
        page=page,
        selected_object_id=selected_object_id,
        show_deleted=show_deleted,
    )
    payload["allow_draw"] = False
    payload["browser_state_key"] = key
    payload["commit_selection_on_click"] = bool(commit_on_click)
    if commit_on_click and selection_state_key:
        import streamlit as st

        valid_object_ids = {item.object_id for item in objects}

        def on_selection_commit_change() -> None:
            _sync_component_selection(
                st,
                component_key=key,
                selection_state_key=selection_state_key,
                valid_object_ids=valid_object_ids,
            )
    else:
        on_selection_commit_change = lambda: None

    result = renderer(
        data=payload,
        key=key,
        height=820,
        width="stretch",
        on_selection_commit_change=on_selection_commit_change,
    )
    selected = _component_result_value(result, "selection_commit")
    return str(selected) if selected else None


def review_canvas_with_drawing(
    image_path: str | Path,
    objects: list[ReviewObjectRow],
    *,
    page: int,
    selected_object_id: str | None,
    show_deleted: bool,
    key: str,
    confirmed_box: dict[str, float] | None = None,
) -> tuple[str | None, dict[str, float] | None]:
    """Selecciona o dibuja localmente y comunica sólo decisiones confirmadas."""
    renderer = _renderer()
    if renderer is None:
        return None, None
    payload = build_review_canvas_payload(
        image_path,
        objects,
        page=page,
        selected_object_id=selected_object_id,
        show_deleted=show_deleted,
    )
    payload["allow_draw"] = True
    payload["browser_state_key"] = key
    payload["confirmed_box"] = confirmed_box
    result = renderer(
        data=payload,
        key=key,
        height=820,
        width="stretch",
        on_selection_commit_change=lambda: None,
        on_box_commit_change=lambda: None,
    )
    selected = getattr(result, "selection_commit", None)
    raw_box = getattr(result, "box_commit", None)
    drawn_box = None
    if raw_box:
        try:
            drawn_box = {name: float(raw_box[name]) for name in ("x0", "y0", "x1", "y1")}
        except (KeyError, TypeError, ValueError):
            drawn_box = None
    return (str(selected) if selected else None), drawn_box
