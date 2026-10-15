import json
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from olympiads.models import Olympiad, OlympiadEvent, OlympiadProfile
from planner.models import Workspace, empty_workspace
from .models import (Assignment, AssignmentReceipt, ChatMessage, Classroom, Invitation, Membership,
                     SchoolNotice, StudentRegistration, VariantDraft)
from .services import calendar_context, progress

PASSWORD = 'Navigation!Class-2026'


class SchoolTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.teacher = User.objects.create_user(username='teacher', first_name='Ирина Учитель', password=PASSWORD, role='teacher')
        cls.stranger = User.objects.create_user(username='stranger', password=PASSWORD, role='teacher')
        cls.student = User.objects.create_user(username='student', first_name='Анна', password=PASSWORD)
        cls.peer = User.objects.create_user(username='peer', first_name='Иван', password=PASSWORD)
        cls.other = User.objects.create_user(username='other', password=PASSWORD)
        cls.classroom = Classroom.objects.create(teacher=cls.teacher, name='10 А')
        cls.foreign = Classroom.objects.create(teacher=cls.stranger, name='Чужой класс')
        cls.member = Membership.objects.create(classroom=cls.classroom, student=cls.student)
        cls.peer_member = Membership.objects.create(classroom=cls.classroom, student=cls.peer)
        cls.foreign_member = Membership.objects.create(classroom=cls.foreign, student=cls.other)
        cls.olympiad = Olympiad.objects.create(season='2026/2027', catalog_number=1, name='Олимпиада А', catalog_url='https://example.test')
        cls.second = Olympiad.objects.create(season='2026/2027', catalog_number=2, name='Олимпиада Б', catalog_url='https://example.test')
        cls.profile = OlympiadProfile.objects.create(olympiad=cls.olympiad, name='математика', level=1)
        cls.other_profile = OlympiadProfile.objects.create(olympiad=cls.second, name='информатика', level=1)
        cls.event = OlympiadEvent.objects.create(olympiad=cls.olympiad, profile=cls.profile, profile_name='математика', kind='stage',
            name='Отборочный тур', starts_on=date(2026, 10, 20), ends_on=date(2026, 10, 22),
            source_url='https://example.test/a/tour', last_checked_at=timezone.now())
        cls.second_event = OlympiadEvent.objects.create(olympiad=cls.second, profile=cls.other_profile, profile_name='информатика', kind='stage',
            name='Отборочный тур', starts_on=date(2026, 10, 21), ends_on=date(2026, 10, 23),
            source_url='https://example.test/b/tour', last_checked_at=timezone.now())

    def setUp(self):
        cache.clear()
        self.teacher_client = Client(); self.teacher_client.force_login(self.teacher)
        self.student_client = Client(); self.student_client.force_login(self.student)
        self.peer_client = Client(); self.peer_client.force_login(self.peer)
        self.stranger_client = Client(); self.stranger_client.force_login(self.stranger)

    def url(self, name, pk=None):
        return reverse('classrooms:' + name, args=[pk] if pk is not None else [])

    def make_assignment(self):
        assignment = Assignment.objects.create(classroom=self.classroom, title='Комбинаторика', instructions='Решить 5 задач', due_on=timezone.localdate())
        return AssignmentReceipt.objects.create(assignment=assignment, membership=self.member)

    def calendar(self):
        return calendar_context([self.classroom], {'year': '2026', 'month': '10'})

    def test_old_accounts_default_to_student(self):
        self.assertEqual(self.student.role, 'student')
        self.assertFalse(self.student.is_teacher)

    def test_separate_signup_assigns_role_on_server(self):
        for path, username, role in [('/signup/', 'new-student', 'student'), ('/teacher/signup/', 'new-teacher', 'teacher')]:
            client = Client()
            response = client.post(path, {'username': username, 'first_name': 'Новое имя', 'password1': PASSWORD,
                                         'password2': PASSWORD, 'role': 'teacher'})
            self.assertEqual(response.status_code, 302)
            user = get_user_model().objects.get(username=username)
            self.assertEqual(user.role, role)
            self.assertTrue(user.check_password(PASSWORD))
            self.assertTrue(Workspace.objects.filter(user=user).exists())

    def test_teacher_login_and_wrong_role_login(self):
        client = Client()
        response = client.post('/teacher/login/', {'username': self.student.username, 'password': PASSWORD})
        self.assertContains(response, 'Выбран другой тип аккаунта')
        self.assertNotIn('_auth_user_id', client.session)
        self.assertRedirects(client.post('/teacher/login/', {'username': 'teacher', 'password': PASSWORD}), '/teacher/')
        self.assertRedirects(self.teacher_client.get('/'), '/teacher/')

    def test_login_next_is_local_only(self):
        client = Client()
        response = client.post('/teacher/login/', {'username': 'teacher', 'password': PASSWORD, 'next': 'https://evil.test'})
        self.assertEqual(response.url, '/teacher/')
        client.post('/logout/')
        response = client.post('/login/?next=/class/', {'username': 'student', 'password': PASSWORD})
        self.assertEqual(response.url, '/class/')

    def test_role_boundaries(self):
        for path in ['/teacher/', '/teacher/calendar/', '/teacher/variants/', self.url('teacher_class', self.classroom.pk)]:
            self.assertEqual(self.student_client.get(path).status_code, 403)
        for path in ['/class/', self.url('student_class', self.classroom.pk)]:
            self.assertEqual(self.teacher_client.get(path).status_code, 403)
        self.assertIn('/teacher/login/', Client().get('/teacher/').url)

    def test_teacher_can_create_class_and_render_cabinet(self):
        response = self.teacher_client.post('/teacher/', {'name': '11 Б'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Classroom.objects.get(name='11 Б').teacher, self.teacher)
        for path in ['/teacher/', self.url('teacher_class', self.classroom.pk), self.url('student_profile', self.member.pk), '/teacher/calendar/', '/teacher/variants/', '/account/', '/notifications/']:
            self.assertEqual(self.teacher_client.get(path).status_code, 200, path)

    def test_teacher_cannot_access_other_teacher_class_or_students(self):
        self.assertEqual(self.stranger_client.get(self.url('teacher_class', self.classroom.pk)).status_code, 404)
        self.assertEqual(self.stranger_client.get(self.url('student_profile', self.member.pk)).status_code, 404)
        for route in ['invite', 'rotate_code', 'assign', 'announce']:
            self.assertEqual(self.stranger_client.post(self.url(route, self.classroom.pk), {'username': 'other'}).status_code, 404)
        self.assertEqual(self.teacher_client.get('/teacher/calendar/?class=' + str(self.foreign.pk)).status_code, 404)

    def test_invitation_requires_acceptance_and_only_recipient_can_accept(self):
        self.teacher_client.post(self.url('invite', self.classroom.pk), {'username': 'other'})
        invitation = Invitation.objects.get(classroom=self.classroom, student=self.other)
        self.assertFalse(Membership.objects.filter(classroom=self.classroom, student=self.other).exists())
        self.assertEqual(self.student_client.post(self.url('invitation_answer', invitation.pk), {'action': 'accept'}).status_code, 404)
        client = Client(); client.force_login(self.other)
        self.assertContains(client.get('/class/'), 'Приглашения')
        client.post(self.url('invitation_answer', invitation.pk), {'action': 'accept'})
        self.assertTrue(Membership.objects.filter(classroom=self.classroom, student=self.other, is_active=True).exists())
        invitation.refresh_from_db(); self.assertEqual(invitation.status, 'accepted')

    def test_code_join_is_idempotent_and_invalid_code_is_throttled(self):
        for _ in range(2):
            self.student_client.post('/class/join/', {'code': self.classroom.code.lower()})
        self.assertEqual(Membership.objects.filter(classroom=self.classroom, student=self.student).count(), 1)
        for _ in range(10):
            self.student_client.post('/class/join/', {'code': 'INVALID'})
        self.student_client.post('/class/join/', {'code': self.foreign.code})
        self.assertFalse(Membership.objects.filter(classroom=self.foreign, student=self.student).exists())

    def test_code_rotation_invalidates_old_code(self):
        old = self.classroom.code
        self.teacher_client.post(self.url('rotate_code', self.classroom.pk))
        self.classroom.refresh_from_db(); self.assertNotEqual(old, self.classroom.code)
        client = Client(); client.force_login(self.other)
        client.post('/class/join/', {'code': old})
        self.assertFalse(Membership.objects.filter(classroom=self.classroom, student=self.other).exists())

    def test_student_class_shows_progress_without_private_task_titles_or_chats(self):
        state = empty_workspace(); state['tasks'] = [{'id': 'secret', 'title': 'Секретная личная задача', 'date': timezone.localdate().isoformat(), 'done': True}]
        Workspace.objects.create(user=self.peer, state=state)
        ChatMessage.objects.create(membership=self.peer_member, sender=self.teacher, text='Личное сообщение другому ученику')
        response = self.student_client.get(self.url('student_class', self.classroom.pk))
        self.assertContains(response, 'Иван')
        self.assertNotContains(response, 'Секретная личная задача')
        self.assertNotContains(response, 'Личное сообщение другому ученику')
        self.assertEqual(self.student_client.get(self.url('student_class', self.foreign.pk)).status_code, 404)

    def test_assignment_to_all_is_delivered_only_to_current_class(self):
        response = self.teacher_client.post(self.url('assign', self.classroom.pk), {'recipient': 'all', 'title': 'Первое задание', 'instructions': 'Условие', 'due_on': timezone.localdate().isoformat()})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(AssignmentReceipt.objects.count(), 2)
        self.assertEqual(set(AssignmentReceipt.objects.values_list('membership_id', flat=True)), {self.member.pk, self.peer_member.pk})
        self.assertEqual(SchoolNotice.objects.filter(kind='assignment').count(), 2)
        self.assertContains(self.student_client.get('/'), 'Первое задание')

    def test_assignment_cannot_target_foreign_member(self):
        response = self.teacher_client.post(self.url('assign', self.classroom.pk), {'recipient': self.foreign_member.pk, 'title': 'Задание', 'instructions': 'Условие'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Assignment.objects.count(), 0)
        self.assertEqual(self.student_client.post(self.url('assign', self.classroom.pk), {}).status_code, 403)

    def test_assignment_answer_updates_activity_once_and_prevents_stale_workspace_overwrite(self):
        receipt = self.make_assignment()
        Workspace.objects.create(user=self.student)
        self.assertEqual(self.peer_client.get(self.url('assignment_detail', receipt.pk)).status_code, 404)
        self.assertEqual(self.student_client.get(self.url('assignment_detail', receipt.pk)).status_code, 200)
        for _ in range(2):
            self.student_client.post(self.url('answer', receipt.pk), {'answer': 'Моё решение', 'action': 'complete'})
        receipt.refresh_from_db(); self.assertIsNotNone(receipt.completed_at)
        self.assertEqual(receipt.answer, 'Моё решение')
        workspace = Workspace.objects.get(user=self.student)
        self.assertEqual(len(workspace.state['activity']), 1)
        self.assertEqual(progress(Membership.objects.filter(pk=self.member.pk))[0].metrics['completed'], 1)
        self.assertEqual(SchoolNotice.objects.filter(kind='answer').count(), 1)
        self.assertEqual(self.student_client.post('/api/workspace/', json.dumps({'revision': 0, 'state': empty_workspace()}), content_type='application/json').status_code, 409)
        self.student_client.post(self.url('answer', receipt.pk), {'action': 'reopen', 'answer': 'Поправлю'})
        workspace.refresh_from_db(); self.assertEqual(workspace.state['activity'], {})

    def test_assignment_answer_edits_keep_original_completion_date(self):
        receipt = self.make_assignment()
        earlier = timezone.now() - timedelta(days=2)
        receipt.completed_at = earlier; receipt.save()
        self.student_client.post(self.url('answer', receipt.pk), {'answer': 'Уточнение', 'action': 'complete'})
        receipt.refresh_from_db(); self.assertEqual(receipt.completed_at, earlier)

    def test_chat_only_between_teacher_and_own_student_and_notices_are_private(self):
        path = self.url('chat_api', self.member.pk)
        self.assertEqual(self.student_client.post(path, {'text': '<script>alert(1)</script>'}).status_code, 200)
        response = self.teacher_client.get(path).json()
        self.assertEqual(response['messages'][0]['text'], '<script>alert(1)</script>')
        self.assertFalse(response['messages'][0]['own'])
        self.assertContains(self.teacher_client.get(self.url('chat', self.member.pk)), '&lt;script&gt;alert(1)&lt;/script&gt;')
        for client in [self.peer_client, self.stranger_client]:
            self.assertEqual(client.get(path).status_code, 403)
            self.assertEqual(client.post(path, {'text': 'Чужое'}).status_code, 403)
        self.assertEqual(self.student_client.get('/class/notices/').json()['unread'], 0)
        self.assertEqual(self.teacher_client.get('/class/notices/').json()['unread'], 1)
        self.assertEqual(Client().get(path).status_code, 401)
        self.assertEqual(self.student_client.get(path+'?after=not-a-number').status_code, 400)

    def test_chat_pagination_and_empty_messages(self):
        for i in range(105):ChatMessage.objects.create(membership=self.member, sender=self.teacher, text=str(i))
        path=self.url('chat_api', self.member.pk)
        data=self.student_client.get(path).json(); self.assertEqual(len(data['messages']),100); self.assertTrue(data['has_more'])
        rest=self.student_client.get(path+'?after='+str(data['messages'][-1]['id'])).json()
        self.assertEqual(len(rest['messages']),5); self.assertFalse(rest['has_more'])
        self.assertEqual(self.student_client.post(path, {'text': '  '}).status_code,400)

    def test_read_notice_does_not_change_another_account_notice(self):
        self.student_client.post(self.url('chat_api', self.member.pk), {'text':'Вопрос'})
        item=SchoolNotice.objects.get(recipient=self.teacher)
        self.student_client.post('/class/notices/read/',{'notice':item.pk})
        item.refresh_from_db();self.assertIsNone(item.read_at)
        self.teacher_client.post('/class/notices/read/',{'membership':self.member.pk})
        item.refresh_from_db();self.assertIsNotNone(item.read_at)
        self.assertEqual(self.teacher_client.get('/class/notices/read/').status_code,405)

    def test_csrf_protects_chat_and_class_join(self):
        client=Client(enforce_csrf_checks=True);client.force_login(self.student)
        for path,data in [(self.url('chat_api',self.member.pk),{'text':'Вопрос'}),('/class/join/',{'code':self.classroom.code})]:
            self.assertEqual(client.post(path,data).status_code,403)
        client.get('/class/')
        token=client.cookies['csrftoken'].value
        self.assertEqual(client.post(self.url('chat_api',self.member.pk),{'text':'Вопрос'},HTTP_X_CSRFTOKEN=token).status_code,200)

    def test_announcement_creates_separate_private_chats(self):
        self.teacher_client.post(self.url('announce',self.classroom.pk),{'text':'Завтра консультация'})
        self.assertEqual(ChatMessage.objects.count(),2)
        self.assertEqual(SchoolNotice.objects.filter(kind='message').count(),2)
        self.assertEqual(self.student_client.get(self.url('chat_api',self.member.pk)).json()['messages'][0]['text'],'Завтра консультация')
        self.assertEqual(self.student_client.get(self.url('chat_api',self.peer_member.pk)).status_code,403)

    def test_registration_is_explicit_profile_specific_and_unique(self):
        for _ in range(2):self.student_client.post('/class/registrations/add/',{'profile':self.profile.pk})
        self.assertEqual(StudentRegistration.objects.filter(student=self.student).count(),1)
        registration=StudentRegistration.objects.get(student=self.student)
        self.assertContains(self.teacher_client.get(self.url('student_profile',self.member.pk)),'математика')
        self.assertEqual(self.peer_client.post(self.url('registration_remove',registration.pk)).status_code,404)
        self.assertEqual(self.teacher_client.post('/class/registrations/add/',{'profile':self.profile.pk}).status_code,403)
        self.student_client.post(self.url('registration_remove',registration.pk));self.assertEqual(StudentRegistration.objects.count(),0)

    def test_calendar_warns_only_for_shared_student(self):
        StudentRegistration.objects.create(student=self.student,profile=self.profile)
        StudentRegistration.objects.create(student=self.peer,profile=self.other_profile)
        data=self.calendar()['calendar_data'];self.assertEqual(len(data['2026-10-21']['events']),2)
        self.assertEqual(data['2026-10-21']['conflicts'],[])
        StudentRegistration.objects.create(student=self.student,profile=self.other_profile)
        data=self.calendar()['calendar_data'];self.assertEqual(len(data['2026-10-21']['conflicts']),1)
        self.assertEqual(data['2026-10-21']['conflicts'][0]['students'],['Анна'])

    def test_calendar_deduplicates_one_tour_for_several_pupils(self):
        StudentRegistration.objects.create(student=self.student,profile=self.profile)
        StudentRegistration.objects.create(student=self.peer,profile=self.profile)
        data=self.calendar()['calendar_data']['2026-10-20']
        self.assertEqual(len(data['events']),1);self.assertEqual(len(data['events'][0]['students']),2)
        self.assertEqual(data['conflicts'],[])

    def test_calendar_does_not_include_unregistered_profiles_or_removed_students(self):
        StudentRegistration.objects.create(student=self.student,profile=self.profile)
        self.assertEqual(len(self.calendar()['calendar_data']['2026-10-23']['events']),0)
        self.member.is_active=False;self.member.save()
        self.assertFalse(self.calendar()['calendar_has_entries'])

    def test_calendar_uses_only_known_boundary_and_handles_invalid_month(self):
        StudentRegistration.objects.create(student=self.student,profile=self.profile)
        self.event.ends_on=None;self.event.save()
        data=self.calendar()['calendar_data']
        self.assertEqual(len(data['2026-10-20']['events']),1)
        self.assertEqual(len(data['2026-10-21']['events']),0)
        self.assertTrue(data['2026-10-20']['events'][0]['incomplete'])
        self.assertTrue(calendar_context([self.classroom],{'month':'9999'})['calendar_days'])

    def test_leaving_revokes_teacher_profile_and_chat_access_without_deleting_history(self):
        ChatMessage.objects.create(membership=self.member,sender=self.teacher,text='История')
        self.student_client.post(self.url('leave',self.member.pk))
        self.assertEqual(self.teacher_client.get(self.url('student_profile',self.member.pk)).status_code,404)
        self.assertEqual(self.student_client.get(self.url('chat_api',self.member.pk)).status_code,404)
        self.assertEqual(ChatMessage.objects.count(),1)

    def test_variant_drafts_persist_and_have_owner_scope(self):
        self.teacher_client.post('/teacher/variants/',{'classroom':self.classroom.pk,'title':'Вариант 1','notes':'Комбинаторика'})
        draft=VariantDraft.objects.get()
        self.assertEqual(self.teacher_client.get(self.url('variant_edit',draft.pk)).status_code,200)
        self.assertEqual(self.stranger_client.get(self.url('variant_edit',draft.pk)).status_code,404)
        self.teacher_client.post(self.url('variant_edit',draft.pk),{'title':'Вариант 2','notes':'Геометрия'})
        draft.refresh_from_db();self.assertEqual(draft.notes,'Геометрия')

    def test_student_pages_and_theme_controls_render(self):
        for path in ['/','/class/',self.url('student_class',self.classroom.pk),self.url('chat',self.member.pk),'/notifications/','/olympiads/','/olympiads/'+str(self.olympiad.pk)+'/']:
            response=self.student_client.get(path);self.assertEqual(response.status_code,200,path)
            self.assertContains(response,'data-theme-toggle');self.assertIn('no-store',response['Cache-Control'])

    def test_registered_profiles_bootstrap_is_database_backed(self):
        StudentRegistration.objects.create(student=self.student, profile=self.profile)
        response = self.student_client.get('/')
        self.assertEqual(response.context['personal_bootstrap']['registered_profiles'],
                         [{'id': str(self.profile.pk), 'key': self.olympiad.plan_key}])
        self.assertNotIn('registered_profiles', self.teacher_client.get('/account/').context['personal_bootstrap'])
        response = self.peer_client.post('/api/workspace/', json.dumps({'revision': 0,
            'state': {**empty_workspace(), 'registered': [self.olympiad.plan_key]}}), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(StudentRegistration.objects.filter(student=self.peer).exists())

    def test_calendar_compares_distinct_profiles_of_same_olympiad(self):
        profile = OlympiadProfile.objects.create(olympiad=self.olympiad, name='физика', level=1)
        OlympiadEvent.objects.create(olympiad=self.olympiad, profile=profile, profile_name='физика',
            name='Тур физики', kind='stage', starts_on=date(2026,10,21), ends_on=date(2026,10,21),
            source_url='https://example.test/physics/tour', last_checked_at=timezone.now())
        StudentRegistration.objects.create(student=self.student, profile=self.profile)
        StudentRegistration.objects.create(student=self.student, profile=profile)
        self.assertEqual(len(self.calendar()['calendar_data']['2026-10-21']['conflicts']),1)

    def test_chat_rate_limit_covers_api_and_plain_form(self):
        path = self.url('chat_api',self.member.pk)
        for _ in range(30):
            self.assertEqual(self.student_client.post(path,{'text':'Сообщение'}).status_code,200)
        self.assertEqual(self.student_client.post(path,{'text':'Лишнее'}).status_code,429)
        response=self.student_client.post(self.url('chat',self.member.pk),{'text':'Через форму'})
        self.assertContains(response,'Слишком много сообщений')
        self.assertEqual(ChatMessage.objects.count(),30)
