from .models import Olympiad


def catalog_names(request):
    rows = Olympiad.objects.filter(is_active=True).values('season', 'catalog_number', 'name')
    names = {'olymp-{}-{}'.format(row['season'][:4], row['catalog_number']): row['name'] for row in rows}
    aliases = {}
    for legacy, phrase in [('hse', 'Высшая проба'), ('tech', 'ТехноКубок'), ('msu', 'Ломоносов')]:
        matches = [(key, name) for key, name in names.items() if '«{}»'.format(phrase).lower() in name.lower()]
        if matches:
            aliases[legacy] = sorted(matches)[-1][0]
    return {'catalog_names': names, 'catalog_aliases': aliases}
