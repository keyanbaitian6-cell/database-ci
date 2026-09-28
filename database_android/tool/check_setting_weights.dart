// Independent Python audit passes synthetic cases on stdin. No saved data writes.
import 'dart:convert';
import 'dart:io';

import 'package:database_android/models.dart';
import 'package:database_android/setting_estimate.dart';

Future<void> main() async {
  final cases = jsonDecode(await stdin.transform(utf8.decoder).join()) as List;
  stdout.write(
    jsonEncode([
      for (final value in cases)
        () {
          final r = value as Map;
          final e = estimateSetting(
            SlotRecord(
              store: 'saiwaichou',
              day: '2026-09-29',
              rack: 1,
              machine: r['machine'] as String,
              games: r['games'] as int,
              bb: r['bb'] as int,
              rb: r['rb'] as int,
            ),
          );
          return e == null
              ? null
              : {
                  'weights': {
                    for (final fit in e.ranked) fit.setting: fit.weight,
                  },
                  'pair': e.topTwo.map((fit) => fit.setting).toList(),
                  'outside': e.outsideWeight,
                };
        }(),
    ]),
  );
}
