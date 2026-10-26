"""本体と同時に転送待ちを確定し、検証DBへ別接続で送る。"""
from __future__ import annotations
import hashlib
import json
import os
import sqlite3
import threading
import uuid
from contextlib import closing
from datetime import datetime
from pathlib import Path

FILE_NAME = 'input_versions.sqlite3'
VOLATILE_KEYS = ('captured_at', 'record_updated_at', 'observed_at', 'jo_captured_at')
SOURCES = {
 'meruhen': ('days', "{t}.store || char(9) || {t}.day || char(9) || {t}.machine || char(9) || {t}.rack", '{t}.day'),
 'pscube': ('records', '{t}.key', 'iv_day({t}.payload)'),
}
_last_error = {}
_workers = {}
_clients = {}
_stops = {}
_known_paths = set()
_guard = threading.Lock()
BATCH = 200
MAX_PENDING_BYTES = 64 * 1024 * 1024
# 本体の保存中などで一時的に書けないとき、続きを送るまで待つ秒数。
RETRY_SECONDS = 1


def _key(path):
    """同じDBを、接続・転送・保持で同じ名前として数える。"""
    return os.path.normcase(os.path.abspath(str(path)))


def _busy(error):
    return isinstance(error, sqlite3.OperationalError) and 'locked' in str(error)


def content(raw):
    try: payload = json.loads(raw)
    except (TypeError, ValueError): return raw
    if not isinstance(payload, dict): return raw
    payload = {k:v for k,v in payload.items() if k not in VOLATILE_KEYS}
    g = payload.get('graph_measurement')
    if isinstance(g, dict): payload['graph_measurement'] = {k:v for k,v in g.items() if k != 'preview_image'}
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _day(raw):
    try: value = json.loads(raw).get('day')
    except (TypeError, ValueError, AttributeError): return None
    return value if isinstance(value, str) else None


def _now(): return datetime.now().astimezone().isoformat()


class Connection(sqlite3.Connection):
    """保存確定を確認した上限時刻を残す。検証先の失敗は確定済み本体へ伝えない。"""
    recording_path = None
    def _confirmed(self):
        if self.recording_path is None or self.in_transaction: return
        try:
            # 他接続の未確認行も、既に確定して見えているので安全な上限時刻になる。
            sqlite3.Connection.execute(self, 'UPDATE iv_outbox SET confirmed_at=? WHERE confirmed_at IS NULL', (_now(),))
            sqlite3.Connection.commit(self)
            _schedule(self.recording_path)
        except (sqlite3.Error, OSError) as error:
            sqlite3.Connection.rollback(self)
            _last_error[str(self.recording_path)] = repr(error)
    def close(self):
        path = _key(self.recording_path) if self.recording_path else None
        self.recording_path = None
        super().close()
        if path: _leave(path)

    def commit(self):
        super().commit()
        self._confirmed()
    def __exit__(self, *args):
        result = super().__exit__(*args)
        if args[0] is None: self._confirmed()
        return result
    def execute(self, sql, parameters=(), /):
        result = super().execute(sql, parameters)
        if sql.strip().rstrip(';').upper() in ('COMMIT', 'END', 'END TRANSACTION'): self._confirmed()
        return result


def connect(path, *, recording=True):
    db = sqlite3.connect(path, factory=Connection)
    db.recording_allowed = recording
    return db


def attach(db, data_dir, source):
    """本体内だけに一時トリガーを設定する。出力用コピーでは呼び出しても開始しない。"""
    if not getattr(db, 'recording_allowed', True): return True
    table,key_sql,day_sql = SOURCES[source]
    try:
        db.create_function('iv_content', 1, content, deterministic=True)
        db.create_function('iv_day', 1, _day, deterministic=True)
        db.create_function('iv_now', 0, _now)
        db.create_function('iv_digest', 1, lambda raw: hashlib.sha256(content(raw).encode()).hexdigest(), deterministic=True)
        with db:
            db.execute('CREATE TABLE IF NOT EXISTS iv_control (singleton INTEGER PRIMARY KEY CHECK(singleton=1), identity TEXT NOT NULL, source TEXT NOT NULL, paused_at TEXT, pending_bytes INTEGER NOT NULL DEFAULT 0, delivered_seq INTEGER NOT NULL DEFAULT 0)')
            db.execute('CREATE TABLE IF NOT EXISTS iv_outbox (id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT NOT NULL, day TEXT, saved_at TEXT NOT NULL, confirmed_at TEXT, kind TEXT NOT NULL, content TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS iv_heads (key TEXT PRIMARY KEY,digest TEXT)')
            fresh = db.execute('SELECT 1 FROM iv_control').fetchone() is None
            if fresh:
                db.execute('INSERT INTO iv_control(singleton,identity,source) VALUES(1,?,?)', (uuid.uuid4().hex,source))
                # 基準点も本体内で一貫して確定する。以後、開くたびに作り直さない。
                db.execute("INSERT INTO iv_outbox(key,saved_at,kind) VALUES('',iv_now(),'reset')")
                db.execute(f"INSERT INTO iv_outbox(key,day,saved_at,kind,content) SELECT {key_sql.format(t=table)},{day_sql.format(t=table)},iv_now(),'baseline',iv_content(payload) FROM {table}")
                db.execute(f"INSERT OR REPLACE INTO iv_heads SELECT {key_sql.format(t=table)},iv_digest(payload) FROM {table}")
                db.execute("INSERT INTO iv_outbox(key,saved_at,kind) VALUES('',iv_now(),'baseline')")
                db.execute('UPDATE iv_control SET pending_bytes=0')
        # 基準点は既存DB全件を含むので容量上限の対象外。通常変更が増え続けた場合のみ休止。
        for event in ('insert','update','delete'):
            db.execute(f'DROP TRIGGER IF EXISTS temp.iv_{table}_{event}')
        def emit(t, kind, key=None):
            key = key or key_sql.format(t=t)
            value = 'NULL' if kind=='delete' else f'iv_content({t}.payload)'
            digest = 'NULL' if kind=='delete' else f'iv_digest({t}.payload)'
            return f"INSERT INTO iv_outbox(key,day,saved_at,kind,content) VALUES({key},{day_sql.format(t=t)},iv_now(),'{kind}',{value}); INSERT INTO iv_heads VALUES({key},{digest}) ON CONFLICT(key) DO UPDATE SET digest=excluded.digest; UPDATE iv_control SET pending_bytes=pending_bytes+coalesce(length(CAST({value} AS BLOB)),0);"
        for event in ('INSERT','UPDATE'):
            condition = ' AND iv_digest(new.payload) IS NOT (SELECT digest FROM iv_heads WHERE key='+key_sql.format(t='new')+')'
            tombstone = '' if event=='INSERT' else f"INSERT INTO iv_outbox(key,day,saved_at,kind) SELECT {key_sql.format(t='old')},{day_sql.format(t='old')},iv_now(),'delete' WHERE {key_sql.format(t='old')} IS NOT {key_sql.format(t='new')}; DELETE FROM iv_heads WHERE key={key_sql.format(t='old')} AND {key_sql.format(t='old')} IS NOT {key_sql.format(t='new')};"
            db.execute(f"CREATE TEMP TRIGGER iv_{table}_{event.lower()} AFTER {event} ON main.{table} WHEN (SELECT paused_at FROM iv_control) IS NULL{condition} BEGIN {tombstone}{emit('new','write')} END")
        db.execute(f"CREATE TEMP TRIGGER iv_{table}_delete AFTER DELETE ON main.{table} WHEN (SELECT paused_at FROM iv_control) IS NULL BEGIN {emit('old','delete')} END")
        # サイズの判定をSQL内で行い、休止状態を全接続で共有する。既存待ち行は削除しない。
        db.execute(f"CREATE TEMP TRIGGER IF NOT EXISTS iv_capacity AFTER INSERT ON iv_outbox WHEN new.kind<>'baseline' AND (SELECT pending_bytes FROM iv_control)>{MAX_PENDING_BYTES} BEGIN UPDATE iv_control SET paused_at=coalesce(paused_at,iv_now()); END")
        path = Path(db.execute('PRAGMA database_list').fetchone()[2])
        if isinstance(db, Connection):
            if db.recording_path is None:
                with _guard: _clients[_key(path)] = _clients.get(_key(path),0)+1
            _known_paths.add(_key(path))
            db.recording_path = path
            db._confirmed()
        _last_error.pop(source,None)
        return True
    except (sqlite3.Error, OSError) as error:
        _last_error[source] = repr(error)
        for event in ('insert','update','delete'):
            try: db.execute(f'DROP TRIGGER IF EXISTS temp.iv_{table}_{event}')
            except sqlite3.Error: pass
        return False


def _leave(path, *, timeout=5):
    """接続・保持を1つ減らす。最後の1つなら転送を止め、ファイルを手放すまで待つ。"""
    worker = None
    with _guard:
        _clients[path] = max(0,_clients.get(path,1)-1)
        if not _clients[path]:
            _stops.setdefault(path,threading.Event()).set()
            worker = _workers.get(path)
    if worker and worker is not threading.current_thread(): worker.join(timeout=timeout)


def hold(path):
    """アプリの起動中、接続を閉じても転送を続ける。終了時に release() を呼ぶ。

    PC版は操作ごとに接続を開いて閉じる。接続の数だけで転送を止めると、初回の全件基準点（数万件）や
    閉じる直前の保存が次の操作まで送られず、締切までに検証先へ届かない（2026-10-26、実DBで確認）。
    """
    path = _key(path)
    with _guard: _clients[path] = _clients.get(path,0)+1
    _known_paths.add(path)
    if Path(path).is_file(): _schedule(path)


def release(path, *, timeout=5):
    _leave(_key(path), timeout=timeout)


def _schedule(path):
    path = _key(path)
    with _guard:
        if not _clients.get(path): return
        _stops.setdefault(path,threading.Event()).clear()
        if path in _workers and _workers[path].is_alive(): return
        worker = threading.Thread(target=_run, args=(path,), daemon=True, name='input-versions-transfer')
        _workers[path] = worker
        worker.start()


def _pending(path):
    try:
        with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True,timeout=.05)) as db:
            return db.execute('SELECT 1 FROM iv_outbox LIMIT 1').fetchone() is not None
    except sqlite3.Error as error:
        # 使用中で確かめられないときだけ、もう一度送ってみる。表が無いなどは送る物が無い。
        return _busy(error)


def _run(path):
    stop = _stops[path]
    finished = False
    try:
        while True:
            try:
                flush(path, background=True)
            except sqlite3.OperationalError as error:
                if not _busy(error): raise
                # 本体の保存中など。次の保存を待たずに、少し待って続きから送る。
                if stop.wait(RETRY_SECONDS): break
                continue
            _last_error.pop(path, None)
            finished = True
            break
    except (sqlite3.Error, OSError, ValueError) as error:
        _last_error[path]=repr(error)
    finally:
        with _guard:
            _workers.pop(path,None)
    # 実行中に確定した行の _schedule() は何もしないので、後始末の後に確かめて続ける。
    if finished and not stop.is_set() and _pending(path): _schedule(path)


def _receipt_digest(text):
    # 受領の照合値。内容の写しを残すと検証記録が内容の約2倍になる（2026-10-26）。
    return hashlib.sha256(text.encode()).hexdigest()


def flush(path, *, background=False):
    """確定した待ち行だけ転送。読み取りロックを持ったまま検証先を待たない。"""
    path = Path(path)
    if not path.is_file(): return
    with closing(sqlite3.connect(path, timeout=.05)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='iv_control'").fetchone(): return
        control = db.execute('SELECT identity,source,delivered_seq FROM iv_control').fetchone()
        if not control: return
        identity,source,delivered = control
        with db: db.execute('UPDATE iv_outbox SET confirmed_at=? WHERE confirmed_at IS NULL',(_now(),))
        with closing(sqlite3.connect(path.parent/FILE_NAME, timeout=.05)) as target:
            target.execute('CREATE TABLE IF NOT EXISTS versions (id INTEGER PRIMARY KEY, source TEXT NOT NULL,key TEXT NOT NULL,day TEXT,saved_at TEXT NOT NULL,kind TEXT NOT NULL,content TEXT)')
            target.execute('CREATE TABLE IF NOT EXISTS iv_receipts (identity TEXT, seq INTEGER, digest TEXT NOT NULL, confirmed_at TEXT, version_id INTEGER, PRIMARY KEY(identity,seq))')
            target.execute('CREATE TABLE IF NOT EXISTS iv_gaps (identity TEXT PRIMARY KEY,source TEXT,paused_at TEXT)')
            target.commit()
            if delivered and not target.execute('SELECT 1 FROM iv_receipts WHERE identity=? AND seq=?',(identity,delivered)).fetchone():
                with db: db.execute('UPDATE iv_control SET paused_at=coalesce(paused_at,?)',(_now(),))
                raise ValueError('検証先の確定済み履歴が見つかりません。復旧まで記録を休止します。')
            maximum = db.execute("SELECT seq FROM sqlite_sequence WHERE name='iv_outbox'").fetchone()
            if target.execute('SELECT 1 FROM iv_receipts WHERE identity=? AND seq>? LIMIT 1',(identity,maximum[0] if maximum else 0)).fetchone():
                with db: db.execute('UPDATE iv_control SET paused_at=coalesce(paused_at,?)',(_now(),))
                raise ValueError('本体の記録番号が巻き戻っています。復元したDBの再基準化が必要です。')
            while True:
                if background and _stops.get(_key(path),threading.Event()).is_set(): break
                batch = db.execute('SELECT id,key,day,saved_at,confirmed_at,kind,content FROM iv_outbox ORDER BY id LIMIT ?', (BATCH,)).fetchall()
                if not batch: break
                with target:
                    for seq,key,day,at,confirmed,kind,value in batch:
                        text = json.dumps([source,key,day,at,confirmed,kind,value],ensure_ascii=False)
                        digest = _receipt_digest(text)
                        old = target.execute('SELECT digest FROM iv_receipts WHERE identity=? AND seq=?',(identity,seq)).fetchone()
                        if old:
                            # 初期の受領は内容の写し（text）をそのまま持つ。どちらの形でも同じ内容なら再送扱い。
                            if old[0] not in (digest, text): raise ValueError('検証記録の同一番号で内容が異なります。')
                            continue
                        version_id = target.execute('INSERT INTO versions(source,key,day,saved_at,kind,content) VALUES(?,?,?,?,?,?)',(source,key,day,at,kind,value)).lastrowid
                        target.execute('INSERT INTO iv_receipts VALUES(?,?,?,?,?)',(identity,seq,digest,confirmed,version_id))
                # 転送先の確定後だけ受領を更新する。
                with db:
                    db.execute('UPDATE iv_control SET delivered_seq=max(delivered_seq,?)',(batch[-1][0],))
                    db.executemany('DELETE FROM iv_outbox WHERE id=?', [(r[0],) for r in batch])
                    db.execute('UPDATE iv_control SET pending_bytes=max(0,pending_bytes-?)',(sum(len((r[6] or '').encode()) for r in batch if r[5]!='baseline'),))
            gap = db.execute('SELECT paused_at FROM iv_control').fetchone()[0]
            if gap:
                with target: target.execute('INSERT OR REPLACE INTO iv_gaps VALUES(?,?,?)',(identity,source,gap))


def wait(root):
    """診断・試験用。通常の画面操作では待たない。"""
    root=Path(root).resolve()
    with _guard: workers=list(_workers.items())
    for path,worker in workers:
        if Path(path).parent.resolve()==root: worker.join(timeout=5)
    for path in list(_known_paths):
        if Path(path).parent.resolve()==root:
            try: flush(path)
            except (sqlite3.Error,OSError,ValueError) as error: _last_error[path]=repr(error)


def state(): return dict(_last_error)


def summary(path, days=7):
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)) as db:
        kinds=db.execute("SELECT source,kind,COUNT(*) FROM versions WHERE key<>'' GROUP BY source,kind").fetchall()
        recent=db.execute("SELECT source,day,COUNT(*),MAX(saved_at) FROM versions WHERE kind<>'baseline' GROUP BY source,day ORDER BY day DESC LIMIT ?",(days*2,)).fetchall()
    return dict(kinds=kinds,recent=recent)


def as_of(path, source, cutoff):
    limit=datetime.fromisoformat(cutoff) if isinstance(cutoff,str) else cutoff
    if limit.tzinfo is None: raise ValueError('締切には時差を含めてください。')
    result={}
    checkpoints=[]
    waiting=[]
    # 検証先にまだ届いていない変更・休止状態を完全な履歴と取り違えない。
    for candidate in Path(path).parent.iterdir():
        if candidate == Path(path) or candidate.suffix not in ('.db','.sqlite3') or not candidate.is_file(): continue
        try:
            with closing(sqlite3.connect(candidate.resolve().as_uri()+'?mode=ro',uri=True,timeout=.05)) as live:
                if not live.execute("SELECT 1 FROM sqlite_master WHERE name='iv_control'").fetchone(): continue
                control=live.execute('SELECT source,paused_at,identity,delivered_seq FROM iv_control').fetchone()
                if not control or control[0]!=source: continue
                checkpoints.append((control[2],control[3]))
                if control[1] and datetime.fromisoformat(control[1])<limit: raise ValueError('検証記録が休止中です。')
                waiting+=[(control[2],seq) for seq,at in live.execute('SELECT id,saved_at FROM iv_outbox') if datetime.fromisoformat(at)<limit]
        except sqlite3.OperationalError:
            raise  # 使用中などで読めない本体は、確かめられないので完全とはしない。
        except sqlite3.DatabaseError:
            continue  # SQLiteではない同名の拡張子のファイル（WindowsのThumbs.dbなど）。
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)) as db:
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for identity,seq in checkpoints:
            if seq and ('iv_receipts' not in tables or not db.execute('SELECT 1 FROM iv_receipts WHERE identity=? AND seq=?',(identity,seq)).fetchone()): raise ValueError('検証履歴の確定済み部分が失われています。')
        # 検証先が受け取り、本体から消す前に止まった行は届いている（受領で照合する）。
        for identity,seq in waiting:
            if 'iv_receipts' not in tables or not db.execute('SELECT 1 FROM iv_receipts WHERE identity=? AND seq=?',(identity,seq)).fetchone():
                raise ValueError('未転送の検証記録があります。')
        # 受領は版の番号（version_id）で引く。索引が無いので、SQLで結合すると版1件ごとに受領を全件読み、
        # 実データ（版16.7万・受領8.3万、2026-10-26）では終わらなかった。先に1回だけ読む。
        received={}
        if 'iv_receipts' in tables:
            received=dict(db.execute('SELECT version_id,confirmed_at FROM iv_receipts WHERE version_id IS NOT NULL'))
        resets=[]
        for version_id,at in db.execute("SELECT id,saved_at FROM versions WHERE source=? AND kind='reset'",(source,)):
            confirmed=received.get(version_id)
            if confirmed and datetime.fromisoformat(confirmed)<limit: resets.append(datetime.fromisoformat(at))
        latest_reset=max(resets,default=None)
        if 'iv_gaps' in tables and any(datetime.fromisoformat(r[0])<limit and (latest_reset is None or datetime.fromisoformat(r[0])>latest_reset) for r in db.execute('SELECT paused_at FROM iv_gaps WHERE source=?',(source,))):
            raise ValueError('検証記録の休止区間があります。入力の完全性は未確認です。')
        for version_id,key,at,value,kind in db.execute('SELECT id,key,saved_at,content,kind FROM versions WHERE source=? ORDER BY id',(source,)):
            if datetime.fromisoformat(at)>=limit: continue
            if version_id in received and (received[version_id] is None or datetime.fromisoformat(received[version_id])>=limit):
                raise ValueError('締切前の保存確定を確認できない記録があります。')
            if kind=='reset': result.clear();continue
            if key=='': continue
            if value is None: result.pop(key,None)
            else: result[key]=json.loads(value)
    return result


def recording_status_lines(directory):
    lines=[]
    for path in Path(directory).glob('*.sqlite3'):
        if path.name==FILE_NAME: continue
        try:
            with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=.05)) as db:
                if not db.execute("SELECT 1 FROM sqlite_master WHERE name='iv_control'").fetchone(): continue
                source,paused=db.execute('SELECT source,paused_at FROM iv_control').fetchone()
                pending=db.execute('SELECT count(*) FROM iv_outbox').fetchone()[0]
                label='長町南・幸町' if source=='meruhen' else 'P’s CUBE'
                lines.append(f'{label}の検証記録：'+(f'休止中（{paused}以降の完全性は未確認）' if paused else f'転送待ち{pending}件'))
                if _key(path) in _last_error: lines.append('直近の転送エラー：'+_last_error[_key(path)])
        except sqlite3.Error: lines.append(f'{path.name}の検証記録：状態を確認できません。')
    return lines or ['検証記録：未開始']


def resume_recording(path):
    """アプリを閉じ、転送先を復旧した後だけ実行する。休止中の過去は埋めない。"""
    path=Path(path)
    if _clients.get(_key(path)): raise ValueError('すべての書き込み接続を閉じてから再開してください。')
    flush(path)
    with closing(sqlite3.connect(path)) as db:
        source,paused=db.execute('SELECT source,paused_at FROM iv_control').fetchone()
        if not paused: return
        if db.execute('SELECT 1 FROM iv_outbox LIMIT 1').fetchone(): raise ValueError('未転送の記録があります。')
        table,key_sql,day_sql=SOURCES[source]
        db.create_function('iv_content',1,content)
        db.create_function('iv_day',1,_day)
        db.create_function('iv_now',0,_now)
        db.create_function('iv_digest',1,lambda raw:hashlib.sha256(content(raw).encode()).hexdigest())
        with db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('UPDATE iv_control SET identity=?,paused_at=NULL,pending_bytes=0,delivered_seq=0',(uuid.uuid4().hex,))
            db.execute("INSERT INTO iv_outbox(key,saved_at,kind) VALUES('',iv_now(),'reset')")
            db.execute(f"INSERT INTO iv_outbox(key,day,saved_at,kind,content) SELECT {key_sql.format(t=table)},{day_sql.format(t=table)},iv_now(),'baseline',iv_content(payload) FROM {table}")
            db.execute('DELETE FROM iv_heads')
            db.execute(f"INSERT INTO iv_heads SELECT {key_sql.format(t=table)},iv_digest(payload) FROM {table}")
        with db: db.execute('UPDATE iv_outbox SET confirmed_at=? WHERE confirmed_at IS NULL',(_now(),))
    flush(path)
