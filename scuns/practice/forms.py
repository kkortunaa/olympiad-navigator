from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from classrooms.models import Classroom, Membership, VariantDraft
from .grading import validate_spec
from .models import PaperAssignment, Question


class QuestionForm(forms.ModelForm):
    correct_answers = forms.CharField(label='Правильные ответы', widget=forms.Textarea(attrs={'rows': 3}),
        help_text='Каждый допустимый ответ с новой строки. Для выбора укажите номер, для нескольких ответов — например 1,3.')
    options_text = forms.CharField(label='Варианты для выбора', required=False, widget=forms.Textarea(attrs={'rows': 4}),
        help_text='Каждый вариант с новой строки, от 2 до 12. Номера 1, 2, 3… сайт добавит сам.')

    class Meta:
        model = Question
        fields = ['title', 'subject', 'topic', 'difficulty', 'statement', 'image', 'answer_type', 'rule',
                  'tolerance', 'solution', 'source']
        widgets = {'statement': forms.Textarea(attrs={'rows': 8}), 'solution': forms.Textarea(attrs={'rows': 6}),
                   'image': forms.ClearableFileInput(attrs={'accept': 'image/png,image/jpeg,image/webp'}),
                   'tolerance': forms.NumberInput(attrs={'step': '0.00000001', 'min': '0'})}
        help_texts = {
            'statement': 'Текст и математические символы. HTML не исполняется. Не добавляйте правильный ответ в условие.',
            'subject': 'Например: математика, русский язык, история, информатика.',
            'image': 'PNG, JPEG или WebP, до 4 МБ. Изображение должно содержать только условие.',
            'tolerance': 'Только для числового ответа. 0 означает точное равенство чисел.',
            'solution': 'Разбор откроется ученику только согласно настройкам выданного варианта.',
            'source': 'Например: «Авторское задание» или название разрешённого источника и год.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and not self.is_bound:
            self.fields['correct_answers'].initial = '\n'.join(self.instance.answers)
            self.fields['options_text'].initial = '\n'.join(self.instance.options)
        self.order_fields(['title', 'subject', 'topic', 'difficulty', 'statement', 'image', 'answer_type',
                           'options_text', 'correct_answers', 'rule', 'tolerance', 'solution', 'source'])

    def clean_image(self):
        image = self.cleaned_data.get('image')
        if image and hasattr(image, 'content_type'):
            if image.size > 4 * 1024 * 1024 or image.image.format not in ('PNG', 'JPEG', 'WEBP'):
                raise ValidationError('Используйте PNG, JPEG или WebP размером до 4 МБ.')
            if image.image.width * image.image.height > 20_000_000:
                raise ValidationError('Изображение слишком большое: максимум 20 миллионов пикселей.')
        return image

    def clean(self):
        data = super().clean()
        answers = [x.strip() for x in data.get('correct_answers', '').splitlines() if x.strip()]
        options = [x.strip() for x in data.get('options_text', '').splitlines() if x.strip()]
        self.instance.answers = list(dict.fromkeys(answers))
        self.instance.options = options if data.get('answer_type') in ('choice', 'multiple') else []
        if all(k in data for k in ('answer_type', 'rule', 'tolerance')):
            validate_spec(data['answer_type'], data['rule'], self.instance.answers, self.instance.options, data['tolerance'])
        return data


class PaperForm(forms.ModelForm):
    class Meta:
        model = VariantDraft
        fields = ['classroom', 'title', 'notes']
        labels = {'classroom': 'Класс по умолчанию', 'notes': 'Инструкция ученикам'}
        widgets = {'notes': forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, teacher, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['classroom'].queryset = Classroom.objects.filter(teacher=teacher)
        # Older draft editors sent title/notes only. Preserve their existing classroom.
        if self.instance.pk and self.is_bound and not self.data.get('classroom'):
            self.data = self.data.copy()
            self.data['classroom'] = self.instance.classroom_id


class ItemForm(forms.Form):
    question = forms.ModelChoiceField(label='Задание из моего банка', queryset=Question.objects.none())
    points = forms.IntegerField(label='Баллов за верный ответ', min_value=1, max_value=100, initial=1)

    def __init__(self, *args, teacher, variant, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['question'].queryset = Question.objects.filter(author=teacher, archived=False).exclude(variant_items__variant=variant)


class GivePaperForm(forms.ModelForm):
    audience = forms.ChoiceField(label='Кому выдать', choices=[('all', 'Всему текущему классу'), ('selected', 'Выбранным ученикам')])
    students = forms.ModelMultipleChoiceField(label='Выбранные ученики', queryset=Membership.objects.none(), required=False,
                                              widget=forms.CheckboxSelectMultiple)

    class Meta:
        model = PaperAssignment
        fields = ['classroom', 'due_at', 'max_attempts', 'feedback_mode', 'show_solutions']
        labels = {'classroom': 'Класс'}
        widgets = {'due_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M')}
        help_texts = {'due_at': 'Московское время. После срока работа становится доступна только для чтения.',
                      'max_attempts': 'От 1 до 10. Все попытки сохраняются; в сводке учитывается лучшая.',
                      'show_solutions': 'ИИ-разбор подчиняется этому же разрешению.'}

    def __init__(self, *args, teacher, classroom=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['classroom'].queryset = Classroom.objects.filter(teacher=teacher)
        self.fields['due_at'].input_formats = ['%Y-%m-%dT%H:%M']
        self.fields['classroom'].widget = forms.HiddenInput()
        class_id = self.data.get('classroom') if self.is_bound else (classroom.pk if classroom else None)
        if str(class_id).isascii() and str(class_id).isdigit() and len(str(class_id)) < 19:
            self.fields['students'].queryset = Membership.objects.filter(classroom_id=class_id, classroom__teacher=teacher,
                                                                        is_active=True).select_related('student')
        self.fields['students'].label_from_instance = lambda m: m.student.get_full_name() or m.student.username
        self.order_fields(['classroom', 'audience', 'students', 'due_at', 'max_attempts', 'feedback_mode', 'show_solutions'])

    def clean(self):
        data = super().clean()
        if data.get('due_at') and data['due_at'] <= timezone.now():
            self.add_error('due_at', 'Срок должен быть в будущем.')
        if data.get('feedback_mode') == 'deadline' and not data.get('due_at'):
            self.add_error('due_at', 'Для проверки после срока укажите дату и время.')
        if data.get('audience') == 'selected' and not data.get('students'):
            self.add_error('students', 'Выберите хотя бы одного ученика.')
        return data


class AnswerSheetForm(forms.Form):
    revision = forms.IntegerField(min_value=0, widget=forms.HiddenInput)

    def __init__(self, *args, questions, saved, revision=0, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['revision'].initial = revision
        self.questions = questions
        for question in questions:
            data, name = question.data, f'answer_{question.pk}'
            choices = [(str(i), f'{i}. {label}') for i, label in enumerate(data['options'], 1)]
            initial = saved.get(question.pk, '')
            if data['answer_type'] == 'choice':
                field = forms.ChoiceField(choices=[('', 'Выберите ответ')] + choices, required=False, initial=initial)
            elif data['answer_type'] == 'multiple':
                field = forms.MultipleChoiceField(choices=choices, required=False, widget=forms.CheckboxSelectMultiple,
                                                  initial=initial.split(',') if initial else [])
            else:
                field = forms.CharField(max_length=2000, required=False, initial=initial,
                    widget=forms.TextInput(attrs={'autocomplete': 'off', **({'inputmode': 'decimal'} if data['answer_type'] == 'number' else {})}))
            field.label = 'Ваш ответ'
            self.fields[name] = field

    def values_by_question(self):
        result = {}
        for question in self.questions:
            value = self.cleaned_data[f'answer_{question.pk}']
            result[question.pk] = ','.join(sorted(value, key=int)) if isinstance(value, list) else value
        return result
