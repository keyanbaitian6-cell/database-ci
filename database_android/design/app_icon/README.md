# パンダのアプリアイコン（2026-09-30）

利用者提供の横長画像を参考に、中央のパンダ帽子の女の子と抱えているパンダを主役にした正方形の画像を、組み込みの画像生成機能で作成した。利用者指定の対象はAndroid・ブラウザの両方。原画は `panda_master.png`（1254×1254）。参照画像の原本は変更していない。

Androidは既存の `@mipmap/ic_launcher` と5密度のPNGを置き換える。Webはfavicon、通常・maskableの192/512px、iPhoneホーム画面向けの180px。Webの参照には `v=panda-20260930` を付け、新アイコンを別URLで取得する。OSの形状マスクに備え、原画には角丸や透明な外枠を焼き込まない。既に追加したホーム画面アイコンの更新可否は端末依存で、今回実機では確認していない。

機械的なサイズ生成と一致確認（database_android内で実行）：

```powershell
dart --packages=.dart_tool/package_config.json tool/generate_app_icons.dart
dart --packages=.dart_tool/package_config.json tool/generate_app_icons.dart --check
```

これは画像の再生成APIを呼ばず、保存した原画から各サイズへ縮小する。画面、採点、候補、データ形式は変更しない。AndroidのAPKは利用者指定により今回ビルドしない。

## 実際に使った生成指示

```text
Use case: stylized-concept. Asset type: square Android launcher icon and browser/PWA icon for the database app, one finished image, not a sheet or mockup. Input image 1 is a character and visual-style reference. Create a crisp polished 1024x1024 full-bleed square illustration closely based on the central girl wearing a white panda hood and hugging the smiling panda in the reference. Preserve her recognizable light-brown hair with red ribbon, large turquoise/emerald eyes, friendly expression, white hood with black panda ears and small red M motif, white outfit with red trim, and the hugged panda's sleepy happy face. Focus on their two faces with a compact bust-up composition; omit the small surrounding floating characters, tiny distant girl, full body and extraneous props. Keep the girl's entire hood and the panda face recognizable within the central circular safe area (roughly central 65% of the canvas), with no essential facial features near the outer edges. Fill the whole square with the reference's beautiful deep-blue-to-cyan starry background, simplified to sparse soft sparkles and a subtle bright cyan halo that provides contrast without visual noise. Clean anime illustration, bold readable contours, soft shading and balanced silhouette so it remains distinctive at 48 pixels. No added text, app title, border, rounded-corner cutout, phone mockup, drop shadow outside the square, or watermark. Opaque background. Deliver just the finished icon image.
```

生成結果は1254×1254。実ファイルを確認して各用途のサイズに縮小している。
