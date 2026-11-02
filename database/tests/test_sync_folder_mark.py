"""同期フォルダの目印とドライブ文字の切り替え（2026-11-03 利用者「何度目かわからないけどまたグーグルドライブの
ドライブレター変わってるのに気づかず取り込み終えてしまった」「別のアカウントで文字つかってるときはこっちはEになるね」
→「自動で探して知らせる」）。"""
import json
import tempfile
import unittest
from pathlib import Path, PureWindowsPath
from unittest.mock import patch

import core
from core import SYNC_MARK_NAME, Store, auto_backup, load_settings, resolve_sync_dir, save_settings, write_sync_mark


class SyncFolderMarkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.data = base / 'data'
        self.data.mkdir()
        self.g = base / 'G' / 'マイドライブ' / 'database共有'   # 設定の場所（G:）
        self.e = base / 'E' / 'マイドライブ' / 'database共有'   # 文字が変わったあとの同じ場所（E:）
        self.e.mkdir(parents=True)
        self.other = patch('core._other_drive_folders', side_effect=lambda folder: [self.e])
        self.other.start()
        self.addCleanup(self.other.stop)

    def mark(self, folder):
        return json.loads((Path(folder) / SYNC_MARK_NAME).read_text(encoding='utf-8'))['id']

    def test_first_use_marks_the_configured_folder(self):
        self.g.mkdir(parents=True)
        save_settings(self.data, sync_dir=str(self.g))
        self.assertEqual(resolve_sync_dir(self.data), str(self.g))
        self.assertEqual(self.mark(self.g), load_settings(self.data)['sync_mark'])
        self.assertEqual(resolve_sync_dir(self.data), str(self.g), '2回目も同じ（目印は書き直さない）')

    def test_missing_letter_switches_to_the_folder_with_the_same_mark(self):
        self.g.mkdir(parents=True)
        save_settings(self.data, sync_dir=str(self.g))
        mark = write_sync_mark(self.data, self.g)
        (self.e / SYNC_MARK_NAME).write_text(json.dumps({'id': mark}), encoding='utf-8')   # Driveの同じフォルダ
        self.g.rename(self.g.parent / 'gone')   # G: が見えなくなった
        moved = resolve_sync_dir(self.data)
        self.assertEqual(Path(moved), self.e)
        settings = load_settings(self.data)
        self.assertEqual(Path(settings['sync_dir']), self.e, '設定も新しい場所へ')
        self.assertEqual(settings['sync_moved']['old'], str(self.g))
        self.assertTrue((self.data / 'errors.log').read_text(encoding='utf-8').count('切り替えました'))

    def test_never_writes_to_a_folder_without_the_same_mark(self):
        # もう一方のアカウントのドライブ：同じ場所にフォルダがあっても、目印が無い・違う番号なら使わない。
        save_settings(self.data, sync_dir=str(self.g), sync_mark='mine')
        self.assertIsNone(resolve_sync_dir(self.data), '目印の無いフォルダへは切り替えない')
        (self.e / SYNC_MARK_NAME).write_text(json.dumps({'id': 'theirs'}), encoding='utf-8')
        self.assertIsNone(resolve_sync_dir(self.data))
        self.g.mkdir(parents=True)
        (self.g / SYNC_MARK_NAME).write_text(json.dumps({'id': 'theirs'}), encoding='utf-8')
        self.assertIsNone(resolve_sync_dir(self.data), '設定の場所でも、別の番号の目印なら使わない')
        self.assertEqual(Path(load_settings(self.data)['sync_dir']), self.g, '設定は変えない')

    def test_backup_goes_to_the_switched_folder(self):
        self.g.mkdir(parents=True)
        save_settings(self.data, sync_dir=str(self.g))
        mark = write_sync_mark(self.data, self.g)
        (self.e / SYNC_MARK_NAME).write_text(json.dumps({'id': mark}), encoding='utf-8')
        self.g.rename(self.g.parent / 'gone')
        store = Store(self.data / 'database.sqlite3')
        try:
            store.save([dict(store='nagamachiminami', kind_code=21, day='2026-11-02', machine='テスト', rack=1,
                             games=3000, bb=10, rb=5, max_hold=1000)])
            auto_backup(store, self.data, import_shared=False)
        finally:
            store.close()
        self.assertTrue((self.e / core.AUTO_BACKUP_NAME).is_file(), 'E: 側へ書き出す')
        status = json.loads((self.data / 'backup-output-meruhen.json').read_text(encoding='utf-8'))
        self.assertEqual(status['state'], 'success')

    def test_backup_reports_unavailable_when_nothing_matches(self):
        save_settings(self.data, sync_dir=str(self.g), sync_mark='mine')
        store = Store(self.data / 'database.sqlite3')
        try:
            auto_backup(store, self.data, import_shared=False)
        finally:
            store.close()
        status = json.loads((self.data / 'backup-output-meruhen.json').read_text(encoding='utf-8'))
        self.assertEqual(status['state'], 'unavailable')
        self.assertEqual(status['folder'], str(self.g), '設定の場所を出す（画面の知らせに使う）')

    def test_other_drive_letters_keep_the_rest_of_the_path(self):
        self.other.stop()
        try:
            found = core._other_drive_folders(PureWindowsPath('G:/マイドライブ/database共有'))
            self.assertIn(Path('E:/マイドライブ/database共有'), found)
            self.assertNotIn(Path('G:/マイドライブ/database共有'), found)
            self.assertEqual(core._other_drive_folders(PureWindowsPath('relative/folder')), [])
        finally:
            self.other.start()


if __name__ == '__main__':
    unittest.main()
