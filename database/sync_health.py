"""書き出し・Driveファイル更新・Google処理を別々に伝える。未確認の工程を成功にしない。"""
import json
import re
from datetime import datetime
from pathlib import Path


def _time(value):
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) and re.search(r'(Z|[+-]\d{2}:\d{2})$', value) else None
    except ValueError:
        return None


def sync_status_lines(status, exported_at=None, loaded_at=None):
    status = status if isinstance(status, dict) and status.get('version') == 1 else {}
    def when(value):
        at = _time(value)
        return at.astimezone().strftime('%Y/%m/%d %H:%M:%S') if at else '未確認'
    lines = []
    writes = status.get('writes', [])
    for w in writes[:3] if isinstance(writes, list) else []:
        if not isinstance(w, dict) or w.get('source') not in ('pc', 'android', 'browser'):
            continue
        label = {'pc': 'PC', 'android': 'Android', 'browser': 'iPhone・ブラウザ'}[w['source']]
        lines.append(f'{label}の書き出し：{when(w.get("at"))}／Driveファイルの更新：{when(w.get("drive_at"))}')
        for st in w.get('stores', []) if isinstance(w.get('stores'), list) else []:
            if not isinstance(st, dict):
                continue
            place = {'nagamachiminami':'長町南', 'saiwaichou':'幸町'}.get(st.get('store'), 'P’s CUBE')
            rate = f'（{st["rate"]}スロ）' if st.get('rate') else ''
            lines.append(f'この出力の最新日：{place}{rate} {st.get("day", "未確認")}・{st.get("count", "未確認")}台')
    if not lines:
        lines.append('元ファイルの書き出し：未確認')
    lines.append(f'Google側の処理：{when(status.get("processed_at"))}')
    if status.get('pending') or status.get('failed_inputs'):
        lines.append(f'Google側の処理待ち {status.get("pending", 0)}件・入力失敗 {status.get("failed_inputs", 0)}件')
    if exported_at is not None:
        lines.append(f'閲覧データの書き出し：{when(exported_at)}')
    if loaded_at is not None:
        lines.append(f'この端末の読み込み：{when(loaded_at)}')
    s = status.get('supplement')
    if isinstance(s, dict) and all(type(s.get(k)) is int and s[k] >= 0 for k in ('applied', 'known', 'mismatched', 'unmatched')):
        lines.append(f'スマホ補完：反映 {s["applied"]}件・取得済み {s["known"]}件・数値不一致 {s["mismatched"]}件・元記録なし {s["unmatched"]}件（{when(s.get("at"))}）')
    return lines


def synced_status(folder, site):
    if site not in ('meruhen', 'pscube') or not folder:
        return None
    path = Path(folder) / f'database-viewer-parts-{site}.json'
    try:
        if path.stat().st_size > 1024 * 1024:
            return None
        doc = json.loads(path.read_text(encoding='utf-8-sig'))
        if doc.get('format') != 'database-viewer-parts' or doc.get('site') != site:
            return None
        return doc.get('header', {}).get('sync_status')
    except (OSError, ValueError, AttributeError):
        return None


def local_net_lines(data_dir):
    """最新日の台だけを読む。取得・DB初期化・既存データの変更はしない。"""
    import sqlite3
    from contextlib import closing
    from pscube_health import net_capture_label
    path = Path(data_dir) / 'pscube.sqlite3'
    if not path.is_file():
        return ['P’s CUBE：PC内の記録ファイルなし']
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=0.2)) as db:
            rows = db.execute('''WITH days AS (
                SELECT json_extract(payload,'$.store') AS store,json_extract(payload,'$.rate') AS rate,
                       MAX(json_extract(payload,'$.day')) AS day FROM records GROUP BY store,rate)
                SELECT r.payload FROM records r JOIN days d ON json_extract(r.payload,'$.store')=d.store
                  AND json_extract(r.payload,'$.rate')=d.rate AND json_extract(r.payload,'$.day')=d.day''').fetchall()
        records = [json.loads(r[0]) for r in rows]
        groups = {}
        for r in records:
            groups.setdefault((r['store'], r['rate'], r['day']), []).append(r)
        lines = []
        for (store, rate, day), values in sorted(groups.items()):
            missing = [r for r in values if type(r.get('net_medals')) is not int]
            zero = sum(r.get('net_medals') == 0 for r in values)
            lines.append(f'P’s CUBE（{rate}スロ） {day}：{len(values)}台中{len(values)-len(missing)}台差枚取得済み（0枚{zero}台）・未取得{len(missing)}台')
            lines.extend(f'{r["rack"]}番 {r["machine"]}：{net_capture_label(r)}' for r in sorted(missing, key=lambda r: r['rack']))
        return lines or ['P’s CUBE：保存済みの台なし']
    except (sqlite3.Error, ValueError, KeyError):
        return ['P’s CUBE：取得状況を読めませんでした（取り込み中なら、少し待って読み直してください）。']
