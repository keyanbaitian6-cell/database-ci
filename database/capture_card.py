"""取り込み窓の共通カード。サイト固有の読取り・ボタンの処理は含めない。"""
from pathlib import Path

CARD_JS = (Path(__file__).resolve().parent / 'assets' / 'capture_card.js').read_text(encoding='utf-8')
