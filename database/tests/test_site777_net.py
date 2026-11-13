"""サイトセブンのグラフ画像から読む推定差枚（site777_net.py、2026-11-07）。

本物の画像はGitに入れない。目盛りの文字（+5,000・-5,000）の白い画素の形だけを本物の画像から写し、
背景・目盛り線・ゼロ線・黄色い線を描いた合成画像で試す。サイト・実DBには接続しない。
"""
import base64
import sys
import tempfile
import unittest
from datetime import datetime
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import site777_import as capture  # noqa: E402
import site777_net  # noqa: E402

TOP_MASK = '000000000000000000003c0c30c001000000000c049248000824924000412492000200000000e230c3000020000000000000000000000000'
BOTTOM_MASK = '000000000000000000003c0c30c001000000000c049248000824924070412492000200000000e230c3000020000000000000000000000000'
NOW = datetime.fromisoformat('2026-11-07T09:05:00+09:00')
URL = 'https://m.site777.jp/f/D3300.do?pmc=04034001&urt=2000&mdc=123&dtdd=0&pan=1'


def mask(text):
    return np.unpackbits(np.frombuffer(bytes.fromhex(text), dtype=np.uint8))[:12 * 37].reshape(12, 37).astype(bool)


def png(curve, labels=True, size=(260, 226), extra=None):
    """curve：黄色い線の [(x, y), ...]。extra：描き足す処理（draw を受け取る）。"""
    image = Image.new('RGB', size, (24, 28, 24))
    draw = ImageDraw.Draw(image)
    for y in site777_net.GRID_Y:
        if y != 111:
            draw.line([(8, y), (244, y)], fill=(64, 64, 64))
    if curve:
        draw.line(curve, fill=(250, 230, 30), width=2)
    draw.line([(8, 111), (244, 111)], fill=(255, 255, 255))
    if extra:
        extra(draw)
    a = np.array(image)
    if labels:
        a[9:21, 16:53][mask(TOP_MASK)] = 255
        a[201:213, 16:53][mask(BOTTOM_MASK)] = 255
    stream = BytesIO()
    Image.fromarray(a).save(stream, 'PNG')
    return stream.getvalue()


def data_uri(raw):
    return 'data:image/png;base64,' + base64.b64encode(raw).decode()


DOWN = [(9, 111), (40, 118), (80, 126), (120, 140)]
UP = [(9, 111), (60, 90), (120, 70), (180, 60)]
# 見切れ（2026-11-13）：上の端に触れて中に戻る・上の端のまま終わる・下の端のまま終わる。
TOP_RETURN = [(9, 111), (60, 40), (100, 16), (140, 60)]
TOP_END = [(9, 111), (60, 60), (100, 16), (140, 16)]
BOTTOM_END = [(9, 111), (60, 170), (100, 206), (140, 206)]
SHORT = [(9, 111), (14, 115)]
FLAT = [(9, 111), (30, 100), (100, 125), (106, 108), (115, 109)]


class EstimateTest(unittest.TestCase):
    def test_negative_and_positive_curves_read_from_the_axis(self):
        for curve in (DOWN, UP):
            result = site777_net.analyze(png(curve))
            self.assertEqual(result['status'], 'candidate', result)
            expected = (111 - result['endpoint'][1]) * 10000 / 192
            self.assertLessEqual(abs(result['estimate'] - expected), .5)
            estimate = site777_net.net_estimate(png(curve))
            self.assertEqual(estimate, {'value': result['estimate'], 'sure': True, 'method': site777_net.METHOD})
            self.assertTrue(site777_net.valid(estimate))
        self.assertLess(site777_net.analyze(png(DOWN))['estimate'], 0)
        self.assertGreater(site777_net.analyze(png(UP))['estimate'], 0)

    def test_near_zero_is_marked_unsure(self):
        estimate = site777_net.net_estimate(png(FLAT))
        self.assertIsNotNone(estimate)
        self.assertFalse(estimate['sure'])

    def test_ten_and_eleven_pixels_round_to_individual_medals(self):
        for y, expected in ((101, 521), (100, 573), (121, -521), (122, -573)):
            with self.subTest(y=y):
                raw = png([(9, 111), (20, y), (100, y)],
                          extra=lambda d: d.line([(101, y), (120, y)], fill=(250, 230, 30)))
                result = site777_net.analyze(raw)
                self.assertEqual(result['status'], 'candidate', result)
                self.assertEqual(result['estimate'], expected)

    def test_held_or_unreadable_images_get_no_estimate(self):
        cases = {
            'short_curve': png([(9, 111), (14, 115)]),
            'axis_labels_unknown': png(DOWN, labels=False),
            'unsupported_size': png(DOWN, size=(300, 226)),
            'curve_missing': png(None),
            'curve_gap': png(DOWN, extra=lambda d: d.rectangle([(60, 100), (66, 140)], fill=(24, 28, 24))),
        }
        for reason, raw in cases.items():
            with self.subTest(reason):
                result = site777_net.analyze(raw)
                self.assertEqual(result['reason'], reason, result)
                self.assertIsNone(site777_net.net_estimate(raw))
        self.assertEqual(site777_net.analyze(b'not a png')['reason'], 'image_unreadable')

    def test_top_edge_racks_read_the_endpoint_or_take_my(self):
        # 2026-11-13 利用者「両方直す」「myそのままでいい」：上の端（+5,000）に触れた大勝ちの台が推定なしになり、
        # 店の合計から抜けて毎日負けて見えていた。
        back = site777_net.analyze(png(TOP_RETURN))
        self.assertEqual(back['status'], 'candidate', back)                      # 中に戻ったら終点から読む
        self.assertLessEqual(abs(back['estimate'] - (111 - back['endpoint'][1]) * 10000 / 192), .5)
        self.assertGreater(back['estimate'], 2000)
        self.assertEqual(site777_net.net_estimate(png(TOP_RETURN), 9999)['value'], back['estimate'], 'MYは使わない')
        top = site777_net.analyze(png(TOP_END))
        self.assertEqual((top['status'], top['reason']), ('clipped_top', 'boundary_contact'))
        self.assertIsNone(site777_net.net_estimate(png(TOP_END)), 'MYが無ければ付けない')
        self.assertIsNone(site777_net.net_estimate(png(TOP_END), 4999), 'MYが5,000未満は付けない')
        self.assertIsNone(site777_net.net_estimate(png(TOP_END), '6915'))
        estimate = site777_net.net_estimate(png(TOP_END), 6915)
        self.assertEqual(estimate, {'value': 6915, 'sure': True, 'method': site777_net.METHOD})
        self.assertTrue(site777_net.valid(estimate))
        self.assertEqual(site777_net.net_estimate(png(BOTTOM_END), 6915), {'value': -5000, 'sure': True, 'method': site777_net.METHOD},
                         '下の端のまま終わった台は -5,000（MYは使わない）')
        # 端の外を通って描かれない区間があっても、両側が端に接していれば途切れとは見なさない。
        hidden = png(TOP_END, extra=lambda d: d.rectangle([(110, 14), (116, 19)], fill=(24, 28, 24)))
        self.assertEqual(site777_net.analyze(hidden)['status'], 'clipped_top')

    def test_right_edge_unsteady_endpoint_and_overlapped_labels_are_read(self):
        # 2026-11-13 利用者「四つとも治して」：まだ読めていなかった台（勝ち台に偏っていた）を読む。
        # 右端に届いた台は右端の値。
        right = site777_net.analyze(png([(9, 111), (20, 100), (120, 96), (243, 90)]))
        self.assertEqual(right['status'], 'candidate', right)
        self.assertTrue(right['right_edge'])
        self.assertLessEqual(abs(right['estimate'] - (111 - right['endpoint'][1]) * 10000 / 192), .5)
        # 線の先の色が薄く、色の閾値で終点が2.5画素ほど動く台（前は2画素を超えると保留）。
        faint = lambda d: d.line([(150, 102), (150, 106)], fill=(140, 140, 30))
        unsteady = site777_net.analyze(png([(9, 111), (20, 104), (150, 100)], extra=faint))
        self.assertEqual(unsteady['status'], 'candidate', unsteady)
        self.assertGreater(unsteady['spread'], 2 * site777_net.SCALE)
        self.assertLessEqual(unsteady['spread'], site777_net.UNSTABLE_PIXELS * site777_net.SCALE)
        self.assertLessEqual(unsteady['interval'][0], unsteady['estimate'])
        # 動く幅が5画素を超える台は今までどおり保留。
        wide = lambda d: d.line([(150, 101), (150, 125)], fill=(140, 140, 30))
        self.assertEqual(site777_net.analyze(png([(9, 111), (20, 104), (150, 100)], extra=wide))['status'], 'unavailable')
        # 黄色い線が「5,000」の文字に重なった台：重なっていない画素で文字を確かめて読む。
        crossing = [(9, 111), (25, 40), (36, 15), (60, 15), (100, 60)]

        def over_labels(curve, labels=True):
            image = Image.open(BytesIO(png(curve, labels=labels))).convert('RGB')
            ImageDraw.Draw(image).line(curve, fill=(250, 230, 30), width=2)
            stream = BytesIO()
            image.save(stream, 'PNG')
            return stream.getvalue()

        overlapped = site777_net.analyze(over_labels(crossing))
        self.assertEqual(overlapped['status'], 'candidate', overlapped)
        self.assertEqual(site777_net.analyze(over_labels(crossing, labels=False))['reason'], 'axis_labels_unknown',
                         '文字が無い画像は、線が重なっていても読まない')
        # 違う文字（目盛りの数字が違う画像）は、線が重なっていても読まない。
        other = Image.open(BytesIO(over_labels(crossing))).convert('RGB')
        ImageDraw.Draw(other).rectangle([(40, 10), (52, 20)], fill=(255, 255, 255))
        stream = BytesIO()
        other.save(stream, 'PNG')
        self.assertEqual(site777_net.analyze(stream.getvalue())['reason'], 'axis_labels_unknown')
        # 文字の形の元（ビット）と、照合に使うハッシュが同じ形を指していること。
        import hashlib
        for rows, cols, bits, digest in site777_net.LABEL_BOXES:
            shape = np.unpackbits(np.frombuffer(bytes.fromhex(bits), dtype=np.uint8))[:12 * 37].reshape(12, 37).astype(bool)
            self.assertEqual(hashlib.sha256(shape.tobytes()).hexdigest(), digest)

    def test_only_the_site777_form_is_valid(self):
        good = {'value': -573, 'sure': True, 'method': site777_net.METHOD}
        self.assertTrue(site777_net.valid(good))
        self.assertTrue(site777_net.valid({**good, 'value': -550, 'method': site777_net.LEGACY_METHOD}))
        for bad in ({**good, 'method': 'anaslo-graph-v1'}, {**good, 'method': site777_net.LEGACY_METHOD}, {**good, 'value': 700.0},
                    {**good, 'sure': 1}, {**good, 'extra': 1}, {'value': -700, 'sure': True}, None):
            self.assertFalse(site777_net.valid(bad), bad)


class ImportTest(unittest.TestCase):
    def table(self):
        return {'url': URL, 'machine': '試験ジャグラー3', 'model_id': '123', 'selected_md': '11/6', 'count': 2,
                'headers': ['', '台番', '累計ゲーム', 'BB回数', 'RB回数', '最高出玉', 'ART回数'],
                'rows': [['', '101', '3000', '10', '8', '900', '--'], ['', '102', '2800', '9', '5', '1,234', '0']]}

    def backup(self, images):
        table = self.table()
        rows = capture.table_records(table, '2026-11-06', NOW)
        payload = {'url': URL.replace('D3300', 'D4300'), 'model_id': '123', 'selected_md': '11/6',
                   'graphs': [{'rack': rack, 'png': data_uri(raw)} for rack, raw in images.items()]}
        graphs = capture.graph_records(payload, '2026-11-06', '123', {101, 102}, NOW)
        return capture.make_backup(table, rows, graphs, '2026-11-06', '試験ジャグラー3', now=NOW)

    def test_capture_adds_the_estimate_only_where_it_can_be_read(self):
        backup = self.backup({101: png(DOWN), 102: png(SHORT)})
        by_rack = {r['rack']: r for r in backup['records']}
        self.assertEqual(by_rack[101]['net_estimate']['method'], site777_net.METHOD)
        self.assertIsNone(by_rack[101]['net_medals'])
        self.assertNotIn('net_estimate', by_rack[102])  # 線が短い：推定なし。MYはそのまま
        self.assertEqual(by_rack[102]['my'], 1234)
        for record in backup['records']:
            capture.validate_record(record)
        with self.assertRaises(ValueError):
            capture.validate_record({**by_rack[101], 'net_estimate': {'value': -700, 'sure': True, 'method': 'anaslo-graph-v1'}})

    def test_capture_takes_my_for_a_rack_ending_on_the_top_edge(self):
        table = self.table()
        table['rows'][1][5] = '6,915'
        rows = capture.table_records(table, '2026-11-06', NOW)
        payload = {'url': URL.replace('D3300', 'D4300'), 'model_id': '123', 'selected_md': '11/6',
                   'graphs': [{'rack': 101, 'png': data_uri(png(DOWN))}, {'rack': 102, 'png': data_uri(png(TOP_END))}]}
        graphs = capture.graph_records(payload, '2026-11-06', '123', {r['rack']: r['my'] for r in rows}, NOW)
        backup = capture.make_backup(table, rows, graphs, '2026-11-06', '試験ジャグラー3', now=NOW)
        by_rack = {r['rack']: r for r in backup['records']}
        self.assertEqual(by_rack[102]['net_estimate'], {'value': 6915, 'sure': True, 'method': site777_net.METHOD})
        self.assertEqual(by_rack[102]['my'], 6915)
        for record in backup['records']:
            capture.validate_record(record)

    def test_store_accepts_it_and_moves_a_later_estimate_onto_the_same_image_only(self):
        from pscube_import import PscubeStore, _record_key
        with tempfile.TemporaryDirectory() as tmp:
            store = PscubeStore(Path(tmp) / 'test.sqlite3', recording=False)
            try:
                with_estimate = self.backup({101: png(DOWN), 102: png(UP)})
                without = {**with_estimate, 'records': [{k: v for k, v in r.items() if k != 'net_estimate'}
                                                         for r in with_estimate['records']]}
                store.import_backup(without)
                key = _record_key(with_estimate['records'][0])
                self.assertNotIn('net_estimate', store._read('records', key))
                # 同じ表・同じ画像から後で付けた推定差枚は移る（数値・出典はそのまま）。
                store.import_backup(with_estimate)
                saved = store._read('records', key)
                self.assertEqual(saved['net_estimate'], with_estimate['records'][0]['net_estimate'])
                self.assertEqual({k: v for k, v in saved.items() if k != 'net_estimate'}, without['records'][0])
                # 別の画像（取り直し）から作った推定差枚は移さない。
                other = self.backup({101: png(UP), 102: png(UP)})
                store.import_backup(other)
                self.assertEqual(store._read('records', key)['net_estimate'], with_estimate['records'][0]['net_estimate'])
                # 書き出し→読み直しでも残る。
                exported = store.export_payload()
                self.assertTrue(any(r.get('net_estimate', {}).get('method') == site777_net.METHOD for r in exported['records']))
            finally:
                store.close()

    def test_an_anaslo_record_cannot_carry_the_site777_method(self):
        from pscube_import import _validate_record
        record = self.backup({101: png(DOWN), 102: png(UP)})['records'][0]
        anaslo_like = {**record, 'source_site': 'anaslo'}
        with self.assertRaises(ValueError):
            _validate_record(anaslo_like)


if __name__ == '__main__':
    unittest.main()


class CalendarTest(unittest.TestCase):
    def test_day_total_counts_estimates_as_needing_check_but_never_my(self):
        from event_calendar import pscube_day_nets
        base = {'rate': '20', 'day': '2026-11-06', 'games': 3000, 'bb': 10, 'rb': 5, 'my': 900}
        records = [{**base, 'net_medals': 300},
                   {**base, 'source_site': 'site777', 'net_medals': None,
                    'net_estimate': {'value': -700, 'sure': True, 'method': site777_net.METHOD}},
                   {**base, 'source_site': 'site777', 'net_medals': None,
                    'net_estimate': {'value': 50, 'sure': False, 'method': site777_net.METHOD}},
                   {**base, 'source_site': 'site777', 'net_medals': None, 'my': 6915}]  # 見切れ：MYは足さない
        day = pscube_day_nets(records, '2026-11-06', '2026-11-06')['2026-11-06']
        self.assertEqual((day['total'], day['captured'], day['needs_check']), (300 - 700 + 50, 3, 1))


class BackfillTest(unittest.TestCase):
    def test_saved_racks_get_estimates_only_from_their_own_images(self):
        import json
        from pscube_import import ANDROID_SYNC_NAME, PscubeStore, _record_key
        import site777_backfill
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path, sources = root / 'pscube.sqlite3', root / 'sources'
            sources.mkdir()
            images = {101: png(DOWN), 102: png(SHORT)}
            backup = ImportTest().backup(images)
            plain = {**backup, 'records': [{k: v for k, v in r.items() if k != 'net_estimate'} for r in backup['records']]}
            store = PscubeStore(db_path, recording=False)
            try:
                store.import_backup(plain)
            finally:
                store.close()
            page = {'kind': 'graphs', 'graphs': [{'rack': rack, 'png': data_uri(raw)} for rack, raw in images.items()]}
            (sources / 'page.json').write_text(json.dumps(page), encoding='utf-8')
            before = db_path.read_bytes()
            result, summary = site777_backfill.build(db_path, sources)
            self.assertEqual(db_path.read_bytes(), before, '件数を見るだけではDBを変えない')
            self.assertEqual(summary['推定を付ける'], 1)
            self.assertEqual(summary['保留：short_curve'], 1)
            self.assertEqual([r['rack'] for r in result['records']], [101])
            self.assertEqual({k: v for k, v in result['records'][0].items() if k != 'net_estimate'}, plain['records'][0])
            store = PscubeStore(db_path, recording=False)
            try:
                store.import_backup(result)
                self.assertEqual(store._read('records', _record_key(result['records'][0]))['net_estimate'],
                                 result['records'][0]['net_estimate'])
            finally:
                store.close()
            # 付け終わったら、もう一度作っても入れる台は無い。
            self.assertIsNone(site777_backfill.build(db_path, sources)[0])
        self.assertTrue(ANDROID_SYNC_NAME.fullmatch('pscube-backup-site777net-20261107.json'))
        self.assertFalse(ANDROID_SYNC_NAME.fullmatch('pscube-backup-site777net-x.json'))

    def test_upgrade_recalculates_only_legacy_estimates_with_matching_images(self):
        import json
        from pscube_import import PscubeStore
        import site777_backfill
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            images = {101: png(DOWN), 102: png(UP)}
            precise = ImportTest().backup(images)
            legacy = {**precise, 'records': [
                {**r, 'net_estimate': {'value': 500, 'sure': True, 'method': site777_net.LEGACY_METHOD}}
                for r in precise['records']
            ]}
            (root / 'page.json').write_text(json.dumps({
                'kind': 'graphs', 'graphs': [{'rack': 101, 'png': data_uri(images[101])}],
            }), encoding='utf-8')
            db_path = root / 'test.sqlite3'
            store = PscubeStore(db_path, recording=False)
            try:
                store.import_backup(legacy)
                self.assertIsNone(site777_backfill.build(db_path, root)[0])
                upgrade, counts = site777_backfill.build(db_path, root, upgrade=True)
                self.assertEqual(counts['推定を更新する'], 1)
                self.assertEqual(counts['画像なし'], 1)
                self.assertEqual(upgrade['records'], precise['records'][:1])
                self.assertEqual(store.import_backup(upgrade)['updated'], 1)
                self.assertEqual(store.import_backup(legacy)['updated'], 0)
                self.assertCountEqual(store.export_payload()['records'], [precise['records'][0], legacy['records'][1]])
            finally:
                store.close()
