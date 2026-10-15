from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django import forms


class SignupForm(UserCreationForm):
    first_name = forms.CharField(label='Имя и фамилия', max_length=150, required=False)
    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ('username', 'first_name')


class RoleAuthenticationForm(AuthenticationForm):
    def __init__(self, *args, role='student', **kwargs):
        self.role = role
        super().__init__(*args, **kwargs)

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if user.role != self.role:
            raise forms.ValidationError('Выбран другой тип аккаунта. Используйте вход для учителя или ученика.', code='role')


class ProfileForm(forms.ModelForm):
    first_name = forms.CharField(label='Как к тебе обращаться', max_length=150, required=False)

    class Meta:
        model = get_user_model()
        fields = ('first_name',)
