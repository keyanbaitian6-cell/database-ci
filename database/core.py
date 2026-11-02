"""Local storage and transparent scoring for database."""
from __future__ import annotations

import html
import json
import math
import re
import shutil
import sqlite3
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from file_io import atomic_copy, atomic_writer
import input_versions

from setting_estimate import candidate_label, estimate_setting
from normal_day_context import normal_day_context_html

VERSION = '2026-09-29-v12'
MIN_REFERENCE_ROWS = 20  # Initial operational default, not statistical confidence.
OBSERVATION_KEEP_DAYS = 30  # How long the write log keeps its lines (it is never read by the app).
HISTORY_REPORT_DAYS = 14    # How many of the most recent dates the history page draws.
# Descriptive daily score. No setting probabilities or next-day win prediction.
# The same policy is implemented in database_android/lib/scoring.dart.
# See SCORING_POLICY.md for policy choices, limitations and validation.
MAX_GAMES_SCORE = 0
MAX_HOLD_SCORE = 20
MAX_HITS_SCORE = 60
MAX_POSITIVE_SCORE = 10
MAX_RETENTION_SCORE = 10
SHRINK_GAMES = 1500  # Policy parameters, not a fitted probability model.
SHRINK_DAYS = 3
# 当日この回転数以下の台は採点しない（利用者の指定、2026-09-25）。
MIN_SCORED_GAMES = 500
# 出玉のコンプリート上限。利用者の記録（最大持玉19,008枚で打ち止め）から採用した値で、
# 規則の条文を確認したものではない。機種ごとの上限の違いも見ていない。
COMPLETE_HOLD = 19000
# iPhoneの閲覧ページが読む軽いファイル（画像なし・直近の日数だけ）。同期フォルダに置く。
VIEWER_FILE_NAME = 'database-viewer.json'
VIEWER_DAYS = 60
VIEWER_KEYS = ('store', 'kind_code', 'day', 'machine', 'rack', 'games', 'bb', 'rb', 'max_hold',
               'graph_measurement', 'captured_at', 'confirmed_setting',
               # 確定が出た台の印🌈（PCで付ける。RAINBOW.md）
               'rainbow', 'rainbow_at',
               # ジャグラーオンラインの差枚（お試し、JUGGLER_ONLINE.md）。閲覧ページは推定差枚より優先する。
               'jo_net', 'record_updated_at')
# 取り込みの対象外の機種。次の機種の候補にせず、印は「対象外」にし、表・グラフも保存しない。
# 長町南店はジャグラーシリーズ、幸町店はブラックボードを公開していない。
# （幸町のジャグラー、長町南のスーパーブラックジャック等は対象のまま）
# 沖ドキ（サイトの表記は「沖ドキ」「オキドキ」の両方）は、両店とも利用者の指定で対象外（2026-09-29）。
# 幸町の聖闘士星矢 海皇覚醒（1279番台の1台だけ）は、ずっと稼働停止のため利用者の指定で対象外
# （2026-10-11「取り込まない、表示しないようにしてほしい」）。
_OKIDOKI_WORDS = ('沖ドキ', 'オキドキ')
EXCLUDED_MACHINE_WORDS = {'nagamachiminami': ('ジャグラー', *_OKIDOKI_WORDS),
                          'saiwaichou': ('ブラックボード', '聖闘士星矢海皇覚醒', *_OKIDOKI_WORDS)}
EXCLUDED_MACHINE_NOTES = {'nagamachiminami': '長町南店のジャグラーと沖ドキ',
                          'saiwaichou': '幸町店のブラックボード・聖闘士星矢 海皇覚醒（稼働停止）と沖ドキ'}


# 表示しない機種（取り込みの対象外のうち、以前に保存した記録も出さないもの）。保存せず、保存済みの記録も
# 消さずに読み出し（Store.rows・raw_payloads・閲覧用ファイル・カレンダー）から外す。沖ドキなど、対象外にする
# 前に取り込んだ記録は今までどおり出す（利用者が外すよう頼んだのは1279番台だけ）。
HIDDEN_MACHINE_WORDS = {'saiwaichou': ('聖闘士星矢海皇覚醒',)}


def _machine_text(name):
    return ''.join(unicodedata.normalize('NFKC', str(name or '')).split())


def is_hidden_machine(location, name):
    """表示しない機種か（[HIDDEN_MACHINE_WORDS]）。"""
    text = _machine_text(name)
    return any(word in text for word in HIDDEN_MACHINE_WORDS.get(location, ()))


def is_excluded_machine(location, name):
    """取り込みの対象外の機種か。長町南は機種名が半角カナのこともある（例「ｶﾊﾞﾈﾘ」「沖ﾄﾞｷ」）
    ため、NFKCで全角へそろえてから判定する（「ｼﾞｬｸﾞﾗｰ」も「ジャグラー」として扱う）。
    空白は無視する（「聖闘士星矢 海皇覚醒」も「聖闘士星矢海皇覚醒」として扱う）。"""
    words = EXCLUDED_MACHINE_WORDS.get(location, ())
    text = _machine_text(name)
    return any(word in text for word in words)


STORE_NAMES = {
    'nagamachiminami': 'メルヘンワールド長町南店',
    'saiwaichou': 'スーパーメルヘンワールド幸町',
}
CONFIRMED_SETTING_OPTIONS = ('4以上', '5以上', '6')
DATE_EVENT_OPTIONS = ('超探す楽しみ', '半列', '4台構成', 'バラエティ', '華の日')
INITIAL_DATE_EVENTS = [
    {'store': 'nagamachiminami', 'day': f'2026-09-{day:02}', 'name': '4台構成'}
    for day in range(14, 21)
] + [
    {'store': 'nagamachiminami', 'day': f'2026-09-{day:02}', 'name': '超探す楽しみ'}
    for day in range(21, 28)
]


def implausible_numbers(row):
    """The site's placeholder for racks under maintenance (games 88888888,
    BB/RB 888, max hold 88888888) or numbers a day cannot produce. Such rows are
    never scored, compared, used for candidates or setting estimates (same rule
    as Android's hasImplausibleNumbers)."""
    return ((row.get('games') or 0) > 20000 or (row.get('bb') or 0) > 500
            or (row.get('rb') or 0) > 500 or (row.get('max_hold') or 0) > 100000)


def spin_score(g):
    if g is None or g <= 0:
        return None
    return 0.0  # Exposure changes shrinkage, never earns points by itself.


def round_score(value):
    """Non-negative scores use the same half-up rounding as Dart."""
    return math.floor(value * 10 + 0.5) / 10


def graph_metrics(path, baseline, tolerance=1.0):
    """Read the rendered SVG M/L polyline, never infer coin amounts."""
    if not path:
        return None
    parts = re.findall(r'([ML])\s*(-?\d+(?:\.\d+)?)\s*,?\s*(-?\d+(?:\.\d+)?)', path)
    residual = re.sub(r'[ML]\s*-?\d+(?:\.\d+)?\s*,?\s*-?\d+(?:\.\d+)?', '', path)
    if residual.strip() or len(parts) < 2 or parts[0][0] != 'M':
        raise ValueError('未対応のグラフ形式です。評価を保留します。')
    points = [(float(x), float(y)) for _, x, y in parts]
    if any(b[0] < a[0] for a, b in zip(points, points[1:])):
        raise ValueError('グラフの横軸が単調ではありません。')
    baseline = float(baseline)
    if not math.isfinite(baseline) or abs(points[0][1] - baseline) > tolerance:
        raise ValueError('グラフの開始点とゼロ線が一致しません。')
    peak = max(0.0, baseline - min(y for _, y in points))
    end = baseline - points[-1][1]
    uncertain = 0 < abs(end) <= tolerance
    positive = None if uncertain else (float(MAX_POSITIVE_SCORE) if end > 0 else 0.0)
    retention = None if uncertain else (MAX_RETENTION_SCORE * max(0, min(1, end / peak)) if peak else 0.0)
    return dict(baseline=baseline, peak_height=peak, end_height=end,
                positive_score=positive, retention_score=retention, points=points)


def measurement_metrics(measurement, tolerance=1.0):
    """Score user-confirmed graph positions from a screenshot."""
    try:
        baseline = float(measurement['baseline_y'])
        peak_y = float(measurement['peak_y'])
        end_y = float(measurement['end_y'])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('スクショのグラフ測定値が不完全です。') from exc
    if not all(math.isfinite(v) for v in (baseline, peak_y, end_y)):
        raise ValueError('スクショのグラフ測定値が不正です。')
    peak = max(0.0, baseline - peak_y)
    end = baseline - end_y
    uncertain = 0 < abs(end) <= tolerance
    positive = None if uncertain else (float(MAX_POSITIVE_SCORE) if end > 0 else 0.0)
    retention = None if uncertain else (MAX_RETENTION_SCORE * max(0, min(1, end / peak)) if peak else 0.0)
    return dict(baseline=baseline, peak_height=peak, end_height=end,
                positive_score=positive, retention_score=retention)


def normalize_machine_name(value):
    """Same machine, one spelling: '+' and runs of spaces become one space.

    Old PC rows and some site pages spell spaces as '+'. Compared as-is, the
    same rack is saved twice under two machine names (Android does the same
    in ``normalizeMachineName``).
    """
    if not value:
        return ''
    return ' '.join(str(value).replace('+', ' ').split())


def _merge_spellings(kept, other):
    """One payload from two spellings of the same rack (Android's rule).

    The side with more games has the newer numbers; a graph, link or setting
    only one side has is kept; the first capture time is the earlier one.
    """
    newest, older = (kept, other) if kept.get('games', 0) >= other.get('games', 0) else (other, kept)
    merged = {**older, **{k: v for k, v in newest.items() if v is not None}}
    if not (newest.get('graph') or newest.get('graph_measurement')):
        for k in ('graph', 'graph_measurement'):
            if older.get(k):
                merged[k] = older[k]
    firsts = [v for v in (kept.get('first_captured_at'), other.get('first_captured_at')) if v]
    if firsts:
        merged['first_captured_at'] = min(firsts, key=_timestamp)
    merged['machine'] = normalize_machine_name(merged.get('machine'))
    return merged


def _timestamp(value):
    """ISO time for ordering; one without an offset is taken as this PC's time."""
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.astimezone()


# イベントカレンダー（EVENT_CALENDAR.md、2026-10-07）：入力時刻つき・新しい方が上書き・消した印を残す。
EVENT_JST = timezone(timedelta(hours=9))
# 営業日は日本時間の午前3時で切り替わる（browser_import.BUSINESS_DAY_CUTOFF_HOUR と同じ。2026-10-26に2時から3時へ）。
EVENT_DAY_START_HOUR = 3


def _record_after_deletion(row, mark):
    stamps = [_record_operation_time(row.get('record_updated_at')), _record_operation_time(row.get('captured_at'))]
    return any(stamp and stamp > _timestamp(mark['deleted_at']) for stamp in stamps)


def _record_operation_time(value):
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=EVENT_JST)


def _valid_record_deletion(mark):
    if not isinstance(mark, dict) or mark.get('store') not in STORE_NAMES:
        return False
    try:
        if date.fromisoformat(mark['day']).isoformat() != mark['day']:
            return False
        return (isinstance(mark.get('machine'), str) and bool(mark['machine'].strip())
                and type(mark.get('rack')) is int and mark['rack'] > 0
                and _event_time(mark.get('deleted_at')) is not None)
    except (KeyError, TypeError, ValueError):
        return False


def _event_time(value):
    """An event's updated_at as an aware datetime; None if absent or unreadable."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None


def _valid_date_event(event):
    if not isinstance(event, dict) or event.get('store') not in STORE_NAMES:
        return False
    try:
        date.fromisoformat(event.get('day', ''))
    except (TypeError, ValueError):
        return False
    if 'updated_at' in event and _event_time(event['updated_at']) is None:
        return False
    name = event.get('name')
    if name is None:
        # 「イベントを消した」印は、入力時刻のあるものだけ。
        return 'updated_at' in event
    return isinstance(name, str) and 0 < len(name.strip()) <= 60


def _clean_date_event(event):
    cleaned = {'store': event['store'], 'day': event['day'],
               'name': event['name'].strip() if isinstance(event.get('name'), str) else None}
    if 'updated_at' in event:
        cleaned['updated_at'] = event['updated_at']
    return cleaned


def merge_date_events(stored, incoming):
    """Merge event lists by store/day (EVENT_CALENDAR.md).

    Both timed: the newer wins (a tie goes to the incoming one). Only one timed:
    the timed one wins. Neither timed: keep the stored one, counting a different
    name as a conflict. Removal marks (name None) follow the same rule.
    Returns (merged events, number changed, number of conflicts)."""
    events = {(e['store'], e['day']): _clean_date_event(e) for e in stored}
    changed = conflicts = 0
    for raw in incoming:
        event = _clean_date_event(raw)
        key = (event['store'], event['day'])
        old = events.get(key)
        if old is None:
            take = True
        else:
            new_at, old_at = _event_time(event.get('updated_at')), _event_time(old.get('updated_at'))
            if new_at is not None and old_at is not None:
                take = new_at >= old_at
            elif new_at is not None or old_at is not None:
                take = new_at is not None
            else:
                take = False
                conflicts += old['name'] != event['name']
        if take and old != event:
            events[key] = event
            changed += 1
    return list(events.values()), changed, conflicts


# 共有カレンダー（EVENT_CALENDAR.md、2026-10-08）：閲覧ページで入れたイベントをApps Scriptが
# 同期フォルダに書くファイル。PCは届いたものを取り込む（書き換えない）。
SHARED_EVENTS_NAME = 'database-events-shared.json'


def pull_shared_events(store, folder):
    """Merge the shared events file in the sync ``folder`` into ``store``.

    Only timed events are taken; an unreadable or invalid file is ignored (the
    events stay in the file for the next try). Returns the number changed."""
    path = Path(folder) / SHARED_EVENTS_NAME if folder else None
    if path is None or not path.is_file():
        return 0
    try:
        events = json.loads(path.read_text(encoding='utf-8-sig')).get('events')
    except (OSError, ValueError, AttributeError):
        return 0
    if not isinstance(events, list):
        return 0
    timed = [e for e in events if _valid_date_event(e) and 'updated_at' in e]
    merged, changed, _conflicts = merge_date_events(store.date_events(include_removed=True), timed)
    if changed:
        store.set_date_events(merged)
    return changed


# iPhoneの閲覧ページで付け外しした🌈（RAINBOW.md「iPhoneから付ける」、2026-10-11）。Apps Script が同期フォルダに書く。
SHARED_RAINBOW_NAME = 'database-rainbow-shared.json'

SHARED_HISTORY_NAME = 'database-event-history-shared.json'


def pull_shared_history(store, folder):
    """共有で編集した結果記号を合流する。週・機種対応は共有から作らない。"""
    path = Path(folder) / SHARED_HISTORY_NAME if folder else None
    if path is None or not path.is_file():
        return 0, 0, 0, 0
    from event_history_data import validate_envelope, VARIETY_KEY
    raw = json.loads(path.read_text(encoding='utf-8-sig'))
    validate_envelope(raw)
    if raw.get('weeks') or raw.get('links') or VARIETY_KEY in raw:
        raise ValueError('共有の履歴では週の構成・機種対応は変更できません。')
    # 「共有の編集」の除外数に、PCに保存済みの基準外原文を混ぜない。
    return store.merge_history_edits(raw, count_stored_rejected=False)


def sync_shared_history(store, data_dir, notices=None):
    """本体DBに共有編集を取り込む。失敗時も既存のバックアップ出力は続ける。"""
    try:
        folder = resolve_sync_dir(data_dir)
        _changed, _conflicts, rejected, _skipped = pull_shared_history(store, folder)
        if rejected and notices is not None:
            notices.append(f'共有のイベント履歴は形式が合わない編集{rejected}件を除外しました。')
    except (OSError, ValueError, sqlite3.Error) as error:
        if notices is not None:
            notices.append(f'共有のイベント履歴を取り込めませんでした（元の記録は保持）：{error}')


def _valid_rainbow_mark(mark):
    try:
        return (isinstance(mark, dict) and mark.get('store') in STORE_NAMES
                and date.fromisoformat(mark.get('day', '')).isoformat() == mark['day']
                and type(mark.get('rack')) is int and 0 < mark['rack'] < 100000
                and isinstance(mark.get('on'), bool) and isinstance(mark.get('updated_at'), str)
                and _timestamp(mark['updated_at']) is not None)
    except (TypeError, ValueError):
        return False


def pull_shared_rainbow(store, folder):
    """同期フォルダの共有ファイル（iPhoneで付け外しした🌈）を記録に取り込む。付け外しした時刻が、その台の
    rainbow_at（PCで付け外しした時刻・前に取り込んだ時刻）より新しいものだけ。その日の記録がまだ無い台は飛ばす
    （ファイルに残るので、表を取り込んだあとの次の取り込みで入る）。読めない・形の違うファイルは無視。
    変わった台の数を返す。"""
    path = Path(folder) / SHARED_RAINBOW_NAME if folder else None
    if path is None or not path.is_file():
        return 0
    try:
        marks = json.loads(path.read_text(encoding='utf-8-sig')).get('marks')
    except (OSError, ValueError, AttributeError):
        return 0
    if not isinstance(marks, list):
        return 0
    changed = 0
    for mark in marks:
        if not _valid_rainbow_mark(mark):
            continue
        rows = store.db.execute(
            "SELECT machine, json_extract(payload, '$.rainbow'), json_extract(payload, '$.rainbow_at') FROM days"
            " WHERE store=? AND day=? AND rack=? AND json_valid(payload)",
            (mark['store'], mark['day'], mark['rack'])).fetchall()
        rows = [r for r in rows if not is_hidden_machine(mark['store'], r[0])]
        if not rows:
            continue
        newer = all(not at or _timestamp(mark['updated_at']) > _timestamp(at) for _m, _on, at in rows)
        if not newer:
            continue
        if any((on == 1) != mark['on'] for _m, on, _at in rows) or any(at != mark['updated_at'] for *_x, at in rows):
            store.set_rainbow(mark['store'], mark['day'], mark['rack'], mark['on'], at=mark['updated_at'])
            changed += 1
    return changed


def date_event_in_advance(event):
    """True when the event was entered before 03:00 JST of its day (the end of the
    previous business day). Untimed events are never counted as entered in advance."""
    at = _event_time(event.get('updated_at'))
    if at is None:
        return False
    start = datetime.fromisoformat(event['day']).replace(hour=EVENT_DAY_START_HOUR, tzinfo=EVENT_JST)
    return at < start


class Store:
    def __init__(self, path, *, recording=True):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = input_versions.connect(self.path, recording=recording)
        try:
            self._initialize()
        except BaseException:
            # 壊れたDBなどで初期化に失敗しても、接続・ファイルロックを残さない。
            self.db.close()
            raise

    def _initialize(self):
        self.db.execute('CREATE TABLE IF NOT EXISTS observations (id INTEGER PRIMARY KEY, captured_at TEXT NOT NULL, payload TEXT NOT NULL)')
        # 1行保存するたびの古い行の削除（_log_observation）が、索引なしでは全件（数万行・数十MB）を読んでいた。
        # 新しいバックアップ551行の取り込みで約21秒画面が止まった主因（2026-10-14 レビュー、専用コピーで計測）。
        self.db.execute('CREATE INDEX IF NOT EXISTS observations_captured_at ON observations(captured_at)')
        self._ensure_store_schema()
        # 機種ごとの全記録（採点・翌日候補・バラエティ）を店＋機種で引く。主キーは店・日・機種・台の順なので、
        # 索引なしでは機種ごとに店の全行を読み直していた（2026-10-25、複製DBで2.3秒→0.6秒）。
        self.db.execute('CREATE INDEX IF NOT EXISTS days_store_machine ON days(store, machine, day)')
        # 翌日候補（仮）の記録。Android版と同じ形（candidate_log.dart）。
        self.db.execute('CREATE TABLE IF NOT EXISTS candidate_snapshots (store TEXT NOT NULL, day TEXT NOT NULL, '
                        'machine TEXT NOT NULL, taken_at TEXT NOT NULL, payload TEXT NOT NULL, '
                        'PRIMARY KEY(store, day, machine, taken_at))')
        self.db.execute('CREATE TABLE IF NOT EXISTS app_state (state_key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        if self.state('date_events') is None:
            self.set_date_events(INITIAL_DATE_EVENTS)
        self.db.commit()
        input_versions.attach(self.db, self.path.parent, 'meruhen')
        self._merge_machine_spellings()
        self.db.commit()
        # 翌日候補の店舗別案を並べて比べるための版の記録（input_versions.py）。失敗しても開ける。
        if not input_versions.attach(self.db, self.path.parent, 'meruhen'):
            try:
                with self.db:
                    failures = self.state('input_versions_failures')
                    self.db.execute("INSERT OR REPLACE INTO app_state VALUES('input_versions_failures', ?)",
                                    (str(int(failures) + 1 if failures else 1),))
                    self.db.execute("INSERT OR REPLACE INTO app_state VALUES('input_versions_last_error', ?)",
                                    (input_versions.state().get('meruhen', ''),))
            except sqlite3.Error:
                pass

    def _merge_machine_spellings(self):
        """Fold rows saved under a '+'-spelled machine name into the normal one.

        Runs once per open and does nothing when every name is already
        normalized. A copy of the database is kept first, as the store
        migration above does.
        """
        # Keys only: reading every payload (graph images included) on each open
        # made opening the database grow with the data for no reason.
        # 機種名の種類（数百）だけを点検する。全行（数万）の名前を毎回直すと、DBを開くたびに
        # 0.1〜0.5秒かかり、バラエティ🌈のタブでは開き直しが重なって数秒になった（2026-10-25）。
        names = [name for (name,) in self.db.execute('SELECT DISTINCT machine FROM days')]
        odd_names = [name for name in names if name != normalize_machine_name(name)]
        keys = [k for name in odd_names
                for k in self.db.execute('SELECT store,day,machine,rack FROM days WHERE machine IS ?', (name,))]
        odd = [(*k, self.db.execute('SELECT payload FROM days WHERE store=? AND day=? AND machine=? AND rack=?',
                                    k).fetchone()[0])
               for k in keys]
        if not odd:
            return
        backup_path = self.path.with_name(self.path.stem + '.pre-machine-name-fix' + self.path.suffix)
        if self.path.exists() and not backup_path.exists():
            backup = sqlite3.connect(backup_path)
            try:
                self.db.backup(backup)
            finally:
                backup.close()
        with self.db:
            for location, day, machine, rack, raw in odd:
                name = normalize_machine_name(machine)
                try:
                    payload = dict(json.loads(raw), machine=name)
                except ValueError:
                    continue  # 読めない行はそのまま残す（開けなくならないように）
                twin = self.db.execute('SELECT payload FROM days WHERE store=? AND day=? AND machine=? AND rack=?',
                                       (location, day, name, rack)).fetchone()
                if twin:
                    try:
                        payload = _merge_spellings(json.loads(twin[0]), payload)
                    except ValueError:
                        pass  # 読めない片方は、読める方で置き換える
                self.db.execute('DELETE FROM days WHERE store=? AND day=? AND machine=? AND rack=?',
                                (location, day, machine, rack))
                self.db.execute('INSERT INTO days VALUES(?,?,?,?,?) ON CONFLICT(store,day,machine,rack) '
                                'DO UPDATE SET payload=excluded.payload',
                                (location, day, name, rack, json.dumps(payload, ensure_ascii=False)))
        self._machine_cache = {}

    def _ensure_store_schema(self):
        columns = [row[1] for row in self.db.execute('PRAGMA table_info(days)')]
        if not columns:
            self.db.execute('CREATE TABLE days (store TEXT NOT NULL, day TEXT, machine TEXT, rack INTEGER, payload TEXT NOT NULL, PRIMARY KEY(store,day,machine,rack))')
            return
        if 'store' in columns:
            return

        backup_path = self.path.with_name(self.path.stem + '.pre-store-migration' + self.path.suffix)
        if self.path.exists() and not backup_path.exists():
            backup = sqlite3.connect(backup_path)
            try:
                self.db.backup(backup)
            finally:
                backup.close()
        legacy_rows = self.db.execute('SELECT day,machine,rack,payload FROM days').fetchall()
        with self.db:
            self.db.execute('CREATE TABLE days_with_store (store TEXT NOT NULL, day TEXT, machine TEXT, rack INTEGER, payload TEXT NOT NULL, PRIMARY KEY(store,day,machine,rack))')
            for day, machine, rack, raw in legacy_rows:
                payload = json.loads(raw)
                location = payload.get('store') or 'nagamachiminami'
                if location not in STORE_NAMES:
                    location = 'nagamachiminami'
                    payload['store'] = location
                    raw = json.dumps(payload, ensure_ascii=False)
                self.db.execute('INSERT INTO days_with_store VALUES(?,?,?,?,?)',
                                (location, day, machine, rack, raw))
            self.db.execute('DROP TABLE days')
            self.db.execute('ALTER TABLE days_with_store RENAME TO days')

    def save(self, rows, log_candidates=True):
        """Save rows; with ``log_candidates`` the changed next-day candidates are
        recorded in the same transaction (a backup import passes False: the
        candidates of old days recomputed now are not what was shown then)."""
        with self.db:
            self._begin_write()
            # A direct save is an explicit capture/restore. Imported backups use
            # _save_rows and cannot turn an old record into a new operation.
            deleted = {self._record_key(m): m for m in self.record_deletions()}
            rows = [dict(row, record_updated_at=max(datetime.now().astimezone(),
                        _timestamp(deleted[self._record_key(row)]['deleted_at']) + timedelta(milliseconds=1)).isoformat())
                    if self._record_key(row) in deleted else row for row in rows]
            self._save_rows(rows, log_candidates)

    def _begin_write(self):
        """読んでから一覧全体を書き戻す前に、書き込みロックを取る（呼ぶ側の ``with self.db`` が確定・取り消し）。
        PC本体と取り込みブラウザは別プロセスで同じDBに書く。ロックの外で読んだ未取り込みの🌈の一覧を
        書き戻すと、その間に他方が足した印を消していた（2026-10-14 レビュー）。"""
        if not self.db.in_transaction:
            self.db.execute('BEGIN IMMEDIATE')

    def _save_rows(self, rows, log_candidates):
        """``save`` の中身。トランザクションは呼ぶ側が持つ（バックアップの取り込みは、
        イベント名・台・翌日候補の記録を1回で書くため）。"""
        self._machine_cache = {}
        groups = set()
        self._begin_write()
        deleted = {self._record_key(m): m for m in self.record_deletions()}
        pending = {(m['store'], m['day'], m['rack']): m for m in self.pending_rainbow_marks()}
        applied_marks = set()
        for row in rows:
            row = dict(row, machine=normalize_machine_name(row.get('machine')))
            if row.get('kind_code') != 21 or row.get('store') not in STORE_NAMES:
                raise ValueError('対象は長町南店・幸町店の1000円46枚スロットのみです。')
            if is_hidden_machine(row['store'], row['machine']):
                continue
            date.fromisoformat(row['day'])
            key = (row['store'], row['day'], row['machine'], int(row['rack']))
            if key in deleted and not _record_after_deletion(row, deleted[key]):
                continue
            old = self.db.execute('SELECT payload FROM days WHERE store=? AND day=? AND machine=? AND rack=?', key).fetchone()
            try:
                merged = json.loads(old[0]) if old else {}
            except ValueError:
                # 読めない行は無いものとして上書きする（rows() でも飛ばしている）。
                old, merged = None, {}
            # Preserve a graph only while its corresponding source numbers match.
            changed = any(k in merged and k in row and row[k] is not None and merged[k] != row[k]
                          for k in ('games','bb','rb','max_hold'))
            if changed and not row.get('graph'):
                merged.pop('graph', None)
                merged.pop('graph_measurement', None)
            rainbow = _newer_rainbow(merged, row)
            mark_key = (row['store'], row['day'], int(row['rack']))
            if mark_key in pending:
                mark = pending[mark_key]
                rainbow = _newer_rainbow(rainbow, dict(rainbow=mark['on'], rainbow_at=mark['updated_at']))
                applied_marks.add(mark_key)
            merged.update({k: v for k, v in row.items() if v is not None})
            # 🌈は付け外しした時刻（rainbow_at）の新しい方を残す（RAINBOW.md）。PCで外したあとに、🌈の付いた
            # 古いバックアップ（グラフ追加など）を読み込んでも付き直らない。
            merged.pop('rainbow', None)
            merged.pop('rainbow_at', None)
            merged.update(rainbow)
            # ジャグラーオンラインの数字で作った台（jo_created、JUGGLER_ONLINE.md）を、あとでサイトの表から
            # 取り込み直したら、作った台の印は外す（数値はサイトのもの。差枚 jo_net などは残す）。
            if merged.get('jo_created') and not row.get('jo_created') and (row.get('source_url') or row.get('detail_url')):
                merged.pop('jo_created', None)
            # First save time never moves on a re-capture (same as Android's
            # first_captured_at). A row saved before this existed stays unknown.
            firsts = [v for v in (json.loads(old[0]).get('first_captured_at') if old else None,
                                  row.get('first_captured_at')) if v]
            if firsts:
                merged['first_captured_at'] = min(firsts, key=_timestamp)
            elif not old:
                merged['first_captured_at'] = datetime.now().astimezone().isoformat()
            self._log_observation(row)
            self.db.execute('INSERT INTO days VALUES(?,?,?,?,?) ON CONFLICT(store,day,machine,rack) DO UPDATE SET payload=excluded.payload', (*key, json.dumps(merged, ensure_ascii=False)))
            groups.add((key[0], key[2], key[1]))
        if applied_marks:
            self._write_pending_rainbow_marks([m for k, m in pending.items() if k not in applied_marks])
        if log_candidates:
            self._log_candidates(groups)
        self._machine_cache = {}

    def _log_candidates(self, groups):
        """Record the next-day candidates changed by a write (inside its transaction).

        Only the written day and later days (30 days) of the same store and
        machine can change. A row is added only when the content differs from
        the last one. A failure to compute never undoes the save: it is counted
        in ``app_state`` so it is visible, as on Android.
        """
        try:
            affected = set()
            for location, machine, day in groups:
                last = (date.fromisoformat(day) + timedelta(days=30)).isoformat()
                affected.add((location, machine, day))
                for (later,) in self.db.execute(
                        'SELECT DISTINCT day FROM days WHERE store=? AND machine=? AND day>? AND day<=?',
                        (location, machine, day, last)):
                    affected.add((location, machine, later))

            def latest_of(location, day, machine):
                found = self.db.execute(
                    'SELECT payload FROM candidate_snapshots WHERE store=? AND day=? AND machine=? '
                    'ORDER BY taken_at DESC LIMIT 1', (location, day, machine)).fetchone()
                return json.loads(found[0]) if found else None

            # その日にバラエティ（1〜3台）の機種は、機種ではなくその日その店のバラエティを
            # 計算し直す。台数が変わって機種がバラエティに入った・出た場合に備え、影響する
            # 日のバラエティは毎回計算し直す（中身が変わらなければ記録しない）。
            # Android版 `changedCandidateSnapshots` と同じ決め方。
            counts = {}
            for location, day in {(location, day) for location, _machine, day in affected}:
                counts[(location, day)] = dict(self.db.execute(
                    'SELECT machine, COUNT(*) FROM days WHERE store=? AND day=? GROUP BY machine',
                    (location, day)).fetchall())
            targets = set()
            for location, machine, day in affected:
                racks = counts[(location, day)].get(machine, 0)
                previous = latest_of(location, day, machine)
                was_listed = bool(previous and previous.get('candidates'))
                if racks == 0 or racks > variety_max_racks(location) or was_listed:
                    targets.add((location, machine, day))
                has_variety = any(n <= variety_max_racks(location) for n in counts[(location, day)].values())
                if has_variety or latest_of(location, day, VARIETY_GROUP_NAME) is not None:
                    targets.add((location, VARIETY_GROUP_NAME, day))
            self._machine_cache = {}
            now = datetime.now().astimezone()
            for location, machine, day in sorted(targets):
                snapshot = candidate_snapshot(self, location, day, machine, now)
                latest = latest_of(location, day, machine)
                if latest and candidate_signature(latest) == candidate_signature(snapshot):
                    continue
                self.db.execute('INSERT OR IGNORE INTO candidate_snapshots VALUES(?,?,?,?,?)',
                                (location, day, machine, snapshot['taken_at'],
                                 json.dumps(snapshot, ensure_ascii=False)))
        except Exception as exc:  # noqa: BLE001 - counted, never blocks the save
            failures = self.db.execute("SELECT value FROM app_state WHERE state_key='candidate_log_failures'").fetchone()
            count = int(failures[0]) + 1 if failures else 1
            self.db.execute("INSERT OR REPLACE INTO app_state VALUES('candidate_log_failures', ?)", (str(count),))
            self.db.execute("INSERT OR REPLACE INTO app_state VALUES('candidate_log_last_error', ?)", (repr(exc),))

    def candidate_snapshots(self, day=None, location=None):
        query, values = 'SELECT payload FROM candidate_snapshots WHERE 1=1', []
        if location:
            query += ' AND store=?'
            values.append(location)
        if day:
            query += ' AND day=?'
            values.append(day)
        return [x[0] for x in self.db.execute(query + ' ORDER BY taken_at', values)]

    def add_candidate_snapshots(self, snapshots):
        """Merge candidate records from a backup (same group and time = same row)."""
        with self.db:
            return self._add_candidate_snapshots(snapshots)

    def _add_candidate_snapshots(self, snapshots):
        added = 0
        for s in snapshots:
            if not (isinstance(s, dict) and s.get('store') in STORE_NAMES and s.get('day')
                    and s.get('machine') and s.get('taken_at')):
                continue
            machine = normalize_machine_name(s['machine'])
            cursor = self.db.execute('INSERT OR IGNORE INTO candidate_snapshots VALUES(?,?,?,?,?)',
                                     (s['store'], s['day'], machine, s['taken_at'],
                                      json.dumps(dict(s, machine=machine), ensure_ascii=False)))
            added += cursor.rowcount
        return added

    def state(self, key):
        found = self.db.execute('SELECT value FROM app_state WHERE state_key=?', (key,)).fetchone()
        return found[0] if found else None

    def history_edits_raw(self):
        """バックアップ用。基準に合わなくなった編集も保存した文書のまま返す。"""
        from event_history_data import empty_edits, validate_envelope
        raw = self.state('event_history_edits')
        if not raw:
            return empty_edits()
        try:
            doc = json.loads(raw)
            # 外枠が壊れた文書をそのまま書くと、バックアップ全体が取り込み・復元できなくなる。
            validate_envelope(doc)
            return doc
        except (TypeError, ValueError):
            # 通常の台データのバックアップを妨げず、読めない原文も控えに残す。
            return dict(empty_edits(), unreadable_raw=raw)

    def history_edits_status(self):
        from event_history_data import clean_edits, load_base
        raw = self.history_edits_raw()
        clean, rejected = clean_edits(raw, load_base())
        return clean, rejected + int('unreadable_raw' in raw)

    def history_edits(self):
        """表示・共有用。原文の保持は history_edits_raw を使う。"""
        return self.history_edits_status()[0]

    def _write_history_edits(self, edits):
        from event_history_data import validate_envelope
        # 合流後に上限を超えた文書を書き込むと、次回の読み取りで全履歴が読めなくなる。
        validate_envelope(edits)
        self.db.execute('INSERT OR REPLACE INTO app_state VALUES(?,?)',
                        ('event_history_edits', json.dumps(edits, ensure_ascii=False)))

    def merge_history_edits(self, incoming, *, count_stored_rejected=True):
        from event_history_data import merge_edits, load_base
        with self.db:
            # GUI保存と共有取り込みが並行しても、古い原文で別の編集を上書きしない。
            # 読む前に書き込み権を確保し、合流と保存を一つの操作にする。
            if not self.db.in_transaction:
                self.db.execute('BEGIN IMMEDIATE')
            raw = self.history_edits_raw()
            if 'unreadable_raw' in raw:
                raise ValueError('履歴の原文が読めません。台データの保存・バックアップは続けられます。')
            merged, changed, conflicts, rejected, skipped_weeks = merge_edits(
                raw, incoming, load_base(), count_stored_rejected=count_stored_rejected)
            self._write_history_edits(merged)
        return changed, conflicts, rejected, skipped_weeks

    def date_events(self, location=None, day=None, include_removed=False):
        """Events with a name. ``include_removed`` also returns the removal marks
        (name None) that backups and merging need."""
        try:
            events = json.loads(self.state('date_events') or '[]')
        except (TypeError, ValueError):
            events = []
        return [event for event in events if _valid_date_event(event)
                and (include_removed or event.get('name') is not None)
                and (location is None or event['store'] == location)
                and (day is None or event['day'] == day)]

    def date_event_names(self, location=None):
        """Default choices, then the names in use (newest day first) for the input lists."""
        used = sorted(self.date_events(location=location), key=lambda e: e['day'], reverse=True)
        return list(dict.fromkeys([*DATE_EVENT_OPTIONS, *(e['name'] for e in used)]))

    def set_date_events(self, events):
        with self.db:
            self._write_date_events(self._date_events_payload(events))

    def _write_date_events(self, payload):
        self.db.execute('INSERT OR REPLACE INTO app_state VALUES(?,?)', ('date_events', payload))

    @staticmethod
    def _date_events_payload(events):
        valid = {}
        for event in events:
            if _valid_date_event(event):
                valid[(event['store'], event['day'])] = _clean_date_event(event)
        return json.dumps(list(valid.values()), ensure_ascii=False)

    def set_date_event(self, location, day, name, now=None):
        self.set_date_event_days(location, [day], name, now)

    def set_date_event_days(self, location, days, name, now=None):
        """Give each day the same event name (None or blank removes it), stamped
        with the entry time. Unchanged days keep their old time, so re-entering the
        same name does not turn an event entered in advance into a late one."""
        cleaned = name.strip() if isinstance(name, str) and name.strip() else None
        events = {(e['store'], e['day']): e for e in self.date_events(include_removed=True)}
        stamp = (now or datetime.now()).astimezone(EVENT_JST)
        changed = False
        for day in days:
            previous = events.get((location, day))
            if (previous.get('name') if previous else None) == cleaned:
                continue
            at = stamp
            previous_at = _event_time(previous.get('updated_at')) if previous else None
            if previous_at is not None and at <= previous_at:
                at = previous_at + timedelta(milliseconds=1)
            event = {'store': location, 'day': day, 'name': cleaned,
                     'updated_at': at.isoformat(timespec='milliseconds')}
            if not _valid_date_event(event):
                raise ValueError('イベント名、店舗、日付を確認してください。')
            events[(location, day)] = event
            changed = True
        if changed:
            self.set_date_events(events.values())

    def _log_observation(self, row, keep_days=OBSERVATION_KEEP_DAYS):
        """Append one "what was written when" line, and drop worn-out ones.

        This log is never read back by the app; it exists so a surprising
        number can be traced later. The graph image is left out (it is 80% of
        a record and the current one is always in ``days``), and lines older
        than ``keep_days`` go, so the file cannot grow without end.
        """
        logged = {k: v for k, v in row.items() if k not in ('graph', 'graph_measurement')}
        measurement = row.get('graph_measurement')
        if measurement:
            logged['graph_measurement'] = {k: v for k, v in measurement.items() if k != 'preview_image'}
        now = datetime.now().astimezone()
        self.db.execute('INSERT INTO observations(captured_at,payload) VALUES(?,?)',
                        (now.isoformat(), json.dumps(logged, ensure_ascii=False)))
        self.db.execute('DELETE FROM observations WHERE captured_at < ?',
                        ((now - timedelta(days=keep_days)).isoformat(),))

    def payload_map(self, keys):
        """Current stored payload (or None) for each (store, day, machine, rack) key."""
        result = []
        for key in keys:
            found = self.db.execute(
                'SELECT payload FROM days WHERE store=? AND day=? AND machine=? AND rack=?', key).fetchone()
            result.append(json.loads(found[0]) if found else None)
        return result

    def restore_payloads(self, entries):
        self._machine_cache = {}
        """Put back exact payloads captured by ``payload_map`` (None = the row did not exist)."""
        with self.db:
            self._begin_write()
            for key, payload in entries:
                if payload is None:
                    previous = self.payload_map([key])[0]
                    if previous:
                        self._record_deletion(previous)
                    self.db.execute('DELETE FROM days WHERE store=? AND day=? AND machine=? AND rack=?', key)
                else:
                    if self.record_is_deleted(payload):
                        mark = next(m for m in self.record_deletions() if self._record_key(m) == self._record_key(payload))
                        payload = dict(payload, record_updated_at=max(datetime.now().astimezone(), _timestamp(mark['deleted_at']) + timedelta(milliseconds=1)).isoformat())
                    self.db.execute(
                        'INSERT INTO days VALUES(?,?,?,?,?) ON CONFLICT(store,day,machine,rack) '
                        'DO UPDATE SET payload=excluded.payload',
                        (*key, json.dumps(payload, ensure_ascii=False)))
            self._log_candidates({(k[0], k[2], k[1]) for k, _ in entries})
        self._machine_cache = {}

    def delete(self, store, day, machine, rack):
        self._machine_cache = {}
        """Delete one saved machine record and leave all other history intact."""
        if store not in STORE_NAMES:
            raise ValueError('対象店舗が不正です。')
        date.fromisoformat(day)
        with self.db:
            self._begin_write()
            raw = self.db.execute('SELECT payload FROM days WHERE store=? AND day=? AND machine=? AND rack=?',
                                  (store, day, machine, int(rack))).fetchone()
            found = self._deletion_source((store, day, machine, int(rack), raw[0])) if raw else None
            if found:
                self._record_deletion(found)
            cursor = self.db.execute(
                'DELETE FROM days WHERE store=? AND day=? AND machine=? AND rack=?',
                (store, day, machine, int(rack)),
            )
            self._log_candidates({(store, machine, day)})
        self._machine_cache = {}
        return cursor.rowcount == 1

    def delete_group(self, day, store=None, machine=None):
        """Delete every saved rack of one day (optionally one store / one machine).

        取り込みミスをまとめて消すための操作。日付は必須で、機種を指定するときは
        店舗も必須（別店舗の同名機種を巻き込まないため）。消した台数を返す。
        """
        self._machine_cache = {}
        date.fromisoformat(day)
        if store is not None and store not in STORE_NAMES:
            raise ValueError('対象店舗が不正です。')
        if machine is not None and store is None:
            raise ValueError('機種ごとに消すときは店舗も指定してください。')
        query, values = 'DELETE FROM days WHERE day=?', [day]
        if store is not None:
            query += ' AND store=?'
            values.append(store)
        if machine is not None:
            query += ' AND machine=?'
            values.append(machine)
        with self.db:
            self._begin_write()
            removed = self.db.execute(query.replace('DELETE FROM', 'SELECT store, day, machine, rack, payload FROM'), values).fetchall()
            self._merge_record_deletions([self._deletion_mark(self._deletion_source(row)) for row in removed], apply=False)
            groups = set(self.db.execute(query.replace('DELETE FROM', 'SELECT DISTINCT store, machine, day FROM'),
                                         values).fetchall())
            cursor = self.db.execute(query, values)
            self._log_candidates(groups)
        self._machine_cache = {}
        return cursor.rowcount

    @staticmethod
    def _record_key(row):
        return (row['store'], row['day'], normalize_machine_name(row['machine']), int(row['rack']))

    def record_deletions(self, location=None, day=None):
        marks = json.loads(self.state('record_deletions') or '[]')
        return [m for m in marks if (location is None or m['store'] == location)
                and (day is None or m['day'] == day)]

    def record_is_deleted(self, row):
        try:
            key = self._record_key(row)
        except (KeyError, TypeError, ValueError):
            return False
        mark = next((m for m in self.record_deletions() if self._record_key(m) == key), None)
        return bool(mark and not _record_after_deletion(row, mark))

    def _record_deletion(self, row):
        self._merge_record_deletions([self._deletion_mark(row)], apply=False)

    @staticmethod
    def _deletion_source(row):
        location, day, machine, rack, raw = row
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            payload = {}
        return dict(payload if isinstance(payload, dict) else {}, store=location, day=day, machine=machine, rack=rack)

    def _deletion_mark(self, row):
        now = datetime.now().astimezone()
        for value in (row.get('captured_at'), row.get('record_updated_at')):
            stamp = _record_operation_time(value)
            if stamp:
                now = max(now, stamp + timedelta(milliseconds=1))
        return dict(zip(('store', 'day', 'machine', 'rack'), self._record_key(row)), deleted_at=now.isoformat())

    def _merge_record_deletions(self, incoming, *, apply=True):
        self._begin_write()
        marks = {self._record_key(m): m for m in self.record_deletions()}
        for mark in incoming:
            key = self._record_key(mark)
            if key not in marks or _timestamp(mark['deleted_at']) > _timestamp(marks[key]['deleted_at']):
                marks[key] = mark
        self.db.execute('INSERT OR REPLACE INTO app_state VALUES(?,?)',
                        ('record_deletions', json.dumps(list(marks.values()), ensure_ascii=False)))
        for key, mark in marks.items() if apply else ():
            found = self.db.execute('SELECT payload FROM days WHERE store=? AND day=? AND machine=? AND rack=?', key).fetchone()
            if found and not _record_after_deletion(json.loads(found[0]), mark):
                self.db.execute('DELETE FROM days WHERE store=? AND day=? AND machine=? AND rack=?', key)
        self._machine_cache = {}

    def pending_rainbow_marks(self, location=None, day=None):
        """数値の未取り込み中に保存した印。壊れた控えは上書きせず止める。"""
        marks = json.loads(self.state('pending_rainbow_marks') or '[]')
        if not isinstance(marks, list) or any(not _valid_rainbow_mark(m) for m in marks):
            raise ValueError('未取り込みの🌈の保存内容を読めません。元のDBを残して修復してください。')
        return [m for m in marks if (location is None or m['store'] == location)
                and (day is None or m['day'] == day)]

    def _write_pending_rainbow_marks(self, marks):
        self.db.execute('INSERT OR REPLACE INTO app_state VALUES(?,?)',
                        ('pending_rainbow_marks', json.dumps(marks, ensure_ascii=False)))

    def _merge_pending_rainbow_marks(self, incoming):
        """バックアップ復元用。呼び側のトランザクション内で印を統合する。数値行は作らない。"""
        self._begin_write()
        pending = {(m['store'], m['day'], m['rack']): m for m in self.pending_rainbow_marks()}
        changed = 0
        for mark in incoming:
            if not _valid_rainbow_mark(mark):
                raise ValueError('未取り込みの🌈の形式が不正です。')
            key = (mark['store'], mark['day'], mark['rack'])
            previous = pending.get(key)
            if previous and _timestamp(previous['updated_at']) > _timestamp(mark['updated_at']):
                continue
            found = self.db.execute('SELECT machine, payload FROM days WHERE store=? AND day=? AND rack=?', key).fetchall()
            # 表示しない機種だけの行は無いものとして扱う（set_rainbow・_save_rows と同じ）。捨てずに控えに残す。
            found = [(machine, raw) for machine, raw in found if not is_hidden_machine(mark['store'], machine)]
            if not found:
                if previous != mark:
                    pending[key] = mark
                    changed += 1
                continue
            updated = False
            for machine, raw in found:
                payload = json.loads(raw)
                newest = _newer_rainbow(payload, dict(rainbow=mark['on'], rainbow_at=mark['updated_at']))
                if newest == _newer_rainbow(payload, {}):
                    continue
                payload.pop('rainbow', None)
                payload.pop('rainbow_at', None)
                payload.update(newest)
                self.db.execute('UPDATE days SET payload=? WHERE store=? AND day=? AND rack=? AND machine=?',
                                (json.dumps(payload, ensure_ascii=False), *key, machine))
                updated = True
            changed += int(updated)
            pending.pop(key, None)
        self._write_pending_rainbow_marks(list(pending.values()))
        return changed

    def set_rainbow(self, store, day, rack, on, at=None, allow_missing=False):
        """確定が出た台の印🌈を付ける（on=True）・外す（False）。採点には使わない（RAINBOW.md）。

        店舗・日・台番号で決める（その日のその台は1機種）。通常は保存済みの台だけ。
        本日のバラエティ画面は allow_missing=True で印だけを別保存し、数値取得時に統合する。
        記録の payload に ``rainbow: true`` を持つので、表を取り込み直しても・バックアップを読み込んでも残る。
        付け外しした時刻を ``rainbow_at`` に残す（外しても残す）。iPhoneの閲覧ページで付け外しした分
        （pull_shared_rainbow）と、時刻の新しい方を残すため。at はその時刻（省略は今）。"""
        if store not in STORE_NAMES:
            raise ValueError('対象店舗が不正です。')
        date.fromisoformat(day)
        if not isinstance(on, bool):
            raise ValueError('🌈の指定が不正です。')
        with self.db:
            # 行・控えを読む前にロックを取る（取り込みブラウザが同時に保存しても、読んだ内容のまま書く）。
            self._begin_write()
            found = self.db.execute('SELECT machine, payload FROM days WHERE store=? AND day=? AND rack=?',
                                    (store, day, int(rack))).fetchall()
            found = [(machine, payload) for machine, payload in found if not is_hidden_machine(store, machine)]
            if not found and not allow_missing:
                raise ValueError(f'{rack}番台は{day}の記録がありません。先に表を取り込んでください。')
            if at is None:
                now = datetime.now().astimezone()
                previous = [m['updated_at'] for m in self.pending_rainbow_marks(store, day) if m['rack'] == int(rack)]
                previous += [json.loads(raw).get('rainbow_at') for _machine, raw in found]
                stamps = []
                for value in previous:
                    try:
                        if value:
                            stamps.append(_timestamp(value))
                    except (TypeError, ValueError):
                        pass
                latest = max(stamps, default=None)
                if latest and now <= latest:
                    now = latest + timedelta(milliseconds=1)
                at = now.isoformat()
            mark = dict(store=store, day=day, rack=int(rack), on=on, updated_at=at)
            if not _valid_rainbow_mark(mark):
                raise ValueError('🌈の指定が不正です。')
            if not found:
                self._merge_pending_rainbow_marks([mark])
                return 0
            pending = self.pending_rainbow_marks()
            if any((m['store'], m['day'], m['rack']) == (store, day, int(rack)) for m in pending):
                self._write_pending_rainbow_marks([m for m in pending
                    if (m['store'], m['day'], m['rack']) != (store, day, int(rack))])
            for machine, raw in found:
                payload = json.loads(raw)
                if on:
                    payload['rainbow'] = True
                else:
                    payload.pop('rainbow', None)
                payload['rainbow_at'] = at
                # 観測の記録（_log_observation）には書かない：数値ではない印で、書くたびに古い行の掃除が全件を
                # 見るため、押すたびに遅くなっていた（2026-10-12 利用者「一個押すたびに…数秒かかってしまう」）。
                self.db.execute('UPDATE days SET payload=? WHERE store=? AND day=? AND machine=? AND rack=?',
                                (json.dumps(payload, ensure_ascii=False), store, day, machine, int(rack)))
        self._machine_cache = {}
        return len(found)

    def rainbow_racks(self, store, day):
        """その日・その店で🌈の付いた台番号（小さい順）。"""
        rows = self.db.execute(
            "SELECT machine, rack FROM days WHERE store=? AND day=? AND json_valid(payload)"
            " AND json_extract(payload, '$.rainbow') = 1", (store, day)).fetchall()
        return sorted({int(rack) for machine, rack in rows if not is_hidden_machine(store, machine)}
                      | {m['rack'] for m in self.pending_rainbow_marks(store, day) if m['on']})

    def rainbow_counts(self, store, first, last):
        """台番号ごとの、first〜last（両端を含む）に🌈が付いた日数（{台番号: 日数}）。バラエティのタブで使う。"""
        rows = self.db.execute(
            "SELECT rack, machine, day FROM days WHERE store=? AND day>=? AND day<=? AND json_valid(payload)"
            " AND json_extract(payload, '$.rainbow') = 1", (store, first, last)).fetchall()
        days = {}
        for rack, machine, day in rows:
            if not is_hidden_machine(store, machine):
                days.setdefault(int(rack), set()).add(day)
        for mark in self.pending_rainbow_marks(store):
            if mark['on'] and first <= mark['day'] <= last:
                days.setdefault(mark['rack'], set()).add(mark['day'])
        return {rack: len(found) for rack, found in days.items()}

    def last_rainbow_days(self, store, before):
        """台番号ごとの、before より前で最後に🌈が付いた日（{台番号: 日}）。最終🌈の欄に使う（RAINBOW.md）。
        台番号で見る（機種が入れ替わっても同じ台番号なら続けて数える）。"""
        rows = self.db.execute(
            "SELECT rack, machine, day FROM days WHERE store=? AND day<? AND json_valid(payload)"
            " AND json_extract(payload, '$.rainbow') = 1", (store, before)).fetchall()
        last = {}
        for rack, machine, day in rows:
            if not is_hidden_machine(store, machine) and day > last.get(int(rack), ''):
                last[int(rack)] = day
        for mark in self.pending_rainbow_marks(store):
            if mark['on'] and last.get(mark['rack'], '') < mark['day'] < before:
                last[mark['rack']] = mark['day']
        return last

    def set_confirmed_setting(self, store, day, machine, rack, value):
        self._machine_cache = {}
        """Store a manually confirmed setting annotation without rescoring.

        ``value`` is one of ``4以上``, ``5以上``, ``6`` or ``None`` to clear
        it. The annotation deliberately stays outside the score calculation.
        """
        if store not in STORE_NAMES:
            raise ValueError('対象店舗が不正です。')
        date.fromisoformat(day)
        if value not in (*CONFIRMED_SETTING_OPTIONS, None):
            raise ValueError('設定情報は「4以上」「5以上」「6」から選んでください。')
        key = (store, day, machine, int(rack))
        found = self.db.execute(
            'SELECT payload FROM days WHERE store=? AND day=? AND machine=? AND rack=?', key).fetchone()
        if not found:
            raise ValueError(f'{rack}番台は保存されていません。')
        payload = json.loads(found[0])
        if value is None:
            payload.pop('confirmed_setting', None)
        else:
            payload['confirmed_setting'] = value
        with self.db:
            self.db.execute(
                'UPDATE days SET payload=? WHERE store=? AND day=? AND machine=? AND rack=?',
                (json.dumps(payload, ensure_ascii=False), *key),
            )
            self._log_observation(payload)

    def rows(self, day=None, machine=None, store=None):
        query, values = 'SELECT payload FROM days WHERE 1=1', []
        if store:
            query += ' AND store=?'
            values.append(store)
        if day:
            query += ' AND day=?'
            values.append(day)
        if machine:
            query += ' AND machine=?'
            values.append(machine)
        # 読めない行（壊れたJSON）は飛ばす。1件のために画面も採点も止めない
        # （行は消さずに残し、書き出しには unreadable_record として入る）。
        result = []
        for (row_store, row_machine, payload) in self.db.execute(
                query.replace('SELECT payload', 'SELECT store, machine, payload') + ' ORDER BY day,store,rack', values):
            if is_hidden_machine(row_store, row_machine):
                continue
            try:
                result.append(json.loads(payload))
            except ValueError:
                continue
        return result

    def raw_payloads(self, day=None, store=None):
        """The stored JSON text of each row, in the same order as ``rows()``.

        A backup copies rows out verbatim, so decoding every payload (80% of
        which is a base64 graph image) only to re-encode it is pure overhead.
        """
        query, values = 'SELECT payload FROM days WHERE 1=1', []
        if store:
            query += ' AND store=?'
            values.append(store)
        if day:
            query += ' AND day=?'
            values.append(day)
        return [payload for (row_store, row_machine, payload) in self.db.execute(
            query.replace('SELECT payload', 'SELECT store, machine, payload') + ' ORDER BY day,store,rack', values)
            if not is_hidden_machine(row_store, row_machine)]

    def days_for(self, store=None):
        """Distinct saved days, most recent first (for a date picker).

        Every store's days if ``store`` is omitted (e.g. for a backup export
        that spans both shops).
        """
        if store:
            query, params = 'SELECT DISTINCT day FROM days WHERE store=? ORDER BY day DESC', (store,)
        else:
            query, params = 'SELECT DISTINCT day FROM days ORDER BY day DESC', ()
        return [row[0] for row in self.db.execute(query, params)]

    def machines_for(self, store, day):
        """Distinct saved machine names for one store and day (for a machine picker)."""
        query = 'SELECT DISTINCT machine FROM days WHERE store=? AND day=? ORDER BY machine'
        return [row[0] for row in self.db.execute(query, (store, day)) if not is_hidden_machine(store, row[0])]

    def _machine_rows(self, machine, store):
        """All saved rows of one machine at one store, decoded once and reused.

        Scoring asks for the same pool once per rack (history/summary pages
        do this for hundreds of racks), and every ask used to re-read and
        re-decode every payload, including the large graph images. The cache
        is dropped by every write method, so it never serves stale rows.
        Callers only read these rows; they must not modify them.
        """
        cache = self.__dict__.setdefault('_machine_cache', {})
        key = (machine, store)
        if key not in cache:
            cache[key] = self.rows(machine=machine, store=store)
        return cache[key]

    def references(self, row):
        first = (date.fromisoformat(row['day']) - timedelta(days=30)).isoformat()
        return [r for r in self._machine_rows(row['machine'], row['store'])
                if first <= r['day'] < row['day'] and r.get('games', 0) > 0]

    def provisional_references(self, row):
        """Same-machine pool for an explicitly provisional comparison.

        Unlike the formal reference pool, this includes the scored date. The
        resulting rank is shrunk toward the midpoint until 20 rows exist.
        """
        first = (date.fromisoformat(row['day']) - timedelta(days=30)).isoformat()
        return [r for r in self._machine_rows(row['machine'], row['store'])
                if first <= r['day'] <= row['day'] and r.get('games', 0) > 0]

    def close(self):
        self.db.close()


BACKUP_FORMAT = 'database-backup'
BACKUP_VERSION = 1
BACKUP_NUMERIC_FIELDS = ('games', 'bb', 'rb', 'max_hold')


def candidate_snapshot(store, location, day, machine, now=None):
    """The next-day candidates of one store/day/machine now, in Android's format.

    ``machine == VARIETY_GROUP_NAME`` is that store/day's variety group (every
    machine with 1-3 racks); its candidates are identified by rack number,
    which is unique within one store and day.
    """
    result = (variety_next_day_candidates(store, day, location) if machine == VARIETY_GROUP_NAME
              else provisional_next_day_candidates(store, day, machine, location))
    return dict(store=location, day=day, machine=machine,
                taken_at=(now or datetime.now().astimezone()).isoformat(),
                method=candidate_method_version(location, machine, day),
                total=result['total'], eligible=result['eligible'],
                candidates=[dict(rack=int(c['row']['rack']), index=c['index'], days=c['days'])
                            for c in result['candidates']])


def candidate_signature(snapshot):
    """Content without the time: an unchanged list is not recorded again.

    The method version is part of it, so a formula change is recorded anew.
    """
    return (snapshot.get('method'), snapshot.get('total'), snapshot.get('eligible'),
            tuple((c.get('rack'), float(c.get('index')), c.get('days'))
                  for c in snapshot.get('candidates', [])))


_RECORDS_START = re.compile(r'"records"\s*:\s*\[$')


def _decode_backup_json(text):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'バックアップ内で {key} が重複しています。')
            result[key] = value
        return result
    return json.loads(text, object_pairs_hook=unique)


def _validate_backup_envelope(payload, allow_viewer=False, elided_candidates=False):
    if not isinstance(payload, dict) or payload.get('format') != BACKUP_FORMAT or not isinstance(payload.get('records'), list):
        raise ValueError('バックアップファイルの形式が不正です。')
    if type(payload.get('version')) is not int or payload['version'] != BACKUP_VERSION:
        raise ValueError('対応していないバックアップのバージョンです。')
    if payload.get('source') == 'pc-viewer' and not allow_viewer:
        raise ValueError('これは閲覧ページ用の軽いファイル（画像なし）です。バックアップとして取り込まないでください。')
    for key in ('candidate_snapshots', 'date_events', 'rainbow_marks', 'record_deletions'):
        if key in payload and not isinstance(payload[key], list):
            raise ValueError(f'{key} の形式が不正です。')
    if payload.get('recovery_required', 0) != 0 or 'unreadable_date_events' in payload:
        raise ValueError('読めないデータを含む救出用ファイルです。元のファイルを残して、データの修復を依頼してください。')
    if any(not _valid_date_event(event) for event in payload.get('date_events', [])):
        raise ValueError('イベント情報に読めない項目があります。')
    if any(not _valid_rainbow_mark(mark) for mark in payload.get('rainbow_marks', [])):
        raise ValueError('未取り込みの🌈に読めない項目があります。')
    if any(not _valid_record_deletion(m) for m in payload.get('record_deletions', [])):
        raise ValueError('削除記録に読めない項目があります。')
    if 'event_history_edits' in payload:
        from event_history_data import validate_envelope
        validate_envelope(payload['event_history_edits'])
    if not elided_candidates:
        for snapshot in payload.get('candidate_snapshots', []):
            if not (isinstance(snapshot, dict) and snapshot.get('store') in STORE_NAMES
                    and isinstance(snapshot.get('day'), str) and isinstance(snapshot.get('machine'), str)
                    and snapshot['machine'].strip() and isinstance(snapshot.get('taken_at'), str)
                    and snapshot['taken_at'] and isinstance(snapshot.get('candidates'), list)):
                raise ValueError('翌日候補の記録に読めない項目があります。')


def _read_backup_document(path, allow_viewer=False):
    """Read record values separately, validating the complete JSON envelope before saving."""
    path = Path(path)
    records, snapshots, structure = [], [], []
    streamed_candidates = False
    with path.open(encoding='utf-8-sig') as source:
        first = next((line.strip() for line in source if line.strip()), '')
        match = _RECORDS_START.search(first)
        if first.startswith('{') and match:
            header = _decode_backup_json(first[:match.start()].rstrip().rstrip(',') + '}')
            _validate_backup_envelope(dict(header, records=[]), allow_viewer)
            structure.append(first)
            section = 'records'
            for line in source:
                text = line.strip()
                if not text:
                    continue
                if section == 'done' or text.startswith(']'):
                    structure.append(text)
                    section = ('candidates' if section == 'records' and '"candidate_snapshots"' in text
                               and text.endswith('[') else 'done')
                    streamed_candidates |= section == 'candidates'
                    continue
                item = _decode_backup_json(text[:-1] if text.endswith(',') else text)
                (records if section == 'records' else snapshots).append(item)
                structure.append('null,' if text.endswith(',') else 'null')
            payload = _decode_backup_json('\n'.join(structure))
            _validate_backup_envelope(payload, allow_viewer, elided_candidates=streamed_candidates)
            payload['records'] = records
            if streamed_candidates:
                payload['candidate_snapshots'] = snapshots
            _validate_backup_envelope(payload, allow_viewer)
            return payload
    payload = _decode_backup_json(path.read_text(encoding='utf-8-sig'))
    _validate_backup_envelope(payload, allow_viewer)
    return payload


def read_backup_file(path, allow_viewer=False):
    """(records, candidate_snapshots), with the same checks for every supported layout."""
    payload = _read_backup_document(path, allow_viewer)
    return payload['records'], payload.get('candidate_snapshots', [])


def read_backup_events(path):
    """Read event labels from any position in a validated portable backup."""
    return _read_backup_document(path).get('date_events', [])


def export_viewer(store, path, days=VIEWER_DAYS):
    """Write the light file the iPhone viewer reads: the latest ``days`` days
    (counted from the newest saved day), without graph images. The graph
    curve (the site's SVG line, about a sixth of the image's size) is kept so
    the viewer can draw the real graph (the user's choice, 2026-09-28).

    Same one-record-per-line layout as a backup, so the viewer and
    ``read_backup_file`` read it the same way. Returns the number of racks.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    latest = store.db.execute('SELECT MAX(day) FROM days').fetchone()[0]
    cutoff = ((date.fromisoformat(latest) - timedelta(days=days - 1)).isoformat()
              if latest else None)
    # 先の日に入力したイベントも渡す（イベントカレンダー）。消した印も含める。
    date_events = [event for event in store.date_events(include_removed=True)
                   if cutoff and event['day'] >= cutoff]
    # 保存したアナスロのHTMLからの日ごとの「何台中何台プラス」（台の数値は無い。共有ページのカレンダーが
    # 台データの無い日にだけ使う。2026-10-18、html_day_summary.py）。DBの隣のファイルが無ければ載せない。
    import html_day_summary
    summaries = html_day_summary.load_days(Path(store.path).parent / html_day_summary.SUMMARY_NAME)
    header = json.dumps(dict(format=BACKUP_FORMAT, version=BACKUP_VERSION,
                             exported_at=datetime.now().astimezone().isoformat(),
                             source='pc-viewer', days=days, date_events=date_events,
                             record_deletions=store.record_deletions(),
                             **({'day_summaries': summaries} if summaries else {})), ensure_ascii=False)[:-1]
    # 未取り込み日の🌈（pending_rainbow_marks）は入れない。閲覧ページは rainbow_marks を端末の印として表示・送信し、
    # 旧形式の同期GSは見出しをそのまま渡すため、取り込み前にWebへ出てしまう。Webへは数値の取り込み後（RAINBOW.md）。
    count = 0
    with atomic_writer(path) as out:
        out.write(f'{header}, "records": [')
        if latest:
            cutoff = (date.fromisoformat(latest) - timedelta(days=days - 1)).isoformat()
            for (row_store, row_machine, payload) in store.db.execute(
                    'SELECT store, machine, payload FROM days WHERE day >= ? ORDER BY day,store,rack', (cutoff,)):
                if is_hidden_machine(row_store, row_machine):
                    continue  # 対象外の機種（稼働停止の台など）は閲覧用にも出さない
                # 閲覧ページが使う項目だけ（台ページのURL・取り込み元などは省く）。
                try:
                    row = {k: v for k, v in json.loads(payload).items() if k in VIEWER_KEYS}
                except (ValueError, AttributeError):
                    continue  # 読めない行は閲覧用には出さない
                graph = row.get('graph_measurement')
                if isinstance(graph, dict):
                    graph.pop('preview_image', None)
                out.write(('\n' if count == 0 else ',\n') + json.dumps(row, ensure_ascii=False))
                count += 1
        out.write('\n]}')
    return count


def snapshot_store(path):
    """本体DBを1つの時点で写し、その写しを開いた Store を渡す（with で使う）。

    export_backup はイベント・削除印を読んでから台を読む。その間に別の接続が台を消すと、
    台も削除印も入っていないバックアップになっていた（2026-11-01、Codexの洗い出し4）。
    写しはSQLiteのバックアップ機能で一度に取るので、書き込み側を待たせるのは写す間だけ。
    """
    import tempfile
    from contextlib import closing, contextmanager

    @contextmanager
    def opened():
        with tempfile.TemporaryDirectory(prefix='database-snapshot-') as directory:
            copy = Path(directory) / 'snapshot.sqlite3'
            with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)) as source, \
                    closing(sqlite3.connect(copy)) as target:
                source.backup(target)
            store = Store(copy, recording=False)
            try:
                yield store
            finally:
                store.close()
    return opened()


def backup_from_snapshot(db_path, data_dir, *, notices=None):
    """共有編集は本体へ取り込み、バックアップは同じ時点の写しから書く（自動出力 output_worker と同じ順番）。"""
    from contextlib import closing
    try:
        with closing(Store(db_path)) as source:
            sync_shared_history(source, data_dir, notices)
    except (OSError, sqlite3.Error) as error:
        import error_log
        error_log.record(data_dir, 'backup.shared_import', error)
        if notices is not None:
            notices.append(f'共有のイベント履歴を取り込めませんでした（元の記録は保持）：{error}')
    with snapshot_store(db_path) as store:
        return auto_backup(store, data_dir, notices=notices, import_shared=False)


def export_backup(store, path, location=None, day=None, since=None):
    """Write saved records as a portable JSON file (share via Drive, USB, etc.).

    The format is shared with the Android app's own backup export, so either
    side's file can be read back by the other: both use the same field names
    (store/day/machine/rack/games/bb/rb/max_hold/graph_measurement/...).
    ``day`` narrows the export to one date (across every machine/store), for
    when a full-database export would be too many machines to review at once.
    ``since`` keeps only the records (and events / candidate records) dated on or after
    that day: the small "recent" backup Android reads day to day (RECENT_BACKUP_NAME).
    Deletion marks and pending 🌈 are always written in full (they are small, and an
    older record deleted on the PC must disappear on Android too).
    """
    events = [e for e in store.date_events(location=location, day=day, include_removed=True)
              if since is None or e['day'] >= since]
    header = json.dumps(dict(format=BACKUP_FORMAT, version=BACKUP_VERSION,
                             exported_at=datetime.now().astimezone().isoformat(),
                             source='pc', date_events=events, **({'since': since} if since else {}),
                             record_deletions=store.record_deletions(location, day),
                             rainbow_marks=store.pending_rainbow_marks(location, day),
                             event_history_edits=store.history_edits_raw()), ensure_ascii=False)[:-1]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    query, values = 'SELECT payload FROM days WHERE 1=1', []
    if location:
        query += ' AND store=?'
        values.append(location)
    if day:
        query += ' AND day=?'
        values.append(day)
    if since:
        query += ' AND day>=?'
        values.append(since)
    count = 0
    # One record per line, written as read: the whole database is never held
    # as one string (this runs after every save), and the file can be read
    # back line by line (``iter_backup_file``). Payloads are copied verbatim.
    # 読めない行（壊れたJSON）をそのまま書くとファイル全体が読めなくなるので、
    # その行だけ unreadable_record に包む（Android版と同じ。取り込みでは対象外）。
    with atomic_writer(path) as out:
        out.write(f'{header}, "records": [')
        for (row_store, row_machine, payload) in store.db.execute(
                query.replace('SELECT payload', 'SELECT store, machine, payload') + ' ORDER BY day,store,rack', values):
            if is_hidden_machine(row_store, row_machine):
                continue
            try:
                json.loads(payload)
                line = payload
            except ValueError:
                line = json.dumps({'unreadable_record': payload}, ensure_ascii=False)
            out.write(('\n' if count == 0 else ',\n') + line)
            count += 1
        out.write('\n]')
        snapshots = store.candidate_snapshots(day=day, location=location)
        if since:
            snapshots = [x for x in snapshots if json.loads(x).get('day', '') >= since]
        if snapshots:
            out.write(', "candidate_snapshots": [\n' + ',\n'.join(snapshots) + '\n]')
        out.write('}')
    return count


RAINBOW_MARK = '🌈'


def _newer_rainbow(local, incoming):
    """保存済みの台 [local] と、保存する台 [incoming] の🌈のうち、付け外しした時刻（rainbow_at）の新しい方の
    {'rainbow': True?, 'rainbow_at': ...}（どちらにも無ければ空）。時刻の無い🌈（古い記録）は、時刻のある方に負ける。
    同じ時刻なら保存する方。"""
    def state(row):
        return {k: row[k] for k in ('rainbow', 'rainbow_at') if row.get(k) is not None}

    def at(row):
        try:
            return _timestamp(row['rainbow_at']) if row.get('rainbow_at') else None
        except (TypeError, ValueError):
            return None
    mine, theirs = at(local), at(incoming)
    if theirs is None and mine is None:
        return state(incoming) or state(local)
    if theirs is None:
        return state(local)
    if mine is None or theirs >= mine:
        return state(incoming)
    return state(local)


def rack_mark(row):
    """台番号の横に付ける印（確定が出た台は「 🌈」）。PCの結果・まとめ・カレンダーで使う。"""
    return f' {RAINBOW_MARK}' if row.get('rainbow') is True else ''


def _valid_backup_record(record):
    try:
        return (isinstance(record, dict) and record.get('kind_code') == 21
                and record.get('store') in STORE_NAMES
                and isinstance(record.get('machine'), str) and record['machine'].strip()
                and _valid_backup_numbers(record)
                and record.get('confirmed_setting') in (*CONFIRMED_SETTING_OPTIONS, None)
                and date.fromisoformat(record.get('day', '')).isoformat() == record['day'])
    except (ValueError, TypeError):
        return False


def _valid_backup_numbers(record):
    def integer(value):
        return (type(value) is int and value >= 0
                or type(value) is float and math.isfinite(value) and value >= 0 and value.is_integer())
    return (integer(record.get('rack')) and record['rack'] > 0
            and all(integer(record.get(key)) for key in ('games', 'bb', 'rb'))
            and all(record.get(key) is None or integer(record[key]) for key in ('max_hold', 'previous_start')))


def plan_backup_import(store, records):
    """Classify incoming backup records against what is already saved.

    A record whose games/BB/RB/max_hold differ from an existing same
    store/day/machine/rack row is never merged automatically -- it goes to
    'conflicts' so the user decides, matching the rule that a conflicting
    duplicate is never silently overwritten. A record that only adds a graph
    the local copy lacks (numbers otherwise equal) is safe to merge on its
    own ('graph_only'). Anything with an unrecognised shape or an
    out-of-scope store/kind_code lands in 'skipped'.
    """
    existing = {(r['store'], r['day'], r['machine'], int(r['rack'])): r for r in store.rows()}
    new, graph_only, unchanged, conflicts, skipped = [], [], [], [], []
    link_only, setting_only, jo_only = [], [], []
    seen = {}
    for record in records:
        if not _valid_backup_record(record):
            skipped.append(record)
            continue
        # Compare with one spelling, or a '+'-spelled copy is added as a new rack.
        record = dict(record, machine=normalize_machine_name(record['machine']))
        if is_hidden_machine(record['store'], record['machine']):
            continue
        key = (record['store'], record['day'], record['machine'], int(record['rack']))
        if key in seen:
            if seen[key] != record:
                raise ValueError(f'{record["rack"]}番台の異なる記録がバックアップ内で重複しています。保存せず中止しました。')
            continue
        seen[key] = record
        local = existing.get(key)
        if local is None:
            new.append(record)
            continue
        differs = any(record.get(f) is not None and local.get(f) is not None
                      and record[f] != local[f] for f in BACKUP_NUMERIC_FIELDS)
        differs = differs or (record.get('confirmed_setting') is not None
                              and local.get('confirmed_setting') is not None
                              and record['confirmed_setting'] != local['confirmed_setting'])
        if differs:
            conflicts.append((local, record))
            continue
        incoming_has_graph = bool(record.get('graph') or record.get('graph_measurement'))
        local_has_graph = bool(local.get('graph') or local.get('graph_measurement'))
        if incoming_has_graph and not local_has_graph:
            graph_only.append(record)
        elif record.get('detail_url') and not local.get('detail_url'):
            # Same numbers, but the backup knows the rack's own site link that
            # the local row lacks (e.g. captured on the phone) -- safe to fill in.
            link_only.append(record)
        elif record.get('confirmed_setting') and not local.get('confirmed_setting'):
            setting_only.append(record)
        elif _newer_rainbow(local, record) != _newer_rainbow(local, {}):
            # 数値は同じで、別の端末などで付け外しした🌈だけが新しい（RAINBOW.md。付け外しした時刻で比べる）。
            setting_only.append(record)
        elif juggler_online_newer(record, local):
            # 数値は同じで、Androidで足したジャグラーオンラインの差枚など（jo_…）だけが新しい（JUGGLER_ONLINE.md）。
            jo_only.append(record)
        else:
            unchanged.append(record)
    return dict(new=new, graph_only=graph_only, unchanged=unchanged,
               conflicts=conflicts, skipped=skipped, link_only=link_only,
               setting_only=setting_only, jo_only=jo_only)


def juggler_online_newer(record, local):
    """取り込む台のジャグラーオンラインの値（jo_net など）が、手元より新しいか（取り込んだ時刻で比べる）。"""
    if not isinstance(record.get('jo_net'), int):
        return False
    if not isinstance(local.get('jo_net'), int):
        return True
    theirs, ours = record.get('jo_captured_at'), local.get('jo_captured_at')
    try:
        return bool(theirs) and (not ours or _timestamp(theirs) > _timestamp(ours))
    except ValueError:
        return False


# 推定差枚を出さない店・日（ジャグラーオンラインの差枚は出す）。長町南の10/7は、サイトのグラフが全台「始点と終点を
# 結んだ直線」で途中の推移が無く、推定が正しく決められないため（2026-10-12 利用者「長町南10/7だけ消す」）。
# Android・閲覧ページ（lib/meruhen_net.dart の meruhenNetHiddenDays）・共有ページ（share_viewer/net.mjs）と同じ。
MERUHEN_NET_HIDDEN_DAYS = {'nagamachiminami': ('2026-10-07',)}


def meruhen_net_hidden(store, day):
    """その店・日の推定差枚を出さないか（[MERUHEN_NET_HIDDEN_DAYS]）。"""
    return day in MERUHEN_NET_HIDDEN_DAYS.get(store, ())


def rack_net(row):
    """画面に出す差枚：ジャグラーオンラインの差枚（jo_net、お試し JUGGLER_ONLINE.md）があればそれ、
    無ければグラフと最大持玉からの推定差枚（[MERUHEN_NET_HIDDEN_DAYS] の店・日は出さない）。
    戻り値は（差枚、要確認、ジャグラーオンラインか）。"""
    if isinstance(row.get('jo_net'), int) and not isinstance(row.get('jo_net'), bool):
        return row['jo_net'], False, True
    if meruhen_net_hidden(row.get('store'), row.get('day')):
        return None, False, False
    net, needs_check = meruhen_net_estimate_detail(row.get('graph_measurement'), row.get('max_hold'), row.get('games'))
    return net, needs_check, False


def rack_won(row):
    """その台がプラスで終わったか（True/False）、分からなければ None（勝率に数えない）。

    差枚があればその符号。無ければグラフの終点がゼロ線より上か（採点の終点と同じく1ピクセル以内は
    プラスにしない）。アナスロ補完はグラフの形だけが分かり差枚が出ないので、こちらで決まる
    （2026-10-17、ジャグラーオンラインの差枚と4,086台すべてで符号が一致）。大当たり0回でグラフを
    取らない台はマイナス。未稼働の台と [MERUHEN_NET_HIDDEN_DAYS] の店・日は None。
    Android `SlotRecord.won`・共有ページ `rackWon` と同じ。"""
    if not row.get('games'):
        return None
    net = rack_net(row)[0]
    if net is not None:
        return net > 0
    if meruhen_net_hidden(row.get('store'), row.get('day')):
        return None
    measurement = row.get('graph_measurement')
    if isinstance(measurement, dict):
        try:
            end = float(measurement['baseline_y']) - float(measurement['end_y'])
        except (KeyError, TypeError, ValueError):
            return None
        return end > 1 if math.isfinite(end) else None
    return False if no_hits(row) else None


def show_win_rate(captured, judged):
    """カレンダーの1日に総差枚の代わりに勝率を出すか：差枚の分かる台が、勝ち負けの分かる台の
    半分に満たない日（2026-10-17 利用者「差枚を出せないところについては勝率を書いてほしい」）。
    一部の台だけの総差枚は店全体より小さく見えるため。"""
    return judged > 0 and captured * 2 < judged


def win_rate_text(won, judged):
    """「勝率48%」。整数で四捨五入（0.5は切り上げ）し、Android `winRateLabel`・共有ページ `winRateText` とそろえる。"""
    return f'勝率{(200 * won + judged) // (2 * judged)}%'


SETTINGS_NAME = 'settings.json'
# Fixed file name so the shared folder always holds exactly one auto-written
# copy (overwritten each time) instead of piling up timestamped files.
AUTO_BACKUP_NAME = 'database-backup-auto.json'
# Androidがふだん読み込む小さいバックアップ：直近 RECENT_BACKUP_DAYS 日分（最新の記録日から数える）。
# 全期間の database-backup-auto.json は127MBほどあり、読み込みに約2分かかる（2026-10-18 利用者
# 「アプリ版も差分処理っていけないのだろうか」→ 案1「PCが直近の分だけのバックアップも書き出す」）。
RECENT_BACKUP_NAME = 'database-backup-recent.json'
RECENT_BACKUP_DAYS = 7


def _read_settings(data_dir):
    """(設定, 状態)。状態は 'ok'（読めた）・'missing'（まだ無い）・'locked'（あるが開けない）・'broken'（中身が壊れている）。"""
    path = Path(data_dir) / SETTINGS_NAME
    try:
        text = path.read_text(encoding='utf-8')
    except FileNotFoundError:
        return {}, 'missing'
    except UnicodeDecodeError:
        return {}, 'broken'
    except OSError:
        return {}, 'locked'
    try:
        loaded = json.loads(text)
    except ValueError:
        return {}, 'broken'
    return (loaded, 'ok') if isinstance(loaded, dict) else ({}, 'broken')


def load_settings(data_dir):
    return _read_settings(data_dir)[0]


def save_settings(data_dir, **updates):
    """設定へ updates を足して保存する。

    2026-11-01：読めない設定を空として扱い、次の保存で原文（同期先など）を上書きしていた。
    中身が壊れていたら、上書きの前に原文を `settings.json.broken-日時` として残し、errors.log に書く。
    ファイルはあるのに開けない（同期ソフト等の一時的なロック）ときは、正しい原文を消さないよう保存しない。
    """
    import error_log
    settings, state = _read_settings(data_dir)
    path = Path(data_dir) / SETTINGS_NAME
    if state == 'locked':
        error_log.note(data_dir, 'settings.locked', f'{SETTINGS_NAME} を開けないため、設定の保存を見送りました（原文は変更していません）')
        settings.update(updates)
        return settings
    if state == 'broken':
        keep = path.with_name(f'{SETTINGS_NAME}.broken-{datetime.now().strftime("%Y%m%d-%H%M%S")}')
        try:
            if not keep.exists():
                shutil.copy2(path, keep)
            error_log.note(data_dir, 'settings.broken',
                           f'{SETTINGS_NAME} が読めない形だったため、原文を {keep.name} に残してから保存し直しました')
        except OSError as error:
            # 原文を残せないなら上書きしない（同期先などを失わない）。
            error_log.record(data_dir, 'settings.broken', error, detail='原文を残せないため保存を見送りました')
            settings.update(updates)
            return settings
    settings.update(updates)
    path.parent.mkdir(parents=True, exist_ok=True)
    with atomic_writer(path) as out:
        json.dump(settings, out, ensure_ascii=False, indent=2)
    return settings


# 同期フォルダの目印（2026-11-03 利用者「何度目かわからないけどまたグーグルドライブのドライブレター変わってるのに
# 気づかず取り込み終えてしまった」「別のアカウントで文字つかってるときはこっちはEになるね」→「自動で探して知らせる」）。
# Windowsのもう一方のアカウントのGoogleドライブが G: を使うと、こちらは E: などになり、設定の G:/マイドライブ/database共有
# が見つからず書き出しが止まっていた（10/26・11/3）。同期フォルダに番号入りの目印を置き、設定の場所に無いときは
# ほかのドライブ文字の同じ場所を探して、番号が一致したときだけそちらへ切り替える（別アカウントのドライブには書かない）。
SYNC_MARK_NAME = 'database-sync-folder.json'


def _sync_mark(folder):
    try:
        value = json.loads((Path(folder) / SYNC_MARK_NAME).read_text(encoding='utf-8'))
        return value.get('id') if isinstance(value, dict) and isinstance(value.get('id'), str) else None
    except (OSError, ValueError):
        return None


def write_sync_mark(data_dir, folder):
    """[folder] を同期フォルダとして目印を付け、設定に番号を覚える（フォルダに目印があればその番号を使う）。
    「同期フォルダを指定」で選び直したときにも呼ぶ。書けなくても（ドライブの一時的な不調など）止めない。"""
    import uuid
    mark = _sync_mark(folder) or load_settings(data_dir).get('sync_mark') or uuid.uuid4().hex
    try:
        if _sync_mark(folder) != mark:
            with atomic_writer(Path(folder) / SYNC_MARK_NAME) as out:
                json.dump({'id': mark, 'note': 'database（PC版）の同期フォルダの目印。消さないでください。'}, out,
                          ensure_ascii=False)
    except OSError:
        pass
    if load_settings(data_dir).get('sync_mark') != mark:
        save_settings(data_dir, sync_mark=mark)
    return mark


def _other_drive_folders(folder):
    """[folder] と同じ場所の、ほかのドライブ文字のフォルダ（Windowsのドライブ文字つきのパスだけ）。"""
    from pathlib import PureWindowsPath
    path = PureWindowsPath(str(folder))   # 試験・CI（Linux）でも同じく読む
    if len(path.drive) != 2 or path.drive[1] != ':':
        return []
    rest = path.relative_to(path.anchor).as_posix()
    return [Path(f'{letter}:/{rest}') for letter in 'CDEFGHIJKLMNOPQRSTUVWXYZ' if letter != path.drive[0].upper()]


def resolve_sync_dir(data_dir):
    """書き出し・読み込みに使う同期フォルダ（文字列）。未設定・見つからないときは None。

    設定の場所にあり、目印が無いか番号が一致すればそこ（目印が無ければ付ける）。別の番号の目印があるフォルダ
    （もう一方のアカウントのドライブなど）は使わない。設定の場所に使えるフォルダが無ければ、ほかのドライブ文字の
    同じ場所で番号が一致するものを探し、見つかれば設定をそちらへ書き換えて、移ったことを `sync_moved` に残す
    （PC版の画面の上に知らせる）。"""
    settings = load_settings(data_dir)
    folder, mark = settings.get('sync_dir'), settings.get('sync_mark')
    if not folder:
        return None
    here = Path(folder)
    try:
        usable = here.is_dir()
    except OSError:   # もう一方のアカウントのドライブはアクセス拒否になることがある
        usable = False
    if usable:
        found = _sync_mark(here)
        if found is None or mark is None or found == mark:
            if found is None or mark is None:
                write_sync_mark(data_dir, here)
            return folder
    if not mark:
        return None
    for candidate in _other_drive_folders(here):
        try:
            if candidate.is_dir() and _sync_mark(candidate) == mark:
                moved = candidate.as_posix()
                save_settings(data_dir, sync_dir=moved, sync_moved=dict(
                    old=folder, new=moved, at=datetime.now().astimezone().isoformat(timespec='seconds')))
                import error_log
                error_log.note(data_dir, 'sync_dir.moved', f'同期フォルダが {folder} に無く、目印の一致する {moved} へ切り替えました')
                return moved
        except OSError:
            continue
    return None


SNAPSHOT_KEEP_DAYS = 7
SNAPSHOT_PATTERN = 'database-backup-????-??-??.json'


def snapshot_dir(data_dir):
    """Where the dated backups live: ``backups/`` inside the sync folder when one
    is set (so they reach Drive too), otherwise inside the local data folder."""
    folder = resolve_sync_dir(data_dir)
    root = Path(folder) if folder and Path(folder).is_dir() else Path(data_dir)
    return root / 'backups'


def snapshot_backup(store, data_dir, today=None, keep_days=SNAPSHOT_KEEP_DAYS):
    """Keep one backup file per day (the day's latest state) and drop the old ones.

    The single auto-backup file is overwritten on every save, so a bad save is
    copied into it within seconds. These dated copies are what lets you go back
    to "how it was N days ago". Files older than ``keep_days`` days are deleted.
    """
    today = today or date.today()
    folder = snapshot_dir(data_dir)
    target = folder / f'database-backup-{today.isoformat()}.json'
    export_backup(store, target)
    for path in folder.glob(SNAPSHOT_PATTERN):
        try:
            stamp = date.fromisoformat(path.stem[len('database-backup-'):])
        except ValueError:
            continue
        if (today - stamp).days > keep_days:
            path.unlink(missing_ok=True)
    return target


def list_snapshots(data_dir):
    """[(date, path), ...] newest first."""
    found = []
    for path in snapshot_dir(data_dir).glob(SNAPSHOT_PATTERN):
        try:
            found.append((date.fromisoformat(path.stem[len('database-backup-'):]), path))
        except ValueError:
            continue
    return sorted(found, reverse=True)


def restore_backup(store, path):
    """Bring the data back to how a dated backup had it.

    Applies what a normal import applies (new racks, graphs, links), and also
    forces the backup's version wherever it disagrees with what is saved now:
    differing numbers, and a different graph. Racks added AFTER that backup are
    left alone (nothing is deleted).
    """
    plan = import_backup(store, path)
    existing = {(r['store'], r['day'], r['machine'], int(r['rack'])): r for r in store.rows()}
    forced = [incoming for _local, incoming in plan['conflicts']] + plan.get('deleted', [])
    for record in plan['unchanged']:
        local = existing.get((record['store'], record['day'], record['machine'], int(record['rack'])))
        wanted = record.get('graph_measurement') or record.get('graph')
        if local and wanted and wanted != (local.get('graph_measurement') or local.get('graph')):
            forced.append(record)
    if forced:
        store.save(forced)
    return dict(plan, forced=forced)


def auto_backup(store, data_dir, *, strict=False, notices=None, import_shared=True):
    from backup_status import BackupStatus
    status = BackupStatus(data_dir, 'meruhen', load_settings(data_dir).get('sync_dir'))
    try:
        names = {'nagamachiminami': '長町南', 'saiwaichou': '幸町'}
        status.stores = [dict(name=names.get(place, place), day=day, count=count)
                         for place, day, count in store.db.execute(
                             'SELECT store, MAX(day), COUNT(*) FROM days GROUP BY store')]
        result = _auto_backup(store, data_dir, strict=strict, notices=notices,
                              import_shared=import_shared, status=status)
        if not status.folder or not Path(status.folder).is_dir():
            state, message = 'unavailable', ('同期フォルダ未設定' if not status.folder else
                                             '同期フォルダが見つかりません。ドライブ・接続を確認してください。')
        elif result is None:
            state, message = 'failed', '\n'.join(status.problems)
        elif status.problems:
            state, message = 'partial', '\n'.join(status.problems)
        else:
            state, message = 'success', ''
    except Exception as error:
        status.finish('failed', f'{status.step}：{error}')
        raise
    if not status.finish(state, message) and notices is not None:
        notices.append('書き出し結果の記録を保存できませんでした。共有フォルダのファイルを確認してください。')
    return result


def _auto_backup(store, data_dir, *, strict, notices, import_shared, status):
    """Refresh backups after data changed; strict=True reports output failures.

    Also writes today's dated backup (see ``snapshot_backup``). The shared-folder
    copy is skipped unless a sync folder was configured, because a failed backup
    must never get in the way of saving the record itself.
    """
    if import_shared:
        status.step = '共有編集の取り込み'
        sync_shared_history(store, data_dir, notices)
    snapshot = None
    try:
        status.step = '日別バックアップ'
        snapshot = snapshot_backup(store, data_dir)
        status.done('snapshot')
    except (OSError, ValueError) as error:
        status.problems.append(f'日別バックアップ：{error}')
        if strict:
            raise
    folder = resolve_sync_dir(data_dir)
    configured = load_settings(data_dir).get('sync_dir')
    status.folder = str(folder) if folder else configured
    if not folder or not Path(folder).is_dir():
        if configured and not folder and Path(configured).is_dir():
            status.problems.append(f'{configured} には別の同期フォルダの目印があるため書き出しませんでした'
                                   '（もう一方のアカウントのドライブの可能性）。「同期フォルダを指定」で選び直してください。')
        return None
    try:
        status.step = '全期間バックアップの共有フォルダへの書き出し'
        path = Path(folder) / AUTO_BACKUP_NAME
        if snapshot is not None:
            # 同じ内容なので、全データを2回書き出さず、書き出した1つを複製する。
            atomic_copy(snapshot, path)
        else:
            export_backup(store, path)
        status.done('backup')
    except OSError as error:
        status.problems.append(f'{status.step}：{error}')
        if strict:
            raise
        return None
    try:
        status.step = '閲覧用ファイルの共有フォルダへの書き出し'
        # 閲覧ページ用の軽いファイル。ローカルで書いてから同期フォルダへ複製する
        # （書きかけのファイルがDriveへ上がらないように）。
        local = Path(data_dir) / VIEWER_FILE_NAME
        export_viewer(store, local)
        atomic_copy(local, Path(folder) / VIEWER_FILE_NAME)
        status.done('viewer')
    except (OSError, ValueError) as error:
        status.problems.append(f'{status.step}：{error}')
        if strict:
            raise
    # 履歴の基準・個別項目が読めなくても、通常のバックアップとAndroid出力は続ける。
    try:
        status.step = 'イベント履歴の共有フォルダへの書き出し'
        from event_history_data import FILE_NAME, load_base, VARIETY_KEY, saiwaichou_base, clean_edits, empty_edits
        clean, rejected = store.history_edits_status()
        variety, variety_rejected = clean_edits(store.history_edits_raw().get(VARIETY_KEY, empty_edits()), saiwaichou_base())
        if variety['weeks'] or variety['cells'] or variety['links'] or variety_rejected:
            clean[VARIETY_KEY] = dict(variety, base=saiwaichou_base(), rejected=variety_rejected)
        with atomic_writer(Path(folder) / FILE_NAME) as out:
            json.dump(dict(clean, base=load_base(), rejected=rejected,
                           updated_at=datetime.now().astimezone().isoformat()), out, ensure_ascii=False)
        status.done('history')
    except (OSError, ValueError) as error:
        status.problems.append(f'{status.step}：{error}')
        if notices is not None:
            notices.append(f'イベント履歴の共有用出力は更新できませんでした：{error}')
    # Android用の直近7日分は最後に、失敗してもほかの書き出しを止めない（strict でも知らせるだけ）。
    # 先に書くと、ここでの失敗で閲覧用（iPhone版・共有ページ）の更新まで止まる（2026-10-18 確認）。
    try:
        status.step = 'Android用の直近7日分の書き出し'
        if export_recent_backup(store, data_dir, folder) is not None:
            status.done('recent')
    except (OSError, ValueError) as error:
        status.problems.append(f'{status.step}：{error}')
        if notices is not None:
            notices.append(f'Android用の直近7日分（{RECENT_BACKUP_NAME}）を書き出せませんでした（{error}）。'
                           '全期間のバックアップと閲覧用は更新済みです。次の保存でもう一度書き出します。')
    return path


def export_recent_backup(store, data_dir, folder):
    """直近 RECENT_BACKUP_DAYS 日分のバックアップを、ローカルで書いてから同期フォルダへ複製する
    （書きかけのファイルがDriveへ上がらないように）。記録が無ければ書かない。"""
    latest = store.db.execute('SELECT MAX(day) FROM days').fetchone()[0]
    if not latest:
        return None
    since = (date.fromisoformat(latest) - timedelta(days=RECENT_BACKUP_DAYS - 1)).isoformat()
    local = Path(data_dir) / RECENT_BACKUP_NAME
    export_backup(store, local, since=since)
    return atomic_copy(local, Path(folder) / RECENT_BACKUP_NAME)


UNDO_NAME = 'last_save.json'
SHORT_STORE_NAMES = {'nagamachiminami': '長町南', 'saiwaichou': '幸町'}


def remember_for_undo(store, data_dir, label, rows, previous=None):
    """Snapshot what ``rows`` looked like just BEFORE they are saved.

    One level only: it always describes the most recent save, so "取り消す"
    means exactly "put those racks back the way they were".
    """
    keys = [(r['store'], r['day'], r['machine'], int(r['rack'])) for r in rows]
    if previous is None:
        previous = store.payload_map(keys)
    if len(previous) != len(keys):
        raise ValueError('取り消し控えの件数が一致しません。')
    entries = [dict(key=list(k), previous=p) for k, p in zip(keys, previous)]
    path = Path(data_dir) / UNDO_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(label=label, saved_at=datetime.now().astimezone().isoformat(),
                                    entries=entries), ensure_ascii=False), encoding='utf-8')


def delete_records(store, data_dir, day, location=None, machine=None, *, defer_outputs=False):
    """機種ごと・日付ごとにまとめて削除する。消した台数を返す。

    消す前の内容を「直前の保存を取り消す」の控えに残すので、誤って消しても
    1回分は元に戻せる。消す前と後の両方で日付入りバックアップも更新する
    （消す前の状態は「過去のバックアップから戻す」の当日分に一度書かれる）。
    """
    rows = store.rows(day, machine, location)
    if not rows:
        raise ValueError('削除できる記録がありません。')
    where = ' '.join(x for x in (day, SHORT_STORE_NAMES.get(location, '両店舗'), machine) if x)
    previous = store.payload_map([
        (r['store'], r['day'], r['machine'], int(r['rack'])) for r in rows
    ])
    # 消す前の台を、読み込めるバックアップの形で7日間残す（取り消しは1回分だけで、
    # 日付入りの控えも消した後の状態で上書きされるため）。
    keep_deleted(data_dir, where, previous)
    count = store.delete_group(day, location, machine)
    remember_for_undo(store, data_dir, f'{where}の削除（{len(rows)}台）', rows, previous=previous)
    if not defer_outputs:
        auto_backup(store, data_dir)
    return count


DELETED_KEEP_DAYS = 7


def deleted_dir(data_dir):
    folder = snapshot_dir(data_dir) / 'deleted'
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def keep_deleted(data_dir, label, payloads, now=None):
    """Write the racks about to be deleted as a backup file; drop week-old ones.

    「バックアップを読み込む」でこのファイルを選べば、消した台を戻せる。
    """
    now = now or datetime.now()
    folder = deleted_dir(data_dir)
    rows = [p for p in payloads if p]
    header = json.dumps(dict(format=BACKUP_FORMAT, version=BACKUP_VERSION,
                             exported_at=now.astimezone().isoformat(), source='pc-deleted',
                             label=label), ensure_ascii=False)[:-1]
    body = ',\n'.join(json.dumps(p, ensure_ascii=False) for p in rows)
    target = folder / f'database-deleted-{now:%Y%m%d-%H%M%S}.json'
    target.write_text(f'{header}, "records": [\n{body}\n]}}', encoding='utf-8')
    for old in folder.glob('database-deleted-*.json'):
        try:
            stamp = datetime.strptime(old.stem[len('database-deleted-'):], '%Y%m%d-%H%M%S')
        except ValueError:
            continue
        if (now - stamp).days >= DELETED_KEEP_DAYS:
            old.unlink(missing_ok=True)
    return target


def undo_last_save(store, data_dir, *, defer_outputs=False):
    """Restore the racks touched by the last save; returns its label."""
    path = Path(data_dir) / UNDO_NAME
    try:
        info = json.loads(path.read_text(encoding='utf-8'))
        entries = [(tuple(e['key']), e['previous']) for e in info['entries']]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError('取り消せる保存がありません。') from exc
    store.restore_payloads(entries)
    path.unlink()
    if not defer_outputs:
        auto_backup(store, data_dir)
    return info.get('label', '直前の保存')


def has_graph(row):
    return bool(row.get('graph') or row.get('graph_measurement'))


def no_hits(row):
    """表の大当たり（BB+RB）が0回か。BB・RBが分からない台は0回にしない。"""
    try:
        return int(row.get('bb')) + int(row.get('rb')) == 0
    except (TypeError, ValueError):
        return False


def graph_not_needed(row):
    """大当たり0回でグラフの無い台。グラフは取らない（利用者の指定、2026-09-29。
    実データの0回550台で、終点がプラスだったのは24Gの1台だけ）。表を取り込み
    直して当たりが付けば、また取る対象に戻る。Android版 `graphNotNeeded`。"""
    return not has_graph(row) and no_hits(row)


def juggler_online_made(row):
    """メルヘンのサイトが落ちていた日に、Androidがジャグラーオンラインの数字で作った台（グラフは取れない）。"""
    return row.get('jo_created') is True and not has_graph(row)


def graph_done(row):
    """グラフが済んでいる（取り込み済み、または大当たり0回で不要）。"""
    return has_graph(row) or no_hits(row)


def progress_text(store, day):
    """"2026-09-18　長町南 42/80台・幸町 18/60台" -- graphs done / racks listed
    (大当たり0回でグラフを取らない台は済みとして数える).
    取り込みの対象外の機種（沖ドキなど）は数えない：サイトからは取らないのに、ジャグラーオンラインの読み取りで
    記録ができるため、「未取り込みの機種・グラフはありません」なのに 532/551台 のように残って見えていた
    （2026-10-12、幸町のオキドキデュオ2の19台）。Android の progressText と同じ規則。"""
    parts = []
    for location, short in SHORT_STORE_NAMES.items():
        rows = [r for r in store.rows(day, None, location) if not is_excluded_machine(location, r['machine'])]
        if rows:
            done = sum(1 for r in rows if graph_done(r))
            parts.append(f'{short} {done}/{len(rows)}台')
    return f'{day}　' + '・'.join(parts) if parts else ''


def rack_trend(store, row, limit=7):
    """Recent days of the SAME rack running the SAME machine, newest first.

    A rack number can host a different machine on another day, and scores are
    only comparable within one machine, so a machine swap ends the history.
    """
    rows = [r for r in store._machine_rows(row['machine'], row['store'])
            if int(r['rack']) == int(row['rack']) and r['day'] <= row['day']]
    rows.sort(key=lambda r: r['day'], reverse=True)
    trend = []
    for r in rows[:limit]:
        result = score(r, store.references(r))
        hits = r['bb'] + r['rb']
        trend.append(dict(day=r['day'], games=r['games'], hits=hits,
                          rate=(r['games'] / hits if hits else None),
                          total=result['total'], provisional=result['provisional']))
    return trend


def slump_days(store, row, count=5):
    """The latest ``count`` days of graphs for this rack (same machine), oldest first.

    Empty unless at least ``count`` days have a saved graph: the strip only
    makes sense as a multi-day view.
    """
    rows = [r for r in store._machine_rows(row['machine'], row['store'])
            if int(r['rack']) == int(row['rack'])
            and r['day'] <= row['day'] and (r.get('graph_measurement') or r.get('graph'))]
    rows.sort(key=lambda r: r['day'], reverse=True)
    return list(reversed(rows[:count])) if len(rows) >= count else []


def slump_strip_html(store, row, count=5):
    """Each day's saved graph side by side, oldest to newest (left to right).

    Every graph keeps its own vertical scale (the site auto-scales each day),
    so this shows the shape day after day, not one cumulative medal count.
    """
    days = slump_days(store, row, count)
    if not days:
        return ''
    totals = {t['day']: t['total'] for t in rack_trend(store, row, limit=max(count, 7))}
    tiles = []
    for r in days:
        kind, payload = measurement_preview(r)
        if kind == 'image':
            picture = f'<img src="data:image/png;base64,{payload}" alt="スランプグラフ">'
        elif kind in ('svg', 'reconstructed'):
            picture = payload
        else:
            continue
        total = totals.get(r['day'])
        tiles.append(f'<figure><div class="sg">{picture}</div>'
                     f'<figcaption>{r["day"][5:].replace("-", "/")}<br>'
                     f'{"—" if total is None else format(total, ".1f")}点</figcaption></figure>')
    if len(tiles) < count:
        return ''
    return (f'<div class="dsub" style="margin-top:14px">{count}日間のスランプグラフ（左が古い日）</div>'
            f'<div class="strip">{"".join(tiles)}</div>'
            '<div class="dsub" style="font-size:12px">縦軸は日ごとに自動調整される相対形状です（日をまたいだ差枚の合計ではありません）。</div>')


def reliability_label(games):
    """How much data stands behind a rack's hit frequency (games played)."""
    if games is None or games < 1500:
        return '少'
    return '多' if games >= 3500 else '中'


def captured_note(row):
    """"取得 21:48" (+ a warning when the numbers were taken well before closing)."""
    raw = row.get('captured_at')
    if not raw:
        return ''
    try:
        stamp = datetime.fromisoformat(raw)
    except ValueError:
        return ''
    text = f'取得 {stamp:%m/%d %H:%M}'
    return text + '（早めの取得：回転数は途中経過）' if stamp.hour < 20 else text


def signed_index(index):
    """Show a 50-is-neutral tendency index as "平均より +13".

    The raw "63 / 100" hides both the midpoint and which direction is good.
    """
    delta = index - 50
    return f'平均より {"+" if delta >= 0 else "-"}{abs(delta):.0f}'


# 翌日候補（仮）の計算方式の版。保存する候補の記録に残し、式を変えたときに新旧の
# 成績を混ぜないようにする。Android版 `nextDayMethodVersion` と同じ値。
# 2026-09-27：サイトの異常値を除外。
# 2026-09-29：1〜3台の機種を店ごとに「バラエティ」にまとめ、店ごとの狙い方で5台選ぶ
# （variety_next_day_candidates）。4台以上の機種の選び方は変えていない
# （NEXT_DAY_CANDIDATES_VALIDATION_20260929.md の「9. バラエティ」）。
NEXT_DAY_METHOD_VERSION = '2026-10-07'

# バラエティ：その日その店で1〜3台の機種（利用者の指定、2026-09-29）。今の選び方は
# 同じ機種の台どうしで比べ、1機種で4台以上判定できる必要があるので、これらの機種は
# 一度も候補に入らなかった。Android版 `varietyMaxRacks`・`varietyGroupName` と同じ。
VARIETY_MAX_RACKS = 3


def variety_max_racks(location):
    """店舗のバラエティ上限。2026-10-13利用者指定：幸町は1〜2台、ほかは1〜3台。"""
    return 2 if location == 'saiwaichou' else VARIETY_MAX_RACKS


def variety_range(location):
    return f'1〜{variety_max_racks(location)}台'


def candidate_method_version(location, machine, day=None):
    # 幸町のバラエティの母集団変更を旧記録と区別する。通常機種の固定検証方式は維持。
    # 幸町のジャグラー・ハナハナは予想の式で並べる（2026-10-17）ので、旧記録と区別する。
    if location == 'saiwaichou' and machine == VARIETY_GROUP_NAME:
        return '2026-10-13-saiwaichou-variety-2'
    if normal_model_applies(location, machine, day):
        import normal_next_day_model
        return normal_next_day_model.METHOD_VERSION
    return NEXT_DAY_METHOD_VERSION

VARIETY_GROUP_NAME = 'バラエティ'
# バラエティで「よく回った」とみなす回転数（4時間ほど打たれた台の目安。プロの経験則で、
# 数値の出典は無い）と、候補に出す台数（利用者の指定）。Android版と同じ。
VARIETY_BUSY_GAMES = 3000
VARIETY_PICKS = 5
VARIETY_STATE_LABELS = {'dented': '回ったのに凹み', 'plus': '回ってプラス',
                        'quiet': '3000G未満', 'unknown': 'グラフ未取得'}


def variety_machines(rows):
    """1店舗・1日の行 ``rows`` のうち、バラエティにまとめる機種の名前。"""
    counts, limits = {}, {}
    for r in rows:
        counts[r['machine']] = counts.get(r['machine'], 0) + 1
        limits[r['machine']] = variety_max_racks(r.get('store', 'nagamachiminami'))
    return {machine for machine, count in counts.items() if count <= limits[machine]}


def is_variety_row(store, row):
    """その台の機種が、その日その店でバラエティ（1〜3台）か。"""
    return sum(1 for r in store._machine_rows(row['machine'], row['store'])
               if r['day'] == row['day']) <= variety_max_racks(row['store'])


def next_day_index(store, row, max_days=10, shrink_days=5):
    evidence = next_day_evidence(store, row, max_days, shrink_days)
    return {k: evidence[k] for k in ('days', 'index', 'confidence')}


def next_day_evidence(store, row, max_days=10, shrink_days=5):
    """Historical hit-frequency tendency for the provisional candidate view.

    This is not a validated forecast, setting probability, or part of the
    100-point daily score. It is deliberately limited to data available by
    ``row['day']`` so it can be evaluated later without future leakage.
    """
    by_day = _evidence_pool(store, row['machine'], row['store'], row['day'])
    rack = int(row['rack'])
    days = sorted((d for d, rows in by_day.items() if any(int(r['rack']) == rack for r in rows)),
                  reverse=True)[:max_days]
    gaps = []
    contributions = []
    for day in days:
        mine = next(r for r in by_day[day] if int(r['rack']) == rack)
        peers = [r for r in by_day[day] if mine['games'] / 2 <= r['games'] <= mine['games'] * 2]
        if len(peers) >= 3:
            rates = [(r['bb'] + r['rb']) / r['games'] for r in peers]
            rank = percentile((mine['bb'] + mine['rb']) / mine['games'], rates)
            gaps.append((100 * rank - 50) * mine['games'] / (mine['games'] + SHRINK_GAMES))
            contributions.append(dict(day=day, games=mine['games'], peers=len(peers), rank=rank, gap=gaps[-1]))
        else:
            contributions.append(dict(day=day, games=mine['games'], peers=len(peers), rank=None, gap=None))
    n = len(gaps)
    used = [d for d in contributions if d['gap'] is not None]
    variance = sum((d['peers'] ** 2 - 1) / (12 * d['peers'] ** 2) for d in used)
    z = sum(d['rank'] - .5 for d in used) / math.sqrt(variance) if variance else 0
    raw = 50 + sum(gaps) / (n + shrink_days) if n >= 3 else None
    return dict(days=n, index=round_score(raw) if raw is not None else None,
                confidence='データ不足' if n < 3 else '少' if n < 7 else '中',
                raw_index=raw, latest_used=used[0]['day'] if used else '',
                contributions=contributions, stability_z=z,
                today_used=bool(used and used[0]['day'] == row['day']))


def _evidence_pool(store, machine, location, day):
    """next_day_evidence の比較材料（その日までの30日・使える記録）を日ごとにまとめたもの。
    同じ機種・同じ日の台はすべて同じ材料を使うので、台ごとに全記録をふるい直さない（2026-10-25、
    幸町の翌日候補で台数×日数×記録数の走査になっていた）。並びは _machine_rows と同じ。
    _machine_cache の中に置き、書き込みでキャッシュが作り直されると一緒に捨てる。"""
    cache = store.__dict__.setdefault('_machine_cache', {})
    key = ('next_day_evidence', machine, location, day)
    if key not in cache:
        first = (date.fromisoformat(day) - timedelta(days=30)).isoformat()
        by_day = {}
        for r in store._machine_rows(machine, location):
            if (first <= r['day'] <= day and r.get('games', 0) >= 500
                    and r.get('bb') is not None and r.get('rb') is not None
                    and r['bb'] >= 0 and r['rb'] >= 0 and not implausible_numbers(r)):
                by_day.setdefault(r['day'], []).append(r)
        cache[key] = by_day
    return cache[key]


def next_day_focus(evidence, today_score):
    """Fixed descriptive screen; not a calibrated probability. User cutoff is inclusive."""
    return (evidence['raw_index'] is not None and evidence['today_used']
            and evidence['stability_z'] >= 1.96
            and (today_score is None or today_score < 88))


def next_day_sort_key(item):
    # 同じ指数なら、その日の回転数が多い台を上（利用者、2026-10-07）。Android `compareNextDayEvidence` と同じ。
    return (-round(item['raw_index'], 9), -int(item['row'].get('games') or 0), -item['days'],
            -date.fromisoformat(item['latest_used']).toordinal(), int(item['row']['rack']))


def next_day_reason(item):
    evidence = item
    today = next((d for d in evidence['contributions'] if d['day'] == item['row']['day']), None)
    if evidence['today_used']:
        band = '上' if today['rank'] >= .75 else '下' if today['rank'] <= .25 else '中'
        current = f"選択日 {today['games']:,}G・当たり順位 {band}・寄与{today['gap']:+.1f}"
    else:
        reason = ('500G未満' if item['row']['games'] < 500 else '数値異常' if implausible_numbers(item['row'])
                  else '回転数が近い比較相手が3台未満' if today else '使用できる記録なし')
        current = f'選択日の結果は指数に入っていません（{reason}）'
    if item['today_score'] is not None and item['today_score'] >= 88:
        why = f"当日{item['today_score']:.1f}点：88点以上のため★注目から除外"
    elif not evidence['today_used']:
        why = '当日情報が入っていないため★注目の条件未達'
    elif evidence['stability_z'] < 1.96:
        why = '傾向の安定性基準未達のため★注目の条件未達'
    else:
        why = '当日情報あり・傾向の安定性基準を満たす（予測精度は検証中）'
    return f'{current}／{why}'


def variety_state(row):
    """バラエティの台のその日の終わり方（Android版 `varietyState`）。

    'dented'（3000G以上回ったのにプラスで終わらなかった）・'plus'（回ってプラス）・
    'quiet'（3000G未満）・'unknown'（グラフが無く終わり方が分からない）。プラスは
    グラフの終点がゼロ線より上（採点の終点と同じく1ピクセル以内はゼロ扱い）。
    大当たり0回でグラフを取らない台は凹み。
    """
    if (row.get('games') or 0) < VARIETY_BUSY_GAMES:
        return 'quiet'
    measurement = row.get('graph_measurement')
    if not measurement:
        return 'dented' if no_hits(row) else 'unknown'
    try:
        end = float(measurement['baseline_y']) - float(measurement['end_y'])
    except (KeyError, TypeError, ValueError):
        return 'unknown'
    if not math.isfinite(end):
        return 'unknown'
    return 'plus' if end > 1 else 'dented'


def variety_order(location):
    """店ごとの狙い方（先に見る終わり方の順）。利用者の指定（2026-09-29）で、実データ
    7日分の傾向に合わせている：長町南は前日「回ったのに凹んだ台」が翌日よい割合が高く、
    幸町は「回ってプラスの台」が翌日も続きやすかった。Android版 `varietyOrder`。"""
    return ('dented', 'plus') if location == 'nagamachiminami' else ('plus', 'dented')


def variety_rule_text(location):
    first, second = (VARIETY_STATE_LABELS[s] for s in variety_order(location))
    return (f'前日{VARIETY_BUSY_GAMES}G以上回った台から、「{first}」の台を先に、次に「{second}」の台を、'
            f'それぞれ当たりがその台の普段より軽い順に{VARIETY_PICKS}台')


def variety_hit_percent(store, row):
    """その日の当たり確率が、その台の普段（同じ機種の前の30日の記録。1台の機種なら
    その台自身の過去）と比べて何番目か（0〜100、50が普段どおり）。比べる相手の条件は
    採点の comparison_pool と同じで、別の機種とは比べない。3件未満なら percent=None。
    Android版 `varietyHitPercent`。"""
    history = store._machine_rows(row['machine'], row['store'])
    rates = [(r['bb'] + r['rb']) / r['games'] for r in comparison_pool(row, history)
             if r.get('bb') is not None and r.get('rb') is not None
             and r['bb'] >= 0 and r['rb'] >= 0]
    if len(rates) < 3 or not row.get('games'):
        return dict(percent=None, refs=len(rates))
    rank = percentile((row['bb'] + row['rb']) / row['games'], rates)
    return dict(percent=round_score(100 * rank), refs=len(rates))


def variety_judgement_text(store, row):
    """台の詳細に出す、バラエティの台の翌日候補の見方（Android版 `varietyJudgementText`）。"""
    state = variety_state(row)
    hit = variety_hit_percent(store, row)
    if state == 'quiet':
        detail = f'{VARIETY_BUSY_GAMES}G未満で、判断の材料が少ないので候補にしません'
    elif state == 'unknown':
        detail = 'グラフが未取得で、終わり方が分からないので候補にしません'
    elif hit['percent'] is None:
        detail = f'{VARIETY_STATE_LABELS[state]}（当たりは普段と比べる記録が足りない）'
    else:
        delta = hit['percent'] - 50
        detail = (f'{VARIETY_STATE_LABELS[state]}・当たり 普段より {"+" if delta >= 0 else "-"}'
                  f'{abs(delta):.0f}（比べた記録{hit["refs"]}件）')
    return (f'この台は{variety_range(row["store"])}の機種なので「{VARIETY_GROUP_NAME}」にまとめています。'
            f'{SHORT_STORE_NAMES.get(row["store"], row["store"])}の狙い方：{variety_rule_text(row["store"])}。'
            f'この日のこの台：{row["games"]}G・{detail}。'
            '当たりは同じ機種の前の30日（1台の機種ならこの台自身の過去）とだけ比べ、別の機種の台とは比べていません。')


def provisional_next_day_candidates(store, day, machine, location='nagamachiminami'):
    """Return a clearly-labelled trial list for the day after ``day``.

    Only same-rack, same-machine hit-frequency history is used. At least four
    racks need three usable historical days before one top-quartile candidate
    can be shown. The output stays independent from ``score`` and contains no
    claim that the next day's setting, payout, or win chance is known.
    """
    rows = store.rows(day, machine, location)
    eligible = []
    for row in rows:
        tendency = next_day_evidence(store, row)
        if tendency['index'] is not None:
            today_score = score(row, store._machine_rows(row['machine'], row['store']))['total']
            eligible.append(dict(row=row, variety=False, today_score=today_score,
                                 focus=next_day_focus(tendency, today_score), **tendency))
    if eligible and normal_model_applies(location, machine, day):
        # 幸町のジャグラー・ハナハナは、14か月分から作った予想の式の点の高い順（2026-10-17、
        # normal_next_day_model.py）。候補に入りうる台と台数は同じで、並べる順だけが違う。
        import normal_next_day_model as model
        per_rack = model.history_values(store._machine_rows(machine, location), day)
        for item in eligible:
            item['model_score'] = model.score(model.features(per_rack, item['row'], item['raw_index']))
        eligible.sort(key=lambda item: (-round(item['model_score'], 9), -int(item['row'].get('games') or 0),
                                        int(item['row']['rack'])))
    else:
        eligible.sort(key=next_day_sort_key)
    count = math.ceil(len(eligible) * .25) if len(eligible) >= 4 else 0
    return dict(total=len(rows), eligible=len(eligible), count=count,
                candidates=eligible[:count])


def normal_model_applies(location, machine, day=None):
    """幸町のジャグラー・ハナハナで、選ぶ日が式の使用開始日以降（翌日候補を予想の式で並べる対象）。
    day を省くと日付は見ない（説明文を出すかの判定など）。Android `normalModelApplies` と同じ。"""
    import normal_next_day_model
    return normal_next_day_model.applies(location, machine, day)


def variety_next_day_candidates(store, day, location='nagamachiminami'):
    """その日その店のバラエティ（1〜3台の機種の台）の翌日候補（Android版
    `varietyNextDayCandidates`）。プロの見方で選ぶ（利用者の指定、2026-09-29）：前日
    3000G以上回った台（打ち手が粘った台）だけを見て、店ごとの狙い方（variety_order）の
    順に、同じ終わり方の中では当たりがその台の普段より軽い順（比べられない台は50）、
    次に回転数の多い順で5台。``index`` は当たりの普段比、``days`` は比べた記録の件数。
    """
    rows = store.rows(day, None, location)
    names = variety_machines(rows)
    rows = [r for r in rows if r['machine'] in names]
    order = variety_order(location)
    ranked = []
    for row in rows:
        if implausible_numbers(row):
            continue
        state = variety_state(row)
        if state not in order:
            continue
        hit = variety_hit_percent(store, row)
        confidence = '比較なし' if hit['percent'] is None else '少' if hit['refs'] < 7 else '中'
        ranked.append((order.index(state), dict(
            row=row, index=50.0 if hit['percent'] is None else hit['percent'], days=hit['refs'],
            confidence=confidence, variety=True, state=state)))
    ranked.sort(key=lambda item: (item[0], -item[1]['index'], -item[1]['row']['games'],
                                  int(item[1]['row']['rack']), item[1]['row']['machine']))
    picks = [candidate for _group, candidate in ranked[:VARIETY_PICKS]]
    return dict(total=len(rows), eligible=len(ranked), count=len(picks), candidates=picks)


def day_candidates(store, day, location='nagamachiminami'):
    """その日その店の全機種の翌日候補（Android版 `dayCandidates` と同じ並び）。

    4台以上の機種は機種ごとの上位4分の1を「平均より」の大きい順・機種名・台番号の順に
    並べ、その後ろにバラエティ（1〜3台の機種）の5台を狙い方の順に付ける。
    """
    rows = store.rows(day, None, location)
    names = variety_machines(rows)
    candidates = []
    for machine in sorted({r['machine'] for r in rows} - names):
        candidates.extend(provisional_next_day_candidates(store, day, machine, location)['candidates'])
    candidates.sort(key=lambda item: (-item['index'], item['row']['machine'], int(item['row']['rack'])))
    if names:
        candidates.extend(variety_next_day_candidates(store, day, location)['candidates'])
    return candidates


def machine_progress(store, location, day):
    """{whitespace-stripped machine name: (graphed, listed)} for one store and day."""
    result = {}
    for r in store.rows(day, None, location):
        key = re.sub(r'\s+', '', r['machine'])
        done, total = result.get(key, (0, 0))
        result[key] = (done + (1 if graph_done(r) else 0), total + 1)
    return result


def machine_last_capture(store, location, day):
    """{空白を除いた機種名: その日の行の一番新しい取り込み時刻（秒）}。時刻の分からない行は数えない。"""
    result = {}
    for r in store.rows(day, None, location):
        try:
            stamp = datetime.fromisoformat(r['captured_at']).timestamp() if r.get('captured_at') else None
        except ValueError:
            stamp = None
        if stamp is not None:
            key = re.sub(r'\s+', '', r['machine'])
            result[key] = max(result.get(key, stamp), stamp)
    return result


# 取り込みを開き直しただけで、少し前（今夜）に取った分まで取り直さないよう、3時間の余裕を持たせる（昼と夜のような差だけを取り直す。2026-10-05、開き直した後に手動の「次へ」が済んだ機種の表へ向かった不具合）。営業が終わった日は、その日の23時より後に取った分を最終とみなす。
STALE_MARGIN_HOURS = 3


def stale_capture_cutoff(day, since):
    """[day] の機種の表を、これより前に取ったきりなら取り直す（昼に取った数値を夜の分として残さない）。

    since：今回の取り込みを始めた時刻（取り込みの画面を開いた・自動取り込みをONにした時刻）。
    その日の営業が終わった後（翌日の午前2時以降）の数値はもう変わらないので、そこで頭打ちにする。
    閉店後の基準なので、営業日の切り替え（3時、2026-10-26）とは別に2時のまま（pscube_import.DAY_FINAL_HOUR）。
    P’s CUBE の `stale_cutoff`（pscube_import.py）と同じ考え方。"""
    if since is None or not day:
        return None
    day_end = datetime.fromisoformat(f'{day}T00:00:00+09:00') + timedelta(days=1, hours=2)
    return min(since.timestamp(), day_end.timestamp()) - STALE_MARGIN_HOURS * 3600


def day_fully_graphed(store, day):
    rows = store.rows(day)
    return bool(rows) and all(graph_done(r) for r in rows)


def suspicious_duplicates(store, day, location, machine=None):
    """Racks of one machine whose games/BB/REG are all identical (games > 0).

    Real racks essentially never agree on all three, so this is the
    fingerprint of a capture saved under the wrong rack number.
    Returns ``[(machine, [racks...]), ...]``.
    """
    groups = {}
    for r in store.rows(day, machine, location):
        if r.get('games', 0) > 0:
            groups.setdefault((r['machine'], r['games'], r['bb'], r['rb']), []).append(int(r['rack']))
    return sorted((key[0], sorted(racks)) for key, racks in groups.items() if len(racks) > 1)


def duplicate_warning(store, day, location, machine, rack=None):
    """Human-readable warning text, or '' when nothing looks off."""
    groups = [g for g in suspicious_duplicates(store, day, location, machine)
              if rack is None or int(rack) in g[1]]
    if not groups:
        return ''
    text = '、'.join('・'.join(map(str, racks)) + '番台' for _m, racks in groups)
    return f'⚠ {text}の数値（回転・BIG・REG）が完全に同じです。台番号のずれがないか確認してください。'


def latest_backup_file(folder, seen=None):
    """Newest backup JSON in ``folder`` (ignoring this app's own auto copy and
    the light viewer file, which has no graph images and must never be
    imported as if it were a backup). ``seen`` is the last successfully
    imported file's name/mtime; unchanged content need not be read again, and
    files older than it are not read at all (None: nothing new)."""
    for mtime, path in sorted(_backup_candidates(folder), key=lambda item: item[0], reverse=True):
        if seen and seen.get('name') == path.name and seen.get('mtime') == mtime:
            return path
        # 起動時の自動取り込み：前回取り込んだものより古いファイルは「新しいバックアップ」ではない。
        # 前回のファイルが消えていても、古いバックアップを読み直して取り込み直さない。
        if seen and isinstance(seen.get('mtime'), (int, float)) and mtime < seen['mtime']:
            return None
        if _is_backup_file(path):
            return path
    return None


def new_backup_files(folder, seen=None):
    """起動時に読む、前回取り込んだ版より新しいバックアップを古い順に返す（2026-10-25 利用者指定）。
    店舗ごとに分けて書き出したAndroidのファイルを、最新の1本だけ読んで取りこぼさないため。
    前回の記録が無いときは、従来どおり最新の1本だけ（過去のファイルをまとめて読み直さない）。"""
    seen_mtime = seen.get('mtime') if seen else None
    if not isinstance(seen_mtime, (int, float)):
        latest = latest_backup_file(folder)
        return [latest] if latest is not None else []
    newer = [(mtime, path) for mtime, path in _backup_candidates(folder)
             if mtime > seen_mtime or (mtime == seen_mtime and path.name != seen.get('name'))]
    return [path for _mtime, path in sorted(newer, key=lambda item: (item[0], item[1].name)) if _is_backup_file(path)]


def _backup_candidates(folder):
    """同期フォルダ内の、取り込み対象になりうるJSONの（更新時刻, パス）。"""
    # 日別原本・閲覧パーツもGoogle Driveからダウンロードして解析しない。
    # pscube-* はP’s CUBE用（別形式・大きい）。ここで読み込もうとしない。
    generated_prefixes = ('pscube-', 'database-history-day-',
                          'database-viewer-part-', 'database-viewer-parts-')
    candidates = [p for p in Path(folder).glob('*.json')
                  if p.name not in (AUTO_BACKUP_NAME, RECENT_BACKUP_NAME, VIEWER_FILE_NAME, 'database-android-cloud.json',
                                    SHARED_RAINBOW_NAME, SHARED_EVENTS_NAME)
                  and not p.name.startswith(generated_prefixes)]
    found = []
    for path in candidates:
        try:
            found.append((path.stat().st_mtime, path))
        except OSError:
            continue   # 探している間に消えた・読めないファイルは飛ばす（Driveの同期中など）
    return found


def _is_backup_file(path):
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return False
    return isinstance(payload, dict) and payload.get('format') == BACKUP_FORMAT


def import_backup(store, path):
    """Merge a validated backup atomically; old data cannot undo a deletion."""
    try:
        payload = _read_backup_document(path)
    except (OSError, ValueError) as exc:
        raise ValueError(f'バックアップファイルを読み込めません。{exc}') from exc
    with store.db:
        store._begin_write()
        store._merge_record_deletions(payload.get('record_deletions', []))
        marks = {store._record_key(m): m for m in store.record_deletions()}
        def deleted(row):
            try:
                mark = marks.get(store._record_key(row))
            except (KeyError, TypeError, ValueError):
                return False  # The normal classifier reports malformed rows.
            return bool(mark and not _record_after_deletion(row, mark))
        records = payload['records']
        if payload.get('source') == 'pc-deleted':
            records = [dict(r, record_updated_at=max(datetime.now().astimezone(),
                _timestamp(marks[store._record_key(r)]['deleted_at']) + timedelta(milliseconds=1)).isoformat())
                if deleted(r) else r for r in records]
        plan = plan_backup_import(store, [r for r in records if not deleted(r)])
        plan['deleted'] = [r for r in records if deleted(r)]
        merged_events, plan['events_added'], plan['event_conflicts'] = merge_date_events(
            store.date_events(include_removed=True), payload.get('date_events', []))
        plan['rainbow_added'] = store._merge_pending_rainbow_marks(payload['rainbow_marks']) if payload.get('rainbow_marks') else 0
        if plan['events_added']:
            store._write_date_events(store._date_events_payload(merged_events))
        plan['history_added'] = plan['history_conflicts'] = plan['history_rejected'] = plan['history_week_conflicts'] = 0
        if 'event_history_edits' in payload:
            from event_history_data import merge_edits, load_base
            try:
                raw = store.history_edits_raw()
                if 'unreadable_raw' in raw or 'unreadable_raw' in payload['event_history_edits']:
                    raise ValueError('履歴の原文に読めない項目があります。原本とバックアップを保持しています。')
                merged, plan['history_added'], plan['history_conflicts'], plan['history_rejected'], plan['history_week_conflicts'] = merge_edits(
                    raw, payload['event_history_edits'], load_base())
                store._write_history_edits(merged)
            except ValueError as error:
                plan['history_error'] = str(error)
        to_save = plan['new'] + plan['graph_only'] + plan['link_only'] + plan['setting_only'] + plan['jo_only']
        if to_save:
            store._save_rows(to_save, log_candidates=False)
        if payload.get('candidate_snapshots'):
            store._add_candidate_snapshots(payload['candidate_snapshots'])
    return plan


def percentile(value, values):
    # Midrank ties; reference excludes the scored date, even during re-runs.
    return (sum(x < value for x in values) + .5 * sum(x == value for x in values)) / len(values)


def provisional_rank_score(value, values, maximum):
    """Legacy helper; v8以降の採点は adjusted_rank を使う。"""
    if value == 0:
        return 0.0
    raw = maximum * percentile(value, values)
    weight = min(1.0, len(values) / MIN_REFERENCE_ROWS)
    midpoint = maximum / 2
    return midpoint + weight * (raw - midpoint)


def comparison_pool(row, reference):
    """Past-only, same store/model, similar exposure; caller cannot leak today."""
    first = (date.fromisoformat(row['day']) - timedelta(days=30)).isoformat()
    target = max(500, row['games'])
    return [r for r in reference
            if r.get('store') == row.get('store') and r.get('machine') == row.get('machine')
            and first <= r['day'] < row['day']
            and max(500, target / 2) <= r.get('games', 0) <= target * 2
            and not implausible_numbers(r)]


def adjusted_rank(value, rows, field, maximum, games):
    """Continuous conservative rank shrinkage; NOT Bayesian setting inference.

    v9 (2026-09-21): the three thinness factors are combined with their
    geometric mean instead of their product. Multiplied together they
    compounded so hard that, with the pool sizes this app actually has
    (median 4 racks from 1 day), no rack could reach 80 points even when it
    ranked first in every column -- the 100-point scale had collapsed to
    about 60-76. The mean keeps every factor's influence without that.
    """
    if value is None or not rows:
        return None
    values = [field(r) for r in rows]
    n, days = len(rows), len({r['day'] for r in rows})
    weight = (games / (games + SHRINK_GAMES) * n / (n + MIN_REFERENCE_ROWS)
              * days / (days + SHRINK_DAYS)) ** (1 / 3)
    return maximum * (0.5 + weight * (percentile(value, values) - 0.5))


def absolute_hold_score(max_hold):
    """Max-hold points from the coin count itself, full marks at the cap.

    Unlike a rank, this needs no comparison racks: COMPLETE_HOLD is a fixed
    ceiling a machine cannot exceed, so hitting it is the best possible
    result whatever the other racks did. Used only to raise the ranked
    score, never to lower it (see ``score``).
    """
    if max_hold is None:
        return None
    return MAX_HOLD_SCORE * min(1.0, max_hold / COMPLETE_HOLD)


def score(row, reference, provisional_reference=None):
    # Kept as a compatibility argument; same-day fallback is deliberately gone.
    s = dict(version=VERSION, games=spin_score(row.get('games')), max_hold=None,
             hits=None, positive=None, retention=None, total=None,
             reference_count=0, reference_days=0, hold_reference_count=0,
             provisional_count=0, provisional=True, confidence=None,
             coverage=0, missing_low=None, missing_high=None, status='pending', reasons=[])
    if s['games'] is None:
        s['reasons'].append('未稼働・回転数なし')
        return s
    if implausible_numbers(row):
        s['reasons'].append('サイトの数値が異常なため採点なし（88888888などの表示）')
        return s
    if row['games'] <= MIN_SCORED_GAMES:
        s['reasons'].append(f'{MIN_SCORED_GAMES}G以下のため採点なし')
        return s
    if any(row.get(k) is not None and row[k] < 0 for k in ('bb', 'rb', 'max_hold')):
        s['reasons'].append('負の数値を確認してください')
        return s
    refs = comparison_pool(row, reference)
    hits_refs = [r for r in refs if r.get('bb') is not None and r.get('rb') is not None
                 and r['bb'] >= 0 and r['rb'] >= 0]
    holds_refs = [r for r in refs if r.get('max_hold') is not None and r['max_hold'] >= 0]
    rate_of = lambda r: (r['bb'] + r['rb']) / r['games']
    rate = rate_of(row) if row.get('bb') is not None and row.get('rb') is not None else None
    s['hits'] = adjusted_rank(rate, hits_refs, rate_of, MAX_HITS_SCORE, row['games'])
    ranked_hold = adjusted_rank(row.get('max_hold'), holds_refs, lambda r: r['max_hold'],
                                MAX_HOLD_SCORE, row['games'])
    # 枚数そのものによる点が上回るときだけ、そちらを採る（下げることはない）。
    # 比較相手がいない場合は従来どおり欠測扱いのまま（中立10点で補完）。
    s['max_hold'] = (None if ranked_hold is None
                     else max(ranked_hold, absolute_hold_score(row.get('max_hold'))))
    s['reference_count'] = len(hits_refs)
    s['reference_days'] = len({r['day'] for r in hits_refs})
    s['hold_reference_count'] = len(holds_refs)
    if s['hits'] is None:
        s['reasons'].append('当たり頻度の比較データ不足：中立30点で補完')
    if s['max_hold'] is None:
        s['reasons'].append('最大持玉の比較データ不足：中立10点で補完')
    graph, measurement = row.get('graph'), row.get('graph_measurement')
    skipped = graph_not_needed(row)
    try:
        # Confirmed manual corrections take precedence over old raw curves.
        metrics = (measurement_metrics(measurement) if measurement else
                   graph_metrics(graph['path'], graph['baseline']) if graph else None)
        if skipped:
            # v12：大当たり0回の台はグラフを取らない。取った場合とほぼ同じ結果
            # （終点はゼロ以下、最高はゼロ付近）になるので、終点・維持とも0点。
            s['positive'], s['retention'] = 0, 0
            s['reasons'].append('大当たり0回でグラフ省略：終点・維持は0点')
        elif metrics:
            s['positive'], s['retention'] = metrics['positive_score'], metrics['retention_score']
            if s['positive'] is None:
                s['reasons'].append('グラフ終点がゼロ線付近：中立点で補完')
        else:
            s['reasons'].append('グラフ未取得：中立10点で補完')
    except (KeyError, ValueError, TypeError):
        s['reasons'].append('グラフ解析保留：中立10点で補完')
    weights = dict(hits=MAX_HITS_SCORE, max_hold=MAX_HOLD_SCORE,
                   positive=MAX_POSITIVE_SCORE, retention=MAX_RETENTION_SCORE)
    observed = sum(s[k] for k in weights if s[k] is not None)
    missing = sum(w for k, w in weights.items() if s[k] is None)
    s['coverage'] = 100 - missing
    s['missing_low'], s['missing_high'] = round_score(observed), round_score(observed + missing)
    s['total'] = round_score(observed + missing / 2)
    hold_days = len({r['day'] for r in holds_refs})
    s['provisional'] = (missing > 0 or row['games'] < SHRINK_GAMES or
                        min(len(hits_refs), len(holds_refs)) < MIN_REFERENCE_ROWS or
                        min(s['reference_days'], hold_days) < SHRINK_DAYS)
    s['status'] = 'provisional' if s['provisional'] else 'reference'
    if s['provisional']:
        s['reasons'].append('少数データ・欠測を含む評価')
    if s['positive'] == 0 and not skipped:
        s['reasons'].append('グラフ終点がゼロ線以下')
    s['reasons'].append(f"比較{s['reference_count']}件/{s['reference_days']}日・持玉比較{s['hold_reference_count']}件・観測{row['games']}G")
    if missing:
        s['reasons'].append(f"評価可能配点{s['coverage']}/100・欠測項目による幅{s['missing_low']:.1f}〜{s['missing_high']:.1f}（信頼区間ではありません）")
    return s


def measurement_preview(row):
    """Return ('image'|'svg'|'reconstructed'|None, content) for showing a saved graph.

    'image' content is a base64 PNG (an actual saved thumbnail, screenshot- or
    browser-sourced). 'svg' is a precise reconstruction from raw SVG path
    points (Selenium collector rows). 'reconstructed' is an approximate line
    built only from the four measured y-positions, for older records saved
    before a preview thumbnail was stored -- callers must label it as such.
    """
    measurement = row.get('graph_measurement')
    graph = row.get('graph')
    if measurement and measurement.get('preview_image'):
        return 'image', measurement['preview_image']
    if graph:
        try:
            m = graph_metrics(graph['path'], graph['baseline'])
            points = m['points']
            w = max(x for x, _ in points)
            y0 = min(y for _, y in points + [(0, m['baseline'])]) - 8
            h = max(y for _, y in points + [(0, m['baseline'])]) - y0 + 8
            p = ' '.join(f'{x},{y}' for x, y in points)
            svg = (f'<svg viewBox="0 {y0} {max(1,w)} {max(1,h)}" preserveAspectRatio="none" '
                   f'aria-label="枚数目盛りなしの相対グラフ">'
                   f'<line x1="0" y1="{m["baseline"]}" x2="{w}" y2="{m["baseline"]}" stroke="#abb3c1"/>'
                   f'<polyline points="{p}" fill="none" stroke="#0d8b74" stroke-width="2" '
                   f'vector-effect="non-scaling-stroke"/></svg>')
            return 'svg', svg
        except (ValueError, TypeError, KeyError):
            return None, None
    if measurement:
        try:
            m = measurement_metrics(measurement)
            baseline = m['baseline']
            peak_y = float(measurement['peak_y'])
            trough_y = float(measurement.get('trough_y', measurement['peak_y']))
            end_y = float(measurement['end_y'])
            y0 = min(baseline, peak_y, trough_y, end_y) - 8
            y1 = max(baseline, peak_y, trough_y, end_y) + 8
            svg = (f'<svg viewBox="0 {y0} 100 {max(1,y1-y0)}" preserveAspectRatio="none" '
                   f'aria-label="4点から復元した概略グラフ（元画像なし）">'
                   f'<line x1="0" y1="{baseline}" x2="100" y2="{baseline}" stroke="#abb3c1"/>'
                   f'<polyline points="0,{baseline} 30,{peak_y} 65,{trough_y} 100,{end_y}" '
                   f'fill="none" stroke="#c77d00" stroke-width="2" stroke-dasharray="4,3" '
                   f'vector-effect="non-scaling-stroke"/></svg>')
            return 'reconstructed', svg
        except (ValueError, TypeError, KeyError):
            return None, None
    return None, None


# メルヘンの推定差枚（グラフの座標と最大持玉から計算する。追加の通信なし）。Android版
# `database_android/lib/meruhen_net.dart` と同じ規則。サイトは差枚の数値を返さないため、
# SVG（高さ400、ゼロ線200.5・上下180px）の縦軸の片側の幅 R 枚を、1,000・2,000・4,000…
# （以降2,000刻み）のうち振れ幅が収まる最小の段階として、最大持玉（谷から山までの最大の
# 上がり幅）と合わせて決める（2026-10-03の調査：保存済み約6,200件の統計、BIG・REG・回転数との
# 照合、実機での高さ変更）。確定差枚ではないので「推定」と表示し、決められない台は None。
MERUHEN_AXIS_STEPS = (1000,) + tuple(range(2000, 40001, 2000))
_MERUHEN_ZERO_Y, _MERUHEN_TOP_Y = 200.5, 20.5
# 幸町の正確なjo_netと照合し、旧推定の誤差100枚以上を除いた6,875組で確認した終点の偏り。
# 9/30〜10/9で決めた半px補正は10/10〜19でも改善。段階を選んだ後の終点だけに適用する。
_MERUHEN_END_PIXEL_CORRECTION = 0.5
# 線が下がった分の合計（その日に使った枚数の目安）の、1回転あたりの上限。グラフの形と最大持玉だけでは
# 段階が決まらない台で、いちばん大きい段階を選ぶと、1回転に3枚しか入らないのに −8,944枚（1,634回転）
# のような値になっていた（2026-10-06、幸町 東京リベンジャーズ517・北斗637）。段階が1つに決まる3,755台
# （300回転以上）では1回転あたり中央値0.95・99.9%が1.71以下・最大1.93枚。これを超える段階は除き、
# 残りが無ければ最も小さい段階を使い、それも物理的な上限（3枚）を超えるときだけ決められない（None）。
MERUHEN_PLAUSIBLE_USE_PER_GAME = 1.75
MERUHEN_MAX_USE_PER_GAME = 3.0


def _rise(values):
    low = rise = 0.0
    for value in values:
        low = min(low, value)
        rise = max(rise, value - low)
    return rise


def meruhen_net_estimate_detail(measurement, max_hold, games=None):
    """(estimated net medals or None, needs_check) for a Meruhen rack.

    needs_check: axis steps that fit the shape and the max holding were ruled out by the medals used
    per game, so the step was chosen again (the graph alone could not decide it). Shown with "※".

    games: the day's total games. With the full curve, it rules out axis steps that would mean
    more medals used per game than racks with a known step ever showed."""
    if not isinstance(measurement, dict) or max_hold is None or not 0 <= max_hold <= 100000:
        return None, False
    try:
        baseline = float(measurement['baseline_y'])
        peak = baseline - float(measurement['peak_y'])
        trough = baseline - float(measurement.get('trough_y', measurement['end_y']))
        end = baseline - float(measurement['end_y'])
    except (KeyError, TypeError, ValueError):
        return None, False
    if abs(baseline - _MERUHEN_ZERO_Y) > 0.01:
        return None, False  # 高さ400以外のSVGは未確認
    half = _MERUHEN_ZERO_Y - _MERUHEN_TOP_Y
    amp = max(abs(peak), abs(trough), abs(end))
    if amp == 0:
        return 0, False

    def fits(index):
        step = MERUHEN_AXIS_STEPS[index]
        previous = MERUHEN_AXIS_STEPS[index - 1] if index else 0
        unit = step / half
        return previous - unit / 2 < amp * unit <= step + unit / 2

    chosen = None
    needs_check = False
    curve = measurement.get('curve')
    if isinstance(curve, list) and len(curve) >= 2:
        values = [baseline - float(point[1]) for point in curve]
        rise = _rise(values)
        if rise <= 0:
            return None, False
        candidates = [step for index, step in enumerate(MERUHEN_AXIS_STEPS)
                      if fits(index) and max_hold / (rise * step / half) >= 0.98]
        drops = sum(max(0.0, a - b) for a, b in zip(values, values[1:]))

        def within(step, per_game):
            return not games or games <= 0 or drops * step / half <= per_game * games

        plausible = [step for step in candidates if within(step, MERUHEN_PLAUSIBLE_USE_PER_GAME)]
        needs_check = len(plausible) != len(candidates)
        if plausible:
            chosen = plausible[-1]
        elif candidates and within(candidates[0], MERUHEN_MAX_USE_PER_GAME):
            chosen = candidates[0]
    else:
        peak_x, trough_x, end_x = (measurement.get(k) for k in ('peak_x', 'trough_x', 'end_x'))
        if peak_x is None or trough_x is None:
            low = max(peak, 0.0)
        else:
            points = sorted([(0.0, 0.0), (float(peak_x), peak), (float(trough_x), trough),
                             (float(end_x) if end_x is not None else float('inf'), end)], key=lambda p: p[0])
            low = _rise(value for _, value in points)
        high = max(peak, 0.0) - min(trough, 0.0)
        feasible = [step for index, step in enumerate(MERUHEN_AXIS_STEPS)
                    if fits(index) and low * step / half * 0.98 - step / half <= max_hold
                    <= high * step / half * 1.3 + step / half]
        if len(feasible) == 1:
            chosen = feasible[0]
    if chosen is None:
        return None, False
    value = (end - _MERUHEN_END_PIXEL_CORRECTION) * chosen / half
    rounded = int(value + 0.5) if value >= 0 else -int(-value + 0.5)  # Dartの round と同じ（0から遠い側）
    return rounded, needs_check


def meruhen_net_estimate(measurement, max_hold, games=None):
    """Estimated net medals for a Meruhen rack, or None when it cannot be determined.

    games: the day's total games. With the full curve, it rules out axis steps that would mean
    more medals used per game than racks with a known step ever showed."""
    return meruhen_net_estimate_detail(measurement, max_hold, games)[0]


def signed_medals(value):
    return f'{value:+,}' if value else '0'


def measurement_preview_html(row):
    """Render measurement_preview() as ready-to-embed HTML with a caption when reconstructed."""
    kind, payload = measurement_preview(row)
    if kind == 'image':
        return f'<img src="data:image/png;base64,{payload}" alt="スランプグラフ" loading="lazy">'
    if kind == 'svg':
        return payload
    if kind == 'reconstructed':
        return payload + '<p class="reconstructed-note">元画像なし。4点の測定値から復元した概略グラフです。</p>'
    return '<p>グラフはまだ取り込まれていません。</p>'


def scored_rows(store, day, machine, location='nagamachiminami'):
    return [dict(**r, score=score(r, store.references(r)), setting_estimate=estimate_setting(r))
            for r in store.rows(day, machine, location)]


# PC版「結果を見る」で開くHTML（機種の結果・この日のまとめ・過去の記録）の見た目。
# 利用者が渡したデザイン（Flip7 Design System：ティール・コーラル・ゴールドのレトロで遊び心のある配色、
# 角丸のカード、色つきの光る影、リボン風の見出し、扇形のカード、1〜3位の金・銀・銅）を参考にした
# （2026-10-04）。PCのページだけに使う。各ページの元のCSSの後ろに置いて上書きするので、
# 数値・文言・並び・機能は変えない。動きは控えめにし、動きを減らす設定の端末では止める。
FLIP7_CSS = """
:root{--f7-teal:#2BA8A2;--f7-teal-l:#3CC4BD;--f7-teal-d:#1E8C86;--f7-teal-bg:#E8F6F5;
  --f7-gold:#FFD23F;--f7-gold-l:#FFE47A;--f7-gold-d:#E6B800;--f7-coral:#EF6C4A;--f7-coral-l:#FF8A6A;
  --f7-coral-d:#D45233;--f7-cream:#FFF8E7;--f7-sky:#5DADE2;--f7-surface:#EFF8F7;--f7-ink:#1E3B3A;
  --f7-mute:#5D7472;--f7-line:#CFE9E6;
  --f7-shadow-card:0 4px 20px rgba(43,168,162,.10);--f7-glow-teal:0 4px 20px rgba(43,168,162,.30);
  --f7-glow-gold:0 4px 20px rgba(255,210,63,.40);--f7-glow-coral:0 4px 20px rgba(239,108,74,.35);
  --f7-bounce:cubic-bezier(.34,1.56,.64,1);
  --frost:var(--f7-surface);--bg:var(--f7-surface);--ice:var(--f7-teal-bg);--ash:var(--f7-mute);--muted:var(--f7-mute);
  --mist:var(--f7-mute);--pebble:var(--f7-teal-bg);--hairline:var(--f7-line);--line:var(--f7-line);
  --blue:var(--f7-teal);--link:var(--f7-teal-d);--ink:var(--f7-ink);--navy:var(--f7-teal-d);--green:var(--f7-teal-d);
  --amber:var(--f7-coral-d);--card:#fff}
body{background:linear-gradient(180deg,var(--f7-teal-bg) 0,var(--f7-surface) 360px);color:var(--f7-ink);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Yu Gothic UI","Meiryo",sans-serif}
a{color:var(--f7-teal-d)}
.f7-brand{display:flex;align-items:center;gap:18px;margin:0 0 6px}
.f7-fan{position:relative;flex:0 0 74px;height:62px}
.f7-fan i{position:absolute;left:24px;top:6px;width:28px;height:42px;border-radius:6px;border:2.5px solid var(--f7-ink);
  transform-origin:50% 115%;box-shadow:0 2px 6px rgba(30,59,58,.18)}
.f7-fan i:nth-child(1){background:var(--f7-coral);transform:rotate(-24deg)}
.f7-fan i:nth-child(2){background:var(--f7-sky);transform:rotate(-12deg)}
.f7-fan i:nth-child(3){background:var(--f7-teal);transform:rotate(0)}
.f7-fan i:nth-child(4){background:var(--f7-gold);transform:rotate(12deg)}
.f7-fan i:nth-child(5){background:var(--f7-cream);transform:rotate(24deg)}
.f7-fan i:nth-child(5)::after{content:"7";position:absolute;inset:0;display:grid;place-items:center;font-weight:800;
  font-size:22px;color:var(--f7-gold-d);text-shadow:-1px -1px 0 var(--f7-ink),1px -1px 0 var(--f7-ink),-1px 1px 0 var(--f7-ink),1px 1px 0 var(--f7-ink)}
.f7-brand h1,.f7-brand h1:first-child{display:inline-block;margin:0;padding:6px 22px 8px;background:var(--f7-cream);
  border:3px solid var(--f7-ink);border-radius:8px;color:var(--f7-teal-d);font-weight:800;letter-spacing:2px;
  transform:rotate(-2deg) skewX(-6deg);box-shadow:4px 4px 0 var(--f7-teal-d)}
h2{font-weight:800;letter-spacing:1px;color:var(--f7-teal-d)}
main>section>h2,.candidate h2{padding-bottom:6px;border-bottom:3px dashed var(--f7-teal-l)}
.sub{color:var(--f7-mute)}
.kpi{background:#fff;border:none;border-left:6px solid var(--f7-teal-l);border-radius:16px;box-shadow:var(--f7-shadow-card)}
.kpi b{color:var(--f7-teal-d);font-weight:800}
.candidate{background:linear-gradient(135deg,var(--f7-cream),#fff 60%);border:none;border-left:6px solid var(--f7-gold);
  border-radius:24px;box-shadow:var(--f7-glow-gold)}
.candidate-tag{background:var(--f7-coral);color:#fff;font-weight:700}
.candidate-list li{border-bottom:2px dashed var(--f7-line)}
.candidate-list b{color:var(--f7-teal-d)}
.table-wrap,.card,.record-group,.empty{border:none;border-radius:24px;box-shadow:var(--f7-shadow-card);background:#fff}
thead tr.group th{background:var(--f7-teal-bg);color:var(--f7-teal-d);font-weight:800}
thead tr.labels th,.record-group th{background:var(--f7-teal-d);color:#fff;font-weight:700}
tbody td{border-bottom:1px solid #E3F1EF}
tbody tr:hover,tr.pick:hover{background:#FFF6D6}
td.rack{color:var(--f7-teal-d);font-weight:800}
/* 機種の結果：「補完・注意の理由」が細い列に押し込まれ、1台の行が300px以上の高さになっていた。幅を持たせる。 */
td.reasons{min-width:320px;line-height:1.5}
.tag{background:var(--f7-teal-bg);color:var(--f7-teal-d);font-weight:600}
.badge{border-radius:999px;font-weight:800;transition:transform .2s var(--f7-bounce)}
.badge.high{background:linear-gradient(180deg,var(--f7-gold-l),var(--f7-gold) 55%,var(--f7-gold-d));color:var(--f7-ink);
  border:none;box-shadow:var(--f7-glow-gold)}
.badge.mid{background:var(--f7-teal-bg);color:var(--f7-teal-d);border:2px solid var(--f7-teal-l)}
.badge.low{background:var(--f7-cream);color:var(--f7-mute);border:1px solid #EADFC2}
.badge.reference{background:var(--f7-teal-bg);color:var(--f7-teal-d)}
.badge.provisional{background:var(--f7-gold-l);color:#6B5300}
.badge.pending{background:var(--f7-cream);color:var(--f7-mute)}
tr:hover .badge{transform:scale(1.06)}
.record-group{border-left:6px solid var(--f7-teal-l);margin:14px 0;transition:box-shadow .2s ease}
.record-group:has(details[open]){border-left-color:var(--f7-gold);box-shadow:var(--f7-glow-gold)}
summary:before{color:var(--f7-coral)}
.store{color:var(--f7-teal-d)}
.event{background:var(--f7-coral);color:#fff}
select,input{background:var(--f7-cream);border:2px solid var(--f7-line);border-radius:16px;color:var(--f7-ink)}
select:focus,input:focus{outline:none;border-color:var(--f7-teal);box-shadow:0 0 0 4px rgba(43,168,162,.15)}
.rack-btn{color:var(--f7-teal-d)}
.graph-btn{border-radius:16px;transition:transform .2s var(--f7-bounce),box-shadow .2s ease}
.graph-btn:hover{transform:translateY(-2px);box-shadow:var(--f7-glow-teal)}
.graph-btn svg,.graph-btn img{border-radius:16px;border:2px solid var(--f7-line)}
.miss{background:var(--f7-cream);border:none;border-left:6px solid var(--f7-coral);border-radius:24px;box-shadow:var(--f7-shadow-card)}
.miss summary{color:var(--f7-coral-d)}
.reconstructed-note{color:var(--f7-coral-d)}
.modal{background:rgba(30,59,58,.55)}
.modal-card{border:3px solid var(--f7-ink);border-radius:32px;box-shadow:0 8px 32px rgba(30,59,58,.25)}
.modal-card h3{color:var(--f7-teal-d);font-weight:800;padding-bottom:6px;border-bottom:3px dashed var(--f7-teal-l)}
.modal-close{width:34px;height:34px;border-radius:999px;background:var(--f7-coral);color:#fff;line-height:1;
  box-shadow:var(--f7-glow-coral);transition:transform .2s var(--f7-bounce)}
.modal-close:hover{transform:scale(1.1)}
.modal-card .kpi{box-shadow:none;border-left-width:4px;background:var(--f7-teal-bg)}
div.strip{border:2px solid var(--f7-line);border-radius:16px}
footer{color:var(--f7-mute)}
/* この日のまとめ：上位の1〜3位を金・銀・銅に */
.card tr.pick td.rank{text-align:center}
.card tr.pick td.rank{font-weight:800}
.card tr.pick:nth-child(-n+3) td.rank{color:transparent;position:relative}
.card tr.pick:nth-child(-n+3) td.rank::before{content:"";position:absolute;left:50%;top:50%;width:30px;height:30px;
  margin:-15px 0 0 -15px;border-radius:999px;display:grid;place-items:center;font-size:15px;color:var(--f7-ink)}
.card tr.pick:nth-child(1) td.rank::before{content:"1";background:linear-gradient(180deg,var(--f7-gold-l),var(--f7-gold-d));box-shadow:var(--f7-glow-gold)}
.card tr.pick:nth-child(2) td.rank::before{content:"2";background:linear-gradient(180deg,#F1F4F6,#AEB8BF);box-shadow:0 4px 14px rgba(120,135,145,.35)}
.card tr.pick:nth-child(3) td.rank::before{content:"3";background:linear-gradient(180deg,var(--f7-coral-l),var(--f7-coral-d));color:#fff;box-shadow:var(--f7-glow-coral)}
.card tr.pick:nth-child(1) td.rank::after{content:"\\1F451";position:absolute;left:50%;top:50%;margin:-27px 0 0 4px;font-size:14px;
  line-height:1;color:#000;animation:f7-crown 1.5s infinite}
.card tr.pick:nth-child(1){background:linear-gradient(90deg,#FFF6D6,#fff 70%)}
.card tr.pick:nth-child(1) .badge.high{animation:f7-glow 2s infinite}
@keyframes f7-crown{0%,100%{transform:translateY(0) rotate(0)}25%{transform:translateY(-3px) rotate(-8deg)}
  50%{transform:translateY(0) rotate(0)}75%{transform:translateY(-3px) rotate(8deg)}}
@keyframes f7-glow{0%,100%{box-shadow:0 4px 12px rgba(255,210,63,.30);transform:scale(1)}50%{box-shadow:0 4px 24px rgba(255,210,63,.70);transform:scale(1.03)}}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
@media(max-width:760px){.f7-fan{display:none}}
"""
FLIP7_FAN = '<span class="f7-fan" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></span>'


def report(store, day, machine, folder, location='nagamachiminami'):
    if location not in STORE_NAMES:
        raise ValueError('対象外の店舗です。')
    results = scored_rows(store, day, machine, location)
    variety = 0 < len(results) <= variety_max_racks(location)
    candidate_info = (variety_next_day_candidates(store, day, location) if variety else
                      provisional_next_day_candidates(store, day, machine, location))
    candidate_marks = {int(c['row']['rack']): '★' if variety or c['focus'] else '☆'
                       for c in candidate_info['candidates']}
    event_rows = store.date_events(location, day)
    event_label = f' ｜ {html.escape(event_rows[0]["name"])}' if event_rows else ''
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    json_path = folder / f'database-{location}-{day}-{stamp}.json'
    json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    def fmt(x):
        return '—' if x is None else f'{x:.1f}'
    def tier(total):
        # One accent color used deliberately (Apple style guide): a strong
        # result gets the filled blue pill, a middling one the outlined
        # version, everything else stays neutral gray -- never more than
        # one chromatic color on the page.
        if total is None:
            return 'low'
        return 'high' if total >= 80 else 'mid' if total >= 60 else 'low'
    body = []
    for r in results:
        s = r['score']
        measurement = r.get('graph_measurement')
        svg = measurement_preview_html(r)
        total = s['total']
        max_hold_display = '—' if r.get('max_hold') is None else str(r['max_hold'])
        net, net_check, _from_site = rack_net(r)
        net_display = '—' if net is None or implausible_numbers(r) else signed_medals(net) + ('※' if net_check else '')
        setting_display = r.get('confirmed_setting') or '—'
        estimate = r['setting_estimate']
        estimate_display = candidate_label(estimate)
        cells = [str(r['rack']) + rack_mark(r) + (f" {candidate_marks[int(r['rack'])]}" if int(r['rack']) in candidate_marks else ''), str(r['games']), str(r['bb']), str(r['rb']), max_hold_display,
                 net_display, setting_display, estimate_display]
        cells += [fmt(s[k]) for k in ('max_hold','hits','positive','retention')]
        total_text = fmt(total)
        comparison = f'{s["reference_count"]}件/{s["reference_days"]}日・持玉{s["hold_reference_count"]}件'
        image_name = (measurement or {}).get('source_image') or r.get('source_image')
        source_url = (measurement or {}).get('source_url') or r.get('source_url')
        if image_name:
            safe_name = Path(str(image_name)).name
            evidence = f'<a class="evidence" href="../data/screenshots/{html.escape(safe_name, quote=True)}">元画像</a>'
        elif source_url:
            evidence = f'<a class="evidence" href="{html.escape(str(source_url), quote=True)}">出典ページ</a>'
        else:
            evidence = '—'
        reason_tags = ''.join(f'<span class="tag">{html.escape(reason)}</span>' for reason in s['reasons']) or '—'
        graph_html = html.escape(svg, quote=True)
        source_link = (f' <a href="{html.escape(estimate["source"], quote=True)}">出典</a>'
                       if estimate else '')
        data_cells = (f'<td class="rack">{html.escape(cells[0])}</td>'
                      + ''.join(f'<td>{html.escape(c)}</td>' for c in cells[1:7])
                      + f'<td>{html.escape(cells[7])}{source_link}</td>'
                      + ''.join(f'<td>{html.escape(c)}</td>' for c in cells[8:]))
        body.append(
            '<tr>' + data_cells
            + f'<td><span class="badge {tier(total)}">{html.escape(total_text)}</span></td>'
            + f'<td>{html.escape(comparison)}</td>'
            + f'<td><button type="button" class="graph-btn" data-title="{html.escape(str(r["rack"]))}番台" '
              f'data-graph="{graph_html}" onclick="showGraph(this)">{svg}</button></td>'
            + f'<td>{evidence}</td>'
            + f'<td class="reasons">{reason_tags}</td></tr>')
    header_groups = [(1, ''), (7, '表示データ'), (4, '得点内訳'), (1, '総合'), (4, '参考')]
    header = ['台番号','表示G','BB','RB','最大持玉','推定差枚','設定情報（手入力）','設定候補（BB/RB）','持玉 /20','当り /60','終点 /10','維持 /10',
              '合計 /100','比較（件数/日数）','相対グラフ','確認画像','状態・注意']
    done = sum(r['score']['total'] is not None for r in results)
    totals = [r['score']['total'] for r in results if r['score']['total'] is not None]
    average = round(sum(totals) / len(totals), 1) if totals else None
    best = max(totals) if totals else None
    source = results[0].get('source_url') if results else None
    source_html = f'｜ <a href="{html.escape(source, quote=True)}">画面の出典</a>' if source else ''
    # 1〜3台の機種は、機種ごとではなく店の「バラエティ」にまとめて判定する。
    if variety:
        candidate_lead = (f'<p class="candidate-lead">この機種は{variety_range(location)}の機種なので、店の「バラエティ」に'
                          f'まとめて選びます。{html.escape(SHORT_STORE_NAMES.get(location, location))}の狙い方：'
                          f'{html.escape(variety_rule_text(location))}。'
                          '明日どの台から見るかの参考用で、今日の合計点には影響しません。</p>')
    elif normal_model_applies(location, machine, day):
        import normal_next_day_model
        candidate_lead = ('<p class="candidate-lead">この機種で、翌日の当たりの軽さを予想の式で見積もった上位の台です。'
                          '明日どの台から見るかの参考用で、今日の合計点には影響しません。</p>'
                          f'<p class="candidate-lead">{html.escape(normal_next_day_model.NOTE)}</p>')
    else:
        candidate_lead = ('<p class="candidate-lead">この機種で、過去に当たりが周りの台より軽かった台です。'
                          '明日どの台から見るかの参考用で、今日の合計点には影響しません。</p>')
    candidate_lead += normal_day_context_html(location, day, [machine])
    if candidate_info['count']:
        # 素の「63/100」では50が中立であることも上下どちらが良いのかも読めないので、
        # 差分（平均より+13。バラエティは普段より+13）で出す。
        def variety_hit(item):
            if item['confidence'] == '比較なし':
                return '当たりは普段と比べる記録が足りない'
            delta = item['index'] - 50
            return f'当たり 普段より {"+" if delta >= 0 else "-"}{abs(delta):.0f}（比べた記録{item["days"]}件）'
        if variety:
            # 「501番台　機種名（バラエティ）」の形で、前日の回転数と終わり方を添える。
            candidate_rows = ''.join(
                f'<li><b>{int(item["row"]["rack"])}番台</b>'
                f'<span>{html.escape(item["row"]["machine"])}（{VARIETY_GROUP_NAME}）'
                f'{"・この機種" if item["row"]["machine"] == machine else ""}</span>'
                f'<span class="candidate-delta">前日 {item["row"]["games"]:,}G・{VARIETY_STATE_LABELS[item["state"]]}</span>'
                f'<span class="candidate-days">{html.escape(variety_hit(item))}</span></li>'
                for item in candidate_info['candidates'])
            candidate_note = (f'バラエティ{candidate_info["total"]}台のうち、よく回って終わり方が分かる'
                              f'{candidate_info["eligible"]}台から{candidate_info["count"]}台。'
                              '機種ごとに当たりの重さが違うので、別の機種の台どうしは比べていません。'
                              '店ごとの狙い方は7日分の傾向に合わせたもので、外れる可能性も高いです。')
        else:
            candidate_rows = ''.join(
                f'<li><b>{"★ 注目" if item["focus"] else "☆ 長期傾向"} {int(item["row"]["rack"])}番台</b>'
                f'<span class="candidate-delta">当たりの軽さ {signed_index(item["index"])}</span>'
                f'<span class="candidate-days">過去{item["days"]}日分・{html.escape(next_day_reason(item))}</span></li>'
                for item in candidate_info['candidates'])
            candidate_note = (f'傾向を出せた{candidate_info["total"]}台中{candidate_info["eligible"]}台から、'
                              f'上位{candidate_info["count"]}台。「平均より」は、同じ日・同じ機種で回転数が近い台と'
                              '比べた当たり頻度の差です。★注目は当日情報あり・安定性基準を満たす・'
                              '当日88点未満（未採点は除外しない）の台のみです。'
                              '88点以上は☆長期傾向には残ります。'
                              + ('' if any(item['focus'] for item in candidate_info['candidates'])
                                 else '翌日向けの注目なし（条件を満たす台なし）。'))
        candidate_html = (f'<section class="candidate"><h2>翌日候補（仮）<span class="candidate-tag">試験中</span></h2>'
                          f'{candidate_lead}<ul class="candidate-list">{candidate_rows}</ul>'
                          f'<p class="candidate-note">{candidate_note}<br>'
                          '翌日の設定・勝率・期待収支を示すものではありません（効果は検証中）。</p></section>')
    elif variety:
        candidate_html = (f'<section class="candidate"><h2>翌日候補（仮）<span class="candidate-tag">試験中</span></h2>'
                          f'{candidate_lead}'
                          f'<p class="candidate-note">この日のバラエティ{candidate_info["total"]}台に、'
                          f'{VARIETY_BUSY_GAMES}G以上回って終わり方が分かる台がありません。</p></section>')
    else:
        candidate_html = (f'<section class="candidate"><h2>翌日候補（仮）<span class="candidate-tag">試験中</span></h2>'
                          f'{candidate_lead}'
                          f'<p class="candidate-note">まだ判定できません。過去の実績から傾向を出せた台が'
                          f'{candidate_info["total"]}台中{candidate_info["eligible"]}台です（4台以上で表示）。'
                          '同じ台・同じ機種のデータが3日分たまると傾向を出せます。</p></section>')
    text = f'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>database 結果</title>
<style>
:root{{--carbon:#1d1d1f;--frost:#f5f5f7;--ice:#f4f8fb;--ash:#707070;--mist:#858585;
  --pebble:#e2e2e5;--hairline:#d2d2d7;--blue:#0071e3;--link:#0066cc}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--frost);color:var(--carbon);
  font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text",Inter,system-ui,"Segoe UI","Yu Gothic UI",sans-serif;
  font-size:14px}}
main{{max-width:1320px;margin:auto;padding:40px 24px}}
header h1{{margin:0;font-size:28px;font-weight:600;letter-spacing:0.2px}}
.sub{{color:var(--ash);margin-top:12px;line-height:1.6;font-size:14px}}
.sub a{{color:var(--link);text-decoration:none}}
.sub a:hover{{text-decoration:underline}}
.kpis{{display:grid;grid-template-columns:repeat(4,minmax(120px,1fr));gap:12px;margin:32px 0}}
.kpi{{background:#fff;border:1px solid var(--hairline);border-radius:8px;padding:20px}}
.kpi b{{display:block;font-size:28px;font-weight:600;letter-spacing:0.2px}}
.kpi span{{color:var(--ash);font-size:12px}}
.candidate{{background:#fff;border:1px solid var(--hairline);border-radius:8px;padding:18px 20px;margin:0 0 20px}}
.candidate h2{{font-size:17px;margin:0 0 8px;display:flex;align-items:center;gap:8px}}.candidate p{{margin:5px 0}}.candidate-note{{color:var(--ash);font-size:12px;line-height:1.6}}
.candidate-tag{{background:var(--pebble);color:var(--ash);border-radius:980px;padding:3px 10px;font-size:11px;font-weight:400}}
.candidate-lead{{color:var(--ash);font-size:13px;line-height:1.6}}
.candidate-list{{list-style:none;margin:12px 0;padding:0}}
.candidate-list li{{display:flex;align-items:baseline;gap:14px;padding:8px 0;border-bottom:1px solid #edeef0}}
.candidate-list li:last-child{{border-bottom:none}}
.candidate-list b{{min-width:84px;font-size:15px}}
.candidate-delta{{font-variant-numeric:tabular-nums}}
.candidate-days{{color:var(--ash);font-size:12px}}
.table-wrap{{background:#fff;border:1px solid var(--hairline);border-radius:8px;overflow:auto}}
table{{width:100%;border-collapse:collapse;min-width:1180px}}
thead tr.group th{{background:var(--ice);color:var(--ash);font-size:11px;font-weight:600;padding:8px 10px;
  border-bottom:1px solid var(--hairline);text-align:center;text-transform:uppercase;letter-spacing:0.4px}}
thead tr.labels th{{background:#fff;color:var(--carbon);font-size:12px;font-weight:600;padding:12px 10px;
  border-bottom:1px solid var(--hairline);white-space:nowrap}}
tbody td{{padding:12px 10px;border-bottom:1px solid #edeef0;text-align:right;white-space:nowrap;
  font-size:14px;font-variant-numeric:tabular-nums}}
tbody tr:hover{{background:var(--ice)}}
td.rack{{font-weight:600;font-size:15px}}
td.reasons,th:last-child{{text-align:left;white-space:normal}}
.tag{{display:inline-block;background:var(--pebble);color:var(--ash);border-radius:980px;padding:3px 10px;
  font-size:11px;margin:1px 4px 1px 0}}
.badge{{display:inline-block;border-radius:980px;padding:5px 14px;font-weight:600;font-size:13px}}
.badge.high{{background:var(--blue);color:#fff}}
.badge.mid{{background:transparent;color:var(--link);border:1px solid var(--link)}}
.badge.low{{background:var(--pebble);color:var(--ash)}}
.graph-btn{{border:none;background:none;padding:0;cursor:pointer;line-height:0;border-radius:8px;overflow:hidden}}
.graph-btn svg,.graph-btn img{{width:190px;height:66px;object-fit:contain;border-radius:8px;
  background:var(--ice);border:1px solid var(--hairline)}}
a.evidence{{color:var(--link);font-size:12px;text-decoration:none}}
a.evidence:hover{{text-decoration:underline}}
.reconstructed-note{{font-size:11px;color:var(--ash);margin:2px 0 0}}
.modal{{position:fixed;inset:0;background:rgba(29,29,31,.5);display:flex;align-items:center;
  justify-content:center;padding:20px;z-index:50}}
.modal[hidden]{{display:none}}
.modal-card{{background:#fff;border-radius:8px;padding:24px;max-width:460px;width:100%;max-height:86vh;
  overflow:auto;position:relative;border:1px solid var(--hairline)}}
.modal-card h3{{margin:0 0 12px;font-size:17px;font-weight:600}}
.modal-card svg,.modal-card img{{width:100%;height:auto;max-height:320px;object-fit:contain;
  background:var(--carbon);border-radius:8px}}
.modal-close{{position:absolute;top:14px;right:16px;border:none;background:none;font-size:20px;
  cursor:pointer;color:var(--ash)}}
@media(max-width:760px){{main{{padding:24px 16px}}.kpis{{grid-template-columns:1fr 1fr}}}}
{FLIP7_CSS}</style></head><body><main>
<header><div class="f7-brand">{FLIP7_FAN}<h1>database 結果</h1></div><div class="sub">{html.escape(STORE_NAMES[location])} ｜ {html.escape(machine)} ｜ {day}{event_label} ｜ 1000円46枚 {source_html}<br>
独自の結果評価です。出率・差枚・設定確率を表す点数ではありません。<br>
比較：同店・同機種の過去30日、回転数が概ね半分〜2倍（最低500G）の台。当日・未来は比較に使いません。比較件数・日数・回転数が少ないほど中間へ補正します。<br>
当たり頻度60点、最大持玉20点、終点10点、維持10点。回転数は加点しません。欠けた項目は中立点で補完し、欠測幅を示します。<br>
「推定差枚」はグラフの形と最大持玉から縦軸の目盛りを割り出した計算で、確定値ではありません（誤差はおよそグラフ1目盛り分。決められない台は「—」。「※」はグラフだけでは目盛りを決めきれず、回転数から選び直した要確認の値）。<br>
「設定候補」は公開BB/RB確率との条件付き比較です。各設定を同じ重みと仮定したモデル内中央80%候補範囲で、確定設定・実際の設定確率・翌日の予測ではありません。<br>計算版：{VERSION}</div></header>
<section class="kpis">
<div class="kpi"><b>{len(results)}</b><span>台数</span></div>
<div class="kpi"><b>{done}</b><span>実績点表示</span></div>
<div class="kpi"><b>{fmt(average)}</b><span>平均</span></div>
<div class="kpi"><b>{fmt(best)}</b><span>最高</span></div>
</section>
{candidate_html}
<div class="table-wrap"><table><thead>
<tr class="group">{''.join(f'<th colspan="{n}">{html.escape(label)}</th>' for n, label in header_groups)}</tr>
<tr class="labels">{''.join('<th>'+html.escape(c)+'</th>' for c in header)}</tr>
</thead><tbody>{''.join(body)}</tbody></table></div>
</main>
<div id="graph-modal" class="modal" hidden><div class="modal-card"><button type="button" class="modal-close" onclick="closeGraph()" aria-label="閉じる">×</button><h3 id="graph-modal-title"></h3><div id="graph-modal-body"></div></div></div>
<script>
function showGraph(btn){{document.getElementById('graph-modal-title').textContent=btn.dataset.title;document.getElementById('graph-modal-body').innerHTML=btn.dataset.graph;document.getElementById('graph-modal').hidden=false}}
function closeGraph(){{document.getElementById('graph-modal').hidden=true}}
document.getElementById('graph-modal').addEventListener('click',e=>{{if(e.target.id==='graph-modal')closeGraph()}});
</script></body></html>'''
    output = json_path.with_suffix('.html')
    output.write_text(text, encoding='utf-8')
    return output, results


class HistoryReportCancelled(Exception):
    """The PC app is closing; the history page is rebuilt when it is next opened."""


def history_report(store, folder, days=HISTORY_REPORT_DAYS, cancelled=None):
    """Build one offline page that groups saved records by date and machine.

    Only the most recent ``days`` dates are drawn. Each rack carries its graph
    image inside the page, so drawing every date made the file grow by roughly
    0.4MB per day of capture and the browser slower to open it every day.
    Nothing is deleted -- older dates stay in the database and are shown by
    the result and summary pages.

    ``cancelled`` is checked between machines. When it returns true, nothing is
    written and ``HistoryReportCancelled`` is raised (PC終了時、2026-10-17：
    実データ規模で10秒以上かかり、×を押してから閉じるまで待たせていた)。
    """
    def stop_if_cancelled():
        if cancelled is not None and cancelled():
            raise HistoryReportCancelled()

    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    stop_if_cancelled()
    all_rows = store.rows()
    all_dates = sorted({r['day'] for r in all_rows}, reverse=True)
    dates = all_dates[:days]
    hidden_dates = all_dates[days:]
    stored = [r for r in all_rows if r['day'] in set(dates)]
    keys = sorted({(r['day'], r['store'], r['machine']) for r in stored}, reverse=True)
    locations = sorted({location for _day, location, _machine in keys})
    machines = sorted({machine for _day, _location, machine in keys})
    groups = []
    for index, (day, location, machine) in enumerate(keys):
        stop_if_cancelled()
        day_events = store.date_events(location, day)
        event_html = (f'<span class="event">{html.escape(day_events[0]["name"])}</span>'
                      if day_events else '')
        rows = scored_rows(store, day, machine, location)
        totals = [(r['rack'], r['score']['total']) for r in rows if r['score']['total'] is not None]
        average = round(sum(total for _rack, total in totals) / len(totals), 1) if totals else None
        best = max(totals, key=lambda item: item[1]) if totals else None
        official = sum(r['score']['status'] == 'reference' for r in rows)
        provisional = sum(r['score']['status'] == 'provisional' for r in rows)
        pending = len(rows) - official - provisional
        year, month, day_number = map(int, day.split('-'))
        summary_bits = [f'{len(rows)}台', f'合計表示 {len(totals)}台']
        if average is not None:
            summary_bits.append(f'平均 {average:.1f}点')
        if best:
            summary_bits.append(f'最高 {best[0]}番台 {best[1]:.1f}点')
        row_html = []
        for r in rows:
            s = r['score']
            status = '保留' if s['status'] == 'pending' else '参考'
            badge = 'pending' if s['status'] == 'pending' else 'reference'
            total = '—' if s['total'] is None else f'{s["total"]:.1f}'
            comparison = f'{s["reference_count"]}件/{s["reference_days"]}日・持玉{s["hold_reference_count"]}件'
            measurement = r.get('graph_measurement') or {}
            image_name = measurement.get('source_image') or r.get('source_image')
            evidence = '—'
            if image_name:
                safe_name = Path(str(image_name)).name
                evidence = f'<a href="../data/screenshots/{html.escape(safe_name, quote=True)}">元画像</a>'
            reason_text = '・'.join(s['reasons']) or '—'
            graph_html = html.escape(measurement_preview_html(r), quote=True)
            rack_cell = (f'<button type="button" class="rack-btn" data-rack="{int(r["rack"])}" '
                        f'data-graph="{graph_html}" onclick="showGraph(this)">{int(r["rack"])}{rack_mark(r)}</button>')
            setting = r.get('confirmed_setting') or '—'
            estimate = r['setting_estimate']
            estimate_text = candidate_label(estimate)
            row_html.append(
                '<tr>'
                f'<td>{rack_cell}</td><td>{int(r.get("games") or 0):,}</td>'
                f'<td>{html.escape(setting)}</td><td>{html.escape(estimate_text)}</td>'
                f'<td>{html.escape(total)}</td><td><span class="badge {badge}">{status}</span></td>'
                f'<td>{html.escape(comparison)}</td><td>{evidence}</td><td>{html.escape(reason_text)}</td>'
                '</tr>')
        open_attribute = ' open' if index == 0 else ''
        groups.append(
            f'<article class="record-group" data-date="{day}" data-store="{location}" data-machine="{html.escape(machine, quote=True)}" '
            f'data-count="{len(rows)}" data-scored="{len(totals)}">'
            f'<details{open_attribute}><summary><span class="date">{year}年{month}月{day_number}日{event_html}</span>'
            f'<span class="store">{html.escape(STORE_NAMES[location])}</span>'
            f'<span class="machine">{html.escape(machine)}</span>'
            f'<span class="summary">{" ｜ ".join(summary_bits)}</span></summary>'
            f'<div class="status-row"><span>参考 {official + provisional}台</span><span>保留 {pending}台</span></div>'
            '<div class="table-wrap"><table><thead><tr><th>台番号</th><th>表示G</th><th>設定情報（手入力）</th><th>設定候補（BB/RB）</th><th>合計 /100</th>'
            '<th>状態</th><th>比較（件数/日数）</th><th>確認画像</th><th>補完・注意の理由</th></tr></thead><tbody>'
            + ''.join(row_html) + '</tbody></table></div></details></article>')

    store_options = ''.join(f'<option value="{location}">{html.escape(STORE_NAMES[location])}</option>'
                            for location in STORE_NAMES)
    machine_options = ''.join(f'<option value="{html.escape(m, quote=True)}">{html.escape(m)}</option>' for m in machines)
    empty = '<div class="empty">保存済みのデータはありません。</div>' if not groups else ''
    scope = (f'直近{len(dates)}日分（{dates[-1]} 〜 {dates[0]}）を表示しています。'
             if dates else '')
    if hidden_dates:
        scope += (f'これより前の{len(hidden_dates)}日分（{hidden_dates[-1]} 〜 {hidden_dates[0]}）も'
                  '保存されています。アプリの「結果を見る」で日付を選ぶか、「この日のまとめ」から確認してください。')
    generated = datetime.now().astimezone().strftime('%Y-%m-%d %H:%M')
    text = f'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>database 過去の記録</title>
<style>
:root{{--bg:#f3f6fa;--card:#fff;--ink:#203044;--muted:#687789;--line:#dce3eb;--navy:#203044;--green:#0d8b74;--amber:#a66700}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px system-ui,"Yu Gothic UI",sans-serif}}main{{max-width:1180px;margin:auto;padding:28px}}
header{{display:flex;justify-content:space-between;gap:20px;align-items:end;flex-wrap:wrap;margin-bottom:18px}}h1{{margin:0;font-size:28px}}.sub{{color:var(--muted);margin-top:5px}}
.filters{{display:flex;gap:10px;flex-wrap:wrap}}label{{display:grid;gap:4px;font-size:12px;color:var(--muted)}}select,input{{min-width:190px;padding:9px 11px;border:1px solid var(--line);border-radius:8px;background:#fff;color:var(--ink)}}
.kpis{{display:grid;grid-template-columns:repeat(4,minmax(140px,1fr));gap:12px;margin:18px 0}}.kpi{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:15px 18px}}.kpi b{{display:block;font-size:25px}}.kpi span{{color:var(--muted);font-size:12px}}
.record-group{{background:var(--card);border:1px solid var(--line);border-radius:10px;margin:12px 0;overflow:hidden}}summary{{cursor:pointer;display:grid;grid-template-columns:24px 135px 230px minmax(220px,1fr) auto;gap:14px;align-items:center;padding:17px 20px;list-style:none}}summary::-webkit-details-marker{{display:none}}summary:before{{content:"＋";font-weight:bold;color:var(--green)}}details[open] summary:before{{content:"－"}}.date{{font-weight:700}}.event{{display:inline-block;margin-left:5px;padding:2px 7px;border-radius:99px;background:#eaf2fb;color:#075db5;font-size:11px;font-weight:600}}.store{{color:var(--green);font-weight:700}}.machine{{font-weight:650}}.summary{{color:var(--muted);font-size:13px;text-align:right}}
.status-row{{display:flex;gap:18px;padding:0 20px 12px;color:var(--muted);font-size:13px}}.table-wrap{{overflow:auto;border-top:1px solid var(--line)}}table{{width:100%;border-collapse:collapse}}th,td{{padding:11px 15px;border-bottom:1px solid #edf0f4;text-align:right;white-space:nowrap}}th{{background:var(--navy);color:white;font-size:12px}}td:last-child,th:last-child{{text-align:left}}.badge{{display:inline-block;border-radius:99px;padding:3px 9px;font-size:12px;font-weight:700}}.badge.reference{{background:#d4efe5;color:#086451}}.badge.provisional{{background:#fff0be;color:#775000}}.badge.pending{{background:#e9edf2;color:#596675}}a{{color:#075db5}}.empty{{background:white;padding:30px;border-radius:10px;color:var(--muted)}}footer{{color:var(--muted);font-size:12px;margin-top:22px}}
.rack-btn{{border:none;background:none;color:#075db5;font:inherit;font-weight:700;cursor:pointer;padding:0;text-decoration:underline}}
.modal{{position:fixed;inset:0;background:rgba(20,28,40,.55);display:flex;align-items:center;justify-content:center;padding:20px;z-index:50}}
.modal[hidden]{{display:none}}.modal-card{{background:#fff;border-radius:12px;padding:20px;max-width:460px;width:100%;max-height:86vh;overflow:auto;position:relative}}
.modal-card h3{{margin:0 0 12px}}.modal-card svg,.modal-card img{{width:100%;height:auto;max-height:280px;object-fit:contain;background:#0c0c10;border-radius:6px}}
.modal-close{{position:absolute;top:10px;right:14px;border:none;background:none;font-size:20px;cursor:pointer;color:var(--muted)}}
.reconstructed-note{{font-size:12px;color:var(--amber);margin:8px 0 0}}
@media(max-width:760px){{main{{padding:16px}}.kpis{{grid-template-columns:1fr}}summary{{grid-template-columns:1fr;gap:5px}}summary:before{{display:none}}.summary{{text-align:left}}}}
{FLIP7_CSS}</style></head><body><main><header><div><div class="f7-brand">{FLIP7_FAN}<h1>database 過去の記録</h1></div><div class="sub">店舗と日付ごとに保存した機種・採点結果を確認できます。台番号を押すとスランプグラフを見られます。<br>{html.escape(scope)}</div></div><div class="filters"><label>店舗<select id="store-filter"><option value="">すべての店舗</option>{store_options}</select></label><label>日付<input id="date-filter" type="date"></label><label>機種<select id="machine-filter"><option value="">すべての機種</option>{machine_options}</select></label></div></header>
<section class="kpis"><div class="kpi"><b id="kpi-stores">{len(locations)}</b><span>店舗</span></div><div class="kpi"><b id="kpi-days">{len(dates)}</b><span>日分</span></div><div class="kpi"><b id="kpi-machines">{len(machines)}</b><span>機種</span></div><div class="kpi"><b id="kpi-rows">{len(stored)}</b><span>台データ</span></div></section>
<section id="records">{''.join(groups)}{empty}</section><footer>更新：{generated} ｜ 計算版：{VERSION}</footer></main>
<div id="graph-modal" class="modal" hidden><div class="modal-card"><button type="button" class="modal-close" onclick="closeGraph()" aria-label="閉じる">×</button><h3 id="graph-modal-title"></h3><div id="graph-modal-body"></div></div></div>
<script>
const groups=[...document.querySelectorAll('.record-group')];
function applyFilters(){{const s=document.getElementById('store-filter').value;const d=document.getElementById('date-filter').value;const m=document.getElementById('machine-filter').value;const visible=groups.filter(g=>{{const show=(!s||g.dataset.store===s)&&(!d||g.dataset.date===d)&&(!m||g.dataset.machine===m);g.hidden=!show;return show}});document.getElementById('kpi-stores').textContent=new Set(visible.map(g=>g.dataset.store)).size;document.getElementById('kpi-days').textContent=new Set(visible.map(g=>g.dataset.date)).size;document.getElementById('kpi-machines').textContent=new Set(visible.map(g=>g.dataset.machine)).size;document.getElementById('kpi-rows').textContent=visible.reduce((n,g)=>n+Number(g.dataset.count),0)}}
document.getElementById('store-filter').addEventListener('change',applyFilters);document.getElementById('date-filter').addEventListener('change',applyFilters);document.getElementById('machine-filter').addEventListener('change',applyFilters);
function showGraph(btn){{document.getElementById('graph-modal-title').textContent=btn.dataset.rack+'番台';document.getElementById('graph-modal-body').innerHTML=btn.dataset.graph;document.getElementById('graph-modal').hidden=false}}
function closeGraph(){{document.getElementById('graph-modal').hidden=true}}
document.getElementById('graph-modal').addEventListener('click',e=>{{if(e.target.id==='graph-modal')closeGraph()}});
</script></body></html>'''
    stop_if_cancelled()
    output = folder / 'database-history.html'
    output.write_text(text, encoding='utf-8')
    return output


def missing_graphs(store, day, location):
    """Racks whose list row is saved but whose individual graph is not.

    Returns ``[(machine, [racks...], no_link_count), ...]`` sorted by machine.
    ``no_link_count`` is how many of them lack the site's own per-rack link
    (``detail_url``): those cannot be reached by "次の未取り込み台へ" until the
    machine's list page is imported again.
    """
    found = []
    for machine in store.machines_for(location, day):
        # ジャグラーオンラインの数字で作った台は、サイトから取り直せないのでここに出さない（まとめで別に数える）。
        rows = [r for r in store.rows(day, machine, location)
                if not graph_done(r) and not juggler_online_made(r)]
        if rows:
            racks = sorted(int(r['rack']) for r in rows)
            found.append((machine, racks, sum(1 for r in rows if not r.get('detail_url'))))
    return found


SUMMARY_REPORT_CSS = r""":root{--carbon:#1d1d1f;--frost:#f5f5f7;--ash:#707070;--pebble:#e2e2e5;--hairline:#d2d2d7;--blue:#0071e3;--link:#0066cc}
body{margin:0;background:var(--frost);color:var(--carbon);font-family:-apple-system,BlinkMacSystemFont,Inter,system-ui,"Segoe UI","Yu Gothic UI",sans-serif;font-size:14px}
main{max-width:720px;margin:auto;padding:32px 16px}
h1{margin:0 0 4px;font-size:26px;font-weight:600} h2{margin:28px 0 4px;font-size:18px;font-weight:600}
.sub{color:var(--ash);margin:0 0 10px;line-height:1.6}
.card{background:#fff;border:1px solid var(--hairline);border-radius:8px;overflow:hidden}
table{width:100%;border-collapse:collapse} td{padding:12px 14px;border-bottom:1px solid #edeef0}
tr:last-child td{border-bottom:none} td.rank{width:28px;color:var(--ash)} td.num{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
td.none{color:var(--ash)}
.badge{display:inline-block;border-radius:980px;padding:4px 12px;font-weight:600}
.badge.high{background:var(--blue);color:#fff} .badge.mid{color:var(--link);border:1px solid var(--link)} .badge.low{background:var(--pebble);color:var(--ash)}
.miss{margin-top:10px;background:#fff;border:1px solid var(--hairline);border-radius:8px;padding:12px 16px}
.miss summary{cursor:pointer;font-weight:600} .miss ul{margin:10px 0 0;padding-left:18px;line-height:1.7}
.note{color:var(--ash);font-size:12px}
div.strip{display:flex;overflow-x:auto;border:1px solid var(--hairline);border-radius:8px;margin-top:6px}
div.strip figure{margin:0;flex:1 0 96px;text-align:center;font-size:11px;color:var(--ash);border-right:1px solid #edeef0}
div.strip figure:last-child{border-right:none}
div.strip .sg svg,div.strip .sg img{width:100%;height:84px;object-fit:fill;background:#0c0c10;display:block;border-radius:0;max-height:none}
div.strip figcaption{padding:4px 2px}
table.trend{width:100%;border-collapse:collapse;font-size:13px} table.trend th{text-align:left;color:var(--ash);font-weight:500;padding:4px 6px}
table.trend td{padding:5px 6px;border-top:1px solid #edeef0} table.trend td.num{text-align:right;font-variant-numeric:tabular-nums}
tr.pick{cursor:pointer} tr.pick:hover{background:#f4f8fb}
.tag{display:inline-block;background:var(--pebble);color:var(--ash);border-radius:980px;padding:3px 10px;font-size:12px;margin:2px 4px 2px 0}
.kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:12px 0}
.kpi{border:1px solid var(--hairline);border-radius:8px;padding:12px} .kpi b{display:block;font-size:20px;font-weight:600} .kpi span{color:var(--ash);font-size:12px}
.dsub{color:var(--ash);font-size:13px;margin:4px 0}
.dgraph svg,.dgraph img{width:100%;height:auto;max-height:320px;object-fit:contain;background:var(--carbon);border-radius:8px}
.modal{position:fixed;inset:0;background:rgba(29,29,31,.5);display:flex;align-items:center;justify-content:center;padding:20px}
.modal[hidden]{display:none}
.modal-card{background:#fff;border-radius:8px;padding:24px;max-width:520px;width:100%;max-height:88vh;overflow:auto;position:relative;border:1px solid var(--hairline)}
.modal-card h3{margin:0 0 6px;font-size:18px;font-weight:600}
.modal-close{position:absolute;top:14px;right:16px;border:none;background:none;font-size:20px;cursor:pointer;color:var(--ash)}
"""


def summary_report(store, folder, day, top=5):
    """One-page digest of a day: per store, the best racks and how complete it is."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    sections = []
    day_event_labels = [f'{STORE_NAMES[location]}：{events[0]["name"]}'
                        for location in STORE_NAMES
                        if (events := store.date_events(location, day))]
    event_subtitle = ('<p class="sub">' + ' ／ '.join(map(html.escape, day_event_labels)) + '</p>'
                      if day_event_labels else '')
    for location, label in STORE_NAMES.items():
        entries = []
        candidates_by_rack = {int(c['row']['rack']): c for c in day_candidates(store, day, location)}
        for machine in store.machines_for(location, day):
            for r in scored_rows(store, day, machine, location):
                entries.append((machine, r))
        if not entries:
            continue
        scored = [(m, r) for m, r in entries if r['score']['total'] is not None]
        scored.sort(key=lambda item: item[1]['score']['total'], reverse=True)
        pending = len(entries) - len(scored)
        made = sum(1 for _m, r in entries if juggler_online_made(r))
        no_graph = sum(1 for _m, r in entries if not graph_done(r)) - made
        skipped = sum(1 for _m, r in entries if graph_not_needed(r))
        def detail(machine, r):
            sc = r['score']
            hits = r['bb'] + r['rb']
            rate = f'1/{r["games"] / hits:.1f}' if hits else '—'
            total = sc['total']
            total_text = f'{total:.1f}'
            tier_name = 'high' if total >= 80 else 'mid' if total >= 60 else 'low'
            hold = '—' if r.get('max_hold') is None else str(r['max_hold'])
            parts = ''.join(
                f'<span class="tag">{name} {"—" if sc[key] is None else format(sc[key], ".1f")}</span>'
                for name, key in (('持玉/20', 'max_hold'), ('当り/60', 'hits'),
                                  ('終点/10', 'positive'), ('維持/10', 'retention')))
            trend = rack_trend(store, r)
            forecast = next_day_index(store, r)
            if is_variety_row(store, r):
                # 1〜3台の機種（バラエティ）は、回転数と終わり方で見る（過去傾向の指数は無い）。
                forecast_html = (f'<div class="dsub" style="margin-top:12px">'
                                 f'{html.escape(variety_judgement_text(store, r))}<br>'
                                 '翌日の設定・勝率・期待収支を示すものではありません（効果は検証中）。</div>')
            elif forecast['index'] is None:
                forecast_html = (f'<div class="dsub" style="margin-top:12px">この台の当たりの軽さ（過去傾向）：'
                                 f'まだ判定できません（同じ機種で{forecast["days"]}日分／3日分から判定）</div>')
            else:
                forecast_html = (f'<div class="dsub" style="margin-top:12px">この台の当たりの軽さ（過去傾向）：'
                                 f'<b>{signed_index(forecast["index"])}</b>'
                                 f'（過去{forecast["days"]}日分・データ量{forecast["confidence"]}）<br>'
                                 '同じ日・同じ機種で回転数が近い台と比べた当たり頻度の差です。'
                                 '「翌日候補（仮）」の根拠に使っています。今日の合計点とは別で、'
                                 '翌日の設定・勝率・期待収支を示すものではありません（効果は検証中）。</div>')
                evidence = next_day_evidence(store, r)
                item = dict(row=r, today_score=total, **evidence)
                picked = candidates_by_rack.get(int(r['rack']))
                mark = ('★ 注目' if picked and picked.get('focus') else '☆ 長期傾向' if picked else '長期上位ではありません')
                forecast_html += (f'<div class="dsub"><b>{mark}</b><br>{html.escape(next_day_reason(item))}<br>'
                                  f'安定性 z={evidence["stability_z"]:.2f}（基準1.96。高設定の確率や検定の有意性ではありません）。'
                                  '当日88点以上は★注目から除外し、☆長期傾向には残します。</div>')
            forecast_html += normal_day_context_html(location, day, [r['machine']])
            strip_html = slump_strip_html(store, r)
            if len(trend) > 1:
                totals = [t['total'] for t in trend if t['total'] is not None]
                average = f'（平均 {sum(totals) / len(totals):.1f}点）' if totals else ''
                lines = ''.join(
                    f'<tr><td>{t["day"]}</td><td class="num">{"—" if t["total"] is None else format(t["total"], ".1f")}'
                    '</td>'
                    f'<td class="num">{t["games"]}G</td>'
                    f'<td class="num">{"1/" + format(t["rate"], ".1f") if t["rate"] else "—"}</td></tr>'
                    for t in trend)
                trend_html = (f'<div class="dsub" style="margin-top:14px">この台の推移（同じ機種・直近{len(trend)}日）{average}</div>'
                              f'<table class="trend"><thead><tr><th>日付</th><th>合計点</th><th>回転</th><th>当たり</th></tr></thead>'
                              f'<tbody>{lines}</tbody></table>')
            else:
                trend_html = '<div class="dsub" style="margin-top:14px">この台の過去データ（同じ機種）はまだありません。</div>'
            note = captured_note(r)
            note_html = f'<div class="dsub">{html.escape(note)}</div>' if note else ''
            estimate = r['setting_estimate']
            estimate_html = (f'<p class="dsub">BB/RBのモデル内中央80%候補範囲：{html.escape("・".join(estimate["range80"]))}'
                             f'｜最多適合 {html.escape(estimate["setting"])}（均等仮定のモデル内相対重み {estimate["support"]:.1f}%）'
                             f'｜実際の設定確率ではありません'
                             f'｜<a href="{html.escape(estimate["source"], quote=True)}">メーカー確率表</a></p>'
                             if estimate else '')
            return (f'<div class="dsub">{html.escape(label)} ｜ {html.escape(day)} ｜ {html.escape(machine)}</div>{note_html}'
                    f'<p><span class="badge {tier_name}">{html.escape(total_text)}</span> <span class="dsub">実績点（設定確率ではありません）</span></p>'
                    f'<div class="kpis"><div class="kpi"><b>{hits}回</b><span>当たり回数</span></div>'
                    f'<div class="kpi"><b>{rate}</b><span>表示当たり頻度</span></div>'
                    f'<div class="kpi"><b>{r["games"]}G</b><span>総回転</span></div></div>'
                    f'<p class="dsub">BIG {r["bb"]}　REG {r["rb"]}　最大持玉 {hold}　｜　観測量（設定判別の信頼度ではありません）：{reliability_label(r["games"])}</p>{estimate_html}<p>{parts}</p><p class="dsub">{html.escape("・".join(sc["reasons"]))}</p>'
                    f'<div class="dgraph">{measurement_preview_html(r)}</div>{strip_html}{trend_html}{forecast_html}')

        rows = ''.join(
            f'<tr class="pick" data-title="{r["rack"]}番台" data-detail="{html.escape(detail(m, r), quote=True)}" '
            f'onclick="showDetail(this)"><td class="rank">{i}</td><td>{html.escape(m)}</td><td class="num">{r["rack"]}番台{rack_mark(r)}</td>'
            f'<td class="num">{r["games"]}G</td>'
            f'<td class="num"><span class="badge {"high" if r["score"]["total"] >= 80 else "mid" if r["score"]["total"] >= 60 else "low"}">'
            f'{r["score"]["total"]:.1f}</span></td></tr>'
            for i, (m, r) in enumerate(scored[:top], 1))
        if not rows:
            rows = '<tr><td colspan="5" class="none">合計点が確定した台はまだありません。</td></tr>'
        odd = suspicious_duplicates(store, day, location)
        odd_html = ''
        if odd:
            odd_html = ('<details class="miss" open><summary>要確認：数値が完全に同じ台</summary><ul>'
                        + ''.join(f'<li><b>{html.escape(m)}</b>　{"・".join(map(str, racks))}番台'
                                  '<br><span class="note">回転数・BIG・REGがすべて同じです。台番号のずれで別の台のデータが'
                                  '保存された可能性があります。</span></li>' for m, racks in odd)
                        + '</ul></details>')
        missing = missing_graphs(store, day, location)
        if missing:
            items = ''.join(
                f'<li><b>{html.escape(m)}</b>　{len(racks)}台：{"、".join(map(str, racks))}'
                + (f'<br><span class="note">うち{nl}台は個別台リンクが保存されていません。'
                   '機種別一覧をもう一度取り込むと「次の未取り込み台へ」が使えます。</span>' if nl else '')
                + '</li>' for m, racks, nl in missing)
            total_missing = sum(len(racks) for _m, racks, _nl in missing)
            missing_html = (f'<details class="miss"><summary>グラフ未取得の台（{total_missing}台）</summary>'
                            f'<ul>{items}</ul></details>')
        else:
            missing_html = '<p class="sub">この日の一覧にある台は、すべてグラフ取り込み済みです。</p>'
        sections.append(
            f'<section><h2>{html.escape(label)}</h2>'
            f'<p class="sub">{len(entries)}台 ／ 実績点表示{len(scored)}台'
            f' ／ 保留{pending}台 ／ グラフ未取得{no_graph}台'
            + (f'（大当たり0回でグラフ省略{skipped}台は除く）' if skipped else '')
            + (f' ／ ジャグラーオンラインの数字で作った台{made}台（グラフ無し）' if made else '') + '</p>'
            f'<div class="card"><table><tbody>{rows}</tbody></table></div>{missing_html}{odd_html}</section>')
    if not sections:
        raise ValueError(f'{day}の保存データがありません。')
    text = f'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>database まとめ</title>
<style>
{SUMMARY_REPORT_CSS}{FLIP7_CSS}</style></head><body><main><div class="f7-brand">{FLIP7_FAN}<h1>{html.escape(day)} のまとめ</h1></div>{event_subtitle}
<p class="sub">実績点の上位{top}台（機種横断の記録表示で、狙い台順位ではありません）。台をクリックするとグラフと当たり回数を表示します。独自の結果評価であり、出率・設定を表すものではありません。</p>
{''.join(sections)}</main>
<div id="detail-modal" class="modal" hidden><div class="modal-card"><button type="button" class="modal-close" onclick="closeDetail()" aria-label="閉じる">×</button><h3 id="detail-title"></h3><div id="detail-body"></div></div></div>
<script>
function showDetail(tr){{document.getElementById('detail-title').textContent=tr.dataset.title;document.getElementById('detail-body').innerHTML=tr.dataset.detail;document.getElementById('detail-modal').hidden=false}}
function closeDetail(){{document.getElementById('detail-modal').hidden=true}}
document.getElementById('detail-modal').addEventListener('click',e=>{{if(e.target.id==='detail-modal')closeDetail()}});
document.addEventListener('keydown',e=>{{if(e.key==='Escape')closeDetail()}});
</script></body></html>'''
    output = folder / f'database-summary-{day}.html'
    output.write_text(text, encoding='utf-8')
    return output
