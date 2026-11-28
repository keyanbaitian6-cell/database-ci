"""取り込みタブが縦にスクロールできることの再発確認（2026-11-28 利用者「機能加えたら見切れてる」）。

一括取り込みのボタンと窓ごとの状態の行が増え、取り込みタブの下の段・説明が窓の外に隠れた。
取り込みタブ・同期タブは app.scroll_page で作り、中身が窓より高くなっても最後まで見られるようにする。
"""
import inspect
import tkinter as tk
import unittest
from tkinter import ttk

import app


class HomeTabScrollTest(unittest.TestCase):
    def test_home_and_sync_tabs_use_scroll_page(self):
        source = inspect.getsource(app.main)
        self.assertIn('home_page, tab_home = scroll_page(notebook)', source)
        self.assertIn('sync_page, tab_sync = scroll_page(notebook)', source)
        self.assertIn("notebook.add(home_page, text='  取り込み  ')", source)

    def test_tall_content_can_scroll_to_the_end(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f'画面がない環境：{exc}')
        try:
            root.geometry('920x400')
            notebook = ttk.Notebook(root)
            notebook.pack(fill='both', expand=True)
            page, inner = app.scroll_page(notebook)
            notebook.add(page, text='取り込み')
            for i in range(40):
                ttk.Label(inner, text=f'行 {i}').pack(anchor='w')
            root.update()
            canvas = page.winfo_children()[0]
            self.assertLess(canvas.yview()[1], 1.0)  # 収まらない＝最初は下が隠れている
            canvas.yview_moveto(1.0)
            root.update()
            self.assertEqual(canvas.yview()[1], 1.0)  # スクロールで最後まで見られる
        finally:
            root.destroy()


if __name__ == '__main__':
    unittest.main()
