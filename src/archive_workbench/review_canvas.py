from __future__ import annotations

import base64
import mimetypes
from functools import lru_cache
from pathlib import Path
from typing import Any

from archive_workbench.review import ReviewObjectRow, _normalized_polygons


_COMPONENT_HTML = """
<div class="aw-toolbar" aria-label="Controles de imagen">
  <button type="button" data-action="zoom-out" title="Alejar">−</button>
  <button type="button" data-action="fit" title="Ajustar">Ajustar</button>
  <button type="button" data-action="zoom-in" title="Acercar">+</button>
  <span class="aw-zoom-label">100%</span>
  <span class="aw-help">Zoom con Ctrl+rueda. Arrastrá el fondo para desplazarte.</span>
</div>
<div class="aw-viewport">
  <div class="aw-stage">
    <img class="aw-image" alt="Página documental" draggable="false" />
    <svg class="aw-overlay" viewBox="0 0 1 1" preserveAspectRatio="none" aria-label="Cajas de objetos"></svg>
  </div>
</div>
"""

_COMPONENT_CSS = """
.aw-toolbar {
  display: flex;
  align-items: center;
  gap: .45rem;
  margin-bottom: .45rem;
  font-family: var(--st-font, sans-serif);
}
.aw-toolbar button {
  border: 1px solid color-mix(in srgb, var(--st-text-color) 28%, transparent);
  border-radius: .35rem;
  background: var(--st-secondary-background-color);
  color: var(--st-text-color);
  padding: .28rem .62rem;
  cursor: pointer;
}
.aw-toolbar button:hover { border-color: var(--st-primary-color); }
.aw-help { opacity: .72; font-size: .82rem; margin-left: .25rem; }
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

  const state = parentElement.__awbViewState || {
    zoom: 1,
    scrollLeft: 0,
    scrollTop: 0,
  };
  parentElement.__awbViewState = state;

  const applyZoom = (nextZoom, anchorX = viewport.clientWidth / 2, anchorY = viewport.clientHeight / 2) => {
    const oldZoom = state.zoom || 1;
    const contentX = (viewport.scrollLeft + anchorX) / oldZoom;
    const contentY = (viewport.scrollTop + anchorY) / oldZoom;
    state.zoom = Math.max(0.5, Math.min(5, nextZoom));
    stage.style.width = `${state.zoom * 100}%`;
    zoomLabel.textContent = `${Math.round(state.zoom * 100)}%`;
    requestAnimationFrame(() => {
      viewport.scrollLeft = Math.max(0, contentX * state.zoom - anchorX);
      viewport.scrollTop = Math.max(0, contentY * state.zoom - anchorY);
      state.scrollLeft = viewport.scrollLeft;
      state.scrollTop = viewport.scrollTop;
    });
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
  };

  viewport.onscroll = () => {
    state.scrollLeft = viewport.scrollLeft;
    state.scrollTop = viewport.scrollTop;
  };
  viewport.onwheel = (event) => {
    if (!event.ctrlKey && !event.metaKey) return;
    event.preventDefault();
    const rect = viewport.getBoundingClientRect();
    const anchorX = event.clientX - rect.left;
    const anchorY = event.clientY - rect.top;
    applyZoom(state.zoom + (event.deltaY < 0 ? 0.15 : -0.15), anchorX, anchorY);
  };

  let dragging = false;
  let moved = false;
  let startX = 0;
  let startY = 0;
  let startLeft = 0;
  let startTop = 0;
  viewport.onpointerdown = (event) => {
    if (event.button !== 0 || event.target.closest('.aw-box')) return;
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
    if (!dragging) return;
    const dx = event.clientX - startX;
    const dy = event.clientY - startY;
    if (Math.abs(dx) + Math.abs(dy) > 3) moved = true;
    viewport.scrollLeft = startLeft - dx;
    viewport.scrollTop = startTop - dy;
  };
  const endDrag = (event) => {
    if (!dragging) return;
    dragging = false;
    viewport.classList.remove('dragging');
    if (viewport.hasPointerCapture(event.pointerId)) viewport.releasePointerCapture(event.pointerId);
    state.scrollLeft = viewport.scrollLeft;
    state.scrollTop = viewport.scrollTop;
  };
  viewport.onpointerup = endDrag;
  viewport.onpointercancel = endDrag;

  if (image.src !== data.image_data_url) image.src = data.image_data_url;
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
      group.setAttribute('aria-label', `Objeto ${box.label}: ${box.object_type}`);
      group.onclick = (event) => {
        event.stopPropagation();
        if (!moved) setTriggerValue('selected', box.object_id);
      };
      group.onkeydown = (event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          setTriggerValue('selected', box.object_id);
        }
      };

      const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      rect.setAttribute('x', String(x));
      rect.setAttribute('y', String(y));
      rect.setAttribute('width', String(width));
      rect.setAttribute('height', String(height));
      rect.setAttribute('rx', '0.004');
      rect.setAttribute('class', `aw-box${box.selected ? ' selected' : ''}${box.deleted ? ' deleted' : ''}`);
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
        boxes.append(
            {
                "object_id": item.object_id,
                "label": item.order_index + 1,
                "object_type": item.object_type,
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


def clickable_review_canvas(
    image_path: str | Path,
    objects: list[ReviewObjectRow],
    *,
    page: int,
    selected_object_id: str | None,
    show_deleted: bool,
    key: str,
) -> str | None:
    """Renderiza la página y devuelve el ID clicado; usa None como fallback seguro."""
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
    result = renderer(
        data=payload,
        key=key,
        height=780,
        width="stretch",
        on_selected_change=lambda: None,
    )
    selected = getattr(result, "selected", None)
    return str(selected) if selected else None
