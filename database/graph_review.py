"""Shared four-point graph confirmation dialog.

Used by the screenshot flow (a cropped picture with auto-detected points from
pixel analysis) and the browser flow (an exact vector curve rendered from the
page's own SVG coordinates). Both hand this dialog a source image plus
suggested points; the user only ever confirms or adjusts before saving.
"""
from __future__ import annotations

from pathlib import Path

import tkinter as tk
from tkinter import messagebox, ttk

from PIL import Image, ImageTk

from screenshot_import import encode_preview_image, graph_auto_points, graph_view


class PointsPickerDialog(tk.Toplevel):
    labels = ('① 赤いゼロ線', '② グラフの最高点', '③ グラフの最低点', '④ グラフ右端の終点')
    colors = ('#ff3b30', '#ffb000', '#3182ce', '#00a884')

    def __init__(self, parent, title, source_image, automatic_points=None,
                 guide_y=None, stat_fields=None, caption='', method='four-point',
                 source_image_name=None):
        super().__init__(parent)
        self.title(title)
        self.geometry('1060x790')
        self.transient(parent)
        self.grab_set()
        self.result = None
        self.stats_result = None
        self.method = method
        self.source_image_name = source_image_name
        self.source = source_image.convert('RGB')
        self.points = []

        max_width, max_height = 1010, 660
        self.scale = min(max_width / self.source.width, max_height / self.source.height, 1.0) or 1.0
        size = (max(1, int(self.source.width * self.scale)), max(1, int(self.source.height * self.scale)))
        display = self.source.resize(size, Image.Resampling.LANCZOS) if size != self.source.size else self.source
        self.photo = ImageTk.PhotoImage(display)

        top = ttk.Frame(self)
        top.pack(fill='x', padx=18, pady=(14, 4))
        self.instruction = tk.StringVar(value=self.labels[0] + 'をクリックしてください。')
        ttk.Label(top, textvariable=self.instruction, font=('Yu Gothic UI', 14, 'bold')).pack(
            side='left', anchor='w')
        # Right at the top, next to where the browser's own capture buttons
        # sit, so confirming a take doesn't need a trip across the window.
        ttk.Button(top, text='採点を確定', command=self._accept).pack(side='right')
        if caption:
            ttk.Label(self, text=caption, foreground='#526274').pack(anchor='w', padx=18, pady=(0, 8))

        self.stat_variables = {}
        if stat_fields:
            stat_frame = ttk.Frame(self)
            stat_frame.pack(fill='x', padx=18, pady=(0, 8))
            ttk.Label(stat_frame, text='数値：').pack(side='left')
            for field, label in (('games', '総回転数'), ('bb', 'BIG'), ('rb', 'REG'), ('max_hold', '最大持玉')):
                if field not in stat_fields or stat_fields[field] is None:
                    continue
                ttk.Label(stat_frame, text=label).pack(side='left', padx=(10, 3))
                variable = tk.StringVar(value=str(stat_fields[field]))
                ttk.Entry(stat_frame, textvariable=variable, width=8).pack(side='left')
                self.stat_variables[field] = variable

        self.canvas = tk.Canvas(self, width=size[0], height=size[1], background='black', cursor='crosshair')
        self.canvas.create_image(0, 0, image=self.photo, anchor='nw')
        if guide_y is not None:
            y = guide_y * self.scale
            self.canvas.create_line(0, y, size[0], y, fill='#ff8a80', dash=(6, 4), tags='suggestion')
        if automatic_points:
            for x, y in automatic_points:
                self._add_point(x, y)
            self.instruction.set('4点を自動検出しました。位置を確認して「採点を確定」を押してください。')
        self.canvas.pack(padx=18, fill='both', expand=True)
        self.canvas.bind('<Button-1>', self._click)
        buttons = ttk.Frame(self)
        buttons.pack(fill='x', padx=18, pady=12)
        ttk.Button(buttons, text='1つ戻す', command=self._undo).pack(side='left')
        ttk.Button(buttons, text='キャンセル', command=self.destroy).pack(side='right')

        # Enterで確定・Escでキャンセル。自動検出がほぼ正しい台では、マウスを
        # 「採点を確定」まで運ぶ代わりにキーボードだけで進められるようにする。
        self.bind('<Return>', lambda _e: self._accept())
        self.bind('<Escape>', lambda _e: self.destroy())

    def _add_point(self, x, y):
        sx, sy = x * self.scale, y * self.scale
        index = len(self.points)
        radius = 6
        self.canvas.create_oval(sx - radius, sy - radius, sx + radius, sy + radius,
                                fill=self.colors[index], outline='white', width=2, tags='marker')
        self.canvas.create_text(sx + 10, sy - 10, text=str(index + 1), fill='white', anchor='w', tags='marker')
        self.points.append((x, y))

    def _click(self, event):
        if len(self.points) >= 4:
            return
        x = self.canvas.canvasx(event.x) / self.scale
        y = self.canvas.canvasy(event.y) / self.scale
        self._add_point(x, y)
        if len(self.points) < 4:
            self.instruction.set(self.labels[len(self.points)] + 'をクリックしてください。')
        else:
            self.instruction.set('4点を確認し、「採点を確定」を押してください。')

    def _undo(self):
        if not self.points:
            return
        self.points.pop()
        self.canvas.delete('marker')
        remaining = self.points[:]
        self.points = []
        for x, y in remaining:
            self._add_point(x, y)
        self.instruction.set(self.labels[len(self.points)] + 'をクリックしてください。')

    def _accept(self):
        if len(self.points) != 4:
            messagebox.showerror('4点が必要です', 'ゼロ線、最高点、最低点、終点の順に4か所を指定してください。', parent=self)
            return
        try:
            stats = {field: int(variable.get().strip()) for field, variable in self.stat_variables.items()}
            if any(value < 0 for value in stats.values()):
                raise ValueError
        except ValueError:
            messagebox.showerror('数字を確認してください', '総回転数・BIG・REG・最大持玉は0以上の整数で入力してください。', parent=self)
            return
        (bx, by), (px, py), (tx, ty), (ex, ey) = self.points
        preview_b64, preview_w, preview_h = encode_preview_image(self.source)
        result = dict(baseline_x=bx, baseline_y=by, peak_x=px, peak_y=py,
                     trough_x=tx, trough_y=ty, end_x=ex, end_y=ey,
                     preview_image=preview_b64, preview_width=preview_w, preview_height=preview_h,
                     method=self.method)
        if self.source_image_name:
            result['source_image'] = self.source_image_name
        self.result = result
        self.stats_result = stats
        self.destroy()


def from_screenshot(parent, image_path, rack, graph_stats=None):
    """Build the picker for a saved screenshot (pixel-analysis auto-detection)."""
    image_path = Path(image_path)
    source, _offset, suggested = graph_view(image_path)
    automatic = graph_auto_points(source, suggested)
    return PointsPickerDialog(
        parent, f'{rack}番台 グラフ確認', source,
        automatic_points=automatic, guide_y=suggested,
        stat_fields=graph_stats, caption=image_path.name,
        method='screenshot-four-point', source_image_name=image_path.name)
