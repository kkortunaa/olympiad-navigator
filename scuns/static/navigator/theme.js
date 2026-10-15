(() => {
  'use strict';
  const button = document.querySelector('[data-theme-toggle]');
  const sheet = document.getElementById('dark-theme');
  function apply(theme) {
    const light = theme === 'light';
    document.documentElement.dataset.theme = light ? 'light' : 'dark';
    if (sheet) sheet.disabled = light;
    if (button) {
      button.setAttribute('aria-pressed', String(light));
      button.setAttribute('aria-label', light ? 'Включить тёмную тему' : 'Включить светлую тему');
      button.querySelector('[data-theme-icon]').textContent = light ? '☾' : '☀';
      button.querySelector('[data-theme-label]').textContent = light ? 'Тёмная тема' : 'Светлая тема';
    }
  }
  apply(document.documentElement.dataset.theme || 'dark');
  button?.addEventListener('click', () => {
    const theme = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light';
    apply(theme);
    try { localStorage.setItem('navigator-theme', theme); } catch (_) { /* The switch works without local storage. */ }
  });
  window.addEventListener('storage', event => { if (event.key === 'navigator-theme') apply(event.newValue); });
})();
