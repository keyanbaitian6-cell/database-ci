/// 自動取り込みがONの間に取り込み画面へ出す注意（メルヘン・P’s CUBE共通）。ONの間はアプリが画面を
/// 消さずに暗くする（MainActivity.keepScreenOnDimmed）。画面が消える・ほかのアプリを前に出すと、
/// アプリ内のブラウザがページの読み込みを終えず止まる（2026-10-06 実機で確認）。
const autoCaptureScreenNote =
    '自動取り込み中は画面を消さずに暗くしています。このアプリを前に出したままにしてください'
    '（画面を消す・ほかのアプリを前に出すと、読み込みが止まります）。';

/// Session-only admission for the optional browser auto-capture loop.
/// No persisted ON state and no interaction with the site's controls.
class AutoCaptureState {
  /// メルヘンの固定間隔は0.1秒単位。selectIntervalがあれば待機設定ごとに選ぶ。
  AutoCaptureState({
    Duration Function()? elapsed,
    this.minTenths = 1,
    this.maxTenths = 45,
    this.intervalTenths = 35,
    this.selectInterval,
  }) : _elapsed = elapsed ?? _monotonic;

  static final Stopwatch _watch = Stopwatch()..start();
  static Duration _monotonic() => _watch.elapsed;

  final Duration Function() _elapsed;
  final Duration Function()? selectInterval;
  Duration? _selectedInterval;
  final int minTenths;
  final int maxTenths;
  bool enabled = false;
  int intervalTenths;
  int revision = 0;
  int page = 0;
  Duration _deadline = Duration.zero;
  final Set<String> _seen = {};

  Duration get interval =>
      _selectedInterval ?? Duration(milliseconds: intervalTenths * 100);

  void _schedule() {
    _selectedInterval = selectInterval?.call();
    _deadline = _elapsed() + interval;
  }

  void setIntervalTenths(int value) {
    if (value < minTenths || value > maxTenths) {
      throw RangeError.range(value, minTenths, maxTenths);
    }
    intervalTenths = value;
    _schedule();
  }

  void turnOn() {
    revision++;
    enabled = true;
    _seen.clear();
    _schedule();
  }

  void turnOff() {
    revision++;
    enabled = false;
    _seen.clear();
  }

  void nextPage(int value) {
    page = value;
    revision++;
    _seen.clear();
    _schedule();
  }

  int? due({required bool busy}) {
    if (!enabled) return null;
    if (busy) {
      _schedule();
      return null;
    }
    if (_elapsed() < _deadline) return null;
    _schedule();
    return revision;
  }

  bool current(int token, int document) =>
      enabled && revision == token && page == document;

  bool admit(int token, int document, String signature) {
    if (!current(token, document) || _seen.contains(signature)) return false;
    _seen.add(signature);
    return true;
  }
}
