"""Tkを作る試験が、別スレッドで片付けられるTkを残さないこと（2026-10-18）。

PC試験をまとめて流すと、変換画面の試験で作ったTkが循環参照のまま残り、後の test_pscube_auto の
問い合わせ用スレッド（pscube-eval）でGCが走ったときに片付けられて、
「Tcl_AsyncDelete: async handler deleted by the wrong thread」でプロセスごと落ちた（終了コード3）。
GCがいつ走るかはメモリの使われ方しだいで、作業フォルダによって起きたり起きなかったりした。
ここでは「各試験の本体が始まる瞬間に、別スレッドでGCを走らせる」最悪の場合を毎回わざと起こして確かめる。
"""
import gc
import os
import subprocess
import sys
import threading
import tkinter as tk
import unittest
import weakref
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
TESTS = Path(__file__).resolve().parent

# 別プロセスで試験を流し、各試験の本体の直前に別スレッドでGCを走らせる。
# Tkが別スレッドで片付けられたら、その試験名を書き出す（Tclが先にプロセスを落とすこともある）。
PROBE = r'''
import gc, json, sys, threading, tkinter, unittest, weakref
current = ['']
off_main = []
original_init = tkinter.Tk.__init__

def init(self, *args, **kwargs):
    original_init(self, *args, **kwargs)
    made = current[0]
    weakref.finalize(self, lambda: threading.current_thread() is threading.main_thread() or off_main.append(made))

tkinter.Tk.__init__ = init
original_setup = unittest.TestCase._callSetUp
original_call = unittest.TestCase._callTestMethod

def call_setup(self):
    current[0] = self.id()
    return original_setup(self)

def call_test(self, method):
    worker = threading.Thread(target=gc.collect, name='gc-in-another-thread')
    worker.start()
    worker.join()
    return original_call(self, method)

unittest.TestCase._callSetUp = call_setup
unittest.TestCase._callTestMethod = call_test
result = unittest.main(module=None, argv=['probe'] + sys.argv[1:], exit=False).result
print('OFF_MAIN=' + json.dumps(off_main))
sys.exit(0 if result.wasSuccessful() and not off_main else 1)
'''

# Tkを作る試験と、その後で別スレッドを動かす試験（ゲートと同じ名前順）。
MODULES = ['test_anaslo_browser', 'test_anaslo_download_ui', 'test_anaslo_saiwaichou', 'test_pscube_auto']


class TkThreadTests(unittest.TestCase):
    def test_tk_tests_leave_nothing_for_another_thread_to_collect(self):
        # 試験は tests/ にあり、試験から読む本体（core など）は database/ にある。両方を読めるようにする。
        env = dict(os.environ, PYTHONPATH=os.pathsep.join(
            [str(TESTS)] + [p for p in os.environ.get('PYTHONPATH', '').split(os.pathsep) if p]))
        run = subprocess.run([sys.executable, '-c', PROBE, *MODULES], cwd=HERE, env=env,
                             capture_output=True, text=True, encoding='utf-8', errors='replace',
                             stdin=subprocess.DEVNULL, timeout=600)
        tail = (run.stdout + run.stderr)[-3000:]
        self.assertNotIn('Tcl_AsyncDelete', run.stderr, tail)
        self.assertIn('OFF_MAIN=[]', run.stdout, tail)
        self.assertEqual(run.returncode, 0, tail)

    def test_pscube_auto_collects_leftover_tk_on_the_main_thread_first(self):
        # 修正していない試験（Codexの試験など）が残したTkも、pscube-eval が動く前に片付ける。
        import test_pscube_auto
        enabled = gc.isenabled()
        gc.disable()
        try:
            gc.collect()
            freed = []
            root = tk.Tk()
            root.withdraw()
            root.destroy()
            root.cycle = root  # 循環参照：GCでしか片付かない
            weakref.finalize(root, lambda: freed.append(threading.current_thread().name))
            del root
            self.assertEqual(freed, [], 'まだ残っている')
            test_pscube_auto.setUpModule()
            self.assertEqual(freed, [threading.main_thread().name])
        finally:
            if enabled:
                gc.enable()


if __name__ == '__main__':
    unittest.main()
