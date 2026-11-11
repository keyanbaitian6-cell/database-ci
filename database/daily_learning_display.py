"""既存レポートへ固定予測を表示する。候補計算と研究の関数は変更しない。"""
from datetime import date, timedelta
from html import escape
import json
from pathlib import Path


def report_panel(data_dir, day, location, machine=None):
    target = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
    lead = f'<section class="candidate"><h2>日次学習・採用中の候補</h2><p>対象日 {escape(target)}。下の★・☆は従来方式の参考です。</p>'
    try:
        doc = json.loads((Path(data_dir) / 'daily-learning.json').read_text(encoding='utf-8'))
        if doc.get('format') != 'daily-learning' or doc.get('version') != 1:
            raise ValueError('形式不正')
        groups = [g for d in doc['days'] if d['target'] == target for g in d['groups']
                  if g['store'] == location and (machine is None or g['name'] in (machine, 'バラエティ'))]
        lines = [f'<p>{escape(doc["status"])}<br>最終処理 {escape(doc["updated_at"])}</p>']
        for g in groups:
            method = '日次学習版' if g['active'] == 'learned' else '従来方式'
            items = [i for i in g['selected'] if machine is None or i[2] == machine]
            lines.append(f'<p>{escape(g["name"])}／採用中 {method}／{escape(g["status"])}<br>' +
                         '、'.join(f'{i[3]}番 {escape(i[2])}' for i in items) + '</p>')
        if not groups:
            lines.append('<p>この日の保存済み事前予測はありません。午前8時以降は作り直しません。</p>')
        return lead + ''.join(lines) + '</section>'
    except (OSError, ValueError, KeyError, TypeError):
        return lead + '<p>日次学習の記録がまだ届いていません。PCの日次学習画面を確認してください。</p></section>'
