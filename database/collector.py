"""Single-browser, single-machine collection through visible site UI."""
from __future__ import annotations

import json
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.common.exceptions import WebDriverException, StaleElementReferenceException

from core import STORE_NAMES, Store, report

HOST = 'meruhenworld.pt.teramoba2.com'
DEFAULT_URL = 'https://' + HOST + '/nagamachiminami/standlist_slot?kind_code=21&machine_name=L%25E6%2588%25A6%25E5%259B%25BD%25E4%25B9%2599%25E5%25A5%25B35L8'
HEADERS = ['台番号','BB','RB','総回転数','合成確率','前日最終スタート','最大持玉']
# saiwaichou's own list page never shows a 最大持玉 column at all (confirmed
# against the live site, not just a rendering quirk) -- that store's max_hold
# is only ever filled in later, from the individual rack's graph page.
HEADERS_NO_MAX_HOLD = HEADERS[:-1]


def check_url(url):
    p = urlparse(url)
    q = parse_qs(p.query)
    location = p.path.strip('/').split('/')[0] if p.path.strip('/') else ''
    expected_path = f'/{location}/standlist_slot'
    if (p.scheme != 'https' or p.netloc != HOST or location not in STORE_NAMES
            or p.path.rstrip('/') != expected_path or q.get('kind_code') != ['21']
            or not q.get('machine_name')):
        raise ValueError('長町南店または幸町店・1000円46枚の機種別一覧URLを指定してください。')
    return unquote(q['machine_name'][0])


def store_from_url(url):
    check_url(url)
    return urlparse(url).path.strip('/').split('/')[0]


def parse_table(matrix, links, day, machine, source, updated, location='nagamachiminami'):
    if not matrix or matrix[0] not in (HEADERS, HEADERS_NO_MAX_HOLD):
        raise ValueError('一覧の列構成が変わりました。保存を止めました。')
    has_max_hold = matrix[0] == HEADERS
    expected_cols = len(matrix[0])
    rows = []
    for cells, link in zip(matrix[1:], links, strict=True):
        if len(cells) != expected_cols:
            raise ValueError('一覧の列数が一致しません。')
        int_indexes = (0,1,2,3,5,6) if has_max_hold else (0,1,2,3,5)
        numbers = [int(cells[i].replace(',', '')) for i in int_indexes]
        if any(x < 0 for x in numbers):
            raise ValueError('不正な負の数値があります。')
        if has_max_hold:
            rack, bb, rb, games, previous, maximum = numbers
        else:
            rack, bb, rb, games, previous = numbers
            maximum = None
        parsed_link = urlparse(link)
        q = parse_qs(parsed_link.query)
        if (parsed_link.hostname != HOST or not parsed_link.path.startswith(f'/{location}/')
                or q.get('rack_no') != [str(rack)] or q.get('target_date') != [day]):
            raise ValueError('選択日と台リンクの日付が一致しません。')
        rows.append(dict(store=location,kind_code=21,day=day,machine=machine,rack=rack,bb=bb,rb=rb,games=games,previous_start=previous,max_hold=maximum,combined_display=cells[4],source_url=source,detail_url=link,updated_at_display=updated))
    if len({r['rack'] for r in rows}) != len(rows) or not rows:
        raise ValueError('台番号が重複しているか、一覧が空です。')
    return rows


class Collector:
    def __init__(self, folder, log=print, stop=None):
        self.folder = Path(folder)
        self.log = log
        self.stop = stop or threading.Event()
        self.driver = None
        self.last_access = 0.0

    def pause(self):
        delay = max(0, 3 - (time.monotonic() - self.last_access))
        if self.stop.wait(delay):
            raise InterruptedError('停止しました。保存済みデータは残っています。')
        self.last_access = time.monotonic()

    def start(self):
        options = webdriver.ChromeOptions()
        # Separate temporary profile supplied by ChromeDriver; no existing cookies.
        options.add_argument('--window-size=1200,850')
        self.driver = webdriver.Chrome(options=options)
        self.driver.set_page_load_timeout(40)

    def load(self, url):
        self.pause()
        self.driver.get(url)
        current = urlparse(self.driver.current_url)
        if current.hostname != HOST:
            raise ValueError('対象外のサイトに移動したため停止しました。')
        if current.path.endswith('/protection_redirect'):
            buttons = self.driver.find_elements(By.ID, 'submittos')
            if buttons:
                _ = buttons[0].location_once_scrolled_into_view
            self.driver.save_screenshot(str(self.folder / 'consent-screen.png'))
            self.log('ブラウザの利用規約をご自身で確認し、同意する場合は「同意する」を押してください（最大3分待ちます）。')
            def ready(d):
                if self.stop.is_set():
                    raise InterruptedError('停止しました。')
                current_url = d.current_url
                return bool(current_url) and '/protection_redirect' not in current_url
            WebDriverWait(self.driver, 180).until(ready)

    def get_table(self, day, machine, location):
        self.pause()
        select = WebDriverWait(self.driver, 25).until(lambda d: d.find_elements(By.TAG_NAME,'select') or False)[0]
        Select(select).select_by_visible_text(day.replace('-','/'))
        def ready(d):
            if self.stop.is_set():
                raise InterruptedError('停止しました。')
            tables = d.find_elements(By.TAG_NAME,'table')
            for table in tables:
                trs = table.find_elements(By.TAG_NAME,'tr')
                if len(trs) < 2:
                    continue
                matrix = [[c.text.strip() for c in tr.find_elements(By.CSS_SELECTOR,'th,td')] for tr in trs]
                if matrix[0] != HEADERS:
                    continue
                anchors = table.find_elements(By.CSS_SELECTOR,'td a')
                links = [a.get_attribute('href') for a in anchors]
                if len(links) != len(matrix)-1 or any(parse_qs(urlparse(x).query).get('target_date') != [day] for x in links):
                    continue
                body = d.find_element(By.TAG_NAME,'body').text
                updated = next((s for s in body.splitlines() if s.startswith('更新日時')), '')
                return parse_table(matrix, links, day, machine, d.current_url, updated, location)
            return False
        return WebDriverWait(self.driver, 30).until(ready)

    def get_graph(self, row):
        self.load(row['detail_url'])
        def ready(d):
            if self.stop.is_set():
                raise InterruptedError('停止しました。')
            # Selectors refer only to the rendered SVG observed on the page.
            svg = d.find_elements(By.CSS_SELECTOR, 'svg.today')
            if not svg:
                return False
            svg = svg[0]
            values = {}
            for name, selector in [('games','.info_soukaiten'),('bb','.info_big'),('rb','.info_reg'),('max_hold','.info_max_mochidama')]:
                elements = svg.find_elements(By.CSS_SELECTOR,selector)
                if not elements or not elements[0].text.strip():
                    return False
                values[name] = int(elements[0].text.strip().replace(',',''))
            label = svg.find_elements(By.CSS_SELECTOR,'.text-x-time text')
            if not label or label[0].text.strip() != row['day'].replace('-','/'):
                return False
            if any(values[k] != row[k] for k in values):
                raise ValueError(f'{row["rack"]}番台の一覧とグラフの数値が一致しません。更新中の可能性があります。')
            paths = svg.find_elements(By.CSS_SELECTOR,'.path-slump path')
            zero = svg.find_elements(By.CSS_SELECTOR,'.back-line-middle line')
            if len(paths) != 1 or len(zero) != 1:
                return False
            return dict(path=paths[0].get_attribute('d'), baseline=float(zero[0].get_attribute('y1')),source_url=d.current_url)
        return WebDriverWait(self.driver,25).until(ready)

    def run(self, url, target):
        machine = check_url(url)
        location = store_from_url(url)
        target_date = date.fromisoformat(target)
        if target_date >= date.today():
            raise ValueError('更新途中の混在を避けるため、前日以前を指定してください。')
        store = Store(self.folder / 'data' / 'database.sqlite3')
        output = None
        try:
            self.start()
            self.load(url)
            def available_dates(d):
                try:
                    selects = d.find_elements(By.TAG_NAME, 'select')
                    if not selects:
                        return False
                    options = [o.text.strip().replace('/','-') for o in Select(selects[0]).options]
                    return options if options else False
                except StaleElementReferenceException:
                    return False
            available = WebDriverWait(self.driver,30).until(available_dates)
            if target not in available:
                raise ValueError('指定日はサイトの日付選択にありません。')
            dates = sorted(d for d in available if (target_date-timedelta(days=30)).isoformat() <= d <= target)
            for day in dates:
                self.log(f'{machine} / {day} の一覧を取得しています。')
                rows = self.get_table(day, machine, location)
                store.save(rows)
                self.log(f'{len(rows)}台を保存しました。')
            target_rows = store.rows(target,machine,location)
            for i, row in enumerate(target_rows,1):
                if self.stop.is_set():
                    raise InterruptedError('停止しました。')
                self.log(f'グラフ {i}/{len(target_rows)}：{row["rack"]}番台')
                graph = self.get_graph(row)
                from core import graph_metrics
                graph_metrics(graph['path'],graph['baseline'])
                store.save([dict(row,graph=graph)])
            output, results = report(store,target,machine,self.folder/'reports',location)
            self.log(f'完了：{len(results)}台。総合点確定 {sum(r["score"]["total"] is not None for r in results)}台。')
            self.log(str(output))
            return output
        finally:
            if store.rows(target,machine,location) and output is None:
                output, _ = report(store,target,machine,self.folder/'reports',location)
                self.log('途中結果：'+str(output))
            store.close()
            if self.driver:
                self.driver.quit()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--url',default=DEFAULT_URL)
    parser.add_argument('--date',default=(date.today()-timedelta(days=1)).isoformat())
    args = parser.parse_args()
    Collector(Path(__file__).parent).run(args.url,args.date)
