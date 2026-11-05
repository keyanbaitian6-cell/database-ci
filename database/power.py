"""PCのスリープの扱い（2026-11-06 利用者「取り込み中はスリープ禁止」「取り込み後問題なかったか確認し、5分後にスリープ」）。

- 取り込み窓（P’s CUBE）の自動取り込みがON（休憩・拒否のあとの待機中も）の間は、PCを自動でスリープさせない
  （`keep_awake`、Windows の SetThreadExecutionState。呼んだスレッドが終わると自動で解ける）。画面の消灯は止めない。
- 自動取り込みが終わって取り込み窓が自分で閉じたら、親画面が結果を確かめ（`pscube_import.capture_problems`）、
  5分後にスリープする（`sleep_now`）。5分の間は取り消せる。利用者が窓を自分で閉じたときはスリープしない。
- Windows 以外では何もしない（試験・別の環境で止めない）。
"""
import sys

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
SLEEP_DELAY_SECONDS = 300


def _kernel32():
    if sys.platform != 'win32':
        return None
    import ctypes
    return ctypes.windll.kernel32


def keep_awake(on, kernel32=None):
    """このスレッドが動いている間、PCを自動でスリープさせない（on=False で解く）。できたらTrue。"""
    kernel32 = kernel32 or _kernel32()
    if kernel32 is None:
        return False
    flags = ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0)
    return bool(kernel32.SetThreadExecutionState(flags))


def sleep_now(powrprof=None):
    """PCをスリープにする（休止状態ではなくスリープ。強制しない＝ほかのアプリが止めていれば従う）。できたらTrue。"""
    if powrprof is None:
        if sys.platform != 'win32':
            return False
        import ctypes
        powrprof = ctypes.windll.powrprof
    return bool(powrprof.SetSuspendState(False, False, False))
