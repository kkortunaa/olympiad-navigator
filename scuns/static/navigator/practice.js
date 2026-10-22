(() => {
    'use strict';
    const editor = document.querySelector('[data-question-editor]');
    if (editor) {
        const kind = editor.elements.answer_type, rule = editor.elements.rule;
        const refresh = () => {
            const allowed = kind.value === 'number' ? ['number'] : kind.value === 'multiple' ? ['set'] : kind.value === 'choice' ? ['exact'] : ['exact', 'text'];
            for (const option of rule.options) option.disabled = !allowed.includes(option.value);
            if (!allowed.includes(rule.value)) rule.value = allowed[0];
            editor.querySelector('[data-field="options_text"]').hidden = !['choice', 'multiple'].includes(kind.value);
            editor.querySelector('[data-field="tolerance"]').hidden = kind.value !== 'number';
        };
        kind.addEventListener('change', refresh); refresh();
    }
    const giving = document.querySelector('[data-give-paper]');
    if (giving) {
        const refresh = () => { giving.querySelector('[data-field="students"]').hidden = giving.elements.audience.value !== 'selected'; };
        giving.elements.audience.addEventListener('change', refresh); refresh();
    }
    const sheet = document.querySelector('[data-answer-sheet]');
    if (sheet) {
        let generation = 0, saved = 0, timer = null, inflight = null, manual = false, blocked = false;
        const status = document.querySelector('[data-save-state]');
        const setStatus = (message, error = false) => { status.textContent = message; status.classList.toggle('practice-save-error', error); };
        const send = async action => {
            const snapshot = generation;
            const body = new FormData(sheet); body.set('action', action);
            const response = await fetch(sheet.getAttribute('action'), {method: 'POST', body, credentials: 'same-origin', headers: {'Accept': 'application/json'}});
            if (response.redirected && response.url.includes('/login/')) throw new Error('Сессия закончилась. Скопируйте ответы и войдите в аккаунт снова.');
            let data;
            try { data = await response.json(); } catch (_) { throw new Error('Сервер не подтвердил сохранение. Ответы остались в полях. Повторите сохранение.'); }
            if (!response.ok) {
                if (response.status === 409) blocked = true;
                throw new Error(data.error || 'Ответы не сохранены. Проверьте соединение и повторите.');
            }
            sheet.elements.revision.value = data.revision;
            saved = snapshot;
            setStatus('Сохранено в аккаунте · ' + new Date().toLocaleTimeString('ru-RU', {hour: '2-digit', minute: '2-digit'}));
            if (action !== 'save') window.location.assign(data.redirect);
        };
        const schedule = () => { clearTimeout(timer); if (!blocked && !manual) timer = setTimeout(autosave, 1000); };
        const autosave = async () => {
            if (blocked || manual || saved === generation) return;
            if (inflight) { schedule(); return; }
            setStatus('Сохраняем ответы…');
            inflight = send('save');
            try { await inflight; } catch (error) { setStatus(error.message || 'Нет связи. Нажмите «Сохранить ответы» для повтора.', true); }
            finally { inflight = null; }
            if (saved !== generation && !status.classList.contains('practice-save-error')) schedule();
        };
        sheet.addEventListener('input', event => {
            if (!event.target.name.startsWith('answer_')) return;
            generation += 1; setStatus('Есть несохранённые ответы…'); schedule();
        });
        sheet.addEventListener('change', event => {
            if (!event.target.name.startsWith('answer_')) return;
            generation += 1; schedule();
        });
        sheet.addEventListener('submit', async event => {
            event.preventDefault(); if (manual) return;
            const action = event.submitter?.value || 'save';
            if (action === 'finish' && !window.confirm('Завершить попытку? После этого ответы в ней нельзя будет изменить.')) return;
            manual = true; clearTimeout(timer);
            try {
                if (inflight) { try { await inflight; } catch (_) {} }
                if (blocked) throw new Error('Нужно загрузить актуальную версию. Скопируйте ответы перед обновлением страницы.');
                setStatus(action === 'finish' ? 'Завершаем и проверяем…' : 'Сохраняем…');
                // Inert prevents edits during final submission without excluding controls from FormData.
                sheet.inert = true;
                await send(action);
            } catch (error) { setStatus(error.message || 'Не удалось сохранить. Ответы остались в полях.', true); }
            finally { sheet.inert = false; manual = false; }
        });
        window.addEventListener('beforeunload', event => {
            if (generation !== saved) { event.preventDefault(); event.returnValue = ''; }
        });
    }
    document.querySelectorAll('[data-explain-url]').forEach(button => button.addEventListener('click', async () => {
        const panel = document.getElementById(button.getAttribute('aria-controls'));
        panel.hidden = false; panel.textContent = 'Готовим объяснение…'; button.disabled = true;
        const csrf = document.querySelector('[data-csrf] input[name=csrfmiddlewaretoken]').value;
        try {
            const response = await fetch(button.dataset.explainUrl, {method: 'POST', credentials: 'same-origin', headers: {'X-CSRFToken': csrf, 'Accept': 'application/json'}});
            const data = await response.json(); panel.replaceChildren();
            const message = document.createElement('p'); message.textContent = data.message || data.error || 'Объяснение временно недоступно.'; panel.append(message);
            if (data.text) { const text = document.createElement('p'); text.textContent = data.text; panel.append(text); }
        } catch (_) { panel.textContent = 'Нет связи с сервисом. Разбор преподавателя, если он добавлен, доступен выше.'; }
        finally { button.disabled = false; button.textContent = 'Объяснить решение'; }
    }));
})();
