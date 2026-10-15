(() => {
  'use strict';
  const $ = s => document.querySelector(s);
  const $$ = s => [...document.querySelectorAll(s)];
  const bootstrap = JSON.parse($('#school-bootstrap')?.textContent || '{}');
  const csrf = $('[data-csrf] input')?.value || '';
  const make = (tag, text, cls) => { const node=document.createElement(tag); if(text!==undefined)node.textContent=text; if(cls)node.className=cls; return node; };
  const link = (text, url) => { const a=make('a',text); a.href=url; return a; };
  async function request(url, options={}) {
    const controller=new AbortController(), timer=setTimeout(()=>controller.abort(),15000);
    try {
      const response=await fetch(url,{credentials:'same-origin',cache:'no-store',...options,signal:controller.signal});
      const body=await response.json().catch(()=>({}));
      if(!response.ok)throw new Error(body.error || (response.status===403?'Нет доступа. Проверьте аккаунт и обновите страницу.':'Не удалось получить данные. Повторите попытку.'));
      return body;
    } catch(error) {
      if(error.name==='AbortError'||error.name==='TypeError')throw new Error('Нет ответа от сервера. Проверьте соединение.');
      throw error;
    } finally { clearTimeout(timer); }
  }
  const post = (url, data) => request(url,{method:'POST',headers:{'X-CSRFToken':csrf},body:new URLSearchParams(data)});
  window.schoolUnreadCount=bootstrap.unread || 0;
  let notices=[], showRead=false, noticeBusy=false;
  function drawNotices() {
    const host=$('[data-school-notices]');if(!host)return;
    host.replaceChildren();
    notices.filter(n=>showRead||!n.read).forEach(n=>{
      const row=make('article',undefined,`school-notice${n.read?' is-read':''}`);
      row.append(make('h3',n.title),make('p',n.text),make('time',n.time));
      const actions=make('div',undefined,'detail-actions');actions.append(link('Открыть →',n.url));
      if(!n.read){const button=make('button','Прочитано');button.type='button';button.addEventListener('click',async()=>{button.disabled=true;try{await post('/class/notices/read/',{notice:n.id});await refreshNotices();}catch(e){$('[data-school-notices-status]').textContent=e.message;button.disabled=false;}});actions.append(button);}
      row.append(actions);host.append(row);
    });
    $('[data-school-notices-empty]').hidden=host.children.length>0;
  }
  async function refreshNotices() {
    if(!bootstrap.authenticated||noticeBusy)return;noticeBusy=true;
    try {
      const data=await request('/class/notices/');notices=data.notices;
      const changed=window.schoolUnreadCount!==data.unread;window.schoolUnreadCount=data.unread;
      $$('[data-school-unread]').forEach(n=>n.textContent=data.unread);
      drawNotices();if(changed)document.dispatchEvent(new Event('planner:render'));
      if($('[data-school-notices-status]'))$('[data-school-notices-status]').textContent='';
    } catch(e) {if($('[data-school-notices-status]'))$('[data-school-notices-status]').textContent=e.message;}
    finally{noticeBusy=false;}
  }
  $('[data-school-show-read]')?.addEventListener('click',event=>{showRead=!showRead;event.target.textContent=showRead?'Скрыть прочитанные':'Показать прочитанные';drawNotices();});
  if(bootstrap.authenticated){refreshNotices();setInterval(()=>{if(!document.hidden)refreshNotices();},20000);}

  const chat=$('[data-school-chat]');
  if(chat){
    const log=$('[data-chat-log]'),form=$('[data-chat-form]'),status=$('[data-chat-status]');
    let last=Math.max(0,...$$('[data-message-id]').map(n=>Number(n.dataset.messageId))), busy=false;
    const historical=chat.dataset.chatHistory==='true';
    const draftKey=`school-chat-draft:${bootstrap.user}:${chat.dataset.membership}`;
    const input=form.querySelector('textarea');
    try{if(!input.value)input.value=sessionStorage.getItem(draftKey)||'';}catch(_){}
    input.addEventListener('input',()=>{try{sessionStorage.setItem(draftKey,input.value);}catch(_){}});
    log.scrollTop=log.scrollHeight;
    async function poll(){
      if(busy)return;busy=true;
      try{
        const nearBottom=log.scrollHeight-log.scrollTop-log.clientHeight<80;
        const data=await request(`${chat.dataset.schoolChat}?after=${last}`);
        if(historical){if(data.messages.length)$('[data-chat-new]').hidden=false;return;}
        data.messages.forEach(m=>{
          $('[data-chat-empty]')?.remove();
          if(log.querySelector(`[data-message-id="${m.id}"]`))return;
          const row=make('article',undefined,`chat-bubble${m.own?' chat-own':''}`);row.dataset.messageId=m.id;
          const meta=make('div',undefined,'chat-meta');meta.append(make('strong',m.name),make('time',m.time));
          row.append(meta,make('p',m.text));log.append(row);last=Math.max(last,m.id);
        });
        if(nearBottom)log.scrollTop=log.scrollHeight;
        if(!data.has_more){await post('/class/notices/read/',{membership:chat.dataset.membership});refreshNotices();}
        else setTimeout(poll,0);
        status.textContent='Сообщения обновляются, пока страница открыта.';
      }catch(e){status.textContent=e.message+' Сообщения сохранены на сервере; обновление повторится автоматически.';}
      finally{busy=false;}
    }
    form.addEventListener('submit',async event=>{
      event.preventDefault();const button=form.querySelector('button[type=submit]');if(button.disabled)return;
      if(!input.value.trim()){input.focus();return;}
      button.disabled=true;status.textContent='Отправляем…';
      try{await post(chat.dataset.schoolChat,new FormData(form));input.value='';try{sessionStorage.removeItem(draftKey);}catch(_){};if(historical){location.href=location.pathname;return;}await poll();log.scrollTop=log.scrollHeight;}
      catch(e){status.textContent=e.message+' Текст оставлен в поле. Проверьте чат перед повторной отправкой.';}
      finally{button.disabled=false;}
    });
    poll();setInterval(()=>{if(!document.hidden)poll();},5000);
  }

  const calendar=$('[data-school-calendar]');
  if(calendar){
    const data=JSON.parse($('#school-calendar-data').textContent);
    function select(day){
      $$('[data-calendar-day]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.calendarDay===day)));
      const item=data[day]||{events:[],conflicts:[]};
      $('[data-calendar-title]').textContent=new Date(`${day}T12:00:00`).toLocaleDateString('ru',{day:'numeric',month:'long',year:'numeric'});
      const warnings=$('[data-calendar-conflicts]'),events=$('[data-calendar-events]');warnings.replaceChildren();events.replaceChildren();
      item.conflicts.forEach(c=>{const box=make('div',undefined,'school-warning');box.append(make('strong','Пересечение дат'),make('p',`${c.left} и ${c.right}. Ученики: ${c.students.join(', ')}. Уточните время туров.`));warnings.append(box);});
      if(!item.events.length)events.append(make('p','На эту дату нет известных туров по регистрациям учеников.','empty-state'));
      item.events.forEach(e=>{
        const article=make('article');article.append(make('h3',e.olympiad),make('p',`${e.name}${e.profiles.length?' · '+e.profiles.join(', '):''}`));
        article.append(make('p',`${e.start.split('-').reverse().join('.')} — ${e.end.split('-').reverse().join('.')}`,'muted'));
        if(e.incomplete)article.append(make('p','Одна из границ периода не опубликована. На календаре отмечена только известная дата.','muted'));
        if(e.format||e.venue)article.append(make('p',[e.format,e.venue].filter(Boolean).join(' · '),'muted'));
        const students=make('ul');e.students.forEach(s=>{const li=make('li');li.append(link(s.name,s.url),make('span',` · ${s.class_name}`));students.append(li);});article.append(students,link('Расписание и источники →',e.url+'#schedule'));events.append(article);
      });
    }
    $$('[data-calendar-day]').forEach(button=>button.addEventListener('click',()=>select(button.dataset.calendarDay)));
    select(calendar.dataset.initial);
  }
  $('[data-copy-code]')?.addEventListener('click',async()=>{
    const code=$('[data-invite-code]');try{await navigator.clipboard.writeText(code.textContent.trim());$('[data-copy-status]').textContent='Код скопирован.';}
    catch(_){const range=document.createRange();range.selectNodeContents(code);const selection=getSelection();selection.removeAllRanges();selection.addRange(range);$('[data-copy-status]').textContent='Код выделен. Скопируйте его сочетанием Ctrl+C или ⌘C.';}
  });
  $('[data-school-student-search]')?.addEventListener('input',event=>{
    const query=event.target.value.trim().toLocaleLowerCase('ru');
    $$('[data-student-name]').forEach(row=>row.hidden=!row.dataset.studentName.toLocaleLowerCase('ru').includes(query));
  });
})();
