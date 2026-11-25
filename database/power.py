"""PCのスリープの扱い（2026-11-06 利用者「取り込み中はスリープ禁止」「取り込み後問題なかったか確認し、5分後にスリープ」）。

- 取り込み窓（P’s CUBE）の自動取り込みがON（休憩・拒否のあとの待機中も）の間は、PCを自動でスリープさせない
  （`keep_awake`、Windows の SetThreadExecutionState。呼んだスレッドが終わると自動で解ける）。画面の消灯は止めない。
- 取り込み後にPCをスリープにする仕組み（11/6の「5分後にスリープ」）は、2026-11-22 利用者「自動スリープは取り消そう」でやめた。
  窓が閉じると日次学習・前向き検証が裏で動き始め、その途中で眠ると前向き検証の9:00の締切を逃すため（日次学習の
  8:00締切は2026-11-25に撤廃）。このアプリからは
  スリープにしない（Windowsの電源設定の自動スリープは、このアプリでは変えない）。
- Windows 以外では何もしない（試験・別の環境で止めない）。
"""
import sys

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


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

