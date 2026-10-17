"""翌日の曜日傾向の補足（幸町のジャグラー・ハナハナ、表示専用）。Android `normal_day_context.dart` と同じ規則・文。"""
import re
import tempfile
import unittest
from pathlib import Path

from core import Store, report, summary_report
from normal_day_context import AVAILABLE_FROM, EVIDENCE, normal_day_context, normal_day_context_html

ROOT = Path(__file__).resolve().parents[2]


class NormalDayContextTests(unittest.TestCase):
    def test_next_day_weekend_or_weekday_only_for_saiwaichou_normal_types(self):
        friday = normal_day_context('saiwaichou', '2026-10-23', ['SマイジャグラーVKD'])
        self.assertEqual((friday['target_day'], friday['weekend']), ('2026-10-24', True))
        self.assertEqual(friday['title'], '10/24（土）の曜日傾向：土日')
        sunday = normal_day_context('saiwaichou', '2026-10-25', ['SキングハナハナSP−30'])
        self.assertEqual((sunday['target_day'], sunday['weekend']), ('2026-10-26', False))
        self.assertIn('該当しません', sunday['body'])
        self.assertIsNone(normal_day_context('nagamachiminami', '2026-10-23', ['SマイジャグラーVKD']))
        self.assertIsNone(normal_day_context('saiwaichou', '2026-10-23', ['L ゴッドイーター']))
        # 分析を確定した日より前の日には出さない（過去の予測へ遡らない）。日付の形が違うものも出さない。
        self.assertIsNone(normal_day_context('saiwaichou', '2026-10-16', ['SマイジャグラーVKD']))
        for bad in ('2026-02-30', '2026/10/23', '', None):
            self.assertIsNone(normal_day_context('saiwaichou', bad, ['SマイジャグラーVKD']))
        self.assertEqual(AVAILABLE_FROM, '2026-10-17')

    def test_html_is_escaped_and_keeps_the_limits(self):
        text = normal_day_context_html('saiwaichou', '2026-10-23', ['SマイジャグラーVKD'])
        self.assertIn('normal-day-context', text)
        self.assertIn('曜日傾向の根拠と限界', text)
        self.assertIn('候補の点数・順位には反映していません', text)
        self.assertIn('混雑で長く打たれる台が増えるためか', text)
        self.assertEqual(normal_day_context_html('saiwaichou', '2026-10-23', ['沖ドキ']), '')

    def test_android_uses_the_same_rule_and_text(self):
        dart = (ROOT / 'database_android' / 'lib' / 'normal_day_context.dart').read_text(encoding='utf-8')
        block = dart[dart.index('const normalDayContextEvidence ='):]
        block = block[:block.index(';')]
        self.assertEqual(''.join(re.findall(r"'([^']*)'", block)), EVIDENCE)
        self.assertIn(f"const normalDayContextAvailableFrom = '{AVAILABLE_FROM}';", dart)

    def test_pc_reports_show_it_beside_next_day_candidates(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Store(Path(folder) / 'database.sqlite3')
            try:
                rows = [dict(store='saiwaichou', kind_code=21, day='2026-10-23', machine='SマイジャグラーVKD', rack=r,
                             games=4000, bb=15, rb=12) for r in range(700, 706)]
                rows.append(dict(rows[0], machine='L ゴッドイーター', rack=900))
                db.save(rows)
                machine_page = Path(report(db, '2026-10-23', 'SマイジャグラーVKD', folder, 'saiwaichou')[0]).read_text(encoding='utf-8')
                other_page = Path(report(db, '2026-10-23', 'L ゴッドイーター', folder, 'saiwaichou')[0]).read_text(encoding='utf-8')
                summary = Path(summary_report(db, folder, '2026-10-23')).read_text(encoding='utf-8')
            finally:
                db.close()
        self.assertIn('10/24（土）の曜日傾向：土日', machine_page)
        self.assertNotIn('曜日傾向', other_page)
        self.assertIn('10/24（土）の曜日傾向：土日', summary)


if __name__ == '__main__':
    unittest.main()
