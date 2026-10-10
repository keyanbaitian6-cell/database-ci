/// 取り込みの対象外の機種か（[isExcludedMachine]）。次の機種の候補にせず、印は「対象外」にし、
/// 表・グラフも保存しない。PC版 `core.is_excluded_machine` と同じ規則。
/// そのうち [isHiddenMachine] の機種は、以前に保存した記録も消さずに画面・閲覧ページに出さない
/// （`AppController` の一覧・`ViewerData.parse`）。PC版 `core.is_hidden_machine` と同じ規則。
///
/// 長町南店はジャグラーシリーズ、幸町店はブラックボードを公開していない
/// （幸町のジャグラー、長町南のスーパーブラックジャック等は対象のまま）。
/// 沖ドキ（サイトの表記は「沖ドキ」「オキドキ」の両方）は、両店とも利用者の
/// 指定で対象外（2026-09-29）。
/// 幸町の聖闘士星矢 海皇覚醒（1279番台の1台だけ）は、ずっと稼働停止のため利用者の指定で
/// 対象外（2026-10-11「取り込まない、表示しないようにしてほしい」）。
/// 長町南は機種名が半角カナのこともある（例「ｶﾊﾞﾈﾘ」「沖ﾄﾞｷ」）ので、半角の表記も
/// 見る（PC版は NFKC で全角にそろえてから同じ判定をしている）。空白は無視する。
library;

const excludedMachineWords = <String, List<String>>{
  'nagamachiminami': ['ジャグラー', 'ｼﾞｬｸﾞﾗｰ', ..._okidokiWords],
  'saiwaichou': ['ブラックボード', 'ﾌﾞﾗｯｸﾎﾞｰﾄﾞ', '聖闘士星矢海皇覚醒', ..._okidokiWords],
};

const _okidokiWords = ['沖ドキ', '沖ﾄﾞｷ', 'オキドキ', 'ｵｷﾄﾞｷ'];

/// 「対象外」の案内で使う呼び方。
const excludedMachineNotes = <String, String>{
  'nagamachiminami': '長町南店のジャグラーと沖ドキ',
  'saiwaichou': '幸町店のブラックボード・聖闘士星矢 海皇覚醒（稼働停止）と沖ドキ',
};

bool isExcludedMachine(String? store, String? name) {
  final words = excludedMachineWords[store] ?? const <String>[];
  final text = (name ?? '').replaceAll(RegExp(r'[\s　]+'), '');
  return words.any(text.contains);
}

/// 表示しない機種（取り込みの対象外のうち、以前に保存した記録も出さないもの）。沖ドキなど、
/// 対象外にする前に取り込んだ記録は今までどおり出す（利用者が外すよう頼んだのは1279番台だけ）。
const hiddenMachineWords = <String, List<String>>{
  'saiwaichou': ['聖闘士星矢海皇覚醒'],
};

bool isHiddenMachine(String? store, String? name) {
  final words = hiddenMachineWords[store] ?? const <String>[];
  final text = (name ?? '').replaceAll(RegExp(r'[\s　]+'), '');
  return words.any(text.contains);
}
