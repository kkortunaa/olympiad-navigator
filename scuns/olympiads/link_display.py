"""Use saved link checks when rendering; never contact external sites in a view."""
from .links import corrected_url
from .models import CatalogLinkCheck


def prepare_catalog_links(olympiads):
    blocked = set(CatalogLinkCheck.objects.exclude(outcome__in=(
        'reachable', 'restricted')).values_list('url', flat=True))
    for olympiad in olympiads:
        owners = [olympiad, *olympiad.profiles.all(), *olympiad.events.all()]
        for owner in owners:
            original_registration = owner.registration_url
            for field in owner._meta.fields:
                if field.name.endswith('_url'):
                    url = corrected_url(getattr(owner, field.name))
                    setattr(owner, field.name, '' if url in blocked else url)
            owner.registration_unavailable = bool(original_registration and not owner.registration_url)
            official = getattr(owner, 'official_url', '') or olympiad.official_url
            source = owner.source_url or olympiad.source_url
            owner.registration_action = {
                'url': owner.registration_url or official or source,
                'label': ('Зарегистрироваться ↗' if owner.registration_url else
                          'Регистрация на сайте организатора ↗' if official else
                          'Условия участия и источники ↗'),
            }
    return olympiads
