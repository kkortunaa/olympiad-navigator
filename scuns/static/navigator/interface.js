(() => {
  'use strict';
  const $ = selector => document.querySelector(selector);
  const $$ = selector => [...document.querySelectorAll(selector)];
  const bridge = window.plannerBridge;
  if (!bridge) return;

  // Searchable pickers use the same change events as the catalog filters.
  const pickers = $$('[data-picker]').map(root => {
    const value = root.querySelector('input[type=hidden]'), trigger = root.querySelector('.picker-trigger');
    const popup = root.querySelector('.picker-popup'), search = root.querySelector('[data-picker-search]');
    const options = [...root.querySelectorAll('[role=option]')];
    const visible = () => options.filter(option => !option.hidden);
    const sync = () => {
      const selected = options.find(option => option.dataset.value === value.value);
      root.querySelector('[data-picker-label]').textContent = selected?.textContent || 'Все';
      options.forEach(option => option.setAttribute('aria-selected',String(option === selected)));
      if (value.id === 'profile-filter' && $('[data-profile-caption]')) $('[data-profile-caption]').textContent = value.value === 'all' ? '' : `· ${selected?.textContent || value.value}`;
    };
    const close = (focus = false) => { popup.hidden = true; trigger.setAttribute('aria-expanded','false'); if (focus) trigger.focus(); };
    const filter = () => {
      const query = (search?.value || '').toLocaleLowerCase('ru').replaceAll('ё','е');
      options.forEach(option => { option.hidden = !option.textContent.toLocaleLowerCase('ru').replaceAll('ё','е').includes(query); });
      root.querySelector('.picker-empty').hidden = visible().length !== 0;
    };
    const open = () => {
      pickers.forEach(picker => picker.close());
      if (search) search.value = '';
      filter(); popup.hidden = false; trigger.setAttribute('aria-expanded','true');
      if (search) search.focus(); else (options.find(option => option.dataset.value === value.value) || options[0])?.focus();
    };
    trigger.addEventListener('click', () => popup.hidden ? open() : close());
    search?.addEventListener('input', filter);
    options.forEach(option => option.addEventListener('click', () => {
      value.value = option.dataset.value; sync(); close(true); value.dispatchEvent(new Event('change',{bubbles:true}));
    }));
    root.addEventListener('keydown', event => {
      if (event.key === 'Escape' && !popup.hidden) { event.preventDefault(); event.stopPropagation(); close(true); }
      else if (event.key === 'Tab') close();
      else if (['ArrowDown','ArrowUp'].includes(event.key)) {
        event.preventDefault();
        if (popup.hidden) { open(); return; }
        const choices = visible(), index = choices.indexOf(document.activeElement);
        choices[(index+(event.key==='ArrowDown'?1:-1)+choices.length)%choices.length]?.focus();
      } else if (event.key === 'Home' && document.activeElement?.getAttribute('role') === 'option') { event.preventDefault(); visible()[0]?.focus(); }
      else if (event.key === 'End' && document.activeElement?.getAttribute('role') === 'option') { event.preventDefault(); visible().at(-1)?.focus(); }
      else if (event.key === 'Enter' && document.activeElement === search) { event.preventDefault(); visible()[0]?.click(); }
    });
    document.addEventListener('click', event => { if (!root.contains(event.target)) close(); });
    document.addEventListener('catalog:render',sync); sync();
    return {close};
  });
  const syncRegistration = () => $$('[data-registration]').forEach(button => button.setAttribute('aria-pressed',String(button.dataset.registration === $('#registration-status')?.value)));
  $$('[data-registration]').forEach(button => button.addEventListener('click', () => {
    const input = $('#registration-status'); input.value = button.dataset.registration; input.dispatchEvent(new Event('change')); syncRegistration();
  }));
  document.addEventListener('catalog:render',syncRegistration);

  const catalogTabs = $$('[data-catalog-tab]');
  function switchCatalog() {
    const participation = ['#my-olympiads','#participation','#conflicts'].includes(location.hash);
    $$('[data-catalog-view]').forEach(view => { view.hidden = (view.dataset.catalogView === 'participation') !== participation; });
    catalogTabs.forEach(tab => {
      const active = (tab.dataset.catalogTab === 'participation') === participation;
      if (active) tab.setAttribute('aria-current','page'); else tab.removeAttribute('aria-current');
    });
    if (participation && location.hash === '#conflicts') $('#conflicts')?.scrollIntoView({block:'start'});
  }
  window.addEventListener('hashchange',switchCatalog); switchCatalog();
  const participationCount = () => $$('[data-participation-count]').forEach(node => { node.textContent = new Set([...bridge.getState().favorites, ...bridge.getState().planned, ...(bridge.getState().registered || [])]).size; });
  document.addEventListener('planner:render',participationCount); participationCount();

  const grid = $('[data-activity-grid]');
  if (!grid) return;
  const data = window.PreparationActivity;
  let year = Number(data.moscowDay().slice(0,4)), selected = data.moscowDay(), scrolledYear = null;
  const pretty = day => data.date(day).toLocaleDateString('ru-RU',{timeZone:'UTC',day:'numeric',month:'long',year:'numeric'});
  const describe = (day,count) => `${pretty(day)} · выполнено задач: ${count}`;
  function renderActivity() {
    const today=data.moscowDay(), state=bridge.getState(), activity=data.yearData(state.activity,year,today);
    const focusDay = grid.contains(document.activeElement) ? document.activeElement.dataset.day : null;
    if (!selected.startsWith(String(year))) selected = year === Number(today.slice(0,4)) ? today : `${year}-12-31`;
    $('[data-activity-year]').textContent = year;
    $('[data-activity-total]').textContent = activity.total;
    $('[data-activity-days]').textContent = activity.days;
    $('[data-activity-streak]').textContent = activity.best;
    $('[data-activity-next]').disabled = year >= Number(today.slice(0,4));
    $('[data-activity-prev]').disabled = year <= 2000;
    grid.style.setProperty('--activity-weeks',activity.weeks);
    grid.replaceChildren();
    const months=$('[data-activity-months]'); months.style.setProperty('--activity-weeks',activity.weeks); months.replaceChildren();
    activity.cells.forEach((cell,index) => {
      if (!cell) { const blank=document.createElement('span'); blank.className='activity-blank'; grid.append(blank); return; }
      const button=document.createElement('button'); button.type='button'; button.className='activity-cell'; button.dataset.day=cell.day; button.dataset.level=data.level(cell.count); button.disabled=cell.future;
      button.title=describe(cell.day,cell.count); button.setAttribute('aria-label',button.title); button.setAttribute('aria-pressed',String(cell.day===selected)); button.tabIndex=cell.day===selected ? 0 : -1;
      if (cell.day===today) button.setAttribute('aria-current','date');
      button.addEventListener('click', () => { selected=cell.day; renderActivity(); grid.querySelector(`[data-day="${selected}"]`)?.focus({preventScroll:true}); });
      grid.append(button);
      if (cell.first) { const month=document.createElement('span'); month.textContent=data.date(cell.day).toLocaleDateString('ru-RU',{timeZone:'UTC',month:'short'}).replace('.',''); month.style.gridColumn=String(Math.floor(index/7)+1); months.append(month); }
    });
    $('[data-activity-detail]').textContent = describe(selected,data.counts(state.activity)[selected] || 0);
    const legacy=state.tasks.filter(task=>task.done && !task.completed_on && !state.activity[task.id]).length;
    const note=$('[data-activity-legacy]'); note.hidden=!legacy; note.textContent=`Старых выполненных задач без даты: ${legacy}. Они сохранены, но не включены в календарь активности.`;
    if (scrolledYear !== year) {
      const scroller=$('.activity-scroll'), target=grid.querySelector(`[data-day="${selected}"]`);
      if (target) { scroller.scrollLeft += target.getBoundingClientRect().left - scroller.getBoundingClientRect().left - scroller.clientWidth/2; }
      scrolledYear=year;
    }
    if (focusDay) grid.querySelector(`[data-day="${focusDay}"]`)?.focus({preventScroll:true});
  }
  grid.addEventListener('keydown',event=>{
    const offset={ArrowLeft:-7,ArrowRight:7,ArrowUp:-1,ArrowDown:1}[event.key];
    if (!offset || !event.target.dataset.day) return;
    event.preventDefault(); const next=data.date(event.target.dataset.day); next.setUTCDate(next.getUTCDate()+offset);
    const key=next.toISOString().slice(0,10), target=grid.querySelector(`[data-day="${key}"]`);
    if (target && !target.disabled) { selected=key; renderActivity(); grid.querySelector(`[data-day="${key}"]`)?.focus(); }
  });
  $('[data-activity-prev]').addEventListener('click',()=>{year--;renderActivity();});
  $('[data-activity-next]').addEventListener('click',()=>{year++;renderActivity();});
  document.addEventListener('planner:render',renderActivity); renderActivity();
})();
