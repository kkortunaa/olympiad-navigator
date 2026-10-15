import calendar
from collections import Counter, defaultdict
from datetime import date, timedelta

from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone

from olympiads.models import OlympiadEvent
from planner.models import Workspace
from .models import AssignmentReceipt, SchoolNotice, StudentRegistration

MONTHS = ['январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь']


def notice(user, classroom, title, text, url, kind, membership=None):
    return SchoolNotice.objects.create(recipient=user, classroom=classroom, membership=membership,
                                       title=title[:180], text=text[:500], url=url, kind=kind)


def progress(memberships):
    members = list(memberships.select_related('student'))
    workspaces = {w.user_id: w.state for w in Workspace.objects.filter(user_id__in=[m.student_id for m in members])}
    registrations = Counter(StudentRegistration.objects.filter(student_id__in=[m.student_id for m in members],
        profile__is_active=True, profile__olympiad__is_active=True).values_list('student_id', flat=True))
    assigned = {r['membership_id']: r for r in AssignmentReceipt.objects.filter(membership__in=members).values('membership_id').annotate(
        total=Count('pk'), done=Count('pk', filter=Q(completed_at__isnull=False)))}
    week_start = (timezone.localdate() - timedelta(days=6)).isoformat()
    completed_assignments = defaultdict(dict)
    for receipt in AssignmentReceipt.objects.filter(membership__student_id__in=[m.student_id for m in members],
                                                    completed_at__isnull=False).select_related('membership'):
        completed_assignments[receipt.membership.student_id][f'school-assignment-{receipt.pk}'] = timezone.localdate(receipt.completed_at).isoformat()
    for member in members:
        state = workspaces.get(member.student_id, {})
        activity = {**state.get('activity', {}), **completed_assignments[member.student_id]}
        done_ids = set(activity) | {t['id'] for t in state.get('tasks', []) if t.get('done')}
        stats = assigned.get(member.pk, {})
        member.metrics = {'completed': len(done_ids), 'week': sum(day >= week_start for day in activity.values()),
                          'registrations': registrations[member.student_id], 'assigned': stats.get('total', 0),
                          'assignments_done': stats.get('done', 0)}
    return members


def calendar_context(classrooms, query):
    today = timezone.localdate()
    try:
        year, month = int(query.get('year', today.year)), int(query.get('month', today.month))
        if not 2001 <= year <= 2099 or not 1 <= month <= 12:
            raise ValueError()
    except (ValueError, TypeError):
        year, month = today.year, today.month
    first = date(year, month, 1)
    previous = first - timedelta(days=1)
    following = first + timedelta(days=32)
    calendar_days = list(calendar.Calendar(firstweekday=0).itermonthdates(year, month))
    first_day, last_day = calendar_days[0], calendar_days[-1]
    memberships = [m for cls in classrooms for m in cls.memberships.filter(is_active=True).select_related('student')]
    by_student = defaultdict(list)
    for m in memberships:
        by_student[m.student_id].append(m)
    registrations = list(StudentRegistration.objects.filter(student_id__in=by_student, profile__is_active=True,
        profile__olympiad__is_active=True).select_related('profile__olympiad'))
    events = list(OlympiadEvent.objects.filter(is_active=True, kind='stage',
        olympiad_id__in={r.profile.olympiad_id for r in registrations}).select_related('olympiad'))
    grouped = {}
    for event in events:
        start, end = event.starts_on or event.ends_on, event.ends_on or event.starts_on
        if not start or end < first_day or start > last_day or end < start:
            continue
        pupils = {}
        for reg in registrations:
            if reg.profile.olympiad_id != event.olympiad_id:
                continue
            if event.profile_id and event.profile_id != reg.profile_id:
                continue
            if not event.profile_id and event.profile_name and event.profile_name.casefold() != reg.profile.name.casefold():
                continue
            for member in by_student[reg.student_id]:
                pupils[reg.student_id] = {'id': reg.student_id, 'name': member.student.get_full_name() or member.student.username,
                    'class_name': member.classroom.name, 'url': reverse('classrooms:student_profile', args=[member.pk])}
        if not pupils:
            continue
        # The source can repeat one tour for several profiles and students.
        key = (event.olympiad_id, event.source_url, start, end)
        item = grouped.setdefault(key, {'id': event.pk, 'name': event.name, 'olympiad': event.olympiad.name,
            'profiles': set(), 'start': start.isoformat(), 'end': end.isoformat(), 'students': {},
            'url': reverse('olympiad_detail', args=[event.olympiad_id]),
            'format': event.get_participation_format_display(), 'venue': event.venue,
            'incomplete': not event.starts_on or not event.ends_on})
        item['students'].update(pupils)
        if event.profile_name:
            item['profiles'].add(event.profile_name)
    entries = sorted(grouped.values(), key=lambda e: (e['start'], e['olympiad'], e['id']))
    days, payload = [], {}
    for day in calendar_days:
        key = day.isoformat()
        active = [e for e in entries if e['start'] <= key <= e['end']]
        conflicts, overlapping = set(), []
        for i, left in enumerate(active):
            for right in active[i + 1:]:
                shared = set(left['students']) & set(right['students'])
                if shared:
                    conflicts.update(shared)
                    overlapping.append({'left': left['olympiad'] + (' · ' + ', '.join(sorted(left['profiles'])) if left['profiles'] else ''), 'right': right['olympiad'] + (' · ' + ', '.join(sorted(right['profiles'])) if right['profiles'] else ''),
                                        'students': [left['students'][pk]['name'] for pk in sorted(shared)]})
        public = [{**e, 'profiles': sorted(e['profiles']), 'students': list(e['students'].values())} for e in active]
        payload[key] = {'events': public, 'conflicts': overlapping}
        label = '; '.join(e['olympiad'] + ': ' + e['name'] for e in active)
        days.append({'date': day, 'key': key, 'current': day.month == month, 'today': day == today,
                     'count': len(active), 'conflict': bool(conflicts), 'label': label})
    return {'calendar_days': days, 'calendar_data': payload, 'calendar_caption': f'{MONTHS[month - 1].capitalize()} {year}',
            'previous_month': f'year={previous.year}&month={previous.month}',
            'next_month': f'year={following.year}&month={following.month}',
            'calendar_initial': today.isoformat() if today.year == year and today.month == month else first.isoformat(),
            'calendar_has_entries': bool(entries)}
