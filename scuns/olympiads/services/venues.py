"""Extract venue facts from the event itself or its own subject description."""
import re
from bs4 import BeautifulSoup
from .parsing import clean, text, safe_url

QUALIFYING = re.compile(r'\bотбор(?:очн|а|е|у|ом|\b)|квалификационн|перв(?:ый|ого|ом)\s+(?:этап|тур)', re.I)
FINAL = re.compile(r'заключительн|финал', re.I)
PLACE_LABEL = re.compile(r'^(?:место(?:\s+проведения)?|адрес(?:\s+(?:проведения|площадки))?)\s*[:—–-]\s*(.+)', re.I)


def phase(name):
    if QUALIFYING.search(name):
        return 'qualifying'
    if FINAL.search(name):
        return 'final'
    return ''


def mode(value):
    value = value.lower().replace('ё', 'е')
    if re.search(r'очно[-\s]заочн|гибридн|смешанн', value):
        return 'hybrid'
    patterns = {'online': r'онлайн|дистанцион|через интернет|в интернете|в интернет[ -]',
                'remote': r'\bзаочн', 'offline': r'\bочн'}
    found = set()
    for key, pattern in patterns.items():
        for match in re.finditer(pattern, value):
            if not re.search(r'\bне\s*$', value[max(0, match.start()-6):match.start()]):
                found.add(key)
    if 'offline' in found and found & {'online', 'remote'}:
        return 'hybrid' if re.search(r'\bили\b|\bтак и\b', value) else ''
    if 'online' in found:
        return 'online'
    if 'remote' in found:
        return 'remote'
    return 'offline' if 'offline' in found else ''


def place(value, format_name):
    if format_name in ('online', 'remote'):
        return ''
    match = PLACE_LABEL.match(value)
    if match:
        result = match.group(1).strip()
        if not re.search(r'уточн|будет (?:опублик|сообщ|извест)|позже|не указан', result, re.I):
            return result[:1000]
    if re.search(r'проход|провод|состо|пройд|собер|организ', value, re.I):
        match = re.search(r'\bв\s+((?:г\.?\s+)?[А-ЯЁ][^.!?]+)', value)
        if match and not re.match(r'(?:Интернет|Очно|Заочно|Дистанцион)', match.group(1)):
            return 'В ' + match.group(1).strip(' ,;')[:998]
        match = re.search(r'\bна (?:базе|площадках|площадке)\s+(.+)', value, re.I)
        if match and not re.search(r'будет|уточн|позже', match.group(1), re.I):
            return 'На ' + match.group(0)[3:].strip(' .;')[:990]
    return ''


def facts(blocks, name, source_url, basis, season=None):
    target = phase(name)
    candidates = []
    for node in blocks:
        value = text(node)
        if not value:
            continue
        # Keep labelled addresses intact, including "г.", "ул." and building numbers.
        snippets = [value] if PLACE_LABEL.match(value) else re.split(r'(?<=[.!?;])\s+', value)
        for snippet in snippets:
            if basis == 'profile':
                if re.search(r'состоял[а-я]*|прош[её]л|прошла|прошли|проводил[а-я]*|проходил[а-я]*', snippet, re.I):
                    continue
                years = {int(value) for value in re.findall(r'\b(20\d{2})\b', snippet)}
                allowed = {int(season[:4]), int(season[:4])+1} if season else set()
                if years and not years.issubset(allowed):
                    continue
            if basis == 'profile' and not target and (QUALIFYING.search(snippet) or FINAL.search(snippet)):
                continue
            if basis == 'profile' and target:
                if target == 'qualifying' and not QUALIFYING.search(snippet):
                    continue
                if target == 'final' and not FINAL.search(snippet):
                    continue
            if target == 'qualifying' and FINAL.search(snippet) and not QUALIFYING.search(snippet):
                continue
            if target == 'final' and QUALIFYING.search(snippet) and not FINAL.search(snippet):
                continue
            if QUALIFYING.search(snippet) and FINAL.search(snippet):
                # Do not assign an online qualifier's format to an in-person final.
                continue
            format_name = mode(snippet)
            venue = place(snippet, format_name)
            venue_url = ''
            for anchor in node.select('a[href]'):
                label = text(anchor)
                if re.search(r'площадк|мест[ао] провед|адрес[а]? площад', label, re.I):
                    venue_url = safe_url(anchor['href'], source_url)
                    break
            if format_name or venue or venue_url:
                candidates.append({'participation_format': format_name, 'venue': venue,
                                   'venue_url': venue_url, 'venue_source_url': source_url,
                                   'venue_note': snippet[:1800], 'venue_basis': basis})
    if not candidates:
        return {}
    formats = {item['participation_format'] for item in candidates if item['participation_format']}
    if formats == {'online', 'remote'}:
        formats = {'online'}
    if len(formats) > 1:
        # Several qualifiers may use different formats and venues. Do not guess which one.
        return {}
    winner = max(candidates, key=lambda item: (bool(item['venue']), bool(item['venue_url']), bool(item['participation_format'])))
    if len(formats) == 1 and not winner['participation_format']:
        winner = {**winner, 'participation_format': next(iter(formats))}
    if not winner['venue_url']:
        winner = {**winner, 'venue_url': next((item['venue_url'] for item in candidates if item['venue_url']), '')}
    return winner


def event_venue_data(html, name, source_url):
    soup = html if isinstance(html, BeautifulSoup) else BeautifulSoup(html, 'html.parser')
    root = soup.select_one('.content .right')
    if not root:
        return {}
    blocks = root.select('.full_event_info p, .full_event_info li, .event-place, .event-venue, .event_place, .event_location, .place_for_event, .address_for_event, [itemprop="location"]')
    blocks += [node for node in root.select('.full_event_info') if not node.select('p, li') and text(node)]
    result = facts(blocks, name, source_url, 'event')
    if result:
        return result
    format_name = mode(name)
    if format_name:
        return {'participation_format': format_name, 'venue': '', 'venue_url': '',
                'venue_source_url': source_url, 'venue_note': name, 'venue_basis': 'event'}
    return {}


def activity_venue_data(html, name, source_url, season=None):
    soup = BeautifulSoup(html, 'html.parser')
    root = soup.select_one('.content.activity-content .right')
    if not root:
        return {}
    result = facts(root.select('#history p, .full_event_info li, .full_event_info p'), name, source_url, 'profile', season)
    if result:
        return result
    # A mixed competition's generic tooltip can contradict its actual stage text.
    # Never infer a particular stage from "Очно-заочная".
    labels = [text(node.select_one('span')) for node in root.select('.f_blocks')]
    single_format = next((value for value in labels if value in ('Очная', 'Заочная', 'Дистанционная', 'Онлайн')), '')
    description = ' '.join(text(node) for node in root.select('#history p, .full_event_info li, .full_event_info p'))
    # Even a single-format badge may be generic or outdated: explicit round text wins.
    if single_format == 'Очная' and re.search(r'дистанцион|заочн|онлайн', description, re.I):
        return {}
    if single_format in ('Заочная', 'Дистанционная', 'Онлайн') and re.search(r'\bочн', description, re.I):
        return {}
    if single_format:
        return {'participation_format': {'Очная':'offline', 'Заочная':'remote', 'Дистанционная':'online', 'Онлайн':'online'}[single_format],
                'venue':'', 'venue_url':'', 'venue_source_url':source_url,
                'venue_note':'Формат олимпиады в описании: ' + single_format + '. Место конкретного тура уточни у организатора.',
                'venue_basis':'profile'}
    return {}


def merge_venue_data(direct, description):
    """Prefer a published event address; supplement an otherwise format-only fact."""
    if not direct:
        return description
    if direct.get('venue') or direct.get('venue_url') or not description:
        return direct
    if description.get('venue') or description.get('venue_url'):
        direct_format = direct.get('participation_format')
        profile_format = description.get('participation_format')
        if not direct_format or not profile_format or direct_format == profile_format or {direct_format, profile_format} <= {'online', 'remote'}:
            return {**description, 'participation_format': direct_format or profile_format}
    return direct
