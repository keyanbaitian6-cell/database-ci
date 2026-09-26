"""Local storage and transparent scoring for database."""
from __future__ import annotations

import html
import json
import math
import re
import shutil
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from setting_estimate import candidate_label, estimate_setting

VERSION = '2026-09-27-v11'
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
               'graph_measurement', 'captured_at', 'confirmed_setting')
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


def _valid_date_event(event):
    if not isinstance(event, dict) or event.get('store') not in STORE_NAMES:
        return False
    try:
        date.fromisoformat(event.get('day', ''))
    except (TypeError, ValueError):
        return False
    name = event.get('name')
    return isinstance(name, str) and 0 < len(name.strip()) <= 60


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.execute('CREATE TABLE IF NOT EXISTS observations (id INTEGER PRIMARY KEY, captured_at TEXT NOT NULL, payload TEXT NOT NULL)')
        self._ensure_store_schema()
        # 翌日候補（仮）の記録。Android版と同じ形（candidate_log.dart）。
        self.db.execute('CREATE TABLE IF NOT EXISTS candidate_snapshots (store TEXT NOT NULL, day TEXT NOT NULL, '
                        'machine TEXT NOT NULL, taken_at TEXT NOT NULL, payload TEXT NOT NULL, '
                        'PRIMARY KEY(store, day, machine, taken_at))')
        self.db.execute('CREATE TABLE IF NOT EXISTS app_state (state_key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        if self.state('date_events') is None:
            self.set_date_events(INITIAL_DATE_EVENTS)
        self._merge_machine_spellings()
        self.db.commit()

    def _merge_machine_spellings(self):
        """Fold rows saved under a '+'-spelled machine name into the normal one.

        Runs once per open and does nothing when every name is already
        normalized. A copy of the database is kept first, as the store
        migration above does.
        """
        # Keys only: reading every payload (graph images included) on each open
        # made opening the database grow with the data for no reason.
        keys = self.db.execute('SELECT store,day,machine,rack FROM days').fetchall()
        odd = [(*k, self.db.execute('SELECT payload FROM days WHERE store=? AND day=? AND machine=? AND rack=?',
                                    k).fetchone()[0])
               for k in keys if k[2] != normalize_machine_name(k[2])]
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
                payload = dict(json.loads(raw), machine=name)
                twin = self.db.execute('SELECT payload FROM days WHERE store=? AND day=? AND machine=? AND rack=?',
                                       (location, day, name, rack)).fetchone()
                if twin:
                    payload = _merge_spellings(json.loads(twin[0]), payload)
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
        self._machine_cache = {}
        groups = set()
        with self.db:
            for row in rows:
                row = dict(row, machine=normalize_machine_name(row.get('machine')))
                if row.get('kind_code') != 21 or row.get('store') not in STORE_NAMES:
                    raise ValueError('対象は長町南店・幸町店の1000円46枚スロットのみです。')
                date.fromisoformat(row['day'])
                key = (row['store'], row['day'], row['machine'], int(row['rack']))
                old = self.db.execute('SELECT payload FROM days WHERE store=? AND day=? AND machine=? AND rack=?', key).fetchone()
                merged = json.loads(old[0]) if old else {}
                # Preserve a graph only while its corresponding source numbers match.
                changed = any(k in merged and k in row and row[k] is not None and merged[k] != row[k]
                              for k in ('games','bb','rb','max_hold'))
                if changed and not row.get('graph'):
                    merged.pop('graph', None)
                    merged.pop('graph_measurement', None)
                merged.update({k: v for k, v in row.items() if v is not None})
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
            targets = set()
            for location, machine, day in groups:
                last = (date.fromisoformat(day) + timedelta(days=30)).isoformat()
                targets.add((location, machine, day))
                for (later,) in self.db.execute(
                        'SELECT DISTINCT day FROM days WHERE store=? AND machine=? AND day>? AND day<=?',
                        (location, machine, day, last)):
                    targets.add((location, machine, later))
            self._machine_cache = {}
            now = datetime.now().astimezone()
            for location, machine, day in sorted(targets):
                snapshot = candidate_snapshot(self, location, day, machine, now)
                latest = self.db.execute(
                    'SELECT payload FROM candidate_snapshots WHERE store=? AND day=? AND machine=? '
                    'ORDER BY taken_at DESC LIMIT 1', (location, day, machine)).fetchone()
                if latest and candidate_signature(json.loads(latest[0])) == candidate_signature(snapshot):
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
        added = 0
        with self.db:
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

    def date_events(self, location=None, day=None):
        try:
            events = json.loads(self.state('date_events') or '[]')
        except (TypeError, ValueError):
            events = []
        return [event for event in events if _valid_date_event(event)
                and (location is None or event['store'] == location)
                and (day is None or event['day'] == day)]

    def set_date_events(self, events):
        valid = {}
        for event in events:
            if _valid_date_event(event):
                valid[(event['store'], event['day'])] = {
                    'store': event['store'], 'day': event['day'], 'name': event['name'].strip()}
        payload = json.dumps(list(valid.values()), ensure_ascii=False)
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO app_state VALUES(?,?)', ('date_events', payload))

    def set_date_event(self, location, day, name):
        events = {(event['store'], event['day']): event for event in self.date_events()}
        key = (location, day)
        if name is None or not name.strip():
            events.pop(key, None)
        else:
            event = {'store': location, 'day': day, 'name': name.strip()}
            if not _valid_date_event(event):
                raise ValueError('イベント名、店舗、日付を確認してください。')
            events[key] = event
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
            for key, payload in entries:
                if payload is None:
                    self.db.execute('DELETE FROM days WHERE store=? AND day=? AND machine=? AND rack=?', key)
                else:
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
            groups = set(self.db.execute(query.replace('DELETE FROM', 'SELECT DISTINCT store, machine, day FROM'),
                                         values).fetchall())
            cursor = self.db.execute(query, values)
            self._log_candidates(groups)
        self._machine_cache = {}
        return cursor.rowcount

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
        return [json.loads(x[0]) for x in self.db.execute(query + ' ORDER BY day,store,rack', values)]

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
        return [x[0] for x in self.db.execute(query + ' ORDER BY day,store,rack', values)]

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
        return [row[0] for row in self.db.execute(query, (store, day))]

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
    """The next-day candidates of one store/day/machine now, in Android's format."""
    result = provisional_next_day_candidates(store, day, machine, location)
    return dict(store=location, day=day, machine=machine,
                taken_at=(now or datetime.now().astimezone()).isoformat(),
                total=result['total'], eligible=result['eligible'],
                candidates=[dict(rack=int(c['row']['rack']), index=c['index'], days=c['days'])
                            for c in result['candidates']])


def candidate_signature(snapshot):
    """Content without the time: an unchanged list is not recorded again."""
    return (snapshot.get('total'), snapshot.get('eligible'),
            tuple((c.get('rack'), float(c.get('index')), c.get('days'))
                  for c in snapshot.get('candidates', [])))


_RECORDS_START = re.compile(r'"records"\s*:\s*\[$')


def read_backup_file(path, allow_viewer=False):
    """(records, candidate_snapshots) of a backup, read line by line when possible.

    The one-record-per-line layout (this PC app and the current Android app)
    is parsed line by line, so the file is never held as one big string;
    anything else (older Android exports) is read whole.
    """
    path = Path(path)
    records, snapshots, section = [], [], 'header'
    with path.open(encoding='utf-8') as source:
        first = source.readline().strip()
        match = _RECORDS_START.search(first)
        if first.startswith('{') and match:
            header = json.loads(first[:match.start()].rstrip().rstrip(',') + '}')
            if not isinstance(header, dict) or header.get('format') != BACKUP_FORMAT:
                raise ValueError('バックアップファイルの形式が不正です。')
            if header.get('source') == 'pc-viewer' and not allow_viewer:
                raise ValueError('これは閲覧ページ用の軽いファイル（画像なし）です。バックアップとして取り込まないでください。')
            section = 'records'
            for line in source:
                text = line.strip()
                if not text:
                    continue
                if text.startswith(']'):
                    section = ('candidates' if section == 'records' and '"candidate_snapshots"' in text
                               and text.endswith('[') else 'done')
                    continue
                if section == 'done':
                    continue
                item = json.loads(text[:-1] if text.endswith(',') else text)
                (records if section == 'records' else snapshots).append(item)
            return records, snapshots
    payload = json.loads(path.read_text(encoding='utf-8'))
    found = payload.get('records') if isinstance(payload, dict) else None
    if not isinstance(found, list):
        raise ValueError('バックアップファイルの形式が不正です。')
    extra = payload.get('candidate_snapshots')
    return found, extra if isinstance(extra, list) else []


def read_backup_events(path):
    """Read independent store/day event labels from a portable backup header."""
    path = Path(path)
    with path.open(encoding='utf-8') as source:
        first = source.readline().strip()
    match = _RECORDS_START.search(first)
    if first.startswith('{') and match:
        header = json.loads(first[:match.start()].rstrip().rstrip(',') + '}')
    else:
        header = json.loads(path.read_text(encoding='utf-8'))
    raw_events = header.get('date_events', []) if isinstance(header, dict) else []
    return [event for event in raw_events if _valid_date_event(event)] if isinstance(raw_events, list) else []


def export_viewer(store, path, days=VIEWER_DAYS):
    """Write the light file the iPhone viewer reads: the latest ``days`` days
    (counted from the newest saved day), without graph images or curves.

    Same one-record-per-line layout as a backup, so the viewer and
    ``read_backup_file`` read it the same way. Returns the number of racks.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    latest = store.db.execute('SELECT MAX(day) FROM days').fetchone()[0]
    cutoff = ((date.fromisoformat(latest) - timedelta(days=days - 1)).isoformat()
              if latest else None)
    date_events = [event for event in store.date_events()
                   if cutoff and event['day'] >= cutoff and event['day'] <= latest]
    header = json.dumps(dict(format=BACKUP_FORMAT, version=BACKUP_VERSION,
                             exported_at=datetime.now().astimezone().isoformat(),
                             source='pc-viewer', days=days, date_events=date_events), ensure_ascii=False)[:-1]
    count = 0
    with path.open('w', encoding='utf-8') as out:
        out.write(f'{header}, "records": [')
        if latest:
            cutoff = (date.fromisoformat(latest) - timedelta(days=days - 1)).isoformat()
            for (payload,) in store.db.execute(
                    'SELECT payload FROM days WHERE day >= ? ORDER BY day,store,rack', (cutoff,)):
                # 閲覧ページが使う項目だけ（台ページのURL・取り込み元などは省く）。
                row = {k: v for k, v in json.loads(payload).items() if k in VIEWER_KEYS}
                graph = row.get('graph_measurement')
                if isinstance(graph, dict):
                    graph.pop('preview_image', None)
                    graph.pop('curve', None)
                out.write(('\n' if count == 0 else ',\n') + json.dumps(row, ensure_ascii=False))
                count += 1
        out.write('\n]}')
    return count


def export_backup(store, path, location=None, day=None):
    """Write saved records as a portable JSON file (share via Drive, USB, etc.).

    The format is shared with the Android app's own backup export, so either
    side's file can be read back by the other: both use the same field names
    (store/day/machine/rack/games/bb/rb/max_hold/graph_measurement/...).
    ``day`` narrows the export to one date (across every machine/store), for
    when a full-database export would be too many machines to review at once.
    """
    events = store.date_events(location=location, day=day)
    header = json.dumps(dict(format=BACKUP_FORMAT, version=BACKUP_VERSION,
                             exported_at=datetime.now().astimezone().isoformat(),
                             source='pc', date_events=events), ensure_ascii=False)[:-1]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    query, values = 'SELECT payload FROM days WHERE 1=1', []
    if location:
        query += ' AND store=?'
        values.append(location)
    if day:
        query += ' AND day=?'
        values.append(day)
    count = 0
    # One record per line, written as read: the whole database is never held
    # as one string (this runs after every save), and the file can be read
    # back line by line (``iter_backup_file``). Payloads are copied verbatim.
    with path.open('w', encoding='utf-8') as out:
        out.write(f'{header}, "records": [')
        for (payload,) in store.db.execute(query + ' ORDER BY day,store,rack', values):
            out.write(('\n' if count == 0 else ',\n') + payload)
            count += 1
        out.write('\n]')
        snapshots = store.candidate_snapshots(day=day, location=location)
        if snapshots:
            out.write(', "candidate_snapshots": [\n' + ',\n'.join(snapshots) + '\n]')
        out.write('}')
    return count


def _valid_backup_record(record):
    try:
        return (isinstance(record, dict) and record.get('kind_code') == 21
                and record.get('store') in STORE_NAMES and record.get('machine')
                and record.get('rack') is not None
                and record.get('confirmed_setting') in (*CONFIRMED_SETTING_OPTIONS, None)
                and bool(date.fromisoformat(record.get('day', ''))))
    except (ValueError, TypeError):
        return False


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
    link_only, setting_only = [], []
    seen = {}
    for record in records:
        if not _valid_backup_record(record):
            skipped.append(record)
            continue
        # Compare with one spelling, or a '+'-spelled copy is added as a new rack.
        record = dict(record, machine=normalize_machine_name(record['machine']))
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
        else:
            unchanged.append(record)
    return dict(new=new, graph_only=graph_only, unchanged=unchanged,
               conflicts=conflicts, skipped=skipped, link_only=link_only,
               setting_only=setting_only)


SETTINGS_NAME = 'settings.json'
# Fixed file name so the shared folder always holds exactly one auto-written
# copy (overwritten each time) instead of piling up timestamped files.
AUTO_BACKUP_NAME = 'database-backup-auto.json'


def load_settings(data_dir):
    try:
        loaded = json.loads((Path(data_dir) / SETTINGS_NAME).read_text(encoding='utf-8'))
        return loaded if isinstance(loaded, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(data_dir, **updates):
    settings = load_settings(data_dir)
    settings.update(updates)
    path = Path(data_dir) / SETTINGS_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding='utf-8')
    return settings


SNAPSHOT_KEEP_DAYS = 7
SNAPSHOT_PATTERN = 'database-backup-????-??-??.json'


def snapshot_dir(data_dir):
    """Where the dated backups live: ``backups/`` inside the sync folder when one
    is set (so they reach Drive too), otherwise inside the local data folder."""
    folder = load_settings(data_dir).get('sync_dir')
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
    forced = [incoming for _local, incoming in plan['conflicts']]
    for record in plan['unchanged']:
        local = existing.get((record['store'], record['day'], record['machine'], int(record['rack'])))
        wanted = record.get('graph_measurement') or record.get('graph')
        if local and wanted and wanted != (local.get('graph_measurement') or local.get('graph')):
            forced.append(record)
    if forced:
        store.save(forced)
    return dict(plan, forced=forced)


def auto_backup(store, data_dir):
    """Refresh the shared-folder backup after data changed; never raises.

    Also writes today's dated backup (see ``snapshot_backup``). The shared-folder
    copy is skipped unless a sync folder was configured, because a failed backup
    must never get in the way of saving the record itself.
    """
    snapshot = None
    try:
        snapshot = snapshot_backup(store, data_dir)
    except (OSError, ValueError):
        pass
    folder = load_settings(data_dir).get('sync_dir')
    if not folder or not Path(folder).is_dir():
        return None
    try:
        path = Path(folder) / AUTO_BACKUP_NAME
        if snapshot is not None:
            # 同じ内容なので、全データを2回書き出さず、書き出した1つを複製する。
            shutil.copyfile(snapshot, path)
        else:
            export_backup(store, path)
    except OSError:
        return None
    try:
        # 閲覧ページ用の軽いファイル。ローカルで書いてから同期フォルダへ複製する
        # （書きかけのファイルがDriveへ上がらないように）。
        local = Path(data_dir) / VIEWER_FILE_NAME
        export_viewer(store, local)
        shutil.copyfile(local, Path(folder) / VIEWER_FILE_NAME)
    except (OSError, ValueError):
        pass
    return path


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


def delete_records(store, data_dir, day, location=None, machine=None):
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


def undo_last_save(store, data_dir):
    """Restore the racks touched by the last save; returns its label."""
    path = Path(data_dir) / UNDO_NAME
    try:
        info = json.loads(path.read_text(encoding='utf-8'))
        entries = [(tuple(e['key']), e['previous']) for e in info['entries']]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError('取り消せる保存がありません。') from exc
    store.restore_payloads(entries)
    path.unlink()
    auto_backup(store, data_dir)
    return info.get('label', '直前の保存')


def progress_text(store, day):
    """"2026-09-18　長町南 42/80台・幸町 18/60台" -- graphs saved / racks listed."""
    parts = []
    for location, short in SHORT_STORE_NAMES.items():
        rows = store.rows(day, None, location)
        if rows:
            done = sum(1 for r in rows if r.get('graph') or r.get('graph_measurement'))
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


def next_day_index(store, row, max_days=10, shrink_days=5):
    """Historical hit-frequency tendency for the provisional candidate view.

    This is not a validated forecast, setting probability, or part of the
    100-point daily score. It is deliberately limited to data available by
    ``row['day']`` so it can be evaluated later without future leakage.
    """
    first = (date.fromisoformat(row['day']) - timedelta(days=30)).isoformat()
    all_rows = [r for r in store._machine_rows(row['machine'], row['store'])
                if first <= r['day'] <= row['day'] and r.get('games', 0) >= 500
                and r.get('bb') is not None and r.get('rb') is not None
                and r['bb'] >= 0 and r['rb'] >= 0 and not implausible_numbers(r)]
    days = sorted({r['day'] for r in all_rows if int(r['rack']) == int(row['rack'])}, reverse=True)[:max_days]
    gaps = []
    for day in days:
        mine = next(r for r in all_rows if r['day'] == day and int(r['rack']) == int(row['rack']))
        peers = [r for r in all_rows if r['day'] == day and
                 mine['games'] / 2 <= r['games'] <= mine['games'] * 2]
        if len(peers) >= 3:
            rates = [(r['bb'] + r['rb']) / r['games'] for r in peers]
            rank = percentile((mine['bb'] + mine['rb']) / mine['games'], rates)
            gaps.append((100 * rank - 50) * mine['games'] / (mine['games'] + SHRINK_GAMES))
    n = len(gaps)
    if n < 3:
        return dict(days=n, index=None, confidence='データ不足')
    return dict(days=n, index=round_score(50 + sum(gaps) / (n + shrink_days)),
                confidence='少' if n < 7 else '中')


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
        tendency = next_day_index(store, row)
        if tendency['index'] is not None:
            eligible.append(dict(row=row, **tendency))
    eligible.sort(key=lambda item: (-item['index'], int(item['row']['rack'])))
    count = math.ceil(len(eligible) * .25) if len(eligible) >= 4 else 0
    return dict(total=len(rows), eligible=len(eligible), count=count,
                candidates=eligible[:count])


def machine_progress(store, location, day):
    """{whitespace-stripped machine name: (graphed, listed)} for one store and day."""
    result = {}
    for r in store.rows(day, None, location):
        key = re.sub(r'\s+', '', r['machine'])
        done, total = result.get(key, (0, 0))
        result[key] = (done + (1 if (r.get('graph') or r.get('graph_measurement')) else 0), total + 1)
    return result


def day_fully_graphed(store, day):
    rows = store.rows(day)
    return bool(rows) and all(r.get('graph') or r.get('graph_measurement') for r in rows)


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


def latest_backup_file(folder):
    """Newest backup JSON in ``folder`` (ignoring this app's own auto copy and
    the light viewer file, which has no graph images and must never be
    imported as if it were a backup)."""
    candidates = [p for p in Path(folder).glob('*.json')
                  if p.name not in (AUTO_BACKUP_NAME, VIEWER_FILE_NAME)]
    for path in sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if isinstance(payload, dict) and payload.get('format') == BACKUP_FORMAT:
            return path
    return None


def import_backup(store, path):
    """Apply a backup file's safe records; return the classification plan.

    Only 'new' and 'graph_only' records are written. Conflicts are left for
    the caller to show the user and, if they choose, apply individually via
    ``store.save([incoming])``.
    """
    try:
        records, snapshots = read_backup_file(path)
    except (OSError, ValueError) as exc:
        raise ValueError(f'バックアップファイルを読み込めません。{exc}') from exc
    plan = plan_backup_import(store, records)
    plan['events_added'] = 0
    plan['event_conflicts'] = 0
    local_events = {(event['store'], event['day']): event for event in store.date_events()}
    for event in read_backup_events(path):
        key = (event['store'], event['day'])
        existing = local_events.get(key)
        if existing is None:
            local_events[key] = event
            plan['events_added'] += 1
        elif existing['name'] != event['name']:
            plan['event_conflicts'] += 1
    if plan['events_added']:
        store.set_date_events(local_events.values())
    to_save = plan['new'] + plan['graph_only'] + plan['link_only'] + plan['setting_only']
    if to_save:
        store.save(to_save, log_candidates=False)
    if snapshots:
        store.add_candidate_snapshots(snapshots)
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
    try:
        # Confirmed manual corrections take precedence over old raw curves.
        metrics = (measurement_metrics(measurement) if measurement else
                   graph_metrics(graph['path'], graph['baseline']) if graph else None)
        if metrics:
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
        s['reasons'].append('少数データ・欠測を含む暫定評価')
    if s['positive'] == 0:
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


def report(store, day, machine, folder, location='nagamachiminami'):
    if location not in STORE_NAMES:
        raise ValueError('対象外の店舗です。')
    results = scored_rows(store, day, machine, location)
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
        setting_display = r.get('confirmed_setting') or '—'
        estimate = r['setting_estimate']
        estimate_display = candidate_label(estimate)
        cells = [str(r['rack']), str(r['games']), str(r['bb']), str(r['rb']), max_hold_display,
                 setting_display, estimate_display]
        cells += [fmt(s[k]) for k in ('max_hold','hits','positive','retention')]
        total_text = fmt(total)
        if total is not None and s['provisional']:
            total_text = '暫定 ' + total_text
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
                      + ''.join(f'<td>{html.escape(c)}</td>' for c in cells[1:6])
                      + f'<td>{html.escape(cells[6])}{source_link}</td>'
                      + ''.join(f'<td>{html.escape(c)}</td>' for c in cells[7:]))
        body.append(
            '<tr>' + data_cells
            + f'<td><span class="badge {tier(total)}">{html.escape(total_text)}</span></td>'
            + f'<td>{html.escape(comparison)}</td>'
            + f'<td><button type="button" class="graph-btn" data-title="{html.escape(str(r["rack"]))}番台" '
              f'data-graph="{graph_html}" onclick="showGraph(this)">{svg}</button></td>'
            + f'<td>{evidence}</td>'
            + f'<td class="reasons">{reason_tags}</td></tr>')
    header_groups = [(1, ''), (6, '表示データ'), (4, '得点内訳'), (1, '総合'), (4, '参考')]
    header = ['台番号','表示G','BB','RB','最大持玉','設定情報（手入力）','設定候補（BB/RB）','持玉 /20','当り /60','終点 /10','維持 /10',
              '合計 /100','比較（件数/日数）','相対グラフ','確認画像','状態・注意']
    done = sum(r['score']['total'] is not None for r in results)
    totals = [r['score']['total'] for r in results if r['score']['total'] is not None]
    average = round(sum(totals) / len(totals), 1) if totals else None
    best = max(totals) if totals else None
    source = results[0].get('source_url') if results else None
    source_html = f'｜ <a href="{html.escape(source, quote=True)}">画面の出典</a>' if source else ''
    candidate_info = provisional_next_day_candidates(store, day, machine, location)
    candidate_lead = ('<p class="candidate-lead">この機種で、過去に当たりが周りの台より軽かった台です。'
                      '明日どの台から見るかの参考用で、今日の合計点には影響しません。</p>')
    if candidate_info['count']:
        # 素の「63/100」では50が中立であることも上下どちらが良いのかも読めないので、
        # 差分（平均より+13）で出す。
        candidate_rows = ''.join(
            f'<li><b>{int(item["row"]["rack"])}番台</b>'
            f'<span class="candidate-delta">当たりの軽さ {signed_index(item["index"])}</span>'
            f'<span class="candidate-days">過去{item["days"]}日分</span></li>'
            for item in candidate_info['candidates'])
        candidate_html = (f'<section class="candidate"><h2>翌日候補（仮）<span class="candidate-tag">試験中</span></h2>'
                          f'{candidate_lead}<ul class="candidate-list">{candidate_rows}</ul>'
                          f'<p class="candidate-note">傾向を出せた{candidate_info["total"]}台中{candidate_info["eligible"]}台から、'
                          f'上位{candidate_info["count"]}台。「平均より」は、同じ日・同じ機種で回転数が近い台と比べた当たり頻度の差です。<br>'
                          '翌日の設定・勝率・期待収支を示すものではありません（効果は検証中）。</p></section>')
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
</style></head><body><main>
<header><h1>database 結果</h1><div class="sub">{html.escape(STORE_NAMES[location])} ｜ {html.escape(machine)} ｜ {day}{event_label} ｜ 1000円46枚 {source_html}<br>
独自の結果評価です。出率・差枚・設定確率を表す点数ではありません。<br>
比較：同店・同機種の過去30日、回転数が概ね半分〜2倍（最低500G）の台。当日・未来は比較に使いません。比較件数・日数・回転数が少ないほど中間へ補正します。<br>
当たり頻度60点、最大持玉20点、終点10点、維持10点。回転数は加点しません。欠けた項目は中立点で補完し、暫定表示と欠測幅を示します。<br>
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


def history_report(store, folder, days=HISTORY_REPORT_DAYS):
    """Build one offline page that groups saved records by date and machine.

    Only the most recent ``days`` dates are drawn. Each rack carries its graph
    image inside the page, so drawing every date made the file grow by roughly
    0.4MB per day of capture and the browser slower to open it every day.
    Nothing is deleted -- older dates stay in the database and are shown by
    the result and summary pages.
    """
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
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
            status = '参考' if s['status'] == 'reference' else '暫定' if s['status'] == 'provisional' else '保留'
            badge = s['status']
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
                        f'data-graph="{graph_html}" onclick="showGraph(this)">{int(r["rack"])}</button>')
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
            f'<div class="status-row"><span>参考 {official}台</span><span>暫定 {provisional}台</span><span>保留 {pending}台</span></div>'
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
</style></head><body><main><header><div><h1>database 過去の記録</h1><div class="sub">店舗と日付ごとに保存した機種・採点結果を確認できます。台番号を押すとスランプグラフを見られます。<br>{html.escape(scope)}</div></div><div class="filters"><label>店舗<select id="store-filter"><option value="">すべての店舗</option>{store_options}</select></label><label>日付<input id="date-filter" type="date"></label><label>機種<select id="machine-filter"><option value="">すべての機種</option>{machine_options}</select></label></div></header>
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
        rows = [r for r in store.rows(day, machine, location)
                if not (r.get('graph') or r.get('graph_measurement'))]
        if rows:
            racks = sorted(int(r['rack']) for r in rows)
            found.append((machine, racks, sum(1 for r in rows if not r.get('detail_url'))))
    return found


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
        for machine in store.machines_for(location, day):
            for r in scored_rows(store, day, machine, location):
                entries.append((machine, r))
        if not entries:
            continue
        scored = [(m, r) for m, r in entries if r['score']['total'] is not None]
        scored.sort(key=lambda item: item[1]['score']['total'], reverse=True)
        provisional = sum(1 for _m, r in scored if r['score']['provisional'])
        pending = len(entries) - len(scored)
        no_graph = sum(1 for _m, r in entries if not (r.get('graph') or r.get('graph_measurement')))
        def detail(machine, r):
            sc = r['score']
            hits = r['bb'] + r['rb']
            rate = f'1/{r["games"] / hits:.1f}' if hits else '—'
            total = sc['total']
            total_text = ('暫定 ' if sc['provisional'] else '') + f'{total:.1f}'
            tier_name = 'high' if total >= 80 else 'mid' if total >= 60 else 'low'
            hold = '—' if r.get('max_hold') is None else str(r['max_hold'])
            parts = ''.join(
                f'<span class="tag">{name} {"—" if sc[key] is None else format(sc[key], ".1f")}</span>'
                for name, key in (('持玉/20', 'max_hold'), ('当り/60', 'hits'),
                                  ('終点/10', 'positive'), ('維持/10', 'retention')))
            trend = rack_trend(store, r)
            forecast = next_day_index(store, r)
            if forecast['index'] is None:
                forecast_html = (f'<div class="dsub" style="margin-top:12px">この台の当たりの軽さ（過去傾向）：'
                                 f'まだ判定できません（同じ機種で{forecast["days"]}日分／3日分から判定）</div>')
            else:
                forecast_html = (f'<div class="dsub" style="margin-top:12px">この台の当たりの軽さ（過去傾向）：'
                                 f'<b>{signed_index(forecast["index"])}</b>'
                                 f'（過去{forecast["days"]}日分・データ量{forecast["confidence"]}）<br>'
                                 '同じ日・同じ機種で回転数が近い台と比べた当たり頻度の差です。'
                                 '「翌日候補（仮）」の根拠に使っています。今日の合計点とは別で、'
                                 '翌日の設定・勝率・期待収支を示すものではありません（効果は検証中）。</div>')
            strip_html = slump_strip_html(store, r)
            if len(trend) > 1:
                totals = [t['total'] for t in trend if t['total'] is not None]
                average = f'（平均 {sum(totals) / len(totals):.1f}点）' if totals else ''
                lines = ''.join(
                    f'<tr><td>{t["day"]}</td><td class="num">{"—" if t["total"] is None else format(t["total"], ".1f")}'
                    f'{"（暫定）" if t["provisional"] and t["total"] is not None else ""}</td>'
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
            f'onclick="showDetail(this)"><td class="rank">{i}</td><td>{html.escape(m)}</td><td class="num">{r["rack"]}番台</td>'
            f'<td class="num">{r["games"]}G</td>'
            f'<td class="num"><span class="badge {"high" if r["score"]["total"] >= 80 else "mid" if r["score"]["total"] >= 60 else "low"}">'
            f'{"暫定 " if r["score"]["provisional"] else ""}{r["score"]["total"]:.1f}</span></td></tr>'
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
            f'<p class="sub">{len(entries)}台 ／ 実績点表示{len(scored)}台（うち暫定{provisional}台）'
            f' ／ 保留{pending}台 ／ グラフ未取得{no_graph}台</p>'
            f'<div class="card"><table><tbody>{rows}</tbody></table></div>{missing_html}{odd_html}</section>')
    if not sections:
        raise ValueError(f'{day}の保存データがありません。')
    text = f'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>database まとめ</title>
<style>
:root{{--carbon:#1d1d1f;--frost:#f5f5f7;--ash:#707070;--pebble:#e2e2e5;--hairline:#d2d2d7;--blue:#0071e3;--link:#0066cc}}
body{{margin:0;background:var(--frost);color:var(--carbon);font-family:-apple-system,BlinkMacSystemFont,Inter,system-ui,"Segoe UI","Yu Gothic UI",sans-serif;font-size:14px}}
main{{max-width:720px;margin:auto;padding:32px 16px}}
h1{{margin:0 0 4px;font-size:26px;font-weight:600}} h2{{margin:28px 0 4px;font-size:18px;font-weight:600}}
.sub{{color:var(--ash);margin:0 0 10px;line-height:1.6}}
.card{{background:#fff;border:1px solid var(--hairline);border-radius:8px;overflow:hidden}}
table{{width:100%;border-collapse:collapse}} td{{padding:12px 14px;border-bottom:1px solid #edeef0}}
tr:last-child td{{border-bottom:none}} td.rank{{width:28px;color:var(--ash)}} td.num{{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}}
td.none{{color:var(--ash)}}
.badge{{display:inline-block;border-radius:980px;padding:4px 12px;font-weight:600}}
.badge.high{{background:var(--blue);color:#fff}} .badge.mid{{color:var(--link);border:1px solid var(--link)}} .badge.low{{background:var(--pebble);color:var(--ash)}}
.miss{{margin-top:10px;background:#fff;border:1px solid var(--hairline);border-radius:8px;padding:12px 16px}}
.miss summary{{cursor:pointer;font-weight:600}} .miss ul{{margin:10px 0 0;padding-left:18px;line-height:1.7}}
.note{{color:var(--ash);font-size:12px}}
div.strip{{display:flex;overflow-x:auto;border:1px solid var(--hairline);border-radius:8px;margin-top:6px}}
div.strip figure{{margin:0;flex:1 0 96px;text-align:center;font-size:11px;color:var(--ash);border-right:1px solid #edeef0}}
div.strip figure:last-child{{border-right:none}}
div.strip .sg svg,div.strip .sg img{{width:100%;height:84px;object-fit:fill;background:#0c0c10;display:block;border-radius:0;max-height:none}}
div.strip figcaption{{padding:4px 2px}}
table.trend{{width:100%;border-collapse:collapse;font-size:13px}} table.trend th{{text-align:left;color:var(--ash);font-weight:500;padding:4px 6px}}
table.trend td{{padding:5px 6px;border-top:1px solid #edeef0}} table.trend td.num{{text-align:right;font-variant-numeric:tabular-nums}}
tr.pick{{cursor:pointer}} tr.pick:hover{{background:#f4f8fb}}
.tag{{display:inline-block;background:var(--pebble);color:var(--ash);border-radius:980px;padding:3px 10px;font-size:12px;margin:2px 4px 2px 0}}
.kpis{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:12px 0}}
.kpi{{border:1px solid var(--hairline);border-radius:8px;padding:12px}} .kpi b{{display:block;font-size:20px;font-weight:600}} .kpi span{{color:var(--ash);font-size:12px}}
.dsub{{color:var(--ash);font-size:13px;margin:4px 0}}
.dgraph svg,.dgraph img{{width:100%;height:auto;max-height:320px;object-fit:contain;background:var(--carbon);border-radius:8px}}
.modal{{position:fixed;inset:0;background:rgba(29,29,31,.5);display:flex;align-items:center;justify-content:center;padding:20px}}
.modal[hidden]{{display:none}}
.modal-card{{background:#fff;border-radius:8px;padding:24px;max-width:520px;width:100%;max-height:88vh;overflow:auto;position:relative;border:1px solid var(--hairline)}}
.modal-card h3{{margin:0 0 6px;font-size:18px;font-weight:600}}
.modal-close{{position:absolute;top:14px;right:16px;border:none;background:none;font-size:20px;cursor:pointer;color:var(--ash)}}
</style></head><body><main><h1>{html.escape(day)} のまとめ</h1>{event_subtitle}
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
