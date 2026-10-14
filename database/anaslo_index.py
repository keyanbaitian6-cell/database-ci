"""Inert parsing of one P-STATION index; never fetch links discovered here."""
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
import re
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit

INDEX_PATH = '/ホールデータ/宮城県/p-stationiiスロット館-データ一覧/'
INDEX_URL = 'https://ana-slo.com' + quote(INDEX_PATH, safe='/')
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


def canonical_url(url, *, index=False):
    u = urlsplit(url)
    if u.scheme != 'https' or u.netloc.lower() != 'ana-slo.com' or u.query:
        raise ValueError('対象のHTTPSアナスロURLではありません。')
    path = unquote(u.path, errors='strict')
    if index:
        if path != INDEX_PATH:
            raise ValueError('P-STATIONのデータ一覧URLを指定してください。')
    else:
        match = DAILY.fullmatch(path)
        if not match:
            raise ValueError('P-STATIONの日別データURLではありません。')
        valid_day(match[1])
    return urlunsplit(('https', 'ana-slo.com', quote(path, safe='/'), '', ''))


def link_day(url):
    url = canonical_url(url)
    return DAILY.fullmatch(unquote(urlsplit(url).path))[1]


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
    dom = Anchors()
    dom.feed(raw.decode('utf-8-sig', errors='strict'))
    links = {}
    for href in dom.hrefs:
        try:
            url = canonical_url(urljoin(base_url, href.strip()))
            day = link_day(url)
        except (ValueError, UnicodeError):
            continue
        if start <= day <= end:
            links[url] = DayLink(day, url)
    return sorted(links.values(), key=lambda item: (item.day, item.url))
