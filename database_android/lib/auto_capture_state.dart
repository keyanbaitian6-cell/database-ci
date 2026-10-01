/// Session-only admission for the optional browser auto-capture loop.
/// No persisted ON state and no interaction with the site's controls.
class AutoCaptureState {
  /// 間隔の範囲（0.1秒単位）。メルヘンは1〜45（0.1〜4.5秒、初期3.5秒）。P’s CUBEは
  /// 50〜600（5〜60秒、初期10秒）で使う（サイトに止められないよう長めに。2026-10-01）。
  AutoCaptureState({
    Duration Function()? elapsed,
    this.minTenths = 1,
    this.maxTenths = 45,
    this.intervalTenths = 35,
  }) : _elapsed = elapsed ?? _monotonic;

  static final Stopwatch _watch = Stopwatch()..start();
  static Duration _monotonic() => _watch.elapsed;

  final Duration Function() _elapsed;
  final int minTenths;
  final int maxTenths;
  bool enabled = false;
  int intervalTenths;
  int revision = 0;
  int page = 0;
  Duration _deadline = Duration.zero;
  final Set<String> _seen = {};

  Duration get interval => Duration(milliseconds: intervalTenths * 100);

  void setIntervalTenths(int value) {
    if (value < minTenths || value > maxTenths) {
      throw RangeError.range(value, minTenths, maxTenths);
    }
    intervalTenths = value;
    _deadline = _elapsed() + interval;
  }

  void turnOn() {
    revision++;
    enabled = true;
    _seen.clear();
    _deadline = _elapsed() + interval;
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
    _deadline = _elapsed() + interval;
  }

  int? due({required bool busy}) {
    if (!enabled) return null;
    if (busy) {
      _deadline = _elapsed() + interval;
      return null;
    }
    if (_elapsed() < _deadline) return null;
    _deadline = _elapsed() + interval;
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
