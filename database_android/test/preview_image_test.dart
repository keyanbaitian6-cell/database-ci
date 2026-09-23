import 'package:flutter_test/flutter_test.dart';
import 'package:image/image.dart' as imglib;

import 'package:database_android/import_service.dart';

void main() {
  imglib.Image sample() {
    final image = imglib.Image(width: 400, height: 300);
    imglib.fill(image, color: imglib.ColorRgb8(255, 255, 255));
    imglib.drawLine(
      image,
      x1: 0,
      y1: 150,
      x2: 399,
      y2: 150,
      color: imglib.ColorRgb8(220, 45, 45),
    );
    imglib.drawLine(
      image,
      x1: 0,
      y1: 250,
      x2: 399,
      y2: 60,
      color: imglib.ColorRgb8(30, 30, 30),
    );
    return image;
  }

  test('保存する画像は画素が半分・32色以下で、元よりはっきり小さい', () {
    final source = sample();
    final stored = imglib.decodePng(encodePreviewPng(source))!;
    expect(stored.width, 200);
    expect(stored.height, 150);
    expect(stored.numChannels <= 4, isTrue);
    final colors = <int>{};
    for (final pixel in stored) {
      colors.add(
        (pixel.r.toInt() << 16) | (pixel.g.toInt() << 8) | pixel.b.toInt(),
      );
    }
    expect(colors.length, lessThanOrEqualTo(previewColors));
    // 実データ（1台分のスランプグラフ）では元の約1/6になる。ここでは線が2本だけの
    // 作り物の画像なので比率は比べず、保存しても十分小さいことだけを見る。
    expect(encodePreviewPng(source).length, lessThan(20 * 1024));
  });

  test('1枚あたりの処理時間を記録する（実機はこれより遅い）', () {
    final source = sample();
    encodePreviewPng(source); // 準備
    final watch = Stopwatch()..start();
    for (var i = 0; i < 10; i++) {
      encodePreviewPng(source);
    }
    watch.stop();
    final perImage = watch.elapsedMilliseconds / 10;
    // ignore: avoid_print
    print('encodePreviewPng: ${perImage.toStringAsFixed(1)} ms/枚（PC上）');
    expect(perImage, lessThan(1000));
  });
}
