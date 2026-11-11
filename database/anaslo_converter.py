"""Offline HTML-to-backup service shared by the separate desktop converter.

Never opens a writable application database. Native MY/URLs are not fabricated.
"""
from collections import Counter
from contextlib import closing
from datetime import datetime
from difflib import SequenceMatcher
import json
import math
from pathlib import Path
import re
import sqlite3
import unicodedata

import anaslo_net
from anaslo_html import convert, set_rate
from anaslo_index import HALL_NAMES, HALLS, P_STATION, SAIWAICHOU

SHOP = 'c740601'
SHOP_NAME = P_STATION.source_name


def normalized(name):
    text = unicodedata.normalize('NFKC', name).strip()
    text = re.sub(r'^(?:スマスロ\s*|LB\s*|L(?=[\sァ-ヶぁ-ん一-龯])\s*)', '', text)
    return re.sub(r'[^\w]', '', text.casefold())


def read_catalog(path):
    path = Path(path)
    if not path.is_file():
        return []
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        return [json.loads(row[0]) for row in db.execute('SELECT payload FROM machines')]


def suggestions(name, catalog, rate='20'):
    names = sorted({m['machine'] for m in catalog if m['store'] == SHOP and m['rate'] == rate})
    key = normalized(name)
    exact = [n for n in names if normalized(n) == key]
    candidates = sorted(names, key=lambda n: (-SequenceMatcher(None, key, normalized(n)).ratio(), n))[:5]
    return {'automatic': exact[0] if len(exact) == 1 else None, 'candidates': candidates}


def analyze(paths, rate='20', cache_dir=None):
    """``rate`` is the user-confirmed P-STATION rate. 幸町 goes to the meruhen
    DB (1000円46枚 only), so no rate is attached there.
    ``cache_dir``：解析結果の控えの置き場（変換アプリ。anaslo_html.parse_cached）。"""
    staging = convert(paths, cache_dir=cache_dir)
    names = {d['store']['source_name'] for d in staging['days']}
    halls = [h for h in HALLS if h.source_name in names]
    if len(halls) != len(names):
        raise ValueError(f'現在は{HALL_NAMES}のHTMLだけに対応しています。')
    if len(halls) != 1:
        raise ValueError('1回に変換できるのは1店舗のHTMLだけです。店舗ごとに選び直してください。')
    if halls[0] is P_STATION:
        # 解析し直さず、1回目の結果に貸玉を付ける（2026-11-06。以前は全ファイルを2回解析していた）。
        set_rate(staging, rate)
    staging['hall'] = halls[0].key
    return staging


def read_native_occupied(path):
    """P’s CUBE で実際に取った台・日（アナスロの補完でないもの）。読み取りだけ。"""
    path = Path(path)
    if not path.is_file():
        return frozenset()
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        rows = db.execute("SELECT json_extract(payload, '$.day'), json_extract(payload, '$.rack') FROM records "
                          "WHERE json_extract(payload, '$.store')=? AND json_extract(payload, '$.rate')='20' "
                          "AND COALESCE(json_extract(payload, '$.source_site'), '')<>'anaslo'", (SHOP,)).fetchall()
    return frozenset((day, int(rack)) for day, rack in rows if isinstance(day, str) and rack is not None)


def make_backup(staging, mapping, catalog, native=frozenset()):
    """Mapping entries are explicitly chosen names; None means omit this machine.

    ``native``：P’s CUBE の実データがある (日, 台番号)。取り込みでも飛ばされる（実データを優先）ので、
    JSON に入れない（2026-11-06。36日分で10,620件のうち大半がこれだった）。アナスロの補完どうしは
    今までどおり入れる（後から付けた推定差枚を取り込みで移すため）。"""
    from pscube_import import _validate_machine, _validate_record, is_excluded_machine
    if staging.get('format') != 'anaslo-hall-staging' or staging.get('version') != 1:
        raise ValueError('解析結果の形式が違います。')
    machines, records, skipped = {}, [], Counter()
    occupied = set()
    for d in staging['days']:
        if d['store']['source_name'] != SHOP_NAME or d['store']['rate'] is None:
            raise ValueError('店舗・貸玉を確認してください。')
        rate = d['store']['rate']
        known = {m['machine']: m for m in catalog if m['store'] == SHOP and m['rate'] == rate}
        for source in d['records']:
            name = source['machine']
            if is_excluded_machine(name):
                skipped['excluded'] += 1
                continue
            if name not in mapping:
                raise ValueError(f'機種名の対応を確認してください：{name}')
            target = mapping[name]
            if target is None:
                skipped['manual'] += 1
                continue
            if not isinstance(target, str) or not target.strip() or is_excluded_machine(target):
                raise ValueError(f'対応する機種名が不正です：{name}')
            target = target.strip()
            if (d['day'], source['rack']) in native:
                skipped['existing'] += 1
                continue
            key = (SHOP, rate, target)
            if key not in machines:
                # Use real catalog URLs only; source-only machines are never capture targets.
                machines[key] = dict(known[target]) if target in known else {
                    'store': SHOP, 'rate': rate, 'machine': target, 'url': None,
                    'expected_count': None, 'machine_type': None, 'source_site': 'anaslo'}
            identity = (SHOP, rate, source['rack'], d['day'])
            if identity in occupied:
                raise ValueError('同じ日付・台番号が重複しています。')
            occupied.add(identity)
            records.append({'store': SHOP, 'rate': rate, 'machine': target, 'rack': source['rack'],
                            'day': d['day'], 'games': source['games'], 'bb': source['bb'],
                            'rb': source['rb'], 'at_art': source['at_art'], 'my': None,
                            'detail_url': None, 'observed_at': None, 'net_medals': None, 'graph': None,
                            'source_site': 'anaslo', 'source_url': d['source']['url'],
                            'source_sha256': d['source']['sha256'], 'source_machine': name,
                            'source_probabilities': source['probabilities'], 'source_graph': source['graph']})
            # 推定差枚（anaslo_net.py、2026-11-06）。付けられない台（AT機などの確かでない台・式の無い機種）は付けない。
            guess = anaslo_net.estimate(records[-1])
            if guess:
                records[-1]['net_estimate'] = guess
    if not records:
        raise ValueError('出力対象のデータがありません（P’s CUBEに実データがある日付・台、または対象外だけでした）。'
                         if skipped.get('existing') else '出力対象のデータがありません。')
    for m in machines.values():
        _validate_machine(m)
    for r in records:
        _validate_record(r)
    return {'format': 'pscube-viewer', 'version': 1, 'kind': 'backup',
            'source': 'anaslo-converter', 'import_mode': 'fill_missing',
            'machines': list(machines.values()), 'records': records, 'rack_captures': [],
            'conversion_summary': {'records': len(records), 'skipped': dict(skipped)}}


def save_backup(path, payload):
    """Exclusive creation prevents silently overwriting another backup."""
    text = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    with Path(path).open('x', encoding='utf-8') as stream:
        stream.write(text)


# --- 幸町（メルヘン用DB）-------------------------------------------------------

MERUHEN_STORE = SAIWAICHOU.key


_SERIES_WORDS = r'(?:スマスロ|パチスロ|スロット)'


def _plain(name):
    return re.sub(r'[^\w]', '', unicodedata.normalize('NFKC', name).casefold())


def _plain_source(name):
    """Ana-slo name without 'スマスロ' / a leading 'L' before kana."""
    return re.sub(r'^l(?=[^a-z0-9])', '', re.sub('^' + _SERIES_WORDS, '', _plain(name)))


def _same_apart_from_decorations(source_key, candidate):
    """Meruhen spells names like '★L／いざ番長／SB8' or 'SマイジャグラーVKD':
    an L/S/LB/SB prefix, an optional series word and a short trailing code."""
    return bool(source_key) and re.fullmatch(
        r'(?:lb|sb|l|s)?' + _SERIES_WORDS + '?' + re.escape(source_key) + r'[a-z0-9]{0,6}',
        _plain(candidate)) is not None


def read_meruhen_catalog(path, store=MERUHEN_STORE):
    """Read-only: saved (day, machine, rack) of one meruhen store."""
    from core import is_hidden_machine, normalize_machine_name
    path = Path(path)
    if not path.is_file():
        return MeruhenCatalog(store, [])
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        rows = db.execute("SELECT day, machine, rack, json_extract(payload, '$.source_site') FROM days WHERE store=?",
                          (store,)).fetchall()
    return MeruhenCatalog(store, [(d, normalize_machine_name(m), int(r), site) for d, m, r, site in rows
                                  if not is_hidden_machine(store, m)])


class MeruhenCatalog:
    def __init__(self, store, rows):
        """``rows``: (day, machine, rack[, source_site]) of saved records."""
        self.store = store
        self.occupied = {(day, rack) for day, _, rack, *_ in rows}
        self.names = sorted({name for _, name, _, *_ in rows})
        self.racks = {}
        self.native = {}  # Names the meruhen site itself gave each rack.
        for _, name, rack, *site in rows:
            self.racks.setdefault(rack, Counter())[name] += 1
            if not site or site[0] != 'anaslo':
                self.native.setdefault(rack, Counter())[name] += 1

    def rack_spelling(self, rack, name):
        """Meruhen marks some racks of a machine with ★ (2026-10-17：海門決戦は1278番台だけ★).
        Use the spelling meruhen itself saved on this rack, or the history splits."""
        same = [(count, n) for n, count in self.native.get(rack, {}).items() if _plain(n) == _plain(name)]
        return max(same)[1] if same else name

    def suggestions(self, name, racks=()):
        """Name candidates; names saved on the same racks come first.

        Automatic only when two independent signals agree on one name: the
        names match apart from meruhen's decorations (★, L/S prefix, a short
        trailing code), and that name was saved on one of the same racks."""
        key = _plain_source(name)
        on_racks = Counter()
        for rack in racks:
            on_racks.update(self.racks.get(rack, {}))
        matched = [n for n in self.names if _same_apart_from_decorations(key, n)]
        # Spellings that differ only by symbols (e.g. a leading ★) are one machine:
        # take the one saved most often on these racks.
        spelled = [n for n in matched if n in on_racks]
        automatic = (max(spelled, key=lambda n: (on_racks[n], n))
                     if spelled and len({_plain(n) for n in matched}) == 1 else None)
        by_rack = [n for n, _ in sorted(on_racks.items(), key=lambda item: (-item[1], item[0]))]
        similar = sorted(self.names, key=lambda n: (-SequenceMatcher(None, key, _plain(n)).ratio(), n))[:5]
        return {'automatic': automatic, 'candidates': list(dict.fromkeys([*matched, *by_rack, *similar]))[:8]}


# メルヘンのグラフの座標（core.py の推定差枚と同じ）：ゼロ線200.5、片側180px＝軸の段階 R 枚。
_MERUHEN_ZERO_Y, _MERUHEN_HALF = 200.5, 180.0
# アナスロのグラフは同じホールのグラフを片側1000に引き伸ばしたもの（2026-10-17、ジャグラー
# オンラインの差枚で8日分4,000台中3,821台が「終点×R÷1000」と一致）。
_ANASLO_HALF = 1000.0


def graph_measurement_from_source(graph):
    """アナスロのグラフ → メルヘンと同じ座標の測定値（max_hold が無いので差枚は推定されない）。

    縮尺 R が分からなくても、終点のプラス・マイナス、維持率（終点÷山）、バラエティの終わり方は
    メルヘンと同じに決まる（2026-10-17：重なる日でそれぞれ728/728・728/728・315/317台一致）。"""
    if not isinstance(graph, dict) or graph.get('kind') != 'source_coordinates':
        return None
    try:
        zero = float(graph.get('zero_y', 0.0))
        points = [(float(x), float(y) - zero) for x, y in graph['points']]
    except (KeyError, TypeError, ValueError):
        return None
    if len(points) < 2 or any(not (math.isfinite(x) and math.isfinite(y)) for x, y in points):
        return None
    if any(abs(y) > _ANASLO_HALF * 1.05 for _, y in points):
        return None  # 枠の外の値は想定外（推測で縮めない）
    to_px = lambda y: round(_MERUHEN_ZERO_Y - y * _MERUHEN_HALF / _ANASLO_HALF, 3)
    start = (points[0][0], 0.0)
    peak = max([start, *points], key=lambda p: p[1])
    trough = min([start, *points], key=lambda p: p[1])
    return {'baseline_x': points[0][0], 'baseline_y': _MERUHEN_ZERO_Y,
            'peak_x': peak[0], 'peak_y': to_px(peak[1]), 'trough_x': trough[0], 'trough_y': to_px(trough[1]),
            'end_x': points[-1][0], 'end_y': to_px(points[-1][1]),
            'curve': [[x, to_px(y)] for x, y in points], 'method': 'anaslo-source-graph'}


def make_meruhen_backup(staging, mapping, catalog):
    """Meruhen backup that only fills (day, rack) slots missing in the DB.

    The meruhen import never overwrites differing numbers either; skipping
    occupied slots here also avoids a second row under another machine name.
    Racks never saved in the meruhen DB are left out: the HTML has no rate,
    and that DB holds only 1000円46枚 slots."""
    from core import BACKUP_FORMAT, BACKUP_VERSION, _valid_backup_record, is_excluded_machine, normalize_machine_name
    if staging.get('format') != 'anaslo-hall-staging' or staging.get('version') != 1:
        raise ValueError('解析結果の形式が違います。')
    store = catalog.store
    records, skipped, occupied = [], Counter(), set()
    for d in staging['days']:
        if d['store']['source_name'] != SAIWAICHOU.source_name:
            raise ValueError('店舗を確認してください。')
        for source in d['records']:
            name = source['machine']
            if is_excluded_machine(store, name):
                skipped['excluded'] += 1
                continue
            if name not in mapping:
                raise ValueError(f'機種名の対応を確認してください：{name}')
            target = mapping[name]
            if target is None:
                skipped['manual'] += 1
                continue
            if not isinstance(target, str) or not target.strip() or is_excluded_machine(store, target):
                raise ValueError(f'対応する機種名が不正です：{name}')
            if source['rack'] not in catalog.racks:
                skipped['unknown_rack'] += 1
                continue
            identity = (d['day'], source['rack'])
            if identity in catalog.occupied:
                skipped['existing'] += 1
                continue
            if identity in occupied:
                raise ValueError('同じ日付・台番号が重複しています。')
            occupied.add(identity)
            record = {'store': store, 'kind_code': 21, 'day': d['day'],
                      'machine': catalog.rack_spelling(source['rack'], normalize_machine_name(target)),
                      'rack': source['rack'],
                      'games': source['games'], 'bb': source['bb'], 'rb': source['rb'], 'max_hold': None,
                      'source_site': 'anaslo', 'source_url': d['source']['url'],
                      'source_sha256': d['source']['sha256'], 'source_machine': name,
                      'source_probabilities': source['probabilities'], 'source_graph': source['graph']}
            measurement = graph_measurement_from_source(source['graph'])
            if measurement:
                record['graph_measurement'] = measurement
            if not _valid_backup_record(record):
                raise ValueError(f'{source["rack"]}番台の数値を確認してください。')
            records.append(record)
    if not records:
        raise ValueError('出力対象のデータがありません（databaseに保存済みの日付・台、または対象外だけでした）。')
    return {'format': BACKUP_FORMAT, 'version': BACKUP_VERSION, 'source': 'anaslo-converter',
            'exported_at': datetime.now().astimezone().isoformat(timespec='seconds'), 'records': records,
            'conversion_summary': {'records': len(records), 'skipped': dict(skipped)}}


# --- 幸町のノーマルタイプ分析用（2026-10-17）---------------------------------------
# 利用者「古い記録は今からやってもらうデータ処理用で、jsonファイルを作る際にノーマルタイプの
# ジャグラーシリーズハナハナシリーズしか作成せず、共有に載せない処理をしてほしい」。
# databaseには読み込まない別の形式にする（バックアップの読み込み・同期フォルダの自動取り込みは
# format が違うと拒否する）。共有・閲覧・採点・翌日候補には一切入らず、AIの傾向分析だけが読む。

NORMAL_ANALYSIS_FORMAT = 'database-normal-analysis'
NORMAL_SERIES = ('ジャグラー', 'ハナハナ')


def is_normal_type(name):
    """ジャグラーシリーズ・ハナハナシリーズ（半角・全角の違いは無視）。"""
    text = unicodedata.normalize('NFKC', str(name or ''))
    return any(word in text for word in NORMAL_SERIES)


def make_normal_analysis(staging, mapping=None):
    """幸町のHTMLから、ジャグラー・ハナハナの台だけを分析用に取り出す。

    databaseの保存済みの日付・台や、記録のない台番号も除かない（分析には全台が要る）。
    機種名は、対応表で決まっていればdatabaseの表記も添える（設定推定の機種の判定に使う）。
    対応を決めていない機種があっても作れる。"""
    from core import normalize_machine_name
    if staging.get('format') != 'anaslo-hall-staging' or staging.get('version') != 1:
        raise ValueError('解析結果の形式が違います。')
    names = {d['store']['source_name'] for d in staging['days']}
    halls = [h for h in HALLS if h.source_name in names]
    if len(names) != 1 or len(halls) != 1:
        raise ValueError('ノーマルタイプの分析用は、幸町かP-STATIONの1店舗のHTMLだけに対応しています。')
    hall = halls[0]
    pstation = hall is P_STATION
    mapping = mapping or {}
    records, days, others = [], [], 0
    for d in staging['days']:
        days.append(d['day'])
        for source in d['records']:
            name = source['machine']
            target = mapping.get(name)
            if not (is_normal_type(name) or is_normal_type(target)):
                others += 1
                continue
            record = {'store': hall.key, 'day': d['day'], 'rack': source['rack'],
                      'machine': normalize_machine_name(target) if isinstance(target, str) and target.strip() else name,
                      'source_machine': name, 'games': source['games'], 'bb': source['bb'], 'rb': source['rb'],
                      'source_probabilities': source['probabilities'],
                      'source_url': d['source']['url'], 'source_sha256': d['source']['sha256']}
            if pstation:
                # P-STATION（2026-11-11）。P’s CUBEの実データがある日・台も除かない（分析には全台が要る）。
                # 幸町と同じメルヘン座標の測定値にはしない：アナスロのグラフが「片側1000」の縮尺なのは幸町で
                # 確かめた事実で、P-STATIONは台ごとの段で決まる（anaslo_net.py）。原グラフを残し、
                # 推定差枚は補完用JSONと同じ式で付く台だけ付ける（確かでない台は sure=false）。
                record.update({'rate': d['store'].get('rate'), 'at_art': source.get('at_art'),
                               'source_site': 'anaslo', 'source_graph': source.get('graph')})
                guess = anaslo_net.estimate(record)
                if guess:
                    record['net_estimate'] = guess
            else:
                measurement = graph_measurement_from_source(source['graph'])
                if measurement:
                    record['graph_measurement'] = measurement
            records.append(record)
    if not records:
        raise ValueError('ジャグラー・ハナハナの台がありませんでした。')
    return {'format': NORMAL_ANALYSIS_FORMAT, 'version': 1, 'store': hall.key,
            'note': '分析用（ジャグラー・ハナハナだけ）。databaseには読み込まず、共有・採点・翌日候補には使わない。',
            'exported_at': datetime.now().astimezone().isoformat(timespec='seconds'),
            'days': sorted(days), 'records': records,
            'summary': {'records': len(records), 'days': len(days), 'other_machines': others}}


def normal_analysis_name(payload):
    days = [d.replace('-', '') for d in payload['days']]
    period = days[0] if len(days) == 1 else f'{days[0]}-{days[-1]}'
    return f'normal-analysis-{payload["store"]}-{period}.json'


def save_normal_analysis(folder, payload):
    """分析用ファイルを決まったフォルダへ保存する。同じ期間は作り直し（HTMLから毎回同じ内容になる）。"""
    from file_io import atomic_writer
    path = Path(folder) / normal_analysis_name(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    with atomic_writer(path) as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, allow_nan=False) + '\n')
    return path


OTHER_ANALYSIS_FORMAT = 'database-other-analysis'


def make_other_analysis(staging, mapping=None):
    """幸町のジャグラー・ハナハナ以外を分析専用に保存する。厳密なAT/ART分類ではない。

    通常の補完から除外した台・未登録の台も保持する。ART回数や縮尺不明の原グラフを残し、
    MY・差枚・最大持玉・観測時刻・貸玉は推測しない。既存のノーマル用JSONは変更しない。"""
    from core import normalize_machine_name
    if staging.get('format') != 'anaslo-hall-staging' or staging.get('version') != 1:
        raise ValueError('解析結果の形式が違います。')
    mapping = mapping or {}
    records, days, sources, normal_count = [], [], [], 0
    for d in staging['days']:
        if d['store']['source_name'] != SAIWAICHOU.source_name:
            raise ValueError('その他機種の分析用は、幸町のHTMLだけに対応しています。')
        days.append(d['day'])
        sources.append(dict(d['source'], day=d['day']))
        for source in d['records']:
            name = source['machine']
            target = mapping.get(name)
            if is_normal_type(name) or is_normal_type(target):
                normal_count += 1
                continue
            record = {'store': MERUHEN_STORE, 'day': d['day'], 'rack': source['rack'],
                      'machine': normalize_machine_name(target) if isinstance(target, str) and target.strip() else name,
                      'source_machine': name, 'games': source['games'], 'bb': source['bb'], 'rb': source['rb'],
                      'at_art': source.get('at_art'), 'my': source.get('my'), 'net_medals': source.get('net_medals'),
                      'max_hold': source.get('max_hold'), 'rate': d['store'].get('rate'),
                      'observed_at': d['source'].get('observed_at'), 'source_site': 'anaslo',
                      'source_probabilities': source['probabilities'], 'source_graph': source.get('graph'),
                      'source_url': d['source']['url'], 'source_sha256': d['source']['sha256']}
            measurement = graph_measurement_from_source(source.get('graph'))
            if measurement:
                record['graph_measurement'] = measurement
            records.append(record)
    if not records:
        raise ValueError('ジャグラー・ハナハナ以外の台がありませんでした。')
    return {'format': OTHER_ANALYSIS_FORMAT, 'version': 1, 'store': MERUHEN_STORE,
            'import_ready': False,
            'note': '分析用（ジャグラー・ハナハナ以外。他のAタイプも含む）。database・共有・採点・翌日候補には取り込まない。',
            'classification': 'source_machine または対応先の名称にジャグラー・ハナハナを含む台を除外。AT/ARTの確定分類ではない。',
            'exported_at': datetime.now().astimezone().isoformat(timespec='seconds'),
            'days': sorted(set(days)), 'sources': sources, 'records': records,
            'summary': {'records': len(records), 'days': len(set(days)), 'normal_records_excluded': normal_count}}


def save_other_analysis(folder, payload):
    """通常バックアップと別の名前・形式・保存先。出力は一時ファイルから置き換える。"""
    from file_io import atomic_writer
    if payload.get('format') != OTHER_ANALYSIS_FORMAT or payload.get('version') != 1:
        raise ValueError('その他機種の分析用ファイルの形式が違います。')
    days = sorted({d.replace('-', '') for d in payload['days']})
    period = days[0] if len(days) == 1 else f'{days[0]}-{days[-1]}'
    path = Path(folder) / f'other-analysis-{payload["store"]}-{period}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    with atomic_writer(path) as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, allow_nan=False) + '\n')
    return path


# --- 変換画面が店舗ごとに切り替える部分 --------------------------------------------

class PscubeTarget:
    """P-STATION → P’s CUBE用DB（既存の仕様のまま）。"""
    hall = P_STATION
    alias_file = 'machine_names.json'
    rate_text = '貸玉：20円'
    notice = ('P’s CUBEに実データがある日付・台は出力しません（既存の記録を優先）。MY・差枚は不明のまま保存します。\n'
              '沖ドキは既存ルールに従い対象外です。実DBへの反映はdatabaseの「バックアップを読み込む」で行います。')

    def __init__(self, data_dir):
        self.catalog = read_catalog(Path(data_dir) / 'pscube.sqlite3')
        self.native = read_native_occupied(Path(data_dir) / 'pscube.sqlite3')

    def names(self):
        return sorted({m['machine'] for m in self.catalog if m['store'] == SHOP and m['rate'] == '20'})

    def suggestions(self, name, racks=()):
        return suggestions(name, self.catalog)

    def excluded(self, name):
        from pscube_import import is_excluded_machine
        return is_excluded_machine(name)

    def make_backup(self, staging, mapping):
        return make_backup(staging, mapping, self.catalog, self.native)

    def file_name(self, period):
        return f'pscube-backup-anaslo-{period}.json'


class MeruhenTarget:
    """幸町 → メルヘン用DB。databaseに記録のある1000円46枚の台・未保存の日付だけを足す。"""
    hall = SAIWAICHOU
    alias_file = 'machine_names_saiwaichou.json'
    rate_text = '1000円46枚（databaseに記録のある台だけ）'
    notice = ('databaseに保存済みの日付・台は出力しません（既存の記録を優先）。最大持玉・グラフは不明のまま保存します。\n'
              'ブラックボード・沖ドキ・聖闘士星矢 海皇覚醒は既存ルールに従い対象外です。'
              '実DBへの反映はdatabaseの「バックアップを読み込む」で行います。')

    def __init__(self, data_dir):
        self.catalog = read_meruhen_catalog(Path(data_dir) / 'database.sqlite3', MERUHEN_STORE)

    def names(self):
        return list(self.catalog.names)

    def suggestions(self, name, racks=()):
        return self.catalog.suggestions(name, racks)

    def excluded(self, name):
        from core import is_excluded_machine
        return is_excluded_machine(MERUHEN_STORE, name)

    def make_backup(self, staging, mapping):
        return make_meruhen_backup(staging, mapping, self.catalog)

    def file_name(self, period):
        return f'database-backup-anaslo-{MERUHEN_STORE}-{period}.json'


TARGETS = {target.hall.key: target for target in (PscubeTarget, MeruhenTarget)}


# --- 取得期間の初期値（2026-11-06）----------------------------------------------------
# 11/5 から P’s CUBE の取り込みは PC がメインで、取れなかった日をアナスロで補うのが主な使い方。
# DB の台数が足りない日を読み取りだけで探し、取得画面の開始日・終了日に入れる。

def day_counts(hall_key, data_dir):
    """日ごとの台数（読み取りだけ）。P-STATION は P’s CUBE 用DB（アナスロの補完も数える）、幸町はメルヘン用DB。"""
    data_dir = Path(data_dir)
    if hall_key == P_STATION.key:
        path, sql, args = (data_dir / 'pscube.sqlite3',
                           "SELECT json_extract(payload, '$.day'), COUNT(*) FROM records "
                           "WHERE json_extract(payload, '$.store')=? AND json_extract(payload, '$.rate')='20' GROUP BY 1",
                           (SHOP,))
    elif hall_key == SAIWAICHOU.key:
        path, sql, args = data_dir / 'database.sqlite3', 'SELECT day, COUNT(*) FROM days WHERE store=? GROUP BY day', (MERUHEN_STORE,)
    else:
        return {}
    if not path.is_file():
        return {}
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        return {day: count for day, count in db.execute(sql, args) if isinstance(day, str)}


def suggest_period(hall_key, data_dir, folder, today=None, window=14):
    """直近 window 日（昨日まで）で台数が足りない日のうち、HTMLをまだ保存していない日の、いちばん新しい連続した
    範囲を返す。範囲の途中に要らない日を入れない（サイトへのアクセスを増やさない）。無ければ None。
    返り値：{'start', 'end', 'note'}。"""
    from datetime import date, timedelta
    from statistics import median
    today = today or date.today()
    days = [(today - timedelta(days=i)).isoformat() for i in range(1, window + 1)]
    counts = day_counts(hall_key, data_dir)
    seen = [counts[d] for d in days if counts.get(d)]
    if not seen:
        return None
    full = median(seen)
    short = [d for d in days if counts.get(d, 0) < full * 0.97]  # 台の入替の数台の差は数えない
    folder = Path(folder)
    saved = {d for d in short if any(folder.glob(f'{d}-{hall_key}-*.html'))}
    need = sorted(d for d in short if d not in saved)
    notes = []
    if saved:
        notes.append('HTML保存済みで変換だけで補える日：' + '・'.join(sorted(saved)))
    if not need:
        return {'start': None, 'end': None, 'note': '　'.join(notes)} if notes else None
    end = need[-1]
    start = end
    while (prev := (date.fromisoformat(start) - timedelta(days=1)).isoformat()) in need:
        start = prev
    others = [d for d in need if d < start]
    if others:
        notes.append('ほかに台数が足りない日：' + '・'.join(others))
    label = {P_STATION.key: 'P’s CUBE', SAIWAICHOU.key: 'database'}[hall_key]
    note = f'初期値は{label}の台数が足りない日（{start}〜{end}）です。' + ('　'.join(['', *notes]) if notes else '')
    return {'start': start, 'end': end, 'note': note}
