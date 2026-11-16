"""幸町ノーマルの曜日傾向。採点や候補選択から独立した表示専用の情報。"""
from datetime import date, timedelta
import html
import re


# 分析を確定した日以降に作る翌日向け表示だけに使う。過去予測へ遡及しない。
AVAILABLE_FROM = '2026-10-17'
EVIDENCE = (
    '出典：保存データの分析（2026/10/17確定）。2,000〜20,000Gの台が対象です。'
    '機種・月の差を調整した勝ち台の割合は、土日が平日より低めでした。'
    '2025/10/16〜12/28の74日で6.1ポイント（週単位の再抽出による条件付き95%区間：3.9〜8.4ポイント）、'
    'あとから足した2025/12/29〜2026/2/28の62日でも6.4ポイント（3.8〜8.7ポイント）、'
    '2026/3/1〜3/26の26日でも8.0ポイント（4.0〜10.5ポイント）、'
    '2026/3/27〜6/15の80日でも5.4ポイント（3.2〜7.6ポイント）、'
    '2026/6/16〜7/31の46日でも5.1ポイント（2.4〜6.9ポイント）です。'
    '合算の設定位置でも同方向でした。'
    '2025/9〜2026/10の14か月すべてで同方向でしたが、部分月を含みます。'
    '打ち切り方に左右されない推定（台ごとの回転数・BB・RBから設定の配分を推定。確率表のある6機種、'
    '2025/9/15〜2026/11/12の47,506台日）では、土日祝の平均の合算確率は平日の0.994倍でした'
    '（週単位の再抽出による95%区間：0.989〜1.000倍）。'
    '上の勝ち台の割合の差の大部分は、土日に悪い台も長く打たれる影響とみられます。'
    '設定の差があっても約0.6%と小さく、あるともないとも言い切れません。'
    '曜日を加えた予測の改善は確認できていません。'
    '機種全体の過去傾向であり、この台の翌日の設定や勝率はわかりません。'
    '候補の点数・順位には反映していません。'
)


def normal_day_context(store, day, machines):
    """選択日の翌日を表示。machinesには選択店舗・選択日の機種だけを渡す。"""
    if store != 'saiwaichou' or not any(
            'ジャグラー' in m or 'ハナハナ' in m for m in machines):
        return None
    if not isinstance(day, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', day):
        return None
    try:
        selected = date.fromisoformat(day)
        target = selected + timedelta(days=1)
    except (ValueError, OverflowError):
        return None
    if day < AVAILABLE_FROM:
        return None
    weekend = target.weekday() >= 5
    label = f'{target.month}/{target.day}（{"月火水木金土日"[target.weekday()]}）'
    return dict(
        target_day=target.isoformat(), weekend=weekend,
        title=f'{label}の曜日傾向：{"土日" if weekend else "平日"}',
        body=('幸町のジャグラー・ハナハナ全体では、過去の土日は平日より低めでした。'
              if weekend else
              '幸町のジャグラー・ハナハナの土日低下傾向には該当しません。'
              '平日の好結果を保証するものではありません。'),
        evidence=EVIDENCE,
    )


def normal_day_context_html(store, day, machines):
    context = normal_day_context(store, day, machines)
    if context is None:
        return ''
    return (f'<aside class="dsub normal-day-context"><b>{html.escape(context["title"])}</b>'
            f'<p>{html.escape(context["body"])}</p>'
            f'<details><summary>曜日傾向の根拠と限界</summary>'
            f'<p>{html.escape(context["evidence"])}</p></details></aside>')
