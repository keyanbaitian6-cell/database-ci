"""Reproducible model checks, not a real-world setting accuracy claim.

Requires numpy (developer tool only). Reads official tables from the existing
PC implementation, cross-checks Dart on a synthetic grid, then samples exact
multinomial counts with equal numbers of each true setting. No user records,
training labels, tuned priors, or application-state writes are used.
Run from database_android: python tool/audit_setting_top_two.py --dart <dart.exe>
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'database'))
from setting_estimate import SPECS, MACHINE_SIGNATURES  # noqa: E402


def probabilities(spec):
    return np.array([[1 / b, 1 / r, 1 - 1 / b - 1 / r] for _, b, r in spec])


def weights(counts, probs, mode='joint'):
    if mode == 'joint':
        logs = counts @ np.log(probs).T
    else:
        g = counts.sum(axis=1)[:, None]
        index = {'bb': 0, 'rb': 1}.get(mode)
        hits = counts[:, index:index + 1] if index is not None else counts[:, :2].sum(axis=1)[:, None]
        p = probs[:, index] if index is not None else probs[:, :2].sum(axis=1)
        logs = hits * np.log(p) + (g - hits) * np.log1p(-p)
    raw = np.exp(logs - logs.max(axis=1)[:, None])
    return raw / raw.sum(axis=1)[:, None]


def pair(w):
    return np.argsort(-w, axis=1, kind='stable')[:, :2]


def check_dart(executable):
    cases, expected = [], []
    for machine, key in MACHINE_SIGNATURES.items():
        spec = SPECS[key][2]
        p = probabilities(spec)
        for g in [1, 100, 500, 501, 3000, 8000, 10000, 20000]:
            for b, r in [(0, 0), (1, 0), (0, 1), (min(g, 20), 0),
                         (min(g // 2, 44), min(g // 2, 43)),
                         (g // 260, g // 400), (g // 240, g // 250)]:
                cases.append(dict(machine=machine, games=g, bb=b, rb=r))
                w = weights(np.array([[b, r, g-b-r]]), p)[0]
                expected.append((spec, w))
    result = subprocess.run([executable, 'run', 'tool/check_setting_weights.dart'],
                            input=json.dumps(cases), text=True, capture_output=True,
                            cwd=ROOT / 'database_android', check=True)
    actual = json.loads(result.stdout)
    assert len(actual) == len(expected)
    for a, (spec, w) in zip(actual, expected):
        np.testing.assert_allclose([a['weights'][s] for s, _, _ in spec], w, atol=1e-10, rtol=0)
        chosen = [spec[i][0] for i in pair(w[None, :])[0]]
        assert a['pair'] == chosen, (a, chosen)
        assert abs(sum(a['weights'][s] for s in a['pair']) + a['outside'] - 1) < 1e-12
    print(f'Dart / independent Python parity: {len(cases)} cases passed')


def simulate(samples):
    rng = np.random.default_rng(20260929)
    print('Synthetic multinomial, equal true-setting frequencies. NOT observed accuracy.')
    print('model,G,joint_top2,rb_only_top2,bb_only_top2,combined_top2,mean_pair_weight,coverage_by_setting')
    for key, (_, _, spec) in SPECS.items():
        p = probabilities(spec)
        for g in [500, 1000, 3000, 5000, 8000]:
            sums = {mode: [] for mode in ['joint', 'rb', 'bb', 'combined']}
            calibration = []
            for true in range(len(spec)):
                counts = rng.multinomial(g, p[true], size=samples)
                for mode in sums:
                    w = weights(counts, p, mode)
                    selected = pair(w)
                    sums[mode].append(np.mean((selected == true).any(axis=1)))
                    if mode == 'joint':
                        calibration.append(np.take_along_axis(w, selected, axis=1).sum(axis=1).mean())
            print(','.join([key, str(g)] + [f'{np.mean(v)*100:.2f}' for v in sums.values()]
                           + [f'{np.mean(calibration)*100:.2f}',
                              '/'.join(f'{v*100:.1f}' for v in sums['joint'])]))
    print(f'{samples} trials per model/G/true setting; seed 20260929')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dart', required=True)
    parser.add_argument('--samples', type=int, default=20000)
    args = parser.parse_args()
    check_dart(args.dart)
    simulate(args.samples)
