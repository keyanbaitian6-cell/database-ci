import 'models.dart';

/// ノーマルタイプ（Aタイプ）の系列。過去の記録を系列でまとめて見るために使う。
///
/// 機種名だけで判定する。設定推測（setting_estimate.dart）が対応している機種は
/// この一部で、対応外の機種もここには入る（例：新台や名称の違うハナハナ）。
enum NormalSeries {
  juggler('ジャグラーシリーズ', ['ジャグラー', 'ｼﾞｬｸﾞﾗｰ']),
  hanahana('ハナハナシリーズ', ['ハナハナ', 'ﾊﾅﾊﾅ']);

  const NormalSeries(this.label, this.words);

  /// 画面に出す名前。
  final String label;

  /// 機種名に含まれていれば、その系列とみなす言葉。長町南の一覧は半角カナの
  /// ことがあるので、全角・半角の両方を見る（PC版はNFKCでそろえてから判定）。
  final List<String> words;
}

/// [machine] がノーマルタイプの系列なら、その系列。違えば null。
NormalSeries? normalSeriesOf(String? machine) {
  final name = machine ?? '';
  for (final series in NormalSeries.values) {
    if (series.words.any(name.contains)) return series;
  }
  return null;
}

/// [series] に合う記録だけを返す。[series] が null なら全部そのまま返す。
List<SlotRecord> recordsOfSeries(
  Iterable<SlotRecord> records,
  NormalSeries? series,
) => [
  for (final record in records)
    if (series == null || normalSeriesOf(record.machine) == series) record,
];

/// ノーマルタイプ（ジャグラー・ハナハナのどちらか）の記録だけを返す。
List<SlotRecord> normalTypeRecords(Iterable<SlotRecord> records) => [
  for (final record in records)
    if (normalSeriesOf(record.machine) != null) record,
];
