import 'models.dart';

const dateEventOptions = <String>[
  '超探す楽しみ',
  '半列',
  '4台構成',
  'バラエティ',
  '華の日',
];

/// 日付イベントは台データとは独立して、店舗と日付の組で保存する。
class DateEvent {
  const DateEvent({
    required this.store,
    required this.day,
    required this.name,
  });

  final String store;
  final String day;
  final String name;

  String get key => '$store|$day';

  Map<String, dynamic> toJson() => {
    'store': store,
    'day': day,
    'name': name,
  };

  static DateEvent? tryFromJson(Object? raw) {
    if (raw is! Map) return null;
    final store = raw['store'];
    final day = raw['day'];
    final name = raw['name'];
    if (store is! String ||
        !storeNames.containsKey(store) ||
        day is! String ||
        !isValidRecordDay(day) ||
        name is! String ||
        name.trim().isEmpty ||
        name.trim().length > 60) {
      return null;
    }
    return DateEvent(store: store as String, day: day as String, name: name.trim());
  }
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
