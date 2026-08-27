from __future__ import annotations

from functools import lru_cache
from typing import Any

_COMPONENT_HTML = """
<div class="aw-tree-shell" role="tree" aria-label="Estructura archivística">
  <div class="aw-tree"></div>
</div>
"""

_COMPONENT_CSS = """
.aw-tree-shell {
  max-height: 68vh;
  overflow: auto;
  border: 1px solid color-mix(in srgb, var(--st-text-color) 18%, transparent);
  border-radius: .45rem;
  background: color-mix(in srgb, var(--st-secondary-background-color) 45%, transparent);
  padding: .35rem .2rem .45rem .25rem;
  font-family: var(--st-font, sans-serif);
}
.aw-tree, .aw-tree ul { list-style: none; margin: 0; padding: 0; }
.aw-tree ul {
  margin-left: .72rem;
  padding-left: .72rem;
  border-left: 1px solid color-mix(in srgb, var(--st-text-color) 18%, transparent);
}
.aw-tree li { margin: 0; padding: 0; position: relative; }
.aw-tree li > .aw-node-row::before {
  content: "";
  position: absolute;
  left: -.72rem;
  top: 1.05rem;
  width: .62rem;
  border-top: 1px solid color-mix(in srgb, var(--st-text-color) 18%, transparent);
}
.aw-tree > li > .aw-node-row::before { display: none; }
.aw-node-row {
  position: relative;
  display: grid;
  grid-template-columns: 1.4rem minmax(0, 1fr);
  align-items: center;
  min-height: 2rem;
  border-radius: .32rem;
  margin: .03rem .2rem .03rem 0;
}
.aw-node-row:hover { background: color-mix(in srgb, var(--st-text-color) 5%, transparent); }
.aw-node-row.selected {
  background: color-mix(in srgb, var(--st-text-color) 10%, transparent);
  box-shadow: inset 2px 0 0 color-mix(in srgb, var(--st-text-color) 55%, transparent);
}
.aw-toggle {
  width: 1.35rem;
  height: 1.7rem;
  border: 0;
  padding: 0;
  margin: 0;
  background: transparent;
  color: var(--st-text-color);
  cursor: pointer;
  opacity: .78;
  font-size: .84rem;
}
.aw-toggle:disabled { cursor: default; opacity: .35; }
.aw-node {
  width: 100%;
  min-width: 0;
  border: 0;
  background: transparent;
  color: var(--st-text-color);
  text-align: left;
  padding: .34rem .4rem .34rem .1rem;
  cursor: pointer;
  line-height: 1.25;
  overflow-wrap: anywhere;
}
.aw-node:disabled { cursor: default; opacity: .68; }
.aw-node-title { font-size: .91rem; }
.aw-node-meta { opacity: .67; font-size: .76rem; margin-left: .35rem; }
.aw-root-row { margin-bottom: .15rem; }
.aw-empty { padding: .6rem; opacity: .7; font-size: .88rem; }
"""

_COMPONENT_JS = r"""
export default function(component) {
  const { parentElement, data, setTriggerValue } = component;
  const tree = parentElement.querySelector('.aw-tree');
  const stateKey = `archive-workbench-catalog-tree:${String(data.browser_state_key || 'default')}`;

  const readExpanded = () => {
    try {
      const value = JSON.parse(window.sessionStorage.getItem(stateKey) || '[]');
      return new Set(Array.isArray(value) ? value.map(String) : []);
    } catch (error) { return new Set(); }
  };
  const expanded = readExpanded();
  const saveExpanded = () => window.sessionStorage.setItem(stateKey, JSON.stringify([...expanded]));

  const rows = (data.rows || []).map((row) => ({...row, id: String(row.id), parent_id: row.parent_id == null ? null : String(row.parent_id)}));
  const byId = new Map(rows.map((row) => [row.id, row]));
  for (const value of data.force_open_ids || []) {
    const targetId = String(value);
    expanded.add(targetId);
    let current = byId.get(targetId);
    const seen = new Set();
    while (current && current.parent_id && !seen.has(current.parent_id)) {
      seen.add(current.parent_id);
      expanded.add(current.parent_id);
      current = byId.get(current.parent_id);
    }
  }
  const byParent = new Map();
  for (const row of rows) {
    const parent = row.parent_id;
    if (!byParent.has(parent)) byParent.set(parent, []);
    byParent.get(parent).push(row);
  }
  const selected = data.selected_id == null ? null : String(data.selected_id);

  const makeNode = (row) => {
    const li = document.createElement('li');
    li.setAttribute('role', 'treeitem');
    li.setAttribute('aria-selected', String(row.id === selected));
    const kids = byParent.get(row.id) || [];
    const rowEl = document.createElement('div');
    rowEl.className = `aw-node-row${row.id === selected ? ' selected' : ''}`;

    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'aw-toggle';
    toggle.tabIndex = kids.length ? 0 : -1;
    toggle.disabled = !kids.length;
    toggle.setAttribute('aria-label', kids.length ? `${expanded.has(row.id) ? 'Cerrar' : 'Abrir'} ${row.title}` : 'Sin unidades hijas');
    toggle.textContent = kids.length ? (expanded.has(row.id) ? '▾' : '▸') : '·';
    rowEl.appendChild(toggle);

    const label = document.createElement('button');
    label.type = 'button';
    label.className = 'aw-node';
    label.disabled = !Boolean(row.selectable);
    label.title = row.path || row.title;
    const title = document.createElement('span');
    title.className = 'aw-node-title';
    title.textContent = `${row.level_label} · ${row.title}`;
    label.appendChild(title);
    if (row.reference_code) {
      const meta = document.createElement('span');
      meta.className = 'aw-node-meta';
      meta.textContent = row.reference_code;
      label.appendChild(meta);
    }
    rowEl.appendChild(label);
    li.appendChild(rowEl);

    const renderKids = () => {
      const existing = li.querySelector(':scope > ul');
      if (existing) existing.remove();
      toggle.textContent = kids.length ? (expanded.has(row.id) ? '▾' : '▸') : '·';
      toggle.setAttribute('aria-label', kids.length ? `${expanded.has(row.id) ? 'Cerrar' : 'Abrir'} ${row.title}` : 'Sin unidades hijas');
      li.setAttribute('aria-expanded', kids.length ? String(expanded.has(row.id)) : 'false');
      if (!kids.length || !expanded.has(row.id)) return;
      const ul = document.createElement('ul');
      ul.setAttribute('role', 'group');
      for (const child of kids) ul.appendChild(makeNode(child));
      li.appendChild(ul);
    };

    toggle.onclick = (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (!kids.length) return;
      if (expanded.has(row.id)) expanded.delete(row.id); else expanded.add(row.id);
      saveExpanded();
      renderKids();
    };
    label.onclick = () => {
      if (!row.selectable) return;
      setTriggerValue('selection_commit', row.id);
    };
    renderKids();
    return li;
  };

  tree.replaceChildren();
  if (Boolean(data.allow_root)) {
    const li = document.createElement('li');
    li.setAttribute('role', 'treeitem');
    const rowEl = document.createElement('div');
    rowEl.className = `aw-node-row aw-root-row${selected == null ? ' selected' : ''}`;
    const spacer = document.createElement('span');
    rowEl.appendChild(spacer);
    const root = document.createElement('button');
    root.type = 'button';
    root.className = 'aw-node';
    root.textContent = 'Raíz del catálogo';
    root.onclick = () => setTriggerValue('selection_commit', '__ROOT__');
    rowEl.appendChild(root);
    li.appendChild(rowEl);
    tree.appendChild(li);
  }
  const roots = byParent.get(null) || [];
  if (!roots.length && !Boolean(data.allow_root)) {
    const empty = document.createElement('div');
    empty.className = 'aw-empty';
    empty.textContent = 'No hay unidades visibles en esta estructura.';
    tree.appendChild(empty);
  } else {
    for (const row of roots) tree.appendChild(makeNode(row));
  }
  saveExpanded();
}
"""


@lru_cache(maxsize=1)
def _renderer():
    import streamlit as st

    if not hasattr(st.components, "v2"):
        return None
    return st.components.v2.component(
        name="archive_workbench_catalog_tree",
        html=_COMPONENT_HTML,
        css=_COMPONENT_CSS,
        js=_COMPONENT_JS,
    )


def _result_value(result: Any, name: str) -> Any:
    if result is None:
        return None
    if isinstance(result, dict):
        return result.get(name)
    return getattr(result, name, None)


def catalog_tree_select(
    st,
    *,
    rows,
    level_labels: dict[str, str],
    selected_id: str | None,
    key: str,
    selection_state_key: str,
    selectable_ids: set[str] | None = None,
    include_ids: set[str] | None = None,
    force_open_ids: set[str] | None = None,
    allow_root: bool = False,
) -> str | None:
    """Árbol tipo explorador: abrir/cerrar es local; sólo seleccionar llega a Python."""
    renderer = _renderer()
    if renderer is None:
        st.error("El árbol archivístico requiere Streamlit 1.51 o posterior.")
        return selected_id

    selectable = {str(item) for item in selectable_ids} if selectable_ids is not None else None
    include = {str(item) for item in include_ids} if include_ids is not None else None
    payload_rows = []
    for row in rows:
        if include is not None and str(row.id) not in include:
            continue
        payload_rows.append(
            {
                "id": str(row.id),
                "parent_id": str(row.parent_id) if row.parent_id is not None else None,
                "title": row.title,
                "level_label": level_labels.get(row.level_key, row.level_key),
                "reference_code": row.reference_code or "",
                "path": row.path,
                "selectable": selectable is None or str(row.id) in selectable,
            }
        )

    valid_ids = {item["id"] for item in payload_rows}

    def on_selection_commit_change() -> None:
        result = st.session_state.get(key)
        value = _result_value(result, "selection_commit")
        if value is None:
            return
        value = str(value)
        if value == "__ROOT__" and allow_root:
            st.session_state[selection_state_key] = None
        elif value in valid_ids and (selectable is None or value in selectable):
            st.session_state[selection_state_key] = value

    result = renderer(
        data={
            "rows": payload_rows,
            "selected_id": selected_id,
            "allow_root": bool(allow_root),
            "browser_state_key": key,
            "force_open_ids": sorted(str(item) for item in (force_open_ids or set())),
        },
        key=key,
        height=min(660, max(230, 48 + len(payload_rows) * 31)),
        width="stretch",
        on_selection_commit_change=on_selection_commit_change,
    )
    value = _result_value(result, "selection_commit")
    if value is None:
        return st.session_state.get(selection_state_key, selected_id)
    value = str(value)
    if value == "__ROOT__" and allow_root:
        return None
    if value in valid_ids and (selectable is None or value in selectable):
        return value
    return st.session_state.get(selection_state_key, selected_id)
