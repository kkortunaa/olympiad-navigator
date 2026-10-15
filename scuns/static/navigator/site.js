(() => {
  'use strict';
  const $ = selector => document.querySelector(selector);
  const $$ = selector => [...document.querySelectorAll(selector)];
  const bootstrap = JSON.parse($('#personal-bootstrap')?.textContent || '{}');
  const STORAGE_KEY = 'olympiad-navigator:v1';
  const names = JSON.parse($('#catalog-names')?.textContent || '{}');
  const aliases = JSON.parse($('#catalog-aliases')?.textContent || '{}');
  const catalog = JSON.parse($('#catalog-metadata')?.textContent || '{}');
  const dateKey = date => `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`;
  const parseDate = key => {
    if (typeof key !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(key)) return null;
    const date = new Date(`${key}T12:00:00`);
    return !Number.isNaN(date.getTime()) && dateKey(date) === key ? date : null;
  };
  let today = window.PreparationActivity.moscowDay();
  let catalogToday = $('#olympiads')?.dataset.today || today;
  const uid = () => globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  const initialState = () => ({tasks: [
    {id: uid(), title: 'Решить 5 задач по комбинаторике', date: today, done: false},
    {id: uid(), title: 'Повторить перестановки и сочетания', date: today, done: false},
  ], planned: [], favorites: []});
  function readSaved(serialized) {
      const saved = JSON.parse(serialized);
      if (!saved || !Array.isArray(saved.tasks)) throw new Error('Invalid state');
      const seen = new Set();
      const tasks = saved.tasks.filter(task => {
        if (!task || typeof task.id !== 'string' || seen.has(task.id) || typeof task.title !== 'string' || !task.title.trim() || !parseDate(task.date)) return false;
        seen.add(task.id); return true;
      }).map(task => ({id: task.id, title: task.title.slice(0,180), date: task.date, done: task.done === true, ...(Object.hasOwn(names, aliases[task.source] || task.source) ? {source: aliases[task.source] || task.source} : {})}));
      const activity = Object.fromEntries(Object.entries(saved.activity || {}).filter(([id, day]) => id.length > 0 && id.length <= 100 && parseDate(day) && day <= today));
      tasks.forEach(task => {
        const original = saved.tasks.find(candidate => candidate.id === task.id);
        const day = original.completed_on || activity[task.id];
        if (task.done && parseDate(day) && day <= today) { task.completed_on = day; activity[task.id] = day; }
        if (!task.done) delete activity[task.id];
      });
      const participation = Object.fromEntries(Object.entries(saved.participation || {}).filter(([key, value]) => /^\d+$/.test(key) && Object.hasOwn(bootstrap.statuses || {}, value)));
      const preferences = {notifications: saved.preferences?.notifications !== false, lead_days: [1,3,7,14].includes(saved.preferences?.lead_days) ? saved.preferences.lead_days : 3};
      return {tasks, activity, registered: [...new Set((bootstrap.registered_profiles || []).map(p=>p.key))], planned: Object.keys(names).filter(id => tasks.some(task => task.source === id)), favorites: Array.isArray(saved.favorites) ? saved.favorites.map(id => aliases[id] || id).filter(id => Object.hasOwn(names,id)) : [], participation, preferences, dismissed: Array.isArray(saved.dismissed) ? saved.dismissed.filter(key => typeof key === 'string').slice(-2000) : []};
  }
  let storageUnavailable = false;
  let state;
  try {
    const stored = bootstrap.authenticated ? JSON.stringify(bootstrap.state) : localStorage.getItem(STORAGE_KEY);
    if (stored === null) state = readSaved(JSON.stringify(initialState()));
    else {
      state = readSaved(stored);
    }
  } catch (_) { state = readSaved(JSON.stringify(initialState())); storageUnavailable = true; }
  let selected = today;
  let taskFilter = 'all';
  let allTaskDates = new URLSearchParams(location.search).get('tasks') === 'all';
  let subject = 'all';
  let profileFilter = 'all';
  let registrationFilter = 'all';
  let onlyFavorites = false;
  let sortOrder = 'registration-asc';
  const pageSize = Number($('#olympiads')?.dataset.pageSize || 12);
  let visibleCount = pageSize;
  let editingId = null;
  let feedbackTimer;
  function format(key, options) { return parseDate(key).toLocaleDateString('ru-RU', options); }
  function storageNotice() {
    const message = $('[data-storage-message]');
    if (message) {
      message.hidden = !storageUnavailable;
      message.textContent = 'Браузер не разрешил сохранить данные. Сейчас план работает только до закрытия страницы.';
    }
  }
  function persist() {
    if (bootstrap.authenticated) { window.personalPlanner?.save(state); return; }
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); storageUnavailable = false; }
    catch (_) { storageUnavailable = true; }
    storageNotice();
  }
  function announce(message) {
    const feedback = $('[data-feedback]');
    if (!feedback) return;
    clearTimeout(feedbackTimer);
    feedback.textContent = message;
    feedbackTimer = setTimeout(() => { feedback.textContent = ''; }, 5000);
  }
  function syncPlan() {
    state.planned = Object.keys(names).filter(id => state.tasks.some(task => task.source === id));
  }
  function canAddTask() { if (state.tasks.length < 1000) return true; announce('Максимум 1000 задач. Удали ненужные или завершённые.'); return false; }
  function changed() { syncPlan(); persist(); render(); }
  function selectDay(key) {
    selected = key; allTaskDates = false;
    if (!editingId && $('#task-date')) $('#task-date').value = selected;
    renderTasks();
  }
  function resetForm() {
    editingId = null;
    if (!$('#task-form')) return;
    $('#task-title').value = '';
    $('#task-date').value = selected;
    $('#task-submit').textContent = 'Добавить';
    $('#task-cancel').hidden = true;
  }
  function renderTasks() {
    const list = $('#task-list');
    if (!list) return;
    const tasks = state.tasks.filter(task => allTaskDates || task.date === selected).sort((a,b) => a.date.localeCompare(b.date) || a.title.localeCompare(b.title,'ru'));
    const visible = tasks.filter(task => taskFilter === 'all' || (taskFilter === 'done' ? task.done : !task.done));
    const done = tasks.filter(task => task.done).length;
    if ($('#task-day')) $('#task-day').value = selected;
    $('[data-selected-label]').textContent = allTaskDates ? 'Все запланированные дни' : format(selected,{weekday:'long', day:'numeric', month:'long'});
    $('[data-task-all-dates]').setAttribute('aria-pressed',String(allTaskDates));
    $('[data-task-count]').textContent = `${done} / ${tasks.length}`;
    $('[data-task-message]').textContent = tasks.length === 0 ? 'Начни с одного небольшого дела.' : done === tasks.length ? 'Все показанные задачи выполнены!' : `Осталось задач: ${tasks.length - done}`;
    $('#clear-done').disabled = done === 0;
    list.replaceChildren();
    visible.forEach(task => {
      const item = document.createElement('li'); item.className = `task-item${task.done ? ' done' : ''}`;
      const label = document.createElement('label');
      const checkbox = document.createElement('input'); checkbox.type = 'checkbox'; checkbox.checked = task.done;
      const text = document.createElement('span'); text.textContent = task.title;
      if (allTaskDates) { const due=document.createElement('small'); due.className='task-due'; due.textContent=format(task.date,{day:'numeric',month:'long',year:'numeric'}); text.append(due); }
      checkbox.addEventListener('change', () => {
        if (checkbox.checked && !state.activity[task.id] && Object.keys(state.activity).length >= 5000) { checkbox.checked = false; announce('История заполнена: максимум 5000 выполненных задач. Скачай копию данных.'); return; }
        task.done = checkbox.checked;
        if (task.done) { task.completed_on = window.PreparationActivity.moscowDay(); state.activity[task.id] = task.completed_on; }
        else { delete task.completed_on; delete state.activity[task.id]; }
        changed();
        // Keep keyboard focus when re-rendering the list.
        const next = [...list.children].find(row => row.dataset.id === task.id);
        if (next) next.querySelector('input').focus();
      });
      label.append(checkbox,text);
      const actions = document.createElement('div'); actions.className = 'task-actions';
      const edit = document.createElement('button'); edit.type = 'button'; edit.textContent = 'Изменить'; edit.setAttribute('aria-label',`Изменить: ${task.title}`);
      edit.addEventListener('click', () => { editingId = task.id; $('#task-title').value = task.title; $('#task-date').value = task.date; $('#task-submit').textContent = 'Сохранить'; $('#task-cancel').hidden = false; $('#task-title').focus(); });
      const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'delete'; remove.textContent = '×'; remove.setAttribute('aria-label',`Удалить: ${task.title}`);
      remove.addEventListener('click', () => { state.tasks = state.tasks.filter(candidate => candidate.id !== task.id); if (editingId === task.id) resetForm(); changed(); announce('Задача удалена.'); });
      actions.append(edit,remove); item.dataset.id = task.id; item.append(label,actions); list.append(item);
    });
    $('#task-empty').hidden = visible.length !== 0;
    $('#task-empty').textContent = tasks.length === 0 ? (allTaskDates ? 'Задач пока нет. Добавь первую.' : 'На этот день задач пока нет. Добавь первую.') : 'Нет задач с выбранным статусом.';
    $$('[data-task-filter]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.taskFilter === taskFilter)));
  }
  function registrationState(period) {
    if (period.estimated) return 'unknown';
    if (period.ends_on && period.ends_on < catalogToday) return 'closed';
    if (period.starts_on && period.starts_on > catalogToday) return 'upcoming';
    if (period.starts_on && period.ends_on) return 'active';
    return 'unknown';
  }
  function renderRegistration(label, period, count) {
    if (!label) return;
    label.replaceChildren();
    const status = period ? registrationState(period) : 'unknown';
    const badge = document.createElement('span');
    badge.className = `registration-status registration-${status}`;
    badge.textContent = period?.estimated ? 'Дедлайн не подтверждён' : status === 'unknown' && period?.ends_on ? `Регистрация до ${format(period.ends_on, {day:'numeric', month:'long'})}` : {active: 'Идёт регистрация', closed: 'Регистрация завершена', unknown: 'Даты уточняются'}[status]
      || `Откроется ${format(period.starts_on, {day:'numeric', month:'long'})}`;
    label.append(badge);
    if (period) {
      const caption = document.createElement('p'); caption.className = 'registration-profile';
      caption.textContent = [period.profile || 'Все профили', period.name].filter(Boolean).join(' · ');
      label.append(caption);
    }
    const dates = document.createElement('dl'); dates.className = 'registration-dates';
    [['Открытие регистрации', period?.starts_on], [period?.estimated ? 'Предположительно до' : 'Окончание регистрации', period?.ends_on]].forEach(([name, value]) => {
      const term = document.createElement('dt'); term.textContent = name;
      const definition = document.createElement('dd');
      if (value) {
        const time = document.createElement('time'); time.dateTime = value;
        time.textContent = format(value, {day:'2-digit', month:'2-digit', year:'numeric'});
        definition.append(time);
      } else { definition.textContent = 'Не опубликовано'; definition.className = 'muted'; }
      dates.append(term, definition);
    });
    label.append(dates);
    if (period?.estimated) { const note=document.createElement('p'); note.className='registration-estimate-note'; note.textContent='Ориентир — начало отборочного тура. Уточни срок у организатора.'; note.title=period.estimate_explanation; label.append(note); }
    if (period?.source_url) {
      const source = document.createElement('a'); source.href = period.source_url; source.target = '_blank';
      source.rel = 'noopener noreferrer'; source.className = 'text-link'; source.textContent = period.estimated ? 'Дата отборочного тура ↗' : 'Источник дат ↗'; source.href = period.estimate_source_url || period.source_url; label.append(source);
    }
    if (count > 1) {
      const more = document.createElement('p'); more.className = 'muted registration-more';
      more.textContent = `Других периодов и профилей: ${count - 1}. Все — в расписании.`; label.append(more);
    }
  }
  function renderCards() {
    const query = ($('#olympiad-search')?.value || '').trim().toLocaleLowerCase('ru-RU');
    const normalize = value => value.toLocaleLowerCase('ru-RU').replaceAll('ё', 'е');
    const matchesSubject = profile => {
      if (subject === 'all') return true;
      const values = [profile.name, ...profile.subjects].map(normalize);
      const chosen = normalize(subject);
      if (chosen === 'информатика') return values.some(value => value.includes('информат'));
      if (chosen === 'математика') return values.some(value => value.includes('математ'));
      return values.includes(chosen);
    };
    const dateField = sortOrder.startsWith('registration-start-') ? 'starts_on' : 'ends_on';
    const direction = sortOrder.endsWith('-desc') ? -1 : 1;
    const periodGroup = period => !period[dateField] ? 2 : period.ends_on && period.ends_on < catalogToday ? 1 : 0;
    const comparePeriods = (left, right) => periodGroup(left) - periodGroup(right)
      || direction * (left[dateField] || '').localeCompare(right[dateField] || '')
      || (left.profile || '').localeCompare(right.profile || '', 'ru')
      || (left.name || '').localeCompare(right.name || '', 'ru');
    const cards = $$('[data-card]').map(card => {
      const data = catalog[card.dataset.card] || {name: card.querySelector('h3')?.textContent || '', number: 0, profiles: [], registrations: []};
      const profiles = data.profiles.filter(profile => matchesSubject(profile) && (profileFilter === 'all' || profile.name === profileFilter));
      const filtered = subject !== 'all' || profileFilter !== 'all';
      const profileNames = new Set(profiles.map(profile => profile.name));
      const allPeriods = data.registrations.filter(period => !filtered || !period.profile || profileNames.has(period.profile));
      const periods = allPeriods.filter(period => registrationFilter === 'all' || registrationState(period) === registrationFilter).sort(comparePeriods);
      const period = periods.find(candidate => !candidate.ends_on || candidate.ends_on >= catalogToday) || periods[0];
      const searchText = [data.name, ...data.profiles.flatMap(profile => [profile.name, ...profile.subjects])].join(' ');
      const statusMatches = registrationFilter === 'all' || periods.length > 0 || (registrationFilter === 'unknown' && !allPeriods.length);
      const match = (!onlyFavorites || state.favorites.includes(card.dataset.card)) && (!filtered || profiles.length > 0) && statusMatches && normalize(searchText).includes(normalize(query));
      renderRegistration(card.querySelector('[data-registration-label]'), period, periods.length);
      const matching = card.querySelector('[data-matched-profiles]');
      if (matching) { matching.hidden = !filtered; matching.textContent = `Подходит: ${profiles.map(profile => profile.name).join(', ')}`; }
      return {card, data, match, date: period?.[dateField] || '', group: period ? periodGroup(period) : 2};
    });
    cards.sort((left, right) => {
      if (sortOrder === 'catalog') return left.data.number - right.data.number;
      if (sortOrder === 'name') return left.data.name.localeCompare(right.data.name, 'ru');
      return left.group - right.group || direction * left.date.localeCompare(right.date) || left.data.number - right.data.number;
    });
    const grid = $('.olympiad-grid');
    if (grid && cards.some((item, index) => grid.children[index] !== item.card)) {
      const focus = document.activeElement;
      grid.append(...cards.map(item => item.card));
      if (focus && grid.contains(focus)) focus.focus({preventScroll:true});
    }
    let count = 0;
    cards.forEach(({card, match}) => {
      card.hidden = !match || count >= visibleCount; if (match) count++;
    });
    $$('[data-subject]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.subject === subject)));
    if ($('[data-results-count]')) $('[data-results-count]').textContent = `Найдено: ${count}`;
    if ($('#olympiad-empty')) $('#olympiad-empty').hidden = count !== 0;
    if ($('#reset-filters')) $('#reset-filters').hidden = subject === 'all' && profileFilter === 'all' && registrationFilter === 'all' && !query && !onlyFavorites && sortOrder === 'registration-asc';
    if ($('#load-more')) { $('#load-more').hidden = count <= visibleCount; $('#load-more').textContent = `Показать ещё (${Math.max(0, Math.min(pageSize, count-visibleCount))})`; }
    $$('[data-olympiad]').forEach(button => {
      const added = state.planned.includes(button.dataset.olympiad);
      button.setAttribute('aria-pressed',String(added)); button.textContent = added ? '✓ Задача добавлена · убрать' : '+ Задача подготовки';
    });
    $$('[data-save]').forEach(button => {
      const saved = state.favorites.includes(button.dataset.save);
      button.setAttribute('aria-pressed',String(saved)); button.textContent = saved ? '★' : '☆';
    });
    if ($('[data-only-favorites]')) $('[data-only-favorites]').setAttribute('aria-pressed',String(onlyFavorites));
    document.dispatchEvent(new Event('catalog:render'));
  }
  function render() {
    $$('[data-plan-count]').forEach(badge => { badge.textContent = state.tasks.filter(task => !task.done).length; badge.setAttribute('aria-label','Невыполненных задач'); });
    $$('[data-study]').forEach(button => {
      const added = state.tasks.some(task => task.title === button.dataset.study && task.date === today);
      button.textContent = added ? '✓ Добавлено на сегодня' : 'На сегодня'; button.setAttribute('aria-pressed',String(added));
    });
    renderTasks(); renderCards(); storageNotice();
    document.dispatchEvent(new Event('planner:render'));
  }
  $('#task-form')?.addEventListener('submit', event => {
    event.preventDefault();
    const title = $('#task-title').value.trim(); const date = $('#task-date').value;
    if (!title || !parseDate(date)) { $('#task-title').setCustomValidity('Введи название задачи и корректную дату.'); $('#task-title').reportValidity(); return; }
    const task = editingId && state.tasks.find(candidate => candidate.id === editingId);
    if (task) { task.title = title; task.date = date; }
    else { if (!canAddTask()) return; state.tasks.push({id:uid(), title, date, done:false}); }
    selectDay(date); resetForm(); taskFilter = 'all'; changed(); announce(task ? 'Задача сохранена.' : 'Задача добавлена.'); $('#task-title').focus();
  });
  $('#task-title')?.addEventListener('input', () => $('#task-title').setCustomValidity(''));
  $('#task-date')?.addEventListener('input', () => $('#task-title').setCustomValidity(''));
  $('#task-cancel')?.addEventListener('click',resetForm);
  $$('[data-task-filter]').forEach(button => button.addEventListener('click', () => { taskFilter = button.dataset.taskFilter; renderTasks(); }));
  $('[data-task-all-dates]')?.addEventListener('click', () => { allTaskDates = !allTaskDates; renderTasks(); });
  $('#clear-done')?.addEventListener('click', () => {
    state.tasks = state.tasks.filter(task => !((allTaskDates || task.date === selected) && task.done));
    if (editingId && !state.tasks.some(task => task.id === editingId)) resetForm();
    changed(); announce('Показанные выполненные задачи удалены. История активности сохранена.');
  });
  const moveDay = offset => { const date = parseDate(selected); date.setDate(date.getDate()+offset); selectDay(dateKey(date)); };
  $('[data-day-prev]')?.addEventListener('click', () => moveDay(-1));
  $('[data-day-next]')?.addEventListener('click', () => moveDay(1));
  $('[data-day-today]')?.addEventListener('click', () => selectDay(window.PreparationActivity.moscowDay()));
  $('#task-day')?.addEventListener('change', event => { if (parseDate(event.target.value)) selectDay(event.target.value); });
  $$('[data-subject]').forEach(button => button.addEventListener('click', () => {
    subject = button.dataset.subject; profileFilter = 'all';
    if ($('#subject-filter')) $('#subject-filter').value = subject;
    if ($('#profile-filter')) $('#profile-filter').value = 'all';
    visibleCount = pageSize; renderCards();
  }));
  $('#subject-filter')?.addEventListener('change', event => { subject = event.target.value; profileFilter = 'all'; $('#profile-filter').value = 'all'; visibleCount = pageSize; renderCards(); });
  $('#profile-filter')?.addEventListener('change', event => { profileFilter = event.target.value; visibleCount = pageSize; renderCards(); });
  $('#registration-status')?.addEventListener('change', event => { registrationFilter = event.target.value; visibleCount = pageSize; renderCards(); });
  $('#registration-sort')?.addEventListener('change', event => { sortOrder = event.target.value; visibleCount = pageSize; renderCards(); });
  $('#olympiad-search')?.addEventListener('input', () => { visibleCount = pageSize; renderCards(); });
  $('[data-only-favorites]')?.addEventListener('click', () => { onlyFavorites = !onlyFavorites; visibleCount = pageSize; renderCards(); });
  $('#load-more')?.addEventListener('click', () => { visibleCount += pageSize; renderCards(); });
  const resetFilters = () => {
    subject = 'all'; profileFilter = 'all'; registrationFilter = 'all'; sortOrder = 'registration-asc'; onlyFavorites = false; visibleCount = pageSize;
    $('#olympiad-search').value = ''; $('#subject-filter').value = 'all'; $('#profile-filter').value = 'all'; $('#registration-status').value = 'all'; $('#registration-sort').value = 'registration-asc';
    renderCards(); $('#olympiad-search').focus();
  };
  $('#reset-search')?.addEventListener('click', resetFilters);
  $('#reset-filters')?.addEventListener('click', resetFilters);
  $$('[data-olympiad]').forEach(button => button.addEventListener('click', () => {
    const id = button.dataset.olympiad;
    if (state.planned.includes(id)) { state.tasks = state.tasks.filter(task => task.source !== id); announce('Задачи подготовки этой олимпиады удалены.'); }
    else {
      if (!canAddTask()) return;
      state.tasks.push({id:uid(),title:`Подготовиться: ${names[id]}`.slice(0,180),date:selected,done:false,source:id});
      announce('Задача подготовки добавлена на главную.');
    }
    changed();
  }));
  $$('[data-save]').forEach(button => button.addEventListener('click', () => {
    const id = button.dataset.save;
    if (state.favorites.includes(id)) state.favorites = state.favorites.filter(candidate => candidate !== id);
    else state.favorites.push(id);
    changed(); announce(state.favorites.includes(id) ? 'Сохранено в избранное.' : 'Убрано из избранного.');
  }));
  $$('[data-study]').forEach(button => button.addEventListener('click', () => {
    const title = button.dataset.study;
    if (state.tasks.some(task => task.title === title && task.date === today)) { announce('Это занятие уже есть в задачах на сегодня.'); return; }
    if (!canAddTask()) return;
    state.tasks.push({id:uid(),title,date:today,done:false}); changed(); announce('Занятие добавлено на сегодня.');
  }));
  $('.menu-toggle')?.addEventListener('click', () => {
    const toggle = $('.menu-toggle'); const expanded = toggle.getAttribute('aria-expanded') !== 'true';
    toggle.setAttribute('aria-expanded',String(expanded)); $('#main-nav').classList.toggle('open',expanded);
  });
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && $('.menu-toggle')) { $('.menu-toggle').setAttribute('aria-expanded','false'); $('#main-nav').classList.remove('open'); } });
  window.addEventListener('storage', event => {
    if (bootstrap.authenticated || event.key !== STORAGE_KEY) return;
    try {
      state = readSaved(event.newValue === null ? JSON.stringify({tasks: [], favorites: []}) : event.newValue);
      resetForm(); render(); announce('План обновлён из другой вкладки.');
    } catch (_) { announce('Не удалось загрузить изменения из другой вкладки.'); }
  });
  window.addEventListener('pageshow', () => {
    // Browsers can restore form controls after the initial deferred script.
    subject = $('#subject-filter')?.value || 'all';
    profileFilter = $('#profile-filter')?.value || 'all';
    registrationFilter = $('#registration-status')?.value || 'all';
    sortOrder = $('#registration-sort')?.value || 'registration-asc';
    renderCards();
  });
  if ($('[data-today-label]')) $('[data-today-label]').textContent = format(today,{day:'numeric',month:'long',year:'numeric'});
  window.plannerBridge = {getState: () => state, changed, announce, get today() { return window.PreparationActivity.moscowDay(); }, uid, canAddTask,
    canRefresh: () => !editingId,
    replace: saved => { state = readSaved(JSON.stringify(saved)); syncPlan(); resetForm(); render(); },
    importGuest: (serialized, overwrite = false) => {
      const guest = readSaved(serialized);
      const existing = new Set(state.tasks.map(task => task.id));
      const imported = guest.tasks.filter(task => !existing.has(task.id));
      if (state.tasks.length + imported.length > 1000) throw new Error('Слишком много задач для переноса. Сохрани копию и сократи план.');
      const mergedActivity = overwrite ? {...state.activity, ...guest.activity} : {...guest.activity, ...state.activity};
      const mergedTasks = overwrite ? state.tasks.map(task => guest.tasks.find(item => item.id === task.id) || task).concat(imported) : state.tasks.concat(imported);
      mergedTasks.forEach(task => { if (!task.done) delete mergedActivity[task.id]; });
      if (Object.keys(mergedActivity).length > 5000) throw new Error('В истории может быть не более 5000 выполненных задач.');
      state.activity = mergedActivity;
      if (overwrite) { const restored = new Map(guest.tasks.map(task => [task.id, task])); state.tasks = state.tasks.map(task => restored.get(task.id) || task); }
      state.tasks.push(...imported);
      state.favorites = [...new Set([...state.favorites, ...guest.favorites])];
      state.participation = overwrite ? {...state.participation, ...guest.participation} : {...guest.participation, ...state.participation};
      if (overwrite) { state.preferences = guest.preferences; state.dismissed = [...new Set([...state.dismissed, ...guest.dismissed])].slice(-2000); }
      changed(); return imported.length;
    }};
  setInterval(() => {
    const next = window.PreparationActivity.moscowDay();
    if (next !== today) { const wasToday = selected === today; today = next; catalogToday = next; if ($('[data-today-label]')) $('[data-today-label]').textContent = format(today,{day:'numeric',month:'long',year:'numeric'}); if (wasToday && !editingId) selectDay(today); render(); }
  }, 60000);
  resetForm(); if (!bootstrap.authenticated) persist(); render();
})();
