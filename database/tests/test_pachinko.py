"""4円パチンコの手動取り込み（pachinko.py、PC版だけ、2026-10-12）。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pachinko  # noqa: E402
from browser_import import GraphExtractionError, build_graph_context  # noqa: E402
from core import Store  # noqa: E402

LINK = 'https://meruhenworld.pt.teramoba2.com/saiwaichou/standgraph?rack_no={}&target_date=2026-10-10'


def table_payload(rows=None):
    rows = rows or [['80', '12', '1/222.8', '2673'], ['81', '4', '1/677.5', '2710'], ['82', '0', '-', '615']]
    return dict(store='saiwaichou', machine='e東京喰種MW', target_date='2026-10-10', kind_code='1',
                matrix=[pachinko.PACHI_HEADERS] + rows, links=[LINK.format(r[0]) for r in rows],
                source_url='https://meruhenworld.pt.teramoba2.com/saiwaichou/dai_list_pachi')


class PachinkoTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=Path(__file__).parents[1])
        self.slot_db = Path(self.folder.name) / 'database.sqlite3'

    def tearDown(self):
        self.folder.cleanup()

    def test_table_header_is_recognized(self):
        self.assertTrue(pachinko.is_pachinko_table([['台番号▲', '大当り', '大当り確率', '総回転数']]))
        self.assertFalse(pachinko.is_pachinko_table([['台番号', 'BB', 'RB', '総回転数', '合成確率', '前日最終スタート']]))
        self.assertFalse(pachinko.is_pachinko_table([]))

    def test_parse_table_rows(self):
        rows, day, machine = pachinko.parse_pachinko_table(table_payload())
        self.assertEqual((day, machine, len(rows)), ('2026-10-10', 'e東京喰種MW', 3))
        self.assertEqual({k: rows[0][k] for k in ('rack', 'hits', 'probability', 'games')},
                         {'rack': 80, 'hits': 12, 'probability': '1/222.8', 'games': 2673})
        self.assertEqual(rows[2]['probability'], '-')
        self.assertEqual(rows[0]['detail_url'], LINK.format(80))

    def test_parse_table_refuses_duplicates_and_bad_racks(self):
        with self.assertRaises(pachinko.PachinkoError):
            pachinko.parse_pachinko_table(table_payload([['80', '1', '1/2', '3'], ['80', '1', '1/2', '3']]))
        with self.assertRaises(pachinko.PachinkoError):
            pachinko.parse_pachinko_table(table_payload([['台', '1', '1/2', '3']]))
        with self.assertRaises(pachinko.PachinkoError):
            pachinko.parse_pachinko_table(dict(table_payload(), target_date=None))

    def test_saving_keeps_slot_records_apart_and_writes_the_export(self):
        message, _ = pachinko.save_table(table_payload(), self.slot_db)
        self.assertIn('3台を保存しました', message)
        self.assertFalse(self.slot_db.exists(), 'スロットの記録には書かない')
        store = pachinko.PachinkoStore(pachinko.db_path_for(self.slot_db))
        try:
            self.assertEqual([r['rack'] for r in store.rows()], [80, 81, 82])
            self.assertEqual(store.get('saiwaichou', '2026-10-10', 80)['kind_code'], '1')
        finally:
            store.close()
        exported = json.loads((Path(self.folder.name) / pachinko.EXPORT_NAME).read_text(encoding='utf-8'))
        self.assertEqual(exported['format'], 'database-pachinko')
        self.assertEqual(len(exported['records']), 3)

    def test_graph_is_added_to_the_rack_and_table_recapture_keeps_it(self):
        graph = {'store': 'saiwaichou', 'rack': 80, 'target_date': '2026-10-10', 'games': 2673, 'max_hold': 14030,
                 'page_text': '台データ情報\n大当り\n12\n大当り確率\n1/222.8\n初当り\n10\n最大連チャン数\n2\n最大持玉\n14030',
                 'info': {'info_soukaiten': '2673'}, 'source_url': LINK.format(80)}
        self.assertIsNone(pachinko.graph_target(graph, self.slot_db), '台一覧の前は対象外')
        with self.assertRaises(pachinko.PachinkoError):
            pachinko.save_graph(graph, self.slot_db, {'end_y': 1})
        pachinko.save_table(table_payload(), self.slot_db)
        self.assertEqual(pachinko.graph_target(graph, self.slot_db)['rack'], 80)
        message, _ = pachinko.save_graph(graph, self.slot_db, {'end_y': 1})
        self.assertIn('80番台', message)
        self.assertIn('初当り10', message)
        # 台一覧を取り込み直しても、グラフ・ページの数字は残る。
        pachinko.save_table(table_payload([['80', '13', '1/210.0', '2800']]), self.slot_db)
        store = pachinko.PachinkoStore(pachinko.db_path_for(self.slot_db))
        try:
            row = store.get('saiwaichou', '2026-10-10', 80)
        finally:
            store.close()
        self.assertEqual((row['hits'], row['games']), (13, 2800))
        self.assertEqual(row['graph_measurement'], {'end_y': 1})
        self.assertEqual(row['panel'], {'大当り': '12', '大当り確率': '1/222.8', '初当り': '10', '最大連チャン数': '2',
                                        '最大持玉': '14030'})
        self.assertEqual(row['max_hold'], 14030)

    def test_page_text_with_seven_segment_backgrounds_and_hit_history(self):
        # 実際のページの文字の形（2026-10-12に取り込んだ page_text と同じ並び。数字は作ったもの）。
        nb, nl, tab = '\xa0', '\n', '\t'

        def slots(pairs):
            return nl.join(tab + nl + nl.join([nb] * 10) + nl + f'{c}{nl}{g}' for c, g in pairs)
        axis = nl.join(str(n) for n in range(10, 0, -1))
        text = nl.join([
            '台データ情報', '更新日時：2026/10/11 00:17',
            '大当り', '88888', '7', tab, '大当り確率', '8/8888.8', f'1/{nb}301.5',
            'スタート', '888888', '88', tab, '総回転数', '888888', '2110',
            '初当り', '888888', '5', tab, '最大連チャン数', '888888', '3', tab,
            '1セット最大出玉', '888888', '最大持玉', '888888', '9120', tab, '差玉', '888888', tab,
            '前日最終スタート', '888888', '40',
            '当り履歴', '', '2026/10/11 (1日前)', '', axis, '', nb, slots([(1, 50)]), '',
            '2026/10/10 (2日前)', '', axis, '', nb, slots([(1, 120), (3, 15), (1, 400), (1, 8), (1, 300)]), '',
            'グラフ表示', '一覧表示', '過去データ履歴', '2026/10/09 (3日前)', '大当り', '88888', '99'])
        self.assertEqual(pachinko.panel_numbers(text), {
            '大当り': '7', '大当り確率': '1/301.5', 'スタート': '88', '総回転数': '2110', '初当り': '5',
            '最大連チャン数': '3', '最大持玉': '9120', '前日最終スタート': '40'})
        self.assertEqual(pachinko.hit_history(text, '2026-10-10'),
                         [{'chain': 1, 'games': 120}, {'chain': 3, 'games': 15}, {'chain': 1, 'games': 400},
                          {'chain': 1, 'games': 8}, {'chain': 1, 'games': 300}])
        self.assertEqual(pachinko.hit_history(text, '2026-10-11'), [{'chain': 1, 'games': 50}])
        self.assertIsNone(pachinko.hit_history(text, '2026-10-01'))

    def test_panel_numbers_reads_only_numbers_after_labels(self):
        self.assertEqual(pachinko.panel_numbers('スタート\n153\n差玉\n\n前日最終スタート\n96\n1セット最大出玉\n-'),
                         {'スタート': '153', '前日最終スタート': '96'})

    def test_report_page(self):
        import pachinko_report
        with self.assertRaises(ValueError):
            pachinko_report.build_report(self.slot_db, Path(self.folder.name) / 'reports')
        pachinko.save_table(table_payload(), self.slot_db)
        pachinko.save_graph({'store': 'saiwaichou', 'rack': 80, 'target_date': '2026-10-10',
                             'page_text': '\n'.join(['初当り', '888888', '4', '最大持玉', '888888', '9000'])},
                            self.slot_db,
                            {'baseline_y': 200.5, 'curve': [[0.5, 200.5], [10.5, 150.5]]})
        output = pachinko_report.build_report(self.slot_db, Path(self.folder.name) / 'reports')
        page = output.read_text(encoding='utf-8')
        self.assertIn('パチンコ 末尾0の記録', page)
        self.assertIn('e東京喰種MW', page)
        self.assertNotIn('888888', page, 'ページの文字は載せない')
        store = pachinko.PachinkoStore(pachinko.db_path_for(self.slot_db))
        try:
            records = {r['rack']: r for r in pachinko_report.report_records(store.rows())}
        finally:
            store.close()
        self.assertEqual((records[80]['first'], records[80]['max_hold'], records[80]['games']), (4, 9000, 2673))
        self.assertEqual(sorted(records), [80], '末尾0の台だけ')

    def test_jumps_to_the_next_tail_zero_rack(self):
        # 2026-10-12 利用者「取り込んだら次の末尾0に飛ぶようにしてほしい110→120みたいな」。
        rows = [[str(r), '1', '1/200.0', '1000'] for r in range(105, 136)]
        message, url = pachinko.save_table(table_payload(rows), self.slot_db)
        self.assertIn('末尾0の110番台へ移動します', message)
        self.assertEqual(url, LINK.format(110))
        page = 'https://meruhenworld.pt.teramoba2.com/saiwaichou/standgraph?dai_hall_id=821&rack_no={}&target_date=2026-10-10'
        text = '\n'.join(['台データ情報', 'e機種', '109番台', '110番台', '111番台', '大当り', '88888', '1', '大当り確率',
                          '8/8888.8', '1/200.0', '初当り', '888888', '1', '当り履歴'])

        def graph(rack):
            return {'store': 'saiwaichou', 'rack': rack, 'target_date': '2026-10-10', 'page_text': text,
                    'source_url': page.format(rack)}
        message, url = pachinko.save_graph(graph(110), self.slot_db, {'end_y': 1})
        self.assertIn('次の末尾0、120番台へ移動します', message)
        self.assertIn('rack_no=120', url)
        self.assertIn('dai_hall_id=821', url)
        self.assertIn('target_date=2026-10-10', url)
        # 130番台が済んでいれば、120番台のあとは飛ばして終わり（台一覧の最後は135番台）。
        pachinko.save_graph(graph(130), self.slot_db, {'end_y': 1})
        message, url = pachinko.save_graph(graph(120), self.slot_db, {'end_y': 1})
        self.assertIn('末尾0の台はここまでです', message)
        self.assertIsNone(url)
        # 台一覧を取り込み直すと、グラフがまだの末尾0が無いので移動しない。
        message, url = pachinko.save_table(table_payload(rows), self.slot_db)
        self.assertIsNone(url)

    def test_a_rack_page_alone_is_saved_when_its_table_was_not_captured(self):
        pachinko.save_table(table_payload(), self.slot_db)   # 80〜82番台だけ
        text = '\n'.join(['台データ情報', 'P大海物語', '169番台', '170番台', '171番台', '大当り', '88888', '9',
                          '大当り確率', '8/8888.8', '1/ 300.0', 'スタート', '888888', '12', '総回転数', '888888', '2700',
                          '初当り', '888888', '6', '当り履歴'])
        payload = {'store': 'saiwaichou', 'rack': 170, 'target_date': '2026-10-10', 'page_text': text,
                   'source_url': LINK.format(170)}
        self.assertEqual(pachinko.graph_target(payload, self.slot_db)['machine'], 'P大海物語')
        message, url = pachinko.save_graph(payload, self.slot_db, {'end_y': 1})
        self.assertIn('170番台', message)
        self.assertIn('まだの末尾0：80番台', message, '前に残っている末尾0を知らせる')
        store = pachinko.PachinkoStore(pachinko.db_path_for(self.slot_db))
        try:
            row = store.get('saiwaichou', '2026-10-10', 170)
        finally:
            store.close()
        self.assertEqual((row['machine'], row['hits'], row['games'], row['probability']), ('P大海物語', 9, 2700, '1/300.0'))
        # スロットの台のページ（初当り・当り履歴が無い）は、パチンコとして保存しない。
        self.assertIsNone(pachinko.graph_target(dict(payload, rack=999, page_text='BB\n3\nRB\n2'), self.slot_db))

    def test_slot_graph_refuses_other_kinds(self):
        db = Store(self.slot_db)
        try:
            with self.assertRaisesRegex(GraphExtractionError, '46'):
                build_graph_context({'store': 'saiwaichou', 'kind_code': '10', 'rack': 1, 'target_date': '2026-10-10'}, db)
        finally:
            db.close()


if __name__ == '__main__':
    unittest.main()
