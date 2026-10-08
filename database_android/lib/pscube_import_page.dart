import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:share_plus/share_plus.dart';
import 'package:webview_flutter/webview_flutter.dart';
import 'package:webview_flutter_android/webview_flutter_android.dart';

import 'auto_capture_state.dart' show autoCaptureScreenNote;
import 'browser_session.dart';
import 'daily_net_page.dart' show dailyNetLookup, dailyNetNote;
import 'date_events.dart' show DateEvent;
import 'event_calendar_page.dart';
import 'event_name_dialog.dart';
import 'list_views.dart' show shortDayLabel;
import 'models.dart' show isPscubeStore, viewerStoreNames;
import 'pscube_auto.dart';
import 'pscube_connection.dart';
import 'pscube_list_wait.dart';
import 'pscube_store.dart';
import 'pscube_viewer_data.dart' show pscubeDateEvents, pscubeViewerRecords;
import 'theme.dart';
import 'picked_file.dart';

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
  bool _browserReady = false;
  bool _preparing = false;
  bool _opening = false;
  Completer<void>? _blankLoaded;
  final _connection = PscubeConnection();
  int _page = 0;
  String? _navigationUrl;
  int _remaining = 0;
  DateTime? _lastBackup;

  // 自動取り込み（仕様：database/PSCUBE_AUTO_CAPTURE.md）。メルヘンと同じ ON/OFF・間隔・
  // 起動時OFF・常駐通知。サイトのボタン・人間確認・同意には触れず、表示中のページを読む判定
  // （assets/pscube_auto_probe.js）が ready のときだけ「未取得を取り込む」と同じ処理を始める。
  static const _autoService = MethodChannel('database/auto_capture');
  // 待機ごとに15〜25秒を抽選する（PC版と同じ）。
  final _auto = pscubeRandomAutoState();
  Timer? _autoTimer;
  String? _probe;
  bool _autoChanging = false;
  bool _autoProbing = false;
  String _autoStatus = '停止中';
  final _autoDone = <String>{};
  final _guard = PscubeAutoGuard();
  final _clock = Stopwatch()..start();
  final _autoFailures = <String, int>{};
  // 日付指定取り込み：取り込む営業日（null＝サイトの表示どおり）と、機種を数える向き
  // （top＝一覧の上から、bottom＝下から）。起動のたびに戻る。日本時間の午前2時で営業日が変わる。
  String? _targetDay;
  String _direction = 'top';
  // {日付: 今回の取り込みで最初に保存したページのサイトの更新時刻}。これより古い数値の機種は取り直す。
  // 画面を開いている間（手動の取り込みも）続き、自動取り込みをONにするたびに作り直す。
  final Map<String, String> _freshSince = {};
  // イベント名（自由記入、2026-10-06）。日付指定の日、指定なしなら今の営業日の分を出して編集する。
  String? _eventName;
  String? _eventShownDay;
  bool _eventLoading = false;

  String get _eventDay => _targetDay ?? pscubeBusinessDay();

  @override
  void initState() {
    super.initState();
    _web = WebViewController();
    unawaited(_prepareBrowser());
    _autoTimer = Timer.periodic(const Duration(milliseconds: 100), (_) {
      // 表示中のイベント名の日が変わった（日付指定・その日の完了・午前2時）ら読み直す。
      if (_store != null && _eventShownDay != _eventDay && !_eventLoading) {
        _eventLoading = true;
        unawaited(_loadEvent());
      }
      unawaited(_autoTick());
    });
    unawaited(_initialize());
  }

  Future<void> _prepareBrowser() async {
    if (_preparing) return;
    _preparing = true;
    try {
      await prepareBrowserSession(
        configureJavaScript: () =>
            _web.setJavaScriptMode(JavaScriptMode.unrestricted),
        configureNavigation: () => _web.setNavigationDelegate(
          NavigationDelegate(
            onPageStarted: (url) {
              if (_navigationUrl != null &&
                  _navigationUrl != url &&
                  _samePage(_navigationUrl!, url)) {
                return;
              }
              _navigationUrl = url;
              _connection.start(url);
              _page++;
              _auto.nextPage(_page);
              if (_auto.enabled) _autoMessage('ON・読み込み待ち');
              if (mounted) setState(() => _loading = true);
            },
            onPageFinished: (url) {
              if (url == 'about:blank' && _blankLoaded?.isCompleted == false) {
                _blankLoaded!.complete();
              }
              if (mounted && _connection.finish(url)) {
                setState(() => _loading = false);
              }
            },
            onWebResourceError: (error) {
              if (mounted &&
                  _connection.networkError(
                    url: error.url,
                    mainFrame: error.isForMainFrame == true,
                    code: error.errorCode,
                    description: error.description,
                  )) {
                _connectionFailed();
              }
            },
            onHttpError: (error) {
              if (mounted &&
                  _connection.httpError(
                    url: error.request?.uri.toString(),
                    status: error.response?.statusCode,
                  )) {
                _connectionFailed();
              }
            },
          ),
        ),
        configureCookies: () async {
          final platform = _web.platform;
          final cookies = WebViewCookieManager().platform;
          if (platform is AndroidWebViewController &&
              cookies is AndroidWebViewCookieManager) {
            await cookies.setAcceptThirdPartyCookies(platform, true);
          }
        },
        load: () async {
          _connection.start(PscubeStore.root);
          await _web.loadRequest(Uri.parse(PscubeStore.root));
          if (mounted) setState(() => _browserReady = true);
        },
        active: () => mounted,
      );
    } catch (_) {
      if (mounted) {
        setState(() {
          _loading = false;
          _status = 'ブラウザのCookie・接続設定を準備できませんでした。「もう一度開く」で再試行してください。';
        });
      }
    } finally {
      _preparing = false;
      if (mounted) setState(() {});
    }
  }

  void _connectionFailed() {
    final message = _connection.failure!.message;
    // Invalidate a capture already reading the DOM, before any awaited work.
    _page++;
    _auto.turnOff();
    setState(() {
      _loading = false;
      _status = message;
      _autoStatus = '停止中（通信エラー）';
    });
    unawaited(_stopAuto('停止中（通信エラー）'));
  }

  // This site writes scroll position to the hash on its overview pages.
  // A rack hash identifies the history day and must still match exactly.
  bool _samePage(String first, String? second) =>
      second != null && pscubeSamePage(Uri.parse(first), Uri.parse(second));

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

  Future<void> _loadEvent() async {
    final store = _store;
    final day = _eventDay;
    try {
      final name = store == null ? null : await store.dateEventFor(day);
      if (mounted) {
        setState(() {
          _eventName = name;
          _eventShownDay = day;
        });
      }
    } catch (_) {
      if (mounted) setState(() => _eventShownDay = day);
    } finally {
      _eventLoading = false;
    }
  }

  /// イベントカレンダー（2026-10-08、メルヘンと同じ画面）。先の日にも入れられ、各日に総差枚を出す。
  /// 入れたイベントは記録のある店舗・貸玉すべてに付く（[PscubeStore.setDateEventDays]）。
  Future<void> _openCalendar() async {
    final store = _store;
    if (store == null) return;
    final Map<String, Object?> data;
    try {
      data = await store.calendarData();
    } catch (error) {
      if (mounted) setState(() => _status = 'カレンダーを開けませんでした：$error');
      return;
    }
    final records = pscubeViewerRecords(data);
    final stores = {
      for (final e in viewerStoreNames(records).entries)
        if (isPscubeStore(e.key)) e.key: e.value,
    };
    if (stores.isEmpty) {
      if (mounted) setState(() => _status = '先にP’s CUBEの記録を取り込んでください。');
      return;
    }
    final events = <String, DateEvent>{};
    var names = <String>[];
    Future<void> reload() async {
      final latest = await store.calendarData();
      events
        ..clear()
        ..addAll({
          for (final e in pscubeDateEvents(latest)) e.event.key: e.event,
        });
      names = await store.dateEventNames();
    }

    try {
      await reload();
    } catch (error) {
      if (mounted) setState(() => _status = 'イベント名を読めませんでした：$error');
      return;
    }
    if (!mounted) return;
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => EventCalendarPage(
          stores: stores,
          initialStore: stores.keys.first,
          eventFor: (scope, day) => events['$scope|$day'],
          namesFor: (_) => names,
          onSave: (_, days, name) async {
            await store.setDateEventDays(days, name);
            await reload();
          },
          netFor: dailyNetLookup(records),
          netNote: dailyNetNote(stores.keys.first),
          note: 'ここで入れたイベントは、記録のある貸玉すべてに付きます。PC・閲覧ページへは'
              'P’s CUBEのバックアップで届きます。同じ日は、あとから入れた方が残ります。',
        ),
      ),
    );
    await _loadEvent();
  }

  /// その日のイベント名を付ける・変える・消す。記録はP’s CUBEのバックアップで共有する。
  Future<void> _editEvent() async {
    final store = _store;
    if (store == null) return;
    final day = _eventDay;
    final List<String> names;
    final String? current;
    try {
      names = await store.dateEventNames();
      current = await store.dateEventFor(day);
    } catch (error) {
      if (mounted) setState(() => _status = 'イベント名を読めませんでした：$error');
      return;
    }
    if (!mounted) return;
    final name = await showEventNameDialog(
      context,
      title: '${shortDayLabel(day)} のイベント',
      current: current,
      names: names,
    );
    if (name == null || !mounted) return;
    try {
      await store.setDateEvent(day, name.isEmpty ? null : name);
      if (mounted) {
        setState(
          () => _status = name.isEmpty
              ? '${shortDayLabel(day)}のイベントを外しました。'
              : '${shortDayLabel(day)}のイベントを「$name」にしました。',
        );
      }
    } catch (error) {
      if (mounted) setState(() => _status = 'イベント名を保存できませんでした：$error');
    }
    await _loadEvent();
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

  Future<void> _showFullList({int? expectedCount, int? page}) =>
      waitForPscubeList(
        expectedCount: expectedCount,
        isCurrent: () => mounted && (page == null || _page == page),
        scroll: (action) async {
          // 1回の問い合わせで、決められた動きを1つだけ行い、台数と位置を返す。
          final move = switch (action) {
            PscubeScroll.none => '',
            PscubeScroll.step => 'window.scrollBy(0, Math.max(200, Math.round(window.innerHeight * 0.8)));',
            PscubeScroll.arrive => "list.lastElementChild?.scrollIntoView({block:'end'}); window.scrollTo(0, document.documentElement.scrollHeight);",
            PscubeScroll.nudge =>
              'window.scrollBy(0, -Math.max(300, window.innerHeight * 1.5));',
          };
          // 設置台数が分かっているときは、リストごと入れ替わっても数えられるよう全体から数える。
          final countJs = expectedCount == null
              ? 'list.children.length'
              : r'''document.querySelectorAll('li[id^="li-"]').length''';
          final result = await _web.runJavaScriptReturningResult('''
        (() => {
          const list = document.querySelector('#ulKI') || document.querySelector('li[id^="li-"]')?.parentElement;
          if (!list) return '-1|0';
          $move
          const count = $countJs;
          const bottom = window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 4;
          return count + '|' + (bottom ? 1 : 0);
        })()
      ''');
          final parts = result.toString().replaceAll('"', '').split('|');
          return (
            count: int.tryParse(parts.first) ?? -1,
            atBottom: parts.length > 1 && parts[1] == '1',
          );
        },
      );

  /// サイトの中のページから次のページへは、リンクをたどるのと同じ形（ページ内で移動）で
  /// 開く。アドレスを直接開くと「どのページから来たか」が付かず、普通のブラウザと
  /// 違って見えるため（PC版も同じ形）。サイトの外にいるときだけ直接開く。
  Future<void> _open(String url) async {
    if (!_browserReady || _busy || _opening) return;
    final target = Uri.parse(url);
    if (!PscubeConnection.allowedPage(target)) {
      throw const FormatException('対象のP’s CUBEページではありません。');
    }
    setState(() => _opening = true);
    try {
      final current = Uri.tryParse(await _web.currentUrl() ?? '');
      if (!mounted) return;
      final insidePage =
          _connection.canCapture && current?.host == 'www.pscube.jp';
      _connection.start(url);
      _page++;
      _auto.nextPage(_page);
      setState(() => _loading = true);
      if (insidePage) {
        await _web.runJavaScript('location.assign(${jsonEncode(url)})');
      } else {
        await _web.loadRequest(target);
      }
    } catch (_) {
      if (mounted) {
        setState(() {
          _loading = false;
          _status = 'ページへ移動できませんでした。「もう一度開く」を試してください。';
        });
      }
    } finally {
      if (mounted) setState(() => _opening = false);
    }
  }

  Future<void> _retryPage() async {
    if (_busy || _opening || _preparing) return;
    setState(() => _opening = true);
    try {
      await _stopAuto('停止中（手動で再読み込み）');
      if (!mounted) return;
      if (!_browserReady) {
        await _prepareBrowser();
        return;
      }
      final target = _connection.page;
      final url = target != null && PscubeConnection.allowedPage(target)
          ? target
          : Uri.parse(PscubeStore.root);
      // Loading the next URL replaces the failed document.
      if (!mounted) return;
      _page++;
      _connection.start(url.toString());
      _guard.reset();
      setState(() {
        _loading = true;
        _status = 'Cookieと取り込んだ記録を保持して、ページを開き直しています…';
      });
      await reopenBrowserPage(
        target: url,
        currentUrl: _web.currentUrl,
        reload: _web.reload,
        load: _web.loadRequest,
        active: () => mounted,
      );
    } catch (_) {
      if (mounted) setState(() => _status = 'ページを開き直せませんでした。通信状態を確認してください。');
    } finally {
      if (mounted) setState(() => _opening = false);
    }
  }

  Future<void> _showConnectionHistory() async {
    await showDialog<void>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('通信エラーの記録'),
        content: SingleChildScrollView(
          child: SelectableText(
            _connection.history.isEmpty
                ? 'この画面で記録した通信エラーはありません。'
                : _connection.history.map((error) => error.report).join('\n\n'),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('閉じる'),
          ),
        ],
      ),
    );
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

  /// [direction]：「上から取り込む」「下から取り込む」から始めるとき。省略は今の向きのまま。
  Future<void> _toggleAuto([String? direction]) async {
    if (_autoChanging) return;
    if (_auto.enabled) {
      await _stopAuto('停止中（開始済みの保存は完了まで待ちます）');
      return;
    }
    if (direction != null) _direction = direction;
    if (!_browserReady || _opening || _connection.failure != null) {
      _autoMessage('停止中（通信状態を確認して「もう一度開く」を押してください）');
      return;
    }
    setState(() => _autoChanging = true);
    try {
      if (Platform.isAndroid) await _autoService.invokeMethod<void>('start');
      if (!mounted || _connection.failure != null || _opening) {
        if (Platform.isAndroid) await _autoService.invokeMethod<void>('stop');
        return;
      }
      _autoDone.clear();
      _autoFailures.clear();
      _freshSince.clear();
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
          _opening ||
          !_browserReady ||
          _connection.failure != null ||
          _loading ||
          _store == null ||
          _script == null ||
          _probe == null,
    );
    if (token == null) return;
    setState(() {}); // 待機開始時に今回抽選した秒数を表示する。
    _autoProbing = true;
    try {
      final probe = jsonDecode(
        _decodeJs(await _web.runJavaScriptReturningResult(_probe!)),
      );
      if (!_auto.current(token, page)) return;
      final decision = _guard.decide(
        probe,
        _autoDone,
        _autoFailures,
        _clock.elapsed,
        targetDay: _targetDay,
      );
      if (decision.stop) {
        await _stopAuto(decision.message);
        return;
      }
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
    if (_busy ||
        _opening ||
        !_browserReady ||
        !_connection.canCapture ||
        _loading ||
        _store == null ||
        _script == null) {
      return;
    }
    final store = _store!;
    final page = _page;
    setState(() {
      _busy = true;
      _status = '表示中のデータを読み取っています…';
    });
    try {
      final before = await _web.currentUrl();
      if (before == null) throw const FormatException('ページのURLを確認できません。');
      final expectedCount = await store.installationCount(before);
      if (!mounted || _page != page) return;
      await _showFullList(expectedCount: expectedCount, page: page);
      if (!mounted) return;
      final capturedUrl = await _web.currentUrl();
      if (_page != page ||
          capturedUrl == null ||
          !_samePage(before, capturedUrl)) {
        throw const FormatException('読み取り中にページが切り替わりました。');
      }
      // 台別ページでは元グラフの通信も行う。WebViewの評価結果はPromiseを
      // 待たないため、ページ内で完了を記録してから読み取る。前の読み取りの
      // 遅れた結果を取り違えないよう、読み取りごとの番号で結果を分ける。
      final run = DateTime.now().microsecondsSinceEpoch;
      await _web.runJavaScript('''
        window.__pscubeCaptureRun = $run;
        window.__pscubeCaptureResult = null;
        Promise.resolve(${_script!}).then(
          value => { if (window.__pscubeCaptureRun === $run) window.__pscubeCaptureResult = value; },
          error => { if (window.__pscubeCaptureRun === $run) window.__pscubeCaptureResult = JSON.stringify({error: String(error)}); }
        );
      ''');
      var complete = false;
      for (var attempt = 0; attempt < 75; attempt++) {
        if (!mounted ||
            _page != page ||
            !_samePage(capturedUrl, await _web.currentUrl())) {
          throw const FormatException('読み取り中にページが切り替わりました。');
        }
        final ready = await _web.runJavaScriptReturningResult(
          'window.__pscubeCaptureRun === $run && window.__pscubeCaptureResult != null',
        );
        if (ready == true || ready.toString() == 'true') {
          complete = true;
          break;
        }
        await Future<void>.delayed(const Duration(milliseconds: 200));
      }
      if (!complete) {
        throw const FormatException('ページの読み取りが時間切れになりました。再試行してください。');
      }
      final raw = _decodeJs(
        await _web.runJavaScriptReturningResult('window.__pscubeCaptureResult'),
      );
      if (!mounted) return;
      // OFFを押した・ページが移った後に、古い自動の取り込みを保存しない。
      if (autoToken != null && !_auto.current(autoToken, page)) {
        throw const FormatException('自動取り込みを止めたため、保存しませんでした。');
      }
      if (_page != page || !_samePage(capturedUrl, await _web.currentUrl())) {
        throw const FormatException('保存前にページが切り替わりました。');
      }
      final result = await store.importPage(
        raw,
        capturedUrl,
        expectedDay: _targetDay,
        direction: _direction,
        // 自動取り込みがOFFのとき（手動）は、一覧の最初からではなく、保存したページの次へ進む。
        manual: !_auto.enabled,
        freshSince: _freshSince,
      );
      // 差枚の元データだけ取れなかった（数値・グラフは保存済み、差枚は空欄のまま）。
      final netWarning = pscubeNetWarning(raw);
      if (!mounted) return;
      setState(() {
        _remaining = result.remaining;
        _status =
            _connection.failure?.message ??
            '${result.kind}を保存しました。残り ${result.remaining} 件。'
                '${netWarning == null ? '' : '（$netWarning）'}';
      });
      if (autoSignature != null) {
        _autoDone.add(autoSignature);
        _autoFailures.remove(autoSignature);
        if (_auto.enabled && result.nextUrl == null) {
          final day = _targetDay;
          setState(() => _targetDay = null);
          await _stopAuto(
            day == null
                ? 'すべて取り込みました（自動取り込みを停止しました）'
                : '${int.parse(day.substring(5, 7))}/${int.parse(day.substring(8))}の分をすべて取り込みました（自動取り込みを停止しました）',
          );
        } else if (_auto.enabled) {
          _autoMessage(
            'ON・${result.kind}を保存・残り${result.remaining}件・次のページへ'
            '${netWarning == null ? '' : '（差枚は未取得）'}',
          );
        }
      }
      if (result.nextUrl != null && _page == page && _connection.canCapture) {
        // The save has finished. _open itself still rejects a concurrent save.
        setState(() => _busy = false);
        await _open(result.nextUrl!);
      }
    } catch (error) {
      if (mounted) {
        setState(
          () => _status = _connection.failure?.message ?? '保存できませんでした：$error',
        );
      }
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

  /// サイトの記録（Cookie・保存データ）を消して最初のページを開き直す。取り込んだ記録は消さない。
  /// 利用者が明示的に選んだ場合だけ。DNSやHTTP403の解決を保証しない。
  Future<void> _resetSite() async {
    if (_busy || _opening || !_browserReady) return;
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('サイトの記録を消してやり直す'),
        content: const Text(
          'このアプリのブラウザに残っているCookie・保存データを消して、P’s CUBEの最初のページを開き直します。'
          '取り込んだ記録は消えません。自動取り込みはOFFになります。\n\n'
          'DNSエラーやHTTP403が直るとは限りません。人間確認・同意が出たら手で操作してください。'
          'メルヘンの取り込み画面でも、次に開いたとき同意や確認が出ることがあります。',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('やめる'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('消してやり直す'),
          ),
        ],
      ),
    );
    if (ok != true || !mounted || _busy || _opening) return;
    setState(() => _busy = true);
    try {
      await _stopAuto('停止中（サイトの記録を消して開き直します）');
      _blankLoaded = Completer<void>();
      await _web.loadRequest(Uri.parse('about:blank'));
      await _blankLoaded!.future.timeout(const Duration(seconds: 10));
      if (!mounted) return;
      _page++;
      // Wait until the old site document is gone before clearing Cookies.
      await WebViewCookieManager().clearCookies();
      await _web.clearLocalStorage();
      await _web.clearCache();
      _autoDone.clear();
      _autoFailures.clear();
      _guard.reset();
      if (!mounted) return;
      _connection.start(PscubeStore.root);
      setState(() {
        _loading = true;
        _status =
            'サイトのCookie・保存データを消しました（取り込んだ記録はそのまま）。'
            '人間確認・同意が出たら手で操作してください。';
      });
      await _web.loadRequest(Uri.parse(PscubeStore.root));
    } catch (_) {
      if (mounted) {
        setState(() => _status = 'サイトの記録の消去・再読み込みに失敗しました。「もう一度開く」を試してください。');
      }
    } finally {
      _blankLoaded = null;
      if (mounted) setState(() => _busy = false);
    }
  }

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
      // 選んだファイルの写し（アプリの一時置き場）は、読み終えたら消す（溜めない）。
      await discardPickedCopy(path);
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
          tooltip: 'サイトの記録を消してやり直す',
          onPressed: _busy || _opening || !_browserReady ? null : _resetSite,
          icon: const Icon(Icons.cookie_outlined),
        ),
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
              if (_connection.failure != null ||
                  !_browserReady ||
                  _status.contains('もう一度開く'))
                Wrap(
                  children: [
                    TextButton.icon(
                      onPressed: _busy || _opening || _preparing
                          ? null
                          : _retryPage,
                      icon: const Icon(Icons.refresh),
                      label: const Text('もう一度開く'),
                    ),
                    TextButton(
                      onPressed: _showConnectionHistory,
                      child: const Text('通信エラーの記録'),
                    ),
                  ],
                ),
              Text(_backupText, style: Theme.of(context).textTheme.bodySmall),
              const SizedBox(height: 8),
              Row(
                children: [
                  Expanded(
                    child: OutlinedButton(
                      onPressed: _busy || _opening || !_browserReady
                          ? null
                          : () => _open(PscubeStore.index),
                      child: const Text('スロット機種一覧'),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: FilledButton(
                      onPressed:
                          _busy ||
                              _opening ||
                              !_browserReady ||
                              !_connection.canCapture ||
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
                  onPressed:
                      _autoChanging ||
                          _opening ||
                          !_browserReady ||
                          _connection.failure != null ||
                          _store == null
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
              // 日付指定取り込み：取り込む営業日を決める（日本時間の午前2時までは前日）。
              // 上から／下から：機種を一覧のどちら側から取り込むか。押すと自動取り込みをONにする。
              DropdownButtonFormField<String>(
                key: ValueKey('pscube-day-$_targetDay'),
                initialValue: _targetDay ?? '',
                isExpanded: true,
                decoration: const InputDecoration(
                  labelText: '日付指定取り込み（取り込む日）',
                  isDense: true,
                ),
                items: [
                  const DropdownMenuItem(
                    value: '',
                    child: Text('指定なし（サイトの表示どおり）'),
                  ),
                  for (final (i, day) in pscubeRecentBusinessDays().indexed)
                    DropdownMenuItem(
                      value: day,
                      child: Text(
                        '${shortDayLabel(day)}${i == 0 ? '　今の営業日' : ''}',
                      ),
                    ),
                ],
                onChanged: _auto.enabled
                    ? null
                    : (value) => setState(
                        () => _targetDay = value == null || value.isEmpty
                            ? null
                            : value,
                      ),
              ),
              Align(
                alignment: Alignment.centerLeft,
                child: TextButton.icon(
                  onPressed: _store == null ? null : _editEvent,
                  icon: const Icon(Icons.event_note_outlined, size: 18),
                  label: Text(
                    '${shortDayLabel(_eventDay)}のイベント：'
                    '${_eventShownDay == _eventDay ? (_eventName ?? 'なし') : '…'}（編集）',
                  ),
                ),
              ),
              Align(
                alignment: Alignment.centerLeft,
                child: TextButton.icon(
                  onPressed: _store == null ? null : _openCalendar,
                  icon: const Icon(Icons.calendar_month_outlined, size: 18),
                  label: const Text('イベントカレンダー'),
                ),
              ),
              const SizedBox(height: 6),
              Row(
                children: [
                  for (final (direction, label) in const [
                    ('top', '上から取り込む'),
                    ('bottom', '下から取り込む'),
                  ])
                    Expanded(
                      child: Padding(
                        padding: EdgeInsets.only(
                          right: direction == 'top' ? 6 : 0,
                        ),
                        child: FilledButton(
                          style: FilledButton.styleFrom(
                            backgroundColor: AppColors.appleBlue,
                            foregroundColor: Colors.white,
                            minimumSize: const Size.fromHeight(44),
                          ),
                          onPressed:
                              _auto.enabled ||
                                  _autoChanging ||
                                  _opening ||
                                  !_browserReady ||
                                  _connection.failure != null ||
                                  _store == null
                              ? null
                              : () => _toggleAuto(direction),
                          child: Text(label),
                        ),
                      ),
                    ),
                ],
              ),
              Row(
                children: [
                  const Text('15〜25秒ランダム', style: TextStyle(fontSize: 13)),
                  Expanded(
                    child: Slider(
                      min: 15,
                      max: 25,
                      value: _auto.interval.inMicroseconds / 1000000,
                      label:
                          '${(_auto.interval.inMicroseconds / 1000000).toStringAsFixed(4)}秒',
                      onChanged: null,
                    ),
                  ),
                  Text(
                    '${(_auto.interval.inMicroseconds / 1000000).toStringAsFixed(4)}秒',
                    style: const TextStyle(fontSize: 13),
                  ),
                ],
              ),
              Text(
                _autoStatus,
                style: const TextStyle(fontSize: 12, color: AppColors.ash),
              ),
              if (_auto.enabled)
                const Text(
                  autoCaptureScreenNote,
                  style: TextStyle(fontSize: 12, color: AppColors.ash),
                ),
            ],
          ),
        ),
        Expanded(child: WebViewWidget(controller: _web)),
      ],
    ),
  );
}
