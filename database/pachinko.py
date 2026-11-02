"""メルヘンの4円パチンコの手動取り込み（PC版だけ、2026-10-12）。

利用者「10月10日…末尾0のパチンコ台が異常に回されてて、もしかしたらすごい回転率がよかったのかもしれない。
10日、20日、30日のデータを集めていきたい」「その日1日で10台くらいしか取り込まない。なので、自動とかはいりません」
「4円ぱちんこだけ」「ＰＣ版だけでいいです」。

- 取り込み用ブラウザの「この画面を取り込む」を、パチンコの台一覧（見出し「台番号・大当り・大当り確率・総回転数」）と
  台のページ（スロットと同じ作りのスランプグラフ）で押したときに使う。自動取り込み・次の台への移動はしない。
- 記録はスロットと別のファイル（data/pachinko.sqlite3）に置く。スロットの採点・ランキング・バラエティ🌈・
  進み具合・閲覧ページには混ぜない。
- 台のページの数字（初当り・最大連チャン数など）と当り履歴は、ページの見え方を確かめていないため、ページの文字
  （page_text）をそのまま残し、読めた数字だけ panel に入れる。あとで回転率の推定などに使う。
- 保存のたびに、全部の記録を pachinko-records.json に書き出す（同期フォルダがあればそこにも複製）。
"""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
from datetime import date, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

DB_NAME = 'pachinko.sqlite3'
EXPORT_NAME = 'pachinko-records.json'
# パチンコの台一覧の見出し（2026-10-12、幸町の e東京喰種MW の台一覧で確認）。
PACHI_HEADERS = ['台番号', '大当り', '大当り確率', '総回転数']
# 台のページで数字を読む見出し（ページの文字で、見出しの次に出る数字）。
PANEL_LABELS = ('大当り確率', '大当り', '総回転数', 'スタート', '初当り', '最大連チャン数', '1セット最大出玉',
                '最大持玉', '差玉', '前日最終スタート')
PAGE_TEXT_LIMIT = 20000
# 取り込む末尾（2026-10-12 利用者「末尾0しか取り込まないし、見ない」→「月と日付が重なる日が強いってことみたいだ。
# 10/10 11/11みたいなね。なので取り込む末尾を毎月変えたいから取り込む末尾選択ボタンが欲しい」）。
# settings.json の pachinko_tail：'month'（月に合わせる：10月→0、11月→1、12月→2、1月→1）か '0'〜'9'。既定は 'month'。
TAIL_SETTING = 'pachinko_tail'
# 店のパチンコの最後の台番号（2026-10-12 利用者「389番台までパチンコあります」＝幸町）。次の末尾の台へ進むのはここまで。
# 書いていない店は、取り込んで分かっている一番後ろの台まで。
LAST_RACK = {'saiwaichou': 389}
TAIL_MONTH = 'month'


def tail_for(day, setting=TAIL_MONTH):
    """[day] に取り込む末尾（0〜9）。"""
    if isinstance(setting, int) or (isinstance(setting, str) and setting.isdigit() and len(setting) == 1):
        return int(setting) % 10
    return int(str(day)[5:7]) % 10


def capture_tail(slot_db_path, day):
    """PC版で選んだ取り込む末尾（settings.json の pachinko_tail）で、[day] の末尾。"""
    from core import load_settings
    return tail_for(day, load_settings(Path(slot_db_path).parent).get(TAIL_SETTING, TAIL_MONTH))


class PachinkoError(ValueError):
    pass


def now_stamp():
    return datetime.now().astimezone().isoformat(timespec='seconds')


def _clean(text):
    return re.sub(r'[\s▲▼△▽⇧⇩]', '', str(text or ''))


def is_pachinko_table(matrix):
    """表の見出しがパチンコの台一覧か。"""
    return bool(matrix) and [_clean(c) for c in matrix[0]] == PACHI_HEADERS


def _int(text):
    text = str(text or '').replace(',', '').strip()
    return int(text) if re.fullmatch(r'-?\d+', text) else None


def parse_pachinko_table(payload):
    """台一覧の表（取り込みカードのJSが返す matrix・links）から台の行を作る。台番号の重複・読めない台番号は止める。"""
    from core import STORE_NAMES, normalize_machine_name
    location = payload.get('store')
    if location not in STORE_NAMES:
        raise PachinkoError('対象外の店舗のページです。長町南店・幸町店の一覧を開いてください。')
    machine = normalize_machine_name(payload.get('machine'))
    if not machine:
        raise PachinkoError('機種名を取得できません。機種別の台一覧を表示してください。')
    day = payload.get('target_date') or payload.get('day')
    try:
        day = date.fromisoformat(day).isoformat()
    except (TypeError, ValueError):
        raise PachinkoError('日付を特定できません。日付を選んでから取り込んでください。') from None
    matrix, links = payload.get('matrix') or [], payload.get('links') or []
    if not is_pachinko_table(matrix):
        raise PachinkoError('パチンコの台一覧の表ではありません。')
    rows, seen = [], set()
    for i, cells in enumerate(matrix[1:]):
        cells = list(cells) + [''] * (4 - len(cells))
        rack = _int(cells[0])
        if rack is None:
            raise PachinkoError(f'{i + 1}行目の台番号を読めません：{cells[0]!r}')
        if rack in seen:
            raise PachinkoError(f'{rack}番台が表に2回あります。ページを読み込み直してください。')
        seen.add(rack)
        probability = str(cells[2] or '').strip()
        rows.append(dict(store=location, day=day, machine=machine, rack=rack,
                         hits=_int(cells[1]), probability=probability or None, games=_int(cells[3]),
                         detail_url=links[i] if i < len(links) else None))
    if not rows:
        raise PachinkoError('台が1台もありません。')
    return rows, day, machine


# 7セグ表示の背景（消えている桁）。ページの文字では見出しと数字の間に「88888」「888888」「8/8888.8」が入る
# （2026-10-12、幸町の80番台を取り込んだ page_text で確認）。
_GHOST = re.compile(r'8{5,}|8/8{4}\.8')
_VALUE = re.compile(r'-?\d+(?:\.\d+)?|1/\d+(?:\.\d+)?')
_DAY_HEAD = re.compile(r'(\d{4})/(\d{2})/(\d{2})\s*\(')


def _lines(text):
    return [line.replace('\xa0', ' ').strip() for line in str(text or '').splitlines()]


def panel_numbers(text):
    """台のページの文字から、見出しの数字を読む（最初の＝その日の欄だけ。値が空の見出しは入れない）。
    例：「大当り\n88888\n12\n大当り確率\n8/8888.8\n1/ 222.8」→ {'大当り': '12', '大当り確率': '1/222.8'}。"""
    lines = [line for line in _lines(text) if line]
    result = {}
    for i, line in enumerate(lines):
        label = _clean(line)
        if label not in PANEL_LABELS or label in result:
            continue
        j = i + 1
        if j < len(lines) and _GHOST.fullmatch(lines[j]):
            j += 1   # 7セグの背景を飛ばす
        value = lines[j].replace(',', '').replace(' ', '') if j < len(lines) else ''
        if _VALUE.fullmatch(value):
            result[label] = value
    return result


def hit_history(text, day):
    """当り履歴の [day] の欄：当りごとの（連チャン数, その当りまでの回転数）。表示どおりの順。欄が無ければ None。
    ページの文字では、日付の見出しのあとに目盛り（10〜1）、そのあと「連チャン数」「回転数」が当りごとに並ぶ。"""
    lines = _lines(text)
    try:
        start = lines.index('当り履歴')
    except ValueError:
        return None
    end = next((i for i in range(start, len(lines)) if lines[i] == 'グラフ表示'), len(lines))
    want = tuple(day.split('-'))
    head = next((i for i in range(start, end)
                 if (m := _DAY_HEAD.match(lines[i])) and m.groups() == want), None)
    if head is None:
        return None
    tokens = []
    for line in lines[head + 1:end]:
        if _DAY_HEAD.match(line):
            break
        if line:
            tokens.append(line)
    if tokens[:10] == [str(n) for n in range(10, 0, -1)]:
        tokens = tokens[10:]   # 目盛り
    numbers = [int(t) for t in tokens if re.fullmatch(r'\d+', t)]
    if len(numbers) % 2:
        return None
    return [dict(chain=numbers[i], games=numbers[i + 1]) for i in range(0, len(numbers), 2)]


class PachinkoStore:
    def __init__(self, path):
        self.path = Path(path)
        self.db = sqlite3.connect(str(self.path))
        self.db.execute('CREATE TABLE IF NOT EXISTS racks (store TEXT NOT NULL, day TEXT NOT NULL, rack INTEGER NOT NULL,'
                        ' machine TEXT, payload TEXT NOT NULL, PRIMARY KEY(store, day, rack))')
        self.db.commit()

    def close(self):
        self.db.close()

    def get(self, store, day, rack):
        found = self.db.execute('SELECT payload FROM racks WHERE store=? AND day=? AND rack=?',
                                (store, day, int(rack))).fetchone()
        return json.loads(found[0]) if found else None

    def save(self, row):
        """1台を保存する。前の記録の項目（グラフなど）は残し、新しい値で上書きする。"""
        merged = dict(self.get(row['store'], row['day'], row['rack']) or {})
        merged.update({k: v for k, v in row.items() if v is not None})
        self.db.execute('INSERT OR REPLACE INTO racks(store, day, rack, machine, payload) VALUES (?,?,?,?,?)',
                        (merged['store'], merged['day'], int(merged['rack']), merged.get('machine'),
                         json.dumps(merged, ensure_ascii=False)))
        return merged

    def commit(self):
        self.db.commit()

    def rows(self):
        return [json.loads(p) for (p,) in self.db.execute('SELECT payload FROM racks ORDER BY store, day, rack')]


def db_path_for(slot_db_path):
    return Path(slot_db_path).parent / DB_NAME


def export_records(store, data_dir):
    """全部の記録を pachinko-records.json に書き、同期フォルダがあれば複製する。失敗しても保存は止めない。"""
    from core import load_settings
    try:
        local = Path(data_dir) / EXPORT_NAME
        document = dict(format='database-pachinko', version=1, exported_at=now_stamp(), records=store.rows())
        temporary = local.with_suffix('.tmp')
        temporary.write_text(json.dumps(document, ensure_ascii=False), encoding='utf-8')
        temporary.replace(local)
        from core import resolve_sync_dir
        folder = resolve_sync_dir(data_dir)
        if folder and Path(folder).is_dir():
            shutil.copyfile(local, Path(folder) / EXPORT_NAME)
        return local
    except (OSError, ValueError):
        return None


def has_graph(row):
    return bool(row and row.get('graph_measurement'))


def is_tail(rack, tail):
    """末尾 [tail] の台か。"""
    return int(rack) % 10 == int(tail)


def with_rack(url, rack, day):
    """台のページのURLの台番号（rack_no）と日付（target_date）を差し替える。"""
    parsed = urlparse(url or '')
    if not parsed.scheme or not parsed.netloc:
        return None
    query = parse_qs(parsed.query, keep_blank_values=True)
    query['rack_no'] = [str(rack)]
    query['target_date'] = [day]
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True), fragment=''))


def last_rack(store, location):
    """その店のパチンコの最後の台番号（[LAST_RACK]、無ければ取り込んで分かっている一番後ろ）。"""
    known = [int(r['rack']) for r in store.rows() if r['store'] == location]
    if location in LAST_RACK:
        return max([LAST_RACK[location], *known])
    return max(known) if known else None


def next_tail(store, location, day, after_rack, tail, page_url=None):
    """[after_rack] より後で、グラフがまだの末尾 [tail] の台（番号, URL）。無ければ (None, None)。
    その店のパチンコの最後の台（[last_rack]、幸町は389）までを、10ずつ見る（110→120→130）。
    台一覧に無い台も、台のページのURLの台番号を差し替えて開く（台のページだけで保存できる）。"""
    limit = last_rack(store, location)
    if limit is None:
        return None, None
    rack = int(after_rack) // 10 * 10 + int(tail)
    if rack <= int(after_rack):
        rack += 10
    while rack <= limit:
        row = store.get(location, day, rack)
        if not has_graph(row):
            url = with_rack(page_url, rack, day) if page_url else None
            return rack, url or (row or {}).get('detail_url')
        rack += 10
    return None, None


def missing_tails(store, location, day, tail):
    """台一覧にある、グラフがまだの末尾 [tail] の台番号（小さい順）。"""
    return sorted(int(r['rack']) for r in store.rows()
                  if r['store'] == location and r['day'] == day and is_tail(r['rack'], tail) and not has_graph(r))


def save_table(payload, slot_db_path):
    """台一覧を保存して、（利用者への一言, 次に開くURL）を返す。次は、この台一覧の取り込む末尾でグラフがまだの最初の台。"""
    rows, day, machine = parse_pachinko_table(payload)
    store = PachinkoStore(db_path_for(slot_db_path))
    try:
        stamp = now_stamp()
        for row in rows:
            store.save(dict(row, kind_code=payload.get('kind_code'), source_url=payload.get('source_url'),
                            captured_at=stamp))
        store.commit()
        export_records(store, Path(slot_db_path).parent)
        location = rows[0]['store']
        tail = capture_tail(slot_db_path, day)
        target = next((r for r in sorted(rows, key=lambda r: r['rack'])
                       if is_tail(r['rack'], tail) and not has_graph(store.get(location, day, r['rack']))), None)
    finally:
        store.close()
    message = f'パチンコ {machine}（{day}）{len(rows)}台を保存しました。'
    if target and target.get('detail_url'):
        return message + f"末尾{tail}の{target['rack']}番台へ移動します。", target['detail_url']
    return message + f'この台一覧の末尾{tail}の台は、グラフまで取り込み済みです。', None


def is_pachinko_page(payload):
    """台のページがパチンコの台のページか（スロットには無い「初当り」「当り履歴」がある）。"""
    text = str(payload.get('page_text') or '')
    return '初当り' in text and '当り履歴' in text and '大当り確率' in text


def machine_from_page(text):
    """台のページの機種名：前後の台へのボタン（「79番台」など）のすぐ前の行。"""
    lines = [line for line in _lines(text) if line]
    for i, line in enumerate(lines):
        if re.fullmatch(r'\d+番台', line) and i:
            return lines[i - 1]
    return None


def graph_target(payload, slot_db_path):
    """台のページの送信が、パチンコの台か（その記録。台一覧に無くてもパチンコの台のページなら、ページから作った行）。
    パチンコでなければ None。"""
    rack, location = payload.get('rack'), payload.get('store')
    try:
        day = date.fromisoformat(payload.get('target_date') or payload.get('day') or '').isoformat()
    except ValueError:
        return None
    if rack is None or not location:
        return None
    path = db_path_for(slot_db_path)
    if path.is_file():
        store = PachinkoStore(path)
        try:
            found = store.get(location, day, int(rack))
        finally:
            store.close()
        if found:
            return found
    if not is_pachinko_page(payload):
        return None
    from core import STORE_NAMES, normalize_machine_name
    if location not in STORE_NAMES:
        return None
    machine = normalize_machine_name(machine_from_page(payload.get('page_text')))
    return dict(store=location, day=day, rack=int(rack), machine=machine or None, from_page=True)


def save_graph(payload, slot_db_path, measurement):
    """台のページ（グラフ・数字・ページの文字）を、その台の記録に足して、（利用者への一言, 次に開くURL）を返す。
    measurement はスロットと同じ形のグラフの記録（browser_import.graph_measurement_result）。
    次は、この台より後の取り込む末尾でグラフがまだの台（末尾0なら110→120）。"""
    target = graph_target(payload, slot_db_path)
    if target is None:
        raise PachinkoError('先にこの日付・店舗のパチンコの台一覧を取り込んでください。')
    text = str(payload.get('page_text') or '')[:PAGE_TEXT_LIMIT]
    panel = panel_numbers(text)
    history = hit_history(text, target['day'])
    info = payload.get('info') if isinstance(payload.get('info'), dict) else {}
    row = dict(store=target['store'], day=target['day'], rack=target['rack'], machine=target.get('machine'),
               graph_measurement=measurement, page_text=text, panel=panel, info=info, hit_history=history,
               graph_games=_int(payload.get('games')), max_hold=_int(payload.get('max_hold')),
               graph_source_url=payload.get('source_url'), graph_captured_at=now_stamp())
    if target.get('from_page'):
        # 台一覧を取り込んでいない台：ページの数字で台一覧の分も埋める。
        row.update(hits=_int(panel.get('大当り')), probability=panel.get('大当り確率'),
                   games=_int(panel.get('総回転数')), detail_url=payload.get('source_url'), from_page=True)
    store = PachinkoStore(db_path_for(slot_db_path))
    try:
        store.save(row)
        store.commit()
        export_records(store, Path(slot_db_path).parent)
        tail = capture_tail(slot_db_path, target['day'])
        rack, url = next_tail(store, target['store'], target['day'], target['rack'], tail, payload.get('source_url'))
        left = [r for r in missing_tails(store, target['store'], target['day'], tail) if r < int(target['rack'])]
        # 飛ばした台（グラフまで済んでいた末尾の台）。黙って飛ぶと分からないため知らせる（2026-10-12 利用者
        # 「100の次がいきなり300にとんでしかも320で終わったんだけどなにこれ」）。
        first = int(target['rack']) // 10 * 10 + int(tail)
        if first <= int(target['rack']):
            first += 10
        end = last_rack(store, target['store'])
        last = (rack - 10) if rack is not None else (end if end is not None else first - 10)
        skipped = [r for r in range(first, last + 1, 10) if has_graph(store.get(target['store'], target['day'], r))]
    finally:
        store.close()
    read = [f'{k}{v}' for k, v in panel.items() if k in ('初当り', '最大連チャン数', '最大持玉')]
    if history:
        read.append(f'当り履歴{len(history)}回')
    message = (f"パチンコ {target['rack']}番台（{target['day']}）を保存しました"
               + (f"（{'・'.join(read)}）。" if read else '。'))
    if skipped:
        span = f'{skipped[0]}番台' if len(skipped) == 1 else f'{skipped[0]}〜{skipped[-1]}番台'
        message += f'{span}は取り込み済みなので飛ばしました。'
    if rack is not None:
        message += f'次の末尾{tail}、{rack}番台へ移動します。'
    else:
        message += (f'末尾{tail}の台はここまでです（パチンコの一番後ろは{end}番台）。'
                    if end is not None else f'末尾{tail}の台はここまでです。')
        if left:
            message += f"まだの末尾{tail}：{'・'.join(f'{r}番台' for r in left)}。"
    return message, url
