"""PC既存画面から日次学習の保存済み候補を表示する。"""
import json
from pathlib import Path
import queue
import threading
from tkinter import ttk
import tkinter as tk

from daily_learning_runtime import run, FILE_NAME

NAMES = {'nagamachiminami': '長町南', 'saiwaichou': '幸町', 'pscube:c740601:20': 'P-STATION'}


class DailyLearningWorker:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.thread = None
        self.results = queue.Queue()

    def start(self):
        if self.thread is not None and self.thread.is_alive():
            return False
        def work():
            try:
                result = run(self.data_dir)
                self.results.put(result['status'])
            except Exception as error:
                import error_log
                error_log.note(self.data_dir, 'daily-learning', f'{type(error).__name__}: {error}')
                self.results.put('日次学習で処理失敗。従来候補を利用できます。日次学習画面を確認してください。')
        self.thread = threading.Thread(target=work, name='daily-learning', daemon=True)
        self.thread.start()
        return True


def show(root, data_dir):
    window = tk.Toplevel(root)
    window.title('日次学習・採用中の候補')
    window.geometry('760x600')
    text = tk.Text(window, wrap='word', font=('', 11))
    scroll = ttk.Scrollbar(window, command=text.yview)
    text.configure(yscrollcommand=scroll.set)
    scroll.pack(side='right', fill='y')
    text.pack(fill='both', expand=True)
    def refresh():
        text.configure(state='normal')
        text.delete('1.0', 'end')
        try:
            doc = json.loads((Path(data_dir) / FILE_NAME).read_text(encoding='utf-8'))
            text.insert('end', f"最終処理 {doc['updated_at']}\n{doc['status']}\n\n")
            for day in doc['days']:
                text.insert('end', f"対象日 {day['target']}　元データ {day['input_day']}\n")
                for g in day['groups']:
                    method = '日次学習版' if g['active'] == 'learned' else '従来方式'
                    text.insert('end', f"{NAMES.get(g['store'], g['store'])}　{g['name']}　採用中 {method}\n{g['status']}\n保存 {g.get('saved_at', day['saved_at'])}\n")
                    text.insert('end', '、'.join(f'{v[3]}番 {v[2]}' for v in g['selected']) + '\n\n')
            if not doc['days']:
                text.insert('end', '保存済みの事前予測はまだありません。\n')
            text.insert('end', '午前8時が締切です。古い対象日の候補を本日の予測に読み替えないでください。\n毎日学習しても毎日の改善を保証しません。点数は設定確率・収益性ではありません。')
        except (OSError, ValueError, KeyError):
            text.insert('end', '日次学習の記録を読めません。PCの自動処理・保存先を確認してください。従来候補は引き続き参考にできます。')
        text.configure(state='disabled')
    ttk.Button(window, text='保存済み結果を再表示', command=refresh).pack()
    refresh()
