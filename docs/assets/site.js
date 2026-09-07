(() => {
  const button = document.querySelector('[data-menu-toggle]');
  const nav = document.querySelector('[data-site-nav]');
  if (!button || !nav) return;

  const setOpen = (open) => {
    nav.dataset.open = open ? 'true' : 'false';
    button.setAttribute('aria-expanded', open ? 'true' : 'false');
    button.textContent = open ? 'Cerrar menú' : 'Menú';
  };

  button.addEventListener('click', () => {
    setOpen(nav.dataset.open !== 'true');
  });

  const wide = window.matchMedia('(min-width: 821px)');
  const sync = () => {
    if (wide.matches) {
      nav.removeAttribute('data-open');
      button.setAttribute('aria-expanded', 'false');
      button.textContent = 'Menú';
    } else if (!nav.dataset.open) {
      setOpen(false);
    }
  };
  wide.addEventListener?.('change', sync);
  sync();
})();
