import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:share_plus/share_plus.dart';
import 'package:webview_flutter/webview_flutter.dart';

import 'pscube_store.dart';

class PscubeImportPage extends StatefulWidget {
  const PscubeImportPage({super.key});

  @override
  State<PscubeImportPage> createState() => _PscubeImportPageState();
}

class _PscubeImportPageState extends State<PscubeImportPage> {
  late final WebViewController _web;
  PscubeStore? _store;
  String? _script;
  String _status = 'サイトの認証後、スロット機種一覧を開いてください。';
  bool _busy = false;
  int _remaining = 0;

  @override
  void initState() {
    super.initState();
    _web = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setNavigationDelegate(NavigationDelegate(
        onPageFinished: (_) { if (mounted) setState(() {}); },
        onWebResourceError: (error) {
          if (error.isForMainFrame == true && mounted) {
            setState(() => _status = 'ページを開けませんでした：${error.description}');
          }
        },
      ))
      ..loadRequest(Uri.parse(PscubeStore.root));
    unawaited(_initialize());
  }

  Future<void> _initialize() async {
    try {
      final store = await PscubeStore.open();
      final script = await rootBundle.loadString('assets/pscube_capture.js');
      if (!mounted) { await store.close(); return; }
      setState(() { _store = store; _script = script; });
    } catch (error) {
      if (mounted) setState(() => _status = '取り込みの準備ができません：$error');
    }
  }

  @override
  void dispose() {
    final store = _store;
    if (store != null) unawaited(store.close());
    super.dispose();
  }

  Future<void> _showFullList() async {
    // The site lazily adds cards as the user scrolls. Count-stability is only
    // a loading aid; PscubeStore checks against the installation count.
    var prior = -1;
    var stable = 0;
    for (var i = 0; i < 70 && stable < 3; i++) {
      final result = await _web.runJavaScriptReturningResult('''
        (() => {
          const list = document.querySelector('#ulKI') || document.querySelector('li[id^="li-"]')?.parentElement;
          if (!list) return -1;
          list.lastElementChild?.scrollIntoView({block:'end'});
          return list.children.length;
        })()
      ''');
      final count = int.tryParse(result.toString()) ?? -1;
      if (count == prior && count >= 0) { stable++; } else { stable = 0; }
      prior = count;
      await Future<void>.delayed(const Duration(milliseconds: 350));
    }
  }

  Future<void> _capture() async {
    if (_busy || _store == null || _script == null) return;
    setState(() { _busy = true; _status = '表示中のデータを読み取っています…'; });
    try {
      final before = await _web.currentUrl();
      if (before == null) throw const FormatException('ページのURLを確認できません。');
      await _showFullList();
      if (await _web.currentUrl() != before) throw const FormatException('読み取り中にページが切り替わりました。');
      final value = await _web.runJavaScriptReturningResult(_script!);
      // Android WebView may return the string once or twice JSON encoded.
      dynamic raw = value;
      for (var i = 0; i < 2 && raw is String; i++) {
        final decoded = jsonDecode(raw);
        if (decoded is String) { raw = decoded; } else { raw = jsonEncode(decoded); break; }
      }
      if (raw is! String) raw = jsonEncode(raw);
      if (await _web.currentUrl() != before) throw const FormatException('保存前にページが切り替わりました。');
      final result = await _store!.importPage(raw, before);
      await _store!.exportViewer();
      if (!mounted) return;
      setState(() {
        _remaining = result.remaining;
        _status = '${result.kind}を保存しました。残り ${result.remaining} 件。';
      });
      if (result.nextUrl != null) await _web.loadRequest(Uri.parse(result.nextUrl!));
    } catch (error) {
      if (mounted) setState(() => _status = '保存できませんでした：$error');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _share() async {
    final store = _store;
    if (store == null) return;
    try {
      final file = await store.exportViewer();
      await SharePlus.instance.share(ShareParams(
        title: 'P’s CUBE データ',
        files: [XFile(file.path, mimeType: 'application/json')],
      ));
    } catch (error) {
      if (mounted) setState(() => _status = '書き出せませんでした：$error');
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('P’s CUBE 取り込み'), actions: [
      IconButton(tooltip: 'ブラウザ版へ共有', onPressed: _store == null ? null : _share,
        icon: const Icon(Icons.ios_share)),
    ]),
    body: Column(children: [
      Padding(padding: const EdgeInsets.all(12), child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(_status),
          const SizedBox(height: 8),
          Row(children: [
            Expanded(child: OutlinedButton(onPressed: _busy ? null : () => _web.loadRequest(Uri.parse(PscubeStore.index)),
              child: const Text('スロット機種一覧'))),
            const SizedBox(width: 8),
            Expanded(child: FilledButton(onPressed: _busy || _store == null || _script == null ? null : _capture,
              child: Text(_busy ? '読み込み中…' : '未取得を取り込む'))),
          ]),
          if (_remaining > 0) Text('次のページへ自動で移動します。残り $_remaining 件',
            style: Theme.of(context).textTheme.bodySmall),
        ],
      )),
      Expanded(child: WebViewWidget(controller: _web)),
    ]),
  );
}
