(() => {
  const root = document.documentElement;
  // Sidebar utilities
  const sidebarTop = document.querySelector('.sidebar-top');
  const existingMenu = document.querySelector('[data-menu-toggle]');
  const nav = document.querySelector('[data-site-nav]');
  if (sidebarTop && existingMenu && nav) {
    const tools = document.createElement('div');
    tools.className = 'sidebar-tools';

    const theme = document.createElement('button');
    theme.className = 'theme-toggle';
    theme.type = 'button';
    theme.setAttribute('aria-label', 'Cambiar apariencia');
    theme.textContent = 'Apariencia';

    existingMenu.parentNode?.removeChild(existingMenu);
    tools.append(theme, existingMenu);
    sidebarTop.appendChild(tools);

    const setOpen = (open) => {
      nav.dataset.open = open ? 'true' : 'false';
      existingMenu.setAttribute('aria-expanded', open ? 'true' : 'false');
      existingMenu.textContent = open ? 'Cerrar' : 'Menú';
    };
    existingMenu.addEventListener('click', () => setOpen(nav.dataset.open !== 'true'));
    const wide = window.matchMedia('(min-width: 761px)');
    const syncMenu = () => {
      if (wide.matches) {
        nav.removeAttribute('data-open');
        existingMenu.setAttribute('aria-expanded', 'false');
        existingMenu.textContent = 'Menú';
      } else if (!nav.dataset.open) {
        setOpen(false);
      }
    };
    wide.addEventListener?.('change', syncMenu);
    syncMenu();

    const stored = localStorage.getItem('archive-workbench-site-theme');
    const initial = stored || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    root.dataset.theme = initial;
    const label = () => {
      theme.textContent = root.dataset.theme === 'dark' ? 'Modo claro' : 'Modo oscuro';
    };
    label();
    theme.addEventListener('click', () => {
      root.dataset.theme = root.dataset.theme === 'dark' ? 'light' : 'dark';
      localStorage.setItem('archive-workbench-site-theme', root.dataset.theme);
      label();
    });
  }

  // Reading progress
  const progress = document.createElement('div');
  progress.className = 'reading-progress';
  progress.setAttribute('aria-hidden', 'true');
  document.body.appendChild(progress);
  const updateProgress = () => {
    const max = document.documentElement.scrollHeight - window.innerHeight;
    const pct = max > 0 ? Math.min(100, Math.max(0, (window.scrollY / max) * 100)) : 0;
    progress.style.width = `${pct}%`;
  };
  addEventListener('scroll', updateProgress, { passive: true });
  addEventListener('resize', updateProgress);
  updateProgress();

  // Stage grid and sticky page index on wide screens
  const stage = document.querySelector('.site-stage');
  const main = document.querySelector('.doc-main');
  const footer = document.querySelector('.site-foot');
  const index = main?.querySelector('.page-index');
  if (stage && main) {
    const grid = document.createElement('div');
    grid.className = 'stage-grid';
    stage.insertBefore(grid, main);
    grid.appendChild(main);
    if (index) {
      const rail = document.createElement('aside');
      rail.className = 'page-rail';
      rail.setAttribute('aria-label', 'Contenido de esta página');
      rail.appendChild(index.cloneNode(true));
      grid.appendChild(rail);
      grid.classList.add('has-rail');
      index.style.display = 'none';

      const anchors = [...rail.querySelectorAll('a[href^="#"]')];
      const targets = anchors
        .map(a => [a, document.querySelector(a.getAttribute('href'))])
        .filter(([, target]) => target);
      if (targets.length) {
        const observer = new IntersectionObserver(entries => {
          const visible = entries
            .filter(e => e.isIntersecting)
            .sort((a,b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
          if (!visible) return;
          anchors.forEach(a => a.classList.toggle('is-current', a.getAttribute('href') === `#${visible.target.id}`));
        }, { rootMargin: '-18% 0px -70% 0px', threshold: 0 });
        targets.forEach(([, target]) => observer.observe(target));
      }
    }
    if (footer) stage.appendChild(footer);
  }

  // Figure lightbox; the caption link still opens the original file directly.
  const figures = [...document.querySelectorAll('.figure-link')];
  if (figures.length) {
    const box = document.createElement('div');
    box.className = 'lightbox';
    box.innerHTML = `
      <div class="lightbox__bar"><span>Vista ampliada</span><button class="lightbox__close" type="button">Cerrar</button></div>
      <div class="lightbox__stage"><img alt=""></div>
      <div class="lightbox__foot"><a target="_blank" rel="noopener">Abrir archivo original</a></div>`;
    document.body.appendChild(box);
    const img = box.querySelector('img');
    const original = box.querySelector('a');
    const close = box.querySelector('button');
    let lastFocus = null;

    const closeBox = () => {
      box.dataset.open = 'false';
      document.body.style.overflow = '';
      lastFocus?.focus?.();
    };
    close.addEventListener('click', closeBox);
    box.addEventListener('click', e => { if (e.target === box || e.target.classList.contains('lightbox__stage')) closeBox(); });
    addEventListener('keydown', e => { if (e.key === 'Escape' && box.dataset.open === 'true') closeBox(); });

    figures.forEach(link => {
      link.addEventListener('click', e => {
        const shot = link.querySelector('img');
        if (!shot) return;
        e.preventDefault();
        lastFocus = link;
        img.src = shot.currentSrc || shot.src;
        img.alt = shot.alt || 'Captura ampliada';
        original.href = link.href;
        box.dataset.open = 'true';
        document.body.style.overflow = 'hidden';
        close.focus();
      });
    });
  }
})();
