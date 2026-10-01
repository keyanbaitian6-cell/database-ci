{{flutter_js}}
{{flutter_build_config}}

// Flutterの古いService Worker（オフライン用の仕組み）は登録しない。Flutterが
// 作るものは、登録されるとすぐ自分を解除するだけの中身になっていて、登録すると
// 起動のたびに「登録→解除」の手順と、その完了待ちが入る（電池と起動時間の無駄）。
// https://docs.flutter.dev/platform-integration/web/initialization
_flutter.loader.load({config: {canvasKitBaseUrl: 'canvaskit/'}});
