/// Session-only admission for the optional browser auto-capture loop.
/// No persisted ON state and no interaction with the site's controls.
class AutoCaptureState {
  AutoCaptureState({Duration Function()? elapsed})
    : _elapsed = elapsed ?? _monotonic;

  static final Stopwatch _watch = Stopwatch()..start();
  static Duration _monotonic() => _watch.elapsed;

  final Duration Function() _elapsed;
  bool enabled = false;
  int intervalTenths = 35;
  int revision = 0;
  int page = 0;
  Duration _deadline = Duration.zero;
  final Set<String> _seen = {};

  Duration get interval => Duration(milliseconds: intervalTenths * 100);

  void setIntervalTenths(int value) {
    if (value < 1 || value > 45) throw RangeError.range(value, 1, 45);
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
