import 'dart:math' as math;

import 'models.dart';

/// Manufacturer BB/RB tables. The method and primary sources are documented in
/// ../SETTING_ESTIMATION.md. This does not use or alter confirmedSetting/score.
class _Spec {
  const _Spec(this.name, this.source, this.bb, this.rb, this.settings);
  final String name;
  final String source;
  final List<double> bb;
  final List<double> rb;
  final List<String> settings;
}

const _six = ['1', '2', '3', '4', '5', '6'];
const _specs = <String, _Spec>{
  'my_juggler_v': _Spec(
    'マイジャグラーⅤ',
    'https://www.kitadenshi.co.jp/slot/myjuggler5/',
    [273.1, 270.8, 266.4, 254.0, 240.1, 229.1],
    [409.6, 385.5, 336.1, 290.0, 268.6, 229.1],
    _six,
  ),
  'neo_im_juggler': _Spec(
    'ネオアイムジャグラーEX',
    'https://www.kitadenshi.co.jp/slot/neoimjugglerex/',
    [273.1, 269.7, 269.7, 259.0, 259.0, 255.0],
    [439.8, 399.6, 331.0, 315.1, 255.0, 255.0],
    _six,
  ),
  'houou_tensho': _Spec(
    'ハナハナホウオウ〜天翔〜',
    'https://www.slot-pioneer.co.jp/product/hanahana_houoh_tensho/',
    [297, 284, 273, 262, 249, 236],
    [496, 458, 425, 397, 366, 337],
    _six,
  ),
  'new_king_v': _Spec(
    'ニューキングハナハナV',
    'https://www.slot-pioneer.co.jp/product/new_king_hanahana_v/pop/pop_pdf.pdf',
    [299, 291, 281, 268, 253],
    [496, 471, 442, 409, 372],
    ['1', '2', '3', '4', 'V'],
  ),
  'king_2023': _Spec(
    'キングハナハナ-30 (2023)',
    'https://www.slot-pioneer.co.jp/product/king_hanahana2023/pop/pop_pdf.pdf',
    [292, 280, 268, 257, 244, 232],
    [489, 452, 420, 390, 360, 332],
    _six,
  ),
  'dragon_senko': _Spec(
    'ドラゴンハナハナ〜閃光〜',
    'https://www.slot-pioneer.co.jp/product/dragon_hanahana_senko/pop/pop_pdf.pdf',
    [256, 246, 235, 224, 212, 199],
    [642, 585, 537, 489, 442, 399],
    _six,
  ),
};

/// 半角カナ（濁点・半濁点付きを含む）を全角カナにそろえる。
/// サイトの機種名は全角・半角が混ざるため、照合や検索の前に使う。
String foldHalfWidthKana(String text) {
  var name = text;
  const voiced = <String, String>{
    'ｶﾞ': 'ガ',
    'ｷﾞ': 'ギ',
    'ｸﾞ': 'グ',
    'ｹﾞ': 'ゲ',
    'ｺﾞ': 'ゴ',
    'ｻﾞ': 'ザ',
    'ｼﾞ': 'ジ',
    'ｽﾞ': 'ズ',
    'ｾﾞ': 'ゼ',
    'ｿﾞ': 'ゾ',
    'ﾀﾞ': 'ダ',
    'ﾁﾞ': 'ヂ',
    'ﾂﾞ': 'ヅ',
    'ﾃﾞ': 'デ',
    'ﾄﾞ': 'ド',
    'ﾊﾞ': 'バ',
    'ﾋﾞ': 'ビ',
    'ﾌﾞ': 'ブ',
    'ﾍﾞ': 'ベ',
    'ﾎﾞ': 'ボ',
    'ﾊﾟ': 'パ',
    'ﾋﾟ': 'ピ',
    'ﾌﾟ': 'プ',
    'ﾍﾟ': 'ペ',
    'ﾎﾟ': 'ポ',
  };
  for (final entry in voiced.entries) {
    name = name.replaceAll(entry.key, entry.value);
  }
  const half = 'ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓﾔﾕﾖﾗﾘﾙﾚﾛﾜｦﾝｧｨｩｪｫｬｭｮｯｰ';
  const full = 'アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲンァィゥェォャュョッー';
  for (var i = 0; i < half.length; i++) {
    name = name.replaceAll(half[i], full[i]);
  }
  return name;
}

String? settingModelForMachine(String machine) {
  var name = machine.toUpperCase().replaceAll(RegExp(r'[\s\-−‐‑–—~〜～_・]+'), '');
  // The site mixes full-width/half-width katakana and Roman numerals.
  name = foldHalfWidthKana(name);
  name = name.replaceAll('Ⅴ', 'V').replaceAll('Ⅵ', 'VI').replaceAll('ｖ', 'V');
  if (name == 'SマイジャグラーVKD') {
    return 'my_juggler_v';
  }
  if (name == 'SネオアイムジャグラーEXKK') {
    return 'neo_im_juggler';
  }
  if (name == 'Sハナハナホウオウ天翔EX30') {
    return 'houou_tensho';
  }
  if (name == 'SBニューキングハナハナVPA30') {
    return 'new_king_v';
  }
  if (name == 'SキングハナハナSP30') {
    return 'king_2023';
  }
  if (name == 'Sドラゴンハナハナ閃光SP30') {
    return 'dragon_senko';
  }
  return null;
}

class SettingEstimate {
  const SettingEstimate(
    this.model,
    this.source,
    this.setting,
    this.support,
    this.range80,
    this.settingCount,
  );
  final String model;
  final String source;
  final String setting;
  final double support;
  final List<String> range80;
  final int settingCount;

  String get shortLabel => range80.length == settingCount
      ? 'BB/RBでは絞り込めず'
      : 'BB/RB候補 ${range80.join('・')}';
  String get detailLabel =>
      'モデル内中央80%候補範囲 ${range80.join('・')}／最多適合 $setting（均等仮定のモデル内相対重み ${support.toStringAsFixed(1)}%）';
}

SettingEstimate? estimateSetting(SlotRecord row) {
  if (hasImplausibleNumbers(row)) return null;
  final key = settingModelForMachine(row.machine);
  final spec = key == null ? null : _specs[key];
  if (spec == null ||
      row.games <= 0 ||
      row.bb < 0 ||
      row.rb < 0 ||
      row.bb + row.rb > row.games) {
    return null;
  }
  final logs = <double>[];
  for (var i = 0; i < spec.settings.length; i++) {
    final pBB = 1 / spec.bb[i];
    final pRB = 1 / spec.rb[i];
    logs.add(
      row.bb * math.log(pBB) +
          row.rb * math.log(pRB) +
          (row.games - row.bb - row.rb) * math.log(1 - pBB - pRB),
    );
  }
  final peak = logs.reduce(math.max);
  final raw = logs.map((x) => math.exp(x - peak)).toList();
  final total = raw.reduce((a, b) => a + b);
  final weights = raw.map((x) => x / total).toList();
  final ranked = List<int>.generate(spec.settings.length, (i) => i)
    ..sort((a, b) {
      final comparison = weights[b].compareTo(weights[a]);
      return comparison != 0 ? comparison : a.compareTo(b);
    });
  // Equal tails avoid arbitrarily excluding a near-tied setting at low G.
  var cumulative = 0.0;
  var lower = 0;
  var upper = spec.settings.length - 1;
  var foundLower = false;
  for (var i = 0; i < weights.length; i++) {
    cumulative += weights[i];
    if (!foundLower && cumulative >= 0.1) {
      lower = i;
      foundLower = true;
    }
    if (cumulative >= 0.9) {
      upper = i;
      break;
    }
  }
  final best = ranked.first;
  return SettingEstimate(
    spec.name,
    spec.source,
    spec.settings[best],
    (weights[best] * 1000).round() / 10,
    spec.settings.sublist(lower, upper + 1),
    spec.settings.length,
  );
}
