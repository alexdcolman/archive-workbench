from __future__ import annotations

import base64
import mimetypes
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from archive_workbench.review import ReviewPageView, _normalized_polygons

_COMPONENT_HTML = r'''
<div class="aw-annotation-shell">
  <div class="aw-topbar">
    <div class="aw-nav-group aw-doc-nav">
      <button type="button" data-action="doc-prev" title="Documento anterior">‹ Documento</button>
      <span class="aw-doc-position"></span>
      <strong class="aw-doc-title"></strong>
      <button type="button" data-action="doc-next" title="Documento siguiente">Documento ›</button>
    </div>
    <span class="aw-divider"></span>
    <div class="aw-nav-group aw-page-nav">
      <button type="button" data-action="page-prev" title="Página anterior">‹ Página</button>
      <span class="aw-page-position"></span>
      <button type="button" data-action="page-next" title="Página siguiente">Página ›</button>
    </div>
    <span class="aw-page-review-summary">Página: <strong class="aw-page-review-label"></strong></span>
    <button type="button" data-action="page-review-toggle">Cambiar estado</button>
    <span class="aw-unsaved" hidden>cambios sin guardar</span>
    <button type="button" class="aw-secondary" data-action="jump-toggle">Ir a…</button>
  </div>
  <div class="aw-page-review-panel" hidden>
    <div class="aw-page-review-heading">Estado de revisión de la página</div>
    <div class="aw-page-review-options"></div>
    <textarea class="aw-page-review-note" rows="2" placeholder="Nota sobre el estado de esta página (opcional)" aria-label="Nota sobre el estado de revisión de esta página"></textarea>
    <div class="aw-page-review-help"></div>
    <div class="aw-page-review-actions">
      <button type="button" data-action="page-review-save">Guardar estado de la página</button>
      <button type="button" data-action="page-review-cancel">Cancelar</button>
    </div>
  </div>
  <div class="aw-jump" hidden>
    <input type="search" class="aw-jump-query" placeholder="Buscar documento por nombre" aria-label="Buscar documento por nombre" />
    <div class="aw-jump-results"></div>
  </div>
  <div class="aw-body">
    <section class="aw-image-panel" aria-label="Imagen de la página">
      <div class="aw-image-toolbar">
        <button type="button" data-action="zoom-out" title="Alejar">−</button>
        <button type="button" data-action="fit" title="Ajustar">Ajustar</button>
        <button type="button" data-action="zoom-in" title="Acercar">+</button>
        <span class="aw-zoom-label">100%</span>
        <span class="aw-image-help">Ctrl+rueda: zoom · arrastrar: recorrer</span>
      </div>
      <div class="aw-image-viewport">
        <div class="aw-image-stage">
          <img class="aw-page-image" alt="Página documental" draggable="false" />
          <svg class="aw-overlay" viewBox="0 0 1 1" preserveAspectRatio="none"></svg>
          <div class="aw-no-image" hidden>No hay una imagen de vista previa disponible para esta página.</div>
        </div>
      </div>
    </section>
    <section class="aw-text-panel" aria-label="Texto completo de la página">
      <div class="aw-block-nav">
        <button type="button" data-action="block-prev">‹ Bloque</button>
        <span class="aw-block-position"></span>
        <button type="button" data-action="block-next">Bloque ›</button>
      </div>
      <div class="aw-block-list"></div>
    </section>
  </div>
</div>
'''

_COMPONENT_CSS = r'''
.aw-annotation-shell { font-family:var(--st-font,sans-serif); color:var(--st-text-color); font-size:12.5px; }
.aw-topbar { position:sticky; top:0; z-index:30; display:flex; align-items:center; gap:.55rem; flex-wrap:wrap; padding:.42rem .5rem; margin-bottom:.48rem; background:var(--st-background-color); border:1px solid color-mix(in srgb,var(--st-text-color) 14%,transparent); border-radius:.48rem; box-shadow:0 1px 4px rgba(0,0,0,.08); }
.aw-nav-group { display:flex; align-items:center; gap:.34rem; min-width:0; }
.aw-doc-title { max-width:27rem; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.aw-divider { width:1px; height:1.45rem; background:color-mix(in srgb,var(--st-text-color) 18%,transparent); }
.aw-unsaved { font-size:.72rem; padding:.15rem .38rem; border-radius:999px; background:color-mix(in srgb,#d99000 16%,transparent); }
.aw-page-review-summary { white-space:nowrap; font-size:.74rem; opacity:.86; }
.aw-page-review-panel { display:grid; grid-template-columns:minmax(0,1fr); gap:.34rem; padding:.5rem .56rem; margin-bottom:.48rem; border:1px solid color-mix(in srgb,var(--st-text-color) 15%,transparent); border-radius:.44rem; background:var(--st-secondary-background-color); }
.aw-page-review-panel[hidden] { display:none; }
.aw-page-review-heading { font-weight:700; }
.aw-page-review-options { display:flex; flex-wrap:wrap; gap:.26rem; }
.aw-page-review-options button.active { border-color:var(--st-primary-color); background:color-mix(in srgb,var(--st-primary-color) 14%,var(--st-secondary-background-color)); box-shadow:0 0 0 1px var(--st-primary-color); }
.aw-page-review-note { box-sizing:border-box; width:100%; min-height:3.5rem; resize:vertical; border:1px solid color-mix(in srgb,var(--st-text-color) 22%,transparent); border-radius:.34rem; background:var(--st-background-color); color:var(--st-text-color); padding:.38rem .48rem; }
.aw-page-review-help { font-size:.72rem; opacity:.72; }
.aw-page-review-actions { display:flex; gap:.3rem; flex-wrap:wrap; }
button,input,textarea { font:inherit; }
.aw-topbar button,.aw-page-review-panel button,.aw-image-toolbar button,.aw-block-nav button,.aw-editor-actions button,.aw-type-palette button,.aw-selection-actions button,.aw-authority-results button,.aw-tag-tools button,.aw-comment-tools button,.aw-jump-results button,.aw-status-palette button,.aw-annotation-tabs button,.aw-mention-row button,.aw-existing-tag button,.aw-inline-action { border:1px solid color-mix(in srgb,var(--st-text-color) 22%,transparent); border-radius:.36rem; background:var(--st-secondary-background-color); color:var(--st-text-color); padding:.28rem .5rem; cursor:pointer; }
button:hover:not(:disabled) { border-color:var(--st-primary-color); }
button:disabled { opacity:.42; cursor:default; }
.aw-secondary { margin-left:auto; }
.aw-jump { border:1px solid color-mix(in srgb,var(--st-text-color) 15%,transparent); border-radius:.44rem; padding:.46rem; margin-bottom:.48rem; background:var(--st-secondary-background-color); }
.aw-jump-query,.aw-tag-input,.aw-comment-input,.aw-authority-query { box-sizing:border-box; width:100%; border:1px solid color-mix(in srgb,var(--st-text-color) 22%,transparent); border-radius:.34rem; background:var(--st-background-color); color:var(--st-text-color); padding:.38rem .48rem; }
.aw-comment-input { min-height:5.4rem; resize:vertical; }
.aw-jump-results,.aw-authority-results { display:grid; gap:.3rem; margin-top:.34rem; }
.aw-body { display:grid; grid-template-columns:minmax(0,44fr) minmax(0,56fr); gap:.68rem; height:calc(100vh - 13.8rem); min-height:620px; }
.aw-image-panel,.aw-text-panel { min-width:0; border:1px solid color-mix(in srgb,var(--st-text-color) 16%,transparent); border-radius:.48rem; background:var(--st-background-color); overflow:hidden; }
.aw-image-panel { display:flex; flex-direction:column; }
.aw-image-toolbar { flex:0 0 auto; display:flex; align-items:center; gap:.34rem; padding:.38rem; border-bottom:1px solid color-mix(in srgb,var(--st-text-color) 12%,transparent); }
.aw-image-help { margin-left:auto; opacity:.66; font-size:.72rem; }
.aw-zoom-label { min-width:3rem; font-variant-numeric:tabular-nums; }
.aw-image-viewport { flex:1 1 auto; overflow:auto; cursor:grab; overscroll-behavior:contain; background:color-mix(in srgb,var(--st-secondary-background-color) 82%,transparent); }
.aw-image-viewport.dragging { cursor:grabbing; user-select:none; }
.aw-image-stage { position:relative; width:100%; line-height:0; transform-origin:top left; }
.aw-page-image { display:block; width:100%; height:auto; pointer-events:none; user-select:none; }
.aw-overlay { position:absolute; inset:0; width:100%; height:100%; }
.aw-box { vector-effect:non-scaling-stroke; fill:rgba(20,120,180,.05); stroke:rgb(20,120,180); stroke-width:2.2; cursor:pointer; }
.aw-box:hover { fill:rgba(255,165,0,.16); stroke:rgb(235,135,0); stroke-width:3.5; }
.aw-box.active { fill:rgba(210,45,45,.10); stroke:rgb(210,45,45); stroke-width:4.6; }
.aw-box-label-bg { fill:rgba(0,0,0,.74); pointer-events:none; }
.aw-box-label { fill:white; font-weight:700; pointer-events:none; dominant-baseline:hanging; }
.aw-no-image { line-height:1.4; padding:1rem; }
.aw-text-panel { display:flex; flex-direction:column; }
.aw-block-nav { flex:0 0 auto; display:flex; align-items:center; justify-content:center; gap:.45rem; padding:.38rem; border-bottom:1px solid color-mix(in srgb,var(--st-text-color) 12%,transparent); }
.aw-block-list { flex:1 1 auto; overflow:auto; padding:.45rem; scroll-behavior:smooth; }
.aw-block { border:1px solid color-mix(in srgb,var(--st-text-color) 11%,transparent); border-radius:.42rem; padding:.45rem .52rem; margin-bottom:.38rem; background:var(--st-background-color); cursor:pointer; }
.aw-block:hover { border-color:color-mix(in srgb,var(--st-primary-color) 60%,transparent); }
.aw-block.active { border-color:var(--st-primary-color); box-shadow:0 0 0 1px var(--st-primary-color); cursor:default; }
.aw-block-head { display:flex; align-items:center; gap:.45rem; margin-bottom:.27rem; font-size:.69rem; opacity:.72; }
.aw-block-text { white-space:pre-wrap; line-height:1.30; overflow-wrap:anywhere; font-size:12px; }
.aw-editor { width:100%; box-sizing:border-box; min-height:8.7rem; border:1px solid color-mix(in srgb,var(--st-text-color) 24%,transparent); border-radius:.36rem; padding:.46rem .5rem; background:var(--st-background-color); color:var(--st-text-color); line-height:1.34; font-size:12px; white-space:pre-wrap; overflow-wrap:anywhere; outline:none; }
.aw-editor:focus { outline:2px solid color-mix(in srgb,var(--st-primary-color) 58%,transparent); outline-offset:1px; }
.aw-editor .aw-mention-mark { text-decoration:underline 2px color-mix(in srgb,var(--st-primary-color) 75%,transparent); text-decoration-skip-ink:none; border-radius:.16rem; background:color-mix(in srgb,var(--st-primary-color) 8%,transparent); }
.aw-editor .aw-mention-mark.stale { text-decoration-style:dashed; opacity:.72; }
.aw-editor-section-title { margin:.44rem 0 .24rem; font-size:.68rem; opacity:.7; text-transform:uppercase; letter-spacing:.035em; }
.aw-type-palette,.aw-status-palette { display:flex; flex-wrap:wrap; gap:.26rem; }
.aw-type-palette button,.aw-status-palette button { font-size:.73rem; padding:.24rem .42rem; }
.aw-type-palette button.active,.aw-status-palette button.active { border-color:var(--st-primary-color); background:color-mix(in srgb,var(--st-primary-color) 14%,var(--st-secondary-background-color)); box-shadow:0 0 0 1px var(--st-primary-color); }
.aw-selection-strip { display:flex; gap:.3rem; align-items:center; flex-wrap:wrap; margin:.46rem 0 0; padding:.38rem .42rem; border:1px solid color-mix(in srgb,var(--st-primary-color) 30%,transparent); border-radius:.38rem; background:color-mix(in srgb,var(--st-primary-color) 5%,var(--st-background-color)); }
.aw-selection-quote { flex:1 1 13rem; min-width:0; font-size:.75rem; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.aw-selection-actions { display:flex; gap:.25rem; flex-wrap:wrap; }
.aw-selection-actions button.active { border-color:var(--st-primary-color); box-shadow:0 0 0 1px var(--st-primary-color); }
.aw-annotations { margin-top:.5rem; border-top:1px solid color-mix(in srgb,var(--st-text-color) 12%,transparent); padding-top:.42rem; }
.aw-annotations-title { font-size:.7rem; font-weight:700; opacity:.76; text-transform:uppercase; letter-spacing:.035em; margin-bottom:.3rem; }
.aw-annotation-tabs { display:flex; gap:.28rem; flex-wrap:wrap; margin-bottom:.38rem; }
.aw-annotation-tabs button { font-size:.74rem; }
.aw-annotation-tabs button.active { border-color:var(--st-primary-color); background:color-mix(in srgb,var(--st-primary-color) 10%,var(--st-secondary-background-color)); box-shadow:0 0 0 1px var(--st-primary-color); }
.aw-count { opacity:.65; margin-left:.2rem; }
.aw-annotation-pane { border:1px solid color-mix(in srgb,var(--st-text-color) 10%,transparent); border-radius:.38rem; padding:.42rem; background:color-mix(in srgb,var(--st-secondary-background-color) 42%,transparent); }
.aw-pane-help { margin-bottom:.35rem; font-size:.72rem; opacity:.7; }
.aw-authority-results button { text-align:left; width:100%; }
.aw-authority-results small { display:block; opacity:.68; margin-top:.1rem; }
.aw-mention-list,.aw-comment-list { display:grid; gap:.3rem; margin-top:.4rem; }
.aw-mention-row,.aw-comment-row { border:1px solid color-mix(in srgb,var(--st-text-color) 10%,transparent); border-radius:.34rem; padding:.36rem .4rem; background:var(--st-background-color); }
.aw-mention-main { display:flex; align-items:center; gap:.35rem; flex-wrap:wrap; }
.aw-mention-text { font-weight:700; }
.aw-mention-meta,.aw-comment-meta { font-size:.68rem; opacity:.66; margin-top:.14rem; }
.aw-mention-actions { display:flex; gap:.24rem; flex-wrap:wrap; margin-top:.3rem; }
.aw-mention-actions button { font-size:.69rem; padding:.2rem .34rem; }
.aw-mention-actions button.active { border-color:var(--st-primary-color); }
.aw-tag-kind { display:flex; flex-wrap:wrap; gap:.26rem; margin:.32rem 0; }
.aw-tag-kind button { font-size:.7rem; }
.aw-tag-kind button.active { border-color:var(--st-primary-color); }
.aw-tag-tools,.aw-comment-tools { display:flex; flex-wrap:wrap; gap:.3rem; align-items:center; margin-top:.28rem; }
.aw-existing-tags { display:flex; flex-wrap:wrap; gap:.28rem; margin-bottom:.34rem; }
.aw-existing-tag { display:inline-flex; align-items:center; gap:.25rem; font-size:.7rem; padding:.18rem .25rem .18rem .38rem; border-radius:999px; background:var(--st-background-color); border:1px solid color-mix(in srgb,var(--st-text-color) 14%,transparent); }
.aw-existing-tag button { border:0; background:transparent; padding:0 .14rem; line-height:1; opacity:.62; }
.aw-muted { opacity:.67; font-size:.73rem; }
.aw-editor-actions { position:sticky; bottom:0; display:flex; gap:.35rem; margin-top:.5rem; padding:.45rem 0 .1rem; background:linear-gradient(transparent,var(--st-background-color) 28%); }
.aw-editor-actions .primary { border-color:var(--st-primary-color); background:var(--st-primary-color); color:white; font-weight:700; }
@media (max-width:900px) { .aw-body { grid-template-columns:1fr; height:auto; } .aw-image-panel { height:55vh; } .aw-text-panel { height:64vh; } .aw-doc-title { max-width:16rem; } }
'''

_COMPONENT_JS = r'''
export default function(component) {
  const { parentElement, data, setTriggerValue } = component;
  const pageKey = String(data.page_key || 'page');
  let state = parentElement.__awbAnnotationState;
  if (!state || state.pageKey !== pageKey) {
    state = {
      pageKey,
      activeId: String(data.initial_object_id || ((data.blocks || [])[0] || {}).object_id || ''),
      drafts: {}, zoom: 1, selection: null, annotationTab: 'mentions', tagKind: 'unclassified',
      tagText: '', commentText: '', authorityQuery: '', relinkMentionId: null, jumpOpen: false,
      pageReviewOpen: false, pageReviewStatus: String(data.page_review_status || 'unreviewed'),
      pageReviewNote: String(data.page_review_note || ''),
    };
    parentElement.__awbAnnotationState = state;
  }
  if (!state.pageReviewOpen) {
    state.pageReviewStatus = String(data.page_review_status || 'unreviewed');
    state.pageReviewNote = String(data.page_review_note || '');
  }
  const focusToken = String(data.focus_token ?? '');
  if (focusToken && state.lastFocusToken !== focusToken) {
    state.lastFocusToken = focusToken;
    if (data.focus_object_id) state.activeId = String(data.focus_object_id);
  }
  const blocks = data.blocks || [];
  const blockMap = new Map(blocks.map((b) => [String(b.object_id), b]));
  if (!blockMap.has(state.activeId) && blocks.length) state.activeId = String(blocks[0].object_id);
  const draftFor = (block) => {
    const id = String(block.object_id);
    if (!state.drafts[id] || Number(state.drafts[id].baseRevision) !== Number(block.revision_number)) {
      state.drafts[id] = {
        baseRevision: Number(block.revision_number), text: String(block.text || ''),
        objectType: String(block.object_type || ''), reviewStatus: String(block.review_status || 'unreviewed'), dirty: false,
      };
    }
    return state.drafts[id];
  };
  blocks.forEach(draftFor);

  const docTitle = parentElement.querySelector('.aw-doc-title');
  const docPosition = parentElement.querySelector('.aw-doc-position');
  const pagePosition = parentElement.querySelector('.aw-page-position');
  const blockPosition = parentElement.querySelector('.aw-block-position');
  const unsaved = parentElement.querySelector('.aw-unsaved');
  const pageReviewLabel = parentElement.querySelector('.aw-page-review-label');
  const pageReviewPanel = parentElement.querySelector('.aw-page-review-panel');
  const pageReviewOptions = parentElement.querySelector('.aw-page-review-options');
  const pageReviewNote = parentElement.querySelector('.aw-page-review-note');
  const pageReviewHelp = parentElement.querySelector('.aw-page-review-help');
  const list = parentElement.querySelector('.aw-block-list');
  const overlay = parentElement.querySelector('.aw-overlay');
  const image = parentElement.querySelector('.aw-page-image');
  const stage = parentElement.querySelector('.aw-image-stage');
  const imageViewport = parentElement.querySelector('.aw-image-viewport');
  const noImage = parentElement.querySelector('.aw-no-image');
  const zoomLabel = parentElement.querySelector('.aw-zoom-label');
  const jump = parentElement.querySelector('.aw-jump');
  const jumpQuery = parentElement.querySelector('.aw-jump-query');
  const jumpResults = parentElement.querySelector('.aw-jump-results');

  const emit = (payload) => setTriggerValue('action', {...payload, nonce: `${Date.now()}-${Math.random()}`});
  const activeIndex = () => blocks.findIndex((b) => String(b.object_id) === String(state.activeId));
  const anyDirty = () => Object.values(state.drafts).some((d) => d.dirty);
  const updateHeader = () => {
    docTitle.textContent = String(data.document_title || '');
    docPosition.textContent = `${Number(data.document_index || 0) + 1} / ${Number(data.document_count || 0)}`;
    pagePosition.textContent = `${Number(data.page_index || 0) + 1} / ${Number(data.page_count || 0)}`;
    const idx = activeIndex();
    blockPosition.textContent = blocks.length ? `${idx + 1} / ${blocks.length}` : '0 / 0';
    unsaved.hidden = !anyDirty();
    pageReviewLabel.textContent = String((data.page_status_label_map||{})[data.page_review_status] || data.page_review_status || 'Sin revisar');
    parentElement.querySelector('[data-action="doc-prev"]').disabled = !data.can_previous_document;
    parentElement.querySelector('[data-action="doc-next"]').disabled = !data.can_next_document;
    parentElement.querySelector('[data-action="page-prev"]').disabled = !data.can_previous_page;
    parentElement.querySelector('[data-action="page-next"]').disabled = !data.can_next_page;
    parentElement.querySelector('[data-action="block-prev"]').disabled = idx <= 0;
    parentElement.querySelector('[data-action="block-next"]').disabled = idx < 0 || idx >= blocks.length - 1;
  };

  const centerImageOn = (block) => {
    if (!block || !(block.polygons || []).length) return;
    const points = block.polygons.flat();
    const xs = points.map((p) => Number(p[0]));
    const ys = points.map((p) => Number(p[1]));
    const cx = (Math.min(...xs) + Math.max(...xs)) / 2;
    const cy = (Math.min(...ys) + Math.max(...ys)) / 2;
    requestAnimationFrame(() => {
      imageViewport.scrollTo({
        left: Math.max(0, cx * stage.scrollWidth - imageViewport.clientWidth / 2),
        top: Math.max(0, cy * stage.scrollHeight - imageViewport.clientHeight / 2),
        behavior:'smooth'
      });
    });
  };
  const centerTextOn = (id) => requestAnimationFrame(() => {
    const el = list.querySelector(`[data-object-id="${CSS.escape(String(id))}"]`);
    if (el) el.scrollIntoView({block:'center', behavior:'smooth'});
  });
  const focusBlock = (id, source='text') => {
    if (!blockMap.has(String(id))) return;
    state.activeId = String(id); state.selection = null; state.authorityQuery=''; state.relinkMentionId=null;
    renderBlocks(); renderOverlay(); updateHeader();
    if (source === 'image') centerTextOn(id); else centerImageOn(blockMap.get(String(id)));
  };
  const focusDelta = (delta) => {
    const idx = activeIndex(); const next = idx + delta;
    if (next >= 0 && next < blocks.length) focusBlock(blocks[next].object_id);
  };

  const typeButton = (draft, def) => {
    const btn = document.createElement('button'); btn.type='button'; btn.textContent=String(def.label);
    btn.classList.toggle('active', String(draft.objectType) === String(def.key));
    btn.onclick = (event) => { event.stopPropagation(); draft.objectType=String(def.key); draft.dirty=true; renderBlocks(); updateHeader(); };
    return btn;
  };
  const statusButton = (draft, status) => {
    const btn=document.createElement('button'); btn.type='button'; btn.textContent=String(status.label);
    btn.classList.toggle('active', String(draft.reviewStatus) === String(status.key));
    btn.onclick=(event)=>{ event.stopPropagation(); draft.reviewStatus=String(status.key); draft.dirty=true; renderBlocks(); updateHeader(); };
    return btn;
  };

  const appendDecoratedText = (editor, text, mentions) => {
    const ranges = (mentions || [])
      .filter((m) => Number.isInteger(Number(m.start_offset)) && Number.isInteger(Number(m.end_offset)))
      .map((m) => ({...m, start:Number(m.start_offset), end:Number(m.end_offset)}))
      .filter((m) => m.start >= 0 && m.end > m.start && m.end <= text.length)
      .sort((a,b) => a.start-b.start || a.end-b.end);
    let cursor = 0;
    for (const mention of ranges) {
      if (mention.start < cursor) continue;
      if (mention.start > cursor) editor.appendChild(document.createTextNode(text.slice(cursor, mention.start)));
      const mark=document.createElement('span'); mark.className='aw-mention-mark'+(mention.is_stale?' stale':'');
      mark.textContent=text.slice(mention.start, mention.end);
      mark.title=`${mention.authority_name || 'Mención sin entidad'} · ${String((data.mention_status_label_map||{})[mention.status] || mention.status)}`;
      editor.appendChild(mark); cursor=mention.end;
    }
    if (cursor < text.length) editor.appendChild(document.createTextNode(text.slice(cursor)));
  };

  const selectionOffsets = (editor) => {
    const sel=window.getSelection();
    if (!sel || !sel.rangeCount || !editor.contains(sel.anchorNode) || !editor.contains(sel.focusNode)) return null;
    const range=sel.getRangeAt(0); if(range.collapsed) return null;
    const before=document.createRange(); before.selectNodeContents(editor); before.setEnd(range.startContainer, range.startOffset);
    const through=document.createRange(); through.selectNodeContents(editor); through.setEnd(range.endContainer, range.endOffset);
    const start=before.toString().length, end=through.toString().length;
    if(end<=start) return null;
    return {start,end,text:editor.innerText.slice(start,end)};
  };

  const renderSelectionStrip = (container, block) => {
    if (!state.selection || state.selection.objectId !== String(block.object_id)) return;
    const strip=document.createElement('div'); strip.className='aw-selection-strip';
    const quote=document.createElement('div'); quote.className='aw-selection-quote'; quote.textContent=`Selección: “${state.selection.text}”`; strip.appendChild(quote);
    const actions=document.createElement('div'); actions.className='aw-selection-actions';
    [['mentions','Entidad'],['tags','Etiqueta'],['comments','Comentario']].forEach(([tab,label])=>{
      const btn=document.createElement('button'); btn.type='button'; btn.textContent=label; btn.classList.toggle('active',state.annotationTab===tab);
      btn.onclick=(ev)=>{ev.stopPropagation();state.annotationTab=tab;if(tab==='mentions')state.authorityQuery=state.selection.text;if(tab==='tags')state.tagText=state.selection.text;renderBlocks();};actions.appendChild(btn);
    });
    strip.appendChild(actions); container.appendChild(strip);
  };

  const authoritySearch = (queryValue) => {
    const q=String(queryValue||'').trim().toLocaleLowerCase();
    return (data.authorities||[]).filter((a)=>!q || String(a.search_text||'').includes(q)).slice(0,10);
  };

  const renderMentions = (pane, block, draft) => {
    const selected = state.selection && state.selection.objectId===String(block.object_id) ? state.selection : null;
    const help=document.createElement('div');help.className='aw-pane-help';help.textContent=selected
      ? 'La selección queda lista para vincularse con una entidad.'
      : 'Seleccioná texto para crear una mención. Las menciones existentes aparecen subrayadas dentro del editor.';pane.appendChild(help);

    if (selected) {
      const query=document.createElement('input');query.type='search';query.className='aw-authority-query';query.placeholder='Buscar entidad';query.value=state.authorityQuery || selected.text;
      const results=document.createElement('div');results.className='aw-authority-results';
      const fill=()=>{results.replaceChildren();const matches=authoritySearch(query.value);if(!matches.length){const empty=document.createElement('div');empty.className='aw-muted';empty.textContent='No hay coincidencias.';results.appendChild(empty);}for(const a of matches){const btn=document.createElement('button');btn.type='button';const strong=document.createElement('strong');strong.textContent=String(a.name);btn.appendChild(strong);const small=document.createElement('small');small.textContent=String(a.type_label||a.entity_type||'Entidad');btn.appendChild(small);btn.onclick=(ev)=>{ev.stopPropagation();emit({kind:'create_mention',object_id:String(block.object_id),start_offset:selected.start,end_offset:selected.end,mention_text:selected.text,authority_id:String(a.authority_id),status:'accepted'});};results.appendChild(btn);}};
      query.oninput=()=>{state.authorityQuery=query.value;fill();};pane.appendChild(query);pane.appendChild(results);fill();
      const pending=document.createElement('button');pending.type='button';pending.className='aw-inline-action';pending.textContent='Registrar como pendiente sin vincular';pending.onclick=(ev)=>{ev.stopPropagation();emit({kind:'create_mention',object_id:String(block.object_id),start_offset:selected.start,end_offset:selected.end,mention_text:selected.text,authority_id:'',status:'pending'});};pane.appendChild(pending);
    }

    const listEl=document.createElement('div');listEl.className='aw-mention-list';
    for(const mention of block.mentions || []){
      const row=document.createElement('div');row.className='aw-mention-row';
      const main=document.createElement('div');main.className='aw-mention-main';const name=document.createElement('span');name.className='aw-mention-text';name.textContent=String(mention.mention_text||'');main.appendChild(name);const arrow=document.createElement('span');arrow.textContent=mention.authority_name?`→ ${mention.authority_name}`:'→ sin entidad vinculada';main.appendChild(arrow);row.appendChild(main);
      const meta=document.createElement('div');meta.className='aw-mention-meta';meta.textContent=`${String((data.mention_status_label_map||{})[mention.status] || mention.status)} · offsets ${mention.start_offset}:${mention.end_offset}${mention.is_stale?' · desactualizada':''}`;row.appendChild(meta);
      const actions=document.createElement('div');actions.className='aw-mention-actions';
      for(const status of data.mention_statuses || []){const btn=document.createElement('button');btn.type='button';btn.textContent=String(status.label);btn.classList.toggle('active',String(mention.status)===String(status.key));btn.onclick=(ev)=>{ev.stopPropagation();emit({kind:'update_mention',object_id:String(block.object_id),mention_id:String(mention.mention_id),expected_revision:Number(mention.revision),status:String(status.key),authority_id:String(mention.authority_id||''),note:String(mention.note||'')});};actions.appendChild(btn);}
      const relink=document.createElement('button');relink.type='button';relink.textContent='Cambiar entidad';relink.onclick=(ev)=>{ev.stopPropagation();state.relinkMentionId=String(mention.mention_id);state.authorityQuery=String(mention.mention_text||'');renderBlocks();};actions.appendChild(relink);row.appendChild(actions);
      if(state.relinkMentionId===String(mention.mention_id)){
        const query=document.createElement('input');query.type='search';query.className='aw-authority-query';query.placeholder='Buscar entidad';query.value=state.authorityQuery || String(mention.mention_text||'');row.appendChild(query);
        const results=document.createElement('div');results.className='aw-authority-results';const fill=()=>{results.replaceChildren();for(const a of authoritySearch(query.value)){const btn=document.createElement('button');btn.type='button';btn.textContent=`${a.name} · ${a.type_label||a.entity_type||'Entidad'}`;btn.onclick=(ev)=>{ev.stopPropagation();emit({kind:'update_mention',object_id:String(block.object_id),mention_id:String(mention.mention_id),expected_revision:Number(mention.revision),status:String(mention.status),authority_id:String(a.authority_id),note:String(mention.note||'')});};results.appendChild(btn);}};query.oninput=()=>{state.authorityQuery=query.value;fill();};row.appendChild(results);fill();
      }
      listEl.appendChild(row);
    }
    if(!(block.mentions||[]).length){const empty=document.createElement('div');empty.className='aw-muted';empty.textContent='Sin menciones registradas en este bloque.';listEl.appendChild(empty);}pane.appendChild(listEl);
    const scan=document.createElement('button');scan.type='button';scan.className='aw-inline-action';scan.textContent='Buscar posibles menciones en este bloque';scan.onclick=(ev)=>{ev.stopPropagation();emit({kind:'scan_mentions',object_id:String(block.object_id)});};pane.appendChild(scan);
  };

  const renderTags = (pane, block) => {
    const existing=document.createElement('div');existing.className='aw-existing-tags';
    for(const tag of block.tags || []){const chip=document.createElement('span');chip.className='aw-existing-tag';const label=document.createElement('span');label.textContent=`${tag.kind_label||tag.tag_kind}: ${tag.tag}`;chip.appendChild(label);const remove=document.createElement('button');remove.type='button';remove.title='Quitar etiqueta';remove.textContent='×';remove.onclick=(ev)=>{ev.stopPropagation();emit({kind:'remove_tag',object_id:String(block.object_id),tag_id:String(tag.tag_id)});};chip.appendChild(remove);existing.appendChild(chip);}pane.appendChild(existing);
    if(!(block.tags||[]).length){const empty=document.createElement('div');empty.className='aw-muted';empty.textContent='Sin etiquetas en este bloque.';pane.appendChild(empty);}
    const kind=document.createElement('div');kind.className='aw-tag-kind';for(const k of data.tag_kinds||[]){const btn=document.createElement('button');btn.type='button';btn.textContent=String(k.label);btn.classList.toggle('active',state.tagKind===k.key);btn.onclick=(ev)=>{ev.stopPropagation();state.tagKind=String(k.key);renderBlocks();};kind.appendChild(btn);}pane.appendChild(kind);
    const input=document.createElement('input');input.type='text';input.className='aw-tag-input';input.placeholder='Nueva etiqueta';input.value=state.tagText || ((state.selection&&state.selection.objectId===String(block.object_id))?state.selection.text:'');input.oninput=()=>state.tagText=input.value;pane.appendChild(input);
    const tools=document.createElement('div');tools.className='aw-tag-tools';const add=document.createElement('button');add.type='button';add.textContent='Agregar etiqueta';add.onclick=(ev)=>{ev.stopPropagation();emit({kind:'add_tag',object_id:String(block.object_id),tag:String(input.value||''),tag_kind:String(state.tagKind||'unclassified')});};tools.appendChild(add);pane.appendChild(tools);
  };

  const renderComments = (pane, block) => {
    const comments=document.createElement('div');comments.className='aw-comment-list';
    for(const comment of [...(block.comments||[])].reverse()){const row=document.createElement('div');row.className='aw-comment-row';const body=document.createElement('div');body.textContent=String(comment.body||'');row.appendChild(body);const meta=document.createElement('div');meta.className='aw-comment-meta';meta.textContent=`${comment.created_by||''} · ${String(comment.created_at||'').replace('T',' ').slice(0,16)}`;row.appendChild(meta);comments.appendChild(row);}if(!(block.comments||[]).length){const empty=document.createElement('div');empty.className='aw-muted';empty.textContent='Sin comentarios en este bloque.';comments.appendChild(empty);}pane.appendChild(comments);
    const input=document.createElement('textarea');input.className='aw-comment-input';input.placeholder='Nuevo comentario sobre este bloque';input.value=state.commentText||'';input.oninput=()=>state.commentText=input.value;pane.appendChild(input);
    const tools=document.createElement('div');tools.className='aw-comment-tools';const add=document.createElement('button');add.type='button';add.textContent='Agregar comentario';add.onclick=(ev)=>{ev.stopPropagation();emit({kind:'add_comment',object_id:String(block.object_id),body:String(input.value||'')});};tools.appendChild(add);pane.appendChild(tools);
  };

  const renderAnnotations = (container, block, draft) => {
    const wrap=document.createElement('div');wrap.className='aw-annotations';
    const heading=document.createElement('div');heading.className='aw-annotations-title';heading.textContent='Anotaciones del bloque';wrap.appendChild(heading);
    const tabs=document.createElement('div');tabs.className='aw-annotation-tabs';
    const defs=[['mentions','Menciones',(block.mentions||[]).length],['tags','Etiquetas',(block.tags||[]).length],['comments','Comentarios',(block.comments||[]).length]];
    for(const [key,label,count] of defs){const btn=document.createElement('button');btn.type='button';btn.classList.toggle('active',state.annotationTab===key);btn.innerHTML='';const txt=document.createElement('span');txt.textContent=label;btn.appendChild(txt);const c=document.createElement('span');c.className='aw-count';c.textContent=String(count);btn.appendChild(c);btn.onclick=(ev)=>{ev.stopPropagation();state.annotationTab=key;if(key==='mentions'&&state.selection)state.authorityQuery=state.selection.text;if(key==='tags'&&state.selection)state.tagText=state.selection.text;renderBlocks();};tabs.appendChild(btn);}wrap.appendChild(tabs);
    const pane=document.createElement('div');pane.className='aw-annotation-pane';if(state.annotationTab==='mentions')renderMentions(pane,block,draft);else if(state.annotationTab==='tags')renderTags(pane,block);else renderComments(pane,block);wrap.appendChild(pane);container.appendChild(wrap);
  };

  const renderBlocks = () => {
    list.replaceChildren();
    for (const block of blocks) {
      const id=String(block.object_id); const draft=draftFor(block); const active=id===String(state.activeId);
      const card=document.createElement('article');card.className='aw-block';card.classList.toggle('active',active);card.dataset.objectId=id;
      card.onclick=()=>{ if(!active) focusBlock(id,'text'); };
      const head=document.createElement('div');head.className='aw-block-head';head.textContent=`${Number(block.order_index)+1} · ${String((data.type_label_map||{})[draft.objectType] || draft.objectType)} · ${String((data.status_label_map||{})[draft.reviewStatus] || draft.reviewStatus)}`;card.appendChild(head);
      if (!active) { const text=document.createElement('div');text.className='aw-block-text';text.textContent=draft.text;card.appendChild(text);list.appendChild(card);continue; }

      const editor=document.createElement('div');editor.className='aw-editor';editor.contentEditable='true';editor.setAttribute('role','textbox');editor.setAttribute('aria-multiline','true');editor.setAttribute('aria-label',`Texto del bloque ${Number(block.order_index)+1}`);editor.spellcheck=false;
      if(draft.dirty) editor.textContent=draft.text; else appendDecoratedText(editor,draft.text,block.mentions||[]);
      editor.onclick=(ev)=>ev.stopPropagation();
      editor.oninput=()=>{draft.text=editor.innerText.replace(/\r/g,'');draft.dirty=true;state.selection=null;updateHeader();};
      editor.onmouseup=()=>{const sel=selectionOffsets(editor);if(sel){state.selection={objectId:id,...sel};state.authorityQuery=sel.text;renderBlocks();requestAnimationFrame(()=>{const activeCard=list.querySelector(`[data-object-id="${CSS.escape(id)}"]`);if(activeCard)activeCard.scrollIntoView({block:'nearest'});});}};
      editor.onkeyup=(event)=>{if(event.key==='Escape'){state.selection=null;renderBlocks();}};
      card.appendChild(editor);
      renderSelectionStrip(card,block);

      const typeTitle=document.createElement('div');typeTitle.className='aw-editor-section-title';typeTitle.textContent='Clase del fragmento';card.appendChild(typeTitle);
      const palette=document.createElement('div');palette.className='aw-type-palette';(data.object_types||[]).forEach((def)=>palette.appendChild(typeButton(draft,def)));card.appendChild(palette);
      const statusTitle=document.createElement('div');statusTitle.className='aw-editor-section-title';statusTitle.textContent='Estado de revisión';card.appendChild(statusTitle);
      const statuses=document.createElement('div');statuses.className='aw-status-palette';(data.review_statuses||[]).forEach((status)=>statuses.appendChild(statusButton(draft,status)));card.appendChild(statuses);
      renderAnnotations(card,block,draft);

      const actions=document.createElement('div');actions.className='aw-editor-actions';
      const save=document.createElement('button');save.type='button';save.textContent='Guardar';save.onclick=(ev)=>{ev.stopPropagation();emit({kind:'save',object_id:id,expected_revision:Number(block.revision_number),text:draft.text,object_type:draft.objectType,review_status:draft.reviewStatus,advance:'none'});};actions.appendChild(save);
      const saveNext=document.createElement('button');saveNext.type='button';saveNext.className='primary';const idx=activeIndex();const lastBlock=idx===blocks.length-1;saveNext.textContent=!lastBlock?'Guardar y siguiente':data.can_next_page?'Guardar y página siguiente':data.can_next_document?'Guardar y documento siguiente':'Guardar';saveNext.onclick=(ev)=>{ev.stopPropagation();let advance='none';if(!lastBlock)advance='block';else if(data.can_next_page)advance='page';else if(data.can_next_document)advance='document';emit({kind:'save',object_id:id,expected_revision:Number(block.revision_number),text:draft.text,object_type:draft.objectType,review_status:draft.reviewStatus,advance});};actions.appendChild(saveNext);card.appendChild(actions);
      list.appendChild(card);
    }
    updateHeader();
  };

  const renderOverlay = () => {
    overlay.replaceChildren();
    for (const block of blocks) for (const polygon of block.polygons || []) {
      const xs=polygon.map((p)=>Number(p[0])), ys=polygon.map((p)=>Number(p[1])); if(!xs.length)continue;
      const x=Math.min(...xs),y=Math.min(...ys),w=Math.max(...xs)-x,h=Math.max(...ys)-y;if(!(w>0&&h>0))continue;
      const group=document.createElementNS('http://www.w3.org/2000/svg','g');group.setAttribute('role','button');group.setAttribute('tabindex','0');group.onclick=(ev)=>{ev.stopPropagation();focusBlock(block.object_id,'image');};
      const rect=document.createElementNS('http://www.w3.org/2000/svg','rect');rect.setAttribute('x',x);rect.setAttribute('y',y);rect.setAttribute('width',w);rect.setAttribute('height',h);rect.setAttribute('class','aw-box'+(String(block.object_id)===String(state.activeId)?' active':''));group.appendChild(rect);
      const bg=document.createElementNS('http://www.w3.org/2000/svg','rect');bg.setAttribute('x',x);bg.setAttribute('y',y);bg.setAttribute('width','.035');bg.setAttribute('height','.028');bg.setAttribute('class','aw-box-label-bg');group.appendChild(bg);
      const label=document.createElementNS('http://www.w3.org/2000/svg','text');label.setAttribute('x',x+.004);label.setAttribute('y',y+.003);label.setAttribute('font-size','.018');label.setAttribute('class','aw-box-label');label.textContent=String(Number(block.order_index)+1);group.appendChild(label);overlay.appendChild(group);
    }
  };

  const renderPageReview = () => {
    pageReviewPanel.hidden = !state.pageReviewOpen;
    if (!state.pageReviewOpen) return;
    pageReviewOptions.replaceChildren();
    for (const status of data.review_statuses || []) {
      const btn=document.createElement('button');btn.type='button';btn.textContent=String(status.label);
      btn.classList.toggle('active',String(state.pageReviewStatus)===String(status.key));
      btn.onclick=(ev)=>{ev.stopPropagation();state.pageReviewStatus=String(status.key);renderPageReview();};
      pageReviewOptions.appendChild(btn);
    }
    pageReviewNote.value=String(state.pageReviewNote||'');
    pageReviewNote.oninput=()=>{state.pageReviewNote=pageReviewNote.value;};
    pageReviewHelp.textContent=state.pageReviewStatus==='approved'
      ? 'Las sugerencias automáticas pueden usar esta página con el filtro de calidad predeterminado.'
      : 'Las sugerencias automáticas usan por defecto sólo páginas aprobadas.';
  };

  const applyZoom = (next) => { state.zoom=Math.max(.5,Math.min(5,next));stage.style.width=`${state.zoom*100}%`;zoomLabel.textContent=`${Math.round(state.zoom*100)}%`; };
  parentElement.querySelector('[data-action="zoom-in"]').onclick=()=>applyZoom(state.zoom+.25);
  parentElement.querySelector('[data-action="zoom-out"]').onclick=()=>applyZoom(state.zoom-.25);
  parentElement.querySelector('[data-action="fit"]').onclick=()=>{applyZoom(1);imageViewport.scrollTo({top:0,left:0,behavior:'smooth'});};
  parentElement.querySelector('[data-action="block-prev"]').onclick=()=>focusDelta(-1);
  parentElement.querySelector('[data-action="block-next"]').onclick=()=>focusDelta(1);
  const nav = (scope,delta) => emit({kind:'navigate',scope,delta});
  parentElement.querySelector('[data-action="doc-prev"]').onclick=()=>nav('document',-1);
  parentElement.querySelector('[data-action="doc-next"]').onclick=()=>nav('document',1);
  parentElement.querySelector('[data-action="page-prev"]').onclick=()=>nav('page',-1);
  parentElement.querySelector('[data-action="page-next"]').onclick=()=>nav('page',1);
  parentElement.querySelector('[data-action="jump-toggle"]').onclick=()=>{state.jumpOpen=!state.jumpOpen;jump.hidden=!state.jumpOpen;if(state.jumpOpen){jumpQuery.focus();renderJump();}};
  parentElement.querySelector('[data-action="page-review-toggle"]').onclick=()=>{state.pageReviewOpen=!state.pageReviewOpen;if(state.pageReviewOpen){state.pageReviewStatus=String(data.page_review_status||'unreviewed');state.pageReviewNote=String(data.page_review_note||'');}renderPageReview();};
  parentElement.querySelector('[data-action="page-review-cancel"]').onclick=()=>{state.pageReviewOpen=false;state.pageReviewStatus=String(data.page_review_status||'unreviewed');state.pageReviewNote=String(data.page_review_note||'');renderPageReview();};
  parentElement.querySelector('[data-action="page-review-save"]').onclick=()=>emit({kind:'save_page_review',editable_page_id:String(data.editable_page_id||''),review_status:String(state.pageReviewStatus||'unreviewed'),review_note:String(state.pageReviewNote||'')});
  const renderJump=()=>{jumpResults.replaceChildren();const q=String(jumpQuery.value||'').trim().toLocaleLowerCase();(data.documents||[]).filter((d)=>!q||String(d.title||'').toLocaleLowerCase().includes(q)||String(d.source_key||'').toLocaleLowerCase().includes(q)).slice(0,12).forEach((d)=>{const btn=document.createElement('button');btn.type='button';btn.textContent=String(d.title||d.source_key);btn.onclick=()=>emit({kind:'jump',source_key:String(d.source_key),page:Number((d.pages||[])[0]||1)});jumpResults.appendChild(btn);});};
  jumpQuery.oninput=renderJump;

  let dragging=false,startX=0,startY=0,startLeft=0,startTop=0;
  imageViewport.onpointerdown=(event)=>{if(event.button!==0||event.target.closest('.aw-box'))return;dragging=true;startX=event.clientX;startY=event.clientY;startLeft=imageViewport.scrollLeft;startTop=imageViewport.scrollTop;imageViewport.classList.add('dragging');imageViewport.setPointerCapture(event.pointerId);};
  imageViewport.onpointermove=(event)=>{if(!dragging)return;imageViewport.scrollLeft=startLeft-(event.clientX-startX);imageViewport.scrollTop=startTop-(event.clientY-startY);};
  const endDrag=(event)=>{if(!dragging)return;dragging=false;imageViewport.classList.remove('dragging');if(imageViewport.hasPointerCapture(event.pointerId))imageViewport.releasePointerCapture(event.pointerId);};imageViewport.onpointerup=endDrag;imageViewport.onpointercancel=endDrag;
  imageViewport.onwheel=(event)=>{if(!event.ctrlKey&&!event.metaKey)return;event.preventDefault();applyZoom(state.zoom+(event.deltaY<0?.15:-.15));};

  applyZoom(state.zoom);
  if (data.image_data_url) { image.hidden=false; noImage.hidden=true; if(image.src!==data.image_data_url) image.src=data.image_data_url; } else { image.hidden=true; overlay.replaceChildren(); noImage.hidden=false; }
  jump.hidden=!state.jumpOpen;
  renderPageReview(); renderBlocks(); renderOverlay(); updateHeader();
}
'''


def _image_data_url(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def build_annotation_payload(
    view: ReviewPageView,
    *,
    object_types: list[dict[str, str]],
    authorities: list[Any],
    mentions_by_object: dict[str, list[Any]],
    comments_by_object: dict[str, list[Any]],
    type_label_map: dict[str, str],
    document_rows: list[Any],
    document_index: int,
    page_index: int,
    initial_object_id: str | None,
) -> dict[str, Any]:
    blocks: list[dict[str, Any]] = []
    for item in view.objects:
        if item.lifecycle_status != "active":
            continue
        blocks.append(
            {
                "object_id": item.object_id,
                "order_index": item.order_index,
                "object_type": item.object_type,
                "review_status": item.review_status,
                "revision_number": item.revision_number,
                "text": item.text,
                "polygons": [
                    [[x, y] for x, y in polygon]
                    for polygon in _normalized_polygons(item.geometry, page=view.page)
                ],
                "tags": [
                    {
                        "tag_id": row.tag_id,
                        "tag": row.tag,
                        "tag_kind": row.tag_kind,
                        "kind_label": {
                            "thematic": "Temática",
                            "conceptual": "Conceptual",
                            "workflow": "Flujo de trabajo",
                            "unclassified": "Sin clasificar",
                        }.get(row.tag_kind, row.tag_kind),
                    }
                    for row in item.tags
                ],
                "comments": [
                    {
                        "body": row.body,
                        "created_by": row.created_by,
                        "created_at": row.created_at.isoformat(),
                    }
                    for row in comments_by_object.get(item.object_id, [])
                ],
                "mentions": [
                    {
                        "mention_id": row.mention_id,
                        "mention_text": row.mention_text,
                        "authority_id": row.authority_id,
                        "authority_name": row.authority_name,
                        "status": row.status,
                        "revision": row.revision,
                        "note": row.note,
                        "source": row.source,
                        "start_offset": row.start_offset,
                        "end_offset": row.end_offset,
                        "is_stale": row.is_stale,
                    }
                    for row in mentions_by_object.get(item.object_id, [])
                ],
            }
        )
    docs = [
        {"source_key": row.source_key, "title": row.title, "pages": list(row.editable_pages)}
        for row in document_rows
    ]
    authority_payload = []
    for row in authorities:
        aliases = [alias.alias for alias in getattr(row, "aliases", [])]
        searchable = " ".join([row.preferred_name, *aliases]).casefold()
        authority_payload.append(
            {
                "authority_id": row.authority_id,
                "name": row.preferred_name,
                "entity_type": row.entity_type,
                "type_label": {
                    "person": "Persona",
                    "organization": "Organismo / institución",
                    "place": "Lugar",
                    "event": "Acontecimiento",
                    "work": "Obra / publicación",
                    "other": "Otra entidad",
                }.get(row.entity_type, row.entity_type),
                "search_text": searchable,
            }
        )
    page_count = len(document_rows[document_index].editable_pages) if document_rows else 0
    return {
        "page_key": f"{view.source_key}:{view.page}",
        "editable_page_id": view.editable_page_id,
        "page_review_status": view.page_review_status,
        "page_review_note": view.page_review_note or "",
        "page_status_label_map": {
            "unreviewed": "Sin revisar",
            "needs_review": "Requiere revisión",
            "reviewed": "Revisada",
            "approved": "Aprobada",
        },
        "document_title": view.title,
        "document_index": document_index,
        "document_count": len(document_rows),
        "page_index": page_index,
        "page_count": page_count,
        "can_previous_document": document_index > 0,
        "can_next_document": document_index + 1 < len(document_rows),
        "can_previous_page": page_index > 0,
        "can_next_page": page_index + 1 < page_count,
        "initial_object_id": initial_object_id,
        "focus_object_id": initial_object_id,
        "image_data_url": _image_data_url(view.preview_path),
        "blocks": blocks,
        "object_types": object_types,
        "type_label_map": type_label_map,
        "review_statuses": [
            {"key": "unreviewed", "label": "Sin revisar"},
            {"key": "needs_review", "label": "Requiere revisión"},
            {"key": "reviewed", "label": "Revisado"},
            {"key": "approved", "label": "Aprobado"},
        ],
        "status_label_map": {
            "unreviewed": "Sin revisar",
            "needs_review": "Requiere revisión",
            "reviewed": "Revisado",
            "approved": "Aprobado",
        },
        "mention_statuses": [
            {"key": "pending", "label": "Pendiente"},
            {"key": "accepted", "label": "Aceptada"},
            {"key": "modified", "label": "Modificada"},
            {"key": "rejected", "label": "Rechazada"},
        ],
        "mention_status_label_map": {
            "pending": "Pendiente",
            "accepted": "Aceptada",
            "modified": "Modificada",
            "rejected": "Rechazada",
        },
        "tag_kinds": [
            {"key": "thematic", "label": "Temática"},
            {"key": "conceptual", "label": "Conceptual"},
            {"key": "workflow", "label": "Flujo de trabajo"},
            {"key": "unclassified", "label": "Sin clasificar"},
        ],
        "authorities": authority_payload,
        "documents": docs,
    }


@lru_cache(maxsize=1)
def _renderer():
    import streamlit as st

    if not hasattr(st.components, "v2"):
        return None
    return st.components.v2.component(
        name="archive_workbench_annotation_station",
        html=_COMPONENT_HTML,
        css=_COMPONENT_CSS,
        js=_COMPONENT_JS,
    )


def annotation_station(payload: dict[str, Any], *, key: str) -> dict[str, Any] | None:
    renderer = _renderer()
    if renderer is None:
        return None
    result = renderer(
        data=payload,
        key=key,
        height=900,
        width="stretch",
        on_action_change=lambda: None,
    )
    action = getattr(result, "action", None)
    return dict(action) if isinstance(action, Mapping) else None
