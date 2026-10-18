"""保存したアナスロのHTMLからの日ごとの「何台中何台プラス」（2026-10-18 利用者「各日の勝率、何台中何台
プラスで終わったかをそれだけを乗せて欲しい」「今回のHTML分ってことね」、html_day_summary.py）。
数え方は core.rack_won と同じ（ジャグラーオンラインの差枚が最優先）、対象外の機種・数値の異常な台は数えない、
ノーマル用JSONの無い日はDBのジャグラー・ハナハナ、閲覧用ファイルには台の数値を足さず集計だけを載せること。"""
import json
from pathlib import Path
import tempfile
import unittest

import core
import html_day_summary as summary
from core import Store, export_viewer


def measurement(end):
    return {'baseline_y': 200.5, 'peak_y': 150.0, 'trough_y': 220.0, 'end_y': 200.5 - end,
            'curve': [[0.5, 200.5], [10.5, 200.5 - end]]}


def rec(day, rack, machine, end=None, **extra):
    row = {'store': 'saiwaichou', 'day': day, 'rack': rack, 'machine': machine, 'source_machine': machine,
           'games': 3000, 'bb': 5, 'rb': 2}
    if end is not None:
        row['graph_measurement'] = measurement(end)
    return {**row, **extra}


def write(folder, name, fmt, records):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(json.dumps({'format': fmt, 'version': 1, 'store': 'saiwaichou', 'records': records},
                                          ensure_ascii=False), encoding='utf-8')


class HtmlDaySummaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.normal, self.other, self.data = root / 'normal', root / 'other', root / 'data'
        self.data.mkdir()
        write(self.other, 'other-analysis-saiwaichou-20250915-20250916.json', 'database-other-analysis', [
            rec('2025-09-15', 1, 'L北斗', 50),        # プラス
            rec('2025-09-15', 2, 'L北斗', -30),       # マイナス
            rec('2025-09-15', 3, 'L北斗', 0.5),       # 1px以内 → プラスにしない
            rec('2025-09-15', 4, 'L北斗', games=0, bb=0, rb=0),   # 未稼働 → 数えない（台数には入る）
            rec('2025-09-15', 5, '沖ドキ!DUO', 80),    # 取り込みの対象外 → 数えない
            rec('2025-09-15', 6, 'L北斗', 80, games=88888888),    # 数値異常 → 数えない
            rec('2025-09-16', 1, 'L北斗', 50),        # ノーマル用JSONもDBも無い日 → 出さない
            rec('2026-08-01', 1, 'L北斗', -10),       # ノーマル用JSONの無い日 → DBのジャグラー
        ])
        write(self.normal, 'normal-analysis-saiwaichou-20250915-20250915.json', 'database-normal-analysis', [
            rec('2025-09-15', 101, 'SアイムジャグラーEX', 20),
            rec('2025-09-15', 102, 'SアイムジャグラーEX', games=2000, bb=0, rb=0),  # 大当たり0回 → マイナス
        ])
        self.db_path = self.data / 'database.sqlite3'
        db = Store(self.db_path)
        try:
            db.save([
                # グラフはマイナスでもジャグラーオンラインの差枚が最優先（+300）。
                dict(rec('2026-08-01', 101, 'SアイムジャグラーEX', -40), kind_code=21, jo_net=300),
                dict(rec('2026-08-01', 102, 'SアイムジャグラーEX', 60), kind_code=21),
                dict(rec('2026-08-01', 900, 'L北斗', 70), kind_code=21),   # DBのその他機種は使わない（HTMLの分を数える）
            ])
        finally:
            db.close()

    def tearDown(self):
        self.tmp.cleanup()

    def build(self):
        return summary.build(self.normal, self.other, self.db_path)

    def test_counts_like_rack_won_and_skips_excluded_racks(self):
        days = {d['day']: d for d in self.build()['days']}
        self.assertEqual(sorted(days), ['2025-09-15', '2026-08-01'])
        first = days['2025-09-15']
        # 台：1〜4・101・102（沖ドキと数値異常は除く）。判定：1(+)・2・3・101(+)・102。
        self.assertEqual((first['racks'], first['judged'], first['won'], first['normal_from']), (6, 5, 2, 'html'))
        later = days['2026-08-01']
        # HTMLのその他機種1番(−)＋DBのジャグラー101(+300、jo_net)・102(+)。DBのその他機種900番は数えない。
        self.assertEqual((later['racks'], later['judged'], later['won'], later['normal_from']), (3, 3, 2, 'database'))

    def test_viewer_file_carries_only_the_day_counts(self):
        result = self.build()
        (self.data / summary.SUMMARY_NAME).write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
        db = Store(self.db_path)
        try:
            export_viewer(db, self.data / 'viewer.json')
        finally:
            db.close()
        doc = json.loads((self.data / 'viewer.json').read_text(encoding='utf-8'))
        self.assertEqual(doc['day_summaries'], [
            {'store': 'saiwaichou', 'day': '2025-09-15', 'racks': 6, 'judged': 5, 'won': 2},
            {'store': 'saiwaichou', 'day': '2026-08-01', 'racks': 3, 'judged': 3, 'won': 2}])
        # 台の記録はDBの分だけ（HTMLの台は足さない）。閲覧用ファイルとして読める。
        self.assertEqual(sorted(r['rack'] for r in doc['records']), [101, 102, 900])
        records, _ = core.read_backup_file(self.data / 'viewer.json', allow_viewer=True)
        self.assertEqual(len(records), 3)

    def test_no_summary_file_or_broken_days_are_left_out(self):
        db = Store(self.db_path)
        try:
            export_viewer(db, self.data / 'viewer.json')
            self.assertNotIn('day_summaries', json.loads((self.data / 'viewer.json').read_text(encoding='utf-8')))
            (self.data / summary.SUMMARY_NAME).write_text(json.dumps({'format': summary.FORMAT, 'version': 1, 'days': [
                {'store': 'saiwaichou', 'day': '2025-09-15', 'racks': 5, 'judged': 5, 'won': 6},
                {'store': 'saiwaichou', 'day': '2025-09-16', 'racks': 5, 'judged': 5, 'won': True},
                {'store': 'elsewhere', 'day': '2025-09-17', 'racks': 5, 'judged': 5, 'won': 1},
                {'store': 'saiwaichou', 'day': '2025-09-18', 'racks': 5, 'judged': 4, 'won': 1},
            ]}), encoding='utf-8')
            export_viewer(db, self.data / 'viewer.json')
        finally:
            db.close()
        self.assertEqual(json.loads((self.data / 'viewer.json').read_text(encoding='utf-8'))['day_summaries'],
                         [{'store': 'saiwaichou', 'day': '2025-09-18', 'racks': 5, 'judged': 4, 'won': 1}])
        (self.data / summary.SUMMARY_NAME).write_text('{broken', encoding='utf-8')
        self.assertEqual(summary.load_days(self.data / summary.SUMMARY_NAME), [])


if __name__ == '__main__':
    unittest.main()
