"""CIが動く側のGitHubへ main を送る（月の前半・後半の使い分け、AGENTS.md「CI を動かす GitHub」）。

    python tools/push_ci.py            # 確かめてから送る
    python tools/push_ci.py --dry-run  # 確かめるだけ（送らない）
    python tools/push_ci.py <コミット>  # HEAD 以外を送る

切り替えの日（1日・16日）に、だれが・どの順で送っても次のことが起きないようにする（2026-10-26 利用者
「当日に何をしても問題がないようにしておこう」）。

- 送り先の取り違え：日付はPCやクラウドの時刻設定によらず日本時間（UTC+9）で決める。AIの環境は
  世界標準時のことが多く、1日・16日の0時〜9時は前日扱いになって送り先を間違える。
- 片方にだけあるコミットの置き去り・上書き：2つのリポジトリの main をどちらも取得し、両方とも送る
  コミットの祖先であることを確かめる。そうでなければ止める（force push はしない）。
- 1日0時〜9時の正本：GitHubの無料枠は日本時間の1日9時ごろに戻るので、それより前は正本へ
  コード（.md 以外）を送らない。.md だけなら CI が動かないので送ってよい。
- 送信直前にも両mainと日本時間を確認し、履歴や期間が変わっていれば停止する。
  2つのGitHubを同時にロックする仕組みではないため、別AI・別環境との同時pushは避ける。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
CANONICAL = 'https://github.com/imakurudev-eng/database'
CI_COPY = 'https://github.com/keyanbaitian6-cell/database-ci'
# 正本の無料枠が月替わりで戻る時刻（日本時間の1日9時ごろ。GitHubはUTCの0時で切り替える）。
QUOTA_RESET_HOUR = 9


def target_for(now: datetime) -> str:
    """その時刻（日本時間に直して）に CI を動かす側。1〜15日は正本、16日〜月末は database-ci。"""
    return CANONICAL if now.astimezone(JST).day <= 15 else CI_COPY


def before_quota_reset(now: datetime) -> bool:
    jst = now.astimezone(JST)
    return jst.day == 1 and jst.hour < QUOTA_RESET_HOUR


def docs_only(files) -> bool:
    """.md だけの変更なら CI は動かない（regression.yml の paths-ignore）。"""
    return all(name.endswith('.md') for name in files)


def git(*args, check=True) -> str:
    result = subprocess.run(['git', *args], capture_output=True, text=True, encoding='utf-8')
    if check and result.returncode:
        raise SystemExit(f'git {" ".join(args)} に失敗しました：{result.stderr.strip()}')
    return result.stdout.strip()


def remote_tip(url: str) -> str | None:
    """mainの現在値を照会する。取得失敗は空リポジトリと区別して停止する。"""
    refs = git('ls-remote', url, 'refs/heads/main')
    return refs.split()[0] if refs else None


def remote_main(url: str) -> str | None:
    """その GitHub の main を手元に取得してコミットを返す（空のリポジトリなら None）。"""
    if remote_tip(url) is None:
        return None
    git('fetch', '--quiet', '--no-tags', url, 'refs/heads/main')
    return git('rev-parse', 'FETCH_HEAD')


def is_ancestor(older: str, newer: str) -> bool:
    return subprocess.run(['git', 'merge-base', '--is-ancestor', older, newer]).returncode == 0


def main(argv=None, now=None, clock=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        # AIのシェル（パイプ）にはUTF-8で出す。Windowsのcmdの画面ではそのまま。どちらでも文字で止まらない。
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(errors='replace', **({} if stream.isatty() else {'encoding': 'utf-8'}))
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('commit', nargs='?', default='HEAD')
    parser.add_argument('--dry-run', action='store_true', help='確かめるだけで送らない')
    args = parser.parse_args(argv)
    # nowは既存試験用の固定時刻。実運用では呼ぶたびに現在時刻を取得する。
    clock = clock or (lambda: now if now is not None else datetime.now(timezone.utc))
    started = clock()
    commit = git('rev-parse', '--verify', args.commit + '^{commit}')
    target = target_for(started)
    print(f'日本時間 {started.astimezone(JST):%Y-%m-%d %H:%M} → 送り先 {target}')

    heads = {url: remote_main(url) for url in (CANONICAL, CI_COPY)}
    # この取得時点の両mainを包含することを確認する。送信前に先端の変化も確認する。
    for url, head in heads.items():
        if head and not is_ancestor(head, commit):
            only = git('log', '--oneline', f'{commit}..{head}')
            print(f'止めました：{url} の main に、送るコミットに無い変更があります。\n{only}\n'
                  'その main を取得して手元の main に合わせて（merge）から、もう一度送ってください。'
                  'force push はしません。', file=sys.stderr)
            return 1

    current = heads[target]
    if current == commit:
        print('送り先の main は既にこのコミットです。送る物はありません。')
        return 0
    files = git('diff', '--name-only', current, commit).splitlines() if current else ['(全体)']
    doc = docs_only(files)
    if target == CANONICAL and before_quota_reset(started) and not doc:
        print('止めました：日本時間の1日9時ごろまでは正本の無料枠が前月のままで、CIが動かない恐れがあります。'
              '9時を過ぎてから送ってください（.md だけの変更なら今でも送れます）。', file=sys.stderr)
        return 1
    summary = ('中身の変更は無く、履歴だけを送ります。' if not files else
               f'{len(files)}ファイル変更：' + ('.md だけなので CI は動きません。' if doc else 'CI が1回動きます。'))
    print(f'{git("log", "--oneline", "-1", commit)}（{summary}）')
    # 再fetchは不要。削除・新設を含め、確認時から変わったmainがあれば再実行を求める。
    latest = {url: remote_tip(url) for url in heads}
    if latest != heads:
        changed = '\n'.join(f'{url}: {heads[url]} → {latest[url]}'
                            for url in heads if latest[url] != heads[url])
        print(f'止めました：確認中にmainが変わりました。\n{changed}\n'
              '別の作業のpushが終わってから、両mainを取得して確認し直してください。', file=sys.stderr)
        return 1
    # 通信完了後に時刻を取得する。送り先が同じでも翌月へ跨いだ場合は確認をやり直す。
    final_now = clock()
    start_jst, final_jst = started.astimezone(JST), final_now.astimezone(JST)
    if (target_for(final_now) != target or
            (start_jst.year, start_jst.month) != (final_jst.year, final_jst.month)):
        print('止めました：確認中に日本時間の送信期間が変わりました。'
              '送り先を確認するため、最初から実行し直してください。', file=sys.stderr)
        return 1
    if target == CANONICAL and before_quota_reset(final_now) and not doc:
        print('止めました：送信直前の日本時間が1日9時より前です。'
              '時計を確認し、9時以降に実行し直してください。', file=sys.stderr)
        return 1
    if args.dry_run:
        print('確認だけで終わりました（--dry-run）。')
        return 0
    result = subprocess.run(['git', 'push', target, f'{commit}:refs/heads/main'])
    return result.returncode


if __name__ == '__main__':
    sys.exit(main())
