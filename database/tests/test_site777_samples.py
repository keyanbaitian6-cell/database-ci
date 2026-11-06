"""資料の保存とページ切替時の保護。実サイトには接続しない。"""
import sys
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import site777_samples as samples


class SamplesTest(unittest.TestCase):
    def test_fullwidth_hall_name_is_accepted_without_changing_source_html(self):
        payload = self.payload(html='<h1>Ｐ－ＳＴＡＴＩＯＮ＆ＩＩ　スロット館</h1><table>累計ゲーム</table>')
        with tempfile.TemporaryDirectory() as tmp:
            result = samples.save_sample(tmp, payload)
            self.assertIsNotNone(result)
            self.assertIn('Ｐ－ＳＴＡＴＩＯＮ', result.read_text(encoding='utf-8'))

    def payload(self, **changes):
        return {'url': 'https://m.site777.jp/f/D3300.do?pmc=04034001&urt=2000&mdc=123&dtdd=0&pan=1',
                'html': '<h1>P-STATION＆II スロット館</h1><table>累計ゲーム BB回数</table>',
                'images': [], 'canvases': [], **changes}

    def test_only_target_data_is_saved_exclusively(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(samples.save_sample(tmp, self.payload(url='https://example.com/')))
            self.assertIsNone(samples.save_sample(tmp, self.payload(html='<input type="password">')))
            self.assertFalse((Path(tmp) / 'site777-samples').exists())
            a = samples.save_sample(tmp, self.payload())
            b = samples.save_sample(tmp, self.payload())
            self.assertNotEqual(a, b)
            self.assertTrue(a.is_file())
            self.assertEqual(a.parent.name, 'site777-samples')

    def test_disabled_collection_does_not_read_the_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            samples.collect(object(), tmp, object())
            flag = Path(tmp) / 'site777-samples.enabled'
            flag.touch()
            os.utime(flag, (1, 1))
            samples.collect(object(), tmp, object())

    def test_page_identity_preserves_date_and_page_but_normalizes_spelling(self):
        first = self.payload()['url']
        self.assertTrue(samples.same_page(first, first.replace('dtdd=0&pan=1', 'pan=1&dtdd=0')+'#scroll'))
        for second in (first.replace('dtdd=0','dtdd=1'), first.replace('pan=1','pan=2'),
                       first.replace('m.site777.jp','example.com')):
            self.assertFalse(samples.same_page(first, second))

    def test_page_change_during_read_is_not_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'site777-samples.enabled').touch()
            payload = self.payload()

            class Window:
                def __init__(self):
                    self.calls = 0

                def get_current_url(self):
                    self.calls += 1
                    return payload['url'] if self.calls == 1 else payload['url'].replace('pan=1','pan=2')

                def evaluate_js(self, _):
                    return payload

            samples.collect(Window(), tmp, SimpleNamespace(write=lambda *a, **kw: None))
            self.assertFalse((Path(tmp) / 'site777-samples').exists())


if __name__ == '__main__':
    unittest.main()
