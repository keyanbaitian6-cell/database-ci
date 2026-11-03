import 'dart:convert';
import 'dart:async';
import 'dart:io';

export 'excluded_machines.dart';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:image/image.dart' as imglib;
import 'package:path_provider/path_provider.dart';
import 'package:webview_flutter/webview_flutter.dart';
import 'package:webview_flutter_android/webview_flutter_android.dart';

import 'capture_flow.dart';
import 'capture_notice.dart';
import 'error_log.dart';
import 'excluded_machines.dart';
import 'browser_session.dart';
import 'auto_capture_state.dart';
import 'page_readiness.dart';
import 'import_service.dart';
import 'models.dart' show isValidRecordDay, storeDisplayName, storeNames;
import 'theme.dart';
import 'web_extraction_channel.dart';
import 'youtube_request_block.dart';
import 'import_day.dart';
import 'list_views.dart' show shortDayLabel;

class WebTableExtraction {
  const WebTableExtraction({
    required this.sourceUrl,
    required this.store,
    required this.day,
    required this.machine,
    required this.expectedCount,
    required this.rows,
  });

  final String sourceUrl;
  final String? store;
  final String? day;
  final String? machine;
  final int? expectedCount;
  final List<EditableRow> rows;
}

/// 確認画面を出さずに保存してよい表か。
///
/// 店舗・日付・機種名がそろっているときだけ。欠けたまま保存すると、今日の
/// 日付や空の機種名で保存されてしまう（PC版は同じ場合に保存せずエラーにする）。
/// 読み取った店舗・日付・台番号が、実際に表示しているページのURLと食い違う
/// ときの理由（食い違いがなければ null）。ページから返ってきた値をそのまま
/// 信じず、Dart 側で確かめる。URLそのものが取れないときは保存しない。
/// URLに日付・台番号が無いときは、その項目だけ確かめずに通す。
String? pageMismatch(
  String? currentUrl, {
  String? store,
  String? day,
  int? rack,
}) {
  // URLを取れないときは、ページから返ってきた値を確かめようがないので保存
  // しない（取り込みは人が押したときだけなので、押し直せばよい）。
  final uri = currentUrl == null ? null : Uri.tryParse(currentUrl);
  if (uri == null) {
    return '表示中のページの場所（URL）を確かめられませんでした。表示が終わってから、もう一度押してください。';
  }
  final urlStore = uri.pathSegments.isEmpty ? null : uri.pathSegments.first;
  if (!storeNames.containsKey(urlStore)) return '対象店舗のページではありません。';
  if (store != null && store != urlStore) {
    return 'ページの店舗と読み取った店舗が違います。保存しませんでした。';
  }
  Map<String, String> fragment;
  try {
    fragment = Uri.splitQueryString(uri.fragment);
  } on FormatException {
    fragment = const {};
  }
  final rawDay = uri.queryParameters['target_date'] ?? fragment['database_day'];
  final urlDay = rawDay?.replaceAll('/', '-');
  if (day != null && isValidRecordDay(urlDay) && day != urlDay) {
    return 'ページの日付（$urlDay）と読み取った日付（$day）が違います。保存しませんでした。';
  }
  final urlRack = int.tryParse(uri.queryParameters['rack_no'] ?? '');
  if (rack != null && urlRack != null && rack != urlRack) {
    return 'ページの台番号（$urlRack）と読み取った台番号（$rack）が違います。保存しませんでした。';
  }
  return null;
}

bool canSaveWithoutReview(WebTableExtraction extraction) =>
    extraction.store != null &&
    isValidRecordDay(extraction.day) &&
    (extraction.machine ?? '').trim().isNotEmpty;

/// 埋め込みの YouTube 動画か。取り込みでは動画を再生しないため、内部ブラウザでは
/// 表示しない（通信量と画面の場所を取らないように）。判定は [_hideYouTubeScript]
/// の JS と同じ規則。通信そのものは youtube_request_block.dart で端末の中で止め、
/// この JS は空になった枠を詰めるために残す（PCと同じ分担）。
final _youTubeUrlPattern = RegExp(
  r'^(https?:)?//([a-z0-9-]+\.)*(youtube\.com|youtube-nocookie\.com|youtu\.be)(/|$)',
  caseSensitive: false,
);

bool isYouTubeUrl(String? url) => _youTubeUrlPattern.hasMatch(url ?? '');

/// 今日の日付（yyyy-MM-dd）。サイトの機種一覧ページには日付が無いので、
/// そのページの取り込み状況（印・進み具合）は、サイトの日付選択の初期値と同じ
/// 「今日」で判定する（以前は保存済みの最新日だったため、今日の分を消すと
/// 前日の「済」が出て紛らわしかった）。
///
/// 営業日は深夜3時で切り替わる。0時〜3時は前日の日付を返す（例：9/22の27時＝
/// 9/23 2:59 までは 2026-09-22）。PC版 `today_iso` と同じ規則。
String todayIso([DateTime? now]) {
  final day = (now ?? DateTime.now()).subtract(
    const Duration(hours: businessDayCutoffHour),
  );
  String two(int value) => value.toString().padLeft(2, '0');
  return '${day.year}-${two(day.month)}-${two(day.day)}';
}

/// 営業日の切り替えは3時。翌日候補の比較・評価の締切（2026-10-25の比較計画と
/// 旧focus計画の `focusCutoffHour`）は、2026-10-28から別に翌日8時（3店舗の最も早い開店時刻）。
const businessDayCutoffHour = 3;

/// 機種一覧の見出し行（「機種名 台数 通常順 ピックアップ順」）か。
/// 実サイトでは見出し行も機種の行と同じ tr.teram2-link-block で描画される。
bool isListHeaderName(String? name) {
  final text = (name ?? '').replaceAll(RegExp(r'\s+'), '');
  return text.startsWith('機種名') && text.contains('台数');
}

/// 1000円46枚スロット（kind_code=21）の対象になりうるURLか。
///
/// 種別が明示されていて21以外（低貸しの10・5）なら対象外。旧形式のリンクは
/// 種別を持たないことがあるので、無いものは対象外にしない（表の保存時にも
/// 21以外は拒否している）。
bool isTargetKindUrl(String url) {
  final kind = Uri.tryParse(url)?.queryParameters['kind_code'];
  return kind == null || kind == '21';
}

/// 機種一覧に出ている台数から見て、表を取り込み直すべきか。
///
/// 一覧の台数が保存台数より「多い」ときだけ（増台・取りこぼし）。一覧は今の
/// 設置台数なので、減台後に前日分を取り込むと保存台数の方が多くなる。取り込み
/// 直しても台は上書きされるだけで消えないため、「少ない」を台数変更として扱うと
/// 何度押しても同じ機種へ戻され、後ろの機種へ進めなくなる（PC版も同じ判定）。
bool listedCountNeedsReimport({required int? listed, required int saved}) =>
    listed != null && listed > saved;

/// WebViewから返ったJavaScriptの結果を、Mapとして読む。
///
/// 端末やWebViewによって、結果は JSON文字列・二重にJSON化された文字列・null・
/// 空文字のどれでも返りうる。どの場合も、原因の分かる日本語で失敗させる
/// （以前は null で Dart の型エラーが出て、利用者には意味が分からなかった）。
/// スクリプトが `{error: ...}` を返したときは、その文言をそのまま伝える。
Map<String, dynamic> decodeJavaScriptResult(
  Object? value, {
  String what = 'ページのデータ',
}) {
  final empty = FormatException(
    '$whatを読み取れませんでした（結果が空でした）。ページの表示が終わってから、もう一度押してください。',
  );
  final broken = FormatException('$whatの形式が不正です。ページを再読み込みしてから、もう一度押してください。');
  Object? decoded = value;
  for (var i = 0; i < 2 && decoded is String; i++) {
    final text = decoded.trim();
    if (text.isEmpty || text == 'null' || text == 'undefined') throw empty;
    try {
      decoded = jsonDecode(text);
    } on FormatException {
      throw broken;
    }
  }
  if (decoded == null) throw empty;
  if (decoded is! Map) throw broken;
  final map = Map<String, dynamic>.from(decoded);
  final error = map['error'];
  if (error is String && error.trim().isNotEmpty) throw FormatException(error);
  return map;
}

/// Answer to "which saved rack still has no graph, and where is its page?".
/// [url] is only ever a link the site itself gave us in a saved list table.
class NextGraphTarget {
  const NextGraphTarget({
    this.url,
    this.rack,
    this.remaining = 0,
    this.reason,
    this.warning,
    this.dayComplete = false,
  });
  final String? url;
  final int? rack;
  final int remaining;

  /// 台番号ずれの疑い（数値が完全に同じ台）があるときの警告文。
  final String? warning;

  /// この日の一覧にある台が、すべてグラフ取り込み済み。
  final bool dayComplete;

  /// unknown_page / unknown_machine / no_rows / all_done / linkless
  final String? reason;
}

class WebImportPage extends StatefulWidget {
  const WebImportPage({
    super.key,
    required this.onSave,
    required this.onGraph,
    required this.onNext,
    required this.onUndo,
    required this.onProgress,
    required this.onMachineStatus,
    required this.skipTableReview,
    this.graphsAtRisk,
    this.onGapDay,
    this.onDayCounts,
  });

  final Future<void> Function(WebTableExtraction extraction) onSave;

  /// 表をそのまま保存すると、グラフが外れる台の数。1台でもあれば、確認なし
  /// の設定でも確認画面を出す（偽の表や読み違いで、グラフを黙って失わない）。
  final int Function(WebTableExtraction extraction)? graphsAtRisk;
  final Future<bool> Function(BuildContext context, CaptureAnalysis captured)
  onGraph;
  final NextGraphTarget Function({
    required String? store,
    required String? day,
    required String? machine,
    required int? rack,
  })
  onNext;
  final Future<String> Function() onUndo;
  final String Function({required String? store, required String? day})
  onProgress;
  final List<Map<String, int>?> Function({
    required String? store,
    required String? day,
    required List<String> machines,
  })
  onMachineStatus;

  /// 「表の確認画面を省く」設定。店舗・日付・機種名がそろっている表だけ、
  /// 確認画面を出さずに保存する（PC版は元から確認画面なし）。
  final bool Function() skipTableReview;

  /// 抜けた日を探す（`meruhenGapDay`）。自動取り込みがある日の分を済ませたら、止めずにその日を取り戻す
  /// （2026-11-04）。null なら取り戻さない。
  final String? Function({
    required String store,
    required String day,
    Set<String> skip,
  })?
  onGapDay;

  /// その日・その店の台数とグラフの済んだ台数（結果の通知に使う）。
  final ({int racks, int graphs}) Function({
    required String store,
    required String day,
  })?
  onDayCounts;

  @override
  State<WebImportPage> createState() => _WebImportPageState();
}

class _WebImportPageState extends State<WebImportPage> {
  static const _nagamachiminami =
      'https://meruhenworld.pt.teramoba2.com/nagamachiminami/rack_info';
  static const _saiwaichou =
      'https://meruhenworld.pt.teramoba2.com/saiwaichou/rack_info';

  late final WebViewController _web;
  bool _browserReady = false;
  bool _preparingBrowser = false;
  bool _openingPage = false;
  bool _extractionChannelReady = false;

  /// 画面の状態（読み込み中・処理中・ページの世代・次のページでの予定）。
  /// 変え方は capture_flow.dart にまとめてある。ある機種の最後のグラフを
  /// 保存した後だけ、機種一覧から次の未取込機種（または台数変更の機種）を
  /// 探す。表・グラフの保存操作は自動化しない。
  late final _flow = CaptureFlow(
    onChanged: () {
      if (mounted) setState(() {});
    },
  );
  String? _error;
  String? _notice;
  String _progress = '';
  Timer? _noticeTimer;
  Timer? _loadTimer;
  Timer? _clickTimer;
  final _extractions = WebExtractionChannel();
  static const _autoService = MethodChannel('database/auto_capture');
  final _auto = AutoCaptureState();
  Timer? _autoTimer;
  bool _autoChanging = false;
  bool _autoProbing = false;
  bool _legacyAdvanceAllowed = true;
  String _autoStatus = '停止中';
  // 日付指定取り込み：取り込む営業日（null＝サイトの表示どおり）と、機種を数える向き
  // （top＝一覧の上から、bottom＝下から）。起動のたびに戻る。日本時間の午前3時で営業日が変わる。
  String? _targetDay;

  /// 今回の自動取り込みで済ませた日（店舗|日付）と、取り戻そうとした日、取り戻す前に選んでいた取り込み日
  /// （2026-11-04）。OFF→ONで数え直す。
  final _finishedDays = <String>{};
  final _gapTried = <String>{};
  String? _gapBase;
  String? _targetBeforeGap;
  String _direction = 'top';
  // 手動で取り込んでいるとき、いま済ませた機種。機種一覧へ戻ったあと、一覧の上から探し直さず
  // この機種の次から探すために一度だけ使う（自動取り込みは使わない）。
  String? _afterMachine;
  // サイトが「該当する台情報が見つかりませんでした」と返した機種（`noRacksKey`：店舗・日・機種）。
  // この画面を開いている間だけ覚え、次の機種を探すときに飛ばす（開き直せばもう一度見る：
  // サイトが一時的に空を返しただけなら、次は取り込める）。PC版 `_no_racks` と同じ。
  final _noRacks = <String>{};
  // 今回の取り込みを始めた時刻。その日の機種の表をこれより前に取ったきりなら取り直す
  // （昼に取った機種を、夜の取り込みで「済み」として飛ばさない。PC版と同じ）。
  // 画面を開いたとき・自動取り込みをONにしたときに決める。
  DateTime _freshSince = DateTime.now();

  bool _autoCurrent(int? token, int page) =>
      token == null || _auto.current(token, page);

  void _autoMessage(String message) {
    if (mounted && message != _autoStatus) {
      setState(() => _autoStatus = message);
    }
  }

  /// [direction]：「上から取り込む」「下から取り込む」から始めるとき。省略は今の向きのまま。
  Future<void> _toggleAuto([String? direction]) async {
    if (_autoChanging) return;
    if (!_auto.enabled && direction != null) _direction = direction;
    if (_auto.enabled) {
      _auto.turnOff();
      setState(() => _autoStatus = '停止中（開始済みの保存は完了まで待ちます）');
      if (Platform.isAndroid) {
        try {
          await _autoService.invokeMethod<void>('stop');
        } catch (error) {
          debugPrint('自動取り込みの常駐を止められませんでした：$error');
        }
      }
      return;
    }
    if (!_browserReady || _openingPage || _failedPage == _flow.page) {
      _autoMessage('停止中（通信状態を確認して再読み込みしてください）');
      return;
    }
    setState(() => _autoChanging = true);
    unawaited(requestCaptureNotices());
    _finishedDays.clear();
    _gapTried.clear();
    _gapBase = null;
    try {
      if (Platform.isAndroid) await _autoService.invokeMethod<void>('start');
      if (!mounted ||
          !_browserReady ||
          _openingPage ||
          _failedPage == _flow.page) {
        if (Platform.isAndroid) await _autoService.invokeMethod<void>('stop');
        return;
      }
      _freshSince = DateTime.now();
      _auto.turnOn();
      setState(() => _autoStatus = 'ON・次の取り込みを待っています');
    } catch (error) {
      _autoMessage('自動取り込みを開始できませんでした：$error');
    } finally {
      if (mounted) setState(() => _autoChanging = false);
    }
  }

  Future<void> _autoTick() async {
    if (!mounted || _autoProbing) return;
    final page = _flow.page;
    final token = _auto.due(busy: !_flow.canCapture || _error != null);
    if (token == null) return;
    _autoProbing = true;
    try {
      final current = await _web.currentUrl();
      if (!_auto.current(token, page)) return;
      if (current == null || !_allowed(current)) {
        _autoMessage('ON・対象店舗のページ待ち');
        return;
      }
      final probe = _decodeJavaScriptResult(
        await _runExtraction(_autoProbeScript),
      );
      if (!_auto.current(token, page)) return;
      if (probe['ready'] != true) {
        _autoMessage('ON・待機：${probe['reason'] ?? 'ページの準備待ち'}');
        return;
      }
      if (!meruhenSamePageUrl(probe['url'], current) ||
          !meruhenSamePageUrl(await _web.currentUrl(), current)) {
        _autoMessage('ON・ページ切り替え待ち');
        return;
      }
      if (!_auto.admit(token, page, '${probe['signature']}')) {
        _autoMessage('ON・同じ画面の重複取り込みを待機中');
        return;
      }
      _autoMessage('ON・取り込み中');
      await _captureCurrentPage(autoToken: token);
    } catch (error) {
      if (_auto.current(token, page)) _autoMessage('ON・待機：$error');
    } finally {
      _autoProbing = false;
    }
  }

  void _receiveExtraction(JavaScriptMessage message) {
    _extractions.receive(message.message);
  }

  Future<Object?> _runExtraction(String script) => _extractions.run(
    (id) => _web.runJavaScript(
      '($_extractionBridgeScript)(${jsonEncode(script)}, ${jsonEncode(id)})',
    ),
  );

  int _failedPage = -1;
  String? _navigationUrl;
  bool _samePage(int page) =>
      mounted && _flow.isCurrent(page) && _failedPage != page;

  void _failDocument(String? url, String message) {
    if (!mounted) return;
    if (url != null &&
        Uri.tryParse(url)?.removeFragment() !=
            Uri.tryParse(_navigationUrl ?? '')?.removeFragment()) {
      return;
    }
    _failedPage = _flow.page;
    _extractions.navigationStarted();
    if (_auto.enabled) {
      unawaited(notifyCaptureResult('メルヘン：取り込みが止まりました', '通信エラー：$message'));
    }
    unawaited(_stopAuto('停止中（通信エラー・Cookieと記録は保持しています）'));
    _loadTimer?.cancel();
    _flow.fail(_flow.page);
    setState(() => _error = message);
  }

  void _showNotice(String message) {
    if (!mounted) return;
    _noticeTimer?.cancel();
    setState(() => _notice = message);
    _noticeTimer = Timer(const Duration(seconds: 4), () {
      if (mounted) setState(() => _notice = null);
    });
  }

  @override
  void dispose() {
    _auto.turnOff();
    _autoTimer?.cancel();
    if (Platform.isAndroid) {
      unawaited(_autoService.invokeMethod<void>('stop').catchError((_) {}));
    }
    _noticeTimer?.cancel();
    _loadTimer?.cancel();
    _clickTimer?.cancel();
    _extractions.dispose();
    super.dispose();
  }

  @override
  void initState() {
    super.initState();
    _autoTimer = Timer.periodic(
      const Duration(milliseconds: 100),
      (_) => unawaited(_autoTick()),
    );
    // デバッグ版だけ、USB接続したPCから内部ブラウザを調べられるようにする
    // （不具合調査用。リリース版では無効）。
    if (kDebugMode && Platform.isAndroid) {
      unawaited(AndroidWebViewController.enableDebugging(true));
    }
    _web = WebViewController();
    unawaited(_prepareBrowser(_nagamachiminami));
  }

  Future<void> _prepareBrowser(String initialUrl) async {
    if (_preparingBrowser) return;
    _preparingBrowser = true;
    try {
      await prepareBrowserSession(
        configureJavaScript: () async {
          await _web.setJavaScriptMode(JavaScriptMode.unrestricted);
          if (!mounted) return;
          if (!_extractionChannelReady) {
            await _web.addJavaScriptChannel(
              'DatabaseExtraction',
              onMessageReceived: _receiveExtraction,
            );
            _extractionChannelReady = true;
          }
        },
        configureNavigation: () => _web.setNavigationDelegate(
          NavigationDelegate(
            onPageStarted: (url) {
              _navigationUrl = url;
              _failedPage = -1;
              _extractions.navigationStarted();
              _loadTimer?.cancel();
              _clickTimer?.cancel();
              _noticeTimer?.cancel();
              final start = _flow.pageStarted(url);
              _auto.nextPage(start);
              if (_auto.enabled) _autoMessage('ON・読み込み待ち');
              _loadTimer = Timer(const Duration(seconds: 45), () {
                if (_samePage(start)) {
                  _flow.loadTimedOut(start);
                  setState(
                    () => _error = 'まだ読み込み完了を確認できません。通信状態を確認し、再読み込みしてください。',
                  );
                }
              });
              if (mounted) {
                setState(() {
                  _notice = null;
                  _error = null;
                });
              }
            },
            onPageFinished: (url) => unawaited(_afterPageFinished(url)),
            onWebResourceError: (error) {
              if (error.isForMainFrame != true || !mounted) return;
              _failDocument(
                error.url,
                error.errorCode == -2 ||
                        error.description.contains('ERR_NAME_NOT_RESOLVED')
                    ? '接続先の名前を確認できませんでした（DNSエラー）。Cookieを消さずに再読み込みしてください。'
                    : 'ページを読み込めませんでした（エラー ${error.errorCode}）。Cookieを消さずに再読み込みしてください。',
              );
            },
            onHttpError: (error) {
              final url = error.request?.uri.toString();
              // 広告など別URLの失敗は止めず、表示対象のHTTPエラーだけ扱う。
              if (url != null && (error.response?.statusCode ?? 0) >= 400) {
                _failDocument(
                  url,
                  'ページを読み込めませんでした（HTTP ${error.response?.statusCode}）。Cookieを消さずに再読み込みしてください。',
                );
              }
            },
            onNavigationRequest: (request) => _allowed(request.url)
                ? NavigationDecision.navigate
                : NavigationDecision.prevent,
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
          _navigationUrl = initialUrl;
          await _web.loadRequest(Uri.parse(initialUrl));
          if (mounted) setState(() => _browserReady = true);
        },
        active: () => mounted,
      );
    } catch (_) {
      if (mounted) {
        _browserReady = false;
        _flow.fail(_flow.page);
        setState(() => _error = 'Cookie・ブラウザ設定を準備できませんでした。再読み込みで再試行してください。');
      }
    } finally {
      _preparingBrowser = false;
      if (mounted) setState(() {});
    }
  }

  Future<void> _afterPageFinished(String url) async {
    if (!mounted) return;
    final page = _flow.page;
    try {
      if (!meruhenSamePageUrl(await _web.currentUrl(), url) ||
          !_samePage(page) ||
          !_flow.pageFinished(page)) {
        return;
      }
    } catch (_) {
      if (_samePage(page)) _flow.fail(page);
      return;
    }
    try {
      // 保存の途中で次のページの読み込みが終わることがある。保存が終わるのを待つ。
      await _flow.whenIdle();
      if (!_samePage(page)) return;
      await _waitForPage(page);
      if (!_samePage(page)) return;
      _loadTimer?.cancel();
      unawaited(_web.runJavaScript(_hideYouTubeScript).catchError((_) {}));
      final pending = _flow.takeAfterLoadNotice();
      if (pending != null) _showNotice(pending);
      // _runExtraction has one reply channel.  Keep the auxiliary page reads
      // sequential and keep the capture button disabled until they finish;
      // otherwise a quick tap can replace the pending reply and time out.
      await _markMachines();
      if (!_samePage(page)) return;
      await _refreshProgress();
      if (!_samePage(page)) return;
      if (_flow.takeAdvance() && _legacyAdvanceAllowed && !_auto.enabled) {
        await _moveToNextMachine(
          automatic: true,
          toggleRevision: _auto.revision,
        );
        return;
      }
      _flow.ready(page);
    } catch (error) {
      if (_samePage(page)) {
        _flow.fail(page);
        setState(() => _error = '$error');
      }
    }
  }

  Future<void> _waitForPage(int page) async {
    await waitForStablePage(
      read: () async =>
          _decodeJavaScriptResult(await _runExtraction(_pageReadinessScript)),
      isCurrent: () => _samePage(page),
    );
  }

  bool _allowed(String rawUrl) {
    final uri = Uri.tryParse(rawUrl);
    return uri?.scheme == 'https' &&
        uri?.host == 'meruhenworld.pt.teramoba2.com' &&
        (uri?.path.startsWith('/nagamachiminami/') == true ||
            uri?.path.startsWith('/saiwaichou/') == true);
  }

  /// 自動取り込みが、ある店のある日の分を済ませたとき（2026-11-04）。結果を通知で1回だけ知らせ、抜けた日
  /// （`meruhenGapDay`）があれば、止めずにその日の機種一覧を日付つきで開いて取り戻す。開いたら true。
  Future<bool> _dayFinished(String store, String day, int autoToken) async {
    final name = storeDisplayName(store);
    if (_finishedDays.add('$store|$day')) {
      final counts = widget.onDayCounts?.call(store: store, day: day);
      unawaited(
        notifyCaptureResult(
          'メルヘン：取り込み完了',
          '$name ${shortDayLabel(day)}：'
              '${counts == null ? 'すべて取り込み済み' : '${counts.racks}台（グラフ${counts.graphs}台）'}',
        ),
      );
    }
    final base = _gapBase ??= day;
    final gap = widget.onGapDay?.call(
      store: store,
      day: base,
      skip: {
        ..._gapTried,
        for (final key in _finishedDays)
          if (key.startsWith('$store|')) key.substring(store.length + 1),
      },
    );
    if (gap == null || !_autoCurrent(autoToken, _flow.page)) {
      if (_gapBase != null &&
          _targetDay != _targetBeforeGap &&
          _gapTried.isNotEmpty) {
        setState(() => _targetDay = _targetBeforeGap);
      }
      return false;
    }
    final url = meruhenMachineListUrl(store, gap);
    if (!_allowed(url)) return false;
    if (_gapTried.isEmpty) _targetBeforeGap = _targetDay;
    _gapTried.add(gap);
    setState(() => _targetDay = gap);
    unawaited(noteErrorLog('meruhen.gap', '$store $gapを取り戻す（$dayの後）'));
    final notice =
        '${shortDayLabel(day)}の分は済みました。抜けていた${shortDayLabel(gap)}の分を取り戻します。';
    _autoMessage('ON・$notice');
    _flow.expectPage(notice: notice, advance: true);
    _flow.startLoading();
    await _web.loadRequest(Uri.parse(url));
    return true;
  }

  Future<void> _stopAuto(String message) async {
    _auto.turnOff();
    if (mounted) setState(() => _autoStatus = message);
    if (Platform.isAndroid) {
      try {
        await _autoService.invokeMethod<void>('stop');
      } catch (error) {
        // 常駐（通知）が残る原因を後から調べられるよう、端末のログに残す。
        debugPrint('自動取り込みの常駐を止められませんでした：$error');
      }
    }
  }

  Future<void> _reloadPage() async {
    if (_flow.busy || _openingPage || _preparingBrowser) return;
    await _stopAuto('停止中（Cookieと記録を保持して再読み込み）');
    if (!mounted) return;
    final url = _navigationUrl;
    await _openStore(
      url != null && _allowed(url) ? url : _nagamachiminami,
      reload: true,
    );
  }

  Future<void> _openStore(String url, {bool reload = false}) async {
    if (!_allowed(url) || _flow.busy || _openingPage || _preparingBrowser) {
      return;
    }
    setState(() => _openingPage = true);
    _flow.cancelExpectation();
    _flow.startLoading();
    _extractions.navigationStarted();
    _failedPage = _flow.page; // Reject old callbacks until the new load starts.
    setState(() => _error = null);
    try {
      if (!_browserReady) {
        await _prepareBrowser(url);
      } else if (reload) {
        await reopenBrowserPage(
          target: Uri.parse(url),
          currentUrl: _web.currentUrl,
          reload: _web.reload,
          load: _web.loadRequest,
          active: () => mounted,
        );
      } else {
        await _web.loadRequest(Uri.parse(url));
      }
    } catch (_) {
      if (mounted) {
        _flow.fail(_flow.page);
        setState(() => _error = '店舗のページを開けませんでした。Cookieを消さずに再読み込みしてください。');
      }
    } finally {
      if (mounted) setState(() => _openingPage = false);
    }
  }

  Future<void> _extract({int? autoToken}) => _flow.whileBusy(() async {
    final page = _flow.page;
    if (!_autoCurrent(autoToken, page)) return;
    setState(() => _error = null);
    try {
      final value = await _runExtraction(_extractTableScript);
      if (!_samePage(page) || !_autoCurrent(autoToken, page)) return;
      final decoded = _decodeJavaScriptResult(value);
      final mismatch = pageMismatch(
        await _web.currentUrl(),
        store: decoded['store'] as String?,
        day: decoded['day'] as String?,
      );
      if (mismatch != null) throw FormatException(mismatch);
      final dayMismatch = targetDayMismatch(
        _targetDay,
        decoded['day'] as String?,
      );
      if (dayMismatch != null) throw FormatException(dayMismatch);
      if (!_samePage(page) || !_autoCurrent(autoToken, page)) return;
      final rows = ((decoded['rows'] as List<dynamic>?) ?? const [])
          .map((item) => Map<String, dynamic>.from(item as Map))
          .map(
            (item) => EditableRow(
              rack: item['rack'] as int,
              bb: item['bb'] as int,
              rb: item['rb'] as int,
              games: item['games'] as int,
              maxHold: item['max_hold'] as int?,
              previousStart: item['previous_start'] as int?,
              detailUrl: _trustedRackLink(
                item['detail_url'] as String?,
                item['rack'] as int,
              ),
            ),
          )
          .toList();
      if (!mounted || !_autoCurrent(autoToken, page)) return;
      final extraction = WebTableExtraction(
        sourceUrl: (decoded['url'] as String?) ?? '',
        store: decoded['store'] as String?,
        day: decoded['day'] as String?,
        machine: decoded['machine'] as String?,
        expectedCount: (decoded['expected_count'] as num?)?.toInt(),
        rows: rows,
      );
      if (isExcludedMachine(extraction.store, extraction.machine)) {
        _showNotice('${extraction.machine}は取り込みの対象外です。保存しませんでした。');
        return;
      }
      if (rows.isEmpty &&
          decoded['no_racks'] == true &&
          extraction.store != null &&
          extraction.day != null &&
          (extraction.machine ?? '').isNotEmpty) {
        // 機種の表の代わりに「台情報なし」：保存せず、その日はこの機種を飛ばして機種一覧へ戻る。
        await _skipMachineWithoutRacks(
          store: extraction.store!,
          day: extraction.day!,
          machine: extraction.machine!,
          autoToken: autoToken,
        );
        return;
      }
      if (rows.isEmpty) {
        setState(
          () => _error = '表の行を読み取れませんでした。台番号・BB・RB・総回転数がある一覧を表示してから試してください。',
        );
        return;
      }
      if (extraction.expectedCount != null &&
          rows.length != extraction.expectedCount) {
        setState(
          () => _error =
              '読み取った台数（${rows.length}台）と設置台数（${extraction.expectedCount}台）が一致しません。保存しませんでした。',
        );
        return;
      }
      // そろっていない表は、設定が入っていても確認画面へ回す。
      final identified = canSaveWithoutReview(extraction);
      final atRisk = widget.graphsAtRisk?.call(extraction) ?? 0;
      final bool? saved;
      if (!_autoCurrent(autoToken, page)) return;
      if (widget.skipTableReview() && identified && atRisk == 0) {
        await widget.onSave(extraction);
        saved = true;
      } else {
        if (widget.skipTableReview() && !identified) {
          _showNotice('店舗・日付・機種名を読み取れなかったので、確認画面を開きます。');
        } else if (widget.skipTableReview() && atRisk > 0) {
          _showNotice('保存すると$atRisk台のグラフが外れるため、確認画面を開きます。');
        }
        saved = await Navigator.of(context).push<bool>(
          MaterialPageRoute(
            fullscreenDialog: true,
            builder: (_) => WebTableReviewPage(
              extraction: extraction,
              onSave: widget.onSave,
            ),
          ),
        );
      }
      if (saved == true && _samePage(page) && _autoCurrent(autoToken, page)) {
        // 表を保存したら、そのまま最初のグラフ未取得の台へ移動する。
        // 大当たり0回の台はグラフを取らない（次の台にもしない）。
        final noHits = rows.where((r) => r.bb + r.rb == 0).length;
        await _moveToNext(
          saved:
              '${rows.length}台を保存しました。'
              '${noHits > 0 ? '大当たり0回の$noHits台はグラフを省略します。' : ''}',
          firstOfMachine: true,
          store: extraction.store,
          day: extraction.day,
          machine: extraction.machine,
          rack: null,
          autoToken: autoToken,
        );
      }
    } catch (error) {
      if (_samePage(page)) {
        setState(() => _error = '表を読み取れませんでした。機種別の一覧画面を表示してから試してください。\n$error');
      }
    }
  });

  Future<void> _extractGraph({int? autoToken}) => _flow.whileBusy(() async {
    final page = _flow.page;
    if (!_autoCurrent(autoToken, page)) return;
    setState(() => _error = null);
    try {
      final value = await _runExtraction(_extractGraphScript);
      if (!_samePage(page) || !_autoCurrent(autoToken, page)) return;
      final decoded = _decodeJavaScriptResult(value);
      final mismatch = pageMismatch(
        await _web.currentUrl(),
        store: decoded['store'] as String?,
        day: decoded['day'] as String?,
        rack: decoded['rack'] as int?,
      );
      if (mismatch != null) throw FormatException(mismatch);
      final dayMismatch = targetDayMismatch(
        _targetDay,
        decoded['day'] as String?,
      );
      if (dayMismatch != null) throw FormatException(dayMismatch);
      if (!_samePage(page) || !_autoCurrent(autoToken, page)) return;
      if (isExcludedMachine(
        decoded['store'] as String?,
        decoded['machine'] as String?,
      )) {
        _showNotice('${decoded['machine']}は取り込みの対象外です。保存しませんでした。');
        return;
      }
      final isSvg = decoded['format'] == 'svg';
      if (!isValidRecordDay(decoded['day'] as String?)) {
        throw const FormatException('評価日を特定できません。日付を選んでから取り込んでください。');
      }
      final dataUrl = decoded['image'] as String?;
      final path = isSvg
          ? ''
          : dataUrl == null || !dataUrl.startsWith('data:image/png;base64,')
          ? throw const FormatException('この画面に取り込めるグラフが見つかりません。')
          : await _writeGraphImage(dataUrl);
      final GraphDetection? graph;
      try {
        graph = isSvg
            ? _graphFromSvg(decoded)
            : await ImportService().detectGraph(path);
      } finally {
        // 判定に使った一時ファイルは、この後使わない（画像はメモリにある）。
        if (path.isNotEmpty) {
          unawaited(File(path).delete().then((_) {}, onError: (_) {}));
        }
      }
      if (graph == null) {
        throw const FormatException('ゼロ線とグラフ線を判定できませんでした。');
      }
      final captured = CaptureAnalysis(
        path: path,
        kind: CaptureKind.graph,
        fullText: decoded['body'] as String? ?? '',
        store: decoded['store'] as String?,
        day: decoded['day'] as String?,
        machine: decoded['machine'] as String?,
        rack: decoded['rack'] as int?,
        games: decoded['games'] as int?,
        bb: decoded['bb'] as int?,
        rb: decoded['rb'] as int?,
        maxHold: decoded['max_hold'] as int?,
        graph: graph,
      );
      if (!mounted || !_samePage(page) || !_autoCurrent(autoToken, page)) {
        return;
      }
      final saved = await widget.onGraph(context, captured);
      if (saved && _samePage(page) && _autoCurrent(autoToken, page)) {
        // 保存が済んだら、次のグラフ未取得の台へ自動で移動する（取り込みボタンを
        // 押すのはこれまで通り人。移動先は一覧から保存済みのサイト自身のリンクだけ）。
        final points = graph.points;
        final details = [
          if (captured.games != null) '${captured.games}G',
          if (captured.bb != null) 'BIG${captured.bb}',
          if (captured.rb != null) 'REG${captured.rb}',
          if (points.length == 4)
            '終点${points[3].dy < points[0].dy ? '上昇' : '下降'}',
        ];
        await _moveToNext(
          saved:
              '${captured.rack}番台を保存しました'
              '${details.isEmpty ? '' : '（${details.join('・')}）'}。',
          store: captured.store,
          day: captured.day,
          machine: captured.machine,
          rack: captured.rack,
          autoToken: autoToken,
        );
      }
    } catch (error) {
      if (_samePage(page)) {
        setState(
          () => _error = 'グラフを取り込めませんでした。個別台のグラフ画面を表示してから試してください。\n$error',
        );
      }
    }
  });

  /// 表示中の機種の表が「台情報なし」のとき、その日はこの機種を飛ばして機種一覧へ戻る
  /// （PC版 `skip_machine_without_racks` と同じ）。戻った一覧では、次の機種を探すときに
  /// この機種を飛ばす（手動のときは、この機種の次から探す）。
  Future<void> _skipMachineWithoutRacks({
    required String store,
    required String day,
    required String machine,
    int? autoToken,
  }) async {
    if (!_autoCurrent(autoToken, _flow.page)) return;
    _noRacks.add(noRacksKey(store, day, machine));
    final notice = noRacksNotice(day, machine);
    final url = meruhenMachineListUrl(store, day);
    if (!_allowed(url)) {
      _showNotice(notice);
      return;
    }
    _flow.expectPage(notice: notice, advance: true);
    _flow.startLoading();
    _afterMachine = autoToken == null ? machine : null;
    if (autoToken != null) _autoMessage('ON・$notice');
    try {
      await _web.loadRequest(Uri.parse(url));
    } catch (error) {
      if (mounted) {
        _flow.cancelExpectation();
        _flow.stopLoading();
        setState(() => _error = '機種一覧へ移動できませんでした。\n$error');
      }
    }
  }

  /// Only a link that stays on this site, in the same shop, and names the
  /// rack it was found on is kept; anything else is dropped.
  String? _trustedRackLink(String? url, int rack) {
    if (url == null || !_allowed(url)) return null;
    return Uri.parse(url).queryParameters['rack_no'] == '$rack' ? url : null;
  }

  Future<void> _moveToNext({
    String saved = '',
    bool firstOfMachine = false,
    String? store,
    String? day,
    String? machine,
    int? rack,
    int? autoToken,
  }) async {
    if (!_autoCurrent(autoToken, _flow.page)) return;
    final target = widget.onNext(
      store: store,
      day: day,
      machine: machine,
      rack: rack,
    );
    final url = target.url;
    final warning = target.warning ?? '';
    if (url != null && _allowed(url) && _autoCurrent(autoToken, _flow.page)) {
      final String step;
      final allDone = target.reason == 'all_done';
      final machineFinished = allDone || target.reason == 'linkless';
      if (target.reason == 'linkless') {
        step = '個別リンクがない台は未取得のまま残し、機種一覧へ移動します。';
      } else if (allDone) {
        // 機種のグラフが全部済んだら、サイト自身の機種一覧ページへ案内する。
        // 読み込み後は、その一覧から次の未取込機種も探す。
        step =
            'この機種はすべて取り込み済みです。機種一覧へ移動します。'
            '${target.dayComplete ? 'この日の取り込み済みの台はすべて完了しました。「結果」タブの「この日のまとめ」で確認できます。' : ''}';
      } else {
        step =
            '${firstOfMachine ? '最初の未取り込み台へ移動します。' : ''}'
            '次：${target.rack}番台（残り${target.remaining}台）';
      }
      _flow.expectPage(
        notice: '$saved$step $warning'.trim(),
        advance: machineFinished,
      );
      _flow.startLoading();
      _afterMachine = machineFinished && autoToken == null ? machine : null;
      try {
        await _web.loadRequest(Uri.parse(url));
      } catch (error) {
        if (mounted) {
          _flow.cancelExpectation();
          _flow.stopLoading();
          setState(() => _error = '次のページへ移動できませんでした。\n$error');
        }
      }
      return;
    }
    final message = switch (target.reason) {
      'no_rows' => 'この機種・日付の一覧をまだ取り込んでいません。先に一覧を取り込んでください。',
      'unknown_machine' => '機種名を特定できません。一覧の取り込み後にお試しください。',
      'linkless' => '取得できる個別リンクのある未取得台はありません。未取得台を残して機種一覧へ戻ります。',
      'all_done' => 'この機種・日付はすべて取り込み済みです。',
      _ => '店舗・日付を特定できませんでした。機種別一覧か個別台のページで押してください。',
    };
    _showNotice('$saved$message $warning'.trim());
    // 取り込みの処理が終わってから進み具合を読み直す（処理中は読まないため）。
    unawaited(_flow.whenIdle().then((_) => _refreshProgress()));
  }

  /// 「今日 長町南 42/80台・幸町 18/60台」の進捗行を更新する。
  Future<void> _refreshProgress() async {
    if (!mounted || _flow.busy) return;
    final page = _flow.page;
    try {
      final value = await _runExtraction(_pageIdentityScript);
      if (!_samePage(page)) return;
      final decoded = _decodeJavaScriptResult(value);
      final text = widget.onProgress(
        store: decoded['store'] as String?,
        day: decoded['day'] as String?,
      );
      if (mounted && text != _progress) setState(() => _progress = text);
    } catch (_) {
      // 進捗表示は補助情報。読み取れなくても取り込みの邪魔をしない。
    }
  }

  /// サイトの機種一覧ページで、各機種の横に「済 8/8」「5/18」「未取込」の印を出す。
  Future<void> _markMachines() async {
    if (!mounted || _flow.busy) return;
    final page = _flow.page;
    try {
      final url = await _web.currentUrl() ?? '';
      if (!_samePage(page)) return;
      if (!url.contains('rack_info_kt')) return;
      final value = await _runExtraction(_machineLinksScript);
      if (!_samePage(page)) return;
      final decoded = _decodeJavaScriptResult(value);
      final names = [
        for (final item in (decoded['machines'] as List<dynamic>?) ?? const [])
          '${(item as Map)['name'] ?? ''}',
      ];
      final store = decoded['store'] as String?;
      final counts = widget.onMachineStatus(
        store: store,
        day: decoded['day'] as String?,
        machines: names,
      );
      final status = [
        for (var i = 0; i < names.length; i++)
          isExcludedMachine(store, names[i])
              ? <String, Object>{'excluded': true}
              : counts[i],
      ];
      // 印に、どの日の状況かを付ける（ページに日付が無いときは今日）。
      final shownDay = decoded['day'] as String? ?? todayIso();
      await _web.runJavaScript(
        '($_markMachinesScript)(${jsonEncode(status)}, ${jsonEncode(shownDay)})',
      );
    } catch (_) {
      // 印は補助情報。付けられなくても取り込みの邪魔をしない。
    }
  }

  /// The single capture action follows the page the user has opened:
  /// a machine table saves the table, a rack page saves its graph, and the
  /// 1000-yen / high-slot machine list opens the next machine that needs work.
  /// It never starts a capture merely because a page finished loading.
  Future<void> _captureCurrentPage({int? autoToken}) async {
    if (!mounted || !_flow.canCapture || !_autoCurrent(autoToken, _flow.page)) {
      return;
    }
    _legacyAdvanceAllowed = autoToken == null;
    await _flow.whileBusy(() async {
      final page = _flow.page;
      setState(() => _error = null);
      try {
        await _waitForPage(page);
        if (!_samePage(page) || !_autoCurrent(autoToken, page)) return;
        final value = await _runExtraction(_pageIdentityScript);
        if (!_samePage(page) || !_autoCurrent(autoToken, page)) return;
        final decoded = _decodeJavaScriptResult(value);
        final url = await _web.currentUrl() ?? '';
        if (!_samePage(page) || !_autoCurrent(autoToken, page)) return;
        if (!isTargetKindUrl(url)) {
          _showNotice('対象は1000円46枚スロットのみです。');
          return;
        }
        final rack = (decoded['rack'] as num?)?.toInt();
        final machine = (decoded['machine'] as String?)?.trim() ?? '';

        if (rack != null) {
          await _extractGraph(autoToken: autoToken);
        } else if (machine.isNotEmpty) {
          await _extract(autoToken: autoToken);
        } else if (url.contains('rack_info_kt')) {
          await _moveToNextMachine(autoToken: autoToken);
        } else {
          _showNotice('1000円46枚スロット／ハイスロの機種一覧、機種別の表、または個別台のグラフを表示してから押してください。');
        }
      } catch (error) {
        if (mounted) setState(() => _error = 'この画面を取り込めませんでした。\n$error');
      }
    });
  }

  /// On the site's machine-list page, first resume a machine whose graph is
  /// still missing. If none remains, open a never-imported machine (or one
  /// whose listed cabinet count changed) so its current table can be saved.
  /// This only navigates to the site's links; the user still presses each
  /// table/graph import button.
  Future<void> _moveToNextMachine({
    bool automatic = false,
    int? autoToken,
    int? toggleRevision,
  }) async {
    if (!mounted) return;
    final page = _flow.page;
    bool active() =>
        _samePage(page) &&
        _autoCurrent(autoToken, page) &&
        (toggleRevision == null || _auto.revision == toggleRevision);
    // ページを移動したか。移動しなかった場合は最後に読み込み中の表示を外す
    // （グラフ完了後の自動移動で「残りなし」などになったとき、くるくるが
    // 回り続けてボタンが押せなくなっていた）。
    var moved = false;
    await _flow.whileBusy(() async {
      setState(() => _error = null);
      try {
        final currentUrl = await _web.currentUrl() ?? '';
        if (!active()) return;
        if (!currentUrl.contains('rack_info_kt')) {
          _showNotice('1000円46枚スロット／ハイスロの機種一覧画面で押してください。');
          return;
        }
        final stable = await waitForStablePage(
          read: () async {
            final data = _decodeJavaScriptResult(
              await _runExtraction(_machineLinksScript),
            );
            return {
              ...data,
              'content': data['machines'],
              'hasContent': (data['machines'] as List?)?.isNotEmpty == true,
            };
          },
          isCurrent: active,
        );
        if (!active()) return;
        final decoded = stable;
        // 低貸し（kind_code=10・5）の機種一覧では、次の機種を選ばない。
        if (!isTargetKindUrl(currentUrl)) {
          _showNotice('1000円46枚スロット（ハイスロ）の機種一覧で押してください。低貸しの機種は取り込みの対象外です。');
          return;
        }
        final store = decoded['store'] as String?;
        final day = _targetDay ?? decoded['day'] as String?;
        var machines = [
          for (final raw in (decoded['machines'] as List<dynamic>?) ?? const [])
            Map<String, dynamic>.from(raw as Map),
        ];
        // 公開されていない機種（長町南のジャグラーなど）は候補から外す。
        // 一覧に出ているのが対象外だけなら、読み込み中ではなく「残りなし」と伝える。
        machines = [
          for (final item in machines)
            if (!isListHeaderName('${item['name'] ?? ''}')) item,
        ];
        final visible = [
          for (final item in machines)
            if (!isExcludedMachine(store, '${item['name'] ?? ''}')) item,
        ];
        if (machines.isNotEmpty && visible.isEmpty) {
          _showNotice(
            '未取り込みの機種・グラフはありません。（${excludedMachineNotes[store] ?? 'データ非公開の機種'}は対象外）',
          );
          return;
        }
        machines = _direction == 'bottom' ? visible.reversed.toList() : visible;
        // 初めて開いた機種一覧にはサイト側の日付がありません。最初の機種別
        // 一覧を開けば選択中の日付を読めるため、そこで表の取り込みを始める。
        // グラフ完了後に戻る場合はURLフラグメントから日付を復元しているので、
        // この分岐には入りません。
        if (store == null || day == null) {
          // 日付を確かめるために開く機種も、なるべく未取込の機種にする
          // （日付が分からないので、この店で最後に取り込んだ日の状況で判断）。
          // そうすれば開いた先でそのまま表を取り込める。
          final guessed = widget.onMachineStatus(
            store: store,
            day: null,
            machines: [for (final item in machines) '${item['name'] ?? ''}'],
          );
          bool openable(Map<String, dynamic>? item) {
            final url = item?['url'] as String?;
            return url != null && _allowed(url) && isTargetKindUrl(url);
          }

          Map<String, dynamic>? first;
          final today = todayIso();
          for (var index = 0; index < machines.length; index++) {
            final status = guessed[index];
            final skipped =
                store != null &&
                _noRacks.contains(
                  noRacksKey(store, today, '${machines[index]['name'] ?? ''}'),
                );
            if (openable(machines[index]) &&
                !skipped &&
                (status == null || status['done'] != status['total'])) {
              first = machines[index];
              break;
            }
          }
          first ??= machines.cast<Map<String, dynamic>?>().firstWhere(
            openable,
            orElse: () => null,
          );
          final targetUrl = first?['url'] as String?;
          if (targetUrl == null) {
            _showNotice(
              '機種一覧が表示されるのを待ってから、もう一度押してください。'
              '（しばらく待っても表示されない場合は、ページを再読み込みしてください）',
            );
            return;
          }
          final name = first?['name'] as String? ?? '先頭の機種';
          moved = await _openMachineTable(
            first!,
            '$name の一覧で対象日を確認します。表示後に「この画面を取り込む」を押してください。',
            autoToken: autoToken,
            toggleRevision: toggleRevision,
          );
          return;
        }
        final statuses = widget.onMachineStatus(
          store: store,
          day: day,
          machines: [for (final item in machines) '${item['name'] ?? ''}'],
        );

        // 手動で取り込んでいるときは、一覧の上から探し直さず、いま済ませた機種の次
        // （一覧の並びの順）から探す。先が無くなったときだけ、取りこぼしを探して最初から見直す。
        final passes = machineSearchPasses([
          for (final item in machines) '${item['name'] ?? ''}',
        ], autoToken == null && !automatic ? _afterMachine : null);
        _afterMachine = null;
        final cutoff = staleCaptureCutoff(day, _freshSince);
        bool stale(Map<String, int>? status) =>
            cutoff != null &&
            status?['newest'] != null &&
            status!['newest']! < cutoff;
        for (final (order, prefix) in passes) {
          // 一覧の並び（選んだ向き）の順に1回だけ見る。グラフが残る機種も、未取込・台数変更・
          // 古い表の機種も、並びで先にある方から（`machineNextStep`、PC版と同じ。2026-10-06）。
          for (final index in order) {
            // その日はサイトに台情報が無かった機種。
            if (_noRacks.contains(
              noRacksKey(store, day, '${machines[index]['name'] ?? ''}'),
            )) {
              continue;
            }
            final status = statuses[index];
            final step = machineNextStep(
              status,
              listedCount: (machines[index]['count'] as num?)?.toInt(),
              stale: status != null && stale(status),
            );
            if (step == null) continue;
            if (step == 'table') {
              final targetUrl = machines[index]['url'] as String?;
              if (targetUrl == null ||
                  !_allowed(targetUrl) ||
                  !isTargetKindUrl(targetUrl)) {
                continue;
              }
              final name = machines[index]['name'] as String? ?? 'この機種';
              final changed = status != null && !stale(status);
              moved = await _openMachineTable(
                machines[index],
                changed
                    ? '$prefix$name は設置台数が変わっています。現在の表を取り込んでください。'
                    : status != null
                    ? '$prefix$name は前に取った表のままです。現在の表を取り込み直してください（数値が変わった台だけグラフも取り直します）。'
                    : '$prefix$name は未取込です。現在の表を取り込んでください。',
                autoToken: autoToken,
                toggleRevision: toggleRevision,
              );
              return;
            }
            final target = widget.onNext(
              store: store,
              day: day,
              machine: machines[index]['name'] as String?,
              rack: null,
            );
            if (target.url != null &&
                target.reason != 'all_done' &&
                target.reason != 'linkless' &&
                _allowed(target.url!) &&
                active()) {
              _flow.expectPage(
                notice:
                    '$prefix未取得グラフが残る${machines[index]['name']}へ移動します。次：${target.rack}番台（残り${target.remaining}台）',
              );
              _flow.startLoading();
              moved = true;
              await _web.loadRequest(Uri.parse(target.url!));
              return;
            }
            // Older screenshot/backup records can have the table but no saved
            // per-rack detail links.  Re-read this displayed table before moving
            // on, otherwise this machine would stay permanently incomplete.
            final tableUrl = machines[index]['url'] as String?;
            if (tableUrl != null &&
                _allowed(tableUrl) &&
                isTargetKindUrl(tableUrl)) {
              final name = machines[index]['name'] as String? ?? 'この機種';
              moved = await _openMachineTable(
                machines[index],
                '$prefix$name の一覧を更新して、未取得グラフを続けます。',
                autoToken: autoToken,
                toggleRevision: toggleRevision,
              );
              return;
            }
          }
        }
        if (automatic && autoToken != null) {
          moved = await _dayFinished(store, day, autoToken);
          if (moved) return;
        }
        _showNotice(
          automatic ? 'この日の機種とグラフはすべて取り込み済みです。' : '未取り込みの機種・グラフはありません。',
        );
      } catch (error) {
        if (_samePage(page)) {
          _flow.fail(page);
          setState(() => _error = '次の機種を探せませんでした。\n$error');
        }
      }
    });
    if (!moved && _samePage(page)) _flow.stopLoading();
  }

  /// 機種一覧から機種別の表へ移動する。組み立てたURLを開くのではなく、サイト自身の
  /// 行（旧形式ならリンク）を押す。組み立てたURLには選択中の日付（target_date）が
  /// 無く、実サイトは空のページ（「該当する台情報がありません」）を返していたため。
  /// 日付と機種名の表記はサイトが自分で付ける。移動するだけで、取り込みは利用者が
  /// ボタンを押したときだけ。行が見つからない場合は従来どおりURLを開く。
  Future<bool> _openMachineTable(
    Map<String, dynamic> machine,
    String notice, {
    int? autoToken,
    int? toggleRevision,
  }) async {
    final name = '${machine['name'] ?? ''}';
    final url = machine['url'] as String?;
    final before = await _web.currentUrl();
    if (!mounted ||
        !_autoCurrent(autoToken, _flow.page) ||
        (toggleRevision != null && _auto.revision != toggleRevision)) {
      return false;
    }
    final chosenDay = _targetDay;
    if (chosenDay != null &&
        url != null &&
        _allowed(url) &&
        isTargetKindUrl(url)) {
      // 取り込み日を指定しているときは、サイトの行を押さず（押すと、サイトが選んでいる日付に
      // なってしまう）、日付つきのURLで開く。サイトが日付を選んだときに自分で付ける形。
      _flow.expectPage(notice: notice);
      _flow.startLoading();
      await _web.loadRequest(Uri.parse(withTargetDate(url, chosenDay)));
      return true;
    }
    final starts = _flow.page;
    _flow.expectPage(notice: notice);
    _flow.startLoading();
    var clicked = false;
    if (name.isNotEmpty) {
      try {
        if (!_autoCurrent(autoToken, starts) ||
            (toggleRevision != null && _auto.revision != toggleRevision)) {
          return false;
        }
        clicked =
            await _runExtraction(
              '($_clickMachineRowScript)(${jsonEncode(name)})',
            ) ==
            true;
      } catch (_) {
        clicked = false;
      }
    }
    if (!_samePage(starts)) return true;
    if (!_autoCurrent(autoToken, starts) ||
        (toggleRevision != null && _auto.revision != toggleRevision)) {
      return false;
    }
    if (!clicked) {
      if (url != null) {
        await _web.loadRequest(Uri.parse(url));
        return true;
      }
      _flow.takeAfterLoadNotice();
      return false;
    }
    // 押しても移動しない場合に、読み込み中のまま操作できなくならないようにする。
    _clickTimer?.cancel();
    _clickTimer = Timer(const Duration(seconds: 30), () async {
      if (!mounted || !_flow.isCurrent(starts)) return;
      String? now;
      try {
        now = await _web.currentUrl();
      } catch (_) {
        return;
      }
      if (!mounted || !_flow.isCurrent(starts)) return;
      final pending = _flow.takeAfterLoadNotice();
      if (!meruhenSamePageUrl(now, before)) {
        try {
          await _waitForPage(starts);
          if (!_samePage(starts)) return;
          _flow.ready(starts);
          if (pending != null) _showNotice(pending);
        } catch (error) {
          if (_samePage(starts)) {
            _flow.fail(starts);
            setState(() => _error = '$error');
          }
        }
        return;
      }
      _flow.fail(starts);
      setState(() => _error = '$name への移動をまだ確認できません。通信状態を確認し、再読み込みしてください。');
    });
    return true;
  }

  Future<void> _undoLast() async {
    if (!mounted || _flow.busy) return;
    await _flow.whileBusy(() async {
      try {
        final message = await widget.onUndo();
        _showNotice(message);
      } catch (error) {
        if (mounted) setState(() => _error = '取り消しできませんでした。\n$error');
      }
    });
    await _refreshProgress();
  }

  Future<String> _writeGraphImage(String dataUrl) async {
    final base64 = dataUrl.substring(dataUrl.indexOf(',') + 1);
    final bytes = base64Decode(base64);
    final directory = await getTemporaryDirectory();
    final file = File(
      '${directory.path}${Platform.pathSeparator}database-web-graph-${DateTime.now().microsecondsSinceEpoch}.png',
    );
    await file.writeAsBytes(Uint8List.fromList(bytes), flush: true);
    return file.path;
  }

  GraphDetection _graphFromSvg(Map<String, dynamic> decoded) {
    final width = (decoded['width'] as num?)?.round() ?? 392;
    final height = (decoded['height'] as num?)?.round() ?? 400;
    final baseline = (decoded['baseline_y'] as num?)?.toDouble();
    final rawPoints = decoded['points'] as List<dynamic>?;
    if (baseline == null || rawPoints == null || rawPoints.length < 2) {
      throw const FormatException('SVGグラフの線を読み取れませんでした。');
    }
    final curvePoints = rawPoints
        .map((item) => item as List<dynamic>)
        .map(
          (item) =>
              Offset((item[0] as num).toDouble(), (item[1] as num).toDouble()),
        )
        .toList();
    final rawAutoPoints = decoded['auto_points'] as List<dynamic>?;
    final autoPoints = rawAutoPoints
        ?.map((item) => item as List<dynamic>)
        .map(
          (item) =>
              Offset((item[0] as num).toDouble(), (item[1] as num).toDouble()),
        )
        .toList();
    // SVG上で判定した4点をそのまま使う。画面画像から改めて判定すると、
    // スマホ表示時の縮小や広告の影響で点がずれるため。
    final scorePoints = autoPoints != null && autoPoints.length == 4
        ? autoPoints
        : [
            Offset(width * .85, baseline),
            curvePoints.reduce((a, b) => a.dy <= b.dy ? a : b),
            curvePoints.reduce((a, b) => a.dy >= b.dy ? a : b),
            curvePoints.last,
          ];
    final preview = imglib.Image(width: width, height: height);
    final red = imglib.ColorRgb8(220, 45, 45);
    final white = imglib.ColorRgb8(235, 235, 235);
    imglib.drawLine(
      preview,
      x1: 0,
      y1: baseline.round(),
      x2: width - 1,
      y2: baseline.round(),
      color: red,
    );
    for (var index = 1; index < curvePoints.length; index++) {
      imglib.drawLine(
        preview,
        x1: curvePoints[index - 1].dx.round(),
        y1: curvePoints[index - 1].dy.round(),
        x2: curvePoints[index].dx.round(),
        y2: curvePoints[index].dy.round(),
        color: white,
      );
    }
    return GraphDetection(
      previewPng: encodePreviewPng(preview),
      width: width,
      height: height,
      points: scorePoints,
      curve: curvePoints,
      baselineY: baseline,
    );
  }

  Map<String, dynamic> _decodeJavaScriptResult(Object? value) =>
      decodeJavaScriptResult(value);

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: const Text('database'),
      actions: [
        IconButton(
          tooltip: '前のページへ',
          onPressed: () async {
            if (await _web.canGoBack()) await _web.goBack();
          },
          icon: const Icon(Icons.arrow_back),
        ),
        IconButton(
          tooltip: '再読み込み',
          onPressed: _flow.busy || _openingPage || _preparingBrowser
              ? null
              : _reloadPage,
          icon: const Icon(Icons.refresh),
        ),
      ],
    ),
    body: Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 4),
          child: Wrap(
            spacing: 8,
            children: [
              OutlinedButton(
                onPressed: _flow.busy || _openingPage || _preparingBrowser
                    ? null
                    : () => _openStore(_nagamachiminami),
                child: const Text('長町南店'),
              ),
              OutlinedButton(
                onPressed: _flow.busy || _openingPage || _preparingBrowser
                    ? null
                    : () => _openStore(_saiwaichou),
                child: const Text('幸町店'),
              ),
            ],
          ),
        ),
        const Padding(
          padding: EdgeInsets.symmetric(horizontal: 16),
          child: Text(
            '店・機種・日付を選択して一覧を表示します。横に隠れた列もまとめて読み取ります。',
            style: TextStyle(fontSize: 12),
          ),
        ),
        if (_progress.isNotEmpty)
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 2, 16, 0),
            child: Align(
              alignment: Alignment.centerLeft,
              child: Text(
                _progress,
                style: const TextStyle(fontSize: 12, color: AppColors.ash),
              ),
            ),
          ),
        if (_error != null)
          Padding(
            padding: const EdgeInsets.all(12),
            child: Text(_error!, style: const TextStyle(color: Colors.red)),
          ),
        if (_notice != null)
          Padding(
            padding: const EdgeInsets.all(12),
            child: Text(
              _notice!,
              style: const TextStyle(color: AppColors.linkBlue),
            ),
          ),
        Expanded(
          child: Stack(
            children: [
              WebViewWidget(controller: _web),
              if (_flow.loading)
                const Center(child: CircularProgressIndicator()),
            ],
          ),
        ),
        SafeArea(
          top: false,
          minimum: const EdgeInsets.fromLTRB(16, 10, 16, 12),
          child: ConstrainedBox(
            constraints: BoxConstraints(
              maxHeight: MediaQuery.sizeOf(context).height * 0.42,
            ),
            child: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  SizedBox(
                    width: double.infinity,
                    child: FilledButton.icon(
                      style: FilledButton.styleFrom(
                        backgroundColor: _auto.enabled
                            ? AppColors.appleBlue
                            : AppColors.ash,
                        foregroundColor: Colors.white,
                        minimumSize: const Size.fromHeight(52),
                      ),
                      onPressed: _autoChanging ? null : _toggleAuto,
                      icon: Icon(
                        _auto.enabled
                            ? Icons.autorenew
                            : Icons.pause_circle_outline,
                      ),
                      label: Text('自動取り込み：${_auto.enabled ? 'ON' : 'OFF'}'),
                    ),
                  ),
                  const SizedBox(height: 4),
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
                          onChanged: (value) => setState(
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
                  // 日付指定取り込み：取り込む営業日を決める（日本時間の午前3時までは前日）。
                  // 上から／下から：機種を一覧のどちら側から取り込むか。押すと自動取り込みをONにする。
                  DropdownButtonFormField<String>(
                    key: ValueKey('meruhen-day-$_targetDay'),
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
                      for (final (i, day) in recentImportDays(
                        todayIso(),
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
                              onPressed: _auto.enabled || _autoChanging
                                  ? null
                                  : () => _toggleAuto(direction),
                              child: Text(label),
                            ),
                          ),
                        ),
                    ],
                  ),
                  Align(
                    alignment: Alignment.centerLeft,
                    child: Text(
                      _autoStatus,
                      style: const TextStyle(
                        fontSize: 12,
                        color: AppColors.ash,
                      ),
                    ),
                  ),
                  if (_auto.enabled)
                    const Align(
                      alignment: Alignment.centerLeft,
                      child: Text(
                        autoCaptureScreenNote,
                        style: TextStyle(fontSize: 12, color: AppColors.ash),
                      ),
                    ),
                  const SizedBox(height: 4),
                  SizedBox(
                    width: double.infinity,
                    child: FilledButton.icon(
                      onPressed: _flow.canCapture && !_auto.enabled
                          ? () => unawaited(_captureCurrentPage())
                          : null,
                      icon: _flow.busy
                          ? const SizedBox(
                              width: 18,
                              height: 18,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.download_for_offline_outlined),
                      label: Text(_flow.busy ? '取り込み中…' : 'この画面を取り込む'),
                    ),
                  ),
                  Align(
                    alignment: Alignment.centerRight,
                    child: TextButton.icon(
                      onPressed: _flow.busy || _auto.enabled ? null : _undoLast,
                      icon: const Icon(Icons.undo, size: 18),
                      label: const Text('直前の保存を取り消す'),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ],
    ),
  );
}

class WebTableReviewPage extends StatefulWidget {
  const WebTableReviewPage({
    super.key,
    required this.extraction,
    required this.onSave,
  });

  final WebTableExtraction extraction;
  final Future<void> Function(WebTableExtraction extraction) onSave;

  @override
  State<WebTableReviewPage> createState() => _WebTableReviewPageState();
}

class _WebTableReviewPageState extends State<WebTableReviewPage> {
  late String _store;
  late final TextEditingController _day;
  late final TextEditingController _machine;
  late final List<_WebRowControllers> _rows;
  var _saving = false;

  @override
  void initState() {
    super.initState();
    _store = widget.extraction.store ?? 'nagamachiminami';
    _day = TextEditingController(text: widget.extraction.day ?? '');
    _machine = TextEditingController(text: widget.extraction.machine ?? '');
    _rows = widget.extraction.rows.map(_WebRowControllers.fromRow).toList();
  }

  @override
  void dispose() {
    _day.dispose();
    _machine.dispose();
    for (final row in _rows) {
      row.dispose();
    }
    super.dispose();
  }

  Future<void> _save() async {
    try {
      final day = _day.text.trim();
      final machine = _machine.text.trim();
      if (!isValidRecordDay(day)) {
        throw const FormatException('実在する日付をYYYY-MM-DDで入力してください。');
      }
      if (machine.isEmpty) throw const FormatException('機種名を入力してください。');
      final rows = _rows.map((row) => row.value()).toList();
      if (rows.isEmpty) throw const FormatException('台データがありません。');
      setState(() => _saving = true);
      await widget.onSave(
        WebTableExtraction(
          sourceUrl: widget.extraction.sourceUrl,
          store: _store,
          day: day,
          machine: machine,
          expectedCount: widget.extraction.expectedCount,
          rows: rows,
        ),
      );
      if (mounted) Navigator.of(context).pop(true);
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('入力を確認してください：$error')));
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: const Text('一覧データを確認'),
      actions: [
        TextButton.icon(
          onPressed: _saving ? null : _save,
          icon: const Icon(Icons.check),
          label: const Text('保存'),
        ),
      ],
    ),
    // 保存ボタンは下に固定する。台数分の入力欄の一番下に置いていたため、
    // 直すところが無くても最後までスクロールしないと押せなかった。
    bottomNavigationBar: SafeArea(
      minimum: const EdgeInsets.fromLTRB(16, 8, 16, 12),
      child: SizedBox(
        width: double.infinity,
        child: FilledButton(
          onPressed: _saving ? null : _save,
          child: Text(_saving ? '保存中…' : '保存してブラウザへ戻る'),
        ),
      ),
    ),
    body: ListView(
      padding: EdgeInsets.fromLTRB(
        16,
        12,
        16,
        24 + MediaQuery.of(context).viewPadding.bottom,
      ),
      children: [
        const Text('保存後はブラウザへ戻り、そのままグラフを開けます。'),
        const SizedBox(height: 14),
        DropdownButtonFormField<String>(
          initialValue: _store,
          decoration: const InputDecoration(labelText: '店舗'),
          items: const [
            DropdownMenuItem(value: 'nagamachiminami', child: Text('長町南店')),
            DropdownMenuItem(value: 'saiwaichou', child: Text('幸町店')),
          ],
          onChanged: (value) => setState(() => _store = value!),
        ),
        const SizedBox(height: 10),
        TextField(
          controller: _day,
          keyboardType: TextInputType.datetime,
          decoration: const InputDecoration(labelText: '日付（YYYY-MM-DD）'),
        ),
        const SizedBox(height: 10),
        TextField(
          controller: _machine,
          decoration: const InputDecoration(labelText: '機種名'),
        ),
        const SizedBox(height: 16),
        Text('${_rows.length}台を読み取りました。必要なら数値を修正してください。'),
        const SizedBox(height: 8),
        ..._rows.asMap().entries.map(
          (entry) => _WebRowEditor(index: entry.key + 1, row: entry.value),
        ),
      ],
    ),
  );
}

class _WebRowControllers {
  _WebRowControllers({
    required int rack,
    required int bb,
    required int rb,
    required int games,
    int? maxHold,
    int? previousStart,
    this.detailUrl,
  }) : rack = TextEditingController(text: '$rack'),
       bb = TextEditingController(text: '$bb'),
       rb = TextEditingController(text: '$rb'),
       games = TextEditingController(text: '$games'),
       maxHold = TextEditingController(text: maxHold?.toString() ?? ''),
       previousStart = TextEditingController(
         text: previousStart?.toString() ?? '',
       );

  factory _WebRowControllers.fromRow(EditableRow row) => _WebRowControllers(
    rack: row.rack,
    bb: row.bb,
    rb: row.rb,
    games: row.games,
    maxHold: row.maxHold,
    previousStart: row.previousStart,
    detailUrl: row.detailUrl,
  );

  final String? detailUrl;
  final TextEditingController rack, bb, rb, games, maxHold, previousStart;

  EditableRow value() {
    int requiredValue(TextEditingController controller, String label) {
      final value = int.tryParse(controller.text.trim());
      if (value == null || value < 0) throw FormatException('$labelを確認してください。');
      return value;
    }

    final previous = previousStart.text.trim();
    final maxHoldText = maxHold.text.trim();
    return EditableRow(
      rack: requiredValue(rack, '台番号'),
      bb: requiredValue(bb, 'BB'),
      rb: requiredValue(rb, 'RB'),
      games: requiredValue(games, '総回転数'),
      // Optional: saiwaichou's own list page never shows this column, and
      // it gets filled in later from the individual rack's graph page.
      maxHold: maxHoldText.isEmpty ? null : int.tryParse(maxHoldText),
      previousStart: previous.isEmpty ? null : int.tryParse(previous),
      detailUrl: detailUrl,
    );
  }

  void dispose() {
    rack.dispose();
    bb.dispose();
    rb.dispose();
    games.dispose();
    maxHold.dispose();
    previousStart.dispose();
  }
}

class _WebRowEditor extends StatelessWidget {
  const _WebRowEditor({required this.index, required this.row});
  final int index;
  final _WebRowControllers row;

  @override
  Widget build(BuildContext context) => Card(
    margin: const EdgeInsets.only(bottom: 8),
    child: Padding(
      padding: const EdgeInsets.all(10),
      child: Wrap(
        spacing: 8,
        runSpacing: 8,
        children: [
          Text('台$index', style: const TextStyle(fontWeight: FontWeight.bold)),
          _numberField('台番', row.rack),
          _numberField('BB', row.bb),
          _numberField('RB', row.rb),
          _numberField('総回転', row.games),
          _numberField('最大持玉', row.maxHold),
          _numberField('前日最終', row.previousStart),
        ],
      ),
    ),
  );

  Widget _numberField(String label, TextEditingController controller) =>
      SizedBox(
        width: 104,
        child: TextField(
          controller: controller,
          keyboardType: TextInputType.number,
          decoration: InputDecoration(labelText: label, isDense: true),
        ),
      );
}

const _extractGraphScript = r'''
(() => {
  const kind = new URL(location.href).searchParams.get('kind_code');
  if (kind && kind !== '21') return JSON.stringify({error: '対象は1000円46枚スロットのみです。'});
  const clean = value => String(value || '').replace(/\s+/g, ' ').trim();
  const body = document.body ? document.body.innerText : '';
  const normalizeDate = value => {
    const match = clean(value).match(/^(20\d{2})[\/.年-](\d{1,2})[\/.月-](\d{1,2})$/);
    return match ? `${match[1]}-${String(match[2]).padStart(2, '0')}-${String(match[3]).padStart(2, '0')}` : null;
  };
  const readDay = () => {
    // 個別グラフの target_date が正本。無いときは台リンク、日付選択欄の順。
    // 本文の最初の日付は「更新日時」を拾い、前日のデータを翌日の
    // 日付で保存してしまうので使わない（読めなければ null＝確認画面で入力）。
    const fromUrl = normalizeDate(new URL(location.href).searchParams.get('target_date'));
    if (fromUrl) return fromUrl;
    for (const anchor of document.querySelectorAll('a[href*="target_date="]')) {
      try {
        const day = normalizeDate(new URL(anchor.href, location.href).searchParams.get('target_date'));
        if (day) return day;
      } catch (_) {}
    }
    for (const option of document.querySelectorAll('select option:checked')) {
      const match = clean(option.textContent).match(/(20\d{2})\s*[\/.年-]\s*(\d{1,2})\s*[\/.月-]\s*(\d{1,2})/);
      if (match) return `${match[1]}-${String(match[2]).padStart(2,'0')}-${String(match[3]).padStart(2,'0')}`;
    }
    return null;
  };
  const readMachineFromUrl = () => {
    let value = new URL(location.href).searchParams.get('machine_name') || null;
    for (let i = 0; value && value.includes('%') && i < 3; i++) {
      try { value = decodeURIComponent(value); } catch (_) { break; }
    }
    return clean(value).replace(/\+/g, ' ') || null;
  };
  const looksLikeMachine = value => {
    const text = clean(value);
    if (text.length < 3 || text.length > 80) return false;
    if (/番台|総回転|最大持|BIG|REG|グラフ|データ|メニュー|営業時間/.test(text)) return false;
    return /^(?:L|S)[\/\s]?/i.test(text) || text.includes('スマスロ');
  };
  const readMachine = () => {
    const fromUrl = readMachineFromUrl();
    if (fromUrl) return fromUrl;
    const selectors = [
      '.machine_name', '#machine_name', '[class*="machine"]', '[id*="machine"]',
      '.title', 'h1', 'h2'
    ];
    const candidates = selectors.flatMap(selector =>
      Array.from(document.querySelectorAll(selector)).map(element => clean(element.textContent)));
    candidates.push(...body.split(/\n+/).map(clean));
    return candidates.find(looksLikeMachine) || null;
  };
  const numberAfter = labels => {
    for (const label of labels) {
      const match = body.match(new RegExp(label + '\\s*[:：]?\\s*([0-9０-９,，]+)', 'i'));
      if (match) return Number(match[1].replace(/[０-９]/g, c => String.fromCharCode(c.charCodeAt(0) - 0xFEE0)).replace(/[，,]/g, ''));
    }
    return null;
  };
  const svg = document.querySelector('svg.today') || document.querySelector('svg:has(.path-slump)');
  if (svg) {
    const curve = svg.querySelector('.path-slump path');
    const baselineLine = svg.querySelector('.back-line-middle line');
    const zeroText = baselineLine?.getAttribute('y1');
    if (!curve || !zeroText?.trim() || !Number.isFinite(Number(zeroText))) {
      return JSON.stringify({error: 'ゼロ線またはグラフ線を検出できません。表示が終わってから再試行してください。'});
    }
    const numbers = (curve?.getAttribute('d') || '').match(/-?\d+(?:\.\d+)?/g) || [];
    const points = [];
    for (let index = 0; index + 1 < numbers.length; index += 2) {
      points.push([Number(numbers[index]), Number(numbers[index + 1])]);
    }
    const viewBox = svg.viewBox?.baseVal;
    const width = Math.round(viewBox?.width || svg.getBoundingClientRect().width);
    const height = Math.round(viewBox?.height || svg.getBoundingClientRect().height);
    const baseline = Number(zeroText);
    const peak = points.reduce((best, point) => point[1] < best[1] ? point : best, points[0]);
    const trough = points.reduce((best, point) => point[1] > best[1] ? point : best, points[0]);
    const end = points[points.length - 1];
    const day = readDay();
    const rackMatch = body.match(/(\d{1,4})\s*番台/);
    // 台番号は URL の rack_no が正本。本文の最初の「N番台」は前後の台へのリンク
    // （ページャー）を拾って1つずれることがある。
    const urlRackParam = Number(new URL(location.href).searchParams.get('rack_no'));
    const urlRack = Number.isInteger(urlRackParam) && urlRackParam > 0 ? urlRackParam : null;
    const svgText = selector => clean(svg.querySelector(selector)?.textContent);
    const svgNumber = selector => {
      const text = svgText(selector).replace(/,/g, '');
      return /^\d+$/.test(text) ? Number(text) : null;
    };
    // グラフ内に数字の欄があるときはその欄だけを読む。欄が空のとき本文から探すと、
    // 7セグ表示の背景の「88888888」を拾うことがある（PC版は欄だけを読む）。
    const svgOrBody = (selector, labels) =>
      svg.querySelector(selector) ? svgNumber(selector) : numberAfter(labels);
    const store = location.pathname.startsWith('/saiwaichou/') ? 'saiwaichou' :
      location.pathname.startsWith('/nagamachiminami/') ? 'nagamachiminami' : null;
    return JSON.stringify({
      format: 'svg', body: clean(body), store, day, machine: readMachine(),
      rack: urlRack ?? (rackMatch ? Number(rackMatch[1]) : null),
      games: svgOrBody('.info_soukaiten', ['総回転数?', '総回転']),
      bb: svgOrBody('.info_big', ['BIG', 'BB']),
      rb: svgOrBody('.info_reg', ['REG', 'RB']),
      max_hold: svgOrBody('.info_max_mochidama', ['最大持玉', '最大持ち玉']),
      width, height, baseline_y: Number.isFinite(baseline) ? baseline : null, points,
      auto_points: Number.isFinite(baseline) && points.length >= 2
        ? [[width * .85, baseline], peak, trough, end]
        : null,
    });
  }
  const graphScore = element => {
    const rect = element.getBoundingClientRect();
    if (rect.width < 120 || rect.height < 80) return -1;
    const hint = `${element.id || ''} ${element.className || ''} ${element.src || ''}`.toLowerCase();
    let score = Math.min(rect.width * rect.height, 1000000);
    if (/graph|chart|trend|dai/.test(hint)) score += 2000000;
    if (element.tagName === 'CANVAS') score += 1000000;
    return score;
  };
  const candidates = Array.from(document.querySelectorAll('canvas,img')).map(element => ({element, score: graphScore(element)}))
    .filter(item => item.score >= 0).sort((a, b) => b.score - a.score);
  const selected = candidates.length ? candidates[0].element : null;
  let image = null;
  if (selected && selected.tagName === 'CANVAS') {
    image = selected.toDataURL('image/png');
  } else if (selected && selected.tagName === 'IMG') {
    const canvas = document.createElement('canvas');
    canvas.width = selected.naturalWidth || selected.width;
    canvas.height = selected.naturalHeight || selected.height;
    const context = canvas.getContext('2d');
    try {
      context.drawImage(selected, 0, 0, canvas.width, canvas.height);
      image = canvas.toDataURL('image/png');
    } catch (_) {
      image = null;
    }
  }
  const day = readDay();
  const rackMatch = body.match(/(\d{1,4})\s*番台/);
    // 台番号は URL の rack_no が正本。本文の最初の「N番台」は前後の台へのリンク
    // （ページャー）を拾って1つずれることがある。
    const urlRackParam = Number(new URL(location.href).searchParams.get('rack_no'));
    const urlRack = Number.isInteger(urlRackParam) && urlRackParam > 0 ? urlRackParam : null;
  let machine = new URL(location.href).searchParams.get('machine_name') || null;
  for (let i = 0; machine && machine.includes('%') && i < 3; i++) {
    try { machine = decodeURIComponent(machine); } catch (_) { break; }
  }
  machine = clean(machine).replace(/\+/g, ' ') || null;
  const store = location.pathname.startsWith('/saiwaichou/') ? 'saiwaichou' :
    location.pathname.startsWith('/nagamachiminami/') ? 'nagamachiminami' : null;
  return JSON.stringify({
    image,
    body: clean(body),
    store,
    day,
    machine,
    rack: urlRack ?? (rackMatch ? Number(rackMatch[1]) : null),
    games: numberAfter(['総回転数?', '総回転']),
    bb: numberAfter(['BIG', 'BB']),
    rb: numberAfter(['REG', 'RB']),
    max_hold: numberAfter(['最大持玉', '最大持ち玉']),
  });
})()
''';

const _extractTableScript = r'''
(async () => {
  const kind = new URL(location.href).searchParams.get('kind_code');
  if (kind && kind !== '21') return JSON.stringify({error: '対象は1000円46枚スロットのみです。'});
  const compact = (value) => (value || '').replace(/\s+/g, '').trim();
  const number = (value) => {
    const normalized = String(value || '')
      .replace(/[０-９]/g, c => String.fromCharCode(c.charCodeAt(0) - 0xFEE0))
      .replace(/[，,]/g, '');
    const match = normalized.match(/\d+/);
    return match ? Number(match[0]) : null;
  };
  const labels = {
    rack: value => /台番号|台番/.test(value),
    bb: value => value === 'BB' || value === 'BIG',
    rb: value => value === 'RB' || value === 'REG',
    games: value => /総回転|回転数/.test(value),
    previous: value => /前日最終/.test(value),
    max_hold: value => /最大持玉|最大持ち玉/.test(value),
  };
  const tables = Array.from(document.querySelectorAll('table'));
  const candidates = [];
  for (const table of tables) {
    const trs = Array.from(table.querySelectorAll('tr'));
    const lines = trs.map(row =>
      Array.from(row.querySelectorAll('th,td')).map(cell => compact(cell.innerText)));
    // 各台の行にあるサイト自身の個別台リンク（rack_no付き）。Dart側でも検証する。
    const rowLinks = trs.map(row => {
      const anchor = Array.from(row.querySelectorAll('a[href]')).find(a => /[?&]rack_no=\d+/.test(a.href));
      return anchor ? anchor.href : null;
    });
    for (let headerRow = 0; headerRow < lines.length; headerRow++) {
      const headers = lines[headerRow];
      const index = {};
      for (const [key, test] of Object.entries(labels)) {
        const found = headers.findIndex(test);
        if (found >= 0) index[key] = found;
      }
      // max_hold is intentionally not required here: saiwaichou's own list
      // page never shows that column at all, and the row is still worth
      // saving without it -- it gets filled in later from the individual
      // rack's graph page instead.
      if (index.rack === undefined || index.bb === undefined || index.rb === undefined ||
          index.games === undefined) continue;
      const rows = [];
      for (let lineIndex = headerRow + 1; lineIndex < lines.length; lineIndex++) {
        const line = lines[lineIndex];
        const item = {
          detail_url: rowLinks[lineIndex],
          rack: number(line[index.rack]),
          bb: number(line[index.bb]),
          rb: number(line[index.rb]),
          games: number(line[index.games]),
          max_hold: index.max_hold === undefined ? null : number(line[index.max_hold]),
          previous_start: index.previous === undefined ? null : number(line[index.previous]),
        };
        if ([item.rack, item.bb, item.rb, item.games].every(v => v !== null)) {
          const previous = rows.find(row => row.rack === item.rack);
          if (previous && JSON.stringify(previous) !== JSON.stringify(item)) {
            throw new Error(`台番号${item.rack}の行が重複し、数値が一致しません。再読み込みしてください。`);
          }
          if (!previous) rows.push(item);
        }
      }
      if (rows.length) candidates.push(rows);
    }
  }
  const body = document.body ? document.body.innerText : '';
  let targetDay = new URL(location.href).searchParams.get('target_date') || '';
  if (!targetDay) {
    // 機種別一覧のURLに日付が無いときは、表の各台リンク（サイト自身が付けた
    // target_date）を、画面上の文字列より優先する。
    for (const anchor of document.querySelectorAll('a[href*="target_date="]')) {
      try { targetDay = new URL(anchor.href).searchParams.get('target_date') || ''; } catch (_) {}
      if (targetDay) break;
    }
  }
  // 無いときはサイトの日付選択欄で選ばれている日を使う。本文の最初の日付は
  // 「更新日時」を拾い、前日のデータを翌日の日付で保存してしまうので使わない
  // （読めなければ null。店舗・日付・機種名がそろわない表は保存しない）。
  const pickedDay = () => {
    for (const option of document.querySelectorAll('select option:checked')) {
      const match = (option.textContent || '').match(/(20\d{2})\s*[\/.年-]\s*(\d{1,2})\s*[\/.月-]\s*(\d{1,2})/);
      if (match) return match;
    }
    return null;
  };
  const dateMatch = targetDay.match(/^(20\d{2})-(\d{1,2})-(\d{1,2})$/) || pickedDay();
  const day = dateMatch ? `${dateMatch[1]}-${String(dateMatch[2]).padStart(2,'0')}-${String(dateMatch[3]).padStart(2,'0')}` : null;
  const params = new URL(location.href).searchParams;
  let machine = params.get('machine_name') || null;
  for (let i = 0; machine && machine.includes('%') && i < 3; i++) {
    try { machine = decodeURIComponent(machine); } catch (_) { break; }
  }
  const store = location.pathname.startsWith('/saiwaichou/') ? 'saiwaichou' :
    location.pathname.startsWith('/nagamachiminami/') ? 'nagamachiminami' : null;
  machine = String(machine || '').replace(/\+/g, ' ').replace(/\s+/g, ' ').trim() || null;
  const machineKey = value => String(value || '').replace(/\+/g, ' ').replace(/\s+/g, '').trim();
  // 以前は、台数の照合のために裏で機種一覧ページをもう一度取得していた。今のサイトは
  // 一覧の行を後からXHRで読み込むため、取得したHTMLには行が無く照合は常に空振りで、
  // 取り込みのたびに最大5秒待ち、通信も1回増えていた。表示中の表だけを読む。
  const expectedCount = null;
  const rows = (expectedCount === null
    ? candidates.slice().sort((a, b) => b.length - a.length)[0]
    : candidates.find(candidate => candidate.length === expectedCount) ||
      candidates.slice().sort((a, b) => b.length - a.length)[0]) || [];
  // 機種の表の代わりにサイトが出す「台情報なし」（PC版 NO_RACKS_PATTERN と同じ文）。
  const no_racks = /該当する台情報が(?:見つかりませんでした|ありません)/.test(body);
  return JSON.stringify({url: location.href, store, day, machine, expected_count: expectedCount, rows, no_racks});
})()
''';

const _pageIdentityScript = r'''
(() => {
  const url = new URL(location.href);
  let machine = url.searchParams.get('machine_name') || '';
  for (let i = 0; machine.includes('%') && i < 3; i++) {
    try { machine = decodeURIComponent(machine); } catch (_) { break; }
  }
  machine = machine.replace(/\+/g, ' ').replace(/\s+/g, ' ').trim();
  // 機種別一覧のURLには target_date が無いことがあるため、一覧内のリンクや
  // 日付選択欄からも日付を探す。
  let day = url.searchParams.get('target_date');
  if (!day) {
    day = new URLSearchParams(url.hash.replace(/^#/, '')).get('database_day');
  }
  if (!day) {
    for (const a of document.querySelectorAll('a[href*="target_date="]')) {
      try { day = new URL(a.href).searchParams.get('target_date'); } catch (_) {}
      if (day) break;
    }
  }
  if (!day) {
    for (const option of document.querySelectorAll('select option:checked')) {
      const match = (option.textContent || '').match(/(\d{4})\/(\d{2})\/(\d{2})/);
      if (match) { day = `${match[1]}-${match[2]}-${match[3]}`; break; }
    }
  }
  const rack = url.searchParams.get('rack_no');
  const store = location.pathname.startsWith('/saiwaichou/') ? 'saiwaichou' :
    location.pathname.startsWith('/nagamachiminami/') ? 'nagamachiminami' : null;
  if (day && store) {
    try { localStorage.setItem(`database-active-day-${store}`, day); } catch (_) {}
  } else if (store && new URLSearchParams(url.hash.replace(/^#/, '')).get('database_next_machine') === '1') {
    try { day = localStorage.getItem(`database-active-day-${store}`) || ''; } catch (_) {}
  }
  return JSON.stringify({store, day, machine: machine || null, rack: rack ? Number(rack) : null});
})()
''';

/// 埋め込みの YouTube 動画を内部ブラウザに表示しない。
///
/// 動画本体（iframe・embed・object）は取り除く。サイトによっては、最初は
/// サムネイル画像と再生ボタンだけを置き、押したときに動画を差し込む形式
/// （i.ytimg.com の画像、class や data-* 属性に youtube を含む枠など）なので、
/// それも隠す。中身が動画だけになった親の枠も隠して空白を残さないが、
/// 表・日付の選択・ボタン・他の画像を含む枠には手を出さない。
/// 後から差し込まれたり src を書き換えられたりしたものも MutationObserver で隠す。
const _hideYouTubeScript = r'''
(() => {
  const ytUrl = /(^|[\s"'(,=])((https?:)?\/\/)?([a-z0-9-]+\.)*(youtube\.com|youtube-nocookie\.com|youtu\.be|ytimg\.com)(\/|$|["')\s])/i;
  const ytName = /youtube|(^|[-_\s])yt([-_\s]|$)/i;
  const FLAG = 'databaseHidden';
  const mentionsYouTube = el => {
    for (const attr of Array.from(el.attributes || [])) {
      if (attr.name === 'class' || attr.name === 'id') {
        if (ytName.test(attr.value)) return true;
      } else if (ytUrl.test(attr.value) || (attr.name.startsWith('data-') && ytName.test(attr.name))) {
        return true;
      }
    }
    return false;
  };
  // 取り込みに使う表や日付の選択を含む枠は、youtube の印があっても隠さない。
  const dataSelector = 'table, select, input, textarea, svg, canvas';
  const holdsData = el => el.matches(dataSelector) || !!el.querySelector(dataSelector);
  // 動画だけを包んでいる枠（再生ボタンや黒い背景を含む）までさかのぼって隠す。
  // 表・日付の選択、他の画像、ある程度の文字を含む枠の手前で止める（最大4段）。
  const hide = el => {
    if (!el || el.closest('[data-database-hidden]') || holdsData(el)) return;
    let target = el;
    for (let depth = 0; depth < 4; depth++) {
      const parent = target.parentElement;
      if (!parent || parent === document.body || parent === document.documentElement) break;
      if (holdsData(parent)) break;
      if ((parent.textContent || '').trim().length > 4) break;
      const otherImage = Array.from(parent.querySelectorAll('img, video, canvas, svg'))
        .some(item => !target.contains(item) && !item.closest('[data-database-hidden]') && !mentionsYouTube(item));
      if (otherImage) break;
      target = parent;
    }
    target.dataset[FLAG] = '1';
    target.style.setProperty('display', 'none', 'important');
  };
  const sweep = () => {
    document.querySelectorAll('iframe, embed, object').forEach(el => {
      const source = el.getAttribute('src') || el.getAttribute('data-src') || el.getAttribute('data') || '';
      if (!ytUrl.test(source) && !mentionsYouTube(el)) return;
      try { el.src = 'about:blank'; } catch (_) {}
      const parent = el.parentElement;
      el.remove();
      if (parent && parent !== document.body && !parent.dataset[FLAG] &&
          (parent.textContent || '').trim().length <= 4 && !holdsData(parent) &&
          !parent.querySelector('img, video, canvas, svg')) {
        hide(parent);
      }
    });
    // サムネイルと再生ボタンだけを置く形式
    document.querySelectorAll('body *:not([data-database-hidden])').forEach(el => {
      if (/^(SCRIPT|STYLE|LINK|META|HTML|BODY|HEAD)$/.test(el.tagName)) return;
      if (el.closest('[data-database-hidden]')) return;
      if (mentionsYouTube(el) && !holdsData(el)) hide(el);
    });
  };
  sweep();
  if (!window.__databaseHideYouTube) {
    let queued = false;
    window.__databaseHideYouTube = new MutationObserver(() => {
      if (queued) return;
      queued = true;
      setTimeout(() => { queued = false; sweep(); }, 200);
    });
    window.__databaseHideYouTube.observe(document.documentElement, {
      childList: true, subtree: true, attributes: true,
      attributeFilter: ['src', 'data-src', 'srcset', 'style', 'class', 'href'],
    });
  }
})()
''';

/// 機種一覧で、指定した機種名の行（旧形式ならリンク）を押す。見つかれば true。
/// 押すのは応答を返した後にして、移動で応答が失われないようにする。
/// 行の選び方と名前の読み方は [_machineLinksScript] と同じ。
const _clickMachineRowScript = r'''
(wanted) => {
  const key = value => String(value || '').normalize('NFKC').replace(/\+/g, ' ').replace(/\s+/g, '');
  const anchors = Array.from(document.querySelectorAll('a[href*="machine_name"]'));
  let target = null;
  if (anchors.length) {
    target = anchors.find(a => {
      let value = new URL(a.href, location.origin).searchParams.get('machine_name') || '';
      for (let i = 0; value.includes('%') && i < 3; i++) {
        try { value = decodeURIComponent(value); } catch (_) { break; }
      }
      return key(value) === key(wanted);
    }) || null;
  } else {
    const rows = Array.from(document.querySelectorAll('tr.teram2-link-block')).filter(row => !row.querySelector('th'));
    const named = rows.filter(row => row.querySelector('.wrap-machine-name'));
    target = (named.length ? named : rows).find(row =>
      key(row.querySelector('.wrap-machine-name')?.textContent || row.textContent) === key(wanted)) || null;
  }
  if (!target) return false;
  setTimeout(() => target.click(), 0);
  return true;
}
''';

const _machineLinksScript = r'''
(() => {
  const url = new URL(location.href);
  let day = url.searchParams.get('target_date');
  if (!day) {
    day = new URLSearchParams(url.hash.replace(/^#/, '')).get('database_day');
  }
  if (!day) {
    for (const a of document.querySelectorAll('a[href*="target_date="]')) {
      try { day = new URL(a.href).searchParams.get('target_date'); } catch (_) {}
      if (day) break;
    }
  }
  if (!day) {
    for (const option of document.querySelectorAll('select option:checked')) {
      const match = (option.textContent || '').match(/(\d{4})\/(\d{2})\/(\d{2})/);
      if (match) { day = `${match[1]}-${match[2]}-${match[3]}`; break; }
    }
  }
  const store = location.pathname.startsWith('/saiwaichou/') ? 'saiwaichou' :
    location.pathname.startsWith('/nagamachiminami/') ? 'nagamachiminami' : null;
  if (day && store) {
    try { localStorage.setItem(`database-active-day-${store}`, day); } catch (_) {}
  } else if (store && new URLSearchParams(url.hash.replace(/^#/, '')).get('database_next_machine') === '1') {
    try { day = localStorage.getItem(`database-active-day-${store}`) || ''; } catch (_) {}
  }
  // 見出し行（「機種名 台数 …」）も同じクラスの行で描画されるため除く。
  const machineRows = () => {
    const rows = Array.from(document.querySelectorAll('tr.teram2-link-block')).filter(row => !row.querySelector('th'));
    const named = rows.filter(row => row.querySelector('.wrap-machine-name'));
    return named.length ? named : rows;
  };
  const anchors = Array.from(document.querySelectorAll('a[href*="machine_name"]'));
  const machines = anchors.length ? anchors.map(a => {
      let value = new URL(a.href, location.origin).searchParams.get('machine_name') || '';
      for (let i = 0; value.includes('%') && i < 3; i++) {
        try { value = decodeURIComponent(value); } catch (_) { break; }
      }
      const count = (a.closest('tr')?.innerText || '').match(/(\d+)\s*台/);
      return {name: value, url: a.href, count: count ? Number(count[1]) : null};
    }) : machineRows().map(row => {
      // 現行サイトは行クリックで遷移するため、画面に出た機種名から
      // サイト自身と同じ機種別一覧URLを組み立てる。
      const name = (row.querySelector('.wrap-machine-name')?.textContent || row.textContent || '')
        .replace(/\s+/g, ' ').trim();
      const count = (row.innerText || '').match(/(\d+)\s*台/);
      const kind = url.searchParams.get('kind_code') || '21';
      // サイト自身の機種名は全角スペースを含む（「L無職転生　NM」）。URLにはその綴りを使う
      // （半角に直すと空のページになる）。ここで畳むのは改行・半角スペースだけ。
      const urlName = (row.querySelector('.wrap-machine-name')?.textContent || row.textContent || '')
        .replace(/[ \t\r\n\f\v]+/g, ' ').trim();
      const encoded = encodeURIComponent(encodeURIComponent(urlName));
      return {name,
        url: `${location.origin}/${store}/standlist_slot/?kind_code=${encodeURIComponent(kind)}&machine_name=${encoded}`,
        count: count ? Number(count[1]) : null};
    }).filter(item => item.name);
  const busy = (window.jQuery && window.jQuery.active > 0) ||
    Array.from(document.querySelectorAll('[aria-busy="true"], .loading, .spinner')).some(e => e.getClientRects().length);
  return JSON.stringify({store, day, kind_code: url.searchParams.get('kind_code'), machines,
    ready: document.readyState === 'complete' && !busy});
})()
''';

const _pageReadinessScript = r'''
(() => {
  const busy = (window.jQuery && window.jQuery.active > 0) ||
    Array.from(document.querySelectorAll('[aria-busy="true"], .loading, .spinner')).some(e => e.getClientRects().length);
  const rows = Array.from(document.querySelectorAll('tr')).map(e => e.textContent);
  const curves = Array.from(document.querySelectorAll('svg path, svg polyline'))
    .map(e => e.getAttribute('d') || e.getAttribute('points'));
  const content = [location.href, rows, curves];
  return JSON.stringify({ready: document.readyState === 'complete' && !busy,
    hasContent: !!document.body && (rows.length > 0 || curves.length > 0 || document.body.innerText.trim().length > 0), content});
})()
''';

/// 読み込み・人間確認中はONのまま待ち、サイトの操作は行わない。
/// URLと表示内容を組にして、同じ画面を繰り返し保存しない。
const _autoProbeScript = r'''
(() => {
  const url = location.href;
  const visible = e => !!e && e.getClientRects().length > 0;
  const body = document.body;
  if (!body || document.readyState !== 'complete')
    return JSON.stringify({ready:false, reason:'読み込み中', url});
  const busy = (window.jQuery && window.jQuery.active > 0) ||
    Array.from(document.querySelectorAll('[aria-busy="true"], .loading, .spinner')).some(visible);
  if (busy) return JSON.stringify({ready:false, reason:'読み込み中', url});
  const dialogs = Array.from(document.querySelectorAll('dialog[open], [role="dialog"], [aria-modal="true"]')).filter(visible);
  const challenges = Array.from(document.querySelectorAll('iframe[src*="captcha"], iframe[src*="recaptcha"], iframe[src*="hcaptcha"]')).filter(visible);
  const words = (body.innerText || '').replace(/\s+/g, ' ').trim();
  if (dialogs.length || challenges.length ||
      /人間であること|ロボットでは|セキュリティチェック|verify you are human|checking your browser|captcha|利用規約.*同意|利用条件.*同意/i.test(words))
    return JSON.stringify({ready:false, reason:'確認画面を手動で操作してください', url});
  const target = /[?&]rack_no=/.test(url) ? 'graph' :
    /[?&]machine_name=/.test(url) ? 'table' :
    /rack_info_kt/.test(url) ? 'machines' : null;
  if (!target) return JSON.stringify({ready:false, reason:'対象画面待ち', url});
  const rows = Array.from(document.querySelectorAll('tr')).map(e => e.innerText || e.textContent || '');
  const curves = Array.from(document.querySelectorAll('svg path, svg polyline'))
    .map(e => e.getAttribute('d') || e.getAttribute('points') || '');
  const images = Array.from(document.querySelectorAll('canvas, img')).filter(visible)
    .map(e => e.tagName === 'CANVAS' ? `${e.width}x${e.height}` : e.currentSrc || e.src || '');
  if (target === 'machines' && !document.querySelector('tr.teram2-link-block, a[href*="machine_name"]'))
    return JSON.stringify({ready:false, reason:'機種一覧の表示待ち', url});
  // 「該当する台情報が見つかりませんでした」のページは表が無くても準備済み（取り込みで飛ばす）。
  if (target === 'table' && rows.length === 0 &&
      !/該当する台情報が(?:見つかりませんでした|ありません)/.test(words))
    return JSON.stringify({ready:false, reason:'表の表示待ち', url});
  if (target === 'graph' && curves.length === 0 && images.length === 0)
    return JSON.stringify({ready:false, reason:'グラフの表示待ち', url});
  // 曲線が描けていても、グラフ内の数字（class が info_ で始まるもの）が4つとも空のあいだは待つ
  // （2026-10-16、PCの幸町で多発）。入らないままの台で止まり続けないよう、同じページで20秒
  // たっても空なら進む。PC版（auto_capture.py の graphNumbersPending）と同じ規則。
  if (target === 'graph') {
    const svg = document.querySelector('svg.today');
    const numbers = svg ? Array.from(svg.querySelectorAll('[class*="info_"]')) : [];
    if (!numbers.length || numbers.some(e => (e.textContent || '').trim() !== '')) {
      window.__databaseGraphNumbersEmpty = null;
    } else {
      const since = window.__databaseGraphNumbersEmpty;
      if (!since || since.url !== url) window.__databaseGraphNumbersEmpty = {url, since: Date.now()};
      if (Date.now() - window.__databaseGraphNumbersEmpty.since < 20000)
        return JSON.stringify({ready:false, reason:'台の数値（総回転数・最大持玉など）の表示待ち', url});
    }
  }
  const signature = JSON.stringify([url, rows, curves, images, words]);
  return JSON.stringify({ready:true, url, signature});
})()
''';

const _markMachinesScript = r'''
(status, day) => {
  const md = day ? `${+day.slice(5, 7)}/${+day.slice(8, 10)} ` : '';
  const anchors = Array.from(document.querySelectorAll('a[href*="machine_name"]'));
  const rows = Array.from(document.querySelectorAll('tr.teram2-link-block')).filter(row => !row.querySelector('th'));
  const named = rows.filter(row => row.querySelector('.wrap-machine-name'));
  const links = anchors.length ? anchors : (named.length ? named : rows)
    .map(row => row.querySelector('.wrap-machine-name') || row);
  links.forEach((a, i) => {
    const old = a.parentElement && a.parentElement.querySelector(`.database-badge[data-for="${i}"]`);
    if (old) old.remove();
    const s = status[i];
    const badge = document.createElement('span');
    badge.className = 'database-badge';
    badge.dataset.for = String(i);
    let text, bg, fg;
    if (s && s.excluded) { text = '対象外'; bg = 'transparent'; fg = '#8a94a6'; }
    else if (!s) { text = `${md}未取込`; bg = '#e2e2e5'; fg = '#707070'; }
    else if (s.done >= s.total) { text = `${md}済 ${s.done}/${s.total}`; bg = '#0d8b74'; fg = '#fff'; }
    else { text = `${md}${s.done}/${s.total}`; bg = '#f5a623'; fg = '#1d1d1f'; }
    badge.textContent = text;
    badge.style.cssText = `display:inline-block;margin-left:8px;padding:1px 9px;border-radius:980px;font:600 12px system-ui;background:${bg};color:${fg}`;
    a.insertAdjacentElement('afterend', badge);
  });
}
''';

const _extractionBridgeScript = r'''
(script, id) => {
  Promise.resolve().then(() => (0, eval)(script)).then(
    value => DatabaseExtraction.postMessage(JSON.stringify({id, value})),
    error => DatabaseExtraction.postMessage(JSON.stringify({id, error: String(error)}))
  );
}
''';
