"""不正なAndroidファイルは後続の同期を妨げず、DB障害は止める。"""
import gc
import json
import os
import sqlite3
import tempfile
import tkinter as tk
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
import app
import pscube_import
from core import load_settings, save_settings
from test_pscube_sync import machine, record


def setUpModule():
    gc.collect()  # 前のTkを転送スレッドのGCへ持ち越さない。


class BackgroundPscubeSyncTests(unittest.TestCase):
    def run_app(self, callback):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory); data=base/'data'; sync=base/'sync'; sync.mkdir()
            save_settings(data, auto_sync_on_start=False, sync_dir=str(sync), pscube_android_synced={})
            m=machine()
            def put(day, invalid=False):
                path=sync/f'pscube-day-android-{day}.json'
                payload=dict(format='pscube-viewer',version=1,kind='backup',source='android',machines=[m],
                             records=[record(m, 1, day)],rack_captures=[])
                path.write_text('{broken' if invalid else json.dumps(payload,ensure_ascii=False),encoding='utf-8')
                at=1000+int(day[-2:]);os.utime(path,(at,at));return path
            roots=[]; callbacks=[]; original_tk=tk.Tk
            def make_root():
                root=original_tk();root.withdraw();roots.append(root)
                original_after=root.after
                def after(ms, func=None, *args):
                    if getattr(func,'__name__','')=='poll_pscube_from_sync':
                        callbacks.append(func)
                        return 'review-sync-timer'
                    return original_after(ms,func,*args)
                root.after=after
                root.mainloop=lambda: callback(base,data,sync,put,callbacks[0])
                return root
            try:
                with patch.object(app,'ROOT',base),patch.object(app,'DATA_DIR',data),patch.object(app.tk,'Tk',make_root):
                    app.main()
            finally:
                for root in roots:root.destroy()

    def test_broken_file_does_not_block_good_file_and_is_retried_after_repair(self):
        def check(base,data,sync,put,poll):
            bad=put('2026-10-25',invalid=True);good=put('2026-10-26')
            original=pscube_import.PscubeStore.import_backup
            applied=[]
            def track(store,source,**kwargs):
                if isinstance(source,dict) and not kwargs.get('_validate_only'):
                    applied.extend(r['day'] for r in source['records'])
                return original(store,source,**kwargs)
            with patch.object(pscube_import.PscubeStore,'import_backup',track):
                poll();poll()
            self.assertEqual(applied,['2026-10-26'], '正常な同じ版は2回読み込まない')
            seen=load_settings(data)['pscube_android_synced']
            self.assertNotIn(bad.name,seen);self.assertIn(good.name,seen)
            self.assertEqual(bad.read_text(encoding='utf-8'),'{broken')
            with closing(pscube_import.PscubeStore(data/'pscube.sqlite3')) as store:
                self.assertEqual(store.days(),['2026-10-26'])
            put('2026-10-25');poll()
            seen=load_settings(data)['pscube_android_synced'];self.assertIn(bad.name,seen)
            with closing(pscube_import.PscubeStore(data/'pscube.sqlite3')) as store:
                self.assertEqual(store.days(),['2026-10-26','2026-10-25'])
        self.run_app(check)

    def test_schema_invalid_file_does_not_block_good_file(self):
        def check(base,data,sync,put,poll):
            bad=put('2026-10-25');bad.write_text('{"format":"other"}',encoding='utf-8');os.utime(bad,(1025,1025))
            good=put('2026-10-26');poll()
            seen=load_settings(data)['pscube_android_synced']
            self.assertNotIn(bad.name,seen);self.assertIn(good.name,seen)
        self.run_app(check)

    def test_database_failure_stops_batch_without_marking_any_file_read(self):
        def check(base,data,sync,put,poll):
            put('2026-10-25');put('2026-10-26')
            with patch.object(pscube_import.PscubeStore,'import_backup',side_effect=sqlite3.OperationalError('database is locked')) as load:
                poll()
            self.assertEqual(load.call_count,1)
            self.assertEqual(load_settings(data)['pscube_android_synced'],{})
        self.run_app(check)
