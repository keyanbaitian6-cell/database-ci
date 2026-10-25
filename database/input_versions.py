"""保存した記録の版を、別ファイル（input_versions.sqlite3）へ追記する。

翌日候補の店舗別案を現行と並べて比べるため（NEXT_DAY_SHADOW_PLAN_20261025.md）、
予測の締切（翌日02:00 JST）より前に何が保存されていたかを、あとから正確に作り直せるようにする。
アプリはこのファイルを読まない。画面・候補・バックアップは変わらない。

- 接続ごとの一時トリガー（TEMP TRIGGER）で、メルヘンの ``days``・P’s CUBEの ``records`` への
  すべての書き込み（保存・復元・削除・機種名の統一など）を写す。経路ごとに処理を足さない。
- 内容（取得時刻とグラフのプレビュー画像を除く）が直前の版と同じなら追記しない。
- 最初に開いたとき、その時点の全行を出発点（baseline）として1回だけ記録する。
- 準備に失敗したら記録しないだけで、保存は止めない（失敗の内容は ``state()`` で読める）。
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

FILE_NAME = 'input_versions.sqlite3'
SCHEMA = 'iv'
# 版を比べるときに除く項目。取り直すたびに変わる時刻と、記録の大半を占めるプレビュー画像。
VOLATILE_KEYS = ('captured_at', 'record_updated_at', 'observed_at', 'jo_captured_at')
SOURCES = {
    # source: (表, 鍵の式, 日付の式)
    'meruhen': ('days', "{t}.store || char(9) || {t}.day || char(9) || {t}.machine || char(9) || {t}.rack", '{t}.day'),
    'pscube': ('records', '{t}.key', "iv_day({t}.payload)"),
}
_last_error = {}


def content(raw):
    """比べる・残す内容。読めない行はそのまま残す（版の記録で保存を止めない）。"""
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return raw
    if not isinstance(payload, dict):
        return raw
    payload = {k: v for k, v in payload.items() if k not in VOLATILE_KEYS}
    measurement = payload.get('graph_measurement')
    if isinstance(measurement, dict) and 'preview_image' in measurement:
        payload['graph_measurement'] = {k: v for k, v in measurement.items() if k != 'preview_image'}
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _day(raw):
    try:
        value = json.loads(raw).get('day')
    except (TypeError, ValueError, AttributeError):
        return None
    return value if isinstance(value, str) else None


def _now():
    return datetime.now().astimezone().isoformat()


def _has_baseline(db, source):
    if db.execute(f"SELECT 1 FROM {SCHEMA}.sqlite_master WHERE type='table' AND name='versions'").fetchone() is None:
        return False
    return db.execute(f"SELECT 1 FROM {SCHEMA}.versions WHERE source=? AND key='' AND kind='baseline' LIMIT 1",
                      (source,)).fetchone() is not None


def attach(db, data_dir, source):
    """``db`` の書き込みを ``data_dir/input_versions.sqlite3`` へ写す。成功したらTrue。"""
    table, key_sql, day_sql = SOURCES[source]
    try:
        db.create_function('iv_content', 1, content, deterministic=True)
        db.create_function('iv_day', 1, _day, deterministic=True)
        db.create_function('iv_now', 0, _now)
        if SCHEMA not in [row[1] for row in db.execute('PRAGMA database_list')]:
            db.execute(f'ATTACH DATABASE ? AS {SCHEMA}', (str(Path(data_dir) / FILE_NAME),))
        if not _has_baseline(db, source):
            # 表と出発点を作るときだけ書き込みロックを取る。開くたびには取らない（他の処理の書き込み中でも
            # 準備が失敗しないように。失敗した接続の書き込みは記録から漏れる）。
            with db:
                db.execute('BEGIN IMMEDIATE')
                db.execute(f'CREATE TABLE IF NOT EXISTS {SCHEMA}.versions (id INTEGER PRIMARY KEY, source TEXT NOT NULL, '
                           'key TEXT NOT NULL, day TEXT, saved_at TEXT NOT NULL, kind TEXT NOT NULL, content TEXT)')
                db.execute(f'CREATE INDEX IF NOT EXISTS {SCHEMA}.versions_key ON versions(source, key, id)')
                db.execute(f'CREATE INDEX IF NOT EXISTS {SCHEMA}.versions_day ON versions(source, day)')
                # 出発点は1回だけ。空のDBでも印（鍵が空の行）を残し、あとで2度目の出発点を作らない。
                if not _has_baseline(db, source):
                    db.execute(f"INSERT INTO {SCHEMA}.versions(source, key, day, saved_at, kind, content) "
                               f"SELECT ?, {key_sql.format(t=table)}, {day_sql.format(t=table)}, iv_now(), 'baseline', "
                               f"iv_content(payload) FROM main.{table}", (source,))
                    db.execute(f"INSERT INTO {SCHEMA}.versions(source, key, day, saved_at, kind, content) "
                               "VALUES(?, '', NULL, iv_now(), 'baseline', NULL)", (source,))
        # トリガーの中の追記先は「iv.」を付けて書けない（SQLiteの制限）。表名だけで書き、本体DB・一時領域に
        # 同名の表が無いことを確かめて、つないだ記録ファイルの表に決まるようにする。
        for schema in ('main', 'temp'):
            if db.execute(f"SELECT 1 FROM {schema}.sqlite_master WHERE name='versions'").fetchone():
                raise sqlite3.OperationalError(f'{schema} に versions 表があります。')
        latest = (f"(SELECT content FROM {SCHEMA}.versions WHERE source='{source}' AND key={{key}} "
                  'ORDER BY id DESC LIMIT 1)')
        for event in ('INSERT', 'UPDATE'):
            key = key_sql.format(t='new')
            db.execute(f'DROP TRIGGER IF EXISTS temp.iv_{table}_{event.lower()}')
            db.execute(f"CREATE TEMP TRIGGER iv_{table}_{event.lower()} AFTER {event} ON main.{table} "
                       f"WHEN iv_content(new.payload) IS NOT {latest.format(key=key)} BEGIN "
                       "INSERT INTO versions(source, key, day, saved_at, kind, content) "
                       f"VALUES('{source}', {key}, {day_sql.format(t='new')}, iv_now(), 'write', iv_content(new.payload)); END")
        key = key_sql.format(t='old')
        db.execute(f'DROP TRIGGER IF EXISTS temp.iv_{table}_delete')
        db.execute(f"CREATE TEMP TRIGGER iv_{table}_delete AFTER DELETE ON main.{table} "
                   f"WHEN {latest.format(key=key)} IS NOT NULL BEGIN "
                   "INSERT INTO versions(source, key, day, saved_at, kind, content) "
                   f"VALUES('{source}', {key}, {day_sql.format(t='old')}, iv_now(), 'delete', NULL); END")
        _last_error.pop(source, None)
        return True
    except (sqlite3.Error, OSError) as exc:
        _last_error[source] = repr(exc)
        try:
            for event in ('insert', 'update', 'delete'):
                db.execute(f'DROP TRIGGER IF EXISTS temp.iv_{table}_{event}')
        except sqlite3.Error:
            pass
        return False


def state():
    """直近の準備の失敗（無ければ空）。"""
    return dict(_last_error)


def summary(path, days=7):
    """確認用：記録の種類ごとの件数と、直近の日ごとの書き込み件数・最後の保存時刻。"""
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)) as db:
        kinds = db.execute("SELECT source, kind, COUNT(*) FROM versions WHERE key<>'' GROUP BY source, kind").fetchall()
        recent = db.execute("SELECT source, day, COUNT(*), MAX(saved_at) FROM versions WHERE kind<>'baseline' "
                            'GROUP BY source, day ORDER BY day DESC LIMIT ?', (days * 2,)).fetchall()
    return dict(kinds=kinds, recent=recent)


def as_of(path, source, cutoff):
    """``cutoff``（時刻つきISO文字列またはdatetime）より前に保存されていた内容を {鍵: 内容(dict)} で返す。

    消された行・出発点より後に初めて保存された行は、その時刻までの状態どおりに扱う。
    """
    limit = datetime.fromisoformat(cutoff) if isinstance(cutoff, str) else cutoff
    if limit.tzinfo is None:
        raise ValueError('締切には時差を含めてください。')
    result = {}
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)) as db:
        for key, saved_at, value in db.execute(
                "SELECT key, saved_at, content FROM versions WHERE source=? AND key<>'' ORDER BY id", (source,)):
            if datetime.fromisoformat(saved_at) >= limit:
                continue
            if value is None:
                result.pop(key, None)
            else:
                result[key] = json.loads(value)
    return result


if __name__ == '__main__':
    import sys
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / 'data' / FILE_NAME
    print(json.dumps(summary(target), ensure_ascii=False, indent=1))
