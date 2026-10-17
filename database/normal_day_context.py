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
    '2026/3/1〜3/26の26日でも8.0ポイント（4.0〜10.5ポイント）です。'
    '合算の設定位置でも同方向でした。'
    '2025/9〜2026/3・2026/8〜10の10か月でも同方向でしたが、部分月を含みます。'
    '土日に設定が低いのか、混雑で長く打たれる台が増えるためかは、閉店後の数値だけではわかりません。'
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
