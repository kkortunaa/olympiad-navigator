import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase
from django.utils import timezone

from olympiads.models import Olympiad, OlympiadProfile
from .models import Workspace, empty_workspace
from .state import clean_state, MAX_WORKSPACE_BYTES

PASSWORD = 'Orbit!Study2026-check'
NEW_PASSWORD = 'Another!Study2026-check'


def task(key='task-1', **changes):
    return {'id': key, 'title': 'Разобрать задачу', 'date': timezone.localdate().isoformat(), 'done': False, **changes}


class AccountTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(username='student', password=PASSWORD)

    def test_signup_creates_hashed_password_and_private_workspace(self):
        response = self.client.post('/signup/', {'username': 'new-student', 'password1': PASSWORD, 'password2': PASSWORD})
        self.assertRedirects(response, '/account/')
        user = get_user_model().objects.get(username='new-student')
        self.assertNotEqual(user.password, PASSWORD)
        self.assertTrue(user.check_password(PASSWORD))
        self.assertEqual(user.workspace.state, empty_workspace())

    def test_invalid_password_and_duplicate_username_are_rejected(self):
        for username, password in [('student', PASSWORD), ('other', '12345678')]:
            self.client.post('/signup/', {'username': username, 'password1': password, 'password2': password})
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_login_and_post_only_logout(self):
        self.assertEqual(self.client.post('/login/', {'username': 'student', 'password': 'wrong'}).status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertRedirects(self.client.post('/login/', {'username': 'student', 'password': PASSWORD}), '/account/')
        self.assertEqual(self.client.get('/logout/').status_code, 405)
        self.assertRedirects(self.client.post('/logout/'), '/')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_login_throttle_after_ten_failed_attempts(self):
        for _ in range(10):
            self.client.post('/login/', {'username': 'student', 'password': 'wrong'})
        response = self.client.post('/login/', {'username': 'student', 'password': PASSWORD})
        self.assertContains(response, 'Слишком много попыток')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_password_change_requires_old_password(self):
        self.client.force_login(self.user)
        response = self.client.post('/account/password/', {'old_password': 'wrong', 'new_password1': NEW_PASSWORD, 'new_password2': NEW_PASSWORD})
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(PASSWORD))

    def test_password_change_keeps_current_session_and_invalidates_old_session(self):
        other_pc = Client()
        self.client.login(username='student', password=PASSWORD)
        other_pc.login(username='student', password=PASSWORD)
        response = self.client.post('/account/password/', {'old_password': PASSWORD, 'new_password1': NEW_PASSWORD, 'new_password2': NEW_PASSWORD})
        self.assertRedirects(response, '/account/')
        self.assertEqual(self.client.get('/api/workspace/').status_code, 200)
        self.assertEqual(other_pc.get('/api/workspace/').status_code, 401)
        self.assertFalse(Client().login(username='student', password=PASSWORD))
        self.assertTrue(Client().login(username='student', password=NEW_PASSWORD))

    def test_anonymous_account_is_redirected(self):
        self.assertRedirects(self.client.get('/account/'), '/login/?next=/account/', fetch_redirect_response=False)
        self.assertEqual(self.client.get('/api/workspace/').status_code, 401)

    def test_authenticated_pages_are_not_cached(self):
        self.client.force_login(self.user)
        response = self.client.get('/')
        self.assertIn('no-store', response['Cache-Control'])
        self.assertIn('private', response['Cache-Control'])

    def test_profile_updates_only_current_user(self):
        self.client.force_login(self.user)
        self.client.post('/account/', {'first_name': 'Ученик'})
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Ученик')


class WorkspaceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='student', password=PASSWORD)
        self.client.force_login(self.user)

    def save(self, state, revision=0, client=None):
        return (client or self.client).post('/api/workspace/', data=json.dumps({'state': state, 'revision': revision}), content_type='application/json')

    def test_same_account_on_two_independent_clients_sees_same_data(self):
        state = empty_workspace()
        state['tasks'] = [task(done=True, completed_on=timezone.localdate().isoformat())]
        self.assertEqual(self.save(state).status_code, 200)
        second_pc = Client()
        self.assertTrue(second_pc.login(username='student', password=PASSWORD))
        stored = second_pc.get('/api/workspace/').json()
        self.assertEqual(stored['state']['tasks'][0]['title'], 'Разобрать задачу')
        self.assertEqual(stored['state']['activity'], {'task-1': timezone.localdate().isoformat()})
        self.assertEqual(stored['revision'], 1)

    def test_other_account_has_separate_workspace(self):
        self.save({**empty_workspace(), 'tasks': [task()]})
        other = get_user_model().objects.create_user(username='second')
        another = Client(); another.force_login(other)
        self.assertEqual(another.get('/api/workspace/').json()['state']['tasks'], [])
        self.save({**empty_workspace(), 'tasks': [task('other-task')]}, client=another)
        self.assertEqual(self.client.get('/api/workspace/').json()['state']['tasks'][0]['id'], 'task-1')

    def test_outdated_revision_does_not_overwrite(self):
        self.assertEqual(self.save({**empty_workspace(), 'tasks': [task()]}).status_code, 200)
        self.assertEqual(self.save(empty_workspace()).status_code, 409)
        self.assertEqual(self.client.get('/api/workspace/').json()['state']['tasks'][0]['id'], 'task-1')

    def test_csrf_is_required(self):
        protected = Client(enforce_csrf_checks=True); protected.force_login(self.user)
        payload = json.dumps({'state': empty_workspace(), 'revision': 0})
        self.assertEqual(protected.post('/api/workspace/', data=payload, content_type='application/json').status_code, 403)
        protected.get('/account/')
        token = protected.cookies['csrftoken'].value
        self.assertEqual(protected.post('/api/workspace/', data=payload, content_type='application/json', HTTP_X_CSRFTOKEN=token).status_code, 200)

    def test_bad_body_revision_and_oversized_body_are_rejected(self):
        for body in ['{', '[]', '{"revision":true,"state":{}}', 'x'*(MAX_WORKSPACE_BYTES+1)]:
            self.assertEqual(self.client.post('/api/workspace/', data=body, content_type='application/json').status_code, 400)

    def test_deleted_completed_task_keeps_history(self):
        today = timezone.localdate().isoformat()
        state = {**empty_workspace(), 'tasks': [task(done=True, completed_on=today)]}
        self.assertEqual(self.save(state).status_code, 200)
        state = self.client.get('/api/workspace/').json()['state']; state['tasks'] = []
        self.assertEqual(self.save(state, revision=1).status_code, 200)
        self.assertEqual(self.client.get('/api/workspace/').json()['state']['activity'], {'task-1': today})


class StateTests(TestCase):
    def test_legacy_done_task_does_not_invent_completion_date(self):
        state = clean_state({'tasks': [task(done=True)]})
        self.assertTrue(state['tasks'][0]['done'])
        self.assertNotIn('completed_on', state['tasks'][0])
        self.assertEqual(state['activity'], {})

    def test_completion_and_undo_reconcile_history(self):
        today = timezone.localdate().isoformat()
        state = clean_state({'tasks': [task(done=True)], 'activity': {'task-1': today}})
        self.assertEqual(state['tasks'][0]['completed_on'], today)
        state['tasks'][0]['done'] = False
        state = clean_state(state)
        self.assertEqual(state['activity'], {})
        self.assertNotIn('completed_on', state['tasks'][0])

    def test_invalid_and_future_activity_dates_rejected(self):
        future = (timezone.localdate()+timedelta(days=1)).isoformat()
        for day in ['2026-02-30', '2026-1-01', '', future, 5]:
            with self.subTest(day=day), self.assertRaises(ValueError):
                clean_state({'activity': {'task-1': day}})

    def test_task_count_title_and_history_limits(self):
        self.assertEqual(len(clean_state({'tasks': [task(str(i), title='x'*180) for i in range(1000)]})['tasks']), 1000)
        with self.assertRaises(ValueError): clean_state({'tasks': [task(str(i)) for i in range(1001)]})
        with self.assertRaises(ValueError): clean_state({'tasks': [task(title='x'*181)]})
        today = timezone.localdate().isoformat()
        self.assertEqual(len(clean_state({'activity': {str(i): today for i in range(5000)}})['activity']), 5000)
        with self.assertRaises(ValueError): clean_state({'activity': {str(i): today for i in range(5001)}})

    def test_duplicate_task_ids_and_non_dates_rejected(self):
        with self.assertRaises(ValueError): clean_state({'tasks': [task(), task()]})
        with self.assertRaises(ValueError): clean_state({'tasks': [task(date='not-a-date')]})

    def test_invalid_notification_preferences_rejected(self):
        with self.assertRaises(ValueError): clean_state({'preferences': {'lead_days': 5}})
        with self.assertRaises(ValueError): clean_state({'participation': {'1': 'invalid'}})


class InterfaceTests(TestCase):
    def test_home_contains_activity_tasks_and_no_catalog_or_old_plan(self):
        response = self.client.get('/')
        self.assertContains(response, 'data-activity-grid')
        self.assertContains(response, 'id="tasks"')
        for text in ['id="olympiads"', 'calendar-days', 'Мой план', 'Моя неделя']:
            self.assertNotContains(response, text)

    def test_legacy_plan_redirects_and_notifications_are_available(self):
        for path in ['/plan/', '/list/', '/sunc/']:
            self.assertRedirects(self.client.get(path), '/', status_code=301)
        self.assertContains(self.client.get('/notifications/'), 'data-notification-list')

    def test_catalog_has_searchable_pickers_registration_buttons_and_participation(self):
        response = self.client.get('/olympiads/')
        self.assertContains(response, 'role="combobox"', count=3)
        self.assertContains(response, 'data-registration="active"')
        self.assertContains(response, 'data-catalog-view="participation"')
        self.assertNotContains(response, '<select id="subject-filter"')
        self.assertContains(response, 'Профиль — направление конкретной олимпиады')

    def test_account_is_settings_only(self):
        self.client.force_login(get_user_model().objects.create_user(username='student'))
        response = self.client.get('/account/')
        self.assertContains(response, 'Изменить пароль')
        self.assertNotContains(response, 'data-participation-list')
        self.assertNotContains(response, 'data-notification-list')
