from __future__ import annotations

from functools import lru_cache
import hashlib
from typing import Any

from archive_workbench.graph import GraphView, graph_layout, graph_payload

_COMPONENT_HTML = """
<div class="awg-toolbar" aria-label="Controles del grafo">
  <button type="button" data-action="zoom-out" title="Alejar">−</button>
  <button type="button" data-action="fit" title="Ajustar">Ajustar</button>
  <button type="button" data-action="zoom-in" title="Acercar">+</button>
  <span class="awg-zoom">100%</span>
  <span class="awg-help">Arrastrá nodos para reubicarlos. Pasá el puntero sobre elementos y vínculos para ver su procedencia.</span>
</div>
<div class="awg-viewport">
  <svg class="awg-svg" viewBox="0 0 1000 720" role="img" aria-label="Grafo documental">
    <g class="awg-world"></g>
  </svg>
</div>
"""

_COMPONENT_CSS = """
.awg-toolbar {
  display: flex; align-items: center; gap: .45rem; margin-bottom: .45rem;
  font-family: var(--st-font, sans-serif);
}
.awg-toolbar button {
  border: 1px solid color-mix(in srgb, var(--st-text-color) 28%, transparent);
  border-radius: .35rem; background: var(--st-secondary-background-color);
  color: var(--st-text-color); padding: .28rem .62rem; cursor: pointer;
}
.awg-toolbar button:hover { border-color: var(--st-primary-color); }
.awg-help { opacity: .72; font-size: .82rem; margin-left: .25rem; }
.awg-zoom { min-width: 3.4rem; text-align: center; font-variant-numeric: tabular-nums; }
.awg-viewport {
  height: 72vh; min-height: 560px; overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--st-text-color) 18%, transparent);
  border-radius: .45rem; background: color-mix(in srgb, var(--st-secondary-background-color) 80%, transparent);
  cursor: grab; touch-action: none;
}
.awg-viewport.dragging { cursor: grabbing; user-select: none; }
.awg-svg { width: 100%; height: 100%; display: block; }
.awg-world { transform-origin: 0 0; }
.awg-edge { fill: none; stroke: color-mix(in srgb, var(--st-text-color) 36%, transparent); cursor: pointer; stroke-linecap: round; }
.awg-edge.explicit { stroke-width: 2.4; }
.awg-edge.mention { stroke-width: 1.7; stroke-dasharray: 7 5; }
.awg-edge.shared_entity { stroke-width: 1.3; stroke-dasharray: 2 5; }
.awg-edge:hover, .awg-edge.selected { stroke: var(--st-primary-color); stroke-width: 4.2; }
.awg-edge-label {
  font: 12px var(--st-font, sans-serif); fill: var(--st-text-color); opacity: .78;
  paint-order: stroke; stroke: var(--st-background-color); stroke-width: 4px; stroke-linejoin: round;
  pointer-events: none; text-anchor: middle;
}
.awg-node { cursor: pointer; }
.awg-node circle { stroke-width: 2.5; stroke: color-mix(in srgb, var(--st-text-color) 55%, transparent); }
.awg-node.entity circle { fill: color-mix(in srgb, var(--st-primary-color) 46%, var(--st-background-color)); }
.awg-node.archival_unit circle { fill: color-mix(in srgb, #d99728 46%, var(--st-background-color)); }
.awg-node.document_part circle { fill: color-mix(in srgb, #3d9b74 46%, var(--st-background-color)); }
.awg-node:hover circle, .awg-node.selected circle { stroke: var(--st-primary-color); stroke-width: 5; }
.awg-node text {
  font: 13px var(--st-font, sans-serif); font-weight: 650; fill: var(--st-text-color);
  paint-order: stroke; stroke: var(--st-background-color); stroke-width: 4px; stroke-linejoin: round;
  pointer-events: none; text-anchor: middle;
}
.awg-node .awg-kind { font-size: 10px; font-weight: 500; opacity: .72; }
.awg-empty { font: 18px var(--st-font, sans-serif); fill: var(--st-text-color); text-anchor: middle; opacity: .7; }
"""

_COMPONENT_JS = r"""
export default function(component) {
  const { parentElement, data, setTriggerValue } = component;
  const viewport = parentElement.querySelector('.awg-viewport');
  const svg = parentElement.querySelector('.awg-svg');
  const world = parentElement.querySelector('.awg-world');
  const zoomLabel = parentElement.querySelector('.awg-zoom');
  const state = parentElement.__awgState || {scale: 1, tx: 0, ty: 0, positions: {}};
  parentElement.__awgState = state;

  const signature = (data.nodes || []).map((node) => node.id).sort().join('|') + '::' +
    (data.edges || []).map((edge) => edge.id).sort().join('|');
  if (state.signature !== signature) {
    state.signature = signature;
    state.scale = 1; state.tx = 0; state.ty = 0;
    state.positions = Object.fromEntries((data.nodes || []).map((node) => [node.id, [node.x, node.y]]));
  } else {
    for (const node of data.nodes || []) {
      if (!state.positions[node.id]) state.positions[node.id] = [node.x, node.y];
    }
  }

  const applyTransform = () => {
    world.setAttribute('transform', `translate(${state.tx} ${state.ty}) scale(${state.scale})`);
    zoomLabel.textContent = `${Math.round(state.scale * 100)}%`;
  };
  applyTransform();

  const makeSvg = (name, attributes = {}) => {
    const element = document.createElementNS('http://www.w3.org/2000/svg', name);
    for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, String(value));
    return element;
  };
  const addTitle = (element, value) => {
    const title = makeSvg('title');
    title.textContent = value || '';
    element.appendChild(title);
  };
  const truncate = (value, maximum) => value.length > maximum ? `${value.slice(0, maximum - 1)}…` : value;
  const wrapLabel = (value, maximum = 25) => {
    const words = String(value || '').split(/\s+/).filter(Boolean);
    const lines = [];
    let current = '';
    for (const word of words) {
      const candidate = current ? `${current} ${word}` : word;
      if (candidate.length <= maximum || !current) {
        current = candidate;
      } else {
        lines.push(current);
        current = word;
      }
      if (lines.length === 2) break;
    }
    if (current && lines.length < 2) lines.push(current);
    if (lines.length === 2 && words.join(' ').length > lines.join(' ').length) {
      lines[1] = truncate(lines[1], maximum);
    }
    return lines.length ? lines : ['Sin nombre'];
  };
  world.replaceChildren();

  if (!(data.nodes || []).length) {
    const empty = makeSvg('text', {x: 500, y: 360, class: 'awg-empty'});
    empty.textContent = 'No hay nodos con estos filtros';
    world.appendChild(empty);
  }

  const nodeById = Object.fromEntries((data.nodes || []).map((node) => [node.id, node]));
  const edgeElements = [];
  const routeFor = (edge) => {
    const source = state.positions[edge.source];
    const target = state.positions[edge.target];
    if (!source || !target) return null;
    const slot = Number(edge.parallel_slot || 0);
    const direction = Number(edge.parallel_direction || 1);
    if (edge.source === edge.target) {
      const radius = 48 + Math.abs(slot) * 24;
      const side = slot < 0 ? -1 : 1;
      const x = source[0], y = source[1];
      return {
        d: `M ${x} ${y - 16} C ${x + side * radius} ${y - radius}, ${x + side * radius} ${y + radius}, ${x} ${y + 16}`,
        labelX: x + side * radius * .82,
        labelY: y - 4,
        nx: side,
        ny: 0,
      };
    }
    const dx = target[0] - source[0];
    const dy = target[1] - source[1];
    const distance = Math.max(1, Math.hypot(dx, dy));
    const nx = -dy / distance;
    const ny = dx / distance;
    const offset = slot * 38 * direction;
    const cx = (source[0] + target[0]) / 2 + nx * offset;
    const cy = (source[1] + target[1]) / 2 + ny * offset;
    return {
      d: `M ${source[0]} ${source[1]} Q ${cx} ${cy} ${target[0]} ${target[1]}`,
      labelX: source[0] * .25 + cx * .5 + target[0] * .25,
      labelY: source[1] * .25 + cy * .5 + target[1] * .25 - 5,
      nx,
      ny,
    };
  };

  for (const edge of data.edges || []) {
    const group = makeSvg('g');
    const path = makeSvg('path', {
      class: `awg-edge ${edge.edge_type}${edge.selected ? ' selected' : ''}`,
      'stroke-width': Math.min(6, 1.2 + Math.log1p(Number(edge.weight || 1))),
      tabindex: 0, role: 'button', 'aria-label': edge.tooltip || edge.label,
    });
    addTitle(path, edge.tooltip || edge.label);
    path.onclick = (event) => { event.stopPropagation(); setTriggerValue('selected_edge', edge.id); };
    path.onkeydown = (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault(); setTriggerValue('selected_edge', edge.id);
      }
    };
    group.appendChild(path);
    const label = makeSvg('text', {class: 'awg-edge-label'});
    label.textContent = truncate(edge.label, 40);
    group.appendChild(label);
    world.appendChild(group);
    edgeElements.push({edge, path, label});
  }

  const nodeElements = [];
  const kindLabel = {entity: 'entidad', archival_unit: 'unidad', document_part: 'parte'};
  for (const node of data.nodes || []) {
    const position = state.positions[node.id];
    const radius = Math.max(15, Math.min(27, 14 + Math.sqrt(Number(node.degree || 0)) * 3));
    const group = makeSvg('g', {
      class: `awg-node ${node.kind}${node.selected ? ' selected' : ''}`,
      transform: `translate(${position[0]} ${position[1]})`,
      tabindex: 0, role: 'button', 'aria-label': node.tooltip || `${kindLabel[node.kind] || node.kind}: ${node.label}`,
    });
    addTitle(group, node.tooltip || node.label);
    const circle = makeSvg('circle', {cx: 0, cy: 0, r: radius});
    group.appendChild(circle);
    const text = makeSvg('text');
    group.appendChild(text);
    const subtype = makeSvg('text', {class: 'awg-kind'});
    subtype.textContent = node.subtype || kindLabel[node.kind] || node.kind;
    group.appendChild(subtype);

    let draggingNode = false;
    let moved = false;
    const pointerToWorld = (event) => {
      const point = svg.createSVGPoint();
      point.x = event.clientX; point.y = event.clientY;
      const transformed = point.matrixTransform(svg.getScreenCTM().inverse());
      return [(transformed.x - state.tx) / state.scale, (transformed.y - state.ty) / state.scale];
    };
    group.onpointerdown = (event) => {
      if (event.button !== 0) return;
      event.stopPropagation(); draggingNode = true; moved = false;
      group.setPointerCapture(event.pointerId);
    };
    group.onpointermove = (event) => {
      if (!draggingNode) return;
      moved = true;
      const [x, y] = pointerToWorld(event);
      state.positions[node.id] = [x, y];
      group.setAttribute('transform', `translate(${x} ${y})`);
      scheduleGeometryRefresh();
    };
    group.onpointerup = (event) => {
      if (!draggingNode) return;
      draggingNode = false;
      if (group.hasPointerCapture(event.pointerId)) group.releasePointerCapture(event.pointerId);
      if (!moved) setTriggerValue('selected_node', node.id);
    };
    group.onkeydown = (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault(); setTriggerValue('selected_node', node.id);
      }
    };
    world.appendChild(group);
    nodeElements.push({node, group, text, subtype, radius});
  }

  const labelPlacement = (item) => {
    const position = state.positions[item.node.id];
    const radius = item.radius;
    const candidates = [
      {name: 'below', x: 0, y: radius + 17, anchor: 'middle', bias: 3},
      {name: 'above', x: 0, y: -radius - 30, anchor: 'middle', bias: 2},
      {name: 'right', x: radius + 12, y: -7, anchor: 'start', bias: 1},
      {name: 'left', x: -radius - 12, y: -7, anchor: 'end', bias: 0},
    ];
    for (const candidate of candidates) {
      const wx = position[0] + candidate.x;
      const wy = position[1] + candidate.y;
      let nearest = 1000;
      for (const other of data.nodes || []) {
        if (other.id === item.node.id) continue;
        const otherPosition = state.positions[other.id];
        nearest = Math.min(nearest, Math.hypot(wx - otherPosition[0], wy - otherPosition[1]));
      }
      candidate.score = nearest + candidate.bias;
    }
    return candidates.sort((left, right) => right.score - left.score || right.bias - left.bias)[0];
  };

  const refreshNodeLabels = () => {
    for (const item of nodeElements) {
      const placement = labelPlacement(item);
      const lines = wrapLabel(item.node.label);
      item.text.replaceChildren();
      item.text.setAttribute('x', placement.x);
      item.text.setAttribute('y', placement.y);
      item.text.setAttribute('text-anchor', placement.anchor);
      lines.forEach((line, index) => {
        const tspan = makeSvg('tspan', {
          x: placement.x,
          dy: index === 0 ? 0 : 14,
        });
        tspan.textContent = line;
        item.text.appendChild(tspan);
      });
      item.subtype.setAttribute('x', placement.x);
      item.subtype.setAttribute('y', placement.y + lines.length * 14);
      item.subtype.setAttribute('text-anchor', placement.anchor);
    }
  };

  const refreshEdges = () => {
    const occupied = [];
    const sorted = [...edgeElements].sort((left, right) => left.edge.id.localeCompare(right.edge.id));
    for (const item of sorted) {
      const route = routeFor(item.edge);
      if (!route) continue;
      item.path.setAttribute('d', route.d);
      let x = route.labelX;
      let y = route.labelY;
      for (let attempt = 0; attempt < 10; attempt += 1) {
        const nodeCollision = (data.nodes || []).some((node) => {
          const position = state.positions[node.id];
          return Math.hypot(x - position[0], y - position[1]) < 54;
        });
        const labelCollision = occupied.some((point) => Math.abs(x - point.x) < 92 && Math.abs(y - point.y) < 22);
        if (!nodeCollision && !labelCollision) break;
        const step = (Math.floor(attempt / 2) + 1) * 18 * (attempt % 2 === 0 ? 1 : -1);
        x = route.labelX + route.nx * step;
        y = route.labelY + route.ny * step;
      }
      item.label.setAttribute('x', x);
      item.label.setAttribute('y', y);
      occupied.push({x, y});
    }
  };

  let refreshPending = false;
  function scheduleGeometryRefresh() {
    if (refreshPending) return;
    refreshPending = true;
    window.requestAnimationFrame(() => {
      refreshPending = false;
      refreshNodeLabels();
      refreshEdges();
    });
  }
  refreshNodeLabels();
  refreshEdges();

  let panning = false;
  let startX = 0, startY = 0, startTx = 0, startTy = 0;
  viewport.onpointerdown = (event) => {
    if (event.button !== 0 || event.target.closest('.awg-node') || event.target.closest('.awg-edge')) return;
    panning = true; startX = event.clientX; startY = event.clientY;
    startTx = state.tx; startTy = state.ty;
    viewport.classList.add('dragging'); viewport.setPointerCapture(event.pointerId);
  };
  viewport.onpointermove = (event) => {
    if (!panning) return;
    state.tx = startTx + (event.clientX - startX) / (viewport.clientWidth / 1000);
    state.ty = startTy + (event.clientY - startY) / (viewport.clientHeight / 720);
    applyTransform();
  };
  const endPan = (event) => {
    if (!panning) return; panning = false; viewport.classList.remove('dragging');
    if (viewport.hasPointerCapture(event.pointerId)) viewport.releasePointerCapture(event.pointerId);
  };
  viewport.onpointerup = endPan; viewport.onpointercancel = endPan;
  viewport.onwheel = (event) => {
    event.preventDefault();
    const next = Math.max(.35, Math.min(3.5, state.scale + (event.deltaY < 0 ? .12 : -.12)));
    state.scale = next; applyTransform();
  };
  parentElement.querySelector('[data-action="zoom-in"]').onclick = () => { state.scale = Math.min(3.5, state.scale + .2); applyTransform(); };
  parentElement.querySelector('[data-action="zoom-out"]').onclick = () => { state.scale = Math.max(.35, state.scale - .2); applyTransform(); };
  parentElement.querySelector('[data-action="fit"]').onclick = () => { state.scale = 1; state.tx = 0; state.ty = 0; applyTransform(); };
}
"""


@lru_cache(maxsize=1)
def _renderer():
    import streamlit as st

    if not hasattr(st.components, "v2"):
        return None
    return st.components.v2.component(
        name="archive_workbench_graph_canvas",
        html=_COMPONENT_HTML,
        css=_COMPONENT_CSS,
        js=_COMPONENT_JS,
    )


def _safe_component_key(key: str) -> str:
    """Devuelve una base estable compatible con los IDs bidireccionales de Streamlit.

    Streamlit Components v2 reserva ``__`` como delimitador interno. Las claves
    construidas desde filtros pueden contenerlo cuando algún segmento está vacío.
    Un digest evita esa colisión y mantiene una identidad determinista por vista.
    """
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
    return f"awg-{digest}"


def interactive_graph_canvas(
    view: GraphView,
    *,
    selected_node: str | None,
    selected_edge: str | None,
    key: str,
) -> tuple[str | None, str | None]:
    renderer = _renderer()
    if renderer is None:
        return None, None
    payload: dict[str, Any] = graph_payload(
        view, selected_node=selected_node, selected_edge=selected_edge
    )
    positions = graph_layout(view)
    for node in payload["nodes"]:
        node["x"], node["y"] = positions.get(node["id"], (500.0, 360.0))
    result = renderer(
        data=payload,
        key=_safe_component_key(key),
        height=660,
        width="stretch",
        on_selected_node_change=lambda: None,
        on_selected_edge_change=lambda: None,
    )
    node = getattr(result, "selected_node", None)
    edge = getattr(result, "selected_edge", None)
    return (str(node) if node else None, str(edge) if edge else None)
