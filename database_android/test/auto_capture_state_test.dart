import 'package:database_android/auto_capture_state.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('starts OFF at 3.5 seconds and accepts all 45 slider values', () {
    var now = Duration.zero;
    final state = AutoCaptureState(elapsed: () => now);
    expect(state.enabled, false);
    expect(state.intervalTenths, 35);
    for (var tenth = 1; tenth <= 45; tenth++) {
      state.setIntervalTenths(tenth);
      state.turnOn();
      now += Duration(milliseconds: tenth * 100 - 1);
      expect(state.due(busy: false), null);
      now += const Duration(milliseconds: 1);
      expect(state.due(busy: false), isNotNull);
      state.turnOff();
    }
  });

  test(
    'OFF invalidates a delayed read and a new page invalidates its token',
    () {
      var now = Duration.zero;
      final state = AutoCaptureState(elapsed: () => now);
      state.setIntervalTenths(1);
      state.turnOn();
      now += const Duration(milliseconds: 100);
      final old = state.due(busy: false)!;
      state.turnOff();
      expect(state.admit(old, 0, 'old page'), false);
      state.turnOn();
      now += const Duration(milliseconds: 100);
      final beforeNavigation = state.due(busy: false)!;
      state.nextPage(1);
      expect(state.admit(beforeNavigation, 0, 'old page'), false);
      expect(state.enabled, true);
    },
  );

  test(
    'busy waits, a stable page is attempted once, changed content resumes',
    () {
      var now = Duration.zero;
      final state = AutoCaptureState(elapsed: () => now)..setIntervalTenths(1);
      state.turnOn();
      now += const Duration(milliseconds: 100);
      expect(state.due(busy: true), null);
      expect(state.due(busy: false), null);
      now += const Duration(milliseconds: 100);
      final token = state.due(busy: false)!;
      expect(state.admit(token, 0, 'same'), true);
      expect(state.admit(token, 0, 'same'), false);
      expect(state.admit(token, 0, 'changed'), true);
      state.nextPage(1);
      now += const Duration(milliseconds: 100);
      expect(state.admit(state.due(busy: false)!, 1, 'same'), true);
    },
  );

  test('new browser controller never restores ON', () {
    final old = AutoCaptureState()..turnOn();
    expect(old.enabled, true);
    expect(AutoCaptureState().enabled, false);
  });
}
