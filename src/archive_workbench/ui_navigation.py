from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache


@lru_cache(maxsize=1)
def _context_help_renderer():
    """Registra ayuda contextual visible mediante un icono de información."""

    import streamlit as st

    if not hasattr(st.components, "v2"):
        return None
    return st.components.v2.component(
        name="archive_workbench_context_help",
        js=r"""
        export default function(component) {
          const { data } = component;
          const targets = Array.isArray(data?.targets) ? data.targets : [];
          const doc = document;
          const win = window;
          const normalize = (value) => String(value || '').replace(/\s+/g, ' ').trim();
          const cleanLabel = (element) => {
            if (!element) return '';
            const clone = element.cloneNode(true);
            clone.querySelectorAll('[data-aw-info-icon], [data-aw-help-description]').forEach((node) => node.remove());
            return normalize(clone.textContent);
          };

          const styleId = 'archive-workbench-context-help-style';
          if (!doc.getElementById(styleId)) {
            const style = doc.createElement('style');
            style.id = styleId;
            style.textContent = `
              .aw-info-icon {
                display: inline-flex;
                align-items: center;
                justify-content: center;
                width: 1rem;
                height: 1rem;
                margin-left: .35rem;
                border: 1px solid currentColor;
                border-radius: 50%;
                box-sizing: border-box;
                font-size: .68rem;
                font-weight: 700;
                line-height: 1;
                opacity: .72;
                vertical-align: middle;
                cursor: help;
                user-select: none;
                flex: 0 0 auto;
              }
              .aw-info-icon:hover,
              .aw-info-icon:focus-visible {
                opacity: 1;
                outline: 2px solid currentColor;
                outline-offset: 2px;
              }
              .aw-choice-info-fallback {
                position: absolute;
                right: 2.4rem;
                top: 50%;
                transform: translateY(-50%);
                z-index: 5;
                margin-left: 0;
              }
              .aw-context-tooltip {
                position: fixed;
                z-index: 2147483647;
                display: none;
                max-width: min(30rem, calc(100vw - 2rem));
                padding: .6rem .75rem;
                border: 1px solid color-mix(in srgb, var(--st-text-color, CanvasText) 24%, transparent);
                border-radius: .45rem;
                background: var(--st-secondary-background-color, Canvas);
                color: var(--st-text-color, CanvasText);
                box-shadow: 0 .35rem 1.25rem rgba(0, 0, 0, .28);
                opacity: 1;
                isolation: isolate;
                font-size: .86rem;
                font-weight: 400;
                line-height: 1.4;
                text-align: left;
                white-space: normal;
                pointer-events: none;
              }
              .aw-sr-only {
                position: absolute !important;
                width: 1px !important;
                height: 1px !important;
                padding: 0 !important;
                margin: -1px !important;
                overflow: hidden !important;
                clip: rect(0, 0, 0, 0) !important;
                white-space: nowrap !important;
                border: 0 !important;
              }
            `;
            doc.head.appendChild(style);
          }

          const tooltipId = 'archive-workbench-context-tooltip';
          let tooltip = doc.getElementById(tooltipId);
          if (!tooltip) {
            tooltip = doc.createElement('div');
            tooltip.id = tooltipId;
            tooltip.className = 'aw-context-tooltip';
            tooltip.setAttribute('role', 'tooltip');
            doc.body.appendChild(tooltip);
          }

          let activeAnchor = null;

          const hideTooltip = () => {
            tooltip.style.display = 'none';
            activeAnchor = null;
          };

          const showTooltip = (anchor, help) => {
            if (!anchor || !help) return;
            tooltip.textContent = String(help);
            activeAnchor = anchor;
            tooltip.style.display = 'block';
            tooltip.style.left = '0px';
            tooltip.style.top = '0px';
            const rect = anchor.getBoundingClientRect();
            const tipRect = tooltip.getBoundingClientRect();
            const margin = 8;
            let left = rect.left + (rect.width / 2) - (tipRect.width / 2);
            left = Math.max(margin, Math.min(left, win.innerWidth - tipRect.width - margin));
            let top = rect.bottom + margin;
            if (top + tipRect.height > win.innerHeight - margin) {
              top = Math.max(margin, rect.top - tipRect.height - margin);
            }
            tooltip.style.left = `${Math.round(left)}px`;
            tooltip.style.top = `${Math.round(top)}px`;
          };

          const descriptionId = (kind, scopeKey, label) => {
            const raw = `${kind}-${scopeKey}-${label}`.toLowerCase().replace(/[^a-z0-9_-]+/g, '-');
            return `aw-help-${raw}`.slice(0, 180);
          };

          const ensureDescription = (host, {kind, scopeKey, label, help}) => {
            const id = descriptionId(kind, scopeKey, label);
            let description = doc.getElementById(id);
            if (!description) {
              description = doc.createElement('span');
              description.id = id;
              description.className = 'aw-sr-only';
              description.dataset.awHelpDescription = '1';
              host.appendChild(description);
            }
            if (description.textContent !== String(help)) description.textContent = String(help);
            return description;
          };

          const pointerFocusIsRecent = (element) => {
            const timestamp = Number(element?.dataset?.awHelpPointerDownAt || 0);
            return timestamp > 0 && (win.performance.now() - timestamp) < 750;
          };

          const showTooltipForKeyboardFocus = (focusElement, anchor, help) => {
            if (!focusElement || !anchor || pointerFocusIsRecent(focusElement)) return;
            win.requestAnimationFrame(() => {
              if (!focusElement.isConnected || !anchor.isConnected || pointerFocusIsRecent(focusElement)) return;
              if (focusElement.matches(':focus-visible')) showTooltip(anchor, help);
            });
          };

          const bindFocusBehavior = (element, help, anchor = element) => {
            if (!element || element.dataset.awHelpFocusBehaviorBound === '1') return;
            element.dataset.awHelpFocusBehaviorBound = '1';
            element.addEventListener('pointerdown', () => {
              element.dataset.awHelpPointerDownAt = String(win.performance.now());
              hideTooltip();
            });
            element.addEventListener('focus', () => showTooltipForKeyboardFocus(element, anchor, help));
            element.addEventListener('blur', hideTooltip);
            element.addEventListener('keydown', (event) => {
              if (event.key === 'Escape') hideTooltip();
            });
          };

          const bindIcon = (icon, help) => {
            icon.dataset.awHelpText = String(help);
            if (icon.dataset.awHelpBound === '1') return;
            icon.dataset.awHelpBound = '1';
            icon.addEventListener('mouseenter', () => showTooltip(icon, icon.dataset.awHelpText));
            icon.addEventListener('mouseleave', () => {
              if (activeAnchor === icon) hideTooltip();
            });
            bindFocusBehavior(icon, icon.dataset.awHelpText, icon);
          };

          const ensureInfoIcon = (host, {help, focusable, fallbackChoice = false}) => {
            let icon = host.querySelector(':scope > [data-aw-info-icon="1"]');
            if (!icon) {
              icon = doc.createElement('span');
              icon.className = 'aw-info-icon';
              icon.dataset.awInfoIcon = '1';
              icon.textContent = 'i';
              host.appendChild(icon);
            }
            icon.classList.toggle('aw-choice-info-fallback', Boolean(fallbackChoice));
            if (focusable) {
              icon.tabIndex = 0;
              icon.setAttribute('aria-label', 'Información');
            } else {
              icon.removeAttribute('tabindex');
              icon.setAttribute('aria-hidden', 'true');
            }
            bindIcon(icon, help);
            return icon;
          };

          const applyHeadingHelp = (element, target) => {
            if (!element) return;
            const description = ensureDescription(element, {
              kind: 'heading', scopeKey: '', label: target.label, help: target.help,
            });
            const icon = ensureInfoIcon(element, {help: target.help, focusable: true});
            icon.setAttribute('aria-describedby', description.id);
          };

          const applyTabHelp = (element, target) => {
            if (!element) return;
            const description = ensureDescription(element, {
              kind: 'tab', scopeKey: target.scope_key, label: target.label, help: target.help,
            });
            element.setAttribute('aria-describedby', description.id);
            element.setAttribute('aria-description', String(target.help));
            const icon = ensureInfoIcon(element, {help: target.help, focusable: false});
            bindFocusBehavior(element, icon.dataset.awHelpText, icon);
          };

          const visible = (element) => {
            if (!element) return false;
            const style = win.getComputedStyle(element);
            const rect = element.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
          };

          const applyChoiceHelp = (scope, target) => {
            if (!scope) return;
            let host = Array.from(scope.querySelectorAll('label, [data-testid="stWidgetLabel"]')).find(visible);
            let fallbackChoice = false;
            if (!host) {
              host = scope;
              fallbackChoice = true;
              if (win.getComputedStyle(scope).position === 'static') scope.style.position = 'relative';
            }
            const description = ensureDescription(host, {
              kind: 'choice', scopeKey: target.scope_key, label: target.label, help: target.help,
            });
            const icon = ensureInfoIcon(host, {help: target.help, focusable: true, fallbackChoice});
            icon.setAttribute('aria-describedby', description.id);
          };

          const scopedTargets = new Map();
          const headingTargets = [];
          for (const target of targets) {
            const kind = String(target?.kind || '');
            const scopeKey = String(target?.scope_key || '');
            if (kind === 'heading') {
              headingTargets.push(target);
            } else if (scopeKey) {
              if (!scopedTargets.has(scopeKey)) scopedTargets.set(scopeKey, []);
              scopedTargets.get(scopeKey).push(target);
            }
          }

          const annotateHeadings = () => {
            if (!headingTargets.length) return;
            for (const element of doc.querySelectorAll('h1, h2, h3, h4')) {
              const elementLabel = cleanLabel(element);
              for (const target of headingTargets) {
                if (elementLabel === normalize(target?.label)) applyHeadingHelp(element, target);
              }
            }
          };

          const annotateScope = (scope, scopeTargets) => {
            if (!scope) return;
            if (activeAnchor && (!activeAnchor.isConnected || !visible(activeAnchor))) hideTooltip();
            for (const target of scopeTargets) {
              const kind = String(target?.kind || '');
              const label = normalize(target?.label);
              const help = String(target?.help || '');
              if (!label || !help) continue;
              if (kind === 'tab') {
                for (const element of scope.querySelectorAll('[role="tab"]')) {
                  if (cleanLabel(element) === label) applyTabHelp(element, target);
                }
              } else if (kind === 'choice') {
                applyChoiceHelp(scope, target);
              }
            }
          };

          const observers = [];
          const attachScope = (scopeKey, scopeTargets) => {
            const className = `st-key-${scopeKey}`;
            const scope = doc.getElementsByClassName(className)[0] || null;
            if (!scope) return false;
            annotateScope(scope, scopeTargets);
            const watchesTabs = scopeTargets.some((target) => String(target?.kind || '') === 'tab');
            const observedRoot = watchesTabs
              ? (scope.querySelector('[role="tablist"]') || scope)
              : scope;
            const observer = new MutationObserver(() => annotateScope(scope, scopeTargets));
            observer.observe(observedRoot, {childList: true, subtree: true});
            observers.push(observer);
            return true;
          };

          annotateHeadings();
          win.requestAnimationFrame(annotateHeadings);
          for (const [scopeKey, scopeTargets] of scopedTargets.entries()) {
            if (attachScope(scopeKey, scopeTargets)) continue;
            let attempts = 0;
            const retry = () => {
              attempts += 1;
              if (attachScope(scopeKey, scopeTargets) || attempts >= 8) return;
              win.requestAnimationFrame(retry);
            };
            win.requestAnimationFrame(retry);
          }
          return () => {
            observers.forEach((observer) => observer.disconnect());
            hideTooltip();
          };
        }
        """,
    )


def _mount_context_help(st, *, targets: list[dict[str, str]], key: str) -> None:
    """Agrega iconos de información sin comunicar estado a Python ni provocar reruns."""

    if getattr(st, "__name__", None) != "streamlit":
        return
    renderer = _context_help_renderer()
    if renderer is None:
        return
    renderer(data={"targets": targets}, key=key)


def section_heading(st, label: str, *, level: str = "header") -> None:
    """Renderiza un título de sección con un icono de información contextual."""

    from archive_workbench.ui_help import SECTION_HELP

    render = getattr(st, level)
    render(label)
    help_text = SECTION_HELP.get(label)
    if help_text:
        normalized = "".join(character if character.isalnum() else "_" for character in label)
        _mount_context_help(
            st,
            targets=[{"kind": "heading", "label": label, "help": help_text}],
            key=f"archive_workbench_heading_help_{normalized}",
        )


def mount_heading_help(st, *, label: str, help_text: str) -> None:
    """Agrega un icono de información a un título renderizado por otra función."""

    normalized = "".join(character if character.isalnum() else "_" for character in label)
    _mount_context_help(
        st,
        targets=[{"kind": "heading", "label": label, "help": help_text}],
        key=f"archive_workbench_heading_help_{normalized}",
    )


def mount_choice_help(st, *, key: str, label: str, help_text: str) -> None:
    """Muestra un icono de información junto al selector de la tarea activa."""

    normalized = "".join(character if character.isalnum() else "_" for character in key)
    _mount_context_help(
        st,
        targets=[
            {
                "kind": "choice",
                "scope_key": key,
                "label": label,
                "help": help_text,
            }
        ],
        key=f"archive_workbench_choice_help_{normalized}",
    )


def request_tab(st, *, key: str, label: str) -> None:
    """Solicita abrir una pestaña en el siguiente rerun.

    La clave pendiente evita modificar el estado de un widget después de haberlo
    instanciado en el mismo ciclo de Streamlit.
    """

    st.session_state[f"{key}__pending"] = label


@lru_cache(maxsize=1)
def _tab_state_keeper_renderer():
    """Conserva la pestaña visual activa sólo en el navegador."""

    import streamlit as st

    if not hasattr(st.components, "v2"):
        return None
    return st.components.v2.component(
        name="archive_workbench_tab_state_keeper",
        js=r"""
        export default function(component) {
          const { data } = component;
          const scopeKey = String(data?.scope_key || '');
          const labels = new Set(
            (Array.isArray(data?.labels) ? data.labels : []).map((value) => String(value))
          );
          const preferred = String(data?.preferred || '');
          const forcePreferred = Boolean(data?.force_preferred);
          if (!scopeKey || labels.size === 0) return;

          const doc = document;
          const win = window;
          const storageKey = `archive-workbench-tab:${scopeKey}`;
          const normalize = (value) => String(value || '').replace(/\s+/g, ' ').trim();
          const cleanLabel = (element) => {
            if (!element) return '';
            const clone = element.cloneNode(true);
            clone.querySelectorAll('[data-aw-info-icon], [data-aw-help-description]').forEach(
              (node) => node.remove()
            );
            return normalize(clone.textContent);
          };
          const className = `st-key-${scopeKey}`;
          const findScope = () => doc.getElementsByClassName(className)[0] || null;

          const bound = new Map();
          const remember = (tab) => {
            const label = cleanLabel(tab);
            if (labels.has(label)) win.sessionStorage.setItem(storageKey, label);
          };
          const bind = (tab) => {
            if (bound.has(tab)) return;
            const pointerHandler = () => remember(tab);
            const keyboardHandler = (event) => {
              if (event.key === 'Enter' || event.key === ' ') remember(tab);
            };
            // Recordar antes de que el tab nativo procese el gesto evita que una
            // restauración visual compita con el primer clic. No se cancela ni se
            // sustituye el comportamiento nativo del tab.
            tab.addEventListener('pointerdown', pointerHandler, true);
            tab.addEventListener('keydown', keyboardHandler, true);
            bound.set(tab, {pointerHandler, keyboardHandler});
          };

          let forced = false;
          const restore = (scope) => {
            if (!scope) return false;
            const tabs = Array.from(scope.querySelectorAll('[role="tab"]'));
            if (!tabs.length) return false;
            tabs.forEach(bind);

            const stored = win.sessionStorage.getItem(storageKey);
            const target = (!forced && forcePreferred && labels.has(preferred))
              ? preferred
              : (labels.has(stored) ? stored : preferred);
            if (!labels.has(target)) return true;
            const tab = tabs.find((candidate) => cleanLabel(candidate) === target);
            if (!tab) return true;
            if (tab.getAttribute('aria-selected') !== 'true') tab.click();
            win.sessionStorage.setItem(storageKey, target);
            if (forcePreferred) forced = true;
            return true;
          };

          const attach = () => {
            const scope = findScope();
            return Boolean(scope && restore(scope));
          };

          if (!attach()) {
            let attempts = 0;
            const retry = () => {
              attempts += 1;
              if (attach() || attempts >= 8) return;
              win.requestAnimationFrame(retry);
            };
            win.requestAnimationFrame(retry);
          }
          return () => {
            for (const [tab, handlers] of bound.entries()) {
              try { tab.removeEventListener('pointerdown', handlers.pointerHandler, true); } catch (error) {}
              try { tab.removeEventListener('keydown', handlers.keyboardHandler, true); } catch (error) {}
            }
          };
        }
        """,
    )


def _mount_tab_state_keeper(
    st,
    *,
    key: str,
    labels: Sequence[str],
    preferred: str,
    force_preferred: bool,
) -> None:
    """Monta persistencia visual de pestañas sin comunicar estado a Python."""

    if getattr(st, "__name__", None) != "streamlit":
        return
    renderer = _tab_state_keeper_renderer()
    if renderer is None:
        return
    renderer(
        data={
            "scope_key": key,
            "labels": list(labels),
            "preferred": preferred,
            "force_preferred": force_preferred,
        },
        key=f"archive_workbench_tab_state_keeper_{key}",
    )


def tracked_tabs(
    st,
    labels: Sequence[str],
    *,
    key: str,
    default: str | None = None,
    rerun_on_change: bool = False,
    help_by_label: dict[str, str] | None = None,
):
    """Crea pestañas persistentes sin rerun global para navegación visual.

    El modo pasivo es el contrato normal del proyecto: cambiar de pestaña no
    cambia el objeto de trabajo y por lo tanto no debe reconstruir la vista.
    ``request_tab()`` permite encolar una apertura programática antes del
    siguiente render cuando una acción real necesita llevar a otra pestaña.
    """

    options = list(labels)
    if not options:
        raise ValueError("tracked_tabs requiere al menos una pestaña")

    if not rerun_on_change:
        pending_key = f"{key}__pending"
        remembered_key = f"{key}__remembered"
        pending = st.session_state.pop(pending_key, None)
        widget_value = st.session_state.get(key)
        if widget_value in options:
            # Compatibilidad con un valor ya existente, incluida navegación
            # programática previa. En modo ignore los clicks visuales no
            # actualizan esta clave y se conservan por separado en el navegador.
            st.session_state[remembered_key] = widget_value
        remembered = st.session_state.get(remembered_key)
        if pending in options:
            passive_default = pending
        elif widget_value in options:
            passive_default = widget_value
        elif remembered in options:
            passive_default = remembered
        else:
            passive_default = default if default in options else options[0]
        st.session_state[remembered_key] = passive_default
        if pending in options:
            # Navegación programática explícita: se aplica antes de instanciar
            # el widget. Los clicks visuales siguen sin viajar a Python.
            st.session_state[key] = pending
        tabs = st.tabs(
            options,
            default=passive_default,
            key=key,
            on_change="ignore",
        )
        _mount_tab_state_keeper(
            st,
            key=key,
            labels=options,
            preferred=passive_default,
            force_preferred=pending in options,
        )
        if help_by_label:
            _mount_context_help(
                st,
                targets=[
                    {
                        "kind": "tab",
                        "scope_key": key,
                        "label": label,
                        "help": help_by_label[label],
                    }
                    for label in options
                    if label in help_by_label
                ],
                key=f"archive_workbench_tab_help_{key}",
            )
        return tabs

    pending_key = f"{key}__pending"
    remembered_key = f"{key}__remembered"
    pending = st.session_state.pop(pending_key, None)
    widget_value = st.session_state.get(key)

    # El valor nativo de ``st.tabs`` puede desaparecer si una acción ubicada antes
    # del widget interrumpe el render y solicita un rerun. Se conserva una copia
    # no asociada al widget para restaurar la pestaña activa en ese caso.
    if widget_value in options:
        st.session_state[remembered_key] = widget_value

    remembered = st.session_state.get(remembered_key)
    if pending in options:
        # La solicitud programática debe sobrevivir también al rerun siguiente.
        current = pending
    elif widget_value in options:
        current = widget_value
    elif remembered in options:
        current = remembered
    else:
        current = default if default in options else options[0]

    if current not in options:
        current = options[0]
    st.session_state[remembered_key] = current
    st.session_state[key] = current
    default = current

    tabs = st.tabs(
        options,
        default=default,
        key=key,
        on_change="rerun",
    )
    if help_by_label:
        _mount_context_help(
            st,
            targets=[
                {
                    "kind": "tab",
                    "scope_key": key,
                    "label": label,
                    "help": help_by_label[label],
                }
                for label in options
                if label in help_by_label
            ],
            key=f"archive_workbench_tab_help_{key}",
        )
    return tabs



@lru_cache(maxsize=1)
def _view_scroll_keeper_renderer():
    """Registra un componente v2 sin iframe para conservar la posición vertical."""

    import streamlit as st

    if not hasattr(st.components, "v2"):
        return None
    return st.components.v2.component(
        name="archive_workbench_view_scroll_keeper",
        js=r"""
        export default function(component) {
          const { data } = component;
          const viewKey = String(data?.view_key || 'default');
          const storageKey = `archive-workbench-scroll:${viewKey}`;
          const doc = document;
          const win = window;
          const findScroller = () =>
            doc.querySelector('section[data-testid="stMain"]') ||
            doc.scrollingElement ||
            doc.documentElement;
          const scroller = findScroller();
          if (!scroller) return;

          const raw = win.sessionStorage.getItem(storageKey);
          const parsed = raw === null ? null : Number(raw);
          const target = Number.isFinite(parsed) ? Math.max(0, parsed) : 0;
          let restoring = raw !== null;
          let lastSaved = target;

          const save = () => {
            if (restoring) return;
            const value = Math.max(0, Number(scroller.scrollTop || 0));
            lastSaved = value;
            win.sessionStorage.setItem(storageKey, String(value));
          };
          const saveSoon = () => win.requestAnimationFrame(() => win.requestAnimationFrame(save));

          const restore = () => {
            if (!restoring) return;
            const maxTop = Math.max(0, scroller.scrollHeight - scroller.clientHeight);
            const reachable = Math.min(target, maxTop);
            if (Math.abs(scroller.scrollTop - reachable) > 1) scroller.scrollTop = reachable;
            if (maxTop >= target - 1) scroller.scrollTop = target;
          };

          const listeners = [];
          const listen = (node, name, handler, options) => {
            node.addEventListener(name, handler, options);
            listeners.push([node, name, handler, options]);
          };

          // Captura la posición antes de toda interacción que pueda provocar un rerun.
          listen(doc, 'pointerdown', save, true);
          listen(doc, 'change', save, true);
          listen(doc, 'submit', save, true);
          listen(doc, 'wheel', saveSoon, {passive: true, capture: true});
          listen(doc, 'touchend', saveSoon, {passive: true, capture: true});
          listen(doc, 'pointerup', saveSoon, true);
          listen(doc, 'keyup', (event) => {
            if (['ArrowUp','ArrowDown','PageUp','PageDown','Home','End',' '].includes(event.key)) {
              saveSoon();
            }
          }, true);

          restore();
          win.requestAnimationFrame(() => {
            restore();
            win.requestAnimationFrame(restore);
          });
          const timers = [50, 110, 190, 310, 470, 680, 950, 1300].map(
            (delay) => win.setTimeout(restore, delay)
          );

          let resizeObserver = null;
          if ('ResizeObserver' in win) {
            resizeObserver = new win.ResizeObserver(restore);
            resizeObserver.observe(scroller);
            const block = doc.querySelector('[data-testid="stMainBlockContainer"]');
            if (block) resizeObserver.observe(block);
          }

          const finishTimer = win.setTimeout(() => {
            restore();
            restoring = false;
            // No escribir cero si Streamlit reseteó el contenedor durante la reconstrucción.
            const now = Math.max(0, Number(scroller.scrollTop || 0));
            const finalValue = target > 0 && now === 0 ? target : now;
            lastSaved = finalValue;
            win.sessionStorage.setItem(storageKey, String(finalValue));
            if (resizeObserver) resizeObserver.disconnect();
          }, 1400);

          return () => {
            // El cleanup puede ocurrir durante un rerun, cuando stMain ya fue puesto a cero.
            // Conservamos el último valor válido en lugar de ese cero transitorio.
            const now = Math.max(0, Number(scroller.scrollTop || 0));
            const value = now === 0 && lastSaved > 0 ? lastSaved : now;
            win.sessionStorage.setItem(storageKey, String(value));
            listeners.forEach(([node, name, handler, options]) => {
              try { node.removeEventListener(name, handler, options); } catch (error) {}
            });
            timers.forEach((timer) => win.clearTimeout(timer));
            win.clearTimeout(finishTimer);
            if (resizeObserver) resizeObserver.disconnect();
          };
        }
        """,
    )


def mount_view_scroll_keeper(st, *, view_key: str) -> None:
    """Monta la conservación de desplazamiento sin introducir un iframe auxiliar.

    Streamlit puede reconstruir ``stMain`` durante reruns. El componente v2 vive en
    el DOM principal, guarda la posición antes de la interacción y la restaura al
    reconstruirse la misma vista. No emite estado ni triggers hacia Python.
    """

    if getattr(st, "__name__", None) != "streamlit":
        return
    renderer = _view_scroll_keeper_renderer()
    if renderer is None:
        return
    normalized = "".join(character if character.isalnum() else "_" for character in view_key)
    # No fijar width/height a cero: los componentes v2 validan el ancho como
    # positivo o como ``stretch``/``content``. Al omitir ambos parámetros,
    # Streamlit usa sus valores nativos (width="stretch", height="content");
    # como este componente no renderiza contenido visible, no agrega una
    # superficie perceptible a la vista.
    renderer(
        data={"view_key": normalized or "default"},
        key=f"archive_workbench_scroll_keeper_{normalized or 'default'}",
    )

def isolated_view(st, *, mode: str):
    """Devuelve un contenedor identificado para integraciones externas.

    La aplicación principal no usa fragmentos como mecanismo de continuidad.
    Este contenedor sólo aporta identidad estable a integraciones externas.
    """

    normalized = "".join(character if character.isalnum() else "_" for character in mode)
    return st.container(key=f"archive_workbench_view_{normalized}")


def rerun_view(st) -> None:
    """Actualiza la aplicación después de una mutación de la vista activa.

    Las vistas principales ya no se envuelven en un fragmento único. Esto evita
    conservar árboles visuales obsoletos al cambiar de sección. La posición y el
    contexto se preservan por separado mediante estado estable y componentes v2.
    """

    try:
        st.rerun(scope="app")
    except TypeError:
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
