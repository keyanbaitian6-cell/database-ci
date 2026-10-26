"""既存の設定を引き継いだGoogle更新用ファイルを、別フォルダーへ作る。"""
import argparse
import hashlib
import json
import re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
FILES=('pscube_cloud_sync.gs','meruhen_cloud_sync.gs','viewer_drive_script.gs','viewer_drive_script_readonly.gs')
SETTING=re.compile(r"(?m)^(const\s+((?:PSCUBE|MERUHEN)_(?:FOLDER_ID|INCREMENTAL_VIEWER|HISTORY_VIEWER))\s*=\s*)([^;\n]+)(;)")
def prepare(existing, output):
    prepared={}
    for name in FILES:
        old=(existing/name).read_text(encoding='utf-8-sig')
        current=(ROOT/'database_android/tool'/name).read_text(encoding='utf-8')
        values={}
        for match in SETTING.finditer(old):
            key,value=match[2],match[3].strip()
            if key in values: raise ValueError(f'{name}の{key}が重複しています。')
            if key.endswith('FOLDER_ID'):
                if not re.fullmatch(r"'[^'\\\r\n]*'|\"[^\"\\\r\n]*\"",value): raise ValueError(f'{name}の{key}は文字列の設定を確認してください。')
            elif value not in ('true','false'): raise ValueError(f'{name}の{key}は真偽値を確認してください。')
            values[key]=value
        required={m[2] for m in SETTING.finditer(current)}
        if required != set(values): raise ValueError(f'{name}の既存の設定項目が一致しません。手動で確認してください。')
        prepared[name]=SETTING.sub(lambda m:m[1]+values[m[2]]+m[4],current)
    # 全入力を確認してから新しい専用フォルダだけへ書く。元ファイルは変更しない。
    output.mkdir(parents=True,exist_ok=False)
    manifest={}
    for name,text in prepared.items():
        (output/name).write_text(text,encoding='utf-8')
        manifest[name]={'sha256':hashlib.sha256(text.encode()).hexdigest()}
    (output/'内容照合.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    (output/'更新手順.md').write_text('既存のGoogleプロジェクトへ対応する同名ファイルを貼り付けます。閲覧用2本は既存デプロイを新バージョンへ更新します。URL・スクリプトプロパティ・既存トリガーを維持します。自動統合2本は保存後に既存の同期関数を各1回実行します。新しいプロジェクトやトリガーは作りません。設定を含む更新ファイルは公開リポジトリへ入れないでください。\n',encoding='utf-8')
    print('既存の設定を維持した更新用4本を作成しました。')
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('existing',type=Path,help='現在運用中の4本を同名で保存したフォルダー')
    parser.add_argument('output',type=Path,help='新しく作る更新用フォルダー')
    args=parser.parse_args();prepare(args.existing,args.output)
