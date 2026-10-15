(() => {
  'use strict';
  const $ = selector => document.querySelector(selector);
  const $$ = selector => [...document.querySelectorAll(selector)];
  const bridge = window.plannerBridge;
  if (!bridge) return;
  const bootstrap = JSON.parse($('#personal-bootstrap')?.textContent || '{}');
  const catalog = JSON.parse($('#planner-catalog')?.textContent || '[]');
  const profiles = new Map();
  catalog.forEach(olympiad => olympiad.profiles.forEach(profile => profiles.set(profile.id, {...profile, olympiad})));
  const csrf = $('[data-csrf] input')?.value || '';
  const registeredProfiles = new Set((bootstrap.registered_profiles || []).map(p=>p.id));
  const watchedKeys = state => new Set([...state.favorites, ...state.planned, ...(state.registered || [])]);
  const profileCaption = names => names.length > 3 ? `${names.slice(0,2).join(', ')}, ещё ${names.length-2}` : names.join(', ');
  const element = (tag, text, className) => {
    const node = document.createElement(tag);
    if (text) node.textContent = text;
    if (className) node.className = className;
    return node;
  };
  const link = (label, url, external = false) => {
    const node = element('a', label, 'text-link'); node.href = url;
    if (external) { node.target = '_blank'; node.rel = 'noopener noreferrer'; }
    return node;
  };
  const day = () => {
    const parts = Object.fromEntries(new Intl.DateTimeFormat('en', {timeZone:'Europe/Moscow', year:'numeric', month:'2-digit', day:'2-digit'}).formatToParts(new Date()).map(part => [part.type, part.value]));
    return `${parts.year}-${parts.month}-${parts.day}`;
  };
  const daysBetween = (a, b) => Math.round((Date.parse(`${a}T12:00:00Z`) - Date.parse(`${b}T12:00:00Z`)) / 86400000);
  const dateLabel = key => new Date(`${key}T12:00:00`).toLocaleDateString('ru', {day:'numeric',month:'long',year:'numeric'});
  const interval = event => event.start === event.end ? dateLabel(event.start) : `${dateLabel(event.start)} — ${dateLabel(event.end)}`;
  let revision = bootstrap.revision || 0;
  let pending = null, running = false, syncError = '', conflict = false, saveTimer;
  let showRead = false, resourcesLimit = 12, draftExported = false;
  const draftKey = `olympiad-draft:${bootstrap.user}`;
  const browserKey = `olympiad-browser-notices:${bootstrap.authenticated ? bootstrap.user : 'guest'}`;
  const sentKey = `${browserKey}:sent`;
  let browserEnabled = false, sent = new Set();
  try { browserEnabled = localStorage.getItem(browserKey) === 'true'; sent = new Set(JSON.parse(localStorage.getItem(sentKey) || '[]')); } catch (_) { /* The on-site notification centre still works. */ }

  async function workspaceRequest(options = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 20000);
    try { return await fetch('/api/workspace/', {...options, signal:controller.signal, credentials:'same-origin', cache:'no-store'}); }
    catch (error) { if (error.name==='AbortError') throw new Error('Сервер не ответил вовремя. Повтори сохранение.'); if(error.name==='TypeError') throw new Error('Нет соединения с сервером. Проверь подключение и повтори попытку.'); throw error; }
    finally { clearTimeout(timer); }
  }
  function setSyncStatus() {
    if (!bootstrap.authenticated) return;
    $$('[data-sync-status]').forEach(node => { node.textContent = syncError ? 'Изменения пока не сохранены в аккаунте.' : running || pending ? 'Сохраняем изменения…' : 'Изменения сохранены в аккаунте.'; });
    $('[data-sync-error]').hidden = !syncError;
    $('[data-sync-error-text]').textContent = syncError;
    $('[data-retry-sync]').hidden = conflict;
  }
  function keepDraft(snapshot) {
    try { sessionStorage.setItem(draftKey, JSON.stringify({revision, state:snapshot})); } catch (_) { /* Saving on the server remains available. */ }
  }
  async function flush() {
    if (!bootstrap.authenticated || running || !pending || conflict) return;
    const snapshot = pending; pending = null; running = true; syncError = ''; keepDraft(snapshot); setSyncStatus();
    try {
      const response = await workspaceRequest({method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json','X-CSRFToken':csrf}, body:JSON.stringify({revision,state:snapshot})});
      const body = await response.json().catch(() => ({}));
      if (!response.ok) { conflict = response.status === 409; throw new Error(body.error || (response.status === 403 ? 'Сессия истекла. Скачай свои изменения и войди в аккаунт снова.' : 'Не удалось сохранить план. Проверь подключение и повтори попытку.')); }
      revision = body.revision;
      if (pending) keepDraft(pending);
      else try { sessionStorage.removeItem(draftKey); } catch (_) { /* No draft to remove. */ }
    } catch (error) {
      pending = pending || snapshot; syncError = error.message; keepDraft(pending);
    } finally { running = false; setSyncStatus(); }
    if (pending && !syncError) flush();
  }
  window.personalPlanner = {save(state) {
    if (!bootstrap.authenticated) return;
    pending = JSON.parse(JSON.stringify(state)); draftExported = false; keepDraft(pending); setSyncStatus();
    clearTimeout(saveTimer); saveTimer = setTimeout(flush, 350);
  }};
  function exportPlan() {
    const blob = new Blob([JSON.stringify(bridge.getState(), null, 2)], {type:'application/json'});
    const url = URL.createObjectURL(blob); const anchor = element('a');
    draftExported = true;
    anchor.href = url; anchor.download = `olympiad-plan-${day()}.json`; anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  $$('[data-export-plan]').forEach(button => button.addEventListener('click', exportPlan));
  $('[data-retry-sync]')?.addEventListener('click', () => { syncError = ''; flush(); });
  $('[data-reload-workspace]')?.addEventListener('click', async () => {
    if (running) return;
    try {
      const response = await workspaceRequest();
      if (!response.ok) throw new Error('Не удалось загрузить план. Войди в аккаунт снова.');
      const body = await response.json();
      if (pending || syncError) exportPlan();
      pending = null; syncError = ''; conflict = false; revision = body.revision;
      try { sessionStorage.removeItem(draftKey); } catch (_) { /* Optional recovery data. */ }
      bridge.replace(body.state); setSyncStatus(); bridge.announce('План загружен из аккаунта. Локальные изменения скачаны отдельной копией.');
    } catch (error) { syncError = error.message; setSyncStatus(); }
  });
  window.addEventListener('beforeunload', event => {
    if (!bootstrap.authenticated || draftExported || (!pending && !running && !syncError)) return;
    event.preventDefault(); event.returnValue = '';
  });
  $('[data-logout-form]')?.addEventListener('submit', event => {
    if (running || ((pending || syncError) && !draftExported)) { event.preventDefault(); bridge.announce('Сначала сохрани изменения или скачай копию плана.'); flush(); }
    else if (draftExported) { pending=null; syncError=''; try { sessionStorage.removeItem(draftKey); } catch (_) {} }
  });
  $('[data-import-guest]')?.addEventListener('click', () => {
    try {
      const guest = localStorage.getItem('olympiad-navigator:v1');
      if (!guest) { $('[data-import-status]').textContent = 'В этом браузере нет гостевого плана.'; return; }
      const count = bridge.importGuest(guest);
      $('[data-import-status]').textContent = `Перенесено новых задач: ${count}. Избранное и статусы объединены. Повторный перенос не создаст копии задач.`;
    } catch (error) { $('[data-import-status]').textContent = `Не удалось перенести план: ${error.message}`; }
  });
  $('[data-restore-plan]')?.addEventListener('change', async event => {
    const file=event.target.files?.[0]; if(!file) return;
    try {
      if(file.size>2000000) throw new Error('Копия слишком большая. Максимум — 2 МБ.');
      const raw=await file.text();
      bridge.importGuest(raw,true);
      $('[data-import-status]').textContent='Копия объединена с текущим планом. Совпадающие задачи и статусы восстановлены из файла.';
    }catch(error){$('[data-import-status]').textContent=`Не удалось загрузить копию: ${error.message}`;}
    event.target.value='';
  });
  async function refresh() {
    if (!bootstrap.authenticated || pending || running || syncError || !bridge.canRefresh() || document.hidden) return;
    try {
      const response = await workspaceRequest();
      if (!response.ok) return;
      const body = await response.json();
      if (pending || running || !bridge.canRefresh()) return;
      if (body.revision !== revision) { revision = body.revision; bridge.replace(body.state); bridge.announce('План обновлён из аккаунта.'); }
    } catch (_) { /* The next save will surface any connectivity problem. */ }
  }
  setInterval(refresh, 45000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) { refresh(); render(); } });

  function renderParticipation(state) {
    const list=$('[data-participation-list]'); if (!list) return;
    const watched=watchedKeys(state);
    list.replaceChildren();
    catalog.filter(olympiad=>watched.has(olympiad.key)).forEach(olympiad=>{
      const row=element('div',null,'participation-row'), description=element('div');
      description.append(link(olympiad.name,olympiad.url),element('p',olympiad.season,'muted'));
      const actions=element('div',null,'detail-actions');
      actions.append(link('Расписание →',olympiad.url+'#schedule'),link('Задания →',olympiad.url+'#profiles'));
      row.append(description,actions);list.append(row);
    });
    $('[data-participation-empty]').hidden=list.children.length>0;
  }
  function selectedEvents(state) {
    const watched=watchedKeys(state), events=new Map();
    catalog.filter(olympiad=>watched.has(olympiad.key)).forEach(olympiad=>{
      const broadWatch=state.favorites.includes(olympiad.key)||state.planned.includes(olympiad.key);
      const registeredNames=new Set(olympiad.profiles.filter(p=>registeredProfiles.has(p.id)).map(p=>p.name.toLocaleLowerCase('ru')));
      olympiad.events.forEach(event=>{
        if(!broadWatch && event.profile && !registeredNames.has(event.profile.toLocaleLowerCase('ru')))return;
        // Editorial subject URLs can refer to the same common event ID.
        const sourceEvent=event.url.match(/\/events\/(\d+)/)?.[1] || event.url;
        const key=`${olympiad.key}:${sourceEvent}:${event.kind}:${event.start}:${event.end}:${event.name}`;
        if(!events.has(key)) events.set(key,{...event,key,olympiad,names:[]});
        const item=events.get(key);
        const names=event.profile ? [event.profile] : olympiad.profiles.map(profile=>profile.name);
        item.names=[...new Set([...item.names,...names])];
      });
    });
    return [...events.values()];
  }
  function findConflicts(events) {
    const stages = events.filter(event => event.kind === 'stage' && event.start && event.end && event.end >= day()).sort((a,b)=>a.start.localeCompare(b.start) || a.key.localeCompare(b.key));
    const matches = [];
    for (let i=0;i<stages.length;i++) for (let j=i+1;j<stages.length && stages[j].start<=stages[i].end;j++) {
      const left=stages[i],right=stages[j];
      if (left.olympiad.key===right.olympiad.key) continue;
      matches.push({id:`overlap:${left.id}:${right.id}:${left.start}:${left.end}:${right.start}:${right.end}`,kind:'conflict',title:'Пересекаются даты туров',left,right,
        text:`${left.olympiad.name} (${profileCaption(left.names)}): ${left.name}, ${interval(left)}. ${right.olympiad.name} (${profileCaption(right.names)}): ${right.name}, ${interval(right)}. Уточни точное время и возможность выбрать день.`});
    }
    return matches;
  }
  function notifications(state, events, conflicts) {
    if (!state.preferences.notifications) return [];
    const notices = [...conflicts], lead = state.preferences.lead_days;
    events.forEach(event => {
      const boundaries = event.kind==='registration' ? [['start','Открывается регистрация'],['end','Заканчивается регистрация']] : event.kind==='stage' ? [['start','Начинается тур']] : [];
      boundaries.forEach(([field,title]) => {
        if (!event[field]) return;
        const diff = daysBetween(event[field],day());
        if (diff<0 || diff>lead) return;
        notices.push({id:`event:${event.id}:${field}:${event[field]}`,title,kind:'event',event,
          text:`${event.olympiad.name} · ${profileCaption(event.names)} · ${event.name}. ${dateLabel(event[field])}${diff===0 ? ' — сегодня' : ` (через ${diff} дн.)`}.`});
      });
    });
    state.tasks.filter(task=>!task.done).forEach(task=>{
      const diff = daysBetween(task.date,day());
      if (diff>0) return;
      notices.push({id:`task:${task.id}:${task.date}`,kind:'task',title:diff===0?'Задача на сегодня':'Задача просрочена',text:`${task.title} · ${dateLabel(task.date)}`});
    });
    return notices;
  }
  function noticeRow(notice, read, dismissible) {
    const row = element('article',null,`notice-item${notice.kind==='conflict'?' notice-warning':''}${read?' notice-read':''}`);
    row.append(element('h3',notice.title),element('p',notice.text));
    const actions = element('div',null,'detail-actions');
    if (notice.event) actions.append(link('Источник дат ↗',notice.event.url,true),link('Олимпиада →',notice.event.olympiad.url));
    if (notice.left) actions.append(link('Первый тур ↗',notice.left.url,true),link('Второй тур ↗',notice.right.url,true));
    if (notice.kind==='task') actions.append(link('К задачам →','/?tasks=all#tasks'));
    if (dismissible) { const button=element('button',read?'Вернуть в непрочитанные':'Прочитано');button.type='button';button.addEventListener('click',()=>{const state=bridge.getState();state.dismissed=read?state.dismissed.filter(id=>id!==notice.id):[...new Set([...state.dismissed,notice.id])].slice(-2000);bridge.changed();});actions.append(button); }
    row.append(actions); return row;
  }
  function browserStatus() {
    const message = $('[data-browser-status]'),button=$('[data-enable-browser]');
    if (!message || !button) return;
    const supported = 'Notification' in window && window.isSecureContext;
    button.disabled = !supported || Notification.permission === 'denied';
    button.textContent = browserEnabled ? 'Отключить уведомления браузера' : 'Включить уведомления браузера';
    message.textContent = !supported ? 'Этот браузер не поддерживает системные уведомления. Уведомления на сайте доступны.' : Notification.permission==='denied' ? 'Браузер запретил уведомления. Разрешение можно изменить в настройках сайта.' : browserEnabled && Notification.permission==='granted' ? 'Уведомления браузера включены на этом устройстве, пока сайт открыт.' : 'Системные уведомления выключены. На сайте напоминания доступны.';
  }
  $('[data-enable-browser]')?.addEventListener('click', async () => {
    if (!('Notification' in window)) return;
    if (browserEnabled) browserEnabled=false;
    else {
      try { browserEnabled = (Notification.permission==='granted' ? 'granted' : await Notification.requestPermission())==='granted'; }
      catch (_) { browserEnabled=false; }
    }
    try { localStorage.setItem(browserKey,String(browserEnabled)); } catch (_) { /* Optional browser preference. */ }
    browserStatus(); render();
  });
  let lastDelivery = 0;
  function deliverBrowser(notices, state) {
    if (!browserEnabled || !('Notification' in window) || Notification.permission!=='granted' || document.hidden || Date.now()-lastDelivery<60000) return;
    let count=0;
    notices.filter(notice=>!sent.has(notice.id) && !state.dismissed.includes(notice.id)).slice(0,3).forEach(notice=>{
      try {
        const notification = new Notification(notice.title,{body:notice.text,tag:notice.id});
        notification.onclick=()=>{window.focus();window.location.href='/notifications/';};
        sent.add(notice.id);count++;
      } catch (_) { /* The centre remains usable if native notifications fail. */ }
    });
    if(count) lastDelivery=Date.now();
    try { localStorage.setItem(sentKey,JSON.stringify([...sent].slice(-2000))); } catch (_) { /* Optional deduplication cache. */ }
  }
  function renderResources(state) {
    const list = $('[data-resource-list]'); if (!list) return;
    const query = ($('[data-resource-search]')?.value || '').trim().toLocaleLowerCase('ru').replaceAll('ё','е');
    const mine = $('[data-resources-mine]')?.checked;
    const resources = [...profiles.values()].filter(profile=>profile.tasks_url && (!mine || watchedKeys(state).has(profile.olympiad.key)) && `${profile.olympiad.name} ${profile.name} ${profile.subjects}`.toLocaleLowerCase('ru').replaceAll('ё','е').includes(query));
    list.replaceChildren();
    resources.slice(0,resourcesLimit).forEach(profile=>{
      const row=element('article',null,'resource-row'),description=element('div');
      description.append(element('strong',profile.olympiad.name),element('p',profile.name,'muted'));
      const actions=element('div',null,'detail-actions');actions.append(link('Открыть архив заданий ↗',profile.tasks_url,true));
      const title=`Разобрать задания: ${profile.olympiad.name} · ${profile.name}`.slice(0,180);
      const added=state.tasks.some(task=>task.title===title && task.date===bridge.today);
      const button=element('button',added?'✓ Задача разбора добавлена':'Запланировать разбор на сегодня');button.type='button';button.disabled=added;
      button.addEventListener('click',()=>{if (!bridge.canAddTask()) return; state.tasks.push({id:bridge.uid(),title,date:bridge.today,done:false,source:profile.olympiad.key});bridge.changed();bridge.announce('Задача разбора добавлена на сегодня.');});
      actions.append(button);description.append(actions);row.append(description);list.append(row);
    });
    $('[data-resource-count]').textContent=`Архивов найдено: ${resources.length}`;
    $('[data-resource-empty]').hidden=resources.length>0;
    $('[data-resources-more]').hidden=resources.length<=resourcesLimit;
  }
  $('[data-resource-search]')?.addEventListener('input',()=>{resourcesLimit=12;renderResources(bridge.getState());});
  $('[data-resources-mine]')?.addEventListener('change',()=>{resourcesLimit=12;renderResources(bridge.getState());});
  $('[data-resources-more]')?.addEventListener('click',()=>{resourcesLimit+=12;renderResources(bridge.getState());});
  function render() {
    const state=bridge.getState();renderParticipation(state);renderResources(state);
    const events=selectedEvents(state),conflicts=findConflicts(events),notices=notifications(state,events,conflicts);
    const unread=notices.filter(notice=>!state.dismissed.includes(notice.id));
    const schoolUnread = window.schoolUnreadCount ?? JSON.parse($('#school-bootstrap')?.textContent || '{}').unread ?? 0;
    const totalUnread = unread.length + schoolUnread;
    $$('[data-notification-count]').forEach(node=>{node.textContent=totalUnread;node.setAttribute('aria-label',`Непрочитанных уведомлений: ${totalUnread}`);});
    const banner=$('[data-conflict-banner]');banner.hidden=!conflicts.length;banner.textContent=`Пересечения туров: ${conflicts.length}. Проверь даты в разделе «Олимпиады» →`;
    const conflictList=$('[data-conflict-list]');if(conflictList){conflictList.replaceChildren(...conflicts.slice(0,50).map(notice=>noticeRow(notice,false,false)));$('[data-conflicts-empty]').hidden=conflicts.length>0;}
    const list=$('[data-notification-list]');
    if(list){list.replaceChildren(...notices.filter(notice=>showRead || !state.dismissed.includes(notice.id)).slice(0,100).map(notice=>noticeRow(notice,state.dismissed.includes(notice.id),true)));$('[data-notifications-empty]').hidden=list.children.length>0;$('[data-notifications-empty]').textContent=!state.preferences.notifications?'Напоминания выключены. Совпадения туров доступны в разделе «Олимпиады → Мои олимпиады».':unread.length===0 && notices.length?'Все уведомления прочитаны.':'Срочных событий пока нет. Добавь олимпиаду в избранное или задачи подготовки, чтобы следить за сроками.';$('[data-mark-all]').hidden=unread.length===0;}
    if($('[data-notices-enabled]')) $('[data-notices-enabled]').checked=state.preferences.notifications;
    if($('[data-notice-lead]')) $('[data-notice-lead]').value=String(state.preferences.lead_days);
    browserStatus();deliverBrowser(notices,state);
  }
  $('[data-notices-enabled]')?.addEventListener('change',event=>{bridge.getState().preferences.notifications=event.target.checked;bridge.changed();});
  $('[data-notice-lead]')?.addEventListener('change',event=>{bridge.getState().preferences.lead_days=Number(event.target.value);bridge.changed();});
  $('[data-mark-all]')?.addEventListener('click',()=>{const state=bridge.getState(),events=selectedEvents(state);state.dismissed=[...new Set([...state.dismissed,...notifications(state,events,findConflicts(events)).map(notice=>notice.id)])].slice(-2000);bridge.changed();});
  $('[data-show-read]')?.addEventListener('click',event=>{showRead=!showRead;event.target.textContent=showRead?'Скрыть прочитанные':'Показать прочитанные';render();});
  document.addEventListener('planner:render',render);
  setInterval(render,60000);
  if(bootstrap.authenticated){
    try {
      const draft=JSON.parse(sessionStorage.getItem(draftKey) || 'null');
      if(draft && draft.state){
        bridge.replace(draft.state);pending=JSON.parse(JSON.stringify(bridge.getState()));
        if(draft.revision===revision) flush();
        else {conflict=true;syncError='Есть несохранённые изменения из предыдущей страницы, а план в аккаунте уже обновился. Скачай свои изменения и загрузи свежий план.';}
      }
    }catch(error){if(error.name!=='SecurityError') syncError='Не удалось восстановить несохранённый план. Загрузи план из аккаунта.';}
    setSyncStatus();
  }
  render();
})();
