import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone


def invite_code():
    return ''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(10))


class Classroom(models.Model):
    teacher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='teaching_classes')
    name = models.CharField('Название класса', max_length=100)
    code = models.CharField(max_length=20, unique=True, default=invite_code)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name', 'pk']

    def __str__(self):
        return self.name


class Membership(models.Model):
    classroom = models.ForeignKey(Classroom, on_delete=models.CASCADE, related_name='memberships')
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='class_memberships')
    is_active = models.BooleanField(default=True)
    joined_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['classroom', 'student'], name='one_student_per_class')]
        ordering = ['student__first_name', 'student__username']


class Invitation(models.Model):
    classroom = models.ForeignKey(Classroom, on_delete=models.CASCADE, related_name='invitations')
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='class_invitations')
    status = models.CharField(max_length=12, default='pending', choices=[
        ('pending', 'Ожидает ответа'), ('accepted', 'Принято'), ('declined', 'Отклонено')])
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['classroom', 'student'], name='one_class_invitation')]


class StudentRegistration(models.Model):
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='olympiad_registrations')
    profile = models.ForeignKey('olympiads.OlympiadProfile', on_delete=models.CASCADE, related_name='student_registrations')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['student', 'profile'], name='one_student_registration')]
        ordering = ['profile__olympiad__catalog_number', 'profile__name']


class Assignment(models.Model):
    classroom = models.ForeignKey(Classroom, on_delete=models.CASCADE, related_name='assignments')
    title = models.CharField('Название задания', max_length=180)
    instructions = models.TextField('Условие или инструкция', max_length=8000)
    due_on = models.DateField('Срок выполнения', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-pk']


class AssignmentReceipt(models.Model):
    assignment = models.ForeignKey(Assignment, on_delete=models.CASCADE, related_name='receipts')
    membership = models.ForeignKey(Membership, on_delete=models.CASCADE, related_name='assignments')
    answer = models.TextField('Ответ или ссылка на решение', max_length=4000, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    @property
    def is_overdue(self):
        return not self.completed_at and self.assignment.due_on is not None and self.assignment.due_on < timezone.localdate()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['assignment', 'membership'], name='one_assignment_recipient')]
        ordering = ['assignment__due_on', '-assignment__created_at']


class ChatMessage(models.Model):
    membership = models.ForeignKey(Membership, on_delete=models.CASCADE, related_name='chat_messages')
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    text = models.TextField('Сообщение', max_length=4000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['pk']


class SchoolNotice(models.Model):
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='school_notices')
    classroom = models.ForeignKey(Classroom, on_delete=models.CASCADE)
    membership = models.ForeignKey(Membership, null=True, blank=True, on_delete=models.CASCADE)
    group_message = models.ForeignKey('ClassChatMessage', null=True, blank=True, on_delete=models.CASCADE)
    title = models.CharField(max_length=180)
    text = models.CharField(max_length=500, blank=True)
    url = models.CharField(max_length=250)
    kind = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at', '-pk']
        indexes = [models.Index(fields=['recipient', 'read_at'])]


class ClassChatMessage(models.Model):
    classroom = models.ForeignKey(Classroom, on_delete=models.CASCADE, related_name='chat_messages')
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    text = models.TextField('Сообщение', max_length=4000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['pk']


class VariantDraft(models.Model):
    classroom = models.ForeignKey(Classroom, on_delete=models.CASCADE, related_name='variants')
    title = models.CharField('Название варианта', max_length=180)
    notes = models.TextField('План варианта', max_length=8000, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
