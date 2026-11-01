"""CIが動く側のGitHubへ送る tools/push_ci.py。切り替えの日（1日・16日）に何をしても壊れないこと。"""
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
import push_ci  # noqa: E402


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def git(cwd, *args):
    return subprocess.run(['git', '-c', 'user.name=test', '-c', 'user.email=test@example.com', *args],
                          cwd=cwd, check=True, capture_output=True, text=True, encoding='utf-8').stdout.strip()


class DateTests(unittest.TestCase):
    def test_target_follows_japan_time_not_the_machine_or_utc(self):
        # 日本時間の1日0時・16日0時は、世界標準時ではまだ前日の15時。
        self.assertEqual(push_ci.target_for(utc(2026, 10, 31, 14, 59)), push_ci.CI_COPY)
        self.assertEqual(push_ci.target_for(utc(2026, 10, 31, 15, 0)), push_ci.CANONICAL)
        self.assertEqual(push_ci.target_for(utc(2026, 11, 15, 14, 59)), push_ci.CANONICAL)
        self.assertEqual(push_ci.target_for(utc(2026, 11, 15, 15, 0)), push_ci.CI_COPY)

    def test_quota_window_is_only_the_first_morning_in_japan(self):
        self.assertTrue(push_ci.before_quota_reset(utc(2026, 10, 31, 23, 59)))   # 11/1 8:59
        self.assertFalse(push_ci.before_quota_reset(utc(2026, 11, 1, 0, 0)))     # 11/1 9:00
        self.assertFalse(push_ci.before_quota_reset(utc(2026, 11, 15, 16, 0)))   # 11/16 1:00

    def test_docs_only(self):
        self.assertTrue(push_ci.docs_only(['AI_COLLABORATION.md', 'database/NOTE.md']))
        self.assertFalse(push_ci.docs_only(['AI_COLLABORATION.md', 'database/app.py']))


class PushTests(unittest.TestCase):
    """2つのGitHubを手元の空リポジトリで置き換えて、実際に送る・止めるを確かめる。"""
    def setUp(self):
        temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.canonical, self.copy, self.work = root / 'canonical.git', root / 'copy.git', root / 'work'
        for bare in (self.canonical, self.copy):
            git(root, 'init', '-q', '--bare', '-b', 'main', str(bare))
        git(root, 'init', '-q', '-b', 'main', str(self.work))
        self.commit('app.py', 'A')
        for bare in (self.canonical, self.copy):
            git(self.work, 'push', '-q', str(bare), 'HEAD:refs/heads/main')
        for name, value in (('CANONICAL', str(self.canonical)), ('CI_COPY', str(self.copy))):
            patcher = patch.object(push_ci, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        previous = os.getcwd()
        os.chdir(self.work)
        self.addCleanup(os.chdir, previous)

    def commit(self, name, text, cwd=None):
        cwd = cwd or self.work
        (Path(cwd) / name).write_text(text, encoding='utf-8')
        git(cwd, 'add', name)
        git(cwd, 'commit', '-q', '-m', f'{name} {text}')
        return git(cwd, 'rev-parse', 'HEAD')

    def main_of(self, bare):
        return git(self.work, 'ls-remote', str(bare), 'refs/heads/main').split()[0]

    def run_push(self, now):
        with patch('sys.stdout'), patch('sys.stderr'):
            return push_ci.main([], now=now)

    def test_first_push_of_november_brings_the_second_half_commits_to_the_canonical_repository(self):
        late = self.commit('app.py', 'B')  # 10月後半の作業
        self.assertEqual(self.run_push(utc(2026, 10, 26, 3, 0)), 0)
        self.assertEqual(self.main_of(self.copy), late)
        latest = self.commit('app.py', 'C')
        self.assertEqual(self.run_push(utc(2026, 11, 1, 1, 0)), 0)  # 11/1 10:00
        self.assertEqual(self.main_of(self.canonical), latest)
        self.assertEqual(self.main_of(self.copy), late)  # 期間外の側へは送らない

    def test_a_commit_only_on_the_other_repository_stops_without_overwriting(self):
        other = self.work.parent / 'other'
        git(self.work.parent, 'clone', '-q', str(self.copy), str(other))
        only_there = self.commit('notes.py', 'D', cwd=other)
        git(other, 'push', '-q', 'origin', 'HEAD:refs/heads/main')
        self.commit('app.py', 'B')
        before = self.main_of(self.canonical)
        self.assertEqual(self.run_push(utc(2026, 11, 1, 1, 0)), 1)
        self.assertEqual(self.main_of(self.canonical), before)
        self.assertEqual(self.main_of(self.copy), only_there)
        # 合わせてから送れば、両方の変更が正本に入る。
        git(self.work, 'pull', '-q', '--no-rebase', '--no-edit', str(self.copy), 'main')
        self.assertEqual(self.run_push(utc(2026, 11, 1, 1, 0)), 0)
        self.assertEqual(self.main_of(self.canonical), git(self.work, 'rev-parse', 'HEAD'))

    def test_code_waits_for_the_quota_on_the_first_morning_but_docs_do_not(self):
        before = self.main_of(self.canonical)
        self.commit('app.py', 'B')
        self.assertEqual(self.run_push(utc(2026, 10, 31, 22, 0)), 1)  # 11/1 7:00
        self.assertEqual(self.main_of(self.canonical), before)
        git(self.work, 'reset', '-q', '--hard', 'HEAD~1')
        notes = self.commit('NOTES.md', '記録')
        self.assertEqual(self.run_push(utc(2026, 10, 31, 22, 0)), 0)
        self.assertEqual(self.main_of(self.canonical), notes)

    def test_nothing_to_send_when_the_target_already_has_it(self):
        self.assertEqual(self.run_push(utc(2026, 11, 2, 0, 0)), 0)

    def test_remote_main_ignores_another_fetch_overwriting_fetch_head(self):
        expected = self.main_of(self.canonical)
        newer = self.commit('app.py', 'B')
        git(self.work, 'push', '-q', str(self.copy), 'HEAD:refs/heads/main')
        original = push_ci.git

        def concurrent_fetch(*args, **kwargs):
            result = original(*args, **kwargs)
            if args[0] == 'fetch':
                # 別プロセスの取得が共有FETCH_HEADを書き換えた状況を実Gitで再現。
                git(self.work, 'fetch', '-q', str(self.copy), 'refs/heads/main')
            return result

        with patch.object(push_ci, 'git', side_effect=concurrent_fetch):
            self.assertEqual(push_ci.remote_main(str(self.canonical)), expected)
        self.assertEqual(git(self.work, 'rev-parse', 'FETCH_HEAD'), newer)

    def test_period_change_during_checks_never_pushes(self):
        self.commit('app.py', 'B')
        before = [self.main_of(repo) for repo in (self.canonical, self.copy)]
        cases = [
            (utc(2026, 10, 31, 14, 59), utc(2026, 10, 31, 15, 0)),
            (utc(2026, 11, 15, 14, 59), utc(2026, 11, 15, 15, 0)),
            (utc(2026, 12, 31, 14, 59), utc(2026, 12, 31, 15, 0)),
            # 同じ送り先に見えるほど長い中断でも、月が変われば確認し直す。
            (utc(2026, 11, 2, 1), utc(2026, 12, 2, 1)),
        ]
        for start, finish in cases:
            with self.subTest(start=start), patch('sys.stdout'), patch('sys.stderr'):
                self.assertEqual(push_ci.main([], clock=iter([start, finish]).__next__), 1)
                self.assertEqual([self.main_of(repo) for repo in (self.canonical, self.copy)], before)

    def test_final_clock_rechecks_quota_even_if_target_is_unchanged(self):
        self.commit('app.py', 'B')
        before = self.main_of(self.canonical)
        clock = iter([utc(2026, 11, 1, 0, 1), utc(2026, 10, 31, 23, 59)])
        with patch('sys.stdout'), patch('sys.stderr'):
            self.assertEqual(push_ci.main([], clock=clock.__next__), 1)
        self.assertEqual(self.main_of(self.canonical), before)

    def concurrent_change(self, repo, delete=False):
        """初回fetch後、最終照会までに別cloneから更新する（すべて一時ローカルGit）。"""
        other = self.work.parent / 'concurrent'
        git(self.work.parent, 'clone', '-q', str(repo), str(other))
        concurrent = self.commit('other.py', '別作業', cwd=other)
        self.commit('app.py', 'B')
        before_target = self.main_of(self.canonical)
        original = push_ci.remote_tip
        calls = 0

        def changing_tip(url):
            nonlocal calls
            calls += 1
            if calls == 3:
                if delete:
                    git(repo, 'update-ref', '-d', 'refs/heads/main')
                else:
                    git(other, 'push', '-q', str(repo), 'HEAD:refs/heads/main')
            return original(url)

        with patch.object(push_ci, 'remote_tip', side_effect=changing_tip):
            self.assertEqual(self.run_push(utc(2026, 11, 2, 1)), 1)
        if delete:
            self.assertEqual(git(self.work, 'ls-remote', str(repo), 'refs/heads/main'), '')
        else:
            self.assertEqual(self.main_of(repo), concurrent)
        if repo != self.canonical:
            self.assertEqual(self.main_of(self.canonical), before_target)

    def test_other_repository_update_after_fetch_stops(self):
        self.concurrent_change(self.copy)

    def test_target_repository_update_after_fetch_stops(self):
        self.concurrent_change(self.canonical)

    def test_other_repository_deleted_after_fetch_stops(self):
        self.concurrent_change(self.copy, delete=True)

    def test_final_lookup_failure_does_not_push(self):
        self.commit('app.py', 'B')
        before = self.main_of(self.canonical)
        original = push_ci.git
        calls = 0

        def failing_git(*args, **kwargs):
            nonlocal calls
            if args[0] == 'ls-remote':
                calls += 1
                if calls == 3:
                    raise SystemExit('最終照会の通信失敗')
            return original(*args, **kwargs)

        with patch.object(push_ci, 'git', side_effect=failing_git):
            with self.assertRaisesRegex(SystemExit, '最終照会'):
                self.run_push(utc(2026, 11, 2, 1))
        self.assertEqual(self.main_of(self.canonical), before)

    def test_dry_run_checks_final_period_without_pushing(self):
        self.commit('app.py', 'B')
        before = self.main_of(self.canonical)
        with patch('sys.stdout'), patch('sys.stderr'):
            self.assertEqual(push_ci.main(['--dry-run'], now=utc(2026, 11, 2, 1)), 0)
            clock = iter([utc(2026, 11, 15, 14, 59), utc(2026, 11, 15, 15)])
            self.assertEqual(push_ci.main(['--dry-run'], clock=clock.__next__), 1)
        self.assertEqual(self.main_of(self.canonical), before)


if __name__ == '__main__':
    unittest.main()
