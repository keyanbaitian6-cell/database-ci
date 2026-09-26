// 閲覧ページ（viewer_main.dart）から、ページ内のJavaScript（web/index.html の
// databaseViewer）を呼ぶ窓口。Web以外（テスト）では何もしない版を使う。
export 'viewer_bridge_stub.dart'
    if (dart.library.js_interop) 'viewer_bridge_web.dart';
