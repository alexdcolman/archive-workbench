from __future__ import annotations

from functools import lru_cache
from typing import Any

_COMPONENT_HTML = """
<div class="aw-doc-browser">
  <div class="aw-thumb-panel">
    <div class="aw-doc-browser-toolbar">
      <button type="button" class="aw-page aw-prev">‹ Conjunto anterior</button>
      <span class="aw-page-label"></span>
      <button type="button" class="aw-page aw-next">Conjunto siguiente ›</button>
    </div>
    <div class="aw-thumb-grid" role="list" aria-label="Miniaturas de archivos digitales"></div>
  </div>
  <div class="aw-doc-browser-footer">
    <span class="aw-selection-count"></span>
    <div class="aw-footer-actions">
      <button type="button" class="aw-clear">Vaciar selección</button>
      <button type="button" class="aw-commit">Crear grupo provisional con la selección</button>
    </div>
  </div>
</div>
"""

_COMPONENT_CSS = """
.aw-doc-browser {
  font-family: var(--st-font, sans-serif);
  color: var(--st-text-color);
}
.aw-thumb-panel {
  border: 1px solid color-mix(in srgb, var(--st-text-color) 18%, transparent);
  border-radius: .6rem;
  padding: .65rem;
  background: color-mix(in srgb, var(--st-secondary-background-color) 22%, transparent);
}
.aw-doc-browser-toolbar,
.aw-doc-browser-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: .7rem;
  flex-wrap: wrap;
  margin: .15rem 0 .65rem;
}
.aw-doc-browser-footer {
  margin-top: .8rem;
  padding: .15rem .05rem 0;
}
.aw-page-label,
.aw-selection-count {
  font-size: .82rem;
  opacity: .78;
}
.aw-thumb-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: .7rem;
}
.aw-thumb-card {
  position: relative;
  display: flex;
  flex-direction: column;
  min-width: 0;
  padding: .35rem;
  border: 1px solid color-mix(in srgb, var(--st-text-color) 18%, transparent);
  border-radius: .5rem;
  background: color-mix(in srgb, var(--st-secondary-background-color) 55%, transparent);
  cursor: pointer;
  text-align: left;
  color: inherit;
}
.aw-thumb-card:hover {
  border-color: color-mix(in srgb, var(--st-text-color) 45%, transparent);
  background: color-mix(in srgb, var(--st-text-color) 5%, var(--st-secondary-background-color));
}
.aw-thumb-card.selected {
  border-color: var(--st-primary-color);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--st-primary-color) 26%, transparent);
}
.aw-thumb-card:focus-visible,
.aw-page:focus-visible,
.aw-clear:focus-visible,
.aw-commit:focus-visible,
.aw-preview:focus-visible {
  outline: 2px solid var(--st-primary-color);
  outline-offset: 2px;
}
.aw-thumb-image-shell {
  position: relative;
  width: 100%;
  aspect-ratio: 3 / 4;
  border-radius: .35rem;
  overflow: hidden;
  background: color-mix(in srgb, var(--st-text-color) 5%, transparent);
  display: flex;
  align-items: center;
  justify-content: center;
}
.aw-thumb-image {
  width: 100%;
  height: 100%;
  object-fit: contain;
}
.aw-thumb-empty {
  padding: .8rem;
  font-size: .78rem;
  opacity: .65;
  text-align: center;
}
.aw-thumb-number {
  position: absolute;
  top: .25rem;
  left: .25rem;
  min-width: 1.6rem;
  padding: .12rem .35rem;
  border-radius: 999px;
  background: rgba(0, 0, 0, .72);
  color: white;
  font-size: .72rem;
  font-weight: 700;
  text-align: center;
}
.aw-thumb-check {
  position: absolute;
  top: .25rem;
  right: .25rem;
  width: 1.35rem;
  height: 1.35rem;
  border-radius: 50%;
  display: none;
  align-items: center;
  justify-content: center;
  background: var(--st-primary-color);
  color: white;
  font-size: .78rem;
  font-weight: 800;
}
.aw-thumb-card.selected .aw-thumb-check { display: flex; }
.aw-thumb-name {
  margin-top: .38rem;
  font-size: .78rem;
  line-height: 1.25;
  overflow-wrap: anywhere;
}
.aw-thumb-meta {
  margin-top: .18rem;
  font-size: .69rem;
  opacity: .64;
}
.aw-preview {
  margin-top: .35rem;
  border: 0;
  background: transparent;
  color: inherit;
  text-decoration: underline;
  text-underline-offset: .16rem;
  padding: .15rem 0;
  font-size: .72rem;
  cursor: pointer;
  opacity: .78;
  text-align: left;
}
.aw-page,
.aw-clear,
.aw-commit {
  border: 1px solid color-mix(in srgb, var(--st-text-color) 22%, transparent);
  border-radius: .4rem;
  background: var(--st-secondary-background-color);
  color: inherit;
  padding: .38rem .6rem;
  cursor: pointer;
  font: inherit;
  font-size: .78rem;
}
.aw-page:disabled,
.aw-commit:disabled {
  cursor: default;
  opacity: .42;
}
.aw-commit:not(:disabled) {
  border-color: color-mix(in srgb, var(--st-primary-color) 70%, transparent);
}
.aw-footer-actions { display: flex; gap: .45rem; flex-wrap: wrap; }
@media (max-width: 900px) {
  .aw-thumb-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 620px) {
  .aw-thumb-grid { grid-template-columns: 1fr; }
}
"""

_COMPONENT_JS = r"""
export default function(component) {
  const { parentElement, data, setTriggerValue } = component;
  const root = parentElement.querySelector('.aw-doc-browser');
  if (!root) return;

  const grid = root.querySelector('.aw-thumb-grid');
  const prev = root.querySelector('.aw-prev');
  const next = root.querySelector('.aw-next');
  const label = root.querySelector('.aw-page-label');
  const selectionCount = root.querySelector('.aw-selection-count');
  const clear = root.querySelector('.aw-clear');
  const commit = root.querySelector('.aw-commit');
  const page = Number(data.page || 0);
  const pageCount = Math.max(1, Number(data.page_count || 1));
  const total = Number(data.total || 0);
  const storageKey = `archive-workbench-catalog-document-selection:${String(data.selection_key || 'default')}`;
  const clearTokenKey = `${storageKey}:clear-token`;
  const clearToken = String(data.clear_token || '0');

  const readSelection = () => {
    try {
      const raw = JSON.parse(window.sessionStorage.getItem(storageKey) || '[]');
      return new Set(Array.isArray(raw) ? raw.map(String) : []);
    } catch (error) { return new Set(); }
  };
  let selected = readSelection();
  const previousToken = window.sessionStorage.getItem(clearTokenKey);
  if (previousToken !== clearToken) {
    selected = new Set();
    window.sessionStorage.setItem(clearTokenKey, clearToken);
    window.sessionStorage.setItem(storageKey, '[]');
  }
  const saveSelection = () => window.sessionStorage.setItem(storageKey, JSON.stringify([...selected]));

  const renderSelectionState = () => {
    const cards = grid.querySelectorAll('.aw-thumb-card');
    cards.forEach((card) => {
      const isSelected = selected.has(String(card.dataset.id));
      card.classList.toggle('selected', isSelected);
      card.setAttribute('aria-selected', String(isSelected));
    });
    const count = selected.size;
    selectionCount.textContent = count === 1 ? '1 archivo seleccionado' : `${count} archivos seleccionados`;
    commit.disabled = count === 0;
  };

  grid.replaceChildren();
  for (const item of data.items || []) {
    const id = String(item.id);
    const card = document.createElement('div');
    card.tabIndex = 0;
    card.className = 'aw-thumb-card';
    card.dataset.id = id;
    card.setAttribute('role', 'option');
    card.setAttribute('aria-label', `Seleccionar archivo ${String(item.ordinal)}: ${String(item.filename || '')}`);

    const imageShell = document.createElement('span');
    imageShell.className = 'aw-thumb-image-shell';
    if (item.thumbnail) {
      const image = document.createElement('img');
      image.className = 'aw-thumb-image';
      image.alt = '';
      image.src = String(item.thumbnail);
      imageShell.appendChild(image);
    } else {
      const empty = document.createElement('span');
      empty.className = 'aw-thumb-empty';
      empty.textContent = 'Sin miniatura';
      imageShell.appendChild(empty);
    }
    const number = document.createElement('span');
    number.className = 'aw-thumb-number';
    number.textContent = String(item.ordinal);
    imageShell.appendChild(number);
    const check = document.createElement('span');
    check.className = 'aw-thumb-check';
    check.textContent = '✓';
    imageShell.appendChild(check);
    card.appendChild(imageShell);

    const name = document.createElement('span');
    name.className = 'aw-thumb-name';
    name.textContent = String(item.filename || '');
    card.appendChild(name);
    const meta = document.createElement('span');
    meta.className = 'aw-thumb-meta';
    const pages = Number(item.page_count || 0);
    const used = Number(item.organized_count || 0);
    meta.textContent = `${pages ? `${pages} pág.` : 'páginas sin informar'}${used ? ` · usado ${used} vez/veces` : ''}`;
    card.appendChild(meta);

    const preview = document.createElement('button');
    preview.type = 'button';
    preview.className = 'aw-preview';
    preview.textContent = 'Abrir vista previa';
    preview.onclick = (event) => {
      event.preventDefault();
      event.stopPropagation();
      setTriggerValue('preview_commit', { id, nonce: Date.now() });
    };
    card.appendChild(preview);

    const toggleSelection = () => {
      if (selected.has(id)) selected.delete(id); else selected.add(id);
      saveSelection();
      renderSelectionState();
    };
    card.onclick = toggleSelection;
    card.onkeydown = (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        toggleSelection();
      }
    };
    grid.appendChild(card);
  }

  const firstOrdinal = (data.items || []).length ? Number(data.items[0].ordinal || 1) : 0;
  const lastOrdinal = (data.items || []).length ? Number(data.items[data.items.length - 1].ordinal || 0) : 0;
  label.textContent = total ? `Archivos ${firstOrdinal}–${lastOrdinal} de ${total}` : 'Sin archivos';
  prev.disabled = page <= 0;
  next.disabled = page >= pageCount - 1;
  prev.onclick = () => {
    if (page > 0) setTriggerValue('page_commit', { page: page - 1, nonce: Date.now() });
  };
  next.onclick = () => {
    if (page < pageCount - 1) setTriggerValue('page_commit', { page: page + 1, nonce: Date.now() });
  };
  clear.onclick = () => {
    selected = new Set();
    saveSelection();
    renderSelectionState();
  };
  commit.onclick = () => {
    if (!selected.size) return;
    setTriggerValue('create_group_commit', { ids: [...selected], nonce: Date.now() });
  };

  renderSelectionState();
}
"""


@lru_cache(maxsize=1)
def _renderer():
    import streamlit as st

    if not hasattr(st.components, "v2"):
        return None
    return st.components.v2.component(
        name="archive_workbench_catalog_document_browser",
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


def catalog_document_thumbnail_browser(
    st,
    *,
    items: list[dict[str, Any]],
    page: int,
    page_count: int,
    total: int,
    key: str,
    selection_key: str,
    clear_token: int,
) -> dict[str, Any]:
    """Navegador visual; selección y paginación visual permanecen locales salvo commits."""
    renderer = _renderer()
    if renderer is None:
        st.warning("La vista de miniaturas requiere Streamlit 1.51 o posterior.")
        return {}
    result = renderer(
        data={
            "items": items,
            "page": int(page),
            "page_count": int(page_count),
            "total": int(total),
            "selection_key": selection_key,
            "clear_token": int(clear_token),
        },
        key=key,
        height=max(520, 520 * ((len(items) + 2) // 3) + 135),
        width="stretch",
    )
    return {
        "page_commit": _result_value(result, "page_commit"),
        "preview_commit": _result_value(result, "preview_commit"),
        "create_group_commit": _result_value(result, "create_group_commit"),
    }
