"""Stage the read-only share page (share_viewer/, trial 2026-10-09) into its own public repository clone.

Usage (from database_android/):
    python tool/stage_share_viewer.py <folder of the share page clone>

自分用の閲覧ページ（database-viewer、tool/stage_viewer.py）とは別のリポジトリに置く。ページにはスクリプトの
URL・ID も記録も入れない（IDは渡すリンクの # の後ろだけ）。入っていたら公開しない。
"""
import hashlib
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
SOURCE = HERE.parent / 'share_viewer'
TEXT_FILES = {'index.html', 'app.mjs', 'data.mjs', 'net.mjs', 'manifest.json', 'viewer_parts.mjs'}
FILES = TEXT_FILES | {'apple-touch-icon.png', 'favicon.png', 'icon-192.png', 'icon-512.png'}
SCRIPT_ID = re.compile(rb'AKfyc[A-Za-z0-9_-]{20,}|/macros/s/[A-Za-z0-9_-]{20,}')

# ページが読むファイルの参照（どれも1か所だけ）。公開のたびに中身から作った版 ?v= を付ける。
# iPhoneのSafariは前の版の app.mjs・data.mjs を覚えたまま使い、公開しても古い画面のままになった
# （2026-10-10、利用者「強かった機種5選がゲーム数ランキング10に切り替わってない」）。
REFERENCES = (
    ('index.html', 'src="./app.mjs"'),
    ('app.mjs', "from './data.mjs'"),
    ('app.mjs', "from './viewer_parts.mjs'"),
    ('data.mjs', "from './net.mjs'"),
    ('index.html', 'href="./apple-touch-icon.png"'),
    ('index.html', 'href="./favicon.png"'),
    ('index.html', 'href="./manifest.json"'),
    ('manifest.json', '"./icon-192.png"'),
    ('manifest.json', '"./icon-512.png"'),
)


def version_of(files):
    digest = hashlib.sha256()
    for name in sorted(files):
        digest.update(name.encode() + b'\0' + (SOURCE / name).read_bytes() + b'\0')
    return digest.hexdigest()[:12]


def stamped(name, text, version):
    for file, reference in REFERENCES:
        if file != name:
            continue
        if text.count(reference) != 1:
            sys.exit(f'{name} の {reference} が1か所ではありません。版を付けられないので公開しません。')
        text = text.replace(reference, reference[:-1] + f'?v={version}' + reference[-1])
    return text


README = """# database カレンダー（閲覧専用）

イベントカレンダー（各日のイベント・総差枚、日付を押すと差枚TOP50と強かった機種10選、台を押すとその機種の台一覧と台のデータ）と、バラエティの回っていない台・バラエティ🌈（確定が出た台の印）を見るページです。

- このリポジトリには、ページのファイルだけが入っています。記録のデータや接続先は入っていません。
- 記録は、受け取ったリンクの接続先（読むだけのGoogle Apps Script）から、開いた端末のブラウザが直接読みます。
- 書き込むのは🌈（確定が出た台の印）だけです。押したときに、その接続先へ送ります。記録やイベントは書き換えません。
- 端末には接続先と表示の選択（店舗・回っていない台の期間とゲーム数・バラエティ🌈の並べ方）と、付けた🌈を覚えます。差分読み込みでは接続先ごとに記録のキャッシュも保存します。ブラウザが削除した場合は次回取り直します。
"""


def main(target):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from stage_viewer import record_probes

    target = Path(target)
    present = {p.name for p in SOURCE.iterdir() if p.is_file()}
    if present != FILES:
        sys.exit(f'share_viewer のファイルを確認してください: {sorted(present)}')
    probes = record_probes()
    for name in sorted(FILES):
        data = (SOURCE / name).read_bytes()
        if SCRIPT_ID.search(data):
            sys.exit(f'{name} にスクリプトのURL・IDらしい文字列があります。公開しません。')
        if any(p.encode() in data for p in probes):
            sys.exit(f'{name} に記録らしい文字列があります。公開しません。')
    target.mkdir(parents=True, exist_ok=True)
    for entry in target.iterdir():
        if entry.name == '.git':
            continue
        shutil.rmtree(entry) if entry.is_dir() else entry.unlink()
    version = version_of(FILES)
    for name in sorted(FILES):
        if name in TEXT_FILES:
            text = (SOURCE / name).read_text(encoding='utf-8')
            (target / name).write_text(stamped(name, text, version), encoding='utf-8', newline='\n')
        else:
            shutil.copyfile(SOURCE / name, target / name)
    (target / '.nojekyll').write_text('', encoding='utf-8')
    (target / 'README.md').write_text(README, encoding='utf-8')
    print(f'OK: {target} に閲覧専用ページを用意しました（{len(FILES)}ファイル、版 {version}、記録の文字列 {len(probes)} 種・スクリプトのIDで確認、該当なし）。')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
