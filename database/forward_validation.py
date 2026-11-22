"""P-STATION の前向き検証（研究用の記録）を、取り込みが最後まで終わって取り込み窓が自分で閉じたときに自動で保存する。

2026-11-09 利用者「取り込み完了して取得ブラウザが閉じられたときのみ自動実行とかできる？」→「はいお願いします」。

- 動かすのは、リポジトリの外 `../../outputs/` の研究用スクリプト。手で押す `pstation-forward-20261108/毎朝実行.cmd` と
  同じ3つの手順を、同じ順で直接動かす（cmd を画面なしで動かすと、日本語の行の読み取りが崩れることがあったため。2026-11-09 実測）。
    1. 前向き検証v1：`pstation-forward-20261108/forward.py daily`
    2. 1が成功し `viewer-sync-dir.txt` があれば、iPhone用の書き出し：`database/pscube_validation_export.py`
    3. 前向き検証v2（学習版A・B・Cと現行）：`pstation-forward-20261110/forward2.py morning`（1・2の成否に関係なく動かす）
  研究用の記録はこのアプリのDBを読み取り専用で読むだけで、DB・採点・同期・公開は変えない。サイトにも接続しない。
- 動かすのは次のときだけ：
  - サイトセブン：自動取り込みが最後まで終わり、窓が自分で閉じたとき（完了の知らせがあるとき）。
  - P’s CUBE：窓が自分で閉じ、知らせが完了（「すべて取り込みました」）のとき。403などで止まって閉じたときは動かさない。
  - 日本時間の0:00〜8:59。前向き検証は「その日の朝9時より前に、その日の分」を保存する決まりなので、それ以外の時刻は何もしない。
- 利用者が×で閉じたとき・途中で止まったときは知らせが無いので動かさない（app.py の watch_capture_window が after_auto を呼ばない）。
- スクリプトが無いPC（別の環境）では何もしない。失敗しても取り込みとDBには影響しない。手で `毎朝実行.cmd` を押す方法も残る。
"""
from __future__ import annotations

import datetime as dt
import json
import subprocess
import threading
from pathlib import Path

import error_log
import pscube_import

JST = dt.timezone(dt.timedelta(hours=9))
LOG_NAME = 'forward-validation.log'
STATE_NAME = 'forward-validation-state.json'
TIMEOUT_SECONDS = 600
MAX_PENDING_ATTEMPTS = 2
_running = threading.Lock()
_state_lock = threading.Lock()
_queued: dict | None = None
_queued_reports: list = []


def outputs_dir() -> Path:
    # database-main/database から見て ../../outputs（このPCの作業フォルダの並び）。
    return Path(__file__).resolve().parents[2] / 'outputs'


def analysis_python() -> Path:
    # 毎朝実行.cmd と同じ Python（numpy・pandas が入っている）。
    return Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'


def steps(outputs: Path, python: Path) -> list[tuple[str, list[str], Path]] | str:
    """動かす手順（名前, 引数, 作業フォルダ）。足りないものがあれば理由の文。"""
    v1, v2 = outputs / 'pstation-forward-20261108', outputs / 'pstation-forward-20261110'
    export = Path(__file__).resolve().parent / 'pscube_validation_export.py'
    for need in (python, v1 / 'forward.py', v2 / 'forward2.py'):
        if not need.is_file():
            return f'前向き検証のファイルがありません（{need.name}）'
    run = [str(python), '-B', '-X', 'utf8']
    out = [('v1', run + [str(v1 / 'forward.py'), 'daily'], v1)]
    sync = v1 / 'viewer-sync-dir.txt'
    if sync.is_file() and export.is_file():
        out.append(('export', run + [str(export), '--records', str(v1 / 'records'), '--out-dir-file', str(sync)], v1))
    out.append(('v2', run + [str(v2 / 'forward2.py'), 'morning'], v2))
    return out


def in_window(now: dt.datetime) -> bool:
    """日本時間の 0:00:00〜8:59:59 か。PCの地域設定に頼らず、UTC+9 に直して決める。"""
    if now.tzinfo is None:
        raise ValueError('時刻にはタイムゾーンが必要です。')
    return now.astimezone(JST).hour < 9


def in_evening_window(now: dt.datetime) -> bool:
    """日本時間の 23:30:00〜23:59:59 か。この間に取り込みが完了したときは翌0時以降に流す印を残す。"""
    if now.tzinfo is None:
        raise ValueError('時刻にはタイムゾーンが必要です。')
    local = now.astimezone(JST)
    return local.hour == 23 and local.minute >= 30


def _read_state(data_dir: Path) -> dict:
    path = Path(data_dir) / STATE_NAME
    try:
        if not path.is_file():
            return {}
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_state(data_dir: Path, state: dict) -> bool:
    folder = Path(data_dir)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        tmp = folder / f'{STATE_NAME}.tmp'
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        tmp.replace(folder / STATE_NAME)
        return True
    except OSError as error:
        error_log.record(folder, 'forward.state', error)
        return False


def record_pending(data_dir: Path, label: str, now: dt.datetime) -> bool:
    """23:30〜23:59に窓が自分で閉じて完了したとき、翌日分の対象日を印として残す。"""
    local = now.astimezone(JST)
    target = (local.date() + dt.timedelta(days=1)).isoformat()
    with _state_lock:
        state = _read_state(data_dir)
        if state.get('pending_target') != target:
            state.pop('used_count', None)
        state['pending_target'] = target
        state['pending_label'] = label
        state['pending_at'] = local.isoformat(timespec='seconds')
        return _write_state(data_dir, state)


def _record_done(data_dir: Path, now: dt.datetime) -> None:
    """run() がすべて成功（終了コード0）したときだけ、その日の成功を記録する。"""
    local = now.astimezone(JST)
    target = local.date().isoformat()
    with _state_lock:
        state = _read_state(data_dir)
        state['done_target'] = target
        state['done_at'] = local.isoformat(timespec='seconds')
        _write_state(data_dir, state)


def finished(label: str, message) -> bool:
    """取り込み窓が自分で閉じたときの知らせが「最後まで取り込めた」ものか。"""
    if not message:
        return False
    if label == 'サイトセブン':
        # サイトセブンの窓は自動取り込みが最後まで終わったときだけ知らせを残して閉じる（site777_browser.close_when_finished）。
        return True
    if label == 'P’s CUBE':
        return pscube_import.capture_complete(message)
    return False


def decide(label: str, message, now: dt.datetime, plan) -> str | None:
    """動かすなら None、動かさないならその理由。plan は steps() の戻り値。"""
    if not finished(label, message):
        return '最後まで取り込めたときだけ動かします'
    if not in_window(now):
        return '0時〜9時の間だけ動かします（その日の分は9時が締切）'
    if isinstance(plan, str):
        return plan
    return None


def _resolve_now(now) -> dt.datetime:
    value = now() if callable(now) else now
    return (value or dt.datetime.now(JST)).astimezone(JST)


def _run_once(plan, data_dir: Path, *, runner=subprocess.run, now=None) -> tuple[bool, str]:
    current = _resolve_now(now)
    started = current.isoformat(timespec='seconds')
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    codes, outs = {}, []
    for name, args, cwd in plan:
        if name == 'export' and codes.get('v1') != 0:
            continue   # 毎朝実行.cmd と同じく、v1が止まったら書き出さない
        try:
            result = runner(args, cwd=str(cwd), stdin=subprocess.DEVNULL, capture_output=True,
                            timeout=TIMEOUT_SECONDS, creationflags=flags)
            out = (result.stdout or b'').decode('utf-8', 'replace') + (result.stderr or b'').decode('utf-8', 'replace')
            code = result.returncode
        except (OSError, subprocess.SubprocessError) as error:
            out, code = f'{type(error).__name__}: {error}', -1
        codes[name] = code
        outs.append(f'--- {name} 終了コード {code}\n{out.rstrip()}')
    stops = [line.strip() for text in outs for line in text.splitlines() if line.strip().startswith('停止:')]
    failed = [name for name, code in codes.items() if code != 0]
    ok = not failed
    if ok:
        _record_done(Path(data_dir), current)
    text = ('前向き検証を自動で保存しました' if ok else
            '前向き検証の自動保存で止まったものがあります：' +
            (' / '.join(stops) or '終了コード ' + ', '.join(f'{n}={codes[n]}' for n in failed)))
    _append_log(data_dir, started, outs)
    error_log.note(data_dir, 'forward.auto', text)
    return ok, text


def run(plan, data_dir: Path, *, runner=subprocess.run, now=None, _report=None) -> tuple[bool, str]:
    """手順を画面を出さずに順に動かす。(すべて成功か, 画面に出す短い文)。同時に2つは動かさない。
    動いている間に届いた次の完了の知らせは捨てずに控え、先の実行が終わったあとに締切（9時）内なら1回だけ流す。"""
    global _queued
    if not _running.acquire(blocking=False):
        with _state_lock:
            _queued = {'plan': plan, 'data_dir': Path(data_dir), 'runner': runner, 'now': now}
            if _report is not None:
                _queued_reports.append(_report)
        return False, '前向き検証の保存はすでに動いています（終わったあとに続けて保存します）'
    try:
        ok, text = _run_once(plan, Path(data_dir), runner=runner, now=now)
        if _report is not None:
            _report(text)
        while True:
            with _state_lock:
                nxt = _queued
                reports = list(_queued_reports)
                _queued = None
                _queued_reports.clear()
            if nxt is None:
                break
            next_now = _resolve_now(nxt['now'])
            if not in_window(next_now):
                late = '0時〜9時の間だけ動かします（その日の分は9時が締切）'
                for cb in reports:
                    cb(late)
                break
            _, next_text = _run_once(nxt['plan'], nxt['data_dir'], runner=nxt['runner'], now=next_now)
            for cb in reports:
                cb(next_text)
        return ok, text
    finally:
        with _state_lock:
            _queued = None
            _queued_reports.clear()
        _running.release()


def _append_log(data_dir, started, outs):
    try:
        with (Path(data_dir) / LOG_NAME).open('a', encoding='utf-8') as f:
            f.write(f'===== {started}\n' + '\n'.join(outs) + '\n')
    except OSError:
        pass  # 記録の失敗で取り込みの画面を止めない


def start(label, message, data_dir, report, *, outputs=None, python=None, now=None,
          thread=threading.Thread, runner=subprocess.run):
    """取り込み窓が自分で閉じたときに app.py から呼ぶ。条件に合えば裏で動かし、終わったら report(文) を呼ぶ
    （report は別のスレッドから呼ばれる。画面へは app.py 側が root.after で渡す）。
    23:30〜23:59に完了したときは翌0時以降に流す印を残す。0:00〜8:59に完了したときは印があっても止めず毎回動かす。
    動かさないときは理由を返す。"""
    plan = steps(Path(outputs or outputs_dir()), Path(python or analysis_python()))
    current = (now() if callable(now) else now) or dt.datetime.now(JST)
    data_dir = Path(data_dir)
    if finished(label, message) and in_evening_window(current):
        if isinstance(plan, str):
            return plan
        if record_pending(data_dir, label, current):
            return '0時〜9時の間に自動で保存します（23:30以降の取り込み完了を記録しました）'
        return '23:30以降の取り込み完了を記録できませんでした'
    why = decide(label, message, current, plan)
    if why:
        return why
    worker = thread(target=lambda: run(plan, data_dir, runner=runner, now=now, _report=report),
                    name='forward-validation', daemon=True)
    worker.start()
    return None


def start_pending(data_dir, report, *, outputs=None, python=None, now=None,
                  thread=threading.Thread, runner=subprocess.run) -> str | None:
    """前夜23:30〜23:59に取り込み完了の印があり、0:00〜8:59で当日の成功記録がまだ無ければ、
    印を「使った」と書いてから裏で動かす（失敗・中断したときは9時までに1回だけ再試行できる）。
    動かしたときは None、動かさないときはその理由を返す。"""
    current = (now() if callable(now) else now) or dt.datetime.now(JST)
    if not in_window(current):
        return '0時〜9時の間だけ動かします（その日の分は9時が締切）'
    plan = steps(Path(outputs or outputs_dir()), Path(python or analysis_python()))
    if isinstance(plan, str):
        return plan
    data_dir = Path(data_dir)
    local = current.astimezone(JST)
    target = local.date().isoformat()
    with _state_lock:
        state = _read_state(data_dir)
        if state.get('done_target') == target:
            return '本日の前向き検証はすでに自動保存済みです'
        if state.get('pending_target') != target:
            return '前夜23:30以降の取り込み完了の記録がありません'
        used_count = (int(state.get('used_count', 1)) if isinstance(state.get('used_count'), int) else 1) \
            if state.get('used_target') == target else 0
        if used_count >= MAX_PENDING_ATTEMPTS:
            return '前夜23:30以降の取り込み完了の印はすでに実行済みです'
        if _running.locked():
            return '前向き検証の保存はすでに動いています'
        state['used_target'] = target
        state['used_count'] = used_count + 1
        state['used_at'] = local.isoformat(timespec='seconds')
        if not _write_state(data_dir, state):
            return '前向き検証の印を更新できませんでした'
    worker = thread(target=lambda: run(plan, data_dir, runner=runner, now=now, _report=report),
                    name='forward-validation', daemon=True)
    worker.start()
    return None


MERUHEN_STORES = (('nagamachiminami', '長町南'), ('saiwaichou', '幸町'))
SHADOW_CUTOFF_HOUR = 8


def _read_only(path: Path):
    import sqlite3
    return sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=1)


def meruhen_note(data_dir, since: str, now: dt.datetime | None = None) -> str | None:
    """メルヘンの取り込み窓が閉じたとき、記録欄に出す1行（2026-11-16 利用者「ちょっときになるからメルヘンも出すようにして」）。

    メルヘン（長町南・幸町）が入る前向き検証は、店舗別の候補比較（NEXT_DAY_SHADOW_PLAN_20261025.md）の入力の版の記録で、
    PCがDBを開いている間に自動でたまる（input_versions.py）。この窓で取り込んだ日（since 以降に版が記録された日）ごとに、
    締切（翌日の朝8時、日本時間）より前に版がある台の数を、その日の台数と並べて出す。成績は読まない。
    取り込んだ日が無ければ None。読めないときは理由の文。"""
    import contextlib
    import sqlite3
    data_dir = Path(data_dir)
    now = (now or dt.datetime.now(JST)).astimezone(JST)
    main, log = data_dir / 'database.sqlite3', data_dir / 'input_versions.sqlite3'
    try:
        keys: dict[str, dict[str, str]] = {}   # 日 → {台のキー: いちばん早い記録の時刻}
        touched = set()
        # 取り込む日はサイトが見せる範囲（メルヘンは数日）なので、窓を開いた日の60日前より古い日は見ない（日の索引で速く引く）。
        oldest = (dt.datetime.fromisoformat(since).date() - dt.timedelta(days=60)).isoformat()
        sources = []
        if log.is_file():
            sources.append((log, "SELECT key,day,saved_at FROM versions WHERE source='meruhen' AND day IN ({days})",
                            "SELECT DISTINCT day FROM versions WHERE source='meruhen' AND day>=? AND saved_at>=?"))
        if main.is_file():
            sources.append((main, "SELECT key,day,saved_at FROM iv_outbox WHERE key<>'' AND day IN ({days})",
                            "SELECT DISTINCT day FROM iv_outbox WHERE key<>'' AND day>=? AND saved_at>=?"))
        for path, _rows, recent in sources:
            with contextlib.closing(_read_only(path)) as db:
                try:
                    touched |= {r[0] for r in db.execute(recent, (oldest, since))}
                except sqlite3.OperationalError:
                    continue   # 記録をまだ始めていないDB（iv_outbox が無い）
        if not touched:
            return None
        days = sorted(touched)[-3:]
        marks = ','.join('?' * len(days))
        for path, rows, _recent in sources:
            with contextlib.closing(_read_only(path)) as db:
                try:
                    for key, day, saved in db.execute(rows.format(days=marks), days):
                        first = keys.setdefault(day, {})
                        if key not in first or saved < first[key]:
                            first[key] = saved
                except sqlite3.OperationalError:
                    continue
        totals = {}
        if main.is_file():
            with contextlib.closing(_read_only(main)) as db:
                for store, day, count in db.execute(
                        f'SELECT store,day,COUNT(*) FROM days WHERE day IN ({marks}) GROUP BY store,day', days):
                    totals[(store, day)] = count
    except (sqlite3.Error, OSError) as error:
        return f'前向き検証（メルヘン）：記録を確かめられませんでした（{type(error).__name__}）'
    parts = []
    for day in days:
        cutoff = dt.datetime.fromisoformat(day).replace(tzinfo=JST) + dt.timedelta(days=1, hours=SHADOW_CUTOFF_HOUR)
        stores = []
        for store, label in MERUHEN_STORES:
            total = totals.get((store, day), 0)
            if not total:
                continue
            done = sum(1 for key, saved in keys.get(day, {}).items()
                       if key.startswith(store + '\t') and dt.datetime.fromisoformat(saved) < cutoff)
            stores.append(f'{label} {done}/{total}台')
        when = f'{cutoff.month}/{cutoff.day} {cutoff.hour}:00'
        state = (f'締切（{when}）より前に記録' if now < cutoff else
                 f'締切（{when}）までに記録した台だけが比較に入ります')
        stamp = f'{int(day[5:7])}/{int(day[8:10])}分'
        parts.append(f'{stamp}：' + ('・'.join(stores) or '台の記録なし') + f'（{state}）')
    return '前向き検証（メルヘン・店舗別の候補比較）：' + ' / '.join(parts)
