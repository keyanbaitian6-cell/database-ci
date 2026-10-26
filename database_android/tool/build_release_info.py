"""生成元の内容から4画面とGoogleの照合用の版を作る。設定値や記録は含めない。"""
import hashlib
import re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
EXCLUDED={'database/release_info.py','database_android/lib/release_info.dart','database_android/web/viewer_parts.mjs','share_viewer/viewer_parts.mjs','share_viewer/capture_health.mjs'}
paths=[]
for directory in ['database','database_android/lib','database_android/web','database_android/tool','share_viewer']:
    for p in (ROOT/directory).rglob('*'):
        name=p.relative_to(ROOT).as_posix()
        if p.is_file() and not p.name.startswith('test_') and not any(part in ('test','tests') for part in p.relative_to(ROOT).parts) and p.suffix in {'.py','.dart','.js','.mjs','.html'} and name not in EXCLUDED and not any(part.startswith('.') or part=='__pycache__' for part in p.relative_to(ROOT).parts): paths.append(p)
h=hashlib.sha256()
for p in sorted(set(paths)):
    text=p.read_text(encoding='utf-8').replace('\r\n','\n')
    text=re.sub(r"(?:export )?const (?:APPLICATION_RELEASE|SCRIPT_RELEASE) = '[a-f0-9]{12}';\n",'',text)
    h.update(p.relative_to(ROOT).as_posix().encode()+b'\0'+text.encode()+b'\0')
version=h.hexdigest()[:12]
(ROOT/'database/release_info.py').write_text(f"# 生成元: database_android/tool/build_release_info.py\nAPPLICATION_RELEASE = '{version}'\n", encoding='utf-8')
(ROOT/'database_android/lib/release_info.dart').write_text(f"// 生成元: tool/build_release_info.py\nconst applicationRelease = '{version}';\n", encoding='utf-8')
for name,identifier,prefix in [('database_android/web/capture_health.mjs','APPLICATION_RELEASE','export '),('database_android/tool/viewer_parts_core.js','SCRIPT_RELEASE','')]:
    p=ROOT/name;text=p.read_text(encoding='utf-8');text=re.sub(r"(?:export )?const "+identifier+r" = '[a-f0-9]{12}';\n",'',text)
    p.write_text(f"{prefix}const {identifier} = '{version}';\n"+text, encoding='utf-8')
print(f'更新照合用の版：{version}')
