"""Stage the built view-only page for the public repository, with no records.

Usage (from database_android/):
    flutter build web -t lib/viewer_main.dart --release --base-href /database-viewer/
    python tool/stage_viewer.py <folder of the database-viewer clone>
    python tool/stage_viewer.py --pscube-only <folder of the database-viewer clone>

Flutter bundles every asset for the web too, including assets/database_seed.json
(real records). This copies build/web into the target folder (replacing what
is there except .git), removes that file, and then refuses to finish if any
string that only exists in the records is still found.
"""
import json
import os
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
BUILD = HERE / 'build' / 'web'
SEED = HERE / 'assets' / 'database_seed.json'
PSCUBE = HERE / 'web' / 'pscube'
# P’s CUBE版（pscube/ の中）が読む、閲覧ページと共通の部品（../ の .mjs）。P’s CUBE版だけを公開するとき写す。
# 2026-11-22（Geminiの点検 H-12②）：shared_events.mjs が抜けていた。抜けを止めるため、実際に読む部品と照合する（pscube_shared_imports）。
PSCUBE_SHARED = ('drive_fetch.mjs', 'viewer_parts.mjs', 'backup_stream.mjs', 'capture_health.mjs', 'storage_report.mjs', 'shared_events.mjs')
PSCUBE_FILES = {'index.html', 'data.mjs', 'archive.mjs', 'scoring.mjs', 'sync.mjs', 'graph_probe.mjs', 'viewer_bridge.mjs', 'viewer_bootstrap.mjs'}

README = """# database 閲覧

databaseのバックアップ（JSON）を、自分の端末の中だけで読み込んで見るための閲覧専用ページです。

- このリポジトリには、ページのコンパイル済みファイルだけが入っています。記録のデータは入っていません。
- 読み込んだバックアップは、開いた端末のブラウザの中だけで使い、どこにも送信しません。
- 長町南の週イベント履歴は設定済みの接続先から閲覧します。履歴JSONをこの公開リポジトリには含めません。
"""


def record_probes():
    if not SEED.exists():
        return set()
    probes = set()
    for row in json.loads(SEED.read_text(encoding='utf-8')).get('rows', []):
        image = (row.get('graph_measurement') or {}).get('preview_image') or ''
        if len(image) > 200:
            probes.add(image[100:160])
        for key in ('detail_url', 'captured_at', 'source_url'):
            if row.get(key):
                probes.add(str(row[key]))
    return {p for p in probes if len(p) >= 15}


def pscube_shared_imports():
    """P’s CUBE版のファイルが読む共通の部品（../x.mjs）と、その部品が読む同じ階層の部品（./x.mjs）の名前。"""
    names = set()
    for name in PSCUBE_FILES:
        names |= set(re.findall(r"""['"]\.\./([A-Za-z0-9_]+\.mjs)['"]""", (PSCUBE / name).read_text(encoding='utf-8')))
    pending = list(names)
    while pending:
        text = (HERE / 'web' / pending.pop()).read_text(encoding='utf-8')
        for found in re.findall(r"""['"]\./([A-Za-z0-9_]+\.mjs)['"]""", text):
            if found not in names:
                names.add(found)
                pending.append(found)
    return names


def stage_pscube(target):
    """Add P's CUBE's input bridge for the shared Flutter viewer."""
    target = Path(target)
    dest = target / 'pscube'
    existing = {p.name for p in PSCUBE.iterdir() if p.is_file()}
    if existing != PSCUBE_FILES:
        sys.exit(f'P’s CUBEの公開ファイルを確認してください: {sorted(existing)}')
    if not (target / 'main.dart.js').exists() or b'pscube-viewer' not in (target / 'main.dart.js').read_bytes():
        sys.exit('共通閲覧画面の新しいFlutterビルドが必要です。先に全体をstageしてください。')
    if dest.exists() and any(p.name not in PSCUBE_FILES | {'app.mjs', 'style.css'} for p in dest.iterdir()):
        sys.exit('公開先のpscubeフォルダに未知のファイルがあります。')
    missing = pscube_shared_imports() - set(PSCUBE_SHARED)
    if missing:
        sys.exit(f'P’s CUBE版が読む共通の部品が、写す一覧（PSCUBE_SHARED）にありません: {sorted(missing)}')
    for name in PSCUBE_SHARED:
        data = (HERE / 'web' / name).read_bytes()
        if any(p.encode() in data for p in record_probes()):
            sys.exit(f'{name} に記録らしい文字列があります。公開しません。')
        (target / name).write_bytes(data)
    dest.mkdir(parents=True, exist_ok=True)
    for obsolete in ('app.mjs', 'style.css'):
        (dest / obsolete).unlink(missing_ok=True)
    probes = record_probes()
    for name in sorted(PSCUBE_FILES):
        data = (PSCUBE / name).read_bytes()
        if any(p.encode() in data for p in probes):
            sys.exit(f'{name} に記録らしい文字列があります。公開しません。')
        if b'WebMainResource' in data and name not in {'archive.mjs', 'viewer_bridge.mjs'}:
            sys.exit(f'{name} にWebアーカイブの内容が混入しています。')
        (dest / name).write_bytes(data)
    print(f'OK: {dest} にP’s CUBEの公開ファイルだけを用意しました（記録の文字列 {len(probes)} 種で確認、該当なし）。')


def main(target):
    target = Path(target)
    if not (BUILD / 'index.html').exists():
        sys.exit('build/web がありません。先に flutter build web を実行してください。')
    target.mkdir(parents=True, exist_ok=True)
    for entry in target.iterdir():
        if entry.name == '.git':
            continue
        shutil.rmtree(entry) if entry.is_dir() else entry.unlink()
    shutil.copytree(BUILD, target, dirs_exist_ok=True)
    for leftover in (target / 'assets' / 'assets' / 'database_seed.json', target / 'assets' / 'assets' / 'event_history.json', target / '.last_build_id'):
        leftover.unlink(missing_ok=True)
    seed_dir = target / 'assets' / 'assets'
    if seed_dir.exists() and not any(seed_dir.iterdir()):
        seed_dir.rmdir()
    (target / '.nojekyll').write_text('', encoding='utf-8')
    (target / 'README.md').write_text(README, encoding='utf-8')

    probes = record_probes()
    hits = []
    for root, _, files in os.walk(target):
        if '.git' in Path(root).parts:
            continue
        for name in files:
            data = (Path(root) / name).read_bytes()
            hits += [(name, p[:30]) for p in probes if p.encode() in data]
    if any(Path(root, f).name.startswith('database_seed') or f == 'event_history.json' for root, _, fs in os.walk(target) for f in fs):
        hits.append(('database_seed.json', 'file'))
    if hits:
        sys.exit(f'記録らしい文字列が残っています。公開しないでください：{hits[:5]}')
    print(f'OK: {target} に閲覧ページを用意しました（記録の文字列 {len(probes)} 種で確認、該当なし）。')


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--pscube-only':
        stage_pscube(sys.argv[2])
    elif len(sys.argv) == 2:
        main(sys.argv[1])
    else:
        sys.exit(__doc__)
