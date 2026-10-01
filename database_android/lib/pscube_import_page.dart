import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:share_plus/share_plus.dart';
import 'package:webview_flutter/webview_flutter.dart';
import 'package:webview_flutter_android/webview_flutter_android.dart';

import 'auto_capture_state.dart';
import 'pscube_auto.dart';
import 'pscube_store.dart';
import 'theme.dart';

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

  // 自動取り込み（仕様：database/PSCUBE_AUTO_CAPTURE.md）。メルヘンと同じ ON/OFF・間隔・
  // 起動時OFF・常駐通知。サイトのボタン・人間確認・同意には触れず、表示中のページを読む判定
  // （assets/pscube_auto_probe.js）が ready のときだけ「未取得を取り込む」と同じ処理を始める。
  static const _autoService = MethodChannel('database/auto_capture');
  final _auto = AutoCaptureState();
  Timer? _autoTimer;
  String? _probe;
  bool _autoChanging = false;
  bool _autoProbing = false;
  String _autoStatus = '停止中';
  final _autoDone = <String>{};
  final _autoFailures = <String, int>{};

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
            _auto.nextPage(_page);
            if (_auto.enabled) _autoMessage('ON・読み込み待ち');
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
    // 普通のブラウザと同じく、ページ内の別サイト（人間確認の hCaptcha の窓）のCookieも
    // 受け付ける。AndroidのWebViewは初期設定で拒否するため、確認済みを覚えられず、
    // 台別ページを開くたびに人間確認が出ていた可能性がある（2026-10-01、利用者の報告）。
    final platform = _web.platform;
    final cookies = WebViewCookieManager().platform;
    if (platform is AndroidWebViewController &&
        cookies is AndroidWebViewCookieManager) {
      unawaited(cookies.setAcceptThirdPartyCookies(platform, true));
    }
    _autoTimer = Timer.periodic(
      const Duration(milliseconds: 100),
      (_) => unawaited(_autoTick()),
    );
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
      String probe;
      try {
        script = await rootBundle.loadString('assets/pscube_capture.js');
        probe = await rootBundle.loadString('assets/pscube_auto_probe.js');
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
        _probe = probe;
        _lastBackup = backedUp;
      });
    } catch (error) {
      if (mounted) setState(() => _status = '取り込みの準備ができません：$error');
    }
  }

  @override
  void dispose() {
    _auto.turnOff();
    _autoTimer?.cancel();
    if (Platform.isAndroid) {
      unawaited(_autoService.invokeMethod<void>('stop').catchError((_) {}));
    }
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

  /// サイトの中のページから次のページへは、リンクをたどるのと同じ形（ページ内で移動）で
  /// 開く。アドレスを直接開くと「どのページから来たか」が付かず、普通のブラウザと
  /// 違って見えるため（PC版も同じ形）。サイトの外にいるときだけ直接開く。
  Future<void> _open(String url) async {
    final current = Uri.tryParse(await _web.currentUrl() ?? '');
    if (current?.host == 'www.pscube.jp') {
      await _web.runJavaScript('location.assign(${jsonEncode(url)})');
    } else {
      await _web.loadRequest(Uri.parse(url));
    }
  }

  /// Android WebView は文字列を1回か2回JSONにして返すことがある。
  static String _decodeJs(Object value) {
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
    return raw is String ? raw : jsonEncode(raw);
  }

  void _autoMessage(String message) {
    if (mounted && message != _autoStatus) {
      setState(() => _autoStatus = message);
    }
  }

  Future<void> _toggleAuto() async {
    if (_autoChanging) return;
    if (_auto.enabled) {
      await _stopAuto('停止中（開始済みの保存は完了まで待ちます）');
      return;
    }
    setState(() => _autoChanging = true);
    try {
      if (Platform.isAndroid) await _autoService.invokeMethod<void>('start');
      if (!mounted) {
        if (Platform.isAndroid) await _autoService.invokeMethod<void>('stop');
        return;
      }
      _autoDone.clear();
      _autoFailures.clear();
      _auto.turnOn();
      setState(() => _autoStatus = 'ON・次の取り込みを待っています');
    } catch (error) {
      _autoMessage('自動取り込みを開始できませんでした：$error');
    } finally {
      if (mounted) setState(() => _autoChanging = false);
    }
  }

  Future<void> _stopAuto(String message) async {
    _auto.turnOff();
    if (mounted) setState(() => _autoStatus = message);
    if (Platform.isAndroid) {
      try {
        await _autoService.invokeMethod<void>('stop');
      } catch (_) {}
    }
  }

  Future<void> _autoTick() async {
    if (!mounted || _autoProbing) return;
    final page = _page;
    final token = _auto.due(
      busy:
          _busy ||
          _loading ||
          _store == null ||
          _script == null ||
          _probe == null,
    );
    if (token == null) return;
    _autoProbing = true;
    try {
      final probe = jsonDecode(
        _decodeJs(await _web.runJavaScriptReturningResult(_probe!)),
      );
      if (!_auto.current(token, page)) return;
      final decision = pscubeAutoDecision(probe, _autoDone, _autoFailures);
      _autoMessage(decision.message);
      final signature = decision.capture;
      if (signature != null) {
        await _capture(autoSignature: signature, autoToken: token);
      }
    } catch (error) {
      if (_auto.current(token, page)) _autoMessage('ON・待機：$error');
    } finally {
      _autoProbing = false;
    }
  }

  Future<void> _capture({String? autoSignature, int? autoToken}) async {
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
      final raw = _decodeJs(await _web.runJavaScriptReturningResult(_script!));
      if (!mounted) return;
      // OFFを押した・ページが移った後に、古い自動の取り込みを保存しない。
      if (autoToken != null && !_auto.current(autoToken, page)) {
        throw const FormatException('自動取り込みを止めたため、保存しませんでした。');
      }
      if (_page != page || await _web.currentUrl() != capturedUrl) {
        throw const FormatException('保存前にページが切り替わりました。');
      }
      final result = await store.importPage(raw, capturedUrl);
      if (!mounted) return;
      setState(() {
        _remaining = result.remaining;
        _status = '${result.kind}を保存しました。残り ${result.remaining} 件。';
      });
      if (autoSignature != null) {
        _autoDone.add(autoSignature);
        _autoFailures.remove(autoSignature);
        if (_auto.enabled && result.nextUrl == null) {
          await _stopAuto('すべて取り込みました（自動取り込みを停止しました）');
        } else if (_auto.enabled) {
          _autoMessage('ON・${result.kind}を保存・残り${result.remaining}件・次のページへ');
        }
      }
      if (result.nextUrl != null && _page == page) {
        await _open(result.nextUrl!);
      }
    } catch (error) {
      if (mounted) setState(() => _status = '保存できませんでした：$error');
      if (autoSignature != null && _auto.enabled) {
        final count = (_autoFailures[autoSignature] ?? 0) + 1;
        _autoFailures[autoSignature] = count;
        _autoMessage('ON・保存できませんでした（$count回目）：$error');
      }
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
                      onPressed: _busy ? null : () => _open(PscubeStore.index),
                      child: const Text('スロット機種一覧'),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: FilledButton(
                      onPressed:
                          _busy ||
                              _loading ||
                              _store == null ||
                              _script == null ||
                              _auto.enabled
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
              const SizedBox(height: 6),
              SizedBox(
                width: double.infinity,
                child: FilledButton.icon(
                  style: FilledButton.styleFrom(
                    backgroundColor: _auto.enabled
                        ? AppColors.appleBlue
                        : AppColors.ash,
                    foregroundColor: Colors.white,
                    minimumSize: const Size.fromHeight(48),
                  ),
                  onPressed: _autoChanging || _store == null
                      ? null
                      : _toggleAuto,
                  icon: Icon(
                    _auto.enabled
                        ? Icons.autorenew
                        : Icons.pause_circle_outline,
                  ),
                  label: Text('自動取り込み：${_auto.enabled ? 'ON' : 'OFF'}'),
                ),
              ),
              Row(
                children: [
                  const Text('間隔', style: TextStyle(fontSize: 13)),
                  Expanded(
                    child: Slider(
                      min: 1,
                      max: 45,
                      divisions: 44,
                      value: _auto.intervalTenths.toDouble(),
                      label:
                          '${(_auto.intervalTenths / 10).toStringAsFixed(1)}秒',
                      onChanged: _auto.enabled
                          ? null
                          : (value) => setState(
                              () => _auto.setIntervalTenths(value.round()),
                            ),
                    ),
                  ),
                  Text(
                    '${(_auto.intervalTenths / 10).toStringAsFixed(1)}秒',
                    style: const TextStyle(fontSize: 13),
                  ),
                ],
              ),
              Text(
                _autoStatus,
                style: const TextStyle(fontSize: 12, color: AppColors.ash),
              ),
            ],
          ),
        ),
        Expanded(child: WebViewWidget(controller: _web)),
      ],
    ),
  );
}
