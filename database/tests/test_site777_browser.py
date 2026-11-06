"""サイトセブンをスマホとして開くブラウザ（site777_browser.py、2026-11-07）。サイトには接続しない。"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import site777_browser  # noqa: E402


class FakeEvent:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def __isub__(self, handler):
        self.handlers.remove(handler)
        return self


class FakeCore:
    def __init__(self, default):
        self.NewWindowRequested = FakeEvent()
        self.NewWindowRequested += default


class FakeArgs:
    def __init__(self, uri):
        self.Uri = uri
        self.handled = False

    def set_Handled(self, value):
        self.handled = value


class Site777BrowserTest(unittest.TestCase):
    def test_it_presents_itself_as_android_chrome_on_a_phone(self):
        ua = site777_browser.ANDROID_USER_AGENT
        self.assertIn('Linux; Android', ua)
        self.assertIn('Mobile Safari/', ua)
        self.assertNotIn('Windows', ua)
        width, height = site777_browser.WINDOW_SIZE
        self.assertLess(width, height)
        self.assertTrue(site777_browser.START_URL.startswith('https://m.site777.jp/'))

    def test_login_is_kept_in_its_own_folder_under_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = site777_browser.webview_storage(tmp)
            self.assertTrue(folder.is_dir())
            self.assertEqual(folder.name, 'site777-webview')
            self.assertEqual(folder.parent, Path(tmp).resolve())

    def test_new_window_links_open_in_this_window_not_the_normal_browser(self):
        opened_outside = []
        navigated = []

        class Browser:
            def on_new_window_request(self, sender, args):
                opened_outside.append(args.Uri)

        browser = Browser()
        core = FakeCore(browser.on_new_window_request)

        class Control:
            CoreWebView2 = core
            CoreWebView2InitializationCompleted = FakeEvent()

        class Native:
            webview = Control()

        Native.browser = browser

        class Window:
            native = Native()

        site777_browser.keep_popups_here(Window())
        self.assertEqual(len(core.NewWindowRequested.handlers), 1)

        class Sender:
            def Navigate(self, uri):
                navigated.append(uri)

        args = FakeArgs('https://m.site777.jp/f/D0300.do')
        for handler in core.NewWindowRequested.handlers:
            handler(Sender(), args)
        self.assertTrue(args.handled)
        self.assertEqual(navigated, ['https://m.site777.jp/f/D0300.do'])
        self.assertEqual(opened_outside, [])

    def test_the_home_button_opens_it_with_the_same_python(self):
        import app
        command, folder = app.site777_browser_command()
        self.assertEqual(command[0], sys.executable)
        self.assertEqual(Path(command[1]).name, 'site777_browser.py')
        self.assertTrue(Path(command[1]).is_file())
        self.assertEqual(Path(command[2]).name, 'data')
        self.assertEqual(folder, Path(app.__file__).resolve().parent)
        source = Path(app.__file__).read_text(encoding='utf-8')
        self.assertIn("text='サイトセブンを開く（スマホ会員）'", source)


if __name__ == '__main__':
    unittest.main()
