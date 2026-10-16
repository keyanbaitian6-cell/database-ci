"""Inert parsing of one Ana-slo hall index; never fetch links discovered here."""
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
import re
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit


@dataclass(frozen=True)
class Hall:
    """One supported hall. Only the source name and URL slug differ per hall;
    the URL rules (HTTPS, no query, fragment ignored) are shared."""
    key: str
    label: str
    source_name: str
    slug: str
    prefecture: str = '宮城県'

    @property
    def index_path(self):
        return f'/ホールデータ/{self.prefecture}/{self.slug}-データ一覧/'

    @property
    def index_url(self):
        return 'https://ana-slo.com' + quote(self.index_path, safe='/')

    @property
    def index_heading(self):
        return f'{self.source_name} データ一覧'

    def daily_day(self, path):
        match = re.fullmatch(r'/(\d{4}-\d{2}-\d{2})-' + re.escape(self.slug) + r'-data/', path)
        return match[1] if match else None


P_STATION = Hall('p-station', 'P-STATION', 'P-STATION&IIスロット館', 'p-stationiiスロット館')
# 2026-10-16 利用者の保存HTML（日別 2026/09/01）で見出し・URLを確認。メルヘン用DBの幸町（saiwaichou）へ補完する。
SAIWAICHOU = Hall('saiwaichou', '幸町', 'スーパーメルヘンワールド幸町店', 'スーパーメルヘンワールド幸町店')
HALLS = (P_STATION, SAIWAICHOU)
HALL_NAMES = '・'.join(h.label for h in HALLS)

# P-STATION aliases kept for existing callers.
INDEX_PATH = P_STATION.index_path
INDEX_URL = P_STATION.index_url
DAILY = re.compile(r'^/(\d{4}-\d{2}-\d{2})-p-stationiiスロット館-data/$')


@dataclass(frozen=True)
class DayLink:
    day: str
    url: str


def valid_day(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('日付は YYYY-MM-DD 形式で指定してください。')
    if date.fromisoformat(value).isoformat() != value:
        raise ValueError('日付が不正です。')
    return value


def date_range(start, end):
    valid_day(start)
    valid_day(end)
    if start > end:
        raise ValueError('開始日は終了日以前にしてください。')
    return start, end


def _parse(url, index, hall):
    u = urlsplit(url)
    if u.scheme != 'https' or u.netloc.lower() != 'ana-slo.com' or u.query:
        raise ValueError('対象のHTTPSアナスロURLではありません。')
    path = unquote(u.path, errors='strict')
    for candidate in (hall,) if hall else HALLS:
        if index and path == candidate.index_path:
            return candidate, path, None
        day = None if index else candidate.daily_day(path)
        if day:
            valid_day(day)
            return candidate, path, day
    if index:
        raise ValueError(f'{hall.label if hall else HALL_NAMES}のデータ一覧URLを指定してください。')
    raise ValueError(f'{hall.label if hall else HALL_NAMES}の日別データURLではありません。')


def canonical_url(url, *, index=False, hall=None):
    """Any supported hall is accepted unless ``hall`` restricts it. Equality of
    the result still separates halls, because the hall is part of the path."""
    _, path, _ = _parse(url, index, hall)
    return urlunsplit(('https', 'ana-slo.com', quote(path, safe='/'), '', ''))


def hall_of(url, *, index=False):
    return _parse(url, index, None)[0]


def link_day(url):
    return _parse(url, False, None)[2]


class Anchors(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            href = dict(attrs).get('href')
            if href:
                self.hrefs.append(href)


def extract_links(raw, base_url, start, end):
    start, end = date_range(start, end)  # No implicit full-history selection.
    base_url = canonical_url(base_url, index=True)
    hall = hall_of(base_url, index=True)
    dom = Anchors()
    dom.feed(raw.decode('utf-8-sig', errors='strict'))
    links = {}
    for href in dom.hrefs:
        try:
            # Links to another hall on the same index page are never selected.
            url = canonical_url(urljoin(base_url, href.strip()), hall=hall)
            day = link_day(url)
        except (ValueError, UnicodeError):
            continue
        if start <= day <= end:
            links[url] = DayLink(day, url)
    return sorted(links.values(), key=lambda item: (item.day, item.url))
