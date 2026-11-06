"""側面ボタンの解放・履歴の端・32/64bit入力構造。実サイトは使わない。"""
import struct
import ctypes
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import site777_history as history


class HistoryTest(unittest.TestCase):
    def test_only_single_side_button_release_navigates(self):
        # Windows RAWMOUSEの公式値を入力側に固定する。実装の定数を使って入力を作らない。
        # https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-rawmouse
        for flags in (0, 1, 2, 4, 8, 16, 32, 0x40, 0x100, 0x400, 0x800, 0x280):
            self.assertEqual(history.button_direction(flags), 0)
        self.assertEqual(history.button_direction(0x80), -1)
        self.assertEqual(history.button_direction(0x200), 1)

    def test_only_mouse_packets_are_decoded(self):
        for header in (16, 24):
            data = bytearray(header + 24)
            struct.pack_into('<H', data, header + 4, 0x80)
            self.assertEqual(history.raw_mouse_flags(data, header), 0x80)
            self.assertEqual(history.raw_mouse_flags(data[:header], header), 0)
            struct.pack_into('<I', data, 0, 1)
            self.assertEqual(history.raw_mouse_flags(data, header), 0)

    def test_history_end_does_not_reload_or_navigate(self):
        calls = []
        core = SimpleNamespace(CanGoBack=False, CanGoForward=False,
                               GoBack=lambda: calls.append('back'), GoForward=lambda: calls.append('forward'))
        control = SimpleNamespace(CoreWebView2=core)
        log = SimpleNamespace(write=lambda *a, **k: None)
        self.assertFalse(history.navigate(control, -1, log))
        self.assertFalse(history.navigate(control, 1, log))
        core.CanGoBack = core.CanGoForward = True
        self.assertTrue(history.navigate(control, -1, log))
        self.assertTrue(history.navigate(control, 1, log))
        self.assertEqual(calls, ['back', 'forward'])

    def test_child_window_delivery_is_registered_but_background_input_is_not_read(self):
        """WebView2の子プロセスへの焦点と、他アプリ中の入力保護を独立に確認する。"""
        class Api:
            def __init__(self, fn):
                self.fn = fn

            def __call__(self, *args):
                return self.fn(*args)

        class Event:
            def __init__(self):
                self.items = []

            def __iadd__(self, fn):
                self.items.append(fn)
                return self

        header = 8 + ctypes.sizeof(ctypes.c_void_p) * 2
        packet = bytearray(header + 24)
        struct.pack_into('<H', packet, header + 4, 0x0080)  # 公式の4番ボタン解放
        foreground, reads, registrations, moves, removals = [99], [], [], [], []

        def read(handle, command, output, size, actual_header):
            reads.append(True)
            ctypes.cast(size, ctypes.POINTER(ctypes.c_uint))[0] = len(packet)
            if output is None:
                return 0
            ctypes.memmove(output, bytes(packet), len(packet))
            return len(packet)

        def register(device, count, size):
            registrations.append(struct.unpack_from('<I', ctypes.string_at(device, size), 4)[0])
            return True

        user32 = SimpleNamespace(RegisterRawInputDevices=Api(register), GetRawInputData=Api(read),
                                 GetForegroundWindow=Api(lambda: foreground[0]))
        comctl32 = SimpleNamespace(SetWindowSubclass=Api(lambda *args: True),
                                  RemoveWindowSubclass=Api(lambda *args: removals.append(True) or True),
                                  DefSubclassProc=Api(lambda *args: 0))
        core = SimpleNamespace(CanGoBack=True, CanGoForward=False, GoBack=lambda: moves.append('back'))
        form = SimpleNamespace(Handle=SimpleNamespace(ToInt64=lambda: 42), FormClosed=Event(),
                               webview=SimpleNamespace(CoreWebView2=core))
        with patch.object(ctypes, 'WinDLL', lambda name, **kw: user32 if name == 'user32' else comctl32, create=True), \
                patch.object(ctypes, 'WINFUNCTYPE', ctypes.CFUNCTYPE, create=True):
            receiver, closed = history.install(SimpleNamespace(native=form), SimpleNamespace(write=lambda *a, **k: None))
            self.assertEqual(registrations, [0x0100])  # INPUTSINK、NOLEGACYなし
            receiver.receive(1)
            self.assertEqual(reads, [])  # 他アプリが手前ならパケットを読み出す前に止める
            foreground[0] = 42
            receiver.receive(1)
            self.assertEqual(moves, ['back'])
            closed(None, None)
            closed(None, None)
            self.assertEqual(registrations, [0x0100, 1])
            self.assertEqual(removals, [True])
