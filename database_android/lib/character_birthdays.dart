import 'dart:convert';

import 'package:flutter/services.dart';

/// キャラ誕生日（EVENT_CALENDAR.md「キャラ誕生日」、PC `event_calendar.load_character_birthdays` と同じ規則）。
/// イベントとは別データとして読み込み、毎年の月日で表示する。
class CharacterBirthday {
  const CharacterBirthday(this.name, this.work);

  final String name, work;

  @override
  bool operator ==(Object other) =>
      other is CharacterBirthday && other.name == name && other.work == work;

  @override
  int get hashCode => Object.hash(name, work);
}

/// 一覧に出す「名前（作品）」。[note] は作品の後ろに「、」で足す（2/29生まれなど）。
String characterBirthdayLabel(String name, String work, [String note = '']) {
  final inside = [work, note].where((part) => part.isNotEmpty).join('、');
  return inside.isEmpty ? name : '$name（$inside）';
}

String characterBirthdayKey(int month, int day) =>
    '${month.toString().padLeft(2, '0')}-${day.toString().padLeft(2, '0')}';

/// 誕生日一覧のJSONを月日（mm-dd）ごとに読む。値は名前順で、同じ名前・作品は1つ。
/// 形が違う項目・実在しない月日は飛ばす。全体の形が違うときは [FormatException]。
Map<String, List<CharacterBirthday>> parseCharacterBirthdays(String source) {
  final decoded = jsonDecode(source);
  if (decoded is! Map || decoded['entries'] is! List) {
    throw const FormatException('キャラクター誕生日一覧の形式が不正です。');
  }
  final found = <String, Set<CharacterBirthday>>{};
  for (final raw in decoded['entries'] as List) {
    if (raw is! Map) continue;
    final month = raw['month'], day = raw['day'], name = raw['name'];
    if (month is! int || day is! int || name is! String) continue;
    // 実在する月日だけ（うるう年の2024年で確かめるので2/29も入る）。
    final date = DateTime.utc(2024, month, day);
    if (date.month != month || date.day != day) continue;
    final trimmed = name.trim();
    if (trimmed.isEmpty) continue;
    final work = raw['work'] is String ? (raw['work'] as String).trim() : '';
    (found[characterBirthdayKey(month, day)] ??= {}).add(
      CharacterBirthday(trimmed, work),
    );
  }
  return {
    for (final MapEntry(:key, :value) in found.entries)
      key: value.toList()
        ..sort(
          (a, b) => a.name != b.name
              ? a.name.compareTo(b.name)
              : a.work.compareTo(b.work),
        ),
  };
}

/// アセットの誕生日一覧。50KBを超える文字列は [AssetBundle.loadString] が別の isolate で
/// 読むので、バイト列で受け取ってここで文字にする（試験でも読み込みが終わるように）。
Future<Map<String, List<CharacterBirthday>>> loadCharacterBirthdays() async {
  final data = await rootBundle.load('assets/character_birthdays.json');
  return parseCharacterBirthdays(
    utf8.decode(
      data.buffer.asUint8List(data.offsetInBytes, data.lengthInBytes),
    ),
  );
}

/// その日のキャラ誕生日（名前と「名前（作品）」）。うるう年でない年は、2/29生まれを3/1に
/// 「名前（作品、2/29生まれ）」で出す（2026-10-18 利用者指定）。
List<({String name, String label})> characterBirthdaysOn(
  Map<String, List<CharacterBirthday>> birthdays,
  DateTime date,
) {
  final shown = [
    for (final b
        in birthdays[characterBirthdayKey(date.month, date.day)] ??
            const <CharacterBirthday>[])
      (name: b.name, label: characterBirthdayLabel(b.name, b.work)),
  ];
  final leapYear = DateTime.utc(date.year, 2, 29).month == 2;
  if (date.month == 3 && date.day == 1 && !leapYear) {
    for (final b
        in birthdays[characterBirthdayKey(2, 29)] ??
            const <CharacterBirthday>[]) {
      shown.add((
        name: b.name,
        label: characterBirthdayLabel(b.name, b.work, '2/29生まれ'),
      ));
    }
  }
  return shown;
}

String characterBirthdayCellLabel(List<String> names) {
  if (names.isEmpty) return '';
  final shown = names.take(2).join('・');
  final more = names.length > 2 ? ' ほか${names.length - 2}名' : '';
  return '🎂 $shown$more';
}
