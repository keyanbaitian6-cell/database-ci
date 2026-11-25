"""既存レポートへ固定予測を表示する。候補計算と研究の関数は変更しない。

2026-11-12：PCの窓・Android・iPhone閲覧ページ・共有カレンダーと同じ順・意味にそろえた
（重要な注意 → 候補数 → 機種ごとの候補（大きな台番号・採用方式のラベル）→ 開閉式の説明）。"""
from datetime import date, datetime, timedelta
from html import escape
import json
from pathlib import Path

BADGE = ('display:inline-block;padding:2px 10px;border-radius:999px;font-size:12px;'
         'background:{bg};color:{fg};font-weight:{weight}')
RACK = ('display:inline-block;min-width:64px;margin:0 6px 6px 0;padding:4px 10px;border-radius:8px;'
        'background:#f2f2f4;font-size:22px;font-weight:700;font-variant-numeric:tabular-nums;vertical-align:top')
ALERT = 'margin:8px 0;padding:8px 12px;border:1px solid #b37413;border-radius:8px;background:#fff8e8'


def report_panel(data_dir, day, location, machine=None, *, now=None):
    from daily_learning import JST
    from daily_learning_view import METHOD_TEXT, daily_view, date_label, time_label
    target = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
    lead = (f'<section class="candidate"><h2>日次学習・採用中の候補</h2><p>対象日 {escape(date_label(target))}。'
            '下の★・☆は従来方式の参考です。</p>')
    try:
        doc = json.loads((Path(data_dir) / 'daily-learning.json').read_text(encoding='utf-8'))
        if doc.get('format') != 'daily-learning' or doc.get('version') != 1:
            raise ValueError('形式不正')
        view = daily_view(doc, location, target, now or datetime.now(JST))
        groups = []
        for g in view['groups']:
            if machine is not None and g['name'] not in (machine, 'バラエティ'):
                continue
            racks = [(r, m) for r, m in g['racks'] if machine is None or (m or g['name']) == machine]
            if racks:
                groups.append(g | {'racks': racks})
        alerts = [a for a in view['alerts'] if not a.startswith('この日の保存済み候補はありません')]
        if not groups:
            alerts.append('この日の保存済み事前予測はありません。画面を開いても予測を作り直しません。')
        parts = [f'<div style="{ALERT}">' + ''.join(f'<p>{escape(a)}</p>' for a in alerts) + '</div>' if alerts else '']
        count = sum(len(g['racks']) for g in groups)
        if count:
            parts.append(f'<p><strong style="font-size:20px">{count}台</strong>　最終処理 {escape(time_label(view["updated"]))}（日本時間）</p>')
        for g in groups:
            learned = g['learned']
            badge = BADGE.format(bg='#e8f1fd' if learned else '#e6e6e8', fg='#0066cc' if learned else '#1d1d1f',
                                 weight=700 if learned else 400)
            racks = ''.join(f'<span style="{RACK}">{r}<small style="font-size:12px;font-weight:400;color:#707070">番</small>'
                            + (f'<br><small style="font-size:11px;font-weight:400;color:#707070">{escape(m)}</small>' if m else '')
                            + '</span>' for r, m in g['racks'])
            parts.append(f'<div style="margin:10px 0;overflow-wrap:anywhere"><p><strong>{escape(g["name"])}</strong> '
                         f'<span style="{badge}">採用中 {"日次学習版" if learned else "従来方式"}</span> {len(g["racks"])}台</p>'
                         f'<div>{racks}</div><details><summary>採用方式の説明・保存時刻</summary>'
                         f'<p>{escape(g["status"])}</p><p>{escape(METHOD_TEXT[learned])}</p>'
                         f'<p>保存 {escape(time_label(g["saved"]))}（日本時間）</p></details></div>')
        status = [f'{s}' for s in view['mine'] + view['general']]
        parts.append('<details><summary>処理状況・日次学習について</summary>'
                     + ''.join(f'<p>{escape(s)}</p>' for s in status)
                     + '<p>PCで対象日の前日23:30〜当日23:30に保存した候補を表示します。画面を開いても予測を作り直しません。</p></details>')
        return lead + ''.join(parts) + '</section>'
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        return lead + '<p>日次学習の記録がまだ届いていません。PCの日次学習画面を確認してください。</p></section>'
