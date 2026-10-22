"""Deterministic answer checking. Neither Python expressions nor HTML are evaluated."""
import re
import unicodedata
from fractions import Fraction

from django.core.exceptions import ValidationError

ANSWER_TYPES = [('short', 'Короткий текст'), ('number', 'Число или дробь'),
                ('choice', 'Один вариант ответа'), ('multiple', 'Несколько вариантов ответа')]
RULES = [('exact', 'Точное совпадение (крайние пробелы не учитываются)'),
         ('text', 'Без учёта регистра и повторяющихся пробелов'),
         ('number', 'Числовое сравнение: 1/2 = 0,5'),
         ('set', 'Набор номеров без учёта порядка')]


def number(value):
    value = value.strip().replace(',', '.').replace('−', '-')
    atom = r'[+-]?(?:\d{1,40}(?:\.\d{0,40})?|\.\d{1,40})(?:[eE][+-]?\d{1,2})?'
    if len(value) > 160 or not re.fullmatch(rf'{atom}(?:\s*/\s*{atom})?', value):
        raise ValueError('Некорректное число')
    # Bound the magnitude as well as the length before constructing a Fraction.
    for exponent in re.findall(r'[eE]([+-]?\d+)', value):
        if abs(int(exponent)) > 30:
            raise ValueError('Слишком большой порядок числа')
    parts = value.split('/')
    result = Fraction(parts[0].strip())
    return result / Fraction(parts[1].strip()) if len(parts) == 2 else result


def selected(value):
    tokens = re.split(r'[,;\s]+', value.strip())
    if not tokens or any(not re.fullmatch(r'\d{1,2}', token) for token in tokens):
        raise ValueError('Укажите номера ответов')
    values = [int(token) for token in tokens]
    if len(values) != len(set(values)):
        raise ValueError('Не повторяйте номера ответов')
    return frozenset(values)


def normalize(value, rule):
    value = value.strip()
    if rule == 'text':
        return ' '.join(unicodedata.normalize('NFKC', value).casefold().split())
    return value


def is_correct(data, value):
    if not value.strip():
        return False
    try:
        if data['answer_type'] == 'number':
            return any(abs(number(value) - number(expected)) <= number(str(data.get('tolerance', '0')))
                       for expected in data['answers'])
        if data['answer_type'] == 'multiple':
            return any(selected(value) == selected(expected) for expected in data['answers'])
        return any(normalize(value, data['rule']) == normalize(expected, data['rule']) for expected in data['answers'])
    except (ValueError, ZeroDivisionError, OverflowError):
        return False


def validate_spec(kind, rule, answers, options, tolerance):
    if not answers or len(answers) > 20 or any(not isinstance(x, str) or not x.strip() or len(x) > 500 for x in answers):
        raise ValidationError('Нужно от 1 до 20 допустимых ответов, не более 500 символов в каждом.')
    try:
        if kind == 'number':
            if rule != 'number' or number(str(tolerance)) < 0:
                raise ValueError()
            for value in answers:
                number(value)
        elif kind in ('choice', 'multiple'):
            if not 2 <= len(options) <= 12 or any(not isinstance(x, str) or not x.strip() or len(x) > 500 for x in options):
                raise ValidationError('Для выбора ответа нужно от 2 до 12 непустых вариантов, до 500 символов каждый.')
            for value in answers:
                choices = selected(value)
                if not choices or min(choices) < 1 or max(choices) > len(options):
                    raise ValueError()
                if kind == 'choice' and (len(choices) != 1 or rule != 'exact' or value.strip() != str(next(iter(choices)))):
                    raise ValueError()
                if kind == 'multiple' and rule != 'set':
                    raise ValueError()
        elif kind != 'short' or rule not in ('exact', 'text'):
            raise ValueError()
    except (ValueError, ZeroDivisionError, OverflowError):
        raise ValidationError('Проверьте формат правильных ответов и правило сравнения. Для выбора указывайте номера от 1 до числа вариантов.')
