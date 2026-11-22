import 'package:database_android/date_events.dart';
import 'package:database_android/pscube_viewer_data.dart';
import 'package:flutter_test/flutter_test.dart';

/// イベント名の60文字は、PC（Python の len）と同じく1字ずつ数える（2026-11-22、Codexの点検 #12）。
/// 以前は Dart の String.length（UTF-16）で数え、PCで通る「59字＋🌈」を、Android・閲覧ページが拒んでいた。
void main() {
  final sixty = '漢' * 59 + '🌈';
  final sixtyOne = '漢' * 60 + '🌈';

  test('メルヘンのイベント（端末・バックアップ・共有から読む形）', () {
    DateEvent? read(String name) => DateEvent.tryFromJson({
      'store': 'saiwaichou',
      'day': '2026-11-20',
      'name': name,
      'updated_at': '2026-11-20T12:00:00+09:00',
    });
    expect(sixty.length, 61, reason: 'UTF-16 では61');
    expect(read(sixty)?.name, sixty);
    expect(read(sixtyOne), isNull);
  });

  test('P’s CUBE のイベント名', () {
    expect(cleanPscubeEventName(sixty), sixty);
    expect(() => cleanPscubeEventName(sixtyOne), throwsA(anything));
  });
}
