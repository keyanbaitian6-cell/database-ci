import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'capture_health_ui.dart';
import 'capture_notice.dart';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/foundation.dart' show compute;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:webview_flutter/webview_flutter.dart';
import 'package:webview_flutter_android/webview_flutter_android.dart';

import 'auto_capture_state.dart' show autoCaptureScreenNote;
import 'browser_session.dart';
import 'backup_destination.dart';
import 'daily_net_page.dart' show dailyNetLookup, dailyNetNote;
import 'date_events.dart' show DateEvent;
import 'error_log.dart';
import 'home_widget.dart';
import 'event_calendar_page.dart';
import 'event_name_dialog.dart';
import 'list_views.dart' show shortDayLabel;
import 'models.dart' show isPscubeStore, viewerStoreNames;
import 'pscube_auto.dart';
import 'pscube_connection.dart';
import 'pscube_day_upload.dart';
import 'pscube_list_wait.dart';
import 'pscube_store.dart';
import 'pscube_viewer_data.dart' show pscubeDateEvents, pscubeViewerRecords;
import 'theme.dart';
import 'picked_file.dart';
import 'youtube_request_block.dart';

class PscubeImportPage extends StatefulWidget {
  const PscubeImportPage({super.key, this.elapsed, this.now, this.openStore});

  // 時計と保存先を差し替えても、画面の自動判定・読み取り・保存は同じ経路を通す。
  final Duration Function()? elapsed;
  final DateTime Function()? now;
  final Future<PscubeStore> Function()? openStore;

  @override
  State<PscubeImportPage> createState() => _PscubeImportPageState();
}

class _PscubeImportPageState extends State<PscubeImportPage>
    with WidgetsBindingObserver {
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
  // 当日分の自動送信（pscube_day_upload.dart）の設定と、最後の送信の結果。
  PscubeDayUploadSetting? _upload;
  Map<String, dynamic>? _lastUpload;

  // 自動取り込み（仕様：database/PSCUBE_AUTO_CAPTURE.md）。メルヘンと同じ ON/OFF・間隔・
  // 起動時OFF・常駐通知。サイトのボタン・人間確認・同意には触れず、表示中のページを読む判定
  // （assets/pscube_auto_probe.js）が ready のときだけ「未取得を取り込む」と同じ処理を始める。
  static const _autoService = MethodChannel('database/auto_capture');
  // 待機ごとに15〜25秒を抽選する（PC版と同じ）。
  late final _auto = pscubeRandomAutoState(elapsed: _elapsed);
  Timer? _autoTimer;
  String? _probe;
  bool _autoChanging = false;
  bool _autoProbing = false;
  String _autoStatus = '停止中';
  final _autoDone = <String>{};
  final _guard = PscubeAutoGuard();
  final _clock = Stopwatch()..start();
  Duration _elapsed() => widget.elapsed?.call() ?? _clock.elapsed;
  final _autoFailures = <String, int>{};

  /// 3回失敗して待つページの、3回目の失敗の知らせ。次の確認で「同じページで3回失敗」の一般の文に
  /// 上書きしないために覚えておく（2026-11-04、何機種だったかが画面から消えて原因を追えなかった）。
  final _autoHeld = <String, String>{};

  /// 一覧が進まなかった回数（ページごと）。[_autoFailures] と分けて数え、3回で止めない（[_retryList]）。
  final _listRetries = <String, int>{};

  /// 今回の自動取り込みで取り込み終わった日（取り込み日、取り戻した日の順）と、取り戻そうとした日（2026-11-04）。
  final _finishedDays = <String>[];
  final _gapTried = <String>{};
  // 0時に自動取り込みを始める予約（2026-10-26 利用者指定、案A）。ONは端末に保存し、この画面を
  // 開いている間、毎日0時に前日（3時までの営業日）を指定して自動取り込みをONにする。待つ間は画面を
  // 消さずに暗くするだけで、常駐サービスは使わない（Android 15以降の1日6時間の上限を待ち時間で使わない）。
  // 自動取り込み自体のONは従来どおり保存しない（開いた直後はOFF）。
  bool _midnightEnabled = false;
  DateTime? _midnightArmedFor;
  DateTime? _midnightRetryAt;
  int _midnightReopens = 0;
  bool _midnightStarting = false;
  // 予約を待つ間の画面（null＝普段どおり、'bright'＝消さない、'dim'＝消さずに暗く）。
  // 23時までは明るさを変えない（昼に開いても暗くならない）。0時に始めた分が終わったら手放し、
  // スマホを操作してアプリに戻ったときから、また次の0時を待つ（取り込み後に朝まで点けっぱなしにしない）。
  String? _waitingScreen;
  bool _releasedAfterRun = false;
  bool _firedTonight = false;
  DateTime _now() => widget.now?.call() ?? DateTime.now();
  // 日付指定取り込み：取り込む営業日（null＝サイトの表示どおり）と、機種を数える向き
  // （top＝一覧の上から、bottom＝下から）。起動のたびに戻る。日本時間の午前3時で営業日が変わる。
  String? _targetDay;
  String _direction = 'top';
  // {日付: 今回の取り込みで最初に保存したページのサイトの更新時刻}。これより古い数値の機種は取り直す。
  // 画面を開いている間（手動の取り込みも）続き、自動取り込みをONにするたびに作り直す。
  final Map<String, String> _freshSince = {};
  // イベント名（自由記入、2026-10-06）。日付指定の日、指定なしなら今の営業日の分を出して編集する。
  String? _eventName;
  String? _eventShownDay;
  bool _eventLoading = false;

  String get _eventDay => _targetDay ?? pscubeBusinessDay(widget.now?.call());

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _web = WebViewController();
    unawaited(_prepareBrowser());
    _autoTimer = Timer.periodic(const Duration(milliseconds: 100), (_) {
      // 表示中のイベント名の日が変わった（日付指定・その日の完了・午前3時）ら読み直す。
      if (_store != null && _eventShownDay != _eventDay && !_eventLoading) {
        _eventLoading = true;
        unawaited(_loadEvent());
      }
      _midnightTick();
      _updateWaitingScreen();
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
        blockRequests: () => blockYouTubeRequests(_web),
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
    final wasAuto = _auto.enabled;
    // Invalidate a capture already reading the DOM, before any awaited work.
    _page++;
    _auto.turnOff();
    if (wasAuto) {
      unawaited(notifyCaptureResult('P’s CUBE：取り込みが止まりました', '通信エラー：$message'));
    }
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
      final store = await (widget.openStore?.call() ?? PscubeStore.open());
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
      final upload = PscubeDayUploadSetting.fromJson(
        await store.dayUploadSetting(),
      );
      final lastUpload = await store.lastDayUpload();
      final midnight = await store.midnightAutoEnabled();
      if (!mounted) {
        await store.close();
        return;
      }
      setState(() {
        _store = store;
        _script = script;
        _probe = probe;
        _lastBackup = backedUp;
        _upload = upload;
        _lastUpload = lastUpload;
        _midnightEnabled = midnight;
        _midnightArmedFor = midnight ? pscubeNextMidnight(_now()) : null;
        unawaited(_refreshWidget(store));
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
          note:
              'ここで入れたイベントは、記録のある貸玉すべてに付きます。PC・閲覧ページへは'
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
    WidgetsBinding.instance.removeObserver(this);
    _auto.turnOff();
    _autoTimer?.cancel();
    if (Platform.isAndroid) {
      unawaited(_autoService.invokeMethod<void>('stop').catchError((_) {}));
    }
    final store = _store;
    if (store != null) unawaited(store.close());
    super.dispose();
  }

  Future<void> _showFullList({int? expectedCount, int? page}) async {
    var shown = -1;
    final watch = Stopwatch()..start();
    try {
      await _waitFullList(expectedCount, page, (count) => shown = count);
    } finally {
      // 機種一覧（台数不明）を何件まで表示できたか・何秒かかったかを残す（2026-11-04、0時の取り込みだけ
      // 機種一覧が途中で止まる原因を調べるため。時間切れのときも残す）。
      if (expectedCount == null && shown >= 0) {
        unawaited(
          noteErrorLog(
            'pscube.list',
            '機種一覧を$shown件まで表示（${watch.elapsed.inSeconds}秒）',
          ),
        );
      }
    }
  }

  Future<void> _waitFullList(
    int? expectedCount,
    int? page,
    void Function(int) seen,
  ) => waitForPscubeList(
    expectedCount: expectedCount,
    isCurrent: () => mounted && (page == null || _page == page),
    scroll: (action) async {
      // 1回の問い合わせで、決められた動きを1つだけ行い、台数と位置を返す。
      // 動かしたら scroll の通知を出す。サイトの続きの読み込み（jquery.inview）は、その通知が来たときだけ
      // 位置を取り直す（PC版 `SCROLL_SCRIPT` の 2026-10-28 の修正。Androidには入っていなかった。2026-11-03）。
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
          ${move.isEmpty ? '' : "window.dispatchEvent(new Event('scroll'));"}
          const count = $countJs;
          const bottom = window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 4;
          return count + '|' + (bottom ? 1 : 0);
        })()
      ''');
      final parts = result.toString().replaceAll('"', '').split('|');
      final count = int.tryParse(parts.first) ?? -1;
      seen(count);
      return (count: count, atBottom: parts.length > 1 && parts[1] == '1');
    },
  );

  /// サイトの中のページから次のページへは、リンクをたどるのと同じ形（ページ内で移動）で
  /// 開く。アドレスを直接開くと「どのページから来たか」が付かず、普通のブラウザと
  /// 違って見えるため（PC版も同じ形）。サイトの外にいるときだけ直接開く。
  Future<bool> _open(String url, {bool reload = false}) async {
    if (!_browserReady || _busy || _opening) return false;
    final target = Uri.parse(url);
    if (!PscubeConnection.allowedPage(target)) {
      throw const FormatException('対象のP’s CUBEページではありません。');
    }
    setState(() => _opening = true);
    try {
      final current = Uri.tryParse(await _web.currentUrl() ?? '');
      if (!mounted) return false;
      final insidePage =
          _connection.canCapture && current?.host == 'www.pscube.jp';
      _connection.start(url);
      _page++;
      _auto.nextPage(_page);
      setState(() => _loading = true);
      if (insidePage && reload) {
        await _web.runJavaScript('location.reload()');
      } else if (insidePage) {
        await _web.runJavaScript('location.assign(${jsonEncode(url)})');
      } else {
        await _web.loadRequest(target);
      }
      return true;
    } catch (_) {
      if (mounted) {
        setState(() {
          _loading = false;
          _status = 'ページへ移動できませんでした。「もう一度開く」を試してください。';
        });
      }
      return false;
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
    // 利用者がONにしたときだけ通知の許可を聞く（0時の予約で始めるときに聞くと、確認の画面で止まるおそれがある）。
    if (!_midnightStarting) unawaited(requestCaptureNotices());
    try {
      if (Platform.isAndroid) await _autoService.invokeMethod<void>('start');
      if (!mounted || _connection.failure != null || _opening) {
        if (Platform.isAndroid) await _autoService.invokeMethod<void>('stop');
        return;
      }
      _autoDone.clear();
      _autoFailures.clear();
      _autoHeld.clear();
      _listRetries.clear();
      _finishedDays.clear();
      _gapTried.clear();
      _store?.resetIndexConfirmation();
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
    _store?.resetIndexConfirmation();
    // 「すべて取り込みました」などで止まった時刻を、一覧の件数と並べて読めるよう残す（2026-11-04）。
    unawaited(noteErrorLog('pscube.auto.stop', message));
    if (mounted) setState(() => _autoStatus = message);
    if (Platform.isAndroid) {
      try {
        await _autoService.invokeMethod<void>('stop');
      } catch (error) {
        // 常駐（通知）が残る原因を後から調べられるよう、端末のログに残す。
        debugPrint('自動取り込みの常駐を止められませんでした：$error');
      }
    }
    // 常駐を止めると画面も普段どおりに戻る。予約中は次の0時まで画面を消さずに暗くしておく。
    // 常駐を止めると画面も普段どおりに戻る。0時に始めた分が終わったら、次に操作されるまで画面を手放す。
    _waitingScreen = null;
    if (_firedTonight) {
      _firedTonight = false;
      _releasedAfterRun = true;
    }
  }

  /// 0時の予約を待つ間の画面（常駐サービスは起こさない）。周期Timerから呼び、変わったときだけ切り替える。
  void _updateWaitingScreen() {
    if (_auto.enabled || _autoChanging) return; // 取り込み中は常駐の設定（消さずに暗く）。
    final want = pscubeWaitingScreen(
      reserved: _midnightEnabled,
      released: _releasedAfterRun,
      now: _now(),
    );
    if (want == _waitingScreen) return;
    _waitingScreen = want;
    if (!Platform.isAndroid) return;
    unawaited(
      _autoService
          .invokeMethod<void>('keepScreen', {
            'on': want != null,
            'dim': want == 'dim',
          })
          .catchError((_) {}),
    );
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed && _releasedAfterRun) {
      _releasedAfterRun = false; // 操作されたので、また次の0時を待つ。
    }
  }

  Future<void> _setMidnight(bool enabled) async {
    final store = _store;
    if (store == null) return;
    if (enabled) unawaited(requestCaptureNotices());
    try {
      await store.setMidnightAutoEnabled(enabled);
    } catch (error) {
      _autoMessage('0時の予約を保存できませんでした：$error');
      return;
    }
    if (!mounted) return;
    setState(() {
      _midnightEnabled = enabled;
      _midnightArmedFor = enabled ? pscubeNextMidnight(_now()) : null;
      _midnightRetryAt = null;
      _midnightReopens = 0;
      _releasedAfterRun = false;
    });
  }

  /// 予約の0時を過ぎたら、前日の営業日を指定して自動取り込みをONにする。サイトとの接続が切れていれば
  /// 1分おきに3回まで開き直す。3時（営業日の切り替え）を過ぎたら、その夜は始めずに次の0時を待つ。
  void _midnightTick() {
    final armed = _midnightArmedFor;
    if (!mounted || !_midnightEnabled || armed == null || _midnightStarting) {
      return;
    }
    final now = _now();
    final due = pscubeMidnightDue(now, armed);
    if (due == null) return;
    if (due == PscubeMidnight.missed) {
      _rearmMidnight(now, '0時の予約：3時までに始められませんでした。次の0時に始めます。');
      unawaited(
        notifyCaptureResult('P’s CUBE：0時の予約', '3時までに始められませんでした。次の0時に始めます。'),
      );
      return;
    }
    if (_auto.enabled) {
      _rearmMidnight(now, null); // 手動で動かしている。今夜は何もしない。
      return;
    }
    final retryAt = _midnightRetryAt;
    if (retryAt != null && now.isBefore(retryAt)) return;
    if (_autoChanging || _opening || _busy || _store == null) return;
    if (!_browserReady || _connection.failure != null) {
      if (_midnightReopens >= 3) {
        _rearmMidnight(now, '0時の予約：ページを開き直せず、今夜は始めませんでした。次の0時に始めます。');
        unawaited(
          notifyCaptureResult(
            'P’s CUBE：0時の予約',
            'ページを開き直せず、今夜は始めませんでした。次の0時に始めます。',
          ),
        );
        return;
      }
      _midnightReopens++;
      _midnightRetryAt = now.add(const Duration(minutes: 1));
      unawaited(_retryPage());
      return;
    }
    final day = due as String;
    _midnightStarting = true;
    unawaited(_startMidnight(day, armed));
  }

  Future<void> _startMidnight(String day, DateTime armed) async {
    bool current() =>
        mounted &&
        _midnightEnabled &&
        _midnightArmedFor == armed &&
        _now().isBefore(
          armed.add(const Duration(hours: pscubeBusinessDayCutoffHour)),
        );
    try {
      final url = await _web.currentUrl();
      if (!current() || _auto.enabled) return;
      setState(() => _targetDay = day);
      // 前日の全台一覧・台別を残したままでも、既存の機種一覧から全機種を対象日に巡る。
      // 認証の操作やCookieの初期化は行わず、通常の移動と既存の日付照合を使う。
      if (!_samePage(PscubeStore.index, url)) {
        if (!await _open(PscubeStore.index)) {
          if (current()) _retryMidnightStart('機種一覧を開けませんでした');
          return;
        }
        if (!current() || _auto.enabled) return;
      }
      await _toggleAuto();
      if (!current()) {
        if (mounted && _auto.enabled) await _stopAuto('0時の予約を取り消しました');
        return;
      }
      if (_auto.enabled) {
        _firedTonight = true;
        _rearmMidnight(_now(), 'ON・0時の予約で${shortDayLabel(day)}の分を始めました');
      } else {
        _retryMidnightStart(_autoStatus);
      }
    } catch (error) {
      if (current()) _retryMidnightStart(error.toString());
    } finally {
      _midnightStarting = false;
    }
  }

  void _retryMidnightStart(String reason) {
    _midnightReopens++;
    if (_midnightReopens >= 3) {
      _rearmMidnight(_now(), '0時の予約：3回試しても始められませんでした。次の0時を待ちます：$reason');
      unawaited(
        notifyCaptureResult(
          'P’s CUBE：0時の予約',
          '3回試しても始められませんでした。次の0時を待ちます：$reason',
        ),
      );
      return;
    }
    _midnightRetryAt = _now().add(const Duration(minutes: 1));
    _autoMessage('0時の予約：開始できませんでした。1分後に再試行します：$reason');
  }

  String _midnightNote() {
    final armed = _midnightArmedFor;
    if (!_midnightEnabled || armed == null) return '';
    String iso(DateTime d) =>
        '${d.year}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';
    final day = iso(armed.subtract(const Duration(days: 1)));
    return '0時の予約：${shortDayLabel(iso(armed))} 0:00に${shortDayLabel(day)}の分を開始。'
        'この画面を前に出したまま充電（画面は消さず、23時から暗く）';
  }

  void _rearmMidnight(DateTime now, String? message) {
    setState(() {
      _midnightArmedFor = pscubeNextMidnight(now);
      _midnightRetryAt = null;
      _midnightReopens = 0;
    });
    if (message != null) _autoMessage(message);
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
        _elapsed(),
        targetDay: _targetDay,
      );
      if (decision.stop) {
        await _stopAuto(decision.message);
        unawaited(
          notifyCaptureResult('P’s CUBE：取り込みが止まりました', decision.message),
        );
        return;
      }
      final probed = probe is Map ? probe['signature'] : null;
      final held = _autoHeld[probed];
      _autoMessage(
        decision.capture == null &&
                held != null &&
                (_autoFailures[probed] ?? 0) >= pscubeAutoMaxFailures
            ? held
            : decision.message,
      );
      final signature = decision.capture;
      if (signature != null) {
        await _capture(autoSignature: signature, autoToken: token);
      }
    } catch (error) {
      if (_auto.current(token, page)) {
        unawaited(noteErrorLog('pscube.auto.tick', error));
        _autoMessage('ON・待機：$error');
      }
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
            '${result.skipped ?? '${result.kind}を保存しました'}。残り ${result.remaining} 件。'
                '${netWarning == null ? '' : '（$netWarning）'}';
      });
      if (autoSignature != null) {
        _autoDone.add(autoSignature);
        _autoFailures.remove(autoSignature);
        _autoHeld.remove(autoSignature);
        _listRetries.remove(autoSignature);
        if (_auto.enabled && result.nextUrl == null) {
          final day = _targetDay ?? await store.lastDay();
          if (day != null && !_finishedDays.contains(day))
            _finishedDays.add(day);
          // 抜けた日（その日の未取得が残っている直近の日）があれば、止めずにその日を取り戻す（2026-11-04）。
          final gap = day == null ? null : await _gapDay(store, day);
          if (gap != null && _auto.enabled && _page == page) {
            _gapTried.add(gap.day);
            setState(() => _targetDay = gap.day);
            _autoMessage(
              'ON・${_md(day!)}の分を取り込みました。抜けていた${_md(gap.day)}の分を取り戻します（残り${gap.remaining}件）',
            );
            unawaited(
              noteErrorLog(
                'pscube.gap',
                '${gap.day}を取り戻す（残り${gap.remaining}件、$dayの後）',
              ),
            );
            setState(() => _busy = false);
            await _open(pscubeTableUrlForDay(gap.url, gap.day));
            return;
          }
          setState(() => _targetDay = null);
          final days = [..._finishedDays];
          _finishedDays.clear();
          _gapTried.clear();
          final label = days.isEmpty ? null : days.map(_md).join('・');
          await _stopAuto(
            label == null
                ? 'すべて取り込みました（自動取り込みを停止しました）'
                : '$labelの分をすべて取り込みました（自動取り込みを停止しました）',
          );
          // 取り込み終わった日の分だけをDriveへ送り（設定があるときだけ。失敗しても取り込みは済んでいる）、
          // 結果を通知で知らせる。
          unawaited(_finishNight(store, days));
        } else if (_auto.enabled) {
          _autoMessage(
            'ON・${result.skipped ?? '${result.kind}を保存'}・残り${result.remaining}件・次のページへ'
            '${netWarning == null ? '' : '（差枚は未取得）'}',
          );
        }
      }
      if (result.nextUrl != null && _page == page && _connection.canCapture) {
        // The save has finished. _open itself still rejects a concurrent save.
        setState(() => _busy = false);
        await _open(result.nextUrl!);
      }
    } on PscubeIndexRetry catch (error) {
      if (mounted && autoSignature != null && _auto.enabled && _page == page) {
        final counts = error.short
            ? 'いつもの${error.usual}機種に対して${error.shown}機種'
            : '前回の${error.previous}機種に対して${error.shown}機種';
        unawaited(
          noteErrorLog(
            'pscube.index',
            '${(_listRetries[autoSignature] ?? 0) + 1}回目：機種一覧が少ない（$counts）',
          ),
        );
        await _retryList(
          autoSignature,
          store,
          error.short ? '機種一覧が途中までしか読めていません（$counts）' : '機種一覧が前回より少ない（$counts）',
        );
      } else {
        // 保存中に自動取り込みを止めた・ページが替わったとき：開き直さず、保存しなかったことだけ示す。
        store.resetIndexConfirmation();
        if (mounted) setState(() => _status = '$error（保存していません）');
      }
    } catch (error) {
      if (mounted) {
        setState(
          () => _status = _connection.failure?.message ?? '保存できませんでした：$error',
        );
      }
      if (autoSignature != null &&
          _auto.enabled &&
          _page == page &&
          error is FormatException &&
          error.message == pscubeListTimeoutMessage) {
        // 一覧のスクロールが120秒で終わらなかったときも、止めずに読み直す（2026-11-04）。
        unawaited(
          noteErrorLog(
            'pscube.list',
            '${(_listRetries[autoSignature] ?? 0) + 1}回目：一覧の読み込みが時間切れ',
          ),
        );
        await _retryList(autoSignature, store, '一覧の読み込みが時間切れ');
      } else if (autoSignature != null && _auto.enabled) {
        final count = (_autoFailures[autoSignature] ?? 0) + 1;
        _autoFailures[autoSignature] = count;
        unawaited(noteErrorLog('pscube.save', '$count回目：$error'));
        if (count >= pscubeAutoMaxFailures) {
          _autoHeld[autoSignature] =
              'ON・同じページで3回失敗したため待機中（3回目：$error）。内容を確かめて手動で取り込むか、OFF→ONで再開';
          unawaited(
            notifyCaptureResult(
              'P’s CUBE：取り込みが止まっています',
              '同じページで3回失敗しました：$error',
            ),
          );
        }
        _autoMessage('ON・保存できませんでした（$count回目）：$error');
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// 一覧が進まない（機種一覧が足りない・一覧の読み込みが時間切れ）ときは、3回で止めずに読み直す（2026-11-04、
  /// 利用者「進まない場合は停止じゃなくて読み込み直ししてスクロール作業するようにしてね」）。
  /// 次の見張りの回に同じページのまま下まで送り直して読み直し、[pscubeListReloadEvery] 回に1回だけページを
  /// 読み込み直す。同じページの読み直しはサイトへの通信を増やさない（続きの機種はサイトが最初に受け取った
  /// データから足す。`database/PSCUBE_AUTO_CAPTURE.md` の 2026-10-28）。0時の回で止まった一覧が、手で下まで
  /// 送ると最後の機種まで出ていた。[pscubeListMaxRetries] 回（約20分）で待機し、一晩じゅう読み込み直さない。
  Future<void> _retryList(
    String signature,
    PscubeStore store,
    String detail,
  ) async {
    final count = (_listRetries[signature] ?? 0) + 1;
    _listRetries[signature] = count;
    if (count >= pscubeListMaxRetries) {
      store.resetIndexConfirmation();
      _autoFailures[signature] = pscubeAutoMaxFailures; // 見張りは、このページをもう読まずに待つ
      final message =
          'ON・$detail。$count回読み直しても進みませんでした。待機中'
          '（一覧を一番下まで表示して手動で取り込むか、OFF→ONで再開）';
      _autoHeld[signature] = message;
      _autoMessage(message);
      unawaited(
        notifyCaptureResult(
          'P’s CUBE：取り込みが止まっています',
          '$detail。$count回読み直しても進みませんでした。',
        ),
      );
      return;
    }
    if (count % pscubeListReloadEvery != 0) {
      _autoMessage('ON・$detail。同じページで下まで送り直します（$count回目）');
      return;
    }
    _autoMessage('ON・$detail。ページを読み込み直してスクロールし直します（$count回目）');
    final url = await _web.currentUrl();
    if (!mounted) return;
    setState(() => _busy = false);
    if (url == null || !await _open(url, reload: true)) {
      store.resetIndexConfirmation();
    }
  }

  /// バックアップを書き出して保存する（Googleドライブの「database共有」へ保存すると、
  /// PC版が読み込める）。保存を取りやめたときは「書き出し済み」にしない。
  Future<void> _share() async {
    final store = _store;
    if (store == null || _busy) return;
    setState(() => _busy = true);
    try {
      final file = await store.exportViewer();
      if (!mounted) return;
      final fileName = file.uri.pathSegments.last;
      final savedToDestination = await saveBackup(file);
      if (!mounted) return;
      if (!savedToDestination) {
        setState(() => _status = '保存を取りやめました。バックアップ済みにはしていません。');
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
      _autoHeld.clear();
      _listRetries.clear();
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

  Future<void> _showCaptureHealth() async {
    final store = _store;
    if (store == null) return;
    try {
      final rows = await store.healthRecords(_targetDay),
          status = await store.syncStatus();
      if (!mounted) return;
      await showCaptureHealth(
        context,
        records: rows,
        syncStatus: status,
        day: rows.isEmpty ? _targetDay : rows.first['day'] as String,
        pscube: true,
      );
    } catch (error) {
      if (mounted) setState(() => _status = '取得状況を読めませんでした：$error');
    }
  }

  Future<({bool ok, String message})> _sendDay(
    PscubeStore store,
    String day,
    PscubeDayUploadSetting setting,
  ) async {
    if (mounted) setState(() => _lastUpload = {'day': day, 'sending': true});
    final result = await uploadPscubeDay(store, day, setting);
    final last = await store.lastDayUpload();
    if (mounted) {
      setState(() {
        _lastUpload = last;
        if (!result.ok) _status = result.message;
      });
    }
    return result;
  }

  /// 状態の文に使う短い日付（例 10/18。これまでの「◯/◯の分をすべて取り込みました」と同じ形）。
  static String _md(String day) =>
      '${int.parse(day.substring(5, 7))}/${int.parse(day.substring(8))}';

  /// 抜けた日を探す（2026-11-04、利用者が選んだ「抜けた日を自動で取り戻す」）。[day] の前の6日（サイトの
  /// 台別ページが持つ7日の範囲）のうち、記録のある最初の日より後で、その日の未取得が残る日を新しい順に1つ。
  /// 今回すでに取り込んだ日・取り戻そうとした日は除く（同じ日をくり返さない）。抜けが無ければ何もしない
  /// （サイトへの通信も増えない）。
  Future<({String day, String url, int remaining})?> _gapDay(
    PscubeStore store,
    String day,
  ) async {
    final first = await store.firstDay();
    if (first == null) return null;
    final base = DateTime.parse(day);
    for (var back = 1; back < pscubeGapDays; back++) {
      final d = base.subtract(Duration(days: back));
      final iso =
          '${d.year}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';
      if (iso.compareTo(first) < 0) break;
      if (_gapTried.contains(iso) || _finishedDays.contains(iso)) continue;
      final next = await store.nextTarget(iso, _direction);
      if (next.url != null && next.remaining > 0) {
        return (day: iso, url: next.url!, remaining: next.remaining);
      }
    }
    return null;
  }

  /// ホーム画面のウィジェットの翌日候補（2026-11-04）。P’s CUBEの記録の最新の日の候補を、結果画面と同じ
  /// 計算で出す。画面を開いたときと、自動取り込みが終わったときに書き換える。
  Future<void> _refreshWidget(PscubeStore store) async {
    try {
      final records = pscubeViewerRecords(await store.calendarData());
      if (records.isEmpty) return;
      await updateHomeWidgetCandidates(
        await compute(homeWidgetCandidates, records),
      );
    } catch (error) {
      unawaited(noteErrorLog('widget', error));
    }
  }

  /// 取り込み終わった日をDriveへ送り（設定があるときだけ）、結果を通知で知らせる。
  Future<void> _finishNight(PscubeStore store, List<String> days) async {
    unawaited(_refreshWidget(store));
    final lines = <String>[];
    var ok = true;
    for (final day in days) {
      final rows = await store.healthRecords(day);
      final machines = {
        for (final r in rows) '${r['store']}|${r['rate']}|${r['machine']}',
      };
      var line = '${shortDayLabel(day)}：${machines.length}機種・${rows.length}台';
      final upload = _upload;
      if (upload != null && upload.enabled) {
        final sent = await _sendDay(store, day, upload);
        ok = ok && sent.ok;
        line += sent.ok ? '・Driveへ送信済み' : '・Driveへ送れませんでした（${sent.message}）';
      }
      lines.add(line);
    }
    await notifyCaptureResult(
      ok ? 'P’s CUBE：取り込み完了' : 'P’s CUBE：取り込み完了（Driveへの送信に失敗あり）',
      [
        ...lines,
        if (days.length > 1)
          '抜けていた${days.skip(1).map(shortDayLabel).join('・')}の分も取り戻しました。',
      ].join('\n'),
    );
  }

  /// 当日分の自動送信の設定（スクリプトのURL・合言葉）と、今の日の分を手で送る。
  Future<void> _uploadSettings() async {
    final store = _store;
    if (store == null) return;
    final url = TextEditingController(text: _upload?.url ?? '');
    final key = TextEditingController(text: _upload?.key ?? '');
    var enabled = _upload?.enabled ?? true;
    String? problem;
    final action = await showDialog<String>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, update) => AlertDialog(
          title: const Text('当日分をDriveへ自動で送る'),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Text(
                  '自動取り込みが「すべて取り込みました」で止まったら、その日の記録だけをGoogleのスクリプト経由で'
                  'Driveの「database共有」へ送ります。PC版は起動中にそれを自動で読み込みます。',
                ),
                const SizedBox(height: 8),
                TextField(
                  controller: url,
                  keyboardType: TextInputType.url,
                  decoration: const InputDecoration(
                    labelText: 'スクリプトのURL',
                    hintText: 'https://script.google.com/macros/s/…/exec',
                  ),
                ),
                TextField(
                  controller: key,
                  obscureText: true,
                  decoration: const InputDecoration(
                    labelText: '合言葉（スクリプトの PSCUBE_UPLOAD_KEY と同じ）',
                  ),
                ),
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('取り込み終わったら自動で送る'),
                  value: enabled,
                  onChanged: (v) => update(() => enabled = v),
                ),
                if (problem != null)
                  Text(
                    problem!,
                    style: TextStyle(
                      color: Theme.of(context).colorScheme.error,
                    ),
                  ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, 'clear'),
              child: const Text('設定を消す'),
            ),
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('閉じる'),
            ),
            TextButton(
              onPressed: () {
                final error = PscubeDayUploadSetting.problem(
                  url.text,
                  key.text,
                );
                if (error != null) return update(() => problem = error);
                Navigator.pop(context, 'send');
              },
              child: const Text('保存して今の日を送る'),
            ),
            FilledButton(
              onPressed: () {
                final error = PscubeDayUploadSetting.problem(
                  url.text,
                  key.text,
                );
                if (error != null) return update(() => problem = error);
                Navigator.pop(context, 'save');
              },
              child: const Text('保存'),
            ),
          ],
        ),
      ),
    );
    if (action == null || !mounted) return;
    if (action == 'clear') {
      await store.setDayUploadSetting(null);
      if (mounted) setState(() => _upload = null);
      return;
    }
    final setting = PscubeDayUploadSetting(
      url: url.text.trim(),
      key: key.text.trim(),
      enabled: enabled,
    );
    await store.setDayUploadSetting(setting.toJson());
    if (!mounted) return;
    setState(() => _upload = setting);
    if (action == 'send') {
      final day = _targetDay ?? await store.lastDay();
      if (day == null) {
        if (mounted) {
          setState(() => _status = '送る日がありません（まだ全台一覧を保存していません）。');
        }
        return;
      }
      await _sendDay(store, day, setting);
    }
  }

  String get _uploadText {
    final upload = _upload, last = _lastUpload;
    if (upload == null) return 'Driveへの当日分の自動送信：未設定';
    if (last == null) {
      return 'Driveへの当日分の自動送信：${upload.enabled ? 'ON' : 'OFF'}・まだ送っていません';
    }
    if (last['sending'] == true) return 'Driveへ当日分を送っています…';
    final at = DateTime.tryParse('${last['at']}')?.toLocal();
    String two(int v) => v.toString().padLeft(2, '0');
    final when = at == null
        ? ''
        : '（${at.month}/${at.day} ${two(at.hour)}:${two(at.minute)}）';
    return '${last['message']}$when';
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
          tooltip: '当日分をDriveへ自動で送る（設定・今すぐ送る）',
          onPressed: _busy || _store == null ? null : _uploadSettings,
          icon: const Icon(Icons.cloud_upload_outlined),
        ),
        IconButton(
          tooltip: 'バックアップを保存（初回はDriveの「database共有」を選択）',
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
              Text(_uploadText, style: Theme.of(context).textTheme.bodySmall),
              Align(
                alignment: Alignment.centerLeft,
                child: TextButton.icon(
                  onPressed: _store == null || _busy
                      ? null
                      : _showCaptureHealth,
                  icon: const Icon(Icons.info_outline),
                  label: const Text('更新・差枚の取得状況'),
                ),
              ),
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
              Row(
                children: [
                  Expanded(
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
                  const SizedBox(width: 8),
                  // 0時の予約（2026-10-26）。下のサイトの表示を狭くしないよう、ボタン1つにまとめる。
                  Tooltip(
                    message: '0時に自動取り込みを始める（予約）',
                    child: FilledButton.icon(
                      key: const ValueKey('pscube-midnight-auto'),
                      style: FilledButton.styleFrom(
                        backgroundColor: _midnightEnabled
                            ? AppColors.appleBlue
                            : AppColors.ash,
                        foregroundColor: Colors.white,
                        minimumSize: const Size(0, 48),
                        padding: const EdgeInsets.symmetric(horizontal: 12),
                      ),
                      onPressed: _store == null
                          ? null
                          : () => unawaited(_setMidnight(!_midnightEnabled)),
                      icon: Icon(
                        _midnightEnabled ? Icons.alarm_on : Icons.alarm_off,
                      ),
                      label: Text('0時：${_midnightEnabled ? '予約' : 'なし'}'),
                    ),
                  ),
                ],
              ),
              if (_midnightEnabled) ...[
                Text(
                  _midnightNote(),
                  style: Theme.of(context).textTheme.bodySmall,
                ),
                // 下の欄の見出し（枠の上に重なる）と重ならないように空ける。
                const SizedBox(height: 8),
              ],
              // 日付指定取り込み：取り込む営業日を決める（日本時間の午前3時までは前日）。
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
                  for (final (i, day) in pscubeRecentBusinessDays(
                    widget.now?.call(),
                  ).indexed)
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
