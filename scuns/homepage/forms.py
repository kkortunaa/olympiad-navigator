from django import forms
from django.forms import ModelForm
from .models import User


class UserForm(ModelForm):
    class Meta:
        model = User
        fields = [
            'surname',
            'name',
            'name2',
            'phone_num',
            'reg_num',
            'email',
            'avg_score',
            'city',
            'participation_in_olympiads',
            'avg_oge_score',
            'avg_score_of_exam',
        ]

    def clean_name(self):
        name = self.cleaned_data["name"]
        return name.split()[0]
