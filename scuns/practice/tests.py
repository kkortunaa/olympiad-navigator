import json
from datetime import timedelta
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from classrooms.models import Classroom, Membership, SchoolNotice, VariantDraft
from planner.models import Workspace
from .forms import GivePaperForm, QuestionForm
from .grading import is_correct, number, validate_spec
from .models import AIExplanation, AIQuota, Attempt, AttemptAnswer, PaperAssignment, Question, Recipient, VariantItem
from .services import give_paper, start_attempt


class GradingTests(SimpleTestCase):
    def spec(self, **changes):
        return {'answer_type': 'short', 'rule': 'exact', 'answers': ['Точный ответ'], 'tolerance': '0', **changes}

    def test_exact_and_normalized_text_are_distinct(self):
        self.assertTrue(is_correct(self.spec(), '  Точный ответ '))
        self.assertFalse(is_correct(self.spec(), 'точный ответ'))
        self.assertTrue(is_correct(self.spec(rule='text'), ' ТОЧНЫЙ   ответ\n'))

    def test_numeric_fraction_decimal_comma_and_tolerance(self):
        data = self.spec(answer_type='number', rule='number', answers=['0.5'])
        for value in ['1/2', '0,5', '5e-1', '2/4']:
            self.assertTrue(is_correct(data, value), value)
        self.assertFalse(is_correct(data, '0.5001'))
        self.assertTrue(is_correct({**data, 'tolerance': '0.001'}, '0.5001'))
        for value in ['nan', 'inf', '1/0', '__import__("os")', '9e999999', '0.5 or 1', '']:
            self.assertFalse(is_correct(data, value), value)

    def test_multiple_choice_order_and_validation(self):
        data = self.spec(answer_type='multiple', rule='set', answers=['1,3'])
        self.assertTrue(is_correct(data, '3; 1'))
        for value in ['1', '1,3,3', '1,2,3', '1,3,x']:
            self.assertFalse(is_correct(data, value))
        with self.assertRaises(ValidationError):
            validate_spec('choice', 'exact', ['3'], ['A', 'B'], 0)
        with self.assertRaises(ValidationError):
            validate_spec('number', 'exact', ['1'], [], 0)
        with self.assertRaises(ValueError):
            number('1e99')


@override_settings(GROQ_API_KEY='')
class PracticeFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.teacher = User.objects.create_user('practice-teacher', role='teacher', first_name='TeacherPrivateName')
        cls.other_teacher = User.objects.create_user('foreign-teacher', role='teacher')
        cls.student = User.objects.create_user('practice-student', first_name='StudentPrivateName', email='private@example.test')
        cls.peer = User.objects.create_user('practice-peer')
        cls.other = User.objects.create_user('outsider')
        cls.classroom = Classroom.objects.create(teacher=cls.teacher, name='10 А')
        cls.foreign = Classroom.objects.create(teacher=cls.other_teacher, name='Другой класс')
        cls.member = Membership.objects.create(classroom=cls.classroom, student=cls.student)
        cls.peer_member = Membership.objects.create(classroom=cls.classroom, student=cls.peer)
        cls.foreign_member = Membership.objects.create(classroom=cls.foreign, student=cls.other)
        cls.question = Question.objects.create(author=cls.teacher, title='Авторское учебное задание', subject='математика',
            topic='Дроби', statement='Вычислите половину единицы.', answer_type='number', rule='number', answers=['0.5'],
            solution='Разделим единицу на два. Получим половину.', source='Авторское учебное задание')
        cls.variant = VariantDraft.objects.create(classroom=cls.classroom, title='Проверочная работа', notes='Решите самостоятельно.')
        VariantItem.objects.create(variant=cls.variant, question=cls.question, position=1, points=2)

    def setUp(self):
        self.teacher_client = Client(); self.teacher_client.force_login(self.teacher)
        self.student_client = Client(); self.student_client.force_login(self.student)
        self.peer_client = Client(); self.peer_client.force_login(self.peer)
        self.foreign_client = Client(); self.foreign_client.force_login(self.other_teacher)

    def url(self, name, *args):
        return reverse('practice:' + name, args=args)

    def delivery(self, **changes):
        data = {'classroom': self.classroom.pk, 'audience': 'all', 'max_attempts': 1,
                'feedback_mode': 'finish', 'show_solutions': 'on', **changes}
        form = GivePaperForm(data, teacher=self.teacher)
        self.assertTrue(form.is_valid(), form.errors.as_json())
        return give_paper(self.variant, form)

    def begin(self, delivery=None):
        delivery = delivery or self.delivery()
        recipient = delivery.recipients.get(membership=self.member)
        attempt = start_attempt(recipient)
        return delivery, recipient, attempt, delivery.questions.get()

    def save(self, attempt, question, value='1/2', revision=0, action='save', client=None):
        return (client or self.student_client).post(self.url('save', attempt.pk), {
            'revision': revision, f'answer_{question.pk}': value, 'action': action}, HTTP_ACCEPT='application/json')


class PracticeTests(PracticeFixture):
    def test_complete_teacher_student_workflow_through_forms(self):
        response = self.teacher_client.post(self.url('question_new'), {
            'title': 'Слово', 'statement': 'Напишите слово «Москва».', 'subject': 'русский язык', 'topic': 'Лексика',
            'difficulty': 'easy', 'answer_type': 'short', 'rule': 'text', 'tolerance': '0',
            'correct_answers': 'Москва\nМОСКВА', 'solution': 'Используйте название города.', 'source': 'Авторское'})
        self.assertEqual(response.status_code, 302)
        question = Question.objects.get(title='Слово')
        self.teacher_client.post('/teacher/variants/', {'classroom': self.classroom.pk, 'title': 'Русский язык', 'notes': 'Инструкция'})
        paper = VariantDraft.objects.get(title='Русский язык')
        self.teacher_client.post(self.url('paper_item', paper.pk), {'action': 'add', 'question': question.pk, 'points': 3})
        response = self.teacher_client.post(self.url('give', paper.pk), {'classroom': self.classroom.pk,
            'audience': 'selected', 'students': [self.member.pk], 'max_attempts': 2, 'feedback_mode': 'finish', 'show_solutions': 'on'})
        self.assertEqual(response.status_code, 302)
        delivery = PaperAssignment.objects.get(title='Русский язык')
        self.assertEqual(delivery.recipients.count(), 1)
        recipient = delivery.recipients.get()
        self.assertEqual(SchoolNotice.objects.filter(kind='variant', recipient=self.student).count(), 1)
        self.assertContains(self.student_client.get('/'), 'Русский язык')
        self.assertContains(self.student_client.get(self.url('student_works')), 'Русский язык')
        response = self.student_client.post(self.url('start', recipient.pk))
        self.assertEqual(response.status_code, 302)
        attempt = recipient.attempts.get(); assigned = delivery.questions.get()
        self.assertEqual(self.save(attempt, assigned, 'москва', action='finish').status_code, 200)
        answer = attempt.answers.get(); self.assertTrue(answer.is_correct)
        self.assertContains(self.student_client.get(self.url('attempt', attempt.pk)), 'Используйте название города.')
        self.assertContains(self.teacher_client.get(self.url('results', delivery.pk)), '100%')
        self.assertContains(self.student_client.get(self.url('statistics')), 'Лексика')

    def test_draft_compatibility_builder_order_and_ownership(self):
        self.assertEqual(self.teacher_client.post(reverse('classrooms:variant_edit', args=[self.variant.pk]),
            {'title': 'Новое имя', 'notes': 'Новый план'}).status_code, 302)
        self.variant.refresh_from_db(); self.assertEqual(self.variant.notes, 'Новый план')
        q2 = Question.objects.create(author=self.teacher, title='Второе', statement='Текст', subject='история',
            topic='Даты', answers=['ответ'], rule='text')
        self.teacher_client.post(self.url('paper_item', self.variant.pk), {'action': 'add', 'question': q2.pk, 'points': 1})
        item = self.variant.items.get(question=q2)
        self.teacher_client.post(self.url('paper_item', self.variant.pk), {'action': 'up', 'item': item.pk})
        self.assertEqual(list(self.variant.items.values_list('question_id', flat=True)), [q2.pk, self.question.pk])
        self.assertEqual(self.foreign_client.post(self.url('paper_item', self.variant.pk), {'action': 'remove', 'item': item.pk}).status_code, 404)

    def test_autosave_two_devices_and_stale_revision(self):
        delivery, recipient, attempt, question = self.begin()
        self.assertEqual(self.save(attempt, question).json()['revision'], 1)
        device = Client(); device.force_login(self.student)
        self.assertContains(device.get(self.url('attempt', attempt.pk)), '1/2')
        self.assertEqual(self.save(attempt, question, '99', revision=0, client=device).status_code, 409)
        self.assertEqual(attempt.answers.get().value, '1/2')
        self.assertIsNone(attempt.answers.get().is_correct)

    def test_finish_immutability_limit_idempotence_and_activity(self):
        delivery, recipient, attempt, question = self.begin()
        self.save(attempt, question, action='finish')
        self.assertEqual(self.save(attempt, question, '9', action='finish').status_code, 200)
        self.assertEqual(self.save(attempt, question, '9', revision=1).status_code, 409)
        self.assertEqual(attempt.answers.get().value, '1/2')
        self.student_client.post(self.url('start', recipient.pk))
        self.assertEqual(recipient.attempts.count(), 1)
        self.assertEqual(len(Workspace.objects.get(user=self.student).state['activity']), 1)
        self.assertEqual(SchoolNotice.objects.filter(kind='variant_result').count(), 1)

    def test_assignment_snapshot_survives_edits_to_bank_and_draft(self):
        delivery, recipient, attempt, question = self.begin()
        self.question.answers = ['99']; self.question.statement = 'Изменённое условие'; self.question.save()
        self.variant.items.all().delete()
        self.assertEqual(self.save(attempt, question, action='finish').status_code, 200)
        self.assertTrue(attempt.answers.get().is_correct)
        self.assertContains(self.student_client.get(self.url('attempt', attempt.pk)), 'Вычислите половину единицы.')
        self.assertEqual(delivery.questions.count(), 1)

    def test_reference_and_solution_never_leak_before_allowed_moment(self):
        self.question.answers = ['SECRET-REFERENCE']; self.question.answer_type = 'short'; self.question.rule = 'exact'
        self.question.solution = 'SECRET-TEACHER-SOLUTION'; self.question.save()
        delivery, recipient, attempt, question = self.begin()
        response = self.student_client.get(self.url('attempt', attempt.pk))
        self.assertNotContains(response, 'SECRET-REFERENCE'); self.assertNotContains(response, 'SECRET-TEACHER-SOLUTION')
        self.assertNotContains(response, 'data-explain-url')
        self.assertEqual(self.student_client.post(self.url('explain', attempt.pk, question.pk)).status_code, 403)
        response = self.save(attempt, question, value='other')
        self.assertNotIn('is_correct', response.json()); self.assertNotIn('SECRET', response.content.decode())
        self.assertEqual(self.save(attempt, question, value='other', revision=1, action=f'check:{question.pk}').status_code, 400)
        self.save(attempt, question, value='other', revision=1, action='finish')
        response = self.student_client.get(self.url('attempt', attempt.pk))
        self.assertContains(response, 'SECRET-REFERENCE'); self.assertContains(response, 'SECRET-TEACHER-SOLUTION')

    def test_immediate_feedback_resets_after_edit(self):
        delivery, recipient, attempt, question = self.begin(self.delivery(feedback_mode='immediate'))
        self.assertEqual(self.save(attempt, question, action=f'check:{question.pk}').status_code, 200)
        self.assertTrue(attempt.answers.get().is_correct)
        self.assertContains(self.student_client.get(self.url('attempt', attempt.pk)), 'Разделим единицу')
        self.save(attempt, question, '9', revision=1)
        self.assertIsNone(attempt.answers.get().is_correct)
        self.assertNotContains(self.student_client.get(self.url('attempt', attempt.pk)), 'Разделим единицу')

    def test_deferred_feedback_deadline_and_saved_only_expiry(self):
        delivery, recipient, attempt, question = self.begin(self.delivery(feedback_mode='deadline',
            due_at=(timezone.localtime() + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M')))
        self.save(attempt, question)
        delivery.due_at = timezone.now() - timedelta(seconds=1); delivery.save()
        self.assertEqual(self.save(attempt, question, '9', revision=1, action='finish').status_code, 409)
        self.student_client.get(self.url('work', recipient.pk))
        attempt.refresh_from_db(); self.assertEqual(attempt.status, 'submitted')
        self.assertTrue(attempt.answers.get().is_correct); self.assertEqual(attempt.answers.get().value, '1/2')
        self.assertContains(self.student_client.get(self.url('attempt', attempt.pk)), 'Разделим единицу')

    def test_finished_early_deadline_mode_hides_stats_and_solutions(self):
        delivery, recipient, attempt, question = self.begin(self.delivery(feedback_mode='deadline',
            due_at=(timezone.localtime() + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M')))
        self.save(attempt, question, 'wrong', action='finish')
        response = self.student_client.get(self.url('attempt', attempt.pk))
        self.assertNotContains(response, 'Неверно'); self.assertNotContains(response, 'Разделим единицу')
        self.assertNotContains(self.student_client.get(self.url('statistics')), 'Дроби')
        self.assertContains(self.teacher_client.get(self.url('results', delivery.pk)), 'Дроби')

    def test_hidden_solutions_also_block_ai_but_allow_verdict(self):
        delivery, recipient, attempt, question = self.begin(self.delivery(show_solutions=''))
        self.save(attempt, question, action='finish')
        response = self.student_client.get(self.url('attempt', attempt.pk))
        self.assertContains(response, 'Верно'); self.assertNotContains(response, 'Разделим единицу')
        self.assertEqual(self.student_client.post(self.url('explain', attempt.pk, question.pk)).status_code, 403)

    def test_access_is_scoped_to_student_or_own_teacher_and_active_membership(self):
        delivery, recipient, attempt, question = self.begin()
        for client in [self.peer_client, self.foreign_client]:
            self.assertEqual(client.get(self.url('attempt', attempt.pk)).status_code, 404)
        for route in [self.url('work', recipient.pk), self.url('attempt', attempt.pk)]:
            self.assertEqual(self.peer_client.get(route).status_code, 404)
        self.assertEqual(self.save(attempt, question, client=self.peer_client).status_code, 404)
        self.assertEqual(self.peer_client.post(self.url('explain', attempt.pk, question.pk)).status_code, 404)
        self.assertEqual(self.foreign_client.get(self.url('results', delivery.pk)).status_code, 404)
        self.assertEqual(self.teacher_client.get(self.url('attempt', attempt.pk)).status_code, 200)
        self.assertEqual(self.save(attempt, question, client=self.teacher_client).status_code, 403)
        self.member.is_active = False; self.member.save()
        self.assertEqual(self.student_client.get(self.url('attempt', attempt.pk)).status_code, 404)
        self.assertEqual(self.teacher_client.get(self.url('attempt', attempt.pk)).status_code, 404)

    def test_foreign_recipients_class_and_empty_variant_rejected(self):
        form = GivePaperForm({'classroom': self.classroom.pk, 'audience': 'selected', 'students': [self.foreign_member.pk],
                             'max_attempts': 1, 'feedback_mode': 'finish'}, teacher=self.teacher)
        self.assertFalse(form.is_valid())
        form = GivePaperForm({'classroom': self.foreign.pk, 'audience': 'all', 'max_attempts': 1, 'feedback_mode': 'finish'}, teacher=self.teacher)
        self.assertFalse(form.is_valid())
        self.variant.items.all().delete()
        with self.assertRaises(ValidationError):
            self.delivery()
        self.assertEqual(PaperAssignment.objects.count(), 0)

    def test_formats_in_student_form_and_weighted_statistics(self):
        multi = Question.objects.create(author=self.teacher, title='Выбор', statement='Выберите два значения.', subject='информатика',
            topic='Множества', answer_type='multiple', rule='set', answers=['1,3'], options=['Один', 'Два', 'Три'])
        VariantItem.objects.create(variant=self.variant, question=multi, position=2, points=3)
        delivery = self.delivery(max_attempts=2)
        recipient = delivery.recipients.get(membership=self.member); attempt = start_attempt(recipient)
        numeric, question = list(delivery.questions.all())
        data = {'revision': 0, 'action': 'finish', f'answer_{numeric.pk}': '9', f'answer_{question.pk}': ['3', '1']}
        self.assertEqual(self.student_client.post(self.url('save', attempt.pk), data, HTTP_ACCEPT='application/json').status_code, 200)
        response = self.student_client.get(self.url('attempt', attempt.pk))
        self.assertContains(response, '3 / 5'); self.assertEqual(attempt.answers.filter(is_correct=True).count(), 1)
        self.assertContains(self.student_client.get(self.url('statistics')), 'Дроби')
        self.assertContains(self.teacher_client.get(self.url('results', delivery.pk)), '60%')

    def test_html_escaping_and_csrf(self):
        self.question.statement = '<script>alert(1)</script>'; self.question.save()
        delivery, recipient, attempt, question = self.begin()
        response = self.student_client.get(self.url('attempt', attempt.pk))
        self.assertContains(response, '&lt;script&gt;alert(1)&lt;/script&gt;')
        self.assertNotContains(response, '<script>alert(1)</script>')
        strict = Client(enforce_csrf_checks=True); strict.force_login(self.student)
        self.assertEqual(strict.post(self.url('save', attempt.pk), {}).status_code, 403)
        self.assertEqual(strict.post(self.url('explain', attempt.pk, question.pk)).status_code, 403)
        self.assertEqual(Client().get(self.url('student_works')).status_code, 302)

    def test_pages_render_in_existing_site_and_private_cache(self):
        delivery, recipient, attempt, question = self.begin()
        for client, routes in [(self.teacher_client, [self.url('questions'), self.url('question_new'),
            self.url('question_edit', self.question.pk), '/teacher/variants/', reverse('classrooms:variant_edit', args=[self.variant.pk]),
            self.url('give', self.variant.pk), self.url('results', delivery.pk)]),
            (self.student_client, [self.url('student_works'), self.url('work', recipient.pk), self.url('attempt', attempt.pk), self.url('statistics')])]:
            for route in routes:
                response = client.get(route)
                self.assertEqual(response.status_code, 200, route)
                self.assertContains(response, 'data-theme-toggle')
                self.assertIn('no-store', response['Cache-Control'])

    def test_repeated_start_reuses_open_attempt_and_new_attempt_retains_history(self):
        delivery, recipient, attempt, question = self.begin(self.delivery(max_attempts=2))
        self.assertEqual(start_attempt(recipient).pk, attempt.pk)
        self.save(attempt, question, action='finish')
        second = start_attempt(recipient)
        self.assertNotEqual(second.pk, attempt.pk)
        self.save(second, question, '9', action='finish')
        self.assertEqual(recipient.attempts.count(), 2)
        self.assertContains(self.teacher_client.get(self.url('results', delivery.pk)), '100%')
        self.assertContains(self.student_client.get(self.url('statistics')), '50%')
        self.assertEqual(len(Workspace.objects.get(user=self.student).state['activity']), 1)

    def test_question_form_rejects_invalid_reference_and_foreign_bank_access(self):
        data = {'title': 'Выбор', 'statement': 'Условие', 'subject': 'история', 'topic': 'Даты', 'difficulty': 'easy',
                'answer_type': 'choice', 'rule': 'exact', 'tolerance': 0, 'correct_answers': '9', 'options_text': 'Один\nДва'}
        form = QuestionForm(data, instance=Question(author=self.teacher))
        self.assertFalse(form.is_valid())
        self.assertEqual(self.foreign_client.get(self.url('question_edit', self.question.pk)).status_code, 404)
        self.assertEqual(self.student_client.get(self.url('questions')).status_code, 403)
        self.assertEqual(self.foreign_client.post(self.url('give', self.variant.pk), {}).status_code, 404)

    def test_malformed_control_ids_and_oversized_answers_are_rejected(self):
        delivery, recipient, attempt, question = self.begin(self.delivery(feedback_mode='immediate'))
        self.assertEqual(self.save(attempt, question, action='check:²').status_code, 400)
        self.assertEqual(self.save(attempt, question, value='x' * 2001).status_code, 400)
        self.assertEqual(self.teacher_client.post(self.url('paper_item', self.variant.pk),
            {'action': 'remove', 'item': '²'}).status_code, 404)
        self.assertEqual(self.teacher_client.get(self.url('give', self.variant.pk) + '?classroom=²').status_code, 404)


class FakeHTTPResponse:
    def __init__(self, content='Шаг 1. Разделим единицу на два.\nПроверка: половина + половина = 1.\nОтвет: 1/2', finish='stop'):
        self.content, self.finish = content, finish

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, size):
        return json.dumps({'choices': [{'message': {'content': self.content}, 'finish_reason': self.finish}]}).encode()


@override_settings(GROQ_API_KEY='server-secret-never-browser', PRACTICE_AI_COOLDOWN=15)
class AITests(PracticeFixture):
    def ready(self):
        delivery, recipient, attempt, question = self.begin()
        self.save(attempt, question, action='finish')
        return attempt, question

    @override_settings(GROQ_API_KEY='')
    @patch('practice.ai.build_opener')
    def test_missing_key_falls_back_without_network_or_budget(self, opener):
        attempt, question = self.ready()
        response = self.student_client.post(self.url('explain', attempt.pk, question.pk))
        self.assertEqual(response.status_code, 200); self.assertFalse(response.json()['ai'])
        self.assertEqual(response.json()['text'], self.question.solution)
        opener.assert_not_called(); self.assertEqual(AIQuota.objects.count(), 0)
        question.data['solution'] = ''; question.save()
        self.assertEqual(self.student_client.post(self.url('explain', attempt.pk, question.pk)).status_code, 503)

    @patch('practice.ai.build_opener')
    def test_api_payload_privacy_correct_answer_and_shared_cache(self, opener):
        opener.return_value.open.return_value = FakeHTTPResponse()
        attempt, question = self.ready()
        url = self.url('explain', attempt.pk, question.pk)
        response = self.student_client.post(url)
        self.assertEqual(response.status_code, 200); self.assertTrue(response.json()['ai'])
        request = opener.return_value.open.call_args.args[0]
        payload = json.loads(request.data)
        context = json.loads(payload['messages'][1]['content'])
        self.assertEqual(set(context), {'statement', 'subject', 'topic', 'answers', 'options', 'solution'})
        for private in ['StudentPrivateName', 'private@example.test', 'practice-student', 'server-secret-never-browser']:
            self.assertNotIn(private, request.data.decode())
            self.assertNotIn(private, response.content.decode())
        self.assertEqual(request.get_header('Authorization'), 'Bearer server-secret-never-browser')
        self.assertEqual(AIQuota.objects.get(scope='global').used, 1)
        self.assertTrue(self.student_client.post(url).json()['cached'])
        self.assertEqual(opener.return_value.open.call_count, 1)

    @patch('practice.ai.build_opener')
    def test_wrong_or_truncated_ai_result_is_not_shown(self, opener):
        attempt, question = self.ready()
        for content, finish in [('Ошибочный разбор.\nОтвет: 99', 'stop'), ('Обрезанный разбор.\nОтвет: 1/2', 'length')]:
            AIQuota.objects.all().delete()
            opener.return_value.open.return_value = FakeHTTPResponse(content=content, finish=finish)
            data = self.student_client.post(self.url('explain', attempt.pk, question.pk)).json()
            self.assertFalse(data['ai']); self.assertEqual(data['text'], self.question.solution)
            self.assertEqual(AIExplanation.objects.count(), 0)

    @patch('practice.ai.build_opener')
    def test_provider_errors_and_timeout_keep_teacher_solution(self, opener):
        attempt, question = self.ready()
        for error in [HTTPError('https://api.groq.com', 429, 'quota', {}, None),
                      HTTPError('https://api.groq.com', 401, 'invalid', {}, None), URLError('offline'), TimeoutError()]:
            AIQuota.objects.all().delete()
            opener.return_value.open.side_effect = error
            response = self.student_client.post(self.url('explain', attempt.pk, question.pk))
            self.assertEqual(response.status_code, 200); self.assertFalse(response.json()['ai'])
            self.assertEqual(response.json()['text'], self.question.solution)

    @override_settings(PRACTICE_AI_GLOBAL_DAILY_LIMIT=0)
    @patch('practice.ai.build_opener')
    def test_global_budget_blocks_before_network(self, opener):
        attempt, question = self.ready()
        self.student_client.post(self.url('explain', attempt.pk, question.pk))
        opener.assert_not_called(); self.assertEqual(AIQuota.objects.count(), 0)

    @override_settings(PRACTICE_AI_USER_DAILY_LIMIT=0)
    @patch('practice.ai.build_opener')
    def test_user_budget_rolls_back_global_reservation(self, opener):
        attempt, question = self.ready()
        self.student_client.post(self.url('explain', attempt.pk, question.pk))
        self.assertEqual(AIQuota.objects.count(), 0); opener.assert_not_called()

    @patch('practice.ai.build_opener')
    def test_cooldown_blocks_a_second_uncached_request_and_counts_failed_call(self, opener):
        opener.return_value.open.side_effect = URLError('offline')
        attempt, question = self.ready()
        url = self.url('explain', attempt.pk, question.pk)
        self.student_client.post(url)
        second = self.student_client.post(url).json()
        self.assertIn('слишком часто', second['message'])
        self.assertEqual(opener.return_value.open.call_count, 1)
        self.assertEqual(AIQuota.objects.get(scope='global').used, 1)
        self.assertEqual(AIQuota.objects.get(scope=f'user:{self.student.pk}').used, 1)

    @patch('practice.ai.build_opener')
    def test_malformed_response_does_not_replace_teacher_solution(self, opener):
        response = FakeHTTPResponse()
        response.read = lambda size: b'not-json'
        opener.return_value.open.return_value = response
        attempt, question = self.ready()
        data = self.student_client.post(self.url('explain', attempt.pk, question.pk)).json()
        self.assertFalse(data['ai']); self.assertEqual(data['text'], self.question.solution)
        self.assertEqual(AIExplanation.objects.count(), 0)
