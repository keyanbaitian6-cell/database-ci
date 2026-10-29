"""P's CUBE browser capture with its own SQLite records and viewer JSON export.

The usual Meruhen database is deliberately separate: its kind_code, stores,
hold score and backup schema have different meanings. Site authentication is
performed by the person in the embedded browser; this module reads rendered DOM.
"""
from __future__ import annotations

import json
import hashlib
import math
import os
import re
import secrets
import shutil
import sqlite3
import sys
import threading
import unicodedata
import time
from contextlib import closing, nullcontext
from datetime import date, datetime, timedelta, timezone
from file_io import atomic_copy, atomic_writer, take_notice, write_notice
import input_versions
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from auto_capture import AutoCapture
from pscube_health import validate_net_capture, trim_net_probes, merge_net_capture, viewer_net_capture
from pscube_connection import BrowserConnection, install_webview2_handlers, present_connection_failure, retry_page, stop_navigation

# バックアップ・Drive同期（仕様：PSCUBE_SYNC.md）。メルヘンの database-backup-* とは名前を分ける。
AUTO_BACKUP_NAME = 'pscube-backup-auto.json'
VIEWER_DRIVE_NAME = 'pscube-viewer-drive.json'
SNAPSHOT_PATTERN = 'pscube-backup-????-??-??.json'
SNAPSHOT_KEEP_DAYS = 7
VIEWER_DAYS = 31
VIEWER_GRAPH_POINTS = 16
MAX_BACKUP_RECORDS = 200000
SHOP = 'c740601'
HOST = 'www.pscube.jp'
ROOT_URL = f'https://{HOST}/dedamajyoho-P-townDMMpachi/{SHOP}/'
FORMAT = 'pscube-viewer'
# 営業日の切り替わり時刻。日本時間の午前3時まではまだ前日の営業日（利用者の指定、2026-10-04は2時、2026-10-26に3時へ）。
BUSINESS_DAY_CUTOFF_HOUR = 3
# 営業が終わった日の数値を最終とみなす基準（翌日2時。STALE_MARGIN_HOURS を引いてその日の23時）。閉店後の時刻なので
# 営業日の切り替え（3時）とは別に2時のまま。3時にすると23時〜0時に取った分を取り直しに行き、アクセスが増えるだけ。
DAY_FINAL_HOUR = 2
DIRECTIONS = ('top', 'bottom')
# 取り込み日の日付タブがサイトに無かった機種と日（新台・入れ替え）。その日の未取得に数えない（2026-10-19）。
ABSENT_DAYS_KEY = 'absent_table_days'
# 過去の日の全台一覧で、その日の数値もリンクも無かった台（増台した台）。台数の確認と未取得の数え方に足す（2026-10-19）。
ABSENT_RACKS_KEY = 'absent_table_racks'
PACKAGE_ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent))
CAPTURE = PACKAGE_ROOT / 'database_android' / 'assets' / 'pscube_capture.js'
PROBE = PACKAGE_ROOT / 'database_android' / 'assets' / 'pscube_auto_probe.js'

SCROLL_SCRIPT = r'''(async () => {
  // 台数の多い機種の全台一覧を、サイトの続きの読み込み（一番下に着いたときに始まる）に合わせて表示する。
  // 以前は350ミリ秒ごとに毎回一番下へ飛んでいたため、読み込みの途中で何度も押し込んでしまい、
  // 読み込みが詰まって止まることがあった（2026-10-04、利用者の報告）。
  // 今は、少しずつ進み、一番下に着いたら新しい台が出るまで待つ（待つ間は下へ押し込まない）。
  // 4秒たっても増えないときだけ、少し戻ってもう一度下へ進む（最大5回）。
  const findList = () => document.querySelector('#ulKI') || document.querySelector('li[id^="li-"]')?.parentElement;
  const target = typeof expectedCount === 'number' ? expectedCount : null;
  const scale = typeof scrollDelayScale === 'number' ? scrollDelayScale : 1;   // 試験用：待ち時間の倍率
  const deadline = performance.now() + 90000 * scale;
  const timeout = () => new Error('一覧の読み込みが時間切れになりました。保存せずに再試行します。');
  const checkTime = () => { if (performance.now() >= deadline) throw timeout(); };
  const sleep = async ms => {
    checkTime();
    await new Promise(resolve => setTimeout(resolve, Math.min(ms * scale, deadline - performance.now())));
    checkTime();
  };
  const countCards = () => target === null ? (findList()?.children.length ?? -1)
    : document.querySelectorAll('li[id^="li-"]').length;
  const atBottom = () => window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 4;
  // サイトの続きの読み込み（jquery.inview）は、250ミリ秒ごとに「最後の台が画面内か」を調べ、スクロール位置は
  // scroll の通知が来たときだけ取り直す。窓を最小化・裏に回すと描画が止まり、scroll の通知が出ないため、
  // 位置が古いまま続きが出ず、途中で止まった（2026-10-28、利用者の報告）。動かすたびに通知を出す。
  const moved = () => window.dispatchEvent(new Event('scroll'));
  let last = -1, quiet = 0, nudges = 0, idleNudges = 0, armed = true;
  for (let tick = 0; tick < 360; tick++) {          // 追加待機も含め、実際の経過時間で最長90秒
    checkTime();
    const list = findList();
    if (!list) return;
    const count = countCards();
    if (count > last) {                              // 続きが届いた：描画が落ち着くのを待つ
      last = count; quiet = 0; armed = true; nudges = 0; idleNudges = 0;   // 新しい最後の台まで、もう一度下へ
      await sleep(400);
    } else if (atBottom()) quiet++;
    // 設置台数が分かっていれば届いたら終わり。不明（機種一覧）なら、一番下で4秒増えないことを、少し戻って
    // 着き直しながら3回確かめてから終わる（Android `waitForPscubeList` と同じ）。以前は3秒で終わり、
    // 20件ずつ届く機種一覧を途中で読み取ることがあった（2026-10-24〜26、Android）。
    if (target === null ? (quiet >= 16 && idleNudges >= 2) : (count >= target && quiet >= 1)) { await sleep(300); return; }
    if (atBottom()) {
      if (armed) {                                   // 着いたときに1回だけ：最後の台を見せて、一番下まで
        list.lastElementChild?.scrollIntoView({block:'end'});
        window.scrollTo(0, document.documentElement.scrollHeight);
        moved();
        armed = false;
      }
      else if (quiet >= 16) {                        // 4秒増えない：少し戻って、もう一度下へ
        if (++nudges > 5) return;
        idleNudges++;                                  // 最後に増えてから戻った回数（台数不明の終わりの判定）
        window.scrollBy(0, -Math.max(300, window.innerHeight * 1.5));
        moved();
        armed = true; quiet = 0;
        await sleep(400);
      }
    } else {
      window.scrollBy(0, Math.max(200, Math.round(window.innerHeight * 0.8)));
      moved();
      armed = true;
    }
    await sleep(250);
  }
  throw timeout();                                // 回数の安全上限でも、未完了の一覧を保存させない
})()'''


# 「サイトの記録を消してやり直す」：表示中のP’s CUBEのページに残る保存データを消す（Cookieは
# pywebview の clear_cookies で別に消す）。取り込んだ記録（pscube.sqlite3）には触れない。
RESET_SITE_SCRIPT = r'''(async () => {
  try { localStorage.clear(); } catch (_) {}
  try { sessionStorage.clear(); } catch (_) {}
  try { for (const db of (await indexedDB.databases?.()) || []) if (db.name) indexedDB.deleteDatabase(db.name); } catch (_) {}
  try { for (const key of await caches.keys()) await caches.delete(key); } catch (_) {}
  return true;
})()'''
BLOCKED_MESSAGE = ('サイトがデータを表示しなくなりました（止められた可能性）。自動取り込みを止めました。'
                   '時間を空けてから、Cookieを消さずに「もう一度開く」を試してください。')
RESET_DONE_MESSAGE = ('サイトのCookie・保存データを消しました（取り込んだ記録はそのまま）。最初のページを開き直します。'
                      '人間確認・同意が出たら手で操作してください。')


def reset_site(window, pilot, saving):
    """サイトの記録（Cookie・保存データ）を消して最初のページを開き直す。

    同じスマホのChromeでは開けるのにアプリだけデータが出ない＝回線ではなく、この窓に残る
    Cookie等で止められていると考えられたため（2026-10-02、利用者の報告）。自動取り込みはOFFにする。
    """
    if saving():
        raise ValueError('保存中です。保存が終わってから押してください。')
    pilot.configure(False, pilot.state()['seconds'])
    if not stop_navigation(window):
        pilot._eval('window.stop && window.stop()')
    pilot._eval(RESET_SITE_SCRIPT)
    window.clear_cookies()
    with pilot._lock:
        pilot.missing.clear()
        pilot.done.clear()
        pilot.failures.clear()
        pilot.auto.pause(RESET_DONE_MESSAGE)
    window.load_url(ROOT_URL)
    return RESET_DONE_MESSAGE


def business_day(now: datetime | None = None) -> str:
    """今の営業日（yyyy-mm-dd）。日本時間の午前3時までは前日として数える。"""
    now = now or datetime.now()
    return (now - timedelta(hours=BUSINESS_DAY_CUTOFF_HOUR)).date().isoformat()


def recent_business_days(now: datetime | None = None, count: int = 7) -> list[str]:
    """取り込み日として選べる営業日（新しい順）。サイトが見せるのは本日〜6日前の7日分。"""
    latest = date.fromisoformat(business_day(now))
    return [(latest - timedelta(days=i)).isoformat() for i in range(count)]


def _short_day(day: str) -> str:
    parsed = date.fromisoformat(day)
    return f'{parsed.month}/{parsed.day}'


def same_page(first, second) -> bool:
    """同じページか（Android `pscubeSamePage` と同じ規則）。一覧のページはサイトがスクロール位置を
    #以降へ書き込むので比べない。台別ページの#以降は履歴の日付なので完全に一致させる。
    WebView2 の get_current_url は日本語の機種名を元の文字に戻し、location.href は%の形で返すので、
    %を戻して比べる。"""
    if not isinstance(first, str) or not isinstance(second, str):
        return False

    def key(raw):
        parsed = urlparse(raw)
        if not parsed.path.endswith('nc-v06-001.php'):
            parsed = parsed._replace(fragment='')
        return unquote(parsed.geturl(), errors='surrogateescape')

    return key(first) == key(second)


def same_machine_url(first, second) -> bool:
    """同じ機種の全台一覧の住所か（#以降は比べない）。機種名の%は、保存した一覧のリンクでは二重
    （`%25E9…`）、WebViewの住所では一重や元の文字のことがあるので、戻しきってから比べる（2026-10-19）。"""
    def key(raw):
        parsed = urlparse(raw)
        def plain(value):
            for _ in range(4):
                decoded = unquote(value)
                if decoded == value:
                    break
                value = decoded
            return value
        query = sorted((k, tuple(plain(v) for v in values)) for k, values in parse_qs(parsed.query).items())
        return parsed.path, query
    return isinstance(first, str) and isinstance(second, str) and key(first) == key(second)


def day_tab_absent(day, days) -> bool:
    """全台一覧の日付タブ（days）に、取り込み日（day）のタブが無く、飛ばしてよい形か（Android `pscubeDayTabAbsent`
    と同じ規則）。タブが読めない・空のときや、取り込み日がタブより新しい（早朝でまだ出ていない）ときは False。
    自動取り込みの「日付違いでも読み取りへ進めるか」と、保存側の `_skip_absent_day` の両方で使う（2026-10-22）。"""
    return (isinstance(day, str) and isinstance(days, list) and bool(days) and
            all(isinstance(d, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', d) for d in days) and
            day not in days and day < max(days))


def table_url_for_day(url, day):
    """取り込み日を指定しているとき、機種の全台一覧をその日の日付タブで開くURL（Android
    `pscubeTableUrlForDay` と同じ）。サイトは全台一覧の状態（表示件数;位置;選んだ日付;…）を#以降に持ち、
    開いたときにその日付のタブを選ぶ（2026-10-06 実サイトで確認）。#以降が無いと「本日」のタブになり、
    営業中は数値が動き続けるため、その日を取り込めなかった。"""
    if not url or not day:
        return url
    parsed = urlparse(url)
    if not parsed.path.endswith('nc-v05-011.php'):
        return url
    return parsed._replace(fragment=f'0;0;{day.replace("-", "")};0;cd_dai;1;0;0').geturl()


def site_url(raw: str, suffix: str | None = None):
    if not isinstance(raw, str):
        raise ValueError('ページのURLがありません。')
    p = urlparse(raw)
    if p.scheme != 'https' or p.netloc != HOST or p.username or p.password:
        raise ValueError('対象外のサイトです。')
    if not p.path.startswith(f'/dedamajyoho-P-townDMMpachi/{SHOP}/'):
        raise ValueError('対象外の店舗です。')
    if suffix and not p.path.endswith(suffix):
        raise ValueError('ページの種類が一致しません。')
    return p


def compact_day(raw: str) -> str:
    if not re.fullmatch(r'\d{8}', raw or ''):
        raise ValueError('営業日がありません。')
    return datetime.strptime(raw, '%Y%m%d').date().isoformat()


def _key(*parts) -> str:
    return json.dumps(parts, ensure_ascii=False, separators=(',', ':'))


# 沖ドキ（表記は「沖ドキ」「オキドキ」、半角の「沖ﾄﾞｷ」も）は取り込みの対象外。メルヘンと同じ約束
# （利用者の指定、2026-09-29。P’s CUBEへの反映は2026-10-01）。回る対象にせず、表・グラフも保存しない。
EXCLUDED_MACHINE_WORDS = ('沖ドキ', 'オキドキ')


def is_excluded_machine(name) -> bool:
    text = unicodedata.normalize('NFKC', str(name or ''))
    return any(word in text for word in EXCLUDED_MACHINE_WORDS)


def no_hits(r: dict) -> bool:
    """当たりが1回もない台（BB・RB・AT/ARTがすべて0、0回転を含む）。全台一覧の数値は保存するが、
    台別7日分（グラフ）は取りに行かない（メルヘンv12の「大当たり0回はグラフを取らない」を、AT/ARTも
    含めて引き継ぐ。利用者の指定、2026-10-01）。一覧を取り直して当たりが付けば、また取る対象に戻る。"""
    return r['bb'] + r['rb'] + r['at_art'] == 0


def _machine_key(m: dict) -> str:
    return _key(m['store'], m['rate'], m['machine'])


def _record_key(r: dict) -> str:
    return _key(r['store'], r['rate'], r['machine'], r['rack'], r['day'])


def _number(value, name):
    if type(value) is not int or value < 0:
        raise ValueError(f'{name}の数値が不正です。')


def _validate_machine(m):
    if not isinstance(m, dict) or m.get('store') != SHOP or not re.fullmatch(r'\d+(?:\.\d+)?', str(m.get('rate', ''))):
        raise ValueError('店舗・貸玉を確認できません。')
    if not isinstance(m.get('machine'), str) or not m['machine'].strip():
        raise ValueError('機種名を確認できません。')
    if not (m.get('source_site') == 'anaslo' and m.get('url') is None):
        u = site_url(m.get('url'), 'nc-v05-011.php')
        if parse_qs(u.query).get('bai') != [m['rate']] or parse_qs(u.query).get('cd_ps') not in (None, ['2']):
            raise ValueError('機種リンクの貸玉が一致しません。')
    count = m.get('expected_count')
    if count is not None and (type(count) is not int or not 1 <= count <= 5000):
        raise ValueError('設置台数が不正です。')
    if m.get('machine_type') not in (None, 'normal', 'other'):
        raise ValueError('機種タイプが不正です。')


def _validate_record(r):
    if not isinstance(r, dict):
        raise ValueError('台の形式が不正です。')
    if r.get('store') != SHOP or not isinstance(r.get('rate'), str) or not re.fullmatch(r'\d+(?:\.\d+)?', r['rate']):
        raise ValueError('店舗・貸玉を確認できません。')
    if not isinstance(r.get('machine'), str) or not r['machine'].strip() or len(r['machine']) > 200:
        raise ValueError('機種名を確認できません。')
    _number(r.get('rack'), '台番号')
    if r['rack'] < 1:
        raise ValueError('台番号が不正です。')
    try:
        if datetime.strptime(r.get('day', ''), '%Y-%m-%d').date().isoformat() != r['day']:
            raise ValueError
    except (TypeError, ValueError) as e:
        raise ValueError('営業日が不正です。') from e
    external = r.get('source_site') == 'anaslo'
    if external:
        _validate_external_record(r)
    else:
        u = site_url(r.get('detail_url'), 'nc-v06-001.php')
        if parse_qs(u.query).get('cd_dai') != [str(r['rack'])] or u.fragment != r['day'].replace('-', ''):
            raise ValueError('台番号または日付とリンクが一致しません。')
    for name in ('bb', 'rb', 'at_art', 'games') if external else ('bb', 'rb', 'at_art', 'games', 'my'):
        _number(r.get(name), name)
    if r.get('net_medals') is not None and (type(r['net_medals']) is not int or abs(r['net_medals']) > 1000000):
        raise ValueError('差枚の数値が不正です。')
    if r.get('net_capture') is not None:
        r['net_capture'] = validate_net_capture(r['net_capture'], r)
    g = r.get('graph')
    if g is not None:
        if not isinstance(g, dict) or g.get('kind') not in ('overview', 'daily') or type(g.get('zero_y')) not in (int, float) or not math.isfinite(g['zero_y']):
            raise ValueError('グラフの形式が不正です。')
        points = g.get('points')
        if not isinstance(points, list) or not 2 <= len(points) <= 50000:
            raise ValueError('グラフの座標が不正です。')
        for i, point in enumerate(points):
            if not isinstance(point, list) or len(point) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 1e7 for v in point):
                raise ValueError('グラフの座標が不正です。')
            if i and point[0] < points[i - 1][0]:
                raise ValueError('グラフの順序が不正です。')
    if r.get('observed_at') is not None:
        try:
            datetime.fromisoformat(r['observed_at'])
        except (TypeError, ValueError) as exc:
            raise ValueError('更新時刻が不正です。') from exc


def _validate_external_record(r):
    url = urlparse(r.get('source_url') or '')
    if (url.scheme != 'https' or url.netloc != 'ana-slo.com' or
            not url.path.startswith('/' + r['day'] + '-') or
            not re.fullmatch(r'[0-9a-f]{64}', str(r.get('source_sha256', ''))) or
            not isinstance(r.get('source_machine'), str) or not r['source_machine'].strip() or
            any(k not in r or r[k] is not None for k in ('my', 'detail_url', 'observed_at', 'graph', 'net_medals'))):
        raise ValueError('アナスロ履歴の出典または欠損値が不正です。')


def _instant(text):
    """時差つきの時刻文字列を比べられる数（秒）に。読めなければ None。"""
    try:
        return datetime.fromisoformat(text).timestamp() if text else None
    except ValueError:
        return None


# 取り込みを開き直しただけで、少し前（今夜）に取った分まで取り直さないよう、3時間の余裕を持たせる（昼と夜のような差だけを取り直す。2026-10-05、開き直した後に手動の「次へ」が済んだ機種の表へ向かった不具合）。営業が終わった日は、その日の23時より後に取った分を最終とみなす。
STALE_MARGIN_HOURS = 3


def stale_cutoff(day, fresh_since):
    """[day] の記録がこれより古い「サイトの更新時刻」なら、取り直す（昼に取った数値を夜の分として残さない）。

    fresh_since：今回の取り込みで最初に保存したページのサイトの更新時刻（その日の最新に近い）。
    ただし、その日の営業が終わった後（翌日の午前2時以降）の数値はもう変わらないので、そこで頭打ちにする
    （終わった日の記録を、日をまたいで何度も取り直さない）。"""
    since = _instant(fresh_since)
    if since is None or not day:
        return None
    day_end = datetime.fromisoformat(f'{day}T00:00:00+09:00') + timedelta(days=1, hours=DAY_FINAL_HOUR)
    return min(since, day_end.timestamp()) - STALE_MARGIN_HOURS * 3600


def _merge(old: dict | None, fresh: dict) -> dict:
    if old is None:
        return fresh
    # External HTML is fill-only, including later restores of exported backups.
    # A real capture always replaces a source-only record regardless of game count.
    if fresh.get('source_site') == 'anaslo':
        return old
    if old.get('source_site') == 'anaslo':
        return fresh
    same = all(old[k] == fresh[k] for k in ('bb', 'rb', 'at_art', 'games', 'my'))
    old_time = old.get('observed_at') or ''
    fresh_time = fresh.get('observed_at') or ''
    # 表示文字列の大小は時差つき時刻の新旧と一致しない。Android・Webと同じく瞬間で比べる。
    older = (datetime.fromisoformat(fresh_time).timestamp() < datetime.fromisoformat(old_time).timestamp()
             if old_time and fresh_time else fresh['games'] < old['games'])
    if older and not same:
        return old
    chosen = old if older else fresh
    other = fresh if older else old
    if same:
        graph = chosen.get('graph')
        if not graph or graph['kind'] != 'daily':
            second = other.get('graph')
            graph = second if second and second['kind'] == 'daily' else graph or second
        capture = merge_net_capture(chosen, other, same)
        return {**chosen, 'graph': graph, **({'net_capture': capture} if capture else {}),
                **({'net_medals': other['net_medals']} if chosen.get('net_medals') is None and other.get('net_medals') is not None else {})}
    return chosen


def thin_graph(graph: dict | None, limit: int = VIEWER_GRAPH_POINTS) -> dict | None:
    """閲覧用に点を減らす。最初・最後・最高点・最低点（採点に使う終点・維持の元）は必ず残す。"""
    if not graph or len(graph['points']) <= limit:
        return graph
    points = graph['points']
    required = {0, len(points) - 1, min(range(len(points)), key=lambda i: points[i][1]),
                max(range(len(points)), key=lambda i: points[i][1])}
    others = [i for i in range(len(points)) if i not in required]
    slots = limit - len(required)
    spread = {others[round(k * (len(others) - 1) / (slots - 1))] for k in range(slots)}
    chosen = sorted(required | spread)
    return {**graph, 'points': [points[i] for i in chosen]}


def _now_text() -> str:
    return datetime.now().astimezone().isoformat(timespec='seconds')


def _load_settings(data_dir) -> dict:
    try:
        loaded = json.loads((Path(data_dir) / 'settings.json').read_text(encoding='utf-8'))
        return loaded if isinstance(loaded, dict) else {}
    except (OSError, ValueError):
        return {}


def sync_folder(data_dir) -> Path | None:
    """メルヘンと同じ同期フォルダ（settings.json の sync_dir）。未設定・存在しなければ None。"""
    folder = _load_settings(data_dir).get('sync_dir')
    return Path(folder) if folder and Path(folder).is_dir() else None


DATE_EVENT_MAX = 60
SUFFIX_EVENT_NAME = '末尾イベ'
_EVENT_TIME = re.compile(r'\d{4}-\d{2}-\d{2}T.+(?:Z|[+-]\d{2}:\d{2})')


def _event_key(e: dict) -> str:
    return _key(e['store'], e['rate'], e['day'])


def _event_instant(text: str) -> float:
    return datetime.fromisoformat(text.replace('Z', '+00:00')).timestamp()


def clean_event_name(name):
    """イベント名を整える（`web/pscube/data.mjs` の cleanEventName と同じ）。空は None（イベントなし）。"""
    if name is None:
        return None
    if not isinstance(name, str):
        raise ValueError('イベント名が不正です。')
    text = name.strip()
    if not text:
        return None
    if len(text) > DATE_EVENT_MAX or re.search(r'[\x00-\x1f\x7f]', text):
        raise ValueError(f'イベント名は1〜{DATE_EVENT_MAX}文字で入力してください。')
    return text


# 共有カレンダー（EVENT_CALENDAR.md、2026-10-08）：閲覧ページで入れたP’s CUBEのイベントを
# Apps Scriptが同期フォルダに書くファイル。PCは届いたものを取り込む。
SHARED_EVENTS_NAME = 'pscube-events-shared.json'


def merge_date_events(stored, incoming):
    """同じ店舗・貸玉・日付は、更新時刻が新しい方（同じなら後から来た方）を残す。"""
    events = {_event_key(e): e for e in stored}
    for e in incoming:
        previous = events.get(_event_key(e))
        if previous is None or _event_instant(e['updated_at']) >= _event_instant(previous['updated_at']):
            events[_event_key(e)] = e
    return list(events.values())


def validate_date_events(raw, legacy_suffix=None):
    """日付ごとのイベント名（自由記入、2026-10-06。`web/pscube/data.mjs` の validateDateEvents と同じ）。

    {store, rate, day, name, updated_at}。name が None は「イベントを消した」印。以前の末尾イベの印
    （suffix_events の enabled）は「末尾イベ」という名前（外した印は None）に読み替える。"""
    def read(items, convert, what):
        if items is None:
            return []
        if not isinstance(items, list) or len(items) > 100000:
            raise ValueError(f'{what}が不正です。')
        result = []
        for e in items:
            if not isinstance(e, dict) or not isinstance(e.get('store'), str) or not re.fullmatch(r'c\d+', e['store']) \
                    or not isinstance(e.get('rate'), str) or not re.fullmatch(r'\d+(?:\.\d+)?', e['rate']) \
                    or not isinstance(e.get('day'), str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', e['day']) \
                    or not isinstance(e.get('updated_at'), str) or not _EVENT_TIME.fullmatch(e['updated_at']):
                raise ValueError(f'{what}が不正です。')
            try:
                date.fromisoformat(e['day'])
                _event_instant(e['updated_at'])
            except ValueError:
                raise ValueError(f'{what}が不正です。') from None
            result.append({'store': e['store'], 'rate': e['rate'], 'day': e['day'], 'name': convert(e),
                           'updated_at': e['updated_at']})
        if len({_event_key(e) for e in result}) != len(result):
            raise ValueError(f'{what}が重複しています。')
        return result

    def legacy_name(e):
        if not isinstance(e.get('enabled'), bool):
            raise ValueError('末尾イベの印が不正です。')
        return SUFFIX_EVENT_NAME if e['enabled'] else None

    legacy = read(legacy_suffix, legacy_name, '末尾イベの印')
    named = read(raw, lambda e: clean_event_name(e.get('name')), 'イベント名')
    return merge_date_events(legacy, named)


def _write_json(path: Path, payload: dict) -> Path:
    with atomic_writer(path) as out:
        json.dump(payload, out, ensure_ascii=False, separators=(',', ':'))
    return path


def auto_backup(store: 'PscubeStore', export_path, today: date | None = None) -> str:
    """保存のあとに呼ぶ。書き出しに失敗しても取り込みは止めない（例外を出さない）。

    ローカルの `pscube-viewer.json`、日付ごとの控え（7日分）、同期フォルダの
    `pscube-backup-auto.json` と `pscube-viewer-drive.json` を作る。戻り値は画面に出す状態。
    """
    from backup_status import BackupStatus
    data_dir = Path(export_path).parent
    status = BackupStatus(data_dir, 'pscube', _load_settings(data_dir).get('sync_dir'))
    try:
        folder = sync_folder(data_dir)
        today = today or date.today()
        status.step = 'PC内のバックアップ'
        full = store.export_payload('backup')
        groups = {}
        for row in full['records']:
            key = (row['store'], row['rate'])
            entry = groups.setdefault(key, dict(name=f'P’s CUBE {key[0]}・{key[1]}', day=None, count=0))
            entry['day'] = max(entry['day'] or '', row['day'])
            entry['count'] += 1
        status.stores = list(groups.values())
        local = _write_json(Path(export_path), full)
        status.done('local')
        status.step = '日別バックアップ'
        snapshots = (folder or data_dir) / 'backups'
        snapshot = snapshots / f'pscube-backup-{today.isoformat()}.json'
        snapshots.mkdir(parents=True, exist_ok=True)
        atomic_copy(local, snapshot)
        status.done('snapshot')
        for old in snapshots.glob(SNAPSHOT_PATTERN):
            try:
                stamp = date.fromisoformat(old.stem[len('pscube-backup-'):])
            except ValueError:
                continue
            if (today - stamp).days > SNAPSHOT_KEEP_DAYS:
                old.unlink(missing_ok=True)
        if folder is None:
            status.finish('unavailable', '同期フォルダ未設定' if not status.folder else
                          '同期フォルダが見つかりません。ドライブ・接続を確認してください。')
            return '同期フォルダ未設定（本体の「バックアップ・同期」で指定）'
        status.step = '全期間バックアップの共有フォルダへの書き出し'
        atomic_copy(local, folder / AUTO_BACKUP_NAME)
        status.done('backup')
        status.step = '閲覧用ファイルの共有フォルダへの書き出し'
        light = _write_json(data_dir / VIEWER_DRIVE_NAME, store.export_payload('viewer'))
        atomic_copy(light, folder / VIEWER_DRIVE_NAME)
        status.done('viewer')
        status.finish('success')
        return 'バックアップ済み'
    except (OSError, ValueError, sqlite3.Error) as error:
        status.finish('failed', f'{status.step}：{error}')
        return 'バックアップに失敗（取り込みは保存済み）'


def is_pscube_backup(path) -> bool:
    """P’s CUBEのバックアップ（format が pscube-viewer）か。先頭だけ読む（メルヘンの全期間は大きいため）。"""
    try:
        if Path(path).name == 'database-viewer-parts-pscube.json':
            if Path(path).stat().st_size > 1024 * 1024:
                return False
            data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
            return data.get('format') == 'database-viewer-parts' and data.get('site') == 'pscube' and data.get('version') == 2
        with open(path, 'rb') as f:
            head = f.read(512).decode('utf-8', errors='ignore')
    except (OSError, ValueError, AttributeError):
        return False
    return re.search(r'"format"\s*:\s*"pscube-viewer"', head) is not None


def backup_file_name(now: datetime | None = None, source: str = 'pc') -> str:
    """手で書き出すバックアップの名前（例 pscube-backup-pc-20261002-001500.json）。メルヘンと重ならない。"""
    return f'pscube-backup-{source}-{(now or datetime.now()):%Y%m%d-%H%M%S}.json'


def write_backup(store: 'PscubeStore', path) -> Path:
    """全期間のバックアップ（復元に使える形）を [path] に書く。"""
    return _write_json(Path(path), store.export_payload('backup'))


# Androidが同期フォルダに置くP’s CUBEのファイル：全期間（手で保存）と、自動取り込みを終えたときの当日分
# （Apps Script経由、2026-10-26 PSCUBE_SYNC.md「当日分の自動送信」）。PC版は起動中にこれだけを自動で読む。
ANDROID_SYNC_NAME = re.compile(r'pscube-(?:backup-android-\d{8}-\d{6}|day-android-\d{4}-\d{2}-\d{2})\.json')


def android_sync_files(folder) -> list[tuple[str, float, Path]]:
    """同期フォルダのAndroidのP’s CUBEファイルを（名前, 更新時刻, パス）で、更新の古い順に返す。"""
    found = []
    for path in Path(folder).glob('pscube-*.json'):
        if not ANDROID_SYNC_NAME.fullmatch(path.name):
            continue
        try:
            found.append((path.name, path.stat().st_mtime, path))
        except OSError:
            continue  # Driveが書き換え中など。次の確認で読む
    return sorted(found, key=lambda item: (item[1], item[0]))


class InvalidAndroidSyncFile(ValueError):
    """Android同期ファイルの読取・事前検証で見つかった内容の不正。"""


ANDROID_SYNC_SETTLE_SECONDS = 10  # Driveが書き終えたばかりのファイルは、次の確認まで待つ


def android_sync_due(files, seen, now):
    """``android_sync_files`` のうち、読み込むもの（古い順）。

    ``seen`` は前に読み込んだ {名前: 更新時刻}。None（この機能を初めて使う）なら、今あるファイルは
    読み込み済みとして扱い、何も読まない（PC版で既に読んだ古いバックアップを読み直さない）。
    戻り値は（読むファイルの一覧, 次に覚える seen の初期値 または None）。
    """
    if seen is None:
        initial = {name:mtime for name,mtime,_path in files if not name.startswith('pscube-day-android-')}
        due = [(name,mtime,path) for name,mtime,path in files if name.startswith('pscube-day-android-') and now-mtime>=ANDROID_SYNC_SETTLE_SECONDS]
        return due, initial
    return [(name, mtime, path) for name, mtime, path in files
            if seen.get(name) != mtime and now - mtime >= ANDROID_SYNC_SETTLE_SECONDS], None


def latest_pscube_backup(folder) -> Path | None:
    """同期フォルダの最新のP’s CUBEバックアップ。自分の自動コピーと閲覧用の軽いファイルは除く。"""
    candidates = [p for p in Path(folder).glob('pscube-*.json') if p.name not in (AUTO_BACKUP_NAME, VIEWER_DRIVE_NAME)]
    history = Path(folder) / 'database-viewer-parts-pscube.json'
    if history.exists():
        candidates.append(history)
    for path in sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            payload = json.loads(path.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            continue
        if isinstance(payload, dict) and ((payload.get('format') == FORMAT and payload.get('kind') != 'viewer') or
                (payload.get('format') == 'database-viewer-parts' and payload.get('version') == 2 and payload.get('site') == 'pscube')):
            return path
    return None


def installation_count(db_path, current_url):
    """表示中の全台一覧の設置台数を読み取り専用で取得。別機種・貸玉の台数は使わない。"""
    current = site_url(current_url)
    if not current.path.endswith('nc-v05-011.php') or not Path(db_path).is_file():
        return None
    identity = (current.path, parse_qs(current.query))
    with closing(sqlite3.connect(Path(db_path).resolve().as_uri() + '?mode=ro', uri=True)) as db:
        try:
            machines = db.execute('SELECT payload FROM machines').fetchall()
        except sqlite3.OperationalError as error:
            if 'no such table' in str(error):
                return None
            raise
        counts = set()
        for row in machines:
            machine = json.loads(row[0])
            # アナスロだけにある補完機種はP’s CUBEの機種URLを持たない。
            # 表示中の機種の台数確認へ混ぜず、補完記録はそのまま保持する。
            if machine.get('source_site') == 'anaslo' and machine.get('url') is None:
                continue
            stored = site_url(machine['url'])
            if (stored.path, parse_qs(stored.query)) == identity:
                count = machine.get('expected_count')
                if type(count) is int and 1 <= count <= 5000:
                    counts.add(count)
        return counts.pop() if len(counts) == 1 else None


class PscubeIndexRetry(ValueError):
    def __init__(self, keys):
        super().__init__('機種一覧が減ったため、開き直してもう一度確認します。')
        self.keys = keys


class PscubeStore:
    def __init__(self, path, *, recording=True, index_confirmation=None):
        self.index_confirmation = index_confirmation
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = input_versions.connect(self.path, recording=recording)
        self.db.execute('CREATE TABLE IF NOT EXISTS machines (key TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS records (key TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS rack_captures (key TEXT PRIMARY KEY)')
        self.db.execute('CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        self.db.commit()
        # 翌日候補の店舗別案を並べて比べるための版の記録（input_versions.py）。失敗しても開ける。
        if not input_versions.attach(self.db, self.path.parent, 'pscube'):
            try:
                with self.db:
                    failures = self._state('input_versions_failures')
                    self.db.execute('INSERT OR REPLACE INTO state VALUES (?,?)',
                                    ('input_versions_failures', str(int(failures) + 1 if failures else 1)))
                    self.db.execute('INSERT OR REPLACE INTO state VALUES (?,?)',
                                    ('input_versions_last_error', input_versions.state().get('pscube', '')))
            except sqlite3.Error:
                pass

    def close(self):
        self.db.close()

    def _read(self, table, key):
        row = self.db.execute(f'SELECT payload FROM {table} WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def _state(self, key):
        row = self.db.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()
        return row[0] if row else None

    def _check_index_complete(self, machines):
        """減った一覧は、開き直した後も同じ集合なら受け付ける。"""
        stored = self._state('active_machine_keys')
        if stored is None:
            return
        previous = set(json.loads(stored))
        shown = {_machine_key(m) for m in machines}
        if len(shown) < len(previous) and shown != self.index_confirmation:
            raise PscubeIndexRetry(shown)

    def import_page(self, raw, current_url, expected_day=None, direction='top', manual=False, fresh_since=None):
        """expected_day：取り込み日を指定しているときの日付。表示中の日付と違うページは保存しない。
        direction：'top'＝機種の一覧の上から、'bottom'＝下から次の機種を選ぶ。
        manual：手動の取り込み。次のページは、一覧の最初から探し直さず、いま保存したページの次から探す。
        fresh_since：{日付: 今回の取り込みで最初に保存したページのサイトの更新時刻}。これより古い数値の機種は
        全台一覧から取り直す（数値が変わった台だけ台別ページも取り直す）。結果の 'fresh_since' に、この
        ページで分かった分を足して返す（呼び出し側が覚えて、次の保存で渡す）。"""
        fresh_since = dict(fresh_since or {})
        if direction not in DIRECTIONS:
            raise ValueError('取り込みの向きが不正です。')
        data = json.loads(raw) if isinstance(raw, str) else raw
        skipped = self._skip_absent_day(data, current_url, expected_day, direction, manual, fresh_since)
        if skipped:
            return skipped
        if not isinstance(data, dict) or data.get('error'):
            raise ValueError(data.get('error', 'ページを読めませんでした。') if isinstance(data, dict) else 'ページの形式が不正です。')
        if data.get('format') != FORMAT or data.get('version') != 1 or not isinstance(data.get('machines'), list) or not isinstance(data.get('records'), list):
            raise ValueError('P’s CUBEの取り込み形式ではありません。')
        actual = site_url(current_url)
        site_url(data.get('source_url'))
        if not same_page(current_url, data.get('source_url')):
            raise ValueError('表示中のページと読み取り結果が違います。')
        if len(data['machines']) > 10000 or len(data['records']) > 5000:
            raise ValueError('ページの件数が多すぎます。')
        for m in data['machines']:
            _validate_machine(m)
        for r in data['records']:
            _validate_record(r)
        if len({_machine_key(m) for m in data['machines']}) != len(data['machines']) or len({_record_key(r) for r in data['records']}) != len(data['records']):
            raise ValueError('同じ機種・台が重複しています。')
        is_index = actual.path.endswith('nc-v03-001.php')
        is_table = actual.path.endswith('nc-v05-011.php')
        is_rack = actual.path.endswith('nc-v06-001.php')
        if not (is_index or is_table or is_rack):
            raise ValueError('機種一覧・台一覧・台別ページを開いてください。')
        if is_index and (data['records'] or not data['machines'] or parse_qs(actual.query).get('cd_ps') != ['2']):
            raise ValueError('スロット機種一覧を確認できません。')
        if is_index:
            data['machines'] = [m for m in data['machines'] if not is_excluded_machine(m['machine'])]
            if not manual:
                self._check_index_complete(data['machines'])
        elif data['machines'] and is_excluded_machine(data['machines'][0]['machine']):
            raise ValueError(f'{data["machines"][0]["machine"]}は取り込みの対象外です（沖ドキ）。保存しませんでした。')
        if is_table:
            if parse_qs(actual.query).get('cd_ps') not in (None, ['2']) or len(data['machines']) != 1 or not data['records']:
                raise ValueError('全台一覧を確認できません。')
            old = self._read('machines', _machine_key(data['machines'][0]))
            if not old or not old.get('expected_count'):
                raise ValueError('先に設置機種一覧を取り込んでください。')
            missing_racks = self._missing_racks_of(data)
            shown = len(data['records']) + len(missing_racks)
            if shown != old['expected_count']:
                raise ValueError(f'表示は{shown}台、設置台数は{old["expected_count"]}台です。全台を表示してから取り込んでください。')
            if any(_machine_key(r) != _machine_key(old) for r in data['records']):
                raise ValueError('機種と台の情報が一致しません。')
        if is_rack and (len(data['machines']) != 1 or not 1 <= len(data['records']) <= 7):
            raise ValueError('7日分の台別データが揃っていません。')
        day = data['records'][0]['day'] if data['records'] else self._state('last_day')
        if is_rack:
            day = compact_day(actual.fragment)
            current = next((r for r in data['records'] if r['day'] == day), None)
            if not current or self._read('records', _record_key(current)) is None:
                raise ValueError('先にこの台の全台一覧を取り込んでください。')
            if any(r['rack'] != current['rack'] or _machine_key(r) != _machine_key(current) for r in data['records']):
                raise ValueError('台別7日分の内容が一致しません。')
            if parse_qs(actual.query).get('cd_dai') != [str(current['rack'])] or _machine_key(data['machines'][0]) != _machine_key(current):
                raise ValueError('表示中の台番号・機種と一致しません。')
            # 台別ページの7列はサイトの「本日」（history_latest_day）から並び、選んだ日より新しい列は
            # 読み取りで除いてある（2026-10-06）。その日が無い古い読み取り結果は、選んだ日を1列目とみなす。
            selected = datetime.fromisoformat(day).date()
            latest_text = data.get('history_latest_day', day)
            if not isinstance(latest_text, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', latest_text):
                raise ValueError('台別7日分の日付を確認できません。')
            latest = date.fromisoformat(latest_text)
            if not 0 <= (latest - selected).days <= 6:
                raise ValueError('台別7日分の日付を確認できません。')
            expected = {(latest - timedelta(days=i)).isoformat() for i in range(7)
                        if latest - timedelta(days=i) <= selected}
            # 新台の全空欄の過去列は、共通JSが明示して返す。省略を0件の記録にしない。
            missing = data.get('missing_history_days', [])
            present = {r['day'] for r in data['records']}
            if (not isinstance(missing, list) or len(missing) > 6 or
                    any(not isinstance(d, str) for d in missing) or
                    len(set(missing)) != len(missing) or day in missing or
                    present.intersection(missing) or present.union(missing) != expected):
                raise ValueError('連続した7日分の履歴ではありません。')
        if is_table and any(r['day'] != day for r in data['records']):
            raise ValueError('一覧内の日付が一致しません。')
        if expected_day and (is_table or is_rack) and day != expected_day:
            where = '全台一覧の日付タブを' if is_table else 'このページを'
            raise ValueError(f'取り込み日は{expected_day}ですが、表示中は{day}です。{where}{expected_day}に合わせてください。保存しませんでした。')
        with self.db:
            for m in data['machines']:
                key = _machine_key(m)
                previous = self._read('machines', key)
                saved = {**m, 'expected_count': m.get('expected_count') or (previous or {}).get('expected_count'),
                         'machine_type': m.get('machine_type') or (previous or {}).get('machine_type')}
                self.db.execute('INSERT OR REPLACE INTO machines VALUES (?,?)', (key, json.dumps(saved, ensure_ascii=False)))
            for r in data['records']:
                key = _record_key(r)
                previous = self._read('records', key)
                saved = _merge(previous, r)
                if previous and any(previous[k] != saved[k] for k in ('bb', 'rb', 'at_art', 'games', 'my')):
                    self.db.execute('DELETE FROM rack_captures WHERE key=?', (key,))
                self.db.execute('INSERT OR REPLACE INTO records VALUES (?,?)', (key, json.dumps(saved, ensure_ascii=False)))
            if day:
                self.db.execute('INSERT OR REPLACE INTO state VALUES (?,?)', ('last_day', day))
            if is_table:
                # その日に無かった台（増台した台）を覚える。全部そろった一覧を取り直したら消す。
                absent = {k: v for k, v in self._absent_racks().items() if k != (_machine_key(old), day)}
                if missing_racks:
                    absent[(_machine_key(old), day)] = missing_racks
                self.db.execute('INSERT OR REPLACE INTO state VALUES (?,?)',
                                (ABSENT_RACKS_KEY, json.dumps([[k, d, r] for (k, d), r in sorted(absent.items())], ensure_ascii=False)))
                # この機種・日の全台一覧を保存できた＝その日のタブはある。「タブなし」の印を外し、未取得に戻す
                # （以前は外さず、あとで取れても機種ごと除外され続けた。2026-10-22）。ほかの機種・日の印は残す。
                absent_days = self._absent_days()
                if (_machine_key(old), day) in absent_days:
                    self.db.execute('INSERT OR REPLACE INTO state VALUES (?,?)',
                                    (ABSENT_DAYS_KEY, json.dumps(sorted(absent_days - {(_machine_key(old), day)}), ensure_ascii=False)))
            if is_index:
                self.db.execute('INSERT OR REPLACE INTO state VALUES (?,?)',
                                ('active_machine_keys', json.dumps([_machine_key(m) for m in data['machines']], ensure_ascii=False)))
            if is_rack:
                self.db.execute('INSERT OR IGNORE INTO rack_captures VALUES (?)', (_record_key(current),))
        if any(r.get('net_capture') for r in data['records']):
            self._trim_net_probes()
        if (is_table or is_rack) and day and day not in fresh_since:
            times = [r.get('observed_at') for r in data['records'] if r['day'] == day and _instant(r.get('observed_at'))]
            if times:
                fresh_since[day] = max(times, key=_instant)
        # 機種一覧からは、決めた向きの最初の機種を開く。取り込み日を指定していても、その日の基準の時刻が
        # まだ無い（今回まだ1ページも保存していない）ときは同じ：開いた機種の全台一覧で基準が分かる。
        if is_index and (not expected_day or expected_day not in fresh_since):
            first = data['machines'][-1] if direction == 'bottom' else data['machines'][0]
            next_url, remaining = first['url'], len(data['machines'])
        else:
            # 取り込み日を指定しているときは、一覧から最初の機種ではなく、その日の未取得の先頭へ進む。
            after = None
            if manual and is_table:
                after = (_machine_key(data['machines'][0]), None)
            elif manual and is_rack:
                after = (_machine_key(current), current['rack'])
            target_day = expected_day or day
            next_url, remaining = self.next_target(target_day, direction, after, fresh_since.get(target_day))
        next_url = table_url_for_day(next_url, expected_day)
        result = {'saved': len(data['records']), 'day': day, 'next_url': next_url, 'remaining': remaining,
                  'kind': '機種一覧' if is_index else
                  (f'全台一覧（{"・".join(map(str, missing_racks))}番台はこの日の数値なし）' if missing_racks else '全台一覧') if is_table else
                  f'台別履歴（{len(data["records"])}日分）' if len(data['records']) < 7 else '台別7日分',
                  'fresh_since': fresh_since}
        if is_rack and isinstance(data.get('net_warning'), str):
            # 差枚の元データだけ取れなかった（数値・グラフは保存済み、差枚は空欄のまま）。
            result['net_warning'] = data['net_warning'][:200]
        return result

    def _absent_racks(self):
        """その日に無かった台（{(機種のキー, 日付): [台番号]}）。増台した台は、過去の日の全台一覧に数値もリンクも無く並ぶ。"""
        try:
            return {(k, d): list(r) for k, d, r in json.loads(self._state(ABSENT_RACKS_KEY) or '[]')}
        except (TypeError, ValueError):
            return {}

    def _missing_racks_of(self, data):
        """全台一覧の「その日に数値もリンクも無い台」（共通JSの missing_racks）を確かめて返す。今動いている日（日付タブの
        最新）や、ほかの台がすべて空のページ（読み込み途中かもしれない）では受け付けない（2026-10-19）。"""
        missing = data.get('missing_racks', [])
        if not missing:
            return []
        racks = {r['rack'] for r in data['records']}
        days = data.get('available_days')
        day = data['records'][0]['day'] if data['records'] else None
        if (not isinstance(missing, list) or any(type(r) is not int or r < 1 for r in missing) or
                len(set(missing)) != len(missing) or racks.intersection(missing)):
            raise ValueError('数値の無い台の情報が不正です。')
        if (not isinstance(days, list) or not days or any(not isinstance(d, str) for d in days) or
                not day or day >= max(days)):
            raise ValueError(f'{"・".join(map(str, sorted(missing)))}番台に数値と台別ページへのリンクがありません。'
                             '数値が表示されてから保存してください。')
        return sorted(missing)

    def _absent_days(self):
        """取り込み日の日付タブがサイトに無かった機種と日（{(機種のキー, 日付)}）。"""
        try:
            return {tuple(e) for e in json.loads(self._state(ABSENT_DAYS_KEY) or '[]')}
        except (TypeError, ValueError):
            return set()

    def _skip_absent_day(self, data, current_url, expected_day, direction, manual, fresh_since):
        """取り込み日を指定して開いた全台一覧に、その日の日付タブが無ければ、その機種のその日を「サイトに記録なし」
        として覚え、保存せずに次へ進む。入れ替えで入った新台はその日からのタブしか無く、前日を指定するとサイトは
        最新のタブを選ぶ。以前は未取得の先頭に残り続け、取り込みが先へ進まなかった（2026-10-19）。

        飛ばすのは、指定日がタブの範囲より前か、範囲の中で抜けている日だけ。タブより新しい日（その日のタブが
        まだ出ていない早朝など）は飛ばさない。取り込める数値はもともと無いので、飛ばしても記録は減らない。"""
        if not expected_day or not isinstance(data, dict):
            return None
        days = data.get('available_days')
        try:
            actual = site_url(current_url)
        except ValueError:
            return None
        if not actual.path.endswith('nc-v05-011.php') or not day_tab_absent(expected_day, days):
            return None
        if not same_page(current_url, data.get('source_url')):
            raise ValueError('表示中のページと読み取り結果が違います。')
        machine = next((m for m in (json.loads(row[0]) for row in self.db.execute('SELECT payload FROM machines'))
                        if m.get('url') and same_machine_url(m['url'], current_url)), None)
        shown = '・'.join(f'{int(d[5:7])}/{int(d[8:])}' for d in sorted(days))
        if machine is None:
            raise ValueError(f'取り込み日{expected_day}の日付タブがこの機種にありません（タブ：{shown}）。'
                             '先に設置機種一覧を取り込んでください。保存しませんでした。')
        key = _machine_key(machine)
        absent = self._absent_days() | {(key, expected_day)}
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO state VALUES (?,?)',
                            (ABSENT_DAYS_KEY, json.dumps(sorted(absent), ensure_ascii=False)))
        fresh_since = dict(fresh_since or {})
        next_url, remaining = self.next_target(expected_day, direction, (key, None) if manual else None,
                                               fresh_since.get(expected_day))
        return {'saved': 0, 'day': expected_day, 'next_url': table_url_for_day(next_url, expected_day),
                'remaining': remaining, 'kind': '全台一覧', 'fresh_since': fresh_since,
                'skipped': f'{machine["machine"]}は{int(expected_day[5:7])}/{int(expected_day[8:])}の日付タブがサイトに'
                           f'ありません（タブ：{shown}。新台・入れ替えの可能性）。保存せずに飛ばしました'}

    def next_target(self, day=None, direction='top', after=None, fresh_since=None):
        """次に開くページ。direction='bottom' なら機種を一覧の下から数える。

        fresh_since：今回の取り込みの基準の時刻（`stale_cutoff`）。全台一覧が揃っていても、数値がそれより古い
        機種は、全台一覧から取り直す（以前は、昼に一度取った機種を夜も「済み」として飛ばしていた。2026-10-04）。

        after：手動の取り込みで、いま保存したページ（機種のキー、台番号。全台一覧ならNone）。
        一覧の最初から探し直さず、そのページの次（機種の並びの順、機種の中は台番号の小さい順）から探し、
        最後まで行って残りが無いときだけ最初へ回る。"""
        day = day or self._state('last_day')
        machines = [json.loads(row[0]) for row in self.db.execute('SELECT payload FROM machines ORDER BY rowid')]
        active = self._state('active_machine_keys')
        if active:
            by_key = {_machine_key(m): m for m in machines}
            machines = [by_key[key] for key in json.loads(active) if key in by_key]
        machines = [m for m in machines if m.get('url') and not is_excluded_machine(m['machine'])]
        if direction == 'bottom':
            machines.reverse()
        if not machines:
            return ROOT_URL + 'cgi-bin/nc-v03-001.php?cd_ps=2', 0
        if not day:
            return machines[0]['url'], len(machines)
        pending = []   # (機種の並び順, 台番号（全台一覧は-1）, URL)
        all_rows = [json.loads(row[0]) for row in self.db.execute('SELECT payload FROM records')]
        captured = {row[0] for row in self.db.execute('SELECT key FROM rack_captures')}
        cutoff = stale_cutoff(day, fresh_since)
        absent = self._absent_days()
        absent_racks = self._absent_racks()
        for index, machine in enumerate(machines):
            # その日の日付タブがサイトに無かった機種（新台・入れ替え）は、その日の未取得に数えない。
            if (_machine_key(machine), day) in absent:
                continue
            rows = sorted((r for r in all_rows if _machine_key(r) == _machine_key(machine) and r['day'] == day), key=lambda r: r['rack'])
            # 一番古い数値で判断する（台別ページは1台ずつしか新しくならない）。更新時刻が分からない台は判断に使わない
            # （分からないまま「古い」とすると、同じ全台一覧を取り直し続けてしまう）。
            oldest = min((_instant(r.get('observed_at')) for r in rows if _instant(r.get('observed_at'))), default=None)
            missing = [r for r in absent_racks.get((_machine_key(machine), day), []) if r not in {row['rack'] for row in rows}]
            if len(rows) + len(missing) != machine.get('expected_count') or (cutoff is not None and oldest is not None and oldest < cutoff):
                pending.append((index, -1, machine['url']))
            else:
                pending += [(index, r['rack'], r['detail_url']) for r in rows if r.get('detail_url') and _record_key(r) not in captured and not no_hits(r)]
        if after is not None and pending:
            keys = [_machine_key(m) for m in machines]
            if after[0] in keys:
                # 全台一覧を保存した機種は、その機種の台から（-2は全台一覧より前）。台別ページなら、その台の次から。
                here = (keys.index(after[0]), -2 if after[1] is None else after[1])
                pending = [e for e in pending if e[:2] > here] + [e for e in pending if e[:2] <= here]
        urls = [e[2] for e in pending]
        return (urls[0] if urls else None), len(urls)

    def _trim_net_probes(self):
        rows = self.db.execute('SELECT key,payload FROM records WHERE payload LIKE ?', ('%"probe":%',)).fetchall()
        records = [json.loads(row[1]) for row in rows]
        before = [json.dumps(r.get('net_capture'), sort_keys=True) for r in records]
        trim_net_probes(records)
        with self.db:
            for (key, _), record, old in zip(rows, records, before):
                if json.dumps(record.get('net_capture'), sort_keys=True) != old:
                    self.db.execute('UPDATE records SET payload=? WHERE key=?', (json.dumps(record, ensure_ascii=False), key))

    def export_payload(self, kind='backup', today: date | None = None) -> dict:
        """kind='backup'：全期間・グラフ全点・取り込み済みの印つき。'viewer'：閲覧ページ用の軽い版
        （直近31日・グラフ16点まで。復元には使えない）。"""
        machines = [json.loads(row[0]) for row in self.db.execute('SELECT payload FROM machines ORDER BY rowid')]
        records = [json.loads(row[0]) for row in self.db.execute('SELECT payload FROM records ORDER BY rowid')]
        trim_net_probes(records)
        data = {'format': FORMAT, 'version': 1, 'kind': kind, 'source': 'pc', 'exported_at': _now_text(),
                'machines': machines, 'records': records}
        if kind == 'viewer':
            latest = max((r['day'] for r in records), default=None)
            if latest:
                first = (date.fromisoformat(latest) - timedelta(days=VIEWER_DAYS - 1)).isoformat()
                data['records'] = [{**r, 'graph': thin_graph(r.get('graph')),
                                    **({'net_capture': viewer_net_capture(r['net_capture'])} if r.get('net_capture') else {})}
                                   for r in records if r['day'] >= first]
        else:
            data['rack_captures'] = [row[0] for row in self.db.execute('SELECT key FROM rack_captures ORDER BY rowid')]
        events = self.date_events()
        if events:
            data['date_events'] = events
        return data

    def date_events(self) -> list[dict]:
        """日付ごとのイベント名（消した印を含む）。state の date_events に JSON で持つ。"""
        text = self._state('date_events')
        return validate_date_events(json.loads(text)) if text else []

    def set_date_event(self, day: str, name, now: datetime | None = None) -> list[dict]:
        """[day] のイベント名を付ける・変える・消す（None・空はイベントなし）。店舗の全貸玉に付ける
        （閲覧ページは店舗・貸玉ごとに持つので、記録のある貸玉それぞれに同じ名前を入れる）。"""
        return self.set_date_event_days([day], name, now)

    def set_date_event_days(self, days, name, now: datetime | None = None) -> list[dict]:
        """[days] に同じイベント名を付ける（イベントカレンダー、EVENT_CALENDAR.md）。記録の無い先の日にも
        付けられる。名前が変わらない日は前の時刻のまま（前日までに入力した印を消さない）、何も無い日を
        「イベントなし」にしても消した印は作らない。"""
        for day in days:
            date.fromisoformat(day)
        cleaned = clean_event_name(name)
        scopes = sorted({(m['store'], m['rate']) for m in (json.loads(row[0])
                         for row in self.db.execute('SELECT payload FROM machines'))})
        if not scopes:
            raise ValueError('先にP’s CUBEの記録を取り込んでください。')
        events = {_event_key(e): e for e in self.date_events()}
        now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        changed = False
        for day in days:
            for store, rate in scopes:
                key = _key(store, rate, day)
                previous = events.get(key)
                if (previous['name'] if previous else None) == cleaned:
                    continue
                at = now
                if previous is not None:
                    at = max(at, datetime.fromtimestamp(_event_instant(previous['updated_at']), timezone.utc)
                             + timedelta(milliseconds=1))
                events[key] = {'store': store, 'rate': rate, 'day': day, 'name': cleaned,
                               'updated_at': at.isoformat(timespec='milliseconds').replace('+00:00', 'Z')}
                changed = True
        saved = validate_date_events(list(events.values()))
        if changed:
            with self.db:
                self.db.execute('INSERT OR REPLACE INTO state VALUES (?,?)',
                                ('date_events', json.dumps(saved, ensure_ascii=False)))
        return saved

    def pull_shared_events(self, folder) -> int:
        """同期フォルダの共有ファイル（[SHARED_EVENTS_NAME]）のイベントを取り込む（新しい方が残る）。
        読めない・形式が違うファイルは何もしない。変わった件数を返す。"""
        path = Path(folder) / SHARED_EVENTS_NAME if folder else None
        if path is None or not path.is_file():
            return 0
        try:
            incoming = validate_date_events(json.loads(path.read_text(encoding='utf-8-sig')).get('events'))
        except (OSError, ValueError, AttributeError):
            return 0
        stored = self.date_events()
        before = {_event_key(e): e for e in stored}
        merged = validate_date_events(merge_date_events(stored, incoming))
        changed = sum(1 for e in merged if before.get(_event_key(e)) != e)
        if changed:
            with self.db:
                self.db.execute('INSERT OR REPLACE INTO state VALUES (?,?)',
                                ('date_events', json.dumps(merged, ensure_ascii=False)))
        return changed

    def date_event_entries(self) -> dict[str, dict]:
        """日付ごとの今のイベント（名前のあるもの）。貸玉ごとに入っているので、いちばん新しい入力を代表にする。
        カレンダーの表示と「前日までに入力」の印に使う。"""
        entries = {}
        for e in self.date_events():
            if e['name'] and (e['day'] not in entries or
                              _event_instant(e['updated_at']) > _event_instant(entries[e['day']]['updated_at'])):
                entries[e['day']] = e
        return entries

    def date_event_for(self, day: str) -> str | None:
        """[day] のイベント名（どれかの貸玉に付いていれば、その名前）。"""
        names = [e['name'] for e in self.date_events() if e['day'] == day and e['name']]
        return names[0] if names else None

    def date_event_names(self) -> list[str]:
        """今までに付けたイベント名（新しく使った順、重複なし）。入力欄の候補。"""
        latest = {}
        for e in self.date_events():
            if e['name']:
                latest[e['name']] = max(latest.get(e['name'], 0), _event_instant(e['updated_at']))
        return [name for name, _ in sorted(latest.items(), key=lambda item: (-item[1], item[0]))]

    def days(self) -> list[str]:
        """記録がある営業日（新しい順）。PC本体の「結果を見る」の日付の選択肢。"""
        return sorted({json.loads(row[0])['day'] for row in self.db.execute('SELECT payload FROM records')}, reverse=True)

    def machines_for(self, day: str) -> list[str]:
        """[day] に記録がある機種（沖ドキは除く）。PC本体の「結果を見る」の機種の選択肢。"""
        names = set()
        for row in self.db.execute('SELECT payload FROM records'):
            record = json.loads(row[0])
            if record['day'] == day and not is_excluded_machine(record['machine']):
                names.add(record['machine'])
        return sorted(names)

    def export_viewer(self, path):
        return _write_json(Path(path), self.export_payload('backup'))

    def import_backup(self, source, *, _validate_only=False, _transaction=True) -> dict:
        """他の端末のバックアップ（PC・Android・ブラウザ）を統合する。消す操作はない。

        台ごとの統合は取り込みと同じ `_merge`（古い数値で新しい数値を上書きしない）。軽い閲覧用
        ファイル（kind='viewer'）は止める。形式が不正なら1件も保存しない。
        """
        data = json.loads(Path(source).read_text(encoding='utf-8-sig')) if isinstance(source, (str, Path)) else source
        if isinstance(data, dict) and data.get('format') == 'database-viewer-parts':
            if not isinstance(source, (str, Path)):
                raise ValueError('履歴一覧は日別原本と同じフォルダにあるファイルから読み込んでください。')
            return self._import_cloud_history(Path(source), data)
        if not isinstance(data, dict) or data.get('format') != FORMAT or data.get('version') != 1 \
                or not isinstance(data.get('machines'), list) or not isinstance(data.get('records'), list):
            raise ValueError('P’s CUBEのバックアップではありません。')
        if data.get('kind') == 'viewer':
            raise ValueError('閲覧用の軽いファイルはバックアップではないため、読み込めません。')
        if len(data['machines']) > 10000 or len(data['records']) > MAX_BACKUP_RECORDS:
            raise ValueError('バックアップの件数が多すぎます。')
        for m in data['machines']:
            _validate_machine(m)
        for r in data['records']:
            _validate_record(r)
        machine_keys = {_machine_key(m) for m in data['machines']}
        record_keys = [_record_key(r) for r in data['records']]
        if len(machine_keys) != len(data['machines']) or len(set(record_keys)) != len(record_keys):
            raise ValueError('同じ機種・台が重複しています。')
        if any(_machine_key(r) not in machine_keys for r in data['records']):
            raise ValueError('台に対応する機種情報がありません。')
        if 'rack_captures' in data:
            captures = data['rack_captures']
            if not isinstance(captures, list) or any(not isinstance(k, str) for k in captures) or not set(captures) <= set(record_keys):
                raise ValueError('取り込み済みの印が不正です。')
        else:
            # 印の無い古い書き出し：台別7日分のグラフがある日は取り込み済みとみなす。
            captures = [_record_key(r) for r in data['records'] if (r.get('graph') or {}).get('kind') == 'daily']
        wanted = set(captures)
        incoming_events = validate_date_events(data.get('date_events'), data.get('suffix_events'))
        if _validate_only:
            return {}
        stored_events = self.date_events()
        merged_events = merge_date_events(stored_events, incoming_events)
        summary = {'added': 0, 'updated': 0, 'unchanged': 0, 'kept_local': 0, 'machines': len(data['machines']),
                   'events': sum(1 for e in merged_events if e not in stored_events)}
        with self.db if _transaction else nullcontext():
            # Lock before reading occupied racks; a capture may be writing in a
            # separate process. Protect same rack/day even if aliases differ.
            if _transaction and not self.db.in_transaction:
                self.db.execute('BEGIN IMMEDIATE')
            occupied = {(r['store'], r['rate'], r['rack'], r['day']) for row in
                        self.db.execute('SELECT payload FROM records') for r in [json.loads(row[0])]}
            if summary['events']:
                self.db.execute('INSERT OR REPLACE INTO state VALUES (?,?)',
                                ('date_events', json.dumps(merged_events, ensure_ascii=False)))
            for m in data['machines']:
                key = _machine_key(m)
                previous = self._read('machines', key) or {}
                if previous and data.get('import_mode') == 'fill_missing':
                    continue
                if previous and m.get('source_site') == 'anaslo':
                    continue
                saved = {**m, 'expected_count': m.get('expected_count') or previous.get('expected_count'),
                         'machine_type': previous.get('machine_type') or m.get('machine_type')}
                self.db.execute('INSERT OR REPLACE INTO machines VALUES (?,?)', (key, json.dumps(saved, ensure_ascii=False)))
            for r in data['records']:
                key = _record_key(r)
                identity = (r['store'], r['rate'], r['rack'], r['day'])
                if r.get('source_site') == 'anaslo' and identity in occupied:
                    summary['kept_local'] += 1
                    summary['unchanged'] += 1
                    continue
                occupied.add(identity)
                previous = self._read('records', key)
                saved = _merge(previous, r)
                numbers = ('bb', 'rb', 'at_art', 'games', 'my')
                if previous is None:
                    summary['added'] += 1
                elif any(previous[k] != saved[k] for k in numbers):
                    summary['updated'] += 1
                    self.db.execute('DELETE FROM rack_captures WHERE key=?', (key,))
                elif saved != previous:
                    summary['updated'] += 1
                else:
                    summary['unchanged'] += 1
                if previous is not None and any(previous[k] != r[k] for k in numbers) and saved is previous:
                    summary['kept_local'] += 1
                self.db.execute('INSERT OR REPLACE INTO records VALUES (?,?)', (key, json.dumps(saved, ensure_ascii=False)))
                if key in wanted and all(saved[k] == r[k] for k in numbers):
                    self.db.execute('INSERT OR IGNORE INTO rack_captures VALUES (?)', (key,))
            if data['records'] and not self._state('last_day'):
                self.db.execute('INSERT OR REPLACE INTO state VALUES (?,?)', ('last_day', max(r['day'] for r in data['records'])))
        if any(r.get('net_capture') for r in data['records']):
            self._trim_net_probes()
        return summary

    def _import_cloud_history(self, source, index):
        """日別原本を事前検査し、1トランザクションで取り込む。全期間のJSON配列は作らない。"""
        if index.get('version') != 2 or index.get('site') != 'pscube' or not isinstance(index.get('cloud_days'), list):
            raise ValueError('P’s CUBEの履歴一覧ではありません。')
        refs = index['cloud_days']
        indexed_days = index.get('days')
        if not isinstance(indexed_days, list) or not all(isinstance(d, str) for d in indexed_days) or len(set(indexed_days)) != len(indexed_days):
            raise ValueError('履歴の日付一覧が不正です。')
        if len(refs) > 16384 or index.get('history_progress') or len(refs) != len(indexed_days):
            raise ValueError('履歴の初回移行が途中です。Google側の同期完了を待ってください。')
        folder = source.resolve().parent
        seen = set()

        def read_day(ref):
            if not isinstance(ref, dict) or not isinstance(ref.get('day'), str) or ref['day'] in seen:
                raise ValueError('日別原本の一覧が不正です。')
            name = ref.get('name')
            match = re.fullmatch(r'database-history-day-pscube-(\d{4}-\d{2}-\d{2})-([0-9a-f]{64})\.json', name or '')
            if not match or match[1] != ref['day'] or match[2] != ref.get('hash'):
                raise ValueError('日別原本のファイル名・ハッシュが不正です。')
            if date.fromisoformat(ref['day']).isoformat() != ref['day'] or ref['day'] not in indexed_days:
                raise ValueError('日別原本の日付が一覧と一致しません。')
            path = (folder / name).resolve()
            if path.parent != folder:
                raise ValueError('日別原本は同期フォルダ直下に必要です。')
            if not isinstance(ref.get('bytes'), int) or not 0 < ref['bytes'] <= 48 * 1024 * 1024 or path.stat().st_size != ref['bytes']:
                raise ValueError('日別原本の容量が一覧と一致しません。')
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != ref['hash']:
                raise ValueError('日別原本のハッシュが一致しません。記録は変更していません。')
            value = json.loads(raw)
            if value.get('site') != 'pscube' or value.get('day') != ref['day'] or not isinstance(value.get('data'), dict):
                raise ValueError('日別原本の日付・サイトが不正です。')
            doc = value['data']
            if not isinstance(doc.get('records'), list) or any(r.get('day') != ref['day'] for r in doc['records'] if isinstance(r, dict)):
                raise ValueError('日別原本に別の日の記録があります。')
            if ref.get('count') != len(doc['records']):
                raise ValueError('日別原本の件数が一覧と一致しません。')
            return doc

        for ref in refs:
            self.import_backup(read_day(ref), _validate_only=True)
            seen.add(ref['day'])
        if sum(r['count'] for r in refs) != index.get('count'):
            raise ValueError('履歴の合計件数が一覧と一致しません。')
        seen.clear()
        summary = dict.fromkeys(('added', 'updated', 'unchanged', 'kept_local', 'machines', 'events'), 0)
        with self.db:
            for ref in refs:
                # 事前検査後にDrive同期が原本を書き換えても、同じハッシュを再検査して全体を取り消す。
                result = self.import_backup(read_day(ref), _transaction=False)
                for key in summary:
                    summary[key] += result[key]
                seen.add(ref['day'])
        return summary


class PscubeRandomCapture(AutoCapture):
    """Draw a new 100-microsecond interval for each scheduled wait, inclusive."""

    def __init__(self, clock=time.monotonic, draw=secrets.randbelow):
        super().__init__(clock=clock, minimum=15, maximum=25, default=20)
        self._draw = draw

    def _schedule(self):
        # 0.0001秒刻みに丸める（15 + n/10000 は、11,730通りで 21.667099999… のような誤差が出て、
        # 画面のスライダーの値と一致しなかった）。
        self._seconds = round(15 + self._draw(100001) / 10000, 4)
        super()._schedule()


class AutoPilot:
    """P’s CUBEの自動取り込みの判断（仕様：PSCUBE_AUTO_CAPTURE.md）。

    メルヘンの `AutoCapture`（ON/OFF・間隔0.1〜4.5秒・起動時OFF）を時間の管理に使い、
    窓への働きかけは渡された `evaluate`（pywebviewの evaluate_js）だけで行う。サイトの
    ボタン・人間確認・同意には触れない：表示中のページを読む判定（pscube_auto_probe.js）が
    ready のときだけ、手動の「未取得を取り込む」と同じ処理を始める。
    """
    MAX_FAILURES = 3
    # P’s CUBEの間隔（秒）。サイトに止められないよう、メルヘン（0.1〜4.5秒）より長くする。
    MIN_SECONDS, MAX_SECONDS, DEFAULT_SECONDS = 15, 25, 20
    # 対象のページなのにデータが出ない（人間確認の画面でもない）状態が、この回数・秒数続いたら
    # 止められたとみなして自動取り込みをOFFにする（放置しても叩き続けない。利用者の選択、2026-10-01）。
    BLOCK_CHECKS, BLOCK_SECONDS = 5, 60
    # ページへの問い合わせの時間制限（秒）。pywebview の evaluate_js は返事が来るまで待ち続け、
    # ページの読み込み中は読み込みが終わるまで待つ（2026-10-02 実測）。サイトの返事が遅い・来ないと
    # 自動取り込みが止まっていたため、返事が無ければあきらめて次の機会にやり直す。
    EVAL_TIMEOUT = 10
    # 取り込み（全台の表示→読み取り→保存）がこの秒数たっても終わらなければ、印を外してやり直す
    # （ページ内の処理が途中で消えた場合に「取り込み中」のまま進まなくなるのを防ぐ）。
    # 一覧待機90秒に、読み取り・保存通知の余裕30秒を足す。一覧を待っている途中で解除しない。
    PENDING_TIMEOUT = 120

    def __init__(self, evaluate, probe_script, saving=lambda: False, auto=None, eval_timeout=None):
        self.evaluate = evaluate
        self.probe_script = probe_script
        self.saving = saving
        self.auto = auto or PscubeRandomCapture()
        self.clock = getattr(self.auto, '_clock', time.monotonic)
        self.missing = []
        self.done = set()
        self.failures = {}
        self.pending = None
        self.pending_since = None
        self.loading_page = False
        self.connection_error = None
        # 取り込み日（None＝サイトの表示どおり）と、機種を数える向き。起動のたびに戻る。
        self.target_day = None
        self.direction = 'top'
        # {日付: 今回の取り込みで最初に保存したページのサイトの更新時刻}。これより古い数値の機種は取り直す。
        # 画面を開いている間（手動の取り込みも）続き、自動取り込みをONにするたびに作り直す。
        self.fresh_since = {}
        self.index_confirmation = None
        self.index_confirmation_page = None
        self.loaded_pages = 0
        # 自動取り込みが「すべて取り込みました」で止まったときの文。窓はこれを見て閉じる（close_when_finished）。
        self.completed = None
        self.eval_timeout = self.EVAL_TIMEOUT if eval_timeout is None else eval_timeout
        self._lock = threading.RLock()

    def _eval(self, script):
        """時間制限つきの問い合わせ。返事が無い・失敗したときは None（呼んだ側は次の機会にやり直す）。"""
        box = {}

        def run():
            try:
                box['value'] = self.evaluate(script)
            except Exception as error:  # noqa: BLE001 - a failed query is treated as no answer
                box['error'] = error

        worker = threading.Thread(target=run, name='pscube-eval', daemon=True)
        worker.start()
        worker.join(self.eval_timeout)
        if worker.is_alive() or 'error' in box:
            return None
        return box.get('value')

    def state(self):
        state = dict(self.auto.state())
        state.update(target_day=self.target_day, direction=self.direction, days=recent_business_days())
        return state

    def render(self):
        self._eval('window.__pscubeRenderAuto && window.__pscubeRenderAuto(' +
                   json.dumps(self.state(), ensure_ascii=True) + ')')

    def set_target(self, day=None, direction=None):
        """取り込み日・向きを決める。day: None＝変えない、''＝指定なし。自動取り込みのONの間は変えられない。"""
        with self._lock:
            if self.auto.state()['enabled']:
                raise ValueError('自動取り込みをOFFにしてから変えてください。')
            if day is not None:
                if day != '' and day not in recent_business_days():
                    raise ValueError('取り込み日は、サイトが見せる直近7日の営業日から選んでください。')
                self.target_day = day or None
            if direction is not None:
                if direction not in DIRECTIONS:
                    raise ValueError('取り込みの向きが不正です。')
                self.direction = direction
        self.render()
        return self.state()

    def configure(self, enabled, seconds, day=None, direction=None):
        with self._lock:
            if enabled and not self.auto.state()['enabled']:
                if day is not None or direction is not None:
                    self.set_target(day, direction)
            if enabled and self.connection_error:
                self.auto.pause(self.connection_error)
                return self.state()
            if enabled and not self.auto.state()['enabled']:
                self.fresh_since = {}
                self.completed = None
            if not enabled or not self.auto.state()['enabled']:
                self.index_confirmation = None
                self.index_confirmation_page = None
            self.auto.configure(enabled, seconds)
            if enabled:
                self.failures.clear()
                self.done.clear()
        self.render()
        return self.state()

    def connection_failed(self, message):
        """Native WebView2 callback: no JS/UI wait here."""
        with self._lock:
            self.connection_error = message
            self.index_confirmation = self.index_confirmation_page = None
            self.auto.configure(False, self.auto.state()['seconds'])
            self.auto.pause(message)

    def connection_started(self):
        with self._lock:
            self.connection_error = None
            self.loading_page = True

    def loading(self):
        """ページの読み込みが始まった：読み込みが終わるまで問い合わせない（問い合わせると待たされる）。"""
        with self._lock:
            self.loading_page = True

    def loaded(self):
        """新しいページ：間隔ぶん待ってから判定する。途中で消えた取り込み（ページ移動）は待たない。"""
        with self._lock:
            self.loading_page = False
            self.loaded_pages += 1
            if self.pending is not None and not self.saving():
                self.pending = None
                self.pending_since = None
            if self.connection_error:
                self.auto.pause(self.connection_error)
            else:
                self.auto.loaded()
        self.render()

    def tick(self):
        with self._lock:
            if self.loading_page or self.connection_error:
                return
            now = self.clock()
            if (self.pending is not None and self.pending_since is not None and not self.saving()
                    and now - self.pending_since >= self.PENDING_TIMEOUT):
                signature, self.pending, self.pending_since = self.pending, None, None
                self.failures[signature] = self.failures.get(signature, 0) + 1
                self.auto.pause(f'ON・取り込みが{self.PENDING_TIMEOUT}秒たっても終わらないため、やり直します'
                                f'（{self.failures[signature]}回目）')
            token = self.auto.due(busy=self.pending is not None or self.saving())
            if token is None:
                return
        # 問い合わせの間は鍵を持たない（保存完了の処理などを待たせない）。
        raw = self._eval(self.probe_script)
        with self._lock:
            if self.loading_page or self.connection_error:
                return
            try:
                probe = json.loads(raw) if isinstance(raw, str) else (raw or {})
            except ValueError:
                probe = {}
            if not isinstance(probe, dict):
                probe = {}
            now = self.clock()
            if probe.get('missing') and not probe.get('challenge'):
                self.missing.append(now)
                if len(self.missing) >= self.BLOCK_CHECKS and now - self.missing[0] >= self.BLOCK_SECONDS:
                    self.missing.clear()
                    self.auto.configure(False, self.auto.state()['seconds'])
                    self.auto.pause(BLOCKED_MESSAGE)
                    self.render()
                    return
            else:
                self.missing.clear()
            if probe.get('busy'):
                self.auto.pause('ON・保存処理中・完了待ち', token)
            elif not probe.get('ready'):
                self.auto.pause('ON・待機：' + str(probe.get('reason') or 'ページの準備待ち'), token)
            elif (self.target_day and probe.get('day') and probe['day'] != self.target_day and
                  not self._absent_tab(probe)):
                # 取り込み日と違う日のページ。サイトのボタンはアプリが押さない。アプリが開く全台一覧は日付つき（table_url_for_day）
                # なので、ここで待つのは利用者が自分で開いた全台一覧だけ。日付タブを手で合わせてもらう。
                hint = ('全台一覧の日付タブを' if probe.get('kind') == '全台一覧' else 'このページを')
                self.auto.pause(f'ON・待機：取り込み日は{_short_day(self.target_day)}ですが、表示中は{_short_day(probe["day"])}です。'
                                f'{hint}{_short_day(self.target_day)}に合わせてください', token)
            elif probe.get('signature') in self.done:
                self.auto.pause('ON・次のページ待ち（同じページは重複保存しません）', token)
            elif self.failures.get(probe.get('signature'), 0) >= self.MAX_FAILURES:
                self.auto.pause('ON・同じページで3回失敗したため待機中（内容を確かめて手動で取り込むか、OFF→ONで再開）', token)
            else:
                signature = probe['signature']

                def start():
                    if self._eval('window.__pscubeStartCapture ? window.__pscubeStartCapture() : false') is True:
                        self.pending = signature
                        self.pending_since = self.clock()
                        return True
                    return False

                if self.auto.run_current(token, start):
                    self.auto.pause(f'ON・{_short_day(self.target_day)}の日付タブが無い機種か確かめています（全台一覧）'
                                    if self._absent_tab(probe) else
                                    'ON・取り込み中（' + str(probe.get('kind') or 'ページ') + '）', token)
        self.render()

    def _absent_tab(self, probe):
        """表示中の全台一覧に取り込み日の日付タブが無い（新台・入れ替え）。このときだけ、表示中の日が違っても読み取りへ進め、
        保存側（`PscubeStore._skip_absent_day`）が読み取った日付タブで確かめて飛ばす。タブが読めない・取り込み日のタブが
        ある・取り込み日がタブより新しい・台別ページは、今までどおり待つ（2026-10-22、Android `pscubeAutoDecision` と同じ）。"""
        days = probe.get('days')
        return (probe.get('kind') == '全台一覧' and isinstance(days, list) and probe.get('day') in days and
                day_tab_absent(self.target_day, days))

    def finished(self, result=None, error=None):
        """保存の結果（手動の取り込みでも呼ばれる）。自動で始めた取り込みだけを数える。"""
        with self._lock:
            signature, self.pending, self.pending_since = self.pending, None, None
            enabled = self.auto.state()['enabled']
            if error is not None:
                if signature is not None:
                    self.failures[signature] = self.failures.get(signature, 0) + 1
                    if enabled:
                        self.auto.pause(f'ON・保存できませんでした（{self.failures[signature]}回目）：{error}')
            elif result is not None and result.get('retry_index'):
                if not enabled or self.connection_error:
                    result['reload'] = False
                    self.index_confirmation = self.index_confirmation_page = None
                    return
                # 再確認も同じページの失敗に数える。読むたびに違う一覧が返り続けても、開き直しは3回まで
                # （数えないと、一晩じゅう機種一覧を開き直し続ける。Android `_capture` と同じ）。
                count = None
                if signature is not None:
                    count = self.failures[signature] = self.failures.get(signature, 0) + 1
                if count is not None and count >= self.MAX_FAILURES:
                    result['reload'] = False                 # 3回目は開き直さない（この後は待機）
                    self.index_confirmation = self.index_confirmation_page = None
                if enabled:
                    self.auto.pause('ON・機種一覧を開き直し、もう一度確認します' + (f'（{count}回目）' if count else '')
                                    if result.get('reload', True) else
                                    'ON・機種一覧が前回より少なく、開き直すたびに違う一覧でした。3回で止めて待機中'
                                    '（一覧を一番下まで表示して手動で取り込むか、OFF→ONで再開）')
            elif result is not None:
                if signature is not None:
                    self.done.add(signature)
                    self.failures.pop(signature, None)
                if enabled and not result.get('next_url'):
                    self.auto.configure(False, self.auto.state()['seconds'])
                    day, self.target_day = self.target_day, None
                    self.completed = ('すべて取り込みました（自動取り込みを停止しました）' if not day else
                                      f'{_short_day(day)}の分をすべて取り込みました（自動取り込みを停止しました）')
                    self.auto.pause(self.completed)
                elif enabled:
                    self.auto.pause(f'ON・{result.get("skipped") or result.get("kind", "") + "を保存"}・残り{result.get("remaining", "?")}件・'
                                    f'次のページへ（{DIRECTION_LABELS[self.direction]}）'
                                    + ('（差枚は未取得）' if result.get('net_warning') else ''))
        self.render()


DIRECTION_LABELS = {'top': '上から', 'bottom': '下から'}


def submit_capture(db_path, export_path, pilot, raw, current_url):
    """取り込み画面で読み取った1ページを保存し、次に開くページを返す（`run_session` の保存の中身）。

    向き（上から／下から）・取り込み日・今回の基準の時刻は `pilot` が窓を開いている間ずっと持つ。
    ページごとに既定の向きへ戻さない：「下から取り込む」で始めたら、自動でも手動でも、どのページの
    保存のあとも、未取得を下から選び続ける（2026-10-06、再発防止の試験 `test_pscube_direction.py`）。
    """
    with pilot._lock:
        # 自動取り込みがOFFのとき（手動）は、一覧の最初からではなく、保存したページの次へ進む。
        manual = not pilot.auto.state()['enabled']
        direction, target_day, fresh_since = pilot.direction, pilot.target_day, dict(pilot.fresh_since)
    with pilot._lock:
        confirmed = (pilot.index_confirmation if pilot.index_confirmation_page is not None
                     and pilot.loaded_pages > pilot.index_confirmation_page else None)
    db = PscubeStore(db_path, index_confirmation=confirmed)
    try:
        try:
            result = db.import_page(raw, current_url, expected_day=target_day, direction=direction,
                                    manual=manual, fresh_since=fresh_since)
        except PscubeIndexRetry as retry:
            with pilot._lock:
                pilot.index_confirmation = retry.keys
                pilot.index_confirmation_page = pilot.loaded_pages
            return {'retry_index': True, 'next_url': current_url.split('#')[0]}
        pilot.index_confirmation = None
        pilot.index_confirmation_page = None
        pilot.fresh_since = result.pop('fresh_since')
        result['direction'] = direction
        result['backup'] = auto_backup(db, export_path)
        result['source_url'] = current_url
        return result
    finally:
        db.close()


def overlay_script(capture_script, index_url):
    """取り込み画面の右下のカード（手動の取り込み・自動取り込みのON/OFF・間隔・状態）。"""
    return r'''
    (() => {
      if (document.getElementById('database-pscube-card')) return;
      const card = document.createElement('div');
      card.id = 'database-pscube-card';
      Object.assign(card.style, {position:'fixed',bottom:'14px',right:'14px',zIndex:'2147483647',width:'250px',
        maxHeight:'calc(100vh - 50px)',overflowY:'auto',background:'white',border:'1px solid #c9d2df',borderRadius:'12px',
        padding:'10px',boxShadow:'0 4px 18px rgba(0,0,0,.18)',fontFamily:'sans-serif',display:'grid',gap:'8px'});
      const button = document.createElement('button');
      button.id = 'database-pscube-capture';
      const indexUrl = INDEX_URL;
      const isRoot = location.pathname.endsWith('/c740601/');
      button.textContent = isRoot ? 'スロット機種一覧へ' : '未取得を取り込む';
      Object.assign(button.style, {background:'#304d6e',color:'white',padding:'12px',border:'0',borderRadius:'8px',fontSize:'15px',cursor:'pointer'});
      const auto = document.createElement('button');
      auto.id = 'database-pscube-auto';
      auto.type = 'button';
      Object.assign(auto.style, {color:'white',padding:'10px',border:'2px solid #b8c5d8',borderRadius:'6px',fontSize:'14px',fontWeight:'bold',cursor:'pointer',background:'#526078'});
      auto.textContent = '自動取り込み：OFF（押すと開始）';
      // 日付指定取り込み：取り込む営業日を決める（日本時間の午前3時までは前日）。
      // 上から／下から：機種を一覧のどちら側から取り込むか。どちらも押すと自動取り込みをONにする。
      const dayLabel = document.createElement('div');
      dayLabel.style.cssText = 'font-size:12px;display:block;color:#33445a';
      const dayText = document.createElement('span');
      dayText.textContent = '日付指定取り込み（取り込む日）';
      const daySelect = document.createElement('select');
      daySelect.id = 'database-pscube-day';
      daySelect.setAttribute('aria-label', '日付指定取り込み（取り込む日）');
      Object.assign(daySelect.style, {width:'100%',marginTop:'4px',padding:'6px',fontSize:'13px'});
      dayLabel.append(dayText, daySelect);
      const startRow = document.createElement('div');
      startRow.style.cssText = 'display:grid;grid-template-columns:1fr 1fr;gap:6px';
      const mkStart = (id, text) => {
        const b = document.createElement('button');
        b.id = id; b.type = 'button'; b.textContent = text;
        Object.assign(b.style, {color:'white',padding:'10px 4px',border:'2px solid #b8c5d8',borderRadius:'6px',fontSize:'13px',fontWeight:'bold',cursor:'pointer',background:'#304d6e'});
        return b;
      };
      const topButton = mkStart('database-pscube-top', '上から取り込む');
      const bottomButton = mkStart('database-pscube-bottom', '下から取り込む');
      startRow.append(topButton, bottomButton);
      const label = document.createElement('label');
      label.style.cssText = 'font-size:12px;display:block;color:#33445a';
      const seconds = document.createElement('input');
      seconds.id = 'database-pscube-interval';
      seconds.type = 'range'; seconds.min = '15'; seconds.max = '25'; seconds.step = '0.0001'; seconds.value = '20';
      seconds.disabled = true;
      seconds.style.width = '100%';
      const value = document.createElement('span');
      value.textContent = '間隔：15〜25秒ランダム';
      label.append(value, seconds);
      const status = document.createElement('div');
      status.id = 'database-pscube-auto-status';
      status.style.cssText = 'font-size:11px;color:#33445a;white-space:normal;word-break:break-word';
      status.textContent = '人間確認・同意の画面ではONのまま待ちます。確認は手動で操作してください。';
      const reset = document.createElement('button');
      const retry = document.createElement('button');
      retry.id = 'database-pscube-retry';
      retry.type = 'button';
      retry.textContent = 'もう一度開く（Cookie・記録は保持）';
      Object.assign(retry.style, {background:'white',color:'#33445a',padding:'6px',border:'1px solid #b8c5d8',borderRadius:'6px',fontSize:'12px',cursor:'pointer'});
      retry.onclick = async () => {
        if (window.__pscubeBusy) { status.textContent = '保存中です。保存が終わってから押してください。'; return; }
        retry.disabled = true;
        try { await window.pywebview.api.retry_page(); }
        catch (_) { retry.disabled = false; status.textContent = '開き直せませんでした。通信状態を確認してください。'; }
      };
      reset.id = 'database-pscube-reset';
      reset.type = 'button';
      reset.textContent = 'サイトの記録を消してやり直す';
      Object.assign(reset.style, {background:'white',color:'#33445a',padding:'6px',border:'1px solid #b8c5d8',borderRadius:'6px',fontSize:'12px',cursor:'pointer'});
      reset.onclick = async () => {
        if (window.__pscubeBusy) { status.textContent = '保存中です。保存が終わってから押してください。'; return; }
        if (!confirm('この画面に残っているCookie・保存データを消して、P’s CUBEの最初のページを開き直します。\n取り込んだ記録は消えません。自動取り込みはOFFになります。\nDNSエラーやHTTP403が直るとは限りません。人間確認・同意が出たら手で操作してください。')) return;
        reset.disabled = true;
        status.textContent = '消しています…';
        try {
          status.textContent = await window.pywebview.api.reset_site();
        } catch (error) {
          reset.disabled = false;
          status.textContent = '消せませんでした：' + String(error?.message || error);
        }
      };
      card.append(button, auto, dayLabel, startRow, label, status, retry, reset);
      const identity = raw => {
        const u = new URL(raw);
        if (!u.pathname.endsWith('nc-v06-001.php')) u.hash = '';
        return u.href;
      };
      let capturedUrl = null, autoEnabled = false, autoChanging = false, revision = -1;
      const idle = text => { button.textContent = text; button.disabled = autoEnabled; window.__pscubeBusy = false; };
      window.__pscubeBusy = false;
      window.pscubeCaptureFailed = error => { idle(String(error)); };
      window.pscubeCaptureComplete = result => {
        if (!capturedUrl || identity(location.href) !== identity(capturedUrl)) return;
        if (result.retry_index) {
          capturedUrl = null;
          if (!autoEnabled || result.reload === false) { idle('機種一覧が前回より少なく、保存していません'); return; }
          idle('機種一覧を開き直して確認します');
          location.reload();
          return;
        }
        const way = result.direction === 'bottom' ? '下から' : result.direction === 'top' ? '上から' : '';
        idle(`${result.skipped || result.kind + 'を保存'} · 残り${result.remaining}${way ? '（' + way + '）' : ''}${result.net_warning ? ' · ' + result.net_warning : ''} · ${result.backup || ''}`);
        capturedUrl = null;
        if (result.next_url) location.href = result.next_url;
      };
      const run = async () => {
        window.__pscubeBusy = true;
        button.disabled = true; button.textContent = '読み込み中…';
        try {
          const before = location.href;
          const expectedCount = location.pathname.endsWith('nc-v05-011.php')
            ? await window.pywebview.api.get_installation_count() : null;
          if (identity(location.href) !== identity(before)) throw new Error('読み取り中にページが切り替わりました。');
          await SCROLL_SCRIPT;
          if (identity(location.href) !== identity(before)) throw new Error('読み取り中にページが切り替わりました。');
          capturedUrl = location.href;
          const payload = await CAPTURE_SCRIPT;
          if (identity(location.href) !== identity(before)) throw new Error('読み取り中にページが切り替わりました。');
          const result = await window.pywebview.api.submit_page(payload);
          window.pscubeCaptureComplete(result);
        } catch (error) {
          const message = String(error?.message || error);
          idle(message);
          try { await window.pywebview.api.capture_failed(message); } catch (_) {}
        }
      };
      // 自動取り込み（Python側のタイマー）から呼ぶ。取り込み中・最初のページでは始めない。
      window.__pscubeStartCapture = () => {
        if (isRoot || window.__pscubeBusy) return false;
        run();
        return true;
      };
      button.onclick = () => {
        if (isRoot) { location.href = indexUrl; return; }
        if (!window.__pscubeBusy && !autoEnabled) run();
      };
      window.__pscubeRenderAuto = state => {
        if (state.revision < revision) return;
        revision = state.revision;
        autoEnabled = !!state.enabled;
        auto.textContent = autoEnabled ? '自動取り込み：ON（押すと停止）' : '自動取り込み：OFF（押すと開始）';
        auto.style.background = autoEnabled ? '#087d59' : '#526078';
        auto.setAttribute('aria-pressed', String(autoEnabled));
        auto.disabled = autoChanging;
        seconds.disabled = true;
        seconds.value = String(state.seconds);
        value.textContent = '15〜25秒ランダム（今回 ' + Number(state.seconds).toFixed(4) + '秒）';
        status.textContent = state.message;
        // 取り込み日の選択肢は、午前3時で営業日が変わるので、画面を開いたままでも毎回つくり直す。
        const days = Array.isArray(state.days) ? state.days : [];
        if (JSON.stringify(days) !== daySelect.dataset.days) {
          daySelect.dataset.days = JSON.stringify(days);
          daySelect.textContent = '';
          const none = document.createElement('option');
          none.value = ''; none.textContent = '指定なし（サイトの表示どおり）';
          daySelect.append(none);
          days.forEach((day, i) => {
            const o = document.createElement('option');
            const d = new Date(day + 'T00:00:00');
            o.value = day;
            o.textContent = (d.getMonth() + 1) + '/' + d.getDate() + '（' + '日月火水木金土'[d.getDay()] + '）' + (i === 0 ? '　今の営業日' : '');
            daySelect.append(o);
          });
        }
        daySelect.value = state.target_day || '';
        daySelect.disabled = autoEnabled || autoChanging;
        for (const b of [topButton, bottomButton]) {
          b.disabled = autoEnabled || autoChanging || isRoot;
          b.style.opacity = b.disabled ? '.5' : '1';
          // いまの向きを、自動取り込みのOFFの間も示す（手動の「未取得を取り込む」もこの向きで次を選ぶ）。
          const chosen = b === (state.direction === 'bottom' ? bottomButton : topButton);
          b.style.outline = chosen ? '3px solid #087d59' : '';
          b.setAttribute('aria-pressed', String(chosen));
        }
        if (!window.__pscubeBusy) button.disabled = autoEnabled && !isRoot;
        button.style.opacity = button.disabled ? '.5' : '1';
      };
      daySelect.onchange = async () => {
        try { window.__pscubeRenderAuto(await window.pywebview.api.set_target_day(daySelect.value, null)); }
        catch (error) { status.textContent = '取り込み日を変えられませんでした：' + String(error?.message || error); }
      };
      const startFrom = async direction => {
        if (autoChanging || autoEnabled || isRoot) return;
        autoChanging = true; topButton.disabled = bottomButton.disabled = auto.disabled = true;
        try {
          const state = await window.pywebview.api.set_auto_capture(true, Number(seconds.value), daySelect.value, direction);
          autoChanging = false;
          window.__pscubeRenderAuto(state);
        } catch (error) {
          autoChanging = false; auto.disabled = false; topButton.disabled = bottomButton.disabled = false;
          status.textContent = '自動取り込みを始められませんでした：' + String(error?.message || error);
        }
      };
      topButton.onclick = () => startFrom('top');
      bottomButton.onclick = () => startFrom('bottom');
      auto.onclick = async () => {
        if (autoChanging) return;
        autoChanging = true; auto.disabled = true;
        try {
          const state = await window.pywebview.api.set_auto_capture(!autoEnabled, Number(seconds.value), daySelect.value, null);
          autoChanging = false;
          window.__pscubeRenderAuto(state);
        } catch (error) {
          autoChanging = false; auto.disabled = false;
          status.textContent = '自動取り込みを切り替えられませんでした：' + String(error?.message || error);
        }
      };
      document.body.append(card);
    })();
    '''.replace('SCROLL_SCRIPT', SCROLL_SCRIPT).replace('CAPTURE_SCRIPT', capture_script).replace('INDEX_URL', json.dumps(index_url))


# 窓を最小化・裏に回しても、ページの時計（取り込みのスクロール、サイトの続きの読み込みの見回り）を抑えさせない。
# 既定では見えない窓が5分続くと、ページの時計が1分に1回まで抑えられ、全台一覧が6台のまま「一覧の読み込みが
# 時間切れ」になり、3回で待機していた（2026-10-28、利用者の報告。実WebView2とローカルの模擬ページで再現）。
# サイトへの通信の間隔は Python 側（15〜25秒）が決めるので変わらない。pywebview の既定（ElasticOverscroll）も含める。
BROWSER_ARGUMENTS = ('--disable-features=ElasticOverscroll,CalculateNativeWinOcclusion,IntensiveWakeUpThrottling '
                     '--disable-background-timer-throttling --disable-renderer-backgrounding '
                     '--disable-backgrounding-occluded-windows')


def keep_page_timers(environ=os.environ):
    """WebView2 の起動設定（環境変数）に BROWSER_ARGUMENTS を足す。取り込み窓のプロセスの中だけで効く。"""
    current = environ.get('WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS', '').strip()
    if BROWSER_ARGUMENTS not in current:
        environ['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'] = f'{current} {BROWSER_ARGUMENTS}'.strip()


FINISHED_NAME = 'pscube-capture-finished.json'


def close_when_finished(pilot, saving, window, data_dir) -> bool:
    """自動取り込みが「すべて取り込みました」で止まり、保存も終わっていれば、結果の文を親画面への知らせに残して窓を閉じる。

    取り込み窓はタイマーを間引かない設定（keep_page_timers）なので、サイトのページを開いたままにすると、取り込みの
    あともサイトの定期通信が続く（2026-10-30 利用者「各取り込み終わったら停止してほしい」、PCのP’s CUBEだけ）。
    手動の取り込みでは閉じない。知らせが書けなくても窓は閉じる（サイトへの接続を止めるほうを優先する）。"""
    message = pilot.completed
    if not message or saving():
        return False
    write_notice(Path(data_dir) / FINISHED_NAME, message)
    window.destroy()
    return True


def take_finished_message(data_dir) -> str | None:
    """取り込み窓が閉じたあとに親画面が呼ぶ。自動で閉じたときの結果の文を返して知らせを消す（無ければ None）。"""
    return take_notice(Path(data_dir) / FINISHED_NAME)


def run_session(db_path, export_path):
    import webview

    keep_page_timers()
    data_dir = Path(db_path).resolve().parent
    take_finished_message(data_dir)  # 前回の窓の知らせが残っていれば消す（親画面に古い結果を出さない）

    script = CAPTURE.read_text(encoding='utf-8')
    probe = PROBE.read_text(encoding='utf-8')
    connection = BrowserConnection(ROOT_URL)

    class Bridge:
        def __init__(self):
            self._window = None
            self._capture_lock = threading.Lock()
            self.pilot = None

        def get_installation_count(self):
            return installation_count(db_path, self._window.get_current_url())

        def submit_page(self, raw):
            with self._capture_lock:
                try:
                    result = self._submit_page(raw)
                except Exception as error:
                    self._notify('window.pscubeCaptureFailed?.(' + json.dumps(str(error), ensure_ascii=True) + ')')
                    self.pilot.finished(error=str(error))
                    raise
                # The site's scrolling changes location.hash. WebView2 may
                # recreate pywebview's promise callbacks on that navigation,
                # so deliver completion to our own stable DOM handler too.
                self.pilot.finished(result=result)
                self._notify('window.pscubeCaptureComplete?.(' + json.dumps(result, ensure_ascii=True) + ')')
                return result

        def _notify(self, script):
            # 待たずに送る（ページが移っている途中だと evaluate_js が待たされ、保存の完了が遅れるため）。
            threading.Thread(target=lambda: self.pilot._eval(script), name='pscube-notify', daemon=True).start()

        def capture_failed(self, message):
            # 読み取りの途中（保存の前）で失敗したとき。保存中の失敗は submit_page が数える。
            if not self._capture_lock.locked():
                self.pilot.finished(error=str(message)[:300])
            return True

        def set_auto_capture(self, enabled, seconds, day=None, direction=None):
            return self.pilot.configure(enabled, seconds, day, direction)

        def set_target_day(self, day=None, direction=None):
            return self.pilot.set_target(day, direction)

        def reset_site(self):
            if not self._capture_lock.acquire(blocking=False):
                raise ValueError('保存中です。保存が終わってから押してください。')
            try:
                return reset_site(self._window, self.pilot, saving=lambda: False)
            finally:
                self._capture_lock.release()

        def _submit_page(self, raw):
            if connection.failure:
                raise ValueError(connection.failure['message'])
            return submit_capture(db_path, export_path, self.pilot, raw, self._window.get_current_url())

        def retry_page(self):
            if not self._capture_lock.acquire(blocking=False):
                raise ValueError('保存中です。保存が終わってから押してください。')
            try:
                return retry_page(self._window, self.pilot, connection, saving=lambda: False)
            finally:
                self._capture_lock.release()

    bridge = Bridge()
    window = webview.create_window('P’s CUBE 取り込み', ROOT_URL, width=1050, height=780, js_api=bridge)
    bridge._window = window
    bridge.pilot = AutoPilot(window.evaluate_js, probe, saving=bridge._capture_lock.locked)
    overlay = overlay_script(script, ROOT_URL + 'cgi-bin/nc-v03-001.php?cd_ps=2')
    stop = threading.Event()
    native_handlers = []

    def failed():
        with connection.lock:
            if not connection.failure:
                return
            message = connection.failure['message']
            revision = connection.revision
        def show():
            with connection.lock:
                if stop.is_set() or revision != connection.revision or not connection.failure:
                    return
                if connection.showing_error:
                    return
            bridge.pilot.connection_failed(message)
            if not present_connection_failure(window, connection, revision):
                bridge.pilot.render()

        threading.Thread(target=show, name='pscube-connection-error', daemon=True).start()

    def install_native():
        native_handlers.extend(install_webview2_handlers(
            window, connection, failed))

    def install_overlay():
        try:
            site_url(window.get_current_url())
            window.evaluate_js(overlay)
        except Exception:
            pass
        if not connection.failure and not connection.showing_error:
            bridge.pilot.connection_started()
        bridge.pilot.loaded()

    def auto_loop():
        # 窓を最小化してもJavaScriptのタイマーのように遅れないよう、Python側で数える。
        while not stop.wait(0.1):
            try:
                bridge.pilot.tick()
            except Exception:
                pass
            try:
                if close_when_finished(bridge.pilot, bridge._capture_lock.locked, window, data_dir):
                    return
            except Exception:
                pass

    def closed():
        stop.set()

    window.events.before_load += bridge.pilot.loading
    if hasattr(window.events, 'before_show'):
        window.events.before_show += install_native
    window.events.loaded += install_overlay
    window.events.closed += closed
    threading.Thread(target=auto_loop, name='pscube-auto', daemon=True).start()
    # pywebview の初期設定はシークレットモード（起動のたびにCookieを消し、別サイトの
    # Cookieも拒否する）。そのため人間確認（hCaptcha）の確認済みが残らず、何度も確認が
    # 出る。Safariと同じく、data の中の専用の場所にCookieを残す（2026-10-01、Androidで
    # 同じ原因を直して人間確認が出なくなったことを受けて）。
    webview.start(gui='edgechromium', private_mode=False, storage_path=str(webview_storage(db_path)))


def webview_storage(db_path) -> Path:
    """P’s CUBE取り込み画面のCookie・サイトのデータを残す場所（記録と同じ data の中、Gitには入らない）。"""
    folder = Path(db_path).resolve().parent / 'pscube-webview'
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def runtime_root():
    if getattr(sys, 'frozen', False):
        executable_dir = Path(sys.executable).resolve().parent
        for candidate in (executable_dir.parent, executable_dir.parent.parent, executable_dir):
            if (candidate / 'data').exists() or (candidate / 'app.py').exists():
                return candidate
        return executable_dir
    return Path(__file__).resolve().parent


if __name__ == '__main__':
    root = runtime_root()
    if len(sys.argv) == 3 and sys.argv[1] == '--smoke-local':
        from runtime_smoke import run
        run(sys.modules[__name__], 'pscube', sys.argv[2])
    else:
        run_session(sys.argv[1] if len(sys.argv) > 1 else root / 'data' / 'pscube.sqlite3',
                    sys.argv[2] if len(sys.argv) > 2 else root / 'data' / 'pscube-viewer.json')
