import 'dart:io';

import 'package:image/image.dart' as img;

/// Mechanical launcher/PWA size generation from the approved master artwork.
/// dart --packages=.dart_tool/package_config.json tool/generate_app_icons.dart
/// Add --check to verify assets without changing any files.
void main(List<String> args) {
  final root = File.fromUri(Platform.script).parent.parent;
  final master = File('${root.path}/design/app_icon/panda_master.png');
  final source = img.decodePng(master.readAsBytesSync());
  if (source == null || source.width != source.height || source.width < 512) {
    throw StateError('Master must be a square PNG at least 512 pixels wide');
  }
  final targets = <String, int>{
    'android/app/src/main/res/mipmap-mdpi/ic_launcher.png': 48,
    'android/app/src/main/res/mipmap-hdpi/ic_launcher.png': 72,
    'android/app/src/main/res/mipmap-xhdpi/ic_launcher.png': 96,
    'android/app/src/main/res/mipmap-xxhdpi/ic_launcher.png': 144,
    'android/app/src/main/res/mipmap-xxxhdpi/ic_launcher.png': 192,
    'web/favicon.png': 32,
    'web/icons/Icon-180.png': 180,
    'web/icons/Icon-192.png': 192,
    'web/icons/Icon-512.png': 512,
    'web/icons/Icon-maskable-192.png': 192,
    'web/icons/Icon-maskable-512.png': 512,
  };
  final check = args.contains('--check');
  for (final target in targets.entries) {
    final bytes = img.encodePng(
      img.copyResize(
        source,
        width: target.value,
        height: target.value,
        interpolation: img.Interpolation.average,
      ),
    );
    final output = File('${root.path}/${target.key}');
    if (check) {
      final actual = output.readAsBytesSync();
      if (actual.length != bytes.length ||
          Iterable<int>.generate(bytes.length)
              .any((i) => actual[i] != bytes[i])) {
        throw StateError('Icon differs from master: ${target.key}');
      }
    } else {
      output.parent.createSync(recursive: true);
      output.writeAsBytesSync(bytes);
    }
    stdout.writeln(
      '${check ? 'Verified' : 'Generated'} ${target.key}: ${target.value}x${target.value}, ${bytes.length} bytes',
    );
  }
  stdout.writeln(
    'Master ${source.width}x${source.height}; ${targets.length} icons',
  );
}
