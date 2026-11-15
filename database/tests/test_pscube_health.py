"""診断の保持・秘匿情報の除去・元数値の期限と保存済み数値の保護。"""
import copy
import json
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from pscube_health import validate_net_capture, trim_net_probes, net_capture_label, viewer_net_capture
from pscube_import import PscubeStore
from sync_health import sync_status_lines


def fixture():
    d = json.loads((Path(__file__).parent / 'fixtures/pscube_net_capture.json').read_text(encoding='utf-8'))
    d['records'][0]['net_capture']['checked_at'] = datetime.now(timezone.utc).isoformat(timespec='milliseconds')
    return d


class PscubeHealthTests(unittest.TestCase):
    def test_diagnostics_roundtrip_and_light_view_does_not_publish_raw_probe(self):
        d = fixture()
        with tempfile.TemporaryDirectory() as tmp:
            with closing(PscubeStore(Path(tmp) / 'pscube.sqlite3')) as store:
                store.import_backup(d)
                full = store.export_payload()
                self.assertIn('probe', full['records'][0]['net_capture'])
                light = store.export_payload('viewer')
                self.assertNotIn('probe', light['records'][0]['net_capture'])
                self.assertTrue(light['records'][0]['net_capture']['probe_available'])
                self.assertTrue(viewer_net_capture(light['records'][0]['net_capture'])['probe_available'])
                incoming = copy.deepcopy(d)
                incoming['records'][0]['net_capture'].pop('probe')
                store.import_backup(incoming)
                self.assertIn('probe', store.export_payload()['records'][0]['net_capture'])

    def test_only_fixed_numeric_fields_survive_and_mismatched_diagnostics_are_rejected(self):
        d = fixture()
        row = d['records'][0]
        cap = row['net_capture']
        cap['token'] = 'credential-sentinel'
        cap['probe']['graph']['apikey'] = 'credential-sentinel'
        cap['probe']['graph']['datas']['p'][0]['token'] = 'credential-sentinel'
        checked = validate_net_capture(cap, row)
        self.assertNotIn('credential-sentinel', json.dumps(checked))
        with self.assertRaises(ValueError):
            validate_net_capture(cap, {**row, 'games': 301})

    def test_expired_probe_is_removed_without_changing_record_or_turning_unknown_into_zero(self):
        row = fixture()['records'][0]
        old = copy.deepcopy(row)
        now = datetime.fromisoformat(row['net_capture']['checked_at']).timestamp() + 8 * 86400
        trim_net_probes([row], now=now)
        self.assertNotIn('probe', row['net_capture'])
        self.assertEqual(row['games'], old['games'])
        self.assertIsNone(row['net_medals'])
        self.assertEqual(net_capture_label({**row, 'net_medals': 0}), '取得済み（0枚）')

    def test_pc_status_window_no_longer_shows_the_pscube_net_summary(self):
        # 2026-11-15 利用者「P’s CUBE（20スロ） 2026-11-14：289台中0台差枚取得済み…この表記をすべてからなくしてほしい」。
        # ソースの文字ではなく、窓に出す文そのもので確かめる（2026-11-15 レビュー）。差枚が未取得の台を保存してあっても出さない。
        import sync_health
        from types import SimpleNamespace
        from backup_status_ui import BackupStatusPanel
        self.assertFalse(hasattr(sync_health, 'local_net_lines'))
        with tempfile.TemporaryDirectory() as tmp:
            with closing(PscubeStore(Path(tmp) / 'pscube.sqlite3')) as store:
                store.import_backup(fixture())
            panel = SimpleNamespace(_busy=False, folder=lambda: None, data_dir=tmp,
                                    source_text=lambda source: f'{source}の書き出し：試験')
            text = BackupStatusPanel.details_text(panel)
        self.assertIn('pscubeの書き出し：試験', text)
        self.assertIn('同期フォルダ：未設定', text)
        for gone in ('差枚取得状況', '差枚取得済み', '未取得', '応答の形式不正'):
            self.assertNotIn(gone, text)

    def test_unknown_cloud_progress_is_not_reported_as_success(self):
        lines = sync_status_lines(None)
        self.assertIn('Google側の処理：未確認', lines)
        self.assertFalse(any('成功' in line for line in lines))
