"""キャラ誕生日（EVENT_CALENDAR.md「キャラ誕生日」、2026-10-18）：読み込み・うるう日・マスの幅。
Android `test/event_calendar_test.dart` の「キャラ誕生日」と同じ規則。"""
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from event_calendar import (BIRTHDAY_CELL_CHARS, BIRTHDAY_DATA, birthday_label, character_birthday_cell_label,
                            character_birthdays, load_character_birthdays)


def entry(month, day, name, work='作品'):
    return {'month': month, 'day': day, 'name': name, 'work': work}


class LoadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def load(self, content):
        path = Path(self.tmp.name) / 'birthdays.json'
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content if isinstance(content, str) else json.dumps(content), encoding='utf-8')
        return load_character_birthdays(path)

    def test_a_broken_or_odd_file_is_empty_instead_of_stopping_the_app(self):
        # 以前は辞書でない形で AttributeError になり、event_calendar を読み込む app.py ごと起動できなかった。
        for content in ('[1, 2]', '{"entries": {}}', '{"entries": "x"}', 'null', '{', b'\xff\xfe\x00'):
            with self.subTest(content=content):
                self.assertEqual(self.load(content), {})
        self.assertEqual(load_character_birthdays(Path(self.tmp.name) / 'none.json'), {})

    def test_odd_items_and_dates_that_do_not_exist_are_skipped(self):
        loaded = self.load({'entries': [
            'x', None, [1], entry(2, 30, '無い日'), entry(4, 31, '無い日'), entry(13, 1, '無い月'), entry(0, 1, '無い月'),
            {'month': True, 'day': 1, 'name': '真偽値'}, entry(1, 1, '  '), {'month': 1, 'day': 1, 'name': 5},
            entry(2, 29, 'うるう日'), entry(1, 1, ' 元日 ', 3), entry(5, 5, '同じ人'), entry(5, 5, '同じ人'),
        ]})
        self.assertEqual(loaded, {(2, 29): [('うるう日', '作品')], (1, 1): [('元日', '')], (5, 5): [('同じ人', '作品')]})


class RealDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = load_character_birthdays()
        cls.raw = json.loads(BIRTHDAY_DATA.read_text(encoding='utf-8'))['entries']

    def test_every_entry_is_read_once(self):
        self.assertEqual(sum(len(people) for people in self.data.values()), len(self.raw))
        self.assertGreaterEqual(len(self.raw), 573)

    def test_decisions_on_the_data_stay(self):
        def days_of(name):
            return sorted(key for key, people in self.data.items() if any(n == name for n, _w in people))
        self.assertEqual(days_of('柴大寿'), [(7, 24)], '一覧には12/15もあるが、利用者の指定で7/24だけ（2026-10-18）')
        self.assertEqual(days_of('リカード・ウェルキン'), [(1, 12)], '一覧の作品名が「Re:」なしでも取りこぼさない')
        self.assertEqual(days_of('天英院'), [(5, 3)])
        self.assertEqual(days_of('大岡越前'), [(8, 8)])
        works = {work for people in self.data.values() for _n, work in people}
        for variant in ('Re：ゼロから始める異世界生活', 'ゼロから始める異世界生活', 'ソードアートオンライン', '東京卍リベンジャーズ',
                        'エヴァンゲリオンシリーズ', 'ツインエンジェル', '快盗天使ツインエンジェル', 'エウレカセブン',
                        'とある魔術の禁書目録', '大都技研オリキャラ', '大都技研オリジナルキャラ', ''):
            self.assertNotIn(variant, works, '作品名は1つの表記にそろえる（名前（作品）で出すため）')

    def test_cells_stay_narrow_on_every_day(self):
        # 列は同じ幅にそろうので、1日でも長いと月全体が横に広がった（2026-10-18）。イベント名（8文字＋＊）並みに収める。
        day = date(2027, 1, 1)
        while day.year == 2027:
            label = character_birthday_cell_label(character_birthdays(day, self.data))
            self.assertLessEqual(len(label), 1 + BIRTHDAY_CELL_CHARS + 3, (day, label))
            day += timedelta(days=1)


class ShownTests(unittest.TestCase):
    data = {(2, 29): [('カイン・ドレッセル', '革命機ヴァルヴレイヴ')], (3, 1): [('ムーンライトルナシー', 'ウマ娘')],
            (10, 30): [('天猛星ワイバーンのラダマンティス', '聖闘士星矢')]}

    def test_the_list_shows_name_and_work(self):
        self.assertEqual(birthday_label('キリト', 'ソードアート・オンライン'), 'キリト（ソードアート・オンライン）')
        self.assertEqual(birthday_label('名無し', ''), '名無し')
        self.assertEqual(character_birthdays(date(2026, 10, 30), self.data),
                         [('天猛星ワイバーンのラダマンティス', '天猛星ワイバーンのラダマンティス（聖闘士星矢）')])
        self.assertEqual(character_birthdays(date(2026, 10, 29), self.data), [])

    def test_leap_day_birthdays_move_to_march_first_in_other_years(self):
        moved = ('カイン・ドレッセル', 'カイン・ドレッセル（革命機ヴァルヴレイヴ、2/29生まれ）')
        self.assertEqual([label for _n, label in character_birthdays(date(2027, 3, 1), self.data)],
                         ['ムーンライトルナシー（ウマ娘）', moved[1]])
        self.assertEqual(character_birthdays(date(2100, 3, 1), self.data)[-1], moved, '100で割れて400で割れない年もうるう年でない')
        self.assertEqual(character_birthdays(date(2028, 3, 1), self.data), [('ムーンライトルナシー', 'ムーンライトルナシー（ウマ娘）')])
        self.assertEqual(character_birthdays(date(2028, 2, 29), self.data),
                         [('カイン・ドレッセル', 'カイン・ドレッセル（革命機ヴァルヴレイヴ）')])
        self.assertEqual(character_birthdays(date(2027, 2, 28), self.data), [])

    def test_the_cell_shows_the_first_name_and_how_many_more(self):
        self.assertEqual(character_birthday_cell_label([]), '')
        self.assertEqual(character_birthday_cell_label([('キリト', 'x')]), '🎂キリト')
        self.assertEqual(character_birthday_cell_label([('ラインハルト・ヴァン・アストレア', 'x'), ('a', 'x'), ('b', 'x')]),
                         '🎂ラインハ…＋2')


if __name__ == '__main__':
    unittest.main()
