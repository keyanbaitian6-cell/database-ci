"""Small Tk calendar, using the converter's existing ttk style."""
import calendar
from datetime import date, datetime, timedelta, timezone
import tkinter as tk
from tkinter import ttk


class CalendarPicker(tk.Toplevel):
    def __init__(self, parent, value, selected):
        super().__init__(parent)
        self.title('日付を選択')
        self.resizable(False, False)
        self.transient(parent)
        self.parent = parent
        self.selected = selected
        try:
            current = date.fromisoformat(value)
        except (ValueError, TypeError):
            current = datetime.now(timezone(timedelta(hours=9))).date()
        self.year, self.month = current.year, current.month
        self.value = current
        self.grab_set()
        frame = ttk.Frame(self, padding=14)
        frame.pack()
        header = ttk.Frame(frame)
        header.pack(fill='x', pady=(0, 10))
        ttk.Button(header, text='◀', width=3, command=lambda: self.shift(-1)).pack(side='left')
        self.year_var = tk.StringVar(value=str(self.year))
        self.month_var = tk.StringVar(value=str(self.month))
        ttk.Spinbox(header, from_=1, to=9999, textvariable=self.year_var, width=6).pack(side='left', padx=(8, 2))
        ttk.Label(header, text='年').pack(side='left')
        ttk.Spinbox(header, from_=1, to=12, textvariable=self.month_var, width=3).pack(side='left', padx=(4, 2))
        ttk.Label(header, text='月').pack(side='left')
        ttk.Button(header, text='表示', command=self.show_month).pack(side='left', padx=6)
        ttk.Button(header, text='▶', width=3, command=lambda: self.shift(1)).pack(side='right')
        self.grid_frame = ttk.Frame(frame)
        self.grid_frame.pack()
        self.draw()
        ttk.Button(frame, text='閉じる', command=self.close).pack(anchor='e', pady=(10, 0))
        self.protocol('WM_DELETE_WINDOW', self.close)

    def show_month(self):
        try:
            year, month = int(self.year_var.get()), int(self.month_var.get())
            date(year, month, 1)
        except (ValueError, OverflowError):
            self.year_var.set(str(self.year))
            self.month_var.set(str(self.month))
            return
        self.year, self.month = year, month
        self.draw()

    def shift(self, delta):
        total = self.year * 12 + self.month - 1 + delta
        year, month = divmod(total, 12)
        if not 1 <= year <= 9999:
            return
        self.year, self.month = year, month + 1
        self.year_var.set(str(self.year))
        self.month_var.set(str(self.month))
        self.draw()

    def draw(self):
        for widget in self.grid_frame.winfo_children():
            widget.destroy()
        for col, text in enumerate('日月火水木金土'):
            ttk.Label(self.grid_frame, text=text, anchor='center').grid(row=0, column=col, padx=3, pady=4)
        for row, week in enumerate(calendar.Calendar(firstweekday=6).monthdayscalendar(self.year, self.month), 1):
            for col, day in enumerate(week):
                if not day:
                    continue
                chosen = date(self.year, self.month, day)
                style = 'Accent.TButton' if chosen == self.value else 'TButton'
                ttk.Button(self.grid_frame, text=str(day), width=3, style=style,
                           command=lambda d=chosen: self.pick(d)).grid(row=row, column=col, padx=2, pady=2)

    def pick(self, chosen):
        self.selected(chosen.isoformat())
        self.close()

    def close(self):
        self.grab_release()
        self.destroy()
        if self.parent.winfo_exists():
            self.parent.grab_set()
