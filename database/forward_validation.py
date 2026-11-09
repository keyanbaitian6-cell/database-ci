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
import subprocess
import threading
from pathlib import Path

import error_log
import pscube_import

JST = dt.timezone(dt.timedelta(hours=9))
LOG_NAME = 'forward-validation.log'
TIMEOUT_SECONDS = 600
_running = threading.Lock()


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


def run(plan, data_dir: Path, *, runner=subprocess.run, now=None) -> tuple[bool, str]:
    """手順を画面を出さずに順に動かす。(すべて成功か, 画面に出す短い文)。同時に2つは動かさない。"""
    if not _running.acquire(blocking=False):
        return False, '前向き検証の保存はすでに動いています'
    started = (now or dt.datetime.now(JST)).isoformat(timespec='seconds')
    try:
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
        text = ('前向き検証を自動で保存しました' if ok else
                '前向き検証の自動保存で止まったものがあります：' +
                (' / '.join(stops) or '終了コード ' + ', '.join(f'{n}={codes[n]}' for n in failed)))
        _append_log(data_dir, started, outs)
        error_log.note(data_dir, 'forward.auto', text)
        return ok, text
    finally:
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
    （report は別のスレッドから呼ばれる。画面へは app.py 側が root.after で渡す）。動かさないときは理由を返す。"""
    plan = steps(Path(outputs or outputs_dir()), Path(python or analysis_python()))
    now = now or dt.datetime.now(JST)
    why = decide(label, message, now, plan)
    if why:
        return why
    worker = thread(target=lambda: report(run(plan, data_dir, runner=runner, now=now)[1]),
                    name='forward-validation', daemon=True)
    worker.start()
    return None
