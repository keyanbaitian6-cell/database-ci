import assert from 'node:assert/strict';
import {mkdtemp, mkdir, copyFile, writeFile, readFile, rm, access} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import test from 'node:test';

const shellPath = value => value.replaceAll('\\', '/');

for (const failing of [true, false]) {
  test(`pre-build gate ${failing ? 'prints the failed test log and fails' : 'keeps passing local checks successful'}`, async t => {
    const root = await mkdtemp(path.join(tmpdir(), 'gate-log-test-'));
    t.after(() => rm(root, {recursive: true, force: true}));
    const tool = path.join(root, 'database_android', 'tool');
    await mkdir(tool, {recursive: true});
    await mkdir(path.join(root, 'database', 'tests'), {recursive: true});
    await copyFile(new URL('./check_before_build.sh', import.meta.url), path.join(tool, 'check_before_build.sh'));
    await writeFile(path.join(tool, 'dev_env.sh'), ': "${PYTHON:=python3}"\n: "${NODE:=node}"\nexport PYTHON NODE\n');
    const smoke = 'import unittest\nclass FixtureSmoke(unittest.TestCase):\n    def test_fixture(self): pass\n';
    await writeFile(path.join(root, 'database', 'test_smoke.py'), smoke);
    await writeFile(path.join(root, 'database', 'tests', 'test_event_calendar.py'), smoke);
    await writeFile(path.join(tool, 'stage_share_viewer.py'), '# No data to stage in this fixture.\n');
    await writeFile(path.join(tool, 'test_probe.mjs'),
      `console.log('REGRESSION_LOG_DETAIL'); process.exitCode = ${failing ? 9 : 0};\n`);
    const work = path.join(root, 'gate-work');
    const environment = {...process.env, NODE: shellPath(process.execPath), CHECK_BUILD_WORK: shellPath(work)};
    if (environment.PYTHON) environment.PYTHON = shellPath(environment.PYTHON);
    // The fixture starts its own Node test process through the real gate.
    delete environment.NODE_TEST_CONTEXT;
    const result = spawnSync('bash', [shellPath(path.join(tool, 'check_before_build.sh')), '--local'], {
      cwd: root,
      env: environment,
      encoding: 'utf8', timeout: 30000,
    });
    assert.ifError(result.error);
    const output = result.stdout + result.stderr;
    const pythonLog = await readFile(path.join(work, 'pc-tests.log'), 'utf8');
    assert.equal(result.status, failing ? 1 : 0, output + pythonLog);
    assert.match(await readFile(path.join(work, 'test_probe.log'), 'utf8'), /REGRESSION_LOG_DETAIL/);
    if (failing) {
      assert.match(output, /FAIL\s+test_probe/);
      assert.match(output, /REGRESSION_LOG_DETAIL/, 'CI must show the error without access to the runner filesystem');
      assert.doesNotMatch(output, /LOCAL CHECKS PASSED|ALL PASSED/);
    } else {
      assert.match(output, /LOCAL CHECKS PASSED/);
      assert.doesNotMatch(output, /FAIL\s+test_probe/);
    }
  });
}

test('pre-build gate stops before tests when Flutter is unavailable', async t => {
  const root = await mkdtemp(path.join(tmpdir(), 'gate-preflight-test-'));
  t.after(() => rm(root, {recursive: true, force: true}));
  const tool = path.join(root, 'database_android', 'tool');
  await mkdir(tool, {recursive: true});
  await copyFile(new URL('./check_before_build.sh', import.meta.url), path.join(tool, 'check_before_build.sh'));
  // ホストにSDKが入っていても、SDKを見つけられない端末を再現する。
  await writeFile(path.join(tool, 'dev_env.sh'),
    'command() { if [ "$1" = -v ] && [ "$2" = flutter ]; then return 1; fi; builtin command "$@"; }\n');
  const work = path.join(root, 'gate-work');
  const result = spawnSync('bash', [shellPath(path.join(tool, 'check_before_build.sh'))], {
    cwd: root, env: {...process.env, CHECK_BUILD_WORK: shellPath(work)}, encoding: 'utf8', timeout: 10000,
  });
  assert.ifError(result.error);
  assert.equal(result.status, 1, result.stdout + result.stderr);
  assert.match(result.stderr, /Flutterが見つかりません.*FLUTTER_ROOT/);
  assert.doesNotMatch(result.stdout, /ALL PASSED|OK\s+pc-tests/);
  await assert.rejects(access(work), {code: 'ENOENT'});
});
