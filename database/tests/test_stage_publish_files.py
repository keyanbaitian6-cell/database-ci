"""公開の準備（stage_viewer.py・stage_share_viewer.py）の抜けを止める（2026-11-22、Geminiの点検 H-12②）。

- P’s CUBE版だけを公開するとき写す共通の部品（PSCUBE_SHARED）に、P’s CUBE版が実際に読む部品がすべて入っている
  （以前は shared_events.mjs が抜けていた）。
- 共有カレンダーの sw.js の版・保存する一覧の置き換えは、1か所ずつ当たらなければ止める（以前は当たらなくても黙って
  古い版のまま公開した）。
"""
import sys
import unittest
from pathlib import Path

TOOL = Path(__file__).resolve().parents[2] / 'database_android' / 'tool'
sys.path.insert(0, str(TOOL))

import stage_share_viewer  # noqa: E402
import stage_viewer  # noqa: E402


class StagePublishFilesTests(unittest.TestCase):
    def test_pscube_only_stage_copies_every_shared_module_the_pscube_viewer_imports(self):
        imported = stage_viewer.pscube_shared_imports()
        self.assertIn('shared_events.mjs', imported, 'viewer_bridge.mjs が読む')
        self.assertEqual(imported - set(stage_viewer.PSCUBE_SHARED), set())
        for name in stage_viewer.PSCUBE_SHARED:
            self.assertTrue((stage_viewer.HERE / 'web' / name).is_file(), name)

    def test_service_worker_replacement_must_hit_version_and_files_once(self):
        text = "const VERSION = 'old';\nconst FILES = [\n  './a.mjs'\n];\n"
        out = stage_share_viewer.service_worker(text, 'v1', ['./index.html'])
        self.assertIn("const VERSION = 'v1';", out)
        self.assertIn('const FILES = ["./index.html"];', out)
        for broken in ("const VER = 'old';\nconst FILES = [];\n", "const VERSION = 'old';\nconst LIST = [];\n",
                       "const VERSION = 'a';\nconst VERSION = 'b';\nconst FILES = [];\n"):
            with self.assertRaises(SystemExit):
                stage_share_viewer.service_worker(broken, 'v1', [])

    def test_the_real_service_worker_still_has_both_places(self):
        source = (Path(__file__).resolve().parents[2] / 'share_viewer' / 'sw.js').read_text(encoding='utf-8')
        stage_share_viewer.service_worker(source, 'v1', ['./index.html'])


if __name__ == '__main__':
    unittest.main()
