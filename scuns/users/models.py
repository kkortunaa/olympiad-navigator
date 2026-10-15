from django.db import models
from django.contrib.auth.models import AbstractUser

class MyUser(AbstractUser):
    img = models.ImageField("Аватар", upload_to="media", blank=True, null=True)
    role = models.CharField('Роль', max_length=10, default='student',
                            choices=[('student', 'Ученик'), ('teacher', 'Учитель')])

    @property
    def is_teacher(self):
        return self.role == 'teacher'


# Create your models here.
