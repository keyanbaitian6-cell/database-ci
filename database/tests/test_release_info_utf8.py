"""照合版の生成はOSの既定文字コードに依存せず、UTF-8を保持する。"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ReleaseInfoEncodingTests(unittest.TestCase):
    def test_generator_uses_explicit_encoding_and_writes_utf8(self):
        source=Path(__file__).resolve().parents[2]/'database_android/tool/build_release_info.py'
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in ('database','database_android/lib','database_android/web','database_android/tool','share_viewer'):
                (root/name).mkdir(parents=True)
            script=root/'database_android/tool/build_release_info.py'
            script.write_bytes(source.read_bytes())
            (root/'database/unicode.py').write_text('# 日本語の資料と差枚\n',encoding='utf-8')
            for name in ('database_android/web/capture_health.mjs','database_android/tool/viewer_parts_core.js'):
                (root/name).write_text('// 日本語を保持\n',encoding='utf-8')
            env={**os.environ,'PYTHONWARNDEFAULTENCODING':'1','PYTHONWARNINGS':'error::EncodingWarning','PYTHONIOENCODING':'utf-8'}
            result=subprocess.run([sys.executable,'-X','utf8=0',str(script)],capture_output=True,encoding='utf-8',env=env)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('生成元',(root/'database/release_info.py').read_text(encoding='utf-8'))
            self.assertIn('日本語を保持',(root/'database_android/web/capture_health.mjs').read_text(encoding='utf-8'))


    def test_script_edits_change_release_but_generated_tail_does_not(self):
        source=Path(__file__).resolve().parents[2]/'database_android/tool/build_release_info.py'
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in ('database','database_android/lib','database_android/web','database_android/tool','share_viewer'):
                (root/name).mkdir(parents=True)
            script=root/'database_android/tool/build_release_info.py'
            script.write_bytes(source.read_bytes())
            for name in ('database_android/web/capture_health.mjs','database_android/tool/viewer_parts_core.js'):
                (root/name).write_text('// 日本語\n',encoding='utf-8')
            gs=root/'database_android/tool/viewer_drive_script.gs'
            def run(prefix,tail):
                gs.write_text(prefix+'\n// BEGIN GENERATED VIEWER PARTS\n'+tail,encoding='utf-8')
                result=subprocess.run([sys.executable,str(script)],capture_output=True,encoding='utf-8')
                self.assertEqual(result.returncode,0,result.stderr)
                return (root/'database/release_info.py').read_text(encoding='utf-8')
            first=run('const limit = 5000;','old generated')
            self.assertEqual(run('const limit = 5000;','new generated'),first)
            second=run('const limit = 10000;','new generated')
            self.assertNotEqual(first,second)
            self.assertEqual(run('const limit = 10000;','new generated'),second)
