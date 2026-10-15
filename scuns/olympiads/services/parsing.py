"""Pure HTML extraction, kept separate from Selenium and database writes."""
import re
from datetime import date
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

OFFICIAL_CATALOG = 'https://rsr-olymp.ru/'
INDEX_URL = 'https://olimpiada.ru/article/1266'
SOURCE_HOST = 'https://olimpiada.ru'
MONTHS = ('янв', 'фев', 'мар', 'апр', 'ма', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек')
# Explicit name differences between the official register and its editorial index.
ALIASES = {
    'Всероссийская олимпиада по агрогенетике «Иннагрика»': ['/activity/5854'],
    'Всероссийская олимпиада по искусственному интеллекту (с возможностью участия иностранных обучающихся)': ['/activity/5825'],
    'Всероссийская Толстовская олимпиада': ['/activity/5429'],
    'Открытая межвузовская олимпиада школьников «Будущее Сибири»': ['/activity/237'],
    'Санкт-Петербургская олимпиада школьников': ['/activity/246', '/activity/241', '/activity/247'],
}

# Verified alternative subject labels on the editorial site.
PROFILE_LABELS = {
    '5054': 'гуманитарные и социальные науки',
    '236': 'компьютерная безопасность',
    '6': 'математика',
    '5758': 'иностранный язык',
    '5913': 'образование и педагогика',
    '99': 'астрономия', '1': 'математика', '5466': 'предпрофессиональная',
    '279': 'научно-технический', '5898': 'информатика и программирование', '5882': 'инженерное дело',
    '5345': 'инженерные системы', '5831': 'философия',
}


def clean(text):
    return re.sub(r'\s+', ' ', text).strip()


def text(node):
    return clean(node.get_text(' ', strip=True)) if node else ''


def normalize(value):
    value = re.sub(r'^[IVX]+\s+', '', value)
    return re.sub(r'[^а-яa-z0-9]', '', value.lower().replace('ё', 'е'))


def safe_url(raw, base=SOURCE_HOST):
    url = urljoin(base, clean(raw or ''))
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.username or parsed.password:
        return ''
    return url


def parse_catalog(html, season):
    soup = BeautifulSoup(html, 'html.parser')
    year = season.split('/')[0]
    if not re.search(r'на\s+' + year + r'/(?:' + str(int(year)+1) + '|' + str(int(year)+1)[-2:] + r')', text(soup)):
        raise ValueError('Официальный перечень не соответствует запрошенному сезону ' + season)
    table = soup.select_one('.mainTableInfo tbody')
    if not table:
        raise ValueError('Не найдена таблица официального перечня; структура сайта изменилась.')
    olympiads = {}
    current = None
    current_url = ''
    for row in table.select('tr'):
        cells = row.find_all('td', recursive=False)
        if len(cells) >= 5 and text(cells[0]).isdigit():
            number = int(text(cells[0]))
            current_url = safe_url(cells[1].a.get('href'), OFFICIAL_CATALOG) if cells[1].a else ''
            current = olympiads.setdefault(number, {'number': number, 'name': text(cells[1]), 'official_url': current_url, 'profiles': []})
        if current is None or len(cells) < 3:
            continue
        if len(cells) == 4 and cells[0].a:
            current_url = safe_url(cells[0].a.get('href'), OFFICIAL_CATALOG)
        level = text(cells[-1])
        if level not in ('1', '2', '3'):
            raise ValueError('Не удалось прочитать уровень профиля: ' + text(row))
        current['profiles'].append({'name': text(cells[-3]), 'subjects': text(cells[-2]), 'level': int(level), 'official_url': current_url})
    if len(olympiads) < 30:
        raise ValueError('Получен неполный перечень: меньше 30 олимпиад.')
    return list(olympiads.values())


def source_index(html):
    soup = BeautifulSoup(html, 'html.parser')
    result = {}
    for anchor in soup.select('ol a[href*="/activity/"]'):
        url = safe_url(anchor.get('href'))
        if re.fullmatch(r'/activity/\d+', urlparse(url).path):
            result[normalize(text(anchor))] = url
    if len(result) < 30:
        raise ValueError('Не удалось прочитать каталог ссылок Олимпиада.ру.')
    return result


def source_urls(name, index):
    exact = index.get(normalize(name))
    if exact:
        return [exact]
    # Do not use fuzzy matches: two similarly named competitions may be unrelated.
    return [safe_url(url) for key, urls in ALIASES.items() if normalize(key) == normalize(name) for url in urls]


def profile_match(title, profiles):
    """Match grammatical endings only, without confusing common subject names."""
    parenthesis = re.search(r'\(([^()]+)\)\s*$', title)
    suffix = parenthesis.group(1).lower() if parenthesis else re.split(r'\sпо\s', title.lower())[-1]
    def tokens(value):
        return [re.sub(r'(иями|ями|ами|ого|ему|ому|ыми|ими|ее|ие|ые|ое|ей|ий|ый|ой|ем|им|ым|ом|ах|ях|ам|ям|ая|яя|ую|юю|а|я|ы|и|у|ю|е|о|ь)$', '', word.replace('рисунок', 'рисунк'))[:8] for word in re.findall(r'[а-я]+', value.lower().replace('ё', 'е')) if len(word) > 2]
    matches = []
    for profile in profiles:
        required = tokens(profile['name'])
        if required and set(required) == set(tokens(suffix)):
            matches.append(profile)
    return max(matches, key=lambda p: len(p['name'])) if matches else None


def activity_data(html, url, profiles):
    soup = BeautifulSoup(html, 'html.parser')
    if not soup.select_one('.timetableH2, .fav_olimp[act], .top_container'):
        raise ValueError('Карточка олимпиады не распознана: ' + url)
    blocks = soup.select('.multiact .fav_olimp[act]')
    events = {}
    activities = []
    for block in blocks:
        anchor = block.select_one('.o-info a[href*="/activity/"]')
        if not anchor:
            continue
        title = text(anchor)
        profile = profile_match(title, profiles)
        alternative = PROFILE_LABELS.get(block.get('act'))
        if not profile and alternative:
            profile = next((item for item in profiles if item['name'] == alternative), None)
        # Editorial pages can contain extra profiles that are absent from the approved list.
        if not profile:
            continue
        activity_url = safe_url(anchor['href'])
        activities.append({'url': activity_url, 'profile_name': profile['name'], 'title': title})
        for event in block.select('.tl_event[ev_id]'):
            event_url = safe_url('/activity/{}/events/{}'.format(event['ev_act'], event['ev_id']))
            events[(event_url, profile['name'])] = {'url': event_url, 'profile_name': profile['name']}
    if not blocks:
        title = text(soup.select_one('.top_container h1')) or text(soup.select_one('h1'))
        profile = profile_match(title, profiles)
        name = profile['name'] if profile else (profiles[0]['name'] if len(profiles) == 1 else '')
        activities.append({'url': url, 'profile_name': name, 'title': title})
        for anchor in soup.select('.events_for_activity a[href*="/events/"]'):
            raw = anchor['href']
            if '?' in raw:  # Archive links must not become current-season events.
                continue
            event_url = safe_url(raw)
            events[event_url] = {'url': event_url, 'profile_name': name}
    return {'events': list(events.values()), 'activities': activities, 'registration_url': registration_link(soup, url, generic=True)}


def registration_link(soup, base, allowed_hosts=None, generic=False):
    candidates = []
    for anchor in soup.select('a[href]'):
        url = safe_url(anchor.get('href'), base)
        if not url:
            continue
        if allowed_hosts and urlparse(url).hostname not in allowed_hosts:
            continue
        label = text(anchor).lower()
        path = urlparse(url).path.lower()
        if any(token in path for token in ('.pdf', '.doc', '.jpg')) or 'mailto:' in anchor.get('href', ''):
            continue
        if re.search(r'/(news|article|media/news|instr-reg)(/|$)', path) or (re.search(r'/activity/', path) and urlparse(url).hostname == 'olimpiada.ru'):
            continue
        score = 0
        if re.fullmatch(r'(?:вход\s*[/|и]\s*)?регистрация(?: участников)?|зарегистрироваться|пройти регистрацию|начать регистрацию', label):
            score = 5
        elif re.fullmatch(r'личный кабинет(?: участника)?|кабинет участника|вход для участников', label):
            score = 4
        elif label.startswith('регистрация на ') and (not generic or re.search(r'олимпиад|конкурс', label)):
            score = 3
        elif re.fullmatch(r'подать заявку|принять участие', label):
            score = 3
        elif re.search(r'/(register|registration|signup)(/|$)', path):
            score = 2
        if score:
            candidates.append((score, url))
    if not candidates:
        return ''
    best = max(score for score, _ in candidates)
    urls = {url for score, url in candidates if score == best}
    # Multiple equally likely forms can belong to different subjects; retain no guessed link.
    return next(iter(urls)) if len(urls) == 1 else ''


def task_archive_link(html, base):
    """Use a published archive link for this exact activity, never a guessed path."""
    soup = BeautifulSoup(html, 'html.parser')
    expected = urlparse(base).path.rstrip('/') + '/tasks'
    for anchor in soup.select('a[href]'):
        url = safe_url(anchor.get('href'), base)
        parsed = urlparse(url)
        if (parsed.hostname == 'olimpiada.ru' and parsed.path.rstrip('/') == expected
                and re.search(r'задани|решени', text(anchor), re.I)):
            return url
    return ''


def profile_registration_links(soup, base, profiles):
    candidates = {}
    for anchor in soup.select('a[href]'):
        match = re.match(r'^регистрация(?: участников)? (?:на|по) (.+)$', text(anchor), re.I)
        if not match:
            continue
        profile = profile_match(match.group(1), profiles)
        if not profile:
            continue
        url = registration_link(BeautifulSoup(str(anchor), 'html.parser'), base)
        if url:
            candidates.setdefault(profile['name'], set()).add(url)
    return {name: next(iter(urls)) for name, urls in candidates.items() if len(urls) == 1}



def parse_date_display(node):
    raw = text(node)
    if not node:
        return None, None, raw
    # A deadline uses two font nodes: the word "До" and the day itself.
    # A year in a font node must not become two artificial day values (20, 26).
    days = re.findall(r'(?<!\d)\d{1,2}(?!\d)', ' '.join(text(font) for font in node.find_all('font')))
    years = re.findall(r'\b(20\d{2})\b', raw)
    months = []
    for span in node.select('.month'):
        value = text(span).lower()
        for number, prefix in enumerate(MONTHS, 1):
            if value.startswith(prefix):
                months.append(number)
                break
    if not days or not years or not months or len(days) > 2:
        return None, None, raw
    try:
        start_year, end_year = int(years[0]), int(years[-1])
        start_month, end_month = months[0], months[-1]
        if len(years) == 1 and end_month < start_month:
            end_year += 1
        start = date(start_year, start_month, int(days[0]))
        end = date(end_year, end_month, int(days[-1]))
        if end < start:
            raise ValueError('Invalid date range')
        if re.match(r'^до\b', raw, re.I):
            return None, end, raw
        if re.match(r'^с\b', raw, re.I) and len(days) == 1:
            return start, None, raw
        return start, end, raw
    except ValueError:
        return None, None, raw


def event_data(html, url, profile_name, season):
    soup = BeautifulSoup(html, 'html.parser')
    heading = soup.select_one('.content .right h1')
    date_node = soup.select_one('.time_classes_line_for_event .main_date')
    if not heading or not date_node:
        raise ValueError('Не найдены название/дата события: ' + url)
    starts, ends, raw = parse_date_display(date_node)
    year = int(season.split('/')[0])
    # Old approximate events have no concrete days, but their explicit year is
    # still enough to reject them. Never attach archived dates to a new season.
    years = [int(value) for value in re.findall(r'\b(20\d{2})\b', raw)]
    if years and (max(years) < year or min(years) > year + 1):
        return None
    if (ends and ends < date(year, 7, 1)) or (starts and starts >= date(year+1, 9, 1)) or (not starts and ends and ends >= date(year+1, 9, 1)):
        return None
    # Missing/approximate dates may be published intentionally. A concrete but
    # unrecognised date must instead fail the read so an earlier valid date survives.
    concrete_days = re.findall(r'(?<!\d)\d{1,2}(?!\d)', ' '.join(text(font) for font in date_node.find_all('font')))
    if concrete_days and years and not starts and not ends:
        raise ValueError('Не удалось распознать точную дату события {}: {}'.format(url, raw))
    name = text(heading)
    kind = 'registration' if re.search(r'регистра|при[её]м заяв|подача заяв', name, re.I) else 'stage' if re.search(r'тур|этап|отбор|финал', name, re.I) else 'other'
    proof = soup.select_one('.event-proof a[href]')
    from .venues import event_venue_data
    venue = event_venue_data(soup, name, url) if kind == 'stage' else {}
    return {**venue, 'name': name, 'kind': kind, 'profile_name': profile_name, 'starts_on': starts,
            'ends_on': ends, 'dates_raw': raw, 'source_url': url,
            'proof_url': safe_url(proof.get('href'), url) if proof else '',
            'registration_url': registration_link(soup.select_one('.content .right') or soup, url)}


def registration_references(html, url, profiles):
    """Use explicit registration labels; dates still come from full event pages."""
    data = activity_data(html, url, profiles)
    soup = BeautifulSoup(html, 'html.parser')
    labelled = set()
    for event in soup.select('.tl_event[ev_id][ev_act]'):
        if 'ereg' in event.get('class', []) or re.search(r'регистра|при[её]м заяв|подача заяв', text(event), re.I):
            labelled.add(safe_url('/activity/{}/events/{}'.format(event['ev_act'], event['ev_id'])))
    for anchor in soup.select('.events_for_activity a[href*="/events/"]'):
        if '?' not in anchor['href'] and re.search(r'регистра|при[её]м заяв|подача заяв', text(anchor), re.I):
            labelled.add(safe_url(anchor['href'], url))
    return [entry for entry in data['events'] if entry['url'] in labelled]
