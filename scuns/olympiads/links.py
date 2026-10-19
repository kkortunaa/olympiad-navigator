"""Verified corrections for outdated links in upstream catalogues.

Only exact known addresses are replaced; unrelated paths and registration
forms must not be silently redirected to a generic organizer homepage.
"""

VERIFIED_URL_REPLACEMENTS = {
    'http://yumsh.spbu.ru': 'https://yumsh.ru/cms/yumsh-olymp',
    'https://yumsh.spbu.ru': 'https://yumsh.ru/cms/yumsh-olymp',
    'http://www.yumsh.spbu.ru': 'https://yumsh.ru/cms/yumsh-olymp',
    'https://www.yumsh.spbu.ru': 'https://yumsh.ru/cms/yumsh-olymp',
    'http://abiturient.tsu.ru/ru/content/ormo': 'https://info.abiturient.tsu.ru/ru/content/ormo',
    'https://abiturient.tsu.ru/ru/content/ormo': 'https://info.abiturient.tsu.ru/ru/content/ormo',
    'http://ntcontest.ru': 'https://ntcontest.ru/',
    'http://www.olympiads.ru/zaoch': 'https://inf-open.ru/',
    'https://www.olympiads.ru/zaoch': 'https://inf-open.ru/',
    'http://olympiads.ru/zaoch': 'https://inf-open.ru/',
    'https://olympiads.ru/zaoch': 'https://inf-open.ru/',
}


def corrected_url(url):
    return VERIFIED_URL_REPLACEMENTS.get(url.rstrip('/'), url)
