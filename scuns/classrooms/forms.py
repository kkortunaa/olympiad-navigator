from django import forms
from django.contrib.auth import get_user_model

from .models import Assignment, Classroom, VariantDraft


class ClassroomForm(forms.ModelForm):
    class Meta:
        model = Classroom
        fields = ['name']
        widgets = {'name': forms.TextInput(attrs={'placeholder': 'Например, 10 А · олимпиадная группа'})}


class InviteForm(forms.Form):
    username = forms.CharField(label='Логин ученика', max_length=150)

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        student = get_user_model().objects.filter(username=username, role='student', is_active=True).first()
        if not student:
            raise forms.ValidationError('Аккаунт ученика с таким логином не найден. Попросите ученика зарегистрироваться.')
        self.student = student
        return username


class JoinForm(forms.Form):
    code = forms.CharField(label='Код класса', max_length=20, widget=forms.TextInput(attrs={
        'placeholder': 'Код от преподавателя', 'autocomplete': 'off', 'spellcheck': 'false'}))

    def clean_code(self):
        return self.cleaned_data['code'].strip().upper()


class AssignmentForm(forms.ModelForm):
    recipient = forms.ChoiceField(label='Кому отправить')

    class Meta:
        model = Assignment
        fields = ['title', 'instructions', 'due_on']
        widgets = {'instructions': forms.Textarea(attrs={'rows': 5}),
                   'due_on': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')}

    def __init__(self, *args, classroom, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['recipient'].choices = [('all', 'Всем текущим ученикам класса')] + [
            (str(member.pk), member.student.get_full_name() or member.student.username)
            for member in classroom.memberships.filter(is_active=True).select_related('student')]
        self.order_fields(['recipient', 'title', 'instructions', 'due_on'])


class AnswerForm(forms.Form):
    answer = forms.CharField(label='Ответ или ссылка на решение', max_length=4000, required=False,
                             widget=forms.Textarea(attrs={'rows': 3}))


class MessageForm(forms.Form):
    text = forms.CharField(label='Сообщение', max_length=4000, widget=forms.Textarea(attrs={
        'rows': 3, 'placeholder': 'Напишите преподавателю или ученику…'}))


class VariantForm(forms.ModelForm):
    class Meta:
        model = VariantDraft
        fields = ['title', 'notes']
        widgets = {'notes': forms.Textarea(attrs={'rows': 7, 'placeholder': 'Темы, уровень сложности, структура заданий…'})}
