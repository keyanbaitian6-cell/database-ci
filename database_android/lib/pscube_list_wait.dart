/// Scroll each list to its bottom, allowing delayed cards to reach the known
/// installation count. A stable partial list is not a complete list.
Future<void> waitForPscubeList({
  required Future<int> Function() scrollAndCount,
  required bool Function() isCurrent,
  int? expectedCount,
  Future<void> Function(Duration)? delay,
}) async {
  final wait = delay ?? (duration) => Future<void>.delayed(duration);
  var prior = -1;
  var stable = 0;
  for (var i = 0; i < 70; i++) {
    if (!isCurrent()) return;
    final count = await scrollAndCount();
    if (!isCurrent() || count < 0) return;
    stable = count == prior ? stable + 1 : 0;
    prior = count;
    await wait(const Duration(milliseconds: 350));
    if (stable >= 6 && (expectedCount == null || count >= expectedCount)) {
      return;
    }
  }
}
