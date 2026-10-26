import 'package:flutter/material.dart';

import 'models.dart';

/// 閲覧ページ（メルヘン）：グラフの線は起動時に読まず、台の画面・機種の画面を開いたときに
/// その日の分だけGoogleから読む（2026-10-25、iPhoneのSafariがメモリ不足で落ちていたため）。
///
/// [remoteCurveFetcher] は閲覧ページだけが設定する。日付を渡すと、その日の線パーツの
/// [通し番号, 線] を返す。Androidアプリでは null のまま（線は端末のDBにある）。
typedef RemoteCurveFetcher = Future<Map<int, List<List<double>>>> Function(
  String day,
);

RemoteCurveFetcher? remoteCurveFetcher;

final _days =
    <(RemoteCurveFetcher, String), Future<Map<int, List<List<double>>>>>{};
final _recordFetchers = Expando<RemoteCurveFetcher>();

/// 記録と取得先の版を結び付け、開いたままの古い画面でも別版の線を使わない。
void bindRemoteCurves(List<SlotRecord> records, RemoteCurveFetcher? fetcher) {
  if (fetcher == null) return;
  for (final record in records) {
    if (record.graph?.remoteCurve == true) _recordFetchers[record] = fetcher;
  }
}

RemoteCurveFetcher? _fetcher(SlotRecord record) =>
    _recordFetchers[record] ?? remoteCurveFetcher;

/// 読んだ線を持っておく日数（5日分の帯を1つ開ける分）。
const _keepDays = 6;

/// データを読み直したら、前の線を捨てる（番号は日ごとの線パーツの中だけで通じる）。
void clearRemoteCurves() => _days.clear();

/// 線をまだ読んでいない記録か。
bool needsRemoteCurve(SlotRecord record) {
  final graph = record.graph;
  return _fetcher(record) != null &&
      graph != null &&
      graph.remoteCurve &&
      graph.curve == null &&
      graph.curveIndex != null;
}

/// 線を入れた記録の写し。線が見つからなければ例外。
Future<SlotRecord> loadRemoteCurve(SlotRecord record) async {
  final graph = record.graph!;
  final fetch = _fetcher(record)!;
  final key = (fetch, record.day);
  var day = _days.remove(key);
  day ??= fetch(record.day);
  _days[key] = day;
  while (_days.length > _keepDays) {
    _days.remove(_days.keys.first);
  }
  try {
    final curve = (await day)[graph.curveIndex];
    if (curve == null) throw StateError('この台のグラフの線が見つかりません。');
    return record.copyWith(graph: graph.withCurve(curve));
  } on Object {
    // 失敗した日は覚えず、次に開いたときに読み直す。
    if (identical(_days[key], day)) _days.remove(key);
    rethrow;
  }
}

/// 線が要る部分を包む。読んでいる間は線なしの概略を薄く出し、届いたら線で描き直す。
/// [builder] には線を入れた記録（読めなければ元の記録）、線を待っている／読めなかったか、
/// 読み直す関数を渡す。
class RemoteCurveBuilder extends StatefulWidget {
  const RemoteCurveBuilder({
    super.key,
    required this.record,
    required this.builder,
  });
  final SlotRecord record;
  final Widget Function(
    BuildContext context,
    SlotRecord record,
    RemoteCurveState state,
    VoidCallback retry,
  )
  builder;

  @override
  State<RemoteCurveBuilder> createState() => _RemoteCurveBuilderState();
}

enum RemoteCurveState { ready, loading, failed }

class _RemoteCurveBuilderState extends State<RemoteCurveBuilder> {
  Future<SlotRecord>? _future;

  @override
  void initState() {
    super.initState();
    _start();
  }

  @override
  void didUpdateWidget(RemoteCurveBuilder oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!identical(oldWidget.record, widget.record)) _start();
  }

  void _start() {
    _future = needsRemoteCurve(widget.record)
        ? loadRemoteCurve(widget.record)
        : null;
  }

  @override
  Widget build(BuildContext context) {
    final future = _future;
    void retry() => setState(_start);
    if (future == null) {
      return widget.builder(
        context,
        widget.record,
        RemoteCurveState.ready,
        retry,
      );
    }
    return FutureBuilder<SlotRecord>(
      future: future,
      builder: (context, snapshot) {
        if (snapshot.hasData) {
          return widget.builder(
            context,
            snapshot.data!,
            RemoteCurveState.ready,
            retry,
          );
        }
        return widget.builder(
          context,
          widget.record,
          snapshot.hasError
              ? RemoteCurveState.failed
              : RemoteCurveState.loading,
          retry,
        );
      },
    );
  }
}

/// 線を待っている間の概略は薄く出す。
Widget fadeWhileLoading(RemoteCurveState state, Widget child) =>
    state == RemoteCurveState.loading
    ? Opacity(opacity: 0.4, child: child)
    : child;
