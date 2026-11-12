"""Stage the read-only share page (share_viewer/, trial 2026-10-09) into its own public repository clone.

Usage (from database_android/):
    python tool/stage_share_viewer.py <folder of the share page clone>

自分用の閲覧ページ（database-viewer、tool/stage_viewer.py）とは別のリポジトリに置く。ページにはスクリプトの
URL・ID も記録も入れない（IDは渡すリンクの # の後ろだけ）。入っていたら公開しない。
"""
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
SOURCE = HERE.parent / 'share_viewer'
SOURCE_TEXT_FILES = {'index.html', 'app.mjs', 'daily_learning.mjs', 'event_history.mjs', 'recommendations.mjs', 'data.mjs', 'net.mjs', 'manifest.json', 'viewer_parts.mjs', 'offline.mjs', 'sw.js', 'capture_health.mjs'}
SOURCE_FILES = SOURCE_TEXT_FILES | {'apple-touch-icon.png', 'favicon.png', 'icon-192.png', 'icon-512.png'}
# Android入口は共通HTMLとmanifestから生成する。独立したUIやHTMLの二重管理はしない。
GENERATED_FILES = {'android.html', 'manifest-android.json', 'character_birthdays.json'}
# キャラ誕生日（EVENT_CALENDAR.md「キャラ誕生日」）。PC・Flutterと同じアセット1つから作り、二重に持たない。
BIRTHDAYS = HERE / 'assets' / 'character_birthdays.json'
TEXT_FILES = SOURCE_TEXT_FILES | GENERATED_FILES
FILES = SOURCE_FILES | GENERATED_FILES
SCRIPT_ID = re.compile(rb'AKfyc[A-Za-z0-9_-]{20,}|/macros/s/[A-Za-z0-9_-]{20,}')

# ページが読むファイルの参照（どれも1か所だけ）。公開のたびに中身から作った版 ?v= を付ける。
# iPhoneのSafariは前の版の app.mjs・data.mjs を覚えたまま使い、公開しても古い画面のままになった
# （2026-10-10、利用者「強かった機種5選がゲーム数ランキング10に切り替わってない」）。
REFERENCES = (
    ('index.html', 'src="./app.mjs"'),
    ('app.mjs', "from './data.mjs'"),
    ('app.mjs', "from './capture_health.mjs'"),
    ('app.mjs', "from './daily_learning.mjs'"),
    ('daily_learning.mjs', "from './data.mjs'"),
    ('app.mjs', "from './viewer_parts.mjs'"),
    ('app.mjs', "from './offline.mjs'"),
    ('data.mjs', "from './net.mjs'"),
    ('index.html', 'href="./apple-touch-icon.png"'),
    ('index.html', 'href="./favicon.png"'),
    ('index.html', 'href="./manifest.json"'),
    ('manifest.json', '"./icon-192.png"'),
    ('manifest.json', '"./icon-512.png"'),
    ('app.mjs', "'./character_birthdays.json'"),
    ('app.mjs', "from './event_history.mjs'"),
    ('app.mjs', "from './recommendations.mjs'"),
    ('android.html', 'src="./app.mjs"'),
    ('android.html', 'href="./apple-touch-icon.png"'),
    ('android.html', 'href="./favicon.png"'),
    ('android.html', 'href="./manifest-android.json"'),
    ('manifest-android.json', '"./icon-192.png"'),
    ('manifest-android.json', '"./icon-512.png"'),
)


def version_of(files):
    digest = hashlib.sha256()
    for name in sorted(files):
        digest.update(name.encode() + b'\0' + files[name] + b'\0')
    return digest.hexdigest()[:12]


def publication_files():
    present = {p.name for p in SOURCE.iterdir() if p.is_file()}
    if present != SOURCE_FILES:
        sys.exit(f'share_viewer のファイルを確認してください: {sorted(present)}')
    files = {name: (SOURCE / name).read_bytes() for name in SOURCE_FILES}
    html = files['index.html'].decode('utf-8')
    reference = 'href="./manifest.json"'
    if html.count(reference) != 1:
        sys.exit('index.html のmanifest参照が1か所ではありません。Android入口を生成できません。')
    files['android.html'] = html.replace(reference, 'href="./manifest-android.json"').encode('utf-8')
    manifest = json.loads(files['manifest.json'])
    if manifest.get('display') != 'browser':
        sys.exit('既存manifestの起動設定がbrowserではありません。既存設定を確認してから公開してください。')
    android = {**manifest, 'id': './android.html', 'start_url': './android.html', 'display': 'standalone'}
    files['manifest-android.json'] = (json.dumps(android, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    birthdays = json.loads(BIRTHDAYS.read_text(encoding='utf-8'))
    if not isinstance(birthdays, dict) or not isinstance(birthdays.get('entries'), list) or not birthdays['entries']:
        sys.exit('キャラ誕生日のファイルの形が違います。公開しません。')
    files['character_birthdays.json'] = (json.dumps(birthdays, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    return files


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
- カレンダーの🎂（キャラ誕生日）は `character_birthdays.json` を読みます。公開されている誕生日一覧から作った名前・作品・月日だけです。
- 長町南の週イベント履歴は、台データと同じ接続先の `?file=event-history` から読みます。履歴JSONを公開ファイルには含めません。対応するApps Scriptへ更新すると、共有ページでも既存週表の結果記号を選んで保存できます。
- 記録は、受け取ったリンクの接続先（読むだけのGoogle Apps Script）から、開いた端末のブラウザが直接読みます。
- 書き込むのは🌈（確定が出た台の印）と、イベント履歴の結果記号です。4大オススメの台別顔文字も保存できます。PCが作った週の構成、台の数値、カレンダーのイベント名は変更しません。
- 端末には接続先と表示の選択（店舗・回っていない台の期間とゲーム数・バラエティ🌈の並べ方）と、付けた🌈を覚えます。差分読み込みでは接続先ごとに記録のキャッシュも保存します。ブラウザが削除した場合は次回取り直します。
- Android Chrome用の入口は `android.html`。接続先を設定してChromeのメニューから「アプリをインストール」（表示によっては「ホーム画面に追加」→「インストール」）を選びます。ホーム画面から独立した画面で起動するための専用manifestを使用し、通常ページと同じ設定・🌈・差分キャッシュを使います。元の共有リンクは `#` 以降をAndroid用URLへそのまま付けても使えます。
- 既存の `index.html` とmanifestの `display: browser` は維持しています。Android用だけ `display: standalone` です。元写真・実記録・接続先IDは配布しません。Android実機のインストール動作は別途確認が必要です。
"""


def main(target):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from stage_viewer import record_probes

    target = Path(target)
    files = publication_files()
    probes = record_probes()
    for name in sorted(FILES):
        data = files[name]
        if SCRIPT_ID.search(data):
            sys.exit(f'{name} にスクリプトのURL・IDらしい文字列があります。公開しません。')
        if any(p.encode() in data for p in probes):
            sys.exit(f'{name} に記録らしい文字列があります。公開しません。')
    target.mkdir(parents=True, exist_ok=True)
    for entry in target.iterdir():
        if entry.name == '.git':
            continue
        shutil.rmtree(entry) if entry.is_dir() else entry.unlink()
    version = version_of(files)
    for name in sorted(FILES):
        if name in TEXT_FILES:
            text = files[name].decode('utf-8')
            if name == 'sw.js':
                shell = ['./index.html', './android.html'] + [f'./{n}?v={version}' for n in sorted(FILES - {'index.html', 'android.html', 'sw.js'})]
                text = re.sub(r"const VERSION = '[^']+';", f"const VERSION = '{version}';", text)
                text = re.sub(r'const FILES = \[.*?\];', 'const FILES = ' + json.dumps(shell) + ';', text, flags=re.S)
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
