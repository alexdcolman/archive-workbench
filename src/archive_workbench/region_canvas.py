from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path
from typing import Any

from archive_workbench.contracts.regions import RegionDefinition

_COMPONENT_HTML = """
<div class="awr-toolbar">
  <button type="button" data-action="draw">Dibujar una zona</button>
  <span>Arrastrá sobre la página para delimitar la zona.</span>
</div>
<div class="awr-canvas-wrap">
  <canvas class="awr-canvas" aria-label="Página para OCR regional"></canvas>
</div>
"""

_COMPONENT_CSS = """
.awr-toolbar { display:flex; align-items:center; gap:.6rem; margin-bottom:.45rem; font-family:var(--st-font,sans-serif); }
.awr-toolbar button { border:1px solid color-mix(in srgb,var(--st-text-color) 28%,transparent); border-radius:.35rem; background:var(--st-secondary-background-color); color:var(--st-text-color); padding:.38rem .75rem; cursor:pointer; }
.awr-toolbar button.active { border-color:var(--st-primary-color); box-shadow:0 0 0 1px var(--st-primary-color); }
.awr-toolbar span { opacity:.72; font-size:.84rem; }
.awr-canvas-wrap { width:100%; max-height:74vh; overflow:auto; border:1px solid color-mix(in srgb,var(--st-text-color) 18%,transparent); border-radius:.45rem; background:#fff; }
.awr-canvas { display:block; width:100%; height:auto; cursor:crosshair; }
"""

_COMPONENT_JS = r"""
export default function(component) {
  const { parentElement, data, setTriggerValue } = component;
  const canvas = parentElement.querySelector('.awr-canvas');
  const button = parentElement.querySelector('[data-action="draw"]');
  const ctx = canvas.getContext('2d');
  const image = new Image();
  const state = parentElement.__awrState || { drawing:false, start:null, current:null };
  parentElement.__awrState = state;

  const color = (box) => box.draft ? '#d62728' : (box.mode === 'ocr' ? '#1677c8' : '#e58b22');
  const draw = () => {
    if (!image.naturalWidth) return;
    canvas.width = image.naturalWidth;
    canvas.height = image.naturalHeight;
    ctx.drawImage(image, 0, 0);
    for (const box of data.boxes || []) {
      const x = box.bbox.x0 * canvas.width;
      const y = box.bbox.y0 * canvas.height;
      const w = (box.bbox.x1 - box.bbox.x0) * canvas.width;
      const h = (box.bbox.y1 - box.bbox.y0) * canvas.height;
      ctx.strokeStyle = color(box); ctx.lineWidth = Math.max(3, canvas.width / 350);
      ctx.strokeRect(x, y, w, h);
      ctx.font = `${Math.max(13, canvas.width / 70)}px sans-serif`;
      const label = `${box.reading_order}. ${box.label}`;
      const metrics = ctx.measureText(label);
      const boxH = Math.max(20, canvas.width / 45);
      ctx.fillStyle = color(box); ctx.fillRect(x, Math.max(0, y - boxH), metrics.width + 12, boxH);
      ctx.fillStyle = '#fff'; ctx.fillText(label, x + 6, Math.max(15, y - 5));
    }
    if (state.start && state.current) {
      const x = Math.min(state.start.x, state.current.x);
      const y = Math.min(state.start.y, state.current.y);
      const w = Math.abs(state.current.x - state.start.x);
      const h = Math.abs(state.current.y - state.start.y);
      ctx.strokeStyle = '#d62728'; ctx.lineWidth = Math.max(3, canvas.width / 350);
      ctx.strokeRect(x, y, w, h);
    }
  };

  image.onload = draw;
  image.src = data.image_data_url;
  button.classList.toggle('active', state.drawing);
  button.onclick = () => { state.drawing = !state.drawing; state.start = null; state.current = null; button.classList.toggle('active', state.drawing); draw(); };

  const point = (event) => {
    const rect = canvas.getBoundingClientRect();
    return { x:(event.clientX-rect.left)*(canvas.width/rect.width), y:(event.clientY-rect.top)*(canvas.height/rect.height) };
  };
  canvas.onpointerdown = (event) => {
    if (!state.drawing) return;
    state.start = point(event); state.current = state.start; canvas.setPointerCapture(event.pointerId); draw();
  };
  canvas.onpointermove = (event) => { if (!state.drawing || !state.start) return; state.current = point(event); draw(); };
  canvas.onpointerup = (event) => {
    if (!state.drawing || !state.start) return;
    state.current = point(event);
    const x0 = Math.min(state.start.x, state.current.x) / canvas.width;
    const y0 = Math.min(state.start.y, state.current.y) / canvas.height;
    const x1 = Math.max(state.start.x, state.current.x) / canvas.width;
    const y1 = Math.max(state.start.y, state.current.y) / canvas.height;
    if (x1-x0 > .005 && y1-y0 > .005) setTriggerValue('drawn_box', {x0,y0,x1,y1});
    state.drawing = false; state.start = null; state.current = null; button.classList.remove('active'); draw();
  };
}
"""


def _image_data_url(path: str | Path) -> str:
    source = Path(path)
    mime = "image/png" if source.suffix.lower() == ".png" else "image/jpeg"
    encoded = base64.b64encode(source.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def build_region_canvas_payload(
    image_path: str | Path,
    regions: list[RegionDefinition | dict[str, Any]],
    *,
    page: int,
    pending_box: dict[str, float] | None = None,
) -> dict[str, Any]:
    boxes: list[dict[str, Any]] = []
    for item in regions:
        if isinstance(item, RegionDefinition):
            if item.page != page:
                continue
            boxes.append({
                "region_key": item.region_key,
                "label": item.label,
                "reading_order": item.reading_order,
                "mode": item.mode,
                "bbox": item.bbox.model_dump(mode="json"),
                "draft": False,
            })
        else:
            if int(item.get("page", page)) != page:
                continue
            boxes.append({
                "region_key": str(item.get("region_key") or "draft"),
                "label": str(item.get("label") or "Zona"),
                "reading_order": int(item.get("reading_order", len(boxes) + 1)),
                "mode": str(item.get("mode") or "manual"),
                "bbox": dict(item["bbox"]),
                "draft": bool(item.get("draft", False)),
            })
    if pending_box:
        boxes.append({
            "region_key": "pending",
            "label": "Zona recién dibujada",
            "reading_order": len(boxes) + 1,
            "mode": "manual",
            "bbox": dict(pending_box),
            "draft": True,
        })
    return {"image_data_url": _image_data_url(image_path), "page": page, "boxes": boxes}


@lru_cache(maxsize=1)
def _renderer():
    import streamlit as st
    if not hasattr(st.components, "v2"):
        return None
    return st.components.v2.component(
        name="archive_workbench_region_canvas",
        html=_COMPONENT_HTML,
        css=_COMPONENT_CSS,
        js=_COMPONENT_JS,
    )


def regional_region_canvas(
    image_path: str | Path,
    regions: list[RegionDefinition | dict[str, Any]],
    *,
    page: int,
    pending_box: dict[str, float] | None,
    key: str,
) -> dict[str, float] | None:
    renderer = _renderer()
    if renderer is None:
        return None
    result = renderer(
        data=build_region_canvas_payload(
            image_path, regions, page=page, pending_box=pending_box
        ),
        key=key,
        height=760,
        width="stretch",
        on_drawn_box_change=lambda: None,
    )
    value = getattr(result, "drawn_box", None)
    if not value:
        return None
    return {key: float(value[key]) for key in ("x0", "y0", "x1", "y1")}
