"""保存済みの原本を読み、別DBへ日次予測を追記し、表示用JSONを同期する。"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, date, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import statistics
import subprocess
import tempfile
import time

import core
import daily_learning_archive
import daily_learning_fixed
from daily_learning import (JST, VERSION, RULE_VERSION, MATURITY, PERIOD, STORE_COUNT, STORE_MODEL, VARIETY_MODEL, History,
                            BLEND_STORES, BLEND_VERSION, Journal, LateError, blend_weights, candidate_rates, comparison, digest,
                            encoded, identity, jst, outcome, outcome_source, period_days,
                            prediction_target, rank_blend, rank_by, rank_pool, rollback_needed, shift, store_day, train, valid)
from file_io import atomic_writer

FILE_NAME = 'daily-learning.json'
STORES = ('nagamachiminami', 'saiwaichou', 'pscube:c740601:20')
STORE_NAMES = {'nagamachiminami': '長町南', 'saiwaichou': '幸町', 'pscube:c740601:20': 'P-STATION'}
SOURCES = {'nagamachiminami': 'meruhen', 'saiwaichou': 'meruhen', 'pscube:c740601:20': 'pscube'}
SCORING_MJS = Path(__file__).parents[1] / 'database_android/web/pscube/scoring.mjs'
# 分析用JSON（daily_learning_archive）を使えずに保存した予測に付ける注意。「読めません」は各画面で重要な注意として出る。
ARCHIVE_NOTE = '（過去の学習に足す分析用JSONを読めません。原本DBだけで学習しました）'


def store_of(key):
    return key.split('|', 1)[1] if '|' in key else None


# 取り込みが終わったかを、窓の開け閉めではなく原本DBの書き込みで判断する（2026-11-14 利用者「取り込みが終了したら
# 勝手にやってくれるはずなのになぜかうまくいってない」）。11/13夜は、メルヘンの取り込み窓が朝まで開いたままで
# 「最後の窓が閉じたら」「窓が開いていなければ7:30に」のどちらも動かず、PC本体を閉じて予測が保存されなかった。
DB_FILES = {'meruhen': 'database.sqlite3', 'pscube': 'pscube.sqlite3'}
PREDICTION_INPUT_DAYS = 210
# 原本DBにこの秒数だけ書き込みが無ければ、その店の取り込みは一区切りとみなす（2026-11-25 利用者の決定で10分→2分へ短縮）。
QUIET_SECONDS = 120


def unsaved_stores(data_dir, target):
    """対象日の事前予測をまだ保存していない店舗。記録DBの predictions の鍵だけを読む（成績の表は開かない）。"""
    path = Path(data_dir) / 'daily-learning' / 'journal.sqlite3'
    if not path.exists():
        return list(STORES)
    try:
        db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)
        try:
            return [s for s in STORES
                    if db.execute('SELECT 1 FROM predictions WHERE key=?', (f'{target}|{s}',)).fetchone() is None]
        finally:
            db.close()
    except sqlite3.Error:
        return list(STORES)


def _source_stamp(data_dir, source, target):
    """原本の更新時刻の印と、最後の書き込み時刻。P-STATIONは500G未満の控え（日付-low.json）も見る。"""
    data_dir = Path(data_dir)
    try:
        db_mtime = os.stat(data_dir / DB_FILES[source]).st_mtime
    except OSError:
        db_mtime = None
    if source == 'pscube':
        try:
            low_mtime = os.stat(data_dir / 'site777-staging' / f'{shift(target, -1)}-low.json').st_mtime
        except OSError:
            low_mtime = None
        if low_mtime is not None:
            times = [t for t in (db_mtime, low_mtime) if t is not None]
            return (db_mtime, low_mtime), (max(times) if times else None)
    return db_mtime, db_mtime


def _failed_sources(data_dir, target, stores):
    """直近の実行で一時的な失敗（処理失敗・失敗で終了）になった原本。取り込み待ちは含めない。"""
    data_dir = Path(data_dir)
    failed = set()
    doc_at = ''
    try:
        doc = json.loads((data_dir / FILE_NAME).read_text(encoding='utf-8'))
        doc_at = str(doc.get('updated_at') or '')
        if doc_at and prediction_target(datetime.fromisoformat(doc_at)) == target:
            status = str(doc.get('status') or '')
            for store in stores:
                if f'{STORE_NAMES.get(store, store)}：処理失敗' in status:
                    failed.add(SOURCES[store])
            if status.startswith('処理失敗') or '日次学習で処理失敗' in status:
                failed.update(SOURCES[s] for s in stores)
    except (OSError, ValueError, TypeError, KeyError):
        pass
    try:
        lines = (data_dir / 'daily-learning' / TRACE_NAME).read_text(encoding='utf-8').splitlines()
        for line in reversed(lines):
            if not line.strip():
                continue
            stamp, sep, text = line.partition('\t')
            if sep and text.startswith('失敗で終了：') and prediction_target(datetime.fromisoformat(stamp)) == target:
                if not doc_at or stamp >= doc_at:
                    failed.update(SOURCES[s] for s in stores)
            break
    except (OSError, ValueError):
        pass
    return failed


def clear_failed_mark(last, status):
    """実行結果の文に一時的な『処理失敗』が含まれるとき、その原本の印を消して次回の確認で再試行できるようにする。
    データがそろっていない『取り込み待ち』の原本の印は残す。"""
    if not last or not isinstance(last, tuple) or len(last) != 2 or not isinstance(last[1], dict):
        return last
    text = str(status or '')
    if '処理失敗' not in text:
        return last
    failed = {SOURCES[s] for s in STORES if f'{STORE_NAMES.get(s, s)}：処理失敗' in text}
    if not failed and (text.strip().startswith('処理失敗') or '日次学習で処理失敗' in text):
        failed = set(SOURCES.values())
    if not failed:
        return last
    return (last[0], {k: v for k, v in last[1].items() if k not in failed})


SOURCE_NAMES = {'meruhen': 'メルヘン（長町南・幸町）', 'pscube': 'P-STATION'}


def run_due(data_dir, now, last=None, *, on_close=False, quiet=QUIET_SECONDS, skip_sources=(), reasons=None):
    """今、日次学習を動かすか。(動かすか, 入力の印)。入力の印は、前に試したときと同じなら動かさないために使う
    （データがそろわず「取り込み待ち」になった日に、同じ原本で5分ごとに読み直さない）。
    - 対象日の保存時間帯（前日23:30〜当日23:30未満。2026-11-25に8:00締切を完全撤廃）で、まだ保存していない店があるときだけ。
    - 原本ごとに、前に試したときから変わっており（または前回が一時的な処理失敗で）、最後の書き込みから
      quiet 秒たっているものが1つでもあれば動かす（1つの原本が書き込み中でも、そろった別の原本の店は先に保存する）。
    - skip_sources に指定した原本（別店舗の取り込み窓が開いている間など）は対象外とし、印も更新しない。
    - P-STATION（pscube）は500G未満の控え（site777-staging/日付-low.json）の更新時刻も含めて判定する。
    - PC本体を閉じるとき（on_close）は quiet 秒を待たない（閉じる＝取り込みは終わった、とみる。そろっていなければ ready が取り込み待ちにする）。
    - reasons にリストを渡すと、判定の理由を1つ足す（PCの定期確認が run.log と本体画面に出す。2026-11-23）。
    原本DBは開かない（ファイルの更新時刻だけ）。"""
    def because(text):
        if reasons is not None:
            reasons.append(text)

    target = prediction_target(now)
    stores = unsaved_stores(data_dir, target)
    if not stores:
        because('全店の予測は保存済み')
        return False, last
    skip = set(skip_sources or ())
    active_stores = [s for s in stores if SOURCES[s] not in skip]
    if not active_stores:
        because('残りの店は取り込み画面が開いている間は待つ')
        return False, last
    stamps, latest = {}, {}
    for source in sorted({SOURCES[s] for s in active_stores}):
        stamps[source], latest[source] = _source_stamp(data_dir, source, target)
    failed = _failed_sources(data_dir, target, active_stores)
    before = {k: v for k, v in (last[1] if last and last[0] == target else {}).items() if k not in failed}
    now_ts = jst(now).timestamp()
    ready_stamps = {
        source: t for source, t in stamps.items()
        if (source not in before or before[source] != t)
        and (on_close or latest[source] is None or now_ts - latest[source] >= quiet)
    }
    if not ready_stamps:
        waits = []
        for source in sorted(stamps):
            if source in before and before[source] == stamps[source]:
                waits.append(f'{SOURCE_NAMES[source]}は前回と同じ原本')
            else:
                waits.append(f'{SOURCE_NAMES[source]}は書き込みから{max(1, int(quiet) // 60)}分待ち')
        because('、'.join(waits))
        return False, (target, before) if failed and last and last[0] == target else last
    because('・'.join(SOURCE_NAMES[s] for s in sorted(ready_stamps)) + 'の原本で動かす')
    return True, (target, {**before, **ready_stamps})


def _status_segment(status, name):
    """日次学習の結果の文（店ごとに『／』で区切られる）から、その店の部分だけを返す。"""
    for part in str(status or '').split('／'):
        if part.strip().startswith(f'{name}：'):
            return part.strip()[len(name) + 1:]
    return ''


def night_status(data_dir, now) -> tuple[str, str]:
    """PC本体画面の1行（2026-11-23 利用者「普通に取り込んだあと学習し候補を出してるかどうかを肉眼的にわかるようにしたい」）。
    (文, 段階)。段階は ok（全店保存済み）・wait（まだの店がある）・error（処理失敗など）。
    2026-11-25に8時締切を完全撤廃したため、対象日（23:30切替）の保存は終日受け付ける。
    記録DBは予測（predictions）だけを読み取り専用で開く（成績の表は開かない）。原本DBは開かない。"""
    now = jst(now)
    target = prediction_target(now)
    saved = {}
    path = Path(data_dir) / 'daily-learning' / 'journal.sqlite3'
    if path.exists():
        journal = None
        try:
            journal = Journal(path, readonly=True)
            for store in STORES:
                body = journal.get('predictions', f'{target}|{store}')
                if body is not None:
                    saved[store] = body
        except (sqlite3.Error, ValueError, OSError):
            pass
        finally:
            if journal is not None:
                journal.close()
    status = ''
    try:
        doc = json.loads((Path(data_dir) / FILE_NAME).read_text(encoding='utf-8'))
        doc_at = str(doc.get('updated_at') or '')
        if doc_at and prediction_target(datetime.fromisoformat(doc_at)) == target:
            status = str(doc.get('status') or '')
    except (OSError, ValueError, TypeError):
        pass
    parts, level = [], 'ok'
    for store in STORES:
        name = STORE_NAMES[store]
        body = saved.get(store)
        if body is not None:
            at = str(body.get('saved_at') or '')
            when = at[11:16] if len(at) >= 16 else ''
            count = sum(len(g.get('selected') or []) for g in body.get('groups') or [] if isinstance(g, dict))
            parts.append(f'{name} 保存済み{" " + when if when else ""}（候補{count}台）')
            continue
        segment = _status_segment(status, name)
        if '処理失敗' in segment or (status.startswith('処理失敗') and not segment):
            parts.append(f'{name} 処理失敗')
            level = 'error'
        elif '取り込み待ち' in segment:
            parts.append(f'{name} 取り込み待ち')
            level = 'wait' if level == 'ok' else level
        elif '待機' in segment:
            parts.append(f'{name} 取り込み中のため待機')
            level = 'wait' if level == 'ok' else level
        else:
            parts.append(f'{name} まだ')
            level = 'wait' if level == 'ok' else level
    day = f'{int(target[5:7])}/{int(target[8:10])}'
    return f'日次学習（{day}の予測）：' + '／'.join(parts), level


def method_signature(store):
    """候補の作り方の版（学習の版＋従来候補の版）。期間の途中で変わったら、古い版の日を比べない。

    ファイル全体の指紋は無関係な変更でも変わるので使わず、各方式が持つ版の定数を使う。"""
    if SOURCES.get(store) == 'pscube':
        found = re.findall(r"export const (SCORING_VERSION|NEXT_DAY_VERSION) = '([^']+)'",
                           SCORING_MJS.read_text(encoding='utf-8'))
        base = ','.join(f'{k}={v}' for k, v in sorted(found))
    else:
        import normal_next_day_model
        base = (f'score={core.VERSION},next={core.NEXT_DAY_METHOD_VERSION},normal={normal_next_day_model.METHOD_VERSION},'
                f'variety={core.candidate_method_version(store, core.VARIETY_GROUP_NAME)}')
    # 2026-11-21：幸町・P-STATIONの学習版の並べ方（混合）を変えた。長町南の版は変えない（比較期間をやり直さない）。
    learned = f'{VERSION}+{BLEND_STORES[store]}' if store in BLEND_STORES else VERSION
    if store == 'pscube:c740601:20':
        # 2026-11-21：分析用JSONの古い形式のゼロ線を直した（daily_learning_archive.start_at_zero）。学習の正解が変わるので、
        # 直す前の日とは別の方式として数える（採用判定で直す前の日と混ぜない）。
        learned += '+' + daily_learning_archive.ZERO_FIX
    return f'{learned}|{base}'


def explain(error):
    """画面に出す失敗の理由と直し方。型の名前だけを出さない。"""
    text = str(error)
    if isinstance(error, RuntimeError) and 'Node.js' in text:
        return 'Node.jsが見つかりません。Node.jsを入れるか、database/start.cmd から開き直してください'
    if isinstance(error, FileNotFoundError):
        return f'{text}。データフォルダーを確認してください'
    if isinstance(error, TimeoutError):
        return '原本の読み取りが60秒で終わりませんでした。次の確認で読み直します'
    if isinstance(error, sqlite3.Error):
        return f'原本DBを読めません（{text}）。取り込み中なら、終わったあとに読み直します'
    if isinstance(error, subprocess.TimeoutExpired):
        return 'P-STATIONの従来候補の計算が3分で終わりませんでした'
    return f'{type(error).__name__}: {text}'[:160]


DROPPED = ('preview_image', 'image_base64', 'screenshot', 'raw_html')


def compact(value):
    """画像などの項目を、どの深さでも取り除く。読み込みでは decode（同じ結果で速い）を使う。"""
    if isinstance(value, dict):
        return {k: compact(v) for k, v in value.items() if k not in DROPPED}
    if isinstance(value, list):
        return [compact(v) for v in value]
    return value


def _drop(obj):
    return {k: v for k, v in obj.items() if k not in DROPPED} if any(k in obj for k in DROPPED) else obj


def decode(text):
    """compact(json.loads(text)) と同じ結果を、JSONを読みながら作る（2026-11-12 軽量化D。全部の値をたどり直さない）。"""
    return json.loads(text, object_hook=_drop)


def read_database(path, table):
    return read_tables(path, (table,))[table]


def read_tables(path, tables):
    """原本から短い単位でコピーを作り、行の解析中は原本のロックを持たない。複数の表も1回のコピーで読む。"""
    if not tables or any(t not in ('days', 'records', 'machines') for t in tables):
        raise ValueError('入力表が不正です')
    if not Path(path).is_file():
        raise FileNotFoundError(f'{Path(path).name} がありません')
    with tempfile.TemporaryDirectory(prefix='database-daily-read-') as temporary:
        snapshot = sqlite3.connect(Path(temporary) / 'snapshot.sqlite3')
        try:
            db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
            try:
                db.execute('PRAGMA query_only=ON')
                deadline = time.monotonic() + 60
                def progress(status, remaining, total):
                    if time.monotonic() >= deadline:
                        raise TimeoutError('学習用コピーの作成を中断しました。次回に再試行します')
                # 原本のモードや検証記録は変えない。1回1MiBほどずつ読み、
                # 書き込み側を長時間待たせず、一貫したコピーを完成させる。
                db.backup(snapshot, pages=256, progress=progress, sleep=.05)
            finally:
                db.close()
            snapshot.execute('PRAGMA query_only=ON')
            return {table: [decode(row[0]) for row in snapshot.execute(f'SELECT payload FROM {table}')]
                    for table in tables}
        finally:
            snapshot.close()


class MemoryStore:
    _machine_rows = core.Store._machine_rows

    def __init__(self, rows):
        self.all = rows

    def rows(self, day=None, machine=None, store=None):
        return [r for r in self.all if (not day or r['day'] == day) and
                (not machine or r['machine'] == machine) and (not store or r['store'] == store)]


def load_inputs(data_dir, target, sources=('meruhen', 'pscube'), *, outcome_days=()):
    """予測の入力期間と、結果の記録に必要な期間外の日を同じ原本コピーから読む。"""
    data_dir = Path(data_dir)
    first, last = shift(target, -PREDICTION_INPUT_DAYS), shift(target, -1)
    outcome_days = {day for day in outcome_days if day < first}
    rows, raw, machines = [], [], []
    if 'meruhen' in sources:
        rows += [r for r in read_database(data_dir / 'database.sqlite3', 'days')
                 if (first <= r['day'] <= last or r['day'] in outcome_days) and r['store'] in STORES and
                 not core.is_hidden_machine(r['store'], r['machine'])]
    if 'pscube' in sources:
        tables = read_tables(data_dir / 'pscube.sqlite3', ('records', 'machines'))
        # 原本の並び（行の書き直しで変わる）に左右されないよう、決まった順にそろえてから計算・保存する。
        raw = sorted((r for r in tables['records']
                      if first <= r['day'] <= last and str(r['store']) == 'c740601' and str(r['rate']) == '20'),
                     key=lambda r: (r['day'], str(r.get('rack')), encoded(r)))
        machines = sorted((m for m in tables['machines'] if str(m['store']) == 'c740601' and str(m['rate']) == '20'),
                          key=encoded)
        older = (r for r in tables['records'] if r['day'] in outcome_days
                 and str(r['store']) == 'c740601' and str(r['rate']) == '20')
        rows += [{**r, 'store': f"pscube:{r['store']}:{r['rate']}"} for records in (raw, older) for r in records]
    rows.sort(key=lambda r: (r['day'], identity(r)))
    return rows, {'records': raw, 'machines': machines}


def resolve_node(explicit=None, *, environ=None, home=None):
    """start.cmdからはCodex用PATHを継承しないため、既存の実行環境も探す。"""
    if explicit:
        return str(explicit)
    env = os.environ if environ is None else environ
    if env.get('NODE'):
        return env['NODE']
    found = shutil.which('node', path=env.get('PATH', ''))
    if found:
        return found
    user = Path.home() if home is None else Path(home)
    executable = 'node.exe' if os.name == 'nt' else 'node'
    candidates = [user / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin' / executable]
    if os.name == 'nt':
        candidates.extend([Path(env.get('ProgramFiles', 'C:/Program Files')) / 'nodejs/node.exe',
                           user / 'AppData/Local/Programs/nodejs/node.exe'])
    return next((str(p) for p in candidates if p.is_file()), None)


def baseline_groups(rows, pscube, day, node=None):
    groups, store = [], MemoryStore([r for r in rows if not r['store'].startswith('pscube:')])
    for location in STORES[:2]:
        daily = store.rows(day=day, store=location)
        variety = core.variety_machines(daily)
        for machine in sorted({r['machine'] for r in daily} - variety):
            pool = [r for r in daily if r['machine'] == machine and core.next_day_evidence(store, r)['index'] is not None]
            result = core.provisional_next_day_candidates(store, day, machine, location)
            if result['count']:
                groups.append(dict(store=location, rate='', name=machine, pool=pool,
                                   current=[identity(c['row']) for c in result['candidates']]))
        if variety:
            pool = [r for r in daily if r['machine'] in variety and not core.implausible_numbers(r)
                    and core.variety_state(r) in core.variety_order(location)]
            result = core.variety_next_day_candidates(store, day, location)
            if result['count']:
                groups.append(dict(store=location, rate='', name='バラエティ', pool=pool,
                                   current=[identity(c['row']) for c in result['candidates']]))
    if pscube['records']:
        binary = resolve_node(node)
        if not binary:
            raise RuntimeError('P-STATIONの従来候補を計算するNode.jsがありません')
        proc = subprocess.run([binary, str(Path(__file__).with_name('daily_learning_pscube.mjs'))],
                              input=encoded({'data': pscube, 'day': day}), text=True, encoding='utf-8',
                              capture_output=True, timeout=180, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if proc.returncode:
            raise RuntimeError('P-STATIONの従来候補計算に失敗しました')
        for group in json.loads(proc.stdout):
            pool = [r for r in rows if r['day'] == day and r['store'] == group['store']
                    and r['machine'] == group['name'] and r['rack'] in group['pool']]
            by_rack = {r['rack']: r for r in pool}
            groups.append({**group, 'pool': pool, 'current': [identity(by_rack[r]) for r in group['current']]})
    return groups


def group_key(group):
    return encoded([group['store'], group.get('rate', ''), group['name']])


def skipped_low_racks(data_dir, target):
    """サイトセブンで取り込まなかった500G未満の台の控え（日 → 台番号の集合）。

    2026-11-10 から、P-STATIONのサイトセブンの取り込みは500G未満の台を保存しない（AGENTS.md）。
    保存台数だけを数えると、その日から「ふだんの90%未満」になって毎日「取り込み待ち」になる
    （11/10は295台中258台、控え37台。2026-11-11 実データの複製で確認）。確定した日の控えは
    `site777-staging/日付-low.json`（機種ごとの台番号）にあるので、そろったかを数えるときは済みに数える。
    成績は見ない。読めない・無い日は空。
    """
    out = {}
    for n in range(1, 9):
        day = shift(target, -n)
        try:
            data = json.loads((Path(data_dir) / 'site777-staging' / f'{day}-low.json').read_text(encoding='utf-8'))
            out[day] = {int(rack) for racks in data.values() for rack in racks}
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return out


def ready(rows, target, stores=STORES, low=None):
    """途中取り込みや店休日の0台データで初回固定しないための最低限の確認（保存行の数と有効台の有無のみ）。成績は見ない。
    2026-11-25 利用者の決定で、過剰な停止原因となっていた「閉店前／確定前データの1台停止」「前日機種の丸ごと欠落1%超」
    「符号不明台10%超」による停止ルールを撤廃し、直近7日中央値の90%未満と使える台0台のみを残した。"""
    day, reasons = shift(target, -1), []
    for store in stores:
        name = STORE_NAMES.get(store, store)
        racks = defaultdict(set)
        current = []
        for r in rows:
            if r['store'] == store and shift(day, -7) <= r['day'] <= day:
                racks[r['day']].add(r['rack'])
                if r['day'] == day:
                    current.append(r)
        if store.startswith('pscube:'):
            for low_day, skipped in (low or {}).items():
                if low_day in racks:           # その日の取り込みがあるときだけ足す（控えだけの日を取り込み済みにしない）
                    racks[low_day] |= skipped
        counts = {d: len(v) for d, v in racks.items()}
        previous = [n for d, n in counts.items() if d < day]
        if not current or (previous and counts[day] < .9 * statistics.median(previous)):
            reasons.append(f'{name}の前日データが不足しています')
            continue
        usable = [r for r in current if valid(r)]
        # 2026-11-23 利用者の決定（G12）：使える台が0台の店・日は予測を固定せず取り込み待ちにする。
        # 当日23:30（対象日切替）までに有効な台の取り込みが入れば作り直す。0台のまま23:30を過ぎたら未保存（missed）。
        if not usable:
            reasons.append(f'{name}の前日データに使える台がありません（全{len(current)}台）')
    return reasons


def build_prediction(rows, pscube, target, journal, node=None, history_rows=None):
    """history_rows：学習・特徴に使う行（分析用JSONを足したもの）。従来候補（baseline）は原本DBの rows だけで作る。"""
    history, groups = History(history_rows or rows), baseline_groups(rows, pscube, shift(target, -1), node)
    models = train(history, target)
    projected, methods = [], {}
    for group in groups:
        key = group_key(group)
        method = methods.setdefault(group['store'], method_signature(group['store']))
        # 採用は店舗単位（2026-11-12）。採用したときと方式が違えば、採用の根拠が無いので従来方式。
        state = journal.get('state', 'store:' + group['store']) or {'active': 'current'}
        adopted = state.get('active') == 'learned' and state.get('method') == method
        # v4：バラエティは台ごとに独立に見る（機種ごとの係数で機種どうしを比べない）ので、バラエティ専用の係数だけで並べる。
        # それ以外は機種ごとの係数（v3と同じ）、無い機種（新台など）は店舗共通の係数。
        mix = None
        if group['name'] == core.VARIETY_GROUP_NAME:
            kind = 'variety'
            ordered = rank_by(group['pool'], history, models.get((group['store'], group.get('rate', ''), VARIETY_MODEL)), kind)
        elif group['store'] in BLEND_STORES and (group['store'], group.get('rate', ''), STORE_MODEL) in models:
            # 2026-11-21 幸町・P-STATION：店舗共通の点と機種専用の点を、専用係数の学習量で混ぜる（専用係数の無い機種は共通だけ）。
            kind = 'blend'
            ordered = rank_blend(group['pool'], history, models, group['store'], group.get('rate', ''))
            mix = blend_weights(group['pool'], models, group['store'], group.get('rate', ''))
        else:
            kind, ordered = 'machine', rank_pool(group['pool'], history, models)
            if ordered is None:
                kind = 'store'
                ordered = rank_by(group['pool'], history, models.get((group['store'], group.get('rate', ''), STORE_MODEL)), kind)
        current = [list(k) for k in group['current']]
        learned = [list(identity(r)) for r in ordered[:len(current)]] if ordered is not None else current
        active = 'learned' if adopted and ordered is not None else 'current'
        projected.append(dict(key=key, store=group['store'], name=group['name'], current=current,
                              learned=learned, selected=learned if active == 'learned' else current,
                              active=active, trained=ordered is not None, method=method,
                              model=kind if ordered is not None else None,
                              **({'mix': mix} if mix is not None else {}),
                              status=('改善を確認して採用中' if active == 'learned' else
                                      '学習済み・将来成績を比較中' if ordered is not None else '学習データ不足・従来方式'),
                              pool=[{'id': list(identity(r)), 'features': history.model_features(r, kind if ordered is not None else 'machine')}
                                    for r in group['pool']]))
    sources = [Path(__file__), Path(__file__).with_name('daily_learning.py'), Path(core.__file__),
               Path(__file__).with_name('normal_next_day_model.py'),
               Path(__file__).with_name('daily_learning_pscube.mjs'), SCORING_MJS,
               SCORING_MJS.with_name('data.mjs')]
    study = {}
    if daily_learning_fixed.FIRST <= target <= daily_learning_fixed.LAST and groups:
        # 通常の実行は1店舗ずつ。対照側だけ失敗しても従来の予測を保存する。
        try:
            store, = methods
            control = daily_learning_fixed.prediction(target, store, methods[store], groups, projected,
                                                      history, models, journal)
        except Exception as error:
            control = {'reason': f'固定係数の比較記録に失敗：{type(error).__name__}: {error}'}
        study[daily_learning_fixed.STUDY] = control
        sources.append(Path(daily_learning_fixed.__file__))
    return dict(input_day=shift(target, -1), groups=projected, methods=methods, **study,
                models={encoded(k): v for k, v in models.items()},
                source_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sources if p.is_file()})


def due_outcomes(journal, today):
    """結果が成熟した（対象日から8日たった）のに、まだ結果を記録していない予測の鍵。本文は読まない。"""
    keys = journal.db.execute('SELECT key FROM predictions WHERE key NOT IN (SELECT key FROM outcomes) ORDER BY key')
    return [k for (k,) in keys if k[:10] <= shift(today, -MATURITY)]


def record_outcomes(journal, rows, today, stores=None, *, prediction_start=None):
    """成熟した予測の結果を1回だけ記録する。stores を渡すと、その店舗の予測だけ（原本を読めた店舗だけ）。

    記録できなかった予測の（鍵, 例外）を返す（2026-11-12）。1件の失敗で、ほかの予測の記録やその晩の予測の保存を
    止めない。予測の入力期間より古い日は、その日の行が原本にある店舗だけ記録する。
    失敗した分は未記録のまま残り、未記録がある期間は採用・切り戻しを判定しない（decisions）。"""
    histories, failed, older_rows = {}, [], defaultdict(list)
    recent_rows = []
    for row in rows:
        if prediction_start is not None and row['day'] < prediction_start:
            older_rows[row['day']].append(row)
        else:
            recent_rows.append(row)
    for key in due_outcomes(journal, today):
        store = store_of(key)
        if stores is not None and store not in stores:
            continue
        try:
            day = key[:10]
            older = prediction_start is not None and day < prediction_start
            history_key = (store, day if older else None)
            if history_key not in histories:
                try:
                    source_rows = older_rows.get(day, []) if older else recent_rows
                    histories[history_key] = History(source_rows if store is None else
                                                     [r for r in source_rows if r['store'] == store])
                except Exception as error:     # noqa: BLE001 - この店舗の行を読めない理由を、同じ店舗の鍵で使い回す
                    histories[history_key] = error
            history = histories[history_key]
            if isinstance(history, Exception):
                raise history
            prediction, results = journal.get('predictions', key), []
            target = prediction['target']
            available_stores = {r['store'] for r in history.rows} if older else set()
            if older and store is not None and store not in available_stores:
                raise ValueError(f'{target}の原本データがありません')
            # 2026-11-12より前の予測は方式の版を持たない。新しい版と混ぜない。
            method = prediction.get('version', '') + '|legacy'
            for group in prediction['groups']:
                stats = dict(key=group['key'], day=target, trained=group['trained'], method=group.get('method', method))
                # 母集団全体の正解も残す。候補だけを学習・評価資料にしない。
                # 候補は母集団の中から選ぶが、万一外の台があっても落とさず同じように正解を引く。
                ids = [p['id'] for p in group['pool']] + list(group['current']) + list(group['learned'])
                if older and any(i[0] not in available_stores for i in ids):
                    raise ValueError(f'{target}の原本データがありません')
                found = {encoded(i): history.get(target, i) for i in ids}
                labels = {k: outcome(r) for k, r in found.items()}
                for name in ('current', 'learned'):
                    stats.update(candidate_rates(name, group[name], labels))
                stats['labels'] = labels
                # 両方式の候補の台（labels の鍵）。欠測の最悪・最良を、同じ台に同じ結果を置いて計算するため（2026-11-28）。
                stats['candidates'] = {name: [encoded(i) for i in group[name]] for name in ('current', 'learned')}
                # 符号の根拠（ゲーム数・何から決めたか・取り込んだ時刻）。後の訂正・遅い取り込みと見分けるため。
                stats['evidence'] = {k: None if r is None else [r.get('games'), outcome_source(r),
                                                                r.get('captured_at') or r.get('source_captured_at')
                                                                or r.get('observed_at')]
                                     for k, r in found.items()}
                results.append(stats)
            with journal.db:
                journal.append('outcomes', key, dict(target=target, recorded_at=today, store=store, groups=results))
        except Exception as error:     # noqa: BLE001 - 1件の失敗でほかの記録を止めない
            failed.append((key, error))
    return failed


def pending_outcomes(journal, first, last, store=None):
    """期間内の予測のうち、まだ結果を記録していないものがあるか（原本を読めなかった晩・記録の失敗）。本文は読まない。"""
    keys = journal.db.execute('SELECT key FROM predictions WHERE key>=? AND key<=? AND key NOT IN (SELECT key FROM outcomes)',
                              (first, last + '~'))
    return any(store is None or store_of(k) == store for (k,) in keys)


def store_days(journal, store, first, last):
    """期間内のその店舗の日ごとの比較（daily_learning.store_day）。方式の版も付ける。"""
    days = []
    for (key,) in journal.db.execute('SELECT key FROM outcomes WHERE key>=? AND key<=? ORDER BY key', (first, last + '~')):
        if store_of(key) != store:
            continue
        body = journal.get('outcomes', key)
        groups = body['groups']
        versions = {g.get('method') for g in groups if g.get('trained')}
        day = store_day(body['target'], with_candidates(journal, key, groups))
        day['method'] = versions.pop() if len(versions) == 1 else ('混在' if versions else None)
        days.append(day)
    return days


def with_candidates(journal, key, groups):
    """結果の組に、両方式の候補の台（candidates）が無ければ、同じ鍵の予測から補う（読むだけ。記録は書き換えない）。

    2026-11-28 より前の結果は候補の台を持たない。予測が無い・組が見つからない・台が結果に無いときは補わず、
    欠測の最悪・最良は再計算不能になる（daily_learning.manski_bounds）。"""
    if all('candidates' in g for g in groups):
        return groups
    prediction = journal.get('predictions', key)
    saved = {g.get('key'): g for g in (prediction or {}).get('groups') or [] if isinstance(g, dict)}
    out = []
    for g in groups:
        source = saved.get(g.get('key'))
        if 'candidates' not in g and source is not None:
            try:
                ids = {name: [encoded(i) for i in source[name]] for name in ('current', 'learned')}
            except (KeyError, TypeError, ValueError):
                ids = None
            if ids is not None:
                g = {**g, 'candidates': ids}
        out.append(g)
    return out


def latest_method(days):
    """期間の最後の方式の日だけを使う（版で決め、成績では選ばない）。"""
    known = [d for d in days if d['method'] not in (None, '混在')]
    if not known:
        return None, []
    method = max(known, key=lambda d: d['day'])['method']
    return method, [d for d in known if d['method'] == method]


def decisions(journal, today):
    """期間終了後に1度だけ、店舗ごとに検定する。処理の再実行で判定回数を増やさない。

    2026-11-12（結果を見る前）：機種ごと84組で有意水準を分けると16週中15週の勝ち越しが要り、
    実際の差があってもほぼ採用されなかったので、採用・切り戻しを店舗単位にした（DAILY_LEARNING.md）。"""
    start = journal.get('state', 'start')
    if not start:
        return
    offset, epoch = 0, 0
    while True:
        epoch += 1
        length = period_days(epoch)
        first, last = shift(start, offset), shift(start, offset + length - 1)
        if last > shift(today, -MATURITY):
            break
        offset += length
        key = f'adoption:{epoch}'
        if journal.has('decisions', key):
            continue
        # 判定は1回きりなので、期間内の予測の結果がそろうまで待つ（2026-11-12。原本を読めなかった晩に、
        # 記録前の日を欠いたまま判定を確定させない）。後の期間も順番を守って待つ。
        if pending_outcomes(journal, first, last):
            break
        alpha = .05 / (epoch * (epoch + 1) * STORE_COUNT)
        results = {}
        with journal.db:
            for store in STORES:
                days = store_days(journal, store, first, last)
                method, used = latest_method(days)
                result = comparison(used, alpha, first) | dict(method=method, days=len(days),
                                                               other_method_days=len(days) - len(used))
                state = journal.get('state', 'store:' + store) or {'active': 'current', 'since': start}
                # 切り戻した期間の成績を再採用に使わない（切り戻しのあとに始まった期間だけ）。
                # 採用中でも方式の版が変わっていれば、その採用は今の方式の根拠にならないので判定し直す。
                open_to = state['active'] == 'current' or state.get('method') != method
                if open_to and first >= state['since'] and result['adopt']:
                    journal.state('store:' + store, {'active': 'learned', 'since': today, 'method': method,
                                                     'period': [first, last]})
                results[store] = result
            journal.append('decisions', key, dict(first=first, last=last, at=today, rule=RULE_VERSION,
                                                  results=results))
    for store in STORES:
        state = journal.get('state', 'store:' + store)
        if not state or state['active'] != 'learned':
            continue
        blocks = ((date.fromisoformat(shift(today, -MATURITY)) - date.fromisoformat(state['since'])).days + 1) // 28
        for block in range(1, blocks + 1):
            decision_key = f'rollback:{store}:{state["since"]}:{block}'
            if journal.has('decisions', decision_key):
                continue
            first, last = shift(state['since'], 28 * (block - 1)), shift(state['since'], 28 * block - 1)
            if pending_outcomes(journal, first, last, store):
                break                                  # この店舗の結果がそろってから判定する
            days =[d for d in store_days(journal, store, first, last) if d['method'] == state.get('method')]
            rollback = rollback_needed(days)
            with journal.db:
                journal.append('decisions', decision_key, dict(at=today, first=first, last=last, rollback=rollback,
                                                               days=len(days), rule=RULE_VERSION))
                if rollback:
                    journal.state('store:' + store, {'active': 'current', 'since': today})
            if rollback:
                break


# 点検（PCの日次学習の窓）：直近何晩を並べるか。
CHECKUP_NIGHTS = 14


def sign_counts(rows, store, day):
    """その店・その日の有効な台の数と、符号が決まらない台（差枚もグラフも無い）の数。取り込み待ち（ready）と同じ数え方。
    プラスかどうかは数えない（成績は出さない）。"""
    usable = [r for r in rows if r.get('store') == store and r.get('day') == day and valid(r)]
    return {'racks': len(usable), 'unknown': sum(1 for r in usable if outcome(r) is None)}


def input_day_rows(journal, prediction, day):
    """固定した入力のうち、ある日の行だけを読む。塊は（店舗, 日）の順に並ぶので、後ろ（新しい日）から探して
    その日より古い塊に来たら止める（210日分を全部ほどかない）。2026-11-12より前の1つの塊の形にも対応する。"""
    if 'inputs' not in prediction:
        return [r for r in journal.get('inputs', prediction['input_sha256']) or [] if r.get('day') == day]
    for stamp in reversed(prediction['inputs'].get('rows', [])):
        rows = journal.get('inputs', stamp) or []
        found = [r for r in rows if r.get('day') == day]
        if found:
            return found
        if rows and str(rows[0].get('day', '')) < day:
            break
    return []


def checkup(journal, now, nights=CHECKUP_NIGHTS):
    """点検（2026-11-14 利用者「やってみよう」。学習の質はデータの質で決まるため）。店舗ごとに直近の晩について、
    予測を保存できたか（saved・missed・pending＝まだ保存できる時間内・before＝日次学習を始める前）と、その予測に使った
    前日データの有効な台・符号が決まらない台の数を返す。予測（predictions）と固定した入力（inputs）だけを読み、
    成績（outcomes・decisions）は開かない。数えた結果は state に控え、同じ晩を何度も数えない。"""
    now = jst(now)
    open_target = latest = prediction_target(now)
    start = journal.get('state', 'start')
    targets = [shift(latest, -n) for n in range(nights - 1, -1, -1)]
    stores = {}
    for store in STORES:
        cells = []
        for target in targets:
            key = target + '|' + store
            if journal.has('predictions', key):
                counts = journal.get('state', 'checkup|' + key)
                if counts is None:
                    day = shift(target, -1)
                    counts = sign_counts(input_day_rows(journal, journal.get('predictions', key), day), store, day)
                    with journal.db:
                        journal.state('checkup|' + key, counts)
                cells.append({'target': target, 'state': 'saved', **counts})
            elif start is None or target < start:
                cells.append({'target': target, 'state': 'before'})
            elif target == open_target:
                cells.append({'target': target, 'state': 'pending'})
            else:
                cells.append({'target': target, 'state': 'missed'})
        stores[store] = cells
    return {'nights': nights, 'latest': latest, 'stores': stores}


def export(journal, data_dir, status, now, sync_dir=None):
    targets =[k for (k,) in journal.db.execute('SELECT key FROM predictions ORDER BY key DESC LIMIT 93')]
    by_day = {}
    for target in targets:
        p = journal.get('predictions', target)
        day = by_day.setdefault(p['target'], {k: p[k] for k in ('target', 'input_day', 'saved_at', 'version')} | {'groups': []})
        day['groups'].extend([{k: g[k] for k in ('store', 'name', 'active', 'status', 'selected', 'current', 'learned')} |
                              {'saved_at': p['saved_at']} for g in p['groups']])
    days = [by_day[d] for d in sorted(by_day, reverse=True)[:31]]
    document = dict(format='daily-learning', version=1, updated_at=jst(now).isoformat(),
                    status=status, days=days, improvement='将来成績で確認するまで改善未確認')
    # 点検はPCの窓だけで使う（GoogleのスクリプトはこれをiPhone・共有へ渡さない）。数えられなくても保存・表示は続ける。
    try:
        document['checkup'] = checkup(journal, now)
    except Exception as error:     # noqa: BLE001 - 点検の失敗で予測の表示を止めない
        document['checkup_error'] = f'{type(error).__name__}: {error}'[:200]
    if sync_dir is not None:
        # 同期先に書けなくても、PCの表示は更新する（どちらで止まったかを状態の文に残す）。
        try:
            if not Path(sync_dir).is_dir():
                raise OSError('同期先のフォルダーが見つかりません')
            with atomic_writer(Path(sync_dir) / FILE_NAME) as f:
                f.write(encoded(document))
        except OSError as error:
            document['status'] += f'／同期先へ書けません（{error}）。Googleドライブの起動・同期先の設定を確認してください'
    with atomic_writer(Path(data_dir) / FILE_NAME) as f:
        f.write(encoded(document))
    return document


SYNC_UNAVAILABLE_SUFFIX = '／同期先未設定または利用不可'
_SYNC_WRITE_ERR_RE = re.compile(r'／同期先へ書けません（[^）]*）。Googleドライブの起動・同期先の設定を確認してください')


def _has_sync_error(status: str) -> bool:
    return '同期先へ書けません' in status or '同期先未設定または利用不可' in status


def _strip_sync_error(status: str) -> str:
    return _SYNC_WRITE_ERR_RE.sub('', status).replace(SYNC_UNAVAILABLE_SUFFIX, '')


def needs_sync_retry(data_dir) -> bool:
    """直近の daily-learning.json に同期先への書き出し失敗が残っているか（原本DBは開かない）。"""
    try:
        doc = json.loads((Path(data_dir) / FILE_NAME).read_text(encoding='utf-8'))
        return isinstance(doc, dict) and _has_sync_error(str(doc.get('status') or ''))
    except (OSError, ValueError, TypeError):
        return False


def retry_sync_export(data_dir, *, clock=lambda: datetime.now(JST)) -> str | None:
    """同期先（Googleドライブ等）への書き出し失敗だけをやり直す。予測の再計算や原本DBの読み込みは行わない。"""
    data_dir = Path(data_dir)
    if not needs_sync_retry(data_dir):
        return None
    folder = core.resolve_sync_dir(data_dir)
    if folder is None or not Path(folder).is_dir():
        return None
    from backup_status import output_lock
    with output_lock(data_dir / 'daily-learning', 'meruhen'):
        path = data_dir / FILE_NAME
        try:
            doc = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return None
        if not isinstance(doc, dict) or not _has_sync_error(str(doc.get('status') or '')):
            return None
        doc['status'] = _strip_sync_error(str(doc.get('status') or ''))
        try:
            if not Path(folder).is_dir():
                return None
            with atomic_writer(Path(folder) / FILE_NAME) as f:
                f.write(encoded(doc))
        except OSError:
            return None
        with atomic_writer(path) as f:
            f.write(encoded(doc))
        trace(data_dir, '同期先への書き出しを再試行して完了しました', now=clock())
        return '日次学習の同期先への書き出しを再試行して完了しました'


def _run(data_dir, *, clock=lambda: datetime.now(JST), node=None, sync=True, quiet=0, skip_sources=()):
    data_dir = Path(data_dir)
    now, journal = jst(clock()), Journal(data_dir / 'daily-learning' / 'journal.sqlite3')
    today = now.date().isoformat()
    # 保存できるのは、対象日の前日23:30〜当日23:30未満（daily_learning.prediction_target。2026-11-25に8時締切を完全撤廃）。
    # 23:30以降は「明日」が対象日で、今日の取り込み済みの行が前日データになる。
    target = prediction_target(now)
    label = f'{int(target[5:7])}/{int(target[8:])}'
    trace(data_dir, f'開始：対象 {target}', now=now)
    import error_log
    try:
        # 2026-11-12：することがある店舗の原本だけを読む。全店保存済みで、記録すべき結果も無ければ原本を開かない
        # （以前は毎回、原本2つ（509MB・67MB）を丸ごと一時コピーしていた）。読めない原本があっても、ほかの店は続ける。
        saved = {s for s in STORES if journal.has('predictions', target + '|' + s)}
        open_skip = set(skip_sources or ())
        writing = set()
        if quiet > 0:
            now_ts = now.timestamp()
            for source in sorted({SOURCES[s] for s in STORES if s not in saved and SOURCES[s] not in open_skip}):
                _, latest = _source_stamp(data_dir, source, target)
                if latest is not None and now_ts - latest < quiet:
                    writing.add(source)
        blocked = writing | open_skip
        due = due_outcomes(journal, today)
        prediction_start = shift(target, -PREDICTION_INPUT_DAYS)
        older_days = defaultdict(set)
        for key in due:
            if key[:10] < prediction_start:
                source = SOURCES.get(store_of(key))
                for needed in (source,) if source else DB_FILES:
                    older_days[needed].add(key[:10])
        wanted = {s for s in STORES if s not in saved and SOURCES[s] not in blocked}
        wanted |= {store_of(k) for k in due if store_of(k) in STORES and SOURCES[store_of(k)] not in blocked}
        if any(store_of(k) not in STORES for k in due):
            wanted |= {s for s in STORES if SOURCES[s] not in blocked}
        loaded, failed = {}, {}
        for source in sorted({SOURCES[s] for s in wanted}):
            try:
                extra = {'outcome_days': older_days[source]} if older_days[source] else {}
                rows, pscube = load_inputs(data_dir, target, (source,), **extra)
                loaded[source] = ([r for r in rows if SOURCES.get(r['store']) == source], pscube)
            except Exception as error:     # noqa: BLE001 - 店舗ごとに失敗を分ける
                failed[source] = error
                error_log.note(data_dir, 'daily-learning', f'{source}: {type(error).__name__}: {error}')
        rows = [r for source in sorted(loaded) for r in loaded[source][0]]
        pscube = loaded.get('pscube', (None, {'records': [], 'machines': []}))[1]
        trace(data_dir, f'原本を読みました：{"・".join(sorted(loaded)) or "なし"}'
              + (f'（読めない：{"・".join(sorted(failed))}）' if failed else '') + f'・{len(rows)}行')
        # 結果の記録・採用判定の失敗では、その晩の予測の保存を止めない（2026-11-12。以前は1件の失敗で、
        # 直すまで毎晩すべての店舗の予測が保存されなくなった）。失敗は状態の文と errors.log に出す。
        problems = []
        if due:
            readable = {s for s in STORES if SOURCES[s] in loaded}
            unrecorded = record_outcomes(journal, rows, today, readable if len(readable) < len(STORES) else None,
                                         prediction_start=prediction_start)
            for key, error in unrecorded:
                error_log.note(data_dir, 'daily-learning', f'結果の記録 {key}: {type(error).__name__}: {error}')
            if unrecorded:
                problems.append(f'結果の記録で処理失敗（{len(unrecorded)}件。{explain(unrecorded[0][1])}）。'
                                '次の実行でやり直し、そろうまで採用判定を待ちます')
        try:
            decisions(journal, today)
        except Exception as error:     # noqa: BLE001 - 判定は次の実行でやり直せる（確定前の書き込みは取り消される）
            error_log.note(data_dir, 'daily-learning', f'採用判定: {type(error).__name__}: {error}')
            problems.append(f'採用判定で処理失敗（{explain(error)}）。採用の状態は変えていません')
        statuses = []
        low = None
        rows = [r for r in rows if r['day'] >= prediction_start]
        for store in STORES:
            name = STORE_NAMES[store]
            if store in saved:
                # 分析用JSONを読めずに保存した晩は、あとの実行でも分かるように出し続ける。
                note = (journal.get('predictions', target + '|' + store) or {}).get('archive_error')
                statuses.append(f'{name}：{label}の事前予測は保存済みです' + (ARCHIVE_NOTE if note else ''))
                continue
            if SOURCES[store] in open_skip:
                statuses.append(f'{name}：取り込み中のため待機（取り込み画面が閉じたあとに保存します）')
                trace(data_dir, statuses[-1])
                continue
            if SOURCES[store] in writing:
                statuses.append(f'{name}：取り込み中のため待機（書き込み終了後{max(1, int(quiet) // 60)}分で保存します）')
                trace(data_dir, statuses[-1])
                continue
            if SOURCES[store] in failed:
                statuses.append(f'{name}：処理失敗（{explain(failed[SOURCES[store]])}）。従来方式を使用してください')
                continue
            try:
                trace(data_dir, f'{name}：データを確かめます')
                if low is None:
                    low = skipped_low_racks(data_dir, target)
                why = ready(rows, target, (store,), low)
                if why:
                    statuses.append(f'{name}：取り込み待ち：' + '。'.join(why))
                    trace(data_dir, statuses[-1])
                    continue
                trace(data_dir, f'{name}：予測を計算します')
                store_rows = [r for r in rows if r['store'] == store]
                ps = pscube if store.startswith('pscube:') else {'records': [], 'machines': []}
                # アナスロの分析用JSON（幸町・P-STATIONのジャグラー・ハナハナ）を過去の学習にだけ足す（daily_learning_archive.py）。
                archive_note = {}
                try:
                    history_rows = daily_learning_archive.merge(store_rows, store, target)
                    archive_note = {'archive_files': daily_learning_archive.fingerprints(store)}
                    if store in daily_learning_archive.FOLDERS and not archive_note['archive_files']:
                        # フォルダーごと無い・空のときも黙って学習量を減らさない（2026-11-12。予測は原本DBだけで続ける）。
                        archive_note['archive_error'] = '分析用JSONのファイルがありません'
                except Exception as error:     # noqa: BLE001 - 分析用JSONが読めなくても、原本DBだけで予測する
                    error_log.note(data_dir, 'daily-learning', f'{store}: 分析用JSON: {type(error).__name__}: {error}')
                    history_rows, archive_note = store_rows, {'archive_error': f'{type(error).__name__}: {error}'[:200]}
                prediction = build_prediction(store_rows, ps, target, journal, node, history_rows=history_rows)
                if not prediction['groups']:
                    statuses.append(f'{name}：候補を選べるデータが不足しています')
                    continue
                prediction |= archive_note
                inputs = {'rows': store_rows}
                archive_rows = [r for r in history_rows if r.get('archive')]
                if archive_rows:
                    inputs['archive_rows'] = archive_rows
                if store.startswith('pscube:'):
                    inputs |= {'pscube_records': ps['records'], 'pscube_machines': ps['machines']}
                journal.freeze(target, prediction, inputs, clock(), store=store)
                control_reason = prediction.get(daily_learning_fixed.STUDY, {}).get('reason')
                if control_reason:
                    trace(data_dir, f'{name}：{control_reason}')
                with journal.db:
                    if journal.get('state', 'start') is None:
                        journal.state('start', target)
                statuses.append(f'{name}：{label}の事前予測を固定保存しました'
                                + (ARCHIVE_NOTE if 'archive_error' in archive_note else ''))
                trace(data_dir, f'{name}：固定保存しました')
            except LateError:
                statuses.append(f'{name}：計算中に23:30（対象日の切替）を過ぎたため、{label}の事前予測は保存していません')
                trace(data_dir, statuses[-1])
            except Exception as error:     # noqa: BLE001 - 1店舗の失敗でほかの店の保存・表示を止めない
                error_log.note(data_dir, 'daily-learning', f'{store}: {type(error).__name__}: {error}')
                statuses.append(f'{name}：処理失敗（{explain(error)}）。従来方式を使用してください')
                trace(data_dir, statuses[-1])
        status = '／'.join(statuses + problems)
        folder = core.resolve_sync_dir(data_dir) if sync else None
        if sync and folder is None:
            status += '／同期先未設定または利用不可'
        return export(journal, data_dir, status, clock(), folder)
    except Exception as error:
        try:
            export(journal, data_dir, f'処理失敗（{explain(error)}）。従来方式を使用してください', clock(),
                   core.resolve_sync_dir(data_dir) if sync else None)
        except Exception:      # noqa: BLE001 - 失敗の表示を書けないときも元の例外を伝える
            pass
        raise
    finally:
        journal.close()


TRACE_NAME = 'run.log'
TRACE_KEEP = 2000


def trace(data_dir, text, *, now=None):
    """日次学習の実行の記録を1行足す（2026-11-20）。11/20 7:08 の実行が長町南を保存したあと止まり、PCアプリの作業記録欄は
    ファイルに残らないので、どこで止まったか分からなかった。開始・原本の読み込み・店ごとの確認と計算・終了の時刻を残す。
    成績は書かない。書けなくても日次学習は止めない。長くなったら古い行から捨てる。"""
    try:
        path = Path(data_dir) / 'daily-learning' / TRACE_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        stamp = jst(now or datetime.now(JST)).isoformat(timespec='seconds')
        line = stamp + '\t' + ' '.join(str(text).split())[:300] + '\n'
        with open(path, 'a', encoding='utf-8') as f:
            f.write(line)
        if path.stat().st_size > TRACE_KEEP * 200:
            lines = path.read_text(encoding='utf-8').splitlines(keepends=True)[-TRACE_KEEP:]
            path.write_text(''.join(lines), encoding='utf-8')
    except Exception:  # noqa: BLE001 - 記録の失敗で日次学習を止めない
        pass


def run(data_dir, **kwargs):
    from backup_status import output_lock
    trace(data_dir, '依頼を受けました（鍵を待ちます）')
    # 既存のOSファイルロックはプロセス終了時にも解除される。
    with output_lock(Path(data_dir) / 'daily-learning', 'meruhen'):
        try:
            result = _run(data_dir, **kwargs)
        except Exception as error:
            trace(data_dir, f'失敗で終了：{type(error).__name__}: {error}')
            raise
        trace(data_dir, '終了：' + str(result.get('status', '')))
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=Path(__file__).with_name('data'))
    parser.add_argument('--no-sync', action='store_true')
    parser.add_argument('--node')
    args = parser.parse_args()
    try:
        result = run(args.data_dir, sync=not args.no_sync, node=args.node)
        print(result['status'])
    except Exception as error:
        print(f'日次学習に失敗しました：{type(error).__name__}: {error}')
        return 1
    return 1 if '処理失敗' in result['status'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
