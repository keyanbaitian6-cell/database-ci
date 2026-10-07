import 'models.dart';

const dateEventOptions = <String>[
  '超探す楽しみ',
  '半列',
  '4台構成',
  'バラエティ',
  '華の日',
];

/// 日付イベントは台データとは独立して、店舗と日付の組で保存する。
///
/// イベントカレンダー（`EVENT_CALENDAR.md`、2026-10-07）：[updatedAt] は入力・変更・
/// 消した時刻（時差つき）。[name] が空なら「イベントを消した」印で、画面には出さないが
/// バックアップと統合のために残す。2026-10-07より前のイベントには時刻が無い。
class DateEvent {
  const DateEvent({
    required this.store,
    required this.day,
    required this.name,
    this.updatedAt,
  });

  final String store;
  final String day;
  final String name;
  final String? updatedAt;

  String get key => '$store|$day';

  /// 「イベントを消した」印。
  bool get removed => name.isEmpty;

  /// その日の02:00（日本時間、前の営業日の終わり）より前に入力したもの。
  /// 時刻の無いイベントは含めない（PC `core.date_event_in_advance` と同じ）。
  bool get enteredInAdvance {
    final at = eventTime(updatedAt);
    if (at == null) return false;
    final d = DateTime.parse(day);
    return at.isBefore(
      DateTime.utc(d.year, d.month, d.day, eventDayStartHour - 9),
    );
  }

  Map<String, dynamic> toJson() => {
    'store': store,
    'day': day,
    'name': removed ? null : name,
    'updated_at': ?updatedAt,
  };

  static DateEvent? tryFromJson(Object? raw) {
    if (raw is! Map) return null;
    final store = raw['store'];
    final day = raw['day'];
    final name = raw['name'];
    final updatedAt = raw['updated_at'];
    if (store is! String ||
        !storeNames.containsKey(store) ||
        day is! String ||
        !isValidRecordDay(day) ||
        (raw.containsKey('updated_at') && eventTime(updatedAt) == null)) {
      return null;
    }
    if (name == null) {
      // 消した印は、入力時刻のあるものだけ。
      return updatedAt is String
          ? DateEvent(store: store, day: day, name: '', updatedAt: updatedAt)
          : null;
    }
    if (name is! String ||
        name.trim().isEmpty ||
        name.trim().length > eventNameMax) {
      return null;
    }
    return DateEvent(
      store: store,
      day: day,
      name: name.trim(),
      updatedAt: updatedAt as String?,
    );
  }
}

/// イベント名の最大文字数（PC `_valid_date_event` と同じ）。
const eventNameMax = 60;

/// 営業日は日本時間の午前2時で切り替わる（`businessDayCutoffHour` と同じ）。
const eventDayStartHour = 2;

final _zoned = RegExp(r'(Z|[+-]\d{2}:?\d{2})$');

/// 時差つきの時刻だけを読む（無い・読めない・時差なしは null）。
DateTime? eventTime(Object? value) {
  if (value is! String || !_zoned.hasMatch(value)) return null;
  return DateTime.tryParse(value)?.toUtc();
}

/// 入力した時刻（時差つき）。同じ店舗・日付の前の時刻 [previous] より必ず後にする。
String eventStamp(DateTime now, String? previous) {
  var at = now.toUtc();
  final before = eventTime(previous);
  if (before != null && !at.isAfter(before)) {
    at = before.add(const Duration(milliseconds: 1));
  }
  return at.toIso8601String();
}

/// 同じ店舗・日付は、両方に時刻があれば新しい方（同じなら [incoming]）、片方だけなら
/// 時刻のある方、どちらにも無ければ [stored] を残す（名前が違えば不一致）。消した印も
/// 同じ規則（PC `core.merge_date_events` と同じ）。
({Map<String, DateEvent> events, int changed, int conflicts}) mergeDateEvents(
  Map<String, DateEvent> stored,
  Iterable<DateEvent> incoming,
) {
  final events = Map.of(stored);
  var changed = 0, conflicts = 0;
  for (final event in incoming) {
    final old = events[event.key];
    bool take;
    if (old == null) {
      take = true;
    } else {
      final newAt = eventTime(event.updatedAt);
      final oldAt = eventTime(old.updatedAt);
      if (newAt != null && oldAt != null) {
        take = !newAt.isBefore(oldAt);
      } else if (newAt != null || oldAt != null) {
        take = newAt != null;
      } else {
        take = false;
        if (old.name != event.name) conflicts++;
      }
    }
    if (take &&
        (old == null ||
            old.name != event.name ||
            old.updatedAt != event.updatedAt)) {
      events[event.key] = event;
      changed++;
    }
  }
  return (events: events, changed: changed, conflicts: conflicts);
}

/// 入力欄のプルダウン：既定の候補、次に今付いている名前（新しい日の順）。
List<String> dateEventNames(Iterable<DateEvent> events, {String? store}) {
  final used = [
    for (final e in events)
      if (!e.removed && (store == null || e.store == store)) e,
  ]..sort((a, b) => b.day.compareTo(a.day));
  return {...dateEventOptions, for (final e in used) e.name}.toList();
}

/// 利用者が指定した、長町南店の既存イベント。
const initialDateEvents = <DateEvent>[
  DateEvent(store: 'nagamachiminami', day: '2026-09-14', name: '4台構成'),
  DateEvent(store: 'nagamachiminami', day: '2026-09-15', name: '4台構成'),
  DateEvent(store: 'nagamachiminami', day: '2026-09-16', name: '4台構成'),
  DateEvent(store: 'nagamachiminami', day: '2026-09-17', name: '4台構成'),
  DateEvent(store: 'nagamachiminami', day: '2026-09-18', name: '4台構成'),
  DateEvent(store: 'nagamachiminami', day: '2026-09-19', name: '4台構成'),
  DateEvent(store: 'nagamachiminami', day: '2026-09-20', name: '4台構成'),
  DateEvent(store: 'nagamachiminami', day: '2026-09-21', name: '超探す楽しみ'),
  DateEvent(store: 'nagamachiminami', day: '2026-09-22', name: '超探す楽しみ'),
  DateEvent(store: 'nagamachiminami', day: '2026-09-23', name: '超探す楽しみ'),
  DateEvent(store: 'nagamachiminami', day: '2026-09-24', name: '超探す楽しみ'),
  DateEvent(store: 'nagamachiminami', day: '2026-09-25', name: '超探す楽しみ'),
  DateEvent(store: 'nagamachiminami', day: '2026-09-26', name: '超探す楽しみ'),
  DateEvent(store: 'nagamachiminami', day: '2026-09-27', name: '超探す楽しみ'),
];
