from datetime import date

from olympiads.models import Olympiad, OlympiadProfile
from django.utils import timezone

MAX_TASKS = 1000
MAX_ACTIVITY = 5000
MAX_WORKSPACE_BYTES = 2000000


def valid_day(value):
    try:
        return isinstance(value, str) and len(value) == 10 and date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


STATUSES = {'planning': 'Планирую', 'registered': 'Зарегистрирован',
            'qualified': 'Прошёл отбор', 'waiting': 'Ожидаю результат',
            'completed': 'Участие завершено', 'withdrawn': 'Не участвую'}


def clean_state(raw):
    if not isinstance(raw, dict):
        raise ValueError('План должен быть объектом.')
    tasks, favorites = raw.get('tasks', []), raw.get('favorites', [])
    participation = raw.get('participation', {})
    preferences, dismissed = raw.get('preferences', {}), raw.get('dismissed', [])
    activity = raw.get('activity', {})
    if (not isinstance(tasks, list) or len(tasks) > MAX_TASKS or not isinstance(favorites, list)
            or len(favorites) > 1000 or not isinstance(participation, dict) or len(participation) > 1000
            or not isinstance(preferences, dict) or not isinstance(dismissed, list) or len(dismissed) > 2000
            or not isinstance(activity, dict) or len(activity) > MAX_ACTIVITY):
        raise ValueError('Некорректный формат или слишком большой план.')
    today = timezone.localdate().isoformat()
    if any(not isinstance(key, str) or not 1 <= len(key) <= 100 or not valid_day(value) or value > today
           for key, value in activity.items()):
        raise ValueError('Некорректная дата выполнения задачи.')
    activity = dict(activity)
    names = {item.plan_key for item in Olympiad.objects.all()}
    profiles = {str(pk) for pk in OlympiadProfile.objects.values_list('pk', flat=True)}
    result, seen = [], set()
    for task in tasks:
        if not isinstance(task, dict):
            raise ValueError('Некорректная задача.')
        key, title, day = task.get('id'), task.get('title'), task.get('date')
        if (not isinstance(key, str) or not 1 <= len(key) <= 100 or key in seen
                or not isinstance(title, str) or not 1 <= len(title.strip()) <= 180
                or not isinstance(day, str) or len(day) != 10):
            raise ValueError('Проверь название и дату задачи.')
        try:
            if date.fromisoformat(day).isoformat() != day:
                raise ValueError()
        except ValueError:
            raise ValueError('Некорректная дата задачи.')
        seen.add(key)
        item = {'id': key, 'title': title.strip(), 'date': day, 'done': task.get('done') is True}
        completed = task.get('completed_on') or activity.get(key)
        if completed is not None and (not valid_day(completed) or completed > today):
            raise ValueError('Некорректная дата выполнения задачи.')
        if item['done'] and completed:
            item['completed_on'] = completed
            activity[key] = completed
        elif not item['done']:
            activity.pop(key, None)
        if isinstance(task.get('source'), str) and task['source'] in names:
            item['source'] = task['source']
        result.append(item)
    if any(not isinstance(value, str) for value in favorites + dismissed):
        raise ValueError('Некорректные сохранённые элементы.')
    if any(status not in STATUSES for status in participation.values() if isinstance(status, str)) or any(not isinstance(status, str) for status in participation.values()):
        raise ValueError('Неизвестный статус участия.')
    lead = preferences.get('lead_days', 3)
    if type(lead) is not int or lead not in (1, 3, 7, 14):
        raise ValueError('Выбери напоминание за 1, 3, 7 или 14 дней.')
    if len(activity) > MAX_ACTIVITY:
        raise ValueError('В истории может быть не более 5000 выполненных задач.')
    return {'tasks': result, 'activity': activity, 'favorites': list(dict.fromkeys(key for key in favorites if key in names)),
            'participation': {key: value for key, value in participation.items() if key in profiles},
            'preferences': {'notifications': preferences.get('notifications', True) is True, 'lead_days': lead},
            'dismissed': list(dict.fromkeys(key for key in dismissed if len(key) <= 200))}
