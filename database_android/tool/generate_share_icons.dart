import 'dart:io';

import 'package:image/image.dart' as img;

/// Mechanical size conversion; preserve the supplied photo without cropping.
/// dart --packages=.dart_tool/package_config.json tool/generate_share_icons.dart
void main() {
  final root = File.fromUri(Platform.script).parent.parent.parent;
  final master = File('${root.path}/design/share_icon/source.png');
  final source = img.decodePng(master.readAsBytesSync());
  if (source == null || source.width != source.height || source.width < 512) {
    throw StateError('Source must be a square PNG at least 512 pixels wide');
  }
  for (final target in {
    'favicon.png': 32,
    'apple-touch-icon.png': 180,
    'icon-192.png': 192,
    'icon-512.png': 512,
  }.entries) {
    final output = File('${root.path}/share_viewer/${target.key}');
    output.writeAsBytesSync(
      img.encodePng(
        img.copyResize(
          source,
          width: target.value,
          height: target.value,
          interpolation: img.Interpolation.average,
        ),
      ),
    );
    stdout.writeln('Generated ${target.key}: ${target.value}x${target.value}');
  }
}
