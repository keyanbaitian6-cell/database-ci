import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:file_picker/file_picker.dart';
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
  bool _loading = true;
  int _page = 0;
  String? _navigationUrl;
  int _remaining = 0;
  DateTime? _lastBackup;

  @override
  void initState() {
    super.initState();
    _web = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setNavigationDelegate(
        NavigationDelegate(
          onPageStarted: (url) {
            if (_navigationUrl != null && _samePage(_navigationUrl!, url)) {
              return;
            }
            _navigationUrl = url;
            _page++;
            if (mounted) setState(() => _loading = true);
          },
          onPageFinished: (_) {
            if (mounted) setState(() => _loading = false);
          },
          onWebResourceError: (error) {
            if (error.isForMainFrame == true && mounted) {
              setState(() => _status = 'ページを開けませんでした：${error.description}');
            }
          },
        ),
      )
      ..loadRequest(Uri.parse(PscubeStore.root));
    unawaited(_initialize());
  }

  // This site writes scroll position to the hash on its overview pages.
  // A rack hash identifies the history day and must still match exactly.
  bool _samePage(String first, String second) {
    final a = Uri.parse(first);
    final b = Uri.parse(second);
    if (a.path.endsWith('nc-v06-001.php')) return a == b;
    return a.replace(fragment: '') == b.replace(fragment: '');
  }

  Future<void> _initialize() async {
    try {
      final store = await PscubeStore.open();
      String script;
      try {
        script = await rootBundle.loadString('assets/pscube_capture.js');
      } catch (_) {
        await store.close();
        rethrow;
      }
      if (!mounted) {
        await store.close();
        return;
      }
      final backedUp = await store.lastBackupAt();
      if (!mounted) {
        await store.close();
        return;
      }
      setState(() {
        _store = store;
        _script = script;
        _lastBackup = backedUp;
      });
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
    for (var i = 0; i < 70 && stable < 6; i++) {
      if (!mounted) return;
      final result = await _web.runJavaScriptReturningResult('''
        (() => {
          const list = document.querySelector('#ulKI') || document.querySelector('li[id^="li-"]')?.parentElement;
          if (!list) return -1;
          list.lastElementChild?.scrollIntoView({block:'end'});
          window.scrollTo(0, document.documentElement.scrollHeight);
          return list.children.length;
        })()
      ''');
      final count = int.tryParse(result.toString()) ?? -1;
      if (count < 0) return;
      if (count == prior && count >= 0) {
        stable++;
      } else {
        stable = 0;
      }
      prior = count;
      await Future<void>.delayed(const Duration(milliseconds: 350));
    }
  }

  Future<void> _capture() async {
    if (_busy || _loading || _store == null || _script == null) return;
    final store = _store!;
    final page = _page;
    setState(() {
      _busy = true;
      _status = '表示中のデータを読み取っています…';
    });
    try {
      final before = await _web.currentUrl();
      if (before == null) throw const FormatException('ページのURLを確認できません。');
      await _showFullList();
      if (!mounted) return;
      final capturedUrl = await _web.currentUrl();
      if (_page != page ||
          capturedUrl == null ||
          !_samePage(before, capturedUrl)) {
        throw const FormatException('読み取り中にページが切り替わりました。');
      }
      final value = await _web.runJavaScriptReturningResult(_script!);
      // Android WebView may return the string once or twice JSON encoded.
      dynamic raw = value;
      for (var i = 0; i < 2 && raw is String; i++) {
        final decoded = jsonDecode(raw);
        if (decoded is String) {
          raw = decoded;
        } else {
          raw = jsonEncode(decoded);
          break;
        }
      }
      if (raw is! String) raw = jsonEncode(raw);
      if (!mounted) return;
      if (_page != page || await _web.currentUrl() != capturedUrl) {
        throw const FormatException('保存前にページが切り替わりました。');
      }
      final result = await store.importPage(raw, capturedUrl);
      if (!mounted) return;
      setState(() {
        _remaining = result.remaining;
        _status = '${result.kind}を保存しました。残り ${result.remaining} 件。';
      });
      if (result.nextUrl != null && _page == page) {
        await _web.loadRequest(Uri.parse(result.nextUrl!));
      }
    } catch (error) {
      if (mounted) setState(() => _status = '保存できませんでした：$error');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// バックアップを書き出して共有する（Googleドライブの「database共有」へ保存すると、
  /// PC版が読み込める）。共有を取りやめたときは「書き出し済み」にしない。
  Future<void> _share() async {
    final store = _store;
    if (store == null || _busy) return;
    setState(() => _busy = true);
    try {
      final file = await store.exportViewer();
      if (!mounted) return;
      final fileName = file.uri.pathSegments.last;
      final shared = await SharePlus.instance.share(
        ShareParams(
          title: fileName,
          subject: fileName,
          text:
              'PC版と共有するP’s CUBEのバックアップです。Google Driveの「database共有」などに保存してください。',
          files: [XFile(file.path, mimeType: 'application/json')],
        ),
      );
      if (!mounted) return;
      if (shared.status == ShareResultStatus.dismissed) {
        setState(() => _status = '共有を取りやめました。バックアップ済みにはしていません。');
        return;
      }
      await store.markBackedUp();
      final at = await store.lastBackupAt();
      if (mounted) {
        setState(() {
          _lastBackup = at;
          _status = 'バックアップを書き出しました（$fileName）。';
        });
      }
    } catch (error) {
      if (mounted) setState(() => _status = '書き出せませんでした：$error');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// PC版・ブラウザのバックアップを統合する。中身を確かめてから1回で保存するので、
  /// 形式が不正なときは何も保存しない。
  Future<void> _restore() async {
    final store = _store;
    if (store == null || _busy) return;
    final picked = await FilePicker.pickFile(
      type: FileType.custom,
      allowedExtensions: ['json'],
    );
    final path = picked?.path;
    if (path == null || !mounted) return;
    setState(() {
      _busy = true;
      _status = 'バックアップを読み込んでいます…';
    });
    try {
      final result = await store.importBackup(await File(path).readAsString());
      if (!mounted) return;
      setState(
        () => _status =
            '新規${result.added}件、更新${result.updated}件、同じ内容${result.unchanged}件、'
            '新しい自分の数値を維持${result.keptLocal}件を取り込みました。',
      );
    } catch (error) {
      if (mounted) setState(() => _status = '読み込めませんでした（何も保存していません）：$error');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  String get _backupText {
    final at = _lastBackup;
    if (at == null) return 'バックアップ：まだ書き出していません';
    String two(int v) => v.toString().padLeft(2, '0');
    final local = at.toLocal();
    final stale = DateTime.now().difference(local).inHours >= 24;
    return 'バックアップ：最後に書き出した日時 ${local.month}/${local.day} ${two(local.hour)}:${two(local.minute)}'
        '${stale ? '（1日以上前です）' : ''}';
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: const Text('P’s CUBE 取り込み'),
      actions: [
        IconButton(
          tooltip: 'バックアップを読み込む',
          onPressed: _busy || _store == null ? null : _restore,
          icon: const Icon(Icons.file_open),
        ),
        IconButton(
          tooltip: 'バックアップを書き出す（共有）',
          onPressed: _busy || _store == null ? null : _share,
          icon: const Icon(Icons.ios_share),
        ),
      ],
    ),
    body: Column(
      children: [
        Padding(
          padding: const EdgeInsets.all(12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(_status),
              Text(_backupText, style: Theme.of(context).textTheme.bodySmall),
              const SizedBox(height: 8),
              Row(
                children: [
                  Expanded(
                    child: OutlinedButton(
                      onPressed: _busy
                          ? null
                          : () =>
                                _web.loadRequest(Uri.parse(PscubeStore.index)),
                      child: const Text('スロット機種一覧'),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: FilledButton(
                      onPressed:
                          _busy || _loading || _store == null || _script == null
                          ? null
                          : _capture,
                      child: Text(_busy || _loading ? '読み込み中…' : '未取得を取り込む'),
                    ),
                  ),
                ],
              ),
              if (_remaining > 0)
                Text(
                  '次のページへ自動で移動します。残り $_remaining 件',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
            ],
          ),
        ),
        Expanded(child: WebViewWidget(controller: _web)),
      ],
    ),
  );
}
