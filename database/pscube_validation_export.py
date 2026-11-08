"""前向き検証の保存済み原本から閲覧用の小さなJSONを作る。"""
import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

from file_io import atomic_writer
from pscube_import import site777_final


FILE_NAME = 'validation-candidates.json'
JST = timezone(timedelta(hours=9))


def read_envelope(path):
    envelope = json.loads(path.read_text(encoding='utf-8'))
    payload = envelope['payload']
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False,
                         separators=(',', ':'), allow_nan=False).encode('utf-8')
    if hashlib.sha256(encoded).hexdigest() != envelope['sha256']:
        raise ValueError(f'{path.name} のハッシュが一致しません。')
    return payload, envelope['sha256']


def project_prediction(path, study_hash):
    prediction, _ = read_envelope(path)
    target = date.fromisoformat(prediction['target'])
    input_day = (target - timedelta(days=1)).isoformat()
    created_at = datetime.fromisoformat(prediction['created_at'])
    if (prediction['kind'] != 'prospective' or prediction['study_sha256'] != study_hash
            or path.stem != target.isoformat() or prediction['input_day'] != input_day
            or created_at.utcoffset() is None):
        raise ValueError(f'{path.name} はこの検証の事前予測ではありません。')
    saved = created_at.astimezone(JST)
    if saved.date() != target or saved.hour >= 9:
        raise ValueError(f'{path.name} は対象日の午前9時前の保存ではありません。')

    machines = []
    for group in prediction['groups']:
        if group['pool'] != 'main':
            continue
        methods = ['random_draw', 'date_two_exploratory']
        if target.day == 23:
            methods.insert(1, 'day23')
        machines.append({
            'name': group['model'],
            'candidates': {
                method: group['methods'][method]['selected_racks'] for method in methods
            },
        })
    records = prediction['input_snapshot']['records']
    preliminary = sum(row['day'] == input_day and row.get('source_site') == 'site777'
                      and not site777_final(row) for row in records)
    return {'target': target.isoformat(), 'input_day': input_day,
            'saved_at': saved.isoformat(timespec='seconds'), 'preliminary': preliminary,
            'machines': machines}


def export_validation(records, destination):
    study, study_hash = read_envelope(records / 'study.json')
    if study['store'] != 'c740601' or study['rate'] != '20' or study['cutoff_jst'] != '09:00':
        raise ValueError('P-STATIONの20スロ・午前9時締切の検証設定が必要です。')
    if not destination.is_dir():
        raise ValueError('出力先フォルダが見つかりません。')
    files = sorted((records / 'predictions').glob('????-??-??.json'), reverse=True)[:31]
    if not files:
        raise ValueError('保存済みの事前予測がありません。')
    days = [project_prediction(path, study_hash) for path in files]
    output = destination / FILE_NAME
    content = json.dumps({'format': 'pscube-validation', 'version': 1, 'days': days},
                         ensure_ascii=False, separators=(',', ':')) + '\n'
    if output.exists() and output.read_text(encoding='utf-8') == content:
        return len(days)
    with atomic_writer(output) as stream:
        stream.write(content)
    return len(days)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--records', type=Path, required=True)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument('--out-dir', type=Path)
    target.add_argument('--out-dir-file', type=Path)
    args = parser.parse_args()
    try:
        destination = args.out_dir
        if args.out_dir_file is not None:
            path = args.out_dir_file.read_text(encoding='utf-8-sig').strip()
            destination = Path(path)
            if not destination.is_absolute():
                raise ValueError('出力先は絶対パスで指定してください。')
        days = export_validation(args.records, destination)
    except (OSError, ValueError, TypeError, KeyError) as error:
        parser.exit(1, f'検証候補を出力できませんでした。{error}\n')
    print(f'検証候補 {days} 日分を出力しました。{destination / FILE_NAME}')


if __name__ == '__main__':
    main()
