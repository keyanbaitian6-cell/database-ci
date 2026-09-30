import 'dart:convert';
import 'dart:io';

import 'package:database_android/data_checks.dart';
import 'package:database_android/list_views.dart';
import 'package:database_android/models.dart';
import 'package:database_android/next_day_backtest.dart';
import 'package:database_android/scoring.dart';

/// Read-only parity dump, no fitting or performance evaluation. Never publish
/// the input or rack-level output. The existing PC parity tool reads this file.
void main(List<String> args) {
  if (args.length != 2) throw ArgumentError('入力JSONとリポジトリ外の出力JSONを指定してください');
  final root = File.fromUri(Platform.script).parent.parent.parent
      .resolveSymbolicLinksSync();
  final out = File(args[1]).absolute;
  final parent = out.parent.resolveSymbolicLinksSync();
  if (parent.toLowerCase() == root.toLowerCase() ||
      parent.toLowerCase().startsWith(
        '${root.toLowerCase()}${Platform.pathSeparator}',
      )) {
    throw ArgumentError('実データの出力はリポジトリの外にしてください');
  }
  final doc = jsonDecode(File(args[0]).readAsStringSync()) as Map;
  if (doc['format'] != 'database-backup' ||
      (doc['recovery_required'] ?? 0) != 0) {
    throw const FormatException('通常のバックアップが必要です');
  }
  final full = normalizeForBacktest([
    for (final r in doc['records'] as List)
      if (r is Map && !r.containsKey('unreadable_record'))
        SlotRecord.fromJson(Map<String, dynamic>.from(r)),
  ]);
  final groups = {for (final r in full) (r.store, r.day)};
  final watch = Stopwatch()..start();
  var focus = 0, highExcluded = 0, regular = 0, variety = 0;
  final output = <Map<String, Object?>>[];
  for (final (store, day) in groups) {
    final picks = dayCandidates(
      full.where((r) => r.store == store && r.day == day).toList(),
      full,
    ).candidates;
    for (final c in picks) {
      final isFocus = candidateIsFocus(c, full);
      if (c.variety) {
        variety++;
      } else {
        regular++;
        final score = scoreRecord(c.record, full).total;
        if (isFocus) focus++;
        if (score != null && score >= 88) {
          highExcluded++;
          if (isFocus) throw StateError('88点以上が★注目に入っています');
        }
      }
      output.add({
        'store': store,
        'day': day,
        'machine': c.record.machine,
        'rack': c.record.rack,
        'index': c.index,
        'days': c.days,
        'focus': isFocus,
      });
    }
  }
  out.writeAsStringSync(jsonEncode(output));
  stdout.writeln(
    'stores/dates=${groups.length}, regular=$regular, focus=$focus, '
    'score88Excluded=$highExcluded, variety=$variety, elapsedMs=${watch.elapsedMilliseconds}',
  );
}
